-- =====================================================================
--  Реестр научных проектов Южного университета (ИУБиП)
--  Схема начального состояния. Соответствует информационной модели
--  п.6 ТЗ v1.0 от 06.10.2026.
--
--  Правила схемы:
--   * каждый объект имеет внутренний UUID (п.6.1 п.1);
--   * проект дополнительно получает неизменяемый читаемый номер РНП-{год}-{номер};
--   * справочники вынесены в dict_items и правятся без изменения кода (FR-30);
--   * пороговые сроки и шаблон номера — в settings (FR-35);
--   * используемые записи не удаляются физически, а архивируются (п.6.1 п.5).
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
--  Профили людей  (FR-03, раздел 6)
--  Определены раньше учётных записей: users.person_id ссылается на persons.
-- ---------------------------------------------------------------------

-- Один профиль человека используется во всех проектах и результатах (FR-03).
-- Основной ключ сопоставления при импорте — учётная запись или служебный адрес (п.6.1 п.2).
CREATE TABLE IF NOT EXISTS persons (
    id              TEXT PRIMARY KEY,
    user_id         TEXT UNIQUE REFERENCES users(id) ON DELETE SET NULL,
    full_name       TEXT NOT NULL,
    work_place      TEXT,               -- место работы или обучения (п.11.2 п.3)
    position        TEXT,
    academic_degree TEXT,
    service_contact TEXT,               -- служебный контакт (п.11.2 п.3)
    category        TEXT NOT NULL DEFAULT 'staff',  -- staff|student|aspirant
    external_id     TEXT,
    created_at      TEXT NOT NULL,
    created_by      TEXT,
    archived_at     TEXT,
    -- ПС-22: блокировка пользователя не должна терять внесённые данные и историю,
    -- поэтому профиль архивируется, а не удаляется.
    CHECK (category IN ('staff', 'student', 'aspirant'))
);
CREATE INDEX IF NOT EXISTS ix_persons_name ON persons(full_name);

-- ---------------------------------------------------------------------
--  Пользователи, роли, сессии  (раздел 4 ТЗ, FR-01, FR-02)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id                TEXT PRIMARY KEY,          -- UUID
    login             TEXT NOT NULL UNIQUE,      -- университетская учётная запись
    email             TEXT UNIQUE,               -- служебный адрес (ключ сопоставления при импорте, п.6.1 п.2)
    full_name         TEXT NOT NULL,
    password_hash     TEXT,                      -- NULL = вход только по одноразовой ссылке
    role              TEXT NOT NULL DEFAULT 'employee',
    is_active         INTEGER NOT NULL DEFAULT 1,
    must_reset        INTEGER NOT NULL DEFAULT 0,
    last_login_at     TEXT,
    -- Связь с профилем человека. Один профиль на человека (FR-03, п.6.1 п.2).
    person_id         TEXT REFERENCES persons(id) ON DELETE SET NULL,
    created_at        TEXT NOT NULL,
    created_by        TEXT,
    archived_at       TEXT
);

