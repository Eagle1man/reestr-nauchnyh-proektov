"""Научные программы (M-01, FR-04) и профили людей (FR-03)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import audit
from ..access import AccessDenied, load_actor
from ..db import execute, query, query_one, scalar
from ..domain.taxonomy import ROLE_PRORECTOR, ROLE_SECRETARY, ROLE_SYSADMIN
from ..utils import new_id, now_iso
from .deps import CurrentActor, Pagination, attach_relations

router = APIRouter(prefix="/api", tags=["Программы и люди"])


# ---------------------------------------------------------------------------
#  Программы
# ---------------------------------------------------------------------------

class ProgramBody(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=300)
    short_title: str | None = Field(default=None, max_length=150)
    description: str | None = None
    criteria: str | None = None
    expected_results: str | None = None
    planned_start: str | None = None
    planned_end: str | None = None
    public_allowed: bool = False


class CuratorBody(BaseModel):
    person_id: str


def _can_manage_programs(actor) -> bool:
    return bool(actor.global_roles & {ROLE_PRORECTOR, ROLE_SECRETARY, ROLE_SYSADMIN})


def _program_dict(row) -> dict:
    program = dict(row)
    program["curators"] = [
        dict(r) for r in query(
            "SELECT p.id, p.full_name, pc.appointed_at FROM program_curators pc"
            " JOIN persons p ON p.id = pc.person_id WHERE pc.program_id = ?"
            " ORDER BY p.full_name", (row["id"],))
    ]
    program["projects_count"] = scalar(
        "SELECT COUNT(*) FROM projects WHERE program_id = ? AND archived_at IS NULL",
        (row["id"],), 0)
    return program


@router.get("/programs")
def list_programs(
    actor: CurrentActor,
    page: Annotated[Pagination, Depends()],
    include_archived: bool = False,
    mine_only: bool = False,
):
    """Список программ. Куратор и выше видят курируемые; остальные — все действующие."""
    where = [] if include_archived else ["p.archived_at IS NULL"]
    params: list = []
    if mine_only and actor.person_id:
        where.append("p.id IN (SELECT program_id FROM program_curators WHERE person_id = ?)")
        params.append(actor.person_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.extend([page.limit, page.offset])
    rows = query(
        f"SELECT p.* FROM programs p {clause} ORDER BY p.title LIMIT ? OFFSET ?",
        tuple(params))
    return {"items": [_program_dict(r) for r in rows],
            "limit": page.limit, "offset": page.offset}


@router.post("/programs", status_code=201)
def create_program(body: ProgramBody, actor: CurrentActor):
    if not _can_manage_programs(actor):
        raise HTTPException(status_code=403,
                            detail="Создание программы: проректор по науке, "
                                   "секретарь или технический администратор")
    if query_one("SELECT id FROM programs WHERE code = ?", (body.code,)):
        raise HTTPException(status_code=409,
                            detail=f"Программа с кодом {body.code} уже существует")
    pid = new_id()
    execute(
        "INSERT INTO programs (id, code, title, short_title, description, criteria,"
        " expected_results, planned_start, planned_end, public_allowed, created_at,"
        " created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pid, body.code, body.title, body.short_title, body.description, body.criteria,
         body.expected_results, body.planned_start, body.planned_end,
         1 if body.public_allowed else 0, now_iso(), actor.id))
    audit.record(group_name=audit.GROUP_ADMIN, object_type="program", object_id=pid,
                 action="Создание научной программы", user_id=actor.id,
                 user_login=actor.login, new_value={"code": body.code, "title": body.title})
    return _program_dict(query_one("SELECT * FROM programs WHERE id = ?", (pid,)))


@router.patch("/programs/{program_id}")
def update_program(program_id: str, body: ProgramBody, actor: CurrentActor):
    if not _can_manage_programs(actor):
        raise HTTPException(status_code=403, detail="Недостаточно прав на изменение программы")
    current = query_one("SELECT * FROM programs WHERE id = ?", (program_id,))
    if current is None:
        raise HTTPException(status_code=404, detail="Программа не найдена")
    fields = body.model_dump(exclude_unset=True)
    fields["public_allowed"] = 1 if body.public_allowed else 0
    changes = {}
    for key, value in fields.items():
        if current[key] != value:
            changes[key] = (current[key], value)
    if changes:
        execute(
            "UPDATE programs SET " + ", ".join(f"{k} = ?" for k in changes) + " WHERE id = ?",
            tuple(v for _, v in changes.values()) + (program_id,))
        audit.record_change(group_name=audit.GROUP_ADMIN, object_type="program",
                            object_id=program_id, action="Изменение программы",
                            changes=changes, user_id=actor.id, user_login=actor.login)
    return _program_dict(query_one("SELECT * FROM programs WHERE id = ?", (program_id,)))


@router.post("/programs/{program_id}/curators")
def appoint_curator(program_id: str, body: CuratorBody, actor: CurrentActor):
    """FR-04: назначение куратора программы."""
    if not _can_manage_programs(actor):
        raise HTTPException(status_code=403, detail="Назначение куратора: проректор, "
                                                   "секретарь или администратор")
    if query_one("SELECT id FROM programs WHERE id = ?", (program_id,)) is None:
        raise HTTPException(status_code=404, detail="Программа не найдена")
    if query_one("SELECT id FROM persons WHERE id = ? AND archived_at IS NULL",
                 (body.person_id,)) is None:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    execute(
        "INSERT OR REPLACE INTO program_curators (program_id, person_id, appointed_at,"
        " appointed_by) VALUES (?, ?, ?, ?)",
        (program_id, body.person_id, now_iso(), actor.id))
    audit.record(group_name=audit.GROUP_ADMIN, object_type="program",
                 object_id=program_id, action="Назначение куратора программы",
                 user_id=actor.id, user_login=actor.login,
                 new_value={"person_id": body.person_id})
    return _program_dict(query_one("SELECT * FROM programs WHERE id = ?", (program_id,)))


@router.delete("/programs/{program_id}/curators/{person_id}", status_code=204)
def remove_curator(program_id: str, person_id: str, actor: CurrentActor):
    if not _can_manage_programs(actor):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    execute("DELETE FROM program_curators WHERE program_id = ? AND person_id = ?",
            (program_id, person_id))
    audit.record(group_name=audit.GROUP_ADMIN, object_type="program",
                 object_id=program_id, action="Снятие куратора программы",
                 user_id=actor.id, user_login=actor.login, old_value={"person_id": person_id})
    return None


# ---------------------------------------------------------------------------
#  Профили людей
# ---------------------------------------------------------------------------

class PersonBody(BaseModel):
    full_name: str = Field(min_length=2, max_length=300)
    work_place: str | None = Field(default=None, max_length=300)
    position: str | None = Field(default=None, max_length=200)
    academic_degree: str | None = Field(default=None, max_length=100)
    service_contact: str | None = Field(default=None, max_length=200)
    category: str = Field(default="staff", pattern="^(staff|student|aspirant)$")
    external_id: str | None = Field(default=None, max_length=100)


@router.get("/persons")
def list_persons(
    actor: CurrentActor,
    page: Annotated[Pagination, Depends()],
    q: str | None = Query(default=None, max_length=200),
    category: str | None = None,
):
    """Справочник людей для выбора в полях карточки (однократный ввод, FR-03)."""
    where = ["archived_at IS NULL"]
    params: list = []
    if q:
        where.append("(full_name LIKE ? OR service_contact LIKE ? OR position LIKE ?)")
        params.extend([f"%{q}%"] * 3)
    if category:
        where.append("category = ?")
        params.append(category)
    params.extend([page.limit, page.offset])
    rows = query(
        f"SELECT id, full_name, work_place, position, academic_degree,"
        f" service_contact, category FROM persons WHERE {' AND '.join(where)}"
        f" ORDER BY full_name LIMIT ? OFFSET ?", tuple(params))
    return {"items": [dict(r) for r in rows], "limit": page.limit, "offset": page.offset}


@router.post("/persons", status_code=201)
def create_person(body: PersonBody, actor: CurrentActor):
    """Один человек — один профиль (FR-03, п.6.1 п.2).

    Сопоставление идёт по служебному адресу и внешнему идентификатору; при
    совпадении новый профиль не создаётся, а возвращается существующий.
    """
    existing = query_one(
        "SELECT * FROM persons WHERE (service_contact IS NOT NULL AND service_contact = ?)"
        " OR (external_id IS NOT NULL AND external_id = ?)",
        (body.service_contact, body.external_id)) if (
        body.service_contact or body.external_id) else None
    if existing is not None:
        return {**dict(existing), "merged": True,
                "note": "Профиль уже существует — повторный ввод не создал дубль (FR-03)"}
    pid = new_id()
    execute(
        "INSERT INTO persons (id, full_name, work_place, position, academic_degree,"
        " service_contact, category, external_id, created_at, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pid, body.full_name, body.work_place, body.position, body.academic_degree,
         body.service_contact, body.category, body.external_id, now_iso(), actor.id))
    return dict(query_one("SELECT * FROM persons WHERE id = ?", (pid,)))


@router.get("/persons/{person_id}")
def get_person(person_id: str, actor: CurrentActor):
    row = query_one("SELECT * FROM persons WHERE id = ?", (person_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    person = dict(row)
    person["projects"] = [dict(r) for r in query(
        "SELECT p.id, p.code, p.title, pp.role FROM participations pp"
        " JOIN projects p ON p.id = pp.project_id WHERE pp.person_id = ?"
        " AND pp.archived_at IS NULL ORDER BY p.code", (person_id,))]
    person["results"] = [dict(r) for r in query(
        "SELECT r.id, r.code, r.title FROM results r"
        " WHERE r.authors LIKE ? ORDER BY r.code", (f'%"{person_id}"%',))]
    return person