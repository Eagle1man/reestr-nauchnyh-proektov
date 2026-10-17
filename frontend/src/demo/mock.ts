/**
 * Демонстрационный режим: интерфейс без сервера, с сохранением в браузере.
 *
 * ЗАЧЕМ. GitHub Pages отдаёт только статические файлы — запустить там
 * Python нельзя. Без этого демо показало бы пустой экран входа: страница
 * загрузилась бы, а каждый запрос к /api ушёл бы в никуда.
 *
 * КАК СДЕЛАНО. Ответы сняты с настоящей системы на пилотных данных
 * (backend/scripts/shoot_demo_fixtures.py) и лежат в fixtures.json. Здесь
 * они не выдумываются заново: форма и значения те же, что у боевой системы,
 * поэтому демо показывает настоящий интерфейс, а не макет.
 *
 * СОХРАНЕНИЕ. Демо умеет НЕ только читать: создаёт проекты, правит поля,
 * переводит статусы, добавляет точки, риски, команду, рецензии, решения и
 * материалы. Изменения записываются в localStorage браузера и переживают
 * перезагрузку — по сайту можно тестировать, не поднимая сервер и не трогая ВМ.
 *
 * ЧТО ЭТО НЕ ЯВЛЯЕТСЯ. Не системой и не копией данных: изменённые данные
 * живут только у того, кто их менял, и никуда не возвращаются (SEC-05).
 * Кнопка «Вернуть демо-данные» откатывает состояние к снимку.
 *
 * ВКЛЮЧАЕТСЯ ТОЛЬКО ФЛАГОМ VITE_DEMO=1 при сборке. В обычной сборке
 * подмены fetch не происходит.
 */
import fixtures from './fixtures.json';
import {
  bodyOf, COLLECTION_GROUPS, exportState, importState, itemsOf, loadState, makeId,
  mutate, nextStatusCode, resetState, shapeList, structuralDefaults, syncCounts,
  type CollectionSet, type DemoState, type Fixtures,
} from './state';

const KEY = 'rnp.token';
const DEMO_TOKEN = 'demo-mode-no-server';

type Body = Record<string, unknown>;

const snapshot = fixtures as unknown as Fixtures;

/** Результат обработки: статус и тело — чтобы не приводить ответы насильно. */
type Outcome = { status: number; body: unknown };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });
}

function respond(outcome: Outcome | null): Response {
  if (!outcome) return jsonResponse({ error: 'Проект не найден' }, 404);
  return jsonResponse(outcome.body, outcome.status);
}

function now(): string {
  return new Date().toISOString();
}

/** Название статуса по его коду — из справочника снимка. */
function statusTitle(code: string): string {
  const statuses = bodyOf(snapshot, 'taxonomy').statuses;
  const list = Array.isArray(statuses) ? (statuses as Body[]) : [];
  const found = list.find((item) => String(item.code) === code);
  return String(found?.title ?? code);
}

/** Ответ для адреса, которого в снимках нет: честная пустая выдача. */
function emptyFor(path: string): unknown {
  if (/^\/api\/projects$/.test(path)) return { items: [], total: 0 };
  return { items: [] };
}

/** Вкладка карточки по id проекта из живого состояния. */
function collectionOf(state: DemoState, projectId: string, group: keyof CollectionSet): Body[] {
  const items = state.collections[projectId]?.[group];
  return Array.isArray(items) ? (items as Body[]) : [];
}

/**
 * Разбор адреса вкладки: /api/projects/{id}/{группа}[/{запись}].
 *
 * Группа сравнивается по полному имени из списка, а не по началу строки:
 * прежний способ (startsWith от первых пяти букв) легко перепутал бы
 * будущие группы с похожими именами.
 */
function parseCollection(path: string) {
  const match = path.match(/^\/api\/projects\/([^/]+)\/([a-z]+)(?:\/([^/]+))?$/);
  if (!match) return null;
  const [, projectId, plural, itemId] = match;
  const group = COLLECTION_GROUPS.find((key) => key === plural);
  if (!group) return null;
  return { projectId, group, itemId: itemId ?? null };
}

