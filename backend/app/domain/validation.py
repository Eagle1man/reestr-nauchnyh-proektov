"""Обязательные поля карточки и точная проверка комплектности.

FR-07: переход блокируется с точным перечнем незаполненных полей.

Обозначения Приложения А: О — обязательное, У — условно обязательное,
Н — необязательное, А — формируется автоматически. Столбцы «УМ» (упрощённый
маршрут) и «ПМ» (полный маршрут) дают два разных набора требований.

ДОПУЩЕНИЕ, зафиксированное при разработке.
  П.4.2 ТЗ требует для запуска упрощённого проекта «шесть обязательных научных
  полей», но не перечисляет их. Здесь приняты шесть научных полей раздела
  «Научное содержание», отвечающих принципу «Проверяемый результат»
  (п.2.3): проблема, вопрос/гипотеза, цель, методы, данные или доказательная
  база, критерии результата. Плановый тип результата (A-25) проверяется
  вместе с критериями (A-26) как один смысловой блок. Набор полей вынесен в
  settings, поэтому уточнение не требует правки кода (FR-35).
"""

from __future__ import annotations

from typing import Any, Final

# ---------------------------------------------------------------------------
#  Словарь полей карточки (Приложение А) — код, название, обязательность
#  УМ/ПМ: О обязательное, У условно обязательное, Н необязательное, А авто
# ---------------------------------------------------------------------------

