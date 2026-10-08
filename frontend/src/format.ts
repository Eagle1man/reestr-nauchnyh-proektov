/** Форматирование под требования ТЗ п.10.2 п.2: даты ДД.ММ.ГГГГ, время московское. */

export function fmtDate(value: string | null | undefined): string {
  if (!value) return '';
  const iso = value.slice(0, 10);
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : value;
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return '';
  // Значения приходят с московским смещением от сервера; здесь только
  // приводим к виду ДД.ММ.ГГГГ ЧЧ:ММ без пересчёта часового пояса.
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!m) return fmtDate(value);
  return `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}`;
}

/** Значение JSON-поля списка/объекта → массив строк. */
export function asList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object') {
          const o = item as Record<string, unknown>;
          return String(o.title ?? o.code ?? o.name ?? '');
        }
        return String(item);
      })
      .filter(Boolean);
  }
  if (typeof value === 'string') {
    const text = value.trim();
    if (!text) return [];
    if (text.startsWith('[') || text.startsWith('{')) {
      try {
        return asList(JSON.parse(text));
      } catch {
        return [text];
      }
    }
    return text
      .split(';')
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return [];
}

export function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(
    now.getDate(),
  ).padStart(2, '0')}`;
}

const STATUS_COLORS: Record<string, string> = {
  'ST-01': 'neutral', 'ST-02': 'accent', 'ST-03': 'yellow', 'ST-04': 'accent',
  'ST-05': 'yellow', 'ST-06': 'accent', 'ST-07': 'green', 'ST-08': 'yellow',
  'ST-09': 'neutral', 'ST-10': 'accent', 'ST-11': 'green', 'ST-12': 'neutral',
};

export function statusTone(code: string): string {
  return STATUS_COLORS[code] ?? 'neutral';
}

export function riskTone(level: string): string {
  if (level === 'red') return 'red';
  if (level === 'yellow') return 'yellow';
  return 'green';
}

export const RISK_TITLES: Record<string, string> = {
  green: 'Зелёный', yellow: 'Жёлтый', red: 'Красный',
};

export const PUBLISH_MODES: Record<string, string> = {
  none: 'Не публиковать',
  project: 'Проект',
  results: 'Результаты',
  all: 'Всё',
};

/** Признаки полного маршрута T-01…T-06 в порядке отображения (п.5.1). */
export const FULL_ROUTE_FLAGS: { key: string; code: string; title: string }[] = [
  { key: 'flag_external_funding', code: 'T-01', title: 'Внешнее финансирование' },
  { key: 'flag_partner', code: 'T-01', title: 'Партнёр или договорные обязательства' },
  { key: 'flag_personal_data', code: 'T-02', title: 'Персональные данные' },
  { key: 'flag_human_subjects', code: 'T-02', title: 'Участие людей в исследовании' },
  { key: 'flag_ethics_required', code: 'T-02', title: 'Этическое рассмотрение' },
  { key: 'flag_extra_resources', code: 'T-03', title: 'Ресурсы сверх лимита' },
  { key: 'flag_critical_infra', code: 'T-04', title: 'Критичная инфраструктура' },
  { key: 'flag_high_risk', code: 'T-04', title: 'Повышенный риск' },
  { key: 'flag_external_product', code: 'T-05', title: 'Продукт для внешнего применения' },
  { key: 'flag_confidential', code: 'T-06', title: 'Конфиденциальные данные' },
  { key: 'flag_ip_restricted', code: 'T-06', title: 'Ограничение прав' },
];

/** Флаги, которые карточка уже имеет (для предзаполнения формы правки). */
export function flagSet(card: ProjectCardLike | null): Set<string> {
  const set = new Set<string>();
  if (!card) return set;
  for (const flag of FULL_ROUTE_FLAGS) {
    if ((card as unknown as Record<string, unknown>)[flag.key]) set.add(flag.key);
  }
  return set;
}

interface ProjectCardLike {
  [key: string]: unknown;
}