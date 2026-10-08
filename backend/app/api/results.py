"""Результаты и публикации (M-04, FR-16…FR-18; A-43…A-62).

Ключевые правила ТЗ, которые реализуются здесь:
  * результат — самостоятельная подтверждаемая запись (FR-16);
  * один результат связывается с несколькими проектами и учитывается в общей
    статистике ОДИН раз (FR-17, п.6.1 п.3, ПС-12);
  * публикация проверяется на возможный дубль по DOI, EDN либо сочетанию
    названия, авторов и года (п.6.1 п.4);
  * раздельные стадии публикации A-56 (FR-18);
  * разрешение на публикацию даёт уполномоченное лицо (A-54, п.9.2);
  * снятие с публикации прекращает передачу объекта (FR-34).
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import audit
from ..access import ROLE_PRORECTOR, ROLE_SECRETARY, ROLE_SYSADMIN, attach_relations
from ..db import execute, query, query_one, scalar
from ..services import projects as svc
from ..services.public import result_public_card
from ..utils import fmt_date, new_id, now_iso
from .deps import CurrentActor, Pagination

router = APIRouter(prefix="/api", tags=["Результаты"])

READINESS_TITLES = {
    "planned": "Запланирован", "produced": "Получен", "applied": "Апробирован",
    "accepted": "Принят", "published": "Опубликован", "implemented": "Внедрён",
}
ACCEPTED_STAGES = ("accepted", "published", "implemented")

PUBLICATION_STAGES = ("concept", "reviewing", "submitted", "revision",
                      "accepted", "published")
PUBLICATION_STAGE_TITLES = {
    "concept": "Замысел", "reviewing": "Внутренняя экспертиза", "submitted": "Подана",
    "revision": "Доработка", "accepted": "Принята", "published": "Опубликована",
}
STAGE_ORDER = {s: i for i, s in enumerate(PUBLICATION_STAGES)}

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


class ResultBody(BaseModel):
    result_type: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=3, max_length=500)
    description: str = Field(min_length=5, max_length=1500)
    authors: list[str] = Field(min_length=1)
    readiness_stage: str = Field(
        default="produced",
        pattern="^(planned|produced|applied|accepted|published|implemented)$")
    project_ids: list[str] = Field(min_length=1)
    planned_date: str | None = None
    actual_date: str | None = None
    acceptance_criterion: str = Field(min_length=5, max_length=2000)
    confirmation: str | None = Field(default=None, max_length=2000)
    doi: str | None = Field(default=None, max_length=200)
    edn: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)


class PublicationBody(BaseModel):
    kind: str | None = Field(default=None, max_length=100)
    stage: str = Field(
        pattern="^(concept|reviewing|submitted|revision|accepted|published)$")
    target_venue: str | None = Field(default=None, max_length=300)
    planned_submit_at: str | None = None
    submitted_at: str | None = None
    accepted_at: str | None = None
    published_at: str | None = None
    biblio_volume: str | None = Field(default=None, max_length=100)
    biblio_issue: str | None = Field(default=None, max_length=100)
    biblio_pages: str | None = Field(default=None, max_length=100)


class ResultUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=500)
    description: str | None = Field(default=None, min_length=5, max_length=1500)
    readiness_stage: str | None = None
    planned_date: str | None = None
    actual_date: str | None = None
    acceptance_criterion: str | None = Field(default=None, min_length=5, max_length=2000)
    confirmation: str | None = Field(default=None, max_length=2000)
    doi: str | None = Field(default=None, max_length=200)
    edn: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    version: int | None = None


class ResultPublishBody(BaseModel):
    allow: bool
    reason: str | None = Field(default=None, max_length=2000)


def _author_names(authors_json: str | None) -> list[str]:
    if not authors_json:
        return []
    try:
        ids = json.loads(authors_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(ids, list) or not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = query(f"SELECT full_name FROM persons WHERE id IN ({placeholders})", tuple(ids))
    return [r["full_name"] for r in rows]


def _result_dict(row) -> dict:
    result = dict(row)
    result["authors_names"] = _author_names(result.get("authors"))
    result["projects"] = [dict(r) for r in query(
        "SELECT p.id, p.code, p.title, p.status, p.publish_mode FROM result_projects rp"
        " JOIN projects p ON p.id = rp.project_id WHERE rp.result_id = ?"
        " ORDER BY p.code", (result["id"],))]
    result["readiness_title"] = READINESS_TITLES.get(result["readiness_stage"])
    result["planned_date_fmt"] = fmt_date(result.get("planned_date"))
    result["actual_date_fmt"] = fmt_date(result.get("actual_date"))
    pub = query_one("SELECT * FROM publications WHERE result_id = ?", (result["id"],))
    result["publication"] = dict(pub) if pub else None
    if pub:
        result["publication"]["stage_title"] = PUBLICATION_STAGE_TITLES.get(pub["stage"])
    result["confirmed"] = result.get("review_status") == "accepted"
    return result


def normalize(text: str) -> str:
    return svc.normalize_title(text)


def check_result_duplicates(body: ResultBody, exclude_id: str | None = None) -> list[dict]:
    """П.6.1 п.4: возможный дубль по DOI, EDN либо сочетанию названия, авторов и года."""
    found: list[dict] = []
    year = (body.actual_date or body.planned_date or "")[:4]

    if body.doi and not DOI_RE.match(body.doi):
        found.append({"id": None, "code": None, "title": body.title,
                      "reason": f"DOI «{body.doi}» не соответствует формату"})
    if body.doi:
        for row in query("SELECT id, code, title FROM results WHERE doi = ?"
                         " AND archived_at IS NULL", (body.doi,)):
            if row["id"] != exclude_id:
                found.append({"id": row["id"], "code": row["code"], "title": row["title"],
                              "reason": f"Совпадает DOI {body.doi}"})
    if body.edn:
        for row in query("SELECT id, code, title FROM results WHERE edn = ?"
                         " AND archived_at IS NULL", (body.edn,)):
            if row["id"] != exclude_id and not any(f["id"] == row["id"] for f in found):
                found.append({"id": row["id"], "code": row["code"], "title": row["title"],
                              "reason": f"Совпадает EDN {body.edn}"})

    target = normalize(body.title)
    if target:
        for row in query(
            "SELECT id, code, title, actual_date, authors FROM results"
            " WHERE archived_at IS NULL AND LOWER(title) LIKE ? LIMIT 200",
            (f"%{target[:60]}%",)
        ):
            if row["id"] == exclude_id or normalize(row["title"]) != target:
                continue
            row_year = (row["actual_date"] or "")[:4]
            if row["authors"] == json.dumps(body.authors, ensure_ascii=False) \
                    and row_year and year and row_year == year \
                    and not any(f["id"] == row["id"] for f in found):
                found.append({"id": row["id"], "code": row["code"], "title": row["title"],
                              "reason": "Совпадают название, авторы и год"})
    return found


def _can_edit_result(actor, result_id: str) -> None:
    """Право правки результата: его автор или руководитель связанного проекта."""
    for row in query("SELECT project_id FROM result_projects WHERE result_id = ?",
                     (result_id,)):
        scoped = attach_relations(actor, row["project_id"])
        if scoped.is_leader or scoped.global_roles & {
                ROLE_PRORECTOR, ROLE_SECRETARY, ROLE_SYSADMIN}:
            return
    if actor.person_id and query_one(
        "SELECT 1 FROM results WHERE id = ? AND authors LIKE ?",
        (result_id, f'%"{actor.person_id}"%')):
        return
    raise HTTPException(status_code=403,
                        detail="Правка результата доступна его автору "
                               "или руководителю связанного проекта")


@router.get("/results")
def list_results(
    actor: CurrentActor,
    page: Annotated[Pagination, Depends()],
    q: str | None = Query(default=None, max_length=200),
    result_type: str | None = None,
    readiness_stage: str | None = None,
    project_id: str | None = None,
    year: str | None = Query(default=None, max_length=4),
    public_only: bool = False,
):
    where = ["r.archived_at IS NULL"]
    params: list[Any] = []
    if q:
        where.append("(LOWER(r.title) LIKE ? OR LOWER(r.search_blob) LIKE ? OR r.code LIKE ?)")
        params.extend([f"%{q.lower()}%", f"%{q.lower()}%", f"%{q}%"])
    if result_type:
        where.append("r.result_type = ?")
        params.append(result_type)
    if readiness_stage:
        where.append("r.readiness_stage = ?")
        params.append(readiness_stage)
    if project_id:
        where.append("r.id IN (SELECT result_id FROM result_projects WHERE project_id = ?)")
        params.append(project_id)
    if year:
        where.append("SUBSTR(COALESCE(r.actual_date, r.planned_date), 1, 4) = ?")
        params.append(year)
    if public_only:
        where.append("r.publish_allowed = 1 AND r.is_public = 1")
    clause = f"WHERE {' AND '.join(where)}"
    total = scalar(f"SELECT COUNT(*) FROM results r {clause}", tuple(params), 0)
    rows = query(f"SELECT r.* FROM results r {clause} ORDER BY r.code LIMIT ? OFFSET ?",
                 tuple(params) + (page.limit, page.offset))
    return {"items": [_result_dict(r) for r in rows], "total": total,
            "limit": page.limit, "offset": page.offset}


@router.get("/results/{result_id}")
def get_result(result_id: str, actor: CurrentActor):
    row = query_one("SELECT * FROM results WHERE id = ?", (result_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Результат не найден")
    return _result_dict(row)


@router.post("/results", status_code=201)
def create_result(body: ResultBody, actor: CurrentActor,
                  duplicate_ack: bool = Query(default=False)):
    """Регистрация результата (FR-16). Связь минимум с одним проектом обязательна (A-47)."""
    problems: list[str] = []
    for pid in body.project_ids:
        if query_one("SELECT id FROM projects WHERE id = ? AND archived_at IS NULL",
                     (pid,)) is None:
            problems.append(f"проект {pid} не найден")
    for aid in body.authors:
        if query_one("SELECT id FROM persons WHERE id = ? AND archived_at IS NULL",
                     (aid,)) is None:
            problems.append(f"автор {aid} не найден в справочнике людей")
    if problems:
        raise HTTPException(status_code=400, detail={
            "error": "Однократный ввод: сведения о человеке и проекте выбираются "
                     "из связанных записей, а не перепечатываются",
            "problems": problems})

    duplicates = check_result_duplicates(body)
    if duplicates and not duplicate_ack:
        return {"created": False, "reason": "duplicate_candidates",
                "message": "Возможный дубль результата (п.6.1 п.4). Подтвердите создание "
                           "повторным запросом с ?duplicate_ack=true",
                "duplicates": duplicates}

    if body.readiness_stage in ACCEPTED_STAGES:
        if not body.actual_date:
            problems.append("A-50: фактическая дата обязательна после принятия результата")
        if not (body.confirmation or "").strip():
            problems.append("A-52: подтверждение обязательно для принятого результата")
    if problems:
        raise HTTPException(status_code=400,
                            detail={"error": "Проверка не пройдена", "problems": problems})

    rid = new_id()
    record = {
        "id": rid, "code": svc.next_result_code(), "result_type": body.result_type,
        "title": body.title, "description": body.description,
        "authors": json.dumps(body.authors, ensure_ascii=False),
        "readiness_stage": body.readiness_stage,
        "planned_date": body.planned_date, "actual_date": body.actual_date,
        "acceptance_criterion": body.acceptance_criterion,
        "confirmation": body.confirmation,
        "doi": body.doi, "edn": body.edn, "url": body.url,
        "search_blob": f"{body.title} {body.description}".lower(),
        "created_at": now_iso(), "created_by": actor.id, "updated_at": now_iso(),
    }
    names = list(record)
    execute(
        f"INSERT INTO results ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
        tuple(record[n] for n in names))
    for pid in dict.fromkeys(body.project_ids):
        execute("INSERT OR IGNORE INTO result_projects (result_id, project_id, linked_at,"
                " linked_by) VALUES (?, ?, ?, ?)", (rid, pid, now_iso(), actor.id))
    audit.record(group_name=audit.GROUP_CARD, object_type="result", object_id=rid,
                 action="Регистрация результата", user_id=actor.id, user_login=actor.login,
                 new_value={"code": record["code"], "title": body.title,
                            "projects": len(dict.fromkeys(body.project_ids))})
    out = {"created": True}
    out.update(_result_dict(query_one("SELECT * FROM results WHERE id = ?", (rid,))))
    return out


@router.patch("/results/{result_id}")
def update_result(result_id: str, body: ResultUpdate, actor: CurrentActor):
    current = query_one("SELECT * FROM results WHERE id = ?", (result_id,))
    if current is None:
        raise HTTPException(status_code=404, detail="Результат не найден")
    _can_edit_result(actor, result_id)
    current = dict(current)
    data = body.model_dump(exclude_unset=True)
    version = data.pop("version", None)
    if version is not None and int(version) != int(current["version"]):
        raise HTTPException(
            status_code=409,
            detail=f"Результат изменён после вашего открытия (версия {current['version']}). "
                   f"Обновите и внесите правки заново (FR-32)")
    if not data:
        raise HTTPException(status_code=400, detail="Нет полей для изменения")

    if current["readiness_stage"] in ACCEPTED_STAGES \
            and data.get("readiness_stage") not in (None, current["readiness_stage"]):
        raise HTTPException(status_code=409,
                            detail="Принятый результат нельзя перевести на более раннюю стадию")
    stage = data.get("readiness_stage") or current["readiness_stage"]
    if stage in ACCEPTED_STAGES:
        actual = data.get("actual_date", current["actual_date"])
        confirm = data.get("confirmation", current["confirmation"])
        if not actual:
            raise HTTPException(status_code=400,
                                detail="A-50: фактическая дата обязательна после принятия")
        if not (confirm or "").strip():
            raise HTTPException(status_code=400,
                                detail="A-52: подтверждение обязательно для принятого результата")

    changes = {k: (current[k], v) for k, v in data.items() if current[k] != v}
    if changes:
        execute(
            "UPDATE results SET " + ", ".join(f"{k} = ?" for k in changes)
            + ", updated_at = ?, version = version + 1 WHERE id = ?",
            tuple(v for _, v in changes.values()) + (now_iso(), result_id))
        merged = {**current, **changes}
        execute("UPDATE results SET search_blob = ? WHERE id = ?",
                (f"{merged.get('title', '')} {merged.get('description', '')}".lower(),
                 result_id))
        audit.record_change(group_name=audit.GROUP_CARD, object_type="result",
                            object_id=result_id, action="Изменение результата",
                            changes=changes, user_id=actor.id, user_login=actor.login)
    return _result_dict(query_one("SELECT * FROM results WHERE id = ?", (result_id,)))


@router.post("/results/{result_id}/projects")
def link_project(result_id: str, project_id: str, actor: CurrentActor):
    """FR-17: один результат — несколько проектов без двойного счёта (ПС-12)."""
    if query_one("SELECT id FROM results WHERE id = ?", (result_id,)) is None:
        raise HTTPException(status_code=404, detail="Результат не найден")
    if query_one("SELECT id FROM projects WHERE id = ? AND archived_at IS NULL",
                 (project_id,)) is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    if query_one("SELECT 1 FROM result_projects WHERE result_id = ? AND project_id = ?",
                 (result_id, project_id)):
        raise HTTPException(status_code=409, detail="Связь уже существует")
    execute("INSERT INTO result_projects (result_id, project_id, linked_at, linked_by)"
            " VALUES (?, ?, ?, ?)", (result_id, project_id, now_iso(), actor.id))
    audit.record(group_name=audit.GROUP_CARD, object_type="result", object_id=result_id,
                 action="Связывание результата с проектом", user_id=actor.id,
                 user_login=actor.login, new_value={"project_id": project_id},
                 basis="FR-17 один результат — несколько проектов, учёт один раз")
    return _result_dict(query_one("SELECT * FROM results WHERE id = ?", (result_id,)))


@router.post("/results/{result_id}/publish")
def set_result_publish(result_id: str, body: ResultPublishBody, actor: CurrentActor):
    """Разрешение или отзыв разрешения на публикацию (A-54, FR-34, п.9.2)."""
    result = query_one("SELECT * FROM results WHERE id = ?", (result_id,))
    if result is None:
        raise HTTPException(status_code=404, detail="Результат не найден")
    if not (actor.global_roles & {ROLE_PRORECTOR, ROLE_SECRETARY, ROLE_SYSADMIN,
                                  "rector", "council"}):
        raise HTTPException(status_code=403,
                            detail="Разрешение на публикацию даёт проректор, секретарь "
                                   "или куратор программы (п.9.2)")
    result = dict(result)
    if body.allow:
        if result["readiness_stage"] not in ACCEPTED_STAGES:
            raise HTTPException(status_code=409,
                                detail="Публикуется только подтверждённый результат (п.9.1 п.3)")
        if not result["review_id"]:
            raise HTTPException(status_code=409,
                                detail="A-53: без заключения результат не подтверждён")
        # A-33: результат с ограничением публикации или правами не передаётся наружу
        blocked = query_one(
            "SELECT 1 FROM result_projects rp JOIN projects p ON p.id = rp.project_id"
            " WHERE rp.result_id = ? AND p.confidentiality IS NOT NULL"
            " AND TRIM(p.confidentiality) <> ''", (result_id,))
        if blocked:
            raise HTTPException(status_code=409,
                                detail="A-33: результат связан с проектом, имеющим "
                                       "ограничения по конфиденциальности или правам")
        execute("UPDATE results SET publish_allowed = 1, is_public = 1,"
                " publish_allowed_by = ?, publish_allowed_at = ? WHERE id = ?",
                (actor.id, now_iso(), result_id))
        audit.record(group_name=audit.GROUP_PUBLISH, object_type="result",
                     object_id=result_id, action="Разрешение публикации результата",
                     user_id=actor.id, user_login=actor.login,
                     old_value={"publish_allowed": 0}, new_value={"publish_allowed": 1},
                     basis=body.reason)
    else:
        execute("UPDATE results SET publish_allowed = 0, is_public = 0 WHERE id = ?",
                (result_id,))
        audit.record(group_name=audit.GROUP_PUBLISH, object_type="result",
                     object_id=result_id, action="Снятие публикации результата",
                     user_id=actor.id, user_login=actor.login,
                     old_value={"publish_allowed": 1}, new_value={"publish_allowed": 0},
                     basis=body.reason or "отзыв разрешения уполномоченным лицом")
    fresh = dict(query_one("SELECT * FROM results WHERE id = ?", (result_id,)))
    return {"result": _result_dict(fresh), "public_card": result_public_card(fresh)}


@router.put("/results/{result_id}/publication")
def upsert_publication(result_id: str, body: PublicationBody, actor: CurrentActor):
    """Раздельные стадии публикации (FR-18, A-56)."""
    if query_one("SELECT id FROM results WHERE id = ?", (result_id,)) is None:
        raise HTTPException(status_code=404, detail="Результат не найден")
    problems: list[str] = []
    stage = body.stage
    # A-57: целевое издание обязательно с момента подачи
    if STAGE_ORDER[stage] >= STAGE_ORDER["submitted"] and not (body.target_venue or "").strip():
        problems.append("A-57: с момента подачи обязательно целевое издание")
    # A-58: фактическая подача обязательна со стадии «подана»
    if STAGE_ORDER[stage] >= STAGE_ORDER["submitted"] and not body.submitted_at:
        problems.append("A-58: фактическая дата подачи обязательна со стадии «подана»")
    if STAGE_ORDER[stage] >= STAGE_ORDER["accepted"] and not body.accepted_at:
        problems.append("A-59: дата принятия обязательна для стадии «принята»")
    if STAGE_ORDER[stage] >= STAGE_ORDER["published"] and not body.published_at:
        problems.append("A-59: дата публикации обязательна для стадии «опубликована»")
    if problems:
        raise HTTPException(status_code=400,
                            detail={"error": "Проверка стадии не пройдена",
                                    "problems": problems})

    existing = query_one("SELECT result_id FROM publications WHERE result_id = ?",
                         (result_id,))
    params = (body.kind, stage, body.target_venue, body.planned_submit_at,
              body.submitted_at, body.accepted_at, body.published_at,
              body.biblio_volume, body.biblio_issue, body.biblio_pages, now_iso())
    if existing is None:
        execute(
            "INSERT INTO publications (kind, stage, target_venue, planned_submit_at,"
            " submitted_at, accepted_at, published_at, biblio_volume, biblio_issue,"
            " biblio_pages, updated_at, result_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", params + (result_id,))
    else:
        execute(
            "UPDATE publications SET kind = ?, stage = ?, target_venue = ?,"
            " planned_submit_at = ?, submitted_at = ?, accepted_at = ?, published_at = ?,"
            " biblio_volume = ?, biblio_issue = ?, biblio_pages = ?, updated_at = ?"
            " WHERE result_id = ?", params + (result_id,))
    if stage == "published":
        execute("UPDATE results SET readiness_stage = 'published',"
                " actual_date = COALESCE(?, actual_date), updated_at = ? WHERE id = ?",
                (body.published_at, now_iso(), result_id))
    audit.record(group_name=audit.GROUP_CARD, object_type="result", object_id=result_id,
                 action=f"Стадия публикации: {stage}", user_id=actor.id,
                 user_login=actor.login, new_value={"stage": stage})
    return _result_dict(query_one("SELECT * FROM results WHERE id = ?", (result_id,)))