FIELD_DICTIONARY: Final[dict[str, dict[str, str]]] = {
    # A.1 Паспорт проекта
    "A-01": {"section": "Паспорт", "label": "Идентификатор", "um": "А", "pm": "А",
             "field": "id, code", "filled_by": "Система", "public": "Да",
             "validation": "Уникален и неизменяем"},
    "A-02": {"section": "Паспорт", "label": "Полное название", "um": "О", "pm": "О",
             "field": "title", "filled_by": "Руководитель", "public": "Да",
             "validation": "Проверка точного и близкого дубля"},
    "A-03": {"section": "Паспорт", "label": "Краткое название", "um": "О", "pm": "О",
             "field": "short_title", "filled_by": "Руководитель", "public": "Да",
             "validation": "Для списков и панели"},
    "A-04": {"section": "Паспорт", "label": "Публичная аннотация", "um": "У", "pm": "У",
             "field": "public_annotation", "filled_by": "Руководитель", "public": "Да",
             "validation": "Обязательна при публикации"},
    "A-05": {"section": "Паспорт", "label": "Научная программа", "um": "О", "pm": "О",
             "field": "program_id", "filled_by": "Руководитель; куратор подтверждает",
             "public": "Да", "validation": "Только действующая программа"},
    "A-06": {"section": "Паспорт", "label": "Связь с общей темой", "um": "О", "pm": "О",
             "field": "theme_link", "filled_by": "Руководитель", "public": "Да",
             "validation": "Конкретное смысловое пояснение"},
    "A-07": {"section": "Паспорт", "label": "Маршрут", "um": "А", "pm": "А",
             "field": "route", "filled_by": "Система; уполномоченное лицо подтверждает",
             "public": "Нет", "validation": "Основание хранится отдельно"},
    "A-08": {"section": "Паспорт", "label": "Основания полного маршрута", "um": "У", "pm": "О",
             "field": "project_full_route_reasons", "filled_by": "Руководитель",
             "public": "Нет", "validation": "Хотя бы одно для полного маршрута"},
    "A-09": {"section": "Паспорт", "label": "Статус", "um": "А", "pm": "А",
             "field": "status", "filled_by": "Система", "public": "Частично",
             "validation": "Только допустимый переход"},
    "A-10": {"section": "Паспорт", "label": "Индикатор риска", "um": "А", "pm": "А",
             "field": "risk_level", "filled_by": "Система; уполномоченное лицо",
             "public": "Нет", "validation": "Ручная правка требует комментария"},
    "A-11": {"section": "Паспорт", "label": "Плановые даты", "um": "О", "pm": "О",
             "field": "planned_start, planned_end", "filled_by": "Руководитель",
             "public": "Частично", "validation": "Начало не позднее завершения"},
    "A-12": {"section": "Паспорт", "label": "Руководитель", "um": "О", "pm": "О",
             "field": "leader_person_id", "filled_by": "Руководитель; куратор подтверждает",
             "public": "Частично", "validation": "Один основной руководитель"},
    "A-13": {"section": "Паспорт", "label": "Команда", "um": "О", "pm": "О",
             "field": "participations", "filled_by": "Руководитель", "public": "Частично",
             "validation": "Роль, задача и период для каждого"},
    "A-14": {"section": "Паспорт", "label": "Партнёры", "um": "У", "pm": "У",
             "field": "project_partners", "filled_by": "Руководитель", "public": "Частично",
             "validation": "Обязательно при наличии партнёра"},
    "A-15": {"section": "Паспорт", "label": "Режим публикации", "um": "О", "pm": "О",
             "field": "publish_mode", "filled_by": "Руководитель; уполномоченное лицо",
             "public": "Нет", "validation": "До утверждения данные закрыты"},
    "A-16": {"section": "Паспорт", "label": "Дата и автор создания", "um": "А", "pm": "А",
             "field": "created_at, created_by", "filled_by": "Система", "public": "Нет",
             "validation": "Неизменяемо"},
    # A.2 Научное содержание
    "A-17": {"section": "Научное содержание", "label": "Исследовательская проблема",
             "um": "О", "pm": "О", "field": "problem", "filled_by": "Руководитель",
             "public": "Частично", "validation": "Проверяемая проблема, не общая тема"},
    "A-18": {"section": "Научное содержание", "label": "Вопрос или гипотеза",
             "um": "О", "pm": "О", "field": "question", "filled_by": "Руководитель",
             "public": "Да", "validation": "Допускает проверку"},
    "A-19": {"section": "Научное содержание", "label": "Цель", "um": "О", "pm": "О",
             "field": "goal", "filled_by": "Руководитель", "public": "Да",
             "validation": "Одна основная цель"},
    "A-20": {"section": "Научное содержание", "label": "Задачи", "um": "Н", "pm": "О",
             "field": "tasks", "filled_by": "Руководитель", "public": "Частично",
             "validation": "Связь с методом или результатом"},
    "A-21": {"section": "Научное содержание", "label": "Объект", "um": "Н", "pm": "О",
             "field": "research_object", "filled_by": "Руководитель", "public": "Да",
             "validation": "Обязателен для полного маршрута"},
    "A-22": {"section": "Научное содержание", "label": "Предмет", "um": "Н", "pm": "О",
             "field": "research_subject", "filled_by": "Руководитель", "public": "Да",
             "validation": "Конкретизирует объект"},
    "A-23": {"section": "Научное содержание", "label": "Методы", "um": "О", "pm": "О",
             "field": "methods", "filled_by": "Руководитель", "public": "Частично",
             "validation": "Не менее одного метода"},
    "A-24": {"section": "Научное содержание", "label": "Данные или доказательная база",
             "um": "О", "pm": "О", "field": "data_basis", "filled_by": "Руководитель",
             "public": "Частично", "validation": "Источник, состав, период и доступ"},
    "A-25": {"section": "Научное содержание", "label": "Планируемый результат",
             "um": "О", "pm": "О", "field": "planned_result_type", "filled_by": "Руководитель",
             "public": "Да", "validation": "Один основной проверяемый результат"},
    "A-26": {"section": "Научное содержание", "label": "Критерии результата",
             "um": "О", "pm": "О", "field": "result_criteria", "filled_by": "Руководитель",
             "public": "Частично", "validation": "Не менее одного признака выполнения"},
    "A-27": {"section": "Научное содержание", "label": "Научная новизна", "um": "Н", "pm": "О",
             "field": "novelty", "filled_by": "Руководитель", "public": "Да",
             "validation": "Отличие от известных решений"},
    "A-28": {"section": "Научное содержание", "label": "Практическая применимость",
             "um": "Н", "pm": "О", "field": "applicability", "filled_by": "Руководитель",
             "public": "Да", "validation": "Пользователь и способ применения"},
    "A-29": {"section": "Научное содержание", "label": "Ограничения", "um": "Н", "pm": "О",
             "field": "limitations", "filled_by": "Руководитель", "public": "Нет",
             "validation": "Данные, метод, переносимость выводов"},
    "A-30": {"section": "Научное содержание", "label": "Персональные данные",
             "um": "У", "pm": "У", "field": "personal_data", "filled_by": "Руководитель",
             "public": "Нет", "validation": "«Да» включает полный маршрут"},
    "A-31": {"section": "Научное содержание", "label": "Участие людей", "um": "У", "pm": "У",
             "field": "human_subjects", "filled_by": "Руководитель", "public": "Нет",
             "validation": "Требует правовой и этической проверки"},
    "A-32": {"section": "Научное содержание", "label": "Правовое и этическое основание",
             "um": "У", "pm": "У", "field": "legal_basis_status", "filled_by": "Руководитель; "
             "уполномоченное лицо", "public": "Нет", "validation": "До соответствующего этапа"},
    "A-33": {"section": "Научное содержание", "label": "Конфиденциальность и права",
             "um": "У", "pm": "О", "field": "confidentiality", "filled_by": "Руководитель",
             "public": "Нет", "validation": "До публикации результата"},
    "A-34": {"section": "Научное содержание", "label": "Ресурсный запрос",
             "um": "У", "pm": "О", "field": "resource_request", "filled_by": "Руководитель",
             "public": "Нет", "validation": "Сравнение с утверждённым лимитом"},
    # A.3 Контрольные точки
    "A-35": {"section": "Контрольные точки", "label": "Название точки", "um": "О", "pm": "О",
             "field": "milestones.title", "filled_by": "Руководитель", "public": "Нет",
             "validation": "Описывает проверяемое событие"},
    "A-36": {"section": "Контрольные точки", "label": "Плановая дата", "um": "О", "pm": "О",
             "field": "milestones.planned_date", "filled_by": "Руководитель",
             "public": "Частично", "validation": "В пределах проекта"},
    "A-37": {"section": "Контрольные точки", "label": "Ответственный", "um": "О", "pm": "О",
             "field": "milestones.responsible_person_id", "filled_by": "Руководитель",
             "public": "Нет", "validation": "Только действующий участник"},
    "A-38": {"section": "Контрольные точки", "label": "Плановое подтверждение",
             "um": "О", "pm": "О", "field": "milestones.planned_evidence",
             "filled_by": "Руководитель", "public": "Нет",
             "validation": "Не допускается «выполнение работы» без доказательства"},
    "A-39": {"section": "Контрольные точки", "label": "Статус точки", "um": "А", "pm": "А",
             "field": "milestones.status", "filled_by": "Система; руководитель",
             "public": "Частично", "validation": "Просрочка рассчитывается автоматически"},
    "A-40": {"section": "Контрольные точки", "label": "Фактическая дата", "um": "У", "pm": "У",
             "field": "milestones.actual_date", "filled_by": "Руководитель", "public": "Нет",
             "validation": "Обязательна при выполнении"},
    "A-41": {"section": "Контрольные точки", "label": "Подтверждение", "um": "У", "pm": "У",
             "field": "milestones.confirmation", "filled_by": "Руководитель",
             "public": "Частично", "validation": "Обязательно при выполнении"},
    "A-42": {"section": "Контрольные точки", "label": "Причина переноса", "um": "У", "pm": "У",
             "field": "milestones.postpone_reason", "filled_by": "Руководитель",
             "public": "Нет", "validation": "Обязательна при изменении срока"},
    # A.4 Результаты
    "A-43": {"section": "Результаты", "label": "Идентификатор результата", "um": "А", "pm": "А",
             "field": "results.id, results.code", "filled_by": "Система", "public": "Да",
             "validation": "Уникален"},
    "A-44": {"section": "Результаты", "label": "Тип результата", "um": "О", "pm": "О",
             "field": "results.result_type", "filled_by": "Руководитель или автор",
             "public": "Да", "validation": "Публикация, методика, модель, данные, продукт"},
    "A-45": {"section": "Результаты", "label": "Название", "um": "О", "pm": "О",
             "field": "results.title", "filled_by": "Руководитель или автор",
             "public": "Да", "validation": "Проверка дубля"},
    "A-46": {"section": "Результаты", "label": "Описание", "um": "О", "pm": "О",
             "field": "results.description", "filled_by": "Руководитель или автор",
             "public": "Да", "validation": "Содержание и научное значение"},
    "A-47": {"section": "Результаты", "label": "Связанные проекты", "um": "О", "pm": "О",
             "field": "result_projects", "filled_by": "Руководитель", "public": "Да",
             "validation": "Не менее одного проекта"},
    "A-48": {"section": "Результаты", "label": "Авторы", "um": "О", "pm": "О",
             "field": "results.authors", "filled_by": "Руководитель или автор",
             "public": "Частично", "validation": "Внутренние авторы из профилей"},
    "A-49": {"section": "Результаты", "label": "Стадия готовности", "um": "О", "pm": "О",
             "field": "results.readiness_stage", "filled_by": "Руководитель",
             "public": "Частично", "validation": "От запланирован до опубликован или внедрён"},
    "A-50": {"section": "Результаты", "label": "Плановый и фактический срок",
             "um": "О/У", "pm": "О/У", "field": "results.planned_date, results.actual_date",
             "filled_by": "Руководитель", "public": "Частично",
             "validation": "Фактическая обязательна после принятия"},
    "A-51": {"section": "Результаты", "label": "Критерий приёмки", "um": "О", "pm": "О",
             "field": "results.acceptance_criterion", "filled_by": "Руководитель",
             "public": "Нет", "validation": "Проверяемый критерий"},
    "A-52": {"section": "Результаты", "label": "Подтверждение", "um": "У", "pm": "У",
             "field": "results.confirmation", "filled_by": "Руководитель",
             "public": "Частично", "validation": "Обязательно для принятого результата"},
    "A-53": {"section": "Результаты", "label": "Заключение", "um": "У", "pm": "У",
             "field": "results.review_status", "filled_by": "Эксперт; принимающее лицо",
             "public": "Нет", "validation": "Без заключения результат не подтверждён"},
    "A-54": {"section": "Результаты", "label": "Разрешение на публикацию", "um": "О", "pm": "О",
             "field": "results.publish_allowed", "filled_by": "Уполномоченное лицо",
             "public": "Нет", "validation": "Учитывает ограничения и права"},
    # A.5 Дополнительные поля публикации
    "A-55": {"section": "Публикация", "label": "Вид публикации", "um": "О", "pm": "О",
             "field": "publications.kind", "filled_by": "Автор", "public": "Да",
             "validation": "Статья, монография, глава, материалы"},
    "A-56": {"section": "Публикация", "label": "Стадия", "um": "О", "pm": "О",
             "field": "publications.stage", "filled_by": "Автор", "public": "Частично",
             "validation": "Замысел; рецензирование; подана; доработка; принята; опубликована"},
    "A-57": {"section": "Публикация", "label": "Целевое издание", "um": "О", "pm": "О",
             "field": "publications.target_venue", "filled_by": "Автор", "public": "Да",
             "validation": "Обязательно с момента подачи"},
    "A-58": {"section": "Публикация", "label": "Плановая и фактическая подача",
             "um": "О/У", "pm": "О/У", "field": "publications.submitted_at", "filled_by": "Автор",
             "public": "Нет", "validation": "Фактическая обязательна со стадии «подана»"},
    "A-59": {"section": "Публикация", "label": "Дата принятия и публикации", "um": "У", "pm": "У",
             "field": "publications.accepted_at, publications.published_at", "filled_by": "Автор",
             "public": "Да", "validation": "По соответствующей стадии"},
    "A-60": {"section": "Публикация", "label": "DOI, EDN, URL", "um": "У", "pm": "У",
             "field": "results.doi, results.edn, results.url", "filled_by": "Автор",
             "public": "Да", "validation": "Проверка формата и уникальности"},
    "A-61": {"section": "Публикация", "label": "Выходные данные", "um": "У", "pm": "У",
             "field": "publications.biblio_*", "filled_by": "Автор", "public": "Да",
             "validation": "Для опубликованного материала"},
    "A-62": {"section": "Публикация", "label": "Внутреннее рецензирование", "um": "У", "pm": "У",
             "field": "publications.internal_review_id", "filled_by": "Эксперт",
             "public": "Нет", "validation": "По установленному маршруту"},
    # A.6 Связанные записи
    "A-63": {"section": "Связанные записи", "label": "Экспертиза", "um": "—", "pm": "—",
             "field": "reviews", "filled_by": "Секретарь; эксперт", "public": "Нет",
             "validation": "Заключение после фиксации неизменяемо"},
    "A-64": {"section": "Связанные записи", "label": "Решение", "um": "—", "pm": "—",
             "field": "decisions", "filled_by": "Уполномоченное лицо", "public": "Нет",
             "validation": "Не создаётся без основания"},
    "A-65": {"section": "Связанные записи", "label": "Риск", "um": "—", "pm": "—",
             "field": "risks", "filled_by": "Руководитель", "public": "Нет",
             "validation": "Ручное изменение уровня требует комментария"},
    "A-66": {"section": "Связанные записи", "label": "Задача обучающегося", "um": "—", "pm": "—",
             "field": "student_tasks", "filled_by": "Руководитель", "public": "Частично",
             "validation": "Одна запись на одну задачу"},
    "A-67": {"section": "Связанные записи", "label": "Диссертация", "um": "—", "pm": "—",
             "field": "dissertations", "filled_by": "Руководитель; секретарь",
             "public": "Частично", "validation": "Одна запись на одну диссертацию"},
    "A-68": {"section": "Связанные записи", "label": "Материал", "um": "—", "pm": "—",
             "field": "evidences", "filled_by": "Руководитель; участник", "public": "Частично",
             "validation": "Один материал может использоваться несколькими объектами"},
    "A-69": {"section": "Связанные записи", "label": "Событие аудита", "um": "А", "pm": "А",
             "field": "audit_events", "filled_by": "Система", "public": "Нет",
             "validation": "Автоматически; не редактируется"},
}

