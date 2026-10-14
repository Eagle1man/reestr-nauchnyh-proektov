# -*- coding: utf-8 -*-
"""Справочник интерфейса /api/projects/taxonomy.

Дефект, который закрывает этот файл (найден 14.10.2026 при сборке демо
для GitHub Pages): эндпоинт отдавал 500 при ЛЮБОМ вызове. Причина —
разворот словаря, который содержит код → заголовок (строку), как будто
это словарь объектов:

    {"code": code, **spec} for code, spec in FULL_ROUTE_TITLES.items()
    TypeError: 'str' object is not a mapping

Почему это не поймали 399 проверок: ни один тест не вызывал эндпоинт,
а в test_concurrency путь был осознанно исключён из обхода с пометкой
«известный дефект». То есть проверка проходила не потому, что система
работала, а потому, что этот адрес не посещали.

Отсюда правило, которое теперь держит файл: любой эндпоинт, который
вызывает интерфейс, должен быть вызван хотя бы одной проверкой с
настоящим ответом 200. Иначе «зелёный набор» ничего не доказывает.
"""

from __future__ import annotations


def test_taxonomy_returns_200(api, users):
    """Справочник отдаётся авторизованному пользователю и не падает."""
    response = api.get("/api/projects/taxonomy", login="secretary")
    assert response.status_code == 200, (
        f"справочник вернул {response.status_code}: {response.text[:300]}")


def test_taxonomy_shape_matches_frontend_expectations(api, users):
    """Форма ответа совпадает с тем, что читает интерфейс.

    Frontend ждёт (frontend/src/pages/Projects.tsx и NewProject.tsx):
      statuses:             { code, title, content }[]
      routes:               Record<string, string>
      full_route_triggers:  { code, title, fields }[]
      route_rule:           string
      publish_modes:        Record<string, string>
      risk_levels:          Record<string, string>
    """
    body = api.get("/api/projects/taxonomy", login="secretary").json()

    for key in ("statuses", "routes", "full_route_triggers", "route_rule",
                "publish_modes", "risk_levels", "active_statuses",
                "field_dictionary"):
        assert key in body, f"в справочнике нет ключа {key}"

    assert isinstance(body["route_rule"], str) and body["route_rule"]

    for item in body["statuses"]:
        assert set(("code", "title", "content")) <= set(item), (
            f"статус {item} описан не полностью")
    assert len(body["statuses"]) == 12, "ожидались 12 статусов ST-01…ST-12"

    triggers = body["full_route_triggers"]
    assert len(triggers) == 6, f"ожидались признаки T-01…T-06, получено {len(triggers)}"
    for item in triggers:
        # Именно этот ключ ломает эндпоинт, если взять не тот словарь:
        # fields есть у FULL_ROUTE_TRIGGERS и отсутствует у FULL_ROUTE_TITLES.
        assert set(("code", "title", "fields")) <= set(item), (
            f"признак {item} описан не полностью — интерфейс ждёт поля")
        assert isinstance(item["fields"], list)

    assert {item["code"] for item in triggers} == {
        "T-01", "T-02", "T-03", "T-04", "T-05", "T-06"}


def test_taxonomy_requires_login(api):
    """Без входа справочник не отдаётся — закрытая зона закрыта."""
    response = api.get("/api/projects/taxonomy")
    assert response.status_code == 401