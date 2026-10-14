/**
 * Сбор ошибок в браузере и отчёт для разработчика.
 *
 * ЗАЧЕМ. Тестировщик работает со своей копией системы. Когда что-то
 * ломается, он видит либо пустой экран, либо «Ошибка сети» — и сообщить
 * нам о такой ошибке нечего: ни адреса, ни текста, ни момента. Здесь
 * ошибки копятся на его машине, а по кнопке собираются в текст, который
 * можно отправить письмом или вставить в задачу.
 *
 * ЧТО СЮДА НЕ ПОПАДАЕТ. Токен, пароль, содержимое запросов с телом и любые
 * значения, похожие на секрет, вычищаются перед сохранением. Отчёт
 * предназначен для отправки наружу, поэтому лишнее в нём было бы утечкой
 * (SEC-05). Вычистка делается ДО записи, а не при отправке: уже сохранённое
 * в localStorage утекать не должно.
 *
 * ГДЕ ХРАНИТСЯ. Только в localStorage браузера. Наружу ничего не уходит
 * само собой — отправляет человек, и он видит, что отправляет.
 */

const STORAGE_KEY = 'rnp.errors';
const MAX_ENTRIES = 50;
const MAX_MESSAGE = 600;

/**
 * Что считаем секретом и заменяет�� на заглушку до сохранения.
 *
 * ПОРЯДОК ОБЯЗАТЕЛЕН. Сначала bearer и JWT: у них нет имени-подсказки,
 * и общая маска «имя = значение» отработала бы раньше них. При
 * «Authorization: Bearer <токен» она съела бы слово Bearer, а сам токен
 * остался бы в отчёте целиком — проверено на стенде, так и было.
 */
const SECRET_PATTERNS: RegExp[] = [
  /\b[Bb]earer\s+[A-Za-z0-9._~+/-]{8,}=*/g,
  /\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b/g,
  /("?(?:password|passwd|пароль|secret|token|api[_-]?key|authorization|cookie)"?\s*[:=]\s*)("?)[^"',\s}]{3,}\2/gi,
  /rnp\.token["']?\s*[:=]\s*["'][^"']+["']/gi,
];

/** Подписчики на новые ошибки: счётчик на кнопке должен меняться сразу. */
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) {
    try {
      listener();
    } catch {
      // Подписчик не должен ломать сбор ошибок.
    }
  }
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export interface CapturedError {
  at: string;
  kind: 'javascript' | 'promise' | 'api' | 'network';
  message: string;
  source: string;
  line?: number;
  column?: number;
  path?: string;
  status?: number;
  reference?: string;
}

/**
 * Убирает из текста всё, что похоже на секрет.
 *
 * Порядок важен: сначала JWT и bearer — у них нет ключа-подсказки, и без
 * первого прохода общая маска их не поймала бы.
 */
export function redact(text: string): string {
  let result = String(text ?? '');
  for (const pattern of SECRET_PATTERNS) {
    result = result.replace(pattern, (_match: string, prefix?: string) => {
      // В первых шаблонах есть группа с именем значения: её заменяем
      // вместе с двоеточием, чтобы ключ остался читаемым, а значение исчезло.
      if (prefix !== undefined) return `${prefix}«скрыто»`;
      return '«скрыто»';
    });
  }
  return result.length > MAX_MESSAGE ? `${result.slice(0, MAX_MESSAGE)}…` : result;
}

function read(): CapturedError[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    // Повреждённое значение в хранилище не должно ломать страницу.
    return [];
  }
}

function write(entries: CapturedError[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
  } catch {
    // Хранилище переполнено или запрещено — отчёт соберём из того,
    // что есть в памяти, и не будем ломать работу приложения.
  }
}

let memory: CapturedError[] = [];

export function capture(entry: Omit<CapturedError, 'at'>): void {
  const safe: CapturedError = {
    at: new Date().toISOString(),
    kind: entry.kind,
    message: redact(entry.message),
    source: redact(entry.source),
    line: entry.line,
    column: entry.column,
    path: entry.path,
    status: entry.status,
    reference: entry.reference,
  };
  memory = [safe, ...memory].slice(0, MAX_ENTRIES);
  write(memory);
  notify();
}