#: Название поля для показа пользователю: столбец → название из Приложения А.
#: Индекс строится по КАЖДОМУ столбцу отдельно: одна позиция Приложения А
#: иногда закрывает несколько полей («planned_start, planned_end», «id, code»).
#: Раньше название искалось сравнением со строкой целиком, поэтому объединённые
#: поля не находились и пользователю показывалось `planned_start` — служебное
#: имя вместо «Плановое начало».
FIELD_LABELS: Final[dict[str, str]] = {
    column.strip(): meta["label"]
    for meta in FIELD_DICTIONARY.values()
    for column in meta["field"].split(",")
}

#: Уточнения там, где одна позиция Приложения А закрывает два разных поля
#: карточки: пользователю нужно знать, КАКОЕ из них заполнить.
COLUMN_LABEL_OVERRIDES: Final[dict[str, str]] = {
    "planned_start": "Плановое начало (A-11)",
    "planned_end": "Плановое завершение (A-11)",
}

#: Шесть обязательных научных полей (допущение зафиксировано в модуле docstring)
SCIENTIFIC_CORE: Final[tuple[str, ...]] = ("problem", "question", "goal",
                                           "methods", "data_basis", "result_criteria")

#: Паспортные поля, обязательные в обоих маршрутах (A-02, A-03, A-05, A-06, A-11, A-12, A-15)
PASSPORT_COMMON: Final[tuple[str, ...]] = (
    "title", "short_title", "program_id", "theme_link",
    "planned_start", "planned_end", "leader_person_id", "publish_mode",
)

