"use client";

/**
 * Operator-facing audit workspace.
 *
 * The backend remains the immutable source of truth. This view translates
 * audit rows into four usable lenses: agent orchestration, cost attribution,
 * compliance signals, and temporal activity. Raw JSON is intentionally kept
 * out of the primary table; Trace exposes the structured event sequence.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  Clock3,
  DollarSign,
  Download,
  Eye,
  Filter,
  Hand,
  RefreshCw,
  ShieldCheck,
  X,
  XCircle,
} from "lucide-react";
import { api, type AuditRow, type InferenceUsage } from "../../lib/api";

type Payload = Record<string, unknown>;

type Trace = {
  key: string;
  caseId: string;
  rows: AuditRow[];
};

const ACTION_LABELS: Record<string, string> = {
  triage: "Classify ticket",
  triage_override: "Human reroute",
  policy_query: "Retrieve policy",
  policy_qa: "Answer policy question",
  resume_screen: "Screen resume",
  attrition_predict: "Predict attrition",
  human_approved: "Human approval",
  human_rejected: "Human rejection",
  prompt_injection_blocked: "Blocked prompt injection",
  onboarding: "Onboarding step",
};

export default function AuditLog() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [usage, setUsage] = useState<InferenceUsage | null>(null);
  const [agent, setAgent] = useState("");
  const [status, setStatus] = useState("");
  const [action, setAction] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [selectedTrace, setSelectedTrace] = useState<Trace | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [visibleRows, setVisibleRows] = useState(8);

  const load = useCallback(async () => {
    const [auditResult, usageResult] = await Promise.allSettled([
      api.audit(agent || undefined),
      api.inferenceUsage(),
    ]);
    if (auditResult.status === "fulfilled") setRows(auditResult.value);
    if (usageResult.status === "fulfilled") setUsage(usageResult.value);
  }, [agent]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 10_000);
    return () => window.clearInterval(id);
  }, [load]);

  const agents = useMemo(
    () => Array.from(new Set(rows.map((row) => row.agent_name))).sort(),
    [rows]
  );
  const actions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.action_type))).sort(),
    [rows]
  );
  const statuses = useMemo(
    () => Array.from(new Set(rows.map((row) => row.status))).sort(),
    [rows]
  );

  const filtered = useMemo(
    () =>
      rows.filter((row) => {
        const timestamp = new Date(row.timestamp).getTime();
        if (status && row.status !== status) return false;
        if (action && row.action_type !== action) return false;
        if (from && timestamp < new Date(`${from}T00:00:00`).getTime()) return false;
        if (to && timestamp > new Date(`${to}T23:59:59.999`).getTime()) return false;
        return true;
      }),
    [action, from, rows, status, to]
  );

  const traces = useMemo(() => groupTraces(filtered), [filtered]);
  const humanReviews = filtered.filter(isHumanReview).length;
  const failures = filtered.filter((row) => row.status === "error").length;
  const piiRedactions = filtered.filter((row) => hasPiiRedaction(row)).length;
  const costRows = Object.entries(usage?.tiers ?? {}).filter(([, value]) => value.queries > 0);
  const observedSpend = usage?.totals.estimated_usd ?? 0;
  const shownRows = filtered.slice(0, visibleRows);

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-brand-magenta">
            <ShieldCheck size={14} /> Governance workspace
          </div>
          <h2 className="mt-1 text-2xl font-semibold text-brand-purple">Audit & orchestration</h2>
          <p className="mt-1 max-w-2xl text-sm text-ink-700/60">
            Follow how agents acted, where a human intervened, what the system spent, and which controls fired.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-700/55">
          <Activity size={14} className="text-green-600" />
          Append-only log · refreshes every 10s
        </div>
      </header>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <SummaryCard label="Audit events" value={filtered.length.toLocaleString()} icon={<Activity size={16} />} tone="purple" />
        <SummaryCard label="Traced workflows" value={traces.length.toLocaleString()} icon={<ArrowRight size={16} />} tone="blue" />
        <SummaryCard label="Human checkpoints" value={humanReviews.toLocaleString()} icon={<Hand size={16} />} tone="amber" />
        <SummaryCard label="PII redaction events" value={piiRedactions.toLocaleString()} icon={<ShieldCheck size={16} />} tone="green" />
        <SummaryCard label="Control failures" value={failures.toLocaleString()} icon={<AlertTriangle size={16} />} tone={failures ? "red" : "green"} />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.25fr_0.75fr]">
        <Panel title="Agent orchestration timeline" icon={<ArrowRight size={16} />}>
          {traces.length === 0 ? (
            <EmptyState text="No traceable workflows match the current filters." />
          ) : (
            <div className="space-y-3">
              {traces.slice(0, 5).map((trace) => (
                <button
                  key={trace.key}
                  type="button"
                  onClick={() => setSelectedTrace(trace)}
                  className="w-full rounded-xl border border-brand-purple/10 bg-brand-cream/35 p-3 text-left transition hover:border-brand-magenta/35 hover:bg-brand-cream/60"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-xs text-ink-700/60">{trace.caseId}</span>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${traceTone(trace.rows)}`}>
                      {traceStatus(trace.rows)}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {trace.rows.slice(0, 5).map((row, index) => (
                      <span key={row.id} className="flex items-center gap-1.5">
                        <span className="rounded-lg border border-brand-purple/10 bg-white px-2 py-1 text-xs font-medium text-brand-purple">
                          {agentLabel(row.agent_name)}
                          <span className="ml-1 text-ink-700/45">{actionLabel(row.action_type)}</span>
                        </span>
                        {index < Math.min(trace.rows.length, 5) - 1 && <ArrowRight size={12} className="text-ink-700/35" />}
                      </span>
                    ))}
                    {trace.rows.length > 5 && <span className="text-xs text-ink-700/50">+{trace.rows.length - 5} events</span>}
                  </div>
                  <div className="mt-2 flex items-center gap-3 text-[11px] text-ink-700/50">
                    <span>{trace.rows.length} recorded steps</span>
                    <span>·</span>
                    <span>{new Date(trace.rows[0].timestamp).toLocaleString()}</span>
                    <span className="ml-auto inline-flex items-center gap-1 font-medium text-brand-magenta"><Eye size={12} /> Trace</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Cost & endpoint attribution" icon={<DollarSign size={16} />}>
          {costRows.length === 0 ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-amber-800"><Clock3 size={15} /> No live spend measured</div>
              <p className="mt-1 text-xs leading-relaxed text-amber-700">
                The local ledger has no provider calls. Control benchmarks remain visible in Command, but they are not provider billing evidence.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {costRows.map(([tier, value]) => (
                <div key={tier} className="flex items-center justify-between rounded-xl border border-brand-purple/10 bg-brand-cream/35 px-3 py-2.5">
                  <div>
                    <div className="text-sm font-semibold capitalize text-brand-purple">{tier} route</div>
                    <div className="text-[11px] text-ink-700/50">{value.provider_calls} provider calls · {value.queries} queries</div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-sm font-semibold text-green-700">{currency(value.total_usd)}</div>
                    <div className="text-[10px] text-ink-700/50">{currency(value.avg_per_query)}/query</div>
                  </div>
                </div>
              ))}
              <div className="flex items-center justify-between border-t border-brand-purple/10 pt-3 text-sm font-semibold text-brand-purple">
                <span>Observed application estimate</span><span>{currency(observedSpend)}</span>
              </div>
              <p className="text-[10px] leading-relaxed text-ink-700/50">Local ledger estimate only · Fireworks billing export is separate and credential-gated.</p>
            </div>
          )}
        </Panel>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-[0.8fr_1.2fr]">
        <Panel title="Compliance controls" icon={<ShieldCheck size={16} />}>
          <div className="grid grid-cols-3 gap-2">
            <ComplianceMetric label="PII redactions" value={piiRedactions} tone="red" />
            <ComplianceMetric label="Human review" value={humanReviews} tone="purple" />
            <ComplianceMetric label="Failures" value={failures} tone={failures ? "amber" : "green"} />
          </div>
          <div className="mt-4 space-y-2 text-xs text-ink-700/65">
            <ControlRow label="Audit persistence" value="append-only" ok />
            <ControlRow label="Prompt injection" value={filtered.some((row) => row.action_type === "prompt_injection_blocked") ? "blocked + logged" : "no blocks in filter"} ok />
            <ControlRow label="Human-in-the-loop" value={humanReviews ? "checkpoints recorded" : "no checkpoint in filter"} ok={humanReviews > 0} />
          </div>
        </Panel>

        <Panel title="Temporal activity" icon={<CalendarDays size={16} />}>
          <TemporalBars rows={filtered} />
        </Panel>
      </section>

      <section className="rounded-2xl border border-brand-purple/10 bg-white shadow-sm">
        <div className="border-b border-brand-purple/10 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Filter size={15} className="text-brand-magenta" />
            <select value={agent} onChange={(event) => setAgent(event.target.value)} className="rounded-lg border border-brand-purple/15 bg-white px-2.5 py-1.5 text-xs">
              <option value="">All agents</option>
              {agents.map((item) => <option key={item}>{item}</option>)}
            </select>
            <select value={action} onChange={(event) => setAction(event.target.value)} className="rounded-lg border border-brand-purple/15 bg-white px-2.5 py-1.5 text-xs">
              <option value="">All actions</option>
              {actions.map((item) => <option key={item}>{item}</option>)}
            </select>
            <select value={status} onChange={(event) => setStatus(event.target.value)} className="rounded-lg border border-brand-purple/15 bg-white px-2.5 py-1.5 text-xs">
              <option value="">All statuses</option>
              {statuses.map((item) => <option key={item}>{item}</option>)}
            </select>
            <label className="inline-flex items-center gap-1 text-xs text-ink-700/55"><CalendarDays size={13} /> from <input type="date" value={from} onChange={(event) => setFrom(event.target.value)} className="rounded-lg border border-brand-purple/15 px-2 py-1.5" /></label>
            <label className="inline-flex items-center gap-1 text-xs text-ink-700/55">to <input type="date" value={to} onChange={(event) => setTo(event.target.value)} className="rounded-lg border border-brand-purple/15 px-2 py-1.5" /></label>
            <button type="button" onClick={() => load()} title="Refresh audit data" aria-label="Refresh audit data" className="rounded-lg border border-brand-purple/15 p-2 text-brand-purple hover:bg-brand-cream"><RefreshCw size={14} /></button>
            <a href={api.auditExportUrl(agent || undefined)} className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-brand-purple px-3 py-2 text-xs font-medium text-white hover:opacity-90"><Download size={14} /> Export CSV</a>
          </div>
        </div>
        <div className="space-y-2 p-3 sm:p-4">
          {shownRows.map((row) => {
            const trace = traces.find((item) => item.rows.some((candidate) => candidate.id === row.id));
            const isOpen = expanded === row.id;
            return (
              <article key={row.id} className="rounded-xl border border-brand-purple/10 bg-brand-cream/25 p-3 transition hover:border-brand-magenta/30 hover:bg-brand-cream/45">
                <div className="flex flex-wrap items-start gap-3">
                  <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${row.status === "error" ? "bg-red-500" : row.status === "paused" ? "bg-amber-500" : "bg-green-500"}`} aria-hidden="true" />
                  <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="text-sm font-semibold text-brand-purple">{agentLabel(row.agent_name)}</span><span className="rounded-full bg-white px-2 py-1 text-[10px] font-medium text-brand-purple">{actionLabel(row.action_type)}</span><span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10px] font-medium ${statusTone(row.status)}`}>{row.status === "success" ? <CheckCircle2 size={11} /> : row.status === "error" ? <XCircle size={11} /> : <Clock3 size={11} />}{row.status}</span></div><button type="button" onClick={() => setExpanded(isOpen ? null : row.id)} className="mt-2 block max-w-full text-left text-xs leading-relaxed text-ink-700/75 hover:text-brand-purple"><span className={isOpen ? "" : "line-clamp-2"}>{payloadSummary(row.input)}</span>{isOpen && <span className="mt-2 block rounded-lg border border-brand-purple/10 bg-white/70 p-2 text-[11px] text-ink-700/65">Outcome: {payloadSummary(row.output)}</span>}</button></div>
                  <div className="flex shrink-0 items-center gap-2 text-[10px] text-ink-700/50"><span>{new Date(row.timestamp).toLocaleString()}</span><button type="button" onClick={() => trace && setSelectedTrace(trace)} disabled={!trace} className="inline-flex items-center gap-1 rounded-lg border border-brand-purple/15 bg-white px-2 py-1.5 text-xs font-medium text-brand-purple hover:bg-brand-cream disabled:cursor-not-allowed disabled:opacity-35"><Eye size={12} /> Trace</button></div>
                </div>
              </article>
            );
          })}
          {filtered.length === 0 && <div className="px-4 py-10 text-center text-sm text-ink-700/55">No audit entries match the current filters.</div>}
          {shownRows.length < filtered.length && <button type="button" onClick={() => setVisibleRows((count) => count + 8)} className="w-full rounded-lg border border-brand-purple/15 bg-white px-3 py-2 text-xs font-semibold text-brand-purple hover:bg-brand-cream">Show 8 more events <span className="font-normal text-ink-700/50">({filtered.length - shownRows.length} remaining)</span></button>}
        </div>
      </section>

      {selectedTrace && <TraceModal trace={selectedTrace} onClose={() => setSelectedTrace(null)} />}
    </div>
  );
}

function groupTraces(rows: AuditRow[]): Trace[] {
  const grouped = new Map<string, AuditRow[]>();
  for (const row of rows) {
    const caseId = findCaseId(row) ?? `event:${row.id.slice(0, 8)}`;
    grouped.set(caseId, [...(grouped.get(caseId) ?? []), row]);
  }
  return Array.from(grouped.entries())
    .map(([caseId, items]) => ({ key: caseId, caseId, rows: [...items].sort((a, b) => a.timestamp.localeCompare(b.timestamp)) }))
    .sort((a, b) => b.rows[0].timestamp.localeCompare(a.rows[0].timestamp));
}

function parsePayload(raw: string): Payload | null {
  try {
    const value: unknown = JSON.parse(raw);
    return value && typeof value === "object" && !Array.isArray(value) ? value as Payload : null;
  } catch {
    return null;
  }
}

function findCaseId(row: AuditRow): string | null {
  for (const raw of [row.input, row.output]) {
    const payload = parsePayload(raw);
    const caseId = payload?.case_id;
    if (typeof caseId === "string" && caseId) return caseId;
  }
  return null;
}

function payloadSummary(raw: string): string {
  const payload = parsePayload(raw);
  if (!payload) return raw.trim() || "No recorded context";
  const keys = ["query", "input", "message", "summary", "detail", "reason", "category", "step", "risk"];
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number") return `${key}: ${value}`;
  }
  const entries = Object.entries(payload).filter(([key]) => !["case_id", "timestamp"].includes(key)).slice(0, 2);
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join(" · ") || "Structured audit event";
}

function agentLabel(agent: string): string {
  return agent.replace(/_agent$/, "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action.replaceAll("_", " ");
}

function isHumanReview(row: AuditRow): boolean {
  return /human|approval|reject|override|reroute/i.test(`${row.action_type} ${row.status} ${row.output}`);
}

function hasPiiRedaction(row: AuditRow): boolean {
  return /redacted|\[REDACTED|<redacted/i.test(`${row.input} ${row.output}`);
}

function traceStatus(rows: AuditRow[]): string {
  if (rows.some((row) => row.status === "error")) return "Needs review";
  if (rows.some(isHumanReview)) return "Human checkpoint";
  return "Recorded workflow";
}

function traceTone(rows: AuditRow[]): string {
  if (rows.some((row) => row.status === "error")) return "bg-red-100 text-red-700";
  if (rows.some(isHumanReview)) return "bg-amber-100 text-amber-800";
  return "bg-green-100 text-green-700";
}

function statusTone(status: string): string {
  if (status === "error") return "bg-red-100 text-red-700";
  if (status === "paused") return "bg-amber-100 text-amber-800";
  return "bg-green-100 text-green-700";
}

function currency(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 6 }).format(value);
}

function SummaryCard({ label, value, icon, tone }: { label: string; value: string; icon: React.ReactNode; tone: "purple" | "blue" | "amber" | "green" | "red" }) {
  const colors = { purple: "text-brand-purple", blue: "text-sky-600", amber: "text-amber-600", green: "text-green-600", red: "text-red-600" };
  return <div className="rounded-xl border border-brand-purple/10 bg-white p-3 shadow-sm"><div className={`flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-ink-700/50 ${colors[tone]}`}>{icon}{label}</div><div className={`mt-2 text-2xl font-semibold ${colors[tone]}`}>{value}</div></div>;
}

function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return <section className="rounded-2xl border border-brand-purple/10 bg-white p-4 shadow-sm"><h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-brand-purple">{icon}{title}</h3>{children}</section>;
}

function ComplianceMetric({ label, value, tone }: { label: string; value: number; tone: "red" | "purple" | "amber" | "green" }) {
  const colors = { red: "text-red-600", purple: "text-brand-purple", amber: "text-amber-600", green: "text-green-600" };
  return <div className="rounded-lg border border-brand-purple/10 bg-brand-cream/30 px-2 py-2 text-center"><div className={`text-lg font-semibold ${colors[tone]}`}>{value}</div><div className="mt-0.5 text-[10px] leading-tight text-ink-700/50">{label}</div></div>;
}

function ControlRow({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return <div className="flex items-center justify-between gap-3"><span>{label}</span><span className={`inline-flex items-center gap-1 font-medium ${ok ? "text-green-700" : "text-amber-700"}`}>{ok ? <CheckCircle2 size={12} /> : <Clock3 size={12} />}{value}</span></div>;
}

function TemporalBars({ rows }: { rows: AuditRow[] }) {
  const buckets = new Map<string, number>();
  for (const row of rows) {
    const key = new Date(row.timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    buckets.set(key, (buckets.get(key) ?? 0) + 1);
  }
  const points = Array.from(buckets.entries()).slice(-7);
  const max = Math.max(...points.map(([, value]) => value), 1);
  if (!points.length) return <EmptyState text="No temporal activity in this filter." />;
  return <div className="flex h-36 items-end gap-2">{points.map(([label, value]) => <div key={label} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-1"><span className="text-[10px] font-medium text-brand-purple">{value}</span><div className="w-full rounded-t-md bg-brand-magenta/75" style={{ height: `${Math.max(8, (value / max) * 96)}px` }} title={`${value} events on ${label}`} /><span className="truncate text-[10px] text-ink-700/50">{label}</span></div>)}</div>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-brand-purple/15 bg-brand-cream/25 px-4 py-8 text-center text-xs text-ink-700/55">{text}</div>;
}

function TraceModal({ trace, onClose }: { trace: Trace; onClose: () => void }) {
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/35 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={`Trace ${trace.caseId}`}>
    <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white shadow-2xl">
      <header className="flex items-start justify-between border-b border-brand-purple/10 bg-brand-cream/60 px-5 py-4"><div><div className="text-[10px] uppercase tracking-[0.16em] text-brand-magenta">Agent trace</div><h2 className="mt-1 font-semibold text-brand-purple">{trace.caseId}</h2><p className="mt-1 text-xs text-ink-700/55">{trace.rows.length} immutable event{trace.rows.length === 1 ? "" : "s"} · chronological order</p></div><button type="button" onClick={onClose} aria-label="Close trace" className="rounded-lg p-1 text-ink-700/50 hover:bg-brand-purple/10"><X size={18} /></button></header>
      <ol className="space-y-3 px-5 py-5">{trace.rows.map((row, index) => <li key={row.id} className="relative pl-8"><span className={`absolute left-0 top-1 flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold text-white ${row.status === "error" ? "bg-red-500" : isHumanReview(row) ? "bg-amber-500" : "bg-brand-magenta"}`}>{index + 1}</span>{index < trace.rows.length - 1 && <span className="absolute left-[9px] top-6 h-[calc(100%+12px)] w-px bg-brand-purple/15" />}<div className="rounded-xl border border-brand-purple/10 bg-brand-cream/25 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div className="font-medium text-brand-purple">{agentLabel(row.agent_name)} <span className="font-normal text-ink-700/60">· {actionLabel(row.action_type)}</span></div><span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${statusTone(row.status)}`}>{row.status}</span></div><p className="mt-2 text-xs leading-relaxed text-ink-700/75">{payloadSummary(row.output)}</p><div className="mt-2 flex items-center gap-1 text-[10px] text-ink-700/45"><Clock3 size={11} />{new Date(row.timestamp).toLocaleString()}{isHumanReview(row) && <><span>·</span><Hand size={11} /> Human checkpoint</>}</div></div></li>)}</ol>
    </div>
  </div>;
}
