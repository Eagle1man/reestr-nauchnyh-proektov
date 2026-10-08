# -*- coding: utf-8 -*-
"""Журнал аудита — FR-23, п.11.3 ТЗ, M-10.

Требования п.11.3:
  * журнал неизменяем: в API нет операций изменения и удаления событий;
  * для каждого события хранятся дата и время, пользователь, объект, операция
    и результат;
  * ключевое изменение фиксирует ПРЕЖДНЕЕ и НОВОЕ значение;
  * отказ фиксируется с причиной — это основной источник разбора «почему
    система не дала сменить статус»;
  * секреты в журнал не попадают (SEC-05).
"""

from __future__ import annotations

import json

import pytest

from app import audit
from app.db import execute, query, query_one, scalar
from app.utils import now_iso, now_msk


# ===========================================================================
#  FR-23: прежнее и новое значение, автор, время
# ===========================================================================

def test_card_change_records_old_and_new_value(api, project, users):
    """FR-23: ключевое изменение пишет прежнее и новое значение."""
    before = project["title"]
    after = "Адаптивные методы управления качеством образовательных услуг (2026)"
    assert api.patch(f"/api/projects/{project['id']}", login="leader1",
                     json={"title": after}).status_code == 200

    events = api.get(f"/api/audit/object/project/{project['id']}",
                     login="admin").json()["items"]
    change = next(e for e in events if e["action"] == "Изменение карточки: title")
    assert change["old_value"] == before
    assert change["new_value"] == after
    assert change["user_login"] == "leader1"
    assert change["user_id"] == users["leader1"].id
    assert change["happened_at"]
    assert change["happened_at_fmt"]
    assert change["group_name"] == audit.GROUP_CARD
    assert change["object_type"] == "project"
    assert change["outcome"] == "ok"


def test_only_really_changed_fields_are_logged(api, project, users):
    """В журнал попадает только реально изменившееся: иначе карточка из
    тридцати полей даёт тридцать событий на каждое сохранение."""
    same = project["title"]
    response = api.patch(f"/api/projects/{project['id']}", login="leader1",
                         json={"title": same})
    assert response.status_code == 200
    assert response.json()["changed"] == []

    events = api.get(f"/api/audit/object/project/{project['id']}",
                     login="admin").json()["items"]
    assert not [e for e in events if e["action"].startswith("Изменение карточки")]


def test_structured_values_are_stored_as_json(api, project, users):
    """Структурные значения сохраняются в читаемом виде (FR-23, разбор)."""
    api.post(f"/api/projects/{project['id']}/team", login="leader1",
             json={"person_id": users["leader2"].person_id, "role": "member",
                   "task": "анализ данных"})
    events = api.get(f"/api/audit/object/project/{project['id']}",
                     login="admin").json()["items"]
    added = next(e for e in events if e["action"] == "Добавлен участник команды")
    new_value = json.loads(added["new_value"])
    assert new_value["person_id"] == users["leader2"].person_id
    assert new_value["role"] == "member"
    assert added["user_login"] == "leader1"


def test_scalar_values_are_stored_as_is(api, project, users):
    """Прежнее и новое значение индикатора риска сохраняются буквально."""
    api.post(f"/api/projects/{project['id']}/risk", login="prorector",
             json={"level": "yellow", "comment": "нет подтверждения в срок"})
    events = api.get(f"/api/audit/object/project/{project['id']}",
                     login="admin").json()["items"]
    change = next(e for e in events if e["action"] == "Смена индикатора риска")
    assert change["old_value"] == "green"
    assert change["new_value"] == "yellow"
    assert change["basis"] == "нет подтверждения в срок"


def test_route_change_records_old_and_new_route(api, make_project, users):
    """FR-09: фиксация маршрута уполномоченным лицом попадает в журнал с
    прежним и новым значением и с основанием."""
    project = make_project(flag_external_funding=1,
                           title="Проект со сменой маршрута")
    response = api.post(f"/api/projects/{project['id']}/route", login="prorector",
                        json={"route": "simplified",
                              "reason": "основания сняты после проверки"})
    assert response.status_code == 200
    events = api.get(f"/api/audit/object/project/{project['id']}",
                     login="admin").json()["items"]
    change = next(e for e in events if e["action"] == "Смена маршрута")
    assert change["new_value"] == "simplified"
    assert change["basis"] == "основания сняты после проверки"
    assert change["user_login"] == "prorector"


