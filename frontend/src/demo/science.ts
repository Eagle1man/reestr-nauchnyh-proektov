/**
 * Данные раздела «Научная деятельность» для демонстрационного режима.
 *
 * ЧТО ЭТО. Синтетические записи, повторяющие форму модели данных из ТЗ
 * мониторинга научной деятельности: стадии публикации, происхождение записи,
 * статусы изданий по каждому перечню отдельно, тематическое решение с
 * категорией, направлением, объяснением и фрагментами текста.
 *
 * ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Это НЕ выгрузка eLIBRARY/РИНЦ. Критерий приёмки
 * AC-01 требует импорта минимум 30 реальных записей, поэтому демо его не
 * закрывает: подменять реальные данные демонстрационными запрещает п.1 ТЗ.
 * В интерфейсе это сказано прямо, а не спрятано в подписи источника.
 *
 * СЧЁТ. Уникальной считается работа (D-06): одна запись публикации, сколько
 * бы соавторов и проектов к ней ни относилось. Рукописи, принятые и
 * направленные показываются отдельными числами (A-01), тематическая доля —
 * вместе со знаменателем (A-02).
 */
import raw from './science.json';

export type Stage = 'manuscript' | 'submitted' | 'accepted' | 'published';

export interface SciStatus {
  list: string;
  level: number | null;
  year: number | null;
  source: string;
  received_at: string | null;
  availability: 'confirmed' | 'not_found' | 'error' | 'stale';
}

export interface SciVenue {
  id: string;
  title: string;
  publisher: string;
  type: string;
  issn: string | null;
  eissn: string | null;
  subjects: string[];
  statuses: SciStatus[];
  status_history?: SciStatus[];
}

export interface SciAuthor {
  person_id: string;
  order: number;
  affiliation: string;
  confirmation: 'source' | 'participant' | 'coordinator';
  confirmed_at: string | null;
}

export interface SciFragment {
  lang: string;
  quote: string;
}

/**
 * Ответ модели, сохранённый отдельно от решения эксперта (T-07): исходная
 * машинная оценка не затирается, когда эксперт её меняет.
 */
export interface MachineAnswer {
  category: string;
  directions: string[];
  explanation: string;
  criteria_version: number;
  model_version: string | null;
  analyzed_at: string | null;
}

export interface SciTopicDecision {
  category: string;
  directions: string[];
  explanation: string;
  fragments: SciFragment[];
  criteria_version: number;
  model_version: string | null;
  state: 'pending' | 'auto' | 'awaiting_expert' | 'confirmed' | 'expert_changed' | 'recheck' | 'error';
  analyzed_at: string | null;
  expert_at: string | null;
  expert_note?: string;
  machine?: MachineAnswer | null;
}

export interface SciPublication {
  id: string;
  type: string;
  title_ru: string;
  title_en: string | null;
  year: number;
  date_precision: 'year' | 'month' | 'day';
  published_at: string | null;
  doi: string | null;
  edn: string | null;
  venue_id: string | null;
  stage: Stage;
  stage_dates: { submitted?: string | null; accepted?: string | null; published?: string | null };
  university_owned: boolean;
  ownership_basis: string;
  source_system: string;
  source_record_id: string;
  imported_at: string;
  abstract_ru: string | null;
  keywords_ru: string[];
  authors: SciAuthor[];
  topic: SciTopicDecision;
}

export interface SciParticipant {
  person_id: string;
  category: string;
  periods: { from: string; to: string | null; category: string; unit: string }[];
  external_ids: { system: string; value: string; status: string }[];
}

export interface SciPassport {
  id: string;
  title: string;
  version: number;
  status: string;
  approved_at: string;
  directions: { code: string; title: string }[];
  categories: { code: string; title: string; rule: string }[];
}

export interface ScienceData {
  topic: SciPassport;
  venues: SciVenue[];
  participants: SciParticipant[];
  publications: SciPublication[];
}

export const science = raw as unknown as ScienceData;

export const STAGE_TITLES: Record<Stage, string> = {
  manuscript: 'рукопись',
  submitted: 'направлена',
  accepted: 'принята',
  published: 'опубликована',
};

