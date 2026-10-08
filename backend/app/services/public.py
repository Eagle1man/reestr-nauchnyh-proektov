"""Публичная проекция (FR-22, FR-33, FR-34; раздел 9 ТЗ).

П.9.1: раздел «Наука» — публичная витрина, реестр — операционный источник
данных. Сайт не хранит и не редактирует вторую копию карточки. Прямое
подключение сайта к рабочей базе запрещается.

SEC-03: в публичной зоне нет прямого доступа к рабочей базе; передаются
ТОЛЬКО утверждённые поля.

П.9.2 — что публикуется:
  номер, название, публичная аннотация, программа, открытый статус, год или
  сроки, ключевые слова, утверждённые сведения о руководителе и команде,
  подтверждённые результаты, ссылки на открытые материалы.
Что НЕ публикуется никогда:
  внутренние комментарии, экспертные заключения, история согласований, риски,
  ресурсные запросы, персональные контакты, закрытые файлы, конфиденциальные
  сведения о партнёрах, журнал действий.

Здесь белый список полей, а не чёрный: новое поле, добавленное в карточку,
в публичный контур не попадёт, пока его явно не внесут в список.
"""

from __future__ import annotations

from typing import Any

from ..db import query, query_one, scalar
from ..domain.taxonomy import (
    PUBLISH_MODE_SCOPE, RISK_TITLES, STATUS_TITLES,
)
from ..utils import fmt_date, today_iso

#: Статусы, которые показываются в открытом разделе (п.9.1 п.2: действующие
#: и завершённые проекты). Черновики и внутренние стадии не показываются.
PUBLIC_STATUSES: tuple[str, ...] = ("ST-07", "ST-08", "ST-10", "ST-11")

#: Стадии результата, которые считаются подтверждёнными (п.9.1 п.3)
PUBLIC_RESULT_STAGES: tuple[str, ...] = ("accepted", "published", "implemented")


def _keywords(project: dict) -> list[str]:
    """Ключевые слова из названия и краткой аннотации.

    Отдельного поля «ключевые слова» в Приложении А нет, а п.9.2 относит его
    к публикуемым. Собираем из уже существующих текстов, не вводя новых данных.
    """
    source = " ".join(filter(None, [
        project.get("short_title"), project.get("title"),
        project.get("public_annotation"),
    ]))
    stop = {
        "для", "под", "над", "при", "через", "этот", "эта", "который", "которая",
        "исследование", "проект", "метод", "анализ", "разработка", "изучение",
    }
    words = [w for w in "".join(
        c.lower() if c.isalnum() else " " for c in source).split()
        if len(w) > 4 and w not in stop]
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= 12:
            break
    return out


def _public_team(project: dict) -> list[dict]:
    """Открытая команда: только те, кто разрешён к публикации (A-13 is_public)."""
    # position и work_place — поля профиля человека, а не записи участия.
    rows = query(
        "SELECT pe.full_name, pp.role, pp.is_public, pe.position, pe.work_place"
        " FROM participations pp JOIN persons pe ON pe.id = pp.person_id"
        " WHERE pp.project_id = ? AND pp.archived_at IS NULL AND pp.is_public = 1"
        " ORDER BY CASE pp.role WHEN 'leader' THEN 0 ELSE 1 END, pe.full_name",
        (project["id"],))
    team = []
    for row in rows:
        item = {
            "full_name": row["full_name"],
            "role": row["role"],
            "role_title": {"leader": "Руководитель", "member": "Участник",
                           "supervisor": "Научный руководитель",
                           "curator": "Куратор программы"}.get(row["role"], row["role"]),
        }
        # Утверждённые сведения о руководителе и команде — без контактов (п.9.2)
        if row["position"]:
            item["position"] = row["position"]
        if row["work_place"]:
            item["work_place"] = row["work_place"]
        team.append(item)
    return team


def _public_results(project: dict) -> list[dict]:
    """Подтверждённые результаты проекта (п.9.1 п.3)."""
    rows = query(
        "SELECT r.id, r.code, r.result_type, r.title, r.description, r.readiness_stage,"
        " r.actual_date, r.doi, r.edn, r.url, r.is_public"
        " FROM result_projects rp JOIN results r ON r.id = rp.result_id"
        " WHERE rp.project_id = ? AND r.archived_at IS NULL"
        " AND r.publish_allowed = 1 AND r.is_public = 1"
        " AND r.readiness_stage IN (?, ?, ?)"
        " ORDER BY COALESCE(r.actual_date, '9999') DESC, r.code",
        (project["id"], *PUBLIC_RESULT_STAGES))
    out = []
    for row in rows:
        out.append({
            "code": row["code"],
            "type": row["result_type"],
            "title": row["title"],
            "description": row["description"],
            "stage": row["readiness_stage"],
            "year": (row["actual_date"] or "")[:4] or None,
            "identifiers": _identifiers(row),
        })
    return out