export function isDemoMode(): boolean {
  return import.meta.env.VITE_DEMO === '1';
}

function handleLogin(): Response {
  return jsonResponse({
    token: DEMO_TOKEN,
    user: bodyOf(snapshot, 'auth_me').user,
    password_min_length: 12,
  });
}

/** Создание проекта: карточка собирается со всеми обязательными полями. */
function createProject(body: Body): Outcome | null {
  return mutate((state): Outcome => {
    const id = makeId();
    const index = Object.keys(state.cards).length + 1;
    const card: Body = {
      ...structuralDefaults(snapshot),
      ...body,
      id,
      code: body.code ?? `РНП-DEMO-${String(index).padStart(4, '0')}`,
      title: body.title ?? 'Новый проект',
      short_title: body.short_title ?? body.title ?? 'Новый проект',
      status: 'ST-01',
      status_title: statusTitle('ST-01'),
      created_at: now(),
      updated_at: now(),
    };
    state.cards[id] = card;
    state.collections[id] = {
      milestones: [], risks: [], team: [], reviews: [], decisions: [], materials: [],
    };
    return { status: 200, body: card };
  });
}

/**
 * Правка полей карточки.
 *
 * Форма ответа повторяет боевой PATCH (`api/projects.py`): { ok, changed,
 * version, card }. Страница паспорта читает из неё version и changed.length —
 * прежний ответ-карточка ронял сохранение с сообщением «Cannot read
 * properties of undefined (reading 'length')».
 *
 * Проверка версии — та же, что на сервере: при расхождении 409, а не тихая
 * перезапись. Отклонения по правам и по составу редактируемых полей демо НЕ
 * выдумывает: снимок матрицы прав не содержит, а показать отказ там, где
 * боевая система приняла бы правку, значило бы исказить поведение системы.
 */
function patchProject(projectId: string, body: Body): Outcome | null {
  return mutate((state): Outcome => {
    const card = state.cards[projectId];
    if (!card) return { status: 404, body: { error: 'Проект не найден' } };

    const sent = body.version;
    const current = Number(card.version ?? 0);
    if (sent !== undefined && sent !== null && Number(sent) !== current) {
      return {
        status: 409,
        body: {
          detail: `Карточка изменена (версия ${current}, у вас ${sent}). `
            + 'Обновите страницу и внесите правки заново.',
        },
      };
    }

    const clean = { ...body };
    delete clean.version;

    const changed: Body[] = [];
    for (const [field, value] of Object.entries(clean)) {
      const old = card[field];
      // Сравнение через JSON: поля бывают объектами, а undefined и null на
      // сервере — это одно и то же отсутствие значения.
      if (JSON.stringify(old ?? null) === JSON.stringify(value ?? null)) continue;
      changed.push({ field, old: old ?? null, new: value ?? null });
      card[field] = value;
    }
    if (changed.length) {
      card.version = current + 1;
      card.updated_at = now();
    }
    return {
      status: 200,
      body: { ok: true, changed, version: Number(card.version ?? current), card },
    };
  });
}

/** Пароль в демо не создаётся: показывать выдуманный значило бы врать. */
const DEMO_PASSWORD_NOTE = '(в демо-режиме пароль не создаётся)';

/**
 * Предпросмотр импорта.
 *
 * Странице нужна форма Preview целиком: заглушка { ok, demo } роняла её на
 * preview.counts.total. Содержимое — честно пустое, потому что демо не
 * разбирает XLSX/CSV: нулевые счётчики и пустой протокол вместо выдуманных
 * строк (п.7.2 п.5 — протокол показывает результат настоящей проверки).
 * created остаётся false: подтверждение в демо ничего не загружает.
 */
