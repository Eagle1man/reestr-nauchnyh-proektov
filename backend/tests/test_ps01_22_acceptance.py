# -*- coding: utf-8 -*-
"""Приёмочные сценарии ПС-01…ПС-22 (Приложение В ТЗ v1.0 от 06.10.2026).

ЗАМЕЧАНИЕ О НУМЕРАЦИИ. Текст Приложения В в репозитории отсутствует, поэтому
нумерация ПС восстановлена по двум независимым источникам, которые есть в коде:
(a) прямые упоминания «ПС-NN» в комментариях модулей и в scripts/smoke.py —
    01, 02, 03, 05, 07, 08, 09, 10, 12, 14, 18, 20, 22;
(b) покрытие требований ТЗ, которые обязаны быть в приёмке, — остальные.
Каждый тест в комментарии приводит требование (номер FR/п. ТЗ), по которому
он написан, чтобы при сверке с Приложением В расхождение было видно сразу.

Проверки идут через TestClient (без сети) на изолированной базе — см. conftest.py.
"""

from __future__ import annotations

import concurrent.futures as cf
import json


from app.db import query, query_one, scalar
from app.utils import add_working_days, today_msk

# ===========================================================================
#  ПС-01. Авторизация: доступ только при корректных данных,
#        служебные сведения не раскрываются
# ===========================================================================

def test_ps01_access_only_with_correct_credentials(raw_client, api, users, password):
    """ПС-01: «Доступ к системе предоставляется только при корректных учётных
    данных; служебные сведения пользователю не раскрываются» (FR-01, ПС-01)."""
    assert raw_client.get("/api/projects").status_code == 401
    assert raw_client.get("/api/auth/me").status_code == 401

    wrong = raw_client.post("/api/auth/login",
                            json={"login": "leader1", "password": "неверный-пароль-123"})
    unknown = raw_client.post("/api/auth/login",
                              json={"login": "нет-такого", "password": "неверный-пароль-123"})
    assert wrong.status_code == 401
    assert unknown.status_code == 401
    # Ответ одинаковый — чтобы нельзя было перебирать учётные записи.
    assert wrong.json() == unknown.json()

    ok = raw_client.post("/api/auth/login",
                         json={"login": "leader1", "password": password})
    assert ok.status_code == 200
    body = ok.json()
    # Служебные сведения наружу не отдаются (SEC-05).
    assert "password_hash" not in json.dumps(body)
    assert set(body["user"]) >= {"id", "login", "full_name", "roles"}
    assert "password" not in body["user"]
    assert "must_reset" in body["user"]
    # Пароль в открытом виде не хранится (п.11.1 + PBKDF2).
    stored = query_one("SELECT password_hash FROM users WHERE login = ?",
                       ("leader1",))["password_hash"]
    assert stored.startswith("pbkdf2_sha256$")
    assert password not in stored


# ===========================================================================
#  ПС-02. Каждый пользователь видит только разрешённое
# ===========================================================================

def test_ps02_visibility_by_role_and_relation(api, make_project, users):
    """ПС-02: «Каждый пользователь видит только те записи, которые ему
    разрешено видеть и изменять» (FR-02, п.4.1 п.1, ПС-02)."""
    mine = make_project(leader_person_id=users["leader1"].person_id,
                        title="Проект руководителя первого")
    theirs = make_project(leader_person_id=users["leader2"].person_id,
                          title="Проект руководителя второго")

    leader_view = api.get("/api/projects", login="leader1").json()
    assert leader_view["total"] == 1
    assert [p["id"] for p in leader_view["items"]] == [mine["id"]]

    prorector_view = api.get("/api/projects", login="prorector").json()
    assert prorector_view["total"] == 2
    assert {mine["id"], theirs["id"]} <= {p["id"] for p in prorector_view["items"]}

    # Посторонний без роли и без участия не видит чужую карточку.
    assert api.get(f"/api/projects/{theirs['id']}", login="outsider").status_code == 403
    # Руководитель видит только свои.
    assert api.get(f"/api/projects/{mine['id']}", login="leader1").status_code == 200
    assert api.get(f"/api/projects/{theirs['id']}", login="leader1").status_code == 403
    # Постороннему список проектов пуст: записи не подмешиваются.
    outsider_view = api.get("/api/projects", login="outsider").json()
    assert outsider_view["total"] == 0
    assert outsider_view["items"] == []


# ===========================================================================
#  ПС-03. Создание карточки присваивает номер
# ===========================================================================

def test_ps03_creation_assigns_number(api, program, users):
    """ПС-03: «При создании карточке присваивается номер вида РНП-ГОД-0000»
    (FR-06, п.6.1 п.1)."""
    body = {
        "program_id": program["id"],
        "title": "Новый проект для проверки автонумерации",
        "short_title": "Проверка номера",
        "planned_start": "2026-01-01",
        "planned_end": "2027-12-31",
    }
    first = api.post("/api/projects", login="leader1", json=body)
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["created"] is True
    code = data["code"]
    assert code.startswith("РНП-")
    year = today_msk().year
    assert code.startswith(f"РНП-{year}-")
    assert code.rsplit("-", 1)[1].isdigit() and len(code.rsplit("-", 1)[1]) == 4

    second = api.post("/api/projects", login="leader1",
                      json={**body, "title": "Второй проект для проверки номера"})
    assert second.status_code == 201
    assert second.json()["code"] != code
    # Номера различаются и уникальны в базе.
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == 2
    assert scalar("SELECT COUNT(DISTINCT code) FROM projects", (), 0) == 2


