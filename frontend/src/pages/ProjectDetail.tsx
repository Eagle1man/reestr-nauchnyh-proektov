/**
 * Карточка проекта — 10 разделов Приложения А (раздел 6.2 ТЗ).
 *
 * Разделы: паспорт, научное содержание, команда, план, риски и ресурсы,
 * экспертизы и решения, результаты, материалы, публичное представление, история.
 *
 * ПС-02: каждый видит только разрешённые поля и действия — сервер решает права,
 * интерфейс лишь показывает то, что сервер разрешил (can_edit, actions).
 */
import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  api, AuditEvent, Decision, Milestone, Participation, Person, ProjectCard,
  ResultRecord, Review, RiskRow,
} from '../api';
import {
  Alert, Badge, ConfirmButton, Detail, Empty, ErrorAlert, Field, Spinner, Tabs,
} from '../components/ui';
import {
  asList, fmtDate, fmtDateTime, FULL_ROUTE_FLAGS, PUBLISH_MODES, riskTone, statusTone,
} from '../format';

const TABS = [
  { key: 'passport', label: 'Паспорт' },
  { key: 'science', label: 'Научное содержание' },
  { key: 'team', label: 'Команда' },
  { key: 'plan', label: 'План' },
  { key: 'risks', label: 'Риски и ресурсы' },
  { key: 'reviews', label: 'Экспертизы и решения' },
  { key: 'results', label: 'Результаты' },
  { key: 'materials', label: 'Материалы' },
  { key: 'public', label: 'Публичное представление' },
  { key: 'history', label: 'История' },
];