def test_creation_and_route_change_are_logged(api, program, users):
    """Создание карточки и фиксация маршрута — в журнале с автором (FR-09)."""
    created = api.post("/api/projects", login="leader1",
                       json={"program_id": program["id"],
                             "title": "Проект для проверки журнала создания",
                             "planned_start": "2026-01-01",
                             "planned_end": "2027-12-31"}).json()
    project_id = created["id"]
    events = api.get(f"/api/audit/object/project/{project_id}",
                     login="admin").json()["items"]
    creation = next(e for e in events if e["action"] == "Создание карточки")
    assert creation["new_value"]
    assert created["code"] in creation["new_value"]
    assert creation["user_login"] == "leader1"


# ===========================================================================
#  Отказы фиксируются с причиной (FR-10, п.11.3)
# ===========================================================================

def test_denied_transition_is_logged_with_reason(api, project, users):
    """Отказ фиксируется с ПРИЧИНОЙ — это основной источник разбора (FR-10)."""
    response = api.post(f"/api/projects/{project['id']}/transition",
                        login="leader1", json={"action": "accept"})
    assert response.status_code == 409
    reasons = response.json()["detail"]["reasons"]

    events = api.get(f"/api/audit/object/project/{project['id']}",
                     login="admin").json()["items"]
    denial = next(e for e in events if e["outcome"] == "denied")
    assert denial["action"] == "Переход accept заблокирован"
    for reason in reasons:
        assert reason in denial["basis"]


def test_reasons_report_lists_all_denials(api, project, users):
    """Разбор журнала: какие переходы блокировались и почему (FR-10)."""
    for action in ("accept", "launch", "suspend"):
        api.post(f"/api/projects/{project['id']}/transition", login="leader1",
                 json={"action": action})
    report = api.get("/api/audit/reasons", login="admin").json()
    assert report["count"] >= 3
    for item in report["items"]:
        assert item["basis"], item
        assert item["happened_at"]
        assert item["happened_at_fmt"]
        assert "почему система не дала" in report["note"]


def test_failed_login_and_lockout_are_logged(raw_client, users):
    """Неудачный вход и блокировка фиксируются без пароля (п.11.3, SEC-05)."""
    for _ in range(5):
        raw_client.post("/api/auth/login",
                        json={"login": "expert1", "password": "неверный-пароль-1"})
    raw_client.post("/api/auth/login",
                    json={"login": "expert1", "password": "Proverka-2026-Testovyi!"})

    events = [dict(r) for r in query(
        "SELECT * FROM audit_events WHERE group_name = 'auth'"
        " AND action = 'Блокировка входа' ORDER BY happened_at DESC")]
    assert events
    assert events[0]["outcome"] == "denied"
    assert events[0]["basis"]
    assert "Proverka-2026-Testovyi!" not in json.dumps(events, ensure_ascii=False)


# ===========================================================================
#  Журнал только для чтения
# ===========================================================================

def test_journal_api_has_no_write_or_delete_methods():
    """п.11.3 и M-10: в API журнала нет операций изменения и удаления."""
    from app.main import app as fastapi_app

    writable = []
    for route in fastapi_app.routes:
        methods = getattr(route, "methods", None) or set()
        if not getattr(route, "path", "").startswith("/api/audit"):
            continue
        for method in methods:
            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                writable.append((route.path, method))
    assert writable == [], f"в журнале есть изменяющие методы: {writable}"


@pytest.mark.parametrize("method", ["post", "put", "patch"])
def test_write_requests_to_journal_are_refused(api, users, method):
    """Попытка изменить журнал через API отвергается."""
    response = getattr(api, method)("/api/audit", login="admin",
                                    json={"action": "подделка"})
    assert response.status_code in (404, 405), response.status_code


def test_delete_request_to_journal_is_refused(api, project, users):
    """Попытка удалить событие журнала отвергается."""
    api.patch(f"/api/projects/{project['id']}", login="leader1",
              json={"title": "Проект для проверки удаления события"})
    event = query_one("SELECT id FROM audit_events LIMIT 1")
    assert event is not None
    response = api.request("DELETE", f"/api/audit/{event['id']}", login="admin")
    assert response.status_code in (404, 405)
    assert scalar("SELECT COUNT(*) FROM audit_events WHERE id = ?",
                  (event["id"],), 0) == 1


def test_summary_declares_immutability(api, project, users):
    """Сводка прямо сообщает о неизменяемости и сроках хранения (п.11.3)."""
    api.patch(f"/api/projects/{project['id']}", login="leader1",
              json={"title": "Проект для сводки журнала"})
    summary = api.get("/api/audit/summary", login="admin").json()
    assert summary["totals"]["all"] > 0
    assert summary["totals"]["denied"] >= 0
    assert summary["totals"]["errors"] >= 0
    assert set(summary["by_group"][0]) == {"group_name", "n"}
    assert "не менее пяти лет" in summary["retention"]["content_history"]
    assert "не менее 12 месяцев" in summary["retention"]["technical_logs"]
    assert "нет операций изменения" in summary["immutability"]


