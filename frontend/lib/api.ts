/**
 * Typed fetch wrappers around the FastAPI backend.
 *
 * Most backend endpoints return the envelope:
 *   { success: boolean; data: T | null; error: string | null }
 *
 * Operational probe endpoints such as /health and /metrics may be raw JSON or
 * the standard envelope, depending on which backend build is deployed.
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

export interface FireworksBatchStatus {
  job_id: string;
  status:
    | "validating"
    | "pending"
    | "running"
    | "completed"
    | "failed"
    | "expired"
    | "cancelled"
    | "unknown";
  label: string;
  provider_state: string;
  explanation: string;
  provider_message: string;
  progress_percent: number | null;
  processed_requests: number | null;
  total_requests: number | null;
  failed_requests: number | null;
  terminal: boolean;
  poll_after_seconds: number | null;
}

export interface CostControlGate {
  name: string;
  ok: boolean;
  detail: string;
  evidence: Record<string, unknown>;
}

export interface CostControlsCertification {
  certification: string;
  ok: boolean;
  network_required: boolean;
  provider_key_required: boolean;
  gate_count: number;
  passed_count: number;
  gates: CostControlGate[];
}

export type CapabilityStatus =
  | "proven"
  | "measured_local"
  | "configured"
  | "live_gated"
  | "not_configured"
  | "unavailable";

export interface RuntimeMeasurement {
  name: string;
  value: number;
  unit: string;
  evidence_level: string;
  notes: string;
}

export interface ProviderCapability {
  provider_id: string;
  provider_type: string;
  status: CapabilityStatus;
  models_available: string[];
  supports_batch: boolean;
  supports_streaming: boolean;
  supports_prompt_cache: boolean;
  supports_json_schema: boolean;
  supports_byok: boolean;
  live_enabled: boolean;
  missing_inputs: string[];
  evidence_required: string[];
  measurements: RuntimeMeasurement[];
  route_fit: string[];
}

export interface HardwareCapability {
  hardware_id: string;
  vendor: string;
  status: CapabilityStatus;
  detector: string;
  evidence_required: string[];
  runtime_evidence_file: string | null;
  device_names: string[];
  measurements: RuntimeMeasurement[];
  notes: string[];
}

export interface CapabilityRoute {
  task_type: string;
  selected_provider: string;
  status: CapabilityStatus;
  reason: string;
  evidence_used: string[];
  live_call_allowed: boolean;
}

export interface CapabilitySnapshot {
  generated_at_unix: number;
  claim_policy: string;
  demo_mode: boolean;
  active_provider: string;
  providers: ProviderCapability[];
  hardware: HardwareCapability[];
  routing: CapabilityRoute[];
  required_live_inputs: Record<string, string[]>;
  safe_wording: string[];
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

let inMemoryByokKey: string | null = null;

/**
 * Ephemeral Bring-Your-Own-Key store. Kept only in this JavaScript runtime
 * (cleared on reload/tab close; never Web Storage) and sent only as the
 * `X-Client-LLM-Key` request header. The backend uses it per request and never
 * persists it.
 */
export const byokStore = {
  get(): string | null {
    if (typeof window === "undefined") return null;
    return inMemoryByokKey;
  },
  set(key: string) {
    if (typeof window !== "undefined") inMemoryByokKey = key;
  },
  clear() {
    inMemoryByokKey = null;
  },
};

/** Build ordinary application headers. BYOK is deliberately excluded. */
export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers = { ...extra };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

/** Add the ephemeral provider key only for an endpoint that may invoke a model. */
export function inferenceHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers = authHeaders(extra);
  const byok = byokStore.get();
  if (byok) headers["X-Client-LLM-Key"] = byok;
  return headers;
}

