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

import threading
from collections import deque
from datetime import datetime, timedelta, timezone

#: Сколько последних ошибок держим. Круг небольшой: нужен разбор последней
#: сессии, а не журнал за месяц.
MAX_ERRORS = 200

_lock = threading.Lock()
_errors: deque[dict] = deque(maxlen=MAX_ERRORS)


def record(kind: str, message: str, *, reference: str | None = None,
           path: str | None = None, user_login: str | None = None) -> dict:
    """Записать ошибку и вернуть её же — для ответа пользователю."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "message": message[:2000],
        "reference": reference,
        "path": path,
        "user": user_login,
    }
    with _lock:
        _errors.appendleft(entry)
    return entry


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
    }


def clear() -> None:
    """Очистить после разбора — иначе старые ошибки будут выдаваться
    как текущие и запутают разбор."""
    with _lock:
        _errors.clear()