"""Точка входа приложения «Реестр научных проектов Южного университета (ИУБиП)».

Одна кодовая база и одна реляционная база данных (п.3.1 ТЗ). Модульное
веб-приложение: закрытая рабочая зона (/api) и отдельная публичная проекция
(/api/public/v1) без доступа к рабочим таблицам (SEC-03).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, settings

logger = logging.getLogger("registry")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .db import run_migrations
    from .security import purge_expired_sessions

    settings.ensure_secret()
    # Путь к базе печатается при старте намеренно: если процесс запущен не из
    # ожидаемого каталога, он молча создаст пустую базу рядом с собой, и это
    # обнаружится только на приёмке. (Урок отдела: молчаливый снимок/файл.)
    print(f"[registry] база данных: {settings.db_file}", flush=True)
    print(f"[registry] каталог проекта: {BASE_DIR}", flush=True)
    applied = run_migrations()
    if applied:
        logger.info("Применены миграции: %s", ", ".join(applied))
    purged = purge_expired_sessions()
    if purged:
        logger.info("Удалено истёкших сессий: %d", purged)
    logger.info("%s: база %s", settings.app_name, settings.database_path)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Электронная информационная система «Реестр научных проектов "
        "Южного университета (ИУБиП)». Разработана по техническому заданию "
        "версии 1.0 от 06.10.2026."
    ),
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS: только явно разрешённые источники. Пустой список = запросы без Origin
# (curl, серверные интеграции) плюс тот же origin.
_origins = list(settings.cors_origins) or [settings.public_allowed_origins and
                                           list(settings.public_allowed_origins)[0] or ""]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in _origins if o],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
    max_age=600,
)


# ---------------------------------------------------------------------------
#  Обработка ошибок
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Ошибка указывает поле и способ исправления (п.10.2 п.6)."""
    problems = []
    for err in exc.errors():
        location = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
        problems.append({
            "field": ".".join(location) or "запрос",
            "message": err.get("msg", "некорректное значение"),
            "type": err.get("type"),
        })
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "Проверка входных данных не пройдена", "problems": problems},
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    """Внутренняя ошибка не должна выдавать служебные подробности (ПС-01).

    Подробности — в журнал сервера, наружу — нейтральный текст и
    идентификатор для поиска по журналу.
    """
    import uuid as _uuid
    ref = str(_uuid.uuid4())[:8]
    logger.exception("Необработанная ошибка [%s] на %s %s", ref, request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Внутренняя ошибка сервера",
                 "reference": ref,
                 "hint": "Сообщите администратору код обращения"},
    )


# ---------------------------------------------------------------------------
#  Маршруты
# ---------------------------------------------------------------------------

def _include_routers() -> None:
    from .api import (
        admin, analytics, audit_api, auth, education, programs, projects,
        public_api, results, review, transfer, work,
    )
    for module in (auth, programs, projects, work, review, results, education,
                   analytics, transfer, public_api, admin, audit_api):
        app.include_router(module.router)


_include_routers()


@app.get("/api/health", tags=["Служебные"])
def health():
    """Проверка состояния. Не раскрывает путей и версий внутренних компонентов."""
    from .db import query_one
    ok = query_one("SELECT 1") is not None
    return {"status": "ok" if ok else "degraded", "app": settings.app_name,
            "version": app.version}


@app.get("/api/meta/roles", tags=["Служебные"])
def roles_matrix():
    """Матрица ролей для поставки (п.15, позиция 5)."""
    from .domain.taxonomy import DECISION_MATRIX, GLOBAL_ROLES
    return {"roles": GLOBAL_ROLES, "decision_matrix": DECISION_MATRIX}


@app.get("/api/meta/fields", tags=["Служебные"])
def field_dictionary():
    """Словарь полей карточки (Приложение А)."""
    from .domain.validation import dictionary_document
    return {"fields": dictionary_document(), "count": len(dictionary_document())}


# ---------------------------------------------------------------------------
#  Интерфейс (SPA) и публичная витрина
# ---------------------------------------------------------------------------

FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"),
              name="assets")

    @app.get("/public", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    def spa_root():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_catchall(full_path: str):
        """SPA-маршрутизация: неизвестный путь отдаёт index.html, но не API."""
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404,
                                content={"error": "Неизвестный метод API"})
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def no_frontend():
        return JSONResponse(
            status_code=200,
            content={"app": settings.app_name, "api": "/api/docs",
                     "public_api": "/api/public/v1",
                     "note": "Интерфейс не собран: выполните "
                             "cd frontend && npm install && npm run build"})