# -*- coding: utf-8 -*-
"""Временная проверка фикстур. Удалить после отладки."""
from app.db import query, scalar


def test_harness(api, project, users):
    token = api.login("leader1")
    assert token
    r = api.get("/api/projects", login="leader1")
    assert r.status_code == 200, r.text
    body = r.json()
    print(body["total"], [i["code"] for i in body["items"]])
    assert body["total"] >= 1
    assert project["code"].startswith("РНП-")


def test_raw_client_isolated(raw_client):
    r = raw_client.get("/api/health")
    assert r.status_code == 200
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == 0