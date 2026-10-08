/**
 * Открытая витрина раздела «Наука» (п.9.1).
 *
 * Читает публичный API только для чтения. Аутентификация не используется и не
 * нужна: витрина получает ровно те поля, которые уполномоченное лицо разрешило
 * к публикации (SEC-03). Адаптивна от 360 пикселей (п.10.2 п.5).
 */
import { useEffect, useMemo, useState } from 'react';
import { PublicProject, PublicResult } from '../api';
import { Empty, Spinner } from '../components/ui';

interface ListResponse {
  data: PublicProject[];
  meta: {
    total: number;
    limit: number;
    offset: number;
    filters?: Record<string, string>;
    generated_at: string;
  };
}

const STAGES = [
  { key: '', label: 'Все результаты' },
  { key: 'publication', label: 'Публикации' },
  { key: 'methodology', label: 'Методики' },
  { key: 'model', label: 'Модели' },
  { key: 'dataset', label: 'Наборы данных' },
  { key: 'digital_product', label: 'Цифровые продукты' },
  { key: 'implementation', label: 'Внедрение' },
];

export default function PublicPage() {
  const [projects, setProjects] = useState<PublicProject[] | null>(null);
  const [results, setResults] = useState<PublicResult[] | null>(null);
  const [programs, setPrograms] = useState<
    { id?: string; code: string; title: string; projects_count: number }[] | null
  >(null);
  const [programFilter, setProgramFilter] = useState('');
  const [resultType, setResultType] = useState('');
  const [error, setError] = useState<string>('');
  const [generatedAt, setGeneratedAt] = useState('');

  useEffect(() => {
    const qs = new URLSearchParams({ limit: '100' });
    if (programFilter) qs.set('program', programFilter);
    void fetch(`/api/public/v1/projects?${qs}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data: ListResponse) => {
        setProjects(data.data);
        setGeneratedAt(data.meta.generated_at);
      })
      .catch(() => setError('Публичные сведения временно недоступны'));
  }, [programFilter]);

  useEffect(() => {
    const qs = new URLSearchParams({ limit: '100' });
    if (resultType) qs.set('type', resultType);
    void fetch(`/api/public/v1/results?${qs}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data: { data: PublicResult[] }) => setResults(data.data))
      .catch(() => setResults([]));
  }, [resultType]);

  useEffect(() => {
    void fetch('/api/public/v1/programs?limit=100')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data: { data: { id?: string; code: string; title: string; projects_count: number }[] }) =>
        setPrograms(data.data))
      .catch(() => setPrograms([]));
  }, []);

  const grouped = useMemo(() => {
    const map = new Map<string, PublicProject[]>();
    for (const project of projects ?? []) {
      const key = project.program?.title ?? 'Без программы';
      const list = map.get(key) ?? [];
      list.push(project);
      map.set(key, list);
    }
    return Array.from(map.entries());
  }, [projects]);

  return (
    <div className="public">
      <header className="public__header">
        <h1>Научные проекты Южного университета (ИУБиП)</h1>
        <p className="muted">
          Открытый раздел. Здесь публикуются только те сведения, на которые
          уполномоченное лицо дало разрешение.
        </p>
      </header>

      {error && <div className="alert alert--error">{error}</div>}

      <div className="card">
        <div className="filters">
          <div className="field">
            <label className="field__label" htmlFor="prog">Научная программа</label>
            <select id="prog" value={programFilter}
              onChange={(e) => setProgramFilter(e.target.value)}>
              <option value="">Все программы</option>
              {(programs ?? []).map((p) => (
                <option key={p.code} value={p.code}>{p.title}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <h2>Проекты</h2>
      {projects === null ? (
        <Spinner />
      ) : projects.length === 0 ? (
        <Empty>Опубликованных проектов пока нет.</Empty>
      ) : (
        grouped.map(([programTitle, items]) => (
          <section key={programTitle} style={{ marginBottom: 20 }}>
            <h3 className="small muted" style={{ textTransform: 'uppercase', letterSpacing: 0.4 }}>
              {programTitle}
            </h3>
            {items.map((project) => <ProjectCardView key={project.code} project={project} />)}
          </section>
        ))
      )}

      <h2>Подтверждённые результаты</h2>
      <div className="card">
        <div className="filters">
          <div className="field">
            <label className="field__label" htmlFor="rtype">Вид результата</label>
            <select id="rtype" value={resultType}
              onChange={(e) => setResultType(e.target.value)}>
              {STAGES.map((s) => (
                <option key={s.key} value={s.key}>{s.label}</option>
              ))}
            </select>
          </div>
        </div>
      </div>
      {results === null ? (
        <Spinner />
      ) : results.length === 0 ? (
        <Empty>Опубликованных результатов пока нет.</Empty>
      ) : (
        results.map((result) => (
          <article className="public__card" key={result.code}>
            <h3 style={{ margin: '0 0 4px' }}>{result.title}</h3>
            <p style={{ margin: 0 }}>{result.description}</p>
            <div className="public__meta">
              <span>{result.type}</span>
              {result.year && <span>{result.year}</span>}
              {result.identifiers?.doi && <span>DOI: {result.identifiers.doi}</span>}
              {result.identifiers?.url && (
                <a href={result.identifiers.url} target="_blank" rel="noreferrer">
                  Открыть материал
                </a>
              )}
            </div>
          </article>
        ))
      )}

      <footer className="public__footer">
        <p>
          Сведения предоставлены из электронного реестра научных проектов.
          Реестр — операционный источник данных; сайт не хранит вторую копию
          карточки.
        </p>
        {generatedAt && <p className="small">Данные сформированы: {generatedAt}</p>}
        <p className="small">
          <a href="/api/public/v1/manifest">Описание публичного API</a>
          {' · '}
          <a href="/">Вход в закрытую часть реестра</a>
        </p>
      </footer>
    </div>
  );
}

function ProjectCardView({ project }: { project: PublicProject }) {
  return (
    <article className="public__card">
      <h3 style={{ margin: '0 0 4px' }}>{project.title}</h3>
      {project.public_annotation && <p style={{ margin: '0 0 6px' }}>{project.public_annotation}</p>}
      <div className="public__meta">
        <span className="mono">{project.code}</span>
        <span>{project.status_title}</span>
        {project.start_year && <span>{project.start_year}{project.end_year ? `—${project.end_year}` : ''}</span>}
        {project.program && <span>{project.program.short_title || project.program.title}</span>}
      </div>

      {project.team && project.team.length > 0 && (
        <p className="small" style={{ margin: '8px 0 0' }}>
          <strong>Команда:</strong>{' '}
          {project.team.map((m) => `${m.full_name} (${m.role_title})`).join('; ')}
        </p>
      )}

      {project.results && project.results.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <strong className="small">Результаты:</strong>
          <ul className="small" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {project.results.map((r) => (
              <li key={r.code}>{r.title}{r.year ? ` (${r.year})` : ''}</li>
            ))}
          </ul>
        </div>
      )}

      {project.materials && project.materials.length > 0 && (
        <div className="small" style={{ marginTop: 6 }}>
          <strong>Материалы:</strong>{' '}
          {project.materials.map((m) => (
            <a key={m.url} href={m.url} target="_blank" rel="noreferrer">{m.title}</a>
          ))}
        </div>
      )}

      {project.keywords.length > 0 && (
        <div className="public__keywords">
          {project.keywords.slice(0, 8).map((k) => (
            <span className="badge badge--neutral" key={k}>{k}</span>
          ))}
        </div>
      )}
    </article>
  );
}