"""API импорта и выгрузки (FR-28, FR-29; п.7.2 ТЗ)."""

from __future__ import annotations

from typing import Annotated, Any
import json

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from .. import audit
from ..access import ROLE_PRORECTOR, ROLE_SECRETARY, ROLE_SYSADMIN
from ..db import execute, query, query_one
from ..services import transfer as svc
from ..utils import now_iso
from .deps import CurrentActor

router = APIRouter(prefix="/api", tags=["Импорт и выгрузка"])


@router.get("/import/template")
def import_template(actor: CurrentActor):
    """Шаблон утверждённой формы инвентаризации (п.7.2 п.1, п.15 позиция 8)."""
    data = svc.build_template_xlsx()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 'attachment; filename="forma_inventarizacii.xlsx"'},
    )


@router.post("/import/preview")
async def import_preview(
    request: Request,
    actor: CurrentActor,
    file: Annotated[UploadFile, File(description="XLSX или CSV по утверждённой форме")],
    confirm: Annotated[bool, Form()] = False,
    batch_id: Annotated[str | None, Form()] = None,
    expected_rows: Annotated[int | None, Form(
        description="Ожидаемое число строк; расхождение означает обрезанный файл")] = None,
):
    """Предпросмотр импорта (FR-29).

    До подтверждения импорт НЕ изменяет рабочие данные (п.7.2 п.4).
    Строки с ошибками не загружаются; пользователь получает построчный протокол
    с названием поля и причиной (п.7.2 п.5).
    """
    if not (actor.global_roles & {ROLE_SYSADMIN, ROLE_SECRETARY, ROLE_PRORECTOR}):
        raise HTTPException(status_code=403,
                            detail="Импорт: технический администратор, секретарь "
                                   "или проректор по науке")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Файл пуст")
    filename = file.filename or "upload.xlsx"
    if not filename.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=400,
                            detail="Поддерживаются форматы XLSX и CSV (п.7.2 п.2)")

    from ..db import execute as ex
    try:
        rows = svc.read_rows(data, filename)
        svc._check_integrity(rows, expected_rows)
        preview = svc.preview_rows(rows, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    # Идентификатор пакета один на всю загрузку — от предпросмотра до итогового
    # протокола (п.7.2 п.6). При подтверждении клиент присылает тот же batch_id,
    # что получил в предпросмотре; иначе пакет «раздваивался» бы на два, и
    # подтверждённый импорт не находился бы в списке пакетов.
    if batch_id:
        preview.batch_id = batch_id

    # Пакет сохраняется всегда: п.7.2 п.6 — у каждой загрузки есть идентификатор,
    # дата, автор и итоговый протокол.
    ex(
        "INSERT OR REPLACE INTO import_batches (id, file_name, total_rows, ok_rows,"
        " warning_rows, error_rows, duplicate_rows, status, protocol, created_at,"
        " created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (preview.batch_id, filename, preview.total_rows, preview.ok_rows,
         preview.warning_rows, preview.error_rows, preview.duplicate_rows,
         "confirmed" if confirm else "preview",
         json.dumps(preview.protocol, ensure_ascii=False), now_iso(), actor.id))
    audit.record(group_name=audit.GROUP_ADMIN, object_type="import_batch",
                 object_id=preview.batch_id,
                 action="Импорт подтверждён" if confirm else "Импорт: предпросмотр",
                 user_id=actor.id, user_login=actor.login,
                 new_value={"file": filename, "rows": preview.total_rows,
                            "errors": preview.error_rows,
                            "duplicates": preview.duplicate_rows})

    if not confirm:
        return preview.as_dict()

    result = svc.confirm_import(preview, rows, filename, actor)
    payload = result.as_dict()
    payload["message"] = (
        f"Загружено строк без ошибок: {result.ok_rows + result.warning_rows}. "
        f"Пропущено строк с ошибками: {result.error_rows}."
    )
    return payload


@router.get("/import/batches")
def import_batches(actor: CurrentActor):
    rows = query(
        "SELECT b.id, b.file_name, b.total_rows, b.ok_rows, b.warning_rows,"
        " b.error_rows, b.duplicate_rows, b.status, b.created_at, b.confirmed_at,"
        " u.login AS author FROM import_batches b LEFT JOIN users u ON u.id = b.created_by"
        " ORDER BY b.created_at DESC LIMIT 100")
    return {"items": [dict(r) for r in rows]}