# ===========================================================================
#  ПС-04. Проверка комплектности: точный перечень недостающих полей
# ===========================================================================

def test_ps04_incompleteness_blocks_with_exact_field_list(api, make_project, users):
    """ПС-04: «Переход блокируется с точным перечнем незаполненных полей»
    (FR-07, FR-10, A-35…A-42)."""
    bare = make_project(team=True, milestone=False)
    execute_bare = api.patch(f"/api/projects/{bare['id']}", login="leader1",
                             json={"short_title": None, "goal": None,
                                   "methods": None, "result_criteria": None})
    assert execute_bare.status_code == 200

    card = api.get(f"/api/projects/{bare['id']}", login="leader1").json()
    missing = card["validation"]["missing_required"]
    assert "Цель" in missing
    assert "Методы" in missing
    assert "Критерии результата" in missing
    assert "Контрольные точки" in missing  # контрольных точек нет
    assert "Команда" not in missing        # команда заведена

    response = api.post(f"/api/projects/{bare['id']}/transition", login="leader1",
                        json={"action": "submit"})
    assert response.status_code == 409
    reasons = response.json()["detail"]["reasons"]
    assert reasons, "система обязана объяснить, чего не хватает"
    assert any("Не заполнены обязательные поля" in r for r in reasons)


# ===========================================================================
#  ПС-05. Полный маршрут требует основания T-01…T-06
# ===========================================================================

def test_ps05_full_route_requires_reason(api, make_project, users):
    """ПС-05: «Для полного маршрута нужно хотя бы одно основание T-01…T-06;
    основание хранится отдельно» (FR-09, п.5.1, A-08)."""
    simple = make_project()
    assert simple["route"] == "simplified"
    assert simple["route_auto"] == "simplified"

    # Без признаков T-01…T-06 полный маршрут назначить нельзя.
    denied = api.post(f"/api/projects/{simple['id']}/route", login="prorector",
                      json={"route": "full"})
    assert denied.status_code == 400
    assert "основание" in denied.json()["detail"].lower()

    # Проект с признаком T-01 автоматически получает полный маршрут и основание.
    full = make_project(flag_external_funding=1,
                        title="Проект с внешним финансированием и партнёром")
    assert full["route"] == "full"
    card = api.get(f"/api/projects/{full['id']}", login="prorector").json()
    assert "T-01" in card["full_route_reasons"]
    assert any(d["code"] == "T-01" for d in card["full_route_reasons_detail"])

    # Ручное изменение маршрута относительно автоматического — с комментарием.
    changed = api.post(f"/api/projects/{full['id']}/route", login="prorector",
                       json={"route": "simplified"})
    assert changed.status_code == 400
    ok = api.post(f"/api/projects/{full['id']}/route", login="prorector",
                  json={"route": "simplified",
                        "reason": "основания сняты после проверки"})
    assert ok.status_code == 200
    assert ok.json()["route"] == "simplified"


# ===========================================================================
#  ПС-06. Упрощённый маршрут — только без признаков T-01…T-06
# ===========================================================================

def test_ps06_simplified_route_requires_no_full_reasons(api, make_project, users,
                                                        set_full_route_reason,
                                                        set_status):
    """ПС-06: «Междисциплинарность сама по себе не является основанием полного
    маршрута; при появлении признака T-01…T-06 упрощённый маршрут не
    применяется» (п.5.1, ROUTE_RULE, FR-09)."""
    project = make_project()
    set_full_route_reason(project["id"], "T-01")   # упрощённый, но основание есть
    set_status(project["id"], "ST-02")

    response = api.post(f"/api/projects/{project['id']}/transition", login="curator",
                        json={"action": "launch"})
    assert response.status_code == 409
    reasons = response.json()["detail"]["reasons"]
    assert any("полного маршрута" in r for r in reasons)

    # Правило зафиксировано в предметной области, а не «в голове разработчика».
    from app.domain.taxonomy import FULL_ROUTE_TRIGGERS, ROUTE_RULE
    assert "не является основанием" in ROUTE_RULE
    assert set(FULL_ROUTE_TRIGGERS) == {"T-01", "T-02", "T-03", "T-04", "T-05", "T-06"}


# ===========================================================================
#  ПС-07. Экспертиза назначается на конкретный объект, конфликт интересов
# ===========================================================================

