#!/usr/bin/env bash
# =====================================================================
#  Установка реестра научных проектов на локальную виртуальную машину.
#
#  Что делает: ставит зависимости, создаёт службу systemd и вход через
#  nginx на 8080. Повторный запуск обновляет установку, не теряя базу и
#  .env (ключ сессий и пароли не пересоздаются).
#
#  ЧЕГО НЕ ДЕЛАЕТ (важно на машине, где живут другие системы):
#    * не удаляет и не перезаписывает чужие сайты nginx и чужие службы;
#    * не занимает порт, если он уже занят другой службой — сообщает и
#      останавливается;
#    * не перезапускает nginx, если его конфигурация не проходит проверку.
#
#  Запуск (от root):
#    sudo bash deploy/install-local.sh /путь/к/распакованному/архиву
#  Переменные:
#    PORT=8080            внешний порт
#    SEED_PASSWORD=...    создать пилотные учётные записи с этим паролем
#    APP_DIR=/opt/registry
# =====================================================================
set -euo pipefail

SRC="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APP_DIR="${APP_DIR:-/opt/registry}"
PORT="${PORT:-8080}"
SERVICE=registry
NGINX_SITE=registry-local
BACKUP_DIR="$APP_DIR/backups"

say()  { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '\n[ОШИБКА] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "нужны права root: sudo bash $0 $*"
[ -d "$SRC/backend" ] || fail "не найден каталог backend в $SRC — распакуйте архив и укажите путь к нему"

say "1/9 Проверка системы"
command -v python3 >/dev/null || fail "нет python3"
PY_OK=$(python3 - <<'PY'
import sys
print(1 if sys.version_info >= (3, 11) else 0)
PY
)
[ "$PY_OK" = "1" ] || fail "нужен Python 3.11 или новее, найден $(python3 -V)"

if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  OWNER=$(ss -ltnp 2>/dev/null | grep ":$PORT " | sed -n 's/.*users:((\"\([^\"]*\)\".*/\1/p' | head -1)
  if [ "$OWNER" != "nginx" ]; then
    fail "порт $PORT уже занят службой '$OWNER'. Ничего не меняю: на машине живут другие системы.
Выберите другой порт: PORT=8081 sudo bash $0 $SRC"
  fi
fi

if ss -ltn 2>/dev/null | grep -q ":8000 "; then
  fail "порт 8000 занят. Приложение слушает 127.0.0.1:8000 и не может стартовать.
Освободите порт или измените ExecStart в deploy/systemd/registry.service"
fi

say "2/9 Пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx sqlite3 curl ca-certificates >/dev/null

say "3/9 Пользователь и каталоги"
id -u registry >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin registry
mkdir -p "$APP_DIR" "$APP_DIR/backend/data" "$APP_DIR/backups" "$APP_DIR/storage"

say "4/9 Обновление файлов"
UPDATING=0
if [ -f "$APP_DIR/.env" ] && [ -f "$APP_DIR/backend/data/registry.db" ]; then
  UPDATING=1
  STAMP=$(date +%Y%m%d-%H%M%S)
  mkdir -p "$BACKUP_DIR"
  # Копия базы через sqlite3 .backup: копирование файла .db даёт пустой снимок
  # при WAL, и это уже ловили на этом проекте.
  sqlite3 "$APP_DIR/backend/data/registry.db" ".backup '$BACKUP_DIR/pre-update-$STAMP.db'"
  cp "$APP_DIR/.env" "$BACKUP_DIR/pre-update-$STAMP.env"
  say "    база и .env сохранены в $BACKUP_DIR (pre-update-$STAMP)"
fi

# Каталог данных и .env не перезаписываем: в них состояние установки.
rsync -a --delete \
  --exclude 'backend/data/' --exclude '.env' --exclude '.venv/' \
  --exclude '.git/' --exclude 'node_modules/' --exclude 'backups/' --exclude 'storage/' \
  "$SRC"/ "$APP_DIR"/

say "5/9 Виртуальное окружение и зависимости"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

say "6/9 Настройки (.env)"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  SECRET=$("$APP_DIR/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(48))")
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|" "$APP_DIR/.env"
  say "    SECRET_KEY сгенерирован"
else
  say "    .env уже есть — ключ и параметры сохранены"
fi
chmod 600 "$APP_DIR/.env"
chown -R registry:registry "$APP_DIR"

say "7/9 База: миграции и справочники"
cd "$APP_DIR"
# Окружение не пробрасываем через xargs: в APP_NAME есть пробелы, и такая
# передача разваливала бы переменную на слова. Приложение само читает .env
# из рабочего каталога, поэтому достаточно запустить его от имени registry.
sudo -u registry "$APP_DIR/.venv/bin/python" - <<'PY'
import sys
sys.path.insert(0, "/opt/registry/backend")
from app.db import run_migrations
print("    применены миграции:", run_migrations() or "нет новых")
PY

# Наполнение — только при первой установке: на обновлении seed не должен
# трогать рабочую базу.
if [ "$UPDATING" = "0" ]; then
  sudo -u registry "$APP_DIR/.venv/bin/python" backend/scripts/seed.py
  if [ -n "${SEED_PASSWORD:-}" ]; then
    sudo -u registry env SEED_PASSWORD="$SEED_PASSWORD" \
      "$APP_DIR/.venv/bin/python" backend/scripts/seed.py --with-users
    say "    пилотные учётные записи созданы (пароль из SEED_PASSWORD)"
  else
    say "    справочники загружены; учётные записи не создавались (нужен SEED_PASSWORD)"
  fi
else
  say "    обновление: seed пропущен, данные не тронуты"
fi

say "8/9 Служба systemd"
install -m 644 "$APP_DIR/deploy/systemd/registry.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1 || true
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || {
  journalctl -u "$SERVICE" -n 30 --no-pager || true
  fail "служба не запустилась"
}
curl -fsS http://127.0.0.1:8000/api/health >/dev/null || fail "приложение не отвечает на 127.0.0.1:8000"
say "    служба активна, /api/health отвечает"

say "9/9 Вход через nginx на :$PORT"
install -m 644 "$APP_DIR/deploy/nginx/registry-local.conf" "/etc/nginx/sites-available/$NGINX_SITE.conf"
ln -sfn "/etc/nginx/sites-available/$NGINX_SITE.conf" "/etc/nginx/sites-enabled/$NGINX_SITE.conf"
if ! nginx -t >/tmp/nginx-test.log 2>&1; then
  cat /tmp/nginx-test.log
  rm -f "/etc/nginx/sites-enabled/$NGINX_SITE.conf"
  fail "конфигурация nginx не прошла проверку; наш сайт отключён, чужие не тронуты"
fi
systemctl enable nginx >/dev/null 2>&1 || true
systemctl reload nginx
sleep 1
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null || fail "через nginx на :$PORT приложение не отвечает"

IP=$(hostname -I | awk '{print $1}')
cat <<EOF

=====================================================================
 Установка завершена.
   Приложение:  http://$IP:$PORT/
   Служба:      systemctl status $SERVICE
   Журнал:      journalctl -u $SERVICE -f
   База:        $APP_DIR/backend/data/registry.db
   Настройки:   $APP_DIR/.env  (права 600)
   Копии базы:  $BACKUP_DIR
 Проверки:
   curl -fsS http://127.0.0.1:8000/api/health
   sudo -u registry $APP_DIR/.venv/bin/python backend/scripts/smoke.py
=====================================================================
EOF
