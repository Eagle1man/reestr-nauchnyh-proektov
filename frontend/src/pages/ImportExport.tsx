/**
 * Импорт и выгрузка (FR-28, FR-29; п.7.2).
 *
 * П.7.2 п.4: до подтверждения импорт НЕ изменяет рабочие данные.
 * П.7.2 п.5: строки с ошибками не загружаются, пользователь получает
 * построчный протокол с названием поля и причиной.
 */
import { useEffect, useState } from 'react';
import { api, download, upload } from '../api';
import { Alert, ErrorAlert, Field } from '../components/ui';

interface Preview {
  batch_id: string;
  file_name: string;
  created: boolean;
  counts: { total: number; ok: number; warning: number; error: number; duplicate: number };
  message: string;
  protocol: {
    row: number;
    title: string;
    status: 'ok' | 'warning' | 'error' | 'duplicate';
    action: string;
    errors: { field: string; reason: string }[];
    warnings: string[];
    duplicates: { code: string; title: string; reason: string }[];
    project_id: string | null;
  }[];
}

const STATUS_TITLES: Record<string, string> = {
  ok: 'корректна', warning: 'предупреждение', error: 'ошибка', duplicate: 'возможный дубль',
};
const STATUS_TONES: Record<string, string> = {
  ok: 'green', warning: 'yellow', error: 'red', duplicate: 'yellow',
};

