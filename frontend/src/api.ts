/**
 * Клиент API реестра научных проектов.
 *
 * Токен передаётся в заголовке Authorization, а не в cookie: bearer-токен не
 * подвержен подделке межсайтовых запросов (SEC-04), поэтому отдельный
 * CSRF-токен не требуется. Решение зафиксировано в документации.
 */

import { captureApiFailure } from './errors';

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

const TOKEN_KEY = 'rnp.token';

export class ApiError extends Error {
  status: number;
  problems: { field?: string; reason: string }[];
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(formatDetail(detail) || `Ошибка ${status}`);
    this.status = status;
    this.detail = detail;
    if (detail && typeof detail === 'object' && 'problems' in detail) {
      this.problems = (detail as { problems: { field?: string; reason: string }[] }).problems;
    } else if (detail && typeof detail === 'object' && 'reasons' in detail) {
      this.problems = (detail as { reasons: string[] }).reasons.map((r) => ({ reason: r }));
    } else {
      this.problems = [];
    }
  }
}

function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') {
    const d = detail as Record<string, unknown>;
    if (typeof d.error === 'string') return d.error;
    if (Array.isArray(d.problems)) {
      return d.problems
        .map((p: { field?: string; reason: string }) =>
          p.field ? `${p.field}: ${p.reason}` : p.reason)
        .join('; ');
    }
    if (Array.isArray(d.reasons)) return d.reasons.join('; ');
  }
  return '';
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  raw?: boolean;
  anonymous?: boolean;
}

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, raw = false, anonymous = false } = options;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json; charset=utf-8';
  const token = getToken();
  if (token && !anonymous) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401) {
    // Сессия истекла после 60 минут бездействия (п.11.1). Сбрасываем токен,
    // чтобы интерфейс вернул пользователя на форму входа, а не показывал
    // пустые экраны с ошибками на каждой странице.
    setToken(null);
  }

  if (raw) {
    if (!response.ok) {
      const payload = await safeJson(response);
      reportFailure(path, response.status, payload);
      throw new ApiError(response.status, payload);
    }
    return (await response.blob()) as T;
  }

  const data = await safeJson(response);
  if (!response.ok) {
    reportFailure(path, response.status, data);
    throw new ApiError(response.status, data);
  }
  return data as T;
}

/**
 * Кладёт неудачный запрос в отчёт разработчику.
 *
 * Отдельно выписаны 500 и 422: это единственные коды, по которым видно
 * САМ дефект (сервер назвал код обращения / перечислил проблемные поля).
 * 401 — обычное истечение сессии, 404 на необязательных разделах и 422 при
 * неверном вводе относятся к действиям человека, а не к поломке системы,
 * и в отчёте только засоряли бы разбор.
 */
function reportFailure(path: string, status: number, payload: unknown): void {
  if (status !== 500 && status !== 422) return;
  const body = payload as { reference?: string; error?: string; detail?: string } | null;
  const reference = body?.reference;
  const detail = body?.error ?? body?.detail ?? (typeof payload === 'string' ? payload : undefined);
  captureApiFailure(path, status, reference, detail);
}

async function safeJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return { error: `Сервер вернул неожиданный ответ (${response.status})` };
  }
}