def _identifiers(row) -> dict[str, str]:
    ids: dict[str, str] = {}
    if row["doi"]:
        ids["doi"] = row["doi"]
    if row["edn"]:
        ids["edn"] = row["edn"]
    if row["url"]:
        ids["url"] = row["url"]
    return ids


def _public_materials(project: dict) -> list[dict]:
    """Ссылки на открытые материалы (п.9.2). Только уровень доступа public."""
    rows = query(
        "SELECT title, kind, url FROM evidences WHERE object_type = 'project'"
        " AND object_id = ? AND access_level = 'public' AND archived_at IS NULL"
        " AND kind = 'link' ORDER BY title", (project["id"],))
    return [{"title": r["title"], "url": r["url"]} for r in rows]


def _program_public(program_id: str) -> dict | None:
    row = query_one(
        "SELECT id, code, title, short_title, description, expected_results,"
        " planned_start, planned_end, public_allowed FROM programs WHERE id = ?",
        (program_id,))
    if row is None:
        return None
    program = dict(row)
    return {
        "code": program["code"],
        "title": program["title"],
        "short_title": program["short_title"],
        "description": program["description"],
        "expected_results": program["expected_results"],
        "start_year": (program["planned_start"] or "")[:4] or None,
        "end_year": (program["planned_end"] or "")[:4] or None,
    }


def project_public_card(project: dict, *, include_unpublished: bool = False) -> dict:
    """Публичная карточка проекта — только разрешённые поля (FR-22).

    include_unpublished=True используется для предпросмотра внутри системы:
    показывает, ЧТО БЫЛО БЫ передано, но с пометкой published=False.
    """
    mode = project.get("publish_mode") or "none"
    scope = PUBLISH_MODE_SCOPE.get(mode, ())
    approved = bool(project.get("public_allowed_at"))
    status = project.get("status")
    status_ok = status in PUBLIC_STATUSES
    not_archived = not project.get("archived_at")

    published = bool(approved and not_archived and status_ok and scope)

    card: dict[str, Any] = {
        "code": project.get("code"),
        "title": project.get("title"),
        "short_title": project.get("short_title"),
        "public_annotation": project.get("public_annotation"),
        "status": status,
        "status_title": STATUS_TITLES.get(status, status),
        # ВНИМАНИЕ: route (упрощённый или полный маршрут) в публичную карточку
        # НЕ выводится. A-07 «Маршрут» помечен в Приложении А как «Открыто: Нет»,
        # а различие маршрутов раскрывает внутреннюю логику процесса и часть
        # оснований T-01…T-06. Поле route отсутствует и в PUBLIC_PROJECT_FIELDS.
        "start_year": (project.get("planned_start") or "")[:4] or None,
        "end_year": (project.get("planned_end") or "")[:4] or None,
        "start_date": fmt_date(project.get("planned_start")),
        "end_date": fmt_date(project.get("planned_end")),
        "program": _program_public(project.get("program_id")),
        "keywords": _keywords(project),
        "published": published,
    }

    if "project" in scope:
        card["team"] = _public_team(project)
        card["materials"] = _public_materials(project)
    if "results" in scope:
        card["results"] = _public_results(project)

    if include_unpublished and not published:
        card["withheld_reasons"] = _withhold_reasons(
            project, mode, approved, status_ok, not_archived)

    return card


def _withhold_reasons(project: dict, mode: str, approved: bool,
                      status_ok: bool, not_archived: bool) -> list[str]:
    reasons: list[str] = []
    if not approved:
        reasons.append("Нет разрешения уполномоченного лица на публикацию (п.9.2)")
    if not mode or mode == "none":
        reasons.append("Режим публикации — «Не публиковать» (A-15)")
    if not not_archived:
        reasons.append("Проект архивирован")
    if not status_ok:
        reasons.append(
            f"Статус «{STATUS_TITLES.get(project.get('status'), project.get('status'))}» "
            "не относится к действующим или завершённым (п.9.1)"
        )
    if not project.get("public_annotation"):
        reasons.append("Не заполнена публичная аннотация (A-04)")
    return reasons


