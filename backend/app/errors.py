# -*- coding: utf-8 -*-
"""Сбор ошибок для отчёта разработчику.

ЗАЧЕМ. Внутренняя ошибка возвращает пользователю код обращения
(«Необработанная ошибка [293401fe]»), но сам код живёт только в журнале
сервера. Пользователь присылает нам сообщение об ошибке — а получить из
него можно разве что слово «ошибка»: что именно сломалось, на какой
странице и с каким запросом, остаётся на машине.

Здесь ошибки складываются в ограниченный круг в памяти, и администратор
может забрать их одним запросом — вместе с тем, что видел браузер.

ЧЕГО ЗДЕСЬ НЕТ. Ничего не отправляется наружу и никуда не пишется на диск:
сбор идёт в память процесса и теряется при перезапуске. Это осознанно —
отчёт собирает и увозит пользователь, а сервер молча не сливает данные
во внешний мир (SEC-05).
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

#: Сколько последних ошибок держим. Круг небольшой: нужен разбор последней
#: сессии, а не журнал за месяц.
MAX_ERRORS = 200

#: Сколько групп отпечатков показывать. Проблем всегда меньше, чем записей;
#: если групп больше двадцати, это уже не разбор, а свалка.
MAX_GROUPS = 20

#: Срок хранения журнала ошибок в базе. Дольше хранить незачем: разбор идёт по
#: последним месяцам, а сведения о сбоях — не тот материал, который стоит
#: копить годами (SEC-05).
RETENTION_DAYS = 90

#: Чистка при записи: не чаще раза в час, иначе каждый сбой будет ещё и
#: удалять строки, а журнал не должен влиять на время ответа.
CLEANUP_INTERVAL_SECONDS = 3600

_lock = threading.Lock()
_errors: deque[dict] = deque(maxlen=MAX_ERRORS)

#: Когда последний раз чистили журнал базы. Живёт в памяти процесса.
_last_cleanup: float = 0.0

#: Отпечаток → сколько раз и когда. Живёт столько же, сколько записи:
#: отдельной истории нет намеренно (ошибки по-прежнему только в памяти).
_groups: dict[str, dict] = {}

#: Что вырезается из сообщения перед подсчётом отпечатка. Одна и та же ошибка
#: от разных пользователей отличается идентификаторами и путями — без
#: нормализации они дали бы десятки «разных» проблем вместо одной.
_NORMALIZERS = (
    (re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"), "<id>"),
    (re.compile(r"/api/[A-Za-z0-9_/{}\-]*"), lambda m: re.sub(
        r"/[0-9a-fA-F-]{8,}|/\d+", "/<id>", m.group(0))),
    (re.compile(r"\b\d{3,}\b"), "<n>"),
    (re.compile(r"\[[0-9a-fA-F]{6,}\]"), "<ref>"),
)


def _normalize(text: str) -> str:
    """Убирает из строки то, что делает одинаковые причины разными."""
    for pattern, replacement in _NORMALIZERS:
        text = pattern.sub(replacement, text)
    return " ".join(text.split())


def fingerprint(kind: str, message: str, path: str | None) -> str:
    """Отпечаток причины, а не отдельного случая.

    Считается от типа, нормализованного сообщения и места: числа, идентификаторы
    и конкретные адреса убираются, иначе одна проблема выглядит как сотня.
    Путь нормализуется так же, как сообщение: иначе одна и та же ошибка на
    разных карточках (`/api/projects/<id>`) дала бы разные отпечатки.
    """
    basis = "|".join((kind.strip().lower(), _normalize(message), _normalize(path or "")))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def record(kind: str, message: str, *, reference: str | None = None,
           path: str | None = None, user_login: str | None = None,
           role: str | None = None, app_version: str | None = None) -> dict:
    """Записать ошибку и вернуть её же — для ответа пользователю.

    Пишет в два места: в круг памяти (его забирает отчёт администратора) и в
    журнал базы `error_events` (по нему работает разбор). Журнал пишется
    осторожно: сбой записи не должен превращать одну ошибку в две, поэтому
    исключение здесь гасится — память всё равно сохранит случай.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print_f = fingerprint(kind, message, path)
    entry = {
        "at": now,
        "kind": kind,
        "message": message[:2000],
        "reference": reference,
        "path": path,
        "user": user_login,
        "fingerprint": print_f,
    }
    with _lock:
        _errors.appendleft(entry)
        group = _groups.get(print_f)
        if group is None:
            _groups[print_f] = {
                "fingerprint": print_f,
                "kind": kind,
                "message": message[:300],
                "path": path,
                "count": 1,
                "first_seen": now,
                "last_seen": now,
            }
        else:
            group["count"] += 1
            group["last_seen"] = now
    _store(entry, role=role, app_version=app_version)
    return entry


