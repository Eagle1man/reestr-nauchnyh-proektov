# -*- coding: utf-8 -*-
"""Безопасность учётных записей — п.11.1 ТЗ, SEC-05, SEC-07.

  1. пароль не менее 12 символов;
  2. после пяти последовательных неудачных попыток вход блокируется на 15 минут;
  3. сессия завершается после 60 минут бездействия;
  4. восстановление доступа выполняет администратор.

SEC-05: пароли, ключи и токены не хранятся открыто и не попадают в журналы.
SEC-07: усиленная защита учётных записей администраторов.

В тестах нет и не может быть живых паролей: используется пароль, который
существует только в изолированной временной базе (фикстура `password`).
"""

from __future__ import annotations

import json
from datetime import timedelta


from app import security
from app.config import settings
from app.db import execute, query, query_one, scalar
from app.security import (
    PBKDF2_ROUNDS, SALT_BYTES, failed_count, generate_password, hash_password,
    ip_lock_remaining, lockout_remaining, password_problems, purge_expired_sessions,
    verify_password,
)
from app.utils import now_iso, now_msk

from conftest import PBKDF2_ROUNDS_REQUIRED, PBKDF2_ROUNDS_TESTS


# ===========================================================================
#  П.11.1 п.1 — требования к паролю
# ===========================================================================

def test_password_minimum_length_is_twelve_characters():
    """П.11.1 п.1: «пароль не менее 12 символов»."""
    assert settings.password_min_length == 12
    assert any("12 символов" in problem for problem in
               password_problems("Коротк1!"))
    assert any("короче 12" in problem for problem in
               password_problems("Ab1!xy"))          # 6 символов
    assert password_problems("Ab1!xy")               # ровно 6


def test_password_requires_all_character_classes():
    """П.11.1 п.1 плюс базовая стойкость: строчные, прописные, цифры и
    специальные символы."""
    long_enough = "Proverka2026"                     # 12 символов
    assert password_problems(long_enough)            # нет спецсимвола

    assert password_problems("proverka-2026-test")           # нет прописных
    assert password_problems("PROVERKA-2026-TEST")           # нет строчных
    assert password_problems("ProverkaTestovyi")            # нет цифр
    assert password_problems("Proverka2026Test")            # нет спецсимвола


def test_strong_password_has_no_problems():
    """Надёжный пароль требований не нарушает."""
    assert password_problems("Proverka-2026-Testovyi!") == []


def test_generated_password_satisfies_requirements():
    """Выдаваемый пароль всегда удовлетворяет требованиям (SEC-07)."""
    for _ in range(5):
        candidate = generate_password()
        assert password_problems(candidate) == []
        assert len(candidate) >= settings.password_min_length


def test_admin_cannot_create_account_with_weak_password(api, users):
    """П.11.1 п.1 применяется и к учётным записям, которые создаёт администратор."""
    response = api.post("/api/admin/users", login="admin",
                        json={"login": "slabiy", "full_name": "Слабый пароль",
                              "password": "123456"})
    assert response.status_code == 400
    assert response.json()["detail"]["problems"]
    assert scalar("SELECT COUNT(*) FROM users WHERE login = 'slabiy'", (), 0) == 0


def test_user_cannot_change_password_to_weak_one(api, users, password):
    """Смена пароля на слабый отклоняется с перечнем проблем."""
    response = api.post("/api/auth/password", login="leader1",
                        json={"current_password": password, "new_password": "kolonok"})
    assert response.status_code == 400
    assert response.json()["detail"]["problems"]


def test_change_password_requires_correct_current_one(api, users, password):
    """Смена пароля требует верного текущего пароля (п.11.1)."""
    wrong = api.post("/api/auth/password", login="leader1",
                     json={"current_password": "неверный-пароль",
                           "new_password": "Novye-Parol-2026!"})
    assert wrong.status_code == 400

    ok = api.post("/api/auth/password", login="leader1",
                  json={"current_password": password,
                        "new_password": "Novye-Parol-2026!"})
    assert ok.status_code == 200
    stored = query_one("SELECT password_hash FROM users WHERE login = 'leader1'")
    assert verify_password("Novye-Parol-2026!", stored["password_hash"])
    assert scalar("SELECT must_reset FROM users WHERE login = 'leader1'") == 0


# ===========================================================================
#  PBKDF2 и хранение пароля (SEC-05)
# ===========================================================================