/** Ping the server with current headers; return whether it accepted a BYOK key. */
export async function checkByok(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/byok/verify`, {
      headers: inferenceHeaders(),
      cache: "no-store",
    });
    return res.headers.get("X-BYOK") === "1";
  } catch {
    return false;
  }
}

export type ByokStatus =
  | "verified"
  | "rejected"
  | "malformed"
  | "missing"
  | "unverifiable"
  | "unsupported";

/** Provider-side verification: checks the request-scoped key against the configured provider. */
export async function verifyByok(): Promise<{ valid: boolean; status: ByokStatus; detail: string; provider?: string }> {
  try {
    return await inferenceRequest<{ valid: boolean; status: ByokStatus; detail: string; provider?: string }>("/byok/verify");
  } catch {
    return { valid: false, status: "unverifiable", detail: "verification request failed" };
  }
}

/** Perform a JSON request and unwrap the standard envelope. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  for (const [name, value] of Object.entries(authHeaders())) headers.set(name, value);
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...init,
    headers,
  });
  const body = (await res.json()) as ApiEnvelope<T>;
  if (!body.success) {
    throw new Error(body.error ?? "request failed");
  }
  return body.data as T;
}

/** Perform a request to the small server-side allowlist of model-capable routes. */
async function inferenceRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  for (const [name, value] of Object.entries(inferenceHeaders())) headers.set(name, value);
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...init,
    headers,
  });
  const body = (await res.json()) as ApiEnvelope<T>;
  if (!body.success) {
    throw new Error(body.error ?? "request failed");
  }
  return body.data as T;
}

async function probeRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  for (const [name, value] of Object.entries(authHeaders())) headers.set(name, value);
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...init,
    headers,
  });
  if (!res.ok) {
    throw new Error(`request failed: ${res.status}`);
  }
  const body = (await res.json()) as T | ApiEnvelope<T>;
  if (body && typeof body === "object" && "success" in body) {
    const envelope = body as ApiEnvelope<T>;
    if (!envelope.success) {
      throw new Error(envelope.error ?? "request failed");
    }
    return envelope.data as T;
  }
  return body as T;
}

export const api = {
  /** Backend health snapshot. */
  health: () =>
    probeRequest<{
      status: string;
      environment: string;
      agents_registered: number;
      agents_active: number;
      auth_enforced?: boolean;
      llm_config_issues?: string[];
      llm_enabled?: boolean;
      llm_provider?: string;
      byok_supported?: boolean;
    }>("/health"),

  /** List all agents with runtime status. */
  agents: () => request<Agent[]>("/agents"),

  /** Operational metrics derived from the audit log + cases. */
  metrics: () => probeRequest<Metrics>("/metrics"),

  /** Four-Fifths rule evidence from the synthetic adverse-impact ATS dataset. */
  biasAudit: () => request<BiasAudit>("/metrics/bias-audit"),

  /** Inspect a known Fireworks Batch job (manager+ in enforced deployments). */
  fireworksBatchStatus: (jobId: string) =>
    request<FireworksBatchStatus>(
      `/lifecycle/fireworks/batch/${encodeURIComponent(jobId)}`
    ),

  /** Zero-spend cost-control certification, safe to run without a provider key. */
  costControls: () => request<CostControlsCertification>("/lifecycle/cost-controls"),

  /** Evidence-driven provider and hardware discovery. */
  capabilities: () => request<CapabilitySnapshot>("/lifecycle/capabilities"),

  /** Manually trigger an agent. */
  triggerAgent: (name: string, input: string, payload?: unknown) =>
    inferenceRequest<unknown>(`/agents/${name}/trigger`, {
      method: "POST",
      body: JSON.stringify({ input, payload }),
    }),

  /** Screen a resume (text) against a job description. */
  screenResume: (jobDescription: string, resume: string) =>
    inferenceRequest<ResumeScreenResult>(`/agents/resume_screener_agent/trigger`, {
      method: "POST",
      body: JSON.stringify({
        input: resume,
        payload: { job_description: jobDescription, resume },
      }),
    }),

  /** Predict attrition risk from the six employee features. */
  predictAttrition: (features: AttritionFeatures) =>
    inferenceRequest<AttritionResult>(`/agents/attrition_agent/trigger`, {
      method: "POST",
      body: JSON.stringify({ input: "", payload: features }),
    }),

  /** Record a manager's decision on a retention suggestion (append-only). */
  submitRetentionFeedback: (payload: {
    case_id: string;
    suggestion_id: string;
    risk_driver: string;
    action_taken: "accepted" | "rejected" | "edited";
    manager_notes?: string;
  }) =>
    request<{ id: string }>(`/feedback`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  /** Per-driver aggregate of manager feedback (the "what's working" signal). */
  feedbackStats: () => request<FeedbackStat[]>(`/feedback/stats`),

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
      headers: inferenceHeaders(),
    });
    return (await res.json()) as ApiEnvelope<unknown>;
  },

  /** List HR cases with optional filters. */
  cases: (category?: string, status?: string) => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    if (status) params.set("status", status);
    const qs = params.toString();
    return request<HRCase[] | { items: HRCase[]; next_cursor: string | null }>(
      `/cases${qs ? `?${qs}` : ""}`
    ).then((data) => (Array.isArray(data) ? data : data.items));
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

  /** Reject the AI's triage routing → hand off to a human queue (override telemetry). */
  rerouteCase: (caseId: string, queue: string, reason = "") =>
    request<HRCase>(`/cases/${caseId}/reroute`, {
      method: "PATCH",
      body: JSON.stringify({ queue, reason }),
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
    inferenceRequest<ChatResponse>("/chat", {
      method: "POST",
      body: JSON.stringify({ message, history }),
    }),

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

  /** Open-access role switch: mint a scoped token for a pre-seeded role. */
  switchPersona: (role: Role) =>
    request<AuthSession>("/auth/open-access/switch", {
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
  triage_overrides: number;
  triage_override_rate: number;
  cases_by_status: { status: string; count: number }[];
  cases_by_category: { category: string; count: number }[];
}

export interface BiasAuditGroup {
  group: string;
  selected: number;
  total: number;
  selection_rate: number;
}

export interface BiasAuditDimension {
  dimension: string;
  reference_group: string;
  reference_rate: number;
  lowest_group: string;
  lowest_rate: number;
  adverse_impact_ratio: number;
  threshold: number;
  violates_four_fifths_rule: boolean;
  groups: BiasAuditGroup[];
}

export interface BiasAudit {
  dataset_path: string;
  record_count: number;
  decision_column: string;
  threshold: number;
  violations_count: number;
  violates_four_fifths_rule: boolean;
  dimensions: BiasAuditDimension[];
  headline: string;
  available: boolean;
}

export interface AttritionFeatures {
  tenure_months: number;
  performance_score: number;
  absence_days: number;
  last_promotion_months: number;
  salary_band: number;
  manager_rating: number;
}

export interface FeedbackStat {
  risk_driver: string;
  accepted: number;
  rejected: number;
  edited: number;
  total: number;
  acceptance_rate: number;
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
  case_id?: string;
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
  // Negation pass: "validated" = an LLM graded each match's context; "keyword_fallback"
  // = keyword-only (blind to negation → confidence downgraded). Dropped matches listed.
  skill_audit_mode?: "validated" | "keyword_fallback";
  unverified_skills?: string[];
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
