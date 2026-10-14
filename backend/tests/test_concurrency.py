# -*- coding: utf-8 -*-
"""Параллельная работа — NFR-01, ПС-20 (регрессия из памяти отдела).

memories/2026/10/2026-10-02-fastapi-sqlite-threadpool:
    FastAPI выполняет синхронные обработчики в пуле потоков. Соединение
    sqlite3, созданное в одном потоке, в другом падает с ошибкой
    «SQLite objects created in a thread can only be used in that same thread».
    Урок сформулирован дважды: (1) хранить соединение в threading.local —
    по одному на поток; (2) проверять это НЕ через TestClient по одному
    запросу, а конкурентной нагрузкой. Этот файл и есть такая проверка.

Проверяем:
  * каждый поток получает СВОЁ соединение (нет «SQLite objects created in a
    thread»);
  * 50 параллельных авторизованных запросов не дают отказов;
  * параллельная запись не теряет данные и не выдаёт дубли номеров;
  * параллельное чтение возвращает одинаковый результат.
"""

from __future__ import annotations

import concurrent.futures as cf
import threading
import time


from app import db
from app.db import get_conn, query, scalar

PARALLEL_REQUESTS = 50
PARALLEL_WORKERS = 20


# ===========================================================================
#  Соединение на поток (первая половина урока)
# ===========================================================================

def test_each_thread_gets_its_own_connection():
    """Каждый поток получает своё соединение с той же базой (threading.local)."""
    main_conn = get_conn()
    assert main_conn is not None

    seen: list[tuple[int, int]] = []
    lock = threading.Lock()

    def worker(_: int) -> tuple[int, int]:
        conn = get_conn()
        with lock:
            seen.append((threading.get_ident(), id(conn)))
        # Соединение действительно рабочее в этом потоке.
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] >= 1
        return threading.get_ident(), id(conn)

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(16)))

    assert len(seen) == 16
    # Все соединения в одном потоке — одно и то же (иначе база «течёт»).
    by_thread: dict[int, set[int]] = {}
    for thread_id, conn_id in seen:
        by_thread.setdefault(thread_id, set()).add(conn_id)
    assert all(len(connections) == 1 for connections in by_thread.values())
    # В разных потоках соединения РАЗНЫЕ — это и есть требование урока.
    assert len({next(iter(c)) for c in by_thread.values()}) == len(by_thread)
    # Ни одно из них не совпадает с соединением главного потока.
    assert id(main_conn) not in {next(iter(c)) for c in by_thread.values()}


def test_connection_from_another_thread_does_not_raise():
    """Соединение, полученное в потоке, используется в нём же — без
    ProgrammingError (регрессия «SQLite objects created in a thread»)."""
    errors: list[BaseException] = []

    def worker(_: int) -> None:
        try:
            conn = get_conn()
            conn.execute("SELECT 1").fetchone()
            conn.execute("SELECT COUNT(*) FROM projects").fetchone()
        except BaseException as exc:            # noqa: BLE001 — фиксируем любую
            errors.append(exc)

    with cf.ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(worker, range(100)))

    assert not errors, errors[:3]


def test_check_same_thread_is_disabled_in_connection():
    """Причина, по которой соединение можно передавать между обработчиками:
    sqlite3.connect(check_same_thread=False). Регрессия, если это изменится."""
    import sqlite3

    connection = get_conn()
    assert isinstance(connection, sqlite3.Connection)
    # Фактическая проверка: вызов из чужого потока не бросает ProgrammingError.
    outcome: list[BaseException] = []

    def worker() -> None:
        try:
            connection.execute("SELECT 1").fetchone()
        except BaseException as exc:            # noqa: BLE001
            outcome.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=10)
    assert not outcome, outcome


def test_wal_and_busy_timeout_are_enabled():
    """WAL и busy_timeout включены: параллельные читатели не мешают писателю."""
    assert scalar("PRAGMA journal_mode") == "wal"
    assert int(scalar("PRAGMA busy_timeout")) > 0
    assert int(scalar("PRAGMA foreign_keys")) == 1


# ===========================================================================
#  Параллельные запросы через TestClient (вторая половина урока, ПС-20)
# ===========================================================================