def test_password_hash_is_pbkdf2_sha256_with_required_rounds(real_pbkdf2):
    """SEC-05: пароль хранится только в виде PBKDF2-HMAC-SHA256 с 260 000
    раундов; открытый пароль в базе отсутствует."""
    assert real_pbkdf2 == 260_000
    assert SALT_BYTES == 16

    stored = hash_password("Proverka-2026-Testovyi!")
    algorithm, rounds, salt_hex, digest_hex = stored.split("$")
    assert algorithm == "pbkdf2_sha256"
    assert int(rounds) == real_pbkdf2
    assert len(bytes.fromhex(salt_hex)) == SALT_BYTES
    assert len(bytes.fromhex(digest_hex)) == 32          # SHA-256
    assert "Proverka-2026-Testovyi!" not in stored


def test_hash_uses_salt_so_equal_passwords_differ(real_pbkdf2):
    """Одинаковые пароли дают разные хеши благодаря случайной соли."""
    first = hash_password("Proverka-2026-Testovyi!")
    second = hash_password("Proverka-2026-Testovyi!")
    assert first != second
    assert first.split("$")[2] != second.split("$")[2]
    assert verify_password("Proverka-2026-Testovyi!", first)
    assert verify_password("Proverka-2026-Testovyi!", second)


def test_verify_password_rejects_wrong_and_malformed_hashes():
    """Проверка пароля не проходит при неверном пароле и при испорченном хеше."""
    stored = hash_password("Proverka-2026-Testovyi!")
    assert verify_password("Proverka-2026-Testovyi!", stored)
    assert not verify_password("Proverka-2026-Testovyi", stored)   # без "!"

    assert not verify_password("любой", None)
    assert not verify_password("любой", "")
    assert not verify_password("любой", "мусор")
    assert not verify_password("любой", "pbkdf2_sha256$260000$не-hex")
    assert not verify_password("любой", "md5$1$aa$bb")             # чужой алгоритм


def test_plaintext_password_never_leaves_the_system(api, users, password):
    """SEC-05: пароль в открытом виде не возвращается из API и не попадает
    в журнал аудита."""
    created = api.post("/api/admin/users", login="admin",
                       json={"login": "novichok", "full_name": "Новый сотрудник",
                             "password": password, "roles": ["secretary"]})
    assert created.status_code == 201
    issued = created.json()["initial_password"]
    assert issued == password          # заданный пароль возвращается один раз
    # В ответе о создании пароль показывается один раз; при чтении — никогда.
    assert "initial_password" not in json.dumps(
        api.get("/api/admin/users", login="admin").json(), ensure_ascii=False)
    assert "password" not in api.get(f"/api/auth/me", login="novichok").json()["user"]

    events = json.dumps([dict(r) for r in query("SELECT * FROM audit_events")],
                        ensure_ascii=False)
    assert password not in events
    assert issued not in events
    assert "pbkdf2" not in events


def test_session_tokens_are_not_exposed_in_admin_list(api, users, password):
    """SEC-05: токены сессий наружу не отдаются — даже администратору."""
    api.login("leader1")
    sessions = api.get("/api/admin/maintenance/sessions", login="admin").json()
    assert sessions["count"] >= 1
    for item in sessions["items"]:
        assert item["token"].endswith("…")
        assert len(item["token"]) <= 9
    assert api.tokens["leader1"] not in json.dumps(sessions, ensure_ascii=False)
    assert "pbkdf2" not in json.dumps(sessions, ensure_ascii=False)


# ===========================================================================
#  П.11.1 п.2 — блокировка после пяти неудачных попыток
# ===========================================================================

def test_five_failed_attempts_lock_the_account_for_fifteen_minutes(raw_client, users,
                                                                 password):
    """П.11.1 п.2: «после пяти последовательных неудачных попыток вход
    блокируется на 15 минут»."""
    for attempt in range(4):
        response = raw_client.post("/api/auth/login",
                                   json={"login": "leader2",
                                         "password": "неверный-пароль-123"})
        assert response.status_code == 401, f"попытка {attempt + 1} ещё не блокирует"

    fifth = raw_client.post("/api/auth/login",
                            json={"login": "leader2", "password": "неверный-пароль-123"})
    assert fifth.status_code == 401
    assert failed_count("leader2") == 5
    assert lockout_remaining("leader2") > 0

    blocked = raw_client.post("/api/auth/login",
                              json={"login": "leader2", "password": password})
    assert blocked.status_code == 423
    assert "15 мин" in blocked.json()["detail"]
    assert "п.11.1" in blocked.json()["detail"]


