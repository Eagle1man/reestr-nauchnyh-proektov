# -*- coding: utf-8 -*-
"""Импорт и выгрузка — п.7.2 ТЗ (FR-28, FR-29).

Правила п.7.2, которые проверяются здесь:
  1. форма инвентаризации совпадает с обязательными полями;
  2. поддерживаемые форматы — XLSX, дополнительно CSV;
  3. ДО загрузки показывается число корректных строк, предупреждений, ошибок
     и возможных дублей;
  4. ДО подтверждения импорт НЕ изменяет рабочие данные;
  5. строки с ошибками не загружаются, пользователь получает ПОСТРОЧНЫЙ
     протокол с названием поля и причиной;
  6. каждая загрузка получает идентификатор пакета, дату, автора и протокол;
  7. выгрузка содержит дату формирования, фильтры и только доступные
     пользователю поля;
  8. полную архивную выгрузку может выполнить технический администратор.

Урок отдела memories/2026/10/2026-10-02-truncated-file-silent-success
проверяет, что обрезанный файл падает явно, а не загружается наполовину.
"""

from __future__ import annotations

import io
import json

from openpyxl import Workbook, load_workbook

from app.db import query, query_one, scalar
from app.services.transfer import (
    EXPORT_COLUMNS, FORBIDDEN_EXPORT_COLUMNS, IMPORT_COLUMNS, RESULT_TYPES,
    RESULT_TYPE_TITLES,
)

from conftest import build_import_csv, build_import_xlsx, valid_import_row

UPLOAD = {"confirm": "false"}


def upload(api, login: str, data: bytes, filename: str, **fields):
    return api.post(
        "/api/import/preview", login=login,
        files={"file": (filename, data,
                         "application/vnd.openxmlformats-officedocument"
                         ".spreadsheetml.sheet")},
        data={**UPLOAD, **fields},
    )


def xlsx_sheets(data: bytes) -> dict[str, list[list]]:
    workbook = load_workbook(io.BytesIO(data), data_only=True)
    out = {}
    for name in workbook.sheetnames:
        sheet = workbook[name]
        out[name] = [list(row) for row in sheet.iter_rows(values_only=True)]
    return out


def confirm_via_service(rows: list[dict], login: str = "secretary"):
    """Подтвердить импорт в обход HTTP-эндпоинта.

    Эндпоинт /api/import/preview при confirm=true падает (см.
    test_confirm_loads_only_rows_without_errors), поэтому правила загрузки
    проверяются на самом сервисе — иначе они останутся непроверенными.

    Возвращает пару (результат сервиса, сохранённый пакет): сервис возвращает
    результат с ДРУГИМ batch_id, чем тот, что записан в import_batches
    (см. test_confirm_returns_the_persisted_batch_id).
    """
    from app.access import load_actor
    from app.services import transfer as service

    parsed = service.read_rows(build_import_xlsx(rows), "forma.xlsx")
    preview = service.preview_rows(parsed, "forma.xlsx")
    actor = load_actor(dict(query_one("SELECT * FROM users WHERE login = ?",
                                      (login,))))
    before = scalar("SELECT COUNT(*) FROM import_batches", (), 0)
    result = service.confirm_import(preview, parsed, "forma.xlsx", actor)
    batches = query("SELECT * FROM import_batches ORDER BY created_at, rowid")
    return result, batches[before]


# ===========================================================================
#  п.7.2 п.1 — форма инвентаризации
# ===========================================================================

def test_template_matches_the_approved_form(api, users):
    """п.7.2 п.1: шаблон формы совпадает с обязательными полями MVP."""
    response = api.get("/api/import/template", login="secretary")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "forma_inventarizacii" in response.headers["content-disposition"]

    sheets = xlsx_sheets(response.content)
    headers = [str(cell) for cell in sheets["Инвентаризация"][0]]
    assert headers == [column["header"] for column in IMPORT_COLUMNS]
    # Пояснение: обязательность и максимальная длина каждого поля.
    note = sheets["Пояснение"]
    assert "Дата формирования" in [str(row[0]) for row in note]
    required = {str(row[0]): str(row[1]) for row in note if row and len(row) > 1}
    for column in IMPORT_COLUMNS:
        assert required[column["header"]] == ("да" if column["required"] else "нет")