#: Научные поля, обязательные в обоих маршрутах (столбец О/О раздела A.2)
SCIENTIFIC_COMMON: Final[tuple[str, ...]] = SCIENTIFIC_CORE + ("planned_result_type",)

#: Научные поля, дополнительные для полного маршрута (столбец Н/О)
SCIENTIFIC_FULL_ONLY: Final[tuple[str, ...]] = (
    "tasks", "research_object", "research_subject", "novelty",
    "applicability", "limitations", "confidentiality", "resource_request",
)

REQUIRED_SIMPLIFIED: Final[tuple[str, ...]] = PASSPORT_COMMON + SCIENTIFIC_COMMON
REQUIRED_FULL: Final[tuple[str, ...]] = (
    PASSPORT_COMMON + SCIENTIFIC_COMMON + SCIENTIFIC_FULL_ONLY
)

#: Команда и хотя бы одна контрольная точка обязательны в обоих маршрутах
REQUIRED_RELATIONAL: Final[tuple[str, ...]] = ("team", "milestones")

#: Условно обязательные поля: требуются, только если включён соответствующий признак
CONDITIONAL_RULES: Final[tuple[tuple[str, str, str], ...]] = (
    ("flag_personal_data", "personal_data_note",
     "Указаны персональные данные — нужно пояснение (A-30)"),
    ("flag_human_subjects", "human_subjects_note",
     "Участие людей в исследовании — нужно пояснение (A-31)"),
    ("flag_ethics_required", "legal_basis_link",
     "Требуется этическое рассмотрение — укажите правовое и этическое основание (A-32)"),
    ("flag_confidential", "confidentiality",
     "Указана конфиденциальность — нужно описание режима (A-33)"),
    ("flag_ip_restricted", "ip_note",
     "Ограничение прав — нужна поясняющая запись (A-33)"),
    ("flag_extra_resources", "resource_request",
     "Запрошены ресурсы сверх лимита — нужен ресурсный запрос (A-34)"),
)

