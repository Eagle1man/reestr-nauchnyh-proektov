# -*- coding: utf-8 -*-
"""Соединение с SQLite: одновременный старт не должен ронять приложение.

Проверяем то, что ломается на практике: uvicorn поднимает несколько воркеров,
каждый открывает соединение и переключает журнал в WAL. Переключение — операция
над файлом базы, и второй воркер получал «locking protocol»: приложение не
стартовало вовсе. Тест воспроизводит одновременное открытие соединений.
"""
import sqlite3
import threading

from app import db


def test_wal_is_enabled() -> None:
    conn = db.get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert mode.lower() == "wal"


def test_busy_timeout_is_set() -> None:
    conn = db.get_conn()
    timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert timeout > 0


def test_parallel_first_connections_do_not_fail(client) -> None:
    """Несколько потоков впервые открывают базу одновременно — без исключений."""
    db._local = threading.local()
    errors: list[Exception] = []
    start = threading.Barrier(8)

    def open_connection() -> None:
        try:
            start.wait(timeout=10)
            conn = db.get_conn()
            conn.execute("SELECT 1").fetchone()
        except Exception as exc:  # noqa: BLE001 — собираем всё, что вылетит
            errors.append(exc)

    threads = [threading.Thread(target=open_connection) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, "одновременное открытие базы дало ошибки: {}".format(errors)


def test_locking_error_is_retried(monkeypatch, client) -> None:
    """Если переключение журнала всё же упёрлось в блокировку — повторяем."""
    original = sqlite3.connect
    attempts = {"count": 0}

    class FlakyConnection:
        """Первое переключение в WAL падает, второе проходит."""

        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, *args):
            if "journal_mode" in sql and attempts["count"] == 0:
                attempts["count"] += 1
                raise sqlite3.OperationalError("locking protocol")
            return self._conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    monkeypatch.setattr(db.sqlite3, "connect", lambda *a, **k: FlakyConnection(original(*a, **k)))
    db._local = threading.local()

    conn = db.get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert attempts["count"] == 1, "повтор должен был случиться"
    assert mode.lower() == "wal"
