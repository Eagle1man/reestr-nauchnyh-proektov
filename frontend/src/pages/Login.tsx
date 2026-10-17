/**
 * Форма входа (FR-01).
 *
 * П.11.1: пароль от 12 символов, блокировка на 15 минут после пяти неудач.
 * Сообщения намеренно не различают «нет такого логина» и «неверный пароль»:
 * иначе форма позволяет перебирать учётные записи.
 */
import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth';
import { ApiError } from '../api';
import { Alert } from '../components/ui';

export default function LoginPage() {
  const { login } = useAuth();
  const [loginValue, setLoginValue] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(loginValue.trim(), password);
    } catch (err) {
      setError(err);
      setPassword('');
    } finally {
      setBusy(false);
    }
  }

  const locked = error instanceof ApiError && error.status === 423;
  const throttled = error instanceof ApiError && error.status === 429;

  return (
    <div style={{ maxWidth: 430, margin: '60px auto', padding: '0 16px' }}>
      <div className="card">
        <h1 style={{ fontSize: 18, marginTop: 0 }}>Реестр научных проектов</h1>
        <p className="muted small" style={{ marginTop: -6 }}>
          Южный университет (ИУБиП) · закрытая рабочая зона
        </p>

        {locked && (
          <Alert kind="warn">
            Вход заблокирован на 15 минут после пяти неудачных попыток (п.11.1).
          </Alert>
        )}
        {throttled && (
          <Alert kind="warn">
            Слишком много попыток входа с этого адреса. Повторите позже.
          </Alert>
        )}
        {Boolean(error) && !locked && !throttled && (
          <Alert kind="error">{errorMessage(error)}</Alert>
        )}

        <form onSubmit={submit}>
          <div className="field">
            <label className="field__label req" htmlFor="login">
              Учётная запись
            </label>
            <input
              id="login"
              name="login"
              type="text"
              autoComplete="username"
              autoFocus
              required
              value={loginValue}
              onChange={(e) => setLoginValue(e.target.value)}
              disabled={busy}
            />
            <div className="field__hint">Университетская учётная запись или служебный логин</div>
          </div>

          <div className="field">
            <label className="field__label req" htmlFor="password">
              Пароль
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy}
            />
            <div className="field__hint">
              Не менее 12 символов: строчные и прописные буквы, цифры, спецсимволы
            </div>
          </div>

          <button className="btn" type="submit" disabled={busy}>
            {busy ? 'Проверка…' : 'Войти'}
          </button>
        </form>
      </div>

      <p className="small muted">
        Сессия завершается после 60 минут бездействия. Учётная запись недоступна или
        требуется смена пароля — обратитесь к техническому администратору.
      </p>
      <p className="small">
        {/* Ссылка через роутер: в демонстрации приложение лежит в подкаталоге,
            и корневой путь увёл бы на 404. */}
        <Link to="/public">Открытый раздел «Наука»</Link>
      </p>
    </div>
  );
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Не удалось выполнить вход';
}