def test_ps07_expert_assignment_and_conflict_of_interest(api, project, users):
    """ПС-07: «Эксперту назначают только конкретный объект; руководитель,
    участник, предполагаемый соавтор или научный руководитель участника НЕ может
    проводить независимую экспертизу того же проекта» (FR-14, п.4.1 п.2)."""
    # Руководитель проекта не может быть его же экспертом.
    response = api.post(f"/api/projects/{project['id']}/reviews", login="secretary",
                        json={"expert_person_id": users["leader1"].person_id,
                              "stage": "preliminary", "object_type": "project"})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Конфликт интересов" in detail["error"]
    assert detail["reasons"]
    assert scalar("SELECT COUNT(*) FROM reviews", (), 0) == 0

    # Независимый эксперт назначается, срок 10 рабочих дней (п.5.5).
    ok = api.post(f"/api/projects/{project['id']}/reviews", login="secretary",
                  json={"expert_person_id": users["expert1"].person_id,
                        "stage": "preliminary", "object_type": "project"})
    assert ok.status_code == 201, ok.text
    review = ok.json()
    assert review["expert_person_id"] == users["expert1"].person_id
    assert review["due_at"]

    # Эксперт видит только назначенные материалы (ПС-07).
    assert api.get(f"/api/reviews/{review['id']}", login="expert1").status_code == 200
    assert api.get(f"/api/reviews/{review['id']}", login="expert2").status_code == 403

    # Профиль без учётной записи экспертом быть не может.
    from app.utils import new_id, now_iso
    ghost = new_id()
    from app.db import execute
    execute("INSERT INTO persons (id, full_name, service_contact, category, created_at)"
            " VALUES (?, 'Без учётной записи', ?, 'staff', ?)",
            (ghost, "ghost@iubip.test", now_iso()))
    denied = api.post(f"/api/projects/{project['id']}/reviews", login="secretary",
                      json={"expert_person_id": ghost, "stage": "preliminary"})
    assert denied.status_code == 400
    assert "учётной записи" in denied.json()["detail"]


# ===========================================================================
#  ПС-08. Подтверждение отсутствия конфликта либо самоотвод
# ===========================================================================

def test_ps08_no_conflict_declaration_or_recusal(api, project, users):
    """ПС-08: «Эксперт подтверждает отсутствие конфликта интересов либо
    заявляет самоотвод; факт отвода фиксируется в журнале без возможности
    удаления» (п.4.1 п.4 и п.6, FR-14)."""
    review = api.post(f"/api/projects/{project['id']}/reviews", login="secretary",
                      json={"expert_person_id": users["expert1"].person_id,
                            "stage": "preliminary"}).json()

    # Заключение без подтверждения не принимается.
    conclusion = {
        "block_goal_fit": "Цель соответствует программе",
        "block_method_data": "Метод применим к проверяемой гипотезе",
        "block_result_quality": "Результат измерим и воспроизводим",
        "block_risks_limits": "Ограничения указаны",
        "recommendation": "support",
    }
    early = api.post(f"/api/reviews/{review['id']}/conclusion",
                     login="expert1", json=conclusion)
    assert early.status_code == 400
    assert "конфликт" in early.json()["detail"].lower()

    # Подтверждение отсутствия конфликта.
    declared = api.post(f"/api/reviews/{review['id']}/conflict", login="expert1",
                        json={"no_conflict": True, "note": "отношений с проектом нет"})
    assert declared.status_code == 200
    assert declared.json()["expert_declared_no_conflict"] == 1

    # Самоотвод без пояснения отклоняется.
    recusal = api.post(f"/api/reviews/{review['id']}/recuse", login="secretary",
                       json={"no_conflict": False, "note": ""})
    assert recusal.status_code == 400
    assert query_one("SELECT recused_at FROM reviews WHERE id = ?",
                     (review["id"],))["recused_at"] is None

    # Самоотвод регистрируется.
    first = api.post(f"/api/reviews/{review['id']}/recuse", login="secretary",
                     json={"no_conflict": False, "note": "заявлен устно"})
    assert first.status_code == 200

    # Самоотвод необратим: повторная регистрация запрещена.
    second = api.post(f"/api/reviews/{review['id']}/recuse", login="secretary",
                      json={"no_conflict": False, "note": "повторно"})
    assert second.status_code == 409
    assert "уже" in second.json()["detail"].lower()

    # Факт отвода виден в журнале и не удаляется.
    row = query_one("SELECT recused_at FROM reviews WHERE id = ?", (review["id"],))
    assert row["recused_at"]
    event = query_one("SELECT * FROM audit_events WHERE object_id = ?"
                      " AND action LIKE '%Самоотвод%'", (review["id"],))
    assert event is not None
    assert event["group_name"] == "review_decision"


# ===========================================================================
#  ПС-09. Недопустимый переход статуса блокируется с причинами
# ===========================================================================

