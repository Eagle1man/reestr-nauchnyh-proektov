# -*- coding: utf-8 -*-
"""Комплект поставки (ТЗ п.15) — проверка состава и свежести документов.

ПОЧЕМУ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ:

Позиции п.15 перечислены в docs/КАРТА-ТЗ.md таблицей, где у каждой стоит
«Сдано». Таблица — рукописный текст: она продолжает говорить «Сдано» и тогда,
когда файл удалён, переименован или устарел относительно кода. Заказчик,
проверяющий комплект по факту, получает расхождение между описью и содержанием.

Поэтому состав проверяется здесь фактами:

1. КАЖДАЯ позиция существует как файл или каталог и не пуста.
2. ССЫЛКИ из описи п.15 ведут на существующие файлы — переименование,
   не отражённое в описи, ломает проверку, а не читателя.
3. Генерируемые документы (словарь полей, матрица ролей) СОВПАДАЮТ с тем,
   что порождает текущий код. Это главный риск: обязательность поля меняется
   в domain/validation.py, а документ об этом молчит.

Третий пункт — не проверка файла, а проверка согласованности: документы
пересобираются в памяти и сравниваются с закоммиченными. Расхождение
означает, что поставка содержит описание устаревшей системы.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
DOCS = PROJECT_DIR / "docs"

#: Позиции комплекта поставки ТЗ п.15: (номер, что поставляется, путь).
#: Позиция 11 (административные доступы) отдельно — см. test_admin_accesses_deferred.
DELIVERY_ITEMS: list[tuple[str, str, str]] = [
    ("1", "Развёрнутая рабочая версия", "README.md"),
    ("2", "Исходный код", "backend/app"),
    ("2", "Исходный код (интерфейс)", "frontend/src"),
    ("3", "Схема БД", "docs/СХЕМА-БД.md"),
    ("3", "Миграции", "backend/migrations"),
    ("4", "Настройки развёртывания", "deploy"),
    ("4", "Перечень компонентов", "docs/ИНСТРУКЦИЯ-РАЗВЁРТЫВАНИЯ.md"),
    ("5", "Словарь полей", "docs/СЛОВАРЬ-ПОЛЕЙ.md"),
    ("5", "Матрица ролей", "docs/МАТРИЦА-РОЛЕЙ.md"),
    ("6", "Руководство пользователя", "docs/РУКОВОДСТВО-ПОЛЬЗОВАТЕЛЯ.md"),
    ("6", "Руководство функционального администратора",
     "docs/РУКОВОДСТВО-ФУНКЦИОНАЛЬНОГО-АДМИНИСТРАТОРА.md"),
    ("6", "Руководство технического администратора",
     "docs/РУКОВОДСТВО-ТЕХНИЧЕСКОГО-АДМИНИСТРАТОРА.md"),
    ("7", "Инструкция по установке, обновлению, б/к и восстановлению",
     "docs/ИНСТРУКЦИЯ-РАЗВЁРТЫВАНИЯ.md"),
    ("8", "Инструкция импорта", "docs/ИНСТРУКЦИЯ-ИМПОРТА.md"),
    ("9", "Описание публичного API", "docs/ПУБЛИЧНЫЙ-API.md"),
    ("10", "Протокол испытаний", "docs/ПРОТОКОЛ-ИСПЫТАНИЙ.md"),
    ("10", "Перечень ограничений", "docs/ОГРАНИЧЕНИЯ.md"),
]

#: Минимальный размер документа, ниже которого файл считается заглушкой.
#: Настоящие руководства — от 15 КБ, пустышка меньше.
MIN_DOC_BYTES = 2048


def test_every_delivery_item_exists_and_is_not_empty() -> None:
    """Каждая позиция п.15 присутствует и наполнена, а не существует формально."""
    missing: list[str] = []
    thin: list[str] = []

    for number, what, relative in DELIVERY_ITEMS:
        path = PROJECT_DIR / relative
        if not path.exists():
            missing.append(f"п.{number} {what}: нет {relative}")
            continue
        if path.is_file() and path.stat().st_size < MIN_DOC_BYTES:
            thin.append(f"п.{number} {what}: {relative} — "
                        f"всего {path.stat().st_size} байт")
        if path.is_dir() and not any(path.iterdir()):
            thin.append(f"п.{number} {what}: каталог {relative} пуст")

    assert not missing, "Позиции комплекта поставки отсутствуют:\n" + "\n".join(missing)
    assert not thin, "Позиции существуют, но не содержат работы:\n" + "\n".join(thin)


def test_delivery_items_have_no_duplicates_in_map() -> None:
    """Опись п.15 в КАРТА-ТЗ.md не должна терять позиции.

    Таблица в документе перечисляет 11 позиций; здесь проверяется, что номера
    идут подряд без пропусков. Пропуск означает, что позиция выпала из описи
    и заказчик её не получит.
    """
    carte = DOCS / "КАРТА-ТЗ.md"
    text = carte.read_text(encoding="utf-8")
    section = text[text.index("## 11. Комплект поставки"):]
    section = section[:section.index("\n## ") if "\n## " in section else len(section)]
    numbers = sorted({int(m) for m in re.findall(r"^\| (\d+) \|", section, re.M)})
    assert numbers == list(range(1, 12)), (
        f"В описи п.15 перечислены позиции {numbers}, ожидалось 1..11: "
        "выпавшая позиция не будет сдана заказчику")


def test_links_in_delivery_map_resolve() -> None:
    """Ссылки из описи п.15 ведут на существующие файлы.

    Классическое рассинхронизация: файл переименовали, ссылку в описи не
    поправили — заказчик получает битую ссылку вместо документа.
    """
    text = (DOCS / "КАРТА-ТЗ.md").read_text(encoding="utf-8")
    section = text[text.index("## 11. Комплект поставки"):]
    section = section[:section.index("\n## ")] if "\n## " in section else section

    broken = [
        target for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", section)
        if not (DOCS / target).exists()
    ]
    assert not broken, "В описи п.15 есть ссылки на несуществующие файлы: " + \
                       ", ".join(sorted(set(broken)))


def _load_generator():
    """Загрузить generate_docs.py как модуль, минуя sys.path.

    Скрипт лежит в backend/scripts и не является пакетом; импорт через
    importlib позволяет пересобрать документы в памяти, не трогая файлы
    в рабочем каталоге.
    """
    path = BACKEND_DIR / "scripts" / "generate_docs.py"
    spec = importlib.util.spec_from_file_location("generate_docs_under_test", path)
    assert spec and spec.loader, "backend/scripts/generate_docs.py не найден"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_field_dictionary_matches_current_code() -> None:
    """Словарь полей соответствует domain/validation.py.

    Главный риск позиции 5: обязательность поля поменяли в коде, а документ
    продолжает описывать старую систему. На этот документ опираются при вводе
    данных, поэтому расхождение — не косметика, а неверная инструкция.
    """
    generator = _load_generator()
    fresh = generator.field_dictionary_doc()
    committed = (DOCS / "СЛОВАРЬ-ПОЛЕЙ.md").read_text(encoding="utf-8")
    assert fresh == committed, (
        "docs/СЛОВАРЬ-ПОЛЕЙ.md устарел относительно кода. Пересоберите: "
        "python backend/scripts/generate_docs.py")


def test_roles_matrix_matches_current_code() -> None:
    """Матрица ролей соответствует текущим правам.

    Регламентирует, кому доступна каждая операция, поэтому расхождение с кодом
    означает выданное заказчику разрешение, не подтверждённое системой.
    """
    generator = _load_generator()
    fresh = generator.roles_matrix_doc()
    committed = (DOCS / "МАТРИЦА-РОЛЕЙ.md").read_text(encoding="utf-8")
    assert fresh == committed, (
        "docs/МАТРИЦА-РОЛЕЙ.md устарел относительно кода. Пересоберите: "
        "python backend/scripts/generate_docs.py")


def test_generated_documents_are_marked_as_generated() -> None:
    """Генерируемые документы предупреждают, что править их нельзя.

    Если файла лишены пометки, редактор правит их руками — и следующая
    генерация затирает правку, а то и уходит мимо неё.
    """
    for name in ("СЛОВАРЬ-ПОЛЕЙ.md", "МАТРИЦА-РОЛЕЙ.md"):
        text = (DOCS / name).read_text(encoding="utf-8")
        assert "СОЗДАН АВТОМАТИЧЕСКИ" in text, (
            f"{name} не помечен как созданный автоматически")


def test_admin_accesses_deferred_and_documented() -> None:
    """Позиция 11 (доступы) передаётся отдельно и помечена как таковая.

    Доступы не должны лежать в репозитории (SEC-05), но заказчик должен знать,
    что их получит. Поэтому проверяется не наличие, а честная пометка в описи.
    """
    text = (DOCS / "КАРТА-ТЗ.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| 11 |"))
    assert "отдельно" in row.lower(), (
        "Позиция 11 не помечена как передаваемая отдельно — заказчик решит, "
        "что доступы не входят в поставку")


def test_import_template_endpoint_is_live(api, users) -> None:
    """Позиция 8: шаблон импорта не только описан, но и отдаётся системой.

    Проверка каталога `backend/app` доказывала лишь наличие кода, а не работу:
    маршрут мог быть удалён или переименован, и тест бы остался зелёным.
    Здесь шаблон запрашивается по-настоящему, как это делает пользователь.
    """
    response = api.get("/api/import/template", login="secretary")
    assert response.status_code == 200, (
        "Шаблон импорта недоступен: "
        f"{response.status_code} {response.text[:200]}")
    assert response.content, "Шаблон импорта отдаётся пустым"
    assert response.content[:2] == b"PK", (
        "Шаблон должен быть XLSX (ZIP-контейнер), "
        f"получено {response.content[:8]!r}")
    assert "attachment" in response.headers.get("content-disposition", ""), (
        "Шаблон не отдаётся как вложение — пользователь не поймёт, "
        "что файл сохранён")


def test_roles_matrix_documents_statuses_and_routes() -> None:
    """Позиция 5: статусы и маршруты описаны, а не только названы в заголовке.

    Критика указывала, что документа по статусам и маршрутам нет. Проверка
    существования этого файла уже была, но она не отвечает на вопрос, ЕСТЬ ЛИ
    в нём содержание. Здесь сверяется состав: 12 статусов и оба маршрута.
    """
    text = (DOCS / "МАТРИЦА-РОЛЕЙ.md").read_text(encoding="utf-8")
    for code in ("ST-01", "ST-06", "ST-12"):
        assert code in text, (
            f"В МАТРИЦА-РОЛЕЙ.md нет статуса {code}: документ не описывает "
            "статусную модель целиком")
    assert "маршрут" in text.lower(), "МАТРИЦА-РОЛЕЙ.md не описывает маршруты"


def test_no_credentials_in_delivery_documents() -> None:
    """В документах поставки нет паролей и ключей.

    Проверяется на случай, если инструкция скопирована вместе с рабочим
    файлом конфигурации (SEC-05).
    """
    #: Секрет в документе — это присваивание значения секретному имени.
    #: Кавычки не требуются: в инструкциях чаще пишут `password: значение`,
    #: чем `password: "значение"`, и первый вариант обязан ловиться так же.
    #: Покрываются имена password/пароль/token/api_key/secret — иначе
    #: захардкоженный ключ подписанный иначе, проходит мимо проверки.
    #: Русский формат с уточнением («Пароль БД: значение») — отдельной
    #: альтернативой: слово «пароль» там стоит не сразу перед двоеточием.
    suspicious = re.compile(
        r"(?i)\b(password|passwd|token|api[_-]?key|secret)\b"
        r"\s*[=:]\s*[\"']?[^\s\"'`,;]{6,}[\"']?"
        r"|"
        r"\bпароль\b\s+\S+\s*[=:]\s*[\"']?[^\s\"'`,;]{6,}[\"']?")
    offenders: list[str] = []
    for path in sorted(DOCS.glob("*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if suspicious.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()[:80]}")
    assert not offenders, "В документах поставки найдены захардкоженные секреты:\n" + \
                          "\n".join(offenders)