def _store(entry: dict, *, role: str | None, app_version: str | None) -> None:
    """Положить случай в журнал базы. Логин не пишется — только роль."""
    try:
        from .db import get_conn

        get_conn().execute(
            "INSERT INTO error_events (fingerprint, kind, message, path, role, "
            "reference, app_version, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (entry["fingerprint"], entry["kind"], entry["message"], entry["path"],
             role, entry["reference"], app_version, entry["at"]),
        )
        get_conn().commit()
    except Exception:  # noqa: BLE001 — журнал не имеет права ломать ответ
        return
    _maybe_cleanup()


def _maybe_cleanup() -> None:
    """Удалить записи старше срока хранения — не чаще раза в час."""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < CLEANUP_INTERVAL_SECONDS:
        return
    _last_cleanup = now
    try:
        from .db import get_conn

        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS))
        get_conn().execute(
            "DELETE FROM error_events WHERE occurred_at < ?",
            (cutoff.isoformat(timespec="seconds"),),
        )
        get_conn().commit()
    except Exception:  # noqa: BLE001
        return


def stored_groups(limit: int = MAX_GROUPS, days: int | None = None) -> list[dict]:
    """История из журнала: проблемы за период, частые сверху.

    Отличие от `groups()`: там — текущая сессия в памяти, здесь — всё, что
    пережило перезапуск. Разбору нужен именно этот список, иначе «повторяется
    или нет» ответить нечем.
    """
    window_days = RETENTION_DAYS if days is None else max(1, days)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days))
    try:
        from .db import get_conn

        rows = get_conn().execute(
            "SELECT fingerprint, kind, message, path, COUNT(*) AS count, "
            "MIN(occurred_at) AS first_seen, MAX(occurred_at) AS last_seen "
            "FROM error_events WHERE occurred_at >= ? "
            "GROUP BY fingerprint ORDER BY count DESC, last_seen DESC LIMIT ?",
            (cutoff.isoformat(timespec="seconds"), max(1, limit)),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception:  # noqa: BLE001
        return []


def recent(limit: int = 50) -> list[dict]:
    """Последние ошибки, свежие первыми."""
    with _lock:
        return list(_errors)[:max(1, min(limit, MAX_ERRORS))]


def summary(within_minutes: int = 60) -> dict:
    """Сколько ошибок и за какое окно — это и нужно в первую очередь."""
    window = datetime.now(timezone.utc) - timedelta(minutes=within_minutes)
    with _lock:
        fresh = [e for e in _errors if datetime.fromisoformat(e["at"]) >= window]
    by_kind: dict[str, int] = {}
    for entry in fresh:
        by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1
    return {
        "total_in_window": len(fresh),
        "window_minutes": within_minutes,
        "by_kind": by_kind,
        "kept_in_memory": len(_errors),
        "limit": MAX_ERRORS,
        # Проблем меньше, чем случаев: одна и та же ошибка от разных
        # пользователей — это одна строка разбора.
        "unique_problems": len(_groups),
    }


def groups(limit: int = MAX_GROUPS) -> list[dict]:
    """Проблемы, а не случаи: одна строка на отпечаток, частые сверху.

    Именно этот список идёт в разбор. Без него 200 записей — это 200 строк,
    среди которых одна и та же проблема повторяется десятки раз, и время
    уходит на её поиск, а не на исправление.
    """
    with _lock:
        items = [dict(group) for group in _groups.values()]
    items.sort(key=lambda item: (-item["count"], item["last_seen"]))
    return items[:max(1, limit)]


def clear() -> None:
    """Очистить после разбора — иначе старые ошибки будут выдаваться
    как текущие и запутают разбор."""
    with _lock:
        _errors.clear()
        _groups.clear()