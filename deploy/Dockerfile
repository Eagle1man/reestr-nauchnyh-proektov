# Образ приложения «Реестр научных проектов Южного университета (ИУБиП)».
#
# Интерфейс собирается на этапе сборки и копируется в образ, поэтому
# контейнер отдаёт и закрытую зону, и публичную витрину сам.

# ---------- Этап 1: сборка интерфейса ----------
FROM node:20-alpine AS frontend

WORKDIR /build

# Сначала манифесты: слой зависимостей переиспользуется при правке кода.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ---------- Этап 2: приложение ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Moscow

# tzdata обязателен: без него Python не знает зону Europe/Moscow, а время
# в интерфейсе и в журнале должно быть московским (п.10.2 п.2).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl \
 && rm -rf /var/lib/apt/lists/*

# Приложение работает не от root: каталоги данных и копий принадлежат
# непривилегированному пользователю.
RUN useradd --system --create-home --uid 10001 registry \
 && mkdir -p /app/data /app/backups /app/storage \
 && chown -R registry:registry /app

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ /app/backend/
COPY .env.example /app/.env.example
COPY --from=frontend /build/dist /app/frontend/dist

RUN chown -R registry:registry /app

USER registry

ENV DATABASE_PATH=/app/data/registry.db \
    BACKUP_DIR=/app/backups

EXPOSE 8000

# Проверка живости совпадает с healthcheck в docker-compose.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# --proxy-headers нужен, чтобы приложение видело реальный адрес клиента за
# обратным прокси: от него зависит ограничение частоты запросов.
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--app-dir", "/app/backend", \
     "--proxy-headers", "--forwarded-allow-ips", "*", \
     "--no-server-header"]