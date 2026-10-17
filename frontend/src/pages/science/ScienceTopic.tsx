/**
 * Паспорт темы и сводка тематической оценки.
 *
 * Страница отвечает на два вопроса, которые задаёт ТЗ: по каким критериям
 * принимается решение (паспорт, версия, направления) и сколько работ
 * оценено. Смещение автоматических оценок и работ без достаточных данных в
 * прямой доле не участвует — иначе показатель выглядел бы лучше, чем есть
 * (A-02, T-09).
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { Alert, ErrorAlert, Spinner } from '../../components/ui';
import type { SciTopicResponse } from '../../science/types';
import { AC01_REQUIRED, fmtDate } from '../../science/types';
import { Metric, ScienceHead } from './ScienceHead';

export default function ScienceTopicPage() {
  const [data, setData] = useState<SciTopicResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    void api<SciTopicResponse>('/api/science/topic').then(setData).catch(setError);
  }, []);

  if (error) return <ErrorAlert error={error} />;
  if (!data) return <Spinner text="Загрузка паспорта темы…" />;
  const { passport, stats } = data;

  return (
    <>
      <ScienceHead
        active="topic"
        notice={data.demo_notice}
        description="Главная тема, утверждённые критерии и состояние тематической оценки."
      />

      <div className="card">
        <h2 className="card__title">Главная тема</h2>
        <p>{passport.title}</p>
        <p className="small muted">
          Паспорт {passport.id} · версия {passport.version} · {passport.status}
          {' '}· действует с {fmtDate(passport.approved_at)}
        </p>
        <Alert kind="info">
          Тематическая оценка не является заключением о научной новизне, качестве
          методологии или зачёте для диссертации (T-09).
        </Alert>
      </div>

      <div className="card">
        <h2 className="card__title">Направления ({passport.directions.length})</h2>
        <ol className="small">
          {passport.directions.map((direction) => (
            <li key={direction.code}>
              <span className="mono">{direction.code}</span> {direction.title}
            </li>
          ))}
        </ol>
      </div>

      <div className="card">
        <h2 className="card__title">Категории решения ({passport.categories.length})</h2>
        <table>
          <thead><tr><th>Категория</th><th>Правило решения</th><th>Работ</th></tr></thead>
          <tbody>
            {passport.categories.map((category) => (
              <tr key={category.code}>
                <td className="nowrap">{category.title}</td>
                <td className="small">{category.rule}</td>
                <td>{stats.categories[category.code] ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid--4">
        <Metric value={stats.direct_confirmed} label="подтверждённых прямых работ" />
        <Metric value={stats.with_enough_data} label="работ с достаточными данными и решением" />
        <Metric value={stats.without_decision} label="ожидают решения эксперта" />
        <Metric value={stats.without_abstract} label="работ без аннотации (данных недостаточно)" />
        <Metric value={stats.real_total} label="реальных записей в разделе" />
        <Metric value={stats.demo_total} label="записей-демо (в приёмку не идут)" />
      </div>

      <div className="card">
        <h2 className="card__title">Состояние приёмки по реальным данным</h2>
        <p className="small">
          Критерий AC-01 требует минимум {AC01_REQUIRED} реальных записей
          eLIBRARY/РИНЦ. В разделе их {stats.real_total}
          {stats.real_total >= AC01_REQUIRED
            ? ' — по количеству критерий закрывается.'
            : ` — не хватает ${AC01_REQUIRED - stats.real_total}.`}
          {' '}Из них eLIBRARY — {stats.elibrary_total}, Scopus — {stats.scopus_total}.
        </p>
        <Alert kind={stats.real_total >= AC01_REQUIRED ? 'info' : 'warn'}>
          Происхождение данных при этом остаётся частичным: выгрузки сделаны
          заказчиком из личного кабинета и вручную, а не официальным экспортом
          организации (I-01), и аннотаций в них не было — поэтому тематическая
          оценка по этим работам остаётся «Недостаточно данных» (T-02). Аннотации
          отдаёт XML-выгрузка eLIBRARY: их стоит запросить вместе с
          подтверждением по AuthorID.
        </Alert>
        <Alert kind="info">
          <strong>Решения эксперта, которые видны на страницах карточек,
          поставлены на демонстрационных работах.</strong>{' '}
          Их {stats.demo_with_decisions} из {stats.demo_total} демо-работ — это
          сделано специально, чтобы показать работу оценки: у реальных работ
          аннотаций нет, и оценка по ним ещё не выносилась. Когда придут
          аннотации, решения появятся и на настоящих работах.
        </Alert>
      </div>

      <p className="small muted">
        Прямая доля считается как {stats.direct_confirmed} из {stats.with_enough_data};
        {' '}версия паспорта — {stats.passport_version}. Смещение оценок сохранено вместе с
        машинным ответом в карточке каждой работы:{' '}
        <Link to="/science">вернуться к публикациям</Link>.
      </p>
    </>
  );
}