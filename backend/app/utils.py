"""Рабочие дни, даты и идентификаторы.

ТЗ п.10.2: даты отображаются в формате ДД.ММ.ГГГГ, время московское.
Все сроки обработки (п.5.5) и пороги риска (п.5.4) считаются в РАБОЧИЕ дни,
поэтому здесь рабочие дни, а не календарные.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: П.10.2 п.2 — время московское. На Windows системной базы часовых поясов нет,
#: поэтому полагаемся на пакет tzdata из requirements.txt. Без него откатываемся
#: на UTC+3 без перехода на летнее время: московское время перехода не имеет.
try:
    MOSCOW = ZoneInfo("Europe/Moscow")
except ZoneInfoNotFoundError:  # pragma: no cover — зависит от окружения
    MOSCOW = timezone(timedelta(hours=3))

#: П.5.5 «рабочий день» — понедельник…пятница. Праздничный календарь
#: университета задаётся в settings (FR-35), по умолчанию не учитывается.


def new_id() -> str:
    """Внутренний UUID объекта (п.6.1 п.1)."""
    return str(uuid.uuid4())


def now_msk() -> datetime:
    return datetime.now(MOSCOW)


def today_msk() -> date:
    return now_msk().date()


def now_iso() -> str:
    """Московское время в ISO 8601 со смещением — для журнала (A-69)."""
    return now_msk().isoformat(timespec="seconds")


def today_iso() -> str:
    return today_msk().isoformat()


def fmt_date(value: str | date | None) -> str:
    """ДД.ММ.ГГГГ (п.10.2 п.2)."""
    if not value:
        return ""
    d = to_date(value)
    return d.strftime("%d.%m.%Y") if d else ""


def fmt_datetime(value: str | datetime | None) -> str:
    """ДД.ММ.ГГГГ ЧЧ:ММ (московское)."""
    if not value:
        return ""
    dt = to_datetime(value)
    return dt.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M") if dt else ""


def to_date(value: str | date | datetime | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:19] if "T" in text or " " in text else text,
                                     fmt).date()
        except ValueError:
            continue
    return None


def to_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        d = to_date(text)
        if d is None:
            return None
        dt = datetime.combine(d, time(0, 0))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_working_day(d: date, holidays: set[str] | None = None) -> bool:
    if d.weekday() >= 5:
        return False
    if holidays and d.isoformat() in holidays:
        return False
    return True


def add_working_days(start: date, days: int, holidays: set[str] | None = None) -> date:
    """Добавить N рабочих дней к дате."""
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if is_working_day(current, holidays):
            remaining -= 1
    return current


def working_days_between(start: date, end: date, holidays: set[str] | None = None) -> int:
    """Сколько рабочих дней прошло между датами (отрицательное — если end раньше)."""
    if start == end:
        return 0
    sign = 1 if end > start else -1
    a, b = (start, end) if end > start else (end, start)
    count = 0
    cursor = a
    while cursor < b:
        cursor += timedelta(days=1)
        if is_working_day(cursor, holidays):
            count += 1
    return sign * count


def next_code(prefix: str, year: int, start: int = 1, width: int = 4) -> list[str]:
    """Сгенерировать последовательные номера вида РНП-2026-0001 (FR-06)."""
    return [f"{prefix}-{year}-{n:0{width}d}" for n in range(start, start + 1)]


def csv_safe(value: object) -> object:
    """Значение, безопасное для выгрузки: снять ведущие формулы (OWASP)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value