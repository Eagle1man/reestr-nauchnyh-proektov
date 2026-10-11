"""Сервис карточки проекта: номера, дубли, маршрут, переходы, риск.

Здесь собрана логика, которая нужна нескольким роутерам, чтобы правила ТЗ
жили в одном месте: один проект — одна карточка, статус и риск разделены,
маршрут выводится из признаков T-01…T-06, недопустимые переходы блокируются.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..db import execute, query, query_one, scalar, transaction
from ..domain.risk import assess_project_risk, required_response
from ..domain.taxonomy import (
    FULL_ROUTE_TRIGGERS, ROUTE_FULL, ROUTE_SIMPLIFIED, ST_ACTIVE, ST_CHECK,
    ST_COMPLETED, STATUS_TITLES,
)
from ..domain.validation import missing_required_fields, validate_lengths
from ..domain.workflow import (
    TransitionContext, available_actions, check_transition, find_transition,
)
from ..utils import new_id, now_iso, today_iso, today_msk

#: Поля карточки, в которые разрешено писать через API (белый список).
#: Это защита от массового присваивания: нельзя протащить created_by или
#: status в обход матрицы переходов (SEC-04, разомкнутый контроль полей).
EDITABLE_FIELDS: frozenset[str] = frozenset({
    "title", "short_title", "public_annotation", "theme_link",
    "planned_start", "planned_end", "publish_mode",
    "problem", "question", "goal", "tasks", "research_object", "research_subject",
    "methods", "methods_note", "data_basis", "planned_result_type",
    "planned_result_note", "result_criteria", "novelty", "applicability",
    "limitations", "personal_data", "personal_data_note", "human_subjects",
    "human_subjects_note", "legal_basis_status", "legal_basis_link",
    "confidentiality", "ip_note", "resource_request",
    "flag_external_funding", "flag_partner", "flag_personal_data",
    "flag_human_subjects", "flag_ethics_required", "flag_extra_resources",
    "flag_critical_infra", "flag_high_risk", "flag_external_product",
    "flag_confidential", "flag_ip_restricted",
})

#: Поля, изменяемые только уполномоченным лицом (A-10 ручная правка риска).
PROTECTED_FIELDS: frozenset[str] = frozenset({"risk_level", "leader_person_id"})

#: Настройки номера проекта (FR-35 — меняются без правки кода)
CODE_PREFIX = "РНП"
CODE_YEAR = today_msk().year


def code_pattern(year: int | None = None) -> re.Pattern:
    y = year or CODE_YEAR
    return re.compile(rf"^{re.escape(CODE_PREFIX)}-{y}-\d+$", re.IGNORECASE)


# ---------------------------------------------------------------------------
#  Номер проекта (FR-06)
# ---------------------------------------------------------------------------

def next_project_code(year: int | None = None, conn=None) -> str:
    """Следующий номер вида РНП-ГГГГ-НННН (FR-06).

    Номер вычисляется и вставляется В ОДНОЙ транзакции. Иначе при параллельном
    создании карточек несколько потоков читают один и тот же максимум, получают
    одинаковый номер, и вторая вставка падает по UNIQUE. Передайте conn, чтобы
    генерация шла внутри уже открытой транзакции.
    """
    y = year or CODE_YEAR
    prefix = f"{CODE_PREFIX}-{y}-"
    runner = conn.execute if conn is not None else query
    rows = runner("SELECT code FROM projects WHERE code LIKE ?", (f"{prefix}%",))
    max_no = 0
    for row in rows:
        tail = row["code"][len(prefix):]
        if tail.isdigit():
            max_no = max(max_no, int(tail))
    return f"{prefix}{max_no + 1:04d}"


def next_result_code(year: int | None = None) -> str:
    y = year or CODE_YEAR
    prefix = f"РЕЗ-{y}-"
    existing = query("SELECT code FROM results WHERE code LIKE ?", (f"{prefix}%",))
    max_no = 0
    for row in existing:
        tail = row["code"][len(prefix):]
        if tail.isdigit():
            max_no = max(max_no, int(tail))
    return f"{prefix}{max_no + 1:04d}"


# ---------------------------------------------------------------------------
#  Поиск дублей (FR-08)
# ---------------------------------------------------------------------------

@dataclass
class DuplicateCandidate:
    id: str
    code: str
    title: str
    short_title: str
    status: str
    status_title: str
    program_id: str
    leader_person_id: str | None
    similarity: float
    reason: str


def normalize_title(title: str) -> str:
    """Привести название к сравнимому виду: без регистра и пунктуации."""
    text = (title or "").lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_duplicates(title: str, *, exclude_id: str | None = None,
                    program_id: str | None = None) -> list[DuplicateCandidate]:
    """Похожие проекты показываются ДО создания карточки (FR-08).

    Точный дубль — совпадение нормализованного названия. Близкий — совпадение
    ключевых слов названия (не менее трёх) или пересечение программы и
    руководителя.
    """
    target = normalize_title(title)
    if not target:
        return []
    words = {w for w in target.split() if len(w) > 3}
    pattern = code_pattern().pattern

    clauses = ["archived_at IS NULL", "status <> ?"]
    params: list[Any] = [ST_COMPLETED]
    if exclude_id:
        clauses.append("id <> ?")
        params.append(exclude_id)
    if program_id:
        clauses.append("(program_id = ? OR ? IS NULL)")
        params.extend([program_id, program_id])

    rows = query(
        "SELECT id, code, title, short_title, status, program_id, leader_person_id"
        f" FROM projects WHERE {' AND '.join(clauses)} LIMIT 500",
        tuple(params),
    )

    out: list[DuplicateCandidate] = []
    for row in rows:
        other = normalize_title(row["title"])
        if not other:
            continue
        reason = ""
        score = 0.0
        if other == target:
            score = 1.0
            reason = "Точное совпадение названия"
        elif target and other and (target in other or other in target):
            overlap = len(words & set(other.split()))
            union = len(words | set(other.split())) or 1
            score = 0.5 + 0.4 * (overlap / union)
            reason = "Название входит в название другого проекта"
        else:
            overlap = words & set(other.split())
            if len(overlap) >= 3:
                score = 0.3 + 0.3 * (len(overlap) / (len(words) or 1))
                reason = f"Совпадают ключевые слова: {', '.join(sorted(overlap)[:5])}"
        if not reason:
            continue
        out.append(DuplicateCandidate(
            id=row["id"], code=row["code"], title=row["title"],
            short_title=row["short_title"] or "", status=row["status"],
            status_title=STATUS_TITLES.get(row["status"], row["status"]),
            program_id=row["program_id"],
            leader_person_id=row["leader_person_id"],
            similarity=round(score, 3), reason=reason,
        ))
    out.sort(key=lambda c: c.similarity, reverse=True)
    return out[:20]


# ---------------------------------------------------------------------------
#  Маршрут (FR-09)
# ---------------------------------------------------------------------------

def detect_full_route_reasons(project: dict) -> list[str]:
    """Основания полного маршрута по T-01…T-06 (п.5.1)."""
    found: list[str] = []
    for code, spec in FULL_ROUTE_TRIGGERS.items():
        if any(project.get(f) for f in spec["fields"]):
            found.append(code)
    return found


def suggest_route(project: dict) -> tuple[str, list[str]]:
    """Автоматически предложить маршрут и вернуть основание (FR-09)."""
    reasons = detect_full_route_reasons(project)
    if reasons:
        return ROUTE_FULL, reasons
    # A-30/A-31: «Да» по персональным данным или участию людей само по себе
    # включает полный маршрут — это те же основания T-02.
    if project.get("personal_data") and "T-02" not in reasons:
        reasons.append("T-02")
    if project.get("human_subjects") and "T-02" not in reasons:
        reasons.append("T-02")
    return ROUTE_SIMPLIFIED, reasons


def stored_full_reasons(project_id: str) -> list[str]:
    return [r["reason"] for r in query(
        "SELECT reason FROM project_full_route_reasons WHERE project_id = ?"
        " ORDER BY reason", (project_id,)
    )]


def sync_full_reasons(project_id: str, project: dict, user_id: str | None) -> list[str]:
    """Привести таблицу оснований в соответствие с признаками карточки."""
    detected = detect_full_route_reasons(project)
    stored = set(stored_full_reasons(project_id))
    for reason in detected:
        if reason not in stored:
            execute(
                "INSERT OR IGNORE INTO project_full_route_reasons"
                " (project_id, reason, added_at, added_by) VALUES (?, ?, ?, ?)",
                (project_id, reason, now_iso(), user_id),
            )
    return detected


# ---------------------------------------------------------------------------
#  Сборка карточки для интерфейса
# ---------------------------------------------------------------------------

def related_counts(project_id: str) -> dict[str, int]:
    return {
        "team": scalar("SELECT COUNT(*) FROM participations WHERE project_id = ?"
                       " AND archived_at IS NULL", (project_id,), 0),
        "milestones": scalar("SELECT COUNT(*) FROM milestones WHERE project_id = ?"
                             " AND archived_at IS NULL", (project_id,), 0),
        "risks": scalar("SELECT COUNT(*) FROM risks WHERE project_id = ?"
                        " AND archived_at IS NULL", (project_id,), 0),
        "results": scalar("SELECT COUNT(*) FROM result_projects WHERE project_id = ?",
                          (project_id,), 0),
        "reviews": scalar("SELECT COUNT(*) FROM reviews WHERE project_id = ?",
                          (project_id,), 0),
        "decisions": scalar("SELECT COUNT(*) FROM decisions WHERE project_id = ?",
                            (project_id,), 0),
        "partners": scalar("SELECT COUNT(*) FROM project_partners WHERE project_id = ?",
                           (project_id,), 0),
        "materials": scalar(
            "SELECT COUNT(*) FROM evidences WHERE object_type = 'project'"
            " AND object_id = ? AND archived_at IS NULL", (project_id,), 0),
    }


def build_context(project_id: str, project: dict) -> TransitionContext:
    """Данные для проверки условий перехода."""
    team_size = scalar("SELECT COUNT(*) FROM participations WHERE project_id = ?"
                       " AND archived_at IS NULL", (project_id,), 0)
    milestone_count = scalar("SELECT COUNT(*) FROM milestones WHERE project_id = ?"
                             " AND archived_at IS NULL", (project_id,), 0)
    partner_count = scalar("SELECT COUNT(*) FROM project_partners WHERE project_id = ?",
                           (project_id,), 0)
    missing = missing_required_fields(
        project,
        team_size=team_size, milestone_count=milestone_count,
        partner_count=partner_count,
    )
    has_result = scalar("SELECT COUNT(*) FROM result_projects WHERE project_id = ?",
                        (project_id,), 0) > 0
    result_has_confirmation = scalar(
        "SELECT COUNT(*) FROM result_projects rp JOIN results r ON r.id = rp.result_id"
        " WHERE rp.project_id = ? AND r.archived_at IS NULL"
        " AND COALESCE(TRIM(r.confirmation), '') <> ''",
        (project_id,), 0) > 0
    has_final_review = scalar(
        "SELECT COUNT(*) FROM reviews WHERE project_id = ? AND object_type = 'project'"
        " AND stage = 'final' AND finalized_at IS NOT NULL",
        (project_id,), 0) > 0
    positive = scalar(
        "SELECT COUNT(*) FROM reviews WHERE project_id = ? AND object_type = 'project'"
        " AND stage = 'final' AND finalized_at IS NOT NULL"
        " AND recommendation IN ('support', 'support_with_conditions')",
        (project_id,), 0) > 0
    return TransitionContext(
        missing_required=missing,
        full_route_reasons=stored_full_reasons(project_id),
        has_linked_result=has_result,
        result_has_confirmation=result_has_confirmation,
        has_final_review=has_final_review,
        positive_final_review=positive,
        route=project.get("route") or ROUTE_SIMPLIFIED,
    )


def recompute_risk(project_id: str) -> dict:
    """Пересчитать индикатор риска и при необходимости пометить точки просроченными.

    FR-13: просрочка формируется автоматически. Статус при этом не меняется —
    статус и риск остаются разными полями (п.5.4).
    """
    project = dict(query_one("SELECT * FROM projects WHERE id = ?", (project_id,)))
    milestones = [dict(r) for r in query(
        "SELECT id, title, planned_date, status FROM milestones"
        " WHERE project_id = ? AND archived_at IS NULL", (project_id,)
    )]
    risks = [dict(r) for r in query(
        "SELECT id, category, description, probability, impact, level, status"
        " FROM risks WHERE project_id = ? AND archived_at IS NULL", (project_id,)
    )]
    today = today_msk()
    overdue_ids = []
    for ms in milestones:
        if ms["status"] in ("done", "cancelled"):
            continue
        if ms["planned_date"] and ms["planned_date"] < today.isoformat():
            overdue_ids.append(ms["id"])
    with transaction() as conn:
        for ms_id in overdue_ids:
            conn.execute(
                "UPDATE milestones SET status = 'overdue' WHERE id = ? AND status <> 'overdue'",
                (ms_id,),
            )
    assessment = assess_project_risk(
        manual_level=project.get("risk_level") or "green",
        manual_comment=project.get("risk_level_comment"),
        milestones=[{**m, "status": "overdue" if m["id"] in overdue_ids else m["status"]}
                    for m in milestones],
        risks=risks,
        today=today,
    )
    if assessment.level != project.get("risk_level"):
        execute(
            "UPDATE projects SET risk_level = ?, risk_changed_at = ? WHERE id = ?",
            (assessment.level, now_iso(), project_id),
        )
    return {
        "level": assessment.level,
        "title": assessment.title,
        "reasons": assessment.reasons,
        "max_delay_working_days": assessment.max_delay_days,
        "overdue_milestones": assessment.overdue_milestones,
        "required_response": required_response(assessment.level),
    }


# ---------------------------------------------------------------------------
#  Создание и изменение
# ---------------------------------------------------------------------------

def build_search_blob(project: dict) -> str:
    parts = [
        project.get("code", ""), project.get("title", ""),
        project.get("short_title", ""), project.get("public_annotation", ""),
        project.get("problem", ""), project.get("question", ""),
        project.get("goal", ""), project.get("theme_link", ""),
        project.get("novelty", ""), project.get("applicability", ""),
        project.get("data_basis", ""), project.get("limitations", ""),
    ]
    return " ".join(str(p) for p in parts if p).lower()


def filter_editable(payload: dict) -> tuple[dict, list[str]]:
    """Оставить только разрешённые поля; вернуть отклонённые имена."""
    clean: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in payload.items():
        if key in EDITABLE_FIELDS:
            clean[key] = _coerce(key, value)
        else:
            rejected.append(key)
    return clean, rejected


def _coerce(key: str, value: Any) -> Any:
    if key in ("tasks", "methods", "result_criteria", "resource_request"):
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return value
    if key.startswith("flag_") or key in ("personal_data", "human_subjects"):
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, str):
            return 1 if value.strip().lower() in ("1", "true", "да", "yes") else 0
        return 1 if value else 0
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip()
    return value


def create_project(*, payload: dict, user_id: str) -> dict:
    clean, rejected = filter_editable(payload)
    program_id = payload.get("program_id")
    if not program_id:
        raise ValueError("Не указана научная программа (A-05)")
    program = query_one(
        "SELECT id FROM programs WHERE id = ? AND archived_at IS NULL", (program_id,)
    )
    if program is None:
        raise ValueError("Научная программа не найдена или архивирована (A-05)")

    if not clean.get("title"):
        raise ValueError("Не указано полное название проекта (A-02)")

    route_auto, reasons = suggest_route(clean)
    project_id = new_id()
    now = now_iso()

    columns = {
        "id": project_id, "program_id": program_id,
        "route": route_auto, "route_auto": route_auto,
        "status": "ST-01", "status_changed_at": now,
        "risk_level": "green", "risk_changed_at": now,
        "created_at": now, "created_by": user_id, "updated_at": now,
        "updated_by": user_id, "publish_mode": clean.pop("publish_mode", "none"),
    }
    columns.update(clean)
    columns["search_blob"] = build_search_blob(columns)

    names = [n for n in columns if n != "code"]
    # Номер вычисляется внутри транзакции: см. next_project_code.
    with transaction() as conn:
        code = next_project_code(conn=conn)
        all_names = names + ["code"]
        placeholders = ", ".join("?" for _ in all_names)
        conn.execute(
            f"INSERT INTO projects ({', '.join(all_names)}) VALUES ({placeholders})",
            tuple(columns[n] for n in names) + (code,),
        )
        for reason in reasons:
            conn.execute(
                "INSERT OR IGNORE INTO project_full_route_reasons"
                " (project_id, reason, added_at, added_by) VALUES (?, ?, ?, ?)",
                (project_id, reason, now, user_id),
            )
    return {"id": project_id, "code": code, "route": route_auto,
            "route_auto": route_auto, "route_reasons": reasons,
            "rejected_fields": rejected}


def update_project(*, project_id: str, payload: dict, actor,
                   basis: str | None = None) -> dict:
    """Изменить карточку. Возвращает список изменённых полей для журнала."""
    current = dict(query_one("SELECT * FROM projects WHERE id = ?", (project_id,)))
    if not current:
        raise ValueError("Проект не найден")

    if "version" in payload and payload["version"] is not None:
        if int(payload["version"]) != int(current["version"]):
            raise VersionConflict(
                f"Карточка изменена после вашего открытия "
                f"(версия {current['version']}). Обновите страницу и внесите правки "
                f"заново — незаметная перезапись запрещена (FR-32)."
            )

    clean, rejected = filter_editable(payload)
    clean.pop("version", None)

    # Защищённые поля меняются отдельными операциями с основанием (A-10, A-12)
    protected = sorted(set(clean) & PROTECTED_FIELDS)
    for key in protected:
        clean.pop(key)

    changes: dict[str, tuple[Any, Any]] = {}
    for key, value in clean.items():
        if current.get(key) != value:
            changes[key] = (current.get(key), value)

    if not changes:
        return {"changed": [], "rejected_fields": rejected, "version": current["version"]}

    assignments = ", ".join(f"{k} = ?" for k in changes)
    execute(
        f"UPDATE projects SET {assignments}, version = version + 1, updated_at = ?,"
        f" updated_by = ? WHERE id = ?",
        tuple([v for _, v in changes.values()] + [now_iso(), actor.id, project_id]),
    )

    merged = {**current, **{k: v for k, v in changes.items()}}
    execute(
        "UPDATE projects SET search_blob = ? WHERE id = ?",
        (build_search_blob(merged), project_id),
    )

    # FR-09: маршрут пересчитывается, ручное изменение требует комментария
    route_notes: dict[str, Any] = {}
    new_route_auto, detected = suggest_route(merged)
    if detected:
        sync_full_reasons(project_id, merged, actor.id)

    return {
        "changed": [{"field": k, "old": o, "new": n} for k, (o, n) in changes.items()],
        "rejected_fields": rejected,
        "protected_fields_ignored": protected,
        "version": int(current["version"]) + 1,
        "suggested_route": new_route_auto,
        "route_reasons": detected or stored_full_reasons(project_id),
        **route_notes,
    }


class VersionConflict(Exception):
    """Попытка незаметно перезаписать более новую версию карточки (FR-32)."""


def set_route(*, project_id: str, route: str, actor, reason: str | None) -> dict:
    """Зафиксировать маршрут уполномоченным лицом (FR-09, п.5.1)."""
    current = dict(query_one("SELECT route, route_auto FROM projects WHERE id = ?",
                             (project_id,)))
    if route not in (ROUTE_SIMPLIFIED, ROUTE_FULL):
        raise ValueError("Маршрут должен быть simplified или full")
    if route == ROUTE_FULL:
        reasons = stored_full_reasons(project_id)
        if not reasons:
            raise ValueError(
                "Для полного маршрута нужно хотя бы одно основание T-01…T-06 (A-08)"
            )
    if route != current["route_auto"] and not (reason or "").strip():
        raise ValueError(
            "Ручное изменение маршрута относительно автоматического предложения"
            " требует комментария, и причина попадает в журнал (FR-09)"
        )
    execute(
        "UPDATE projects SET route = ?, route_reason_comment = ?, route_fixed_by = ?,"
        " updated_at = ?, updated_by = ?, version = version + 1 WHERE id = ?",
        (route, reason, actor.id, now_iso(), actor.id, project_id),
    )
    return {"route": route, "route_auto": current["route_auto"],
            "changed": route != current["route"]}


def set_risk_level(*, project_id: str, level: str, comment: str | None, actor) -> dict:
    """Ручная правка индикатора риска требует комментария (A-10)."""
    if level not in ("green", "yellow", "red"):
        raise ValueError("Индикатор риска: green, yellow или red")
    current = scalar("SELECT risk_level FROM projects WHERE id = ?", (project_id,))
    if current is None:
        raise ValueError("Проект не найден")
    if current != level and not (comment or "").strip():
        raise ValueError("Ручная правка индикатора риска требует комментария (A-10)")
    execute(
        "UPDATE projects SET risk_level = ?, risk_level_comment = ?, risk_changed_at = ?,"
        " updated_at = ?, updated_by = ? WHERE id = ?",
        (level, comment, now_iso(), now_iso(), actor.id, project_id),
    )
    return {"risk_level": level, "previous": current}


def set_leader(*, project_id: str, person_id: str, actor) -> dict:
    """Смена руководителя проекта (A-12) — один основной руководитель."""
    person = query_one("SELECT id, full_name FROM persons WHERE id = ? AND archived_at IS NULL",
                       (person_id,))
    if person is None:
        raise ValueError("Профиль руководителя не найден")
    previous = scalar("SELECT leader_person_id FROM projects WHERE id = ?", (project_id,))
    with transaction() as conn:
        conn.execute(
            "UPDATE projects SET leader_person_id = ?, updated_at = ?, updated_by = ?,"
            " version = version + 1 WHERE id = ?",
            (person_id, now_iso(), actor.id, project_id),
        )
        conn.execute(
            "UPDATE participations SET role = 'leader' WHERE project_id = ? AND person_id = ?",
            (project_id, person_id),
        )
        if previous and previous != person_id:
            conn.execute(
                "UPDATE participations SET role = 'member' WHERE project_id = ?"
                " AND person_id = ?",
                (project_id, previous),
            )
    return {"leader_person_id": person_id, "full_name": person["full_name"],
            "previous": previous}


def apply_transition(*, project_id: str, action: str, actor, reason: str | None) -> dict:
    """Выполнить переход статуса по матрице Приложения Б.

    Недопустимая смена статуса блокируется (FR-10) с перечнем причин.
    """
    from ..db import get_conn

    project = dict(query_one("SELECT * FROM projects WHERE id = ?", (project_id,)))
    if not project:
        raise ValueError("Проект не найден")

    ctx = build_context(project_id, project)
    actor_roles = actor.workflow_actors()
    check = check_transition(
        route=project["route"], status=project["status"], action=action,
        actor_roles=actor_roles, ctx=ctx, reason=reason,
    )
    if not check.allowed:
        return {"applied": False, **check.as_dict()}

    spec = find_transition(project["route"], action)
    assert spec is not None

    # Объект решения (решения регистрируются отдельно, FR-15)
    with transaction() as conn:
        conn.execute(
            "UPDATE projects SET status = ?, status_changed_at = ?, updated_at = ?,"
            " updated_by = ?, version = version + 1 WHERE id = ?",
            (spec.to_status, now_iso(), now_iso(), actor.id, project_id),
        )
        if spec.switches_to_full:
            conn.execute(
                "UPDATE projects SET route = ?, route_fixed_by = ? WHERE id = ?",
                (ROUTE_FULL, actor.id, project_id),
            )
        # ST-11 «Завершён» переводит точки в выполненные только если они закрыты
        if spec.to_status == ST_COMPLETED:
            conn.execute(
                "UPDATE milestones SET status = 'done' WHERE project_id = ?"
                " AND status IN ('done', 'cancelled', 'overdue', 'in_progress', 'planned')"
                " AND actual_date IS NOT NULL AND COALESCE(TRIM(confirmation), '') <> ''",
                (project_id,),
            )

    return {
        "applied": True,
        "from_status": project["status"],
        "to_status": spec.to_status,
        "to_status_title": STATUS_TITLES.get(spec.to_status, spec.to_status),
        "action": spec.action,
        "title": spec.title,
        "route": ROUTE_FULL if spec.switches_to_full else project["route"],
    }


def transition_options(project_id: str, project: dict, actor) -> list[dict]:
    ctx = build_context(project_id, project)
    return available_actions(project["route"], project["status"], actor.workflow_actors(), ctx)


def archive_project(*, project_id: str, actor, basis: str) -> dict:
    """FR-31: архивирование без потери связей и истории.

    Физическое удаление из обычного интерфейса запрещено (п.10.1 п.3).
    """
    project = dict(query_one("SELECT archived_at FROM projects WHERE id = ?", (project_id,)))
    if project is None:
        raise ValueError("Проект не найден")
    if project["archived_at"]:
        return {"archived": True, "already": True}
    if not (basis or "").strip():
        raise ValueError("Архивирование требует указания основания")
    execute(
        "UPDATE projects SET archived_at = ?, updated_at = ?, updated_by = ? WHERE id = ?",
        (now_iso(), now_iso(), actor.id, project_id),
    )
    return {"archived": True, "archived_at": now_iso()}


def card_validation_report(project_id: str, project: dict) -> dict:
    """Точный перечень незаполненных полей + ограничения длины (FR-07)."""
    counts = related_counts(project_id)
    missing = missing_required_fields(
        project,
        team_size=counts["team"], milestone_count=counts["milestones"],
        partner_count=counts["partners"],
    )
    return {
        "missing_required": missing,
        "missing_count": len(missing),
        "length_problems": validate_lengths(project),
        "route": project["route"],
        "counts": counts,
    }


def project_card(project_id: str) -> dict:
    """Полная карточка для интерфейса: 10 разделов Приложения А."""
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if project is None:
        return {}
    card = dict(project)
    card["full_route_reasons"] = stored_full_reasons(project_id)
    card["counts"] = related_counts(project_id)
    card["risk"] = recompute_risk(project_id)
    card["validation"] = card_validation_report(project_id, card)
    card["created_by_login"] = scalar(
        "SELECT login FROM users WHERE id = ?", (card.get("created_by"),), None)
    # Название программы, а не её идентификатор: в списке программа уже
    # показывалась названием, а в карточке выводился UUID — это выглядело как
    # ошибка и было нечитаемо для пользователя (п.10.2 п.1).
    program = query_one("SELECT code, title FROM programs WHERE id = ?",
                        (card.get("program_id"),))
    card["program_code"] = program["code"] if program else None
    card["program_title"] = (program["title"] if program else None) or ""
    return card