export default function ImportExportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [expectedRows, setExpectedRows] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [pending, setPending] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    void api<{ items: {
      id: string; file_name: string; total_rows: number; ok_rows: number;
      warning_rows: number; error_rows: number; duplicate_rows: number;
      status: string; created_at: string; confirmed_at: string | null;
    }[] }>('/api/import/batches').catch(() => undefined);
  }, []);

  async function run(confirm: boolean) {
    if (!pending && !file) return;
    const source = pending ?? file;
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append('file', source);
      form.append('confirm', confirm ? 'true' : 'false');
      if (expectedRows.trim()) form.append('expected_rows', expectedRows.trim());
      // При подтверждении возвращаем тот же идентификатор пакета, что показали
      // в предпросмотре. Без этого сервер считает загрузку новой: в списке
      // остаётся предпросмотр без подтверждения и появляется второй пакет,
      // хотя загрузка была одна (п.7.2 п.6).
      if (confirm && preview) form.append('batch_id', preview.batch_id);
      const result = await upload<Preview>('/api/import/preview', form);
      setPreview(result);
      setDone(result.created);
    } catch (err) {
      setError(err);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function downloadTemplate() {
    try {
      await download('/api/import/template', 'forma_inventarizacii.xlsx');
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Импорт и выгрузка</h1>
          <p>
            Импорт из утверждённой формы инвентаризации и выгрузка с учётом прав
            и активных фильтров.
          </p>
        </div>
        <div className="btn-row">
          <button className="btn btn--secondary" type="button" onClick={() => void downloadTemplate()}>
            Скачать шаблон формы
          </button>
          <button className="btn btn--secondary" type="button"
            onClick={() => void download('/api/export/projects?format=xlsx', 'projects.xlsx')}>
            Выгрузить XLSX
          </button>
          <button className="btn btn--secondary" type="button"
            onClick={() => void download('/api/export/projects?format=csv', 'projects.csv')}>
            Выгрузить CSV
          </button>
        </div>
      </div>

      <ErrorAlert error={error} />

      <div className="card">
        <h2 className="card__title">Шаг 1. Загрузить файл (FR-29)</h2>
        <Alert kind="info">
          Поддерживаются XLSX и CSV. Колонки файла должны совпадать с шаблоном
          формы инвентаризации. Перед загрузкой система покажет число корректных
          строк, предупреждений, ошибок и возможных дублей.
        </Alert>
        <div className="grid grid--2">
          <Field label="Файл" required>
            <input type="file" accept=".xlsx,.csv"
              onChange={(e) => {
                const selected = e.target.files?.[0] ?? null;
                setFile(selected);
                setPending(selected);
                setPreview(null);
                setDone(false);
              }} />
          </Field>
          <Field label="Ожидаемое число строк"
            hint="Защита от обрезанного файла: при несовпадении загрузка прервётся">
            <input type="number" min={0} value={expectedRows}
              onChange={(e) => setExpectedRows(e.target.value)} />
          </Field>
        </div>
        <button className="btn" type="button" disabled={!file || busy}
          onClick={() => void run(false)}>
          {busy ? 'Проверка…' : 'Проверить файл'}
        </button>
      </div>

      {preview && (
        <div className="card">
          <h2 className="card__title">Шаг 2. Предпросмотр (п.7.2 п.3)</h2>
          <div className="grid grid--4">
            <div className="stat"><div className="stat__value">{preview.counts.total}</div>
              <div className="stat__label">строк всего</div></div>
            <div className="stat stat--green"><div className="stat__value">{preview.counts.ok}</div>
              <div className="stat__label">корректных</div></div>
            <div className="stat stat--yellow"><div className="stat__value">
              {preview.counts.warning + preview.counts.duplicate}</div>
              <div className="stat__label">с предупреждениями</div></div>
            <div className="stat stat--red"><div className="stat__value">{preview.counts.error}</div>
              <div className="stat__label">с ошибками</div></div>
          </div>

          <Alert kind={done ? 'ok' : 'warn'}>{preview.message}</Alert>

          {preview.protocol.length > 0 && (
            <div className="table-wrap" style={{ maxHeight: 420, overflowY: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Строка</th><th>Название</th><th>Статус</th><th>Протокол</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.protocol.map((row) => (
                    <tr key={row.row}>
                      <td className="mono nowrap">{row.row}</td>
                      <td className="small">{row.title || '—'}</td>
                      <td className="nowrap">
                        <span className={`badge badge--${STATUS_TONES[row.status]}`}>
                          {STATUS_TITLES[row.status]}
                        </span>
                      </td>
                      <td className="small">
                        {row.errors.map((e, i) => (
                          <div key={i} style={{ color: 'var(--c-danger)' }}>
                            <strong>{e.field}</strong>: {e.reason}
                          </div>
                        ))}
                        {row.warnings.map((w, i) => (
                          <div key={`w${i}`} style={{ color: 'var(--c-warn)' }}>{w}</div>
                        ))}
                        {row.duplicates.map((d, i) => (
                          <div key={`d${i}`} className="muted">
                            {d.code} — {d.reason}
                          </div>
                        ))}
                        {row.project_id && <div className="muted">карточка создана</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {!done && (
            <>
              <Alert kind="warn">
                До подтверждения рабочие данные не изменялись. Строки с ошибками
                не будут загружены; по каждой такой строке в протоколе указано
                поле и причина.
              </Alert>
              <button className="btn" type="button" disabled={busy} onClick={() => void run(true)}>
                Подтвердить загрузку
              </button>
            </>
          )}
          {done && (
            <Alert kind="ok">
              Загрузка выполнена. Протокол сохранён с идентификатором пакета{' '}
              <span className="mono">{preview.batch_id}</span> и доступен в списке
              пакетов импорта.
            </Alert>
          )}
        </div>
      )}

      <div className="card">
        <h2 className="card__title">Что происходит при загрузке</h2>
        <ul className="small">
          <li>Форма инвентаризации совпадает с обязательными полями MVP (п.7.2 п.1).</li>
          <li>До подтверждения импорт не изменяет рабочие данные (п.7.2 п.4).</li>
          <li>Строки с ошибками не загружаются, протокол — построчный (п.7.2 п.5).</li>
          <li>Каждая загрузка получает идентификатор пакета, дату, автора и протокол (п.7.2 п.6).</li>
          <li>Профили людей и программы находятся повторным вводом: человек
            сопоставляется по служебному адресу или Ф. И. О. (FR-03).</li>
        </ul>
      </div>
    </>
  );
}