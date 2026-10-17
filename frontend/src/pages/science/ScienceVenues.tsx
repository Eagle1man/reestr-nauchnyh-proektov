/**
 * Издания: журналы и сборники со статусами по каждому перечню ОТДЕЛЬНО.
 *
 * Статусы РИНЦ, РSCI, ВАК и «Белый список» не сводятся в один «уровень»
 * (I-11): у каждого свой уровень, год и источник. Текущий статус и известный
 * исторический показываются рядом, потому что уровень года публикации и
 * уровень сегодняшнего дня — разные вещи (I-08).
 */
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api';
import { ErrorAlert, Spinner } from '../../components/ui';
import type {
  SciStatus, SciVenueResponse, SciVenuesResponse,
} from '../../science/types';
import { AVAILABILITY_TITLES, fmtDate } from '../../science/types';
import { ScienceHead } from './ScienceHead';

function StatusTable({ statuses, history }: {
  statuses: SciStatus[]; history?: SciStatus[];
}) {
  if (statuses.length === 0 && !(history?.length)) {
    return <p className="small muted">Статусы в перечнях не определены.</p>;
  }
  return (
    <>
      <table>
        <thead>
          <tr>
            <th>Перечень</th><th>Уровень</th><th>Год</th>
            <th>Состояние</th><th>Источник</th><th>Дата</th>
          </tr>
        </thead>
        <tbody>
          {statuses.map((status, index) => (
            <tr key={`${status.list}-${status.year}-${index}`}>
              <td>{status.list}</td>
              <td className="nowrap">{status.level ?? '—'}</td>
              <td className="nowrap">{status.year ?? '—'}</td>
              <td className="small">{AVAILABILITY_TITLES[status.availability]}</td>
              <td className="small muted">{status.source}</td>
              <td className="small nowrap">{fmtDate(status.received_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {history && history.length > 0 && (
        <p className="small muted">
          Исторические уровни (на год публикации, отдельно от текущих):
          {history.map((status) => `${status.list} ${status.year} — уровень ${status.level ?? '—'}`).join('; ')}
        </p>
      )}
    </>
  );
}

export function ScienceVenuesPage() {
  const [data, setData] = useState<SciVenuesResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    void api<SciVenuesResponse>('/api/science/venues').then(setData).catch(setError);
  }, []);

  if (error) return <ErrorAlert error={error} />;
  if (!data) return <Spinner text="Загрузка изданий…" />;

  return (
    <>
      <ScienceHead
        active="venues"
        notice={data.demo_notice}
        description="Журналы и сборники: идентификаторы и статус по каждому перечню отдельно."
      />
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>Издание</th><th>ISSN</th><th>Перечни</th>
              <th>Работ</th><th>Опубликовано</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((venue) => (
              <tr key={venue.id}>
                <td><Link to={`/science/venues/${venue.id}`}>{venue.title}</Link>
                  <div className="small muted">{venue.publisher}</div>
                </td>
                <td className="mono nowrap">{venue.issn ?? '—'}</td>
                <td className="small">
                  {venue.statuses.length
                    ? venue.statuses.map((status) => status.list).join(', ')
                    : '—'}
                </td>
                <td>{venue.works_total ?? 0}</td>
                <td>{venue.works_published ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function ScienceVenuePage() {
  const { id } = useParams();
  const [data, setData] = useState<SciVenueResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    void api<SciVenueResponse>(`/api/science/venues/${id}`).then(setData).catch(setError);
  }, [id]);

  if (error) return <ErrorAlert error={error} />;
  if (!data) return <Spinner text="Загрузка издания…" />;
  const venue = data.venue;

  return (
    <>
      <ScienceHead
        active="venues"
        notice={data.demo_notice}
        description="Карточка издания: идентификаторы, статусы и связанные работы."
      />
      <div className="page-head">
        <div>
          <h2>{venue.title}</h2>
          <p className="small muted">
            {venue.publisher} · тип: {venue.type}
            {' '}· ISSN <span className="mono">{venue.issn ?? '—'}</span>
            {' '}· eISSN <span className="mono">{venue.eissn ?? '—'}</span>
          </p>
        </div>
      </div>

      <div className="card">
        <h2 className="card__title">Статусы по перечням</h2>
        <StatusTable statuses={venue.statuses} history={venue.status_history} />
      </div>

      <div className="card">
        <h2 className="card__title">Публикации университета ({data.publications.length})</h2>
        <table>
          <thead><tr><th>Работа</th><th>Год</th><th>Стадия</th><th>Категория темы</th></tr></thead>
          <tbody>
            {data.publications.map((publication) => (
              <tr key={publication.id}>
                <td>
                  <Link to={`/science/publications/${publication.id}`}>
                    {publication.title_ru}
                  </Link>
                </td>
                <td className="nowrap">{publication.year}</td>
                <td className="small nowrap">{publication.stage_title}</td>
                <td className="small">{publication.category_title}</td>
              </tr>
            ))}
            {data.publications.length === 0 && (
              <tr><td colSpan={4}>Работ этого издания в реестре нет.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}