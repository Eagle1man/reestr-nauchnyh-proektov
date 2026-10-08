/** Напоминания и задачи пользователя (FR-24). */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { Badge, Empty, ErrorAlert, Spinner } from '../components/ui';

interface Reminder {
  kind: string;
  severity: 'critical' | 'high' | 'normal';
  title: string;
  detail: string;
  due_at?: string;
  link?: string;
  project_id?: string;
}

interface Response {
  items: Reminder[];
  counts: { critical: number; high: number; normal: number };
  note: string;
}

const TONE: Record<string, string> = { critical: 'red', high: 'yellow', normal: 'neutral' };
const TITLE: Record<string, string> = {
  critical: 'Срочно', high: 'Важно', normal: 'В работе',
};

export default function RemindersPage() {
  const [data, setData] = useState<Response | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    void api<Response>('/api/reminders')
      .then(setData)
      .catch(setError);
  }, []);

  if (error) return <ErrorAlert error={error} />;
  if (!data) return <Spinner />;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Назначения и сроки</h1>
          <p>
            Срочно: {data.counts.critical} · Важно: {data.counts.high} ·{' '}
            В работе: {data.counts.normal}
          </p>
        </div>
      </div>

      <div className="card">
        {data.items.length === 0 ? (
          <Empty>Заданий, требующих действия, нет.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Важность</th><th>Что требуется</th><th>Пояснение</th></tr>
              </thead>
              <tbody>
                {data.items.map((item, i) => (
                  <tr key={i}>
                    <td className="nowrap">
                      <Badge tone={TONE[item.severity]}>{TITLE[item.severity]}</Badge>
                    </td>
                    <td>
                      {item.link ? (
                        <Link to={item.link.replace(/^\//, '/')}>{item.title}</Link>
                      ) : item.title}
                    </td>
                    <td className="small">{item.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="small muted" style={{ marginBottom: 0 }}>{data.note}</p>
      </div>
    </>
  );
}