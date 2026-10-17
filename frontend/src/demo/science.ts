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
import rawElibrary from './elibrary.json';

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

/**
 * Происхождение записи: демонстрационная или пришедшая из реальной выгрузки.
 *
 * Показывается в интерфейсе и в ответе API отдельным полем, потому что раздел
 * содержит записи трёх разных видов, и смешивать их без метки нельзя.
 */
export type SciSourceKind = 'demo' | 'elibrary' | 'scopus';

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
  /** Вид записи: 'demo' — синтетика, 'elibrary'/'scopus' — реальные выгрузки. */
  source_kind?: SciSourceKind;
  /** Номер регистрации программы для ЭВМ (только для type === 'software'). */
  registration?: string | null;
  /** Число цитирований в eLIBRARY на дату выгрузки (только для реальных). */
  citations_elibrary?: number;
  /** Идентификатор Scopus (EID) для записей, пришедших из Scopus. */
  scopus_eid?: string | null;
  /** Том серии для конференционных публикаций. */
  volume?: string | null;
  /** Ссылка на запись в источнике. */
  url?: string | null;
  /** Авторы в источнике не указаны: запись ждёт уточнения (D-03). */
  needs_author?: boolean;
  /** Разночтения в исходной выгрузке (например, разные диапазоны страниц). */
  source_notes?: string[];
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

export const SOURCE_KIND_TITLES: Record<SciSourceKind, string> = {
  demo: 'демо-данные (не eLIBRARY/РИНЦ)',
  elibrary: 'выгрузка eLIBRARY/РИНЦ',
  scopus: 'Scopus (данные заказчика, вручную)',
};

export const science = raw as unknown as ScienceData;

/* --------------------------------------------------------------------------
 * Выгрузка eLIBRARY/РИНЦ, предоставленная заказчиком.
 * -------------------------------------------------------------------------- */

interface ElibraryAuthor {
  full_name: string;
}

interface ElibraryVenue {
  id: string;
  title: string;
  publisher: string | null;
  type: string;
  year: string;
  issn?: string | null;
}

interface ElibraryWork {
  id: string;
  type: string;
  title_ru: string;
  year: number;
  venue_id: string | null;
  pages?: string | null;
  issue?: string | null;
  volume?: string | null;
  authors: ElibraryAuthor[];
  registration?: string;
  doi: string | null;
  edn?: string | null;
  open_access?: boolean;
  citations_elibrary?: number;
  scopus_eid?: string | null;
  url?: string | null;
  /** Разночтения внутри самой выгрузки: разные диапазоны страниц и т. п. */
  _page_range_variants?: string[];
  /** Авторы в источнике не указаны — причина, а не пропуск. */
  _authors_missing?: string;
}

interface ScopusData {
  exported_at: string;
  source_system: string;
  provenance: string;
  author_page: string;
  publications: ElibraryWork[];
}

export interface ElibraryData {
  exported_at: string;
  source_system: string;
  provenance: string;
  venues: ElibraryVenue[];
  publications: ElibraryWork[];
  /** Работы, которые выгрузка отдала дважды: одна работа — одна запись (D-06). */
  excluded_duplicates: { reason: string; source_title: string; kept_as: string }[];
  scopus: ScopusData;
}

export const elibrary = rawElibrary as unknown as ElibraryData;

/**
 * Работы, которые источник отдал повторно.
 *
 * Показываются в интерфейсе, а не молча выбрасываются: заказчик должен видеть,
 * что три строки его выгрузки не стали тремя работами и почему.
 */
export const excludedDuplicates = elibrary.excluded_duplicates ?? [];

/**
 * Идентификатор автора выгрузки.
 *
 * Авторы из выгрузки — настоящие люди, их нет в демонстрационном списке лиц,
 * поэтому им выдаются собственные идентификаторы с префиксом 'el-', а имена
 * хранятся здесь же: подставлять их неоткуда.
 */
const elibraryAuthorIds = new Map<string, string>();

export function elibraryAuthorId(fullName: string): string {
  const existing = elibraryAuthorIds.get(fullName);
  if (existing) return existing;
  const created = `el-a${elibraryAuthorIds.size + 1}`;
  elibraryAuthorIds.set(fullName, created);
  return created;
}