function importPreview(body: Body): Outcome {
  const file = body.file as { name?: string } | undefined;
  const name = file?.name ?? 'выбранный файл';
  const confirming = body.confirm === 'true';
  return {
    status: 200,
    body: {
      batch_id: typeof body.batch_id === 'string' && body.batch_id
        ? body.batch_id
        : makeId('demo-batch'),
      file_name: file?.name ?? '',
      created: false,
      counts: { total: 0, ok: 0, warning: 0, error: 0, duplicate: 0 },
      message: confirming
        ? `Демо-режим без сервера: подтверждение принято, но файл «${name}» `
          + 'не разобран — строки не загружены, рабочие данные не изменялись.'
        : `Демо-режим без сервера: файл «${name}» не разобран — строки не `
          + 'проверены, рабочие данные не изменялись.',
      protocol: [],
    },
  };
}

/** Поля формы: строки как есть, файл — именем и размером (серверу они и нужны). */
function bodyFromForm(form: FormData): Body {
  const body: Body = {};
  for (const [key, value] of form.entries()) {
    body[key] = typeof value === 'string' ? value : { name: value.name, size: value.size };
  }
  return body;
}

/**
 * Переход на следующий статус.
 *
 * Демо идёт по справочнику вперёд одним шагом и не сверяет матрицу
 * доступности: снимок матрицы не содержит, а выдавать отказ там, где боевая
 * система дала бы действие, значило бы показать ложное поведение системы.
 */
function transition(state: DemoState, projectId: string): Outcome {
  const card = state.cards[projectId];
  if (!card) return { status: 404, body: { error: 'Проект не найден' } };
  const to = nextStatusCode(state.statusOrder, String(card.status ?? ''));
  card.status = to;
  card.status_title = statusTitle(to);
  card.updated_at = now();
  return { status: 200, body: { applied: true, to_status: to, to_status_title: card.status_title } };
}

/**
 * Добавление, правка и удаление записи во вкладке.
 *
 * Счётчики на карточке пересчитываются сразу: иначе бейдж на вкладке
 * остался бы прежним и расходился бы с содержимым.
 */
function collectionWrite(method: string, path: string, body: Body): Outcome | null {
  const parsed = parseCollection(path);
  if (!parsed) return { status: 404, body: { error: 'Не найдено' } };
  const { projectId, group, itemId } = parsed;

  return mutate((state): Outcome => {
    const items = collectionOf(state, projectId, group);
    const card = state.cards[projectId];

    if (method === 'DELETE') {
      const index = items.findIndex((item) => String(item.id) === itemId);
      if (index < 0) return { status: 404, body: { error: 'Запись не найдена' } };
      items.splice(index, 1);
      if (card) syncCounts(card, group, items.length);
      return { status: 200, body: { ok: true } };
    }

    if (method === 'PUT' || method === 'PATCH') {
      const index = items.findIndex((item) => String(item.id) === itemId);
      if (index < 0) return { status: 404, body: { error: 'Запись не найдена' } };
      items[index] = { ...(items[index] as Body), ...body };
      return { status: 200, body: items[index] };
    }

    // POST: новая запись. Имя участника подставляется из справочника лиц —
    // форма добавления присылает только person_id, и без подстановки в
    // таблице появилась бы строка без имени.
    const created: Body = {
      ...body,
      id: makeId(),
      project_id: projectId,
      created_at: now(),
      updated_at: now(),
    };
    if (group === 'team' && created.person_id !== undefined
        && created.full_name === undefined) {
      const person = itemsOf(snapshot, 'persons')
        .find((item) => String(item.id) === String(created.person_id));
      if (person) {
        created.full_name = person.full_name;
        created.position = person.position;
        created.work_place = person.work_place;
      }
    }
    items.push(created);
    if (card) syncCounts(card, group, items.length);
    return { status: 200, body: created };
  });
}

/** Подтверждение вклада участника команды. */
function confirmMember(projectId: string, teamId: string): Outcome | null {
  return mutate((state): Outcome => {
    const member = collectionOf(state, projectId, 'team')
      .find((item) => String(item.id) === teamId);
    if (!member) return { status: 404, body: { error: 'Участник не найден' } };
    member.contribution_confirmed = true;
    return { status: 200, body: { ok: true } };
  });
}

