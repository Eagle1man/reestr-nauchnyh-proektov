# -*- coding: utf-8 -*-
"""Матрица переходов статуса — Приложение Б ТЗ (FR-10, п.5.3).

Матрица проверяется в двух слоях:
  * предметный слой (app.domain.workflow) — каждый переход разрешён из своего
    статуса нужным исполнителем и запрещён оттуда, откуда не должен быть;
  * слой API — те же правила через /api/projects/{id}/transition.

Запрещённый переход обязан давать ПРИЧИНУ, а не молча отказывать (FR-10).
"""

from __future__ import annotations

import pytest

from app.db import query, scalar
from app.domain.taxonomy import (
    ACTIVE_STATUSES, ROUTE_FULL, ROUTE_SIMPLIFIED, ST_ACTIVE, ST_CLOSED,
    STATUS_TITLES, STATUSES,
)
from app.domain.workflow import (
    ACTOR_CURATOR, ACTOR_LEADER, ACTOR_PRORECTOR, ACTOR_SECRETARY,
    FULL_TRANSITIONS, SIMPLIFIED_TRANSITIONS, TRANSITIONS, TransitionContext,
    available_actions, check_transition, find_transition,
)

ALL_TRANSITIONS = (
    [(ROUTE_SIMPLIFIED, t) for t in SIMPLIFIED_TRANSITIONS]
    + [(ROUTE_FULL, t) for t in FULL_TRANSITIONS]
)

#: Подписи параметризованных проверок
LABELS = [f"{route}-{t.action}" for route, t in ALL_TRANSITIONS]


def satisfied_context(transition) -> TransitionContext:  # noqa: D401
    """Контекст, в котором ВСЕ условия перехода выполнены."""
    context = TransitionContext(
        missing_required=[],
        full_route_reasons=[],
        has_linked_result=True,
        result_has_confirmation=True,
        has_final_review=True,
        positive_final_review=True,
    )
    if transition.guard == "not_required_fields":
        # «Вернуть» имеет смысл, только когда есть чего не хватает.
        context.missing_required = ["Цель"]
    if transition.guard == "has_full_reasons":
        context.full_route_reasons = ["T-01"]
    return context


def reason_for(transition) -> str | None:
    return "основание по п.4.2" if transition.reason_required else None


# ---------------------------------------------------------------------------
#  Целостность самой матрицы
# ---------------------------------------------------------------------------

def test_matrix_covers_only_known_statuses_and_unique_actions():
    """Все статусы матрицы — из ST-01…ST-12, действия уникальны внутри маршрута."""
    for route, transitions in TRANSITIONS.items():
        actions = [t.action for t in transitions]
        assert len(actions) == len(set(actions)), f"повтор действия в маршруте {route}"
        for transition in transitions:
            assert transition.from_status in STATUSES
            assert transition.to_status in STATUSES
            assert transition.actors, f"у {route}/{transition.action} нет исполнителя"
            assert transition.condition, f"у {route}/{transition.action} нет условия"


def test_simplified_and_full_routes_have_distinct_action_sets():
    """Приложение Б.1 и Б.2 — разные маршруты: переход полного маршрута
    недоступен упрощённому и наоборот."""
    simplified = {t.action for t in SIMPLIFIED_TRANSITIONS}
    full = {t.action for t in FULL_TRANSITIONS}
    # «Назначить экспертизу» — только полный маршрут.
    assert "assign_review" in full and "assign_review" not in simplified
    # «Запустить» есть в обоих, но с разными исполнителями и условиями.
    assert "launch" in simplified and "launch" in full
    assert find_transition(ROUTE_SIMPLIFIED, "assign_review") is None
    assert find_transition(ROUTE_FULL, "to_full_route") is None


# ---------------------------------------------------------------------------
#  Каждый переход разрешён из своего статуса
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ALL_TRANSITIONS,
                         ids=[f"{r}-{t.action}" for r, t in ALL_TRANSITIONS])
def test_transition_allowed_from_its_own_status(case):
    """Переход из предусмотренного статуса нужным исполнителем разрешён."""
    route, transition = case
    check = check_transition(
        route=route, status=transition.from_status, action=transition.action,
        actor_roles=set(transition.actors), ctx=satisfied_context(transition),
        reason=reason_for(transition),
    )
    assert check.allowed, check.reasons