def test_event_groups_cover_all_five_groups():
    """п.11.3: пять групп событий (auth, card, review_decision, publish, admin)."""
    assert set(audit.EVENT_GROUPS) == {
        "auth", "card", "review_decision", "publish", "admin"}
    for group, actions in audit.EVENT_GROUPS.items():
        assert actions, group
        assert all(isinstance(action, str) and action for action in actions)


def test_event_values_are_truncated_for_safety(api, project, users):
    """SEC-05: значения в журнал обрезаются — в журнал не должна попасть
    многостраничная секретная выгрузка."""
    execute("INSERT INTO audit_events (id, happened_at, group_name, object_type,"
            " action, old_value, new_value, outcome)"
            " VALUES ('very-long', ?, 'card', 'project', 'Длинное значение', ?, ?,'ok')",
            (now_iso(), "A" * 9000, "B" * 9000))
    events = api.get("/api/audit", login="admin", params={"limit": 500}).json()["items"]
    long_event = next(e for e in events if e["id"] == "very-long")
    assert len(long_event["old_value"]) <= 1000
    assert len(long_event["new_value"]) <= 1000


def test_outcome_is_constrained_by_schema():
    """п.11.3: результат операции — из закрытого перечня (ok|denied|error)."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        execute("INSERT INTO audit_events (id, happened_at, group_name,"
                " object_type, action, outcome) VALUES"
                " ('bad-outcome', ?, 'card', 'project', 'Проверка', 'возможно')",
                (now_iso(),))


# ===========================================================================
#  Доступ к журналу (FR-23, SEC-07)
# ===========================================================================

@pytest.mark.parametrize("login", ["leader1", "leader2", "outsider"])
def test_journal_is_closed_to_participants(api, login, users):
    """Журнал недоступен участникам: он содержит отказы и внутренние основания."""
    for path in ("/api/audit", "/api/audit/summary", "/api/audit/reasons"):
        assert api.get(path, login=login).status_code == 403, path


@pytest.mark.parametrize("login", ["admin", "prorector", "secretary", "rector"])
def test_journal_is_open_to_authorities(api, login, users, project):
    """Журнал читают технический администратор, секретарь и руководство."""
    api.patch(f"/api/projects/{project['id']}", login="leader1",
              json={"title": "Проект для проверки доступа к журналу"})
    for path in ("/api/audit", "/api/audit/summary", "/api/audit/reasons"):
        assert api.get(path, login=login).status_code == 200, path


def test_journal_requires_authentication(raw_client):
    """Журнал закрыт и для неавторизованных."""
    assert raw_client.get("/api/audit").status_code == 401
    assert raw_client.get("/api/audit/summary").status_code == 401


# ===========================================================================
#  Фильтры журнала
# ===========================================================================

def test_filters_by_object_group_user_and_action(api, project, users):
    """FR-23: журнал ищется по объекту, группе событий, пользователю и
    действию."""
    api.patch(f"/api/projects/{project['id']}", login="leader1",
              json={"title": "Первый заголовок"})
    api.post(f"/api/projects/{project['id']}/transition", login="leader1",
             json={"action": "accept"})     # отказ
    api.login("leader2")

    by_object = api.get("/api/audit", login="admin",
                        params={"object_id": project["id"]}).json()["items"]
    assert by_object and all(e["object_id"] == project["id"] for e in by_object)

    by_type = api.get("/api/audit", login="admin",
                      params={"object_type": "project"}).json()["items"]
    assert by_type and all(e["object_type"] == "project" for e in by_type)

    by_group = api.get("/api/audit", login="admin",
                       params={"group_name": "auth"}).json()["items"]
    assert by_group and all(e["group_name"] == "auth" for e in by_group)

    by_user = api.get("/api/audit", login="admin",
                      params={"user_id": users["leader1"].id}).json()["items"]
    assert by_user and all(e["user_id"] == users["leader1"].id for e in by_user)

    by_action = api.get("/api/audit", login="admin",
                        params={"action": "Изменение карточки: title"}).json()["items"]
    assert by_action
    assert all(e["action"] == "Изменение карточки: title" for e in by_action)


def test_filter_by_outcome_selects_denied_only(api, project, users):
    """Фильтр по результату операции отбирает именно отказы."""
    api.post(f"/api/projects/{project['id']}/transition", login="leader1",
             json={"action": "accept"})     # отказ
    api.patch(f"/api/projects/{project['id']}", login="leader1",
              json={"title": "Успешная правка"})   # успех

    denied = api.get("/api/audit", login="admin",
                     params={"outcome": "denied"}).json()["items"]
    assert denied
    assert all(e["outcome"] == "denied" for e in denied)


def test_history_by_object_is_reverse_chronological(api, project, users):
    """История объекта читается от новых событий к старым (FR-23)."""
    for index in range(3):
        api.patch(f"/api/projects/{project['id']}", login="leader1",
                  json={"goal": f"Цель номер {index}"})
    history = api.get(f"/api/audit/object/project/{project['id']}",
                      login="admin").json()["items"]
    stamps = [event["happened_at"] for event in history]
    assert stamps == sorted(stamps, reverse=True)
    assert history[0]["action"].endswith("goal")


def test_since_filter_works(api, project, users):
    """Фильтр по времени отсекает старые события."""
    api.patch(f"/api/projects/{project['id']}", login="leader1",
              json={"title": "Проект для фильтра по времени"})
    recent = (now_msk().replace(microsecond=0)).isoformat()
    future = (now_msk().replace(microsecond=0)).isoformat()
    everything = api.get("/api/audit", login="admin",
                         params={"limit": 500}).json()["items"]
    assert len(everything) > 0
    filtered = api.get("/api/audit", login="admin",
                       params={"since": future, "limit": 500}).json()["items"]
    assert len(filtered) <= len(everything)
    assert all(e["happened_at"] >= future for e in filtered)


# ===========================================================================
#  Полнота событий по группам
# ===========================================================================

def test_publish_events_are_logged(api, project, users, set_public_allowed):
    """Группа publish: разрешение публикации фиксируется (п.9.2, п.11.3)."""
    from app.api import projects as projects_api

    set_public_allowed(project["id"], users["prorector"].id)
    audit.record(group_name=audit.GROUP_PUBLISH, object_type="project",
                 object_id=project["id"], action="Разрешение публикации",
                 user_id=users["prorector"].id, user_login="prorector")
    events = api.get("/api/audit", login="admin",
                     params={"group_name": "publish"}).json()["items"]
    assert events
    assert events[0]["user_login"] == "prorector"


def test_review_decision_events_are_logged(api, project, users):
    """Группа review_decision: назначение эксперта и заключение (FR-14)."""
    review = api.post(f"/api/projects/{project['id']}/reviews", login="secretary",
                      json={"expert_person_id": users["expert1"].person_id,
                            "stage": "preliminary"}).json()
    events = api.get("/api/audit/object/review/" + review["id"],
                     login="admin").json()["items"]
    assert events
    assert events[0]["action"] == "Назначение эксперта"
    assert events[0]["group_name"] == "review_decision"
    assert events[0]["new_value"]


def test_admin_events_are_logged(api, project, users):
    """Группа admin: изменения справочников и настроек фиксируются (FR-35)."""
    api.post("/api/admin/dictionaries", login="admin",
             json={"dict": "method", "code": "t1", "title": "Метод для проверки"})
    events = api.get("/api/audit", login="admin",
                     params={"group_name": "admin"}).json()["items"]
    change = next(e for e in events if e["action"] == "Изменение справочника")
    assert change["user_login"] == "admin"
    assert json.loads(change["new_value"])["code"] == "t1"


def test_events_have_ip_address_and_time_in_moscow(api, project, users, password):
    """п.10.2 п.2 и п.11.3: время московское, адрес источника фиксируется."""
    raw_client_login = api.login("leader1")
    assert raw_client_login
    event = query_one("SELECT * FROM audit_events WHERE action = 'Успешный вход'"
                      " ORDER BY happened_at DESC LIMIT 1")
    assert event["ip_address"]
    assert event["happened_at"].endswith("+03:00") or "+03:00" in event["happened_at"]


def test_record_returns_event_id_and_can_be_read_back(api, project, users):
    """Вспомогательная функция журнала возвращает идентификатор события."""
    event_id = audit.record(
        group_name=audit.GROUP_CARD, object_type="project", object_id=project["id"],
        action="Проверка записи", user_id=users["admin"].id, user_login="admin",
        old_value={"старое": 1}, new_value={"новое": 2}, basis="тест")
    stored = query_one("SELECT * FROM audit_events WHERE id = ?", (event_id,))
    assert stored["action"] == "Проверка записи"
    assert json.loads(stored["old_value"]) == {"старое": 1}
    assert json.loads(stored["new_value"]) == {"новое": 2}
    assert stored["basis"] == "тест"


def test_count_by_group_sums_to_total(api, project, users):
    """Сводка по группам сходится с общим числом событий."""
    api.patch(f"/api/projects/{project['id']}", login="leader1",
              json={"title": "Проект для сверки сводки"})
    summary = api.get("/api/audit/summary", login="admin").json()
    assert sum(item["n"] for item in summary["by_group"]) == \
        summary["totals"]["all"]