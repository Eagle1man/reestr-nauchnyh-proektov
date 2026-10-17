/**
 * Карточка публикации.
 *
 * Что показывается и почему именно так:
 *   стадия публикации и её даты отдельно от индексации в базах (D-04);
 *   происхождение записи и основание университетской принадлежности (D-03, D-05);
 *   аннотация целиком, чтобы эксперт принимал решение по тому же тексту, что и
 *   модель, и мог проверить фрагменты (T-05, UI-02);
 *   машинная оценка и решение эксперта рядом: правка эксперта не затирает
 *   ответ модели (T-07).
 */
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api';
import { Alert, ErrorAlert, Field, Spinner } from '../../components/ui';
import type {
  SciDecision, SciPassport, SciPublicationResponse, SciTopicResponse,
} from '../../science/types';
import {
  CONFIRMATION_TITLES, fmtDate, TYPE_TITLES,
} from '../../science/types';
import { ScienceHead } from './ScienceHead';

export default function SciencePublicationPage() {
  const { id } = useParams();
  const [data, setData] = useState<SciPublicationResponse | null>(null);
  const [passport, setPassport] = useState<SciPassport | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ category: '', directions: [] as string[], explanation: '' });
  const [notice, setNotice] = useState('');

  const load = () => {
    void api<SciPublicationResponse>(`/api/science/publications/${id}`)
      .then((response) => {
        setData(response);
        setForm({
          category: response.publication.topic.category,
          directions: response.publication.topic.directions,
          explanation: response.publication.topic.explanation,
        });
      })
      .catch(setError);
  };

  useEffect(load, [id]);

  // Паспорт темы — единственный источник допустимых категорий и направлений:
  // список в коде разошёлся бы с утверждёнными критериями при их обновлении.
  useEffect(() => {
    void api<SciTopicResponse>('/api/science/topic')
      .then((response) => setPassport(response.passport))
      .catch(setError);
  }, []);

  async function saveDecision() {
    setSaving(true);
    setError(null);
    setNotice('');
    try {
      await api(`/api/science/publications/${id}/topic`, {
        method: 'POST',
        body: {
          category: form.category,
          directions: form.directions,
          explanation: form.explanation,
        },
      });
      setNotice('Решение эксперта сохранено; машинная оценка осталась в истории.');
      load();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  if (error && !data) return <ErrorAlert error={error} />;
  if (!data) return <Spinner text="Загрузка публикации…" />;
  const publication = data.publication;
  const topic: SciDecision = publication.topic;

  return (
    <>
      <ScienceHead
        active="publications"
        notice={data.demo_notice}
        description="Карточка работы: библиография, авторство, издание и тематическая оценка."
      />

      <div className="page-head">
        <div>
          <h2>{publication.title_ru}</h2>
          {publication.title_en && <p className="muted">{publication.title_en}</p>}
          <p className="small muted">
            <span className="mono">{publication.id}</span> ·{' '}
            {TYPE_TITLES[publication.type] ?? publication.type} · {publication.year}
            {' '}· запись источника <span className="mono">{publication.source_record_id}</span>
          </p>
        </div>
      </div>

      {notice && <Alert kind="ok">{notice}</Alert>}
      {error && data && <ErrorAlert error={error} />}

      {publication.source_notes?.map((text) => (
        <Alert key={text} kind="warn">{text}</Alert>
      ))}

      <div className="grid grid--2">
        <div className="card">
          <h2 className="card__title">Библиография и стадия</h2>
          <ul className="small">
            <li>Стадия публикации: <strong>{publication.stage_title}</strong></li>
            <li>
              Направлена: {fmtDate(publication.stage_dates.submitted)} · принята:{' '}
              {fmtDate(publication.stage_dates.accepted)} · опубликована:{' '}
              {fmtDate(publication.stage_dates.published)}
            </li>
            <li>
              Точность даты: {publication.date_precision === 'year'
                ? 'только год; дата не восстанавливается (D-07)'
                : publication.date_precision}
            </li>
            <li>DOI: <span className="mono">{publication.doi ?? 'нет данных'}</span></li>
            <li>EDN: <span className="mono">{publication.edn ?? 'нет данных'}</span></li>
            <li>Источник: {publication.source_system}, загружено {fmtDate(publication.imported_at)}</li>
            <li>Происхождение записи: <strong>{publication.source_kind_title}</strong></li>
            {publication.registration && (
              <li>Регистрация программы для ЭВМ: <span className="mono">{publication.registration}</span></li>
            )}
            {publication.citations_elibrary !== undefined && (
              <li>
                Цитирований в eLIBRARY на дату выгрузки: {publication.citations_elibrary}
              </li>
            )}
            <li>
              Принадлежность университету: {publication.university_owned ? 'да' : 'нет'}
              {' '}— {publication.ownership_basis}
            </li>
          </ul>
        </div>

        <div className="card">
          <h2 className="card__title">Издание</h2>
          {data.venue ? (
            <ul className="small">
              <li>
                <Link to={`/science/venues/${data.venue.id}`}>{data.venue.title}</Link>
              </li>
              <li>ISSN: <span className="mono">{data.venue.issn ?? '—'}</span>;
                {' '}eISSN: <span className="mono">{data.venue.eissn ?? '—'}</span></li>
              <li>Издатель: {data.venue.publisher}</li>
            </ul>
          ) : <p className="small muted">Издание не определено.</p>}
        </div>
      </div>

      <div className="card">
        <h2 className="card__title">Авторы ({publication.authors.length})</h2>
        <table>
          <thead>
            <tr><th>Место</th><th>Автор</th><th>Аффилиация</th><th>Подтверждение</th></tr>
          </thead>
          <tbody>
            {publication.authors.map((author) => (
              <tr key={`${publication.id}-${author.person_id}-${author.order}`}>
                <td className="nowrap">{author.order}</td>
                <td>
                  <Link to={`/science/participants/${author.person_id}`}>{author.name}</Link>
                </td>
                <td className="small">{author.affiliation}</td>
                <td className="small">
                  {CONFIRMATION_TITLES[author.confirmation]}
                  {author.confirmed_at ? `, ${fmtDate(author.confirmed_at)}` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2 className="card__title">Аннотация и ключевые слова</h2>
        {publication.abstract_ru ? (
          <>
            <p className="small">{publication.abstract_ru}</p>
            <p className="small muted">
              Ключевые слова: {publication.keywords_ru.join(', ') || 'не указаны'}
            </p>
          </>
        ) : (
          <Alert kind="warn">
            Аннотация отсутствует, поэтому тематическая оценка не выносится по
            существу и остаётся «Недостаточно данных» (T-02). Текст можно
            добавить из разрешённого источника с указанием происхождения (I-06).
          </Alert>
        )}
      </div>

      <div className="card">
        <h2 className="card__title">Тематическая оценка</h2>
        <div className="grid grid--2">
          <div>
            <p className="small">
              <strong>Категория:</strong> {publication.category_title}
              {' · '}<strong>направления:</strong>{' '}
              {publication.direction_titles.join(', ') || 'не назначены'}
            </p>
            <p className="small">
              <strong>Состояние:</strong> {publication.topic_state_title}
              {' · '}версия критериев {topic.criteria_version}
              {' · '}модель {topic.model_version ?? '—'}
            </p>
            <p className="small"><strong>Основание:</strong> {topic.explanation}</p>
            {topic.fragments.length > 0 && (
              <div className="small">
                <strong>Проверяемые фрагменты:</strong>
                <ul>
                  {topic.fragments.map((fragment) => (
                    <li key={`${fragment.lang}-${fragment.quote}`}>
                      <q>{fragment.quote}</q> <span className="muted">({fragment.lang})</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {topic.expert_note && (
              <p className="small muted">{topic.expert_note}</p>
            )}
          </div>
          <div>
            {topic.machine && (
              <div>
                <p className="small"><strong>Ответ модели (сохранён):</strong></p>
                <p className="small muted">
                  {topic.machine.category} · {topic.machine.explanation}
                </p>
              </div>
            )}
            <p className="small muted">
              Решение эксперта: {fmtDate(topic.expert_at)}
              {topic.expert_at ? '' : ' — не подтверждено'}
            </p>
          </div>
        </div>
      </div>

      <div className="card">
        <h2 className="card__title">Решение эксперта</h2>
        <p className="small muted">
          Категория и направления берутся только из паспорта темы; решение без
          основания не принимается (T-03, T-06).
        </p>
        <div className="grid grid--2">
          <Field label="Категория" required>
            <select
              value={form.category}
              onChange={(event) => setForm({ ...form, category: event.target.value })}
            >
              {passport?.categories.map((category) => (
                <option key={category.code} value={category.code}>{category.title}</option>
              ))}
            </select>
          </Field>
          <Field label="Направления" hint="Ctrl для выбора нескольких">
            <select
              multiple
              size={4}
              value={form.directions}
              onChange={(event) => setForm({
                ...form,
                directions: [...event.target.selectedOptions].map((option) => option.value),
              })}
            >
              {passport?.directions.map((direction) => (
                <option key={direction.code} value={direction.code}>{direction.title}</option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Основание решения" required>
          <textarea
            rows={3}
            value={form.explanation}
            onChange={(event) => setForm({ ...form, explanation: event.target.value })}
          />
        </Field>
        <button
          type="button"
          className="btn"
          disabled={saving || !form.explanation.trim()}
          onClick={() => void saveDecision()}
        >
          {saving ? 'Сохраняем…' : 'Сохранить решение'}
        </button>
      </div>
    </>
  );
}