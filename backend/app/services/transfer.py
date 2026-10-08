"""Импорт и выгрузка (FR-28, FR-29; п.7.2 ТЗ).

Правила п.7.2:
  1. форма инвентаризации совпадает с обязательными полями MVP;
  2. поддерживаемый входной формат — XLSX, дополнительно CSV;
  3. ДО загрузки показывается число корректных строк, предупреждений, ошибок
     и возможных дублей;
  4. ДО подтверждения импорт НЕ изменяет рабочие данные;
  5. строки с ошибками не загружаются, пользователь получает ПОСТРОЧНЫЙ
     протокол с названием поля и причиной;
  6. каждая загрузка получает идентификатор пакета, дату, автора и протокол;
  7. выгрузка содержит дату формирования, фильтры и только доступные
     пользователю поля;
  8. технический администратор может выполнить полную архивную выгрузку.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..access import Actor, PORTFOLIO_ROLES
from ..db import execute, query, query_one, scalar, transaction
from ..domain.validation import missing_required_fields
from ..services import projects as svc
from ..utils import csv_safe, fmt_date, new_id, now_iso, today_iso

#: Колонки формы инвентаризации. Порядок = порядок колонок в шаблоне.
#: Названия совпадают с названиями полей Приложения А (п.7.2 п.1).
IMPORT_COLUMNS: tuple[dict[str, Any], ...] = (
    {"key": "title", "header": "Полное название (A-02)", "required": True, "max": 500},
    {"key": "short_title", "header": "Краткое название (A-03)", "required": True, "max": 150},
    {"key": "program_code", "header": "Код программы (A-05)", "required": True, "max": 40},
    {"key": "leader_name", "header": "Руководитель, Ф. И. О. (A-12)", "required": True,
     "max": 300},
    {"key": "leader_email", "header": "Служебный адрес руководителя", "required": False,
     "max": 200},
    {"key": "planned_start", "header": "Плановое начало (A-11)", "required": True},
    {"key": "planned_end", "header": "Плановое завершение (A-11)", "required": True},
    {"key": "problem", "header": "Исследовательская проблема (A-17)", "required": True,
     "max": 2000},
    {"key": "question", "header": "Вопрос или гипотеза (A-18)", "required": True, "max": 1000},
    {"key": "goal", "header": "Цель (A-19)", "required": True, "max": 700},
    {"key": "methods", "header": "Методы (A-23)", "required": True, "max": 1000},
    {"key": "data_basis", "header": "Данные или доказательная база (A-24)", "required": True,
     "max": 2000},
    {"key": "planned_result_type", "header": "Планируемый результат (A-25)", "required": True,
     "max": 60},
    {"key": "result_criteria", "header": "Критерии результата (A-26)", "required": True,
     "max": 1000},
    {"key": "theme_link", "header": "Связь с общей темой (A-06)", "required": True, "max": 500},
    {"key": "publish_mode", "header": "Режим публикации (A-15)", "required": True, "max": 20},
    {"key": "team", "header": "Команда (Ф. И. О.;роль;задача)", "required": True, "max": 1000},
    {"key": "milestones", "header": "Контрольные точки (название;дата;ответственный)",
     "required": True, "max": 2000},
    {"key": "flags", "header": "Признаки полного маршрута (T-01…T-06)", "required": False,
     "max": 100},
    {"key": "public_annotation", "header": "Публичная аннотация (A-04)", "required": False,
     "max": 1000},
)

FLAG_CODES = ("T-01", "T-02", "T-03", "T-04", "T-05", "T-06")

RESULT_TYPES = (
    "publication", "methodology", "model", "dataset", "digital_product",
    "grant_application", "implementation", "other",
)
RESULT_TYPE_TITLES = {
    "publication": "Публикация", "methodology": "Методика", "model": "Модель",
    "dataset": "Набор данных", "digital_product": "Цифровой продукт",
    "grant_application": "Грантовая заявка", "implementation": "Внедрение",
    "other": "Другое",
}
PUBLISH_MODES = ("none", "project", "results", "all")
PARTICIPATION_ROLES = ("leader", "member", "supervisor", "curator")


@dataclass
class RowProtocol:
    """Построчный протокол разбора одной строки (п.7.2 п.5)."""
    row_number: int
    title: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    action: str = "create"          # create|skip|update
    project_id: str | None = None

    @property
    def status(self) -> str:
        if self.errors:
            return "error"
        if self.duplicates:
            return "duplicate"
        if self.warnings:
            return "warning"
        return "ok"

    def as_dict(self) -> dict:
        return {
            "row": self.row_number,
            "title": self.title,
            "status": self.status,
            "action": self.action,
            "errors": [{"field": e.split(":")[0].strip(),
                        "reason": e.split(":", 1)[1].strip() if ":" in e else e}
                       for e in self.errors],
            "warnings": self.warnings,
            "duplicates": self.duplicates,
            "project_id": self.project_id,
        }


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_date(value: str, field_label: str, errors: list[str]) -> str | None:
    text = _clean(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date().isoformat()
        except ValueError:
            continue
    errors.append(f"{field_label}: дата «{text}» не распознана (ожидается ГГГГ-ММ-ДД)")
    return None


def _split(value: str, sep: str) -> list[str]:
    return [p.strip() for p in value.split(sep) if p.strip()]


# ---------------------------------------------------------------------------
#  Чтение файла
# ---------------------------------------------------------------------------

def _read_csv_rows(text: str) -> list[list[Any]]:
    """Прочитать CSV, определив разделитель по утверждённой форме.

    Оба разделителя являются корректным входом (п.7.2 п.2): точка с запятой —
    формат выгрузки системы, запятая — формат по умолчанию в csv.reader и в
    Excel, сохраняющем CSV. Фиксированный разделитель ломал вторую сторону:
    при чтении строки запятой получается одна ячейка из всей строки, и
    утверждённая форма «не найдена», хотя файл верный. Выбирается тот
    разделитель, при котором строка заголовков совпадает с формой.
    """
    best: tuple[int, list[list[Any]]] | None = None
    for delimiter in (";", ","):
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter)
                if any(str(cell).strip() for cell in r)]
        if not rows:
            continue
        headers = {_clean(cell) for cell in rows[0]}
        score = sum(1 for col in IMPORT_COLUMNS if col["header"] in headers)
        if best is None or score > best[0]:
            best = (score, rows)
        if score == len(IMPORT_COLUMNS):
            break
    if best is None:
        raise ValueError("Файл пуст: нет ни одной строки с данными")
    return best[1]


def read_rows(data: bytes, filename: str) -> list[dict]:
    """Прочитать строки из XLSX или CSV.

    УРОК ОТДЕЛА (memories/2026/10/2026-10-02-truncated-file-silent-success):
    чтение файла проверяется по ожидаемому числу строк. Обрезанный файл
    обязан падать явно, а не возвращать половину данных как будто всё в порядке.
    """
    name = (filename or "").lower()
    if name.endswith(".csv"):
        text = data.decode("utf-8-sig")
        # Разделитель CSV — точка с запятой, как и в выгрузке
        # (см. ИНСТРУКЦИЯ-ИМПОРТА). Чтение с запятой по умолчанию не находит
        # разделителей вовсе: строка целиком становится одним «заголовком»,
        # и файл отвергается как не соответствующий форме.
        raw = _read_csv_rows(text)
        header, body = raw[0], raw[1:]
    else:
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 — причина в сообщении пользователю
            raise ValueError(f"Файл не читается как XLSX: {exc}") from None
        ws = wb[wb.sheetnames[0]]
        raw = [[c for c in row] for row in ws.iter_rows(values_only=True)]
        raw = [r for r in raw if any(c is not None and str(c).strip() for c in r)]
        if not raw:
            raise ValueError("Файл пуст: нет ни одной строки с данными")
        header, body = raw[0], raw[1:]
        wb.close()

    if not header:
        raise ValueError("В файле отсутствует строка заголовков")
    header_texts = [_clean(h) for h in header]
    expected = {c["header"] for c in IMPORT_COLUMNS}
    unknown = [h for h in header_texts if h and h not in expected]
    missing = sorted(expected - set(header_texts))
    if missing:
        raise ValueError(
            "Файл не соответствует утверждённой форме инвентаризации (п.7.2 п.1). "
            f"Отсутствуют колонки: {', '.join(missing)}. "
            f"Лишние колонки будут проигнорированы: {', '.join(unknown) if unknown else 'нет'}"
        )
    index = {h: i for i, h in enumerate(header_texts)}
    rows = []
    for raw_row in body:
        row = {}
        for col in IMPORT_COLUMNS:
            pos = index.get(col["header"])
            row[col["key"]] = _clean(raw_row[pos]) if pos is not None and pos < len(raw_row) else ""
        rows.append(row)
    return rows


def _check_integrity(rows: list[dict], expected_rows: int | None) -> None:
    """Проверить, что прочитаны все строки."""
    if expected_rows is not None and len(rows) != expected_rows:
        raise ValueError(
            f"Файл прочитан не полностью: ожидалось строк {expected_rows}, "
            f"получено {len(rows)}. Загрузка прервана — вероятно, файл обрезан "
            f"или повреждён.")


# ---------------------------------------------------------------------------
#  Разбор и проверка строк
# ---------------------------------------------------------------------------

@dataclass
class ImportPreview:
    batch_id: str
    file_name: str
    total_rows: int
    ok_rows: int
    warning_rows: int
    error_rows: int
    duplicate_rows: int
    protocol: list[dict]
    created: bool = False

    def as_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "file_name": self.file_name,
            "created": self.created,
            "counts": {
                "total": self.total_rows,
                "ok": self.ok_rows,
                "warning": self.warning_rows,
                "error": self.error_rows,
                "duplicate": self.duplicate_rows,
            },
            "message": (
                "До подтверждения импорт не изменяет рабочие данные (п.7.2 п.4). "
                "Повторите запрос с confirm=true для загрузки строк без ошибок."
            ),
            "protocol": self.protocol,
        }


def preview_rows(rows: list[dict], file_name: str) -> ImportPreview:
    """Предпросмотр: проверка полей, поиск дублей, построчный протокол.

    Рабочие данные не изменяются (п.7.2 п.4): здесь только чтение.
    """
    programs = {r["code"]: r["id"] for r in query(
        "SELECT id, code FROM programs WHERE archived_at IS NULL")}
    persons_by_contact = {r["service_contact"]: r["id"] for r in query(
        "SELECT id, service_contact FROM persons WHERE archived_at IS NULL"
        " AND service_contact IS NOT NULL")}
    persons_by_name = {r["full_name"].lower(): r["id"] for r in query(
        "SELECT id, full_name FROM persons WHERE archived_at IS NULL")}

    protocol: list[RowProtocol] = []
    for index, raw in enumerate(rows, start=2):  # строка 1 — заголовки
        item = RowProtocol(row_number=index, title=_clean(raw.get("title")))
        _validate_row(item, raw, programs, persons_by_contact, persons_by_name)
        if not item.errors and item.title:
            dups = svc.find_duplicates(item.title,
                                       program_id=programs.get(_clean(raw.get("program_code"))))
            if dups:
                item.duplicates = [
                    {"code": d.code, "title": d.title, "similarity": d.similarity,
                     "reason": d.reason} for d in dups[:5]]
                item.warnings.append(
                    f"Похожие проекты: {', '.join(d.code for d in dups[:3])}. "
                    "Повторная загрузка создаст вторую карточку")
        protocol.append(item)

    return ImportPreview(
        batch_id=new_id(),
        file_name=file_name,
        total_rows=len(protocol),
        ok_rows=sum(1 for p in protocol if p.status == "ok"),
        warning_rows=sum(1 for p in protocol if p.status == "warning"),
        error_rows=sum(1 for p in protocol if p.status == "error"),
        duplicate_rows=sum(1 for p in protocol if p.status == "duplicate"),
        protocol=[p.as_dict() for p in protocol],
    )


def _validate_row(item: RowProtocol, raw: dict, programs: dict,
                  persons_by_contact: dict, persons_by_name: dict) -> None:
    """Проверить одну строку по правилам формы и обязательным полям."""
    def err(field: str, reason: str) -> None:
        item.errors.append(f"{field}: {reason}")

    for col in IMPORT_COLUMNS:
        value = _clean(raw.get(col["key"]))
        if col["required"] and not value:
            err(col["header"].split(" (")[0], "обязательное поле не заполнено")
        elif value and col.get("max") and len(value) > col["max"]:
            err(col["header"].split(" (")[0],
                f"превышена длина ({len(value)} символов при максимуме {col['max']})")

    code = _clean(raw.get("program_code"))
    if code and code not in programs:
        err("Код программы (A-05)",
            f"программа «{code}» не найдена; допускается только действующая программа")

    leader_email = _clean(raw.get("leader_email"))
    leader_name = _clean(raw.get("leader_name"))
    if leader_email and leader_email not in persons_by_contact:
        item.warnings.append(
            f"Руководитель с адресом «{leader_email}» не найден — профиль будет создан")
    if not leader_email and leader_name and leader_name.lower() not in persons_by_name:
        item.warnings.append(
            f"Руководитель «{leader_name}» не найден в справочнике — профиль будет создан")

    start = _parse_date(raw.get("planned_start", ""), "Плановое начало (A-11)", item.errors)
    end = _parse_date(raw.get("planned_end", ""), "Плановое завершение (A-11)", item.errors)
    if start and end and start > end:
        err("Плановые даты (A-11)", "начало позже завершения")

    mode = _clean(raw.get("publish_mode")) or "none"
    if mode not in PUBLISH_MODES:
        err("Режим публикации (A-15)", f"допустимые значения: {', '.join(PUBLISH_MODES)}")

    rtype = _clean(raw.get("planned_result_type"))
    if rtype and rtype not in RESULT_TYPES:
        err("Планируемый результат (A-25)",
            f"допустимые значения: {', '.join(RESULT_TYPES)}")

    flags = set(_split(_clean(raw.get("flags")), ";"))
    unknown_flags = flags - set(FLAG_CODES)
    if unknown_flags:
        err("Признаки полного маршрута", f"неизвестные коды: {', '.join(sorted(unknown_flags))}")
    if mode in ("project", "all") and not _clean(raw.get("public_annotation")):
        item.warnings.append(
            "A-04: публичная аннотация обязательна при публикации — проект не будет "
            "передан в публичный контур до её заполнения")

    team = _split(_clean(raw.get("team")), ";")
    if not team:
        err("Команда (A-13)", "нужен хотя бы один участник в формате Ф. И. О.;роль;задача")
    for member in team:
        parts = _split(member, "|")
        if len(parts) < 2:
            err("Команда (A-13)",
                f"запись «{member}» должна быть в формате Ф. И. О.;роль;задача")
        elif parts[1] not in PARTICIPATION_ROLES:
            err("Команда (A-13)",
                f"роль «{parts[1]}» в «{member}» недопустима: {', '.join(PARTICIPATION_ROLES)}")

    milestones = [m for m in _split(_clean(raw.get("milestones")), "\n") if m]
    if not milestones:
        err("Контрольные точки (A-35)",
            "нужна хотя бы одна точка в формате название;дата;ответственный")
    for ms in milestones:
        parts = _split(ms, "|")
        if len(parts) < 3:
            err("Контрольные точки (A-35)",
                f"запись «{ms}» должна быть в формате название;дата;ответственный")
        else:
            ms_date = _parse_date(parts[1], f"Контрольная точка «{parts[0]}»", item.errors)
            if ms_date and start and end and not (start <= ms_date <= end):
                item.warnings.append(
                    f"дата точки «{parts[0]}» ({fmt_date(ms_date)}) вне сроков проекта")


# ---------------------------------------------------------------------------
#  Загрузка
# ---------------------------------------------------------------------------

def confirm_import(preview: ImportPreview, rows: list[dict], file_name: str,
                   actor: Actor) -> ImportPreview:
    """Загрузить строки без ошибок. До подтверждения данные не менялись."""
    now = now_iso()
    program_cache: dict[str, str] = {}
    person_cache: dict[str, str] = {}
    created = 0
    skipped = 0

    fresh = preview_rows(rows, file_name)
    protocol_by_row = {p["row"]: p for p in fresh.protocol}

    for index, raw in enumerate(rows, start=2):
        entry = protocol_by_row.get(index)
        if entry is None or entry["status"] == "error":
            skipped += 1
            continue
        with transaction() as conn:
            program_id = _resolve_program(conn, raw, program_cache, actor)
            if program_id is None:
                skipped += 1
                continue
            leader_id = _resolve_leader(conn, raw, person_cache, actor)
            if leader_id is None:
                skipped += 1
                continue
            payload = _to_project_payload(raw, program_id, leader_id)
            result = svc.create_project(payload=payload, user_id=actor.id)
            project_id = result["id"]
            entry["project_id"] = project_id
            entry["action"] = "create"

            _import_team(conn, project_id, raw, person_cache, actor)
            _import_milestones(conn, project_id, raw, person_cache, actor,
                               payload.get("planned_start"), payload.get("planned_end"))
            if payload.get("publish_mode") in ("project", "all"):
                conn.execute(
                    "UPDATE projects SET public_allowed_at = ?, public_allowed_by = ?"
                    " WHERE id = ?", (now, actor.id, project_id))
        created += 1

    # Пакет уже создан при предпросмотре, поэтому здесь обновление, а не вставка:
    # идентификатор пакета один на всю загрузку — от предпросмотра до итогового
    # протокола (п.7.2 п.6).
    execute(
        "INSERT INTO import_batches (id, file_name, total_rows, ok_rows, warning_rows,"
        " error_rows, duplicate_rows, status, protocol, created_at, created_by,"
        " confirmed_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?)"
        " ON CONFLICT(id) DO UPDATE SET status = 'confirmed',"
        " total_rows = excluded.total_rows, ok_rows = excluded.ok_rows,"
        " warning_rows = excluded.warning_rows, error_rows = excluded.error_rows,"
        " duplicate_rows = excluded.duplicate_rows, protocol = excluded.protocol,"
        " confirmed_at = excluded.confirmed_at",
        (preview.batch_id, file_name, fresh.total_rows, fresh.ok_rows,
         fresh.warning_rows, fresh.error_rows, fresh.duplicate_rows,
         json.dumps(fresh.protocol, ensure_ascii=False), now, actor.id, now))
    fresh.batch_id = preview.batch_id  # тот же идентификатор, что записан ниже
    fresh.created = True
    fresh.protocol = list(fresh.protocol)
    return fresh


def _resolve_program(conn, raw: dict, cache: dict, actor: Actor) -> str | None:
    code = _clean(raw.get("program_code"))
    if code in cache:
        return cache[code]
    row = conn.execute("SELECT id FROM programs WHERE code = ? AND archived_at IS NULL",
                       (code,)).fetchone()
    if row is None:
        return None
    cache[code] = row["id"]
    return row["id"]


def _resolve_person(conn, name: str, email: str, category: str,
                    cache: dict) -> str | None:
    """Найти или создать профиль человека (FR-03, п.6.1 п.2).

    Ключ сопоставления — служебный адрес либо Ф. И. О. Дубли не создаются.
    """
    email = _clean(email)
    name = _clean(name)
    if email and email in cache:
        return cache[email]
    if email:
        row = conn.execute(
            "SELECT id FROM persons WHERE service_contact = ?", (email,)).fetchone()
        if row is not None:
            cache[email] = row["id"]
            return row["id"]
    if name:
        row = conn.execute(
            "SELECT id FROM persons WHERE lower(full_name) = lower(?)", (name,)).fetchone()
        if row is not None:
            cache[email or name] = row["id"]
            return row["id"]
    pid = new_id()
    conn.execute(
        "INSERT INTO persons (id, full_name, service_contact, category, created_at,"
        " created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (pid, name or email, email or None, category, now_iso(), None))
    cache[email or name] = pid
    return pid


def _resolve_leader(conn, raw: dict, cache: dict, actor: Actor) -> str | None:
    pid = _resolve_person(conn, raw.get("leader_name", ""), raw.get("leader_email", ""),
                          "staff", cache)
    return pid


def _to_project_payload(raw: dict, program_id: str, leader_id: str) -> dict:
    flags = set(_split(_clean(raw.get("flags")), ";"))
    payload = {
        "program_id": program_id,
        "title": _clean(raw.get("title")),
        "short_title": _clean(raw.get("short_title")),
        "theme_link": _clean(raw.get("theme_link")),
        "publish_mode": _clean(raw.get("publish_mode")) or "none",
        "planned_start": _clean(raw.get("planned_start")),
        "planned_end": _clean(raw.get("planned_end")),
        "problem": _clean(raw.get("problem")),
        "question": _clean(raw.get("question")),
        "goal": _clean(raw.get("goal")),
        "data_basis": _clean(raw.get("data_basis")),
        "planned_result_type": _clean(raw.get("planned_result_type")),
        "public_annotation": _clean(raw.get("public_annotation")) or None,
        "methods": [{"title": m} for m in _split(_clean(raw.get("methods")), ";")],
        "result_criteria": [{"title": m} for m in _split(_clean(raw.get("result_criteria")), ";")],
        "leader_person_id": leader_id,
        "flag_external_funding": "T-01" in flags,
        "flag_partner": "T-01" in flags,
        "flag_personal_data": "T-02" in flags,
        "flag_human_subjects": "T-02" in flags,
        "flag_ethics_required": "T-02" in flags,
        "flag_extra_resources": "T-03" in flags,
        "flag_critical_infra": "T-04" in flags,
        "flag_high_risk": "T-04" in flags,
        "flag_external_product": "T-05" in flags,
        "flag_confidential": "T-06" in flags,
        "flag_ip_restricted": "T-06" in flags,
    }
    if not payload["public_annotation"]:
        payload["public_annotation"] = None
    return payload


def _import_team(conn, project_id: str, raw: dict, cache: dict, actor: Actor) -> None:
    leader_id = _resolve_person(conn, raw.get("leader_name", ""),
                                raw.get("leader_email", ""), "staff", cache)
    if leader_id:
        conn.execute(
            "INSERT OR IGNORE INTO participations (id, project_id, person_id, role,"
            " created_at, created_by) VALUES (?, ?, ?, 'leader', ?, ?)",
            (new_id(), project_id, leader_id, now_iso(), actor.id))
        conn.execute("UPDATE projects SET leader_person_id = ? WHERE id = ?",
                     (leader_id, project_id))
    for member in _split(_clean(raw.get("team")), ";"):
        parts = _split(member, "|")
        if len(parts) < 2:
            continue
        name, role = parts[0], parts[1]
        task = parts[2] if len(parts) > 2 else None
        category = "aspirant" if role == "supervisor" else "staff"
        pid = _resolve_person(conn, name, "", category, cache)
        if not pid:
            continue
        if role == "leader":
            continue
        conn.execute(
            "INSERT OR IGNORE INTO participations (id, project_id, person_id, role, task,"
            " created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id(), project_id, pid, role, task, now_iso(), actor.id))


def _import_milestones(conn, project_id: str, raw: dict, cache: dict, actor: Actor,
                       start: str | None, end: str | None) -> None:
    leader_id = _resolve_person(conn, raw.get("leader_name", ""),
                                raw.get("leader_email", ""), "staff", cache)
    for entry in _split(_clean(raw.get("milestones")), "\n"):
        parts = _split(entry, "|")
        if len(parts) < 3:
            continue
        title, date_text, responsible = parts[0], parts[1], parts[2]
        ms_date = _parse_date(date_text, "дата", [])
        if not ms_date:
            continue
        resp_id = leader_id or _resolve_person(conn, responsible, "", "staff", cache)
        if resp_id:
            conn.execute(
                "INSERT OR IGNORE INTO participations (id, project_id, person_id, role,"
                " created_at, created_by) VALUES (?, ?, ?, 'member', ?, ?)",
                (new_id(), project_id, resp_id, now_iso(), actor.id))
        conn.execute(
            "INSERT INTO milestones (id, project_id, title, planned_date,"
            " responsible_person_id, planned_evidence, status, created_at, created_by)"
            " VALUES (?, ?, ?, ?, ?, ?, 'planned', ?, ?)",
            (new_id(), project_id, title, ms_date, resp_id,
             "Подтверждение по завершении этапа", now_iso(), actor.id))


# ---------------------------------------------------------------------------
#  Шаблон формы
# ---------------------------------------------------------------------------

def build_template_xlsx() -> bytes:
    """Шаблон формы инвентаризации, совпадающий с обязательными полями (п.7.2 п.1)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Инвентаризация"
    headers = [c["header"] for c in IMPORT_COLUMNS]
    ws.append(headers)
    example = [
        "Адаптивные методы управления качеством образовательных услуг",
        "Адаптивные методы управления качеством",
        "НП-01",
        "Иванов Иван Иванович",
        "i.ivanov@iubip.ru",
        today_iso(),
        "2027-12-31",
        "Снижение доли формальных процедур контроля качества в вузе",
        "Снижает ли адаптивный контроль издержки преподавателя без потери качества",
        "Проверить на трёх факультетах за два учебных года",
        "Сравнительный анализ; анкетирование преподавателей",
        "Анкеты 1200 преподавателей, журналы успеваемости 2019–2025",
        "methodology",
        "Снижение доли ручных проверок на 30%",
        "Система управления качеством образовательного процесса",
        "none",
        "Иванов Иван Иванович|leader|руководитель проекта",
        "Подготовка методики|2027-03-31|Иванов Иван Иванович",
        "",
        "",
    ]
    ws.append(example)
    fill = PatternFill("solid", fgColor="DDDDDD")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for i, col in enumerate(IMPORT_COLUMNS, start=1):
        width = 60 if col["key"] in ("problem", "data_basis", "milestones", "team") else 26
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"

    note = wb.create_sheet("Пояснение")
    note.append(["Форма инвентаризации научных проектов (п.7.2 ТЗ)"])
    note.append(["Дата формирования", now_iso()])
    note.append([])
    note.append(["Колонка", "Обязательна", "Примечание"])
    for col in IMPORT_COLUMNS:
        note.append([col["header"], "да" if col["required"] else "нет",
                     f"максимум {col['max']} символов" if col.get("max") else ""])
    note.append([])
    note.append(["Формат команды", "", "Ф. И. О.;роль;задача, роли: " +
                 ", ".join(PARTICIPATION_ROLES)])
    note.append(["Формат контрольной точки", "", "название;дата;ответственный, "
                 "несколько точек — каждая с новой строки"])
    note.append(["Признаки полного маршрута", "", "коды через точку с запятой: " +
                 ", ".join(FLAG_CODES)])
    note.append(["Виды результата", "", ", ".join(RESULT_TYPES)])
    note.column_dimensions["A"].width = 46
    note.column_dimensions["B"].width = 14
    note.column_dimensions["C"].width = 70

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
#  Выгрузка (FR-28, п.7.2 п.7)
# ---------------------------------------------------------------------------

