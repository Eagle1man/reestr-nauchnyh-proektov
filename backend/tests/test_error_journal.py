# -*- coding: utf-8 -*-
"""Журнал ошибок в базе: история для разбора.

Три свойства, ради которых журнал сделан:
  * запись переживает «перезапуск» (читается из базы, а не из памяти);
  * в журнале есть роль, но НЕТ логина — сведения о сбое не должны
    становиться сведениями о человеке (SEC-05);
  * отпечаток склеивает повторы, поэтому разбор идёт по проблемам.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import errors
from app.db import get_conn


@pytest.fixture(autouse=True)
def clean_journal(client):
    """Журнал живёт в базе теста: чистим до и после, чтобы не мешал соседям."""
    errors.clear()
    get_conn().execute("DELETE FROM error_events")
    get_conn().commit()
    yield
    get_conn().execute("DELETE FROM error_events")
    get_conn().commit()


def test_event_is_stored_and_survives_memory_clear() -> None:
    errors.record("server", "Ошибка сохранения проекта", path="PATCH /api/projects")
    # Имитируем перезапуск: память пуста, журнал остался.
    errors.clear()

    stored = errors.stored_groups()

    assert len(stored) == 1
    assert stored[0]["count"] == 1
    assert stored[0]["path"] == "PATCH /api/projects"


def test_repeats_are_counted_as_one_problem() -> None:
    for _ in range(4):
        errors.record("server", "Ошибка сохранения проекта", path="PATCH /api/projects")

    stored = errors.stored_groups()

    assert len(stored) == 1
    assert stored[0]["count"] == 4
    assert stored[0]["first_seen"] <= stored[0]["last_seen"]


def test_login_is_not_stored_only_role() -> None:
    errors.record("server", "Ошибка", role="secretary", user_login="ivanov")

    row = get_conn().execute(
        "SELECT role, message FROM error_events ORDER BY id DESC LIMIT 1").fetchone()

    assert row["role"] == "secretary"
    assert "ivanov" not in str(dict(row))


def test_old_events_are_not_shown_in_the_window() -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=errors.RETENTION_DAYS + 5))
    get_conn().execute(
        "INSERT INTO error_events (fingerprint, kind, message, occurred_at) "
        "VALUES (?, ?, ?, ?)",
        ("old0000000000000", "server", "старая ошибка", old.isoformat(timespec="seconds")),
    )
    get_conn().commit()

    assert errors.stored_groups() == []


def test_journal_counts_differ_from_memory_ring() -> None:
    """Память — про текущую сессию, журнал — про историю. Это разные числа."""
    errors.record("server", "Ошибка", path="/api/projects")
    summary = errors.summary()

    assert summary["kept_in_memory"] == 1
    assert summary["unique_problems"] == 1
    assert len(errors.stored_groups()) == 1


def test_diagnostics_exposes_history_for_admin(api, users) -> None:
    errors.record("server", "Ошибка сохранения проекта", path="PATCH /api/projects")

    response = api.get("/api/admin/diagnostics", login="admin")

    assert response.status_code == 200
    body = response.json()
    assert body["problems"], "текущая сессия должна быть видна"
    assert body["stored_problems"], "история для разбора тоже"
    assert body["stored_problems"][0]["count"] >= 1
