/**
 * Состояние демонстрации: меняется и сохраняется в браузере.
 *
 * ЗАЧЕМ. Демо на GitHub Pages не имеет сервера (Pages отдаёт только
 * статику), а тестировщик должен иметь возможность что-то менять и
 * увидеть результат после перезагрузки. Держать состояние только в
 * памяти нельзя: перезагрузка его потеряет.
 *
 * ГДЕ ХРАНИТСЯ. Только в localStorage этого браузера. Ни на кого и ни
 * куда не уходит: это ровно тот случай, когда данные остаются у человека,
 * и в этом нет утечки (SEC-05). У каждого тестировщика — своя копия,
 * как и задумано при работе без общего сервера.
 *
 * ЧТО ЭТО НЕ ЯВЛЯЕТСЯ. Не базой данных и не копией боевых данных.
 * Начальное состояние — пилотный снимок; правки живут в браузере и
 * не возвращаются в систему.
 */

import { seedDecisions } from './science';

const STORAGE_KEY = 'rnp.demo.state';
const STATE_VERSION = 1;

type Body = Record<string, unknown>;

/** Элемент снимка: { путь: { path, body } }. */
export type FixtureEntry = { path?: string; body?: unknown };
export type Fixtures = Record<string, FixtureEntry | undefined>;

export interface CollectionSet {
    milestones: unknown[];
    risks: unknown[];
    team: unknown[];
    reviews: unknown[];
    decisions: unknown[];
    materials: unknown[];
}

/** Ключи вкладок карточки — и для хранения, и для счётчиков на карточке. */
export const COLLECTION_GROUPS = [
  'milestones', 'risks', 'team', 'reviews', 'decisions', 'materials',
] as const;

export type CollectionKey = (typeof COLLECTION_GROUPS)[number];

export interface DemoState {
    version: number;
    /** Карточки проектов по id: то, что читает интерфейс как паспорт. */
    cards: Record<string, Body>;
    /** Вкладки карточки по id проекта. */
    collections: Record<string, CollectionSet>;
    /** Коды статусов по порядку — движение демо по справочнику. */
    statusOrder: string[];
    /**
     * Тематические решения раздела «Научная деятельность» по id публикации.
     *
     * Хранятся отдельно от снимка, потому что их меняет эксперт (T-07), и
     * потому что снимок общий для всех: правка решения не должна выглядеть
     * как правка исходных данных.
     */
    scienceDecisions: Record<string, unknown>;
}

let state: DemoState | null = null;

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** Тело ответа из снимка; пустой объект, если адреса в снимке нет. */
export function bodyOf(fixtures: Fixtures, key: string): Body {
  const entry = fixtures[key];
  if (!entry || typeof entry !== 'object') return {};
  const body = entry.body;
  if (body && typeof body === 'object' && !Array.isArray(body)) return body as Body;
  return {};
}

/** Список из тела ответа; пустой массив, если поля нет. */
export function itemsOf(fixtures: Fixtures, key: string): Body[] {
  const items = bodyOf(fixtures, key).items;
  return Array.isArray(items) ? (items as Body[]) : [];
}

/**
 * Собрать карточку из элемента списка проектов.
 *
 * Отдельно копируется id: раньше его не было в списке полей, и карточка
 * без id не находилась бы по адресу /api/projects/{id}.
 */
function cardFromListItem(item: Body): Body {
  const fields = ['title', 'short_title', 'code', 'status', 'status_title',
                  'risk_level', 'risk_title', 'route', 'route_title',
                  'program_id', 'program_title', 'leader_person_id', 'leader_name',
                  'publish_mode', 'planned_start', 'planned_end',
                  'planned_start_fmt', 'planned_end_fmt', 'created_at', 'updated_at'];
  const card: Body = {};
  for (const field of fields) {
    if (item[field] !== undefined) card[field] = item[field];
  }
  return card;
}

/**
 * Обязательные структурные поля карточки — по снимку.
 *
 * Без них страница проекта не отрисуется, а упадёт: в ней есть обращения
 * вида card.counts.milestones, card.risk.reasons[0], card.validation.
 * length_problems — они не защищены, и разработчик исходит из того, что
 * поля есть всегда (так и есть в боевой системе: их считает сервер).
 *
 * В новом проекте счётчики обнуляются, а список действий пуст: в ST-01
 * действий ещё нет, и это согласуется с тем, что показывает интерфейс.
 */
