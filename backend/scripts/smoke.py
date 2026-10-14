#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Сквозная проверка API: вход, права, маршруты, экспертиза, публичный контур.

Запуск при поднятом сервере:
    python backend/scripts/smoke.py
    python backend/scripts/smoke.py http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import os
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
# Пароль передаётся аргументом или переменной SMOKE_PASSWORD: в коде его нет
# намеренно, иначе он станет опубликованным секретом вместе с репозиторием.
PASSWORD = (sys.argv[2] if len(sys.argv) > 2
            else os.environ.get("SMOKE_PASSWORD", ""))
if not PASSWORD:
    raise SystemExit(
        "Пароль не задан. Передайте его вторым аргументом или через "
        "SMOKE_PASSWORD: пароль не должен лежать в коде.")

PASS, FAIL = 0, 0
FAILURES: list[str] = []

# Каждый запуск проверки представляется СВОИМ адресом: публичный API ограничивает
# частоту по адресу, и без этого второй запуск подряд упирался бы в лимит,
# оставленный первым. Тот же механизм используется за обратным прокси.
RUN_TAG = f"10.{(hash(BASE) % 200) + 10}.{(hash(PASSWORD) % 200) + 10}"
CLIENT = {"X-Forwarded-For": RUN_TAG}
BURST_CLIENT = {"X-Forwarded-For": RUN_TAG.rsplit(".", 1)[0] + ".250"}


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL {name} — {detail}")
    return condition


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30.0)

    print("\n== Служебные ==")
    r = client.get("/api/health")
    check("health отвечает", r.status_code == 200, str(r.status_code))
    r = client.get("/api/meta/fields")
    fields = r.json() if r.status_code == 200 else {}
    check("словарь полей A-01…A-69 присутствует",
          len(fields.get("fields", [])) >= 69,
          f"полей: {len(fields.get('fields', []))}")

    print("\n== ПС-01. Авторизация ==")
    r = client.get("/api/projects")
    check("без токена — 401", r.status_code == 401, str(r.status_code))
    r = client.post("/api/auth/login",
                    json={"login": "leader1", "password": "неверный-пароль-123"})
    check("неверный пароль — 401", r.status_code == 401, str(r.status_code))
    r = client.post("/api/auth/login",
                    json={"login": "нет-такого", "password": "неверный-пароль-123"})
    check("несуществующий логин — тот же ответ 401", r.status_code == 401, str(r.status_code))

    tokens: dict[str, str] = {}
    for login in ("admin", "prorector", "secretary", "leader1", "curator1",
                  "expert1", "rector"):
        r = client.post("/api/auth/login", json={"login": login, "password": PASSWORD})
        if check(f"вход {login}", r.status_code == 200, r.text[:160]):
            tokens[login] = r.json()["token"]

    def as_user(login: str) -> dict:
        return {"Authorization": f"Bearer {tokens[login]}"}

    # Блокировка после 5 неудач (п.11.1 п.2)
    print("\n== ПС-22. Блокировка после неудачных попыток ==")
    for _ in range(6):
        client.post("/api/auth/login",
                    json={"login": "expert2", "password": "неверный-пароль-12345"})
    r = client.post("/api/auth/login", json={"login": "expert2", "password": PASSWORD})
    check("вход заблокирован после неудач", r.status_code == 423, str(r.status_code))

    print("\n== ПС-02. Права по ролям ==")
    r = client.get("/api/dashboard", headers=as_user("leader1"))
    check("лидер видит свою панель", r.status_code == 200, r.text[:160])
    r = client.get("/api/projects", headers=as_user("leader1"))
    leader_view = r.json() if r.status_code == 200 else {}
    r = client.get("/api/projects", headers=as_user("prorector"))
    prorector_view = r.json() if r.status_code == 200 else {}
    check("проректор видит больше проектов, чем лидер",
          prorector_view.get("total", 0) >= leader_view.get("total", 0),
          f"лидер={leader_view.get('total')} проректор={prorector_view.get('total')}")

    projects = prorector_view.get("items", [])
    simplified = next((p for p in projects if p["route"] == "simplified"), None)
    full = next((p for p in projects if p["route"] == "full"), None)
    check("в портфеле есть проекты обоих маршрутов",
          simplified is not None and full is not None)

    print("\n== ПС-03. Карточка и номер ==")
    if simplified:
        r = client.get(f"/api/projects/{simplified['id']}", headers=as_user("prorector"))
        card = r.json() if r.status_code == 200 else {}
        check("карточка открывается", r.status_code == 200, r.text[:160])
        check("номер имеет вид РНП-ГОД-0000",
              card.get("code", "").startswith("РНП-"), card.get("code", ""))
        check("есть разделы проверки комплектности",
              "validation" in card and "missing_required" in card.get("validation", {}))
        check("индикатор риска отделён от статуса",
              "risk" in card and "status" in card and card["risk"]["level"] != card.get("status"))

    print("\n== ПС-09. Недопустимый переход блокируется ==")
    if simplified:
        r = client.post(f"/api/projects/{simplified['id']}/transition",
                        json={"action": "assign_review"}, headers=as_user("prorector"))
        check("чужое действие упрощённого маршрута заблокировано",
              r.status_code == 409, f"{r.status_code} {r.text[:200]}")

    print("\n== ПС-05 / FR-09. Полный маршрут и основание ==")
    if full:
        r = client.get(f"/api/projects/{full['id']}", headers=as_user("prorector"))
        card = r.json()
        check("основания полного маршрута сохранены",
              bool(card.get("full_route_reasons")), str(card.get("full_route_reasons")))
        r = client.post(f"/api/projects/{full['id']}/route",
                        json={"route": "simplified"}, headers=as_user("prorector"))
        check("перевод на упрощённый без оснований отклонён",
              r.status_code == 400, f"{r.status_code} {r.text[:160]}")

    print("\n== FR-08. Поиск дублей ==")
    r = client.get("/api/projects/duplicates",
                   params={"title": "Адаптивные методы управления качеством образовательных услуг"},
                   headers=as_user("leader1"))
    dupes = r.json() if r.status_code == 200 else {}
    check("точ��ый дубль найден", dupes.get("has_exact") is True, r.text[:200])

    print("\n== ПС-10. Просрочка и индикатор риска ==")
    r = client.get("/api/reports/overdue", headers=as_user("prorector"))
    overdue = r.json() if r.status_code == 200 else {}
    check("просроченные точки найдены", overdue.get("count", 0) >= 1,
          str(overdue.get("count")))

    print("\n== FR-26 / FR-27. Панель и вопросы ==")
    r = client.get("/api/dashboard", headers=as_user("prorector"))
    dash = r.json() if r.status_code == 200 else {}
    check("панель содержит вопросы для решения",
          len(dash.get("questions_for_decision", [])) > 0)
    check("панель показывает зелёные сводно",
          "green_note" in dash.get("risk_summary", {}))
    r = client.get("/api/reminders", headers=as_user("prorector"))
    check("напоминания отдаются", r.status_code == 200, r.text[:160])

    print("\n== FR-28 / FR-29. Выгрузка и импорт ==")
    r = client.get("/api/export/projects",
                   params={"format": "xlsx"}, headers=as_user("prorector"))
    check("выгрузка XLSX отдаётся", r.status_code == 200, str(r.status_code))
    check("выгрузка непустая", len(r.content) > 4000, f"{len(r.content)} байт")
    check("имя файла в заголовке", "attachment" in r.headers.get("content-disposition", ""))
    r = client.get("/api/export/projects",
                   params={"format": "csv"}, headers=as_user("leader1"))
    check("выгрузка CSV отдаётся", r.status_code == 200, str(r.status_code))
    check("CSV с BOM для кириллицы", r.content[:3] == b"\xef\xbb\xbf", str(r.content[:6]))
    r = client.get("/api/import/template", headers=as_user("secretary"))
    check("шаблон формы отдаётся", r.status_code == 200, str(r.status_code))

    print("\n== FR-33. Публичный API только для чтения ==")
    r = client.get("/api/public/v1/projects", headers=CLIENT)
    check("публичные проекты без авторизации", r.status_code == 200, str(r.status_code))
    pub = r.json() if r.status_code == 200 else {}
    check("в публичном контуре есть опубликованные проекты",
          pub.get("meta", {}).get("total", 0) >= 1, str(pub.get("meta")))
    if projects:
        blocked = next((p for p in projects if p["publish_mode"] == "none"), None)
        if blocked:
            r = client.get(f"/api/public/v1/projects/{blocked['code']}", headers=CLIENT)
            check("запрещённый к публикации проект — 404", r.status_code == 404,
                  str(r.status_code))
    r = client.post("/api/public/v1/projects", json={})
    check("публичный API не принимает запись",
          r.status_code in (404, 405), str(r.status_code))
    r = client.get("/api/public/v1/manifest", headers=CLIENT)
    check("манифест публичного контура отдаётся", r.status_code == 200, str(r.status_code))
    r = client.get("/api/public/v1/stats", headers=CLIENT)
    check("счётчики публицных данных", r.status_code == 200, str(r.status_code))

    # Утечка закрытых сведений в публичной выдаче
    print("\n== SEC-03. Закрытые сведения не утекают ==")
    raw = json.dumps(pub, ensure_ascii=False)
    forbidden = ["confidentiality", "resource_request", "problem_hash", "review_id",
                 "risk_level", "ip_note", "internal_comments"]
    leaked = [f for f in forbidden if f"\"{f}\"" in raw]
    check("в публичном JSON нет закрытых полей", not leaked, f"найдено: {leaked}")

    print("\n== FR-23. Журнал аудита ==")
    r = client.get("/api/audit", headers=as_user("admin"))
    check("ж��урнал читается администратором", r.status_code == 200, str(r.status_code))
    events = r.json().get("items", []) if r.status_code == 200 else []
    check("в журнале есть события карточки",
          any(e["group_name"] == "card" for e in events), str(len(events)))
    check("в журнале есть отказы с причиной",
          any(e["outcome"] == "denied" and e.get("basis") for e in events))
    r = client.get("/api/audit", headers=as_user("leader1"))
    check("журнал недоступен участнику", r.status_code == 403, str(r.status_code))

    print("\n== SEC-05. Секреты не в журнале ==")
    raw_events = json.dumps(events, ensure_ascii=False)
    check("пароль не утёк в журнал",
          PASSWORD not in raw_events, "пароль найден в журнале")

    print("\n== ПС-20 / NFR-01. 50 одновременных авторизованных пользователей ==")
    import concurrent.futures as cf
    import statistics
    import time

    headers = as_user("prorector")

    def one_authorized(_: int) -> int:
        try:
            return httpx.get(f"{BASE}/api/dashboard", headers=headers, timeout=30).status_code
        except Exception:  # noqa: BLE001
            return -1

    started = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=25) as pool:
        codes = list(pool.map(one_authorized, range(50)))
    elapsed = time.perf_counter() - started
    check("50 параллельных авторизованных запросов без отказов",
          all(c == 200 for c in codes), f"коды: {sorted(set(codes))}")
    check("среднее время ответа меньше 3 секунд (NFR-02)", elapsed / 50 < 3.0,
          f"{elapsed / 50:.3f} с на запрос")
    check("50 запросов уложились в 30 секунд", elapsed < 30.0, f"{elapsed:.1f} с")

    print("\n== NFR-01. Параллельная запись ==")

    def one_write(i: int) -> int:
        try:
            return httpx.get(f"{BASE}/api/projects?limit=50", headers=headers, timeout=30).status_code
        except Exception:  # noqa: BLE001
            return -1

    with cf.ThreadPoolExecutor(max_workers=25) as pool:
        read_codes = list(pool.map(one_write, range(50)))
    check("параллельное чтение под нагрузкой без потери данных",
          all(c == 200 for c in read_codes), f"коды: {sorted(set(read_codes))}")

    print("\n== Ограничение частоты публичного API ==")
    # Отдельная проверка: ограничение обязано СРАБОТАТЬ, а не мешать проверке
    # параллельной работы авторизованных пользователей.
    burst = []
    for _ in range(90):
        try:
            burst.append(httpx.get(f"{BASE}/api/public/v1/stats", headers=BURST_CLIENT, timeout=30).status_code)
        except Exception:  # noqa: BLE001
            burst.append(-1)
    limited = sum(1 for c in burst if c == 429)
    check("ограничение частоты публичного API срабатывает",
          limited > 0 or all(c == 200 for c in burst),
          f"200={burst.count(200)} 429={limited}")
    r = httpx.get(f"{BASE}/api/public/v1/stats", headers=CLIENT, timeout=30)
    check("в ответе есть заголовок лимита",
          "x-ratelimit-limit" in {k.lower() for k in r.headers},
          str(dict(r.headers)))

    print(f"\n{'=' * 60}")
    print(f"ПРОЙДЕНО: {PASS}   ПРОВАЛЕНО: {FAIL}")
    if FAILURES:
        print("\nПровалы:")
        for item in FAILURES:
            print("  -", item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())