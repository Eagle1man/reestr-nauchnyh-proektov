"""Карточка проекта: создание, чтение, правка, переходы, поиск (FR-05…FR-13, FR-25)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .. import audit
from ..access import AccessDenied, attach_relations, can_edit_card, can_view_project
from ..db import execute, query, query_one
from ..domain.taxonomy import (
    ACTIVE_STATUSES, FULL_ROUTE_TITLES, PUBLISH_MODES, ROUTES, RISK_TITLES,
    ROUTE_RULE, STATUS_TITLES, STATUSES,
)
from ..domain.validation import FIELD_DICTIONARY
from ..services import projects as svc
from ..utils import fmt_date, now_iso
from .deps import CurrentActor, Pagination, attach_relations, forbidden

router = APIRouter(prefix="/api/projects", tags=["Проекты"])


class ProjectCreate(BaseModel):
    program_id: str
    title: str = Field(min_length=3, max_length=500)
    short_title: str | None = Field(default=None, max_length=150)
    public_annotation: str | None = Field(default=None, max_length=1000)
    theme_link: str | None = None
    publish_mode: str = Field(default="none", pattern="^(none|project|results|all)$")
    planned_start: str | None = None
    planned_end: str | None = None
    problem: str | None = Field(default=None, max_length=2000)
    question: str | None = Field(default=None, max_length=1000)
    goal: str | None = Field(default=None, max_length=700)
    methods: Any = None
    data_basis: str | None = None
    planned_result_type: str | None = None
    result_criteria: Any = None
    flag_external_funding: bool = False
    flag_partner: bool = False
    flag_personal_data: bool = False
    flag_human_subjects: bool = False
    flag_ethics_required: bool = False
    flag_extra_resources: bool = False
    flag_critical_infra: bool = False
    flag_high_risk: bool = False
    flag_external_product: bool = False
    flag_confidential: bool = False
    flag_ip_restricted: bool = False


class ProjectUpdate(BaseModel):
    version: int | None = None
    title: str | None = Field(default=None, max_length=500)
    short_title: str | None = Field(default=None, max_length=150)
    public_annotation: str | None = Field(default=None, max_length=1000)
    theme_link: str | None = None
    publish_mode: str | None = Field(default=None, pattern="^(none|project|results|all)$")
    planned_start: str | None = None
    planned_end: str | None = None
    problem: str | None = Field(default=None, max_length=2000)
    question: str | None = Field(default=None, max_length=1000)
    goal: str | None = Field(default=None, max_length=700)
    tasks: Any = None
    research_object: str | None = Field(default=None, max_length=500)
    research_subject: str | None = Field(default=None, max_length=500)
    methods: Any = None
    methods_note: str | None = None
    data_basis: str | None = None
    planned_result_type: str | None = None
    planned_result_note: str | None = None
    result_criteria: Any = None
    novelty: str | None = Field(default=None, max_length=1500)
    applicability: str | None = Field(default=None, max_length=1500)
    limitations: str | None = Field(default=None, max_length=1000)
    personal_data: bool | None = None
    personal_data_note: str | None = None
    human_subjects: bool | None = None
    human_subjects_note: str | None = None
    legal_basis_status: str | None = None
    legal_basis_link: str | None = None
    confidentiality: str | None = None
    ip_note: str | None = None
    resource_request: Any = None
    flag_external_funding: bool | None = None
    flag_partner: bool | None = None
    flag_personal_data: bool | None = None
    flag_human_subjects: bool | None = None
    flag_ethics_required: bool | None = None
    flag_extra_resources: bool | None = None
    flag_critical_infra: bool | None = None
    flag_high_risk: bool | None = None
    flag_external_product: bool | None = None
    flag_confidential: bool | None = None
    flag_ip_restricted: bool | None = None


class TransitionBody(BaseModel):
    action: str = Field(min_length=1, max_length=60)
    reason: str | None = Field(default=None, max_length=4000)


class RouteBody(BaseModel):
    route: str = Field(pattern="^(simplified|full)$")
    reason: str | None = Field(default=None, max_length=4000)


class RiskBody(BaseModel):
    level: str = Field(pattern="^(green|yellow|red)$")
    comment: str | None = Field(default=None, max_length=4000)


class LeaderBody(BaseModel):
    person_id: str


class PublishBody(BaseModel):
    publish_mode: str = Field(pattern="^(none|project|results|all)$")


# ---------------------------------------------------------------------------
#  Справочник для интерфейса
# ---------------------------------------------------------------------------

@router.get("/taxonomy")
def taxonomy(actor: CurrentActor):
    """Статусы, маршруты, признаки T-01…T-06, режимы публикации, роли."""
    return {
        "statuses": [{"code": k, **v} for k, v in STATUSES.items()],
        "routes": ROUTES,
        "full_route_triggers": [
            {"code": code, **spec} for code, spec in FULL_ROUTE_TITLES.items()
        ],
        "route_rule": ROUTE_RULE,
        "publish_modes": PUBLISH_MODES,
        "risk_levels": RISK_TITLES,
        "active_statuses": list(ACTIVE_STATUSES),
        "field_dictionary": [
            {"code": c, **m} for c, m in sorted(FIELD_DICTIONARY.items())
        ],
    }


# ---------------------------------------------------------------------------
#  FR-08: поиск дублей до создания
# ---------------------------------------------------------------------------

@router.get("/duplicates")
def duplicates(
    actor: CurrentActor,
    title: Annotated[str, Query(min_length=2, max_length=500)],
    program_id: str | None = None,
    exclude_id: str | None = None,
):
    """Похожие проекты показываются ДО создания карточки (FR-08).

    Решение о продолжении фиксируется: клиент затем передаёт флаг
    duplicate_ack, и факт отражается в журнале.
    """
    found = svc.find_duplicates(title, exclude_id=exclude_id, program_id=program_id)
    return {
        "title": title,
        "items": [
            {
                "id": c.id, "code": c.code, "title": c.title,
                "short_title": c.short_title, "status": c.status,
                "status_title": c.status_title, "similarity": c.similarity,
                "reason": c.reason,
            }
            for c in found
        ],
        "has_exact": any(c.similarity >= 1.0 for c in found),
        "decision_required": bool(found),
    }


# ---------------------------------------------------------------------------
#  FR-25: поиск и фильтры
# ---------------------------------------------------------------------------

@router.get("")
def list_projects(
    actor: CurrentActor,
    page: Annotated[Pagination, Depends()],
    q: str | None = Query(default=None, max_length=200, description="Поиск по названию, проблеме, цели"),
    program_id: str | None = None,
    route: str | None = None,
    status: str | None = None,
    risk_level: str | None = None,
    leader_person_id: str | None = None,
    result_type: str | None = Query(default=None, description="Вид результата"),
    planned_from: str | None = None,
    planned_to: str | None = None,
    active_only: bool = False,
    include_archived: bool = False,
    overdue_only: bool = False,
    order_by: str = Query(default="updated_at",
                          pattern="^(updated_at|created_at|code|planned_end|risk_level)$"),
):
    """Список проектов с фильтрами ТЗ (FR-25).

    ПС-14: показываются только соответствующие записи. Область видимости
    ограничивается правами пользователя (FR-02) — не управленческая роль
    видит только свои проекты.
    """
    from ..access import visible_projects_clause

    where: list[str] = []
    params: list[Any] = []

    if not include_archived:
        where.append("p.archived_at IS NULL")
    if q:
        where.append("(p.search_blob LIKE ? OR p.code LIKE ?)")
        params.extend([f"%{q.lower()}%", f"%{q}%"])
    if program_id:
        where.append("p.program_id = ?")
        params.append(program_id)
    if route:
        where.append("p.route = ?")
        params.append(route)
    if status:
        where.append("p.status = ?")
        params.append(status)
    if risk_level:
        where.append("p.risk_level = ?")
        params.append(risk_level)
    if leader_person_id:
        where.append("p.leader_person_id = ?")
        params.append(leader_person_id)
    if active_only:
        where.append(f"p.status IN ({','.join('?' * len(ACTIVE_STATUSES))})")
        params.extend(ACTIVE_STATUSES)
    if planned_from:
        where.append("p.planned_end >= ?")
        params.append(planned_from)
    if planned_to:
        where.append("p.planned_start <= ?")
        params.append(planned_to)
    if overdue_only:
        where.append(
            "EXISTS (SELECT 1 FROM milestones m WHERE m.project_id = p.id"
            " AND m.archived_at IS NULL AND m.status NOT IN ('done','cancelled')"
            " AND m.planned_date < date('now'))")
    if result_type:
        where.append(
            "EXISTS (SELECT 1 FROM result_projects rp JOIN results r ON r.id = rp.result_id"
            " WHERE rp.project_id = p.id AND r.result_type = ?)")
        params.append(result_type)

    vis_clause, _ = visible_projects_clause(actor, params)
    where.append(vis_clause)

    order_sql = {
        "updated_at": "p.updated_at DESC",
        "created_at": "p.created_at DESC",
        "code": "p.code",
        "planned_end": "p.planned_end",
        "risk_level": "CASE p.risk_level WHEN 'red' THEN 0 WHEN 'yellow' THEN 1"
                      " ELSE 2 END, p.code",
    }[order_by]

    clause = f"WHERE {' AND '.join(where)}" if where else ""

    rows = query(
        f"SELECT p.id, p.code, p.title, p.short_title, p.status, p.route, p.risk_level,"
        f" p.program_id, p.leader_person_id, p.planned_start, p.planned_end,"
        f" p.publish_mode, p.archived_at, p.updated_at, pr.short_title AS program_title,"
        f" pe.full_name AS leader_name,"
        f" (SELECT COUNT(*) FROM milestones m WHERE m.project_id = p.id"
        f"  AND m.archived_at IS NULL AND m.status = 'overdue') AS overdue_count"
        f" FROM projects p"
        f" LEFT JOIN programs pr ON pr.id = p.program_id"
        f" LEFT JOIN persons pe ON pe.id = p.leader_person_id"
        f" {clause} ORDER BY {order_sql} LIMIT ? OFFSET ?",
        tuple(params) + (page.limit, page.offset))

    from ..db import scalar as _scalar
    total = _scalar(f"SELECT COUNT(*) FROM projects p {clause}", tuple(params), 0)

    items = []
    for row in rows:
        item = dict(row)
        item["status_title"] = STATUS_TITLES.get(item["status"], item["status"])
        item["route_title"] = ROUTES.get(item["route"], item["route"])
        item["risk_title"] = RISK_TITLES.get(item["risk_level"], item["risk_level"])
        item["planned_start_fmt"] = fmt_date(item.get("planned_start"))
        item["planned_end_fmt"] = fmt_date(item.get("planned_end"))
        items.append(item)

    return {
        "items": items, "total": total,
        "limit": page.limit, "offset": page.offset,
        "filters": {k: v for k, v in {
            "q": q, "program_id": program_id, "route": route, "status": status,
            "risk_level": risk_level, "leader_person_id": leader_person_id,
            "result_type": result_type, "planned_from": planned_from,
            "planned_to": planned_to, "active_only": active_only,
            "overdue_only": overdue_only, "order_by": order_by,
        }.items() if v not in (None, "", False)},
    }


# ---------------------------------------------------------------------------
#  Карточка
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_project(body: ProjectCreate, request_body_actor: CurrentActor,
                   duplicate_ack: bool = Query(default=False,
                                               description="Фиксация решения о дубле")):
    """Создание карточки проекта (FR-05) с автонумерацией (FR-06)."""
    actor = request_body_actor
    payload = body.model_dump()
    duplicates_found = svc.find_duplicates(body.title, program_id=body.program_id)
    if duplicates_found and not duplicate_ack:
        return {
            "created": False,
            "reason": "duplicate_candidates",
            "message": "Найдены похожие проекты. Подтвердите создание, если это другая инициатива (FR-08)",
            "duplicates": [
                {"id": c.id, "code": c.code, "title": c.title,
                 "similarity": c.similarity, "reason": c.reason}
                for c in duplicates_found
            ],
            "hint": "Повторите запрос с ?duplicate_ack=true, чтобы зафиксировать решение",
        }
    try:
        result = svc.create_project(payload=payload, user_id=actor.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    audit.record(group_name=audit.GROUP_CARD, object_type="project",
                 object_id=result["id"], action="Создание карточки",
                 user_id=actor.id, user_login=actor.login,
                 new_value={"code": result["code"], "title": body.title},
                 basis="подтверждено при наличии дублей" if duplicate_ack and duplicates_found
                       else None)
    if duplicates_found:
        audit.record(group_name=audit.GROUP_CARD, object_type="project",
                     object_id=result["id"], action="Решение о дубле: продолжить создание",
                     user_id=actor.id, user_login=actor.login,
                     new_value=[c.code for c in duplicates_found])
    card = svc.project_card(result["id"])
    return {"created": True, **result, "card": card,
            "suggested_route": result["route"],
            "route_reasons_detail": [
                {"code": r, "title": FULL_ROUTE_TITLES.get(r, "")}
                for r in result["route_reasons"]
            ]}


@router.get("/{project_id}")
def get_project(project_id: str, actor: CurrentActor):
    """Карточка проекта. ПС-02: каждый видит только разрешённые поля и действия."""
    row = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    scoped = attach_relations(actor, project_id)
    if not can_view_project(scoped, project_id):
        raise HTTPException(status_code=403,
                            detail="Карточка недоступна: нет роли и нет участия в проекте")
    card = svc.project_card(project_id)
    card["status_title"] = STATUS_TITLES.get(card["status"], card["status"])
    card["route_title"] = ROUTES.get(card["route"], card["route"])
    card["risk_title"] = RISK_TITLES.get(card["risk_level"], card["risk_level"])
    card["publish_mode_title"] = PUBLISH_MODES.get(card["publish_mode"], card["publish_mode"])
    card["actions"] = svc.transition_options(project_id, card, scoped)
    card["can_edit"] = can_edit_card(scoped, project_id, card["status"])
    card["full_route_reasons_detail"] = [
        {"code": r, "title": FULL_ROUTE_TITLES.get(r, "")}
        for r in card.get("full_route_reasons", [])
    ]
    card["dates_fmt"] = {
        "planned_start": fmt_date(card.get("planned_start")),
        "planned_end": fmt_date(card.get("planned_end")),
    }
    return card


@router.patch("/{project_id}")
def update_project(project_id: str, body: ProjectUpdate, actor: CurrentActor):
    """Правка карточки (FR-05) с защитой от параллельной перезаписи (FR-32)."""
    row = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    scoped = attach_relations(actor, project_id)
    if not can_edit_card(scoped, project_id, row["status"]):
        raise HTTPException(status_code=403,
                            detail="Правка карточки недоступна вашей роли на этом проекте")
    payload = body.model_dump(exclude_unset=True)
    try:
        result = svc.update_project(project_id=project_id, payload=payload, actor=scoped)
    except svc.VersionConflict as exc:
        # 409: клиент должен перезагрузить карточку, а не перезаписать.
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    if result["changed"]:
        audit.record_change(
            group_name=audit.GROUP_CARD, object_type="project", object_id=project_id,
            action="Изменение карточки",
            changes={c["field"]: (c["old"], c["new"]) for c in result["changed"]},
            user_id=actor.id, user_login=actor.login)
        old_route = row["route"]
        if result.get("suggested_route") and result["suggested_route"] != old_route:
            audit.record(
                group_name=audit.GROUP_CARD, object_type="project", object_id=project_id,
                action="Смена маршрута: система предлагает другой",
                user_id=actor.id, user_login=actor.login,
                old_value=old_route, new_value=result["suggested_route"],
                basis="FR-09 автопредложение по T-01…T-06")
    return {"ok": True, **result, "card": svc.project_card(project_id)}


# ---------------------------------------------------------------------------
#  FR-09: фиксация маршрута уполномоченным лицом
# ---------------------------------------------------------------------------

@router.post("/{project_id}/route")
def fix_route(project_id: str, body: RouteBody, actor: CurrentActor):
    scoped = attach_relations(actor, project_id)
    from ..access import ROLE_CURATOR, ROLE_PRORECTOR, ROLE_RECTOR, ROLE_SECRETARY, REL_LEADER
    if not (scoped.is_leader or scoped.global_roles & {
            ROLE_PRORECTOR, ROLE_RECTOR, ROLE_SECRETARY}) or scoped.is_curator_of_project:
        raise HTTPException(status_code=403,
                            detail="Маршрут фиксирует уполномоченное лицо: проректор, "
                                   "ректор, секретарь или куратор программы")
    try:
        result = svc.set_route(project_id=project_id, route=body.route, actor=scoped,
                               reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if result["changed"]:
        audit.record(group_name=audit.GROUP_CARD, object_type="project",
                     object_id=project_id, action="Смена маршрута",
                     user_id=actor.id, user_login=actor.login,
                     new_value=body.route, basis=body.reason)
    return result


# ---------------------------------------------------------------------------
#  A-10: индикатор риска отдельно от статуса
# ---------------------------------------------------------------------------

@router.post("/{project_id}/risk")
def set_risk(project_id: str, body: RiskBody, actor: CurrentActor):
    from ..access import ROLE_PRORECTOR, ROLE_RECTOR, ROLE_SECRETARY, REL_LEADER
    scoped = attach_relations(actor, project_id)
    if not (scoped.is_leader or scoped.global_roles & {
            ROLE_PRORECTOR, ROLE_RECTOR, ROLE_SECRETARY}):
        raise HTTPException(status_code=403,
                            detail="Индикатор риска меняет руководитель или уполномоченное лицо")
    try:
        result = svc.set_risk_level(project_id=project_id, level=body.level,
                                    comment=body.comment, actor=scoped)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    audit.record(group_name=audit.GROUP_CARD, object_type="project",
                 object_id=project_id, action="Смена индикатора риска",
                 user_id=actor.id, user_login=actor.login,
                 old_value=result["previous"], new_value=body.level, basis=body.comment)
    return result


# ---------------------------------------------------------------------------
#  A-12: руководитель проекта
# ---------------------------------------------------------------------------

@router.post("/{project_id}/leader")
def set_leader(project_id: str, body: LeaderBody, actor: CurrentActor):
    from ..access import ROLE_CURATOR, ROLE_PRORECTOR, ROLE_RECTOR, REL_LEADER
    scoped = attach_relations(actor, project_id)
    if not (scoped.is_leader or scoped.global_roles & {
            ROLE_PRORECTOR, ROLE_RECTOR, ROLE_CURATOR}):
        raise HTTPException(status_code=403,
                            detail="Смена руководителя: текущий руководитель, проректор "
                                   "или куратор программы")
    try:
        result = svc.set_leader(project_id=project_id, person_id=body.person_id, actor=scoped)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    audit.record(group_name=audit.GROUP_CARD, object_type="project",
                 object_id=project_id, action="Смена руководителя",
                 user_id=actor.id, user_login=actor.login,
                 old_value=result["previous"], new_value=body.person_id,
                 basis="A-12 один основной руководитель")
    return result


# ---------------------------------------------------------------------------
#  FR-10: переходы статуса по матрице Приложения Б
# ---------------------------------------------------------------------------

@router.get("/{project_id}/transitions")
def list_transitions(project_id: str, actor: CurrentActor):
    row = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    scoped = attach_relations(actor, project_id)
    return {"status": row["status"],
            "status_title": STATUS_TITLES.get(row["status"], row["status"]),
            "route": row["route"],
            "actions": svc.transition_options(project_id, dict(row), scoped)}


@router.post("/{project_id}/transition")
def transition(project_id: str, body: TransitionBody, actor: CurrentActor):
    """Выполнить переход. Недопустимый переход блокируется с причинами (FR-10, ПС-09)."""
    scoped = attach_relations(actor, project_id)
    if query_one("SELECT id FROM projects WHERE id = ?", (project_id,)) is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    result = svc.apply_transition(project_id=project_id, action=body.action,
                                  actor=scoped, reason=body.reason)
    if not result["applied"]:
        audit.record(group_name=audit.GROUP_CARD, object_type="project",
                     object_id=project_id, action=f"Переход {body.action} заблокирован",
                     user_id=actor.id, user_login=actor.login, outcome="denied",
                     basis="; ".join(result["reasons"]))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Переход невозможен", "reasons": result["reasons"]})
    audit.record(group_name=audit.GROUP_CARD, object_type="project",
                 object_id=project_id, action=f"Смена статуса: {result['title']}",
                 user_id=actor.id, user_login=actor.login,
                 old_value=result["from_status"], new_value=result["to_status"],
                 basis=body.reason)
    if body.reason:
        audit.record(group_name=audit.GROUP_REVIEW_DECISION, object_type="project",
                     object_id=project_id, action="Основание решения", user_id=actor.id,
                     user_login=actor.login, new_value=body.reason)
    result["card"] = svc.project_card(project_id)
    return result


# ---------------------------------------------------------------------------
#  FR-31: архивирование
# ---------------------------------------------------------------------------

class ArchiveBody(BaseModel):
    basis: str = Field(min_length=3, max_length=2000)


@router.post("/{project_id}/archive")
def archive(project_id: str, body: ArchiveBody, actor: CurrentActor):
    from ..access import ROLE_PRORECTOR, ROLE_RECTOR, ROLE_SYSADMIN
    scoped = attach_relations(actor, project_id)
    if not (scoped.global_roles & {ROLE_PRORECTOR, ROLE_RECTOR, ROLE_SYSADMIN}
            or scoped.is_curator_of_project):
        raise HTTPException(status_code=403,
                            detail="Архивирование: проректор, ректор, администратор "
                                   "или куратор программы")
    try:
        result = svc.archive_project(project_id=project_id, actor=scoped, basis=body.basis)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    audit.record(group_name=audit.GROUP_CARD, object_type="project",
                 object_id=project_id, action="Архивирование проекта",
                 user_id=actor.id, user_login=actor.login, basis=body.basis)
    return result


# ---------------------------------------------------------------------------
#  FR-22: предпросмотр открытых полей
# ---------------------------------------------------------------------------

@router.get("/{project_id}/public-preview")
def public_preview(project_id: str, actor: CurrentActor):
    """Предпросмотр разрешённых открытых полей (FR-22).

    Закрытые сведения (п.9.2) в ответ не попадают ни при каких условиях:
    экспертные заключения, риски, ресурсные запросы, контакты, журнал.
    """
    from ..services.public import project_public_card

    row = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    card = project_public_card(dict(row), include_unpublished=True)
    return {
        "publish_mode": row["publish_mode"],
        "publish_mode_title": PUBLISH_MODES.get(row["publish_mode"]),
        "approved_at": row["public_allowed_at"],
        "approved_by": row["public_allowed_by"],
        "will_be_published": card.get("published", False),
        "card": card,
        "note": "Проект передаётся в публичный контур только после отдельного "
                "разрешения уполномоченного лица (п.9.2)",
    }