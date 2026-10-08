/** Общие элементы интерфейса. Доступны с клавиатуры (п.10.2 п.7). */

import { ReactNode, useEffect, useState } from 'react';
import { ApiError } from '../api';

export function Alert({ kind, children }: {
  kind: 'error' | 'ok' | 'warn' | 'info';
  children: ReactNode;
}) {
  return (
    <div className={`alert alert--${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  );
}

/** Сообщение об ошибке с точным перечнем полей (FR-07, п.10.2 п.6). */
export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  if (error instanceof ApiError) {
    return (
      <Alert kind="error">
        <strong>{error.message}</strong>
        {error.problems.length > 0 && (
          <ul>
            {error.problems.map((p, i) => (
              <li key={i}>{p.field ? `${p.field}: ${p.reason}` : p.reason}</li>
            ))}
          </ul>
        )}
      </Alert>
    );
  }
  return (
    <Alert kind="error">
      {error instanceof Error ? error.message : 'Неизвестная ошибка'}
    </Alert>
  );
}

export function Spinner({ text = 'Загрузка…' }: { text?: string }) {
  return (
    <div className="spinner" role="status" aria-live="polite">
      {text}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Badge({ tone, children }: { tone: string; children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function Stat({ value, label, tone = '' }: {
  value: ReactNode;
  label: string;
  tone?: string;
}) {
  return (
    <div className={`stat ${tone ? `stat--${tone}` : ''}`}>
      <div className="stat__value">{value}</div>
      <div className="stat__label">{label}</div>
    </div>
  );
}

export function Field({ label, code, required, hint, children }: {
  label: string;
  code?: string;
  required?: boolean;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <label className={`field__label ${required ? 'req' : ''}`}>
        {label}
        {code && <span className="field__code"> · {code}</span>}
      </label>
      {children}
      {hint && <div className="field__hint">{hint}</div>}
    </div>
  );
}

export function Tabs({ tabs, active, onChange }: {
  tabs: { key: string; label: string; count?: number }[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          role="tab"
          aria-selected={active === tab.key}
          className={active === tab.key ? 'active' : ''}
          onClick={() => onChange(tab.key)}
          type="button"
        >
          {tab.label}
          {tab.count !== undefined && ` (${tab.count})`}
        </button>
      ))}
    </div>
  );
}

/** Подтверждение необратимого действия (FR-31 архивирование, ПС-22 блокировка). */
export function ConfirmButton({ label, confirmLabel, onConfirm, tone = '' }: {
  label: string;
  confirmLabel: string;
  onConfirm: () => void;
  tone?: string;
}) {
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 6000);
    return () => clearTimeout(timer);
  }, [armed]);

  if (!armed) {
    return (
      <button className={`btn ${tone}`} type="button" onClick={() => setArmed(true)}>
        {label}
      </button>
    );
  }
  return (
    <span className="btn-row">
      <button
        className="btn btn--danger"
        type="button"
        onClick={() => {
          setArmed(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </button>
      <button className="btn btn--secondary" type="button" onClick={() => setArmed(false)}>
        Отмена
      </button>
    </span>
  );
}

/** Данные в формате «ключ — значение» для карточек. */
export function Detail({ items }: { items: [string, ReactNode][] }) {
  const visible = items.filter(([, value]) => value !== null && value !== undefined && value !== '');
  if (visible.length === 0) return null;
  return (
    <dl className="detail">
      {visible.map(([key, value], i) => (
        <div key={i} style={{ display: 'contents' }}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}