/** Имена авторов выгрузки: подключаются к общему списку лиц демо. */
export function elibraryPersonNames(): Record<string, string> {
  const names: Record<string, string> = {};
  for (const work of elibrary.publications) {
    for (const author of work.authors) names[elibraryAuthorId(author.full_name)] = author.full_name;
  }
  return names;
}

const ELIBRARY_UNIT = 'Южный университет (ИУБиП)';

/**
 * Запись выгрузки в общей форме раздела.
 *
 * Ключевое решение: у выгрузки нет аннотаций и ключевых слов, поэтому
 * тематическая оценка не выдумывается, а остаётся «Недостаточно данных»
 * (T-02) с состоянием «ожидает анализа». Подставить вместо отсутствующего
 * текста догадку — значит показать заказчику решение, которого нет.
 *
 * kind различает eLIBRARY и Scopus: происхождение записи показывается в
 * интерфейсе, потому что это разные выгрузки с разной степенью доверия.
 */
function fromSource(
  work: ElibraryWork,
  kind: SciSourceKind,
  source: { source_system: string; exported_at: string },
): SciPublication {
  const notes: string[] = [];
  if (work._page_range_variants) {
    notes.push(`В выгрузке у этой работы разные диапазоны страниц: ${
      work._page_range_variants.join(', ')}. Оставлен первый вариант (D-02).`);
  }
  if (work._authors_missing) notes.push(work._authors_missing);
  return {
    id: work.id,
    type: work.type,
    title_ru: work.title_ru,
    title_en: null,
    year: work.year,
    date_precision: 'year',
    published_at: null,
    doi: work.doi,
    edn: work.edn ?? null,
    venue_id: work.venue_id,
    stage: 'published',
    stage_dates: {},
    university_owned: true,
    ownership_basis: kind === 'scopus'
      ? 'поиск по автору в Scopus; принадлежность организации не подтверждена'
      : 'выгрузка eLIBRARY по запросу организации',
    source_system: source.source_system,
    source_record_id: work.id,
    imported_at: `${source.exported_at}T00:00:00+03:00`,
    abstract_ru: null,
    keywords_ru: [],
    source_kind: kind,
    registration: work.registration ?? null,
    citations_elibrary: work.citations_elibrary,
    scopus_eid: work.scopus_eid ?? null,
    volume: work.volume ?? null,
    url: work.url ?? null,
    needs_author: work.authors.length === 0,
    source_notes: notes.length ? notes : undefined,
    authors: work.authors.map((author, index) => ({
      person_id: elibraryAuthorId(author.full_name),
      order: index + 1,
      affiliation: ELIBRARY_UNIT,
      confirmation: 'source',
      confirmed_at: source.exported_at,
    })),
    topic: {
      category: 'INSUFFICIENT',
      directions: [],
      explanation: 'В выгрузке нет аннотации и ключевых слов: тематическая оценка '
        + 'не выполнялась до их получения (T-02).',
      fragments: [],
      criteria_version: science.topic.version,
      model_version: null,
      state: 'pending',
      analyzed_at: null,
      expert_at: null,
    },
  };
}

const elibraryPublications: SciPublication[] = elibrary.publications.map((work) => (
  fromSource(work, 'elibrary', elibrary)
));

// Scopus — отдельный вид источника: данные пришли вручную, без выгрузки
// организации, и в двух записях без авторов. Прячем их в общий список было бы
// неверно, поэтому они идут отдельно и видны в фильтре происхождения.
const scopusPublications: SciPublication[] = elibrary.scopus.publications.map((work) => (
  fromSource(work, 'scopus', elibrary.scopus)
));

const elibraryVenues: SciVenue[] = elibrary.venues.map((venue) => ({
  id: venue.id,
  title: venue.title,
  publisher: venue.publisher ?? 'не указан в выгрузке',
  type: venue.type,
  issn: venue.issn ?? null,
  eissn: null,
  subjects: [],
  // Статус по перечням у этих изданий не проверен: подставлять его из
  // названия журнала — значит выдумать результат проверки (T-03).
  statuses: [],
  status_history: [],
}));

/** Авторы выгрузки, у которых нет записи участника: заводятся как сотрудники. */
const elibraryParticipants: SciParticipant[] = [...elibraryPublications, ...scopusPublications]
  .flatMap((publication) => publication.authors.map((author) => author.person_id))
  .filter((personId, index, all) => all.indexOf(personId) === index)
  .filter((personId) => !science.participants.some((item) => item.person_id === personId))
  .map((personId) => ({
    person_id: personId,
    category: 'staff',
    periods: [{ from: elibrary.exported_at, to: null, category: 'staff', unit: ELIBRARY_UNIT }],
    // Идентификаторы (AuthorID, ORCID) в выгрузке не переданы, поэтому
    // участник числится неподтверждённым — это видно на странице «Участники».
    external_ids: [],
  }));