@pytest.mark.parametrize("case", ALL_TRANSITIONS,
                         ids=[f"{r}-{t.action}" for r, t in ALL_TRANSITIONS])
def test_transition_forbidden_from_every_other_status(case):
    """Из любого ДРУГОГО статуса переход запрещён, и система объясняет почему
    (FR-10: «недопустимая смена статуса блокируется, показывается причина»)."""
    route, transition = case
    for status in STATUSES:
        if status == transition.from_status:
            continue
        check = check_transition(
            route=route, status=status, action=transition.action,
            actor_roles=set(transition.actors), ctx=satisfied_context(transition),
            reason=reason_for(transition),
        )
        assert not check.allowed, (route, transition.action, status)
        assert any("доступно из статуса" in reason for reason in check.reasons), (
            route, transition.action, status, check.reasons)


@pytest.mark.parametrize("case", ALL_TRANSITIONS,
                         ids=[f"{r}-{t.action}" for r, t in ALL_TRANSITIONS])
def test_transition_forbidden_for_wrong_actor(case):
    """Исполнитель не из указанного в матрице ролей — отказ с объяснением."""
    route, transition = case
    other_actors = {ACTOR_SECRETARY, ACTOR_PRORECTOR, ACTOR_CURATOR, ACTOR_LEADER}
    wrong = sorted(other_actors - set(transition.actors))
    assert wrong, f"у {route}/{transition.action} не осталось посторонних исполнителей"
    for actor in wrong:
        check = check_transition(
            route=route, status=transition.from_status, action=transition.action,
            actor_roles={actor}, ctx=satisfied_context(transition),
            reason=reason_for(transition),
        )
        assert not check.allowed, (route, transition.action, actor)
        assert any("доступно:" in reason for reason in check.reasons)


@pytest.mark.parametrize("case", ALL_TRANSITIONS,
                         ids=[f"{r}-{t.action}" for r, t in ALL_TRANSITIONS])
def test_transition_requires_reason_when_matrix_says_so(case):
    """Если по матрице нужно основание (reason_required), без комментария
    переход запрещён (FR-15, A-64)."""
    route, transition = case
    if not transition.reason_required:
        check = check_transition(
            route=route, status=transition.from_status, action=transition.action,
            actor_roles=set(transition.actors), ctx=satisfied_context(transition),
            reason=None,
        )
        assert check.allowed, check.reasons
        return
    for empty in (None, "", "   "):
        check = check_transition(
            route=route, status=transition.from_status, action=transition.action,
            actor_roles=set(transition.actors), ctx=satisfied_context(transition),
            reason=empty,
        )
        assert not check.allowed
        assert any("обязателен комментарий" in reason for reason in check.reasons)


# ---------------------------------------------------------------------------
#  Условия переходов (guards)
# ---------------------------------------------------------------------------

def test_submit_requires_all_required_fields():
    """«Подать» невозможно, пока не заполнены обязательные поля (FR-07)."""
    transition = find_transition(ROUTE_SIMPLIFIED, "submit")
    context = satisfied_context(transition)
    check = check_transition(route=ROUTE_SIMPLIFIED, status=transition.from_status,
                             action="submit", actor_roles={ACTOR_LEADER},
                             ctx=context, reason=None)
    assert check.allowed

    context.missing_required = ["Цель", "Методы"]
    denied = check_transition(route=ROUTE_SIMPLIFIED, status=transition.from_status,
                              action="submit", actor_roles={ACTOR_LEADER},
                              ctx=context, reason=None)
    assert not denied.allowed
    assert any("Не заполнены обязательные поля" in r for r in denied.reasons)
    assert any("Цель" in r and "Методы" in r for r in denied.reasons)


def test_return_requires_something_to_return_for():
    """«Вернуть» невозможно, если недостающих сведений нет (FR-07)."""
    transition = find_transition(ROUTE_SIMPLIFIED, "return")
    denied = check_transition(
        route=ROUTE_SIMPLIFIED, status=transition.from_status, action="return",
        actor_roles={ACTOR_SECRETARY},
        ctx=TransitionContext(missing_required=[]), reason="уточнить")
    assert not denied.allowed
    assert any("возвращать карточку не на что" in r for r in denied.reasons)


