/**
 * Кнопка «Сообщить об ошибке» и форма отчёта для разработчика.
 *
 * Отчёт собирается на машине пользователя и уходит только по его команде:
 * копированием в буфер, письмом или задачей в репозитории. Никуда ничего
 * не отправляется молча — человек видит текст и сам решает, что с ним
 * делать. Это осознанно: система работает с данными вуза, и автономная
 * отправка была бы утечкой (SEC-05).
 */
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import {
  buildReport, clearErrors, mailtoLink, recentErrors, subscribe,
} from '../errors';

interface ServerErrors {
  server?: { total_in_window: number; by_kind: Record<string, number> };
  recent_errors?: { at: string; kind: string; message: string; reference?: string; path?: string }[];
}

function currentLogin(): string | null {
  try {
    return window.localStorage.getItem('rnp.login');
  } catch {
    return null;
  }
}

function prettyServerErrors(data?: ServerErrors): string | undefined {
  if (!data) return undefined;
  const rows = (data.recent_errors ?? []).map((entry) => {
    const ref = entry.reference ? ` [${entry.reference}]` : '';
    const path = entry.path ? ` ${entry.path}` : '';
    return `${entry.at}${ref} ${entry.kind}${path}: ${entry.message}`;
  });
  if (!rows.length) {
    const total = data.server?.total_in_window ?? 0;
    return total ? 'Серверных ошибок не зафиксировано.' : undefined;
  }
  return rows.join('\n');
}

export default function ErrorReportButton() {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const [report, setReport] = useState('');
  const [copied, setCopied] = useState(false);
  const [server, setServer] = useState<ServerErrors | undefined>();
  const [count, setCount] = useState(0);

  const refreshCount = useCallback(() => {
    setCount(recentErrors().length);
  }, []);

  // Подписка, а не счёт при монтировании: ошибка может возникнуть позже,
  // и человек должен увидеть счётчик сразу, а не после перезагрузки.
  useEffect(() => subscribe(refreshCount), [refreshCount]);

  /** Отчёт администратора: ошибки сервера, которых не видит браузер. */
  const loadServerErrors = useCallback(async () => {
    try {
      setServer(await api<ServerErrors>('/api/admin/diagnostics'));
    } catch {
      // Раздел доступен не всем ролям, и это не повод ломать форму:
      // отчёт соберётся из данных браузера.
      setServer(undefined);
    }
  }, []);

  const build = useCallback(() => {
    setReport(buildReport({
      login: currentLogin(),
      baseUrl: window.location.origin,
      extra: note.trim() || undefined,
      serverErrors: prettyServerErrors(server),
    }));
  }, [note, server]);

  useEffect(() => {
    if (!open) return;
    void loadServerErrors();
    build();
  }, [open, loadServerErrors, build]);

  const copy = async () => {
    build();
    try {
      await navigator.clipboard.writeText(report);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      // Буфер недоступен: текст всё равно виден в поле, его можно
      // выделить и скопировать вручную.
      setCopied(false);
    }
  };

  const openMail = () => {
    build();
    window.location.href = mailtoLink(report);
  };

  const issueLink = () => {
    const url = 'https://github.com/Eagle1man/reestr-demo/issues/new'
      + `?title=${encodeURIComponent('Ошибка: ' + (recentErrors()[0]?.message ?? 'жалоба пользователя'))}`
      + `&body=${encodeURIComponent(report)}`;
    window.open(url, '_blank', 'noopener');
  };

  const clearAll = async () => {
    clearErrors();
    refreshCount();
    setNote('');
    setServer(undefined);
    build();
    try {
      await api('/api/admin/diagnostics/clear', { method: 'POST' });
    } catch {
      // Не администратор — серверный журнал трогать нельзя, и это нормально.
    }
  };

  return (
    <>
      <button
        type="button"
        className="report-fab"
        onClick={() => setOpen(true)}
        title="Сообщить разработчику об ошибке"
      >
        {count > 0 ? `Ошибки: ${count}` : 'Сообщить об ошибке'}
      </button>

      {open && (
        <div className="report-backdrop" role="dialog" aria-modal="true"
             aria-label="Отчёт об ошибке">
          <div className="report-panel">
            <h2>Сообщить разработчику</h2>
            <p className="report-lead">
              Опишите, что делали и что получилось. Отчёт соберётся из
              ошибок, которые система записала на вашей машине, и его
              можно отправить письмом или в задачу. Никуда ничего не
              уходит само собой.
            </p>

            <label className="report-field">
              Что вы делали, когда возникла ошибка
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={3}
                placeholder="Например: нажимал «Сохранить» в карточке проекта, после этого страница стала пустой"
              />
            </label>

            <label className="report-field">
              Собранный отчёт
              <textarea value={report} readOnly rows={12} />
            </label>

            <div className="report-actions">
              <button type="button" onClick={copy}>
                {copied ? 'Скопировано' : 'Скопировать'}
              </button>
              <button type="button" onClick={openMail}>Отправить письмом</button>
              <button type="button" onClick={issueLink}>Создать задачу</button>
              <button type="button" className="report-danger" onClick={clearAll}>
                Очистить
              </button>
              <button type="button" onClick={() => setOpen(false)}>Закрыть</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}