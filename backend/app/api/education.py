"""Диссертации и задачи обучающихся (M-05, FR-19, FR-20; A-66, A-67).

Задача обучающегося — 6–16 недель (FR-20). Диссертация связывает аспиранта,
тему, научного руководителя, этапы, проекты и результаты (FR-19).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import audit
from ..access import ROLE_PRORECTOR, ROLE_SECRETARY, ROLE_SYSADMIN, attach_relations
from ..db import execute, query, query_one, scalar
from ..utils import fmt_date, new_id, now_iso, to_date, working_days_between

router = APIRouter(prefix="/api", tags=["Аспирантура и обучающиеся"])

DISSERTATION_STATUS_TITLES = {
    "in_progress": "В работе", "admitted_to_defense": "Допущен к защите",
    "defense_scheduled": "Назначена защита", "defended": "Защищена",
    "negative": "Отрицательное решение", "revision": "Требует доработки",
}
DISSERTATION_STATUSES = tuple(DISSERTATION_STATUS_TITLES)

TASK_STATUS_TITLES = {
    "planned": "Запланирована", "in_progress": "В работе",
    "done": "Выполнена", "cancelled": "Отменена",
}
TASK_STATUSES = tuple(TASK_STATUS_TITLES)

MIN_TASK_WEEKS = 6
MAX_TASK_WEEKS = 16


# ===========================================================================
#  Диссертации (FR-19, A-67)
# ===========================================================================

class DissertationBody(BaseModel):
    aspirant_person_id: str
    topic: str = Field(min_length=5, max_length=1000)
    specialty: str = Field(min_length=3, max_length=300)
    supervisor_person_id: str | None = None
    defense_year: int | None = Field(default=None, ge=1990, le=2100)
    status: str = Field(default="in_progress",
                        pattern="^(in_progress|admitted_to_defense|defense_scheduled|"
                                "defended|negative|revision)$")
    project_ids: list[str] = Field(default_factory=list)


class DissertationStageBody(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    planned_date: str | None = None
    actual_date: str | None = None
    status: str = Field(default="planned", pattern="^(planned|in_progress|done)$")


def _dissertation_dict(row) -> dict:
    item = dict(row)
    item["status_title"] = DISSERTATION_STATUS_TITLES.get(item["status"])
    item["aspirant_name"] = scalar(
        "SELECT full_name FROM persons WHERE id = ?", (item["aspirant_person_id"],), None)
    item["supervisor_name"] = scalar(
        "SELECT full_name FROM persons WHERE id = ?",
        (item.get("supervisor_person_id"),), None)
    item["projects"] = [dict(r) for r in query(
        "SELECT p.id, p.code, p.title FROM dissertation_projects dp"
        " JOIN projects p ON p.id = dp.project_id WHERE dp.dissertation_id = ?"
        " ORDER BY p.code", (item["id"],))]
    item["stages"] = [dict(r) for r in query(
        "SELECT * FROM dissertation_stages WHERE dissertation_id = ?"
        " ORDER BY COALESCE(planned_date, '9999')", (item["id"],))]
    return item


@router.get("/dissertations")
def list_dissertations(status: str | None = None, q: str | None = Query(default=None,
                                                                    max_length=200)):
    where = ["d.archived_at IS NULL"]
    params: list = []
    if status:
        where.append("d.status = ?")
        params.append(status)
    if q:
        where.append("(d.topic LIKE ? OR p.full_name LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    rows = query(
        "SELECT d.* FROM dissertations d"
        " LEFT JOIN persons p ON p.id = d.aspirant_person_id"
        f" WHERE {' AND '.join(where)} ORDER BY d.defense_year DESC, d.topic",
        tuple(params))
    return {"items": [_dissertation_dict(r) for r in rows],
            "statuses": [{"code": k, "title": v}
                         for k, v in DISSERTATION_STATUS_TITLES.items()]}


@router.post("/dissertations", status_code=201)
def create_dissertation(body: DissertationBody, actor):
    """FR-19: связь аспиранта, темы, научного руководителя, этапов, проектов."""
    if query_one("SELECT id FROM persons WHERE id = ? AND archived_at IS NULL",
                 (body.aspirant_person_id,)) is None:
        raise HTTPException(status_code=404, detail="Профиль аспиранта не найден")
    if query_one("SELECT id FROM dissertations WHERE aspirant_person_id = ?"
                 " AND archived_at IS NULL", (body.aspirant_person_id,)):
        raise HTTPException(status_code=409,
                            detail="A-67: одна запись на одну диссертацию")
    if body.supervisor_person_id and query_one(
            "SELECT id FROM persons WHERE id = ? AND archived_at IS NULL",
            (body.supervisor_person_id,)) is None:
        raise HTTPException(status_code=404,
                            detail="Профиль научного руководителя не найден")
    did = new_id()
    execute(
        "INSERT INTO dissertations (id, aspirant_person_id, topic, specialty,"
        " supervisor_person_id, defense_year, status, created_at, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (did, body.aspirant_person_id, body.topic, body.specialty,
         body.supervisor_person_id, body.defense_year, body.status, now_iso(), actor.id))
    for pid in dict.fromkeys(body.project_ids):
        if query_one("SELECT id FROM projects WHERE id = ? AND archived_at IS NULL",
                     (pid,)) is None:
            raise HTTPException(status_code=404, detail=f"Проект {pid} не найден")
        execute("INSERT OR IGNORE INTO dissertation_projects (dissertation_id, project_id)"
                " VALUES (?, ?)", (did, pid))
    audit.record(group_name=audit.GROUP_CARD, object_type="dissertation", object_id=did,
                 action="Регистрация диссертации", user_id=actor.id, user_login=actor.login,
                 new_value={"topic": body.topic, "status": body.status})
    return _dissertation_dict(query_one("SELECT * FROM dissertations WHERE id = ?", (did,)))


@router.post("/dissertations/{dissertation_id}/projects")
def link_dissertation_project(dissertation_id: str, project_id: str, actor):
    if query_one("SELECT id FROM dissertations WHERE id = ?", (dissertation_id,)) is None:
        raise HTTPException(status_code=404, detail="Диссертация не найдена")
    if query_one("SELECT id FROM projects WHERE id = ? AND archived_at IS NULL",
                 (project_id,)) is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    execute("INSERT OR IGNORE INTO dissertation_projects (dissertation_id, project_id)"
            " VALUES (?, ?)", (dissertation_id, project_id))
    audit.record(group_name=audit.GROUP_CARD, object_type="dissertation",
                 object_id=dissertation_id, action="Связывание с проектом",
                 user_id=actor.id, user_login=actor.login, new_value={"project_id": project_id})
    return _dissertation_dict(query_one("SELECT * FROM dissertations WHERE id = ?",
                                       (dissertation_id,)))


@router.post("/dissertations/{dissertation_id}/stages", status_code=201)
def add_dissertation_stage(dissertation_id: str, body: DissertationStageBody, actor):
    if query_one("SELECT id FROM dissertations WHERE id = ?", (dissertation_id,)) is None:
        raise HTTPException(status_code=404, detail="Диссертация не найдена")
    sid = new_id()
    execute("INSERT INTO dissertation_stages (id, dissertation_id, title, planned_date,"
            " actual_date, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, dissertation_id, body.title, body.planned_date, body.actual_date,
             body.status, now_iso()))
    return dict(query_one("SELECT * FROM dissertation_stages WHERE id = ?", (sid,)))


# ===========================================================================
#  Задачи обучающихся (FR-20, A-66)
# ===========================================================================

class StudentTaskBody(BaseModel):
    project_id: str
    assignment: str = Field(min_length=5, max_length=2000)
    student_person_id: str
    supervisor_person_id: str
    planned_start: str
    planned_end: str
    planned_result: str | None = Field(default=None, max_length=2000)
    actual_result: str | None = Field(default=None, max_length=2000)
    dissertation_id: str | None = None
    is_public: bool = False


class StudentTaskUpdate(BaseModel):
    assignment: str | None = Field(default=None, min_length=5, max_length=2000)
    supervisor_person_id: str | None = None
    planned_end: str | None = None
    actual_result: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None,
                               pattern="^(planned|in_progress|done|cancelled)$")
    is_public: bool | None = None


def _task_dict(row) -> dict:
    task = dict(row)
    task["status_title"] = TASK_STATUS_TITLES.get(task["status"])
    task["planned_start_fmt"] = fmt_date(task.get("planned_start"))
    task["planned_end_fmt"] = fmt_date(task.get("planned_end"))
    task["student_name"] = scalar("SELECT full_name FROM persons WHERE id = ?",
                                  (task["student_person_id"],), None)
    task["supervisor_name"] = scalar("SELECT full_name FROM persons WHERE id = ?",
                                     (task.get("supervisor_person_id"),), None)
    task["project_code"] = scalar("SELECT code FROM projects WHERE id = ?",
                                  (task["project_id"],), None)
    start, end = to_date(task["planned_start"]), to_date(task["planned_end"])
    if start and end:
        task["duration_calendar_days"] = (end - start).days
        task["duration_weeks"] = round(task["duration_calendar_days"] / 7, 1)
    else:
        task["duration_calendar_days"] = None
        task["duration_weeks"] = None
    task["overdue"] = bool(
        task["status"] not in ("done", "cancelled")
        and task["planned_end"] and task["planned_end"] < date.today().isoformat())
    return task


@router.get("/student-tasks")
def list_student_tasks(project_id: str | None = None, status: str | None = None,
                       student_person_id: str | None = None,
                       public_only: bool = False):
    where = ["st.archived_at IS NULL"]
    params: list = []
    if project_id:
        where.append("st.project_id = ?")
        params.append(project_id)
    if status:
        where.append("st.status = ?")
        params.append(status)
    if student_person_id:
        where.append("st.student_person_id = ?")
        params.append(student_person_id)
    if public_only:
        where.append("st.is_public = 1")
    rows = query(
        f"SELECT st.* FROM student_tasks st WHERE {' AND '.join(where)}"
        f" ORDER BY st.planned_end", tuple(params))
    return {"items": [_task_dict(r) for r in rows],
            "statuses": [{"code": k, "title": v} for k, v in TASK_STATUS_TITLES.items()]}


@router.post("/student-tasks", status_code=201)
def create_student_task(body: StudentTaskBody, actor):
    """FR-20: задача 6–16 недель, исполнитель, руководитель, срок и результат.

    Одна запись на одну задачу (A-66) — повторная регистрация отклоняется.
    """
    problems: list[str] = []
    if query_one("SELECT id FROM projects WHERE id = ? AND archived_at IS NULL",
                 (body.project_id,)) is None:
        problems.append("Проект не найден")
    student = query_one("SELECT id, category FROM persons WHERE id = ?"
                        " AND archived_at IS NULL", (body.student_person_id,))
    if student is None:
        problems.append("Профиль обучающегося не найден")
    elif student["category"] not in ("student", "aspirant"):
        problems.append("Исполнитель должен быть обучающимся или аспирантом "
                        "(FR-20, A-66)")
    if query_one("SELECT id FROM persons WHERE id = ? AND archived_at IS NULL",
                 (body.supervisor_person_id,)) is None:
        problems.append("Профиль руководителя задачи не найден")

    start, end = to_date(body.planned_start), to_date(body.planned_end)
    if start is None or end is None:
        problems.append("Сроки задачи указаны в формате ГГГГ-ММ-ДД")
    elif end <= start:
        problems.append("Дата завершения должна быть позже даты начала")
    else:
        weeks = (end - start).days / 7
        if not (MIN_TASK_WEEKS <= weeks <= MAX_TASK_WEEKS):
            problems.append(
                f"FR-20: продолжительность задачи обучающегося — от {MIN_TASK_WEEKS} "
                f"до {MAX_TASK_WEEKS} недель, указано {weeks:.1f}")
    if problems:
        raise HTTPException(status_code=400,
                            detail={"error": "Проверка не пройдена", "problems": problems})

    duplicate = query_one(
        "SELECT id FROM student_tasks WHERE project_id = ? AND student_person_id = ?"
        " AND assignment = ? AND archived_at IS NULL",
        (body.project_id, body.student_person_id, body.assignment))
    if duplicate:
        raise HTTPException(status_code=409,
                            detail="A-66: такая задача уже зарегистрирована — "
                                   "одна запись на одну задачу")

    tid = new_id()
    execute(
        "INSERT INTO student_tasks (id, project_id, dissertation_id, assignment,"
        " student_person_id, supervisor_person_id, planned_start, planned_end,"
        " planned_result, actual_result, status, is_public, created_at, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?)",
        (tid, body.project_id, body.dissertation_id, body.assignment,
         body.student_person_id, body.supervisor_person_id, body.planned_start,
         body.planned_end, body.planned_result, body.actual_result,
         1 if body.is_public else 0, now_iso(), actor.id))
    audit.record(group_name=audit.GROUP_CARD, object_type="student_task", object_id=tid,
                 action="Регистрация задачи обучающегося", user_id=actor.id,
                 user_login=actor.login,
                 new_value={"project_id": body.project_id,
                            "duration_weeks": round((end - start).days / 7, 1)},
                 basis="FR-20 задача 6–16 недель")
    return _task_dict(query_one("SELECT * FROM student_tasks WHERE id = ?", (tid,)))


@router.patch("/student-tasks/{task_id}")
def update_student_task(task_id: str, body: StudentTaskUpdate, actor):
    current = query_one("SELECT * FROM student_tasks WHERE id = ?", (task_id,))
    if current is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    current = dict(current)
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="Нет полей для изменения")
    if data.get("planned_end"):
        start = to_date(current["planned_start"])
        end = to_date(data["planned_end"])
        if start and end:
            weeks = (end - start).days / 7
            if not (MIN_TASK_WEEKS <= weeks <= MAX_TASK_WEEKS):
                raise HTTPException(
                    status_code=400,
                    detail=f"FR-20: срок задачи должен соответствовать "
                           f"{MIN_TASK_WEEKS}–{MAX_TASK_WEEKS} неделям")
    if data.get("status") == "done" and not (
            data.get("actual_result", current.get("actual_result")) or "").strip():
        raise HTTPException(status_code=400,
                            detail="A-66: у выполненной задачи должен быть фактический "
                                   "результат")
    changes = {k: (current[k], v) for k, v in data.items() if current[k] != v}
    if changes:
        execute("UPDATE student_tasks SET "
                + ", ".join(f"{k} = ?" for k in changes) + " WHERE id = ?",
                tuple(v for _, v in changes.values()) + (task_id,))
        audit.record_change(group_name=audit.GROUP_CARD, object_type="student_task",
                            object_id=task_id, action="Изменение задачи обучающегося",
                            changes=changes, user_id=actor.id, user_login=actor.login)
    return _task_dict(query_one("SELECT * FROM student_tasks WHERE id = ?", (task_id,)))