"""Публичный API только для чтения (FR-33; п.9.4 ТЗ).

П.9.1: раздел «Наука» — публичная витрина, реестр — операционный источник
данных. Сайт не хранит и не редактирует вторую копию карточки.
SEC-03: в публичной зоне нет прямого доступа к рабочей базе; передаются только
утверждённые поля.

Адреса из п.9.4 ТЗ:
  GET /api/public/v1/programs
  GET /api/public/v1/programs/{id}
  GET /api/public/v1/projects
  GET /api/public/v1/projects/{id}
  GET /api/public/v1/results
  GET /api/public/v1/results/{id}

Формат ответа — JSON в UTF-8. Ограничение частоты запросов и разрешённые домены
задаются настройками (п.9.4, на согласовании после обследования).
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from ..db import query_one
from ..services import public as svc
from ..utils import now_iso, today_iso

router = APIRouter(prefix="/api/public/v1", tags=["Публичный API (только чтение)"])


# ---------------------------------------------------------------------------
#  Ограничение частоты запросов
#  Счётчик в памяти процесса: при нескольких экземплярах приложения лимит
#  применяется к каждому, что для витрины университета достаточно.
#  Обход лимита не обслуживает данные и не меняет состояние.
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, per_minute: int):
        self.limit = max(1, per_minute)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > 60:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False, 0
            bucket.append(now)
            return True, max(0, 60 - int(now - bucket[0]))


_limiter: RateLimiter | None = None


def limiter() -> RateLimiter:
    global _limiter
    from ..config import settings
    if _limiter is None or _limiter.limit != settings.public_rate_limit_per_minute:
        _limiter = RateLimiter(settings.public_rate_limit_per_minute)
    return _limiter


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def public_response(request: Request, payload: dict | list,
                    status_code: int = 200) -> JSONResponse:
    """Ответ публичного API: JSON в UTF-8 + заголовки интеграции и лимита."""
    from ..config import settings

    allowed, remaining = limiter().allow(_client_key(request))
    if not allowed:
        # Заголовки лимита возвращаются и при отказе: клиенту нужно знать
        # величину лимита, даже когда запрос не обслужен.
        response = JSONResponse(
            status_code=429,
            content={"error": "Превышена частота запросов публичного API",
                     "limit_per_minute": settings.public_rate_limit_per_minute,
                     "retry_after_seconds": 60},
        )
        response.headers["Retry-After"] = "60"
        response.headers["X-RateLimit-Limit"] = str(settings.public_rate_limit_per_minute)
        response.headers["X-RateLimit-Remaining"] = "0"
        return response

    headers = {
        # Явная кодировка UTF-8 (п.10.2 п.1)
        "Content-Language": "ru",
        "Cache-Control": "public, max-age=300",
        "X-RateLimit-Limit": str(settings.public_rate_limit_per_minute),
        "X-RateLimit-Remaining": str(remaining),
        "X-Registry-Generated-At": now_iso(),
        "X-Registry-Version": "v1",
    }
    if settings.public_allowed_origins:
        headers["Access-Control-Allow-Origin"] = ",".join(settings.public_allowed_origins)
        headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


@router.options("/{rest:path}")
def public_options(request: Request, rest: str = ""):
    """Предварительный запрос для интеграции с официальным сайтом."""
    return public_response(request, {"ok": True})


# ---------------------------------------------------------------------------
#  Программы
# ---------------------------------------------------------------------------

@router.get("/programs")
def list_programs(request: Request, limit: int = Query(default=50, ge=1, le=200),
                  offset: int = Query(default=0, ge=0)):
    items = svc.public_programs()
    return public_response(request, {
        "data": items[offset:offset + limit],
        "meta": {"total": len(items), "limit": limit, "offset": offset,
                 "generated_at": today_iso()},
    })


@router.get("/programs/{program_id}")
def get_program(request: Request, program_id: str):
    """Одна программа — по внутреннему идентификатору или по коду."""
    row = query_one("SELECT id FROM programs WHERE id = ? OR code = ?",
                    (program_id, program_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Программа не найдена")
    for item in svc.public_programs():
        if item.get("id") == row["id"] or item.get("code") == program_id:
            return public_response(request, {"data": item})
    raise HTTPException(status_code=404,
                        detail="Программа не передаётся в публичный контур")


# ---------------------------------------------------------------------------
#  Проекты
# ---------------------------------------------------------------------------

@router.get("/projects")
def list_projects(request: Request,
                  program: str | None = Query(default=None, description="Код или UUID программы"),
                  year: int | None = Query(default=None, ge=1900, le=2200),
                  status: str | None = Query(default=None),
                  q: str | None = Query(default=None, max_length=200),
                  limit: int = Query(default=50, ge=1, le=200),
                  offset: int = Query(default=0, ge=0)):
    """Публичные проекты. Фильтры по программе, году, статусу и ключевым словам."""
    items = svc.public_projects({"program": program, "year": year,
                                 "status": status, "q": q})
    return public_response(request, {
        "data": items[offset:offset + limit],
        "meta": {
            "total": len(items), "limit": limit, "offset": offset,
            "filters": {k: v for k, v in {"program": program, "year": year,
                                         "status": status, "q": q}.items() if v},
            "generated_at": today_iso(),
        },
        "notice": "Передаются только опубликованные и разрешённые поля (SEC-03)",
    })


@router.get("/projects/{project_id}")
def get_project(request: Request, project_id: str):
    """Публичная карточка проекта. Неопубликованный проект — 404, а не 403."""
    row = query_one("SELECT * FROM projects WHERE id = ? OR code = ?",
                    (project_id, project_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    card = svc.project_public_card(dict(row))
    if not card.get("published"):
        # ПС-18: проект, запрещённый к публикации, отсутствует в публичном
        # интерфейсе. Отвечаем 404 и не раскрываем сам факт существования.
        raise HTTPException(status_code=404, detail="Проект не найден")
    return public_response(request, {"data": card})


# ---------------------------------------------------------------------------
#  Результаты
# ---------------------------------------------------------------------------

@router.get("/results")
def list_results(request: Request,
                 type: str | None = Query(default=None, description="Вид результата"),
                 year: int | None = Query(default=None, ge=1900, le=2200),
                 limit: int = Query(default=50, ge=1, le=200),
                 offset: int = Query(default=0, ge=0)):
    """Публичные результаты. Фильтры по виду и году."""
    items = svc.public_results({"type": type, "year": year})
    return public_response(request, {
        "data": items[offset:offset + limit],
        "meta": {"total": len(items), "limit": limit, "offset": offset,
                 "filters": {k: v for k, v in {"type": type, "year": year}.items() if v},
                 "generated_at": today_iso()},
    })


@router.get("/results/{result_id}")
def get_result(request: Request, result_id: str):
    row = query_one("SELECT * FROM results WHERE id = ? OR code = ?",
                    (result_id, result_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Результат не найден")
    card = svc.result_public_card(dict(row))
    if card is None:
        raise HTTPException(status_code=404, detail="Результат не найден")
    return public_response(request, {"data": card})


# ---------------------------------------------------------------------------
#  Сводка и манифест
# ---------------------------------------------------------------------------

@router.get("/stats")
def stats(request: Request):
    """Счётчики публичных данных — для витрины раздела «Наука»."""
    return public_response(request, {"data": svc.stats()})


@router.get("/manifest")
def manifest(request: Request):
    """Манифест публичного контура: состав и правила выдачи.

    Позволяет разработчику сайта проверить интеграцию без чтения документации.
    """
    return public_response(request, {
        "data": {
            "version": "v1",
            "encoding": "UTF-8",
            "read_only": True,
            "content_type": "application/json",
            "endpoints": [
                {"method": "GET", "path": "/api/public/v1/programs",
                 "description": "Публичные программы"},
                {"method": "GET", "path": "/api/public/v1/programs/{id}",
                 "description": "Одна программа (UUID или код)"},
                {"method": "GET", "path": "/api/public/v1/projects",
                 "description": "Публичные проекты; фильтры program, year, status, q"},
                {"method": "GET", "path": "/api/public/v1/projects/{id}",
                 "description": "Публичная карточка проекта (UUID или номер)"},
                {"method": "GET", "path": "/api/public/v1/results",
                 "description": "Публичные результаты; фильтры type, year"},
                {"method": "GET", "path": "/api/public/v1/results/{id}",
                 "description": "Публичная карточка результата (UUID или код)"},
                {"method": "GET", "path": "/api/public/v1/stats",
                 "description": "Счётчики публичных данных"},
                {"method": "GET", "path": "/api/public/v1/manifest",
                 "description": "Манифест публичного контура"},
            ],
            "withheld": [
                "внутренние комментарии", "экспертные заключения", "история согласований",
                "риски", "ресурсные запросы", "персональные контакты", "закрытые файлы",
                "конфиденциальные сведения о партнёрах", "журнал действий",
            ],
            "rules": {
                "404_for_unpublished": "Неопубликованный объект возвращает 404, "
                                       "а не 403: наличие карточки не раскрывается",
                "rate_limit": "Заголовок X-RateLimit-Limit; при превышении — 429",
                "withdrawal": "Снятие с публикации немедленно исключает объект "
                              "из выдачи (FR-34)",
            },
        }
    })


@router.get("/")
def root(request: Request):
    return public_response(request, {
        "data": {
            "name": "Публичный API реестра научных проектов Южного университета (ИУБиП)",
            "version": "v1",
            "manifest": "/api/public/v1/manifest",
            "generated_at": today_iso(),
        }
    })