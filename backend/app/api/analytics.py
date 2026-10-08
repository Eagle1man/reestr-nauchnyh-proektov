"""Панели, отчёты и внутрисистемные напоминания (M-06, M-07; раздел 8 ТЗ; FR-24, FR-26, FR-27).

Раздел 8 ТЗ определяет формы:
  панель ректора, панель проректора, обзор Научного совета, обзор программы,
  публикационный план, аспирантура и студенческая наука, контроль сроков.

Панель и сводный отчёт должны укладываться в 5 секунд при объёме до
10 000 проектов (NFR-03) — здесь только агрегаты в БД, без построчной
загрузки карточек.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from ..access import (
    ROLE_COUNCIL, ROLE_PRORECTOR, ROLE_RECTOR, ROLE_SECRETARY, ROLE_SYSADMIN,
    attach_relations, require_portfolio_access,
)
from ..db import query, query_one, scalar
from ..domain.risk import required_response
from ..domain.taxonomy import (
    ACTIVE_STATUSES, RISK_TITLES, ROUTES, STATUS_TITLES,
)
from ..services import projects as svc
from ..utils import add_working_days, fmt_date, today_iso, today_msk, working_days_between
from .deps import CurrentActor

router = APIRouter(prefix="/api", tags=["Панели и отчёты"])


def _counts_by(column: str, where: str = "", params: tuple = ()) -> dict[str, int]:
    """Число проектов по значению поля. Таблица всегда с алиасом p: условия,
    которые передают вызывающие, используют префикс p."""
    rows = query(f"SELECT {column} AS k, COUNT(*) AS n FROM projects p"
                 f" WHERE {where or '1=1'} GROUP BY {column}", params)
    return {r["k"]: r["n"] for r in rows if r["k"]}


# ===========================================================================
#  FR-26: сводная панель портфеля
# ===========================================================================

@router.get("/dashboard")
def dashboard(actor: CurrentActor, program_id: str | None = None):
    """Сводные показатели портфеля и перечень вопросов, требующих решения.

    Один ответ, одна страница; зелёные проекты показываются сводно (п.8).
    """
    require_portfolio_access(actor)
    where = ["p.archived_at IS NULL"]
    params: list = []
    if program_id:
        where.append("p.program_id = ?")
        params.append(program_id)
    clause = " AND ".join(where)

    total = scalar(f"SELECT COUNT(*) FROM projects p WHERE {clause}", tuple(params), 0)
    by_status = _counts_by("status", clause, tuple(params))
    by_route = _counts_by("route", clause, tuple(params))
    by_risk = _counts_by("risk_level", clause, tuple(params))

    total_results = scalar(
        # COUNT(DISTINCT r.id), а не COUNT(*): один результат может быть связан
        # с несколькими проектами, но учитывается в статистике один раз
        # (FR-17, п.6.1 п.3, сценарий ПС-12).
        "SELECT COUNT(DISTINCT r.id) FROM results r JOIN result_projects rp"
        f" ON rp.result_id = r.id JOIN projects p ON p.id = rp.project_id WHERE {clause}"
        " AND r.archived_at IS NULL", tuple(params), 0)

    questions = _questions(clause, tuple(params))
    deadlines = _deadlines(clause, tuple(params), limit=15)
    overdue = scalar(
        "SELECT COUNT(*) FROM milestones m JOIN projects p ON p.id = m.project_id"
        f" WHERE {clause} AND m.archived_at IS NULL"
        " AND m.status = 'overdue'", tuple(params), 0)
    red = by_risk.get("red", 0)
    yellow = by_risk.get("yellow", 0)

    return {
        "totals": {
            "projects": total,
            "active": sum(by_status.get(s, 0) for s in ACTIVE_STATUSES),
            "completed": by_status.get("ST-11", 0),
            "closed": by_status.get("ST-12", 0),
            "drafts": by_status.get("ST-01", 0),
            "results": total_results,
            "overdue_milestones": overdue,
        },
        "by_status": [
            {"code": k, "title": STATUS_TITLES.get(k, k), "count": v}
            for k, v in sorted(by_status.items())
        ],
        "by_route": [
            {"code": k, "title": ROUTES.get(k, k), "count": v} for k, v in sorted(by_route.items())
        ],
        "by_risk": [
            {"code": k, "title": RISK_TITLES.get(k, k), "count": v}
            for k, v in sorted(by_risk.items(), key=lambda i: {"red": 0, "yellow": 1}.get(i[0], 2))
        ],
        "risk_summary": {
            "green": by_risk.get("green", 0),
            "yellow": yellow,
            "red": red,
            "green_note": "Зелёные проекты отображаются сводно, без отдельного рассмотрения",
            "yellow_action": required_response("yellow")["action"],
            "red_action": required_response("red")["action"],
        },
        "questions_for_decision": questions,
        "deadlines": deadlines,
        "generated_at": today_iso(),
    }


def _questions(clause: str, params: tuple) -> list[dict]:
    """Перечень вопросов, требующих решения (FR-26, п.8)."""
    out: list[dict] = []

    red_rows = query(
        f"SELECT p.id, p.code, p.title, p.status, p.risk_level FROM projects p"
        f" WHERE {clause} AND p.risk_level = 'red' ORDER BY p.code LIMIT 20", params)
    for row in red_rows:
        out.append({
            "kind": "risk_red",
            "severity": "critical",
            "project_id": row["id"], "code": row["code"], "title": row["title"],
            "question": "Красный индикатор риска: проректор рассматривает за 5 рабочих дней "
                        "и может приостановить проект (п.5.4)",
            "who": "Проректор по науке",
        })

    yellow_rows = query(
        f"SELECT p.id, p.code, p.title FROM projects p WHERE {clause}"
        f" AND p.risk_level = 'yellow' ORDER BY p.code LIMIT 20", params)
    for row in yellow_rows:
        out.append({
            "kind": "risk_yellow",
            "severity": "high",
            "project_id": row["id"], "code": row["code"], "title": row["title"],
            "question": "Жёлтый индикатор: руководитель за 5 рабочих дней указывает причину, "
                        "меры и новый срок (п.5.4)",
            "who": "Руководитель проекта",
        })

    check_rows = query(
        f"SELECT p.id, p.code, p.title, p.updated_at FROM projects p"
        f" WHERE {clause} AND p.status = 'ST-02' ORDER BY p.updated_at LIMIT 20", params)
    for row in check_rows:
        out.append({
            "kind": "completeness",
            "severity": "normal",
            "project_id": row["id"], "code": row["code"], "title": row["title"],
            "question": "Ожидает проверки комплектности: срок до 3 рабочих дней (п.5.5)",
            "who": "Секретарь Научного совета",
        })

    review_rows = query(
        f"SELECT p.id, p.code, p.title, r.due_at FROM reviews r"
        f" JOIN projects p ON p.id = r.project_id"
        f" WHERE {clause} AND r.finalized_at IS NULL AND r.recused_at IS NULL"
        f" AND r.due_at IS NOT NULL AND r.due_at <= date('now', '+3 day')"
        f" ORDER BY r.due_at LIMIT 20", params)
    for row in review_rows:
        overdue = row["due_at"] < today_iso()
        out.append({
            "kind": "review_due",
            "severity": "high" if overdue else "normal",
            "project_id": row["id"], "code": row["code"], "title": row["title"],
            "question": (f"Экспертиза просрочена: срок был {fmt_date(row['due_at'])}, "
                         "срок заключения — 10 рабочих дней (п.5.5)" if overdue else
                         f"Экспертиза сдаётся {fmt_date(row['due_at'])}"),
            "who": "Секретарь (замена эксперта) либо проректор",
        })

    decision_rows = query(
        f"SELECT p.id, p.code, p.title, p.route FROM projects p"
        f" WHERE {clause} AND p.status = 'ST-05' ORDER BY p.updated_at LIMIT 20", params)
    for row in decision_rows:
        out.append({
            "kind": "awaiting_decision",
            "severity": "high",
            "project_id": row["id"], "code": row["code"], "title": row["title"],
            "question": "Ожидается решение уполномоченного лица: срок до 5 рабочих "
                        "дней после заключения (п.5.5)",
            "who": "Куратор программы" if row["route"] == "simplified" else "Проректор по науке",
        })

    route_rows = query(
        f"SELECT p.id, p.code, p.title FROM projects p WHERE {clause}"
        f" AND p.route_auto = 'full' AND p.route = 'simplified'"
        f" AND p.status NOT IN ('ST-11','ST-12') ORDER BY p.code LIMIT 20", params)
    for row in route_rows:
        out.append({
            "kind": "route_mismatch",
            "severity": "high",
            "project_id": row["id"], "code": row["code"], "title": row["title"],
            "question": "Система предлагает полный маршрут по признакам T-01…T-06, "
                        "но маршрут остался упрощённым — нужно решение уполномоченного "
                        "лица (FR-09)",
            "who": "Проректор по науке",
        })

    order = {"critical": 0, "high": 1, "normal": 2}
    out.sort(key=lambda q: order.get(q["severity"], 3))
    return out[:50]


def _deadlines(clause: str, params: tuple, limit: int = 15) -> list[dict]:
    """Ближайшие и просроченные сроки (раздел 8, «Контроль сроков»)."""
    today = today_iso()
    rows = query(
        f"SELECT m.id, m.title, m.planned_date, m.status, p.id AS project_id, p.code,"
        f" p.title AS project_title, per.full_name AS responsible"
        f" FROM milestones m JOIN projects p ON p.id = m.project_id"
        f" LEFT JOIN persons per ON per.id = m.responsible_person_id"
        f" WHERE {clause} AND m.archived_at IS NULL"
        f" AND m.status NOT IN ('done','cancelled')"
        f" ORDER BY m.planned_date LIMIT ?", params + (limit * 3,))
    items = []
    for row in rows:
        d1 = date.fromisoformat(row["planned_date"])
        delay = working_days_between(d1, today_msk())
        items.append({
            "milestone_id": row["id"],
            "project_id": row["project_id"],
            "code": row["code"],
            "project_title": row["project_title"],
            "title": row["title"],
            "planned_date": row["planned_date"],
            "planned_date_fmt": fmt_date(row["planned_date"]),
            "responsible": row["responsible"],
            "status": row["status"],
            "overdue": row["planned_date"] < today,
            "delay_working_days": delay if row["planned_date"] < today else 0,
            "suggested_new_date": fmt_date(add_working_days(today_msk(), 10))
            if row["planned_date"] < today else None,
        })
    overdue = [i for i in items if i["overdue"]][:limit]
    upcoming = [i for i in items if not i["overdue"]][:limit]
    return {"overdue": overdue, "upcoming": upcoming}


# ===========================================================================
#  FR-24: внутрисистемный список назначений и просрочек
# ===========================================================================

@router.get("/reminders")
def reminders(actor: CurrentActor):
    """Напоминания внутри системы (FR-24). Электронная почта — вторая очередь.

    Одна сводка: что требует действия пользователя прямо сейчас.
    """
    items: list[dict] = []
    person_id = actor.person_id

    if person_id:
        for row in query(
            "SELECT r.id, r.due_at, p.id AS project_id, p.code, p.title"
            " FROM reviews r JOIN projects p ON p.id = r.project_id"
            " WHERE r.expert_person_id = ? AND r.finalized_at IS NULL"
            " AND r.recused_at IS NULL ORDER BY r.due_at", (person_id,)):
            items.append({
                "kind": "review", "severity": "high" if row["due_at"] < today_iso() else "normal",
                "title": f"Заключение по проекту {row['code']}",
                "detail": f"Срок {fmt_date(row['due_at'])} (10 рабочих дней, п.5.5)",
                "due_at": row["due_at"], "link": f"/reviews/{row['id']}",
                "project_id": row["project_id"],
            })

    scoped_rows = query(
        "SELECT p.id, p.code, p.title, p.risk_level FROM projects p"
        " WHERE p.archived_at IS NULL AND p.risk_level IN ('yellow','red')"
        " AND p.status NOT IN ('ST-11','ST-12')"
        " AND (p.leader_person_id = ? OR ? IS NULL) ORDER BY p.risk_level, p.code",
        (person_id, person_id))
    for row in scoped_rows:
        action = required_response(row["risk_level"])
        items.append({
            "kind": f"risk_{row['risk_level']}",
            "severity": "critical" if row["risk_level"] == "red" else "high",
            "title": f"{RISK_TITLES[row['risk_level']]} риск: {row['code']}",
            "detail": action["action"],
            "project_id": row["id"], "link": f"/projects/{row['id']}",
        })

    check_rows = query(
        "SELECT p.id, p.code, p.title, p.updated_at FROM projects p"
        " WHERE p.archived_at IS NULL AND p.status = 'ST-02' ORDER BY p.updated_at LIMIT 20")
    for row in check_rows:
        items.append({
            "kind": "completeness",
            "severity": "normal",
            "title": f"Проверка комплектности: {row['code']}",
            "detail": f"Карточка ждёт проверки с {fmt_date(row['updated_at'])}, "
                      f"срок до 3 рабочих дней (п.5.5)",
            "project_id": row["id"], "link": f"/projects/{row['id']}",
        })

    for row in query(
        "SELECT d.id, d.topic, d.status FROM dissertations d"
        " WHERE d.archived_at IS NULL AND d.status = 'admitted_to_defense' LIMIT 20"):
        items.append({
            "kind": "dissertation",
            "severity": "normal",
            "title": f"Диссертация допущена к защите: {row['topic'][:80]}",
            "detail": "Нужно назначить защиту",
            "link": f"/dissertations/{row['id']}",
        })

    order = {"critical": 0, "high": 1, "normal": 2}
    items.sort(key=lambda i: order.get(i["severity"], 3))
    return {"items": items[:50],
            "counts": {
                "critical": sum(1 for i in items if i["severity"] == "critical"),
                "high": sum(1 for i in items if i["severity"] == "high"),
                "normal": sum(1 for i in items if i["severity"] == "normal"),
            },
            "note": "Электронные уведомления по почте — вторая очередь (FR-24)"}


# ===========================================================================
#  Обзор программы (п.8) и обзор Научного совета (п.8)
# ===========================================================================

@router.get("/reports/program/{program_id}")
def program_review(program_id: str, actor: CurrentActor):
    """Обзор программы: проекты, статусы, риски, результаты, потребность в поддержке."""
    scoped = attach_relations(actor, program_id)
    program = query_one("SELECT * FROM programs WHERE id = ?", (program_id,))
    if program is None:
        raise HTTPException(status_code=404, detail="Программа не найдена")
    if not scoped.is_curator_of_project and not (actor.global_roles & {
            ROLE_PRORECTOR, ROLE_RECTOR, ROLE_COUNCIL, ROLE_SECRETARY, ROLE_SYSADMIN}):
        raise HTTPException(status_code=403,
                            detail="Обзор программы доступен куратору и руководству")
    out = dict(program)
    out["curators"] = [dict(r) for r in query(
        "SELECT p.id, p.full_name FROM program_curators pc"
        " JOIN persons p ON p.id = pc.person_id WHERE pc.program_id = ?", (program_id,))]
    out["by_status"] = [{"code": k, "title": STATUS_TITLES.get(k, k), "count": v}
                        for k, v in _counts_by(
                            "status", "program_id = ? AND archived_at IS NULL",
                            (program_id,)).items()]
    out["by_risk"] = [{"code": k, "title": RISK_TITLES.get(k, k), "count": v}
                      for k, v in _counts_by(
                          "risk_level", "program_id = ? AND archived_at IS NULL",
                          (program_id,)).items()]
    out["projects"] = [dict(r) for r in query(
        "SELECT id, code, title, status, risk_level, route, planned_start, planned_end"
        " FROM projects WHERE program_id = ? AND archived_at IS NULL ORDER BY code",
        (program_id,))]
    out["results"] = [dict(r) for r in query(
        "SELECT r.id, r.code, r.title, r.result_type, r.readiness_stage FROM results r"
        " JOIN result_projects rp ON rp.result_id = r.id"
        " WHERE rp.project_id IN (SELECT id FROM projects WHERE program_id = ?)"
        " AND r.archived_at IS NULL ORDER BY r.code", (program_id,))]
    out["students"] = [dict(r) for r in query(
        "SELECT st.id, st.assignment, st.status, pe.full_name AS student"
        " FROM student_tasks st JOIN persons pe ON pe.id = st.student_person_id"
        " WHERE st.project_id IN (SELECT id FROM projects WHERE program_id = ?)"
        " AND st.archived_at IS NULL ORDER BY st.planned_end", (program_id,))]
    return out


@router.get("/reports/council")
def council_review(actor: CurrentActor):
    """Обзор Научного совета: программы, динамика портфеля, исключения, результаты.

    Раз в квартал (п.2.3 «минимум согласований»): Совет рассматривает портфель
    и исключения, а не каждый стандартный проект.
    """
    if not (actor.global_roles & {ROLE_COUNCIL, ROLE_RECTOR, ROLE_PRORECTOR,
                                  ROLE_SECRETARY, ROLE_SYSADMIN}):
        raise HTTPException(status_code=403,
                            detail="Обзор Научного совета доступен Совету и руководству")
    programs = []
    for row in query("SELECT id, code, title FROM programs"
                     " WHERE archived_at IS NULL AND is_active = 1 ORDER BY title"):
        programs.append({
            "id": row["id"], "code": row["code"], "title": row["title"],
            "projects": scalar("SELECT COUNT(*) FROM projects WHERE program_id = ?"
                               " AND archived_at IS NULL", (row["id"],), 0),
            "active": scalar("SELECT COUNT(*) FROM projects WHERE program_id = ?"
                             " AND archived_at IS NULL"
                             " AND status IN ('ST-07','ST-08','ST-06')", (row["id"],), 0),
            "red_risk": scalar("SELECT COUNT(*) FROM projects WHERE program_id = ?"
                               " AND archived_at IS NULL AND risk_level = 'red'",
                               (row["id"],), 0),
            "results": scalar(
                # DISTINCT по id: результат на несколько проектов считается один
                # раз в программе, как и во всём портфеле (FR-17).
                "SELECT COUNT(DISTINCT r.id) FROM results r JOIN result_projects rp"
                " ON rp.result_id = r.id JOIN projects p ON p.id = rp.project_id"
                " WHERE p.program_id = ? AND r.archived_at IS NULL", (row["id"],), 0),
        })
    return {
        "generated_at": today_iso(),
        "period": "квартал",
        "programs": programs,
        "portfolio": {
            "by_risk": [{"code": k, "title": RISK_TITLES.get(k, k), "count": v}
                        for k, v in _counts_by("risk_level", "archived_at IS NULL").items()],
            "by_route": [{"code": k, "title": ROUTES.get(k, k), "count": v}
                         for k, v in _counts_by("route", "archived_at IS NULL").items()],
        },
        "exceptions": _exceptions(),
        "strategic_questions": _questions("archived_at IS NULL", ())[:15],
    }


def _exceptions() -> list[dict]:
    """Исключения, требующие рассмотрения Советом (п.4.2)."""
    out: list[dict] = []
    for row in query(
        "SELECT id, code, title FROM projects WHERE archived_at IS NULL"
        " AND route = 'full' AND status NOT IN ('ST-11','ST-12')"
        " AND (flag_external_funding = 1 OR flag_extra_resources = 1"
        "      OR flag_critical_infra = 1 OR flag_high_risk = 1)"
        " ORDER BY code LIMIT 50"):
        out.append({
            "project_id": row["id"], "code": row["code"], "title": row["title"],
            "exception": "Внешнее финансирование, сверхлимитный ресурс или повышенный риск — "
                         "вопрос выходит за утверждённый предел (п.4.2)",
            "who": "Ректор, при стратегическом характере — Научный совет",
        })
    for row in query(
        "SELECT id, code, title FROM projects WHERE archived_at IS NULL"
        " AND status = 'ST-12' AND updated_at >= date('now','-90 day')"
        " ORDER BY updated_at DESC LIMIT 30"):
        out.append({
            "project_id": row["id"], "code": row["code"], "title": row["title"],
            "exception": "Проект закрыт без принятого результата либо мотивированно отклонён",
            "who": "Научный совет",
        })
    return out


# ===========================================================================
#  Публикационный план и аспирантура (вторая очередь, п.8)
# ===========================================================================

@router.get("/reports/publications")
def publication_plan(actor: CurrentActor, year: int | None = None):
    """Публикационный план: публикации по стадиям, авторам, проектам, изданиям, срокам."""
    y = year or today_msk().year
    rows = query(
        "SELECT p.code AS result_code, p.title AS result_title, pub.stage, pub.target_venue,"
        " pub.submitted_at, pub.accepted_at, pub.published_at,"
        " GROUP_CONCAT(DISTINCT pr.code) AS project_codes"
        " FROM publications pub"
        " JOIN results p ON p.id = pub.result_id"
        " LEFT JOIN result_projects rp ON rp.result_id = p.id"
        " LEFT JOIN projects pr ON pr.id = rp.project_id"
        " WHERE p.archived_at IS NULL"
        " AND SUBSTR(COALESCE(pub.published_at, pub.submitted_at, pub.planned_submit_at), 1, 4) = ?"
        " GROUP BY p.id ORDER BY pub.stage, p.code", (str(y),))
    from ..api.results import PUBLICATION_STAGE_TITLES
    by_stage: dict[str, int] = {}
    items = []
    for row in rows:
        by_stage[row["stage"]] = by_stage.get(row["stage"], 0) + 1
        items.append({
            "result_code": row["result_code"],
            "result_title": row["result_title"],
            "stage": row["stage"],
            "stage_title": PUBLICATION_STAGE_TITLES.get(row["stage"], row["stage"]),
            "target_venue": row["target_venue"],
            "submitted_at": row["submitted_at"],
            "accepted_at": row["accepted_at"],
            "published_at": row["published_at"],
            "projects": (row["project_codes"] or "").split(",") if row["project_codes"] else [],
        })
    return {"year": y, "by_stage": [
        {"code": s, "title": PUBLICATION_STAGE_TITLES.get(s, s), "count": by_stage.get(s, 0)}
        for s in ("concept", "reviewing", "submitted", "revision", "accepted", "published")],
        "items": items}


@router.get("/reports/graduate")
def graduate_report(actor: CurrentActor):
    """Аспирантура и студенческая наука: связанные проекты, задачи, этапы, результаты."""
    dissertations = [dict(r) for r in query(
        "SELECT d.id, d.topic, d.specialty, d.status, d.defense_year,"
        " a.full_name AS aspirant, s.full_name AS supervisor FROM dissertations d"
        " LEFT JOIN persons a ON a.id = d.aspirant_person_id"
        " LEFT JOIN persons s ON s.id = d.supervisor_person_id"
        " WHERE d.archived_at IS NULL ORDER BY d.defense_year DESC, d.topic")]
    tasks = [dict(r) for r in query(
        "SELECT st.id, st.assignment, st.status, st.planned_start, st.planned_end,"
        " p.code AS project_code, pe.full_name AS student FROM student_tasks st"
        " JOIN projects p ON p.id = st.project_id"
        " LEFT JOIN persons pe ON pe.id = st.student_person_id"
        " WHERE st.archived_at IS NULL ORDER BY st.planned_end LIMIT 200")]
    today = today_iso()
    return {
        "dissertations": dissertations,
        "tasks": tasks,
        "counts": {
            "dissertations": len(dissertations),
            "tasks": len(tasks),
            "tasks_overdue": sum(1 for t in tasks
                                 if t["status"] not in ("done", "cancelled")
                                 and t["planned_end"] < today),
            "public_tasks": scalar("SELECT COUNT(*) FROM student_tasks"
                                   " WHERE is_public = 1 AND archived_at IS NULL", (), 0),
        },
        "note": "A-66: задача обучающегося — одна запись на одну задачу, "
                "продолжительность 6–16 недель",
    }


# ===========================================================================
#  Отчёт о просрочках и рисках (FR-27)
# ===========================================================================

@router.get("/reports/risks")
def risk_report(actor: CurrentActor, limit: int = Query(default=200, le=1000)):
    require_portfolio_access(actor)
    rows = query(
        "SELECT p.id, p.code, p.title, p.status, p.risk_level, p.risk_level_comment,"
        " r.category, r.description, r.probability, r.impact, r.measures, r.status AS risk_status"
        " FROM projects p LEFT JOIN risks r ON r.project_id = p.id AND r.archived_at IS NULL"
        " WHERE p.archived_at IS NULL AND p.risk_level IN ('yellow','red')"
        " ORDER BY CASE p.risk_level WHEN 'red' THEN 0 ELSE 1 END, p.code LIMIT ?",
        (limit,))
    return {
        "items": [dict(r) for r in rows],
        "counts": {
            "red": scalar("SELECT COUNT(*) FROM projects WHERE archived_at IS NULL"
                          " AND risk_level = 'red'", (), 0),
            "yellow": scalar("SELECT COUNT(*) FROM projects WHERE archived_at IS NULL"
                             " AND risk_level = 'yellow'", (), 0),
        },
        "actions": {k: required_response(k) for k in ("yellow", "red")},
        "note": "Статус и риск — разные поля: проект может быть «Активен» "
                "и при этом иметь жёлтый индикатор (п.5.4)",
    }


@router.get("/reports/overdue")
def overdue_report(actor: CurrentActor):
    """Отчёт по просрочкам контрольных точек (FR-27, раздел 8)."""
    require_portfolio_access(actor)
    rows = query(
        "SELECT m.id, m.title, m.planned_date, m.status, p.id AS project_id, p.code,"
        " p.title AS project_title, per.full_name AS responsible"
        " FROM milestones m JOIN projects p ON p.id = m.project_id"
        " LEFT JOIN persons per ON per.id = m.responsible_person_id"
        " WHERE m.archived_at IS NULL AND m.status = 'overdue'"
        " ORDER BY m.planned_date")
    items = []
    for row in rows:
        d1 = date.fromisoformat(row["planned_date"])
        delay = working_days_between(d1, today_msk())
        items.append({**dict(row),
                      "planned_date_fmt": fmt_date(row["planned_date"]),
                      "delay_working_days": delay,
                      "requires": ("Проректор рассматривает за 5 рабочих дней"
                                   if delay > 20 else
                                   "Руководитель за 5 рабочих дней указывает причину, "
                                   "меры и новый срок"),
                      "suggested_new_date": fmt_date(add_working_days(today_msk(), 10))})
    return {"items": items, "count": len(items),
            "red_threshold_working_days": 20}


@router.get("/reports/contribution")
def contribution_report(actor: CurrentActor):
    """Показатели фактического вклада (вторая очередь, п.8)."""
    require_portfolio_access(actor)
    rows = query(
        "SELECT pe.id, pe.full_name, pe.work_place, pe.category,"
        " COUNT(pp.id) AS projects_count,"
        " SUM(CASE WHEN pp.contribution_confirmed = 1 THEN 1 ELSE 0 END) AS confirmed_count"
        " FROM persons pe JOIN participations pp ON pp.person_id = pe.id"
        " LEFT JOIN projects p ON p.id = pp.project_id AND p.archived_at IS NULL"
        " WHERE pp.archived_at IS NULL"
        " GROUP BY pe.id ORDER BY projects_count DESC, pe.full_name LIMIT 500")
    items = []
    for row in rows:
        person = dict(row)
        person["results_count"] = scalar(
            "SELECT COUNT(*) FROM results r WHERE r.authors LIKE ?"
            " AND r.archived_at IS NULL", (f'%"{row["id"]}"%',), 0)
        person["confirmed_share"] = (
            round(person["confirmed_count"] / person["projects_count"], 2)
            if person["projects_count"] else 0)
        items.append(person)
    return {"items": items,
            "note": "Показатели фактического вклада — вторая очередь (п.12.2 позиция 5)"}