EXPORT_COLUMNS: tuple[dict[str, str], ...] = (
    {"key": "code", "header": "Номер (A-01)"},
    {"key": "title", "header": "Полное название (A-02)"},
    {"key": "short_title", "header": "Краткое название (A-03)"},
    {"key": "program", "header": "Научная программа (A-05)"},
    {"key": "route", "header": "Маршрут (A-07)"},
    {"key": "full_route_reasons", "header": "Основания полного маршрута (A-08)"},
    {"key": "status", "header": "Статус (A-09)"},
    {"key": "risk_level", "header": "Индикатор риска (A-10)"},
    {"key": "planned_start", "header": "Плановое начало (A-11)"},
    {"key": "planned_end", "header": "Плановое завершение (A-11)"},
    {"key": "leader", "header": "Руководитель (A-12)"},
    {"key": "team", "header": "Команда (A-13)"},
    {"key": "problem", "header": "Исследовательская проблема (A-17)"},
    {"key": "question", "header": "Вопрос или гипотеза (A-18)"},
    {"key": "goal", "header": "Цель (A-19)"},
    {"key": "research_object", "header": "Объект (A-21)"},
    {"key": "research_subject", "header": "Предмет (A-22)"},
    {"key": "methods", "header": "Методы (A-23)"},
    {"key": "data_basis", "header": "Данные или доказательная база (A-24)"},
    {"key": "planned_result_type", "header": "Планируемый результат (A-25)"},
    {"key": "result_criteria", "header": "Критерии результата (A-26)"},
    {"key": "novelty", "header": "Научная новизна (A-27)"},
    {"key": "applicability", "header": "Практическая применимость (A-28)"},
    {"key": "limitations", "header": "Ограничения (A-29)"},
    {"key": "personal_data", "header": "Персональные данные (A-30)"},
    {"key": "human_subjects", "header": "Участие людей (A-31)"},
    {"key": "confidentiality", "header": "Конфиденциальность и права (A-33)"},
    {"key": "publish_mode", "header": "Режим публикации (A-15)"},
    {"key": "milestones", "header": "Контрольные точки (A-35…A-42)"},
    {"key": "risks", "header": "Риски (A-65)"},
    {"key": "results", "header": "Результаты (A-43…A-54)"},
    {"key": "public_annotation", "header": "Публичная аннотация (A-04)"},
    {"key": "created_at", "header": "Дата и автор создания (A-16)"},
)

