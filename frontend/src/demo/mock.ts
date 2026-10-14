/**
 * Демонстрационный режим: интерфейс без сервера.
 *
 * ЗАЧЕМ. GitHub Pages отдаёт только статические файлы — запустить там
 * Python нельзя. Без этого демо открывалось бы пустым экраном входа:
 * страница загрузилась бы, а каждый запрос к /api ушёл бы в никуда.
 *
 * КАК СДЕЛАНО. Ответы сняты с настоящей системы на пило��ных данных
 * (backend/scripts/shoot_demo_fixtures.py) и лежат в fixtures.json.
 * Здесь они не выдумываются заново: форма и значения те же, что у боевой
 * системы, поэтому демо показывает реальный интерфейс, а не макет.
 *
 * ЧТО ЭТО НЕ ЯВЛЯЕТСЯ. Не системой и не копией данных: изменения, внесённые
 * в демо, никуда не сохраняются и ни на кого не влияют. Демо нужно ровно
 * для одного — показать заказчику, как выглядит готовый продукт.
 *
 * ВКЛЮЧАЕТСЯ ТОЛЬКО ФЛАГОМ VITE_DEMO=1 при сборке. Обычная сборка этого
 * файла не касается: подмены fetch не происходит.
 */
import fixtures from './fixtures.json';

type FixtureBody = Record<string, unknown> & { items?: unknown[] };

const KEY = 'rnp.token';
const DEMO_TOKEN = 'demo-mode-no-server';

type Route = { test: RegExp; key: string };

/**
 * Порядок важен: частные адреса проверяются раньше общих, иначе
 * /api/projects/любой-id перехватится как список проектов.
 */
const ROUTES: Route[] = [
  { test: /^\/api\/auth\/me$/, key: 'auth_me' },
  { test: /^\/api\/projects\/taxonomy$/, key: 'taxonomy' },
  { test: /^\/api\/projects\/duplicates$/, key: 'projects' },
  { test: /^\/api\/projects\/[^/]+\/public-preview$/, key: 'public_projects' },
  { test: /^\/api\/projects\/[^/]+\/milestones$/, key: 'milestones' },
  { test: /^\/api\/projects\/[^/]+\/risks$/, key: 'risks' },
  { test: /^\/api\/projects\/[^/]+\/team$/, key: 'team' },
  { test: /^\/api\/projects\/[^/]+\/reviews$/, key: 'reviews' },
  { test: /^\/api\/projects\/[^/]+\/decisions$/, key: 'decisions' },
  { test: /^\/api\/projects\/[^/]+\/materials$/, key: 'materials' },
  { test: /^\/api\/projects\/[^/]+$/, key: 'project_card' },
  { test: /^\/api\/projects$/, key: 'projects' },
  { test: /^\/api\/dashboard$/, key: 'dashboard' },
  { test: /^\/api\/programs$/, key: 'programs' },
  { test: /^\/api\/persons$/, key: 'persons' },
  { test: /^\/api\/reminders$/, key: 'reminders' },
  { test: /^\/api\/results$/, key: 'results' },
  { test: /^\/api\/public\/v1\/manifest$/, key: 'public_manifest' },
  { test: /^\/api\/public\/v1\/programs$/, key: 'public_programs' },
  { test: /^\/api\/public\/v1\/results$/, key: 'public_results' },
  { test: /^\/api\/public\/v1\/projects$/, key: 'public_projects' },
];

const store = fixtures as unknown as Record<string, FixtureBody | string>;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });
}

/** Ответ для адреса, которого в снимках нет: честная пустая выдача. */
function emptyFor(path: string): unknown {
  if (/\/milestones|\/risks|\/team|\/reviews|\/decisions|\/materials$/.test(path)) {
    return { items: [] };
  }
  if (/^\/api\/projects$/.test(path)) return { items: [], total: 0 };
  return { items: [] };
}

export function isDemoMode(): boolean {
  return import.meta.env.VITE_DEMO === '1';
}

/** Вход в демо принимает любые логин и пароль — сервера нет. */
function handleLogin(): Response {
  return jsonResponse({
    token: DEMO_TOKEN,
    user: (store.auth_me as FixtureBody).user,
    password_min_length: 12,
  });
}

export function installDemoMode(): void {
  if (!isDemoMode()) return;

  const originalFetch = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    // Внешние адреса (например, загрузка файла) не перехватываем.
    if (!raw.startsWith('/api/')) return originalFetch(input, init);

    const method = (init?.method ?? 'GET').toUpperCase();
    const url = new URL(raw, window.location.origin);
    const path = url.pathname;

    if (path === '/api/auth/login' && method === 'POST') return handleLogin();
    if (path === '/api/auth/logout') return jsonResponse({ ok: true });
    if (path === '/api/auth/password') return jsonResponse({ ok: true });

    const hit = ROUTES.find((route) => route.test.test(path));
    if (hit) {
      const body = store[hit.key];
      if (body && typeof body === 'object' && 'body' in body) {
        return jsonResponse((body as FixtureBody).body);
      }
      if (Array.isArray(body)) return jsonResponse({ items: body });
      return jsonResponse(emptyFor(path));
    }

    // Адрес снять не удалось: отвечаем правдоподобной пустотой, чтобы
    // интерфейс показал «ничего не найдено», а не упал с ошибкой сети.
    return jsonResponse(emptyFor(path));
  };

  // Сессия: демо всегда «вошедший», иначе заказчик увидит только вход.
  window.localStorage.setItem(KEY, DEMO_TOKEN);
  console.info(
    '[демо] интерфейс работает без сервера, данные — снимок пилотных данных. ' +
    'Изменения не сохраняются.',
  );
}