/** Скачать файл с маршрутом API (выгрузка XLSX/CSV, шаблон формы). */
export async function download(path: string, fallbackName: string): Promise<void> {
  const token = getToken();
  const response = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new ApiError(response.status, await safeJson(response));

  const disposition = response.headers.get('Content-Disposition') ?? '';
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const name = match ? decodeURIComponent(match[1]) : fallbackName;

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Загрузить файл на маршрут импорта (multipart). */
export async function upload<T = unknown>(
  path: string,
  form: FormData,
): Promise<T> {
  const token = getToken();
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  const data = await safeJson(response);
  if (!response.ok) throw new ApiError(response.status, data);
  return data as T;
}

export const auth = {
  login: (login: string, password: string) =>
    api<{ token: string; user: User; password_min_length: number }>('/api/auth/login', {
      method: 'POST',
      body: { login, password },
      anonymous: true,
    }),
  logout: () => api('/api/auth/logout', { method: 'POST' }),
  me: () => api<{ user: User; matrix: Matrix; person: Person | null }>('/api/auth/me'),
  changePassword: (current_password: string, new_password: string) =>
    api('/api/auth/password', {
      method: 'POST',
      body: { current_password, new_password },
    }),
};

// --- Типы ------------------------------------------------------------------

export interface User {
  id: string;
  login: string;
  email: string | null;
  full_name: string;
  is_active: boolean;
  must_reset: boolean;
  last_login_at: string | null;
  person_id: string | null;
  roles: string[];
}

export interface Matrix {
  global_roles: string[];
  is_portfolio: boolean;
  is_admin: boolean;
  can_import: boolean;
  can_export_archive: boolean;
  can_manage_users: boolean;
  can_publish: boolean;
}

export interface Person {
  id: string;
  full_name: string;
  work_place?: string | null;
  position?: string | null;
  academic_degree?: string | null;
  service_contact?: string | null;
  category: 'staff' | 'student' | 'aspirant';
  projects?: { id: string; code: string; title: string; role: string }[];
  results?: { id: string; code: string; title: string }[];
}

export interface Program {
  id: string;
  code: string;
  title: string;
  short_title?: string | null;
  description?: string | null;
  criteria?: string | null;
  expected_results?: string | null;
  public_allowed: number;
  is_active: number;
  archived_at?: string | null;
  curators?: { id: string; full_name: string; appointed_at: string }[];
  projects_count?: number;
}

export interface TransitionAction {
  action: string;
  title: string;
  to_status: string;
  to_status_title: string;
  condition: string;
  reason_required: boolean;
  switches_to_full: boolean;
  allowed: boolean;
  blocked_reasons: string[];
}

export interface RiskInfo {
  level: 'green' | 'yellow' | 'red';
  title: string;
  reasons: string[];
  max_delay_working_days: number;
  overdue_milestones: {
    id: string;
    title: string;
    planned_date: string;
    delay_working_days: number;
    status: string;
  }[];
  required_response: { action: string; may_suspend: boolean; days: number | null };
}

export interface ProjectCard {
  id: string;
  code: string;
  title: string;
  short_title: string | null;
  public_annotation: string | null;
  program_id: string;
  route: 'simplified' | 'full';
  route_auto: 'simplified' | 'full';
  route_reason_comment: string | null;
  route_fixed_by: string | null;
  status: string;
  status_title: string;
  status_changed_at: string | null;
  risk_level: 'green' | 'yellow' | 'red';
  risk_title: string;
  risk_level_comment: string | null;
  planned_start: string | null;
  planned_end: string | null;
  leader_person_id: string | null;
  publish_mode: 'none' | 'project' | 'results' | 'all';
  publish_mode_title: string;
  public_allowed_at: string | null;
  problem: string | null;
  question: string | null;
  goal: string | null;
  tasks: string | null;
  research_object: string | null;
  research_subject: string | null;
  methods: string | null;
  methods_note: string | null;
  data_basis: string | null;
  planned_result_type: string | null;
  planned_result_note: string | null;
  result_criteria: string | null;
  novelty: string | null;
  applicability: string | null;
  limitations: string | null;
  personal_data: number;
  personal_data_note: string | null;
  human_subjects: number;
  human_subjects_note: string | null;
  legal_basis_status: string | null;
  legal_basis_link: string | null;
  confidentiality: string | null;
  ip_note: string | null;
  resource_request: string | null;
  theme_link: string | null;
  version: number;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  created_by_login: string | null;
  search_blob?: string;
  flags?: Record<string, number>;
  full_route_reasons: string[];
  full_route_reasons_detail: { code: string; title: string }[];
  program_code: string | null;
  program_title: string;
  counts: {
    team: number; milestones: number; risks: number; results: number;
    reviews: number; decisions: number; partners: number; materials: number;
  };
  risk: RiskInfo;
  validation: {
    missing_required: string[];
    missing_count: number;
    length_problems: string[];
    route: string;
    counts: Record<string, number>;
  };
  actions: TransitionAction[];
  can_edit: boolean;
  dates_fmt: { planned_start: string; planned_end: string };
}

export interface ProjectRow {
  id: string;
  code: string;
  title: string;
  short_title: string | null;
  status: string;
  status_title: string;
  route: 'simplified' | 'full';
  route_title: string;
  risk_level: 'green' | 'yellow' | 'red';
  risk_title: string;
  program_id: string;
  program_title: string | null;
  leader_person_id: string | null;
  leader_name: string | null;
  planned_start: string | null;
  planned_end: string | null;
  planned_start_fmt: string;
  planned_end_fmt: string;
  publish_mode: string;
  overdue_count: number;
  updated_at: string;
  archived_at: string | null;
}

export interface Milestone {
  id: string;
  project_id: string;
  title: string;
  planned_date: string;
  planned_date_fmt: string;
  actual_date: string | null;
  actual_date_fmt: string;
  responsible_person_id: string | null;
  responsible_name: string | null;
  planned_evidence: string | null;
  status: 'planned' | 'in_progress' | 'done' | 'overdue' | 'cancelled';
  confirmation: string | null;
  postpone_reason: string | null;
  is_overdue: boolean;
  delay_working_days: number;
  missing_on_done: string[];
  created_at: string;
  updated_at: string | null;
}

export interface Participation {
  id: string;
  project_id: string;
  person_id: string;
  full_name: string;
  work_place: string | null;
  position: string | null;
  category: string;
  role: 'leader' | 'member' | 'supervisor' | 'curator';
  task: string | null;
  started_at: string | null;
  finished_at: string | null;
  effort_share: number | null;
  contribution_confirmed: number;
  is_public: number;
}

export interface RiskRow {
  id: string;
  project_id: string;
  category: string;
  description: string;
  probability: 'low' | 'medium' | 'high';
  impact: 'low' | 'medium' | 'high';
  measures: string | null;
  owner_person_id: string | null;
  owner_name: string | null;
  review_date: string | null;
  status: 'open' | 'mitigated' | 'closed';
  level: 'green' | 'yellow' | 'red';
  level_comment: string | null;
  created_at: string;
}

export interface Review {
  id: string;
  project_id: string;
  object_type: 'project' | 'result';
  object_id: string | null;
  stage: 'preliminary' | 'final' | 'publication';
  expert_person_id: string | null;
  expert_name: string | null;
  expert_declared_no_conflict: number | null;
  conflict_note: string | null;
  recused_at: string | null;
  block_goal_fit: string | null;
  block_method_data: string | null;
  block_result_quality: string | null;
  block_risks_limits: string | null;
  recommendation: 'support' | 'support_with_conditions' | 'revise' | 'not_support' | null;
  recommendation_title: string | null;
  verdict_text: string | null;
  assigned_at: string;
  due_at: string | null;
  due_at_fmt: string;
  accepted_at: string | null;
  finalized_at: string | null;
  finalized: boolean;
  immutable: boolean;
  version_no: number;
  replaced_by_review_id: string | null;
  blocks_filled: { key: string; title: string; filled: boolean }[];
  project_code?: string;
  project_title?: string;
  overdue?: boolean;
}

export interface Decision {
  id: string;
  project_id: string | null;
  object_type: string;
  object_id: string | null;
  level: string;
  kind: string;
  wording: string;
  basis: string;
  conditions: string | null;
  responsible_person_id: string | null;
  responsible_name: string | null;
  due_at: string | null;
  executed_at: string | null;
  execution_note: string | null;
  decided_at: string;
  decided_by_login: string | null;
}

export interface ResultRecord {
  id: string;
  code: string;
  result_type: string;
  title: string;
  description: string;
  authors: string;
  authors_names: string[];
  readiness_stage: string;
  readiness_title: string;
  planned_date: string | null;
  actual_date: string | null;
  planned_date_fmt: string;
  actual_date_fmt: string;
  acceptance_criterion: string;
  confirmation: string | null;
  review_id: string | null;
  review_status: string | null;
  review_comment: string | null;
  publish_allowed: number;
  is_public: number;
  doi: string | null;
  edn: string | null;
  url: string | null;
  confirmed: boolean;
  projects: { id: string; code: string; title: string; status: string; publish_mode: string }[];
  publication: {
    kind: string | null;
    stage: string;
    stage_title: string;
    target_venue: string | null;
    planned_submit_at: string | null;
    submitted_at: string | null;
    accepted_at: string | null;
    published_at: string | null;
    biblio_volume: string | null;
    biblio_issue: string | null;
    biblio_pages: string | null;
  } | null;
}

export interface AuditEvent {
  id: string;
  happened_at: string;
  happened_at_fmt: string;
  user_id: string | null;
  user_login: string | null;
  group_name: string;
  object_type: string;
  object_id: string | null;
  action: string;
  old_value: string | null;
  new_value: string | null;
  basis: string | null;
  outcome: 'ok' | 'denied' | 'error';
}

export interface Dashboard {
  totals: {
    projects: number;
    active: number;
    completed: number;
    closed: number;
    drafts: number;
    results: number;
    overdue_milestones: number;
  };
  by_status: { code: string; title: string; count: number }[];
  by_route: { code: string; title: string; count: number }[];
  by_risk: { code: string; title: string; count: number }[];
  risk_summary: {
    green: number;
    yellow: number;
    red: number;
    green_note: string;
    yellow_action: string;
    red_action: string;
  };
  questions_for_decision: {
    kind: string;
    severity: 'critical' | 'high' | 'normal';
    project_id: string;
    code: string;
    title: string;
    question: string;
    who: string;
  }[];
  deadlines: {
    overdue: DeadlineItem[];
    upcoming: DeadlineItem[];
  };
  generated_at: string;
}

export interface DeadlineItem {
  milestone_id: string;
  project_id: string;
  code: string;
  project_title: string;
  title: string;
  planned_date: string;
  planned_date_fmt: string;
  responsible: string | null;
  status: string;
  overdue: boolean;
  delay_working_days: number;
  suggested_new_date: string | null;
}

export interface RiskRow {
  id: string;
  project_id: string;
  category: string;
  description: string;
  probability: 'low' | 'medium' | 'high';
  impact: 'low' | 'medium' | 'high';
  measures: string | null;
  owner_person_id: string | null;
  owner_name: string | null;
  review_date: string | null;
  status: 'open' | 'mitigated' | 'closed';
  level: 'green' | 'yellow' | 'red';
  level_comment: string | null;
  created_at: string;
}

export interface PublicResult {
  code: string;
  type: string;
  title: string;
  description: string;
  stage: string;
  year: string | null;
  identifiers: Record<string, string>;
  projects?: { code: string; title: string }[];
}

export interface PublicProject {
  code: string;
  title: string;
  short_title: string | null;
  public_annotation: string | null;
  status: string;
  status_title: string;
  route: string;
  start_year: string | null;
  end_year: string | null;
  start_date: string;
  end_date: string;
  program: {
    code: string;
    title: string;
    short_title: string | null;
    description: string | null;
    expected_results: string | null;
  } | null;
  keywords: string[];
  published: boolean;
  team?: {
    full_name: string;
    role: string;
    role_title: string;
    position?: string;
    work_place?: string;
  }[];
  results?: {
    code: string;
    type: string;
    title: string;
    description: string;
    stage: string;
    year: string | null;
    identifiers: Record<string, string>;
  }[];
  materials?: { title: string; url: string }[];
}