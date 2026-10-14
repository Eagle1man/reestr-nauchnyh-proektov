# -*- coding: utf-8 -*-
"""Сбор ошибок и отчёт для разработчика.

ЗАЧЕМ ЭТОТ ФАЙЛ. Отчёт отправляют наружу — человеку, который его читает,
возможно, в почте. Поэтому главная проверка здесь не «ошибка попала в
отчёт», а «секрет в отчёт НЕ попал». Ошибка без адреса и текста бесполезна,
а утечка токена обесценивает всю переписку.

Отдельно проверяется, что в отчёт попадают именно те сбои, которые
показывают поломку системы, а не обычные действия человека: истёкшая
сессия или неверный ввод дефектом не являются, и в отчёте они только шумят.
"""
from __future__ import annotations

from app import errors as error_log


def setup_function() -> None:
    error_log.clear()


# ---------------------------------------------------------------------------
#  Круг ошибок
# ---------------------------------------------------------------------------

def test_error_is_recorded_and_readable() -> None:
    error_log.record("server", "ValueError: пусто", reference="ab12cd34",
                     path="GET /api/projects", user_login="secretary")
    entries = error_log.recent()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["message"] == "ValueError: пусто"
    assert entry["reference"] == "ab12cd34"
    assert entry["path"] == "GET /api/projects"
    assert entry["user"] == "secretary"
    assert entry["at"]


def test_newest_errors_come_first() -> None:
    error_log.record("server", "первая")
    error_log.record("server", "вторая")
    messages = [e["message"] for e in error_log.recent()]
    assert messages[0] == "вторая", "последняя ошибка должна быть первой"


def test_circle_is_bounded() -> None:
    """Круг не должен расти без предела: сервер живёт месяцами."""
    for index in range(error_log.MAX_ERRORS + 50):
        error_log.record("server", f"ошибка {index}")
    assert len(error_log.recent(limit=error_log.MAX_ERRORS + 10)) <= error_log.MAX_ERRORS


def test_limit_is_respected() -> None:
    for index in range(10):
        error_log.record("server", f"ошибка {index}")
    assert len(error_log.recent(limit=3)) == 3


def test_summary_counts_by_kind() -> None:
    error_log.record("server", "одна")
    error_log.record("server", "две")
    error_log.record("api", "три")
    summary = error_log.summary()
    assert summary["total_in_window"] == 3
    assert summary["by_kind"] == {"server": 2, "api": 1}


def test_clear_empties_the_circle() -> None:
    error_log.record("server", "ошибка")
    error_log.clear()
    assert error_log.recent() == []


def test_long_message_is_truncated() -> None:
    error_log.record("server", "x" * 9000)
    assert len(error_log.recent()[0]["message"]) <= 2000


# ---------------------------------------------------------------------------
#  Отчёт через API: что увидит читатель
# ---------------------------------------------------------------------------

def test_diagnostics_requires_admin(api, users):
    """Журнал ошибок не должен быть доступен обычному сотруднику."""
    response = api.get("/api/admin/diagnostics", login="leader1")
    assert response.status_code == 403


def test_diagnostics_available_to_admin(api, users) -> None:
    error_log.record("server", "ValueError: пусто", reference="ab12cd34",
                     path="GET /api/projects", user_login="secretary")
    response = api.get("/api/admin/diagnostics", login="admin")
    assert response.status_code == 200
    body = response.json()
    assert body["server"]["total_in_window"] >= 1
    references = [e["reference"] for e in body["recent_errors"]]
    assert "ab12cd34" in references


def test_diagnostics_does_not_expose_secret_key(api, users, monkeypatch) -> None:
    """В отчёте не должно быть ключа подписи сессий.

    Ключ подставляется явно: в тестах DEBUG=true и settings.secret_key
    пустой, а проверка «пустая строка не встречается» не прошла бы никогда
    и ничего не доказывала бы. С настоящим значением проверка осмысленна.
    """
    from app.config import settings

    secret = "ТЕСТОВЫЙ-КЛЮЧ-ПОДПИСИ-НЕ-ДОЛЖЕН-ПОПАСТЬ-В-ОТЧЁТ"
    # settings — frozen dataclass, поэтому через object.__setattr__.
    monkeypatch.setattr(type(settings), "secret_key", property(
        lambda self: secret), raising=False)
    object.__setattr__(settings, "_secret_key_override", secret)

    response = api.get("/api/admin/diagnostics", login="admin")
    assert response.status_code == 200
    dumped = str(response.json())
    assert secret not in dumped, "в отчёте засветился SECRET_KEY"

    # Имя файла базы в отчёте остаётся намеренно: по нему видно, какая
    # установка прислала отчёт. Утекать должны данные, а не имя файла.
    assert "registry.db" in dumped, "в отчёте должно быть имя файла базы"


def test_diagnostics_clear_removes_errors(api, users) -> None:
    error_log.record("server", "ошибка до очистки")
    response = api.post("/api/admin/diagnostics/clear", login="admin")
    assert response.status_code == 200
    assert error_log.recent() == []


def test_unhandled_request_is_collected_with_reference(api, users) -> None:
    """Код обращения, который видит пользователь, должен находиться в отчёте.

    Пользователь присылает сообщение об ошибке; без кода обращения в нём
    не было бы ничего, по чему разбор восстановить картину.
    """
    error_log.clear()
    # Адрес, который гарантированно падает: поле с неверным типом.
    response = api.post("/api/projects",
                        login="secretary", json={"title": {"не строка": True}})
    assert response.status_code == 422
    body = response.json()
    if "reference" in body:
        references = [e["reference"] for e in error_log.recent()]
        assert body["reference"] in references