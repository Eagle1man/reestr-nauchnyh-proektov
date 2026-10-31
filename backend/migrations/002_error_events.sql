-- Журнал ошибок установки (002).
--
-- ЗАЧЕМ. До этой миграции ошибки жили только в памяти процесса и терялись
-- при перезапуске: нельзя было ответить «часто ли это повторяется» и «было ли
-- так же месяц назад». Здесь появляется история, по которой работает разбор.
--
-- ЧЕГО ЗДЕСЬ НАМЕРЕННО НЕТ. Логина пользователя и любых его текстов: для
-- разбора достаточно роли. Это согласуется с SEC-05 и N-03 — сведения о сбое
-- не должны становиться сведениями о человеке. Наружу ничего не уходит:
-- таблица живёт в базе установки, выгружает её администратор.
--
-- СРОК ХРАНЕНИЯ. 90 дней (см. RETENTION_DAYS в app/errors.py). Чистка идёт
-- при записи и при чтении сводки, отдельного планировщика не требуется.

CREATE TABLE IF NOT EXISTS error_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint   TEXT    NOT NULL,   -- отпечаток причины, не отдельного случая
    kind          TEXT    NOT NULL,   -- server | client
    message       TEXT    NOT NULL,
    path          TEXT,
    role          TEXT,               -- роль, а не логин: личности здесь нет
    reference     TEXT,               -- код обращения, который видел пользователь
    app_version   TEXT,               -- сборка: после обновления ошибка могла исчезнуть
    occurred_at   TEXT    NOT NULL
);

-- Разбор всегда идёт от частого к редкому и в пределах срока хранения.
CREATE INDEX IF NOT EXISTS idx_error_events_fingerprint
    ON error_events (fingerprint, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_error_events_occurred
    ON error_events (occurred_at);