def result_public_card(result: dict) -> dict | None:
    """Публичная карточка результата. None — если результат передавать нельзя."""
    if result.get("archived_at"):
        return None
    if not result.get("publish_allowed") or not result.get("is_public"):
        return None
    if result.get("readiness_stage") not in PUBLIC_RESULT_STAGES:
        return None
    projects = [
        {"code": r["code"], "title": r["title"]}
        for r in query(
            "SELECT p.code, p.title FROM result_projects rp"
            " JOIN projects p ON p.id = rp.project_id WHERE rp.result_id = ?"
            " AND p.publish_mode <> 'none' AND p.public_allowed_at IS NOT NULL"
            " AND p.archived_at IS NULL ORDER BY p.code", (result["id"],))
    ]
    return {
        "code": result["code"],
        "type": result["result_type"],
        "title": result["title"],
        "description": result["description"],
        "stage": result["readiness_stage"],
        "year": (result.get("actual_date") or "")[:4] or None,
        "identifiers": _identifiers(result),
        "projects": projects,
    }


def public_projects(filters: dict | None = None) -> list[dict]:
    """Публичные проекты для витрины и API (только опубликованные)."""
    where = [
        "p.archived_at IS NULL",
        "p.public_allowed_at IS NOT NULL",
        "p.status IN (?, ?, ?, ?)",
        "p.publish_mode <> 'none'",
        "TRIM(COALESCE(p.public_annotation, '')) <> ''",
    ]
    params: list[Any] = list(PUBLIC_STATUSES)
    filters = filters or {}
    if filters.get("program"):
        where.append("pr.code = ? OR pr.id = ?")
        params.extend([filters["program"], filters["program"]])
    if filters.get("year"):
        where.append("(SUBSTR(p.planned_start, 1, 4) = ? OR SUBSTR(p.planned_end, 1, 4) = ?)")
        params.extend([str(filters["year"])] * 2)
    if filters.get("status"):
        where.append("p.status = ?")
        params.append(filters["status"])
    if filters.get("q"):
        # Поиск идёт по search_blob, а не по LOWER(p.title): встроенная в SQLite
        # lower() работает только с ASCII, поэтому приведение кириллицы к
        # нижнему регистру средствами БД не происходит и фильтр молча не находит
        # НИ ОДНОГО русского проекта. search_blob уже приведён к нижнему
        # регистру в Python при записи карточки.
        needle = f"%{str(filters['q']).lower()}%"
        where.append("p.search_blob LIKE ?")
        params.append(needle)
    rows = query(
        "SELECT p.* FROM projects p LEFT JOIN programs pr ON pr.id = p.program_id"
        f" WHERE {' AND '.join(where)} ORDER BY p.code", tuple(params))
    out = []
    for row in rows:
        card = project_public_card(dict(row))
        if card["published"]:
            out.append(card)
    return out


def public_results(filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    where = [
        "r.archived_at IS NULL",
        "r.publish_allowed = 1",
        "r.is_public = 1",
        f"r.readiness_stage IN ({','.join('?' * len(PUBLIC_RESULT_STAGES))})",
    ]
    params: list[Any] = list(PUBLIC_RESULT_STAGES)
    if filters.get("type"):
        where.append("r.result_type = ?")
        params.append(filters["type"])
    if filters.get("year"):
        where.append("SUBSTR(COALESCE(r.actual_date, ''), 1, 4) = ?")
        params.append(str(filters["year"]))
    rows = query(
        f"SELECT r.* FROM results r WHERE {' AND '.join(where)} ORDER BY r.code",
        tuple(params))
    return [c for c in (result_public_card(dict(r)) for r in rows) if c]


def public_programs() -> list[dict]:
    rows = query(
        "SELECT * FROM programs WHERE archived_at IS NULL AND is_active = 1"
        " AND public_allowed = 1 ORDER BY title")
    out = []
    for row in rows:
        program = _program_public(row["id"])
        if program:
            program["id"] = row["id"]
            program["projects_count"] = scalar(
                "SELECT COUNT(*) FROM projects p WHERE p.program_id = ?"
                " AND p.public_allowed_at IS NOT NULL AND p.archived_at IS NULL"
                f" AND p.status IN ({','.join('?' * len(PUBLIC_STATUSES))})",
                (row["id"], *PUBLIC_STATUSES), 0)
            out.append(program)
    return out


def withdrawal_notice(result: dict) -> dict:
    """Что показывается вместо снятого с публикации объекта (FR-34)."""
    return {
        "code": result.get("code"),
        "published": False,
        "withheld": True,
        "message": "Сведения сняты с публикации уполномоченным лицом",
    }


def stats() -> dict:
    return {
        "projects": len(public_projects()),
        "results": len(public_results()),
        "programs": len(public_programs()),
        "generated_at": today_iso(),
    }