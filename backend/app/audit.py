"""Журнал аудита (M-10, FR-23, п.11.3).

Журнал неизменяем: в нём нет операций обновления и удаления. Для каждого
события хранятся дата и время, пользователь, объект, операция и результат
(п.11.3). Секреты сюда не попадают (SEC-05) — записывается факт операции,
а не её секретное содержимое.

Группы событий (п.11.3): auth | card | review_decision | publish | admin.
"""

from __future__ import annotations

import json
from typing import Any

from .db import execute, query
from .utils import new_id, now_iso

GROUP_AUTH = "auth"
GROUP_CARD = "card"
GROUP_REVIEW_DECISION = "review_decision"
GROUP_PUBLISH = "publish"
GROUP_ADMIN = "admin"

EVENT_GROUPS: dict[str, list[str]] = {
    GROUP_AUTH: [
        "Успешный вход", "Неудачный вход", "Блокировка учётной записи",
        "Выход", "Изменение ролей и прав", "Сброс пароля",
    ],
    GROUP_CARD: [
        "Создание карточки", "Архивирование", "Смена маршрута", "Смена статуса",
        "Смена индикатора риска", "Смена руководителя", "Смена срока",
        "Смена цели", "Смена результата",
    ],
    GROUP_REVIEW_DECISION: [
        "Назначение эксперта", "Самоотвод эксперта", "Заключение",
        "Решение", "Изменение условий", "Исполнение решения",
    ],
    GROUP_PUBLISH: [
        "Разрешение публикации", "Передача публичных данных",
        "Изменение публичных данных", "Снятие с публикации",
    ],
    GROUP_ADMIN: [
        "Импорт", "Выгрузка", "Изменение справочников",
        "Резервное копирование", "Резервное восстановление", "Обновление",
    ],
}


def record(
    *,
    group_name: str,
    object_type: str,
    action: str,
    user_id: str | None = None,
    user_login: str | None = None,
    object_id: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    basis: str | None = None,
    outcome: str = "ok",
    ip_address: str | None = None,
) -> str:
    event_id = new_id()
    execute(
        "INSERT INTO audit_events (id, happened_at, user_id, user_login, group_name,"
        " object_type, object_id, action, old_value, new_value, basis, outcome,"
        " ip_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id, now_iso(), user_id, user_login, group_name,
            object_type, object_id, action,
            _dump(old_value), _dump(new_value), basis, outcome, ip_address,
        ),
    )
    return event_id


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:4000]
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:4000]
    except (TypeError, ValueError):
        return str(value)[:4000]


def record_change(
    *,
    group_name: str,
    object_type: str,
    object_id: str,
    action: str,
    changes: dict[str, tuple[Any, Any]],
    user_id: str | None = None,
    user_login: str | None = None,
    basis: str | None = None,
    ip_address: str | None = None,
) -> list[str]:
    """Записать изменение полей с прежним и новым значением (FR-23).

    В журнал попадает только реально изменившееся: иначе карточка из
    тридцати полей даёт тридцать событий на каждое сохранение.
    """
    ids: list[str] = []
    for field, (old, new) in changes.items():
        if old == new:
            continue
        ids.append(record(
            group_name=group_name, object_type=object_type, object_id=object_id,
            action=f"{action}: {field}", user_id=user_id, user_login=user_login,
            old_value=old, new_value=new, basis=basis, ip_address=ip_address,
        ))
    return ids


def search(
    *,
    object_type: str | None = None,
    object_id: str | None = None,
    group_name: str | None = None,
    user_id: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    since: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    where: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("object_type", object_type), ("object_id", object_id),
        ("group_name", group_name), ("user_id", user_id), ("action", action),
        ("outcome", outcome),
    ):
        if value:
            where.append(f"{column} = ?")
            params.append(value)
    if since:
        where.append("happened_at >= ?")
        params.append(since)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.extend([limit, offset])
    rows = query(
        f"SELECT * FROM audit_events {clause} ORDER BY happened_at DESC, rowid DESC"
        " LIMIT ? OFFSET ?",
        tuple(params),
    )
    return [dict(r) for r in rows]


def for_object(object_type: str, object_id: str, limit: int = 200) -> list[dict]:
    return search(object_type=object_type, object_id=object_id, limit=limit)


def count_by_group(since: str | None = None) -> list[dict]:
    if since:
        rows = query(
            "SELECT group_name, COUNT(*) AS n FROM audit_events WHERE happened_at >= ?"
            " GROUP BY group_name ORDER BY n DESC", (since,))
    else:
        rows = query(
            "SELECT group_name, COUNT(*) AS n FROM audit_events GROUP BY group_name"
            " ORDER BY n DESC")
    return [dict(r) for r in rows]