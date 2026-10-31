# -*- coding: utf-8 -*-
"""Отпечаток ошибки: одна причина — одна строка разбора.

Проверяем две вещи, ради которых отпечаток и нужен: одинаковая причина,
возникшая у разных пользователей с разными идентификаторами, склеивается,
а разные причины — нет. Если второе сломается, разбор начнёт «чинить» не то.
"""
from app import errors


def setup_function() -> None:
    errors.clear()


def test_same_cause_with_different_ids_shares_fingerprint() -> None:
    first = errors.record(
        "server", "Проект 3f2a1b4c-1111-2222-3333-444455556666 не найден",
        path="/api/projects/3f2a1b4c-1111-2222-3333-444455556666")
    second = errors.record(
        "server", "Проект 9d8e7f60-aaaa-bbbb-cccc-ddddeeeeffff не найден",
        path="/api/projects/9d8e7f60-aaaa-bbbb-cccc-ddddeeeeffff")

    assert first["fingerprint"] == second["fingerprint"]


def test_different_causes_have_different_fingerprints() -> None:
    missing = errors.record("server", "Проект <id> не найден", path="/api/projects/<id>")
    forbidden = errors.record("server", "Недостаточно прав", path="/api/projects")

    assert missing["fingerprint"] != forbidden["fingerprint"]


def test_groups_count_repeats_and_sort_by_frequency() -> None:
    # Одна и та же ошибка повторяется — это и есть типичный случай.
    for _ in range(5):
        errors.record("server", "Ошибка сохранения проекта", path="/api/projects")
    errors.record("client", "Страница не загрузилась", path="/projects")

    result = errors.groups()

    assert len(result) == 2
    assert result[0]["count"] == 5, "частая проблема должна быть первой"
    assert result[0]["kind"] == "server"
    assert result[1]["count"] == 1


def test_summary_counts_problems_not_cases() -> None:
    for _ in range(3):
        errors.record("server", "Ошибка сохранения", path="/api/projects")

    summary = errors.summary()

    assert summary["kept_in_memory"] == 3
    assert summary["unique_problems"] == 1


def test_clear_removes_groups_too() -> None:
    errors.record("server", "Ошибка", path="/api/projects")
    errors.clear()

    assert errors.groups() == []
    assert errors.summary()["unique_problems"] == 0
