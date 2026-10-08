"""Движок жизненного цикла проекта.

Матрица переходов взята из Приложения Б ТЗ буквально: отдельно для упрощённого
(Б.1) и полного (Б.2) маршрутов. Недопустимые смены статуса блокируются
(FR-10), при этом система показывает причину блокировки, а не просто «нет».

Переход разрешён только если выполнены три независимых условия:
  1. переход есть в матрице для текущего маршрута;
  2. актор имеет право на этот переход (роль + отношение к проекту);
  3. выполнено условие перехода (обязательные поля, заключение, результат…).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Final

from .taxonomy import (
    ROLE_PRORECTOR, ROLE_SECRETARY, REL_CURATOR, REL_LEADER,
    ST_ACTIVE, ST_CHECK, ST_CLOSED, ST_COMPLETED, ST_DECISION, ST_DRAFT,
    ST_FINAL_REVIEW, ST_PILOT, ST_RESERVE, ST_REVIEW, ST_REVISION, ST_SUSPENDED,
    ROUTE_FULL, ROUTE_SIMPLIFIED,
)

ACTOR_SECRETARY = "secretary"
ACTOR_PRORECTOR = "prorector"
ACTOR_CURATOR = "curator"
ACTOR_LEADER = "leader"


@dataclass(frozen=True)
class Transition:
    """Одна стрка матрицы переходов."""
    action: str                  # действие из Приложения Б
    title: str                   # читаемое название действия
    from_status: str
    to_status: str
    actors: tuple[str, ...]      # кто может выполнить (роль или отношение)
    condition: str               # условие из ТЗ, показывается пользователю
    guard: str | None = None     # ключ программной проверки условия
    reason_required: bool = False
    switches_to_full: bool = False


# ---------------------------------------------------------------------------
#  Приложение Б.1 — упрощённый маршрут
# ---------------------------------------------------------------------------

SIMPLIFIED_TRANSITIONS: Final[tuple[Transition, ...]] = (
    Transition("submit", "Подать", ST_DRAFT, ST_CHECK,
               (ACTOR_LEADER,), "Обязательные поля заполнены", guard="required_fields"),
    Transition("return", "Вернуть", ST_CHECK, ST_REVISION,
               (ACTOR_SECRETARY,), "Единый перечень недостающих сведений",
               guard="not_required_fields", reason_required=True),
    Transition("resubmit", "Подать повторно", ST_REVISION, ST_CHECK,
               (ACTOR_LEADER,), "Исправления внесены"),
    Transition("launch", "Запустить", ST_CHECK, ST_ACTIVE,
               (ACTOR_CURATOR,), "Карточка комплектна; полный маршрут не требуется",
               guard="simplified_launch"),
    Transition("submit_result", "Представить результат", ST_ACTIVE, ST_FINAL_REVIEW,
               (ACTOR_LEADER,), "Результат и подтверждение приложены", guard="result_submitted"),
    Transition("return_result", "Вернуть", ST_FINAL_REVIEW, ST_REVISION,
               (ACTOR_CURATOR,), "Указаны изменения", reason_required=True),
    Transition("accept", "Принять", ST_FINAL_REVIEW, ST_COMPLETED,
               (ACTOR_CURATOR,), "Положительное заключение", guard="positive_verdict"),
    Transition("suspend", "Приостановить", ST_ACTIVE, ST_SUSPENDED,
               (ACTOR_CURATOR, ACTOR_PRORECTOR), "Причина и условие возобновления",
               reason_required=True),
    Transition("resume", "Возобновить", ST_SUSPENDED, ST_ACTIVE,
               (ACTOR_CURATOR, ACTOR_PRORECTOR), "Ограничение устранено"),
    Transition("to_full_route", "Перевести на полный маршрут", ST_ACTIVE, ST_DECISION,
               (ACTOR_PRORECTOR,), "Выявлен T-01–T-06", guard="has_full_reasons",
               switches_to_full=True),
)

# ---------------------------------------------------------------------------
#  Приложение Б.2 — полный маршрут
# ---------------------------------------------------------------------------

FULL_TRANSITIONS: Final[tuple[Transition, ...]] = (
    Transition("submit", "Подать", ST_DRAFT, ST_CHECK,
               (ACTOR_LEADER,), "Обязательные поля заполнены", guard="required_fields"),
    Transition("return", "Вернуть", ST_CHECK, ST_REVISION,
               (ACTOR_SECRETARY,), "Указаны недостающие сведения",
               guard="not_required_fields", reason_required=True),
    Transition("assign_review", "Назначить экспертизу", ST_CHECK, ST_REVIEW,
               (ACTOR_SECRETARY,), "Карточка комплектна", guard="required_fields"),
    Transition("review_return", "Вернуть на уточнение", ST_REVIEW, ST_REVISION,
               (ACTOR_PRORECTOR,), "Указаны необходимые изменения", reason_required=True),
    Transition("to_decision", "Направить на решение", ST_REVIEW, ST_DECISION,
               (ACTOR_SECRETARY,), "Заключение зарегистрировано", guard="review_registered"),
    Transition("start_pilot", "Запустить пилот", ST_DECISION, ST_PILOT,
               (ACTOR_PRORECTOR,), "Требуется проверка замысла", reason_required=True),
    Transition("launch", "Запустить проект", ST_DECISION, ST_ACTIVE,
               (ACTOR_PRORECTOR,), "Проект одобрен", reason_required=True),
    Transition("reserve", "Отложить", ST_DECISION, ST_RESERVE,
               (ACTOR_PRORECTOR,), "Нет ресурса либо текущего приоритета", reason_required=True),
    Transition("reject", "Отклонить", ST_DECISION, ST_CLOSED,
               (ACTOR_PRORECTOR,), "Причина зарегистрирована", reason_required=True),
    Transition("submit_pilot", "Представить пилот", ST_PILOT, ST_DECISION,
               (ACTOR_LEADER,), "Условия пилота выполнены"),
    Transition("return_from_reserve", "Вернуть к рассмотрению", ST_RESERVE, ST_DECISION,
               (ACTOR_PRORECTOR,), "Изменились ресурсы или приоритеты"),
    Transition("submit_result", "Представить результат", ST_ACTIVE, ST_FINAL_REVIEW,
               (ACTOR_LEADER,), "Результат и доказательства приложены", guard="result_submitted"),
    Transition("return_result", "Вернуть", ST_FINAL_REVIEW, ST_REVISION,
               (ACTOR_PRORECTOR,), "Требуется доработка", reason_required=True),
    Transition("accept", "Принять", ST_FINAL_REVIEW, ST_COMPLETED,
               (ACTOR_PRORECTOR,), "Положительное заключение", guard="positive_verdict"),
    Transition("suspend", "Приостановить", ST_ACTIVE, ST_SUSPENDED,
               (ACTOR_PRORECTOR,), "Причина и условие возобновления", reason_required=True),
    Transition("resume", "Возобновить", ST_SUSPENDED, ST_ACTIVE,
               (ACTOR_PRORECTOR,), "Ограничение устранено"),
    Transition("to_reserve", "Перевести в резерв", ST_SUSPENDED, ST_RESERVE,
               (ACTOR_PRORECTOR,), "Проект сохраняет актуальность"),
    Transition("terminate", "Прекратить", ST_SUSPENDED, ST_CLOSED,
               (ACTOR_PRORECTOR,), "Продолжение нецелесообразно", reason_required=True),
)

TRANSITIONS: Final[dict[str, tuple[Transition, ...]]] = {
    ROUTE_SIMPLIFIED: SIMPLIFIED_TRANSITIONS,
    ROUTE_FULL: FULL_TRANSITIONS,
}

TRANSITIONS_BY_ID: Final[dict[tuple[str, str], Transition]] = {
    (route, t.action): t for route, items in TRANSITIONS.items() for t in items
}


# ---------------------------------------------------------------------------
#  Контекст для проверки условий
# ---------------------------------------------------------------------------

@dataclass
class TransitionContext:
    """Данные проекта, нужные проверкам условий перехода."""
    missing_required: list[str] = field(default_factory=list)
    full_route_reasons: list[str] = field(default_factory=list)
    has_linked_result: bool = False
    result_has_confirmation: bool = False
    has_final_review: bool = False
    positive_final_review: bool = False
    route: str = ROUTE_SIMPLIFIED


def _guard_required_fields(ctx: TransitionContext) -> list[str]:
    if ctx.missing_required:
        return [f"Не заполнены обязательные поля: {', '.join(ctx.missing_required)}"]
    return []


def _guard_not_required_fields(ctx: TransitionContext) -> list[str]:
    if not ctx.missing_required:
        return ["Недостающих сведений не обнаружено — возвращать карточку не на что"]
    return []


def _guard_simplified_launch(ctx: TransitionContext) -> list[str]:
    problems = _guard_required_fields(ctx)
    if ctx.full_route_reasons:
        codes = ", ".join(ctx.full_route_reasons)
        problems.append(
            f"Выявлены признаки полного маршрута ({codes}); "
            "упрощённый маршрут не применяется"
        )
    return problems


def _guard_result_submitted(ctx: TransitionContext) -> list[str]:
    problems: list[str] = []
    if not ctx.has_linked_result:
        problems.append("К проекту не привязан результат")
    elif not ctx.result_has_confirmation:
        problems.append("У результата отсутствует подтверждающий материал")
    return problems


def _guard_review_registered(ctx: TransitionContext) -> list[str]:
    if not ctx.has_final_review:
        return ["Заключение эксперта не зарегистрировано"]
    return []


def _guard_positive_verdict(ctx: TransitionContext) -> list[str]:
    if not ctx.has_final_review:
        return ["Итоговое заключение не зарегистрировано"]
    if not ctx.positive_final_review:
        return [
            "Заключение не является положительным: приёмка возможна только "
            "по рекомендации «Поддержать» или «Поддержать с условиями»"
        ]
    return []


def _guard_has_full_reasons(ctx: TransitionContext) -> list[str]:
    if not ctx.full_route_reasons:
        return ["Признаки T-01…T-06 не выявлены — перевод на полный маршрут не требуется"]
    return []


GUARDS: Final[dict[str, Callable[[TransitionContext], list[str]]]] = {
    "required_fields": _guard_required_fields,
    "not_required_fields": _guard_not_required_fields,
    "simplified_launch": _guard_simplified_launch,
    "result_submitted": _guard_result_submitted,
    "review_registered": _guard_review_registered,
    "positive_verdict": _guard_positive_verdict,
    "has_full_reasons": _guard_has_full_reasons,
}


# ---------------------------------------------------------------------------
#  Проверки
# ---------------------------------------------------------------------------

@dataclass
class TransitionCheck:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "reasons": self.reasons}


def find_transition(route: str, action: str) -> Transition | None:
    for t in TRANSITIONS.get(route, ()):
        if t.action == action:
            return t
    return None


def check_transition(
    *,
    route: str,
    status: str,
    action: str,
    actor_roles: set[str],
    ctx: TransitionContext,
    reason: str | None = None,
) -> TransitionCheck:
    """Проверить возможность перехода. Возвращает полный список причин отказа."""
    reasons: list[str] = []

    spec = find_transition(route, action)
    if spec is None:
        return TransitionCheck(False, [
            f"Действие «{action}» не предусмотрено для маршрута "
            f"«{'упрощённого' if route == ROUTE_SIMPLIFIED else 'полного'}»"
        ])

    if spec.from_status != status:
        reasons.append(
            f"Действие «{spec.title}» доступно из статуса "
            f"«{_title(spec.from_status)}», текущий статус — «{_title(status)}»"
        )

    if actor_roles and not (actor_roles & set(spec.actors)):
        human = ", ".join(_actor_title(a) for a in spec.actors)
        reasons.append(f"Действие «{spec.title}» доступно: {human}")

    if spec.reason_required and not (reason or "").strip():
        reasons.append(f"Для действия «{spec.title}» обязателен комментарий: {spec.condition}")

    if spec.guard and spec.from_status == status:
        reasons.extend(GUARDS[spec.guard](ctx))

    return TransitionCheck(not reasons, reasons)


def available_actions(
    route: str, status: str, actor_roles: set[str], ctx: TransitionContext
) -> list[dict]:
    """Какие действия доступны пользователю прямо сейчас (для интерфейса)."""
    out: list[dict] = []
    for spec in TRANSITIONS.get(route, ()):
        if spec.from_status != status:
            continue
        if actor_roles and not (actor_roles & set(spec.actors)):
            continue
        check = check_transition(
            route=route, status=status, action=spec.action,
            actor_roles=actor_roles, ctx=ctx,
        )
        out.append({
            "action": spec.action,
            "title": spec.title,
            "to_status": spec.to_status,
            "to_status_title": _title(spec.to_status),
            "condition": spec.condition,
            "reason_required": spec.reason_required,
            "switches_to_full": spec.switches_to_full,
            "allowed": check.allowed,
            "blocked_reasons": check.reasons,
        })
    return out


def _title(status: str) -> str:
    from .taxonomy import STATUS_TITLES
    return STATUS_TITLES.get(status, status)


def _actor_title(actor: str) -> str:
    return {
        ACTOR_SECRETARY: "секретарь Научного совета",
        ACTOR_PRORECTOR: "проректор по науке",
        ACTOR_CURATOR: "куратор программы",
        ACTOR_LEADER: "руководитель проекта",
    }.get(actor, actor)