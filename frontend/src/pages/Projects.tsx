/**
 * Список проектов с фильтрами ТЗ (FR-25) и выгрузкой (FR-28).
 * ПС-14: показываются только соответствующие записи.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, download, Person, Program, ProjectRow } from '../api';
import { Badge, Empty, ErrorAlert, Field, Spinner } from '../components/ui';
import { PUBLISH_MODES, riskTone, statusTone } from '../format';

interface ListResponse {
  items: ProjectRow[];
  total: number;
  limit: number;
  offset: number;
}

interface Taxonomy {
  statuses: { code: string; title: string; content: string }[];
  routes: Record<string, string>;
  full_route_triggers: { code: string; title: string; fields: string[] }[];
  route_rule: string;
  publish_modes: Record<string, string>;
  risk_levels: Record<string, string>;
}

export default function ProjectsPage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<ListResponse | null>(null);
  const [programs, setPrograms] = useState<Program[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const query = useMemoFilters(params);

  const load = useCallback(() => {
    setError(null);
    api<ListResponse>(`/api/projects?${query.toString()}`)
      .then(setData)
      .catch(setError);
  }, [query]);

  useEffect(load, [load]);

  useEffect(() => {
    void api<{ items: Program[] }>('/api/programs?limit=100').then((r) => setPrograms(r.items));
    void api<{ items: Person[] }>('/api/persons?limit=100').then((r) => setPersons(r.items));
    void api<Taxonomy>('/api/projects/taxonomy').then(setTaxonomy).catch(() => undefined);
  }, []);

  function update(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete('offset');
    setParams(next);
  }

  async function exportFile(format: 'xlsx' | 'csv') {
    setBusy(true);
    try {
      const qs = new URLSearchParams(query);
      qs.set('format', format);
      await download(`/api/export/projects?${qs.toString()}`, `export.${format}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Проекты</h1>
          <p>
            {data ? `Найдено ${data.total}` : 'Загрузка…'}
            {query.get('q') && ` по запросу «${query.get('q')}»`}
          </p>
        </div>
        <div className="btn-row">
          <Link className="btn" to="/projects/new">
            Создать карточку
          </Link>
          <button
            className="btn btn--secondary"
            type="button"
            disabled={busy}
            onClick={() => void exportFile('xlsx')}
          >
            Выгрузить XLSX
          </button>
          <button
            className="btn btn--secondary"
            type="button"
            disabled={busy}
            onClick={() => void exportFile('csv')}
          >
            Выгрузить CSV
          </button>
        </div>
      </div>

      <div className="card no-print">
        <div className="filters">
          <Field label="Поиск">
            <input
              type="search"
              placeholder="название, проблема, цель, номер"
              defaultValue={query.get('q') ?? ''}
              onBlur={(e) => update('q', e.target.value.trim())}
              onKeyDown={(e) => {
                if (e.key === 'Enter') update('q', (e.target as HTMLInputElement).value.trim());
              }}
            />
          </Field>
          <Field label="Программа">
            <select value={query.get('program_id') ?? ''} onChange={(e) => update('program_id', e.target.value)}>
              <option value="">Все программы</option>
              {programs.map((p) => (
                <option key={p.id} value={p.id}>{p.code} — {p.short_title || p.title}</option>
              ))}
            </select>
          </Field>
          <Field label="Маршрут">
            <select value={query.get('route') ?? ''} onChange={(e) => update('route', e.target.value)}>
              <option value="">Любой</option>
              <option value="simplified">Упрощённый</option>
              <option value="full">Полный</option>
            </select>
          </Field>
          <Field label="Статус">
            <select value={query.get('status') ?? ''} onChange={(e) => update('status', e.target.value)}>
              <option value="">Любой</option>
              {(taxonomy?.statuses ?? []).map((s) => (
                <option key={s.code} value={s.code}>{s.code} — {s.title}</option>
              ))}
            </select>
          </Field>
          <Field label="Индикатор риска">
            <select value={query.get('risk_level') ?? ''} onChange={(e) => update('risk_level', e.target.value)}>
              <option value="">Любой</option>
              <option value="green">Зелёный</option>
              <option value="yellow">Жёлтый</option>
              <option value="red">Красный</option>
            </select>
          </Field>
          <Field label="Руководитель">
            <select value={query.get('leader_person_id') ?? ''} onChange={(e) => update('leader_person_id', e.target.value)}>
              <option value="">Любой</option>
              {persons.map((p) => (
                <option key={p.id} value={p.id}>{p.full_name}</option>
              ))}
            </select>
          </Field>
          <Field label="Срок завершения">
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                type="date"
                value={query.get('planned_from') ?? ''}
                onChange={(e) => update('planned_from', e.target.value)}
                aria-label="С завершения не ранее"
              />
              <input
                type="date"
                value={query.get('planned_to') ?? ''}
                onChange={(e) => update('planned_to', e.target.value)}
                aria-label="С завершения не позже"
              />
            </div>
          </Field>
          <Field label="Показать">
            <div>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={query.get('active_only') === '1'}
                  onChange={(e) => update('active_only', e.target.checked ? '1' : '')}
                />
                Только активные
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={query.get('overdue_only') === '1'}
                  onChange={(e) => update('overdue_only', e.target.checked ? '1' : '')}
                />
                С просроченными точками
              </label>
            </div>
          </Field>
        </div>
      </div>

      <ErrorAlert error={error} />

      {!data ? (
        <Spinner />
      ) : data.items.length === 0 ? (
        <Empty>По заданным условиям проекты не найдены.</Empty>
      ) : (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Номер</th>
                  <th>Название</th>
                  <th>Программа</th>
                  <th>Маршрут</th>
                  <th>Статус</th>
                  <th>Риск</th>
                  <th>Сроки</th>
                  <th>Публикация</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono nowrap">
                      <Link to={`/projects/${row.id}`}>{row.code}</Link>
                    </td>
                    <td>
                      {row.title}
                      {row.archived_at && (
                        <div><Badge tone="neutral">архив</Badge></div>
                      )}
                      {row.overdue_count > 0 && (
                        <div className="small" style={{ color: 'var(--c-danger)' }}>
                          просрочено точек: {row.overdue_count}
                        </div>
                      )}
                    </td>
                    <td className="small">{row.program_title}</td>
                    <td className="small nowrap">{row.route_title}</td>
                    <td className="nowrap">
                      <Badge tone={statusTone(row.status)}>{row.status_title}</Badge>
                    </td>
                    <td className="nowrap">
                      <Badge tone={riskTone(row.risk_level)}>{row.risk_title}</Badge>
                    </td>
                    <td className="small nowrap">
                      {row.planned_start_fmt || '—'} — {row.planned_end_fmt || '—'}
                    </td>
                    <td className="small nowrap">
                      {PUBLISH_MODES[row.publish_mode]}
                      {row.leader_name ? (
                        <div className="muted">{row.leader_name}</div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager
            total={data.total}
            offset={Number(query.get('offset') ?? '0')}
            limit={data.limit}
            onChange={(offset) => update('offset', String(offset))}
          />
        </div>
      )}
    </>
  );
}

function Pager({ total, offset, limit, onChange }: {
  total: number; offset: number; limit: number; onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <div className="btn-row" style={{ marginTop: 10, justifyContent: 'flex-end' }}>
      <span className="small muted">
        Страница {page} из {pages}
      </span>
      <button
        className="btn btn--secondary btn--sm"
        type="button"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        Назад
      </button>
      <button
        className="btn btn--secondary btn--sm"
        type="button"
        disabled={offset + limit >= total}
        onClick={() => onChange(offset + limit)}
      >
        Вперёд
      </button>
    </div>
  );
}

function useMemoFilters(params: URLSearchParams): URLSearchParams {
  // Новая ссылка на объект создаётся при каждом рендере, а load() зависит от
  // query — без мемоизации это даёт бесконечный цикл запросов.
  return useMemo(() => new URLSearchParams(params), [params]);
}