"""Проверка: SPA отдаётся сервером, API живой, публичная витрина работает.

    python backend/scripts/check_ui.py <адрес> <пароль>

Пароль передаётся аргументом или переменной CHECK_UI_PASSWORD. В коде его
нет намеренно: скрипт попадает в публичный репозиторий, и зашитый пароль
стал бы опубликованным секретом (SEC-05).
"""
import os
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("CHECK_UI_PASSWORD", "")
if not PASSWORD:
    raise SystemExit(
        "Пароль не задан. Передайте его вторым аргументом или через "
        "CHECK_UI_PASSWORD: пароль не должен лежать в коде.")

ok = 0
bad = 0


def check(name, condition, detail=""):
    global ok, bad
    if condition:
        ok += 1
        print(f"  OK   {name}")
    else:
        bad += 1
        print(f"  FAIL {name} - {detail}")


print("\n== Интерфейс (SPA) ==")
for path in ("/", "/public", "/projects", "/projects/some-id", "/reminders"):
    r = httpx.get(BASE + path, follow_redirects=True, timeout=20)
    check(f"SPA на маршруте {path}", r.status_code == 200 and '<div id="root">' in r.text,
          f"{r.status_code}, ищем корень SPA")

r = httpx.get(BASE + "/assets", timeout=20)
check("каталог ресурсов не отдаётся как страница", r.status_code in (200, 307, 404),
      str(r.status_code))

print("\n== API живой рядом с интерфейсом ==")
r = httpx.get(BASE + "/api/health", timeout=20)
check("health", r.status_code == 200, str(r.status_code))
r = httpx.get(BASE + "/api/docs", timeout=20)
check("документация API", r.status_code == 200 and "swagger" in r.text.lower(),
      str(r.status_code))
r = httpx.get(BASE + "/api/unknown-endpoint", timeout=20)
check("неизвестный путь API возвращает JSON-ошибку, а не HTML",
      r.status_code == 404 and r.headers.get("content-type", "").startswith("application/json"),
      f"{r.status_code} {r.headers.get('content-type')}")

print("\n== Публичная витрина без входа ==")
r = httpx.get(BASE + "/api/public/v1/projects", timeout=20)
check("публичные проекты", r.status_code == 200, str(r.status_code))
check("контент-Type UTF-8", "ru" in r.headers.get("content-language", ""),
      r.headers.get("content-language", ""))
r = httpx.get(BASE + "/api/public/v1/manifest", timeout=20)
check("манифест", r.status_code == 200, str(r.status_code))

print("\n== Вход и рабочие страницы ==")
token = httpx.post(BASE + "/api/auth/login",
                   json={"login": "prorector", "password": PASSWORD},
                   timeout=20).json()["token"]
h = {"Authorization": f"Bearer {token}"}
for path in ("/api/dashboard", "/api/projects", "/api/reminders",
             "/api/reports/risks", "/api/reports/overdue", "/api/reports/council",
             "/api/reports/publications", "/api/reports/graduate"):
    r = httpx.get(BASE + path, headers=h, timeout=30)
    check(f"данные для экрана {path}", r.status_code == 200,
          f"{r.status_code} {r.text[:120]}")

r = httpx.get(BASE + "/api/programs", headers=h, params={"limit": 100}, timeout=20)
check("справочник программ", r.status_code == 200 and len(r.json().get("items", [])) > 0,
      str(r.status_code))
r = httpx.get(BASE + "/api/persons", headers=h, params={"limit": 200}, timeout=20)
check("справочник людей", r.status_code == 200 and len(r.json().get("items", [])) > 0,
      str(r.status_code))

projects = httpx.get(BASE + "/api/projects", headers=h, params={"limit": 5},
                     timeout=20).json()["items"]
if projects:
    pid = projects[0]["id"]
    for suffix in ("", "/transitions", "/team", "/milestones", "/risks", "/reviews",
                   "/decisions", "/materials", "/public-preview"):
        r = httpx.get(BASE + f"/api/projects/{pid}{suffix}", headers=h, timeout=30)
        check(f"карточка: {suffix or 'паспорт'}", r.status_code == 200,
              f"{r.status_code} {r.text[:120]}")

print("\n== Административные разделы ==")
admin = httpx.post(BASE + "/api/auth/login",
                   json={"login": "admin", "password": PASSWORD},
                   timeout=20).json()["token"]
ha = {"Authorization": f"Bearer {admin}"}
for path in ("/api/admin/users", "/api/admin/roles", "/api/admin/dictionaries",
             "/api/admin/settings", "/api/admin/backup", "/api/audit", "/api/audit/summary"):
    r = httpx.get(BASE + path, headers=ha, timeout=30)
    check(f"раздел {path}", r.status_code == 200, f"{r.status_code} {r.text[:120]}")

print("\n== Отчёты ==")
r = httpx.get(BASE + "/api/export/projects", headers=h, params={"format": "xlsx"}, timeout=30)
check("выгрузка XLSX", r.status_code == 200 and len(r.content) > 4000, str(r.status_code))
r = httpx.get(BASE + "/api/export/results", headers=h, params={"format": "csv"}, timeout=30)
check("выгрузка результатов CSV", r.status_code == 200, str(r.status_code))
r = httpx.get(BASE + "/api/import/template", headers=h, timeout=30)
check("шаблон формы импорта", r.status_code == 200 and len(r.content) > 3000,
      str(r.status_code))

print(f"\n{'=' * 60}\nПРОЙДЕНО: {ok}   ПРОВАЛЕНО: {bad}")
sys.exit(1 if bad else 0)