/** Профиль пользователя и смена пароля (п.11.1). */
import { FormEvent, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../auth';
import { Alert, Detail, ErrorAlert, Field } from '../components/ui';

const CATEGORY_TITLES: Record<string, string> = {
  staff: 'работник', student: 'обучающийся', aspirant: 'аспирант',
};

export default function ProfilePage() {
  const { user, person, matrix, refresh } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice('');
    if (next !== repeat) {
      setError(new Error('Новый пароль и его подтверждение не совпадают'));
      return;
    }
    try {
      await api('/api/auth/password', {
        method: 'POST',
        body: { current_password: current, new_password: next },
      });
      setNotice('Пароль изменён');
      setCurrent(''); setNext(''); setRepeat('');
      await refresh();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Профиль</h1>
          <p>{user?.full_name}</p>
        </div>
      </div>

      <div className="grid grid--2">
        <div className="card">
          <h2 className="card__title">Учётная запись</h2>
          <Detail items={[
            ['Логин', user?.login],
            ['Служебный адрес', user?.email],
            ['Роли', matrix?.global_roles.join(', ') || '—'],
            ['Доступ к портфелю', matrix?.is_portfolio ? 'да' : 'только свои проекты'],
            ['Импорт данных', matrix?.can_import ? 'да' : 'нет'],
            ['Публикация', matrix?.can_publish ? 'да' : 'нет'],
            ['Администрирование', matrix?.is_admin ? 'да' : 'нет'],
            ['Требуется смена пароля', user?.must_reset ? 'да' : 'нет'],
          ]} />
          {user?.must_reset && (
            <Alert kind="warn">
              Пароль выдан администратором. Смените его при первом входе.
            </Alert>
          )}
        </div>

        <div className="card">
          <h2 className="card__title">Связанный профиль человека (FR-03)</h2>
          {person ? (
            <Detail items={[
              ['Ф. И. О.', person.full_name],
              ['Место работы или обучения', person.work_place],
              ['Должность', person.position],
              ['Учёная степень', person.academic_degree],
              ['Категория', CATEGORY_TITLES[person.category] ?? person.category],
              ['Участие в проектах', person.projects?.length],
              ['Результаты', person.results?.length],
            ]} />
          ) : (
            <p className="muted">
              Профиль не связан. Связь устанавливается по служебному адресу при
              первом входе либо назначается администратором.
            </p>
          )}
        </div>
      </div>

      <div className="card">
        <h2 className="card__title">Смена пароля (п.11.1)</h2>
        {notice && <Alert kind="ok">{notice}</Alert>}
        <ErrorAlert error={error} />
        <form onSubmit={submit}>
          <div className="grid grid--3">
            <Field label="Текущий пароль" required>
              <input type="password" value={current} autoComplete="current-password"
                onChange={(e) => setCurrent(e.target.value)} required />
            </Field>
            <Field label="Новый пароль" required
              hint="Не менее 12 символов: строчные, прописные, цифры, спецсимволы">
              <input type="password" value={next} autoComplete="new-password"
                onChange={(e) => setNext(e.target.value)} required />
            </Field>
            <Field label="Подтверждение" required>
              <input type="password" value={repeat} autoComplete="new-password"
                onChange={(e) => setRepeat(e.target.value)} required />
            </Field>
          </div>
          <button className="btn" type="submit" disabled={!current || !next || !repeat}>
            Сменить пароль
          </button>
        </form>
      </div>
    </>
  );
}