def test_simplified_launch_blocked_by_full_route_reasons():
    """«Запустить» упрощённого проекта запрещено при признаках T-01…T-06."""
    transition = find_transition(ROUTE_SIMPLIFIED, "launch")
    context = satisfied_context(transition)
    context.full_route_reasons = ["T-02", "T-03"]
    denied = check_transition(route=ROUTE_SIMPLIFIED, status=transition.from_status,
                              action="launch", actor_roles={ACTOR_CURATOR},
                              ctx=context, reason=None)
    assert not denied.allowed
    assert any("T-02" in r and "T-03" in r for r in denied.reasons)


def test_submit_result_requires_linked_result_with_confirmation():
    """«Представить результат» требует связанного результата с подтверждением
    (FR-16, A-47, A-52)."""
    transition = find_transition(ROUTE_SIMPLIFIED, "submit_result")

    no_result = TransitionContext(has_linked_result=False)
    assert not check_transition(route=ROUTE_SIMPLIFIED, status=transition.from_status,
                                action="submit_result", actor_roles={ACTOR_LEADER},
                                ctx=no_result).allowed

    no_confirmation = TransitionContext(has_linked_result=True,
                                        result_has_confirmation=False)
    denied = check_transition(route=ROUTE_SIMPLIFIED, status=transition.from_status,
                              action="submit_result", actor_roles={ACTOR_LEADER},
                              ctx=no_confirmation)
    assert not denied.allowed
    assert any("подтверждающий" in r for r in denied.reasons)

    ok = check_transition(route=ROUTE_SIMPLIFIED, status=transition.from_status,
                          action="submit_result", actor_roles={ACTOR_LEADER},
                          ctx=satisfied_context(transition))
    assert ok.allowed


def test_accept_requires_positive_final_review():
    """«Принять» только по положительному заключению (п.7.1, A-53)."""
    transition = find_transition(ROUTE_FULL, "accept")

    without_review = TransitionContext(has_final_review=False,
                                       positive_final_review=False)
    assert not check_transition(route=ROUTE_FULL, status=transition.from_status,
                                action="accept", actor_roles={ACTOR_PRORECTOR},
                                ctx=without_review).allowed

    negative = TransitionContext(has_final_review=True, positive_final_review=False)
    denied = check_transition(route=ROUTE_FULL, status=transition.from_status,
                              action="accept", actor_roles={ACTOR_PRORECTOR},
                              ctx=negative)
    assert not denied.allowed
    assert any("Поддержать" in r for r in denied.reasons)

    ok = check_transition(route=ROUTE_FULL, status=transition.from_status,
                          action="accept", actor_roles={ACTOR_PRORECTOR},
                          ctx=satisfied_context(transition))
    assert ok.allowed


def test_to_decision_requires_registered_review():
    """«Направить на решение» — только после регистрации заключения (FR-14)."""
    transition = find_transition(ROUTE_FULL, "to_decision")
    denied = check_transition(route=ROUTE_FULL, status=transition.from_status,
                              action="to_decision", actor_roles={ACTOR_SECRETARY},
                              ctx=TransitionContext(has_final_review=False))
    assert not denied.allowed
    assert any("Заключение эксперта не зарегистрировано" in r for r in denied.reasons)


def test_to_full_route_requires_full_reasons():
    """«Перевести на полный маршрут» запрещено без признаков T-01…T-06."""
    transition = find_transition(ROUTE_SIMPLIFIED, "to_full_route")
    denied = check_transition(route=ROUTE_SIMPLIFIED, status=transition.from_status,
                              action="to_full_route", actor_roles={ACTOR_PRORECTOR},
                              ctx=TransitionContext(full_route_reasons=[]))
    assert not denied.allowed
    assert any("T-01…T-06" in r for r in denied.reasons)

    ok = check_transition(route=ROUTE_SIMPLIFIED, status=transition.from_status,
                          action="to_full_route", actor_roles={ACTOR_PRORECTOR},
                          ctx=TransitionContext(full_route_reasons=["T-04"]))
    assert ok.allowed
    assert find_transition(ROUTE_SIMPLIFIED, "to_full_route").switches_to_full


