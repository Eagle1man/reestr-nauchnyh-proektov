"""Конфигурация приложения.

Все секреты приходят из окружения или файла .env (SEC-05: пароли, ключи и
токены не хранятся открыто и не выводятся в журналы). Файл .env в .gitignore.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _load_env_file(path: Path) -> dict[str, str]:
    """Прочитать .env. Отсутствие файла не является ошибкой."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


_env_file = _load_env_file(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    """Переменная окружения имеет приоритет над .env."""
    return os.environ.get(name, _env_file.get(name, default))


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).strip().lower() in {"1", "true", "yes", "on", "да"}


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str = env("APP_NAME", "Реестр научных проектов")
    debug: bool = env_bool("DEBUG", False)
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in env("CORS_ORIGINS").split(",") if o.strip()
        )
    )

    database_path: str = env("DATABASE_PATH", "backend/data/registry.db")
    sqlite_timeout_seconds: int = env_int("SQLITE_TIMEOUT_SECONDS", 30)

    secret_key: str = env("SECRET_KEY", "")
    password_min_length: int = env_int("PASSWORD_MIN_LENGTH", 12)
    login_max_attempts: int = env_int("LOGIN_MAX_ATTEMPTS", 5)
    login_lock_minutes: int = env_int("LOGIN_LOCK_MINUTES", 15)
    # Ограничение перебора по адресу: порог выше, чем у учётной записи, чтобы
    # один посторонний не мог заблокировать сотруднику доступ, отправив 5
    # неверных паролей от его имени. П.11.1 описывает блокировку по попыткам
    # входа; адресный порог — защита от подбора пароля (SEC-04).
    login_ip_max_attempts: int = env_int("LOGIN_IP_MAX_ATTEMPTS", 25)
    session_idle_minutes: int = env_int("SESSION_IDLE_MINUTES", 60)

    backup_dir: str = env("BACKUP_DIR", "backups")
    backup_retention_days: int = env_int("BACKUP_RETENTION_DAYS", 30)
    backup_verify_on_restore: bool = env_bool("BACKUP_VERIFY_ON_RESTORE", True)

    public_rate_limit_per_minute: int = env_int("PUBLIC_RATE_LIMIT_PER_MINUTE", 60)
    public_allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in env("PUBLIC_ALLOWED_ORIGINS").split(",") if o.strip()
        )
    )

    upload_max_bytes: int = env_int("UPLOAD_MAX_BYTES", 20 * 1024 * 1024)
    upload_allowed_extensions: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            e.strip().lower()
            for e in env("UPLOAD_ALLOWED_EXTENSIONS").split(",")
            if e.strip()
        )
    )

    @property
    def db_file(self) -> Path:
        p = Path(self.database_path)
        return p if p.is_absolute() else BASE_DIR / p

    @property
    def backup_path(self) -> Path:
        p = Path(self.backup_dir)
        return p if p.is_absolute() else BASE_DIR / p

    def ensure_secret(self) -> str:
        """Ключ подписи сессий. В DEBUG генерируем временный, иначе требуем явный."""
        if self.secret_key:
            return self.secret_key
        if self.debug:
            return secrets.token_urlsafe(48)
        raise RuntimeError(
            "SECRET_KEY не задан. Скопируйте .env.example в .env и заполните "
            "SECRET_KEY (python -c \"import secrets;print(secrets.token_urlsafe(48))\")."
        )


settings = Settings()