def test_lockout_expires_after_fifteen_minutes(raw_client, users, password):
    """Через 15 минут блокировка снимается — иначе это отказ в обслуживании."""
    for _ in range(5):
        raw_client.post("/api/auth/login",
                        json={"login": "expert2", "password": "неверный-пароль-123"})
    assert lockout_remaining("expert2") > 0

    past = (now_msk() - timedelta(minutes=settings.login_lock_minutes + 1)).isoformat(
        timespec="seconds")
    execute("UPDATE login_attempts SET attempted_at = ? WHERE login = 'expert2'",
            (past,))
    assert lockout_remaining("expert2") == 0

    response = raw_client.post("/api/auth/login",
                               json={"login": "expert2", "password": password})
    assert response.status_code == 200


def test_successful_login_resets_the_failure_counter(raw_client, users, password):
    """Успешный вход обнуляет счётчик неудач для этой учётной записи."""
    raw_client.post("/api/auth/login",
                    json={"login": "expert1", "password": "неверный-пароль-1"})
    raw_client.post("/api/auth/login",
                    json={"login": "expert1", "password": "неверный-пароль-2"})
    assert failed_count("expert1") == 2

    assert raw_client.post("/api/auth/login",
                           json={"login": "expert1", "password": password}).status_code == 200
    assert failed_count("expert1") == 0
    assert lockout_remaining("expert1") == 0


def test_unknown_login_is_not_a_lockout_vector(raw_client, users, password):
    """Блокировка применяется только к существующей учётной записи: иначе любой
    посторонний мог бы «заблокировать» чужой логин (SEC-04, отказ в
    обслуживании)."""
    assert lockout_remaining("нет-такого-логина") == 0
    for _ in range(6):
        response = raw_client.post("/api/auth/login",
                                   json={"login": "нет-такого-логина",
                                         "password": "любой-пароль"})
        assert response.status_code == 401      # не 423

    # Настоящий сотрудник от этого не пострадал.
    assert raw_client.post("/api/auth/login",
                           json={"login": "leader1", "password": password}).status_code == 200


def test_ip_rate_limit_is_separate_and_higher(raw_client, users, password):
    """Ограничение по адресу (защита от подбора логинов) выше порога учётной
    записи и не блокирует сотрудника."""
    assert settings.login_ip_max_attempts > settings.login_max_attempts
    for _ in range(5):
        raw_client.post("/api/auth/login",
                        json={"login": "leader1", "password": "неверный-пароль-1"})
    assert lockout_remaining("leader1") > 0          # учётная запись заблокирована
    assert ip_lock_remaining("testclient") == 0      # адрес ещё не исчерпан
    response = raw_client.post("/api/auth/login",
                               json={"login": "outsider", "password": password})
    assert response.status_code == 200


def test_ip_limit_engages_after_many_failures(raw_client):
    """После серии неудачных попыток с одного адреса включается 429 (SEC-04)."""
    assert ip_lock_remaining("testclient") == 0
    statuses = []
    for _ in range(settings.login_ip_max_attempts + 1):
        response = raw_client.post("/api/auth/login",
                                   json={"login": f"жертва-{_}", "password": "пароль"})
        statuses.append(response.status_code)
    assert 429 in statuses, statuses
    assert ip_lock_remaining("testclient") > 0


# ===========================================================================
#  П.11.1 п.3 — сессия завершается после 60 минут бездействия
# ===========================================================================