export default function ProjectDetailPage() {
  const { id = '' } = useParams();
  const [card, setCard] = useState<ProjectCard | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState('passport');
  const [actionError, setActionError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError(null);
    api<ProjectCard>(`/api/projects/${id}`)
      .then(setCard)
      .catch(setError);
  }, [id]);

  useEffect(load, [load]);

  if (error) return <ErrorAlert error={error} />;
  if (!card) return <Spinner />;

  async function doTransition(action: string, reason?: string) {
    setBusy(true);
    setActionError(null);
    setNotice('');
    try {
      const result = await api<{ applied: boolean; to_status_title?: string }>(
        `/api/projects/${id}/transition`,
        { method: 'POST', body: { action, reason: reason || null } },
      );
      setNotice(`Статус изменён: ${result.to_status_title}`);
      load();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(false);
    }
  }

  async function approvePublication() {
    setBusy(true);
    setActionError(null);
    try {
      await api(`/api/projects/${id}/publish`, {
        method: 'POST',
        body: { publish_mode: card!.publish_mode },
      });
      setNotice('Разрешение на публикацию зафиксировано');
      load();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 style={{ marginBottom: 2 }}>
            <span className="mono">{card.code}</span> {card.short_title || card.title}
          </h1>
          <p>
            <Badge tone={statusTone(card.status)}>{card.status}</Badge>{' '}
            {card.status_title} · {card.route === 'full' ? 'полный' : 'упрощённый'}{' '}
            маршрут · <Badge tone={riskTone(card.risk_level)}>
              риск {card.risk_title.toLowerCase()}
            </Badge>
          </p>
        </div>
        <div className="btn-row no-print">
          <Link className="btn btn--secondary" to="/projects">К списку</Link>
        </div>
      </div>

      {notice && <Alert kind="ok">{notice}</Alert>}
      <ErrorAlert error={actionError} />

      {card.validation.missing_count > 0 && (
        <Alert kind="warn">
          <strong>
            Не заполнено обязательных полей: {card.validation.missing_count}
          </strong>
          <ul>
            {card.validation.missing_required.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </Alert>
      )}

      {card.actions.length > 0 && (
        <div className="card no-print">
          <h2 className="card__title">Доступные действия</h2>
          <div className="btn-row">
            {card.actions.map((action) => (
              <TransitionButton
                key={action.action}
                action={action}
                busy={busy}
                onRun={doTransition}
              />
            ))}
          </div>
          {card.actions.every((a) => !a.allowed) && (
            <p className="small muted" style={{ marginBottom: 0 }}>
              Сейчас ни одно действие недоступно: перечисленные ниже условия не
              выполнены либо действие доступно другой роли.
            </p>
          )}
        </div>
      )}

      <Tabs
        tabs={TABS.map((t) => ({
          ...t,
          count: t.key === 'plan' ? card.counts.milestones
            : t.key === 'team' ? card.counts.team
            : t.key === 'risks' ? card.counts.risks
            : t.key === 'results' ? card.counts.results
            : t.key === 'materials' ? card.counts.materials
            : t.key === 'reviews' ? card.counts.reviews + card.counts.decisions
            : undefined,
        }))}
        active={tab}
        onChange={setTab}
      />

      {tab === 'passport' && <PassportTab card={card} reload={load} />}
      {tab === 'science' && <ScienceTab card={card} canEdit={card.can_edit} reload={load} />}
      {tab === 'team' && <TeamTab projectId={card.id} canEdit={card.can_edit} />}
      {tab === 'plan' && <PlanTab projectId={card.id} canEdit={card.can_edit} reload={load} />}
      {tab === 'risks' && <RisksTab projectId={card.id} canEdit={card.can_edit} reload={load} />}
      {tab === 'reviews' && <ReviewsTab projectId={card.id} />}
      {tab === 'results' && <ResultsTab projectId={card.id} reload={load} />}
      {tab === 'materials' && <MaterialsTab projectId={card.id} canEdit={card.can_edit} />}
      {tab === 'public' && <PublicTab card={card} onApprove={approvePublication} busy={busy} />}
      {tab === 'history' && <HistoryTab projectId={card.id} objectType="project" />}
    </>
  );
}

// --- Переходы статуса -------------------------------------------------------

function TransitionButton({ action, busy, onRun }: {
  action: ProjectCard['actions'][number];
  busy: boolean;
  onRun: (action: string, reason?: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');

  if (!action.allowed) {
    return (
      <span title={action.blocked_reasons.join('. ')}>
        <button className="btn btn--secondary" type="button" disabled>
          {action.title} — недоступно
        </button>
      </span>
    );
  }
  if (!action.reason_required) {
    return (
      <button className="btn" type="button" disabled={busy}
        onClick={() => void onRun(action.action)}>
        {action.title}
      </button>
    );
  }
  return (
    <>
      <button className="btn" type="button" disabled={busy}
        onClick={() => setOpen(!open)}>
        {action.title}
      </button>
      {open && (
        <div className="card" style={{ margin: '10px 0 0', background: '#f8fafc' }}>
          <Field label={`Комментарий: ${action.condition}`} required
            hint="Комментарий обязателен по ТЗ и попадает в журнал решений">
            <textarea value={reason} maxLength={4000}
              onChange={(e) => setReason(e.target.value)} />
          </Field>
          <div className="btn-row">
            <button className="btn" type="button" disabled={busy || !reason.trim()}
              onClick={() => {
                setOpen(false);
                void onRun(action.action, reason.trim());
              }}>
              Подтвердить
            </button>
            <button className="btn btn--secondary" type="button" onClick={() => setOpen(false)}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </>
  );
}

// --- Раздел 1: паспорт -----------------------------------------------------

function PassportTab({ card, reload }: {
  card: ProjectCard; reload: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  const [version, setVersion] = useState(card.version);

  const edit = card.can_edit;

  async function save(fields: Record<string, unknown>) {
    setSaving(true);
    setError(null);
    try {
      const result = await api<{ version: number; changed: unknown[] }>(
        `/api/projects/${card.id}`,
        { method: 'PATCH', body: { ...fields, version } },
      );
      setVersion(result.version);
      setNotice(
        result.changed.length > 0
          ? `Сохранено полей: ${result.changed.length}`
          : 'Изменений не было',
      );
      reload();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      {notice && <Alert kind="ok">{notice}</Alert>}
      <ErrorAlert error={error} />

      <div className="grid grid--2">
        <div className="card">
          <h2 className="card__title">Паспорт</h2>
          <Detail items={[
            ['Номер (A-01)', <span className="mono">{card.code}</span>],
            ['Научная программа (A-05)',
              // Название, а не внутренний идентификатор: программа архивируется,
              // и тогда показываем её код, чтобы карточку можно было опознать.
              card.program_title
                || (card.program_code ? `${card.program_code} (архивная программа)` : '—')],
            ['Маршрут (A-07)',
              `${card.route === 'full' ? 'Полный' : 'Упрощённый'}${
                card.route !== card.route_auto
                  ? ` (изменён вручную: предложен ${card.route_auto === 'full' ? 'полный' : 'упрощённый'})`
                  : ' (предложен системой)'}`],
            ['Основания полного маршрута (A-08)',
              card.full_route_reasons_detail.length > 0
                ? card.full_route_reasons_detail
                    .map((r) => `${r.code} — ${r.title}`).join('; ')
                : '—'],
            ['Статус (A-09)',
              `${card.status} — ${card.status_title}${card.status_changed_at
                ? ` (с ${fmtDateTime(card.status_changed_at)})` : ''}`],
            ['Индикатор риска (A-10)',
              `${card.risk_title}. ${card.risk.reasons[0] ?? ''}`],
            ['Плановые даты (A-11)',
              `${fmtDate(card.planned_start)} — ${fmtDate(card.planned_end)}`],
            ['Режим публикации (A-15)', PUBLISH_MODES[card.publish_mode]],
            ['Разрешение на публикацию',
              card.public_allowed_at ? fmtDateTime(card.public_allowed_at) : 'не выдано'],
            ['Создал (A-16)',
              `${card.created_by_login ?? '—'}, ${fmtDateTime(card.created_at)}`],
            ['Изменён', fmtDateTime(card.updated_at)],
            ['Версия записи (FR-32)', String(card.version)],
          ]} />
          {card.route_reason_comment && (
            <Alert kind="info">
              Комментарий к ручному изменению маршрута: {card.route_reason_comment}
            </Alert>
          )}
          {card.risk_level_comment && (
            <Alert kind="warn">
              Комментарий к индикатору риска: {card.risk_level_comment}
            </Alert>
          )}
        </div>

        <div className="card">
          <h2 className="card__title">Редактирование паспорта</h2>
          {!edit && (
            <Alert kind="info">
              Карточка доступна только для просмотра вашей ролью на этом проекте.
            </Alert>
          )}
          <Field label="Краткое название" code="A-03">
            <input type="text" defaultValue={card.short_title ?? ''} maxLength={150}
              disabled={!edit}
              onBlur={(e) => e.target.value !== (card.short_title ?? '')
                && void save({ short_title: e.target.value })} />
          </Field>
          <Field label="Связь с общей темой" code="A-06">
            <input type="text" defaultValue={card.theme_link ?? ''} maxLength={500}
              disabled={!edit}
              onBlur={(e) => e.target.value !== (card.theme_link ?? '')
                && void save({ theme_link: e.target.value })} />
          </Field>
          <div className="grid grid--2">
            <Field label="Плановое начало" code="A-11">
              <input type="date" defaultValue={card.planned_start ?? ''} disabled={!edit}
                onBlur={(e) => e.target.value !== (card.planned_start ?? '')
                  && void save({ planned_start: e.target.value || null })} />
            </Field>
            <Field label="Плановое завершение" code="A-11">
              <input type="date" defaultValue={card.planned_end ?? ''} disabled={!edit}
                onBlur={(e) => e.target.value !== (card.planned_end ?? '')
                  && void save({ planned_end: e.target.value || null })} />
            </Field>
          </div>
          <Field label="Режим публикации" code="A-15">
            <select defaultValue={card.publish_mode} disabled={!edit}
              onChange={(e) => void save({ publish_mode: e.target.value })}>
              {Object.entries(PUBLISH_MODES).map(([key, title]) => (
                <option key={key} value={key}>{title}</option>
              ))}
            </select>
          </Field>
          {saving && <p className="small muted">Сохранение…</p>}
        </div>
      </div>

      <div className="card">
        <h2 className="card__title">Признаки полного маршрута</h2>
        <div className="grid grid--3">
          {FULL_ROUTE_FLAGS.map((flag) => (
            <label className="checkbox" key={flag.key}>
              <input
                type="checkbox"
                disabled={!edit}
                checked={Boolean((card as unknown as Record<string, unknown>)[flag.key])}
                onChange={(e) => void save({ [flag.key]: e.target.checked })}
              />
              <span>{flag.title} <span className="field__code">{flag.code}</span></span>
            </label>
          ))}
        </div>
        {edit && (
          <p className="small muted">
            Изменение признака сохраняет основание в перечне T-01…T-06. Если
            система предлагает другой маршрут, уполномоченное лицо фиксирует его
            с комментарием (FR-09).
          </p>
        )}
      </div>
    </>
  );
}

// --- Раздел 2: научное содержание -------------------------------------------

function ScienceTab({ card, canEdit, reload }: {
  card: ProjectCard; canEdit: boolean; reload: () => void;
}) {
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');

  async function save(fields: Record<string, unknown>) {
    setError(null);
    try {
      await api(`/api/projects/${card.id}`, {
        method: 'PATCH',
        body: { ...fields, version: card.version },
      });
      setNotice('Сохранено');
      reload();
    } catch (err) {
      setError(err);
    }
  }

  const full = card.route === 'full';

  return (
    <>
      {notice && <Alert kind="ok">{notice}</Alert>}
      <ErrorAlert error={error} />
      {card.validation.length_problems.length > 0 && (
        <Alert kind="warn">
          <ul>
            {card.validation.length_problems.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </Alert>
      )}

      <div className="grid grid--2">
        {[
          { key: 'problem', label: 'Исследовательская проблема', code: 'A-17', max: 2000,
            required: true, hint: 'Проверяемая проблема, а не общая тема' },
          { key: 'question', label: 'Вопрос или гипотеза', code: 'A-18', max: 1000, required: true },
          { key: 'goal', label: 'Цель', code: 'A-19', max: 700, required: true,
            hint: 'Одна основная цель' },
          { key: 'data_basis', label: 'Данные или доказательная база', code: 'A-24',
            max: 2000, required: true, hint: 'Источник, состав, период и доступ' },
        ].map((field) => (
          <Field key={field.key} label={field.label} code={field.code}
            required={field.required} hint={field.hint}>
            <textarea
              defaultValue={(card as unknown as Record<string, string>)[field.key] ?? ''}
              maxLength={field.max}
              disabled={!canEdit}
              onBlur={(e) => {
                if (e.target.value !== ((card as unknown as Record<string, string>)[field.key] ?? '')) {
                  void save({ [field.key]: e.target.value || null });
                }
              }}
            />
          </Field>
        ))}
      </div>

      <div className="grid grid--3">
        <Field label="Объект" code="A-21" required={full}
          hint={full ? 'Обязателен для полного маршрута' : undefined}>
          <textarea defaultValue={card.research_object ?? ''} disabled={!canEdit}
            onBlur={(e) => e.target.value !== (card.research_object ?? '')
              && void save({ research_object: e.target.value || null })} />
        </Field>
        <Field label="Предмет" code="A-22" required={full}>
          <textarea defaultValue={card.research_subject ?? ''} disabled={!canEdit}
            onBlur={(e) => e.target.value !== (card.research_subject ?? '')
              && void save({ research_subject: e.target.value || null })} />
        </Field>
        <Field label="Ограничения" code="A-29" required={full}>
          <textarea defaultValue={card.limitations ?? ''} disabled={!canEdit}
            onBlur={(e) => e.target.value !== (card.limitations ?? '')
              && void save({ limitations: e.target.value || null })} />
        </Field>
      </div>

      <div className="grid grid--3">
        <Field label="Научная новизна" code="A-27" required={full}>
          <textarea defaultValue={card.novelty ?? ''} disabled={!canEdit}
            onBlur={(e) => e.target.value !== (card.novelty ?? '')
              && void save({ novelty: e.target.value || null })} />
        </Field>
        <Field label="Практическая применимость" code="A-28" required={full}>
          <textarea defaultValue={card.applicability ?? ''} disabled={!canEdit}
            onBlur={(e) => e.target.value !== (card.applicability ?? '')
              && void save({ applicability: e.target.value || null })} />
        </Field>
        <Field label="Задачи" code="A-20" required={full}
          hint="Через точку с запятой">
          <textarea defaultValue={asList(card.tasks).join('; ')} disabled={!canEdit}
            onBlur={(e) => void save({ tasks: asList(e.target.value) })} />
        </Field>
      </div>

      <div className="grid grid--2">
        <Field label="Методы" code="A-23" required hint="Через точку с запятой">
          <textarea
            defaultValue={asList(card.methods).join('; ')}
            disabled={!canEdit}
            onBlur={(e) => void save({ methods: asList(e.target.value) })}
          />
        </Field>
        <Field label="Критерии результата" code="A-26" required
          hint="Не менее одного признака выполнения">
          <textarea
            defaultValue={asList(card.result_criteria).join('; ')}
            disabled={!canEdit}
            onBlur={(e) => void save({ result_criteria: asList(e.target.value) })}
          />
        </Field>
      </div>

      <div className="card">
        <h2 className="card__title">Персональные данные, участие людей, права</h2>
        <div className="grid grid--2">
          <label className="checkbox">
            <input type="checkbox" disabled={!canEdit}
              checked={Boolean(card.personal_data)}
              onChange={(e) => void save({ personal_data: e.target.checked })} />
            <span>Обрабатываются персональные данные (A-30)</span>
          </label>
          <label className="checkbox">
            <input type="checkbox" disabled={!canEdit}
              checked={Boolean(card.human_subjects)}
              onChange={(e) => void save({ human_subjects: e.target.checked })} />
            <span>В исследовании участвуют люди (A-31)</span>
          </label>
        </div>
        <div className="grid grid--2">
          <Field label="Пояснение по персональным данным" code="A-30"
            required={Boolean(card.personal_data)}>
            <textarea defaultValue={card.personal_data_note ?? ''} disabled={!canEdit}
              onBlur={(e) => void save({ personal_data_note: e.target.value || null })} />
          </Field>
          <Field label="Пояснение по участию людей" code="A-31"
            required={Boolean(card.human_subjects)}>
            <textarea defaultValue={card.human_subjects_note ?? ''} disabled={!canEdit}
              onBlur={(e) => void save({ human_subjects_note: e.target.value || null })} />
          </Field>
        </div>
        <div className="grid grid--2">
          <Field label="Правовое и этическое основание" code="A-32">
            <input type="text" defaultValue={card.legal_basis_status ?? ''} disabled={!canEdit}
              onBlur={(e) => void save({ legal_basis_status: e.target.value || null })} />
          </Field>
          <Field label="Ссылка на документ" code="A-32">
            <input type="text" defaultValue={card.legal_basis_link ?? ''} disabled={!canEdit}
              onBlur={(e) => void save({ legal_basis_link: e.target.value || null })} />
          </Field>
        </div>
        <div className="grid grid--2">
          <Field label="Конфиденциальность и права" code="A-33" required={full}
            hint="До публикации результата">
            <textarea defaultValue={card.confidentiality ?? ''} disabled={!canEdit}
              onBlur={(e) => void save({ confidentiality: e.target.value || null })} />
          </Field>
          <Field label="Пояснение по правам" code="A-33">
            <textarea defaultValue={card.ip_note ?? ''} disabled={!canEdit}
              onBlur={(e) => void save({ ip_note: e.target.value || null })} />
          </Field>
        </div>
        <Field label="Ресурсный запрос" code="A-34" required={full}
          hint="Категория; объём; срок. Сравнивается с утверждённым лимитом">
          <textarea
            defaultValue={asList(card.resource_request).join('; ')}
            disabled={!canEdit}
            onBlur={(e) => void save({ resource_request: e.target.value })}
          />
        </Field>
        <Alert kind="info">
          Первичные необезличенные массивы данных респондентов, пациентов и иных
          исследуемых лиц в реестре не хранятся (п.11.2). Специальные категории и
          биометрические персональные данные в MVP не обрабатываются.
        </Alert>
      </div>
    </>
  );
}

// --- Раздел 3: команда ------------------------------------------------------

function TeamTab({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const [items, setItems] = useState<Participation[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  const [personId, setPersonId] = useState('');
  const [role, setRole] = useState('member');
  const [task, setTask] = useState('');

  const load = useCallback(() => {
    void api<{ items: Participation[] }>(`/api/projects/${projectId}/team`)
      .then((r) => setItems(r.items))
      .catch(setError);
  }, [projectId]);

  useEffect(load, [load]);
  useEffect(() => {
    void api<{ items: Person[] }>('/api/persons?limit=200')
      .then((r) => setPersons(r.items));
  }, []);

  async function add() {
    setError(null);
    try {
      await api(`/api/projects/${projectId}/team`, {
        method: 'POST',
        body: { person_id: personId, role, task: task || null },
      });
      setPersonId(''); setTask('');
      setNotice('Участник добавлен');
      load();
    } catch (err) {
      setError(err);
    }
  }

  async function confirm_(id: string) {
    await api(`/api/projects/${projectId}/team/${id}/confirm`, { method: 'POST' })
      .catch(setError);
    load();
  }

  async function remove(id: string) {
    await api(`/api/projects/${projectId}/team/${id}`, { method: 'DELETE' })
      .catch(setError);
    load();
  }

  const members = items.filter((i) => i.person_id !== personId);

  return (
    <>
      {notice && <Alert kind="ok">{notice}</Alert>}
      <ErrorAlert error={error} />

      {canEdit && (
        <div className="card">
          <h2 className="card__title">Добавить участника (FR-11)</h2>
          <div className="grid grid--3">
            <Field label="Человек" required
              hint="Профиль выбирается из справочника — однократный ввод (FR-03)">
              <select value={personId} onChange={(e) => setPersonId(e.target.value)}>
                <option value="">— выберите —</option>
                {persons
                  .filter((p) => !items.some((i) => i.person_id === p.id))
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.full_name}{p.position ? `, ${p.position}` : ''}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Роль в проекте" required>
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="member">Участник</option>
                <option value="leader">Руководитель</option>
                <option value="supervisor">Научный руководитель</option>
                <option value="curator">Куратор программы</option>
              </select>
            </Field>
            <Field label="Задача">
              <input type="text" value={task} onChange={(e) => setTask(e.target.value)} />
            </Field>
          </div>
          <button className="btn" type="button" disabled={!personId} onClick={() => void add()}>
            Добавить
          </button>
        </div>
      )}

      <div className="card">
        <h2 className="card__title">Команда (A-13)</h2>
        {items.length === 0 ? (
          <Empty>Команда не заполнена.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Человек</th>
                  <th>Роль</th>
                  <th>Задача</th>
                  <th>Период</th>
                  <th>Вклад</th>
                  <th>В публикации</th>
                  {canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {members.map((item) => (
                  <tr key={item.id}>
                    <td>
                      {item.full_name}
                      {item.position && <div className="small muted">{item.position}</div>}
                    </td>
                    <td className="small">{roleTitle(item.role)}</td>
                    <td className="small">{item.task || '—'}</td>
                    <td className="small nowrap">
                      {fmtDate(item.started_at) || '—'} — {fmtDate(item.finished_at) || '—'}
                    </td>
                    <td className="small nowrap">
                      {item.effort_share !== null
                        ? `${Math.round(item.effort_share * 100)}%`
                        : '—'}
                      {item.contribution_confirmed
                        ? <div><Badge tone="green">подтверждён</Badge></div>
                        : null}
                    </td>
                    <td>{item.is_public ? 'да' : 'нет'}</td>
                    {canEdit && (
                      <td>
                        <div className="btn-row">
                          {!item.contribution_confirmed && (
                            <button className="btn btn--secondary btn--sm" type="button"
                              onClick={() => void confirm_(item.id)}>
                              Подтвердить вклад
                            </button>
                          )}
                          {item.role !== 'leader' && (
                            <ConfirmButton
                              label="Исключить"
                              confirmLabel="Исключить из команды"
                              onConfirm={() => void remove(item.id)}
                              tone="btn--danger"
                            />
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="small muted">
          Участник исключается из команды с сохранением истории, а не удаляется
          (п.6.1). Связь с архивированным объектом не может быть создана без
          предупреждения (п.10.1).
        </p>
      </div>
    </>
  );
}

function roleTitle(role: string): string {
  return {
    leader: 'Руководитель', member: 'Участник',
    supervisor: 'Научный руководитель', curator: 'Куратор программы',
  }[role] ?? role;
}

// --- Раздел 4: план (контрольные точки) ------------------------------------

function PlanTab({ projectId, canEdit, reload }: {
  projectId: string; canEdit: boolean; reload: () => void;
}) {
  const [data, setData] = useState<{ items: Milestone[]; overdue: Milestone[] } | null>(null);
  const [persons, setPersons] = useState<Person[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState({
    title: '', planned_date: '', responsible_person_id: '', planned_evidence: '',
  });
  const [editing, setEditing] = useState<string | null>(null);
  const [editData, setEditData] = useState({
    actual_date: '', confirmation: '', postpone_reason: '', new_date: '',
  });

  const load = useCallback(() => {
    void api<{ items: Milestone[]; overdue: Milestone[] }>(
      `/api/projects/${projectId}/milestones`,
    )
      .then(setData)
      .catch(setError);
  }, [projectId]);

  useEffect(load, [load]);
  useEffect(() => {
    void api<{ items: Person[] }>('/api/persons?limit=200')
      .then((r) => setPersons(r.items));
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api(`/api/projects/${projectId}/milestones`, {
        method: 'POST', body: form,
      });
      setForm({ title: '', planned_date: '', responsible_person_id: '', planned_evidence: '' });
      setNotice('Контрольная точка добавлена');
      load(); reload();
    } catch (err) {
      setError(err);
    }
  }

  async function complete(item: Milestone) {
    setError(null);
    try {
      await api(`/api/projects/${projectId}/milestones/${item.id}`, {
        method: 'PATCH',
        body: {
          status: 'done',
          actual_date: editData.actual_date,
          confirmation: editData.confirmation,
        },
      });
      setEditing(null);
      setNotice('Точка отмечена выполненной');
      load(); reload();
    } catch (err) {
      setError(err);
    }
  }

  async function postpone(item: Milestone) {
    setError(null);
    try {
      await api(`/api/projects/${projectId}/milestones/${item.id}`, {
        method: 'PATCH',
        body: {
          planned_date: editData.new_date,
          postpone_reason: editData.postpone_reason,
        },
      });
      setEditing(null);
      setNotice('Срок перенесён, причина зафиксирована');
      load(); reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      {notice && <Alert kind="ok">{notice}</Alert>}
      <ErrorAlert error={error} />

      {canEdit && (
        <div className="card">
          <h2 className="card__title">Новая контрольная точка (A-35…A-38)</h2>
          <form onSubmit={create}>
            <div className="grid grid--2">
              <Field label="Название точки" code="A-35" required
                hint="Описывает проверяемое событие">
                <input type="text" value={form.title} maxLength={300}
                  onChange={(e) => setForm({ ...form, title: e.target.value })} required />
              </Field>
              <Field label="Плановая дата" code="A-36" required
                hint="В пределах сроков проекта">
                <input type="date" value={form.planned_date}
                  onChange={(e) => setForm({ ...form, planned_date: e.target.value })} required />
              </Field>
            </div>
            <div className="grid grid--2">
              <Field label="Ответственный" code="A-37" required
                hint="Только действующий участник проекта">
                <select value={form.responsible_person_id}
                  onChange={(e) => setForm({ ...form, responsible_person_id: e.target.value })}
                  required>
                  <option value="">— выберите участника —</option>
                  {persons.map((p) => (
                    <option key={p.id} value={p.id}>{p.full_name}</option>
                  ))}
                </select>
              </Field>
              <Field label="Плановое подтверждение" code="A-38" required
                hint="«Выполнение работы» без доказательства недопустимо">
                <input type="text" value={form.planned_evidence}
                  placeholder="Отчёт с результатами, протокол испытаний"
                  onChange={(e) => setForm({ ...form, planned_evidence: e.target.value })}
                  required />
              </Field>
            </div>
            <button className="btn" type="submit">Добавить точку</button>
          </form>
        </div>
      )}

      <div className="card">
        <h2 className="card__title">
          Контрольные точки ({data?.items.length ?? 0})
          {data && data.overdue.length > 0 && (
            <Badge tone="red">просрочено: {data.overdue.length}</Badge>
          )}
        </h2>
        {!data ? (
          <Spinner />
        ) : data.items.length === 0 ? (
          <Empty>Контрольные точки не заданы.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Точка</th>
                  <th>План</th>
                  <th>Факт</th>
                  <th>Ответственный</th>
                  <th>Статус</th>
                  <th>Подтверждение</th>
                  {canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      {item.title}
                      {item.postpone_reason && (
                        <div className="small muted">
                          Перенос: {item.postpone_reason}
                        </div>
                      )}
                    </td>
                    <td className="nowrap">
                      {item.planned_date_fmt}
                      {item.is_overdue && (
                        <div className="small" style={{ color: 'var(--c-danger)' }}>
                          задержка {item.delay_working_days} раб. дн.
                        </div>
                      )}
                    </td>
                    <td className="nowrap">{item.actual_date_fmt || '—'}</td>
                    <td className="small">{item.responsible_name || '—'}</td>
                    <td className="nowrap">
                      <Badge tone={
                        item.status === 'done' ? 'green'
                        : item.status === 'overdue' ? 'red'
                        : item.status === 'in_progress' ? 'accent'
                        : item.status === 'cancelled' ? 'neutral' : 'yellow'
                      }>
                        {milestoneStatus(item.status)}
                      </Badge>
                    </td>
                    <td className="small">{item.confirmation || '—'}</td>
                    {canEdit && (
                      <td>
                        <button className="btn btn--secondary btn--sm" type="button"
                          onClick={() => {
                            setEditing(editing === item.id ? null : item.id);
                            setEditData({
                              actual_date: item.actual_date ?? '',
                              confirmation: item.confirmation ?? '',
                              postpone_reason: '',
                              new_date: item.planned_date,
                            });
                          }}>
                          {editing === item.id ? 'Свернуть' : 'Действия'}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editing && canEdit && (
        <div className="card">
          <h2 className="card__title">Действия с точкой</h2>
          <div className="grid grid--2">
            <Field label="Фактическая дата" code="A-40"
              hint="Обязательна при выполнении">
              <input type="date" value={editData.actual_date}
                onChange={(e) => setEditData({ ...editData, actual_date: e.target.value })} />
            </Field>
            <Field label="Подтверждение" code="A-41"
              hint="Обязательно при выполнении">
              <input type="text" value={editData.confirmation}
                onChange={(e) => setEditData({ ...editData, confirmation: e.target.value })} />
            </Field>
          </div>
          <div className="btn-row" style={{ marginBottom: 12 }}>
            <button className="btn" type="button"
              onClick={() => {
                const item = data?.items.find((i) => i.id === editing);
                if (item) void complete(item);
              }}>
              Отметить выполненной
            </button>
          </div>
          <div className="grid grid--2">
            <Field label="Новый срок" code="A-36">
              <input type="date" value={editData.new_date}
                onChange={(e) => setEditData({ ...editData, new_date: e.target.value })} />
            </Field>
            <Field label="Причина переноса" code="A-42"
              hint="Обязательна при изменении срока">
              <input type="text" value={editData.postpone_reason}
                onChange={(e) => setEditData({ ...editData, postpone_reason: e.target.value })} />
            </Field>
          </div>
          <button className="btn btn--secondary" type="button"
            onClick={() => {
              const item = data?.items.find((i) => i.id === editing);
              if (item) void postpone(item);
            }}>
            Перенести срок
          </button>
        </div>
      )}
    </>
  );
}

function milestoneStatus(status: string): string {
  return {
    planned: 'Запланирована', in_progress: 'Выполняется', done: 'Выполнена',
    overdue: 'Просрочена', cancelled: 'Отменена',
  }[status] ?? status;
}

// --- Раздел 5: риски и ресурсы ---------------------------------------------

function RisksTab({ projectId, canEdit, reload }: {
  projectId: string; canEdit: boolean; reload: () => void;
}) {
  const [data, setData] = useState<{ items: RiskRow[]; counts: Record<string, number> } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [form, setForm] = useState({
    category: 'method', description: '', probability: 'medium', impact: 'medium',
    measures: '', level: 'yellow', level_comment: '',
  });

  const load = useCallback(() => {
    void api<{ items: RiskRow[]; counts: Record<string, number> }>(
      `/api/projects/${projectId}/risks`,
    )
      .then(setData)
      .catch(setError);
  }, [projectId]);

  useEffect(load, [load]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api(`/api/projects/${projectId}/risks`, { method: 'POST', body: form });
      setForm({ ...form, description: '', measures: '' });
      load(); reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      <ErrorAlert error={error} />

      <div className="card">
        <h2 className="card__title">Индикатор риска проекта (A-10)</h2>
        <Alert kind="info">
          Статус и индикатор риска — разные поля. Проект может быть «Активен»
          и при этом иметь жёлтый индикатор (п.5.4).
        </Alert>
        {data && (
          <div className="grid grid--3">
            <div><Badge tone="red">Красный</Badge>: {data.counts.red ?? 0}</div>
            <div><Badge tone="yellow">Жёлтый</Badge>: {data.counts.yellow ?? 0}</div>
            <div><Badge tone="green">Зелёный</Badge>: {data.counts.green ?? 0}</div>
          </div>
        )}
      </div>

      {canEdit && (
        <div className="card">
          <h2 className="card__title">Новый риск (A-65)</h2>
          <form onSubmit={create}>
            <div className="grid grid--2">
              <Field label="Категория" required>
                <select value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  <option value="method">Методологический</option>
                  <option value="data">Данные</option>
                  <option value="team">Команда</option>
                  <option value="resource">Ресурсный</option>
                  <option value="legal">Правовой</option>
                  <option value="ethical">Этический</option>
                  <option value="reputational">Репутационный</option>
                  <option value="informational">Информационный</option>
                  <option value="schedule">Сроки</option>
                  <option value="technical">Технический</option>
                </select>
              </Field>
              <Field label="Уровень" required hint="Ручное изменение уровня требует комментария">
                <select value={form.level}
                  onChange={(e) => setForm({ ...form, level: e.target.value })}>
                  <option value="green">Зелёный</option>
                  <option value="yellow">Жёлтый</option>
                  <option value="red">Красный</option>
                </select>
              </Field>
            </div>
            <Field label="Описание" required>
              <textarea value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })} required />
            </Field>
            <div className="grid grid--2">
              <Field label="Вероятность">
                <select value={form.probability}
                  onChange={(e) => setForm({ ...form, probability: e.target.value })}>
                  <option value="low">Низкая</option>
                  <option value="medium">Средняя</option>
                  <option value="high">Высокая</option>
                </select>
              </Field>
              <Field label="Влияние">
                <select value={form.impact}
                  onChange={(e) => setForm({ ...form, impact: e.target.value })}>
                  <option value="low">Низкое</option>
                  <option value="medium">Среднее</option>
                  <option value="high">Высокое</option>
                </select>
              </Field>
            </div>
            <Field label="Меры реагирования">
              <textarea value={form.measures}
                onChange={(e) => setForm({ ...form, measures: e.target.value })} />
            </Field>
            {form.level !== 'yellow' && (
              <Field label="Комментарий к уровню" required>
                <input type="text" value={form.level_comment}
                  onChange={(e) => setForm({ ...form, level_comment: e.target.value })} />
              </Field>
            )}
            <button className="btn" type="submit">Добавить риск</button>
          </form>
        </div>
      )}

      <div className="card">
        <h2 className="card__title">Риски проекта</h2>
        {!data ? (
          <Spinner />
        ) : data.items.length === 0 ? (
          <Empty>Риски не зафиксированы.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Категория</th><th>Описание</th><th>Вер./влияние</th>
                  <th>Меры</th><th>Уровень</th><th>Статус</th></tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td className="small nowrap">{item.category}</td>
                    <td>
                      {item.description}
                      {item.level_comment && (
                        <div className="small muted">{item.level_comment}</div>
                      )}
                    </td>
                    <td className="small nowrap">{item.probability} / {item.impact}</td>
                    <td className="small">{item.measures || '—'}</td>
                    <td><Badge tone={riskTone(item.level)}>{item.level}</Badge></td>
                    <td className="small">{item.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

// --- Раздел 6: экспертизы и решения ----------------------------------------

function ReviewsTab({ projectId }: { projectId: string }) {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  const [expertId, setExpertId] = useState('');
  const [stage, setStage] = useState('preliminary');
  const [decision, setDecision] = useState({
    level: 'prorector', kind: 'launch', wording: '', basis: '', conditions: '',
  });

  const load = useCallback(() => {
    void api<{ items: Review[] }>(`/api/projects/${projectId}/reviews`)
      .then((r) => setReviews(r.items)).catch(setError);
    void api<{ items: Decision[] }>(`/api/projects/${projectId}/decisions`)
      .then((r) => setDecisions(r.items)).catch(setError);
  }, [projectId]);

  useEffect(load, [load]);
  useEffect(() => {
    void api<{ items: Person[] }>('/api/persons?limit=200')
      .then((r) => setPersons(r.items));
  }, []);

  async function assign() {
    setError(null);
    try {
      await api(`/api/projects/${projectId}/reviews`, {
        method: 'POST',
        body: { expert_person_id: expertId, stage, object_type: 'project' },
      });
      setNotice('Эксперт назначен, срок заключения рассчитан');
      load();
    } catch (err) {
      setError(err);
    }
  }

  async function register() {
    setError(null);
    try {
      await api(`/api/projects/${projectId}/decisions`, {
        method: 'POST',
        body: { object_type: 'project', object_id: projectId, ...decision },
      });
      setNotice('Решение зарегистрировано');
      setDecision({ ...decision, wording: '', basis: '', conditions: '' });
      load();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      {notice && <Alert kind="ok">{notice}</Alert>}
      <ErrorAlert error={error} />

      <div className="card">
        <h2 className="card__title">Экспертизы (FR-14)</h2>
        <div className="grid grid--3">
          <Field label="Эксперт" required
            hint="Участники проекта не могут быть экспертами (п.4.1)">
            <select value={expertId} onChange={(e) => setExpertId(e.target.value)}>
              <option value="">— выберите —</option>
              {persons.map((p) => (
                <option key={p.id} value={p.id}>{p.full_name}</option>
              ))}
            </select>
          </Field>
          <Field label="Вид экспертизы" required>
            <select value={stage} onChange={(e) => setStage(e.target.value)}>
              <option value="preliminary">Предварительная</option>
              <option value="final">Итоговая</option>
            </select>
          </Field>
          <Field label="Срок" hint="До 10 рабочих дней (п.5.5)">
            <input type="text" value="рассчитывается автоматически" disabled />
          </Field>
        </div>
        <button className="btn" type="button" disabled={!expertId} onClick={() => void assign()}>
          Назначить эксперта
        </button>
      </div>

      <div className="card">
        <h2 className="card__title">Назначенные экспертизы</h2>
        {reviews.length === 0 ? (
          <Empty>Экспертиз не назначено.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Эксперт</th><th>Вид</th><th>Срок</th>
                  <th>Рекомендация</th><th>Состояние</th>
                </tr>
              </thead>
              <tbody>
                {reviews.map((review) => (
                  <tr key={review.id}>
                    <td>{review.expert_name || '—'}</td>
                    <td className="small">
                      {review.stage === 'preliminary' ? 'Предварительная' : 'Итоговая'}
                    </td>
                    <td className="nowrap">
                      {review.due_at_fmt || '—'}
                      {review.recused_at && <div><Badge tone="neutral">самоотвод</Badge></div>}
                    </td>
                    <td className="small">{review.recommendation_title || '—'}</td>
                    <td className="small">
                      {review.immutable
                        ? <Badge tone="green">зафиксировано, версия {review.version_no}</Badge>
                        : review.recused_at ? 'отказ'
                        : 'в работе'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="card__title">Решения (FR-15)</h2>
        <div className="grid grid--3">
          <Field label="Уровень решения" required hint="Определяется вашей ролью (п.4.2)">
            <select value={decision.level}
              onChange={(e) => setDecision({ ...decision, level: e.target.value })}>
              <option value="curator">Куратор программы</option>
              <option value="prorector">Проректор по науке</option>
              <option value="rector">Ректор</option>
              <option value="council">Научный совет</option>
              <option value="secretary">Секретарь</option>
            </select>
          </Field>
          <Field label="Вид решения" required>
            <select value={decision.kind}
              onChange={(e) => setDecision({ ...decision, kind: e.target.value })}>
              <option value="launch">Запуск</option>
              <option value="pilot">Запуск пилота</option>
              <option value="accept">Приёмка результата</option>
              <option value="return">Возврат на доработку</option>
              <option value="suspend">Приостановка</option>
              <option value="resume">Возобновление</option>
              <option value="reserve">Перевод в резерв</option>
              <option value="reject">Отклонение</option>
              <option value="close">Прекращение</option>
              <option value="publish">Разрешение публикации</option>
            </select>
          </Field>
          <Field label="Срок исполнения">
            <input type="date"
              onChange={(e) => setDecision({ ...decision, conditions: e.target.value })} />
          </Field>
        </div>
        <Field label="Формулировка" required>
          <textarea value={decision.wording}
            onChange={(e) => setDecision({ ...decision, wording: e.target.value })} required />
        </Field>
        <Field label="Основание" required hint="Без основания решение не создаётся (A-64)">
          <textarea value={decision.basis}
            onChange={(e) => setDecision({ ...decision, basis: e.target.value })} required />
        </Field>
        <button className="btn" type="button"
          disabled={!decision.wording.trim() || !decision.basis.trim()}
          onClick={() => void register()}>
          Зарегистрировать решение
        </button>
      </div>

      <div className="card">
        <h2 className="card__title">История решений</h2>
        {decisions.length === 0 ? (
          <Empty>Решений не зарегистрировано.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Дата</th><th>Вид</th><th>Уровень</th><th>Формулировка</th>
                  <th>Основание</th><th>Исполнено</th></tr>
              </thead>
              <tbody>
                {decisions.map((item) => (
                  <tr key={item.id}>
                    <td className="nowrap small">{fmtDateTime(item.decided_at)}</td>
                    <td className="small">{item.kind}</td>
                    <td className="small">{item.level}</td>
                    <td className="small">{item.wording}</td>
                    <td className="small">{item.basis}</td>
                    <td className="small nowrap">
                      {item.executed_at ? 'да' : 'нет'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

// --- Раздел 7: результаты ---------------------------------------------------

function ResultsTab({ projectId, reload }: { projectId: string; reload: () => void }) {
  const [data, setData] = useState<{ items: ResultRecord[] } | null>(null);
  const [persons, setPersons] = useState<Person[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState({
    result_type: 'publication', title: '', description: '',
    authors: [] as string[], readiness_stage: 'produced',
    acceptance_criterion: '', confirmation: '', doi: '', url: '', actual_date: '',
  });

  const load = useCallback(() => {
    void api<{ items: ResultRecord[] }>(`/api/results?project_id=${projectId}&limit=100`)
      .then(setData)
      .catch(setError);
  }, [projectId]);

  useEffect(load, [load]);
  useEffect(() => {
    void api<{ items: Person[] }>('/api/persons?limit=200')
      .then((r) => setPersons(r.items));
  }, []);

  async function create() {
    setError(null);
    try {
      await api(`/api/results?duplicate_ack=true`, {
        method: 'POST',
        body: {
          result_type: form.result_type,
          title: form.title,
          description: form.description,
          authors: form.authors,
          readiness_stage: form.readiness_stage,
          project_ids: [projectId],
          acceptance_criterion: form.acceptance_criterion,
          confirmation: form.confirmation || null,
          actual_date: form.actual_date || undefined,
          doi: form.doi || null,
          url: form.url || null,
        },
      });
      setForm({ ...form, title: '', description: '', acceptance_criterion: '',
        confirmation: '', doi: '', url: '', actual_date: '' });
      setNotice('Результат зарегистрирован');
      load(); reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      {notice && <Alert kind="ok">{notice}</Alert>}
      <ErrorAlert error={error} />

      <div className="card">
        <h2 className="card__title">Зарегистрированные результаты</h2>
        {!data ? (
          <Spinner />
        ) : data.items.length === 0 ? (
          <Empty>Результаты не зарегистрированы.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Номер</th><th>Название</th><th>Вид</th><th>Стадия</th>
                  <th>Связанные проекты</th><th>Заключение</th><th>Публикация</th></tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td className="mono nowrap">{item.code}</td>
                    <td>{item.title}<div className="small muted">{item.authors_names.join(', ')}</div></td>
                    <td className="small">{item.result_type}</td>
                    <td className="small nowrap">{item.readiness_title}</td>
                    <td className="small">
                      {item.projects.map((p) => p.code).join(', ')}
                    </td>
                    <td className="small">
                      {item.confirmed ? <Badge tone="green">принят</Badge> : 'нет'}
                    </td>
                    <td className="small">
                      {item.publish_allowed ? <Badge tone="green">разрешено</Badge> : 'нет'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Alert kind="info">
          Один результат может быть связан с несколькими проектами и при этом
          учитывается в общей статистике один раз (FR-17).
        </Alert>
      </div>

      <div className="card">
        <h2 className="card__title">Новый результат (A-44…A-54)</h2>
        <div className="grid grid--2">
          <Field label="Вид результата" required>
            <select value={form.result_type}
              onChange={(e) => setForm({ ...form, result_type: e.target.value })}>
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
          <Field label="Стадия готовности" required>
            <select value={form.readiness_stage}
              onChange={(e) => setForm({ ...form, readiness_stage: e.target.value })}>
              <option value="planned">Запланирован</option>
              <option value="produced">Получен</option>
              <option value="applied">Апробирован</option>
              <option value="accepted">Принят</option>
              <option value="published">Опубликован</option>
              <option value="implemented">Внедрён</option>
            </select>
          </Field>
        </div>
        <Field label="Название" required hint="Проверяется на дубль по DOI, EDN и названию">
          <input type="text" value={form.title} maxLength={500}
            onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <Field label="Описание" required>
          <textarea value={form.description} maxLength={1500}
            onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <Field label="Авторы" required hint="Удерживайте Ctrl для выбора нескольких">
          <select multiple size={5} value={form.authors}
            onChange={(e) => setForm({
              ...form,
              authors: Array.from(e.target.selectedOptions).map((o) => o.value),
            })}>
            {persons.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
          </select>
        </Field>
        <Field label="Критерий приёмки" required hint="Проверяемый критерий">
          <input type="text" value={form.acceptance_criterion}
            onChange={(e) => setForm({ ...form, acceptance_criterion: e.target.value })} />
        </Field>
        {['accepted', 'published', 'implemented'].includes(form.readiness_stage) && (
          <div className="grid grid--2">
            <Field label="Фактическая дата" code="A-50" required>
              <input type="date"
                onChange={(e) => setForm({ ...form, actual_date: e.target.value })} />
            </Field>
            <Field label="Подтверждение" code="A-52" required>
              <input type="text" value={form.confirmation}
                onChange={(e) => setForm({ ...form, confirmation: e.target.value })} />
            </Field>
          </div>
        )}
        <div className="grid grid--2">
          <Field label="DOI">
            <input type="text" value={form.doi} placeholder="10.1234/example"
              onChange={(e) => setForm({ ...form, doi: e.target.value })} />
          </Field>
          <Field label="URL">
            <input type="text" value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })} />
          </Field>
        </div>
        <button className="btn" type="button" onClick={() => void create()}
          disabled={!form.title.trim() || !form.description.trim() || form.authors.length === 0}>
          Зарегистрировать результат
        </button>
      </div>
    </>
  );
}

// --- Раздел 8: материалы ----------------------------------------------------

interface Evidence {
  id: string; title: string; kind: string; url: string | null;
  access_level: string; version: number; uploaded_at: string;
}

function MaterialsTab({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const [items, setItems] = useState<Evidence[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [title, setTitle] = useState('');
  const [url, setUrl] = useState('');
  const [access, setAccess] = useState('internal');

  const load = useCallback(() => {
    void api<{ items: Evidence[] }>(`/api/projects/${projectId}/materials`)
      .then((r) => setItems(r.items))
      .catch(setError);
  }, [projectId]);

  useEffect(load, [load]);

  async function add() {
    setError(null);
    try {
      await api(`/api/projects/${projectId}/materials`, {
        method: 'POST',
        body: {
          object_type: 'project', object_id: projectId,
          title, kind: 'link', url, access_level: access,
        },
      });
      setTitle(''); setUrl('');
      load();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      <ErrorAlert error={error} />
      {canEdit && (
        <div className="card">
          <h2 className="card__title">Добавить ссылку (FR-21)</h2>
          <div className="grid grid--3">
            <Field label="Название" required>
              <input type="text" value={title}
                onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Field label="Адрес" required>
              <input type="text" value={url} onChange={(e) => setUrl(e.target.value)} />
            </Field>
            <Field label="Уровень доступа" required>
              <select value={access} onChange={(e) => setAccess(e.target.value)}>
                <option value="internal">Внутренний</option>
                <option value="restricted">Ограниченный</option>
                <option value="public">Открытый</option>
              </select>
            </Field>
          </div>
          <button className="btn" type="button" disabled={!title.trim() || !url.trim()}
            onClick={() => void add()}>
            Добавить материал
          </button>
          <p className="small muted" style={{ marginBottom: 0 }}>
            В MVP материалы хранятся как ссылки. Защищённые вложения и версии
            файлов реализуются во второй очереди (FR-21).
          </p>
        </div>
      )}

      <div className="card">
        <h2 className="card__title">Материалы</h2>
        {items.length === 0 ? (
          <Empty>Материалы не добавлены.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Название</th><th>Тип</th><th>Доступ</th><th>Версия</th><th>Добавлен</th></tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      {item.url ? <a href={item.url} target="_blank" rel="noreferrer">
                        {item.title}</a> : item.title}
                    </td>
                    <td className="small">{item.kind === 'link' ? 'ссылка' : 'файл'}</td>
                    <td className="small">{item.access_level}</td>
                    <td className="small">{item.version}</td>
                    <td className="small nowrap">{fmtDate(item.uploaded_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

// --- Раздел 9: публичное представление --------------------------------------

function PublicTab({ card, onApprove, busy }: {
  card: ProjectCard;
  onApprove: () => Promise<void>;
  busy: boolean;
}) {
  const [preview, setPreview] = useState<{
    will_be_published: boolean;
    card: Record<string, unknown> & { withheld_reasons?: string[] };
    publish_mode_title: string;
    approved_at: string | null;
  } | null>(null);

  useEffect(() => {
    void api<typeof preview>(`/api/projects/${card.id}/public-preview`)
      .then(setPreview)
      .catch(() => setPreview(null));
  }, [card.id, card.publish_mode, card.public_allowed_at]);

  return (
    <div className="grid grid--2">
      <div className="card">
        <h2 className="card__title">Публичная проекция (FR-22)</h2>
        <Alert kind="info">
          В публичный контур передаются только утверждённые открытые поля.
          Экспертные заключения, риски, ресурсные запросы, персональные контакты,
          закрытые файлы и журнал действий не публикуются никогда (п.9.2).
        </Alert>
        <Detail items={[
          ['Режим публикации (A-15)', card.publish_mode_title],
          ['Разрешение', card.public_allowed_at
            ? `выдано ${fmtDateTime(card.public_allowed_at)}`
            : 'не выдано'],
          ['Будет передаваться', preview?.will_be_published ? 'да' : 'нет'],
          ['Публичная аннотация (A-04)',
            card.public_annotation || <span className="muted">не заполнена</span>],
        ]} />
        {preview?.card?.withheld_reasons && preview.card.withheld_reasons.length > 0 && (
          <Alert kind="warn">
            <strong>Причины, по которым проект не передаётся:</strong>
            <ul>
              {preview.card.withheld_reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </Alert>
        )}
        <button className="btn" type="button" disabled={busy} onClick={() => void onApprove()}>
          Разрешить публикацию
        </button>
        <p className="small muted" style={{ marginBottom: 0 }}>
          Для упрощённого маршрута разрешение даёт куратор программы, для полного —
          проректор по науке (п.9.2). Отзыв разрешения немедленно исключает проект
          из публичного контура (FR-34).
        </p>
      </div>

      <div className="card">
        <h2 className="card__title">Предпросмотр открытых полей</h2>
        {!preview ? (
          <Empty>Предпросмотр недоступен.</Empty>
        ) : (
          <pre className="mono" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            maxHeight: 420, overflow: 'auto', margin: 0 }}>
            {JSON.stringify(preview.card, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

// --- Раздел 10: история -----------------------------------------------------

export function HistoryTab({ projectId, objectType }: {
  projectId: string; objectType: string;
}) {
  const [items, setItems] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    void api<{ items: AuditEvent[] }>(
      `/api/audit/object/${objectType}/${projectId}?limit=200`,
    )
      .then((r) => setItems(r.items))
      .catch(() => setItems([]))
      .catch(setError);
  }, [projectId, objectType]);

  return (
    <div className="card">
      <h2 className="card__title">История изменений (FR-23)</h2>
      <ErrorAlert error={error} />
      {items.length === 0 ? (
        <Empty>
          История доступна техническому администратору, секретарю и руководству.
        </Empty>
      ) : (
        <ul className="timeline">
          {items.map((event) => (
            <li key={event.id}>
              <div className="timeline__time">
                {event.happened_at_fmt} · {event.user_login ?? 'система'}
                {event.outcome !== 'ok' && (
                  <Badge tone={event.outcome === 'denied' ? 'yellow' : 'red'}>
                    {event.outcome === 'denied' ? 'отказ' : 'ошибка'}
                  </Badge>
                )}
              </div>
              <div className="timeline__action">{event.action}</div>
              {event.old_value && event.new_value && (
                <div className="small">
                  <span className="muted">было:</span> {truncate(event.old_value)}
                  <br />
                  <span className="muted">стало:</span> {truncate(event.new_value)}
                </div>
              )}
              {event.basis && <div className="small muted">основание: {event.basis}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function truncate(value: string, limit = 160): string {
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}