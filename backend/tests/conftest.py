# -*- coding: utf-8 -*-
"""Фикстуры автотестов реестра научных проектов (ТЗ v1.0 от 06.10.2026).

ТРИ ТРЕБОВАНИЯ, КОТОРЫЕ ЗДЕСЬ ОБЕСПЕЧЕНЫ:

1. ИЗОЛЯЦИЯ. Каждый тест работает на СВОЕЙ базе в отдельном каталоге.
   Рабочая база backend/data/registry.db не открывается и не изменяется.
2. НЕТ СЕТИ. Приложение поднимается через TestClient (in-process ASGI),
   обращения к живому серверу не выполняются.
3. НЕТ ЗАВИСИМОСТИ ОТ ПОРЯДКА. Каждая фикстура создаёт своё состояние,
   общий кэш ограничения частоты публичного API сбрасывается перед тестом.

Почему приходится подменять db._local:
    app.db держит соединение в threading.local — по одному на поток.
    TestClient выполняет синхронные обработчики в пуле потоков anyio, и эти
    потоки живут дольше одного теста. Если только заменить путь к базе,
    рабочий поток возьмёт из своего threading.local Соединение с прошлой
    базой и прочитает чужие данные. Поэтому перед каждым тестом создаётся
    НОВЫЙ threading.local: потоки лениво открывают соединение уже с новым
    путём. Старые файлы баз не удаляются намеренно (на Windows удаление
    файла, открытого чужой нитью, запрещено) — они лежат во временном
    каталоге сессии и удаляются целиком после прогона.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
#  Пути и окружение — ДО импорта app.config
# ---------------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# settings — frozen dataclass, значения читаются один раз при импорте модуля,
# поэтому переменные окружения выставляются до первого «from app…».
os.environ["DEBUG"] = "true"                 # без SECRET_KEY — временный ключ
os.environ["DATABASE_PATH"] = str(Path(tempfile.gettempdir()) / "registry-tests-unused.db")
os.environ["BACKUP_DIR"] = str(Path(tempfile.gettempdir()) / "registry-tests-unused-backups")
os.environ.pop("SECRET_KEY", None)            # ключ из .env в тестах не используется

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app import security as _security  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import execute, query, query_one, scalar  # noqa: E402  (удобно в тестах)
from app.main import app as fastapi_app  # noqa: E402
from app.security import grant_role, hash_password  # noqa: E402
from app.utils import (  # noqa: E402
    add_working_days, is_working_day, new_id, now_iso, today_iso, today_msk,
)
from datetime import date, timedelta  # noqa: E402

#: Пароль тестовых учётных записей. Живых секретов в тестах нет (SEC-05):
#: значение используется только против изолированной временной базы.
TEST_PASSWORD = "Proverka-2026-Testovyi!"

#: Число раундов PBKDF2, требуемое п.11.1/SEC-07. Запоминаем ДО подмены:
#: проверка требования делается на настоящих раундах отдельным тестом.
PBKDF2_ROUNDS_REQUIRED: int = _security.PBKDF2_ROUNDS
PBKDF2_ROUNDS_TESTS: int = 1_000
_security.PBKDF2_ROUNDS = PBKDF2_ROUNDS_TESTS


@pytest.fixture
def real_pbkdf2():
    """Временно вернуть настоящее число раундов PBKDF2 (260 000)."""
    previous = _security.PBKDF2_ROUNDS
    _security.PBKDF2_ROUNDS = PBKDF2_ROUNDS_REQUIRED
    yield PBKDF2_ROUNDS_REQUIRED
    _security.PBKDF2_ROUNDS = previous


@pytest.fixture
def password() -> str:
    """Пароль тестовых учётных записей, который требуется приложению."""
    return TEST_PASSWORD


# ---------------------------------------------------------------------------
#  Изолированная база на каждый тест
# ---------------------------------------------------------------------------

_CASE_COUNTER = itertools.count()

#: Сколько каталогов с базами держать одновременно. Старые удаляются: файлы
#: баз невелики, но сотня прогонов незаметно съедает временный каталог.
#: Оставляем запас — рабочие потоки TestClient живут дольше одного теста.
_KEEP_CASES = 3


@pytest.fixture(scope="session")
def _tmp_root():
    """Каталог сессии: на каждый тест — подкаталог со своей базой."""
    root = Path(tempfile.mkdtemp(prefix="registry-pytest-"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_db(_tmp_root):
    """Свежая база на каждый тест (автоматически для всех тестов каталога)."""
    case_dir = _tmp_root / f"case-{next(_CASE_COUNTER):04d}"
    case_dir.mkdir(parents=True, exist_ok=True)
    db_path = case_dir / "registry.db"

    # Подчищаем базы прошлых тестов, оставляя запас для «живущих» потоков.
    existing = sorted(p for p in _tmp_root.glob("case-*") if p.is_dir())
    for old in existing[:-_KEEP_CASES]:
        shutil.rmtree(old, ignore_errors=True)

    db._local = threading.local()
    object.__setattr__(settings, "database_path", str(db_path))
    object.__setattr__(settings, "backup_dir", str(case_dir / "backups"))

    db.reset_database()          # миграции применены, данных нет

    # Счётчик частоты публичного API живёт в памяти процесса: без сброса
    # один тест исчерпал бы лимит для следующего.
    from app.api import public_api
    public_api._limiter = None

    yield db_path

    db._local = threading.local()   # освободить соединения потоков прошлого теста
    from app.api import public_api as _pa
    _pa._limiter = None


@pytest.fixture
def db_path(isolated_db) -> Path:
    """Путь к базе текущего теста."""
    return isolated_db


@pytest.fixture
def client():
    """TestClient с выполненным lifespan (миграции, уборка сессий)."""
    with TestClient(fastapi_app) as test_client:
        yield test_client


@pytest.fixture
def raw_client():
    """TestClient без авторизации — для негативных проверок доступа."""
    with TestClient(fastapi_app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
#  Люди и учётные записи
# ---------------------------------------------------------------------------

@dataclass
class TestUser:
    id: str
    login: str
    person_id: str
    full_name: str
    email: str
    roles: list[str] = field(default_factory=list)

    @property
    def is_leader(self) -> bool:
        return False


def _make_user(login: str, full_name: str, roles: list[str] | None = None,
               *, email: str | None = None, category: str = "staff",
               is_active: bool = 1, password: str = TEST_PASSWORD) -> TestUser:
    """Создать профиль человека, учётную запись и роли."""
    roles = list(roles or [])
    email = email or f"{login}@iubip.test"
    now = now_iso()

    person_id = new_id()
    execute(
        "INSERT INTO persons (id, full_name, service_contact, category, work_place,"
        " position, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (person_id, full_name, email, category, "Южный университет (ИУБиП)",
         "сотрудник", now),
    )
    user_id = new_id()
    execute(
        "INSERT INTO users (id, login, email, full_name, password_hash, role,"
        " is_active, must_reset, person_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'employee', ?, 0, ?, ?)",
        (user_id, login, email, full_name, hash_password(password), is_active,
         person_id, now),
    )
    for role in roles:
        grant_role(user_id, role, None)
    return TestUser(id=user_id, login=login, person_id=person_id,
                    full_name=full_name, email=email, roles=roles)


@pytest.fixture
def user_factory():
    return _make_user


@pytest.fixture
def users():
    """Участники всех ролей по п.4 ТЗ (FR-01, FR-02)."""
    return {
        "admin": _make_user("admin", "Администратор системы",
                            ["sysadmin", "techadmin"], email="admin@iubip.test"),
        "techadmin": _make_user("techadmin2", "Технический администратор",
                                ["techadmin"], email="techadmin@iubip.test"),
        "prorector": _make_user("prorector", "Мартынов Борис Владимирович",
                                ["prorector"]),
        "rector": _make_user("rector", "Ректор университета", ["rector"]),
        "council": _make_user("council", "Научный совет", ["council"]),
        "secretary": _make_user("secretary", "Секретарь Научного совета",
                                ["secretary"]),
        "curator": _make_user("curator", "Петрова Ирина Сергеевна", []),
        "leader1": _make_user("leader1", "Иванов Иван Иванович", []),
        "leader2": _make_user("leader2", "Смирнова Ольга Петровна", []),
        "expert1": _make_user("expert1", "Кузнецов Павел Андреевич", []),
        "expert2": _make_user("expert2", "Волкова Елена Николаевна", []),
        "outsider": _make_user("outsider", "Посторонний сотрудник", []),
    }


# ---------------------------------------------------------------------------
#  Научные программы
# ---------------------------------------------------------------------------

def _make_program(code: str, title: str, *, public_allowed: int = 1,
                  is_active: int = 1, short_title: str | None = None) -> dict:
    pid = new_id()
    execute(
        "INSERT INTO programs (id, code, title, short_title, description,"
        " expected_results, planned_start, planned_end, is_active, public_allowed,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, '2026-01-01', '2028-12-31', ?, ?, ?)",
        (pid, code, title, short_title or title, f"Описание программы {code}",
         "Методики и публикации", is_active, public_allowed, now_iso()),
    )
    return dict(query_one("SELECT * FROM programs WHERE id = ?", (pid,)))


@pytest.fixture
def program_factory():
    return _make_program


@pytest.fixture
def program(users):
    """Публичная программа НП-01, куратор — пользователь curator."""
    first = _make_program("НП-01", "Цифровая трансформация образовательного процесса",
                          public_allowed=1)
    execute(
        "INSERT INTO program_curators (program_id, person_id, appointed_at)"
        " VALUES (?, ?, ?)",
        (first["id"], users["curator"].person_id, now_iso()),
    )
    return first


@pytest.fixture
def closed_program():
    """Программа, не передаваемая в публичный контур (public_allowed = 0)."""
    return _make_program("НП-04", "Правовые механизмы цифровой среды", public_allowed=0)


# ---------------------------------------------------------------------------
#  Проекты, точки, риски, результаты
# ---------------------------------------------------------------------------

def working_days_ago(days: int, holidays: set[str] | None = None) -> str:
    """Дата, отстоящая на N РАБОЧИХ дней назад (ISO).

    Обратная операция к app.utils.working_days_between: между этой датой и
    сегодня должно быть ровно N рабочих дней.

    app.utils.add_working_days умеет только «вперёд», поэтому назад считаем
    отдельно. Считать назад от сегодняшней даты нельзя: если сегодня выходной,
    счётчик приземляется на рабочий день, который рабочий счёт между датами не
    учитывает (тот исключает начало отрезка), и проверки просрочки расходятся на
    единицу — ровно в дни, когда тесты запускают в субботу или воскресенье.
    Поэтому сначала сегодняшняя дата приводится к последнему рабочему дню:
    после него рабочих дней всё равно нет, а счёт становится симметричным.
    """
    cursor = today_msk()
    while not is_working_day(cursor, holidays):
        cursor -= timedelta(days=1)
    remaining = days
    while remaining > 0:
        cursor -= timedelta(days=1)
        if is_working_day(cursor, holidays):
            remaining -= 1
    return cursor.isoformat()


def working_days_ahead(days: int, holidays: set[str] | None = None) -> str:
    return add_working_days(today_msk(), days).isoformat()


@pytest.fixture
def ago():
    return working_days_ago


@pytest.fixture
def ahead():
    return working_days_ahead


def _default_project_values(*, program_id: str, created_by: str) -> dict:
    today = today_msk()
    return {
        "program_id": program_id,
        "title": "Адаптивные методы управления качеством образовательных услуг",
        "short_title": "Адаптивное управление качеством",
        "public_annotation": "Открытая аннотация проекта для публичного раздела.",
        "theme_link": "Система управления качеством образовательного процесса",
        "status": "ST-01",
        "risk_level": "green",
        "publish_mode": "none",
        "planned_start": today.isoformat(),
        "planned_end": add_working_days(today, 400).isoformat(),
        "problem": "Доля формальных процедур контроля качества растёт.",
        "question": "Снижает ли адаптивный контроль издержки преподавателя?",
        "goal": "Построить и проверить модель адаптивного контроля качества.",
        "methods": json.dumps([{"code": "comparative", "title": "Сравнительный анализ"}],
                              ensure_ascii=False),
        "data_basis": "Анкеты 1200 преподавателей, журналы успеваемости 2019–2025",
        "planned_result_type": "methodology",
        "result_criteria": json.dumps([{"title": "Снижение доли ручных проверок на 30%"}],
                                      ensure_ascii=False),
        "created_by": created_by,
    }


def _make_project(*, program_id: str, created_by: str, leader_person_id: str | None = None,
                  title: str | None = None, team: bool = True, milestone: bool = True,
                  **over) -> dict:
    """Создать карточку проекта напрямую в БД (минуя HTTP и поиск дублей)."""
    from app.services.projects import build_search_blob, next_project_code, suggest_route

    values = _default_project_values(program_id=program_id, created_by=created_by)
    values["title"] = title or values["title"]
    values.update(over)
    values.setdefault("leader_person_id", leader_person_id)

    # Маршрут выводится из признаков T-01…T-06 той же функцией, что и в
    # приложении, — иначе тесты проверяли бы несуществующий маршрут.
    route, full_reasons = suggest_route(values)
    route_fixed = values.pop("route", None)
    values["route"] = route_fixed or route
    values["route_auto"] = values.pop("route_auto", None) or route

    now = now_iso()
    row = {
        "id": new_id(),
        "code": next_project_code(),
        "status_changed_at": now,
        "risk_changed_at": now,
        "created_at": now,
        "updated_at": now,
        "updated_by": created_by,
        "version": 1,
    }
    row.update(values)
    row["search_blob"] = build_search_blob(row)

    names = list(row)
    execute(
        f"INSERT INTO projects ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
        tuple(row[n] for n in names),
    )
    for reason in full_reasons:
        execute("INSERT OR IGNORE INTO project_full_route_reasons"
                " (project_id, reason, added_at, added_by) VALUES (?, ?, ?, ?)",
                (row["id"], reason, now, created_by))
    if team and row.get("leader_person_id"):
        execute(
            "INSERT INTO participations (id, project_id, person_id, role, task,"
            " is_public, created_at, created_by)"
            " VALUES (?, ?, ?, 'leader', 'Руководитель проекта', 1, ?, ?)",
            (new_id(), row["id"], row["leader_person_id"], now, created_by),
        )
    if milestone and row.get("leader_person_id"):
        _make_milestone(row["id"], responsible_person_id=row["leader_person_id"],
                        created_by=created_by,
                        planned_date=add_working_days(today_msk(), 60).isoformat())
    return dict(query_one("SELECT * FROM projects WHERE id = ?", (row["id"],)))


def _make_milestone(project_id: str, *, responsible_person_id: str | None = None,
                    created_by: str | None = None, planned_date: str | None = None,
                    status: str = "planned", title: str = "Промежуточный отчёт",
                    **over) -> dict:
    mid = new_id()
    now = now_iso()
    values = {
        "id": mid,
        "project_id": project_id,
        "title": title,
        "planned_date": planned_date or today_iso(),
        "responsible_person_id": responsible_person_id,
        "planned_evidence": "Отчёт с результатами",
        "status": status,
        "created_at": now,
        "created_by": created_by,
        "updated_at": now,
    }
    values.update(over)
    names = list(values)
    execute(
        f"INSERT INTO milestones ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
        tuple(values[n] for n in names),
    )
    return dict(query_one("SELECT * FROM milestones WHERE id = ?", (mid,)))


def _make_risk(project_id: str, *, level: str = "yellow", category: str = "data",
               description: str = "Неполнота данных за 2020–2021 годы",
               probability: str = "medium", impact: str = "medium",
               status: str = "open", created_by: str | None = None) -> dict:
    rid = new_id()
    execute(
        "INSERT INTO risks (id, project_id, category, description, probability, impact,"
        " status, level, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rid, project_id, category, description, probability, impact, status, level,
         now_iso(), created_by),
    )
    return dict(query_one("SELECT * FROM risks WHERE id = ?", (rid,)))


def _make_result(*, project_ids: list[str], authors: list[str], created_by: str,
                 readiness_stage: str = "produced", publish_allowed: int = 0,
                 is_public: int = 0, confirmation: str | None = None,
                 title: str | None = None, code: str | None = None,
                 **over) -> dict:
    from app.services.projects import next_result_code

    rid = new_id()
    now = now_iso()
    values = {
        "id": rid,
        "code": code or next_result_code(),
        "result_type": "methodology",
        "title": title or "Методика адаптивного контроля качества",
        "description": "Методика расчёта адаптивного интервала контроля качества.",
        "authors": json.dumps(authors, ensure_ascii=False),
        "readiness_stage": readiness_stage,
        "actual_date": today_iso() if readiness_stage in
                       ("accepted", "published", "implemented") else None,
        "acceptance_criterion": "Снижение доли ручных проверок на 30%",
        "confirmation": confirmation,
        "publish_allowed": publish_allowed,
        "is_public": is_public,
        "created_at": now,
        "created_by": created_by,
        "updated_at": now,
        "search_blob": (title or "Методика адаптивного контроля качества").lower(),
    }
    values.update(over)
    names = list(values)
    execute(
        f"INSERT INTO results ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
        tuple(values[n] for n in names),
    )
    for pid in dict.fromkeys(project_ids):
        execute("INSERT OR IGNORE INTO result_projects (result_id, project_id,"
                " linked_at, linked_by) VALUES (?, ?, ?, ?)",
                (rid, pid, now, created_by))
    return dict(query_one("SELECT * FROM results WHERE id = ?", (rid,)))


def _set_status(project_id: str, status: str) -> None:
    """Проставить статус карточки напрямую — минуя матрицу переходов."""
    execute("UPDATE projects SET status = ?, status_changed_at = ? WHERE id = ?",
            (status, now_iso(), project_id))


def _set_full_route_reason(project_id: str, reason: str) -> None:
    execute("INSERT OR IGNORE INTO project_full_route_reasons"
            " (project_id, reason, added_at, added_by) VALUES (?, ?, ?, ?)",
            (project_id, reason, now_iso(), None))


def _set_public_allowed(project_id: str, user_id: str) -> None:
    """Разрешение на публикацию от уполномоченного лица (п.9.2)."""
    execute("UPDATE projects SET public_allowed_at = ?, public_allowed_by = ?"
            " WHERE id = ?", (now_iso(), user_id, project_id))


@pytest.fixture
def make_project(users, program):
    def factory(**kwargs):
        kwargs.setdefault("program_id", program["id"])
        kwargs.setdefault("created_by", users["leader1"].id)
        kwargs.setdefault("leader_person_id", users["leader1"].person_id)
        return _make_project(**kwargs)
    return factory


@pytest.fixture
def project(make_project):
    """Карточка-эталон: упрощённый маршрут, статус «Черновик», риск зелёный."""
    return make_project()


@pytest.fixture
def make_milestone():
    return _make_milestone


@pytest.fixture
def make_risk():
    return _make_risk


@pytest.fixture
def make_result(users):
    def factory(**kwargs):
        kwargs.setdefault("created_by", users["leader1"].id)
        if "authors" not in kwargs:
            kwargs["authors"] = [users["leader1"].person_id]
        return _make_result(**kwargs)
    return factory


@pytest.fixture
def set_status():
    return _set_status


@pytest.fixture
def set_full_route_reason():
    return _set_full_route_reason


@pytest.fixture
def set_public_allowed():
    return _set_public_allowed


# ---------------------------------------------------------------------------
#  Обёртка над клиентом: вход и авторизация
# ---------------------------------------------------------------------------

class Api:
    """TestClient + вход по логинам. Токены кэшируются внутри одного теста."""

    def __init__(self, client: TestClient):
        self.client = client
        self.tokens: dict[str, str] = {}

    def login(self, login: str, password: str = TEST_PASSWORD) -> str:
        response = self.client.post("/api/auth/login",
                                    json={"login": login, "password": password})
        assert response.status_code == 200, (
            f"вход {login} не удался: {response.status_code} {response.text[:300]}")
        self.tokens[login] = response.json()["token"]
        return self.tokens[login]

    def token(self, login: str) -> str:
        return self.tokens.get(login) or self.login(login)

    def headers(self, login: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(login)}"}

    def get(self, path: str, login: str | None = None, **kwargs):
        if login:
            kwargs["headers"] = {**(kwargs.get("headers") or {}), **self.headers(login)}
        return self.client.get(path, **kwargs)

    def post(self, path: str, login: str | None = None, **kwargs):
        if login:
            kwargs["headers"] = {**(kwargs.get("headers") or {}), **self.headers(login)}
        return self.client.post(path, **kwargs)

    def patch(self, path: str, login: str | None = None, **kwargs):
        if login:
            kwargs["headers"] = {**(kwargs.get("headers") or {}), **self.headers(login)}
        return self.client.patch(path, **kwargs)

    def put(self, path: str, login: str | None = None, **kwargs):
        if login:
            kwargs["headers"] = {**(kwargs.get("headers") or {}), **self.headers(login)}
        return self.client.put(path, **kwargs)

    def delete(self, path: str, login: str | None = None, **kwargs):
        if login:
            kwargs["headers"] = {**(kwargs.get("headers") or {}), **self.headers(login)}
        return self.client.request("DELETE", path, **kwargs)

    def request(self, method: str, path: str, login: str | None = None, **kwargs):
        if login:
            kwargs["headers"] = {**(kwargs.get("headers") or {}), **self.headers(login)}
        return self.client.request(method, path, **kwargs)


@pytest.fixture
def api(client) -> Api:
    return Api(client)


# ---------------------------------------------------------------------------
#  Заготовка файла импорта (п.7.2 п.1)
# ---------------------------------------------------------------------------

def build_import_xlsx(rows: list[dict], *, columns=None) -> bytes:
    """Собрать XLSX по форме инвентаризации.

    columns — список словарей колонок из services.transfer.IMPORT_COLUMNS.
    """
    import io

    from openpyxl import Workbook

    from app.services.transfer import IMPORT_COLUMNS

    columns = columns or IMPORT_COLUMNS
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([column["header"] for column in columns])
    for row in rows:
        sheet.append([row.get(column["key"], "") for column in columns])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_import_csv(rows: list[dict], *, columns=None, delimiter: str = ";") -> bytes:
    """Собрать CSV по форме инвентаризации (разделитель «;», UTF-8 с BOM)."""
    import csv
    import io

    from app.services.transfer import IMPORT_COLUMNS

    columns = columns or IMPORT_COLUMNS
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=delimiter)
    writer.writerow([column["header"] for column in columns])
    for row in rows:
        writer.writerow([row.get(column["key"], "") for column in columns])
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def valid_import_row(program_code: str = "НП-01", suffix: str = "1") -> dict:
    """Корректная строка формы инвентаризации (все обязательные поля)."""
    return {
        "title": f"Проект из формы инвентаризации номер {suffix}",
        "short_title": f"Проект {suffix}",
        "program_code": program_code,
        "leader_name": "Иванов Иван Иванович",
        "leader_email": "leader1@iubip.test",
        "planned_start": "2026-03-01",
        "planned_end": "2027-12-31",
        "problem": "Проблема формулируется проверяемо и измеримо.",
        "question": "Вопрос или гипотеза исследования.",
        "goal": "Одна основная цель проекта.",
        "methods": "Сравнительный анализ; анкетирование",
        "data_basis": "Источник, состав, период и условия доступа к данным.",
        "planned_result_type": "methodology",
        "result_criteria": "Не менее одного признака выполнения",
        "theme_link": "Связь с общей темой программы",
        "publish_mode": "none",
        "team": "Иванов Иван Иванович|leader|руководитель проекта",
        "milestones": "Подготовка методики|2026-06-30|Иванов Иван Иванович",
        "flags": "",
        "public_annotation": "",
    }


@pytest.fixture
def import_row_factory():
    return valid_import_row


@pytest.fixture
def xlsx_factory():
    return build_import_xlsx


@pytest.fixture
def csv_factory():
    return build_import_csv