def test_unknown_action_is_refused_with_reason():
    """Несуществующее действие отвергается с объяснением, а не «падает»."""
    check = check_transition(route=ROUTE_FULL, status=ST_ACTIVE,
                             action="придумать", actor_roles={ACTOR_PRORECTOR},
                             ctx=TransitionContext())
    assert not check.allowed
    assert any("не предусмотрено" in r for r in check.reasons)


# ---------------------------------------------------------------------------
#  available_actions — что доступно пользователю «прямо сейчас»
# ---------------------------------------------------------------------------

def test_available_actions_lists_only_current_status_actions():
    """В списке действий только переходы ИЗ текущего статуса."""
    transition = find_transition(ROUTE_FULL, "launch")
    context = satisfied_context(transition)
    actions = available_actions(ROUTE_FULL, transition.from_status,
                                {ACTOR_PRORECTOR}, context)
    assert actions, "у уполномоченного лица есть действия в статусе ST-05"
    assert {a["action"] for a in actions} == {
        t.action for t in FULL_TRANSITIONS if t.from_status == transition.from_status}
    for action in actions:
        assert action["condition"]
        assert "blocked_reasons" in action


def test_available_actions_blocks_by_role_and_reports_reasons():
    """Секретарь в статусе ST-05 не видит действий уполномоченного лица."""
    context = TransitionContext()
    assert available_actions(ROUTE_FULL, "ST-05", {ACTOR_SECRETARY}, context) == []
    secretarial = available_actions(ROUTE_FULL, "ST-02", {ACTOR_SECRETARY}, context)
    assert {a["action"] for a in secretarial} == {"return", "assign_review"}


def test_available_actions_reports_why_action_is_not_allowed():
    """Недоступное по условию действие показывается с причиной блокировки."""
    context = TransitionContext(missing_required=["Цель"])
    actions = {a["action"]: a for a in available_actions(
        ROUTE_SIMPLIFIED, "ST-01", {ACTOR_LEADER}, context)}
    submit = actions["submit"]
    assert submit["allowed"] is False
    assert any("Цель" in reason for reason in submit["blocked_reasons"])


# ---------------------------------------------------------------------------
#  Тот же закон на уровне API
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ALL_TRANSITIONS,
                         ids=[f"{r}-{t.action}" for r, t in ALL_TRANSITIONS])
def test_api_rejects_transition_from_wrong_status(api, project, users, set_status,
                                                  case):
    """Через API переход из чужого статуса тоже блокируется с 409 и причинами."""
    route, transition = case
    status = "ST-07" if transition.from_status != ST_ACTIVE else "ST-11"
    set_status(project["id"], status)
    response = api.post(f"/api/projects/{project['id']}/transition",
                        login="prorector",
                        json={"action": transition.action,
                              "reason": "основание"})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "Переход невозможен"
    assert detail["reasons"]


def test_api_transition_reasons_are_readable_in_russian(api, project, users):
    """Причины блокировки показываются пользователю, а не внутренними кодами
    (FR-10 + п.10.2 — сообщения на русском)."""
    from app.db import execute
    execute("UPDATE projects SET status = 'ST-01' WHERE id = ?", (project["id"],))
    execute("UPDATE projects SET goal = NULL, methods = NULL, result_criteria = NULL"
            " WHERE id = ?", (project["id"],))

    response = api.post(f"/api/projects/{project['id']}/transition", login="leader1",
                        json={"action": "submit"})
    assert response.status_code == 409
    reasons = response.json()["detail"]["reasons"]
    assert reasons
    for reason in reasons:
        assert reason == reason.strip()
        assert reason[0].isupper()
        assert "ST-" not in reason


def test_api_transition_endpoint_lists_allowed_actions(api, project, users, set_status):
    """Карточка и /transitions показывают именно те действия, что доступны."""
    set_status(project["id"], "ST-02")
    listed = api.get(f"/api/projects/{project['id']}/transitions", login="secretary")
    assert listed.status_code == 200
    body = listed.json()
    assert body["status"] == "ST-02"
    assert {a["action"] for a in body["actions"]} <= {t.action for t in SIMPLIFIED_TRANSITIONS}

    card = api.get(f"/api/projects/{project['id']}", login="secretary").json()
    assert card["actions"] == body["actions"]