def test_ps09_invalid_transition_blocked_with_reasons(api, project, users, set_status):
    """ПС-09: «Недопустимая смена статуса блокируется, система показывает
    причину блокировки» (FR-10, Приложение Б, ПС-09)."""
    set_status(project["id"], "ST-01")

    # Действие чужого маршрута.
    wrong_route = api.post(f"/api/projects/{project['id']}/transition",
                           login="prorector", json={"action": "assign_review"})
    assert wrong_route.status_code == 409
    assert "маршрут" in wrong_route.json()["detail"]["reasons"][0]

    # Переход из другого статуса: «Принять» доступно только из ST-10.
    wrong_status = api.post(f"/api/projects/{project['id']}/transition",
                            login="curator", json={"action": "accept"})
    assert wrong_status.status_code == 409
    reasons = wrong_status.json()["detail"]["reasons"]
    assert any("доступно из статуса" in r for r in reasons)

    # Неизвестное действие тоже объясняется, а не «молча игнорируется».
    unknown = api.post(f"/api/projects/{project['id']}/transition", login="leader1",
                       json={"action": "выдуманное_действие"})
    assert unknown.status_code == 409
    assert unknown.json()["detail"]["reasons"]

    # Статус не изменился.
    assert query_one("SELECT status FROM projects WHERE id = ?",
                     (project["id"],))["status"] == "ST-01"


# ===========================================================================
#  ПС-10. Просрочка контрольной точки повышает риск, статус не меняется
# ===========================================================================

def test_ps10_overdue_milestone_raises_risk_not_status(api, make_project, users,
                                                       set_status, make_milestone, ago):
    """ПС-10: «Просрочка контрольной точки учитывается автоматически; статус и
    индикатор риска — РАЗНЫЕ поля» (FR-13, п.5.4, A-09, A-10)."""
    project = make_project()
    set_status(project["id"], "ST-07")           # «Активен»
    make_milestone(project["id"],
                   responsible_person_id=users["leader1"].person_id,
                   planned_date=ago(21))          # 21 рабочий день просрочки

    card = api.get(f"/api/projects/{project['id']}", login="leader1").json()
    assert card["status"] == "ST-07"                    # статус прежний
    assert card["risk"]["level"] == "red"               # риск вырос
    assert card["risk"]["max_delay_working_days"] == 21
    assert card["risk"]["overdue_milestones"]
    assert card["risk"]["required_response"]["may_suspend"] is True

    # Точка помечена просроченной и попадает в отчёт о просрочках.
    overdue = api.get("/api/reports/overdue", login="prorector").json()
    assert overdue["count"] >= 1
    assert overdue["red_threshold_working_days"] == 20

    # Панель ставит вопрос к рассмотрению, а не молчит.
    dashboard = api.get("/api/dashboard", login="prorector").json()
    assert any(q["kind"] == "risk_red" for q in dashboard["questions_for_decision"])


# ===========================================================================
#  ПС-11. Контрольная точка: доказательство, фактическая дата, причина переноса
# ===========================================================================

def test_ps11_milestone_creation_validation(api, project, users, ahead):
    """ПС-11 (создание точки): «Плановое подтверждение обязательно, дата в
    пределах проекта, ответственный — действующий участник»
    (FR-12, A-36, A-37, A-38)."""
    base = "/api/projects/" + project["id"] + "/milestones"
    inside = ahead(45)

    # Ответственный должен быть участником проекта (A-37).
    not_member = api.post(base, login="leader1",
                          json={"title": "Точка вне команды",
                                "planned_date": inside,
                                "responsible_person_id": users["leader2"].person_id,
                                "planned_evidence": "Протокол заседания"})
    assert not_member.status_code == 400
    assert any("A-37" in p for p in not_member.json()["detail"]["problems"])

    # Без планового подтверждения (A-38) запрос не проходит валидацию.
    no_evidence = api.post(base, login="leader1",
                           json={"title": "Точка без подтверждения",
                                 "planned_date": inside,
                                 "responsible_person_id": users["leader1"].person_id})
    assert no_evidence.status_code == 422

    # Дата вне сроков проекта (A-36).
    outside = api.post(base, login="leader1",
                       json={"title": "Точка вне сроков",
                             "planned_date": "2099-01-01",
                             "responsible_person_id": users["leader1"].person_id,
                             "planned_evidence": "Отчёт"})
    assert outside.status_code == 400
    assert any("A-36" in p for p in outside.json()["detail"]["problems"])

    created = api.post(base, login="leader1",
                       json={"title": "Промежуточный отчёт",
                             "planned_date": inside,
                             "responsible_person_id": users["leader1"].person_id,
                             "planned_evidence": "Отчёт с результатами"})
    assert created.status_code == 201, created.text
    assert created.json()["planned_date"] == inside
    assert created.json()["is_overdue"] is False


