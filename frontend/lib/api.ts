/**
 * Typed fetch wrappers around the FastAPI backend.
 *
 * Every backend endpoint returns the envelope:
 *   { success: boolean; data: T | null; error: string | null }
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/feed";

/** Machine-readable outcome the trigger button maps to. */
export type TriggerStatus = "ok" | "error" | "unavailable";

export interface ApiEnvelope<T> {
  success: boolean;
  /** Present on newer endpoints; older ones omit it (treated as ok/error). */
  status?: TriggerStatus;
  data: T | null;
  error: string | null;
}

/** Summary of what was passed into the system on an upload trigger. */
export interface IntakeSummary {
  source_type: "text" | "pdf" | "url";
  source_ref: string;
  chars: number;
  truncated: boolean;
}

export interface Agent {
  name: string;
  label: string;
  framework: string;
  status: "IDLE" | "RUNNING" | "ERROR";
  last_action: string | null;
  last_run: string | null;
  total_runs: number;
}

export interface HRCase {
  id: string;
  category: string;
  status: string;
  assigned_agent: string;
  summary: string;
  detail?: string;
  created_at: string;
  updated_at?: string;
  // Synchronously computed by the POLICY auto-resolve path at triage time.
  // Advisory only — null on cases with no recommendation.
  ai_recommendation?: string | null;
  ai_confidence?: number | null;
  // What produced the recommendation: "llm" | "grounded_excerpt" | "no_context"
  // | "llm_error". Lets the UI flag deterministic answers honestly.
  ai_mode?: string | null;
}

export interface AuditRow {
  id: string;
  agent_name: string;
  action_type: string;
  input: string;
  output: string;
  status: string;
  timestamp: string;
}

export interface ApprovalDecision {
  id: string;
  agent_name: string;
  decision: "approved" | "rejected";
  step: string | null;
  reason: string;
  decided_by_id: string | null;
  role: string | null;
  timestamp: string;
}

export interface PendingTask {
  id: string;
  agent_name: string;
  step: string;
  status: string;
  context: string;
  created_at: string;
}

const TOKEN_KEY = "hr_access_token";

/** Read/write the JWT access token from localStorage (browser only). */
export const tokenStore = {
  get(): string | null {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(TOKEN_KEY);
  },
  set(token: string) {
    if (typeof window !== "undefined") window.localStorage.setItem(TOKEN_KEY, token);
  },
  clear() {
    if (typeof window !== "undefined") window.localStorage.removeItem(TOKEN_KEY);
  },
};

const BYOK_KEY = "hr_byok_key";

/**
 * Ephemeral Bring-Your-Own-Key store. Kept in sessionStorage (cleared when the
 * tab closes, never localStorage) and sent only as the `X-Client-LLM-Key`
 * request header — the backend uses it per-request and never persists it.
 */
export const byokStore = {
  get(): string | null {
    if (typeof window === "undefined") return null;
    return window.sessionStorage.getItem(BYOK_KEY);
  },
  set(key: string) {
    if (typeof window !== "undefined") window.sessionStorage.setItem(BYOK_KEY, key);
  },
  clear() {
    if (typeof window !== "undefined") window.sessionStorage.removeItem(BYOK_KEY);
  },
};

/** Build request headers: bearer token + the visitor's BYOK key when present. */
export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers = { ...extra };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  const byok = byokStore.get();
  if (byok) headers["X-Client-LLM-Key"] = byok;
  return headers;
}

