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
from collections import deque
from datetime import datetime, timedelta, timezone

#: Сколько последних ошибок держим. Круг небольшой: нужен разбор последней
#: сессии, а не журнал за месяц.
MAX_ERRORS = 200

#: Сколько групп отпечатков показывать. Проблем всегда меньше, чем записей;
#: если групп больше двадцати, это уже не разбор, а свалка.
MAX_GROUPS = 20

_lock = threading.Lock()
_errors: deque[dict] = deque(maxlen=MAX_ERRORS)

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
           path: str | None = None, user_login: str | None = None) -> dict:
    """Записать ошибку и вернуть её же — для ответа пользователю."""
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