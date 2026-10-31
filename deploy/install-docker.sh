#!/usr/bin/env bash
# =====================================================================
#  Контейнерная установка реестра на локальную машину (запасной путь).
#
#  Когда нужен: не ставится nginx, порт 8080 занят systemd-вариантом,
#  нет доступа к PyPI для venv или служба systemd недоступна.
#
#  Что делает: собирает образ из архива (интерфейс уже собран), готовит
#  .env с ключом, применяет миграции, создаёт учётные записи, поднимает
#  контейнер на 8080 и проверяет ответ.
#
#  Чего не делает: не останавливает и не пересоздаёт чужие контейнеры,
#  не занимает занятый порт, не печатает пароли в журнал.
#
#  Запуск (от root, из распакованного архива):
#    sudo SEED_PASSWORD='...' SEED_ADMIN_PASSWORD='...' \
#         bash deploy/install-docker.sh
#  Проверка без выполнения: IT_DRY_RUN=1 bash deploy/install-docker.sh
# =====================================================================
set -euo pipefail

SRC="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PORT="${PORT:-8080}"
DRY="${IT_DRY_RUN:-0}"
COMPOSE_FILE="deploy/docker-compose.local.yml"

say()  { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '\n[ОШИБКА] %s\n' "$*" >&2; exit 1; }
do_it() {
  if [ "$DRY" = "1" ]; then
    printf '    [проверка] %s\n' "$*"
  else
    eval "$@"
  fi
}

[ "$DRY" = "1" ] || [ "$(id -u)" -eq 0 ] || fail "нужны права root: sudo bash $0"
[ -f "$SRC/$COMPOSE_FILE" ] || fail "не найден $COMPOSE_FILE в $SRC"
[ -f "$SRC/frontend/dist/index.html" ] || fail "в архиве нет собранного интерфейса"

say "1/7 Проверка Docker"
if [ "$DRY" = "1" ]; then
  say "    режим проверки: наличие Docker не требуется"
  COMPOSE="docker compose"
else
  command -v docker >/dev/null || fail "Docker не установлен"
  if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  else
    fail "нет ни 'docker compose', ни 'docker-compose'"
  fi
  say "    используется: $COMPOSE"
  docker info >/dev/null 2>&1 || fail "движок Docker не отвечает (docker info). Запустите службу docker"
fi

say "2/7 Проверка порта $PORT"
if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  if [ "$DRY" = "1" ]; then
    say "    порт $PORT занят (в проверке это не ошибка)"
  else
    fail "порт $PORT занят. Ничего не меняю. Выберите другой: PORT=8081 sudo bash $0"
  fi
fi

# Старые движки (до 20.10) блокируют системный вызов clone3, а glibc 2.34+
# создаёт через него потоки: приложение падает на старте с «can't start new
# thread». Для них подключается отдельный файл, снимающий фильтр seccomp.
COMPOSE_ARGS="-f $COMPOSE_FILE"
if [ "$DRY" != "1" ]; then
  SERVER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "0.0")
  VERSION_CODE=$(printf '%s' "$SERVER_VERSION" | awk -F. '{printf "%d%03d", $1, $2}')
  if [ "${VERSION_CODE:-0}" -lt 20010 ]; then
    COMPOSE_ARGS="$COMPOSE_ARGS -f deploy/docker-compose.old-engine.yml"
    say "    движок $SERVER_VERSION старше 20.10: подключён обход clone3 (seccomp=unconfined)"
  else
    say "    движок $SERVER_VERSION: обход не нужен"
  fi
fi

cd "$SRC"

say "3/7 Настройки (.env)"
if [ ! -f .env ]; then
  cp .env.example .env
  SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null || true)
  if [ -z "$SECRET" ]; then
    SECRET=$(docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(48))")
  fi
  # В контейнере база и копии лежат в томах, а не в каталогах проекта.
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|" .env
  sed -i "s|^DATABASE_PATH=.*|DATABASE_PATH=/app/data/registry.db|" .env
  sed -i "s|^BACKUP_DIR=.*|BACKUP_DIR=/app/backups|" .env
  say "    .env создан, SECRET_KEY сгенерирован"
else
  say "    .env уже есть — ключ и параметры сохранены"
fi
chmod 600 .env

say "4/7 Сборка образа"
do_it "$COMPOSE $COMPOSE_ARGS build"

say "5/7 Миграции"
do_it "$COMPOSE $COMPOSE_ARGS run --rm --entrypoint python registry -c \
  \"import sys; sys.path.insert(0,'/app/backend'); from app.db import run_migrations; print('миграции:', run_migrations() or 'нет новых')\""

say "6/7 Учётные записи"
if [ -n "${SEED_PASSWORD:-}" ]; then
  SEED_OUT="$SRC/.seed-users-$(date +%Y%m%d-%H%M%S).txt"
  if [ "$DRY" = "1" ]; then
    printf '    [проверка] seed --with-users, вывод в %s\n' "$SEED_OUT"
  else
    $COMPOSE $COMPOSE_ARGS run --rm -T \
      -e SEED_PASSWORD="$SEED_PASSWORD" \
      -e SEED_ADMIN_PASSWORD="${SEED_ADMIN_PASSWORD:-}" \
      --entrypoint python registry backend/scripts/seed.py --with-users \
      > "$SEED_OUT" 2>&1
    chmod 600 "$SEED_OUT"
    say "    логины и пароли: $SEED_OUT (выдать лично, затем удалить)"
  fi
else
  say "    SEED_PASSWORD не задан — учётные записи не создаются"
fi

say "7/7 Запуск и проверка"
do_it "$COMPOSE $COMPOSE_ARGS up -d"
if [ "$DRY" != "1" ]; then
  READY=0
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then READY=1; break; fi
    sleep 2
  done
  [ "$READY" = "1" ] || {
    $COMPOSE $COMPOSE_ARGS logs --tail 40 registry || true
    fail "приложение не ответило на 8080"
  }
  IP=$(hostname -I | awk '{print $1}')
  cat <<EOF

=====================================================================
 Контейнерная установка завершена.
   Приложение:  http://$IP:$PORT/
   Состояние:   $COMPOSE $COMPOSE_ARGS ps
   Журнал:      $COMPOSE $COMPOSE_ARGS logs -f registry
   Копии базы:  docker run --rm -v registry-backups:/b alpine ls /b
=====================================================================
EOF
else
  say "    режим проверки: команды не выполнялись"
fi