/** Ping the server with current headers; return whether it accepted a BYOK key. */
export async function checkByok(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`, { headers: authHeaders(), cache: "no-store" });
    return res.headers.get("X-BYOK") === "1";
  } catch {
    return false;
  }
}

export type ByokStatus = "verified" | "rejected" | "malformed" | "missing" | "unverifiable";

/** Provider-side verification: actually checks the key against Anthropic. */
export async function verifyByok(): Promise<{ valid: boolean; status: ByokStatus; detail: string }> {
  try {
    return await request<{ valid: boolean; status: ByokStatus; detail: string }>("/byok/verify");
  } catch {
    return { valid: false, status: "unverifiable", detail: "verification request failed" };
  }
}

/** Perform a JSON request and unwrap the standard envelope. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: authHeaders({ "Content-Type": "application/json" }),
    cache: "no-store",
    ...init,
  });
  const body = (await res.json()) as ApiEnvelope<T>;
  if (!body.success) {
    throw new Error(body.error ?? "request failed");
  }
  return body.data as T;
}

export const api = {
  /** Backend health snapshot. */
  health: () =>
    request<{
      status: string;
      environment: string;
      agents_registered: number;
      agents_active: number;
      auth_enforced?: boolean;
      llm_enabled?: boolean;
    }>("/health"),

  /** List all agents with runtime status. */
  agents: () => request<Agent[]>("/agents"),

  /** Operational metrics derived from the audit log + cases. */
  metrics: () => request<Metrics>("/metrics"),

  /** Manually trigger an agent. */
  triggerAgent: (name: string, input: string, payload?: unknown) =>
    request<unknown>(`/agents/${name}/trigger`, {
      method: "POST",
      body: JSON.stringify({ input, payload }),
    }),

  /** Screen a resume (text) against a job description. */
  screenResume: (jobDescription: string, resume: string) =>
    request<ResumeScreenResult>(`/agents/resume_screener_agent/trigger`, {
      method: "POST",
      body: JSON.stringify({
        input: resume,
        payload: { job_description: jobDescription, resume },
      }),
    }),

  /** Predict attrition risk from the six employee features. */
  predictAttrition: (features: AttritionFeatures) =>
    request<AttritionResult>(`/agents/attrition_agent/trigger`, {
      method: "POST",
      body: JSON.stringify({ input: "", payload: features }),
    }),

  /**
   * Trigger an agent from typed text, a PDF attachment, or a URL to scrape.
   * Returns the full envelope (including `status`) so the caller can show
   * success / failed / unavailable without throwing.
   */
  triggerUpload: async (
    name: string,
    opts: { text?: string; file?: File | null; url?: string; jobDescription?: string }
  ): Promise<ApiEnvelope<unknown>> => {
    const form = new FormData();
    if (opts.file) form.append("file", opts.file);
    if (opts.url) form.append("url", opts.url);
    if (opts.text) form.append("text", opts.text);
    if (opts.jobDescription) form.append("job_description", opts.jobDescription);
    // NB: do not set Content-Type — the browser adds the multipart boundary.
    const res = await fetch(`${API_BASE}/agents/${name}/trigger/upload`, {
      method: "POST",
      body: form,
      cache: "no-store",
      headers: authHeaders(),
    });
    return (await res.json()) as ApiEnvelope<unknown>;
  },

  /** List HR cases with optional filters. */
  cases: (category?: string, status?: string) => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    if (status) params.set("status", status);
    const qs = params.toString();
    return request<HRCase[]>(`/cases${qs ? `?${qs}` : ""}`);
  },

  /** Full detail for one case: the record plus its audit activity trail. */
  caseDetail: (caseId: string) =>
    request<{ case: HRCase; activity: AuditRow[] }>(`/cases/${caseId}/detail`),

  /** Manually resolve / reopen a case (analyst+). */
  updateCaseStatus: (caseId: string, status: string, note = "") =>
    request<HRCase>(`/cases/${caseId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, note }),
    }),

  /** Pending human-in-the-loop approval tasks. */
  pendingApprovals: () => request<PendingTask[]>("/cases/pending"),

  /** Past approve/reject decisions, queried from the audit log. */
  approvalHistory: () => request<ApprovalDecision[]>("/cases/approvals/history"),

  /** Approve a paused agent task. */
  approve: (caseId: string, taskId: string, reason = "") =>
    request<unknown>(`/cases/${caseId}/approve`, {
      method: "PATCH",
      body: JSON.stringify({ task_id: taskId, reason }),
    }),

  /** Reject a paused agent task with a reason. */
  reject: (caseId: string, taskId: string, reason: string) =>
    request<unknown>(`/cases/${caseId}/reject`, {
      method: "PATCH",
      body: JSON.stringify({ task_id: taskId, reason }),
    }),

  /** Audit log rows. */
  audit: (agent?: string) =>
    request<AuditRow[]>(`/audit${agent ? `?agent=${agent}` : ""}`),

  /** URL for the CSV export endpoint. */
  auditExportUrl: (agent?: string) =>
    `${API_BASE}/audit/export${agent ? `?agent=${agent}` : ""}`,

  // ── Policies ──────────────────────────────────────────────────────────── //
  /** List all ingested policy documents. */
  policies: () =>
    request<PolicyDoc[]>("/policies"),

  /** Upload a PDF policy document for ingestion. */
  ingestPolicy: async (file: File): Promise<ApiEnvelope<unknown>> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/policies/ingest`, {
      method: "POST",
      body: form,
      cache: "no-store",
      headers: authHeaders(),
    });
    return (await res.json()) as ApiEnvelope<unknown>;
  },

  /** Soft-delete a policy (hidden + vectors purged, but restorable). */
  deletePolicy: (docId: string) =>
    request<{ doc_id: string; deleted: boolean; restorable: boolean }>(`/policies/${encodeURIComponent(docId)}`, { method: "DELETE" }),

  /** Restore a soft-deleted policy — re-embeds from retained text (undo). */
  restorePolicy: (docId: string) =>
    request<{ doc_id: string; restored: boolean }>(`/policies/${encodeURIComponent(docId)}/restore`, { method: "POST" }),

  // ── Chat ──────────────────────────────────────────────────────────────── //
  /** Non-streaming chat turn. */
  chat: (message: string, history: ChatMessage[] = []) =>
    request<ChatResponse>("/chat", { method: "POST", body: JSON.stringify({ message, history }) }),

  /** Returns the URL for the streaming endpoint (used with EventSource). */
  chatStreamUrl: () => `${API_BASE}/chat/stream`,

  // ── Auth ──────────────────────────────────────────────────────────────── //
  register: (email: string, password: string, name = "") =>
    request<AuthSession>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, name }),
    }),

  login: (email: string, password: string) =>
    request<AuthSession>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  me: () => request<AuthUser>("/auth/me"),

  /** Demo-mode role switch: mint a token for a pre-seeded persona (no password). */
  demoSwitch: (role: Role) =>
    request<AuthSession>("/auth/demo/switch", {
      method: "POST",
      body: JSON.stringify({ role }),
    }),

  googleStatus: () => request<{ enabled: boolean }>("/auth/google/status"),

  googleLoginUrl: () => `${API_BASE}/auth/google/login`,

  listUsers: () => request<AuthUser[]>("/auth/users"),

  setUserRole: (userId: string, role: string) =>
    request<AuthUser>(`/auth/users/${userId}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),

  // ── Chat sessions ─────────────────────────────────────────────────────── //
  chatSessions: () => request<ChatSession[]>("/chat/sessions"),
  chatSessionMessages: (id: string) =>
    request<StoredChatMessage[]>(`/chat/sessions/${id}`),
  deleteChatSession: (id: string) =>
    request<{ session_id: string; deleted: boolean }>(`/chat/sessions/${id}`, { method: "DELETE" }),
};