export function structuralDefaults(fixtures: Fixtures): Body {
  const base = bodyOf(fixtures, 'project_card');
  if (!Object.keys(base).length) return {};

  const card = deepClone(base);
  const zeroed = Object.fromEntries(
    Object.keys((card.counts ?? {}) as Body).map((key) => [key, 0]),
  );
  card.counts = zeroed;
  if (card.validation && typeof card.validation === 'object') {
    const validation = card.validation as Body;
    validation.missing_required = [];
    validation.missing_count = 0;
    validation.length_problems = [];
    validation.counts = { ...zeroed };
  }
  if (card.risk && typeof card.risk === 'object') {
    const risk = card.risk as Body;
    risk.level = 'green';
    risk.title = 'Зелёный';
    risk.reasons = [];
    risk.max_delay_working_days = 0;
    risk.overdue_milestones = [];
  }
  card.actions = [];
  card.full_route_reasons = [];
  card.full_route_reasons_detail = [];
  return card;
}

/**
 * Начальное состояние из пилотного снимка.
 *
 * Карточка каждого проекта собирается как «структура снимка + свои поля из
 * списка»: так счётчики и валидация существуют у всех проектов, а название,
 * код и статус — именно те, что в списке. Вкладки заполняются тем же
 * снимком — демо изначально так и работало, данные проектов в нём условные.
 */
export function seedState(fixtures: Fixtures): DemoState {
  const cards: Record<string, Body> = {};
  const collections: Record<string, CollectionSet> = {};
  const base = structuralDefaults(fixtures);

  const list = itemsOf(fixtures, 'projects');
  for (const item of list) {
    if (item.id === undefined) continue;
    const id = String(item.id);
    cards[id] = { ...base, ...cardFromListItem(item), id };
  }

  const collectionsFromFixtures: CollectionSet = {
    milestones: itemsOf(fixtures, 'milestones'),
    risks: itemsOf(fixtures, 'risks'),
    team: itemsOf(fixtures, 'team'),
    reviews: itemsOf(fixtures, 'reviews'),
    decisions: itemsOf(fixtures, 'decisions'),
    materials: itemsOf(fixtures, 'materials'),
  };
  for (const id of Object.keys(cards)) {
    collections[id] = deepClone(collectionsFromFixtures);
    // Счётчики считаются от содержимого вкладок, иначе бейдж «Команда (0)»
    // расходился бы с реально открытой вкладкой, где участник есть.
    for (const group of COLLECTION_GROUPS) {
      syncCounts(cards[id], group, collections[id][group].length);
    }
  }

  const statuses = bodyOf(fixtures, 'taxonomy').statuses;
  const statusOrder = (Array.isArray(statuses) ? (statuses as unknown[]) : [])
    .map((item): string => (
      typeof item === 'object' && item !== null ? String((item as Body).code ?? '') : ''
    ))
    .filter(Boolean);
  if (!statusOrder.length) statusOrder.push('ST-01', 'ST-02', 'ST-03', 'ST-04',
    'ST-05', 'ST-06', 'ST-07', 'ST-08', 'ST-09', 'ST-10', 'ST-11', 'ST-12');

  return {
    version: STATE_VERSION,
    cards,
    collections,
    statusOrder,
    scienceDecisions: seedDecisions() as unknown as Record<string, unknown>,
  };
}

/**
 * Разбор сохранённого состояния — и из localStorage, и из выгрузки файла.
 *
 * Одна проверка на два входа нужна затем, чтобы файл от тестировщика не
 * принимался по более слабым правилам, чем собственные данные браузера:
 * форма у них теперь одна, и повреждённый или чужой JSON отклоняется.
 */
export function parseStoredState(raw: string | null | undefined): DemoState | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<DemoState> | null;
    if (!parsed || typeof parsed !== 'object') return null;
    const ok = parsed.version === STATE_VERSION
      && parsed.cards !== null && typeof parsed.cards === 'object'
      && !Array.isArray(parsed.cards)
      && parsed.collections !== null && typeof parsed.collections === 'object'
      && !Array.isArray(parsed.collections);
    return ok ? (parsed as DemoState) : null;
  } catch {
    return null;   // не JSON — не состояние
  }
}

