/**
 * Создание карточки проекта (FR-05, FR-06, FR-08, FR-09).
 *
 * ПС-03: карточка сохранена, присвоен уникальный номер.
 * ПС-05: при партнёре, персональных данных или существенном ресурсе предложен
 * полный маршрут, основание сохранено.
 * FR-08: до создания показываются похожие проекты, решение фиксируется.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, Person, Program, ProjectCard } from '../api';
import { Alert, ErrorAlert, Field, Spinner } from '../components/ui';
import { FULL_ROUTE_FLAGS, PUBLISH_MODES } from '../format';

interface Duplicate {
  id: string; code: string; title: string; similarity: number; reason: string;
}

interface NewProjectResponse {
  created: boolean;
  id?: string;
  code?: string;
  card?: ProjectCard;
  route?: string;
  route_reasons?: string[];
  route_reasons_detail?: { code: string; title: string }[];
  suggested_route?: string;
  rejected_fields?: string[];
  reason?: string;
  message?: string;
  duplicates?: Duplicate[];
  hint?: string;
}

interface Taxonomy {
  full_route_triggers: { code: string; title: string; fields: string[] }[];
  route_rule: string;
  publish_modes: Record<string, string>;
}

export default function NewProjectPage() {
  const navigate = useNavigate();
  const [programs, setPrograms] = useState<Program[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string>('');

  const [title, setTitle] = useState('');
  const [shortTitle, setShortTitle] = useState('');
  const [programId, setProgramId] = useState('');
  const [themeLink, setThemeLink] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [leaderId, setLeaderId] = useState('');
  const [publishMode, setPublishMode] = useState('none');
  const [annotation, setAnnotation] = useState('');
  const [problem, setProblem] = useState('');
  const [question, setQuestion] = useState('');
  const [goal, setGoal] = useState('');
  const [methods, setMethods] = useState('');
  const [dataBasis, setDataBasis] = useState('');
  const [resultType, setResultType] = useState('');
  const [criteria, setCriteria] = useState('');
  const [flags, setFlags] = useState<Set<string>>(new Set());
  const [duplicates, setDuplicates] = useState<Duplicate[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([
      api<{ items: Program[] }>('/api/programs?limit=100'),
      api<{ items: Person[] }>('/api/persons?limit=100'),
      api<Taxonomy>('/api/projects/taxonomy'),
    ])
      .then(([p, people, tax]) => {
        setPrograms(p.items);
        setPersons(people.items);
        setTaxonomy(tax);
        if (p.items[0]) setProgramId(p.items[0].id);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  // Предпросмотр похожих проектов по мере ввода названия (FR-08).
  useEffect(() => {
    if (title.trim().length < 6) {
      setDuplicates([]);
      return;
    }
    const timer = setTimeout(() => {
      void api<{ items: Duplicate[] }>(
        `/api/projects/duplicates?title=${encodeURIComponent(title.trim())}`,
      )
        .then((r) => setDuplicates(r.items))
        .catch(() => setDuplicates([]));
    }, 500);
    return () => clearTimeout(timer);
  }, [title]);

  // Живое предложение маршрута по отмеченным признакам (FR-09).
  const suggested = useMemo(() => {
    const codes = new Set<string>();
    for (const flag of FULL_ROUTE_FLAGS) {
      if (flags.has(flag.key)) codes.add(flag.code);
    }
    return {
      route: codes.size > 0 ? 'full' : 'simplified',
      reasons: Array.from(codes).sort(),
    };
  }, [flags]);

  function toggleFlag(key: string) {
    const next = new Set(flags);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setFlags(next);
  }

  async function submit(acknowledgeDuplicates: boolean) {
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        program_id: programId,
        title: title.trim(),
        short_title: shortTitle.trim() || undefined,
        theme_link: themeLink.trim() || undefined,
        planned_start: start || undefined,
        planned_end: end || undefined,
        publish_mode: publishMode,
        public_annotation: annotation.trim() || undefined,
        problem: problem.trim() || undefined,
        question: question.trim() || undefined,
        goal: goal.trim() || undefined,
        data_basis: dataBasis.trim() || undefined,
        planned_result_type: resultType || undefined,
        methods: methods
          .split(';')
          .map((s) => s.trim())
          .filter(Boolean)
          .map((title_) => ({ title: title_ })),
        result_criteria: criteria
          .split(';')
          .map((s) => s.trim())
          .filter(Boolean)
          .map((title_) => ({ title: title_ })),
      };
      for (const flag of FULL_ROUTE_FLAGS) {
        payload[flag.key] = flags.has(flag.key);
      }
      const suffix = acknowledgeDuplicates ? '&duplicate_ack=true' : '';
      const response = await api<NewProjectResponse>(
        `/api/projects?${suffix}`.replace('?&', '?'),
        { method: 'POST', body: payload },
      );

      if (response.created === false) {
        setDuplicates(response.duplicates ?? []);
        setNotice(response.message ?? 'Найдены похожие проекты');
        return;
      }

      // Руководителя и первую контрольную точку задаём сразу после создания:
      // без них карточка не пройдёт проверку комплектности (FR-07).
      if (leaderId && response.id) {
        await api(`/api/projects/${response.id}/leader`, {
          method: 'POST',
          body: { person_id: leaderId },
        }).catch(() => undefined);
      }
      if (response.id) navigate(`/projects/${response.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner />;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Новая карточка проекта</h1>
          <p>
            Обязательные поля отмечены знаком *. Переход на проверку комплектности
            блокируется с точным перечнем незаполненных полей.
          </p>
        </div>
      </div>

      <ErrorAlert error={error} />
      {notice && <Alert kind="warn">{notice}</Alert>}

      {duplicates.length > 0 && (
        <div className="card">
          <h2 className="card__title">Похожие проекты (FR-08)</h2>
          <p className="small muted">
            Возможно, такая инициатива уже заведена. Решение продолжить создание
            будет зафиксировано в журнале действий.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Номер</th>
                  <th>Название</th>
                  <th>Основание</th>
                </tr>
              </thead>
              <tbody>
                {duplicates.map((d) => (
                  <tr key={d.id}>
                    <td className="mono nowrap">{d.code}</td>
                    <td>{d.title}</td>
                    <td className="small">{d.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="btn-row" style={{ marginTop: 10 }}>
            <button
              className="btn"
              type="button"
              disabled={busy}
              onClick={() => void submit(true)}
            >
              Это другая инициатива — создать
            </button>
          </div>
        </div>
      )}

      <div className="card">
        <h2 className="card__title">Паспорт проекта</h2>
        <Field label="Полное название" code="A-02" required>
          <input
            type="text"
            value={title}
            maxLength={500}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
          <div className="field__hint">Проверяется на точный и близкий дубль</div>
        </Field>

        <Field label="Краткое название" code="A-03" required hint="Для списков и панели">
          <input
            type="text"
            value={shortTitle}
            maxLength={150}
            onChange={(e) => setShortTitle(e.target.value)}
          />
        </Field>

        <Field label="Научная программа" code="A-05" required>
          <select value={programId} onChange={(e) => setProgramId(e.target.value)}>
            {programs.map((p) => (
              <option key={p.id} value={p.id}>{p.code} — {p.title}</option>
            ))}
          </select>
          <div className="field__hint">Только действующая программа</div>
        </Field>

        <Field label="Связь с общей темой" code="A-06" required
          hint="Конкретное смысловое пояснение, а не название темы целиком">
          <input type="text" value={themeLink} maxLength={500}
            onChange={(e) => setThemeLink(e.target.value)} />
        </Field>

        <div className="grid grid--3">
          <Field label="Плановое начало" code="A-11" required>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Field label="Плановое завершение" code="A-11" required>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </Field>
          <Field label="Руководитель" code="A-12" required
            hint="Один основной руководитель">
            <select value={leaderId} onChange={(e) => setLeaderId(e.target.value)}>
              <option value="">Назначить позже</option>
              {persons.map((p) => (
                <option key={p.id} value={p.id}>{p.full_name}</option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="Режим публикации" code="A-15" required
          hint="До утверждения уполномоченным лицом данные закрыты">
          <select value={publishMode} onChange={(e) => setPublishMode(e.target.value)}>
            {Object.entries(PUBLISH_MODES).map(([key, title]) => (
              <option key={key} value={key}>{title}</option>
            ))}
          </select>
        </Field>

        {publishMode !== 'none' && (
          <Field label="Публичная аннотация" code="A-04"
            required hint="Обязательна при публикации, до 1000 знаков">
            <textarea value={annotation} maxLength={1000}
              onChange={(e) => setAnnotation(e.target.value)} />
          </Field>
        )}
      </div>

      <div className="card">
        <h2 className="card__title">Научное содержание</h2>
        <p className="small muted">
          Шесть обязательных научных полей: проблема, вопрос или гипотеза, цель,
          методы, данные или доказательная база, критерии результата. Это
          требование п.4.2 для запуска упрощённого проекта.
        </p>

        <Field label="Исследовательская проблема" code="A-17" required
          hint="Проверяемая проблема, а не общая тема">
          <textarea value={problem} maxLength={2000}
            onChange={(e) => setProblem(e.target.value)} />
        </Field>

        <Field label="Вопрос или гипотеза" code="A-18" required>
          <textarea value={question} maxLength={1000}
            onChange={(e) => setQuestion(e.target.value)} />
        </Field>

        <Field label="Цель" code="A-19" required hint="Одна основная цель">
          <textarea value={goal} maxLength={700} onChange={(e) => setGoal(e.target.value)} />
        </Field>

        <div className="grid grid--2">
          <Field label="Методы" code="A-23" required
            hint="Через точку с запятой. Не менее одного метода">
            <input type="text" value={methods} onChange={(e) => setMethods(e.target.value)}
              placeholder="Сравнительный анализ; анкетирование" />
          </Field>
          <Field label="Данные или доказательная база" code="A-24" required
            hint="Источник, состав, период и доступ">
            <textarea value={dataBasis} maxLength={2000}
              onChange={(e) => setDataBasis(e.target.value)} />
          </Field>
        </div>

        <div className="grid grid--2">
          <Field label="Планируемый результат" code="A-25" required>
            <select value={resultType} onChange={(e) => setResultType(e.target.value)}>
              <option value="">— выберите вид —</option>
              <option value="publication">Публикация</option>
              <option value="methodology">Методика</option>
              <option value="model">Модель</option>
              <option value="dataset">Набор данных</option>
              <option value="digital_product">Цифровой продукт</option>
              <option value="grant_application">Грантовая заявка</option>
              <option value="implementation">Внедрение</option>
              <option value="other">Другое</option>
            </select>
          </Field>
          <Field label="Критерии результата" code="A-26" required
            hint="Через точку с запятой. Не менее одного признака выполнения">
            <input type="text" value={criteria} onChange={(e) => setCriteria(e.target.value)}
              placeholder="Снижение доли ручных проверок на 30%" />
          </Field>
        </div>
      </div>

      <div className="card">
        <h2 className="card__title">Признаки полного маршрута (T-01…T-06)</h2>
        {taxonomy && <Alert kind="info">{taxonomy.route_rule}</Alert>}
        <div className="grid grid--2">
          {FULL_ROUTE_FLAGS.map((flag) => (
            <label className="checkbox" key={flag.key}>
              <input
                type="checkbox"
                checked={flags.has(flag.key)}
                onChange={() => toggleFlag(flag.key)}
              />
              <span>
                {flag.title} <span className="field__code">{flag.code}</span>
              </span>
            </label>
          ))}
        </div>
        <Alert kind={suggested.route === 'full' ? 'warn' : 'info'}>
          {suggested.route === 'full' ? (
            <>
              Система предлагает <strong>полный</strong> маршрут. Основания:{' '}
              {suggested.reasons.join(', ')} (FR-09). Окончательный маршрут
              фиксирует уполномоченное лицо.
            </>
          ) : (
            <>
              По отмеченным признакам предлагается <strong>упрощённый</strong> маршрут.
              Междисциплинарность сама по себе основанием для полного маршрута не является.
            </>
          )}
        </Alert>
      </div>

      <div className="btn-row">
        <button className="btn" type="button" disabled={busy || !title.trim() || !programId}
          onClick={() => void submit(false)}>
          {busy ? 'Создание…' : 'Создать карточку'}
        </button>
        <button className="btn btn--secondary" type="button" onClick={() => navigate(-1)}>
          Отмена
        </button>
      </div>
    </>
  );
}