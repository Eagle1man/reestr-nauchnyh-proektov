"""Индикатор риска проекта (п.5.4).

Ключевое из ТЗ: СТАТУС и РИСК — РАЗНЫЕ ПОЛЯ. Проект может быть «Активен»
и при этом иметь жёлтый индикатор риска. Поэтому здесь нет обращения к статусу
проекта вообще — только к контрольным точкам, рискам и ручному уровню.

  Зелёный — работа идёт по плану; подтверждения актуальны.
  Жёлтый  — нет подтверждения контрольной точки в срок; прогнозируется задержка
            до 20 рабочих дней; есть проблемы с данными, качеством, командой
            или ресурсом.
  Красный — задержка более 20 рабочих дней, повторный срыв, отсутствие реакции,
            потеря данных или руководителя, необходимость изменить цель,
            высокий правовой, этический, репутационный или ресурсный риск.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..utils import to_date, working_days_between
from .taxonomy import DELAY_YELLOW_DAYS, RISK_GREEN, RISK_RED, RISK_YELLOW, RISK_TITLES


@dataclass
class RiskAssessment:
    level: str
    reasons: list[str]
    max_delay_days: int
    overdue_milestones: list[dict]

    @property
    def title(self) -> str:
        return RISK_TITLES.get(self.level, self.level)


def assess_project_risk(
    *,
    manual_level: str,
    manual_comment: str | None,
    milestones: list[dict],
    risks: list[dict],
    today: date,
    holidays: set[str] | None = None,
) -> RiskAssessment:
    """Рассчитать индикатор риска проекта.

    manual_level — последнее решение уполномоченного лица; оно может только
    повысить уровень. Автоматика не имеет права понизить жёлтый или красный,
    установленный человеком: иначе просрочка «смывается» сама собой.
    """
    order = {RISK_GREEN: 0, RISK_YELLOW: 1, RISK_RED: 2}
    reasons: list[str] = []
    overdue: list[dict] = []
    max_delay = 0

    for ms in milestones:
        if ms.get("archived_at") or ms.get("status") in ("done", "cancelled"):
            continue
        planned = to_date(ms.get("planned_date"))
        if not planned:
            continue
        if planned >= today:
            continue
        delay = working_days_between(planned, today, holidays)
        record = {
            "id": ms.get("id"),
            "title": ms.get("title"),
            "planned_date": ms.get("planned_date"),
            "delay_working_days": delay,
            "status": ms.get("status"),
        }
        overdue.append(record)
        max_delay = max(max_delay, delay)

    computed = RISK_GREEN
    if max_delay > 0:
        computed = RISK_YELLOW
        reasons.append(
            f"Просрочена контрольная точка: задержка {max_delay} "
            f"раб. дн. (порог жёлтого — отсутствие подтверждения в срок)"
        )
    if max_delay > DELAY_YELLOW_DAYS:
        computed = RISK_RED
        reasons.append(
            f"Задержка {max_delay} рабочих дней превышает порог {DELAY_YELLOW_DAYS} "
            "(п.5.4 — красный индикатор)"
        )

    for risk in risks:
        if risk.get("archived_at") or risk.get("status") == "closed":
            continue
        if risk.get("level") == RISK_RED:
            computed = RISK_RED
            reasons.append(f"Открыт риск красного уровня: {risk.get('description', '')[:120]}")
        elif risk.get("level") == RISK_YELLOW and computed == RISK_GREEN:
            computed = RISK_YELLOW
            reasons.append(f"Открыт риск жёлтого уровня: {risk.get('description', '')[:120]}")
        if risk.get("probability") == "high" and risk.get("impact") == "high" \
                and computed != RISK_RED:
            computed = RISK_RED
            reasons.append("Риск с высокой вероятностью и высоким влиянием")

    manual = manual_level or RISK_GREEN
    if order[manual] > order[computed]:
        computed = manual
        reasons.insert(0, (
            f"Уровень {RISK_TITLES[manual]} установлен уполномоченным лицом"
            + (f": {manual_comment.strip()}" if manual_comment else "")
        ))

    if not reasons:
        reasons.append("Просрочек нет, подтверждения контрольных точек актуальны")

    return RiskAssessment(
        level=computed,
        reasons=reasons,
        max_delay_days=max_delay,
        overdue_milestones=overdue,
    )


def required_response(level: str) -> dict:
    """Действие, которое ТЗ требует при данном индикаторе (п.5.4)."""
    if level == RISK_RED:
        return {
            "action": "Проректор рассматривает проект за 5 рабочих дней",
            "may_suspend": True,
            "days": 5,
        }
    if level == RISK_YELLOW:
        return {
            "action": "Руководитель за 5 рабочих дней указывает причину, меры и новый срок",
            "may_suspend": False,
            "days": 5,
        }
    return {
        "action": "Сводное отображение без отдельного рассмотрения",
        "may_suspend": False,
        "days": None,
    }