def test_fifty_parallel_authorized_requests_all_succeed(api, make_project, users):
    """ПС-20 / NFR-01: 50 одновременных авторизованных пользователей без
    отказов."""
    for index in range(5):
        make_project(title=f"Проект для нагрузки номер {index}")
    headers = {"Authorization": f"Bearer {api.login('prorector')}"}

    def request(_: int) -> int:
        return api.client.get("/api/dashboard", headers=headers).status_code

    with cf.ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
        codes = list(pool.map(request, range(PARALLEL_REQUESTS)))

    assert codes.count(200) == PARALLEL_REQUESTS, sorted(set(codes))
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == 5


def test_fifty_parallel_reads_return_identical_result(api, make_project, users):
    """Параллельное чтение портфеля не «рассыпается»: все видят одно и то же."""
    for index in range(4):
        make_project(title=f"Проект для параллельного чтения номер {index}")
    headers = {"Authorization": f"Bearer {api.login('prorector')}"}

    def request(_: int) -> dict:
        response = api.client.get("/api/projects", headers=headers,
                                 params={"limit": 100})
        assert response.status_code == 200, response.text
        return response.json()

    with cf.ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
        bodies = list(pool.map(request, range(PARALLEL_REQUESTS)))

    totals = {body["total"] for body in bodies}
    codes = {tuple(item["code"] for item in body["items"]) for body in bodies}
    assert totals == {4}, totals
    assert len(codes) == 1, "параллельные чтения вернули разные наборы"


def unique_title(index: int) -> str:
    """Заведомо НЕпохожие названия: иначе поиск дублей (FR-08) справедливо
    остановит создание, и тест измерял бы не параллельную запись."""
    import uuid

    return f"Проект «Замысел {index}» {uuid.uuid4().hex[:12]}"


def test_fifty_parallel_writes_lose_nothing(api, program, users):
    """Параллельная запись: все 50 карточек созданы, номера уникальны.

    FR-06 (автонумерация) под нагрузкой — самый вероятный источник
    «дырявого» генератора номеров.
    """
    headers = {"Authorization": f"Bearer {api.login('leader1')}"}

    def create(index: int) -> dict:
        response = api.client.post(
            "/api/projects",
            headers=headers,
            json={"program_id": program["id"],
                  "title": unique_title(index),
                  "short_title": f"Проект {index}",
                  "planned_start": "2026-01-01", "planned_end": "2027-12-31"},
        )
        return {"status": response.status_code, "body": response.json()
                if response.status_code < 500 else {}}

    with cf.ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
        results = list(pool.map(create, range(PARALLEL_REQUESTS)))

    statuses = [r["status"] for r in results]
    assert statuses.count(201) == PARALLEL_REQUESTS, sorted(set(statuses))
    assert all(r["body"].get("created") is True for r in results), \
        "карточка объявлена созданной, но не создана"

    stored = query("SELECT code, title FROM projects")
    assert len(stored) == PARALLEL_REQUESTS, "потеряны данные при параллельной записи"
    numbers = [row["code"] for row in stored]
    assert len(set(numbers)) == PARALLEL_REQUESTS, "номера проектов повторяются"
    assert all(n.startswith("РНП-") for n in numbers)
    assert scalar("SELECT COUNT(DISTINCT code) FROM projects", (), 0) == \
        PARALLEL_REQUESTS
    # Каждая карточка попала в журнал — записи не «потерялись по дороге».
    assert scalar("SELECT COUNT(*) FROM audit_events"
                  " WHERE action = 'Создание карточки'", (), 0) == PARALLEL_REQUESTS


def test_parallel_mixed_reads_and_writes(api, make_project, users, program):
    """Смешанная нагрузка: чтения и записи идут одновременно без отказов."""
    for index in range(3):
        make_project(title=unique_title(index))
    headers = {"Authorization": f"Bearer {api.login('prorector')}"}

    def read(_: int) -> int:
        return api.client.get("/api/projects", headers=headers,
                              params={"limit": 50}).status_code

    def write(index: int) -> int:
        response = api.client.post(
            "/api/projects",
            headers=headers,
            json={"program_id": program["id"],
                  "title": unique_title(1000 + index),
                  "short_title": f"Смешанный {index}",
                  "planned_start": "2026-01-01", "planned_end": "2027-12-31"})
        return response.status_code

    def work(index: int) -> int:
        return read(index) if index % 2 else write(index)

    with cf.ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
        codes = list(pool.map(work, range(40)))

    assert set(codes) <= {200, 201}, sorted(set(codes))
    assert codes.count(200) == 20
    assert codes.count(201) == 20
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == 3 + 20


