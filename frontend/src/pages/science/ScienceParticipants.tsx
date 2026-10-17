/**
 * Участники научной деятельности.
 *
 * Показываются интервалы работы или обучения, подразделение и внешние
 * идентификаторы вместе со статусом проверки (D-01, F-01). Один человек может
 * состоять в нескольких категориях одновременно — например, аспирант и
 * сотрудник кафедры, — поэтому интервалы не сворачиваются в одну строку.
 */
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api';
import { Alert, ErrorAlert, Spinner } from '../../components/ui';
import type {
  SciParticipantResponse, SciParticipantsResponse,
} from '../../science/types';
import { fmtDate, ID_STATUS_TITLES } from '../../science/types';
import { ScienceHead } from './ScienceHead';

const CATEGORY_TITLES: Record<string, string> = {
  staff: 'работник',
  aspirant: 'аспирант',
  student: 'студент',
};

export function ScienceParticipantsPage() {
  const [data, setData] = useState<SciParticipantsResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    void api<SciParticipantsResponse>('/api/science/participants')
      .then(setData)
      .catch(setError);
  }, []);

  if (error) return <ErrorAlert error={error} />;
  if (!data) return <Spinner text="Загрузка участников…" />;

  return (
    <>
      <ScienceHead
        active="participants"
        notice={data.demo_notice}
        description="Кто ведёт научную работу: категории, подразделение, интервалы и идентификаторы."
      />
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>Участник</th><th>Категория</th><th>Подразделение</th>
              <th>Идентификаторы</th><th>Работ</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((participant) => (
              <tr key={participant.person_id}>
                <td>
                  <Link to={`/science/participants/${participant.person_id}`}>
                    {participant.name}
                  </Link>
                  {participant.position && (
                    <div className="small muted">{participant.position}</div>
                  )}
                </td>
                <td className="small">
                  {CATEGORY_TITLES[participant.category] ?? participant.category}
                </td>
                <td className="small">{participant.unit ?? '—'}</td>
                <td className="small">
                  {participant.external_ids.length === 0 ? (
                    <span className="muted">
                      не переданы
                      {participant.ids_unverified ? ' (в выгрузке не было)' : ''}
                    </span>
                  ) : participant.external_ids.map((id) => (
                    <div key={id.system}>
                      <span className="mono">{id.value}</span>
                      <span className="muted"> · {id.system} · {ID_STATUS_TITLES[id.status] ?? id.status}</span>
                    </div>
                  ))}
                </td>
                <td className="nowrap">
                  {participant.works_published} / {participant.works_total}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {Object.keys(data.duplicates ?? {}).length > 0 && (
        <Alert kind="warn">
          В выгрузке одна фамилия записана несколькими способами — по всей
          видимости, это один человек, но записи не объединены: без AuthorID
          или ORCID склейка была бы догадкой (D-02). Требуется сверка
          библиотекой:{' '}
          {Object.entries(data.duplicates ?? {}).map(([surname, names]) => (
            <span key={surname}>
              <strong>{surname}</strong>: {names.join(' / ')}.{' '}
            </span>
          ))}
        </Alert>
      )}
    </>
  );
}

export function ScienceParticipantPage() {
  const { id } = useParams();
  const [data, setData] = useState<SciParticipantResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    void api<SciParticipantResponse>(`/api/science/participants/${id}`)
      .then(setData)
      .catch(setError);
  }, [id]);

  if (error) return <ErrorAlert error={error} />;
  if (!data) return <Spinner text="Загрузка участника…" />;
  const participant = data.participant;

  return (
    <>
      <ScienceHead
        active="participants"
        notice={data.demo_notice}
        description="Личный профиль участника научной деятельности."
      />
      <div className="page-head">
        <div>
          <h2>{participant.name}</h2>
          <p className="small muted">{participant.position ?? '—'}</p>
        </div>
      </div>

      <div className="grid grid--2">
        <div className="card">
          <h2 className="card__title">Интервалы работы или обучения</h2>
          <table>
            <thead><tr><th>С</th><th>По</th><th>Категория</th><th>Подразделение</th></tr></thead>
            <tbody>
              {participant.periods.map((period) => (
                <tr key={`${period.from}-${period.unit}`}>
                  <td className="nowrap">{fmtDate(period.from)}</td>
                  <td className="nowrap">{period.to ? fmtDate(period.to) : 'по настоящее время'}</td>
                  <td className="small">
                    {CATEGORY_TITLES[period.category] ?? period.category}
                  </td>
                  <td className="small">{period.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h2 className="card__title">Внешние идентификаторы</h2>
          {participant.external_ids.length === 0
            ? <p className="small muted">Идентификаторы не подтверждены.</p>
            : (
              <table>
                <thead><tr><th>Система</th><th>Значение</th><th>Проверка</th></tr></thead>
                <tbody>
                  {participant.external_ids.map((idItem) => (
                    <tr key={idItem.system}>
                      <td className="small">{idItem.system}</td>
                      <td className="mono">{idItem.value}</td>
                      <td className="small">
                        {ID_STATUS_TITLES[idItem.status] ?? idItem.status}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          <p className="small muted">
            Идентификаторы хранятся отдельными записями с названием системы:
            SPIN и AuthorID — разные поля, их совпадение значения не означает
            (D-01).
          </p>
        </div>
      </div>

      <div className="card">
        <h2 className="card__title">
          Работы: опубликовано {participant.works_published} из {participant.works_total}
        </h2>
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
              <tr><td colSpan={4}>Работ в реестре не заведено.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}