"""Экспертизы и решения (M-03, FR-14, FR-15; п.4.1, п.7.1, A-63, A-64).

Ключевые правила ТЗ, которые реализуются здесь:
  * заключение содержит четыре обязательных блока и рекомендацию (п.7.1);
  * после фиксации заключение НЕ редактируется, исправление — новая версия;
  * эксперт до доступа к закрытым материалам подтверждает отсутствие конфликта
    интересов либо заявляет самоотвод (п.4.1 п.4);
  * факт отвода и замещения фиксируется в журнале без возможности удаления
    (п.4.1 п.6);
  * решение не создаётся без основания (A-64);
  * сроки: эксперт принимает задание либо самоотводится за 1 рабочий день,
    заключение — до 10 рабочих дней (п.5.5).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .. import audit
from ..access import attach_relations, can_be_expert, can_view_project, conflict_reasons
from ..db import execute, query, query_one, scalar
from ..domain.taxonomy import (
    RECOMMENDATIONS, REVIEW_BLOCKS, ROLE_PRORECTOR, ROLE_SECRETARY, ROLE_SYSADMIN,
    SLA_DAYS, STATUS_TITLES,
)
from ..utils import add_working_days, fmt_date, new_id, now_iso, today_msk
from .deps import CurrentActor, Pagination

router = APIRouter(prefix="/api", tags=["Экспертизы и решения"])

REQUIRED_BLOCK_KEYS = [key for key, _ in REVIEW_BLOCKS]


def _project_or_404(project_id: str) -> dict:
    row = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return dict(row)


def _require_edit(project_id: str, actor):
    scoped = attach_relations(actor, project_id)
    if not (scoped.is_leader or scoped.global_roles & {
            ROLE_SECRETARY, ROLE_PRORECTOR, ROLE_SYSADMIN} or scoped.is_curator_of_project):
        raise HTTPException(status_code=403,
                            detail="Операция недоступна вашей роли на этом проекте")
    return scoped


def expert_conflicts(project_id: str, expert_person_id: str) -> list[str]:
    """Почему конкретный человек не может быть независимым экспертом (п.4.1 п.2).

    Проверяется по данным эксперта: участие в проекте, авторство по связанным
    результатам, научное руководство, кураторство программы.
    """
    reasons: list[str] = []

    def check(sql: str, params: tuple, label: str) -> None:
        if query_one(sql, params):
            reasons.append(f"Эксперт является {label}")

    check("SELECT 1 FROM participations WHERE project_id = ? AND person_id = ?"
          " AND archived_at IS NULL", (project_id, expert_person_id),
          "участником или руководителем этого проекта")
    check("SELECT 1 FROM program_curators pc JOIN projects p ON p.program_id = pc.program_id"
          " WHERE p.id = ? AND pc.person_id = ?", (project_id, expert_person_id),
          "куратором программы этого проекта")
    check("SELECT 1 FROM results r JOIN result_projects rp ON rp.result_id = r.id"
          " WHERE rp.project_id = ? AND r.authors LIKE ?",
          (project_id, f'%"{expert_person_id}"%'),
          "автором результата, связанного с проектом")
    check("SELECT 1 FROM student_tasks WHERE project_id = ? AND supervisor_person_id = ?",
          (project_id, expert_person_id),
          "научным руководителем участника или аспиранта по проекту")
    check("SELECT 1 FROM dissertations d JOIN dissertation_projects dp"
          " ON dp.dissertation_id = d.id WHERE dp.project_id = ?"
          " AND d.supervisor_person_id = ?", (project_id, expert_person_id),
          "научным руководителем аспиранта по проекту")
    return reasons


def expert_has_role(expert_person_id: str) -> bool:
    """Есть ли у эксперта активная учётная запись, которая сможет подать заключение."""
    return bool(query_one(
        "SELECT 1 FROM persons p JOIN users u ON u.person_id = p.id"
        " WHERE p.id = ? AND u.is_active = 1", (expert_person_id,)))


# ===========================================================================
#  Экспертизы (FR-14)
# ===========================================================================

class ReviewAssign(BaseModel):
    expert_person_id: str
    stage: str = Field(default="preliminary", pattern="^(preliminary|final|publication)$")
    object_type: str = Field(default="project", pattern="^(project|result)$")
    object_id: str | None = None


class ReviewBody(BaseModel):
    """Краткое заключение: четыре обязательных блока и рекомендация (п.7.1)."""
    block_goal_fit: str = Field(min_length=3, max_length=4000)
    block_method_data: str = Field(min_length=3, max_length=4000)
    block_result_quality: str = Field(min_length=3, max_length=4000)
    block_risks_limits: str = Field(min_length=3, max_length=4000)
    recommendation: str = Field(pattern="^(support|support_with_conditions|revise|not_support)$")
    verdict_text: str | None = Field(default=None, max_length=8000)


def _review_dict(row) -> dict:
    review = dict(row)
    review["due_at_fmt"] = fmt_date(review.get("due_at"))
    review["blocks_filled"] = [
        {"key": key, "title": title, "filled": bool(review.get(key))}
        for key, title in REVIEW_BLOCKS
    ]
    review["recommendation_title"] = RECOMMENDATIONS.get(review.get("recommendation"))
    review["finalized"] = bool(review.get("finalized_at"))
    review["immutable"] = bool(review.get("finalized_at"))
    return review


@router.get("/projects/{project_id}/reviews")
def list_reviews(project_id: str, actor: CurrentActor,
                 object_type: str | None = None):
    _project_or_404(project_id)
    clause = " AND r.object_type = ?" if object_type else ""
    params = (project_id, object_type) if object_type else (project_id,)
    rows = query(
        f"SELECT r.*, p.full_name AS expert_name FROM reviews r"
        f" LEFT JOIN persons p ON p.id = r.expert_person_id"
        f" WHERE r.project_id = ?{clause} ORDER BY r.assigned_at DESC", params)
    return {"items": [_review_dict(r) for r in rows]}


@router.post("/projects/{project_id}/reviews", status_code=201)
def assign_review(project_id: str, body: ReviewAssign, actor: CurrentActor):
    """Назначение эксперта (FR-14). Секретарь назначает, проверяя конфликт интересов."""
    project = _project_or_404(project_id)
    scoped = _require_edit(project_id, actor)
    if not (scoped.has(ROLE_SECRETARY, ROLE_SYSADMIN, ROLE_PRORECTOR)
            or scoped.is_curator_of_project):
        raise HTTPException(status_code=403,
                            detail="Назначение эксперта: секретарь, проректор или куратор")
    if query_one("SELECT id FROM persons WHERE id = ? AND archived_at IS NULL",
                 (body.expert_person_id,)) is None:
        raise HTTPException(status_code=404, detail="Профиль эксперта не найден")

    # ПС-07: эксперту назначают только конкретный объект. Конфликт интересов
    # проверяется ДО назначения — по данным самого эксперта, а не по ролям
    # текущего пользователя (п.4.1 п.2).
    reasons = expert_conflicts(project_id, body.expert_person_id)
    if reasons:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Конфликт интересов: эксперту нельзя назначить эту экспертизу",
                    "reasons": reasons})
    if not expert_has_role(body.expert_person_id):
        raise HTTPException(status_code=400,
                            detail="У профиля эксперта нет учётной записи — он не сможет "
                                   "подать заключение")

    existing_active = query_one(
        "SELECT id, expert_person_id FROM reviews WHERE project_id = ?"
        " AND object_type = ? AND COALESCE(object_id, project_id) = ?"
        " AND stage = ? AND recused_at IS NULL AND finalized_at IS NULL",
        (project_id, body.object_type, body.object_id or project_id, body.stage))
    if existing_active is not None and existing_active["expert_person_id"] == body.expert_person_id:
        raise HTTPException(status_code=409,
                            detail="Эксперту уже назначена эта экспертиза")

    rid = new_id()
    due = add_working_days(today_msk(), SLA_DAYS["review_preliminary_or_final"])
    execute(
        "INSERT INTO reviews (id, project_id, object_type, object_id, stage,"
        " expert_person_id, assigned_at, due_at, created_at, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rid, project_id, body.object_type, body.object_id, body.stage,
         body.expert_person_id, now_iso(), due.isoformat(), now_iso(), actor.id))
    audit.record(group_name=audit.GROUP_REVIEW_DECISION, object_type="review",
                 object_id=rid, action="Назначение эксперта", user_id=actor.id,
                 user_login=actor.login,
                 new_value={"project": project["code"], "expert_person_id": body.expert_person_id,
                            "stage": body.stage,
                            "due_at": due.isoformat()})
    return _review_dict(query_one("SELECT * FROM reviews WHERE id = ?", (rid,)))


@router.get("/reviews/mine")
def my_reviews(actor: CurrentActor, page: Annotated[Pagination, Depends()]):
    """Назначения эксперта — в том числе просроченные (FR-24)."""
    if not actor.person_id:
        return {"items": [], "total": 0}
    total = scalar("SELECT COUNT(*) FROM reviews WHERE expert_person_id = ?",
                   (actor.person_id,), 0)
    rows = query(
        "SELECT r.*, p.code AS project_code, p.title AS project_title"
        " FROM reviews r JOIN projects p ON p.id = r.project_id"
        " WHERE r.expert_person_id = ?"
        " ORDER BY CASE WHEN r.finalized_at IS NULL THEN 0 ELSE 1 END, r.due_at"
        " LIMIT ? OFFSET ?", (actor.person_id, page.limit, page.offset))
    items = []
    for row in rows:
        item = _review_dict(row)
        item["overdue"] = bool(
            item["due_at"] and item["due_at"] < today_msk().isoformat()
            and not item["finalized_at"])
        items.append(item)
    return {"items": items, "total": total}


class ConflictBody(BaseModel):
    """Подтверждение отсутствия конфликта либо заявление о самоотводе (п.4.1 п.4)."""
    no_conflict: bool
    note: str | None = Field(default=None, max_length=2000)


@router.post("/reviews/{review_id}/conflict")
def declare_conflict(review_id: str, body: ConflictBody, actor: CurrentActor):
    """ПС-08: подтверждение отсутствия конфликта интересов либо самоотвод.

    Самоотвод необратим: событие сохраняется в журнале без возможности удаления.
    """
    review = query_one("SELECT * FROM reviews WHERE id = ?", (review_id,))
    if review is None:
        raise HTTPException(status_code=404, detail="Экспертиза не найдена")
    if review["finalized_at"]:
        raise HTTPException(status_code=409,
                            detail="Заключение зафиксировано и не изменяется (п.7.1)")
    if actor.person_id != review["expert_person_id"]:
        raise HTTPException(status_code=403, detail="Заявление подаёт назначенный эксперт")
    if review["recused_at"]:
        raise HTTPException(status_code=409,
                            detail="Самоотвод уже зарегистрирован (п.4.1 п.6)")
    if not body.no_conflict and not (body.note or "").strip():
        raise HTTPException(status_code=400,
                            detail="При самоотводе обязательно пояснение")
    if body.no_conflict:
        execute(
            "UPDATE reviews SET expert_declared_no_conflict = 1, conflict_note = ?"
            " WHERE id = ?", (body.note, review_id))
        audit.record(group_name=audit.GROUP_REVIEW_DECISION, object_type="review",
                     object_id=review_id, action="Подтверждение отсутствия конфликта "
                     "интересов", user_id=actor.id, user_login=actor.login,
                     new_value=body.note)
    else:
        execute(
            "UPDATE reviews SET recused_at = ?, recused_by = ?, conflict_note = ?"
            " WHERE id = ?", (now_iso(), actor.id, body.note, review_id))
        audit.record(group_name=audit.GROUP_REVIEW_DECISION, object_type="review",
                     object_id=review_id, action="Самоотвод эксперта", user_id=actor.id,
                     user_login=actor.login, new_value=body.note,
                     basis="п.4.1 п.4 заявление о самоотводе")
    return _review_dict(query_one("SELECT * FROM reviews WHERE id = ?", (review_id,)))


@router.post("/reviews/{review_id}/recuse")
def secretary_recuse(review_id: str, body: ConflictBody, actor: CurrentActor):
    """Самоотвод фиксируется и экспертом, и секретарём — если отвод заявлен устно."""
    review = query_one("SELECT * FROM reviews WHERE id = ?", (review_id,))
    if review is None:
        raise HTTPException(status_code=404, detail="Экспертиза не найдена")
    scoped = _require_edit(review["project_id"], actor)
    if not scoped.has(ROLE_SECRETARY, ROLE_SYSADMIN, ROLE_PRORECTOR):
        raise HTTPException(status_code=403, detail="Регистрация отвода: секретарь")
    if review["recused_at"]:
        raise HTTPException(status_code=409, detail="Отвод уже зарегистрирован")
    if not (body.note or "").strip():
        raise HTTPException(status_code=400, detail="Нужно пояснение основания отвода")
    execute(
        "UPDATE reviews SET recused_at = ?, recused_by = ?, conflict_note = ? WHERE id = ?",
        (now_iso(), actor.id, body.note, review_id))
    audit.record(group_name=audit.GROUP_REVIEW_DECISION, object_type="review",
                 object_id=review_id, action="Самоотвод эксперта зарегистрирован",
                 user_id=actor.id, user_login=actor.login, new_value=body.note)
    return _review_dict(query_one("SELECT * FROM reviews WHERE id = ?", (review_id,)))


@router.get("/reviews/{review_id}")
def get_review(review_id: str, actor: CurrentActor):
    review = query_one(
        "SELECT r.*, p.full_name AS expert_name FROM reviews r"
        " LEFT JOIN persons p ON p.id = r.expert_person_id WHERE r.id = ?", (review_id,))
    if review is None:
        raise HTTPException(status_code=404, detail="Экспертиза не найдена")
    scoped = attach_relations(actor, review["project_id"])
    is_assigned = actor.person_id == review["expert_person_id"]
    if not (is_assigned or scoped.global_roles & {ROLE_SECRETARY, ROLE_PRORECTOR,
                                                  ROLE_SYSADMIN, "rector"}
            or scoped.is_leader or scoped.is_curator_of_project):
        # ПС-07: эксперт получает только назначенные материалы.
        raise HTTPException(status_code=403,
                            detail="Заключение доступно только назначенному эксперту "
                                   "и уполномоченным лицам (ПС-07)")
    out = _review_dict(review)
    out["my_access"] = "expert" if is_assigned else "authority"
    return out


@router.post("/reviews/{review_id}/conclusion")
def submit_conclusion(review_id: str, body: ReviewBody, actor: CurrentActor):
    """Заключение эксперта. После фиксации — неизменяемо (п.7.1)."""
    review = query_one("SELECT * FROM reviews WHERE id = ?", (review_id,))
    if review is None:
        raise HTTPException(status_code=404, detail="Экспертиза не найдена")
    if actor.person_id != review["expert_person_id"]:
        raise HTTPException(status_code=403,
                            detail="Заключение подаёт назначенный эксперт")
    if review["recused_at"]:
        raise HTTPException(status_code=409,
                            detail="Эксперт заявил самоотвод — заключение не принимается")
    if review["finalized_at"]:
        raise HTTPException(status_code=409,
                            detail="Заключение уже зафиксировано и не редактируется. "
                                   "Исправление оформляется новой версией (п.7.1)")
    if review["expert_declared_no_conflict"] is None:
        raise HTTPException(status_code=400,
                            detail="Сначала подтвердите отсутствие конфликта интересов "
                                   "либо заявите самоотвод (п.4.1 п.4)")

    missing = [title for key, title in REVIEW_BLOCKS if not (body.model_dump().get(key) or "").strip()]
    if missing:
        raise HTTPException(status_code=400, detail={
            "error": "Заключение неполное: обязательны четыре блока (п.7.1)",
            "missing_blocks": missing})

    # Дубликат-контроль результата: результат без заключения не подтверждён (A-53)
    version = int(review["version_no"]) + 1
    execute(
        "UPDATE reviews SET block_goal_fit = ?, block_method_data = ?,"
        " block_result_quality = ?, block_risks_limits = ?, recommendation = ?,"
        " verdict_text = ?, finalized_at = ?, version_no = ? WHERE id = ?",
        (body.block_goal_fit, body.block_method_data, body.block_result_quality,
         body.block_risks_limits, body.recommendation, body.verdict_text,
         now_iso(), version, review_id))
    if review["object_type"] == "result" and review["object_id"]:
        execute(
            "UPDATE results SET review_id = ?, review_status = ?, review_comment = ?"
            " WHERE id = ?",
            (review_id,
             "accepted" if body.recommendation in ("support", "support_with_conditions")
             else "pending",
             body.verdict_text, review["object_id"]))
    audit.record(group_name=audit.GROUP_REVIEW_DECISION, object_type="review",
                 object_id=review_id, action=f"Заключение эксперта (версия {version})",
                 user_id=actor.id, user_login=actor.login,
                 new_value={"recommendation": body.recommendation,
                            "blocks": len(REQUIRED_BLOCK_KEYS)},
                 basis="п.7.1 краткое заключение из четырёх блоков")
    return _review_dict(query_one("SELECT * FROM reviews WHERE id = ?", (review_id,)))


@router.post("/reviews/{review_id}/new-version", status_code=201)
def new_version(review_id: str, actor: CurrentActor):
    """Исправление оформляется новой версией, исходное заключение сохраняется (п.7.1)."""
    review = query_one("SELECT * FROM reviews WHERE id = ?", (review_id,))
    if review is None:
        raise HTTPException(status_code=404, detail="Экспертиза не найдена")
    if not review["finalized_at"]:
        raise HTTPException(status_code=400,
                            detail="Версия создаётся только после фиксации заключения")
    scoped = _require_edit(review["project_id"], actor)
    if not scoped.has(ROLE_PRORECTOR, ROLE_SECRETARY):
        raise HTTPException(status_code=403,
                            detail="Новую версию заключения инициирует проректор "
                                   "или секретарь")
    rid = new_id()
    execute(
        "INSERT INTO reviews (id, project_id, object_type, object_id, stage,"
        " expert_person_id, assigned_at, due_at, created_at, created_by, version_no,"
        " replaced_by_review_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rid, review["project_id"], review["object_type"], review["object_id"],
         review["stage"], review["expert_person_id"], now_iso(),
         add_working_days(today_msk(), SLA_DAYS["review_preliminary_or_final"]).isoformat(),
         now_iso(), actor.id, int(review["version_no"]) + 1, review_id))
    execute("UPDATE reviews SET replaced_by_review_id = ? WHERE id = ?", (rid, review_id))
    audit.record(group_name=audit.GROUP_REVIEW_DECISION, object_type="review",
                 object_id=rid, action=f"Новая версия заключения (исправление)",
                 user_id=actor.id, user_login=actor.login,
                 old_value={"review_id": review_id},
                 basis="п.7.1 исправление оформляется новой версией")
    return _review_dict(query_one("SELECT * FROM reviews WHERE id = ?", (rid,)))


# ===========================================================================
#  Решения (FR-15, A-64)
# ===========================================================================

class DecisionBody(BaseModel):
    object_type: str = Field(default="project", pattern="^(project|result|program)$")
    object_id: str | None = None
    level: str = Field(pattern="^(curator|prorector|rector|council|secretary)$")
    kind: str = Field(pattern="^(launch|accept|return|suspend|resume|pilot|reserve|"
                              "reject|close|publish|return_to_work)$")
    wording: str = Field(min_length=5, max_length=4000)
    basis: str = Field(min_length=3, max_length=4000)
    conditions: str | None = Field(default=None, max_length=4000)
    responsible_person_id: str | None = None
    due_at: str | None = None


@router.get("/projects/{project_id}/decisions")
def list_decisions(project_id: str, actor: CurrentActor):
    _project_or_404(project_id)
    rows = query(
        "SELECT d.*, p.full_name AS responsible_name, u.login AS decided_by_login"
        " FROM decisions d"
        " LEFT JOIN persons p ON p.id = d.responsible_person_id"
        " LEFT JOIN users u ON u.id = d.decided_by"
        " WHERE d.project_id = ? ORDER BY d.decided_at DESC", (project_id,))
    return {"items": [dict(r) for r in rows]}


@router.post("/projects/{project_id}/decisions", status_code=201)
def create_decision(project_id: str, body: DecisionBody, actor: CurrentActor):
    """Регистрация решения. A-64: решение не создаётся без основания."""
    project = _project_or_404(project_id)
    scoped = _require_edit(project_id, actor)

    from ..access import decision_authority
    expected, note = decision_authority(scoped, project_id)
    if expected is None:
        raise HTTPException(status_code=403,
                            detail="Решение по проекту принимает куратор программы "
                                   "или проректор по науке (п.4.2)")
    if body.level != expected:
        raise HTTPException(
            status_code=403,
            detail={"error": f"Уровень решения должен быть «{expected}»", "authority": note})
    # П.4.1 п.3: заинтересованность куратора — решение переходит к проректору
    if body.level == "curator" and conflict_reasons(scoped, project_id):
        raise HTTPException(status_code=409,
                            detail="Заинтересованность куратора: решение переходит "
                                   "к проректору по науке (п.4.1 п.3)")

    did = new_id()
    execute(
        "INSERT INTO decisions (id, project_id, object_type, object_id, level, kind,"
        " wording, basis, conditions, responsible_person_id, due_at, decided_at,"
        " decided_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (did, project_id, body.object_type, body.object_id, body.level, body.kind,
         body.wording, body.basis, body.conditions, body.responsible_person_id,
         body.due_at, now_iso(), actor.id, now_iso()))
    audit.record(group_name=audit.GROUP_REVIEW_DECISION, object_type="decision",
                 object_id=did, action=f"Решение: {body.kind}", user_id=actor.id,
                 user_login=actor.login,
                 new_value={"level": body.level, "kind": body.kind,
                            "project": project["code"]},
                 basis=body.basis)
    return dict(query_one("SELECT * FROM decisions WHERE id = ?", (did,)))


@router.post("/decisions/{decision_id}/execute")
def execute_decision(decision_id: str, note: str, actor: CurrentActor):
    """Исполнение решения фиксируется в журнале (FR-15)."""
    decision = query_one("SELECT * FROM decisions WHERE id = ?", (decision_id,))
    if decision is None:
        raise HTTPException(status_code=404, detail="Решение не найдено")
    if decision["project_id"]:
        _require_edit(decision["project_id"], actor)
    if decision["executed_at"]:
        raise HTTPException(status_code=409, detail="Решение уже исполнено")
    if not (note or "").strip():
        raise HTTPException(status_code=400, detail="Нужна отметка о исполнении")
    execute("UPDATE decisions SET executed_at = ?, execution_note = ? WHERE id = ?",
            (now_iso(), note, decision_id))
    audit.record(group_name=audit.GROUP_REVIEW_DECISION, object_type="decision",
                 object_id=decision_id, action="Исполнение решения",
                 user_id=actor.id, user_login=actor.login, new_value=note)
    return dict(query_one("SELECT * FROM decisions WHERE id = ?", (decision_id,)))