#: Публичная аннотация обязательна, если проект объявлен публичным (A-04)
PUBLIC_ANNOTATION_REQUIRED: Final[tuple[str, ...]] = ("project", "all")


def required_fields_for(route: str) -> tuple[str, ...]:
    return REQUIRED_FULL if route == "full" else REQUIRED_SIMPLIFIED


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple)):
        return len(value) == 0
    return False


#: Поля, задаваемые при СОЗДАНИИ карточки и не меняемые обычной правкой:
#: они не входят в белый список изменяемых полей сервиса. Проверка
#: комплектности обязана их видеть, иначе карточка вечно считалась бы
#: незаполненной по программе и руководителю и не могла бы уйти из ST-01.
CREATION_ONLY_FIELDS: tuple[str, ...] = (
    "program_id", "leader_person_id", "publish_mode", "route",
)


def completeness_source(project: dict) -> dict:
    """Срез карточки для проверки комплектности.

    Берутся ВСЕ поля строки проекта, а не только редактируемые: обязательными
    являются и заданные при создании поля, и те, что меняются правкой.
    """
    source = dict(project)
    source.setdefault("route", project.get("route") or "simplified")
    return source


def missing_required_fields(
    project: dict,
    *,
    team_size: int = 0,
    milestone_count: int = 0,
    partner_count: int = 0,
) -> list[str]:
    """Точный перечень незаполненных полей (FR-07) в человекочитаемом виде.

    Возвращает названия полей из Приложения А, чтобы пользователь видел «что
    именно дозаполнить», а не внутренние имена колонок.
    """
    project = completeness_source(project)
    route = project.get("route") or "simplified"
    missing: list[str] = []

    def label_for(column: str) -> str:
        # Сначала уточнение (одна позиция Приложения А на два поля карточки),
        # затем название позиции, и только в крайнем случае — имя столбца.
        return (COLUMN_LABEL_OVERRIDES.get(column)
                or FIELD_LABELS.get(column) or column)

    for column in required_fields_for(route):
        if _empty(project.get(column)):
            missing.append(label_for(column))

    if team_size < 1:
        missing.append("Команда")
    if milestone_count < 1:
        missing.append("Контрольные точки")

    if partner_count > 0 and _empty(project.get("theme_link")) is False:
        # A-14: партнёры обязательны при наличии партнёра — проверяется наличие
        # самой записи, она уже учтена через partner_count.
        pass

    for flag, column, message in CONDITIONAL_RULES:
        if project.get(flag) and _empty(project.get(column)):
            missing.append(message)

    if project.get("publish_mode") in PUBLIC_ANNOTATION_REQUIRED \
            and _empty(project.get("public_annotation")):
        missing.append("Публичная аннотация")

    # Условно обязательное основание полного маршрута A-08
    if route == "full" and not project.get("full_route_reasons"):
        missing.append("Основания полного маршрута")

    seen: set[str] = set()
    unique: list[str] = []
    for item in missing:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def validate_lengths(project: dict) -> list[str]:
    """Ограничения длины из Приложения А (FR-07, сообщение указывает поле)."""
    limits = {
        "title": (500, "A-02"),
        "short_title": (150, "A-03"),
        "public_annotation": (1000, "A-04"),
        "theme_link": (500, "A-06"),
        "problem": (2000, "A-17"),
        "question": (1000, "A-18"),
        "goal": (700, "A-19"),
        "research_object": (500, "A-21"),
        "research_subject": (500, "A-22"),
        "novelty": (1500, "A-27"),
        "applicability": (1500, "A-28"),
        "limitations": (1000, "A-29"),
    }
    problems: list[str] = []
    for column, (limit, code) in limits.items():
        value = project.get(column)
        if isinstance(value, str) and len(value) > limit:
            label = next((m["label"] for m in FIELD_DICTIONARY.values()
                          if m["field"] == column), column)
            problems.append(f"{code} «{label}»: превышено {limit} знаков (указано {len(value)})")
    if project.get("planned_start") and project.get("planned_end") \
            and project["planned_start"] > project["planned_end"]:
        problems.append("A-11 «Плановые даты»: начало позже завершения")
    return problems


def dictionary_document() -> list[dict]:
    """Словарь полей для поставки (п.15, позиция 5)."""
    return [
        {
            "code": code,
            "section": meta["section"],
            "label": meta["label"],
            "type_field": meta["field"],
            "required_simplified": meta["um"],
            "required_full": meta["pm"],
            "filled_by": meta["filled_by"],
            "public": meta["public"],
            "validation": meta["validation"],
        }
        for code, meta in sorted(FIELD_DICTIONARY.items())
    ]