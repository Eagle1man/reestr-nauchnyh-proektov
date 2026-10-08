"""Команда, контрольные точки, риски и материалы проекта.

FR-11 команда, FR-12 контрольные точки, FR-13 риски (статус и индикатор риска —
разные поля, п.5.4), FR-21 материалы (вторая очередь: ссылки и защищённые файлы).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import audit
from ..access import attach_relations, can_edit_card, can_view_project
from ..db import execute, query, query_one, scalar, transaction
from ..domain.taxonomy import RISK_GREEN, RISK_RED, RISK_YELLOW, REL_MEMBER, ST_ACTIVE
from ..services import projects as svc
from ..utils import fmt_date, new_id, now_iso, today_iso, to_date, working_days_between
from .deps import CurrentActor, Pagination

router = APIRouter(prefix="/api/projects/{project_id}", tags=["Карточка проекта"])


def _require_project(project_id: str) -> dict:
    row = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return dict(row)


def _require_edit(project_id: str, actor):
    scoped = attach_relations(actor, project_id)
    if not can_edit_card(scoped, project_id, _require_project(project_id)["status"]):
        raise HTTPException(status_code=403,
                            detail="Правка недоступна вашей роли на этом проекте")
    return scoped


# ===========================================================================
#  Команда (FR-11, A-13)
# ===========================================================================

class ParticipationBody(BaseModel):
    person_id: str
    role: str = Field(default="member", pattern="^(member|supervisor|curator|leader)$")
    task: str | None = Field(default=None, max_length=2000)
    started_at: str | None = None
    finished_at: str | None = None
    effort_share: float | None = Field(default=None, ge=0, le=1)
    is_public: bool = False


@router.get("/team")
def get_team(project_id: str, actor: CurrentActor):
    rows = query(
        "SELECT pp.*, p.full_name, p.work_place, p.position, p.category"
        " FROM participations pp JOIN persons p ON p.id = pp.person_id"
        " WHERE pp.project_id = ? AND pp.archived_at IS NULL"
        " ORDER BY CASE pp.role WHEN 'leader' THEN 0 WHEN 'member' THEN 1"
        "          WHEN 'supervisor' THEN 2 ELSE 3 END, p.full_name",
        (project_id,))
    return {"items": [dict(r) for r in rows]}


@router.post("/team", status_code=201)
def add_participant(project_id: str, body: ParticipationBody, actor: CurrentActor):
    """FR-11: руководитель назначает участников, роли, задачи и сроки участия."""
    project = _require_project(project_id)
    scoped = _require_edit(project_id, actor)
    if query_one("SELECT id FROM persons WHERE id = ? AND archived_at IS NULL",
                 (body.person_id,)) is None:
        raise HTTPException(status_code=404, detail="Профиль участника не найден")
    if query_one("SELECT id FROM participations WHERE project_id = ? AND person_id = ?",
                 (project_id, body.person_id)):
        raise HTTPException(status_code=409,
                            detail="Участник уже включён в команду проекта")
    if body.started_at and body.finished_at and body.started_at > body.finished_at:
        raise HTTPException(status_code=400,
                            detail="Период участия: начало позже завершения")
    pid = new_id()
    execute(
        "INSERT INTO participations (id, project_id, person_id, role, task, started_at,"
        " finished_at, effort_share, is_public, created_at, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pid, project_id, body.person_id, body.role, body.task, body.started_at,
         body.finished_at, body.effort_share, 1 if body.is_public else 0,
         now_iso(), actor.id))
    # Руководитель обязан быть и в команде (A-12 + A-13)
    if body.role == "leader":
        execute("UPDATE projects SET leader_person_id = ?, updated_at = ? WHERE id = ?",
                (body.person_id, now_iso(), project_id))
    audit.record(group_name=audit.GROUP_CARD, object_type="project",
                 object_id=project_id, action="Добавлен участник команды",
                 user_id=actor.id, user_login=actor.login,
                 new_value={"person_id": body.person_id, "role": body.role})
    return dict(query_one("SELECT * FROM participations WHERE id = ?", (pid,)))


@router.patch("/team/{participation_id}")
def update_participant(project_id: str, participation_id: str,
                       body: ParticipationBody, actor: CurrentActor):
    _require_project(project_id)
    _require_edit(project_id, actor)
    row = query_one("SELECT * FROM participations WHERE id = ? AND project_id = ?",
                    (participation_id, project_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Запись о участии не найдена")
    execute(
        "UPDATE participations SET role = ?, task = ?, started_at = ?, finished_at = ?,"
        " effort_share = ?, is_public = ? WHERE id = ?",
        (body.role, body.task, body.started_at, body.finished_at, body.effort_share,
         1 if body.is_public else 0, participation_id))
    audit.record(group_name=audit.GROUP_CARD, object_type="project",
                 object_id=project_id, action="Изменён участник команды",
                 user_id=actor.id, user_login=actor.login,
                 old_value={"role": row["role"], "is_public": row["is_public"]},
                 new_value={"role": body.role, "is_public": body.is_public})
    return dict(query_one("SELECT * FROM participations WHERE id = ?", (participation_id,)))


@router.post("/team/{participation_id}/confirm")
def confirm_contribution(project_id: str, participation_id: str, actor: CurrentActor):
    """Подтверждение вклада участника (A-13)."""
    _require_project(project_id)
    scoped = _require_edit(project_id, actor)
    row = query_one("SELECT * FROM participations WHERE id = ? AND project_id = ?",
                    (participation_id, project_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Запись о участии не найдена")
    execute("UPDATE participations SET contribution_confirmed = 1 WHERE id = ?",
            (participation_id,))
    audit.record(group_name=audit.GROUP_CARD, object_type="project",
                 object_id=project_id, action="Подтверждён вклад участника",
                 user_id=actor.id, user_login=actor.login,
                 new_value={"person_id": row["person_id"]})
    return {"ok": True}


@router.delete("/team/{participation_id}", status_code=204)
def remove_participant(project_id: str, participation_id: str, actor: CurrentActor):
    """Участник архивируется, а не удаляется: связи и история сохраняются (п.6.1 п.5)."""
    _require_project(project_id)
    _require_edit(project_id, actor)
    row = query_one("SELECT * FROM participations WHERE id = ? AND project_id = ?",
                    (participation_id, project_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Запись о участии не найдена")
    if row["role"] == "leader":
        raise HTTPException(status_code=400,
                            detail="Сначала назначьте другого руководителя проекта (A-12)")
    execute("UPDATE participations SET archived_at = ? WHERE id = ?",
            (now_iso(), participation_id))
    audit.record(group_name=audit.GROUP_CARD, object_type="project",
                 object_id=project_id, action="Исключён участник из команды",
                 user_id=actor.id, user_login=actor.login,
                 old_value={"person_id": row["person_id"]})
    return None


# ===========================================================================
#  Контрольные точки (FR-12, A-35…A-42)
# ===========================================================================

class MilestoneBody(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    planned_date: str
    responsible_person_id: str
    planned_evidence: str = Field(min_length=3, max_length=1000)
    actual_date: str | None = None
    confirmation: str | None = Field(default=None, max_length=2000)
    postpone_reason: str | None = Field(default=None, max_length=700)


def _milestone_dict(row) -> dict:
    ms = dict(row)
    today = today_iso()
    planned = ms.get("planned_date")
    ms["planned_date_fmt"] = fmt_date(planned)
    ms["actual_date_fmt"] = fmt_date(ms.get("actual_date"))
    ms["is_overdue"] = bool(
        planned and planned < today and ms["status"] not in ("done", "cancelled"))
    if ms["is_overdue"] and ms.get("planned_date"):
        d1, d2 = to_date(planned), to_date(today)
        ms["delay_working_days"] = working_days_between(d1, d2) if d1 and d2 else 0
    else:
        ms["delay_working_days"] = 0
    ms["missing_on_done"] = []
    if ms["status"] == "done":
        if not ms.get("actual_date"):
            ms["missing_on_done"].append("Фактическая дата (A-40)")
        if not (ms.get("confirmation") or "").strip():
            ms["missing_on_done"].append("Подтверждение (A-41)")
    return ms


@router.get("/milestones")
def list_milestones(project_id: str, actor: CurrentActor,
                    include_archived: bool = False):
    _require_project(project_id)
    # archived_at есть и в milestones, и в persons: уточняем таблицу,
    # иначе SQLite считает имя неоднозначным.
    clause = "" if include_archived else " AND m.archived_at IS NULL"
    rows = query(
        f"SELECT m.*, p.full_name AS responsible_name FROM milestones m"
        f" LEFT JOIN persons p ON p.id = m.responsible_person_id"
        f" WHERE m.project_id = ?{clause} ORDER BY m.planned_date", (project_id,))
    items = [_milestone_dict(r) for r in rows]
    return {"items": items,
            "overdue": [i for i in items if i["is_overdue"]],
            "planned": [i for i in items if i["status"] == "planned"]}


@router.post("/milestones", status_code=201)
def create_milestone(project_id: str, body: MilestoneBody, actor: CurrentActor):
    project = _require_project(project_id)
    _require_edit(project_id, actor)
    problems: list[str] = []
    if not to_date(body.planned_date):
        problems.append("A-36: плановая дата не распознана")
    elif project["planned_start"] and body.planned_date < project["planned_start"]:
        problems.append("A-36: плановая дата раньше начала проекта")
    elif project["planned_end"] and body.planned_date > project["planned_end"]:
        problems.append("A-36: плановая дата позже завершения проекта")
    # A-37: ответственный — только действующий участник проекта
    if not query_one(
        "SELECT 1 FROM participations WHERE project_id = ? AND person_id = ?"
        " AND archived_at IS NULL", (project_id, body.responsible_person_id)):
        problems.append("A-37: ответственный должен быть участником проекта")
    if not (body.planned_evidence or "").strip():
        problems.append("A-38: нужно плановое подтверждение — «выполнение работы» "
                        "без доказательства недопустимо")
    if problems:
        raise HTTPException(status_code=400, detail={"error": "Проверка не пройдена",
                                                     "problems": problems})
    mid = new_id()
    execute(
        "INSERT INTO milestones (id, project_id, title, planned_date, actual_date,"
        " responsible_person_id, planned_evidence, status, confirmation, postpone_reason,"
        " created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?, ?)",
        (mid, project_id, body.title, body.planned_date, body.actual_date,
         body.responsible_person_id, body.planned_evidence, body.confirmation,
         body.postpone_reason, now_iso(), actor.id))
    audit.record(group_name=audit.GROUP_CARD, object_type="milestone", object_id=mid,
                 action="Создана контрольная точка", user_id=actor.id,
                 user_login=actor.login,
                 new_value={"project": project["code"], "title": body.title,
                            "planned_date": body.planned_date})
    svc.recompute_risk(project_id)
    return _milestone_dict(query_one("SELECT * FROM milestones WHERE id = ?", (mid,)))


class MilestoneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    planned_date: str | None = None
    actual_date: str | None = None
    responsible_person_id: str | None = None
    planned_evidence: str | None = Field(default=None, min_length=3, max_length=1000)
    confirmation: str | None = Field(default=None, max_length=2000)
    postpone_reason: str | None = Field(default=None, max_length=700)
    status: str | None = Field(default=None,
                               pattern="^(planned|in_progress|done|cancelled)$")


@router.patch("/milestones/{milestone_id}")
def update_milestone(project_id: str, milestone_id: str, body: MilestoneUpdate,
                     actor: CurrentActor):
    """Изменение точки. Перенос срока требует причины (A-42) и попадает в историю."""
    _require_project(project_id)
    _require_edit(project_id, actor)
    row = query_one("SELECT * FROM milestones WHERE id = ? AND project_id = ?",
                    (milestone_id, project_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Контрольная точка не найдена")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="Нет полей для изменения")

    if "planned_date" in data and data["planned_date"] and \
            data["planned_date"] != row["planned_date"] \
            and not (data.get("postpone_reason") or row["postpone_reason"]):
        raise HTTPException(status_code=400,
                            detail="A-42: при изменении срока обязательна причина переноса")

    if data.get("status") == "done":
        actual = data.get("actual_date", row["actual_date"])
        confirm = data.get("confirmation", row["confirmation"])
        if not actual:
            raise HTTPException(status_code=400,
                                detail="A-40: при выполнении обязательна фактическая дата")
        if not (confirm or "").strip():
            raise HTTPException(status_code=400,
                                detail="A-41: при выполнении обязательно подтверждение")
        data["status"] = "done"
    elif data.get("status") == "cancelled" and not (
            data.get("postpone_reason") or row["postpone_reason"]):
        raise HTTPException(status_code=400,
                            detail="Отмена контрольной точки требует пояснения")

    changes: dict[str, tuple[Any, Any]] = {}
    for key, value in data.items():
        if key != "status" and row[key] != value:
            changes[key] = (row[key], value)

    if "planned_date" in changes:
        execute(
            "INSERT INTO milestone_postponements (id, milestone_id, old_date, new_date,"
            " reason, changed_at, changed_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id(), milestone_id, row["planned_date"], data["planned_date"],
             data.get("postpone_reason") or row["postpone_reason"] or "не указана",
             now_iso(), actor.id))
        audit.record(group_name=audit.GROUP_CARD, object_type="milestone",
                     object_id=milestone_id, action="Перенос контрольной точки",
                     user_id=actor.id, user_login=actor.login,
                     old_value=row["planned_date"], new_value=data["planned_date"],
                     basis=data.get("postpone_reason"))

    if changes or "status" in data:
        assignments = []
        params: list[Any] = []
        # changes хранит пары (прежнее, новое); в SQL идёт ТОЛЬКО новое —
        # иначе sqlite получает кортеж вместо значения (ProgrammingError).
        for key, (_old_value, new_value) in changes.items():
            assignments.append(f"{key} = ?")
            params.append(new_value)
        if "status" in data:
            assignments.append("status = ?")
            params.append(data["status"])
        assignments.append("updated_at = ?")
        params.append(now_iso())
        params.append(milestone_id)
        execute(f"UPDATE milestones SET {', '.join(assignments)} WHERE id = ?",
                tuple(params))
        audit.record_change(group_name=audit.GROUP_CARD, object_type="milestone",
                            object_id=milestone_id, action="Изменение контрольной точки",
                            changes=changes, user_id=actor.id, user_login=actor.login)
    risk = svc.recompute_risk(project_id)
    result = _milestone_dict(query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,)))
    result["project_risk"] = risk
    return result


@router.get("/milestones/{milestone_id}/postponements")
def milestone_history(project_id: str, milestone_id: str, actor: CurrentActor):
    """История переносов (FR-12)."""
    rows = query(
        "SELECT * FROM milestone_postponements WHERE milestone_id = ? ORDER BY changed_at",
        (milestone_id,))
    return {"items": [dict(r) for r in rows]}


# ===========================================================================
#  Риски (FR-13, A-65)
# ===========================================================================

class RiskBody(BaseModel):
    category: str
    description: str = Field(min_length=5, max_length=2000)
    probability: str = Field(default="medium", pattern="^(low|medium|high)$")
    impact: str = Field(default="medium", pattern="^(low|medium|high)$")
    measures: str | None = Field(default=None, max_length=2000)
    owner_person_id: str | None = None
    review_date: str | None = None
    status: str = Field(default="open", pattern="^(open|mitigated|closed)$")
    level: str = Field(default="yellow", pattern="^(green|yellow|red)$")
    level_comment: str | None = Field(default=None, max_length=2000)


@router.get("/risks")
def list_risks(project_id: str, actor: CurrentActor):
    _require_project(project_id)
    rows = query(
        "SELECT r.*, p.full_name AS owner_name FROM risks r"
        " LEFT JOIN persons p ON p.id = r.owner_person_id"
        " WHERE r.project_id = ? AND r.archived_at IS NULL"
        " ORDER BY CASE r.level WHEN 'red' THEN 0 WHEN 'yellow' THEN 1 ELSE 2 END,"
        " r.created_at", (project_id,))
    return {"items": [dict(r) for r in rows],
            "counts": {
                "red": scalar("SELECT COUNT(*) FROM risks WHERE project_id = ?"
                              " AND level = 'red' AND archived_at IS NULL"
                              " AND status <> 'closed'", (project_id,), 0),
                "yellow": scalar("SELECT COUNT(*) FROM risks WHERE project_id = ?"
                                 " AND level = 'yellow' AND archived_at IS NULL"
                                 " AND status <> 'closed'", (project_id,), 0),
                "green": scalar("SELECT COUNT(*) FROM risks WHERE project_id = ?"
                                " AND level = 'green' AND archived_at IS NULL"
                                " AND status <> 'closed'", (project_id,), 0),
            }}


@router.post("/risks", status_code=201)
def create_risk(project_id: str, body: RiskBody, actor: CurrentActor):
    _require_project(project_id)
    _require_edit(project_id, actor)
    # A-65: ручное изменение уровня требует комментария
    if body.level != "yellow" and not (body.level_comment or "").strip():
        raise HTTPException(status_code=400,
                            detail="A-65: ручное изменение уровня риска требует комментария")
    rid = new_id()
    execute(
        "INSERT INTO risks (id, project_id, category, description, probability, impact,"
        " measures, owner_person_id, review_date, status, level, level_comment,"
        " created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rid, project_id, body.category, body.description, body.probability,
         body.impact, body.measures, body.owner_person_id, body.review_date,
         body.status, body.level, body.level_comment, now_iso(), actor.id))
    audit.record(group_name=audit.GROUP_CARD, object_type="project", object_id=project_id,
                 action="Добавлен риск", user_id=actor.id, user_login=actor.login,
                 new_value={"category": body.category, "level": body.level,
                            "description": body.description[:200]})
    risk = svc.recompute_risk(project_id)
    return {"risk": dict(query_one("SELECT * FROM risks WHERE id = ?", (rid,))),
            "project_risk": risk}


@router.patch("/risks/{risk_id}")
def update_risk(project_id: str, risk_id: str, body: RiskBody, actor: CurrentActor):
    _require_project(project_id)
    _require_edit(project_id, actor)
    row = query_one("SELECT * FROM risks WHERE id = ? AND project_id = ?", (risk_id, project_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Риск не найден")
    if body.level != row["level"] and not (body.level_comment or "").strip():
        raise HTTPException(status_code=400,
                            detail="A-65: ручное изменение уровня риска требует комментария")
    execute(
        "UPDATE risks SET category = ?, description = ?, probability = ?, impact = ?,"
        " measures = ?, owner_person_id = ?, review_date = ?, status = ?, level = ?,"
        " level_comment = ? WHERE id = ?",
        (body.category, body.description, body.probability, body.impact, body.measures,
         body.owner_person_id, body.review_date, body.status, body.level,
         body.level_comment, risk_id))
    audit.record(group_name=audit.GROUP_CARD, object_type="project", object_id=project_id,
                 action="Изменён риск", user_id=actor.id, user_login=actor.login,
                 old_value={"level": row["level"], "status": row["status"]},
                 new_value={"level": body.level, "status": body.status},
                 basis=body.level_comment)
    return {"risk": dict(query_one("SELECT * FROM risks WHERE id = ?", (risk_id,))),
            "project_risk": svc.recompute_risk(project_id)}


# ===========================================================================
#  Материалы (FR-21, A-68)
# ===========================================================================

class EvidenceBody(BaseModel):
    object_type: str = Field(pattern="^(project|milestone|review|result|decision)$")
    object_id: str
    title: str = Field(min_length=3, max_length=300)
    kind: str = Field(default="link", pattern="^(link|file)$")
    url: str | None = Field(default=None, max_length=2000)
    access_level: str = Field(default="internal", pattern="^(internal|restricted|public)$")
    version: int = Field(default=1, ge=1)


@router.get("/materials")
def list_materials(project_id: str, actor: CurrentActor):
    """Материалы объекта. Один материал может использоваться несколькими объектами."""
    rows = query(
        "SELECT * FROM evidences WHERE (object_type = 'project' AND object_id = ?)"
        " OR (object_type = 'milestone' AND object_id IN"
        "     (SELECT id FROM milestones WHERE project_id = ?))"
        " OR (object_type = 'result' AND object_id IN"
        "     (SELECT result_id FROM result_projects WHERE project_id = ?))"
        " ORDER BY uploaded_at DESC", (project_id, project_id, project_id))
    return {"items": [dict(r) for r in rows]}


@router.post("/materials", status_code=201)
def add_material(project_id: str, body: EvidenceBody, actor: CurrentActor):
    """MVP хранит ссылки; защищённые вложения и версии — вторая очередь (FR-21)."""
    _require_project(project_id)
    _require_edit(project_id, actor)
    if body.kind == "link" and not (body.url or "").strip():
        raise HTTPException(status_code=400, detail="Для ссылки нужен адрес URL")
    if body.kind == "file" and not (body.url or "").strip():
        raise HTTPException(status_code=400,
                            detail="Для файла нужно загрузить вложение через /api/uploads")
    eid = new_id()
    execute(
        "INSERT INTO evidences (id, object_type, object_id, title, kind, url,"
        " storage_path, version, access_level, uploaded_by, uploaded_at)"
        " VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
        (eid, body.object_type, body.object_id, body.title, body.kind,
         body.url, body.version, body.access_level, actor.id, now_iso()))
    audit.record(group_name=audit.GROUP_CARD, object_type=body.object_type,
                 object_id=body.object_id, action="Добавлен материал",
                 user_id=actor.id, user_login=actor.login,
                 new_value={"title": body.title, "kind": body.kind,
                            "access_level": body.access_level})
    return dict(query_one("SELECT * FROM evidences WHERE id = ?", (eid,)))


@router.post("/materials/{evidence_id}/archive", status_code=204)
def archive_material(project_id: str, evidence_id: str, actor: CurrentActor):
    _require_project(project_id)
    _require_edit(project_id, actor)
    execute("UPDATE evidences SET archived_at = ?, superseded_at = ? WHERE id = ?",
            (now_iso(), now_iso(), evidence_id))
    audit.record(group_name=audit.GROUP_CARD, object_type="project", object_id=project_id,
                 action="Материал архивирован", user_id=actor.id, user_login=actor.login,
                 old_value={"evidence_id": evidence_id})
    return None