-- Глобальные роли. Руководитель/участник/эксперт — роли отношения к проекту
-- и хранятся в participations и expert_assignments (п.4.1 п.1).
CREATE TABLE IF NOT EXISTS user_roles (
    user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role      TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    granted_by TEXT,
    PRIMARY KEY (user_id, role)
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,     -- сессия завершается после 60 минут бездействия (п.11.1 п.3)
    expires_at  TEXT NOT NULL,
    user_agent  TEXT,
    ip_address  TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_last_seen ON sessions(last_seen_at);

-- Счётчик неудачных попыток входа: блокировка на 15 минут после 5 (п.11.1 п.2)
CREATE TABLE IF NOT EXISTS login_attempts (
    id          TEXT PRIMARY KEY,
    login       TEXT NOT NULL,
    ip_address  TEXT,
    successful  INTEGER NOT NULL DEFAULT 0,
    attempted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_login_attempts_login ON login_attempts(login, attempted_at);

-- ---------------------------------------------------------------------
--  Справочники и настройки  (FR-30, FR-35)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dict_items (
    id          TEXT PRIMARY KEY,
    dict        TEXT NOT NULL,          -- method|result_type|risk_category|organization|
                                         -- publication_kind|target_journal|role|party_type
    code        TEXT NOT NULL,
    title       TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1,
    metadata    TEXT,                   -- JSON
    UNIQUE (dict, code)
);
CREATE INDEX IF NOT EXISTS ix_dict_items_dict ON dict_items(dict, is_active);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);

-- ---------------------------------------------------------------------
--  Научные программы  (M-01, FR-04)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS programs (
    id                  TEXT PRIMARY KEY,
    code                TEXT NOT NULL UNIQUE,
    title               TEXT NOT NULL,
    short_title         TEXT,
    description         TEXT,
    criteria            TEXT,           -- критерии включения (M-01)
    expected_results    TEXT,           -- ожидаемые результаты (M-01)
    planned_start       TEXT,
    planned_end         TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1,
    public_allowed      INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    created_by          TEXT,
    archived_at         TEXT
);

-- Куратор программы — назначение, а не глобальная роль (FR-04, раздел 4)
CREATE TABLE IF NOT EXISTS program_curators (
    program_id TEXT NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    person_id  TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    appointed_at TEXT NOT NULL,
    appointed_by TEXT,
    PRIMARY KEY (program_id, person_id)
);

-- ---------------------------------------------------------------------
--  Проекты  (M-02, раздел 6.2 — 10 разделов карточки)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS projects (
    id                TEXT PRIMARY KEY,
    code              TEXT NOT NULL UNIQUE,      -- РНП-{год}-{номер}, FR-06, неизменяемый
    -- A-01..A-16 паспорт
    title             TEXT NOT NULL,             -- A-02, до 500
    short_title       TEXT,                      -- A-03, до 150
    public_annotation TEXT,                      -- A-04, до 1000
    program_id        TEXT NOT NULL REFERENCES programs(id),
    theme_link        TEXT,                      -- A-06, связь с общей темой
    route             TEXT NOT NULL DEFAULT 'simplified',  -- A-07 simplified|full
    route_auto        TEXT NOT NULL DEFAULT 'simplified',  -- автоматическое предложение FR-09
    route_reason_comment TEXT,                   -- FR-09: комментарий при ручном изменении
    route_fixed_by    TEXT,                      -- уполномоченное лицо, зафиксировавшее маршрут
    status            TEXT NOT NULL DEFAULT 'ST-01',         -- A-09 ST-01..ST-12
    status_changed_at TEXT,
    risk_level        TEXT NOT NULL DEFAULT 'green',         -- A-10 green|yellow|red
    risk_level_comment TEXT,                     -- A-10: ручная правка требует комментария
    risk_changed_at   TEXT,
    planned_start     TEXT,                      -- A-11
    planned_end       TEXT,                      -- A-11: начало не позднее завершения
    leader_person_id  TEXT REFERENCES persons(id),          -- A-12
    publish_mode      TEXT NOT NULL DEFAULT 'none',          -- A-15 none|project|results|all
    public_allowed_at TEXT,
    public_allowed_by TEXT,
    -- A-17..A-34 научное содержание
    problem           TEXT,                      -- A-17, до 2000
    question          TEXT,                      -- A-18, до 1000
    goal              TEXT,                      -- A-19, до 700
    tasks             TEXT,                      -- A-20, нумерованный список (JSON)
    research_object   TEXT,                      -- A-21, обязателен для полного маршрута
    research_subject  TEXT,                      -- A-22
    methods           TEXT,                      -- A-23, JSON: [{code,title,note}]
    methods_note      TEXT,
    data_basis        TEXT,                      -- A-24, источник/состав/период/доступ
    planned_result_type TEXT,                    -- A-25, код справочника result_type
    planned_result_note  TEXT,
    result_criteria   TEXT,                      -- A-26, JSON: [{code,title}]
    novelty           TEXT,                      -- A-27
    applicability     TEXT,                      -- A-28
    limitations       TEXT,                      -- A-29
    personal_data     INTEGER NOT NULL DEFAULT 0,  -- A-30
    personal_data_note TEXT,
    human_subjects    INTEGER NOT NULL DEFAULT 0,  -- A-31
    human_subjects_note TEXT,
    legal_basis_status TEXT,                     -- A-32
    legal_basis_link  TEXT,
    confidentiality   TEXT,                      -- A-33
    ip_note           TEXT,
    resource_request  TEXT,                      -- A-34, JSON {category,volume,period}
    -- признаки полного маршрута T-01..T-06 (FR-09, A-08)
    flag_external_funding   INTEGER NOT NULL DEFAULT 0,  -- T-01
    flag_partner            INTEGER NOT NULL DEFAULT 0,  -- T-01
    flag_personal_data      INTEGER NOT NULL DEFAULT 0,  -- T-02
    flag_human_subjects     INTEGER NOT NULL DEFAULT 0,  -- T-02
    flag_ethics_required    INTEGER NOT NULL DEFAULT 0,  -- T-02
    flag_extra_resources    INTEGER NOT NULL DEFAULT 0,  -- T-03
    flag_critical_infra     INTEGER NOT NULL DEFAULT 0,  -- T-04
    flag_high_risk          INTEGER NOT NULL DEFAULT 0,  -- T-04
    flag_external_product   INTEGER NOT NULL DEFAULT 0,  -- T-05
    flag_confidential       INTEGER NOT NULL DEFAULT 0,  -- T-06
    flag_ip_restricted     INTEGER NOT NULL DEFAULT 0,  -- T-06
    -- служебное
    version         INTEGER NOT NULL DEFAULT 1,  -- FR-32 защита от параллельной перезаписи
    archived_at     TEXT,                        -- FR-31 архивирование без потери связей
    created_at      TEXT NOT NULL,
    created_by      TEXT NOT NULL REFERENCES users(id),
    updated_at      TEXT NOT NULL,
    updated_by      TEXT,
    search_blob     TEXT,                        -- FR-25 полнотекстовый поиск по карточке
    CHECK (route IN ('simplified', 'full')),
    CHECK (route_auto IN ('simplified', 'full')),
    CHECK (status IN ('ST-01','ST-02','ST-03','ST-04','ST-05','ST-06',
                      'ST-07','ST-08','ST-09','ST-10','ST-11','ST-12')),
    CHECK (risk_level IN ('green', 'yellow', 'red')),
    CHECK (publish_mode IN ('none', 'project', 'results', 'all')),
    CHECK ((planned_start IS NULL OR planned_end IS NULL) OR planned_start <= planned_end)
);
CREATE INDEX IF NOT EXISTS ix_projects_program ON projects(program_id);
CREATE INDEX IF NOT EXISTS ix_projects_status  ON projects(status);
CREATE INDEX IF NOT EXISTS ix_projects_route   ON projects(route);
CREATE INDEX IF NOT EXISTS ix_projects_risk    ON projects(risk_level);
CREATE INDEX IF NOT EXISTS ix_projects_leader  ON projects(leader_person_id);
CREATE INDEX IF NOT EXISTS ix_projects_archived ON projects(archived_at);
CREATE INDEX IF NOT EXISTS ix_projects_publish ON projects(publish_mode);

-- Основания полного маршрута хранятся отдельной записью (A-08), чтобы историю
-- оснований можно было показать и проаудитить.
CREATE TABLE IF NOT EXISTS project_full_route_reasons (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    reason     TEXT NOT NULL,          -- T-01..T-06
    note       TEXT,
    added_at   TEXT NOT NULL,
    added_by   TEXT,
    PRIMARY KEY (project_id, reason),
    CHECK (reason IN ('T-01','T-02','T-03','T-04','T-05','T-06'))
);

-- A-14 партнёры — список организаций
CREATE TABLE IF NOT EXISTS project_partners (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    organization  TEXT NOT NULL,
    partner_type  TEXT,
    country       TEXT,
    contract_ref  TEXT,
    is_public     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    created_by    TEXT
);
CREATE INDEX IF NOT EXISTS ix_partners_project ON project_partners(project_id);

-- ---------------------------------------------------------------------
--  Команда  (M-02 раздел 3 карточки, FR-11)
-- ---------------------------------------------------------------------

-- Связь многие ко многим между людьми и проектами (раздел 6, Participation).
CREATE TABLE IF NOT EXISTS participations (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    person_id     TEXT NOT NULL REFERENCES persons(id),
    role          TEXT NOT NULL,          -- leader|member|supervisor|curator
    task          TEXT,                   -- порученная задача (A-13)
    started_at    TEXT,
    finished_at   TEXT,                   -- период участия (A-13)
    effort_share  REAL,                   -- подтверждённый вклад, доля
    contribution_confirmed INTEGER NOT NULL DEFAULT 0,
    is_public     INTEGER NOT NULL DEFAULT 0,   -- A-13/открытая команда
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    archived_at   TEXT,
    UNIQUE (project_id, person_id),
    CHECK (role IN ('leader', 'member', 'supervisor', 'curator'))
);
CREATE INDEX IF NOT EXISTS ix_participations_person ON participations(person_id);
CREATE INDEX IF NOT EXISTS ix_participations_project ON participations(project_id);

-- ---------------------------------------------------------------------
--  Контрольные точки  (M-06, FR-12, A-35..A-42)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS milestones (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,        -- A-35, до 300
    planned_date    TEXT NOT NULL,        -- A-36, в пределах сроков проекта
    actual_date     TEXT,                 -- A-40
    responsible_person_id TEXT REFERENCES persons(id),  -- A-37, только действующий участник
    planned_evidence TEXT,                -- A-38, плановое подтверждение
    status          TEXT NOT NULL DEFAULT 'planned',     -- A-39
    confirmation    TEXT,                 -- A-41, обязательно при выполнении
    postpone_reason TEXT,                 -- A-42, обязательна при изменении срока
    created_at      TEXT NOT NULL,
    created_by      TEXT,
    updated_at      TEXT,
    archived_at     TEXT,
    CHECK (status IN ('planned', 'in_progress', 'done', 'overdue', 'cancelled'))
);
CREATE INDEX IF NOT EXISTS ix_milestones_project ON milestones(project_id);
CREATE INDEX IF NOT EXISTS ix_milestones_planned ON milestones(planned_date);
CREATE INDEX IF NOT EXISTS ix_milestones_status  ON milestones(status);

-- История переноса контрольной точки (FR-12)
CREATE TABLE IF NOT EXISTS milestone_postponements (
    id           TEXT PRIMARY KEY,
    milestone_id TEXT NOT NULL REFERENCES milestones(id) ON DELETE CASCADE,
    old_date     TEXT NOT NULL,
    new_date     TEXT NOT NULL,
    reason       TEXT NOT NULL,
    changed_at   TEXT NOT NULL,
    changed_by   TEXT
);

-- ---------------------------------------------------------------------
--  Риски  (M-06, FR-13, A-65)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS risks (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category      TEXT NOT NULL,          -- код справочника risk_category
    description   TEXT NOT NULL,
    probability   TEXT NOT NULL DEFAULT 'medium',  -- low|medium|high
    impact        TEXT NOT NULL DEFAULT 'medium',  -- low|medium|high
    measures      TEXT,                   -- меры реагирования
    owner_person_id TEXT REFERENCES persons(id),
    review_date   TEXT,                   -- срок проверки
    status        TEXT NOT NULL DEFAULT 'open',    -- open|mitigated|closed
    level         TEXT NOT NULL DEFAULT 'yellow',  -- green|yellow|red (жёлтый по умолчанию)
    level_comment TEXT,                   -- A-65: ручное изменение уровня требует комментария
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    archived_at   TEXT,
    CHECK (probability IN ('low', 'medium', 'high')),
    CHECK (impact IN ('low', 'medium', 'high')),
    CHECK (status IN ('open', 'mitigated', 'closed')),
    CHECK (level IN ('green', 'yellow', 'red'))
);
CREATE INDEX IF NOT EXISTS ix_risks_project ON risks(project_id);

-- ---------------------------------------------------------------------
--  Экспертизы  (M-03, FR-14, п.7.1, A-63)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reviews (
    id                TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    object_type       TEXT NOT NULL,      -- project|result
    object_id         TEXT,               -- id результата при object_type=result
    stage             TEXT NOT NULL,      -- preliminary|final|publication
    expert_person_id  TEXT REFERENCES persons(id),
    expert_declared_no_conflict INTEGER,  -- п.4.1 п.4: подтверждение отсутствия конфликта
    conflict_note     TEXT,               -- заявление о самоотводе
    recused_at        TEXT,               -- факт отвода фиксируется в журнале (п.4.1 п.6)
    recused_by        TEXT,
    -- четыре обязательных блока краткого заключения (п.7.1) + рекомендация
    block_goal_fit    TEXT,               -- соответствие цели
    block_method_data TEXT,               -- метод и данные
    block_result_quality TEXT,            -- качество результата
    block_risks_limits   TEXT,            -- риски и ограничения
    recommendation    TEXT,               -- support|support_with_conditions|revise|not_support
    verdict_text      TEXT,
    assigned_at       TEXT NOT NULL,
    due_at            TEXT,               -- срок: до 10 рабочих дней (п.5.5)
    accepted_at       TEXT,               -- после фиксации заключение НЕ редактируется
    finalized_at      TEXT,
    replaced_by_review_id TEXT,           -- замена эксперта (п.5.5)
    created_at        TEXT NOT NULL,
    created_by        TEXT,
    version_no        INTEGER NOT NULL DEFAULT 1,  -- исправление оформляется новой версией
    CHECK (object_type IN ('project', 'result')),
    CHECK (stage IN ('preliminary', 'final', 'publication')),
    CHECK (recommendation IS NULL OR
           recommendation IN ('support', 'support_with_conditions', 'revise', 'not_support'))
);
CREATE INDEX IF NOT EXISTS ix_reviews_project ON reviews(project_id);
CREATE INDEX IF NOT EXISTS ix_reviews_expert  ON reviews(expert_person_id);
CREATE INDEX IF NOT EXISTS ix_reviews_object  ON reviews(object_type, object_id);

-- ---------------------------------------------------------------------
--  Решения  (M-03, FR-15, A-64)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS decisions (
    id                TEXT PRIMARY KEY,
    project_id        TEXT REFERENCES projects(id) ON DELETE CASCADE,
    object_type       TEXT NOT NULL,      -- project|result|program
    object_id         TEXT,
    level             TEXT NOT NULL,      -- curator|prorector|rector|council|secretary
    kind              TEXT NOT NULL,      -- launch|accept|return|suspend|resume|pilot|
                                         -- reserve|reject|close|publish|return_to_work
    wording           TEXT NOT NULL,
    basis             TEXT NOT NULL,      -- A-64: решение не создаётся без основания
    conditions        TEXT,               -- условия
    responsible_person_id TEXT REFERENCES persons(id),
    due_at            TEXT,               -- срок исполнения
    executed_at       TEXT,
    execution_note    TEXT,
    decided_at        TEXT NOT NULL,
    decided_by        TEXT NOT NULL REFERENCES users(id),
    created_at        TEXT NOT NULL,
    CHECK (level IN ('curator', 'prorector', 'rector', 'council', 'secretary')),
    CHECK (object_type IN ('project', 'result', 'program'))
);
CREATE INDEX IF NOT EXISTS ix_decisions_project ON decisions(project_id);
CREATE INDEX IF NOT EXISTS ix_decisions_object  ON decisions(object_type, object_id);

-- ---------------------------------------------------------------------
--  Результаты  (M-04, FR-16, FR-17, A-43..A-54)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS results (
    id                TEXT PRIMARY KEY,
    code              TEXT NOT NULL UNIQUE,
    result_type       TEXT NOT NULL,      -- A-44, код справочника result_type
    title             TEXT NOT NULL,      -- A-45, до 500
    description       TEXT NOT NULL,      -- A-46, до 1500
    authors           TEXT NOT NULL,      -- A-48, упорядоченный список JSON person_id
    readiness_stage   TEXT NOT NULL,      -- A-49, planned|produced|applied|accepted|published|implemented
    planned_date      TEXT,
    actual_date       TEXT,               -- A-50, обязательна после принятия
    acceptance_criterion TEXT NOT NULL,   -- A-51, проверяемый критерий
    confirmation      TEXT,               -- A-52, обязательно для принятого результата
    review_id         TEXT REFERENCES reviews(id),  -- A-53 заключение
    review_status     TEXT,               -- A-53: accepted|pending
    review_comment    TEXT,
    publish_allowed   INTEGER NOT NULL DEFAULT 0,  -- A-54 разрешение на публикацию
    publish_allowed_by TEXT,
    publish_allowed_at TEXT,
    is_public         INTEGER NOT NULL DEFAULT 0,
    doi              TEXT,                -- A-60
    edn              TEXT,
    url              TEXT,                -- A-60
    archived_at       TEXT,
    created_at        TEXT NOT NULL,
    created_by        TEXT,
    updated_at        TEXT,
    version           INTEGER NOT NULL DEFAULT 1,
    search_blob       TEXT,
    CHECK (readiness_stage IN ('planned', 'produced', 'applied',
                               'accepted', 'published', 'implemented'))
);
CREATE INDEX IF NOT EXISTS ix_results_type ON results(result_type);
CREATE INDEX IF NOT EXISTS ix_results_public ON results(is_public);
CREATE INDEX IF NOT EXISTS ix_results_doi ON results(doi);

-- Многие ко многим с проектами; учитывается один раз (FR-17, п.6.1 п.3).
CREATE TABLE IF NOT EXISTS result_projects (
    result_id  TEXT NOT NULL REFERENCES results(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    linked_at  TEXT NOT NULL,
    linked_by  TEXT,
    PRIMARY KEY (result_id, project_id)
);
CREATE INDEX IF NOT EXISTS ix_result_projects_project ON result_projects(project_id);

-- ---------------------------------------------------------------------
--  Публикации  (FR-18, A-55..A-62) — расширение результата типа «публикация»
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS publications (
    result_id        TEXT PRIMARY KEY REFERENCES results(id) ON DELETE CASCADE,
    kind             TEXT,               -- A-55, код справочника publication_kind
    stage            TEXT NOT NULL,      -- A-56 замысел|рецензирование|подана|доработка|принята|опубликована
    target_venue     TEXT,               -- A-57 целевое издание, обязательно с момента подачи
    submitted_at     TEXT,               -- A-58 фактическая подача
    planned_submit_at TEXT,              -- A-58 плановая подача
    accepted_at      TEXT,               -- A-59
    published_at     TEXT,               -- A-59
    biblio_volume    TEXT,               -- A-61 том, номер, страницы
    biblio_issue     TEXT,
    biblio_pages     TEXT,
    internal_review_id TEXT REFERENCES reviews(id),  -- A-62
    updated_at       TEXT
);
CREATE INDEX IF NOT EXISTS ix_publications_stage ON publications(stage);

-- ---------------------------------------------------------------------
--  Диссертации  (FR-19, A-67)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dissertations (
    id                  TEXT PRIMARY KEY,
    aspirant_person_id  TEXT NOT NULL REFERENCES persons(id),
    topic               TEXT NOT NULL,
    specialty           TEXT NOT NULL,
    supervisor_person_id TEXT REFERENCES persons(id),
    defense_year        INTEGER,
    status              TEXT NOT NULL DEFAULT 'in_progress',
    -- in_progress|admitted_to_defense|defense_scheduled|defended|negative|revision
    created_at          TEXT NOT NULL,
    created_by          TEXT,
    archived_at         TEXT,
    CHECK (status IN ('in_progress', 'admitted_to_defense', 'defense_scheduled',
                      'defended', 'negative', 'revision'))
);
CREATE INDEX IF NOT EXISTS ix_dissertations_person ON dissertations(aspirant_person_id);

CREATE TABLE IF NOT EXISTS dissertation_projects (
    dissertation_id TEXT NOT NULL REFERENCES dissertations(id) ON DELETE CASCADE,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    PRIMARY KEY (dissertation_id, project_id)
);

CREATE TABLE IF NOT EXISTS dissertation_stages (
    id             TEXT PRIMARY KEY,
    dissertation_id TEXT NOT NULL REFERENCES dissertations(id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    planned_date   TEXT,
    actual_date    TEXT,
    status         TEXT NOT NULL DEFAULT 'planned',
    created_at     TEXT NOT NULL
);

-- ---------------------------------------------------------------------
--  Задачи обучающихся  (FR-20, A-66) — задача 6–16 недель
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS student_tasks (
    id                 TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    dissertation_id    TEXT REFERENCES dissertations(id) ON DELETE SET NULL,
    assignment         TEXT NOT NULL,
    student_person_id  TEXT NOT NULL REFERENCES persons(id),
    supervisor_person_id TEXT REFERENCES persons(id),
    planned_start      TEXT NOT NULL,
    planned_end        TEXT NOT NULL,
    planned_result     TEXT,
    actual_result      TEXT,
    status             TEXT NOT NULL DEFAULT 'planned',
    -- planned|in_progress|done|cancelled
    is_public          INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL,
    created_by         TEXT,
    archived_at        TEXT,
    -- Одна запись на одну задачу (A-66)
    CHECK (status IN ('planned', 'in_progress', 'done', 'cancelled'))
);
CREATE INDEX IF NOT EXISTS ix_student_tasks_project ON student_tasks(project_id);
CREATE INDEX IF NOT EXISTS ix_student_tasks_student ON student_tasks(student_person_id);

-- ---------------------------------------------------------------------
--  Материалы  (FR-21, A-68) — ссылки и защищённые вложения с версиями
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS evidences (
    id            TEXT PRIMARY KEY,
    object_type   TEXT NOT NULL,      -- project|milestone|review|result|decision|dissertation|student_task
    object_id     TEXT NOT NULL,
    title         TEXT NOT NULL,
    kind          TEXT NOT NULL,      -- link|file
    url           TEXT,               -- для kind=link
    storage_path  TEXT,               -- для kind=file
    version       INTEGER NOT NULL DEFAULT 1,  -- FR-21 версионирование
    checksum      TEXT,
    size_bytes    INTEGER,
    access_level  TEXT NOT NULL DEFAULT 'internal',  -- internal|restricted|public
    uploaded_by   TEXT,
    uploaded_at   TEXT NOT NULL,
    superseded_at TEXT,
    archived_at   TEXT,
    CHECK (kind IN ('link', 'file')),
    CHECK (access_level IN ('internal', 'restricted', 'public'))
);
CREATE INDEX IF NOT EXISTS ix_evidences_object ON evidences(object_type, object_id);

-- ---------------------------------------------------------------------
--  Аудит  (M-10, FR-23, п.11.3, A-69) — неизменяемый журнал
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_events (
    id            TEXT PRIMARY KEY,
    happened_at   TEXT NOT NULL,      -- дата и время
    user_id       TEXT,               -- пользователь
    user_login    TEXT,
    group_name    TEXT NOT NULL,      -- auth|card|review_decision|publish|admin
    object_type   TEXT NOT NULL,
    object_id     TEXT,
    action        TEXT NOT NULL,      -- операция
    old_value     TEXT,               -- прежнее значение
    new_value     TEXT,               -- новое значение
    basis         TEXT,               -- основание
    outcome       TEXT NOT NULL DEFAULT 'ok',   -- результат операции
    ip_address    TEXT,
    -- SEC: секреты не выводятся в журналы (SEC-05) — пишем только факт входа.
    CHECK (outcome IN ('ok', 'denied', 'error'))
);
CREATE INDEX IF NOT EXISTS ix_audit_object ON audit_events(object_type, object_id);
CREATE INDEX IF NOT EXISTS ix_audit_happened ON audit_events(happened_at);
CREATE INDEX IF NOT EXISTS ix_audit_user ON audit_events(user_id);

-- ---------------------------------------------------------------------
--  Импорт  (FR-29, п.7.2)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS import_batches (
    id            TEXT PRIMARY KEY,       -- идентификатор пакета (п.7.2 п.6)
    file_name     TEXT NOT NULL,
    total_rows    INTEGER NOT NULL DEFAULT 0,
    ok_rows       INTEGER NOT NULL DEFAULT 0,
    warning_rows  INTEGER NOT NULL DEFAULT 0,
    error_rows    INTEGER NOT NULL DEFAULT 0,
    duplicate_rows INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'preview',  -- preview|confirmed|failed
    protocol      TEXT,                   -- построчный протокол (JSON)
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    confirmed_at  TEXT
);