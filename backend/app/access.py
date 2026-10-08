"""Права доступа: роль И отношение к конкретному проекту.

FR-02: права определяются ролью и отношением пользователя к конкретному проекту.
П.4.1 п.1: один пользователь может иметь несколько ролей, но доступ проверяется
также по его отношению к проекту.

П.4.1 п.2: руководитель, участник, предполагаемый соавтор или научный
руководитель участника НЕ может проводить независимую экспертизу того же проекта.
П.4.1 п.3: при заинтересованности куратора решение переходит к проректору;
при заинтересованности проректора — к лицу, назначенному ректором.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .db import query, query_one, scalar
from .domain.taxonomy import (
    ROLE_COUNCIL, ROLE_CURATOR, ROLE_PRORECTOR, ROLE_RECTOR, ROLE_SECRETARY,
    ROLE_SYSADMIN, ROLE_TECH_ADMIN, REL_CURATOR, REL_EXPERT, REL_LEADER, REL_MEMBER,
)
from .domain.workflow import ACTOR_CURATOR, ACTOR_LEADER, ACTOR_PRORECTOR, ACTOR_SECRETARY

#: Роли, которые видят весь портфель
PORTFOLIO_ROLES: frozenset[str] = frozenset({
    ROLE_RECTOR, ROLE_COUNCIL, ROLE_PRORECTOR, ROLE_SECRETARY, ROLE_TECH_ADMIN,
})

#: Роли, которые могут работать с чужими карточками в объёме своих полномочий
MANAGEMENT_ROLES: frozenset[str] = frozenset({
    ROLE_RECTOR, ROLE_COUNCIL, ROLE_PRORECTOR, ROLE_SECRETARY, ROLE_SYSADMIN,
})


class AccessDenied(Exception):
    """Отказ в доступе: операция запрещена ролью или отсутствием отношения к проекту."""

    def __init__(self, message: str, *, required: Iterable[str] = ()):
        super().__init__(message)
        self.required = list(required)


@dataclass
class Actor:
    """Пользователь в контексте конкретного проекта."""
    user: dict
    global_roles: set[str] = field(default_factory=set)
    #: роли отношения к проекту: REL_LEADER, REL_MEMBER, REL_CURATOR, REL_EXPERT
    relations: set[str] = field(default_factory=set)

    @property
    def id(self) -> str:
        return self.user["id"]

    @property
    def login(self) -> str:
        return self.user["login"]

    @property
    def person_id(self) -> str | None:
        return self.user.get("person_id")

    def has(self, *roles: str) -> bool:
        return bool(self.global_roles & set(roles))

    @property
    def is_curator_of_project(self) -> bool:
        return REL_CURATOR in self.relations or ROLE_CURATOR in self.relations

    @property
    def is_leader(self) -> bool:
        return REL_LEADER in self.relations

    @property
    def is_expert(self) -> bool:
        return REL_EXPERT in self.relations

    def workflow_actors(self) -> set[str]:
        """Наборы исполнителей для матрицы переходов (Приложение Б)."""
        actors: set[str] = set()
        if self.has(ROLE_SECRETARY):
            actors.add(ACTOR_SECRETARY)
        if self.has(ROLE_PRORECTOR, ROLE_RECTOR, ROLE_COUNCIL):
            actors.add(ACTOR_PRORECTOR)
        if self.is_curator_of_project:
            actors.add(ACTOR_CURATOR)
        if self.is_leader:
            actors.add(ACTOR_LEADER)
        return actors


def load_actor(user: dict) -> Actor:
    from .security import user_roles

    return Actor(user=user, global_roles=set(user_roles(user["id"])))


def attach_relations(actor: Actor, project_id: str | None) -> Actor:
    """Дополнить актёра ролями отношения к проекту (FR-02)."""
    if not project_id:
        return actor
    person_id = actor.person_id
    if person_id:
        if query_one(
            "SELECT 1 FROM participations WHERE project_id = ? AND person_id = ?"
            " AND role = ? AND archived_at IS NULL",
            (project_id, person_id, REL_LEADER),
        ):
            actor.relations.add(REL_LEADER)
        if query_one(
            "SELECT 1 FROM participations WHERE project_id = ? AND person_id = ?"
            " AND archived_at IS NULL",
            (project_id, person_id),
        ):
            actor.relations.add(REL_MEMBER)
        # Предполагаемый соавтор: автор результата, связанного с проектом (п.4.1 п.2)
        if query_one(
            "SELECT 1 FROM results r JOIN result_projects rp ON rp.result_id = r.id"
            " WHERE rp.project_id = ? AND r.authors LIKE ?",
            (project_id, f'%"{person_id}"%'),
        ):
            actor.relations.add("coauthor")
        # Научный руководитель участника или аспиранта (п.4.1 п.2)
        if query_one(
            "SELECT 1 FROM student_tasks WHERE project_id = ? AND supervisor_person_id = ?",
            (project_id, person_id),
        ):
            actor.relations.add("supervisor")
        if query_one(
            "SELECT 1 FROM dissertations d JOIN dissertation_projects dp"
            " ON dp.dissertation_id = d.id"
            " WHERE dp.project_id = ? AND d.supervisor_person_id = ?",
            (project_id, person_id),
        ):
            actor.relations.add("supervisor")

    if query_one(
        "SELECT 1 FROM program_curators pc JOIN projects p ON p.program_id = pc.program_id"
        " WHERE p.id = ? AND pc.person_id = ?",
        (project_id, person_id),
    ):
        actor.relations.add(REL_CURATOR)

    if person_id and query_one(
        "SELECT 1 FROM reviews WHERE project_id = ? AND expert_person_id = ?"
        " AND recused_at IS NULL",
        (project_id, person_id),
    ):
        actor.relations.add(REL_EXPERT)

    return actor


# ---------------------------------------------------------------------------
#  Конфликт интересов (п.4.1)
# ---------------------------------------------------------------------------

#: Роли отношения, запрещающие независимую экспертизу этого же проекта (п.4.1 п.2)
BLOCKING_RELATIONS: frozenset[str] = frozenset({
    REL_LEADER, REL_MEMBER, "coauthor", "supervisor", REL_CURATOR,
})


def conflict_reasons(actor: Actor, project_id: str) -> list[str]:
    """Почему актёр не может быть независимым экспертом по этому проекту."""
    probe = Actor(user=actor.user, global_roles=set(), relations=set())
    attach_relations(probe, project_id)
    reasons: list[str] = []
    labels = {
        REL_LEADER: "руководитель проекта",
        REL_MEMBER: "участник проекта",
        "coauthor": "предполагаемый соавтор по результату проекта",
        "supervisor": "научный руководитель участника или аспиранта",
        REL_CURATOR: "куратор программы проекта",
    }
    for relation in sorted(probe.relations & BLOCKING_RELATIONS):
        reasons.append(f"Актер является {labels.get(relation, relation)} — "
                       "независимая экспертиза невозможна (п.4.1)")
    return reasons


def can_be_expert(actor: Actor, project_id: str) -> tuple[bool, list[str]]:
    reasons = conflict_reasons(actor, project_id)
    if actor.has(ROLE_PRORECTOR):
        reasons.append("Проректор по науке не может быть экспертом по проекту, "
                       "который он же и запускает")
    return (not reasons, reasons)


def decision_authority(actor: Actor, project_id: str) -> tuple[str | None, str | None]:
    """Кто принимает решение по проекту с учётом замещения (п.4.1 п.3).

    Возвращает (уровень, пояснение). Уровень: prorector|rector|council|curator.
    """
    if actor.has(ROLE_RECTOR):
        return "rector", "Ректор — дополнительные ресурсы и институциональные риски (п.4.2)"
    if actor.has(ROLE_COUNCIL):
        return "council", "Научный совет — стратегические и исключительные случаи (п.4.2)"
    if actor.has(ROLE_PRORECTOR):
        blocked = conflict_reasons(actor, project_id)
        if blocked:
            return "rector", ("Заинтересованность проректора — решение переходит "
                              "к лицу, назначенному ректором (п.4.1 п.3)")
        return "prorector", "Проректор по науке — запуск и приёмка полного маршрута"
    if actor.is_curator_of_project and not conflict_reasons(actor, project_id):
        return "curator", "Куратор программы — упрощённый маршрут"
    if actor.is_curator_of_project:
        return "prorector", ("Заинтересованность куратора — решение переходит "
                             "к проректору по науке (п.4.1 п.3)")
    return None, None


# ---------------------------------------------------------------------------
#  Проверки доступа к операциям
# ---------------------------------------------------------------------------

def require_portfolio_access(actor: Actor) -> None:
    """Просмотр портфеля в целом: ПС-02 — каждый видит только разрешённое."""
    if actor.global_roles & PORTFOLIO_ROLES:
        return
    # Участники проектов видят проекты, в которых участвуют
    if scalar("SELECT COUNT(*) FROM participations WHERE person_id = ?"
              " AND archived_at IS NULL", (actor.person_id,), 0):
        return
    raise AccessDenied(
        "Нет доступа к портфелю: требуется одна из ролей "
        "или участие хотя бы в одном проекте",
        required=sorted(PORTFOLIO_ROLES),
    )


def can_view_project(actor: Actor, project_id: str) -> bool:
    if actor.global_roles & PORTFOLIO_ROLES:
        return True
    person_id = actor.person_id
    if not person_id:
        return False
    return bool(query_one(
        "SELECT 1 FROM participations WHERE project_id = ? AND person_id = ?",
        (project_id, person_id),
    ) or query_one(
        "SELECT 1 FROM program_curators pc JOIN projects p ON p.program_id = pc.program_id"
        " WHERE p.id = ? AND pc.person_id = ?",
        (project_id, person_id),
    ) or query_one(
        "SELECT 1 FROM reviews WHERE project_id = ? AND expert_person_id = ?",
        (project_id, person_id),
    ))


def can_edit_card(actor: Actor, project_id: str, status: str) -> bool:
    """Правка содержания карточки (не статуса)."""
    if actor.is_leader:
        return True
    if actor.has(ROLE_SECRETARY, ROLE_SYSADMIN):
        return True
    if actor.is_curator_of_project and status in ("ST-01", "ST-03"):
        return True
    return False


def require_edit_card(actor: Actor, project_id: str, status: str) -> None:
    if can_edit_project(actor, project_id):
        return
    raise AccessDenied(
        "Правка карточки недоступна: требуется роль руководителя проекта, "
        "секретаря или куратора программы",
    )


def can_edit_project(actor: Actor, project_id: str) -> bool:
    """Правка любой части карточки, включая статусы по матрице переходов."""
    return bool(
        actor.is_leader or actor.has(ROLE_SECRETARY, ROLE_PRORECTOR, ROLE_SYSADMIN)
        or actor.is_curator_of_project
    )


def visible_projects_clause(actor: Actor, params: list) -> tuple[str, str]:
    """SQL-условие видимости портфеля для FR-25 (поиск и фильтры).

    Возвращает (clause, _). Смысл: пользователь без управленческих ролей видит
    только проекты, в которых участвует, курирует или по которым назначен
    экспертом (FR-02, ПС-02).
    """
    if actor.global_roles & PORTFOLIO_ROLES:
        return "1=1", ""
    if not actor.person_id:
        return "1=0", ""
    clause = (
        "p.id IN (SELECT project_id FROM participations WHERE person_id = ?)"
        " OR p.id IN (SELECT p2.id FROM program_curators pc"
        "            JOIN projects p2 ON p2.program_id = pc.program_id"
        "            WHERE pc.person_id = ?)"
        " OR p.id IN (SELECT project_id FROM reviews WHERE expert_person_id = ?)"
    )
    params.extend([actor.person_id, actor.person_id, actor.person_id])
    return clause, ""


def require_admin(actor: Actor) -> None:
    if not actor.has(ROLE_SYSADMIN, ROLE_TECH_ADMIN):
        raise AccessDenied("Требуется роль технического администратора",
                           required=[ROLE_SYSADMIN, ROLE_TECH_ADMIN])


def matrix_for(actor: Actor) -> dict:
    """Матрица прав текущего пользователя — для интерфейса (FR-02)."""
    return {
        "global_roles": sorted(actor.global_roles),
        "is_portfolio": bool(actor.global_roles & PORTFOLIO_ROLES),
        "is_admin": bool(actor.global_roles & {ROLE_SYSADMIN, ROLE_TECH_ADMIN}),
        "can_import": bool(actor.global_roles & {ROLE_SYSADMIN, ROLE_SECRETARY, ROLE_PRORECTOR}),
        "can_export_archive": bool(actor.global_roles & {ROLE_SYSADMIN, ROLE_TECH_ADMIN}),
        "can_manage_users": bool(actor.global_roles & {ROLE_SYSADMIN}),
        "can_publish": bool(actor.global_roles & {
            ROLE_SECRETARY, ROLE_PRORECTOR, ROLE_RECTOR, ROLE_SYSADMIN}),
    }


def project_relations(project_id: str) -> dict[str, list[str]]:
    """Кто в чём участвует — для карточки и для проверки прав."""
    rows = query(
        "SELECT pp.role, p.id AS person_id, p.full_name FROM participations pp"
        " JOIN persons p ON p.id = pp.person_id"
        " WHERE pp.project_id = ? AND pp.archived_at IS NULL",
        (project_id,),
    )
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row["role"], []).append(row["full_name"])
    return out