def test_session_ends_after_sixty_minutes_without_activity(api, users, password):
    """П.11.1 п.3: «сессия завершается после 60 минут бездействия»."""
    assert settings.session_idle_minutes == 60
    token = api.login("leader1")
    assert api.get("/api/auth/me", login="leader1").status_code == 200

    stale = (now_msk() - timedelta(minutes=settings.session_idle_minutes + 1)).isoformat(
        timespec="seconds")
    execute("UPDATE sessions SET last_seen_at = ? WHERE token = ?", (stale, token))

    response = api.client.get("/api/auth/me",
                              headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "истекла" in response.json()["detail"]
    assert "60 минут" in response.json()["detail"]


def test_activity_refreshes_session_and_survives_under_limit(api, users):
    """Активность продлевает сессию: 30 минут idle, затем обращение — и снова
    можно работать."""
    api.login("leader1")
    token = api.tokens["leader1"]
    recent = (now_msk() - timedelta(minutes=30)).isoformat(timespec="seconds")
    execute("UPDATE sessions SET last_seen_at = ? WHERE token = ?", (recent, token))

    first = api.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert first.status_code == 200

    refreshed = query_one("SELECT last_seen_at FROM sessions WHERE token = ?", (token,))
    assert refreshed["last_seen_at"] > recent


def test_expired_session_row_is_removed(api, users):
    """Истёкшая сессия удаляется, а не просто игнорируется."""
    api.login("leader1")
    token = api.tokens["leader1"]
    stale = (now_msk() - timedelta(hours=5)).isoformat(timespec="seconds")
    execute("UPDATE sessions SET last_seen_at = ? WHERE token = ?", (stale, token))
    api.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert query_one("SELECT token FROM sessions WHERE token = ?", (token,)) is None


def test_absolute_session_expiry_is_enforced(api, users):
    """Сессия умирает и по абсолютному сроку, даже если её «подпирали»
    обращениями."""
    api.login("leader1")
    token = api.tokens["leader1"]
    execute("UPDATE sessions SET expires_at = ? WHERE token = ?",
            ((now_msk() - timedelta(minutes=1)).isoformat(timespec="seconds"), token))
    response = api.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_logout_invalidates_the_session(api, users):
    """Выход закрывает сессию немедленно."""
    api.login("leader1")
    assert api.post("/api/auth/logout", login="leader1").json() == {"ok": True}
    response = api.get("/api/auth/me", login="leader1")
    assert response.status_code == 401


def test_purge_expired_sessions_removes_stale_rows(api, users):
    """Уборка истёкших сессий при старте (lifespan) — рабочая."""
    api.login("leader1")
    token = api.tokens["leader1"]
    stale = (now_msk() - timedelta(hours=3)).isoformat(timespec="seconds")
    execute("UPDATE sessions SET last_seen_at = ? WHERE token = ?", (stale, token))
    removed = purge_expired_sessions()
    assert removed >= 1
    assert query_one("SELECT token FROM sessions WHERE token = ?", (token,)) is None


def test_forged_and_malformed_tokens_are_refused(api, users):
    """Поддельный или испорченный токен не даёт доступа (SEC-04)."""
    for header in ("Bearer forged-token", "forged-token",
                   "Basic abcdef", "Bearer "):
        response = api.client.get("/api/auth/me", headers={"Authorization": header})
        assert response.status_code == 401, header


def test_agent_key_header_does_not_grant_session_access(api):
    """Служебный заголовок X-Agent-Key не выдаёт сессию рабочей зоны."""
    response = api.client.get("/api/projects", headers={"X-Agent-Key": "any-service-key"})
    assert response.status_code == 401


# ===========================================================================
#  П.11.1 п.4 — восстановление доступа и отключение учётной записи
# ===========================================================================

def test_admin_reset_password_closes_all_sessions(api, password, users):
    """П.11.1 п.4: сброс пароля администратором закрывает все сессии, новый
    пароль показывается один раз."""
    api.login("leader1")
    assert scalar("SELECT COUNT(*) FROM sessions WHERE user_id = ?",
                  (users["leader1"].id,), 0) >= 1

    reset = api.post(f"/api/admin/users/{users['leader1'].id}/reset-password",
                     login="admin")
    assert reset.status_code == 200
    issued = reset.json()["initial_password"]
    assert password_problems(issued) == []
    assert scalar("SELECT COUNT(*) FROM sessions WHERE user_id = ?",
                  (users["leader1"].id,), 0) == 0
    assert scalar("SELECT must_reset FROM users WHERE id = ?",
                  (users["leader1"].id,)) == 1

    # Старый пароль больше не работает, новый — работает.
    assert raw_login(api, "leader1", password).status_code == 401
    assert raw_login(api, "leader1", issued).status_code == 200


def test_admin_can_disable_account_without_losing_data(api, users, project):
    """SEC-07 + ПС-22: отключение учётной записи закрывает доступ, но данные
    и история сохраняются."""
    api.login("leader2")
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) >= 1
    projects_before = scalar("SELECT COUNT(*) FROM projects", (), 0)
    events_before = scalar("SELECT COUNT(*) FROM audit_events", (), 0)

    disabled = api.patch(f"/api/admin/users/{users['leader2'].id}", login="admin",
                         params={"is_active": False})
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert scalar("SELECT COUNT(*) FROM sessions WHERE user_id = ?",
                  (users["leader2"].id,), 0) == 0

    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == projects_before
    assert scalar("SELECT COUNT(*) FROM audit_events", (), 0) > events_before
    assert scalar("SELECT archived_at FROM users WHERE id = ?",
                  (users["leader2"].id,)) is None
    # Событие о блокировке зафиксировано (п.11.3).
    event = query_one("SELECT * FROM audit_events WHERE action = 'Блокировка "
                      "учётной записи' ORDER BY happened_at DESC LIMIT 1")
    assert event is not None and event["basis"]


