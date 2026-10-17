/**
 * Публикации: список с фильтрами и показателями.
 *
 * Показатели показываются вместе со знаменателями (A-02): отдельно принятые и
 * направленные рукописи, отдельно работы без аннотации, отдельно неоценённые.
 * Числа считаются по уникальным работам, поэтому второй соавтор или второй
 * проект не увеличивают университетский итог (D-06, A-01).
 */
import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../../api';
import { ErrorAlert, Field, Spinner } from '../../components/ui';
import type { SciListResponse } from '../../science/types';
import { TYPE_TITLES } from '../../science/types';
import { Metric, ScienceHead } from './ScienceHead';

const EMPTY_FILTERS = { stage: '', category: '', year: '', q: '' };

export default function SciencePublicationsPage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<SciListResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  const filters = {
    stage: params.get('stage') ?? EMPTY_FILTERS.stage,
    category: params.get('category') ?? EMPTY_FILTERS.category,
    year: params.get('year') ?? EMPTY_FILTERS.year,
    q: params.get('q') ?? EMPTY_FILTERS.q,
  };

  const load = () => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value) query.set(key, value);
    }
    void api<SciListResponse>(`/api/science/publications?${query.toString()}`)
      .then(setData)
      .catch(setError);
  };

  useEffect(load, [params]);   // eslint-disable-line react-hooks/exhaustive-deps

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  if (error) return <ErrorAlert error={error} />;
  if (!data) return <Spinner text="Загрузка публикаций…" />;

  const stats = data.stats;
  return (
    <>
      <ScienceHead
        active="publications"
        notice={data.demo_notice}
        description="Уникальные работы с их стадией, происхождением записи и тематической оценкой."
      />

      <div className="grid grid--4">
        <Metric value={stats.published} label="опубликовано работ" />
        <Metric value={stats.accepted} label="принято рукописей (отдельно)" />
        <Metric value={stats.submitted} label="направлено (отдельно)" />
        <Metric value={stats.unique_works_total} label="всего уникальных работ" />
        <Metric value={stats.authors_total} label="авторов с работами" />
        <Metric value={stats.without_abstract} label="работ без аннотации" />
        <Metric
          value={`${stats.direct_confirmed} / ${stats.with_enough_data}`}
          label="прямая тематика / оценённых с достаточными данными"
        />
        <Metric value={stats.without_decision} label="ожидают решения эксперта" />
      </div>
      <p className="small muted">
        Паспорт темы версии {stats.passport_version}. Автоматические оценки и работы
        без достаточных данных в прямой доле не участвуют (A-02).
      </p>

      <div className="card">
        <h2 className="card__title">Фильтры</h2>
        <div className="grid grid--4">
          <Field label="Стадия">
            <select
              value={filters.stage}
              onChange={(event) => setFilter('stage', event.target.value)}
            >
              <option value="">все</option>
              {data.filters?.stages.map((stage) => (
                <option key={stage.code} value={stage.code}>{stage.title}</option>
              ))}
            </select>
          </Field>
          <Field label="Тематическая категория">
            <select
              value={filters.category}
              onChange={(event) => setFilter('category', event.target.value)}
            >
              <option value="">все</option>
              {data.filters?.categories.map((category) => (
                <option key={category.code} value={category.code}>{category.title}</option>
              ))}
            </select>
          </Field>
          <Field label="Год">
            <select
              value={filters.year}
              onChange={(event) => setFilter('year', event.target.value)}
            >
              <option value="">все</option>
              {data.filters?.years.map((year) => (
                <option key={year} value={year}>{year}</option>
              ))}
            </select>
          </Field>
          <Field label="Поиск по названию, изданию, автору">
            <input
              value={filters.q}
              onChange={(event) => setFilter('q', event.target.value)}
              placeholder="например: объяснимость"
            />
          </Field>
        </div>
        <p className="small muted">Найдено записей: {data.total}</p>
      </div>

      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>Работа</th>
              <th>Издание</th>
              <th>Стадия</th>
              <th>Год</th>
              <th>Тематическая оценка</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((publication) => (
              <tr key={publication.id}>
                <td>
                  <Link to={`/science/publications/${publication.id}`}>{publication.title_ru}</Link>
                  <div className="small muted">
                    {TYPE_TITLES[publication.type] ?? publication.type}
                    {publication.doi ? ` · DOI ${publication.doi}` : ''}
                    {publication.edn ? ` · EDN ${publication.edn}` : ''}
                  </div>
                </td>
                <td className="small">{publication.venue_title ?? '—'}</td>
                <td className="nowrap small">{publication.stage_title}</td>
                <td className="nowrap">{publication.year}</td>
                <td className="small">
                  {publication.category_title}
                  <div className="muted">{publication.topic_state_title}</div>
                </td>
              </tr>
            ))}
            {data.items.length === 0 && (
              <tr><td colSpan={5}>По заданным условиям публикаций нет.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}