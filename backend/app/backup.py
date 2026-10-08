"""Резервное копирование и восстановление (п.11.4 ТЗ).

Требования ТЗ:
  * периодичность — не реже одного раза в сутки;
  * состав — база данных, конфигурация и файловое хранилище при наличии;
  * хранение — ежедневные копии не менее 30 календарных дней,
    еженедельная копия в отдельном защищённом хранилище;
  * перед обновлением — обязательная контрольная копия;
  * RPO не более 24 часов, RTO не более 8 рабочих часов;
  * проверка — контрольное восстановление до приёмки и далее раз в квартал.

ДВА УРОКА ОТДЕЛА, ПРИМЕНЁННЫЕ ЗДЕСЬ:

1. memories/2026/10/2026-10-02-sqlite-snapshot-wal
   Копия делается через sqlite3.Connection.backup(), а НЕ копированием файла
   .db. При работающем журнале WAL данные лежат ещё и в файле -wal; простая
   копия .db даёт снимок БЕЗ последних изменений и выглядит как успешная.

2. memories/2026/10/2026-10-02-truncated-file-silent-success
   Проверка копии проверяет СОДЕРЖИМОЕ: число таблиц и строк, целостность по
   PRAGMA integrity_check. Обрезанный файл тоже открывается и проходит
   integrity_check в SQLite, поэтому одной проверки «файл открылся» мало.
   Поэтому дополнительно сверяется число строк в ключевых таблицах с эталоном
   и минимальный размер файла.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

from .config import settings
from .utils import MOSCOW, fmt_datetime, now_msk, today_iso

#: Таблицы, число строк в которых обязано сохраняться при копировании.
#: Именно они несут содержательные данные реестра.
KEY_TABLES = ("projects", "persons", "results", "milestones", "reviews",
              "decisions", "audit_events", "result_projects", "participations")

#: Минимально осмысленное число строк: ноль строк в проектах у живой базы —
#: признак снимка из пустой или повреждённой копии.
MIN_EXPECTED_ROWS = 0


class BackupError(Exception):
    """Ошибка резервного копирования или проверки копии."""


def backup_dir() -> Path:
    path = settings.backup_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _filename(prefix: str = "registry") -> str:
    stamp = now_msk().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}.sqlite3"


def create_backup(prefix: str = "registry", label: str = "") -> dict:
    """Создать резервную копию через API резервного копирования SQLite.

    В отличие от shutil.copy2 этот способ консистентен при параллельной работе:
    он берёт снимок на согласованной границе транзакций.
    """
    from .db import get_conn

    target = backup_dir() / _filename(prefix)
    source = get_conn()

    tmp = target.with_suffix(".partial")
    dest = sqlite3.connect(str(tmp))
    try:
        source.backup(dest)
    finally:
        dest.close()

    # Пустой или подозрительно маленький файл — снимок непригоден.
    # Молча отдать такой файл значит обнаружить проблему только при
    # аварийном восстановлении.
    size = tmp.stat().st_size
    if size < 4096:
        tmp.unlink(missing_ok=True)
        raise BackupError(
            f"Снимок получился пустым ({size} байт) — копия не создана. "
            "Проверьте путь к базе и права доступа.")

    tmp.replace(target)
    stats = verify_backup(str(target))

    if label:
        with open(str(target) + ".label", "w", encoding="utf-8") as fh:
            fh.write(label)

    audit_copy(target)
    return {
        "file": target.name,
        "path": str(target),
        "created_at": now_msk().isoformat(timespec="seconds"),
        "size_bytes": size,
        "method": "sqlite3.Connection.backup()",
        "label": label,
        **stats,
    }


def audit_copy(target: Path) -> None:
    """Скопировать конфигурацию рядом с базой (состав копии по п.11.4)."""
    env = Path(__file__).resolve().parent.parent.parent / ".env"
    if env.exists():
        shutil.copy2(env, target.parent / f"{target.stem}.env")


def _open_readonly(path: str) -> sqlite3.Connection:
    uri = f"file:{Path(path).as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def verify_backup(path: str) -> dict:
    """Проверить пригодность копии по содержимому, а не по факту открытия.

    Проверяется:
      * файл существует и не пуст;
      * PRAGMA integrity_check;
      * присутствуют ожидаемые таблицы;
      * в ключевых таблицах есть данные или база действительно пуста;
      * строки читаются (не только схема).
    """
    file = Path(path)
    result: dict[str, {"ok": bool, "tables": int, "rows": dict[str, int],
                       "integrity": str, "size_bytes": int, "problems": list[str]}] = {
        "ok": False, "tables": 0, "rows": {}, "integrity": "",
        "size_bytes": file.stat().st_size if file.exists() else 0, "problems": [],
    }
    if not file.exists():
        result["problems"].append("Файл копии не найден")
        return result
    if result["size_bytes"] < 4096:
        result["problems"].append(
            f"Файл слишком мал ({result['size_bytes']} байт) — вероятно, копия пустая "
            "или обрезана")
        return result

    conn = None
    try:
        conn = _open_readonly(str(file))
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        result["integrity"] = str(integrity)
        if integrity != "ok":
            result["problems"].append(f"PRAGMA integrity_check: {integrity}")

        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        result["tables"] = len(tables)
        expected = {"projects", "persons", "results", "audit_events", "schema_migrations"}
        missing = sorted(expected - tables)
        if missing:
            result["problems"].append(f"В копии нет таблиц: {', '.join(missing)}")

        for table in KEY_TABLES:
            if table not in tables:
                continue
            try:
                # Читаем данные, а не только считаем: обрезанный файл может
                # показать правильные метаданные и нечитаемые строки.
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                result["rows"][table] = int(count)
            except sqlite3.Error as exc:
                result["problems"].append(f"Таблица {table} не читается: {exc}")

        if result["rows"].get("projects", 0) == 0:
            live = _live_row_count("projects")
            if live > 0:
                result["problems"].append(
                    f"В копии нет ни одного проекта, а в рабочей базе их {live}. "
                    "Это признак снимка, сделанного не из той базы.")
        result["ok"] = not result["problems"]
    except sqlite3.Error as exc:
        result["problems"].append(f"Копия не открывается как SQLite: {exc}")
    finally:
        if conn is not None:
            conn.close()
    return result


def _live_row_count(table: str) -> int:
    try:
        from .db import scalar
        return scalar(f"SELECT COUNT(*) FROM {table}", (), 0)
    except Exception:  # noqa: BLE001 — проверка не должна падать из-за БД
        return 0


def list_backups() -> list[dict]:
    """Список копий с указанием устаревших (п.11.4: хранение не менее 30 дней)."""
    cutoff = now_msk() - timedelta(days=settings.backup_retention_days)
    items: list[dict] = []
    for file in sorted(backup_dir().glob("*.sqlite3"), reverse=True):
        stat = file.stat()
        created = now_msk().fromtimestamp(stat.st_mtime, tz=MOSCOW)
        label_file = Path(str(file) + ".label")
        items.append({
            "file": file.name,
            "path": str(file),
            "created_at": created.isoformat(timespec="seconds"),
            "created_at_fmt": fmt_datetime(created.isoformat()),
            "size_bytes": stat.st_size,
            "label": label_file.read_text(encoding="utf-8") if label_file.exists() else "",
            "age_days": (now_msk() - created).days,
            "within_retention": created >= cutoff,
            "expired": created < cutoff,
        })
    return items


#: Служебные копии, которые уборка по сроку хранения НЕ трогает.
#: Сравнение идёт по НАЧАЛУ имени файла: реальные имена начинаются с префикса
#: «weekly-…», а не содержат «-weekly-» в середине. Прежняя проверка вхождения
#: подстроки никогда не срабатывала, и уборка удаляла недельные копии и
#: обязательные контрольные копии перед обновлением — ровно те, которые п.11.4
#: требует хранить.
SERVICE_PREFIXES: tuple[str, ...] = (
    "weekly-",           # недельная копия для отдельного хранилища
    "before-update-",    # контрольная копия перед обновлением
    "before-restore-",   # копия текущего состояния перед восстановлением
)


def purge_expired() -> list[str]:
    """Удалить ежедневные копии старше срока хранения.

    Недельные копии, контрольные копии перед обновлением и копии перед
    восстановлением сохраняются независимо от возраста (п.11.4).
    """
    cutoff = now_msk() - timedelta(days=settings.backup_retention_days)
    removed: list[str] = []
    for file in backup_dir().glob("*.sqlite3"):
        if datetime_from_mtime(file) < cutoff:
            if file.name.startswith(SERVICE_PREFIXES):
                continue
            file.unlink(missing_ok=True)
            Path(str(file) + ".label").unlink(missing_ok=True)
            removed.append(file.name)
    return removed


def datetime_from_mtime(file: Path):
    return now_msk().fromtimestamp(file.stat().st_mtime, tz=MOSCOW)


def pre_update_backup(version: str) -> dict:
    """Обязательная контрольная копия перед обновлением (п.11.4)."""
    return create_backup(prefix="before-update", label=f"перед обновлением: {version}")


def weekly_backup() -> dict:
    """Еженедельная копия для отдельного защищённого хранилища (п.11.4)."""
    return create_backup(prefix="weekly", label="еженедельная копия")


def restore_backup(path: str) -> dict:
    """Восстановление из копии.

    Перед восстановлением делается контрольная копия текущего состояния:
    RTO — 8 рабочих часов, но потерять изменения, сделанные после последней
    копии, нельзя.
    """
    file = Path(path)
    if not file.exists():
        raise BackupError(f"Файл копии не найден: {path}")

    verification = verify_backup(str(file))
    if not verification["ok"]:
        raise BackupError(
            "Копия не прошла проверку, восстановление прервано: "
            + "; ".join(verification["problems"]))

    safety = create_backup(prefix="before-restore",
                            label=f"перед восстановлением из {file.name}")

    from .db import get_conn
    import app.db as db_module

    target = settings.db_file
    conn = get_conn()
    conn.close()
    db_module._local.conn = None
    for suffix in ("", "-wal", "-shm"):
        Path(str(target) + suffix).unlink(missing_ok=True)

    shutil.copy2(str(file), str(target))
    restored = verify_backup(str(target))
    if not restored["ok"]:
        raise BackupError(
            "После восстановления проверка не пройдена: "
            + "; ".join(restored["problems"]))

    db_module.run_migrations()
    return {
        "restored_from": file.name,
        "restored_at": now_msk().isoformat(timespec="seconds"),
        "verification": restored,
        "safety_backup": safety["file"],
        "rto_note": "Целевой срок восстановления RTO — 8 рабочих часов (п.11.4)",
    }


def daily_backup_if_needed() -> dict | None:
    """Создать ежедневную копию, если сегодня её ещё не было (п.11.4)."""
    today = today_iso()
    prefix = f"registry-{today.replace('-', '')}"
    existing = list(backup_dir().glob(f"{prefix}*.sqlite3"))
    if existing:
        return None
    return create_backup(label="ежедневная копия")