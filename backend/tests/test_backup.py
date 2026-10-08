# -*- coding: utf-8 -*-
"""Резервное копирование и восстановление — п.11.4 ТЗ.

ДВА УРОКА ОТДЕЛА, КОТОРЫЕ ЗДЕСЬ ЗАКРЕПЛЯЮТСЯ ТЕСТАМИ:

1. memories/2026/10/2026-10-02-sqlite-snapshot-wal
   При работающем журнале WAL часть последних изменений лежит в файле -wal,
   а НЕ в основном файле .db. Копирование файла .db даёт снимок БЕЗ последних
   изменений, который при этом выглядит как успешный. Поэтому копия делается
   через sqlite3.Connection.backup(), и тест проверяет, что в копии есть
   данные, записанные ПОСЛЕ последней фиксации.

2. memories/2026/10/2026-10-02-truncated-file-silent-success
   Обрезанный файл SQLite открывается и проходит integrity_check. Поэтому
   одной проверки «файл открылся» мало: проверяется содержимое — число таблиц,
   число строк в ключевых таблицах и минимальный размер файла.

Тесты работают на изолированной базе (см. conftest.py) и вызывают функции
модуля напрямую: восстановление удаляет файлы базы, а рабочие потоки
TestClient держат их открытыми — на Windows это невозможно.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path

import pytest

from app.backup import (
    KEY_TABLES, BackupError, MIN_EXPECTED_ROWS, backup_dir, create_backup,
    list_backups, pre_update_backup, purge_expired, restore_backup,
    verify_backup, weekly_backup,
)
from app.db import execute, get_conn, query, query_one, scalar
from app.utils import new_id, now_iso


# ---------------------------------------------------------------------------
#  Подготовка данных
# ---------------------------------------------------------------------------

def seed_projects(count: int = 5) -> list[str]:
    """Создать проекты напрямую в БД и вернуть их номера."""
    program = query_one("SELECT id FROM programs ORDER BY code LIMIT 1")
    creator = scalar("SELECT id FROM users ORDER BY login LIMIT 1")
    assert program is not None, "нужна хотя бы одна научная программа"
    assert creator is not None, "нужен хотя бы один пользователь"
    from app.services.projects import next_project_code

    codes = []
    for index in range(count):
        code = next_project_code()
        execute(
            "INSERT INTO projects (id, code, program_id, title, status, route,"
            " route_auto, risk_level, publish_mode, created_at, created_by,"
            " updated_at, version) VALUES (?, ?, ?, ?, 'ST-07', 'simplified',"
            " 'simplified', 'green', 'none', ?, ?, ?, 1)",
            (new_id(), code, program["id"],
             f"Проект для резервной копии номер {index}", now_iso(), creator,
             now_iso()),
        )
        codes.append(code)
    return codes


def db_size() -> int:
    return os.path.getsize(str(query_one("PRAGMA database_list")[0]["file"]))


# ===========================================================================
#  Создание копии
# ===========================================================================

def test_create_backup_produces_non_empty_file_with_data(program):
    """П.11.4: копия содержит базу данных. Файл не пуст, integrity_check в
    порядке, ожидаемые таблицы на месте."""
    result = create_backup(prefix="test")

    assert Path(result["path"]).exists()
    assert result["size_bytes"] >= 4096
    assert result["method"] == "sqlite3.Connection.backup()"
    assert result["ok"] is True, result["problems"]
    assert result["integrity"] == "ok"
    assert result["tables"] >= 20          # 24 таблицы по миграции 001
    assert result["problems"] == []


def test_create_backup_reflects_data_written_after_previous_commit(program, tmp_path):
    """РЕГРЕССИЯ (урок sqlite-snapshot-wal): копия содержит данные, записанные
    ПОСЛЕ последней фиксации транзакции.

    Именно этот случай ломает копирование файла .db при работающем WAL:
    файл .db выглядит валидным, но свежие строки в нём отсутствуют.
    """
    seed_projects(3)
    # Принудительно фиксируем всё, что есть, — «до снимка».
    get_conn().commit()
    before = scalar("SELECT COUNT(*) FROM projects", (), 0)
    assert before == 3

    # Пишем ещё данные и НЕ делаем checkpoint: они живут в -wal.
    seed_projects(4)
    after = scalar("SELECT COUNT(*) FROM projects", (), 0)
    assert after == 7

    # Проверяем, что тест действительно на нужном состоянии: журнал WAL
    # существует и данные ещё не слиты в основной файл. Иначе проверка была бы
    # пустой — копирование .db дало бы тот же результат.
    from app.config import settings
    main_db = Path(settings.database_path)
    wal = Path(str(main_db) + "-wal")
    assert wal.exists() and wal.stat().st_size > 0, \
        "WAL-файл пуст — тест не проверяет заявленный риск"
    naive = tmp_path / "naivnaya-kopiya.db"
    shutil.copy2(main_db, naive)          # ровно то, чего делать нельзя
    naive_connection = sqlite3.connect(str(naive))
    try:
        tables = {r[0] for r in naive_connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        naive_count = naive_connection.execute(
            "SELECT COUNT(*) FROM projects").fetchone()[0] \
            if "projects" in tables else 0
    finally:
        naive_connection.close()
    assert naive_count < after, (
        "наивная копия файла .db не потеряла данные — тест не защищает от "
        "регрессии с потерей снимка")

    result = create_backup(prefix="wal")
    assert result["ok"] is True
    assert result["rows"]["projects"] == after, (
        "копия не содержит данных, записанных после последней фиксации: "
        "видимо, это снимок файла .db без журнала WAL")

    # Проверяем непосредственно в файле копии, а не в рабочей базе.
    copy_path = result["path"]
    connection = sqlite3.connect(copy_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM projects").fetchone()[0] == after
        assert connection.execute(
            "PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = {r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"projects", "persons", "results", "audit_events",
                "schema_migrations"} <= tables
    finally:
        connection.close()


def test_backup_reflects_deletes_and_updates(program):
    """Копия отражает не только вставки: удаления и правки тоже видны."""
    codes = seed_projects(3)
    execute("UPDATE projects SET title = 'Переименованный проект' WHERE code = ?",
            (codes[0],))
    execute("DELETE FROM projects WHERE code = ?", (codes[2],))

    result = create_backup(prefix="mutations")
    assert result["rows"]["projects"] == 2
    connection = sqlite3.connect(result["path"])
    try:
        titles = sorted(r[0] for r in connection.execute("SELECT title FROM projects"))
        assert "Переименованный проект" in titles
        assert len(titles) == 2
    finally:
        connection.close()


def test_backup_goes_to_configured_directory(program):
    """Копии складываются в каталог из настроек, а не рядом с исходником."""
    result = create_backup(prefix="katalog")
    assert Path(result["path"]).parent == backup_dir()
    assert result["file"].startswith("katalog-")
    assert result["file"].endswith(".sqlite3")


def test_backup_of_empty_database_is_valid(program):
    """Пустая, но целая база — допустимая копия (проверка не падает зря)."""
    result = create_backup(prefix="pustaya")
    assert result["ok"] is True, result["problems"]
    assert result["rows"]["projects"] == 0
    assert MIN_EXPECTED_ROWS == 0


def test_pre_update_and_weekly_backups_have_labels(program):
    """п.11.4: перед обновлением — обязательная контрольная копия; еженедельная
    идёт в отдельное хранилище."""
    before_update = pre_update_backup("1.0.1")
    assert before_update["ok"] is True
    assert before_update["file"].startswith("before-update-")
    assert "1.0.1" in before_update["label"]

    weekly = weekly_backup()
    assert weekly["ok"] is True
    assert weekly["file"].startswith("weekly-")


def test_label_file_is_written_next_to_backup(program):
    """Метка копии сохраняется рядом с файлом — иначе при аварии не понять,
    что это за снимок."""
    result = create_backup(prefix="metka", label="перед экспериментом")
    label = Path(str(result["path"]) + ".label")
    assert label.exists()
    assert label.read_text(encoding="utf-8") == "перед экспериментом"


# ===========================================================================
#  Проверка копии: пустой, обрезанный, чужой (урок truncated-file)
# ===========================================================================

def test_verify_rejects_missing_file(tmp_path):
    """Отсутствующий файл — непригодная копия."""
    result = verify_backup(str(tmp_path / "нет-такой-копии.sqlite3"))
    assert result["ok"] is False
    assert "не найден" in result["problems"][0]


def test_verify_rejects_empty_file(tmp_path):
    """Пустой файл отвергается: это не копия, а её отсутствие."""
    empty = tmp_path / "empty.sqlite3"
    empty.write_bytes(b"")
    result = verify_backup(str(empty))
    assert result["ok"] is False
    assert any("слишком мал" in problem for problem in result["problems"])


def test_verify_rejects_tiny_file(tmp_path):
    """Подозрительно маленький файл отвергается до попытки открыть его."""
    tiny = tmp_path / "tiny.sqlite3"
    tiny.write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
    result = verify_backup(str(tiny))
    assert result["ok"] is False
    assert result["ok"] is False
    assert any("слишком мал" in problem for problem in result["problems"])


def test_verify_rejects_foreign_non_sqlite_file(tmp_path):
    """Чужой файл (не SQLite) отвергается с внятной причиной."""
    foreign = tmp_path / "чужой.sqlite3"
    # Файл достаточно большой, чтобы проверка дошла до попытки открыть его.
    foreign.write_text("Это не копия базы данных, а обычный текст.\n" * 300,
                       encoding="utf-8")
    assert foreign.stat().st_size > 4096
    result = verify_backup(str(foreign))
    assert result["ok"] is False
    assert any("не открывается как SQLite" in problem for problem in result["problems"])


def test_verify_rejects_foreign_database_with_other_tables(tmp_path):
    """Чужой файл SQLite открывается и проходит integrity_check, но таблиц
    реестра в нём нет — проверка обязана это увидеть (урок «молчаливый успех»)."""
    foreign = tmp_path / "чужая-база.sqlite3"
    connection = sqlite3.connect(str(foreign))
    connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT)")
    connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    for index in range(400):        # достаточно данных, чтобы файл был не мелкий
        connection.execute("INSERT INTO notes (text) VALUES (?)", ("x" * 200,))
    connection.commit()
    connection.close()
    assert foreign.stat().st_size > 4096
    # Для сравнения: целостность у чужого файла в порядке.
    assert sqlite3.connect(f"file:{foreign.as_posix()}?mode=ro", uri=True).execute(
        "PRAGMA integrity_check").fetchone()[0] == "ok"

    result = verify_backup(str(foreign))
    assert result["ok"] is False
    assert any("нет таблиц" in problem for problem in result["problems"])
    assert "projects" in " ".join(result["problems"])


def test_verify_rejects_truncated_copy(program, tmp_path):
    """РЕГРЕССИЯ (урок truncated-file-silent-success): ОБРЕЗАННАЯ копия не
    проходит проверку, хотя обрезанный файл SQLite обычно открывается."""
    seed_projects(8)
    result = create_backup(prefix="polnaya")
    assert result["ok"] is True
    full_size = Path(result["path"]).stat().st_size
    assert full_size > 8192

    truncated = tmp_path / "obrezannaya.sqlite3"
    data = Path(result["path"]).read_bytes()
    truncated.write_bytes(data[: full_size // 2])
    assert truncated.stat().st_size > 4096      # файл ещё «большой»

    check = verify_backup(str(truncated))
    assert check["ok"] is False, (
        "обрезанный файл прошёл проверку — это регрессия: обрезанный файл "
        "SQLite тоже открывается и проходит integrity_check")
    assert check["problems"]

    # И обрезка до последних 8 килобайт — тоже не копия.
    tail = tmp_path / "obrezannaya-konets.sqlite3"
    tail.write_bytes(data[-(8192 + 1024):])
    assert verify_backup(str(tail))["ok"] is False


def test_verify_rejects_copy_without_projects_while_live_has_them(program, tmp_path):
    """Снимок из пустой или чужой базы отвергается, если в рабочей базе есть
    проекты: «нулевой результат при живых данных» — признак не той базы."""
    empty_backup = create_backup(prefix="do-proektov")
    assert empty_backup["rows"]["projects"] == 0

    # Теперь в рабочей базе появляются проекты — прежняя копия становится
    # подозрительной.
    seed_projects(2)
    result = verify_backup(empty_backup["path"])
    assert result["ok"] is False
    assert any("нет ни одного проекта" in problem for problem in result["problems"])


def test_verify_accepts_a_good_backup(program):
    """Проверка хорошей копии возвращает ok и числа строк по ключевым
    таблицам."""
    seed_projects(2)
    result = create_backup(prefix="horoshaa")
    check = verify_backup(result["path"])
    assert check["ok"] is True, check["problems"]
    assert check["rows"]["projects"] == 2
    assert set(KEY_TABLES) <= set(check["rows"])
    assert check["integrity"] == "ok"


def test_verify_does_not_modify_the_file(program):
    """Проверка не изменяет копию (открытие только на чтение)."""
    result = create_backup(prefix="ne_menu")
    path = Path(result["path"])
    before = path.read_bytes()
    stat_before = path.stat().st_mtime_ns
    assert verify_backup(str(path))["ok"] is True
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == stat_before


# ===========================================================================
#  Восстановление
# ===========================================================================

def test_restore_returns_data_to_previous_state(program):
    """п.11.4: восстановление возвращает базу к состоянию на момент копии."""
    seed_projects(3)
    snapshot = create_backup(prefix="do-vosstanovleniya")
    assert snapshot["ok"] is True

    # После копии базу испортили: удалили всё и добавили лишнее.
    program_id = query_one("SELECT id FROM programs LIMIT 1")["id"]
    creator = scalar("SELECT id FROM users ORDER BY login LIMIT 1")
    execute("DELETE FROM projects")
    execute(
        "INSERT INTO projects (id, code, program_id, title, status, route,"
        " route_auto, risk_level, publish_mode, created_at, created_by,"
        " updated_at, version) VALUES (?, 'РНП-2026-9999', ?, 'Лишний проект',"
        " 'ST-07', 'simplified', 'simplified', 'green', 'none', ?, ?, ?, 1)",
        (new_id(), program_id, now_iso(), creator, now_iso()),
    )
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == 1

    restored = restore_backup(snapshot["path"])
    assert restored["restored_from"] == snapshot["file"]
    assert restored["verification"]["ok"] is True
    assert "8 рабочих часов" in restored["rto_note"]

    rows = query("SELECT code FROM projects ORDER BY code")
    assert len(rows) == 3
    assert "РНП-2026-9999" not in [r["code"] for r in rows]


def test_restore_takes_safety_backup_before_replacing(program):
    """Перед восстановлением делается контрольная копия текущего состояния —
    изменения после снимка терять нельзя."""
    seed_projects(2)
    snapshot = create_backup(prefix=" Istochnik")
    execute("DELETE FROM projects")
    seed_projects(5)                     # данные, которые не хотим потерять

    restored = restore_backup(snapshot["path"])
    assert restored["safety_backup"]
    assert Path(backup_dir() / restored["safety_backup"]).exists()

    # Контрольная копия действительно снята ДО восстановления и содержит 5
    # проектов, а не 2.
    safety = verify_backup(str(backup_dir() / restored["safety_backup"]))
    assert safety["ok"] is True
    assert safety["rows"]["projects"] == 5


def test_restore_refuses_unverified_file(program, tmp_path):
    """Восстановление из непроверяемой копии прервано, данные не тронуты."""
    broken = tmp_path / "broken.sqlite3"
    broken.write_bytes(b"\x00" * 100)
    before = scalar("SELECT COUNT(*) FROM schema_migrations", (), 0)

    with pytest.raises(BackupError) as error:
        restore_backup(str(broken))
    assert "проверку" in str(error.value)

    assert scalar("SELECT COUNT(*) FROM schema_migrations", (), 0) == before
    assert scalar("SELECT COUNT(*) FROM schema_migrations", (), 0) >= 1


def test_restore_refuses_truncated_copy(program, tmp_path):
    """Обрезанная копия не применяется — даже если файл большой."""
    seed_projects(8)
    snapshot = create_backup(prefix="ishodnik")
    data = Path(snapshot["path"]).read_bytes()
    truncated = tmp_path / "obrezannaya.sqlite3"
    truncated.write_bytes(data[: len(data) // 2])

    with pytest.raises(BackupError):
        restore_backup(str(truncated))


def test_restore_refuses_missing_file(tmp_path):
    """Отсутствующий файл — понятная ошибка, а не исключение из sqlite3."""
    with pytest.raises(BackupError) as error:
        restore_backup(str(tmp_path / "net-takoy.sqlite3"))
    assert "не найден" in str(error.value)


def test_restore_keeps_schema_current(program):
    """После восстановления миграции актуальны: SCHEMA_VERSION в силе."""
    from app.db import SCHEMA_VERSION, run_migrations

    seed_projects(1)
    snapshot = create_backup(prefix="migracii")
    assert snapshot["ok"] is True
    restore_backup(snapshot["path"])
    assert run_migrations() == []          # ничего не применено повторно
    assert scalar("SELECT COUNT(*) FROM schema_migrations", (), 0) >= 1
    assert SCHEMA_VERSION == 1


# ===========================================================================
#  Список и очистка копий
# ===========================================================================

def test_list_backups_reports_size_age_and_retention(program):
    """п.11.4: копии хранятся не менее 30 дней — список показывает возраст."""
    create_backup(prefix="svezhaya")
    items = list_backups()
    assert items
    fresh = items[0]
    assert fresh["file"].startswith("svezhaya-")
    assert fresh["size_bytes"] > 4096
    assert fresh["age_days"] == 0
    assert fresh["within_retention"] is True
    assert fresh["expired"] is False
    assert fresh["created_at_fmt"]


def test_purge_removes_expired_daily_but_keeps_weekly(program):
    """п.11.4: ежедневные копии не хранятся дольше срока, недельные — хранятся."""
    daily = create_backup(prefix="registry")
    weekly = create_backup(prefix="weekly")
    old = backup_dir() / "registry-20200101-000000.sqlite3"
    old.write_bytes(Path(daily["path"]).read_bytes())
    stale = (time.time() - 60 * 60 * 24 * 45)
    os.utime(old, (stale, stale))

    removed = purge_expired()
    assert old.name in removed
    assert not old.exists()
    assert Path(daily["path"]).exists()
    assert Path(weekly["path"]).exists()


def test_purge_keeps_pre_update_and_weekly_copies(program):
    """п.11.4: недельные копии и контрольные копии перед обновлением уборкой
    не удаляются."""
    kept = []
    for result in (pre_update_backup("1.0.1"), weekly_backup()):
        path = backup_dir() / result["file"]
        stale = (time.time() - 60 * 60 * 24 * 400)
        os.utime(path, (stale, stale))
        kept.append(path)

    purge_expired()
    for path in kept:
        assert path.exists(), path.name


def test_backup_dir_is_created_if_absent(program):
    """Каталог копий создаётся при первом обращении."""
    directory = backup_dir()
    assert directory.exists()
    assert os.access(directory, os.W_OK)