/** Чтение списка проектов из живого состояния. */
function readProjectList(): Response {
  const state = loadState(snapshot);
  const items = shapeList(state.cards);
  return jsonResponse({
    items,
    total: items.length,
    limit: 50,
    offset: 0,
    filters: bodyOf(snapshot, 'projects').filters ?? {},
  });
}

/** Чтения: из состояния для проектов, из снимка для остального адреса. */
function handleRead(path: string): Response {
  // Порядок важен: «taxonomy» и «duplicates» — тоже /api/projects/...,
  // но не карточки проекта.
  if (path === '/api/projects/taxonomy') return jsonResponse(bodyOf(snapshot, 'taxonomy'));
  if (path === '/api/projects/duplicates') return readProjectList();
  if (path === '/api/projects') return readProjectList();

  const preview = path.match(/^\/api\/projects\/[^/]+\/public-preview$/);
  if (preview) return jsonResponse(bodyOf(snapshot, 'public_projects'));

  const state = loadState(snapshot);

  const tab = path.match(/^\/api\/projects\/([^/]+)\/([a-z]+)$/);
  if (tab) {
    const group = COLLECTION_GROUPS.find((key) => key === tab[2]);
    if (group) return jsonResponse({ items: collectionOf(state, tab[1], group) });
  }

  const cardMatch = path.match(/^\/api\/projects\/([^/]+)$/);
  if (cardMatch) {
    const card = state.cards[cardMatch[1]];
    return card ? jsonResponse(card) : jsonResponse({ error: 'Проект не найден' }, 404);
  }

  const patterns: Array<[RegExp, string]> = [
    [/^\/api\/departments$/, 'departments'],
    [/^\/api\/auth\/me$/, 'auth_me'],
    [/^\/api\/dashboard$/, 'dashboard'],
    [/^\/api\/programs$/, 'programs'],
    [/^\/api\/persons$/, 'persons'],
    [/^\/api\/reminders$/, 'reminders'],
    [/^\/api\/results$/, 'results'],
    [/^\/api\/public\/v1\/manifest$/, 'public_manifest'],
    [/^\/api\/public\/v1\/programs$/, 'public_programs'],
    [/^\/api\/public\/v1\/results$/, 'public_results'],
    [/^\/api\/public\/v1\/projects$/, 'public_projects'],
  ];
  for (const [pattern, key] of patterns) {
    if (pattern.test(path)) return jsonResponse(bodyOf(snapshot, key));
  }
  return jsonResponse(emptyFor(path));
}

