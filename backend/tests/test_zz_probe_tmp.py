# -*- coding: utf-8 -*-
"""Временная проверка. Удалить после отладки."""


def test_probe(api, project, users):
    card = api.get(f"/api/projects/{project['id']}", login="leader1").json()
    print("MISSING:", card["validation"]["missing_required"])
    print("program_id in project:", project["program_id"])
    print("leader:", project["leader_person_id"])
    print("team:", card["counts"]["team"], "milestones:", card["counts"]["milestones"])
    r = api.post(f"/api/projects/{project['id']}/transition", login="leader1",
                 json={"action": "submit"})
    print("SUBMIT:", r.status_code, r.json())
    print("DB program_id:", __import__("app.db", fromlist=["query_one"]).query_one(
        "SELECT program_id, leader_person_id FROM projects WHERE id = ?", (project["id"],))["program_id"])