/** Панель портфеля (FR-26) — одна страница, зелёные проекты сводно (п.8). */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, DeadlineItem, Dashboard } from '../api';
import { Alert, Badge, Empty, ErrorAlert, Spinner, Stat } from '../components/ui';
import { riskTone } from '../format';

const SEVERITY_TONE: Record<string, string> = {
  critical: 'red', high: 'yellow', normal: 'neutral',
};
const SEVERITY_TITLE: Record<string, string> = {
  critical: 'Требует немедленного решения',
  high: 'Требует решения',
  normal: 'В работе',
};

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    void api<Dashboard>('/api/dashboard')
      .then(setData)
      .catch(setError);
  }, []);

  if (error) return <ErrorAlert error={error} />;
  if (!data) return <Spinner />;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Панель портфеля</h1>
          <p>
            Сводные показатели и вопросы, требующие решения. Данные на{' '}
            {data.generated_at}.
          </p>
        </div>
        <Link className="btn btn--secondary" to="/reports/risks">
          Отчёт по рискам
        </Link>
      </div>

      <div className="grid grid--4" style={{ marginBottom: 14 }}>
        <Stat value={data.totals.projects} label="Проектов в портфеле" />
        <Stat value={data.totals.active} label="Активных, приостановленных, на пилоте" />
        <Stat value={data.totals.results} label="Результатов" />
        <Stat
          value={data.totals.overdue_milestones}
          label="Просроченных контрольных точек"
          tone={data.totals.overdue_milestones > 0 ? 'red' : ''}
        />
      </div>

      <div className="grid grid--3" style={{ marginBottom: 14 }}>
        <div className="card">
          <h2 className="card__title">Индикатор риска</h2>
          <table>
            <tbody>
              <tr>
                <td><Badge tone="red">Красный</Badge></td>
                <td className="right">{data.risk_summary.red}</td>
              </tr>
              <tr>
                <td><Badge tone="yellow">Жёлтый</Badge></td>
                <td className="right">{data.risk_summary.yellow}</td>
              </tr>
              <tr>
                <td><Badge tone="green">Зелёный</Badge></td>
                <td className="right">{data.risk_summary.green}</td>
              </tr>
            </tbody>
          </table>
          <p className="small muted" style={{ marginBottom: 0 }}>
            {data.risk_summary.green_note}. {data.risk_summary.yellow_action}.{' '}
            {data.risk_summary.red_action}.
          </p>
        </div>

        <div className="card">
          <h2 className="card__title">Маршруты</h2>
          <table>
            <tbody>
              {data.by_route.map((row) => (
                <tr key={row.code}>
                  <td>{row.title}</td>
                  <td className="right">{row.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted" style={{ marginBottom: 0 }}>
            Маршрут предложен системой по признакам T-01…T-06 и фиксируется
            уполномоченным лицом.
          </p>
        </div>

        <div className="card">
          <h2 className="card__title">Статусы</h2>
          <table>
            <tbody>
              {data.by_status.map((row) => (
                <tr key={row.code}>
                  <td>
                    <span className="mono">{row.code}</span> {row.title}
                  </td>
                  <td className="right">{row.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2 className="card__title">
          Вопросы, требующие решения ({data.questions_for_decision.length})
        </h2>
        {data.questions_for_decision.length === 0 ? (
          <Empty>Вопросов, требующих решения, нет.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Важность</th>
                  <th>Проект</th>
                  <th>Вопрос</th>
                  <th>Кто решает</th>
                </tr>
              </thead>
              <tbody>
                {data.questions_for_decision.map((q, i) => (
                  <tr key={i}>
                    <td className="nowrap">
                      <Badge tone={SEVERITY_TONE[q.severity]}>
                        {SEVERITY_TITLE[q.severity]}
                      </Badge>
                    </td>
                    <td className="nowrap">
                      <Link to={`/projects/${q.project_id}`} className="mono">
                        {q.code}
                      </Link>
                      <div className="small muted">{q.title}</div>
                    </td>
                    <td>{q.question}</td>
                    <td className="small nowrap">{q.who}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid grid--2">
        <DeadlineList
          title={`Просроченные точки (${data.deadlines.overdue.length})`}
          items={data.deadlines.overdue}
          overdue
        />
        <DeadlineList
          title={`Ближайшие сроки (${data.deadlines.upcoming.length})`}
          items={data.deadlines.upcoming}
        />
      </div>
    </>
  );
}

function DeadlineList({ title, items, overdue = false }: {
  title: string;
  items: DeadlineItem[];
  overdue?: boolean;
}) {
  return (
    <div className="card">
      <h2 className="card__title">{title}</h2>
      {items.length === 0 ? (
        <Empty>Нет записей.</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <tbody>
              {items.slice(0, 12).map((item) => (
                <tr key={item.milestone_id}>
                  <td className="nowrap">
                    <Badge tone={riskTone(overdue ? 'red' : 'green')}>
                      {item.planned_date_fmt}
                    </Badge>
                  </td>
                  <td>
                    <Link to={`/projects/${item.project_id}`} className="mono">
                      {item.code}
                    </Link>
                    <div className="small">{item.title}</div>
                    <div className="small muted">
                      Ответственный: {item.responsible || 'не назначен'}
                      {overdue && item.delay_working_days > 0 &&
                        ` · задержка ${item.delay_working_days} раб. дн.`}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {overdue && items.length > 0 && (
        <Alert kind="info">
          Жёлтый индикатор: руководитель за 5 рабочих дней указывает причину, меры и
          новый срок. Красный — задержка более 20 рабочих дней, рассматривает проректор.
        </Alert>
      )}
    </div>
  );
}