def test_parallel_requests_do_not_return_500(api, make_project, users):
    """Внутренние ошибки при параллельной работе недопустимы.

    Раньше /api/projects/taxonomy намеренно не обходился: на нём был
    дефект с 500, и его скрыли исключением из списка, а не починили.
    Дефект закрыт 14.10.2026 (backend/tests/test_taxonomy_endpoint.py),
    поэтому адрес вернулся в обход — иначе проверка снова станет слепой
    к этому классу ошибок.
    """
    for index in range(3):
        make_project(title=unique_title(index))
    headers = {"Authorization": f"Bearer {api.login('secretary')}"}
    paths = ["/api/dashboard", "/api/projects", "/api/reminders",
             "/api/reports/overdue", "/api/audit", "/api/projects/taxonomy"]

    def request(index: int) -> int:
        return api.client.get(paths[index % len(paths)], headers=headers).status_code

    with cf.ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
        codes = list(pool.map(request, range(50)))

    assert 500 not in codes, sorted(set(codes))
    assert codes.count(200) == PARALLEL_REQUESTS, sorted(set(codes))


def test_parallel_updates_conflict_instead_of_silent_overwrite(api, project, users):
    """FR-32: параллельные правки одной карточки не затирают друг друга молча.

    Все запросы несут одну и ту же версию 1: выигрывает один, остальные
    получают 409 и обязаны перечитать карточку. Проверяем, что каждая
    успешная правка увеличивала версию ровно на единицу и итоговая версия
    совпадает с числом успешных правок.
    """
    from app.db import query_one

    headers = {"Authorization": f"Bearer {api.login('leader1')}"}

    def attempt(index: int) -> int:
        return api.client.patch(f"/api/projects/{project['id']}", headers=headers,
                                json={"version": 1,
                                      "goal": f"Цель из параллельной правки {index}"})

    with cf.ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(attempt, range(20)))

    codes = [r.status_code for r in responses]
    assert set(codes) <= {200, 409}, sorted(set(codes))
    assert codes.count(200) >= 1
    assert codes.count(409) >= 1, "устаревшая версия обязана отклоняться (FR-32)"

    final = query_one("SELECT version, goal FROM projects WHERE id = ?",
                      (project["id"],))
    assert final["version"] == 1 + codes.count(200)
    assert final["goal"].startswith("Цель из параллельной правки")


def test_public_api_survives_parallel_reads(raw_client, make_project, users,
                                            set_public_allowed):
    """Публичный контур тоже выдерживает параллельные обращения."""
    for index in range(5):
        project = make_project(publish_mode="project", status="ST-07",
                               public_annotation="Аннотация",
                               title=f"Публичный проект под нагрузкой {index}")
        set_public_allowed(project["id"], users["prorector"].id)

    def request(_: int) -> int:
        return raw_client.get("/api/public/v1/projects").status_code

    with cf.ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
        codes = list(pool.map(request, range(PARALLEL_REQUESTS)))

    assert codes.count(200) == PARALLEL_REQUESTS, sorted(set(codes))


def test_parallel_work_finishes_within_reasonable_time(api, make_project, users):
    """NFR-02: параллельная работа не должна висеть из-за блокировок SQLite."""
    for index in range(3):
        make_project(title=f"Проект для замера номер {index}")
    headers = {"Authorization": f"Bearer {api.login('prorector')}"}

    def request(_: int) -> None:
        api.client.get("/api/projects", headers=headers, params={"limit": 50})

    started = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
        list(pool.map(request, range(PARALLEL_REQUESTS)))
    elapsed = time.perf_counter() - started

    assert elapsed < 30.0, f"{PARALLEL_REQUESTS} запросов заняли {elapsed:.1f} с"
    assert elapsed / PARALLEL_REQUESTS < 3.0