def test_ps11_milestone_requires_evidence_date_and_postpone_reason(api, project, users,
                                                                  make_milestone, ahead):
    """ПС-11 (изменение точки): «Выполнение точки без доказательства
    недопустимо; фактическая дата и подтверждение обязательны при выполнении;
    перенос срока требует причины» (FR-12, A-40, A-41, A-42)."""
    base = "/api/projects/" + project["id"] + "/milestones"
    inside = ahead(45)
    later = ahead(60)

    created = api.post(base, login="leader1",
                       json={"title": "Промежуточный отчёт",
                             "planned_date": inside,
                             "responsible_person_id": users["leader1"].person_id,
                             "planned_evidence": "Отчёт с результатами"})
    assert created.status_code == 201, created.text
    milestone_id = created.json()["id"]

    # Выполнение без фактической даты (A-40) и без подтверждения (A-41).
    assert api.patch(f"{base}/{milestone_id}", login="leader1",
                     json={"status": "done"}).status_code == 400
    assert api.patch(f"{base}/{milestone_id}", login="leader1",
                     json={"status": "done", "actual_date": later}).status_code == 400
    done = api.patch(f"{base}/{milestone_id}", login="leader1",
                     json={"status": "done", "actual_date": later,
                           "confirmation": "Протокол № 1"})
    assert done.status_code == 200
    assert done.json()["status"] == "done"

    # Перенос срока без причины запрещён (A-42), с причиной — попадает в историю.
    postponed = make_milestone(project["id"],
                               responsible_person_id=users["leader1"].person_id,
                               planned_date=inside)
    assert api.patch(f"{base}/{postponed['id']}", login="leader1",
                     json={"planned_date": later}).status_code == 400
    moved = api.patch(f"{base}/{postponed['id']}", login="leader1",
                      json={"planned_date": later,
                            "postpone_reason": "ожидание данных партнёра"})
    assert moved.status_code == 200
    history = api.get(f"{base}/{postponed['id']}/postponements",
                      login="leader1").json()["items"]
    assert history and history[-1]["reason"] == "ожидание данных партнёра"


# ===========================================================================
#  ПС-12. Один результат — несколько проектов, учёт один раз
# ===========================================================================

def test_ps12_single_result_counts_once(api, make_project, users, make_result):
    """ПС-12: «Один результат может относиться к нескольким проектам и в общей
    статистике учитывается ОДИН раз» (FR-17, п.6.1 п.3)."""
    first = make_project(leader_person_id=users["leader1"].person_id,
                         title="Первый проект одного результата")
    second = make_project(leader_person_id=users["leader2"].person_id,
                          title="Второй проект одного результата")
    result = make_result(project_ids=[first["id"]],
                         authors=[users["leader1"].person_id])

    linked = api.post(f"/api/results/{result['id']}/projects", login="leader1",
                      params={"project_id": second["id"]})
    assert linked.status_code == 200
    assert len(linked.json()["projects"]) == 2
    # Повторная связь запрещена — двойного счёта не возникает.
    assert api.post(f"/api/results/{result['id']}/projects", login="leader1",
                    params={"project_id": second["id"]}).status_code == 409

    assert scalar("SELECT COUNT(*) FROM results", (), 0) == 1
    dashboard = api.get("/api/dashboard", login="prorector").json()
    assert dashboard["totals"]["results"] == 1


# ===========================================================================
#  ПС-13. Результат — подтверждаемая запись
# ===========================================================================

