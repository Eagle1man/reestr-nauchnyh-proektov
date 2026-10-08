"""Хеширование паролей, блокировка входа, сессии.

П.11.1 ТЗ:
  1. пароль не менее 12 символов;
  2. после пяти последовательных неудачных попыток вход блокируется на 15 минут;
  3. сессия завершается после 60 минут бездействия;
  4. восстановление доступа выполняет администратор либо подтверждённый
     служебный адрес.

SEC-05: пароли, ключи и токены не хранятся открыто и не выводятся в журналы.
SEC-07: усиленная защита учётных записей администраторов.

Для хешей используется PBKDF2-HMAC-SHA256 из стандартной библиотеки — без
внешних зависимостей, формат самодостаточный и проверяемый на месте.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

from .config import settings
from .db import execute, query, query_one, scalar
from .utils import new_id, now_iso, now_msk, to_datetime

PBKDF2_ROUNDS = 260_000
SALT_BYTES = 16


# ---------------------------------------------------------------------------
#  Пароли
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, actual)


def password_problems(password: str) -> list[str]:
    """Проверки п.11.1 п.1 плюс базовая стойкость."""
    problems: list[str] = []
    if len(password or "") < settings.password_min_length:
        problems.append(
            f"Пароль короче {settings.password_min_length} символов (п.11.1)"
        )
    checks = (
        (any(c.islower() for c in password), "строчные буквы"),
        (any(c.isupper() for c in password), "прописные буквы"),
        (any(c.isdigit() for c in password), "цифры"),
        (any(not c.isalnum() for c in password), "специальные символы"),
    )
    for ok, title in checks:
        if not ok:
            problems.append(f"Пароль должен содержать {title}")
    return problems


def generate_password() -> str:
    """Пароль, удовлетворяющий всем проверкам — для первичной выдачи учётной записи."""
    while True:
        candidate = (
            secrets.choice("abcdefghijkmnopqrstuvwxyz")
            + secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")
            + secrets.choice("23456789")
            + "".join(secrets.choice("!@#$%^&*-_=+") for _ in range(3))
            + secrets.token_urlsafe(9)
        )
        if not password_problems(candidate):
            return candidate


# ---------------------------------------------------------------------------
#  Блокировка после неудачных попыток (п.11.1 п.2)
# ---------------------------------------------------------------------------

def register_attempt(login: str, ip: str | None, successful: bool) -> None:
    execute(
        "INSERT INTO login_attempts (id, login, ip_address, successful, attempted_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (new_id(), login, ip, 1 if successful else 0, now_iso()),
    )
    if successful:
        # Успешный вход обнуляет счётчик неудач для этой учётной записи.
        execute(
            "DELETE FROM login_attempts WHERE login = ? AND successful = 0",
            (login,),
        )


def lockout_remaining(login: str) -> int:
    """Сколько секунд осталось блокировки учётной записи; 0 — можно пробовать.

    Блокировка применяется только к СУЩЕСТВУЮЩЕЙ учётной записи. Иначе любой
    посторонний мог бы «заблокировать» несуществующий логин и упереться в 423
    вместо 401, а это ещё и повод для мелкого отказа в обслуживании: достаточно
    пять раз отправить неверный пароль от имени известного логина, и сотрудник
    на 15 минут теряет доступ. Неизвестные логины ограничиваются по адресу
    (см. ip_lock_remaining).
    """
    if scalar("SELECT id FROM users WHERE login = ?", (login,)) is None:
        return 0
    since = scalar(
        "SELECT MAX(attempted_at) FROM login_attempts"
        " WHERE login = ? AND successful = 0",
        (login,),
    )
    if not since:
        return 0
    last = to_datetime(since)
    if last is None:
        return 0
    window_start = (now_msk().astimezone(last.tzinfo)
                    - timedelta(minutes=settings.login_lock_minutes))
    failures = scalar(
        "SELECT COUNT(*) FROM login_attempts"
        " WHERE login = ? AND successful = 0 AND attempted_at >= ?",
        (login, window_start.isoformat(timespec="seconds")),
        0,
    )
    if (failures or 0) < settings.login_max_attempts:
        return 0
    deadline = last + timedelta(minutes=settings.login_lock_minutes)
    return max(0, int((deadline - now_msk()).total_seconds()))


def ip_lock_remaining(ip: str | None) -> int:
    """Ограничение по адресу для перебора, включая несуществующие логины.

    Отдельный и более высокий порог, чем у учётной записи: он защищает от
    перебора логинов и не даёт отказать в обслуживании одному сотруднику.
    """
    if not ip:
        return 0
    cutoff = (now_msk() - timedelta(minutes=settings.login_lock_minutes))
    since = scalar(
        "SELECT MAX(attempted_at) FROM login_attempts"
        " WHERE ip_address = ? AND successful = 0",
        (ip,),
    )
    if not since:
        return 0
    last = to_datetime(since)
    if last is None:
        return 0
    failures = scalar(
        "SELECT COUNT(*) FROM login_attempts"
        " WHERE ip_address = ? AND successful = 0 AND attempted_at >= ?",
        (ip, cutoff.isoformat(timespec="seconds")),
        0,
    )
    if (failures or 0) < settings.login_ip_max_attempts:
        return 0
    return max(0, int((last + timedelta(minutes=settings.login_lock_minutes)
                       - now_msk()).total_seconds()))


def failed_count(login: str) -> int:
    return scalar(
        "SELECT COUNT(*) FROM login_attempts"
        " WHERE login = ? AND successful = 0 AND attempted_at >= ?",
        (login, (now_msk() - timedelta(minutes=settings.login_lock_minutes))
         .isoformat(timespec="seconds")),
        0,
    )


# ---------------------------------------------------------------------------
#  Сессии (п.11.1 п.3)
# ---------------------------------------------------------------------------

def create_session(user_id: str, user_agent: str | None, ip: str | None) -> str:
    token = secrets.token_urlsafe(48)
    now = now_msk()
    execute(
        "INSERT INTO sessions (token, user_id, created_at, last_seen_at, expires_at,"
        " user_agent, ip_address) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (token, user_id, now.isoformat(timespec="seconds"),
         now.isoformat(timespec="seconds"),
         (now + timedelta(days=7)).isoformat(timespec="seconds"),
         (user_agent or "")[:300], ip),
    )
    return token


def resolve_session(token: str) -> dict | None:
    """Вернуть пользователя по токену, если сессия жива.

    Сессия умирает по двум причинам: истёк абсолютный срок либо прошло
    SESSION_IDLE_MINUTES без обращения (п.11.1 п.3).
    """
    row = query_one("SELECT * FROM sessions WHERE token = ?", (token,))
    if row is None:
        return None
    last_seen = to_datetime(row["last_seen_at"])
    expires = to_datetime(row["expires_at"])
    now = now_msk()
    if last_seen is None or expires is None:
        return None
    idle_limit = timedelta(minutes=settings.session_idle_minutes)
    if (now - last_seen) > idle_limit or now > expires:
        execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None
    user = query_one("SELECT * FROM users WHERE id = ? AND is_active = 1", (row["user_id"],))
    if user is None:
        execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None
    execute(
        "UPDATE sessions SET last_seen_at = ? WHERE token = ?",
        (now.isoformat(timespec="seconds"), token),
    )
    return {
        "token": token,
        "session_id": row["id"] if "id" in row.keys() else token,
        "created_at": row["created_at"],
        "last_seen_at": row["last_seen_at"],
        "user": dict(user),
        "roles": user_roles(user["id"]),
    }


def destroy_session(token: str) -> None:
    execute("DELETE FROM sessions WHERE token = ?", (token,))


def destroy_all_sessions(user_id: str) -> int:
    count = scalar("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,), 0)
    execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return count or 0


def purge_expired_sessions() -> int:
    """Уборка сессий. Вызывается при старте и по расписанию."""
    cutoff = (now_msk() - timedelta(minutes=settings.session_idle_minutes))
    count = scalar("SELECT COUNT(*) FROM sessions WHERE last_seen_at < ?",
                   (cutoff.isoformat(timespec="seconds"),), 0)
    execute("DELETE FROM sessions WHERE last_seen_at < ?",
            (cutoff.isoformat(timespec="seconds"),))
    return count or 0


# ---------------------------------------------------------------------------
#  Роли пользователя
# ---------------------------------------------------------------------------

def user_roles(user_id: str) -> list[str]:
    return [r["role"] for r in query(
        "SELECT role FROM user_roles WHERE user_id = ? ORDER BY role", (user_id,)
    )]


def grant_role(user_id: str, role: str, granted_by: str | None = None) -> None:
    execute(
        "INSERT OR REPLACE INTO user_roles (user_id, role, granted_at, granted_by)"
        " VALUES (?, ?, ?, ?)",
        (user_id, role, now_iso(), granted_by),
    )


def revoke_role(user_id: str, role: str) -> None:
    execute("DELETE FROM user_roles WHERE user_id = ? AND role = ?", (user_id, role))


def password_reset_token(user_id: str) -> str:
    """Одноразовый токен восстановления доступа (п.11.1 п.4).

    Хранится только хеш токена — сам токен возвращается администратору один раз.
    """
    token = secrets.token_urlsafe(32)
    execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at, updated_by)"
        " VALUES (?, ?, ?, ?)",
        (f"reset:{user_id}:{hashlib.sha256(token.encode()).hexdigest()}",
         now_iso(), now_iso(), None),
    )
    return token


def uuid_str() -> str:
    return str(uuid.uuid4())


def sessions_count() -> int:
    return scalar("SELECT COUNT(*) FROM sessions", (), 0)