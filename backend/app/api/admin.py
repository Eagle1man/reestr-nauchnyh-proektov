"""Администрирование (M-09): пользователи, роли, справочники, настройки, б/к.

SEC-07: усиленная защита учётных записей администраторов.
П.11.1 п.4: восстановление доступа выполняет администратор либо подтверждённый
служебный адрес.

SEC-05: пароли и ключи не выводятся в журналы и не показываются повторно —
API возвращает пароль ОДИН раз, в момент создания учётной записи.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import audit
from ..access import ROLE_SYSADMIN, ROLE_TECH_ADMIN
from ..config import settings
from ..db import execute, query, query_one, scalar
from ..domain.taxonomy import GLOBAL_ROLES, ROLE_SYSADMIN
from ..security import (
    destroy_all_sessions, generate_password, grant_role, hash_password,
    password_problems, revoke_role, user_roles,
)
from ..utils import new_id, now_iso
from .deps import CurrentActor, Pagination

router = APIRouter(prefix="/api/admin", tags=["Администрирование"])


def _require_admin(actor) -> None:
    if not (actor.global_roles & {ROLE_SYSADMIN, ROLE_TECH_ADMIN}):
        raise HTTPException(status_code=403,
                            detail="Раздел доступен техническому администратору")


# ===========================================================================
#  Учётные записи (FR-01, SEC-07)
# ===========================================================================

class UserCreate(BaseModel):
    login: str = Field(min_length=3, max_length=100)
    full_name: str = Field(min_length=2, max_length=300)
    email: str | None = Field(default=None, max_length=200)
    roles: list[str] = Field(default_factory=list)
    person_id: str | None = None
    password: str | None = Field(default=None, max_length=200)


def _public(row) -> dict:
    return {
        "id": row["id"], "login": row["login"], "email": row["email"],
        "full_name": row["full_name"], "is_active": bool(row["is_active"]),
        "must_reset": bool(row["must_reset"]), "last_login_at": row["last_login_at"],
        "created_at": row["created_at"], "roles": user_roles(row["id"]),
        "person_id": row["person_id"],
    }


@router.get("/users")
def list_users(actor: CurrentActor, page: Annotated[Pagination, Depends()],
               q: str | None = None, include_inactive: bool = False):
    _require_admin(actor)
    where = [] if include_inactive else ["u.is_active = 1"]
    params: list = []
    if q:
        where.append("(u.login LIKE ? OR u.full_name LIKE ? OR u.email LIKE ?)")
        params.extend([f"%{q}%"] * 3)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.extend([page.limit, page.offset])
    rows = query(f"SELECT u.* FROM users u {clause} ORDER BY u.full_name LIMIT ? OFFSET ?",
                 tuple(params))
    total = scalar(f"SELECT COUNT(*) FROM users u {clause}", tuple(params[:-2]), 0)
    return {"items": [_public(r) for r in rows], "total": total,
            "limit": page.limit, "offset": page.offset}


@router.post("/users", status_code=201)
def create_user(body: UserCreate, request: Request, actor: CurrentActor):
    """Создание учётной записи. Пароль показывается один раз и нигде не хранится."""
    _require_admin(actor)
    if query_one("SELECT id FROM users WHERE login = ?", (body.login,)):
        raise HTTPException(status_code=409,
                            detail=f"Учётная запись «{body.login}» уже существует")
    if body.email and query_one("SELECT id FROM users WHERE email = ?", (body.email,)):
        raise HTTPException(status_code=409,
                            detail=f"Служебный адрес «{body.email}» уже используется")
    if body.person_id and query_one("SELECT id FROM persons WHERE id = ?",
                                    (body.person_id,)) is None:
        raise HTTPException(status_code=404, detail="Профиль не найден")

    password = body.password or generate_password()
    problems = password_problems(password)
    if problems:
        raise HTTPException(status_code=400,
                            detail={"error": "Пароль не удовлетворяет требованиям п.11.1",
                                    "problems": problems})

    uid = new_id()
    execute(
        "INSERT INTO users (id, login, email, full_name, password_hash, role, is_active,"
        " must_reset, person_id, created_at, created_by)"
        " VALUES (?, ?, ?, ?, ?, 'employee', 1, ?, ?, ?, ?)",
        (uid, body.login, body.email, body.full_name, hash_password(password),
         0 if body.password else 1, body.person_id, now_iso(), actor.id))
    for role in dict.fromkeys(body.roles):
        if role not in GLOBAL_ROLES and role != ROLE_SYSADMIN:
            raise HTTPException(status_code=400,
                                detail=f"Неизвестная роль «{role}». Допустимые: "
                                       f"{', '.join(sorted(set(GLOBAL_ROLES) | {ROLE_SYSADMIN}))}")
        grant_role(uid, role, actor.id)
    audit.record(group_name=audit.GROUP_ADMIN, object_type="user", object_id=uid,
                 action="Создание учётной записи", user_id=actor.id, user_login=actor.login,
                 new_value={"login": body.login, "roles": body.roles},
                 ip_address=request.client.host if request.client else None)
    # SEC-05: пароль в журнал не пишется. Возвращается один раз.
    return {**_public(query_one("SELECT * FROM users WHERE id = ?", (uid,))),
            "initial_password": password,
            "note": "Пароль показывается один раз. Передайте его пользователю "
                    "по защищённому каналу и потребуйте смену при первом входе."}


@router.patch("/users/{user_id}")
def update_user(user_id: str, request: Request, actor: CurrentActor,
                full_name: str | None = None, email: str | None = None,
                is_active: bool | None = None, must_reset: bool | None = None):
    _require_admin(actor)
    row = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Учётная запись не найдена")
    changes: dict[str, tuple[Any, Any]] = {}
    for column, value in (("full_name", full_name), ("email", email),
                          ("is_active", None if is_active is None else int(is_active)),
                          ("must_reset", None if must_reset is None else int(must_reset))):
        if value is not None and row[column] != value:
            changes[column] = (row[column], value)
    if changes:
        execute("UPDATE users SET " + ", ".join(f"{k} = ?" for k in changes) + " WHERE id = ?",
                tuple(v for _, v in changes.values()) + (user_id,))
        audit.record_change(group_name=audit.GROUP_ADMIN, object_type="user",
                            object_id=user_id, action="Изменение учётной записи",
                            changes=changes, user_id=actor.id, user_login=actor.login)
        # ПС-22: блокировка прекращает доступ, но не удаляет внесённые данные
        # и историю. Сессии закрываются, записи остаются.
        if "is_active" in changes and changes["is_active"][1] == 0:
            closed = destroy_all_sessions(user_id)
            audit.record(group_name=audit.GROUP_AUTH, object_type="user",
                         object_id=user_id, action="Блокировка учётной записи",
                         user_id=actor.id, user_login=actor.login,
                         basis=f"закрыто сессий: {closed}",
                         ip_address=request.client.host if request.client else None)
    return _public(query_one("SELECT * FROM users WHERE id = ?", (user_id,)))


@router.put("/users/{user_id}/roles")
def set_roles(user_id: str, roles: list[str], actor: CurrentActor):
    """Назначение ролей. Изменение ролей фиксируется в журнале (п.11.3)."""
    _require_admin(actor)
    if query_one("SELECT id FROM users WHERE id = ?", (user_id,)) is None:
        raise HTTPException(status_code=404, detail="Учётная запись не найдена")
    valid = set(GLOBAL_ROLES) | {ROLE_SYSADMIN}
    unknown = [r for r in roles if r not in valid]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"Неизвестные роли: {', '.join(unknown)}. "
                                   f"Допустимые: {', '.join(sorted(valid))}")
    before = set(user_roles(user_id))
    execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
    for role in dict.fromkeys(roles):
        grant_role(user_id, role, actor.id)
    after = set(user_roles(user_id))
    audit.record(group_name=audit.GROUP_AUTH, object_type="user", object_id=user_id,
                 action="Изменение ролей и прав", user_id=actor.id, user_login=actor.login,
                 old_value=sorted(before), new_value=sorted(after),
                 basis="п.11.3 вход и безопасность")
    return _public(query_one("SELECT * FROM users WHERE id = ?", (user_id,)))


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, actor: CurrentActor):
    """Сброс пароля администратором (п.11.1 п.4). Новый пароль показывается один раз."""
    _require_admin(actor)
    if query_one("SELECT id FROM users WHERE id = ?", (user_id,)) is None:
        raise HTTPException(status_code=404, detail="Учётная запись не найдена")
    password = generate_password()
    execute("UPDATE users SET password_hash = ?, must_reset = 1 WHERE id = ?",
            (hash_password(password), user_id))
    destroy_all_sessions(user_id)
    audit.record(group_name=audit.GROUP_AUTH, object_type="user", object_id=user_id,
                 action="Сброс пароля", user_id=actor.id, user_login=actor.login,
                 basis="п.11.1 п.4 восстановление доступа администратором")
    return {"ok": True, "initial_password": password,
            "note": "Все сессии пользователя закрыты. Пароль показывается один раз."}


@router.get("/roles")
def available_roles(actor: CurrentActor):
    _require_admin(actor)
    return {
        "roles": [
            {"code": ROLE_SYSADMIN, "title": "Системный администратор",
             "note": "Внутрисистемная роль: учётные записи и настройки. "
                     "Научных решений не принимает."},
            *({"code": code, **spec} for code, spec in GLOBAL_ROLES.items()),
        ],
        "note": "Роли руководителя проекта, участника и эксперта — это отношение "
                "к конкретному проекту (FR-02, п.4.1), они не выдаются здесь.",
    }


# ===========================================================================
#  Справочники (FR-30)
# ===========================================================================

class DictItemBody(BaseModel):
    # Имя поля dict перекрывает метод BaseModel.dict(), поэтому используем
    # словарь_ и алиас: клиент по-прежнему присылает "dict".
    словарь_: str = Field(min_length=2, max_length=60, alias="dict")
    code: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=300)
    sort_order: int = 0
    is_active: bool = True

    model_config = {"populate_by_name": True}


DICTS = {
    "method": "Методы исследования",
    "result_type": "Виды результатов",
    "risk_category": "Категории рисков",
    "organization": "Организации",
    "publication_kind": "Виды публикаций",
    "target_journal": "Целевые издания",
    "party_type": "Типы партнёров",
}


@router.get("/dictionaries")
def list_dictionaries(actor: CurrentActor,
                      dict_name: str | None = Query(default=None, alias="dict"),
                      include_inactive: bool = False):
    _require_admin(actor)
    where = [] if include_inactive else ["is_active = 1"]
    params: list = []
    # Имя параметра не может быть `dict`: оно перекрывает встроенную функцию,
    # и вызов dict(row) ниже перестаёт работать.
    if dict_name:
        where.append("dict = ?")
        params.append(dict_name)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = query(f"SELECT * FROM dict_items {clause} ORDER BY dict, sort_order, title",
                 tuple(params))
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["dict"], []).append(dict(row))
    return {"available": DICTS,
            "titles": DICTS,
            "items": grouped}


@router.post("/dictionaries", status_code=201)
def add_dict_item(body: DictItemBody, actor: CurrentActor):
    _require_admin(actor)
    dict_name = body.словарь_
    if dict_name not in DICTS:
        raise HTTPException(status_code=400,
                            detail=f"Неизвестный справочник «{dict_name}». Доступные: "
                                   f"{', '.join(DICTS)}")
    if query_one("SELECT id FROM dict_items WHERE dict = ? AND code = ?",
                 (dict_name, body.code)):
        raise HTTPException(status_code=409,
                            detail=f"Запись с кодом «{body.code}» уже есть")
    iid = new_id()
    execute("INSERT INTO dict_items (id, dict, code, title, sort_order, is_active)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (iid, dict_name, body.code, body.title, body.sort_order,
             1 if body.is_active else 0))
    audit.record(group_name=audit.GROUP_ADMIN, object_type="dict_item", object_id=iid,
                 action="Изменение справочника", user_id=actor.id, user_login=actor.login,
                 new_value={"dict": dict_name, "code": body.code, "title": body.title})
    return dict(query_one("SELECT * FROM dict_items WHERE id = ?", (iid,)))


@router.patch("/dictionaries/{item_id}")
def update_dict_item(item_id: str, body: DictItemBody, actor: CurrentActor):
    _require_admin(actor)
    row = query_one("SELECT * FROM dict_items WHERE id = ?", (item_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Запись справочника не найдена")
    execute("UPDATE dict_items SET title = ?, sort_order = ?, is_active = ? WHERE id = ?",
            (body.title, body.sort_order, 1 if body.is_active else 0, item_id))
    audit.record_change(group_name=audit.GROUP_ADMIN, object_type="dict_item",
                        object_id=item_id, action="Изменение справочника",
                        changes={"title": (row["title"], body.title),
                                 "is_active": (row["is_active"], int(body.is_active))},
                        user_id=actor.id, user_login=actor.login)
    return dict(query_one("SELECT * FROM dict_items WHERE id = ?", (item_id,)))


# ===========================================================================
#  Настройки (FR-35)
# ===========================================================================

class SettingsBody(BaseModel):
    values: dict[str, Any]


@router.get("/settings")
def get_settings(actor: CurrentActor):
    _require_admin(actor)
    rows = query("SELECT key, value, updated_at, updated_by FROM settings ORDER BY key")
    return {
        "values": {r["key"]: r["value"] for r in rows},
        "meta": {r["key"]: {"updated_at": r["updated_at"], "updated_by": r["updated_by"]}
                 for r in rows},
        "environment": {
            "app_name": settings.app_name,
            "debug": settings.debug,
            "session_idle_minutes": settings.session_idle_minutes,
            "password_min_length": settings.password_min_length,
            "login_max_attempts": settings.login_max_attempts,
            "login_lock_minutes": settings.login_lock_minutes,
            "public_rate_limit_per_minute": settings.public_rate_limit_per_minute,
            "backup_retention_days": settings.backup_retention_days,
            "upload_max_bytes": settings.upload_max_bytes,
        },
        "note": "Пороговые сроки, шаблон номера и перечни справочников меняются "
                "здесь, без правки кода (FR-35)",
    }


@router.put("/settings")
def put_settings(body: SettingsBody, actor: CurrentActor):
    _require_admin(actor)
    if not body.values:
        raise HTTPException(status_code=400, detail="Передайте объект values")
    before = {r["key"]: r["value"] for r in query("SELECT key, value FROM settings")}
    for key, value in body.values.items():
        execute(
            "INSERT INTO settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (key, json_dumps(value), now_iso(), actor.id))
    after = {r["key"]: r["value"] for r in query("SELECT key, value FROM settings")}
    audit.record_change(group_name=audit.GROUP_ADMIN, object_type="settings",
                        object_id="global", action="Изменение настроек",
                        changes={k: (before.get(k), after.get(k)) for k in after},
                        user_id=actor.id, user_login=actor.login,
                        basis="FR-35 настройки меняются без правки кода")
    return {"values": after}


def json_dumps(value: Any) -> str:
    import json
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


# ===========================================================================
#  Резервное копирование (п.11.4)
# ===========================================================================

@router.post("/backup")
def make_backup(actor: CurrentActor):
    """Создать резервную копию (п.11.4).

    Копия делается через Connection.backup(), а не копированием файла: при
    работающем журнале WAL копирование .db даёт снимок без последних
    изменений. Это урок отдела, memories/2026/10/2026-10-02-sqlite-snapshot-wal.
    """
    _require_admin(actor)
    from ..backup import create_backup

    result = create_backup()
    audit.record(group_name=audit.GROUP_ADMIN, object_type="backup",
                 object_id=result["file"], action="Резервное копирование",
                 user_id=actor.id, user_login=actor.login,
                 new_value={"size_bytes": result["size_bytes"],
                            "tables": result["tables"], "integrity": result["integrity"]})
    return result


@router.get("/backup")
def list_backups(actor: CurrentActor):
    _require_admin(actor)
    from ..backup import list_backups as _list
    return {"items": _list()}


@router.post("/backup/verify")
def verify_backup(actor: CurrentActor, path: str):
    """Проверка копии без её применения (п.11.4 «Проверка»).

    Контрольное восстановление проверяет СОДЕРЖИМОЕ, а не только то, что файл
    открывается: обрезанный файл тоже открывается. Это урок отдела,
    memories/2026/10/2026-10-02-truncated-file-silent-success.
    """
    _require_admin(actor)
    from ..backup import verify_backup as _verify
    result = _verify(path)
    audit.record(group_name=audit.GROUP_ADMIN, object_type="backup", object_id=path,
                 action="Проверка резервной копии", user_id=actor.id, user_login=actor.login,
                 new_value=result, outcome="ok" if result.get("ok") else "error")
    return result


@router.post("/backup/restore")
def restore_backup(actor: CurrentActor, path: str, confirm: bool = False):
    """Восстановление из копии. До подтверждения выполняется только проверка."""
    _require_admin(actor)
    from ..backup import restore_backup as _restore
    if not confirm:
        from ..backup import verify_backup as _verify
        return {"confirmed": False, "verification": _verify(path),
                "hint": "Повторите запрос с confirm=true для восстановления. "
                        "Перед восстановлением система сделает контрольную копию "
                        "текущего состояния."}
    result = _restore(path)
    audit.record(group_name=audit.GROUP_ADMIN, object_type="backup", object_id=path,
                 action="Резервное восстановление", user_id=actor.id, user_login=actor.login,
                 new_value=result)
    return {"confirmed": True, **result}


# ===========================================================================
#  Обслуживание
# ===========================================================================

@router.post("/maintenance/refresh-risks")
def refresh_risks(actor: CurrentActor):
    """Пересчитать индикаторы риска по всем проектам (FR-13)."""
    _require_admin(actor)
    from ..services.projects import recompute_risk
    updated = []
    for row in query("SELECT id, code FROM projects WHERE archived_at IS NULL"):
        risk = recompute_risk(row["id"])
        updated.append({"code": row["code"], "risk_level": risk["level"],
                        "overdue_milestones": len(risk["overdue_milestones"])})
    changed = [u for u in updated if u["risk_level"] != "green"]
    audit.record(group_name=audit.GROUP_ADMIN, object_type="project", object_id=None,
                 action="Пересчёт индикаторов риска", user_id=actor.id,
                 user_login=actor.login, new_value={"processed": len(updated),
                                                    "non_green": len(changed)})
    return {"processed": len(updated), "non_green": len(changed),
            "items": changed,
            "note": "Статус и индикатор риска — разные поля (п.5.4)"}


@router.get("/maintenance/sessions")
def active_sessions(actor: CurrentActor):
    _require_admin(actor)
    rows = query("SELECT s.token, s.user_id, s.created_at, s.last_seen_at, s.expires_at,"
                 " s.ip_address, u.login, u.full_name FROM sessions s"
                 " JOIN users u ON u.id = s.user_id ORDER BY s.last_seen_at DESC")
    items = []
    for row in rows:
        item = dict(row)
        # Токен наружу не выдаётся (SEC-05)
        item["token"] = item["token"][:8] + "…"
        items.append(item)
    return {"items": items, "count": len(items),
            "idle_timeout_minutes": settings.session_idle_minutes}


@router.delete("/maintenance/sessions", status_code=204)
def drop_all_sessions(actor: CurrentActor):
    _require_admin(actor)
    total = scalar("SELECT COUNT(*) FROM sessions", (), 0)
    execute("DELETE FROM sessions")
    audit.record(group_name=audit.GROUP_AUTH, object_type="session", object_id=None,
                 action="Закрытие всех сессий", user_id=actor.id, user_login=actor.login,
                 basis=f"сессий закрыто: {total}")
    return None