export type Role = "viewer" | "analyst" | "manager" | "admin";

export interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  role: Role;
  provider: string;
  avatar_url: string | null;
}

export interface AuthSession {
  token: string;
  user: AuthUser;
}

export interface ChatSession {
  id: string;
  user_id: string | null;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface StoredChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  tool_calls: string | null;
  mode: string | null;
  created_at: string;
}

export interface Metrics {
  agent_actions_total: number;
  actions_by_agent: { agent: string; count: number }[];
  cases_total: number;
  active_cases: number;
  resolved_cases: number;
  resolved_today: number;
  escalations: number;
  resume_screens: number;
  policy_queries: number;
  injection_blocks: number;
  auto_resolution_rate: number;
  escalation_rate: number;
  cases_by_status: { status: string; count: number }[];
  cases_by_category: { category: string; count: number }[];
}

export interface AttritionFeatures {
  tenure_months: number;
  performance_score: number;
  absence_days: number;
  last_promotion_months: number;
  salary_band: number;
  manager_rating: number;
}

export interface RetentionSuggestion {
  factor: string;
  suggestion: string;
  policy_query: string;
  policy_answer: string;
  grounded: boolean;
  sources: string[];
}

export interface AttritionResult {
  attrition_risk_score: number;
  top_risk_factors: { factor: string; contribution: number }[];
  explanation: string;
  needs_review: boolean;
  advisory_only: boolean;
  // Policy-grounded retention suggestions, composed from Policy Q&A on high risk.
  retention_context?: RetentionSuggestion[];
  _mode?: "full" | "degraded";
}

export interface ResumeScreenResult {
  score: number;
  recommendation: string;
  reasoning: string;
  matched_skills: string[];
  missing_skills: string[];
  blinded: boolean;
  needs_review: boolean;
  // Advisory timeline data-integrity flags (never affect the score).
  consistency_flags?: string[];
  _mode?: "full" | "degraded";
}

export interface PolicyDoc {
  doc_id: string;
  filename: string;
  chunks: number;
  char_count: number;
  status: string;
  ingested_at: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  reply: string;
  tool_calls: { tool?: string; name?: string; args?: Record<string, unknown> }[];
  mode: "full" | "degraded" | "error";
}