/** Публикации раздела: демо-снимок и реальные выгрузки рядом, но с меткой. */
export const allPublications: SciPublication[] = [
  ...science.publications,
  ...elibraryPublications,
  ...scopusPublications,
];

export const allVenues: SciVenue[] = [...science.venues, ...elibraryVenues];

export const allParticipants: SciParticipant[] = [
  ...science.participants,
  ...elibraryParticipants,
];

/**
 * Фамилии, записанные в выгрузке несколькими способами.
 *
 * Например, «Акперов Г.И.», «Акперов Г.И.О.» и «Акперов И.Г.О.» — по всему
 * один и тот же человек, но объединять их без AuthorID/ORCID значит угадать
 * (D-02). Поэтому такие группы не склеиваются, а показываются в интерфейсе:
 * заказчик должен увидеть, что такие записи требует сверить, а не молча
 * получить объединённую строку.
 */
export function duplicateSurnameGroups(): Record<string, string[]> {
  const bySurname: Record<string, Set<string>> = {};
  for (const name of Object.values(elibraryPersonNames())) {
    const surname = name.trim().split(/\s+/)[0];
    bySurname[surname] = bySurname[surname] ?? new Set<string>();
    bySurname[surname].add(name);
  }
  const groups: Record<string, string[]> = {};
  for (const [surname, names] of Object.entries(bySurname)) {
    if (names.size > 1) groups[surname] = [...names].sort();
  }
  return groups;
}

/** Счётчик по источникам: показывает, сколько записей реальных. */
export function sourceBreakdown(publications: SciPublication[]): {
  demo: number;
  elibrary: number;
  scopus: number;
  real: number;
} {
  let demo = 0;
  let elibraryCount = 0;
  let scopusCount = 0;
  for (const publication of publications) {
    if (publication.source_kind === 'elibrary') elibraryCount += 1;
    else if (publication.source_kind === 'scopus') scopusCount += 1;
    else demo += 1;
  }
  // Реальными считаются обе выгрузки: Scopus — тоже реальные публикации,
  // просто они пришли вручную, а не официальным экспортом (AC-01, I-01).
  return { demo, elibrary: elibraryCount, scopus: scopusCount, real: elibraryCount + scopusCount };
}

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

/**
 * Решения раздела хранятся отдельно от снимка: их меняет эксперт (T-07).
 *
 * Берутся все публикации раздела, включая выгрузку eLIBRARY: иначе у реальных
 * записей не было бы начального состояния, и первое же решение эксперта
 * отличалось бы от остальных только потому, что их забыли посеять.
 */
export function seedDecisions(
  publications: SciPublication[] = allPublications,
): Record<string, SciTopicDecision> {
  const decisions: Record<string, SciTopicDecision> = {};
  for (const publication of publications) {
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
  demo_total: number;
  elibrary_total: number;
  scopus_total: number;
  /** Реальных записей всего: eLIBRARY + Scopus (критерий AC-01). */
  real_total: number;
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
  const breakdown = sourceBreakdown(publications);

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
    demo_total: breakdown.demo,
    elibrary_total: breakdown.elibrary,
    scopus_total: breakdown.scopus,
    real_total: breakdown.real,
  };
}

/** Публикация, дополненная названием издания, именами авторов и решением. */
export function viewPublication(
  publication: SciPublication,
  decisions: Record<string, SciTopicDecision>,
) {
  const decision = decisions[publication.id] ?? publication.topic;
  const venue = allVenues.find((item) => item.id === publication.venue_id) ?? null;
  const directionTitles = decision.directions.map(
    (code) => science.topic.directions.find((item) => item.code === code)?.title ?? code,
  );
  return {
    ...publication,
    topic: decision,
    venue_title: venue?.title ?? null,
    venue_issn: venue?.issn ?? null,
    stage_title: STAGE_TITLES[publication.stage],
    source_kind: publication.source_kind ?? 'demo',
    source_kind_title: SOURCE_KIND_TITLES[publication.source_kind ?? 'demo'],
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