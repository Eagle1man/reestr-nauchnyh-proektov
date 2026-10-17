/**
 * Типы раздела «Научная деятельность».
 *
 * Форма записей повторяет модель данных ТЗ мониторинга научной деятельности
 * (D-01…D-07, F-01…F-08, T-01…T-09). Это контракт переноса: когда появится
 * боевое API, страницы не меняются — меняется только источник данных.
 *
 * Ключевые требования, которые видно прямо в типах:
 *   D-04 — стадия публикации отдельно от индексации: `stage`;
 *   D-06 — работа уникальна, соавторы её не размножают;
 *   D-07 — `date_precision` не даёт превратить год в выдуманную дату;
 *   I-11 — статусы изданий по перечням НЕ объединены: их список, а не одно поле;
 *   T-05 — у тематического решения есть объяснение, фрагменты и версии.
 */

export type SciStage = 'manuscript' | 'submitted' | 'accepted' | 'published';

export type SciAvailability = 'confirmed' | 'not_found' | 'error' | 'stale';

export type SciDecisionState =
  | 'pending' | 'auto' | 'awaiting_expert' | 'confirmed' | 'expert_changed' | 'recheck' | 'error';

/** Происхождение записи: демонстрационная или реальная выгрузка (AC-01). */
export type SciSourceKind = 'demo' | 'elibrary' | 'scopus';

export interface SciStatus {
  list: string;
  level: number | null;
  year: number | null;
  source: string;
  received_at: string | null;
  availability: SciAvailability;
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
  works_total?: number;
  works_published?: number;
  source_kind?: SciSourceKind;
  source_kind_title?: string;
}

export interface SciAuthor {
  person_id: string;
  name: string;
  order: number;
  affiliation: string;
  confirmation: 'source' | 'participant' | 'coordinator';
  confirmed_at: string | null;
}

export interface SciFragment {
  lang: string;
  quote: string;
}

export interface SciMachineAnswer {
  category: string;
  directions: string[];
  explanation: string;
  criteria_version: number;
  model_version: string | null;
  analyzed_at: string | null;
}

export interface SciDecision {
  category: string;
  directions: string[];
  explanation: string;
  fragments: SciFragment[];
  criteria_version: number;
  model_version: string | null;
  state: SciDecisionState;
  analyzed_at: string | null;
  expert_at: string | null;
  expert_note?: string;
  machine?: SciMachineAnswer | null;
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
  venue_title: string | null;
  venue_issn: string | null;
  stage: SciStage;
  stage_title: string;
  stage_dates: { submitted?: string | null; accepted?: string | null; published?: string | null };
  university_owned: boolean;
  ownership_basis: string;
  source_system: string;
  source_record_id: string;
  imported_at: string;
  abstract_ru: string | null;
  keywords_ru: string[];
  authors: SciAuthor[];
  topic: SciDecision;
  category_title: string;
  topic_state_title: string;
  direction_titles: string[];
  source_kind: SciSourceKind;
  source_kind_title: string;
  /** Номер регистрации программы для ЭВМ (свидетельства Роспатента). */
  registration?: string | null;
  /** Число цитирований в eLIBRARY на дату выгрузки. */
  citations_elibrary?: number;
  /** Идентификатор Scopus (EID). */
  scopus_eid?: string | null;
  /** Том серии конференционных публикаций. */
  volume?: string | null;
  /** Ссылка на запись в источнике. */
  url?: string | null;
  /** Авторы в источнике не указаны: запись ждёт уточнения (D-03). */
  needs_author?: boolean;
  /** Замечания к записи: разночтения в самой выгрузке и т. п. */
  source_notes?: string[];
}