@router.get("/import/batches/{batch_id}")
def import_batch_protocol(batch_id: str, actor: CurrentActor):
    import json
    from ..db import query_one
    row = query_one("SELECT * FROM import_batches WHERE id = ?", (batch_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Пакет импорта не найден")
    item = dict(row)
    item["protocol"] = json.loads(item.get("protocol") or "[]")
    return item


@router.get("/export/projects")
def export_projects(
    actor: CurrentActor,
    format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
    program_id: str | None = None,
    route: str | None = None,
    status: str | None = None,
    risk_level: str | None = None,
    leader_person_id: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    archival: bool = Query(default=False,
                           description="Полная архивная выгрузка: только для "
                                       "технического администратора (п.7.2 п.8)"),
):
    """Выгрузка XLSX или CSV с учётом прав и активных фильтров (FR-28).

    Файл содержит дату формирования, применённые фильтры и только доступные
    пользователю поля (п.7.2 п.7).
    """
    filters = {"program_id": program_id, "route": route, "status": status,
               "risk_level": risk_level, "leader_person_id": leader_person_id, "q": q}
    applied = {k: v for k, v in filters.items() if v}
    try:
        if format == "xlsx":
            data, name = svc.build_export(applied, actor, archival=archival)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            data = svc.build_csv_export(applied, actor, archival=archival)
            name = f"registry_export_{name_stamp()}.csv"
            media = "text/csv; charset=utf-8"
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    audit.record(group_name=audit.GROUP_ADMIN, object_type="export", object_id=None,
                 action="Выгрузка проектов", user_id=actor.id, user_login=actor.login,
                 new_value={"format": format, "archival": archival, "filters": applied})
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def name_stamp() -> str:
    from ..utils import today_iso
    return today_iso().replace("-", "")


@router.get("/export/results")
def export_results(
    actor: CurrentActor,
    format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
    result_type: str | None = None,
    readiness_stage: str | None = None,
    year: str | None = None,
):
    """Выгрузка результатов (FR-28, п.8 «Отчёты»)."""
    import csv as csvmod
    import io
    from openpyxl import Workbook

    from ..utils import today_iso

    where = ["r.archived_at IS NULL"]
    params: list[Any] = []
    if result_type:
        where.append("r.result_type = ?")
        params.append(result_type)
    if readiness_stage:
        where.append("r.readiness_stage = ?")
        params.append(readiness_stage)
    if year:
        where.append("SUBSTR(COALESCE(r.actual_date, r.planned_date), 1, 4) = ?")
        params.append(year)
    rows = query(
        f"SELECT r.* FROM results r WHERE {' AND '.join(where)} ORDER BY r.code",
        tuple(params))
    headers = ["Номер (A-43)", "Тип (A-44)", "Название (A-45)", "Описание (A-46)",
               "Связанные проекты (A-47)", "Авторы (A-48)", "Стадия (A-49)",
               "Плановая дата (A-50)", "Фактическая дата (A-50)",
               "Критерий приёмки (A-51)", "Подтверждение (A-52)",
               "Заключение (A-53)", "Разрешение на публикацию (A-54)",
               "DOI / EDN / URL (A-60)"]
    body: list[list] = []
    for row in rows:
        projects = ", ".join(r["code"] for r in query(
            "SELECT p.code FROM result_projects rp JOIN projects p ON p.id = rp.project_id"
            " WHERE rp.result_id = ? ORDER BY p.code", (row["id"],)))
        try:
            ids = json.loads(row["authors"] or "[]")
        except ValueError:
            ids = []
        author_names = []
        if ids:
            marks = ",".join("?" for _ in ids)
            author_names = [r["full_name"] for r in
                            query(f"SELECT full_name FROM persons WHERE id IN ({marks})",
                                  tuple(ids))]
        body.append([
            row["code"], row["result_type"], row["title"], row["description"],
            projects, ", ".join(author_names), row["readiness_stage"],
            row["planned_date"], row["actual_date"], row["acceptance_criterion"],
            row["confirmation"], row["review_status"],
            "разрешено" if row["publish_allowed"] else "нет",
            row["doi"] or row["edn"] or row["url"] or "",
        ])
    stamp = today_iso().replace("-", "")
    if format == "csv":
        buf = io.StringIO()
        writer = csvmod.writer(buf, delimiter=";")
        writer.writerow(headers)
        writer.writerows(body)
        data = b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
        media = "text/csv; charset=utf-8"
        name = f"registry_results_{stamp}.csv"
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Результаты"
        ws.append(headers)
        for line in body:
            ws.append(line)
        meta = wb.create_sheet("Условия выгрузки")
        meta.append(["Дата формирования", today_iso()])
        meta.append(["Пользователь", actor.login])
        meta.append(["Записей", len(body)])
        meta.append(["Кодировка", "UTF-8"])
        out = io.BytesIO()
        wb.save(out)
        data = out.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        name = f"registry_results_{stamp}.xlsx"
    audit.record(group_name=audit.GROUP_ADMIN, object_type="export", object_id=None,
                 action="Выгрузка результатов", user_id=actor.id, user_login=actor.login,
                 new_value={"format": format, "rows": len(body)})
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})