/** Подтверждённые состояния тематической оценки (T-07). */
export const TOPIC_STATE_TITLES: Record<SciTopicDecision['state'], string> = {
  pending: 'ожидает анализа',
  auto: 'обработана автоматически',
  awaiting_expert: 'ожидает эксперта',
  confirmed: 'подтверждена',
  expert_changed: 'изменена экспертом',
  recheck: 'требует повторной проверки',
  error: 'ошибка',
};

/** Решения раздела хранятся отдельно от снимка: их меняет эксперт (T-07). */
export function seedDecisions(data: ScienceData): Record<string, SciTopicDecision> {
  const decisions: Record<string, SciTopicDecision> = {};
  for (const publication of data.publications) {
    const topic = { ...publication.topic };
    decisions[publication.id] = {
      ...topic,
      // Первый ответ модели сохраняется при первом же решении эксперта:
      // иначе правка эксперта стёрла бы основание, по которому оценивали.
      machine: {
        category: topic.category,
        directions: [...topic.directions],
        explanation: topic.explanation,
        criteria_version: topic.criteria_version,
        model_version: topic.model_version,
        analyzed_at: topic.analyzed_at,
      },
    };
  }
  return decisions;
}

/**
 * Показатели раздела.
 *
 * Считаются по уникальным публикациям, поэтому добавление второго автора или
 * второго проекта не меняет университетский итог (A-01, D-06).
 */
export function scienceStats(
  publications: SciPublication[],
  decisions: Record<string, SciTopicDecision>,
): {
  published: number;
  accepted: number;
  submitted: number;
  unique_works_total: number;
  without_abstract: number;
  authors_total: number;
  direct_confirmed: number;
  with_enough_data: number;
  without_decision: number;
  categories: Record<string, number>;
  passport_version: number;
} {
  const categories: Record<string, number> = {};
  let published = 0;
  let accepted = 0;
  let submitted = 0;
  let withoutAbstract = 0;
  let directConfirmed = 0;
  let withEnoughData = 0;
  let withoutDecision = 0;
  const authors = new Set<string>();

  for (const publication of publications) {
    const decision = decisions[publication.id] ?? publication.topic;
    categories[decision.category] = (categories[decision.category] ?? 0) + 1;
    if (publication.stage === 'published') published += 1;
    if (publication.stage === 'accepted') accepted += 1;
    if (publication.stage === 'submitted') submitted += 1;
    if (!publication.abstract_ru) withoutAbstract += 1;
    const settled = decision.state === 'confirmed' || decision.state === 'expert_changed';
    if (decision.category !== 'INSUFFICIENT' && settled) withEnoughData += 1;
    if (decision.category === 'DIRECT' && settled) directConfirmed += 1;
    if (!settled) withoutDecision += 1;
    for (const author of publication.authors) authors.add(author.person_id);
  }

  return {
    published,
    accepted,
    submitted,
    unique_works_total: publications.length,
    without_abstract: withoutAbstract,
    authors_total: authors.size,
    direct_confirmed: directConfirmed,
    with_enough_data: withEnoughData,
    without_decision: withoutDecision,
    categories,
    passport_version: science.topic.version,
  };
}

/** Публикация, дополненная названием издания, именами авторов и решением. */
export function viewPublication(
  publication: SciPublication,
  decisions: Record<string, SciTopicDecision>,
) {
  const decision = decisions[publication.id] ?? publication.topic;
  const venue = science.venues.find((item) => item.id === publication.venue_id) ?? null;
  const directionTitles = decision.directions.map(
    (code) => science.topic.directions.find((item) => item.code === code)?.title ?? code,
  );
  return {
    ...publication,
    topic: decision,
    venue_title: venue?.title ?? null,
    venue_issn: venue?.issn ?? null,
    stage_title: STAGE_TITLES[publication.stage],
    category_title: science.topic.categories.find((item) => item.code === decision.category)?.title
      ?? decision.category,
    topic_state_title: TOPIC_STATE_TITLES[decision.state],
    direction_titles: directionTitles,
    authors: publication.authors.map((author) => ({
      ...author,
      person_id: author.person_id,
      name: personName(author.person_id),
    })),
  };
}

let personNames: Record<string, string> = {};

/** Имена лиц подставляются из общего снимка демо: отдельного списка участников нет. */
export function setPersonNames(names: Record<string, string>): void {
  personNames = names;
}

function personName(personId: string): string {
  return personNames[personId] ?? personId;
}