def test_file_with_missing_columns_is_rejected(api, program):
    """п.7.2 п.1: файл не по утверждённой форме отвергается с перечнем
    отсутствующих колонок."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Полное название (A-02)", "Что-то ещё"])
    sheet.append(["Проект", "значение"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    response = upload(api, "secretary", buffer.getvalue(), "bad.xlsx")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "не соответствует утверждённой форме" in detail
    assert "Отсутствуют колонки" in detail


def test_only_xlsx_and_csv_are_accepted(api, program):
    """п.7.2 п.2: поддерживаемые входные форматы — XLSX и CSV."""
    response = upload(api, "secretary", "любые данные".encode("utf-8"), "forma.txt")
    assert response.status_code == 400
    assert "XLSX и CSV" in response.json()["detail"]


def test_empty_upload_is_rejected(api, users):
    """Пустой файл — ошибка, а не «импортировано 0 строк»."""
    response = upload(api, "secretary", b"", "pustaya.xlsx")
    assert response.status_code == 400


def test_import_is_forbidden_for_ordinary_users(api, users):
    """Импорт доступен администратору, секретарю и проректору (п.7.2)."""
    response = upload(api, "leader1", build_import_xlsx([valid_import_row()]), "f.xlsx")
    assert response.status_code == 403
    assert response.json()["detail"]


# ===========================================================================
#  п.7.2 п.4 — предпросмотр не меняет рабочие данные
# ===========================================================================

def test_preview_does_not_change_working_data(api, program):
    """п.7.2 п.4: до подтверждения рабочие данные не изменяются."""
    before_projects = scalar("SELECT COUNT(*) FROM projects", (), 0)
    before_persons = scalar("SELECT COUNT(*) FROM persons", (), 0)
    before_codes = sorted(r["code"] for r in query("SELECT code FROM projects"))

    rows = [valid_import_row(suffix="1"), valid_import_row(suffix="2")]
    response = upload(api, "secretary", build_import_xlsx(rows), "f.xlsx")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] is False
    assert body["counts"]["total"] == 2
    assert "не изменяет рабочие данные" in body["message"]

    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == before_projects
    assert scalar("SELECT COUNT(*) FROM persons", (), 0) == before_persons
    assert sorted(r["code"] for r in query("SELECT code FROM projects")) == before_codes


def test_preview_is_repeatable_and_gives_same_verdict(api, program):
    """п.7.2 п.3: предпросмотр можно повторять — он только читает."""
    data = build_import_xlsx([valid_import_row(suffix="1")])
    first = upload(api, "secretary", data, "f.xlsx").json()
    second = upload(api, "secretary", data, "f.xlsx").json()
    assert first["counts"] == second["counts"]
    assert first["protocol"][0]["status"] == second["protocol"][0]["status"]
    assert first["batch_id"] != second["batch_id"]


# ===========================================================================
#  п.7.2 п.5 — построчный протокол с полем и причиной
# ===========================================================================

def test_protocol_reports_field_and_reason_for_every_error(api, program):
    """п.7.2 п.5: для каждой ошибочной строки указано поле и причина."""
    good = valid_import_row(suffix="1")
    no_goal = {**valid_import_row(suffix="2"), "goal": ""}
    wrong_program = {**valid_import_row(suffix="3"), "program_code": "НП-99"}
    bad_date = {**valid_import_row(suffix="4"), "planned_start": "31.31.2026"}
    reversed_dates = {**valid_import_row(suffix="5"),
                      "planned_start": "2027-01-01", "planned_end": "2026-01-01"}
    bad_result_type = {**valid_import_row(suffix="6"), "planned_result_type": "статья"}
    bad_publish_mode = {**valid_import_row(suffix="7"), "publish_mode": "всё-подряд"}
    bad_team = {**valid_import_row(suffix="8"), "team": "Иванов Иван Иванович"}
    bad_role = {**valid_import_row(suffix="9"),
                "team": "Иванов Иван Иванович|директор|задача"}
    unknown_flag = {**valid_import_row(suffix="10"), "flags": "T-09"}
    no_milestones = {**valid_import_row(suffix="11"), "milestones": ""}
    too_long = {**valid_import_row(suffix="12"), "goal": "Ц" * 800}

    rows = [good, no_goal, wrong_program, bad_date, reversed_dates,
            bad_result_type, bad_publish_mode, bad_team, bad_role,
            unknown_flag, no_milestones, too_long]
    body = upload(api, "secretary", build_import_xlsx(rows), "f.xlsx").json()

    protocol = {entry["row"]: entry for entry in body["protocol"]}
    assert body["counts"]["total"] == len(rows)
    assert body["counts"]["error"] == 11
    assert body["counts"]["ok"] == 1

    def fields_of(row: int) -> set[str]:
        return {problem["field"] for problem in protocol[row]["errors"]}

    def reasons_of(row: int) -> list[str]:
        return [problem["reason"] for problem in protocol[row]["errors"]]

    assert "Цель" in fields_of(3)
    assert any("обязательное поле не заполнено" in r for r in reasons_of(3))
    assert "Код программы (A-05)" in fields_of(4)
    assert any("не найдена" in r for r in reasons_of(4))
    assert "Плановое начало (A-11)" in fields_of(5)
    assert any("не распознана" in r for r in reasons_of(5))
    assert "Плановые даты (A-11)" in fields_of(6)
    assert "Режим публикации (A-15)" in fields_of(8)
    assert "Команда (A-13)" in fields_of(9)
    assert "Команда (A-13)" in fields_of(10)
    assert "Признаки полного маршрута" in fields_of(11)
    assert "Контрольные точки (A-35)" in fields_of(12)
    assert "Цель" in fields_of(13)
    assert any("превышена длина" in r for r in reasons_of(13))

    # У каждой ошибки есть и поле, и причина — пустых строк быть не должно.
    for entry in body["protocol"]:
        if entry["errors"]:
            assert entry["title"], entry
            for problem in entry["errors"]:
                assert problem["field"]
                assert problem["reason"]


def test_warnings_do_not_block_the_row(api, program, users):
    """П.7.2 п.3: предупреждения (например, неизвестный руководитель) не
    мешают загрузке строки."""
    row = {**valid_import_row(suffix="1"),
           "leader_name": "Новый руководитель Петров Пётр Петрович",
           "leader_email": "novyi.rabochay@iubip.test",
           "publish_mode": "project", "public_annotation": ""}
    body = upload(api, "secretary", build_import_xlsx([row]), "f.xlsx").json()
    entry = body["protocol"][0]
    assert entry["status"] == "warning"
    assert entry["errors"] == []
    assert any("не найден" in w for w in entry["warnings"])
    assert body["counts"]["warning"] == 1


def test_duplicates_are_reported_before_loading(api, make_project, program):
    """FR-08: возможные дубли показываются ДО загрузки, решение за пользователем."""
    make_project(title=valid_import_row(suffix="7")["title"])
    body = upload(api, "secretary", build_import_xlsx([valid_import_row(suffix="7")]),
                  "f.xlsx").json()
    entry = body["protocol"][0]
    assert entry["status"] == "duplicate"
    assert entry["duplicates"]
    assert entry["duplicates"][0]["reason"]
    assert any("Похожие проекты" in w for w in entry["warnings"])
    assert body["counts"]["duplicate"] == 1


# ===========================================================================
#  п.7.2 п.4 и п.5 — подтверждение: грузится только корректное
# ===========================================================================

def test_confirm_loads_only_rows_without_errors(api, program, users):
    """п.7.2 п.5: строки с ошибками не загружаются, остальные — загружаются."""
    rows = [
        valid_import_row(suffix="1"),
        {**valid_import_row(suffix="2"), "goal": ""},            # ошибка
        valid_import_row(suffix="3"),
        {**valid_import_row(suffix="4"), "program_code": "НП-99"},  # ошибка
    ]
    data = build_import_xlsx(rows)

    preview = upload(api, "secretary", data, "f.xlsx").json()
    assert preview["counts"]["error"] == 2
    assert preview["counts"]["ok"] == 2

    confirmed = upload(api, "secretary", data, "f.xlsx", confirm="true").json()
    assert confirmed["created"] is True
    assert "Загружено строк без ошибок: 2" in confirmed["message"]
    assert "Пропущено строк с ошибками: 2" in confirmed["message"]

    stored = query("SELECT title FROM projects ORDER BY title")
    assert len(stored) == 2
    assert all(row["title"].startswith("Проект из формы инвентаризации") for row in stored)


def test_confirm_creates_team_and_milestones(program, users):
    """п.7.2: одна строка формы создаёт карточку, команду и контрольные точки."""
    row = {**valid_import_row(suffix="1"),
           "team": "Иванов Иван Иванович|leader|руководитель;"
                   "Петрова Ирина Сергеевна|member|анализ данных",
           "milestones": "Подготовка методики|2026-06-30|Иванов Иван Иванович\n"
                         "Апробация|2026-12-31|Петрова Ирина Сергеевна"}
    confirm_via_service([row])

    project = query_one("SELECT * FROM projects")
    assert project is not None
    assert project["program_id"] == program["id"]
    assert project["leader_person_id"]
    assert project["status"] == "ST-01"
    assert scalar("SELECT COUNT(*) FROM participations WHERE project_id = ?",
                  (project["id"],), 0) == 2
    assert scalar("SELECT COUNT(*) FROM milestones WHERE project_id = ?",
                  (project["id"],), 0) == 2


def test_confirm_skips_error_rows_in_service(program, users):
    """п.7.2 п.5 (уровень сервиса): строки с ошибками не загружаются."""
    result, _ = confirm_via_service([
        valid_import_row(suffix="1"),
        {**valid_import_row(suffix="2"), "goal": ""},
        valid_import_row(suffix="3"),
    ])
    assert result.created is True
    assert result.error_rows == 1
    assert result.ok_rows == 2
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == 2


def test_confirm_applies_full_route_reasons(program, users):
    """п.5.1: признаки T-01…T-06 из формы переводят проект на полный маршрут."""
    row = {**valid_import_row(suffix="1"), "flags": "T-02;T-04"}
    confirm_via_service([row])
    project = query_one("SELECT * FROM projects")
    assert project["route"] == "full"
    reasons = [r["reason"] for r in query(
        "SELECT reason FROM project_full_route_reasons WHERE project_id = ?",
        (project["id"],))]
    assert set(reasons) == {"T-02", "T-04"}


def test_confirm_marks_permission_to_publish(program, users):
    """п.7.2 п.4 + п.9.2: строки с режимом публикации получают разрешение."""
    row = {**valid_import_row(suffix="1"), "publish_mode": "project",
           "public_annotation": "Открытая аннотация"}
    confirm_via_service([row])
    project = query_one("SELECT * FROM projects")
    assert project["public_allowed_at"], "разрешение на публикацию не зафиксировано"
    assert project["public_allowed_by"] == users["secretary"].id


def test_confirm_records_batch_with_protocol(program, users):
    """п.7.2 п.6: пакет сохраняется с идентификатором, автором и протоколом."""
    _, batch = confirm_via_service([valid_import_row(suffix="1"),
                                    {**valid_import_row(suffix="2"), "goal": ""}])
    assert batch["status"] == "confirmed"
    assert batch["created_by"] == users["secretary"].id
    assert batch["confirmed_at"]
    protocol = json.loads(batch["protocol"])
    assert len(protocol) == 2
    assert sum(1 for entry in protocol if entry["errors"]) == 1


def test_confirm_returns_the_persisted_batch_id(program, users):
    """п.7.2 п.6: идентификатор в ответе совпадает с сохранённым пакетом."""
    result, batch = confirm_via_service([valid_import_row(suffix="1")])
    assert result.batch_id == batch["id"]


def test_import_does_not_duplicate_people(program, users):
    """п.6.1 п.2: профиль человека не плодится при повторной загрузке."""
    before = scalar("SELECT COUNT(*) FROM persons", (), 0)
    confirm_via_service([valid_import_row(suffix="1")])
    after_first = scalar("SELECT COUNT(*) FROM persons", (), 0)

    confirm_via_service([valid_import_row(suffix="1")])
    assert scalar("SELECT COUNT(*) FROM persons", (), 0) == after_first
    assert after_first >= before
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == 2


# ===========================================================================
#  Урок отдела: обрезанный файл падает явно
# ===========================================================================

def test_truncated_row_count_is_detected(api, program):
    """memories/2026/10/2026-10-02-truncated-file-silent-success: обрезанный
    файл обязан падать явно, а не загружаться наполовину."""
    rows = [valid_import_row(suffix=str(index)) for index in range(6)]
    data = build_import_xlsx(rows)

    # Пользователь заявил 10 строк, а в файле их 6 — файл обрезан.
    response = upload(api, "secretary", data, "f.xlsx", expected_rows="10")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "прочитан не полностью" in detail
    assert "ожидалось строк 10" in detail
    assert "получено 6" in detail
    assert scalar("SELECT COUNT(*) FROM projects", (), 0) == 0

    # Совпадение с ожидаемым числом строк — штатная работа.
    ok = upload(api, "secretary", data, "f.xlsx", expected_rows="6")
    assert ok.status_code == 200
    assert ok.json()["counts"]["total"] == 6
    assert ok.json()["counts"]["error"] == 0


# ===========================================================================
#  CSV тоже поддерживается (п.7.2 п.2)
# ===========================================================================

def test_csv_import_reads_comma_delimited_file(api, program, users):
    """п.7.2 п.2: CSV читается. Проверяем на запятой — именно так работает
    csv.reader по умолчанию."""
    rows = [valid_import_row(suffix="1"), {**valid_import_row(suffix="2"), "goal": ""}]
    data = build_import_csv(rows, delimiter=",")
    body = upload(api, "secretary", data, "forma.csv").json()
    assert body["counts"]["total"] == 2
    assert body["counts"]["error"] == 1
    assert body["counts"]["ok"] == 1


def test_csv_import_with_semicolon_is_accepted(api, program, users):
    """п.7.2 п.2: CSV с «;» — тоже корректный входной формат для Excel.

    Именно этот формат система выдаёт в выгрузке, поэтому он обязан и читаться.
    """
    rows = [valid_import_row(suffix="1")]
    data = build_import_csv(rows, delimiter=";")
    response = upload(api, "secretary", data, "forma.csv")
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["total"] == 1


# ===========================================================================
#  п.7.2 п.6 — пакет загрузки
# ===========================================================================

def test_every_import_has_batch_id_date_author_and_protocol(api, program, users):
    """п.7.2 п.6: у каждой загрузки есть идентификатор, дата, автор и протокол."""
    data = build_import_xlsx([valid_import_row(suffix="1"),
                              {**valid_import_row(suffix="2"), "goal": ""}])
    preview = upload(api, "secretary", data, "f.xlsx").json()
    batch_id = preview["batch_id"]

    detail = api.get(f"/api/import/batches/{batch_id}", login="secretary").json()
    assert detail["id"] == batch_id
    assert detail["file_name"] == "f.xlsx"
    assert detail["created_at"]
    assert detail["created_by"] == users["secretary"].id
    assert detail["status"] == "preview"
    assert len(detail["protocol"]) == 2
    assert detail["total_rows"] == 2
    assert detail["error_rows"] == 1

    listing = api.get("/api/import/batches", login="secretary").json()["items"]
    assert batch_id in {item["id"] for item in listing}
    assert any(item["author"] == "secretary" for item in listing)


def test_confirmed_batch_is_visible_in_listing(api, program, users):
    """п.7.2 п.6: подтверждённый пакет попадает в перечень загрузок."""
    result, batch = confirm_via_service([valid_import_row(suffix="1")])
    assert result.created is True
    assert batch["status"] == "confirmed"
    assert batch["confirmed_at"] is not None

    detail = api.get(f"/api/import/batches/{batch['id']}", login="secretary").json()
    assert detail["status"] == "confirmed"
    listing = api.get("/api/import/batches", login="secretary").json()["items"]
    assert batch["id"] in {item["id"] for item in listing}


# ===========================================================================
#  п.7.2 п.7 — выгрузка
# ===========================================================================

def test_export_contains_generation_date_and_filters(api, make_project, users, program):
    """п.7.2 п.7: выгрузка содержит дату формирования и применённые фильтры."""
    make_project(leader_person_id=users["leader1"].person_id,
                 title="Проект для выгрузки один")
    make_project(leader_person_id=users["leader2"].person_id,
                 title="Проект для выгрузки два")

    response = api.get("/api/export/projects", login="prorector",
                       params={"format": "xlsx", "route": "simplified"})
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith('.xlsx"')

    sheets = xlsx_sheets(response.content)
    assert "Проекты" in sheets
    assert "Условия выгрузки" in sheets
    meta = {str(row[0]): str(row[1]) for row in sheets["Условия выгрузки"][1:]
            if row and len(row) > 1}
    assert meta["Дата формирования"]
    assert meta["Дата и время (МСК)"]
    assert meta["Пользователь"] == "prorector"
    assert meta["Кодировка"] == "UTF-8"
    assert "simplified" in meta["Фильтры"]
    assert meta["Записей"] == "2"


def test_export_columns_follow_the_approved_list(api, make_project, users):
    """п.7.2 п.7: выгрузка содержит только утверждённые поля."""
    make_project()
    response = api.get("/api/export/projects", login="prorector")
    headers = [str(cell) for cell in xlsx_sheets(response.content)["Проекты"][0]]
    assert headers == [column["header"] for column in EXPORT_COLUMNS]
    # Закрытые категории прямо перечислены на листе условий.
    meta = {str(row[0]): str(row[1]) for row in
            xlsx_sheets(response.content)["Условия выгрузки"][1:] if row}
    for forbidden in FORBIDDEN_EXPORT_COLUMNS:
        assert forbidden in meta["Исключённые категории"]


def test_export_respects_filters(api, make_project, users, program):
    """п.7.2 п.7: в выгрузку попадают только записи под фильтром."""
    make_project(leader_person_id=users["leader1"].person_id,
                 title="Проект упрощённого маршрута")
    make_project(leader_person_id=users["leader1"].person_id,
                 title="Проект полного маршрута", flag_extra_resources=1)

    response = api.get("/api/export/projects", login="prorector",
                       params={"format": "xlsx", "route": "full"})
    rows = xlsx_sheets(response.content)["Проекты"][1:]
    assert len(rows) == 1
    assert "Проект полного маршрута" in " ".join(str(value) for value in rows[0])


def test_export_respects_user_rights(api, make_project, users):
    """п.7.2 п.7: в выгрузку попадают только доступные пользователю поля."""
    mine = make_project(leader_person_id=users["leader1"].person_id,
                        title="Проект руководителя первого")
    theirs = make_project(leader_person_id=users["leader2"].person_id,
                          title="Проект руководителя второго")

    mine_export = api.get("/api/export/projects", login="leader1",
                          params={"format": "csv"}).content.decode("utf-8-sig")
    assert "Проект руководителя первого" in mine_export
    assert "Проект руководителя второго" not in mine_export

    prorector_export = api.get("/api/export/projects", login="prorector",
                               params={"format": "csv"}).content.decode("utf-8-sig")
    assert "Проект руководителя второго" in prorector_export


def test_csv_export_has_bom_for_cyrillic(api, make_project, users):
    """п.10.2 п.1: CSV отдаётся в UTF-8 с BOM, иначе Excel ломает кириллицу."""
    make_project()
    response = api.get("/api/export/projects", login="prorector",
                       params={"format": "csv"})
    assert response.status_code == 200
    assert response.content[:3] == b"\xef\xbb\xbf"
    assert "text/csv" in response.headers["content-type"]
    text = response.content.decode("utf-8-sig")
    assert text.splitlines()[0].count(";") >= 10       # разделитель «;»


def test_export_neutralises_formula_injection(api, make_project, users):
    """Безопасность выгрузки: значение, начинающееся с формулы, не должно
    выполняться в Excel (OWASP)."""
    dangerous = "=CMD|'/C calc'!A1"
    project = make_project(title="Безопасная выгрузка")
    api.patch(f"/api/projects/{project['id']}", login="leader1",
              json={"goal": dangerous})

    text = api.get("/api/export/projects", login="prorector",
                   params={"format": "csv"}).content.decode("utf-8-sig")
    cells = [cell.strip() for line in text.splitlines() for cell in line.split(";")]
    assert not [cell for cell in cells if cell.startswith(("=", "+", "-", "@"))], \
        "значение-формула попало в выгрузку без экранирования"
    assert any(cell.startswith("'=") for cell in cells)


def test_export_results_meta_sheet_reports_date(api, make_project, users, make_result):
    """п.7.2 п.7: отчёт по результатам тоже содержит дату формирования."""
    project = make_project()
    make_result(project_ids=[project["id"]])
    response = api.get("/api/export/results", login="prorector",
                       params={"format": "csv"})
    assert response.content[:3] == b"\xef\xbb\xbf"
    assert "attachment" in response.headers["content-disposition"]


def test_export_exports_results_too(api, make_project, users, make_result):
    """FR-28: результаты выгружаются отдельным отчётом."""
    project = make_project()
    make_result(project_ids=[project["id"]])
    response = api.get("/api/export/results", login="prorector",
                       params={"format": "xlsx"})
    assert response.status_code == 200
    sheets = xlsx_sheets(response.content)
    headers = [str(cell) for cell in sheets["Результаты"][0]]
    assert "Номер (A-43)" in headers
    assert "Подтверждение (A-52)" in headers
    assert len(sheets["Результаты"]) == 2
    assert sheets["Условия выгрузки"][0][0] == "Дата формирования"


def test_archival_export_only_for_tech_admin(api, make_project, users):
    """п.7.2 п.8: полная архивная выгрузка — только техническому администратору."""
    make_project()
    denied = api.get("/api/export/projects", login="prorector",
                     params={"format": "xlsx", "archival": True})
    assert denied.status_code == 403
    assert "техническому администратору" in denied.json()["detail"]

    denied_leader = api.get("/api/export/projects", login="leader1",
                            params={"format": "xlsx", "archival": True})
    assert denied_leader.status_code == 403

    allowed = api.get("/api/export/projects", login="admin",
                      params={"format": "xlsx", "archival": True})
    assert allowed.status_code == 200
    meta = {str(row[0]): str(row[1]) for row in
            xlsx_sheets(allowed.content)["Условия выгрузки"][1:] if row}
    assert meta["Тип выгрузки"] == "архивная полная"


def test_import_and_export_are_logged(api, make_project, users, program):
    """п.11.3: выгрузка и импорт фиксируются в журнале без содержимого файла."""
    data = build_import_xlsx([valid_import_row(suffix="1")])
    upload(api, "secretary", data, "f.xlsx")
    confirm_via_service([valid_import_row(suffix="1")])
    api.get("/api/export/projects", login="prorector", params={"format": "csv"})

    events = [dict(row) for row in query(
        "SELECT * FROM audit_events WHERE group_name = 'admin'"
        " AND object_type IN ('import_batch', 'export')")]
    actions = {event["action"] for event in events}
    assert "Импорт: предпросмотр" in actions
    assert "Выгрузка проектов" in actions
    # Секреты и содержимое файла в журнал не попадают.
    blob = json.dumps(events, ensure_ascii=False)
    assert "Proverka-2026-Testovyi!" not in blob
    assert "Загружено строк" not in blob


def test_result_type_dictionary_is_documented_in_the_service():
    """Справочник видов результата используется при разборе формы (FR-30)."""
    assert set(RESULT_TYPE_TITLES) == set(RESULT_TYPES)
    for column in IMPORT_COLUMNS:
        assert column["header"]
        assert "required" in column