export function loadState(fixtures: Fixtures): DemoState {
  if (state) return state;
  let loaded: DemoState | null = null;
  try {
    loaded = parseStoredState(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    loaded = null;   // хранилище недоступно — начинаем с чистого снимка
  }
  state = loaded ?? seedState(fixtures);
  // Состояние, сохранённое до появления раздела, поля scienceDecisions не
  // содержит. Дописываем решения из снимка, иначе раздел открылся бы пустым
  // у того, кто заходил в демо раньше.
  if (!state.scienceDecisions) {
    state.scienceDecisions = seedDecisions() as unknown as Record<string, unknown>;
    persist();
  }
  // Записи выгрузки eLIBRARY могли появиться позже, чем было сохранено
  // состояние. Без дозаписи их решений карточка такой работы открывалась бы
  // пустой: решение эксперта есть, а показать нечего.
  let patched = false;
  for (const [publicationId, decision] of Object.entries(seedDecisions())) {
    if (!state.scienceDecisions[publicationId]) {
      state.scienceDecisions[publicationId] = decision;
      patched = true;
    }
  }
  if (patched) persist();
  return state;
}

/** Состояние текстом — для выгрузки в файл. */
export function exportState(fixtures: Fixtures): string {
  return JSON.stringify(loadState(fixtures), null, 2);
}

/** Принять выгрузку от тестировщика. false — файл не похож на состояние. */
export function importState(raw: string): boolean {
  const parsed = parseStoredState(raw);
  if (!parsed) return false;
  state = parsed;
  persist();
  return true;
}

function persist(): void {
  if (!state) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Хранилище переполнено: демо продолжит работать до перезагрузки.
    // Ошибку не показываем — человек тестирует интерфейс, а не квоты браузера.
  }
}

export function resetState(fixtures: Fixtures): DemoState {
  state = seedState(fixtures);
  persist();
  return state;
}

export function currentState(): DemoState | null { return state; }

/** Применить изменение и сохранить результат. null — состояние ещё не поднято. */
export function mutate<T>(fn: (state: DemoState) => T): T | null {
  if (!state) return null;
  const result = fn(state);
  persist();
  return result;
}

/** Следующий код статуса; на последнем статусе остаёмся (конец маршрута). */
export function nextStatusCode(statusOrder: string[], current: string): string {
  const index = statusOrder.indexOf(current);
  if (index < 0 || index + 1 >= statusOrder.length) return current;
  return statusOrder[index + 1];
}

export function makeId(prefix = 'demo'): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Счётчики вкладок на карточке.
 *
 * Без этого бейджи на вкладках расходятся с содержимым после добавления
 * или удаления записи — интерфейс показывал бы старое количество.
 */
export function syncCounts(card: Body, group: keyof CollectionSet, count: number): void {
  if (card.counts && typeof card.counts === 'object') {
    (card.counts as Body)[group] = count;
  }
  if (card.validation && typeof card.validation === 'object') {
    const validation = card.validation as Body;
    if (validation.counts && typeof validation.counts === 'object') {
      (validation.counts as Body)[group] = count;
    }
  }
}

/** Элементы списка проектов — форма, которую ожидает страница «Проекты». */
export function shapeList(cards: Record<string, Body>): Body[] {
  return Object.values(cards)
    .filter((card) => !card.archived_at)
    .map((card) => ({
      id: card.id,
      code: card.code,
      title: card.title,
      short_title: card.short_title,
      status: card.status,
      status_title: card.status_title,
      risk_level: card.risk_level,
      risk_title: card.risk_title,
      route: card.route,
      route_title: card.route_title,
      program_id: card.program_id,
      program_title: card.program_title,
      leader_person_id: card.leader_person_id,
      leader_name: card.leader_name ?? null,
      planned_start: card.planned_start,
      planned_start_fmt: card.planned_start_fmt,
      planned_end: card.planned_end,
      planned_end_fmt: card.planned_end_fmt,
      publish_mode: card.publish_mode,
      overdue_count: 0,
      updated_at: card.updated_at,
      archived_at: card.archived_at ?? null,
    }))
    .sort((left, right) => String(left.code).localeCompare(String(right.code)));
}