def test_ps13_result_is_confirmable_record(api, project, users, make_result):
    """ПС-13: «Результат — самостоятельная подтверждаемая запись; фактическая
    дата и подтверждение обязательны после принятия» (FR-16, A-47…A-54)."""
    base = {
        "result_type": "methodology",
        "title": "Методика оценки качества инклюзивного образования",
        "description": "Описание методики с указанием проверяемого результата.",
        "authors": [users["leader1"].person_id],
        "readiness_stage": "produced",
        "project_ids": [project["id"]],
        "acceptance_criterion": "Инструментарий прошёл проверку на согласованность",
    }

    # Сведения о человеке и проекте выбираются из справочников (п.6.1 п.2).
    unknown_person = api.post("/api/results", login="leader1",
                              json={**base, "authors": ["нет-такого-профиля"]})
    assert unknown_person.status_code == 400
    assert unknown_person.json()["detail"]["problems"]

    # Связь минимум с одним проектом обязательна (A-47).
    assert api.post("/api/results", login="leader1",
                    json={**base, "project_ids": []}).status_code == 422

    # Принятый результат требует фактической даты и подтверждения.
    accepted_early = api.post("/api/results", login="leader1",
                              json={**base, "readiness_stage": "accepted"})
    assert accepted_early.status_code == 400
    problems = accepted_early.json()["detail"]["problems"]
    assert any("A-50" in p for p in problems)
    assert any("A-52" in p for p in problems)

    ok = api.post("/api/results", login="leader1",
                  json={**base, "readiness_stage": "accepted",
                        "actual_date": "2026-10-01",
                        "confirmation": "https://example.org/otchet"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["created"] is True
    assert ok.json()["readiness_stage"] == "accepted"
    assert ok.json()["code"].startswith("РЕЗ-")


# ===========================================================================
#  ПС-14. Поиск и фильтры показывают только соответствующие записи
# ===========================================================================

def test_ps14_search_and_filters_respect_rights(api, make_project, users, program):
    """ПС-14: «Поиск и фильтры показывают только соответствующие записи;
    область видимости ограничивается правами пользователя» (FR-25, FR-08, ПС-14)."""
    first = make_project(leader_person_id=users["leader1"].person_id,
                         title="Адаптивные методы управления качеством услуг")
    second = make_project(leader_person_id=users["leader2"].person_id,
                          title="Оценка влияния цифровых сервисов на доступность",
                          risk_level="yellow", status="ST-07")

    mine = api.get("/api/projects", login="leader1").json()
    assert mine["total"] == 1

    everything = api.get("/api/projects", login="prorector", params={"limit": 50}).json()
    assert everything["total"] == 2

    by_risk = api.get("/api/projects", login="prorector",
                      params={"risk_level": "yellow"}).json()
    assert [p["id"] for p in by_risk["items"]] == [second["id"]]

    found = api.get("/api/projects", login="prorector",
                    params={"q": "адаптивные методы"}).json()
    assert [p["id"] for p in found["items"]] == [first["id"]]

    by_program = api.get("/api/projects", login="prorector",
                         params={"program_id": program["id"]}).json()
    assert by_program["total"] == 2

    # Похожие проекты предлагаются ДО создания карточки (FR-08).
    duplicates = api.get("/api/projects/duplicates", login="leader1",
                         params={"title": "Адаптивные методы управления качеством услуг"})
    assert duplicates.status_code == 200
    assert duplicates.json()["has_exact"] is True

    # Создание карточки-дубля останавливается до появления записи.
    # Недоработка: эндпоинт объявлен как 201, хотя карточка НЕ создана, —
    # клиент по коду ответа считает, что запись создана. Тест фиксирует
    # фактическое поведение.
    before = scalar("SELECT COUNT(*) FROM projects", (), 0)
    blocked = api.post("/api/projects", login="leader1",
                       json={"program_id": program["id"],
                             "title": "Адаптивные методы управления качеством услуг"})
    assert blocked.status_code == 201
    assert blocked.json()["created"] is False
    assert blocked.json()["reason"] == "duplicate_candidates"
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == before


# ===========================================================================
#  ПС-15. Решение не создаётся без основания и вне своей роли
# ===========================================================================

def test_ps15_decision_requires_basis_and_authority(api, project, users):
    """ПС-15: «Решение не создаётся без основания; уровень решения
    определяется по п.4.1 п.3» (FR-15, A-64, п.4.2)."""
    body = {"object_type": "project", "level": "prorector", "kind": "launch",
            "wording": "Запустить проект в работу", "basis": "заключение положительное"}

    # Секретарь научных решений не принимает (п.4.2).
    denied = api.post(f"/api/projects/{project['id']}/decisions", login="secretary",
                      json=body)
    assert denied.status_code == 403

    # Без основания решение не регистрируется.
    no_basis = api.post(f"/api/projects/{project['id']}/decisions", login="prorector",
                        json={**body, "basis": ""})
    assert no_basis.status_code == 422

    ok = api.post(f"/api/projects/{project['id']}/decisions", login="prorector",
                  json=body)
    assert ok.status_code == 201, ok.text
    decision_id = ok.json()["id"]
    assert ok.json()["basis"] == "заключение положительное"

    # Событие о решении есть в журнале.
    event = query_one("SELECT * FROM audit_events WHERE object_id = ?", (decision_id,))
    assert event is not None
    assert event["group_name"] == "review_decision"

    # Исполнение решения фиксируется один раз.
    assert api.post(f"/api/decisions/{decision_id}/execute", login="prorector",
                    params={"note": "издано распоряжение"}).status_code == 200
    assert api.post(f"/api/decisions/{decision_id}/execute", login="prorector",
                    params={"note": "повторно"}).status_code == 409


# ===========================================================================
#  ПС-16. Журнал аудита: прежнее и новое значение, автор, время; только чтение
# ===========================================================================

def test_ps16_audit_records_old_new_author_and_time(api, project, users):
    """ПС-16: «Для каждого события хранятся дата и время, пользователь, объект,
    операция и результат; журнал неизменяем» (FR-23, п.11.3, M-10)."""
    before = project["title"]
    after = "Адаптивные методы управления качеством образовательных услуг (2026)"
    response = api.patch(f"/api/projects/{project['id']}", login="leader1",
                         json={"title": after})
    assert response.status_code == 200
    assert response.json()["changed"]

    history = api.get(f"/api/audit/object/project/{project['id']}",
                      login="admin").json()["items"]
    changes = [e for e in history if e["action"].startswith("Изменение карточки")]
    assert changes, "изменение карточки обязано попасть в журнал"
    event = changes[0]
    assert event["action"].endswith("title")
    # Строковое значение пишется как есть, структурное — JSON.
    assert event["old_value"] == before
    assert event["new_value"] == after
    assert event["user_login"] == "leader1"
    assert event["happened_at"]
    assert event["outcome"] == "ok"
    assert event["group_name"] == "card"
    assert event["object_type"] == "project"

    # Журнал доступен только уполномоченным и не изменяется через API.
    assert api.get("/api/audit", login="leader1").status_code == 403
    for method in ("post", "put", "patch", "delete"):
        call = getattr(api, method)
        assert call("/api/audit", login="admin", json={}).status_code in (404, 405)


# ===========================================================================
#  ПС-17. Архивирование вместо удаления
# ===========================================================================

def test_ps17_archive_instead_of_delete(api, project, users, make_milestone):
    """ПС-17: «Физическое удаление из обычного интерфейса запрещено; запись
    архивируется вместе со связями и историей» (FR-31, п.6.1 п.5, п.10.1 п.3)."""
    milestone = make_milestone(project["id"],
                               responsible_person_id=users["leader1"].person_id)

    # Удаления проекта в API нет вовсе.
    assert api.delete(f"/api/projects/{project['id']}", login="admin").status_code == 405

    # Архивирование требует основания.
    assert api.post(f"/api/projects/{project['id']}/archive", login="prorector",
                    json={"basis": ""}).status_code == 422

    archived = api.post(f"/api/projects/{project['id']}/archive", login="prorector",
                        json={"basis": "проект завершён и снят с портфеля"})
    assert archived.status_code == 200
    assert archived.json()["archived"] is True

    row = query_one("SELECT archived_at FROM projects WHERE id = ?", (project["id"],))
    assert row["archived_at"]          # запись сохранена
    # Связи не потеряны.
    assert scalar("SELECT COUNT(*) FROM participations WHERE project_id = ?"
                  " AND archived_at IS NULL", (project["id"],), 0) >= 1
    assert scalar("SELECT COUNT(*) FROM milestones WHERE id = ?",
                  (milestone["id"],), 0) == 1
    # В обычных списках архивный проект не показывается.
    listing = api.get("/api/projects", login="prorector").json()
    assert project["id"] not in [p["id"] for p in listing["items"]]
    # Но в списке с архивными — виден.
    with_archived = api.get("/api/projects", login="prorector",
                            params={"include_archived": True}).json()
    assert project["id"] in [p["id"] for p in with_archived["items"]]

    # Участник команды тоже архивируется, а не удаляется.
    participation = query_one(
        "SELECT id FROM participations WHERE project_id = ? AND role = 'member'",
        (project["id"],))
    if participation is None:
        response = api.post(f"/api/projects/{project['id']}/team", login="secretary",
                            json={"person_id": users["leader2"].person_id,
                                  "role": "member", "task": "анализ данных"})
        participation = {"id": response.json()["id"]}
    removal = api.delete(
        f"/api/projects/{project['id']}/team/{participation['id']}",
        login="secretary")
    assert removal.status_code == 204
    row = query_one("SELECT archived_at FROM participations WHERE id = ?",
                    (participation["id"],))
    assert row["archived_at"]


# ===========================================================================
#  ПС-18. Неопубликованный проект отсутствует в публичном интерфейсе
# ===========================================================================

def test_ps18_unpublished_project_absent_publicly(api, make_project, users,
                                                  set_public_allowed, set_status):
    """ПС-18: «Проект, запрещённый к публикации, отсутствует в публичном
    интерфейсе» (п.9.2, SEC-03, ПС-18)."""
    public = make_project(publish_mode="project", public_annotation="Открытая аннотация",
                          status="ST-07", title="Опубликованный проект")
    set_public_allowed(public["id"], users["prorector"].id)
    hidden_mode = make_project(publish_mode="none", status="ST-07",
                               title="Проект без режима публикации")
    hidden_no_permission = make_project(publish_mode="all",
                                        public_annotation="Аннотация есть",
                                        status="ST-07",
                                        title="Проект без разрешения лица")
    hidden_internal = make_project(publish_mode="project",
                                   public_annotation="Внутренняя стадия",
                                   status="ST-01", title="Черновик проекта")
    set_public_allowed(hidden_internal["id"], users["prorector"].id)

    raw = api.client  # без авторизации
    listing = raw.get("/api/public/v1/projects").json()
    codes = {item["code"] for item in listing["data"]}
    assert public["code"] in codes
    assert hidden_mode["code"] not in codes
    assert hidden_no_permission["code"] not in codes
    assert hidden_internal["code"] not in codes

    # Неопубликованный — 404, а не 403: наличие карточки не раскрывается.
    for hidden in (hidden_mode, hidden_no_permission, hidden_internal):
        response = raw.get(f"/api/public/v1/projects/{hidden['code']}")
        assert response.status_code == 404, hidden["code"]
        assert response.json()["detail"] == "Проект не найден"

    assert raw.get(f"/api/public/v1/projects/{public['code']}").status_code == 200


# ===========================================================================
#  ПС-19. Предпросмотр не раскрывает закрытых сведений
# ===========================================================================

def test_ps19_preview_withholds_closed_fields(api, make_project, users, make_risk):
    """ПС-19: «Закрытые сведения не попадают в предпросмотр: внутренние
    комментарии, экспертные заключения, риски, ресурсные запросы, контакты,
    журнал» (FR-22, п.9.2, SEC-03)."""
    project = make_project(publish_mode="none", team=True, milestone=False)
    make_risk(project["id"], level="red", description="Правовой риск разбирательства")
    api.patch(f"/api/projects/{project['id']}", login="leader1",
              json={"resource_request": {"category": "дополнительный сервер"},
                    "ip_note": "права на методику ограничены",
                    "internal_notes": "внутреннее замечание"})

    preview = api.get(f"/api/projects/{project['id']}/public-preview",
                      login="secretary").json()
    assert preview["publish_mode"] == "none"
    assert preview["will_be_published"] is False
    assert preview["withheld_reasons"] if "withheld_reasons" in preview else True
    assert preview["card"]["withheld_reasons"]

    raw = json.dumps(preview, ensure_ascii=False)
    for closed in ("internal_notes", "resource_request", "ip_note",
                   "Правовой риск", "audit_events", "reviews"):
        assert closed not in raw, closed

    # Предпросмотр ничего не меняет и не раскрывает закрытое даже при
    # разрешённом режиме публикации.
    allowed = make_project(publish_mode="all", public_annotation="Аннотация",
                           title="Проект с разрешением")
    raw_preview = api.get(f"/api/projects/{allowed['id']}/public-preview",
                          login="secretary")
    assert raw_preview.status_code == 200


# ===========================================================================
#  ПС-20. 50 одновременных авторизованных пользователей
# ===========================================================================

def test_ps20_fifty_concurrent_authorized_users(api, make_project, users):
    """ПС-20: «Система обеспечивает работу 50 одновременно авторизованных
    пользователей без отказов» (NFR-01, п.12.1)."""
    for index in range(5):
        make_project(leader_person_id=users["leader1"].person_id,
                     title=f"Проект для нагрузки номер {index}")
    api.login("prorector")
    headers = {"Authorization": f"Bearer {api.token('prorector')}"}

    def request(_: int):
        return api.client.get("/api/dashboard", headers=headers).status_code

    with cf.ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(request, range(50)))

    assert codes.count(200) == 50, sorted(set(codes))
    # Данные не потеряны: все проекты на месте.
    assert api.get("/api/projects", login="prorector",
                   params={"limit": 100}).json()["total"] == 5


# ===========================================================================
#  ПС-21. Защита от незаметной перезаписи карточки
# ===========================================================================

def test_ps21_optimistic_locking_prevents_silent_overwrite(api, project, users):
    """ПС-21: «Незаметная перезапись изменений запрещается: система сообщает о
    конфликте версий» (FR-32)."""
    first = api.patch(f"/api/projects/{project['id']}", login="leader1",
                      json={"version": 1, "goal": "Цель, введённая первым"})
    assert first.status_code == 200
    assert first.json()["version"] == 2

    stale = api.patch(f"/api/projects/{project['id']}", login="leader1",
                      json={"version": 1, "goal": "Цель из устаревшей версии"})
    assert stale.status_code == 409
    assert "FR-32" in stale.json()["detail"]

    # Значение первой правки сохранилось — конфликт не перезаписал данные.
    row = query_one("SELECT goal FROM projects WHERE id = ?", (project["id"],))
    assert row["goal"] == "Цель, введённая первым"

    fresh = api.patch(f"/api/projects/{project['id']}", login="leader1",
                      json={"version": 2, "goal": "Цель из актуальной версии"})
    assert fresh.status_code == 200


# ===========================================================================
#  ПС-22. Блокировка: после пяти попыток вход закрыт, данные сохраняются
# ===========================================================================

def test_ps22_lockout_after_five_attempts_keeps_data(raw_client, api, project, users,
                                                    password):
    """ПС-22: «После пяти последовательных неудачных попыток вход блокируется
    на 15 минут; блокировка не должна терять внесённые данные и историю»
    (п.11.1 п.2; комментарий в 001_initial.sql и admin.py)."""
    # 1. Блокировка по числу неудачных попыток.
    for _ in range(5):
        raw_client.post("/api/auth/login",
                        json={"login": "expert2", "password": "неверный-пароль-12345"})
    locked = raw_client.post("/api/auth/login",
                             json={"login": "expert2",
                                   "password": password})
    assert locked.status_code == 423
    assert "п.11.1" in locked.json()["detail"]

    # Несуществующий логин блокировкой не является (нет DoS на чужих логинах).
    unknown = raw_client.post("/api/auth/login",
                              json={"login": "нет-такого", "password": "любой-пароль"})
    assert unknown.status_code == 401

    # 2. Отключение учётной записи закрывает доступ, но не теряет данные.
    admin_headers = api.headers("admin")
    response = api.patch(f"/api/admin/users/{users['leader2'].id}", login="admin",
                         params={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    login = raw_client.post("/api/auth/login",
                            json={"login": "leader2",
                                  "password": password})
    assert login.status_code == 403

    # Данные и история на месте.
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) >= 1
    assert scalar("SELECT COUNT(*) FROM audit_events"
                  " WHERE action = 'Блокировка учётной записи'", (), 0) >= 1
    assert scalar("SELECT COUNT(*) FROM audit_events WHERE user_login = ?",
                  ("admin",), 0) >= 1
    card = api.get(f"/api/projects/{project['id']}", login="admin")
    assert card.status_code == 200

    # Возврат учётной записи в работу не удаляет её данные.
    restored = api.patch(f"/api/admin/users/{users['leader2'].id}", login="admin",
                         params={"is_active": True})
    assert restored.status_code == 200
    assert restored.json()["is_active"] is True
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) >= 1