export interface SciParticipant {
  person_id: string;
  name: string;
  position: string | null;
  category: string;
  unit: string | null;
  periods: { from: string; to: string | null; category: string; unit: string }[];
  external_ids: { system: string; value: string; status: string }[];
  /** Идентификаторов нет вовсе: у реальных авторов выгрузки их не было. */
  ids_unverified?: boolean;
  works_total: number;
  works_published: number;
  confirmed_topics: number;
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

export interface SciStats {
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
  /** Записей-демо (не закрывают AC-01). */
  demo_total: number;
  /** Реальных записей из выгрузки eLIBRARY. */
  elibrary_total: number;
  /** Реальных записей из Scopus. */
  scopus_total: number;
  /** Реальных записей всего (критерий AC-01 требует минимум 30). */
  real_total: number;
  /** Демонстрационных работ, у которых есть решение по тематике. */
  demo_with_decisions: number;
}

export interface SciListResponse {
  items: SciPublication[];
  total: number;
  stats: SciStats;
  demo_notice?: string;
  /** Работы, которые источник отдал дважды: одна работа — одна запись (D-06). */
  excluded_duplicates?: { reason: string; source_title: string; kept_as: string }[];
  filters?: {
    stages: { code: SciStage; title: string }[];
    categories: { code: string; title: string }[];
    years: number[];
    sources: { code: SciSourceKind; title: string }[];
  };
}

export interface SciPublicationResponse {
  publication: SciPublication;
  venue: SciVenue | null;
  demo_notice?: string;
}

export interface SciVenuesResponse {
  items: SciVenue[];
  total: number;
  demo_notice?: string;
}

export interface SciVenueResponse {
  venue: SciVenue;
  publications: SciPublication[];
  demo_notice?: string;
}

export interface SciParticipantsResponse {
  items: SciParticipant[];
  total: number;
  stats: SciStats;
  /** Фамилии, записанные в источнике несколькими способами (требуют сверки). */
  duplicates?: Record<string, string[]>;
  demo_notice?: string;
}

export interface SciParticipantResponse {
  participant: SciParticipant;
  publications: SciPublication[];
  demo_notice?: string;
}

export interface SciTopicResponse {
  passport: SciPassport;
  stats: SciStats;
  demo_notice?: string;
}

/** Подтверждение авторства: источник записи, автор или координатор (D-03). */
export const CONFIRMATION_TITLES: Record<SciAuthor['confirmation'], string> = {
  source: 'по записи источника',
  participant: 'подтверждено автором',
  coordinator: 'подтверждено координатором',
};

export const AVAILABILITY_TITLES: Record<SciAvailability, string> = {
  confirmed: 'подтверждено',
  not_found: 'не найдено по проверенным идентификаторам',
  error: 'техническая ошибка источника',
  stale: 'последнее значение, устарело',
};

export const ID_STATUS_TITLES: Record<string, string> = {
  confirmed: 'подтверждён',
  unverified: 'не проверен',
  conflict: 'конфликт идентификаторов',
};

export const TYPE_TITLES: Record<string, string> = {
  article: 'статья в журнале',
  chapter: 'глава в книге',
  monograph: 'монография',
  conference_paper: 'материалы конференции',
  dataset: 'набор данных',
  product: 'цифровой продукт',
  software: 'программа для ЭВМ (свидетельство о регистрации)',
};

export const SOURCE_KIND_TITLES: Record<SciSourceKind, string> = {
  demo: 'демо-данные (не eLIBRARY/РИНЦ)',
  elibrary: 'выгрузка eLIBRARY/РИНЦ',
  scopus: 'Scopus (данные заказчика, вручную)',
};

/** Сколько реальных записей нужно для приёмки (AC-01). */
export const AC01_REQUIRED = 30;

/**
 * Почему в разделе есть демонстрационные работы.
 *
 * Формулировка показана в интерфейсе: без неё 12 демо-работ выглядят как
 * настоящие публикации, а они взяты только затем, чтобы была видна работа
 * тематической оценки — у реальных работ аннотаций нет, и оценка по ним
 * остаётся «Недостаточно данных» (T-02).
 */
export const DEMO_WORKS_NOTE = 'Демонстрационная работа: взята, чтобы показать, как '
  + 'работает тематическая оценка (есть решения эксперта — подтверждены, изменены, '
  + 'ожидают). Настоящей публикацией не является.';

/** Состояния, при которых работа считается находящейся в работе с оценкой. */
export const IN_PROGRESS_DECISION_STATES = ['awaiting_expert', 'recheck'] as const;

export function fmtDate(value: string | null | undefined): string {
  return value ? value.slice(0, 10).replace(/-/g, '.') : '—';
}