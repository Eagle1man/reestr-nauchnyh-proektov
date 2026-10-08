"""Начальное наполнение справочников и демонстрационных данных.

Справочники (FR-30) обязательны для работы системы: без видов результатов,
методов и категорий рисков карточка не пройдёт проверку. Пользователи создаются
только при явном запуске с --with-users, пароли задаются через переменные
окружения и нигде не печатаются в журнал (SEC-05).

Запуск:
    python backend/scripts/seed.py                 # только справочники
    python backend/scripts/seed.py --with-users    # + пилотные учётные записи
    python backend/scripts/seed.py --with-demo     # + демонстрационные проекты
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_PATH", "backend/data/registry.db")

from app import db  # noqa: E402
from app.db import execute, query, query_one, scalar  # noqa: E402
from app.security import generate_password, grant_role, hash_password  # noqa: E402
from app.utils import new_id, now_iso, today_iso  # noqa: E402

DICTIONARIES: list[dict[str, list[tuple[str, str]]]] = {
    "result_type": [
        ("publication", "Публикация"),
        ("methodology", "Методика"),
        ("model", "Модель"),
        ("dataset", "Набор данных"),
        ("digital_product", "Цифровой продукт"),
        ("grant_application", "Грантовая заявка"),
        ("aprobation", "Апробация"),
        ("implementation", "Внедрение"),
        ("other", "Другое"),
    ],
    "method": [
        ("comparative", "Сравнительный анализ"),
        ("statistical", "Статистический анализ"),
        ("modeling", "Моделирование"),
        ("experiment", "Эксперимент"),
        ("survey", "Анкетирование"),
        ("interview", "Глубинное интервью"),
        ("case_study", "Разбор случая"),
        ("review", "Обзор и синтез"),
        ("experimental_design", "Экспериментальный дизайн"),
    ],
    "risk_category": [
        ("method", "Методологический риск"),
        ("data", "Риск данных"),
        ("team", "Риск команды"),
        ("resource", "Ресурсный риск"),
        ("legal", "Правовой риск"),
        ("ethical", "Этический риск"),
        ("reputational", "Репутационный риск"),
        ("informational", "Информационный риск"),
        ("schedule", "Риск сроков"),
        ("technical", "Технический риск"),
    ],
    "organization": [
        ("university", "Южный университет (ИУБиП)"),
        ("partner_university", "Университет-партнёр"),
        ("institute_ran", "Институт РАН"),
        ("business", "Организация бизнеса"),
        ("ngo", "Некоммерческая организация"),
        ("government", "Государственный орган"),
    ],
    "publication_kind": [
        ("article", "Статья в журнале"),
        ("article_ Scopus", "Статья в журнале индексируемом Scopus"),
        ("monograph", "Монография"),
        ("chapter", "Глава в книге"),
        ("conference", "Материалы конференции"),
        ("preprint", "Препринт"),
        ("book", "Книга"),
        ("review_article", "Обзорная статья"),
    ],
    "target_journal": [
        ("vestnik_iubip", "Вестник Южного университета (ИУБиП)"),
        ("innovation", "Инновации в образовании"),
        ("vysshe_obrazovanie", "Высшее образование"),
        ("open_science", "Открытая наука"),
    ],
    "party_type": [
        ("cofinancing", "Софинансирование"),
        ("consortium", "Консорциум"),
        ("contract", "Договор"),
        ("informal", "Неформальное сотрудничество"),
    ],
}

PROGRAMS = [
    {
        "code": "НП-01",
        "title": "Цифровая трансформация образовательного процесса",
        "short_title": "Цифровая трансформация",
        "description": "Научные программы в области цифровизации обучения, управления "
                       "качеством образовательных услуг и развития цифровой компетенции "
                       "преподавателей и обучающихся.",
        "criteria": "Наличие проверяемого исследовательского вопроса, метода и данных; "
                    "проблема подтверждена предварительным анализом.",
        "expected_results": "Методики оценки, модели, наборы данных для воспроизводимых "
                            "исследований, публикации в журналах списка ВАК.",
        "public_allowed": 1,
    },
    {
        "code": "НП-02",
        "title": "Устойчивое региональное развитие и территориальное управление",
        "short_title": "Устойчивое развитие",
        "description": "Экономика региона, управление территориями, оценка "
                       "социально-экономических последствий решений.",
        "criteria": "Данные о регионе доступны; метод применим к другим территориям.",
        "expected_results": "Методики оценки воздействия, эмпирические модели, "
                            "аналитические записки для органов власти.",
        "public_allowed": 1,
    },
    {
        "code": "НП-03",
        "title": "Человек, здоровье и общество",
        "short_title": "Человек и общество",
        "description": "Социальные науки, экономика труда, демография, качество жизни.",
        "criteria": "Соблюдение правовых и этических требований при работе с людьми.",
        "expected_results": "Эмпирические исследования, методики, диссертационные работы.",
        "public_allowed": 0,
    },
    {
        "code": "НП-04",
        "title": "Правовые механизмы цифровой среды",
        "short_title": "Право и цифровая среда",
        "description": "Правовое регулирование цифровых технологий, интеллектуальная "
                       "собственность, персональные данные.",
        "criteria": "Нормативная база определена; позиция подтверждена практикой.",
        "expected_results": "Нормативные предложения, монографии, публикации.",
        "public_allowed": 0,
    },
]

SETTINGS = {
    "project_code_prefix": "РНП",
    "result_code_prefix": "РЕЗ",
    "yellow_delay_working_days": "20",
    "completeness_check_days": "3",
    "expert_review_days": "10",
    "decision_days": "5",
    "student_task_min_weeks": "6",
    "student_task_max_weeks": "16",
    "public_cache_seconds": "300",
    "retention_content_years": "5",
    "retention_technical_months": "12",
}


def seed_dictionaries() -> int:
    count = 0
    for dict_name, items in DICTIONARIES.items():
        for order, (code, title) in enumerate(items, start=1):
            if query_one("SELECT id FROM dict_items WHERE dict = ? AND code = ?",
                         (dict_name, code)) is None:
                execute(
                    "INSERT INTO dict_items (id, dict, code, title, sort_order, is_active)"
                    " VALUES (?, ?, ?, ?, ?, 1)", (new_id(), dict_name, code, title, order))
                count += 1
    return count


def seed_settings() -> int:
    count = 0
    for key, value in SETTINGS.items():
        if query_one("SELECT key FROM settings WHERE key = ?", (key,)) is None:
            execute("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                    (key, value, now_iso()))
            count += 1
    return count


def seed_programs() -> int:
    count = 0
    for program in PROGRAMS:
        if query_one("SELECT id FROM programs WHERE code = ?", (program["code"],)):
            continue
        execute(
            "INSERT INTO programs (id, code, title, short_title, description, criteria,"
            " expected_results, planned_start, planned_end, is_active, public_allowed,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (new_id(), program["code"], program["title"], program["short_title"],
             program["description"], program["criteria"], program["expected_results"],
             "2026-01-01", "2028-12-31", program["public_allowed"], now_iso()))
        count += 1
    return count


def seed_users() -> list[dict]:
    """Создать пилотные учётные записи по ролям ТЗ (раздел 4).

    Пароль берётся из переменной окружения SEED_PASSWORD. Если она не задана,
    генерируется стойкий пароль, который печатается ОДИН раз в stdout —
    в журнал приложения он не попадает (SEC-05).
    """
    password = os.environ.get("SEED_PASSWORD") or generate_password()
    generated = os.environ.get("SEED_PASSWORD") is None
    admin_password = os.environ.get("SEED_ADMIN_PASSWORD") or generate_password()

    people = [
        ("admin", "Системный администратор", "admin@iubip.local",
         ["sysadmin", "techadmin"], "Системный администратор"),
        ("prorector", "Мартынов Борис Владимирович", "b.martynov@iubip.ru",
         ["prorector"], "Проректор по науке"),
        ("rector", "Ректор университета", "rector@iubip.ru", ["rector"], "Ректор"),
        ("secretary", "Секретарь Научного совета", "secretary@iubip.ru",
         ["secretary"], "Секретарь"),
        ("council", "Научный совет", "council@iubip.ru", ["council"], "Научный совет"),
        ("curator1", "Петрова Ирина Сергеевна", "i.petrova@iubip.ru", [],
         "Куратор программы НП-01"),
        ("leader1", "Иванов Иван Иванович", "i.ivanov@iubip.ru", [], "Руководитель проекта"),
        ("leader2", "Смирнова Ольга Петровна", "o.smirnova@iubip.ru", [], "Руководитель проекта"),
        ("expert1", "Кузнецов Павел Андреевич", "p.kuznetsov@iubip.ru", [], "Эксперт"),
        ("expert2", "Волкова Елена Николаевна", "e.volkova@iubip.ru", [], "Эксперт"),
        ("student1", "Сидоров Артём Игоревич", "a.sidorov@iubip.ru", [], "Аспирант"),
    ]

    created: list[dict] = []
    for login, full_name, email, roles, note in people:
        row = query_one("SELECT id FROM users WHERE login = ?", (login,))
        if row is None:
            uid = new_id()
            pwd = admin_password if login == "admin" else password
            execute(
                "INSERT INTO users (id, login, email, full_name, password_hash, role,"
                " is_active, must_reset, created_at) VALUES (?, ?, ?, ?, ?,"
                " 'employee', 1, 1, ?)",
                (uid, login, email, full_name, hash_password(pwd), now_iso()))
            for role in roles:
                grant_role(uid, role, None)
            created.append({"login": login, "password": pwd, "roles": roles, "note": note})

            category = "aspirant" if "аспирант" in note.lower() else "staff"
            if query_one("SELECT id FROM persons WHERE service_contact = ?", (email,)) is None:
                pid = new_id()
                execute(
                    "INSERT INTO persons (id, full_name, service_contact, category,"
                    " work_place, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (pid, full_name, email, category,
                     "Южный университет (ИУБиП)", now_iso()))
                execute("UPDATE users SET person_id = ? WHERE id = ?", (pid, uid))

    if created and generated:
        print("\n=== ПАРОЛИ (показываются один раз, сохраните в надёжном месте) ===")
        for item in created:
            print(f"  {item['login']:12s} {item['password']:24s} {item['note']}")
        print("=== Все учётные записи созданы с must_reset=1 ===\n")
    return created


def seed_demo() -> None:
    """Демонстрационные проекты — состав Приложения Г.

    Приложение Г требует 5–10 инициатив, из них: две записи полного маршрута,
    одна с просроченной точкой, одна с жёлтым и одна с красным риском, один
    завершённый проект, один результат на два проекта, один разрешённый и один
    запрещённый к публикации.
    """
    from app.services.projects import create_project, recompute_risk, apply_transition
    from app.access import Actor, load_actor
    from app.utils import add_working_days, today_msk
    from datetime import timedelta

    if scalar("SELECT COUNT(*) FROM projects", (), 0) > 0:
        print("Демонстрационные проекты уже есть — пропуск.")
        return

    leader_row = query_one("SELECT id FROM users WHERE login = 'leader1'")
    admin_row = query_one("SELECT id FROM users WHERE login = 'admin'")
    if leader_row is None or admin_row is None:
        print("Сначала создайте учётные записи: --with-users")
        return
    actor = load_actor(dict(leader_row))
    prorector_id = scalar("SELECT id FROM users WHERE login = 'prorector'", (), None)

    programs = {r["code"]: r["id"] for r in query("SELECT id, code FROM programs")}
    leader_person = scalar("SELECT person_id FROM users WHERE id = ?", (leader_row["id"],), None)
    today = today_msk()
    end = add_working_days(today, 400).isoformat()

    demos = [
        {
            "title": "Адаптивные методы управления качеством образовательных услуг",
            "short_title": "Адаптивное управление качеством",
            "program": "НП-01", "publish_mode": "project",
            "public_annotation": "Исследование проверяет, снижает ли адаптивный контроль "
                                 "издержки преподавателя без потери качества подготовки.",
            "problem": "Доля формальных процедур контроля качества в вузе растёт, "
                       "при этом их влияние на результаты обучения не измерено.",
            "question": "Снижает ли адаптивный контроль издержки преподавателя без потери "
                        "качества подготовки обучающихся?",
            "goal": "Построить и проверить модель адаптивного контроля качества "
                    "на данных трёх факультетов.",
            "methods": [{"code": "comparative", "title": "Сравнительный анализ"},
                        {"code": "survey", "title": "Анкетирование"}],
            "data_basis": "Анкеты 1200 преподавателей, журналы успеваемости 2019–2025",
            "planned_result_type": "methodology",
            "result_criteria": [{"title": "Снижение доли ручных проверок на 30%"}],
            "flags": {},
        },
        {
            "title": "Модель прогнозирования успеваемости по данным цифрового следа обучающегося",
            "short_title": "Прогноз успеваемости",
            "program": "НП-01", "publish_mode": "none",
            "problem": "Преподаватели узнают о проблемах обучающегося за неделю до экзамена.",
            "question": "Позволяет ли цифровой след обучающегося выявлять риск отсева "
                        "за четыре недели до дедлайна?",
            "goal": "Проверить предсказательную силу признаков цифрового следа.",
            "methods": [{"code": "modeling", "title": "Моделирование"},
                        {"code": "statistical", "title": "Статистический анализ"}],
            "data_basis": "Журналы LMS 4 курса, результаты промежуточной аттестации",
            "planned_result_type": "model",
            "result_criteria": [{"title": "Полнота 0,8 при доле ложных срабатываний до 15%"}],
            "flags": {"flag_personal_data": True},
        },
        {
            "title": "Оценка влияния цифровых сервисов на доступность образования в регионе",
            "short_title": "Доступность и цифровые сервисы",
            "program": "НП-02", "publish_mode": "project",
            "public_annotation": "Оценка влияния перехода на цифровые сервисы на доступность "
                                 "образования для сельских территорий региона.",
            "problem": "Сельские территории теряют доступ к качественному образованию при "
                       "сокращении аудиторной нагрузки.",
            "question": "Компенсируют ли цифровые сервисы сокращение аудиторной нагрузки "
                        "в сельских школах региона?",
            "goal": "Количественно оценить разрыв доступа до и после цифровизации.",
            "methods": [{"code": "comparative", "title": "Сравнительный анализ"}],
            "data_basis": "Статистика Росстата по 24 муниципалитетам, данные МЦУДО",
            "planned_result_type": "dataset",
            "result_criteria": [{"title": "Панель данных по 24 муниципалитетам за 6 лет"}],
            "flags": {"flag_external_funding": True},
        },
        {
            "title": "Правовые риски автоматической обработки персональных данных в вузах",
            "short_title": "Право и персональные данные",
            "program": "НП-04", "publish_mode": "none",
            "problem": "Вузы внедряют системы обработки персональных данных без "
                       "соответствующей правовой оценки.",
            "question": "Какие правовые риски возникают при автоматической обработке "
                        "персональных данных обучающихся?",
            "goal": "Сформировать систему правовой оценки рисков и предложения по её внедрению.",
            "methods": [{"code": "review", "title": "Обзор и синтез"},
                        {"code": "case_study", "title": "Разбор случаев"}],
            "data_basis": "Судебная практика 2019–2026, репозиторий заключений Роскомнадзора",
            "planned_result_type": "publication",
            "result_criteria": [{"title": "Методика правовой оценки внедрена в двух вузах"}],
            "flags": {"flag_confidential": True},
        },
        {
            "title": "Социально-экономические последствия сокращения числа малых предприятий",
            "short_title": "Малые предприятия",
            "program": "НП-02", "publish_mode": "results",
            "public_annotation": "Эмпирическая оценка влияния сокращения числа малых "
                                 "предприятий на занятость в моногородах.",
            "problem": "Моногорода теряют рабочие места быстрее, чем появляются новые.",
            "question": "Насколько сокращение малого бизнеса определяет уровень "
                        "безработицы в моногороде?",
            "goal": "Оценить вклад малого предпринимательства в занятость моногорода.",
            "methods": [{"code": "econometric", "title": "Эконометрический анализ"}],
            "data_basis": "Росстат, ЕМИСС, обследование 600 домохозяйств в 8 моногородах",
            "planned_result_type": "publication",
            "result_criteria": [{"title": "Статья подана в журнал из перечня ВАК"}],
            "flags": {},
        },
        {
            "title": "Методика оценки качества инклюзивного образования",
            "short_title": "Инклюзивное образование",
            "program": "НП-03", "publish_mode": "project",
            "public_annotation": "Разработка измеримых критериев качества инклюзивного "
                                 "образования для высшей школы.",
            "problem": "Университеты заявляют инклюзивность, не имея измеримых критериев.",
            "question": "Какие измеримые критерии качества инклюзивного образования "
                        "применимы в российском вузе?",
            "goal": "Разработать и валидировать инструментарий оценки качества.",
            "methods": [{"code": "expert", "title": "Экспертная оценка"}],
            "data_basis": "Экспертный опрос 40 специалистов, наблюдение в 6 вузах",
            "planned_result_type": "methodology",
            "result_criteria": [{"title": "Инструментарий прошёл проверку на согласованность"}],
            "flags": {"flag_human_subjects": True, "flag_ethics_required": True},
        },
    ]

    created_ids: list[str] = []
    for demo in demos:
        payload = {k: v for k, v in demo.items() if k not in ("program", "flags")}
        # Признаки T-01…T-06 передаются отдельными полями карточки, а не вложенным
        # объектом: сервис карточки ждёт плоские flag_*.
        payload.update(demo.get("flags") or {})
        payload["program_id"] = programs.get(demo["program"])
        result = create_project(payload=payload, user_id=leader_row["id"])
        pid = result["id"]
        created_ids.append(pid)

        execute("UPDATE projects SET leader_person_id = ?, short_title = ? WHERE id = ?",
                (leader_person, demo.get("short_title"), pid))
        if leader_person:
            execute(
                "INSERT OR IGNORE INTO participations (id, project_id, person_id, role,"
                " task, created_at, created_by) VALUES (?, ?, ?, 'leader', ?, ?, ?)",
                (new_id(), pid, leader_person, "Руководитель проекта", now_iso(),
                 leader_row["id"]))

        # Контрольные точки. Просрочка во внутреннем у всех остальных проектов:
        # просрочка в прошлом должна иметь просроченную точку
        # и зелёный индикатор, иначе предпроектов будут жёлыми и зелёными
        # (Приложение Г п.3 — ровно одна просрочка с просроченной точкой).
        overdue = demo["title"].startswith("Социально-экономические")
        base = today - timedelta(days=45) if overdue else add_working_days(today, 45)
        execute(
            "INSERT INTO milestones (id, project_id, title, planned_date,"
            " responsible_person_id, planned_evidence, status, created_at, created_by)"
            " VALUES (?, ?, ?, ?, ?, ?, 'planned', ?, ?)",
            (new_id(), pid, "Промежуточный отчёт", base.isoformat(), leader_person,
             "Отчёт с результатами", now_iso(), leader_row["id"]))
        execute(
            "INSERT INTO milestones (id, project_id, title, planned_date,"
            " responsible_person_id, planned_evidence, status, created_at, created_by)"
            " VALUES (?, ?, ?, ?, ?, ?, 'planned', ?, ?)",
            (new_id(), pid, "Итоговый отчёт",
             add_working_days(today, 180).isoformat(), leader_person,
             "Итоговый отчёт с подтверждением", now_iso(), leader_row["id"]))

        # Риски: жёлтый и красный (Приложение Г п.4)
        if demo["title"].startswith("Модель прогнозирования"):
            execute(
                "INSERT INTO risks (id, project_id, category, description, probability,"
                " impact, measures, status, level, level_comment, created_at, created_by)"
                " VALUES (?, ?, 'data', 'Неполнота цифрового следа за 2020–2021 годы',"
                " 'medium', 'medium', 'Реконструкция пропусков по смежным данным',"
                " 'open', 'yellow', NULL, ?, ?)",
                (new_id(), pid, now_iso(), leader_row["id"]))
        if demo["title"].startswith("Правовые риски"):
            execute(
                "INSERT INTO risks (id, project_id, category, description, probability,"
                " impact, measures, status, level, level_comment, created_at, created_by)"
                " VALUES (?, ?, 'legal', ?, 'high', 'high', ?, 'open', 'red', ?, ?, ?)",
                (new_id(), pid,
                 "Судебная практика "
                 "неустойчива, возможен "
                 "спор о трактовке "
                 "персональных данных",
                 "Заключение профильного "
                 "юриста до публикации",
                 "Требуется решение "
                 "проректора", now_iso(), leader_row["id"]))

        # Разрешение на публикацию
        # даёт упольночённое лицо не видет
        # (п.9.2): после режима карточки дажен отдельный
        # разреш. Приложение Г п.7 требует одного
        # с разрешённой и одного с запрещённой.
        if prorector_id and demo["publish_mode"] in ("project", "all"):
            execute("UPDATE projects SET public_allowed_at = ?, public_allowed_by = ?"
                    " WHERE id = ?", (now_iso(), prorector_id, pid))

        recompute_risk(pid)

    # Завершённый проект с принятым результатом (Приложение Г п.5)
    if created_ids:
        first = created_ids[0]
        execute("UPDATE projects SET status = 'ST-07', status_changed_at = ? WHERE id = ?",
                (now_iso(), first))
        result_id = new_id()
        execute(
            "INSERT INTO results (id, code, result_type, title, description, authors,"
            " readiness_stage, actual_date, acceptance_criterion, confirmation,"
            " created_at, created_by) VALUES (?, ?, 'methodology', ?"
            ", ?, ?, 'accepted', ?, ?, ?, ?, ?)",
            (result_id, "РЕЗ-2026-0001", "Методика адаптивного контроля качества",
             "Методика расчёта адаптивного интервала контроля качества подготовки.",
             f'["{leader_person}"]', today_iso(),
             "Снижение доли ручных проверок на 30%", "https://example.org/report-2026",
             now_iso(), leader_row["id"]))
        execute("INSERT INTO result_projects (result_id, project_id, linked_at, linked_by)"
                " VALUES (?, ?, ?, ?)", (result_id, first, now_iso(), leader_row["id"]))
        # Тот же результат связан со вторым проектом — но учитывается один раз (Приложение Г п.6)
        if len(created_ids) > 1:
            execute("INSERT OR IGNORE INTO result_projects (result_id, project_id,"
                    " linked_at, linked_by) VALUES (?, ?, ?, ?)",
                    (result_id, created_ids[1], now_iso(), leader_row["id"]))

    print(f"Создано демонстрационных проектов: {len(created_ids)}")


def main() -> None:
    applied = db.run_migrations()
    if applied:
        print("Применены миграции:", ", ".join(applied))
    print("Справочников добавлено:", seed_dictionaries())
    print("Настроек добавлено:", seed_settings())
    print("Программ добавлено:", seed_programs())
    if "--with-users" in sys.argv:
        seed_users()
        print("Учётные записи созданы.")
    if "--with-demo" in sys.argv:
        seed_demo()
    print("Готово. База:", db.settings.db_file)


if __name__ == "__main__":
    main()