"""Доступ к базе данных.

ВАЖНО (урок отдела, memories/2026/10/2026-10-02-fastapi-sqlite-threadpool):
соединение sqlite3 НЕЛЬЗЯ держать одно на процесс. FastAPI исполняет синхронные
обработчики в пуле потоков, и соединение, созданное в одном потоке, упадёт в
другом с ошибкой «SQLite objects created in a thread can only be used in that
same thread». Поэтому соединение хранится в threading.local() — по одному на
поток. Плюс WAL и busy_timeout, чтобы параллельные читатели не мешали писателю.

Тот же урок вторая половина: проверять соединение нужно НЕ только через
TestClient, а конкурентной нагрузкой (tests/test_concurrency.py).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import settings

_local = threading.local()

SCHEMA_VERSION = 1


def _connect() -> sqlite3.Connection:
    """Создать соединение для текущего потока."""
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        timeout=settings.sqlite_timeout_seconds,
        # Соединение используется только в своём потоке — проверку снимаем,
        # но по одному соединению на поток гарантирует безопасность.
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(settings.sqlite_timeout_seconds * 1000)}")
    return conn


def get_conn() -> sqlite3.Connection:
    """Соединение текущего потока; создаётся при первом обращении."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


def close_thread_conn() -> None:
    """Закрыть соединение текущего потока (вызывается в завершении потока)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            _local.conn = None


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Атомарный блок: ошибка одной операции не должна повреждать другие данные (п.10.1 п.1).

    Вложенные вызовы допускаются: внутренний открывает SAVEPOINT и откатывает
    только свою часть, не затрагивая изменения внешнего блока. Это нужно,
    потому что одна логическая операция состоит из нескольких сервисных
    вызовов: например, подтверждение импорта создаёт карточку (собственная
    транзакция) внутри общей транзакции пакета. Без вложенности внутренний
    BEGIN упал бы с «cannot start a transaction within a transaction».
    """
    conn = get_conn()
    depth = getattr(_local, "tx_depth", 0)
    savepoint = f"sp_{depth}"
    if depth == 0:
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute(f"SAVEPOINT {savepoint}")
    _local.tx_depth = depth + 1
    try:
        yield conn
    except Exception:
        try:
            if depth == 0:
                conn.rollback()
            else:
                conn.execute(f"ROLLBACK TO {savepoint}")
                conn.execute(f"RELEASE {savepoint}")
        finally:
            _local.tx_depth = depth
        raise
    else:
        try:
            if depth == 0:
                conn.commit()
            else:
                conn.execute(f"RELEASE {savepoint}")
        finally:
            _local.tx_depth = depth


def query(sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
    return list(get_conn().execute(sql, params))


def query_one(sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
    return get_conn().execute(sql, params).fetchone()


def scalar(sql: str, params: tuple | dict = (), default: Any = None) -> Any:
    row = get_conn().execute(sql, params).fetchone()
    if row is None or row[0] is None:
        return default
    return row[0]


def execute(sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
    conn = get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur


def execute_many(sql: str, seq: list[tuple | dict]) -> None:
    conn = get_conn()
    conn.executemany(sql, seq)
    conn.commit()


# ---------------------------------------------------------------------------
#  Миграции
# ---------------------------------------------------------------------------

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def applied_migrations(conn: sqlite3.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.commit()
    return {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}


def run_migrations() -> list[str]:
    """Применить ещё не применённые миграции в порядке имени файла."""
    conn = get_conn()
    done = applied_migrations(conn)
    from datetime import datetime, timezone

    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        script = path.read_text(encoding="utf-8")
        try:
            conn.executescript(script)
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (path.name, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            conn.commit()
            applied.append(path.name)
        except Exception:
            conn.rollback()
            raise RuntimeError(f"Миграция {path.name} не применена") from None
    return applied


def reset_database() -> None:
    """Полностью пересоздать базу. Только для тестов и демонстрации."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
    db_path = Path(settings.database_path)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    run_migrations()