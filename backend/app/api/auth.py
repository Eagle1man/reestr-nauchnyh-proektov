"""Авторизация (FR-01) и профиль пользователя.

ПС-01: доступ предоставляется только при корректных данных; служебные сведения
не раскрываются. Поэтому наружу не отдаются password_hash, секретные поля,
счётчики неудачных попыток и внутренние идентификаторы сессий.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .. import audit
from ..access import matrix_for
from ..config import settings
from ..db import execute, query, query_one, scalar
from ..security import (
    create_session, destroy_session, failed_count, grant_role, hash_password,
    ip_lock_remaining, lockout_remaining, password_problems, register_attempt,
    revoke_role, user_roles, verify_password,
)
from ..utils import now_iso
from .deps import CurrentActor

router = APIRouter(prefix="/api/auth", tags=["Авторизация"])


class LoginBody(BaseModel):
    login: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=400)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=400)
    new_password: str = Field(min_length=1, max_length=400)


def public_user(row: dict | None) -> dict:
    """Пользователь без служебных сведений (ПС-01)."""
    if row is None:
        return {}
    return {
        "id": row["id"],
        "login": row["login"],
        "email": row.get("email"),
        "full_name": row["full_name"],
        "is_active": bool(row.get("is_active", 1)),
        "must_reset": bool(row.get("must_reset", 0)),
        "last_login_at": row.get("last_login_at"),
        "person_id": row.get("person_id"),
        "roles": user_roles(row["id"]) if row.get("id") else [],
    }


def _link_person(user_id: str, email: str | None, full_name: str) -> str | None:
    """Однократно связать учётную запись с профилем человека (FR-03).

    Основной ключ сопоставления — служебный адрес или учётная запись (п.6.1 п.2).
    Профиль создаётся, только если его ещё нет: повторный вход не плодит дубли.
    """
    if not email:
        return None
    person = query_one("SELECT id FROM persons WHERE service_contact = ? OR external_id = ?",
                       (email, user_id))
    if person is not None:
        execute("UPDATE users SET person_id = ? WHERE id = ?", (person["id"], user_id))
        return person["id"]
    existing = query_one("SELECT person_id FROM users WHERE id = ?", (user_id,))
    if existing and existing["person_id"]:
        return existing["person_id"]
    return None


@router.post("/login")
def login(body: LoginBody, request: Request):
    ip = request.client.host if request.client else None

    # Перебор с одного адреса ограничивается отдельно и раньше по счёту:
    # иначе пять неверных паролей от чужого имени блокируют сотруднику вход.
    ip_wait = ip_lock_remaining(ip)
    if ip_wait:
        audit.record(
            group_name=audit.GROUP_AUTH, object_type="user", action="Ограничение по адресу",
            user_login=body.login, outcome="denied",
            basis="превышен порог неудачных попыток с адреса", ip_address=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток входа с этого адреса. Повторите позже.",
            headers={"Retry-After": str(ip_wait)},
        )

    remaining = lockout_remaining(body.login)
    if remaining:
        minutes = max(1, (remaining + 59) // 60)
        audit.record(
            group_name=audit.GROUP_AUTH, object_type="user", action="Блокировка входа",
            user_login=body.login, outcome="denied", basis="превышено число попыток",
            ip_address=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                f"Вход заблокирован на {minutes} мин после "
                f"{settings.login_max_attempts} неудачных попыток (п.11.1)"
            ),
        )

    row = query_one("SELECT * FROM users WHERE login = ?", (body.login,))
    ok = bool(row) and verify_password(body.password, row["password_hash"] if row else None)
    register_attempt(body.login, ip, ok)

    if not ok:
        audit.record(
            group_name=audit.GROUP_AUTH, object_type="user", action="Неудачный вход",
            user_login=body.login, outcome="denied",
            basis=f"ошибок подряд: {failed_count(body.login)}", ip_address=ip,
        )
        # Ответ одинаков для «нет такого логина» и «неверный пароль» —
        # чтобы не перебирать учётные записи.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Неверный логин или пароль")

    if not row["is_active"]:
        audit.record(
            group_name=audit.GROUP_AUTH, object_type="user", action="Вход заблокирован",
            user_id=row["id"], user_login=body.login, outcome="denied",
            basis="учётная запись отключена", ip_address=ip,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Учётная запись отключена. Обратитесь к администратору")

    token = create_session(row["id"], request.headers.get("user-agent"), ip)
    execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), row["id"]))
    _link_person(row["id"], row["email"], row["full_name"])

    # SEC-05: в журнал — факт успешного входа, без токена и пароля.
    audit.record(
        group_name=audit.GROUP_AUTH, object_type="user", action="Успешный вход",
        user_id=row["id"], user_login=body.login, ip_address=ip,
    )
    user = dict(query_one("SELECT * FROM users WHERE id = ?", (row["id"],)))
    user["person_id"] = scalar("SELECT person_id FROM users WHERE id = ?", (row["id"],), None)
    return {"token": token, "user": public_user(user),
            "password_min_length": settings.password_min_length,
            "session_idle_minutes": settings.session_idle_minutes}


@router.post("/logout")
def logout(request: Request, actor: CurrentActor):
    header = request.headers.get("Authorization", "")
    parts = header.split(None, 1)
    if len(parts) == 2:
        destroy_session(parts[1].strip())
    audit.record(group_name=audit.GROUP_AUTH, object_type="user", action="Выход",
                 user_id=actor.id, user_login=actor.login)
    return {"ok": True}


@router.get("/me")
def me(actor: CurrentActor):
    row = dict(query_one("SELECT * FROM users WHERE id = ?", (actor.id,)))
    row["person_id"] = scalar("SELECT person_id FROM users WHERE id = ?", (actor.id,), None)
    person = None
    if row["person_id"]:
        p = query_one("SELECT * FROM persons WHERE id = ?", (row["person_id"],))
        person = dict(p) if p else None
    return {
        "user": public_user(row),
        "matrix": matrix_for(actor),
        "person": person,
        "settings": {
            "app_name": settings.app_name,
            "session_idle_minutes": settings.session_idle_minutes,
            "password_min_length": settings.password_min_length,
        },
    }


@router.post("/password")
def change_password(body: ChangePasswordBody, actor: CurrentActor):
    if not verify_password(body.current_password, scalar(
            "SELECT password_hash FROM users WHERE id = ?", (actor.id,), None)):
        audit.record(group_name=audit.GROUP_AUTH, object_type="user",
                     action="Смена пароля отклонена", user_id=actor.id,
                     user_login=actor.login, outcome="denied",
                     basis="неверный текущий пароль")
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")
    problems = password_problems(body.new_password)
    if problems:
        raise HTTPException(status_code=400,
                            detail={"error": "Пароль не удовлетворяет требованиям",
                                    "problems": problems})
    execute(
        "UPDATE users SET password_hash = ?, must_reset = 0 WHERE id = ?",
        (hash_password(body.new_password), actor.id),
    )
    audit.record(group_name=audit.GROUP_AUTH, object_type="user", action="Смена пароля",
                 user_id=actor.id, user_login=actor.login)
    return {"ok": True}