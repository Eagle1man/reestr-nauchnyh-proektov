/** Управление учётными записями, справочниками и настройками (M-09). */
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../auth';
import { Alert, Detail, ErrorAlert, Field, Spinner, Tabs } from '../components/ui';
import { fmtDate } from '../format';

interface AdminUser {
  id: string; login: string; email: string | null; full_name: string;
  is_active: boolean; must_reset: boolean; last_login_at: string | null;
  created_at: string; roles: string[]; person_id: string | null;
}

const ROLE_TITLES: Record<string, string> = {
  sysadmin: 'Системный администратор',
  techadmin: 'Технический администратор',
  rector: 'Ректор',
  council: 'Научный совет',
  prorector: 'Проректор по науке',
  secretary: 'Секретарь Научного совета',
  curator: 'Куратор программы',
};

export default function AdminPage() {
  const { can } = useAuth();
  const [tab, setTab] = useState('users');

  if (!can('is_admin')) {
    return (
      <div className="card">
        <ErrorAlert error={new Error('Раздел доступен техническому администратору')} />
      </div>
    );
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Администрирование</h1>
          <p>Учётные записи, роли, справочники, настройки и резервное копирование.</p>
        </div>
      </div>
      <Tabs
        tabs={[
          { key: 'users', label: 'Учётные записи' },
          { key: 'roles', label: 'Роли' },
          { key: 'dicts', label: 'Справочники' },
          { key: 'settings', label: 'Настройки' },
          { key: 'backup', label: 'Резервное копирование' },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === 'users' && <UsersTab />}
      {tab === 'roles' && <RolesTab />}
      {tab === 'dicts' && <DictsTab />}
      {tab === 'settings' && <SettingsTab />}
      {tab === 'backup' && <BackupTab />}
    </>
  );
}

function UsersTab() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState({ login: '', full_name: '', email: '' });
  const [password, setPassword] = useState('');
  const [includeInactive, setIncludeInactive] = useState(false);

  const load = useCallback(() => {
    void api<{ items: AdminUser[] }>(
      `/api/admin/users?limit=200&include_inactive=${includeInactive ? 'true' : 'false'}`,
    )
      .then((r) => setItems(r.items))
      .catch(setError);
  }, [includeInactive]);

  useEffect(load, [load]);

  async function create() {
    setError(null);
    try {
      const result = await api<AdminUser & { initial_password: string }>('/api/admin/users', {
        method: 'POST',
        body: {
          login: form.login,
          full_name: form.full_name,
          email: form.email || null,
          password: password || undefined,
        },
      });
      setPassword(result.initial_password);
      setNotice(
        `Учётная запись «${result.login}» создана. Пароль показывается один раз: ` +
        `${result.initial_password}`,
      );
      setForm({ login: '', full_name: '', email: '' });
      load();
    } catch (err) {
      setError(err);
    }
  }

  async function toggleActive(user: AdminUser) {
    try {
      await api(`/api/admin/users/${user.id}?is_active=${!user.is_active}`,
        { method: 'PATCH' });
      setNotice(
        user.is_active
          ? 'Учётная запись заблокирована. Внесённые данные и история сохранены.'
          : 'Учётная запись разблокирована',
      );
      load();
    } catch (err) {
      setError(err);
    }
  }

  async function resetPassword(user: AdminUser) {
    try {
      const result = await api<{ initial_password: string }>(
        `/api/admin/users/${user.id}/reset-password`, { method: 'POST' });
      setNotice(`Новый пароль для «${user.login}» (однократно): ${result.initial_password}`);
    } catch (err) {
      setError(err);
    }
  }

  async function setRoles(user: AdminUser, role: string, add: boolean) {
    const next = add
      ? Array.from(new Set([...user.roles, role]))
      : user.roles.filter((r) => r !== role);
    try {
      await api(`/api/admin/users/${user.id}/roles`, { method: 'PUT', body: next });
      setNotice('Роли обновлены, изменение зафиксировано в журнале');
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
        <h2 className="card__title">Создать учётную запись</h2>
        <div className="grid grid--3">
          <Field label="Логин" required>
            <input type="text" value={form.login}
              onChange={(e) => setForm({ ...form, login: e.target.value })} />
          </Field>
          <Field label="Ф. И. О." required>
            <input type="text" value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          </Field>
          <Field label="Служебный адрес" hint="Ключ сопоставления профиля (п.6.1)">
            <input type="text" value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
        </div>
        <Field label="Пароль" hint="Оставьте пустым — система сгенерирует стойкий пароль">
          <input type="password" value={password}
            onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </Field>
        <button className="btn" type="button"
          disabled={!form.login.trim() || !form.full_name.trim()}
          onClick={() => void create()}>
          Создать
        </button>
        <p className="small muted" style={{ marginBottom: 0 }}>
          Восстановление доступа выполняет администратор (п.11.1 п.4). Пароль
          показывается один раз и в журнал не записывается (SEC-05).
        </p>
      </div>

      <div className="card">
        <h2 className="card__title">Учётные записи</h2>
        <label className="checkbox">
          <input type="checkbox" checked={includeInactive}
            onChange={(e) => setIncludeInactive(e.target.checked)} />
          Показывать отключённые
        </label>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Логин</th><th>Ф. И. О.</th><th>Роли</th>
                <th>Последний вход</th><th>Состояние</th><th />
              </tr>
            </thead>
            <tbody>
              {items.map((user) => (
                <tr key={user.id}>
                  <td className="mono">{user.login}</td>
                  <td>
                    {user.full_name}
                    {user.email && <div className="small muted">{user.email}</div>}
                  </td>
                  <td className="small">
                    {user.roles.length === 0 ? '—' : user.roles.map((r) => ROLE_TITLES[r] ?? r).join(', ')}
                    <div style={{ marginTop: 4 }}>
                      {Object.entries(ROLE_TITLES)
                        .filter(([code]) => code !== 'curator')
                        .map(([code, title]) => (
                          <button
                            key={code}
                            type="button"
                            className="btn btn--secondary btn--sm"
                            style={{ marginRight: 3, marginBottom: 3,
                              opacity: user.roles.includes(code) ? 1 : 0.5 }}
                            onClick={() => void setRoles(user, code, !user.roles.includes(code))}
                          >
                            {user.roles.includes(code) ? '−' : '+'} {title}
                          </button>
                        ))}
                    </div>
                  </td>
                  <td className="small nowrap">
                    {user.last_login_at ? fmtDate(user.last_login_at) : 'ни разу'}
                  </td>
                  <td className="small">
                    {user.is_active ? 'активна' : 'отключена'}
                    {user.must_reset && <div>требует смены пароля</div>}
                  </td>
                  <td>
                    <div className="btn-row">
                      <button className="btn btn--secondary btn--sm" type="button"
                        onClick={() => void resetPassword(user)}>
                        Сбросить пароль
                      </button>
                      <button className={`btn btn--sm ${user.is_active ? 'btn--danger' : ''}`}
                        type="button" onClick={() => void toggleActive(user)}>
                        {user.is_active ? 'Отключить' : 'Включить'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function RolesTab() {
  const [data, setData] = useState<{
    roles: { code: string; title: string; may: string; may_not: string; note?: string }[];
    note: string;
  } | null>(null);

  useEffect(() => {
    void api<typeof data>('/api/admin/roles').then(setData).catch(() => setData(null));
  }, []);

  if (!data) return <Spinner />;
  return (
    <div className="card">
      <h2 className="card__title">Матрица ролей (п.4)</h2>
      <Alert kind="info">{data.note}</Alert>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Роль</th><th>Полномочия</th><th>Ограничения</th></tr>
          </thead>
          <tbody>
            {data.roles.map((role) => (
              <tr key={role.code}>
                <td className="nowrap">{role.title}</td>
                <td className="small">{role.may}</td>
                <td className="small">{role.may_not}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface DictItem {
  id: string; dict: string; code: string; title: string;
  sort_order: number; is_active: number;
}

function DictsTab() {
  const [groups, setGroups] = useState<Record<string, DictItem[]> | null>(null);
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [form, setForm] = useState({ dict: '', code: '', title: '' });

  const load = useCallback(() => {
    void api<{ items: Record<string, DictItem[]>; titles: Record<string, string> }>(
      '/api/admin/dictionaries',
    )
      .then((r) => { setGroups(r.items); setTitles(r.titles); })
      .catch(setError);
  }, []);

  useEffect(load, [load]);

  async function add() {
    setError(null);
    try {
      await api('/api/admin/dictionaries', {
        method: 'POST',
        body: { dict: form.dict, code: form.code, title: form.title, sort_order: 0 },
      });
      setForm({ ...form, code: '', title: '' });
      load();
    } catch (err) {
      setError(err);
    }
  }

  async function toggle(item: DictItem) {
    await api(`/api/admin/dictionaries/${item.id}`, {
      method: 'PATCH',
      body: { dict: item.dict, code: item.code, title: item.title,
        sort_order: item.sort_order, is_active: !item.is_active },
    }).catch(setError);
    load();
  }

  if (!groups) return <Spinner />;

  return (
    <>
      <ErrorAlert error={error} />
      <div className="card">
        <h2 className="card__title">Справочники (FR-30)</h2>
        <p className="small muted">
          Перечни меняются здесь, без правки кода (FR-35).
        </p>
        <div className="grid grid--3">
          <Field label="Справочник" required>
            <select value={form.dict} onChange={(e) => setForm({ ...form, dict: e.target.value })}>
              <option value="">— выберите —</option>
              {Object.entries(titles).map(([code, title]) => (
                <option key={code} value={code}>{title}</option>
              ))}
            </select>
          </Field>
          <Field label="Код" required>
            <input type="text" value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value })} />
          </Field>
          <Field label="Название" required>
            <input type="text" value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
        </div>
        <button className="btn" type="button"
          disabled={!form.dict || !form.code || !form.title}
          onClick={() => void add()}>
          Добавить
        </button>
      </div>

      {Object.entries(groups).map(([name, items]) => (
        <div className="card" key={name}>
          <h2 className="card__title">{titles[name] ?? name} ({items.length})</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Код</th><th>Название</th><th>Состояние</th><th /></tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td className="mono">{item.code}</td>
                    <td>{item.title}</td>
                    <td className="small">{item.is_active ? 'активна' : 'отключена'}</td>
                    <td>
                      <button className="btn btn--secondary btn--sm" type="button"
                        onClick={() => void toggle(item)}>
                        {item.is_active ? 'Отключить' : 'Включить'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </>
  );
}

function SettingsTab() {
  const [data, setData] = useState<{
    values: Record<string, string>;
    meta: Record<string, { updated_at: string; updated_by: string | null }>;
    environment: Record<string, unknown>;
    note: string;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  const [draft, setDraft] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    void api<typeof data>('/api/admin/settings').then(setData).catch(setError);
  }, []);

  useEffect(load, [load]);

  async function save() {
    setError(null);
    try {
      await api('/api/admin/settings', { method: 'PUT', body: { values: draft } });
      setNotice('Настройки сохранены, изменение зафиксировано в журнале');
      setDraft({});
      load();
    } catch (err) {
      setError(err);
    }
  }

  if (!data) return <Spinner />;

  return (
    <>
      {notice && <Alert kind="ok">{notice}</Alert>}
      <ErrorAlert error={error} />
      <div className="card">
        <h2 className="card__title">Настройки (FR-35)</h2>
        <p className="small muted">{data.note}</p>
        {Object.entries(data.values).map(([key, value]) => (
          <div className="field" key={key}>
            <label className="field__label">{key}</label>
            <input type="text" defaultValue={value}
              onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
            <div className="field__hint">
              Изменено: {fmtDate(data.meta[key]?.updated_at)}
            </div>
          </div>
        ))}
        <button className="btn" type="button"
          disabled={Object.keys(draft).length === 0}
          onClick={() => void save()}>
          Сохранить изменения
        </button>
      </div>

      <div className="card">
        <h2 className="card__title">Параметры окружения</h2>
        <Detail items={Object.entries(data.environment).map(
          ([key, value]) => [key, String(value)] as [string, string]) as [string, string][]} />
      </div>
    </>
  );
}

interface Backup {
  file: string;
  path: string;
  created_at: string;
  created_at_fmt?: string;
  size_bytes: number;
  tables?: number;
  integrity?: string;
  ok?: boolean;
  method?: string;
  label?: string;
  age_days?: number;
  within_retention?: boolean;
}

function BackupTab() {
  const [items, setItems] = useState<Backup[]>([]);
  const [result, setResult] = useState<Backup | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    void api<{ items: Backup[] }>('/api/admin/backup')
      .then((r) => setItems(r.items))
      .catch(setError);
  }, []);

  useEffect(load, [load]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const data = await api<Backup>('/api/admin/backup', { method: 'POST' });
      setResult(data);
      load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function verify(path: string) {
    setBusy(true);
    setError(null);
    try {
      setResult(await api<Backup>('/api/admin/backup/verify?path=' + encodeURIComponent(path),
        { method: 'POST' }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <ErrorAlert error={error} />
      <div className="card">
        <h2 className="card__title">Резервное копирование (п.11.4)</h2>
        <Alert kind="info">
          Копия создаётся через sqlite3.Connection.backup(), а не копированием
          файла: при работающем журнале WAL простая копия дала бы снимок без
          последних изменений. Проверка копии смотрит содержимое, а не только
          факт открытия файла.
        </Alert>
        <div className="btn-row">
          <button className="btn" type="button" disabled={busy} onClick={() => void create()}>
            Создать копию
          </button>
        </div>
        {result && (
          <Alert kind={result.ok === false ? 'error' : 'ok'}>
            <Detail items={[
              ['Файл', result.file],
              ['Метод', result.method ?? '—'],
              ['Размер', `${(result.size_bytes / 1024).toFixed(1)} КБ`],
              ['Таблиц', result.tables !== undefined ? String(result.tables) : '—'],
              ['Целостность', result.integrity ?? '—'],
              ['Создано', result.created_at_fmt ?? result.created_at],
            ]} />
          </Alert>
        )}
      </div>

      <div className="card">
        <h2 className="card__title">Копии ({items.length})</h2>
        {items.length === 0 ? (
          <p className="muted">Копий пока нет.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Файл</th><th>Создана</th><th>Размер</th><th>Метка</th>
                  <th>Срок хранения</th><th /></tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.file}>
                    <td className="mono small">{item.file}</td>
                    <td className="small nowrap">
                      {item.created_at_fmt ?? item.created_at}
                      <div className="muted">{item.age_days} дн.</div>
                    </td>
                    <td className="small">{(item.size_bytes / 1024).toFixed(1)} КБ</td>
                    <td className="small">{item.label || '—'}</td>
                    <td className="small">
                      {item.within_retention ? 'в сроке' : 'срок истёк'}
                    </td>
                    <td>
                      <button className="btn btn--secondary btn--sm" type="button"
                        onClick={() => void verify(item.path)}>
                        Проверить
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="small muted" style={{ marginBottom: 0 }}>
          Ежедневные копии хранятся не менее 30 календарных дней, недельная — в
          отдельном защищённом хранилище. Перед обновлением создаётся обязательная
          контрольная копия. RPO — не более 24 часов, RTO — не более 8 рабочих часов.
        </p>
      </div>
    </>
  );
}