export function installDemoMode(): void {
  if (!isDemoMode()) return;

  const originalFetch = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string'
      ? input
      : input instanceof URL ? input.href : input.url;
    // Внешние адреса не перехватываем — только свои /api/.
    if (!raw.startsWith('/api/')) return originalFetch(input, init);

    const method = (init?.method ?? 'GET').toUpperCase();
    const path = new URL(raw, window.location.origin).pathname;

    if (path === '/api/auth/login' && method === 'POST') return handleLogin();
    if (path === '/api/auth/logout') return jsonResponse({ ok: true });
    if (path === '/api/auth/password') return jsonResponse({ ok: true });

    if (method === 'GET') return handleRead(path);

    let body: Body = {};
    const form = init?.body instanceof FormData ? init.body : null;
    if (form) {
      body = bodyFromForm(form);
    } else {
      try {
        const text = init?.body;
        body = text ? (JSON.parse(String(text)) as Body) : {};
      } catch {
        body = {};
      }
    }

    // Импорт: форма ответа нужна странице целиком, содержимое — честно пустое.
    if (path === '/api/import/preview' && method === 'POST') return respond(importPreview(body));

    // Администрирование: без initial_password страница печатала бы «undefined».
    if (path === '/api/admin/users' && method === 'POST') {
      return jsonResponse({
        ok: true,
        demo: true,
        login: body.login ?? '',
        full_name: body.full_name ?? '',
        email: body.email ?? null,
        roles: [],
        is_active: true,
        initial_password: DEMO_PASSWORD_NOTE,
      });
    }
    if (/^\/api\/admin\/users\/[^/]+\/reset-password$/.test(path) && method === 'POST') {
      return jsonResponse({ ok: true, demo: true, initial_password: DEMO_PASSWORD_NOTE });
    }

    if (path === '/api/projects' && method === 'POST') return respond(createProject(body));

    const patch = path.match(/^\/api\/projects\/([^/]+)$/);
    if (patch && (method === 'PATCH' || method === 'PUT')) {
      return respond(patchProject(patch[1], body));
    }

    const transitionMatch = path.match(/^\/api\/projects\/([^/]+)\/transition$/);
    if (transitionMatch && method === 'POST') {
      const outcome = mutate((state) => transition(state, transitionMatch[1]));
      return respond(outcome);
    }

    const publishMatch = path.match(/^\/api\/projects\/([^/]+)\/publish$/);
    if (publishMatch && method === 'POST') {
      const outcome = mutate((state): Outcome => {
        const card = state.cards[publishMatch[1]];
        if (!card) return { status: 404, body: { error: 'Проект не найден' } };
        card.public_allowed_at = now();
        card.publish_mode = body.publish_mode ?? card.publish_mode ?? 'manual';
        card.updated_at = now();
        return { status: 200, body: { ok: true, public_allowed_at: card.public_allowed_at } };
      });
      return respond(outcome);
    }

    const leaderMatch = path.match(/^\/api\/projects\/([^/]+)\/leader$/);
    if (leaderMatch && method === 'POST') {
      const outcome = mutate((state): Outcome => {
        const card = state.cards[leaderMatch[1]];
        if (!card) return { status: 404, body: { error: 'Проект не найден' } };
        card.leader_person_id = body.leader_person_id ?? null;
        const person = itemsOf(snapshot, 'persons')
          .find((item) => String(item.id) === String(card.leader_person_id));
        card.leader_name = person ? person.full_name : (body.leader_name ?? null);
        card.updated_at = now();
        return { status: 200, body: { ok: true } };
      });
      return respond(outcome);
    }

    const confirmMatch = path.match(/^\/api\/projects\/([^/]+)\/team\/([^/]+)\/confirm$/);
    if (confirmMatch && method === 'POST') {
      return respond(confirmMember(confirmMatch[1], confirmMatch[2]));
    }

    if (parseCollection(path)) return respond(collectionWrite(method, path, body));

    // Прочие записи (администрирование, справочники, резервные копии):
    // на демо их проверять нечего, честно подтверждаем выполнение.
    return jsonResponse({ ok: true, demo: true });
  };

  // Сессия: демо всегда «вошедший», иначе заказчик увидит только вход.
  window.localStorage.setItem(KEY, DEMO_TOKEN);
  // Состояние поднимается до первой отрисовки: первая загрузка уже
  // видит проекты, а не пустой список.
  loadState(snapshot);

  console.info('[демо] работа без сервера. Изменения хранятся в браузере '
    + '(localStorage) и переживают перезагрузку.');
}

/** Откат к исходному снимку — кнопка в интерфейсе демо. */
export function resetDemoData(): void {
  resetState(snapshot);
}

/**
 * Выгрузка состояния в файл.
 *
 * Зачем: правки живут в браузере тестировщика, и без выгрузки заказчик не
 * узнал бы, что у того получилось. Файл и есть способ прислать результат —
 * данные не уходят никуда автоматически, только по команде человека (SEC-05).
 */
export function exportDemoData(): string {
  const json = exportState(snapshot);
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const url = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `reestr-demo-${stamp}.json`;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Отложенная отмена: сразу после click часть браузеров обрывает скачивание.
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  return `reestr-demo-${stamp}.json`;
}

/** Загрузка присланной выгрузки. false — файл не похож на состояние демо. */
export function importDemoData(json: string): boolean {
  return importState(json);
}
