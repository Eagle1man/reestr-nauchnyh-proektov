"""Общие зависимости FastAPI: аутентификация, актёр, пагинация.

УРОК ОТДЕЛА (memories/2026/10/2026-10-02-fastapi-header-alias): если FastAPI
читает заголовок, имя параметра НЕ равно имени заголовка — нужен alias.
Здесь: Authorization читается через Header(alias="Authorization"), а
X-Request-Id — через Header(alias="X-Request-Id"). Иначе заголовок не
сработает никогда и код пройдёт проверку, который никогда не выполнялся.

Токен передаётся в заголовке Authorization, а не в cookie: bearer-токен
не подвержен атаке подделки межсайтовых запросов (SEC-04), поэтому отдельный
CSRF-токен здесь не нужен — решение зафиксировано в документации.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request, status

from ..access import Actor, AccessDenied, attach_relations, load_actor
from ..db import query_one
from ..security import resolve_session

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Требуется вход в систему",
    headers={"WWW-Authenticate": "Bearer"},
)


def bearer_token(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_agent_key: Annotated[str | None, Header(alias="X-Agent-Key")] = None,
) -> str | None:
    """Извлечь токен сессии.

    Основной способ — Authorization: Bearer. X-Agent-Key оставлен для служебных
    интеграций и проверок; в журнал попадает только факт, не значение.
    """
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return None
    if x_agent_key:
        return None  # служебные ключи обрабатываются отдельно, не как сессия
    return None


def request_id(
    x_request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
) -> str:
    """Идентификатор корреляции для журнала (не секрет)."""
    return x_request_id or str(uuid.uuid4())


def current_actor(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Actor:
    if not authorization:
        raise CREDENTIALS_ERROR
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise CREDENTIALS_ERROR
    session = resolve_session(parts[1].strip())
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия истекла: 60 минут бездействия (п.11.1)",
        )
    actor = load_actor(session["user"])
    actor.relations.clear()
    request.state.user_id = session["user"]["id"]
    return actor


def project_actor(
    project_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
) -> Actor:
    """Актёр, дополненный отношениями к проекту из адреса."""
    return attach_relations(actor, project_id)


CurrentActor = Annotated[Actor, Depends(current_actor)]


def require_project_id(project_id: str) -> str:
    if not project_id:
        raise HTTPException(status_code=400, detail="Не указан идентификатор проекта")
    return project_id


class Pagination:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        self.limit = limit
        self.offset = offset

    @property
    def params(self) -> tuple[int, int]:
        return self.limit, self.offset


def forbidden(exc: AccessDenied) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": str(exc), "required_roles": exc.required},
    )


def project_or_404(project_id: str) -> dict:
    row = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return dict(row)