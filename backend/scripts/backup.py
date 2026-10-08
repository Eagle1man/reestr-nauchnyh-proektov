#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Расписание резервного копирования (п.11.4 ТЗ).

Запуск без аргументов делает то, что положено по расписанию:

    python backend/scripts/backup.py            # ежедневная копия, если сегодня ещё нет
    python backend/scripts/backup.py --weekly   # еженедельная копия для отдельного хранилища
    python backend/scripts/backup.py --verify <путь>
    python backend/scripts/backup.py --restore <путь> --confirm
    python backend/scripts/backup.py --list
    python backend/scripts/backup.py --purge     # удалить копии старше срока хранения

Требования ТЗ п.11.4, которые здесь обеспечиваются:
  * периодичность — не реже одного раза в сутки;
  * ежедневные копии хранятся не менее 30 календарных дней;
  * еженедельная копия — в отдельном защищённом хранилище;
  * RPO не более 24 часов (ежедневный запуск);
  * контрольное восстановление — до приёмки и далее раз в квартал.

Планировщик настраивается через systemd (см. deploy/systemd/) или cron.
В cron ежедневный вызов выглядит так:
    17 3 * * *  cd /opt/registry && .venv/bin/python backend/scripts/backup.py
    42 3 * * 0  cd /opt/registry && .venv/bin/python backend/scripts/backup.py --weekly
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import os  # noqa: E402

os.environ.setdefault("DEBUG", "true")

from app import db  # noqa: E402
from app.backup import (  # noqa: E402
    BackupError, create_backup, daily_backup_if_needed, list_backups,
    purge_expired, restore_backup, verify_backup, weekly_backup,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Резервное копирование реестра")
    parser.add_argument("--weekly", action="store_true",
                        help="еженедельная копия для отдельного хранилища")
    parser.add_argument("--verify", metavar="ПУТЬ", help="проверить копию без применения")
    parser.add_argument("--restore", metavar="ПУТЬ", help="восстановить из копии")
    parser.add_argument("--confirm", action="store_true",
                        help="подтвердить восстановление")
    parser.add_argument("--list", action="store_true", help="показать список копий")
    parser.add_argument("--purge", action="store_true", help="удалить устаревшие копии")
    parser.add_argument("--before-update", metavar="ВЕРСИЯ",
                        help="контрольная копия перед обновлением")
    args = parser.parse_args()

    if args.list:
        items = list_backups()
        if not items:
            print("Копий нет.")
            return 0
        for item in items:
            state = "в сроке" if item["within_retention"] else "СРОК ИСТЁК"
            print(f"{item['created_at']}  {item['size_bytes'] / 1024:9.1f} КБ  "
                  f"{state:12s} {item['file']}"
                  + (f"  [{item['label']}]" if item["label"] else ""))
        return 0

    if args.verify:
        result = verify_backup(args.verify)
        print(f"Проверка копии {args.verify}:")
        for key, value in result.items():
            print(f"  {key}: {value}")
        return 0 if result["ok"] else 1

    if args.restore:
        if not args.confirm:
            result = verify_backup(args.restore)
            print("Восстановление не выполнено: не хватает --confirm.")
            print("Проверка копии:", result)
            return 1
        result = restore_backup(args.restore)
        print("Восстановление выполнено:", result["restored_from"])
        print("  Контрольная копия до восстановления:", result["safety_backup"])
        print("  Проверка после восстановления:", result["verification"]["ok"])
        return 0

    if args.before_update:
        result = create_backup(prefix="before-update",
                               label=f"перед обновлением: {args.before_update}")
        print(f"Контрольная копия перед обновлением: {result['file']} "
              f"({result['size_bytes'] / 1024:.1f} КБ)")
        return 0

    if args.purge:
        removed = purge_expired()
        print(f"Удалено устаревших копий: {len(removed)}")
        for name in removed:
            print(f"  {name}")
        return 0

    db.run_migrations()

    if args.weekly:
        result = weekly_backup()
        print(f"Еженедельная копия: {result['file']} "
              f"({result['size_bytes'] / 1024:.1f} КБ), целостность {result['integrity']}")
        return 0

    result = daily_backup_if_needed()
    if result is None:
        print("Ежедневная копия за сегодня уже создана — пропуск.")
        return 0
    print(f"Ежедневная копия: {result['file']} "
          f"({result['size_bytes'] / 1024:.1f} КБ), целостность {result['integrity']}")
    try:
        verification = verify_backup(result["path"])
        if not verification["ok"]:
            print("ПРЕДУПРЕЖДЕНИЕ: копия не прошла проверку:", verification["problems"])
            return 1
    except BackupError as exc:
        print("ПРЕДУПРЕЖДЕНИЕ:", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())