def test_disabled_account_cannot_log_in(raw_client, users, password):
    """Отключённая учётная запись не входит в систему."""
    execute("UPDATE users SET is_active = 0 WHERE id = ?", (users["outsider"].id,))
    response = raw_client.post("/api/auth/login",
                               json={"login": "outsider", "password": password})
    assert response.status_code == 403
    assert "отключена" in response.json()["detail"]


def test_admin_section_is_closed_to_regular_users(api, users):
    """SEC-07: административный раздел недоступен обычному сотруднику."""
    for path in ("/api/admin/users", "/api/admin/roles", "/api/admin/settings",
                 "/api/admin/backup", "/api/admin/dictionaries"):
        assert api.get(path, login="leader1").status_code == 403, path
        assert api.get(path, login="secretary").status_code == 403, path
    assert api.get("/api/admin/users", login="admin").status_code == 200


def test_password_change_and_role_change_are_logged(api, users, password):
    """П.11.3: изменения учётных записей фиксируются в журнале."""
    api.post("/api/auth/password", login="leader1",
             json={"current_password": password, "new_password": "Drugoy-Parol-2026!"})
    api.put(f"/api/admin/users/{users['leader2'].id}/roles", login="admin",
            json=["secretary"])
    events = [dict(r) for r in query(
        "SELECT * FROM audit_events WHERE group_name = 'auth'")]
    actions = {e["action"] for e in events}
    assert any("ролей и прав" in a for a in actions)
    change = query_one("SELECT * FROM audit_events WHERE action = 'Смена пароля'"
                       " ORDER BY happened_at DESC LIMIT 1")
    assert change is not None and change["user_login"] == "leader1"


# ===========================================================================
#  SEC-05 — секретов нет в журнале и в ответах ошибок
# ===========================================================================

def test_failed_login_event_contains_no_password(raw_client):
    """Неудачный вход пишется в журнал без пароля (SEC-05)."""
    raw_client.post("/api/auth/login",
                    json={"login": "outsider", "password": "Очень-Секретный-Пароль-1!"})
    event = query_one("SELECT * FROM audit_events WHERE action = 'Неудачный вход'"
                      " ORDER BY happened_at DESC LIMIT 1")
    assert event is not None
    assert event["outcome"] == "denied"
    assert event["basis"]
    blob = json.dumps(dict(event), ensure_ascii=False)
    assert "Очень-Секретный-Пароль-1!" not in blob
    assert "pbkdf2" not in blob


def test_successful_login_event_contains_no_token(api, users, password):
    """Успешный вход пишется в журнал без токена (SEC-05)."""
    token = api.login("leader1")
    event = query_one("SELECT * FROM audit_events WHERE action = 'Успешный вход'"
                      " ORDER BY happened_at DESC LIMIT 1")
    assert event is not None
    blob = json.dumps(dict(event), ensure_ascii=False)
    assert token not in blob
    assert password not in blob
    assert event["user_login"] == "leader1"


def test_secret_key_is_not_leaked_by_config_endpoint(api, users):
    """SECRET_KEY не попадает в ответы служебных методов."""
    payload = json.dumps(api.get("/api/admin/settings", login="admin").json(),
                        ensure_ascii=False)
    if settings.secret_key:
        assert settings.secret_key not in payload
    for key in ("secret_key", "SECRET_KEY"):
        assert key not in payload


def test_health_endpoint_does_not_disclose_paths(api):
    """Служебный метод не раскрывает путей и версий внутренних компонентов."""
    body = api.client.get("/api/health").json()
    assert body["status"] == "ok"
    assert set(body) == {"status", "app", "version"}
    raw = json.dumps(body, ensure_ascii=False)
    assert "sqlite" not in raw.lower()
    assert "\\" not in raw and "/" not in raw


def raw_login(api, login: str, password: str):
    """Вход без кеширования токена — чтобы проверить конкретный пароль."""
    api.tokens.pop(login, None)
    return api.client.post("/api/auth/login",
                           json={"login": login, "password": password})