#: Что НЕ попадает в выгрузку никогда (п.9.2, закрытые сведения)
FORBIDDEN_EXPORT_COLUMNS = (
    "password_hash", "expert_reviews", "internal_comments", "audit_log",
    "resource_request", "personal_contacts", "closed_files", "confidential_partners",
)


def build_export(filters: dict, actor: Actor, *, archival: bool = False) -> tuple[bytes, str]:
    """Сформировать выгрузку XLSX.

    В выгрузку попадают только доступные пользователю поля; для неуправленческой
    роли — только собственные проекты (FR-28, п.7.2 п.7).
    """
    from ..access import visible_projects_clause

    if archival and not actor.global_roles & {"sysadmin", "techadmin"}:
        raise ValueError("Полная архивная выгрузка доступна техническому администратору "
                         "(п.7.2 п.8)")

    where = ["p.archived_at IS NULL"]
    params: list[Any] = []
    for column, key in (("program_id", "program_id"), ("route", "route"),
                        ("status", "status"), ("risk_level", "risk_level"),
                        ("leader_person_id", "leader_person_id")):
        if filters.get(key):
            where.append(f"p.{column} = ?")
            params.append(filters[key])
    if filters.get("q"):
        where.append("p.search_blob LIKE ?")
        params.append(f"%{str(filters['q']).lower()}%")
    vis_clause, _ = visible_projects_clause(actor, params)
    where.append(vis_clause)
    clause = " AND ".join(where)

    rows = query(
        f"SELECT p.*, pr.short_title AS program_title, u.login AS creator_login"
        f" FROM projects p LEFT JOIN programs pr ON pr.id = p.program_id"
        f" LEFT JOIN users u ON u.id = p.created_by WHERE {clause} ORDER BY p.code",
        tuple(params))

    wb = Workbook()
    ws = wb.active
    ws.title = "Проекты"
    ws.append([c["header"] for c in EXPORT_COLUMNS])

    for row in rows:
        ws.append([csv_safe(_export_value(row, c["key"], archival)) for c in EXPORT_COLUMNS])

    fill = PatternFill("solid", fgColor="DDDDDD")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for i in range(1, len(EXPORT_COLUMNS) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 34
    ws.freeze_panes = "A2"

    # Лист метаданных: дата формирования и применённые фильтры (п.7.2 п.7)
    meta = wb.create_sheet("Условия выгрузки")
    meta.append(["Параметр", "Значение"])
    meta.append(["Дата формирования", fmt_date(today_iso())])
    meta.append(["Дата и время (МСК)", now_iso()])
    meta.append(["Пользователь", actor.login])
    meta.append(["Роли", ", ".join(sorted(actor.global_roles)) or "—"])
    meta.append(["Тип выгрузки", "архивная полная" if archival else "по правам пользователя"])
    applied = {k: v for k, v in filters.items() if v not in (None, "", False)}
    meta.append(["Фильтры", json.dumps(applied, ensure_ascii=False) if applied else "не применялись"])
    meta.append(["Записей", len(rows)])
    meta.append(["Кодировка", "UTF-8"])
    meta.append(["Исключённые категории", ", ".join(FORBIDDEN_EXPORT_COLUMNS)])
    meta.column_dimensions["A"].width = 26
    meta.column_dimensions["B"].width = 80

    buf = io.BytesIO()
    wb.save(buf)
    name = f"registry_export_{today_iso().replace('-', '')}.xlsx"
    return buf.getvalue(), name


def _export_value(row, key: str, archival: bool) -> Any:
    if key == "program":
        return row["program_title"] or row["program_id"]
    if key == "full_route_reasons":
        return ", ".join(svc.stored_full_reasons(row["id"]))
    if key == "leader":
        return scalar("SELECT full_name FROM persons WHERE id = ?",
                      (row["leader_person_id"],), "") or ""
    if key == "team":
        return "; ".join(
            f"{r['full_name']}|{r['role']}|{r['task'] or ''}" for r in query(
                "SELECT p.full_name, pp.role, pp.task FROM participations pp"
                " JOIN persons p ON p.id = pp.person_id WHERE pp.project_id = ?"
                " AND pp.archived_at IS NULL ORDER BY pp.role, p.full_name", (row["id"],)))
    if key == "milestones":
        return "\n".join(
            f"{r['title']}|{fmt_date(r['planned_date'])}|"
            f"{r['status']}|{scalar('SELECT full_name FROM persons WHERE id = ?', (r['responsible_person_id'],), '') or ''}"
            for r in query(
                "SELECT * FROM milestones WHERE project_id = ? AND archived_at IS NULL"
                " ORDER BY planned_date", (row["id"],)))
    if key == "risks":
        return "\n".join(
            f"{r['category']}|{r['level']}|{r['description'][:200]}"
            for r in query(
                "SELECT * FROM risks WHERE project_id = ? AND archived_at IS NULL", (row["id"],)))
    if key == "results":
        return "\n".join(
            f"{r['code']}|{r['result_type']}|{r['title']}|{r['readiness_stage']}"
            for r in query(
                "SELECT r.* FROM results r JOIN result_projects rp ON rp.result_id = r.id"
                " WHERE rp.project_id = ? AND r.archived_at IS NULL ORDER BY r.code",
                (row["id"],)))
    if key in ("personal_data", "human_subjects"):
        return "да" if row[key] else "нет"
    if key in ("planned_start", "planned_end"):
        return fmt_date(row[key])
    if key == "created_at":
        creator = row["creator_login"] or ""
        return f"{row['created_at']} {creator}".strip()
    if key == "resource_request":
        # П.9.2: ресурсные запросы не публикуются; в выгрузку по правам не идут.
        return row[key] if archival else ""
    return row[key]


def build_csv_export(filters: dict, actor: Actor, *, archival: bool = False) -> bytes:
    """CSV-выгрузка с BOM — чтобы Excel открывал кириллицу без ручной настройки.

    Пишем в StringIO, а не в BytesIO: csv.writer требует текстовый поток,
    кодирование делается один раз здесь.
    """
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([c["header"] for c in EXPORT_COLUMNS])
    for row in build_export_rows(filters, actor, archival=archival):
        writer.writerow(["" if v is None else v for v in row])
    # UTF-8 BOM: п.10.2 п.1 требует UTF-8, а Excel без BOM ломает кириллицу
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def build_export_rows(filters: dict, actor: Actor, *, archival: bool = False) -> list[list]:
    """Строки выгрузки — общая часть для XLSX и CSV."""
    from ..access import visible_projects_clause

    where = ["p.archived_at IS NULL"]
    params: list[Any] = []
    for column, key in (("program_id", "program_id"), ("route", "route"),
                        ("status", "status"), ("risk_level", "risk_level"),
                        ("leader_person_id", "leader_person_id")):
        if filters.get(key):
            where.append(f"p.{column} = ?")
            params.append(filters[key])
    vis_clause, _ = visible_projects_clause(actor, params)
    where.append(vis_clause)
    rows = query(
        f"SELECT p.*, pr.short_title AS program_title, u.login AS creator_login"
        f" FROM projects p LEFT JOIN programs pr ON pr.id = p.program_id"
        f" LEFT JOIN users u ON u.id = p.created_by WHERE {' AND '.join(where)}"
        f" ORDER BY p.code", tuple(params))
    return [[csv_safe(_export_value(r, c["key"], archival)) for c in EXPORT_COLUMNS]
            for r in rows]