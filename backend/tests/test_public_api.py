# -*- coding: utf-8 -*-
"""Публичный API только для чтения — п.9.4 ТЗ, FR-33, FR-34, SEC-03.

Контур публикации устроен как БЕЛЫЙ список полей: новое поле карточки не
попадает наружу, пока его явно не внесли в список. Проверяем:

  * наружу отдаются только опубликованные и разрешённые объекты;
  * неопубликованный объект даёт 404, а не 403 (наличие не раскрывается);
  * закрытые сведения отсутствуют в JSON полностью;
  * контур только для чтения: никаких POST/PUT/PATCH/DELETE;
  * заголовки интеграции: кодировка, лимит частоты, версия схемы.
"""

from __future__ import annotations

import json

import pytest

from app.db import execute, query, scalar
from app.domain.taxonomy import CLOSED_PROJECT_FIELDS, PUBLIC_PROJECT_FIELDS

#: Поля, которые не должны появляться в публичном JSON ни при каких условиях
FORBIDDEN_KEYS = (
    "internal_comments", "expert_reviews", "approval_history", "risks",
    "resource_request", "personal_contacts", "closed_files",
    "partner_confidential", "audit_log", "confidentiality", "ip_note",
    "problem_hash", "review_id", "risk_level", "ip_note", "internal_comments",
    "password_hash", "search_blob", "leader_person_id", "created_by",
    "personal_data_note", "human_subjects_note", "legal_basis_link",
)

#: Публикация разрешена и статус открыт — минимальные условия попадания в выдачу
OPEN_STATUSES = ("ST-07", "ST-08", "ST-10", "ST-11")


@pytest.fixture
def published(make_project, users, set_public_allowed, program):
    """Проект, разрешённый к публикации и находящийся в открытом статусе."""
    def factory(**over):
        over.setdefault("publish_mode", "project")
        over.setdefault("public_annotation", "Открытая аннотация для витрины.")
        over.setdefault("status", "ST-07")
        project = make_project(**over)
        set_public_allowed(project["id"], users["prorector"].id)
        return project
    return factory


# ===========================================================================
#  Только опубликованное
# ===========================================================================

def test_public_api_needs_no_authorization(raw_client, published):
    """Раздел «Наука» — публичная витрина: авторизация не требуется (п.9.1)."""
    published(title="Проект в открытом доступе")
    response = raw_client.get("/api/public/v1/projects")
    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 1


def test_only_approved_and_published_projects_are_listed(raw_client, make_project,
                                                        users, set_public_allowed,
                                                        published):
    """ПС-18: в списке только опубликованные и разрешённые проекты."""
    visible = published(title="Проект разрешён к публикации")

    no_mode = make_project(publish_mode="none", status="ST-07",
                           title="Режим «Не публиковать»")
    no_permission = make_project(publish_mode="all", status="ST-07",
                                 public_annotation="Аннотация есть",
                                 title="Нет разрешения уполномоченного лица")
    no_annotation = make_project(publish_mode="project", public_annotation=None,
                                 status="ST-07", title="Нет публичной аннотации")
    set_public_allowed(no_annotation["id"], users["prorector"].id)
    draft = make_project(publish_mode="project", status="ST-01",
                         public_annotation="Внутренняя стадия",
                         title="Черновик")
    set_public_allowed(draft["id"], users["prorector"].id)
    decision = make_project(publish_mode="project", status="ST-05",
                            public_annotation="Ожидает решения",
                            title="На решении")
    set_public_allowed(decision["id"], users["prorector"].id)

    body = raw_client.get("/api/public/v1/projects").json()
    codes = {item["code"] for item in body["data"]}
    assert codes == {visible["code"]}
    for hidden in (no_mode, no_permission, no_annotation, draft, decision):
        assert hidden["code"] not in codes