/** Ошибки, видимые пользователю прямо сейчас. */
export function recentErrors(): CapturedError[] {
  const stored = read();
  const merged = [...memory, ...stored];
  const seen = new Set<string>();
  return merged
    .filter((entry) => {
      const key = `${entry.at}|${entry.message}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, MAX_ENTRIES);
}

export function clearErrors(): void {
  memory = [];
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // см. выше
  }
}

/**
 * Ошибки API, где сервер сам назвал код обращения.
 *
 * Это самый полезный случай: сервер вернул «Внутренняя ошибка сервера»
 * с reference, и без него в сообщении пользователя не было бы ничего
 * проверяемого.
 */
export function captureApiFailure(
  path: string,
  status: number,
  reference?: string,
  detail?: string,
): void {
  capture({
    kind: 'api',
    message: detail ? `HTTP ${status}: ${detail}` : `HTTP ${status}`,
    source: `POST/GET ${path}`,
    path,
    status,
    reference,
  });
}

/** Подписка на ошибки браузера. Ставится один раз при старте. */
export function installErrorCollector(): void {
  if (typeof window === 'undefined') return;
  // Метка, чтобы не навесить второй раз при перерисовке приложения.
  const flag = '__rnp_collector';
  if ((window as unknown as Record<string, unknown>)[flag]) return;
  (window as unknown as Record<string, unknown>)[flag] = true;

  window.addEventListener('error', (event: ErrorEvent) => {
    capture({
      kind: 'javascript',
      message: event.message || 'Ошибка без описания',
      source: event.filename || 'неизвестно',
      line: event.lineno,
      column: event.colno,
    });
  });

  window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
    const reason = event.reason;
    capture({
      kind: 'promise',
      message: reason instanceof Error ? `${reason.name}: ${reason.message}` : String(reason),
      source: 'необработанный отказ промиса',
    });
  });
}

export interface ReportOptions {
  login?: string | null;
  baseUrl?: string;
  serverErrors?: unknown;
  extra?: string;
}

/**
 * Собирает отчёт для отправки.
 *
 * Порядок разделов выбран так, чтобы разбор начинался сверху: сразу
 * видно, что сломалось, и только потом — где и когда.
 */
export function buildReport(options: ReportOptions = {}): string {
  const entries = recentErrors();
  const lines: string[] = [];

  lines.push('ОШИБКА В РЕЕСТРЕ НАУЧНЫХ ПРОЕКТОВ');
  lines.push('='.repeat(52));
  lines.push(`Когда собрано: ${new Date().toLocaleString('ru-RU')}`);
  if (options.baseUrl) lines.push(`Адрес системы: ${options.baseUrl}`);
  if (options.login) lines.push(`Кто работал: ${options.login}`);
  lines.push(`Браузер: ${navigator.userAgent}`);
  lines.push(`Ошибок в отчёте: ${entries.length}`);
  lines.push('');

  if (!entries.length) {
    lines.push('Ошибок не зафиксировано. Опишите, что делали и что увидели.');
  } else {
    entries.forEach((entry, index) => {
      lines.push(`${index + 1}. [${entry.kind}] ${entry.message}`);
      lines.push(`   когда: ${new Date(entry.at).toLocaleString('ru-RU')}`);
      if (entry.source) lines.push(`   где:   ${entry.source}${entry.line ? `:${entry.line}` : ''}`);
      if (entry.path) lines.push(`   адрес: ${entry.path}`);
      if (entry.status) lines.push(`   код:   ${entry.status}`);
      if (entry.reference) lines.push(`   код обращения: ${entry.reference}`);
      lines.push('');
    });
  }

  if (options.extra) {
    lines.push('ЧТО ДЕЛАЛ ЧЕЛОВЕК');
    lines.push('-'.repeat(52));
    lines.push(options.extra);
    lines.push('');
  }

  if (options.serverErrors) {
    lines.push('ЖУРНАЛ СЕРВЕРА');
    lines.push('-'.repeat(52));
    lines.push(typeof options.serverErrors === 'string'
      ? options.serverErrors
      : JSON.stringify(options.serverErrors, null, 1));
    lines.push('');
  }

  lines.push('Как это отправлять: скопируйте текст и пришлите разработчику.');
  return lines.join('\n');
}

/** Тема письма: сразу видно, от кого отчёт. */
export function mailtoLink(report: string): string {
  const subject = 'Ошибка в реестре научных проектов';
  return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(report)}`;
}