def test_api_successful_transition_changes_status_and_keeps_history(api, project, users,
                                                                    set_status):
    """Разрешённый переход меняет статус, и это попадает в журнал (FR-10, FR-23)."""
    set_status(project["id"], "ST-01")
    response = api.post(f"/api/projects/{project['id']}/transition", login="leader1",
                        json={"action": "submit"})
    assert response.status_code == 200, response.text
    assert response.json()["from_status"] == "ST-01"
    assert response.json()["to_status"] == "ST-02"
    assert query_one_status(project["id"]) == "ST-02"

    events = query("SELECT * FROM audit_events WHERE object_id = ? ORDER BY happened_at",
                   (project["id"],))
    changes = [e for e in events if e["action"].startswith("Смена статуса")]
    assert changes and changes[-1]["old_value"] == "ST-01"
    assert changes[-1]["new_value"] == "ST-02"


def test_api_terminal_statuses_have_no_outgoing_transitions(api, project, users):
    """Из ST-11 и ST-12 переходов нет: проекты завершены или закрыты."""
    from app.db import execute
    for status in (ST_CLOSED, "ST-11"):
        execute("UPDATE projects SET status = ? WHERE id = ?", (status, project["id"]))
        response = api.post(f"/api/projects/{project['id']}/transition", login="prorector",
                            json={"action": "launch", "reason": "основание"})
        assert response.status_code == 409
        reasons = response.json()["detail"]["reasons"]
        assert any("доступно из статуса" in r for r in reasons)
    assert ST_ACTIVE in ACTIVE_STATUSES
    assert STATUS_TITLES[ST_ACTIVE] == "Активен"
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == 1


def test_completeness_report_ignores_filled_program_and_leader(api, project, users):
    """Заполненные программа и руководитель не должны попадать в список
    незаполненных полей (FR-07)."""
    card = api.get(f"/api/projects/{project['id']}", login="leader1").json()
    assert card["program_id"] == project["program_id"]
    assert card["leader_person_id"] == project["leader_person_id"]
    assert card["counts"]["team"] >= 1
    assert card["counts"]["milestones"] >= 1
    missing = card["validation"]["missing_required"]
    assert "Научная программа" not in missing
    assert "Руководитель" not in missing


def test_missing_fields_are_named_like_appendix_a(api, project, users):
    """FR-07, п.10.2 п.1: незаполненные поля показываются названиями Приложения А.

    Проверка найдена на интерфейсе: одна позиция Приложения А закрывает два поля
    карточки («Плановые даты» = planned_start и planned_end), и название искалось
    сравнением со строкой целиком. Объединённые поля не находились, и
    пользователю показывалось служебное `planned_start` вместо «Плановое начало».
    """
    card = api.get(f"/api/projects/{project['id']}", login="leader1").json()
    missing = card["validation"]["missing_required"]
    assert all("_" not in item for item in missing), (
        f"в списке незаполненных есть имена столбцов: {missing}")
    # Плановые даты объединяют два поля, поэтому у каждого своё название —
    # иначе пользователь не поймёт, какое именно из них заполнять.
    if not card["planned_start"]:
        assert "Плановое начало (A-11)" in missing
    if not card["planned_end"]:
        assert "Плановое завершение (A-11)" in missing


def test_card_shows_program_title_not_identifier(api, project, users):
    """п.10.2 п.1: в карточке показывается название программы, а не её UUID.

    Найдено на интерфейсе: список проектов отдавал название программы, а
    карточка — внутренний идентификатор, и это выглядело как ошибка.
    """
    from app.db import query_one
    card = api.get(f"/api/projects/{project['id']}", login="leader1").json()
    program = query_one("SELECT code, title FROM programs WHERE id = ?",
                        (project["program_id"],))
    assert card["program_title"] == program["title"]
    assert card["program_code"] == program["code"]


def query_one_status(project_id: str) -> str:
    from app.db import query_one
    return query_one("SELECT status FROM projects WHERE id = ?", (project_id,))["status"]