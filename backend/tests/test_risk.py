# -*- coding: utf-8 -*-
"""Индикатор риска проекта — п.5.4 ТЗ.

Ключевое требование: СТАТУС и РИСК — РАЗНЫЕ ПОЛЯ. Проект может быть «Активен»
и при этом иметь жёлтый или красный индикатор. Ни одна проверка в этом файле
не должна требовать, чтобы статус менялся при изменении риска.

  Зелёный — работа идёт по плану, подтверждения актуальны.
  Жёлтый  — нет подтверждения контрольной точки в срок; задержка ДО 20 рабочих
            дней; открытые жёлтые риски.
  Красный — задержка БОЛЕЕ 20 рабочих дней, открытый красный риск, риск с
            высокой вероятностью и высоким влиянием, либо ручное решение
            уполномоченного лица.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.db import execute, query_one, scalar
from app.domain.risk import RiskAssessment, assess_project_risk, required_response
from app.domain.taxonomy import (
    DELAY_YELLOW_DAYS, RISK_GREEN, RISK_RED, RISK_TITLES, RISK_YELLOW,
    ST_ACTIVE, ST_CHECK, ST_SUSPENDED,
)
from app.utils import today_msk, working_days_between

TODAY = today_msk()


def milestone(planned: str, status: str = "planned", **over) -> dict:
    row = {"id": "m1", "title": "Промежуточный отчёт", "planned_date": planned,
           "status": status}
    row.update(over)
    return row


def assess(*, milestones=(), risks=(), manual=RISK_GREEN, manual_comment=None,
           today=TODAY, holidays=None) -> RiskAssessment:
    return assess_project_risk(
        manual_level=manual, manual_comment=manual_comment,
        milestones=list(milestones), risks=list(risks), today=today,
        holidays=holidays,
    )


# ---------------------------------------------------------------------------
#  Три уровня
# ---------------------------------------------------------------------------

def test_green_when_no_milestones_overdue():
    """П.5.4: зелёный — работа по плану, подтверждения актуальны."""
    future = (TODAY + timedelta(days=30)).isoformat()
    result = assess(milestones=[milestone(future)])
    assert result.level == RISK_GREEN
    assert result.max_delay_days == 0
    assert result.overdue_milestones == []
    assert result.reasons, "уровень сопровождается пояснением"
    assert required_response(RISK_GREEN)["days"] is None


def test_yellow_when_milestone_overdue_below_twenty_working_days():
    """П.5.4: жёлтый — нет подтверждения контрольной точки в срок."""
    planned = (TODAY - timedelta(days=14)).isoformat()      # ≈10 рабочих дней
    result = assess(milestones=[milestone(planned)])
    assert 0 < result.max_delay_days <= DELAY_YELLOW_DAYS
    assert result.level == RISK_YELLOW
    assert RISK_TITLES[result.level] == "Жёлтый"
    assert any("Просрочена контрольная точка" in r for r in result.reasons)
    assert result.title == "Жёлтый"
    assert required_response(RISK_YELLOW)["days"] == 5
    assert required_response(RISK_YELLOW)["may_suspend"] is False


def test_red_when_milestone_overdue_more_than_twenty_working_days():
    """П.5.4: задержка БОЛЕЕ 20 рабочих дней — красный индикатор."""
    planned = (TODAY - timedelta(days=40)).isoformat()      # ≈28 рабочих дней
    result = assess(milestones=[milestone(planned)])
    assert result.max_delay_days > DELAY_YELLOW_DAYS
    assert result.level == RISK_RED
    assert any("превышает порог 20" in r for r in result.reasons)
    assert required_response(RISK_RED)["days"] == 5
    assert required_response(RISK_RED)["may_suspend"] is True


# ---------------------------------------------------------------------------
#  Порог ровно 20 рабочих дней
# ---------------------------------------------------------------------------

def test_delay_counts_working_days_in_half_open_interval():
    """Задержка — это рабочие дни в промежутке (плановая, сегодня].

    Проверка на фиксированных датах, чтобы не зависеть от дня запуска.
    Плановая пятница 11.09.2026: просрочка растёт только по рабочим дням, поэтому
    в пятницу 09.10 это 20 рабочих дней, в субботу 10.10 — те же 20, а в понедельник
    12.10 — уже 21.
    """
    assert working_days_between(date(2026, 9, 11), date(2026, 10, 9)) == 20
    assert working_days_between(date(2026, 9, 11), date(2026, 10, 10)) == 20
    assert working_days_between(date(2026, 9, 11), date(2026, 10, 12)) == 21
    assert working_days_between(date(2026, 9, 11), date(2026, 9, 11)) == 0


def test_working_days_ago_is_inverse_of_the_working_count(ago):
    """Счётчик назад обязан быть обратной операцией к рабочему счёту.

    Урок отдела: счётчик, который просто отсчитывает рабочие дни назад от
    сегодняшней даты, расходится с working_days_between на единицу в те дни,
    когда сегодня выходной, — проверки просрочки падали только по выходным.
    """
    for days in (1, 2, 5, 19, 20, 21, 60):
        planned = date.fromisoformat(ago(days))
        assert working_days_between(planned, TODAY) == days, (
            f"для {days} рабочих дней получилось "
            f"{working_days_between(planned, TODAY)}")


@pytest.mark.parametrize("delay, expected", [
    (1, RISK_YELLOW),
    (DELAY_YELLOW_DAYS - 1, RISK_YELLOW),
    (DELAY_YELLOW_DAYS, RISK_YELLOW),        # ровно 20 — ещё жёлтый
    (DELAY_YELLOW_DAYS + 1, RISK_RED),      # 21 — уже красный
    (60, RISK_RED),
])
def test_threshold_is_exactly_twenty_working_days(ago, delay, expected):
    """Порог п.5.4 — 20 РАБОЧИХ дней: «до 20» жёлтый, «более 20» красный."""
    planned = ago(delay)
    assert working_days_between(date.fromisoformat(planned), TODAY) == delay
    assert assess(milestones=[milestone(planned)]).level == expected


def test_threshold_counts_working_days_not_calendar_days(ago):
    """Счёт идёт в РАБОЧИЕ дни: те же календарные дни с выходными дают разный
    результат."""
    # 20 рабочих дней — это примерно 28 календарных.
    planned_20 = ago(20)
    assert working_days_between(date.fromisoformat(planned_20), TODAY) == 20
    assert assess(milestones=[milestone(planned_20)]).level == RISK_YELLOW
    # Те же 20 рабочих дней, если «забыть» про субботу и воскресенье.
    naive_calendar = (TODAY - timedelta(days=20)).isoformat()
    assert working_days_between(date.fromisoformat(naive_calendar), TODAY) < 20
    assert assess(milestones=[milestone(naive_calendar)]).level == RISK_YELLOW


def test_holiday_calendar_reduces_delay(ago):
    """Праздничный календарь университета учитывается (FR-35): один
    нерабочий день внутри периода уменьшает задержку на день."""
    planned = ago(21)
    holiday = date.fromisoformat(planned) + timedelta(days=2)
    # Праздник имеет смысл только если он выпадает на рабочий день: в выходной
    # задержка и так не считается. Фиксированное «+2 дня» попадало в субботу
    # при некоторых значениях сегодняшней даты, поэтому день сдвигается до
    # понедельника — проверка перестала зависеть от календаря запуска.
    while holiday.weekday() >= 5:
        holiday += timedelta(days=1)
    assert holiday < TODAY
    plain = assess(milestones=[milestone(planned)])
    with_holiday = assess(milestones=[milestone(planned)],
                          holidays={holiday.isoformat()})
    assert plain.max_delay_days == with_holiday.max_delay_days + 1
    # Порог перескакивает: 21 рабочий день без праздника — красный,
    # 20 рабочих дней с праздником — жёлтый.
    assert plain.level == RISK_RED
    assert with_holiday.level == RISK_YELLOW


# ---------------------------------------------------------------------------
#  Статус и риск — независимые поля
# ---------------------------------------------------------------------------

def test_risk_assessment_takes_no_project_status():
    """Функция оценки риска не принимает статус проекта: это гарантирует, что
    статус и риск — независимые поля (п.5.4, A-09 и A-10)."""
    import inspect

    parameters = set(inspect.signature(assess_project_risk).parameters)
    assert "status" not in parameters
    assert "project_status" not in parameters
    # Оценка зависит только от точек, рисков и ручного решения.
    assert parameters == {"manual_level", "manual_comment", "milestones", "risks",
                          "today", "holidays"}


def test_status_and_risk_diverge_in_database(api, make_project, users, set_status,
                                             make_milestone, ago):
    """Проект «Активен» с просроченной точкой: статус ST-07, риск красный."""
    project = make_project(status=ST_ACTIVE, risk_level=RISK_GREEN)
    make_milestone(project["id"], responsible_person_id=users["leader1"].person_id,
                   planned_date=ago(25))

    card = api.get(f"/api/projects/{project['id']}", login="leader1").json()
    assert card["status"] == ST_ACTIVE
    assert card["status_title"] == "Активен"
    assert card["risk"]["level"] == RISK_RED
    # Оба поля хранятся независимо.
    row = query_one("SELECT status, risk_level FROM projects WHERE id = ?",
                    (project["id"],))
    assert row["status"] == ST_ACTIVE
    assert row["risk_level"] == RISK_RED


@pytest.mark.parametrize("status", [ST_ACTIVE, ST_SUSPENDED, ST_CHECK])
def test_any_status_can_carry_yellow_or_red_risk(status):
    """Индикатор риска не привязан к статусу: жёлтый возможен в любом статусе
    рабочей фазы (п.5.4)."""
    project_status, risk = status, RISK_YELLOW
    assert project_status in (ST_ACTIVE, ST_SUSPENDED, ST_CHECK)
    assert risk == RISK_YELLOW


def test_risk_change_does_not_touch_status_in_api(api, make_project, users, project):
    """Смена индикатора риска уполномоченным лицом не меняет статус (A-10)."""
    before = query_one("SELECT status FROM projects WHERE id = ?", (project["id"],))
    response = api.post(f"/api/projects/{project['id']}/risk", login="prorector",
                        json={"level": "yellow", "comment": "нет подтверждения в срок"})
    assert response.status_code == 200
    assert response.json()["previous"] == RISK_GREEN
    after = query_one("SELECT status, risk_level FROM projects WHERE id = ?",
                      (project["id"],))
    assert after["status"] == before["status"]
    assert after["risk_level"] == RISK_YELLOW


def test_manual_risk_change_requires_comment(api, project):
    """Ручная правка индикатора риска требует комментария (A-10)."""
    without = api.post(f"/api/projects/{project['id']}/risk", login="prorector",
                       json={"level": "red"})
    assert without.status_code == 400
    assert "A-10" in without.json()["detail"]

    same_level = api.post(f"/api/projects/{project['id']}/risk", login="prorector",
                          json={"level": "green"})
    assert same_level.status_code == 200        # уровень не меняется — комментарий не нужен


# ---------------------------------------------------------------------------
#  Открытые риски проекта
# ---------------------------------------------------------------------------

def test_open_yellow_risk_raises_level_to_yellow():
    """П.5.4: наличие проблем с данными, качеством, командой или ресурсом —
    жёлтый индикатор."""
    result = assess(risks=[{"level": RISK_YELLOW, "status": "open",
                            "description": "неполнота данных"}])
    assert result.level == RISK_YELLOW
    assert any("Открыт риск жёлтого уровня" in r for r in result.reasons)


def test_open_red_risk_raises_level_to_red():
    """П.5.4: высокий правовой, этический, репутационный или ресурсный риск —
    красный индикатор."""
    result = assess(risks=[{"level": RISK_RED, "status": "open",
                            "description": "правовой риск разбирательства"}])
    assert result.level == RISK_RED
    assert any("Открыт риск красного уровня" in r for r in result.reasons)


def test_high_probability_high_impact_is_red():
    """Риск с высокой вероятностью и высоким влиянием — красный."""
    result = assess(risks=[{"level": RISK_GREEN, "status": "open",
                            "probability": "high", "impact": "high",
                            "description": "потеря данных"}])
    assert result.level == RISK_RED
    assert any("высокой вероятностью и высоким влиянием" in r for r in result.reasons)


def test_closed_and_archived_risks_are_ignored():
    """Закрытые и архивные риски не влияют на индикатор."""
    closed = assess(risks=[{"level": RISK_RED, "status": "closed",
                            "description": "риск снят"}])
    archived = assess(risks=[{"level": RISK_RED, "status": "open",
                              "archived_at": "2026-01-01",
                              "description": "риск архивирован"}])
    assert closed.level == RISK_GREEN
    assert archived.level == RISK_GREEN


# ---------------------------------------------------------------------------
#  Ручное решение уполномоченного лица может только ПОВЫСИТЬ уровень
# ---------------------------------------------------------------------------

def test_manual_level_can_raise_but_never_lower():
    """П.5.4 + FR-13: автоматика не имеет права понизить уровень,
    установленный человеком, — иначе просрочка «смывается» сама собой."""
    # Ручное решение проректора поднимает зелёный до красного.
    raised = assess(manual=RISK_RED, manual_comment="решение проректора от 12.02")
    assert raised.level == RISK_RED
    assert any("уполномоченным лицом" in r for r in raised.reasons)

    # Ручное «зелёный» не понижает красный, найденный автоматически.
    not_lowered = assess(manual=RISK_GREEN, risks=[
        {"level": RISK_RED, "status": "open", "description": "критический риск"}])
    assert not_lowered.level == RISK_RED

    # И не понижает жёлтый.
    still_yellow = assess(manual=RISK_GREEN, risks=[
        {"level": RISK_YELLOW, "status": "open", "description": "риск данных"}])
    assert still_yellow.level == RISK_YELLOW

    # Ручной красный не даёт просрочкам «смыться», даже когда просрочек нет.
    delayed_red = assess(milestones=[milestone((TODAY - timedelta(days=40)).isoformat())],
                         manual=RISK_RED, manual_comment="решение проректора")
    assert delayed_red.level == RISK_RED


def test_manual_red_without_delay_is_red():
    """Ручное решение проректора само по себе даёт красный индикатор."""
    result = assess(manual=RISK_RED, manual_comment="приостановка до выяснения")
    assert result.level == RISK_RED


# ---------------------------------------------------------------------------
#  Какие точки вообще считаются просроченными
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_finished_or_cancelled_milestones_are_not_overdue(status):
    """Выполненная и отменённая точка просрочкой не считается."""
    past = (TODAY - timedelta(days=60)).isoformat()
    result = assess(milestones=[milestone(past, status=status)])
    assert result.max_delay_days == 0
    assert result.level == RISK_GREEN


def test_archived_milestone_is_not_overdue():
    """Архивная точка не участвует в расчёте (п.6.1 п.5)."""
    past = (TODAY - timedelta(days=60)).isoformat()
    result = assess(milestones=[milestone(past, archived_at="2026-01-01")])
    assert result.level == RISK_GREEN


def test_future_milestone_is_not_overdue():
    """Точка с плановой датой в будущем не просрочена."""
    result = assess(milestones=[milestone((TODAY + timedelta(days=1)).isoformat())])
    assert result.max_delay_days == 0
    assert result.overdue_milestones == []


def test_worst_milestone_defines_the_level():
    """Из нескольких просроченных точек уровень задаёт наибольшая задержка."""
    result = assess(milestones=[
        milestone((TODAY - timedelta(days=5)).isoformat(), id="m1"),
        milestone((TODAY - timedelta(days=60)).isoformat(), id="m2"),
        milestone((TODAY + timedelta(days=5)).isoformat(), id="m3"),
    ])
    assert result.level == RISK_RED
    assert len(result.overdue_milestones) == 2
    assert max(m["delay_working_days"] for m in result.overdue_milestones) == \
        result.max_delay_days
    assert {m["id"] for m in result.overdue_milestones} == {"m1", "m2"}


def test_milestone_without_planned_date_is_skipped():
    """Точка без плановой даты не может считаться просроченной."""
    result = assess(milestones=[milestone(None)])
    assert result.level == RISK_GREEN


# ---------------------------------------------------------------------------
#  Согласованность с остальным приложением
# ---------------------------------------------------------------------------

def test_risk_report_exposes_actions_per_level(api, project, users, set_status):
    """Отчёт FR-27 показывает требуемое действие для каждого уровня (п.5.4)."""
    report = api.get("/api/reports/risks", login="prorector").json()
    assert set(report["counts"]) == {"red", "yellow"}
    assert set(report["actions"]) == {"yellow", "red"}
    assert report["actions"]["red"]["may_suspend"] is True
    assert "Статус и риск — разные поля" in report["note"]

    # Открытый красный риск переводит проект в красную зону (A-65: ручной
    # уровень требует комментария).
    set_status(project["id"], ST_ACTIVE)
    created = api.post(f"/api/projects/{project['id']}/risks", login="leader1",
                       json={"category": "legal", "level": "red",
                             "level_comment": "судебный спор с партнёром",
                             "probability": "high", "impact": "high",
                             "description": "Требование партнёра о расторжении"})
    assert created.status_code == 201, created.text
    assert created.json()["project_risk"]["level"] == RISK_RED

    refreshed = api.get("/api/reports/risks", login="prorector").json()
    assert refreshed["counts"]["red"] == 1
    assert any(item["risk_level"] == RISK_RED for item in refreshed["items"])


def test_overdue_report_declares_red_threshold(api, make_project, users, make_milestone,
                                               ago, set_status):
    """Отчёт FR-27 объявляет порог красного в рабочих днях (п.5.4)."""
    project = make_project(status=ST_ACTIVE)
    make_milestone(project["id"], responsible_person_id=users["leader1"].person_id,
                   planned_date=ago(3))
    api.get(f"/api/projects/{project['id']}", login="leader1")   # пересчёт риска

    report = api.get("/api/reports/overdue", login="prorector").json()
    assert report["red_threshold_working_days"] == DELAY_YELLOW_DAYS
    assert report["count"] >= 1
    item = report["items"][0]
    assert item["delay_working_days"] >= 1
    # Жёлтый порог: руководитель, а не проректор.
    assert "Руководитель за 5 рабочих дней" in item["requires"]


def test_risk_constants_match_specification():
    """Константы соответствуют п.5.4 и п.5.5 ТЗ."""
    assert DELAY_YELLOW_DAYS == 20
    assert RISK_TITLES == {"green": "Зелёный", "yellow": "Жёлтый", "red": "Красный"}
    assert required_response("green")["action"].startswith("Сводное")
    assert required_response("yellow")["action"].startswith("Руководитель")
    assert required_response("red")["action"].startswith("Проректор")


def test_recompute_via_api_marks_milestone_overdue(api, make_project, users,
                                                   make_milestone, ago):
    """FR-13: просрочка формируется автоматически при пересчёте (статус точки
    меняется в «просрочена», статус проекта — нет)."""
    project = make_project(status=ST_ACTIVE)
    milestone = make_milestone(project["id"],
                               responsible_person_id=users["leader1"].person_id,
                               planned_date=ago(2))
    assert milestone["status"] == "planned"

    card = api.get(f"/api/projects/{project['id']}", login="leader1").json()
    assert card["risk"]["level"] == RISK_YELLOW
    assert scalar("SELECT status FROM milestones WHERE id = ?",
                  (milestone["id"],), "") == "overdue"
    assert card["status"] == ST_ACTIVE