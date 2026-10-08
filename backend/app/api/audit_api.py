"""Журнал аудита: чтение для уполномоченных лиц (M-10, FR-23).

Журнал неизменяем — здесь только чтение. Ни удаления, ни правки событий в API нет.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import audit
from ..access import (
    ROLE_PRORECTOR, ROLE_RECTOR, ROLE_SECRETARY, ROLE_SYSADMIN, ROLE_TECH_ADMIN,
)
from ..db import query_one, scalar
from ..utils import fmt_datetime
from .deps import CurrentActor, Pagination

router = APIRouter(prefix="/api/audit", tags=["Журнал аудита"])

READ_ROLES = {ROLE_SYSADMIN, ROLE_TECH_ADMIN, ROLE_PRORECTOR, ROLE_RECTOR, ROLE_SECRETARY}


def _require_read(actor) -> None:
    if not (actor.global_roles & READ_ROLES):
        raise HTTPException(status_code=403,
                            detail="Журнал аудита доступен техническому "
                                   "администратору, секретарю и руководству")


@router.get("")
def list_events(
    actor: CurrentActor,
    page: Annotated[Pagination, Depends()],
    object_type: str | None = None,
    object_id: str | None = None,
    group_name: str | None = Query(default=None, pattern="^(auth|card|review_decision|publish|admin)$"),
    user_id: str | None = None,
    action: str | None = Query(default=None, max_length=200),
    outcome: str | None = Query(default=None, pattern="^(ok|denied|error)$"),
    since: str | None = Query(default=None, description="Дата и время в формате ISO"),
):
    """Журнал с фильтрами по объекту, группе событий, пользователю и результату.

    Для каждого события видны дата и время, пользователь, объект, операция и
    результат (п.11.3).
    """
    _require_read(actor)
    events = audit.search(
        object_type=object_type, object_id=object_id, group_name=group_name,
        user_id=user_id, action=action, outcome=outcome, since=since,
        limit=page.limit, offset=page.offset,
    )
    for event in events:
        event["happened_at_fmt"] = fmt_datetime(event.get("happened_at"))
        # SEC-05: парольные хеши и токены в журнал не попадают, но подстраховка
        # на случай ошибки в коде — значения усечены и помечены.
        event["old_value"] = (event.get("old_value") or "")[:1000]
        event["new_value"] = (event.get("new_value") or "")[:1000]
    return {"items": events, "limit": page.limit, "offset": page.offset}


@router.get("/object/{object_type}/{object_id}")
def object_history(object_type: str, object_id: str, actor: CurrentActor,
                   limit: int = Query(default=200, le=500)):
    """История ключевых изменений по объекту (FR-23)."""
    _require_read(actor)
    events = audit.for_object(object_type, object_id, limit=limit)
    for event in events:
        event["happened_at_fmt"] = fmt_datetime(event.get("happened_at"))
    return {"object_type": object_type, "object_id": object_id, "items": events}


@router.get("/summary")
def summary(actor: CurrentActor, since: str | None = None):
    """Сводка по группам событий (п.11.3)."""
    _require_read(actor)
    groups = audit.count_by_group(since)
    return {
        "by_group": groups,
        "event_groups": audit.EVENT_GROUPS,
        "totals": {
            "all": scalar("SELECT COUNT(*) FROM audit_events", (), 0),
            "denied": scalar("SELECT COUNT(*) FROM audit_events WHERE outcome = 'denied'",
                             (), 0),
            "errors": scalar("SELECT COUNT(*) FROM audit_events WHERE outcome = 'error'",
                             (), 0),
        },
        "retention": {
            "content_history": "не менее пяти лет после завершения проекта",
            "technical_logs": "не менее 12 месяцев",
            "source": "п.11.3",
        },
        "immutability": "В API нет операций изменения и удаления событий журнала",
    }


@router.get("/reasons")
def reasons(actor: CurrentActor):
    """Разбор журнала: какие переходы блокировались и почему (FR-10)."""
    _require_read(actor)
    rows = query_denials()
    return {"items": rows, "count": len(rows),
            "note": "Отказы фиксируются с причиной — это основной источник "
                    "для разбора «почему система не дала сменить статус»"}


def query_denials() -> list[dict]:
    from ..db import query
    rows = query(
        "SELECT happened_at, user_login, object_type, object_id, action, basis"
        " FROM audit_events WHERE outcome = 'denied' ORDER BY happened_at DESC LIMIT 200")
    return [{**dict(r), "happened_at_fmt": fmt_datetime(r["happened_at"])}
            for r in rows]