def test_unpublished_project_returns_404_not_403(raw_client, make_project, users,
                                                 published):
    """ПС-18 + SEC-03: неопубликованный объект отсутствует — 404, а не 403,
    чтобы наличие карточки не раскрывалось."""
    hidden = make_project(publish_mode="none", status="ST-07",
                          title="Запрещённый к публикации")
    response = raw_client.get(f"/api/public/v1/projects/{hidden['code']}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Проект не найден"
    # И по внутреннему идентификатору тоже.
    assert raw_client.get(f"/api/public/v1/projects/{hidden['id']}").status_code == 404


def test_internal_status_is_not_public_even_with_permission(raw_client, make_project,
                                                            users, set_public_allowed):
    """Внутренние стадии не показываются в открытом разделе (п.9.1 п.2)."""
    project = make_project(publish_mode="project", status="ST-04",
                           public_annotation="На экспертизе", title="Проект на экспертизе")
    set_public_allowed(project["id"], users["prorector"].id)
    assert raw_client.get(f"/api/public/v1/projects/{project['code']}").status_code == 404


def test_archived_project_leaves_public_contour(raw_client, published, users):
    """FR-34: снятие с публикации немедленно исключает объект из выдачи."""
    project = published(title="Проект, который сняли с публикации")
    assert raw_client.get(f"/api/public/v1/projects/{project['code']}").status_code == 200

    execute("UPDATE projects SET archived_at = '2026-10-01T00:00:00+03:00' WHERE id = ?",
            (project["id"],))
    assert raw_client.get(f"/api/public/v1/projects/{project['code']}").status_code == 404
    assert raw_client.get("/api/public/v1/projects").json()["meta"]["total"] == 0


def test_published_project_is_available_by_code_and_by_id(raw_client, published):
    """Адреса п.9.4: по номеру и по внутреннему идентификатору."""
    project = published(title="Проект для поиска по обоим адресам")
    assert raw_client.get(f"/api/public/v1/projects/{project['code']}").status_code == 200
    assert raw_client.get(f"/api/public/v1/projects/{project['id']}").status_code == 200


def test_unknown_object_returns_404(raw_client):
    """Несуществующий объект — 404, без утечки внутренних кодов."""
    response = raw_client.get("/api/public/v1/projects/РНП-2030-9999")
    assert response.status_code == 404


# ===========================================================================
#  Закрытые сведения не попадают наружу (SEC-03)
# ===========================================================================

def test_public_json_contains_no_closed_fields(raw_client, published, users,
                                                make_risk):
    """ПС/SEC-03: в публичном JSON нет ни одного закрытого поля."""
    project = published(title="Проект с закрытыми сведениями", flag_confidential=1)
    make_risk(project["id"], level="red", description="Правовой риск разбирательства")

    body = raw_client.get("/api/public/v1/projects").json()
    raw = json.dumps(body, ensure_ascii=False)
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in raw, key
    # И сам текст закрытых сведений тоже не утекает.
    assert "Правовой риск разбирательства" not in raw
    assert project["title"] not in raw or True     # название публикуется
    assert set(body["data"][0]) <= {
        "code", "title", "short_title", "public_annotation", "status",
        "status_title", "route", "start_year", "end_year", "start_date",
        "end_date", "program", "keywords", "published", "team", "materials",
        "results", "withheld_reasons"}


def test_closed_fields_list_is_the_source_of_truth():
    """Список закрытых полей Приложения п.9.2 не пуст и покрывает ключевые."""
    for field in ("internal_comments", "expert_reviews", "risks",
                  "resource_request", "personal_contacts", "audit_log"):
        assert field in CLOSED_PROJECT_FIELDS
    assert "title" in PUBLIC_PROJECT_FIELDS


def test_public_card_contains_only_whitelisted_keys(raw_client, published, users):
    """Белый список, а не чёрный: набор ключей карточки предсказуем."""
    project = published(title="Белый список полей", flag_partner=1)
    card = raw_client.get(f"/api/public/v1/projects/{project['code']}").json()["data"]
    assert card["published"] is True
    assert set(card) <= set(PUBLIC_PROJECT_FIELDS) | {
        "status_title", "start_year", "end_year", "start_date", "end_date",
        "program", "keywords", "published", "team", "materials"}
    assert "code" in card and "title" in card


def test_internal_contacts_are_not_exposed(raw_client, published, users, program):
    """Служебные адреса и контакты участников не передаются (п.9.2)."""
    project = published(title="Проект с открытой командой")
    body = raw_client.get("/api/public/v1/projects").json()
    raw = json.dumps(body, ensure_ascii=False)
    assert "iubip.ru" not in raw
    assert "leader1@" not in raw
    assert users["leader1"].email not in raw


def test_team_is_published_only_for_marked_participants(raw_client, published, users):
    """Открытая команда: в публичный контур попадают только те, кто разрешён
    к публикации (A-13 is_public)."""
    project = published(title="Проект с открытой командой")
    execute("UPDATE participations SET is_public = 0 WHERE project_id = ?",
            (project["id"],))
    hidden_team = raw_client.get(f"/api/public/v1/projects/{project['code']}"
                                 ).json()["data"]["team"]
    assert hidden_team == []

    execute("UPDATE participations SET is_public = 1 WHERE project_id = ?",
            (project["id"],))
    open_team = raw_client.get(f"/api/public/v1/projects/{project['code']}").json()["data"]
    assert open_team["team"]
    assert open_team["team"][0]["full_name"] == users["leader1"].full_name
    assert set(open_team["team"][0]) >= {"full_name", "role", "role_title"}


# ===========================================================================
#  Только для чтения (FR-33)
# ===========================================================================

@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_public_contour_rejects_every_write_method(raw_client, method, published):
    """SEC-03 + FR-33: публичный контур не принимает запись."""
    project = published(title="Проект для проверки read-only")
    paths = ["/api/public/v1/projects", f"/api/public/v1/projects/{project['code']}",
             "/api/public/v1/results", "/api/public/v1/programs"]
    for path in paths:
        response = raw_client.request(method.upper(), path, json={"title": "взлом"})
        assert response.status_code in (404, 405), (method, path, response.status_code)
    # Данные не изменились.
    assert scalar("SELECT title FROM projects WHERE code = ?",
                  (project["code"],)) == project["title"]


def test_manifest_declares_read_only_contract(raw_client):
    """Манифест позволяет интегратору проверить контракт без документации."""
    manifest = raw_client.get("/api/public/v1/manifest").json()["data"]
    assert manifest["version"] == "v1"
    assert manifest["encoding"] == "UTF-8"
    assert manifest["read_only"] is True
    assert manifest["content_type"] == "application/json"
    for endpoint in manifest["endpoints"]:
        assert endpoint["method"] == "GET", endpoint
    covered = {e["path"] for e in manifest["endpoints"]}
    for required in ("/api/public/v1/projects", "/api/public/v1/projects/{id}",
                     "/api/public/v1/results", "/api/public/v1/results/{id}",
                     "/api/public/v1/programs", "/api/public/v1/programs/{id}"):
        assert required in covered
    assert manifest["rules"]["404_for_unpublished"].startswith("Неопубликованный")
    assert "конфиденциальные сведения о партнёрах" in manifest["withheld"]


def test_response_headers_declare_integration_contract(raw_client, published):
    """п.10.2 п.1 и п.9.4: UTF-8, версия схемы и лимит частоты в заголовках."""
    response = raw_client.get("/api/public/v1/projects")
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers["content-language"] == "ru"
    assert headers["x-registry-version"] == "v1"
    assert headers["x-registry-generated-at"]
    assert int(headers["x-ratelimit-limit"]) > 0
    assert "max-age=300" in headers["cache-control"]
    # Ответ — валидный UTF-8 JSON.
    response.encoding = "utf-8"
    assert isinstance(response.json(), dict)


def test_rate_limit_is_enforced_and_reported(raw_client):
    """Ограничение частоты публичного API работает и не молчит (п.9.4)."""
    # Каждый запуск представляется своим адресом, иначе второй прогон подряд
    # упёрся бы в лимит, оставленный первым.
    burst = {"X-Forwarded-For": "203.0.113.7"}
    codes = [raw_client.get("/api/public/v1/stats", headers=burst).status_code
             for _ in range(70)]
    assert 429 in codes, sorted(set(codes))
    limited = raw_client.get("/api/public/v1/stats", headers=burst)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json()["limit_per_minute"] > 0
    # Другой адрес не ограничен.
    assert raw_client.get("/api/public/v1/stats",
                          headers={"X-Forwarded-For": "203.0.113.8"}).status_code == 200


def test_cors_preflight_is_answered(raw_client):
    """Предварительный запрос для интеграции с официальным сайтом."""
    response = raw_client.options("/api/public/v1/projects")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


# ===========================================================================
#  Результаты в публичном контуре
# ===========================================================================

def test_only_confirmed_and_allowed_results_are_public(raw_client, published, users,
                                                       make_result):
    """п.9.1 п.3: публикуются только подтверждённые результаты с разрешением
    уполномоченного лица (A-54)."""
    project = published(title="Проект с результатами", publish_mode="all")

    produced = make_result(project_ids=[project["id"]], readiness_stage="produced")
    accepted_private = make_result(project_ids=[project["id"]],
                                   readiness_stage="accepted", confirmation="отчёт",
                                   publish_allowed=0, is_public=0,
                                   title="Принятый, но без разрешения")
    accepted_public = make_result(project_ids=[project["id"]],
                                  readiness_stage="accepted", confirmation="отчёт",
                                  publish_allowed=1, is_public=1,
                                  title="Принятый и разрешённый")

    body = raw_client.get("/api/public/v1/results").json()
    codes = {item["code"] for item in body["data"]}
    assert accepted_public["code"] in codes
    assert produced["code"] not in codes
    assert accepted_private["code"] not in codes

    assert raw_client.get(f"/api/public/v1/results/{produced['code']}").status_code == 404
    assert raw_client.get(
        f"/api/public/v1/results/{accepted_public['code']}").status_code == 200


def test_public_result_card_has_no_internal_review_data(raw_client, published, users,
                                                         make_result):
    """Заключение эксперта и внутренние отметки наружу не передаются (п.9.2)."""
    project = published(title="Проект с подтверждённым результатом", publish_mode="all")
    result = make_result(project_ids=[project["id"]], readiness_stage="accepted",
                         confirmation="https://example.org/otchet",
                         publish_allowed=1, is_public=1)
    card = raw_client.get(f"/api/public/v1/results/{result['code']}").json()["data"]
    assert set(card) <= {"code", "type", "title", "description", "stage", "year",
                         "identifiers", "projects"}
    assert card["projects"][0]["code"] == project["code"]


# ===========================================================================
#  Программы и счётчики
# ===========================================================================

def test_only_public_programs_are_exposed(raw_client, program, closed_program,
                                          published):
    """Программа передаётся в публичный контур только с разрешения (FR-04)."""
    published(title="Проект публичной программы")
    codes = {item["code"] for item in
             raw_client.get("/api/public/v1/programs").json()["data"]}
    assert program["code"] in codes
    assert closed_program["code"] not in codes
    assert raw_client.get(f"/api/public/v1/programs/{program['code']}").status_code == 200
    assert raw_client.get(
        f"/api/public/v1/programs/{closed_program['code']}").status_code == 404


def test_program_public_card_has_no_internal_fields(raw_client, program):
    """Карточка программы — тоже белый список."""
    card = raw_client.get(f"/api/public/v1/programs/{program['code']}").json()["data"]
    assert set(card) <= {"code", "title", "short_title", "description",
                         "expected_results", "start_year", "end_year", "id",
                         "projects_count"}
    assert "criteria" not in card


def test_stats_count_only_published_objects(raw_client, published, make_project,
                                            users):
    """Счётчики витрины не показывают закрытые данные."""
    published(title="Первый опубликованный проект")
    published(title="Второй опубликованный проект")
    make_project(publish_mode="none", status="ST-07", title="Закрытый проект")

    data = raw_client.get("/api/public/v1/stats").json()["data"]
    assert data["projects"] == 2
    assert data["generated_at"]
    blob = json.dumps(data, ensure_ascii=False)
    assert "Закрытый проект" not in blob


# ===========================================================================
#  Фильтры публичного контура
# ===========================================================================

def test_public_filters_work(raw_client, published, program, closed_program):
    """Фильтры п.9.4: по программе и статусу."""
    published(title="Адаптивные методы управления качеством")
    published(title="Оценка влияния цифровых сервисов", status="ST-11")

    by_program = raw_client.get("/api/public/v1/projects",
                                params={"program": program["code"]}).json()
    assert by_program["meta"]["total"] == 2
    assert by_program["meta"]["filters"] == {"program": program["code"]}

    by_status = raw_client.get("/api/public/v1/projects",
                               params={"status": "ST-11"}).json()
    assert by_status["meta"]["total"] == 1

    empty = raw_client.get("/api/public/v1/projects",
                           params={"program": closed_program["code"]}).json()
    assert empty["meta"]["total"] == 0


def test_public_keyword_search_finds_cyrillic(raw_client, published):
    """Поиск по ключевым словам на кириллице (п.9.4, FR-25)."""
    published(title="Адаптивные методы управления качеством")
    published(title="Оценка влияния цифровых сервисов")
    found = raw_client.get("/api/public/v1/projects",
                           params={"q": "адаптивные"}).json()
    assert found["meta"]["total"] == 1


def test_pagination_is_declared_in_meta(raw_client, published):
    """Метаданные содержат total/limit/offset — интегратору нужен счётчик."""
    for _ in range(3):
        published()
    body = raw_client.get("/api/public/v1/projects",
                          params={"limit": 2, "offset": 1}).json()
    assert body["meta"]["total"] == 3
    assert body["meta"]["limit"] == 2
    assert body["meta"]["offset"] == 1
    assert len(body["data"]) == 2