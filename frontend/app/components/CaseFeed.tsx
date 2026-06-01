"use client";

/**
 * CaseFeed panel.
 *
 * Shows a real-time feed of HR cases via the WebSocket endpoint (/ws/feed),
 * falling back to 10s polling when the socket is disconnected. Each row shows
 * the case id, a category badge, status, assigned agent, created time and a
 * summary. Cases can be filtered by category and status, and clicking a row
 * opens a detail drawer with the full ticket and its audit activity trail.
 */

import { useEffect, useRef, useState } from "react";
import {
  X,
  FileText,
  Loader2,
  CheckCircle,
  RotateCcw,
  Sparkles,
  ChevronDown,
  Database,
  AlertTriangle,
  ArrowRightLeft,
} from "lucide-react";
import { WS_URL, api, type HRCase, type AuditRow } from "../../lib/api";
import { useToast } from "./Toast";

const CATEGORIES = [
  "ALL",
  "BENEFITS",
  "POLICY",
  "ONBOARDING",
  "PERFORMANCE",
  "COMPLIANCE",
  "URGENT",
];
const STATUSES = ["ALL", "open", "resolved", "escalated"];

// Human queues a misrouted case can be handed off to (mirrors the backend enum).
const REROUTE_QUEUES: { value: string; label: string }[] = [
  { value: "payroll", label: "Payroll" },
  { value: "legal", label: "Legal" },
  { value: "employee_relations", label: "Employee Relations" },
  { value: "benefits", label: "Benefits" },
  { value: "it_helpdesk", label: "IT Helpdesk" },
  { value: "people_partner", label: "People Partner" },
];

const CATEGORY_COLORS: Record<string, string> = {
  URGENT: "bg-red-500 text-white",
  BENEFITS: "bg-brand-peach text-ink-800",
  POLICY: "bg-brand-magenta text-white",
  ONBOARDING: "bg-brand-purple text-white",
  PERFORMANCE: "bg-amber-400 text-ink-800",
  COMPLIANCE: "bg-indigo-500 text-white",
};

export default function CaseFeed() {
  const [cases, setCases] = useState<HRCase[]>([]);
  const [category, setCategory] = useState("ALL");
  const [status, setStatus] = useState("ALL");
  const [selected, setSelected] = useState<HRCase | null>(null);
  const [live, setLive] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  // Initial + fallback polling load.
  useEffect(() => {
    const load = async () => {
      try {
        setCases(await api.cases());
      } catch {
        /* ignore */
      }
    };
    load();
    const id = setInterval(() => {
      if (!live) load();
    }, 10_000);
    return () => clearInterval(id);
  }, [live]);

  // WebSocket live feed.
  useEffect(() => {
    let ws: WebSocket;
    try {
      ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => setLive(true);
      ws.onclose = () => setLive(false);
      ws.onerror = () => setLive(false);
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "new_case" && msg.case) {
          setCases((prev) => [msg.case as HRCase, ...prev.filter((c) => c.id !== msg.case.id)]);
        }
      };
    } catch {
      setLive(false);
    }
    return () => wsRef.current?.close();
  }, []);

  const filtered = cases.filter(
    (c) =>
      (category === "ALL" || c.category === category) &&
      (status === "ALL" || c.status === status)
  );

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
            live ? "bg-green-500 text-white" : "bg-ink-700/20 text-ink-700"
          }`}
        >
          {live ? "● LIVE" : "○ polling"}
        </span>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-lg border border-brand-purple/15 bg-white px-3 py-1.5 text-sm"
        >
          {CATEGORIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-brand-purple/15 bg-white px-3 py-1.5 text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>

      <div className="overflow-hidden rounded-2xl border border-brand-purple/10 bg-white shadow-sm">
        {filtered.map((c) => (
          <button
            key={c.id}
            onClick={() => setSelected(c)}
            className={`flex w-full items-center gap-4 border-b border-brand-purple/5 px-5 py-3 text-left text-sm last:border-0 hover:bg-brand-cream/50 ${
              selected?.id === c.id ? "bg-brand-cream/60" : ""
            }`}
          >
            <span className="w-28 font-mono text-xs text-ink-700/70">{c.id}</span>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                CATEGORY_COLORS[c.category] ?? "bg-ink-700/15 text-ink-800"
              }`}
            >
              {c.category}
            </span>
            <span className="w-20 text-xs text-ink-700/70">{c.status}</span>
            <span className="w-32 truncate text-xs text-ink-700/70">
              {c.assigned_agent}
            </span>
            <span className="flex-1 truncate">{c.summary}</span>
            <span className="text-xs text-ink-700/50">
              {new Date(c.created_at).toLocaleTimeString()}
            </span>
          </button>
        ))}
        {filtered.length === 0 && (
          <p className="px-5 py-6 text-sm text-ink-700/60">No cases match the filters.</p>
        )}
      </div>

      {selected && (
        <CaseDrawer
          caseRow={selected}
          onClose={() => setSelected(null)}
          onChanged={(c) => {
            setCases((prev) => prev.map((x) => (x.id === c.id ? c : x)));
            setSelected(c);
          }}
        />
      )}
    </div>
  );
}

/** Render an audit row's output as a readable dossier (not raw JSON) for
 *  compliance reviewers, falling back to the raw text for unknown shapes. */
function AuditOutput({ raw }: { raw: string }) {
  let obj: Record<string, unknown> | null = null;
  try {
    obj = JSON.parse(raw);
  } catch {
    obj = null;
  }
  if (!obj || typeof obj !== "object") {
    return (
      <pre className="mt-1 overflow-x-auto rounded-lg bg-brand-cream/50 p-2 text-[11px] leading-snug text-ink-700/80">
        {raw}
      </pre>
    );
  }
  const rows: { label: string; value: string }[] = [];
  const o = obj as Record<string, unknown>;
  if (o.category) rows.push({ label: "Category", value: `${o.category}${o.status ? ` · ${o.status}` : ""}` });
  if (o.rationale) rows.push({ label: "Why", value: String(o.rationale) });
  if (o.recommended_action) rows.push({ label: "Recommended", value: String(o.recommended_action) });
  if (o.decision) rows.push({ label: "Decision", value: String(o.decision) });
  if (o.risk !== undefined) rows.push({ label: "Risk", value: `${Math.round(Number(o.risk) * 100)}%` });
  if (o.score !== undefined) rows.push({ label: "Score", value: `${o.score}${o.recommendation ? ` · ${o.recommendation}` : ""}` });
  if (o.confidence !== undefined) rows.push({ label: "Confidence", value: String(o.confidence) });
  if (Array.isArray(o.source_documents) && o.source_documents.length > 0) {
    const docs = o.source_documents as Array<{ doc_id?: string }>;
    const ids = docs.map((d) => d.doc_id).filter(Boolean).slice(0, 3).join(", ");
    rows.push({ label: "Vector recall", value: `${docs.length} chunk(s)${ids ? ` · ${ids}` : ""}` });
  }
  if (o.retrieval_attempts !== undefined)
    rows.push({ label: "Retrieval attempts", value: `${o.retrieval_attempts} (agentic retry loop)` });
  if (o.mode)
    rows.push({
      label: "Reasoning",
      value: o.mode === "llm" ? "LLM synthesis" : `deterministic (${String(o.mode)})`,
    });
  if (o.rerouted_to) rows.push({ label: "Re-routed to", value: String(o.rerouted_to) });
  if (o.needs_review === true) rows.push({ label: "Flag", value: "Needs human review" });

  // The type-safe classifier's confidence renders as a gauge, not a bare number.
  const classifierConf =
    typeof o.classifier_confidence === "number" ? (o.classifier_confidence as number) : null;

  if (rows.length === 0 && classifierConf === null) {
    return (
      <pre className="mt-1 overflow-x-auto rounded-lg bg-brand-cream/50 p-2 text-[11px] leading-snug text-ink-700/80">
        {raw}
      </pre>
    );
  }
  return (
    <div className="mt-1 space-y-0.5 rounded-lg bg-brand-cream/50 p-2 text-[11px] leading-snug">
      {rows.map((r) => (
        <div key={r.label} className="flex gap-1.5">
          <span className="shrink-0 font-semibold text-brand-purple/80">{r.label}:</span>
          <span className="text-ink-700/80">{r.value}</span>
        </div>
      ))}
      {classifierConf !== null && (
        <div className="pt-1">
          <span className="font-semibold text-brand-purple/80">Classifier confidence</span>
          <div className="mt-1">
            <ConfidenceBar value={classifierConf} />
          </div>
        </div>
      )}
    </div>
  );
}

/** A 0–1 confidence rendered as a coloured gauge (green ≥0.7, amber ≥0.4, red below). */
function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const color = value >= 0.7 ? "bg-green-500" : value >= 0.4 ? "bg-amber-400" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700/10">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="shrink-0 text-xs font-semibold text-ink-700/70">{pct}%</span>
    </div>
  );
}

/** Honest "what produced this answer" chip. LLM synthesis gets an active colour;
 *  every deterministic/fallback mode is neutral grey, so a local excerpt can
 *  never masquerade as premium reasoning. */
function ReasoningModeChip({ mode }: { mode?: string | null }) {
  if (!mode) return null;
  const map: Record<string, { label: string; cls: string }> = {
    llm: { label: "LLM synthesis", cls: "bg-brand-purple/15 text-brand-purple" },
    grounded_excerpt: { label: "Deterministic excerpt", cls: "bg-ink-700/10 text-ink-700/70" },
    no_context: { label: "No matching policy", cls: "bg-ink-700/10 text-ink-700/70" },
    llm_error: { label: "LLM unavailable — excerpt", cls: "bg-ink-700/10 text-ink-700/70" },
  };
  const m = map[mode] ?? { label: mode, cls: "bg-ink-700/10 text-ink-700/70" };
  return (
    <span className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${m.cls}`}>
      {mode === "llm" ? <Sparkles size={11} /> : <Database size={11} />}
      {m.label}
    </span>
  );
}

/** First-class AI recommendation card — the synchronously-computed dossier the
 *  POLICY auto-resolve path attached to the case. Advisory; a human still closes. */
function RecommendationCard({
  text,
  confidence,
  mode,
}: {
  text: string;
  confidence?: number | null;
  mode?: string | null;
}) {
  const lowConf = typeof confidence === "number" && confidence < 0.7;
  return (
    <section className="rounded-xl border border-brand-magenta/20 bg-brand-magenta/5 p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-brand-magenta">
          <Sparkles size={13} /> AI recommendation
        </h3>
        <div className="flex items-center gap-1.5">
          <ReasoningModeChip mode={mode} />
          {lowConf && (
            <span className="flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">
              <AlertTriangle size={11} /> Needs review
            </span>
          )}
        </div>
      </div>
      {typeof confidence === "number" && (
        <div className="mt-2.5">
          <ConfidenceBar value={confidence} />
        </div>
      )}
      <p className="mt-3 whitespace-pre-wrap text-sm text-ink-800">{text}</p>
      <p className="mt-3 text-[11px] italic text-ink-700/55">
        Advisory only — generated at triage from policy documents. A human verifies the
        cited source before closing.
      </p>
    </section>
  );
}

/** One expandable step in the execution trace: header always visible, the
 *  structured metadata inspector revealed on click. */
function ExecutionStep({ row, defaultOpen }: { row: AuditRow; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const dot =
    row.status === "error"
      ? "bg-red-500"
      : row.status === "paused"
        ? "bg-amber-400"
        : "bg-green-500";
  return (
    <li className="relative">
      <span className={`absolute -left-[21px] top-2.5 h-2.5 w-2.5 rounded-full ${dot}`} />
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 rounded-lg px-1 py-1 text-left hover:bg-brand-cream/50"
      >
        <span className="text-sm font-medium text-ink-800">
          {row.agent_name} · {row.action_type}
        </span>
        <span className="flex items-center gap-2">
          <span className="text-xs text-ink-700/50">
            {new Date(row.timestamp).toLocaleTimeString()}
          </span>
          <ChevronDown
            size={14}
            className={`text-ink-700/40 transition-transform ${open ? "rotate-180" : ""}`}
          />
        </span>
      </button>
      {open && <AuditOutput raw={row.output} />}
    </li>
  );
}

/** Slide-over drawer with a case's full ticket and its audit activity trail. */
function CaseDrawer({
  caseRow,
  onClose,
  onChanged,
}: {
  caseRow: HRCase;
  onClose: () => void;
  onChanged: (c: HRCase) => void;
}) {
  const [activity, setActivity] = useState<AuditRow[] | null>(null);
  const [detail, setDetail] = useState<HRCase>(caseRow);
  const [busy, setBusy] = useState(false);
  const [showReroute, setShowReroute] = useState(false);
  const [queue, setQueue] = useState(REROUTE_QUEUES[0].value);
  const toast = useToast();

  const setStatus = async (status: string) => {
    setBusy(true);
    try {
      const updated = await api.updateCaseStatus(detail.id, status);
      setDetail(updated);
      onChanged(updated);
      toast.notify(`Case ${status}`, status === "resolved" ? "success" : "warning");
    } catch (e) {
      toast.notifyError(e);
    } finally {
      setBusy(false);
    }
  };

  const reroute = async () => {
    setBusy(true);
    try {
      const updated = await api.rerouteCase(detail.id, queue);
      setDetail(updated);
      onChanged(updated);
      setShowReroute(false);
      const label = REROUTE_QUEUES.find((q) => q.value === queue)?.label ?? queue;
      toast.notify(`Triage overridden → ${label}`, "warning");
    } catch (e) {
      toast.notifyError(e);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    let mounted = true;
    setActivity(null);
    api
      .caseDetail(caseRow.id)
      .then((d) => {
        if (!mounted) return;
        setDetail(d.case);
        setActivity(d.activity);
      })
      .catch(() => mounted && setActivity([]));
    return () => {
      mounted = false;
    };
  }, [caseRow.id]);

  // Dual-label state: if the case now sits in a human re-route queue, its AI
  // category is the *machine* label and the queue is the *manual* override.
  const overrideQueue = REROUTE_QUEUES.find((q) => q.value === detail.assigned_agent);

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      {/* backdrop */}
      <div
        className="absolute inset-0 bg-ink-900/30 backdrop-blur-sm"
        onClick={onClose}
      />
      {/* panel */}
      <aside className="relative z-50 flex h-full w-full max-w-md flex-col bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b border-brand-purple/10 bg-brand-cream/60 px-6 py-4">
          <div>
            <p className="font-mono text-xs text-ink-700/60">{detail.id}</p>
            <h2 className="mt-1 font-semibold text-brand-purple">
              {detail.summary || "Case detail"}
            </h2>
            <div className="mt-2 flex items-center gap-2">
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                  CATEGORY_COLORS[detail.category] ?? "bg-ink-700/15 text-ink-800"
                }`}
              >
                {detail.category}
              </span>
              <span className="rounded-full bg-brand-purple/10 px-2 py-0.5 text-xs text-brand-purple">
                {detail.status}
              </span>
              {overrideQueue ? (
                <span className="flex items-center gap-1 rounded-full border border-red-300 bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">
                  <ArrowRightLeft size={11} /> Manual → {overrideQueue.label}
                </span>
              ) : (
                <span className="text-xs text-ink-700/60">→ {detail.assigned_agent}</span>
              )}
            </div>
            {overrideQueue && (
              <p className="mt-1.5 text-[11px] text-ink-700/55">
                AI classified <span className="font-semibold">{detail.category}</span>; a human
                re-routed it to <span className="font-semibold">{overrideQueue.label}</span>. The
                machine label is kept for drift tracking.
              </p>
            )}
          </div>
          <button
            aria-label="Close case detail"
            onClick={onClose}
            className="rounded-lg p-1 text-ink-700/50 hover:bg-brand-purple/10 hover:text-brand-purple"
          >
            <X size={18} />
          </button>
        </header>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          {/* AI recommendation (first-class, computed synchronously at triage) */}
          {detail.ai_recommendation && (
            <RecommendationCard
              text={detail.ai_recommendation}
              confidence={detail.ai_confidence}
              mode={detail.ai_mode}
            />
          )}

          {/* Ticket */}
          <section>
            <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-ink-700/60">
              <FileText size={13} /> Ticket
            </h3>
            <p className="mt-2 whitespace-pre-wrap text-sm text-ink-800">
              {detail.detail || detail.summary || "—"}
            </p>
          </section>

          {/* Agent execution trace — expandable, structured metadata inspector
              over the immutable audit rows for this case. */}
          <section>
            <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-ink-700/60">
              <Database size={13} /> Agent execution trace
            </h3>
            {activity === null ? (
              <div className="mt-3 flex items-center gap-2 text-sm text-ink-700/60">
                <Loader2 size={14} className="animate-spin" /> Loading…
              </div>
            ) : activity.length === 0 ? (
              <p className="mt-3 text-sm text-ink-700/60">No recorded activity.</p>
            ) : (
              <ol className="mt-3 space-y-1.5 border-l-2 border-brand-purple/10 pl-4">
                {activity.map((a, i) => (
                  <ExecutionStep key={a.id} row={a} defaultOpen={i === 0} />
                ))}
              </ol>
            )}
          </section>
        </div>

        {/* Split action — resolve, or reject the AI's triage and re-route (analyst+).
            Re-routing keeps misclassifications out of the resolution metrics. */}
        <footer className="border-t border-brand-purple/10 px-6 py-4">
          {detail.status === "resolved" ? (
            <button
              onClick={() => setStatus("open")}
              disabled={busy}
              className="flex items-center gap-1.5 rounded-lg border border-brand-purple/15 px-3 py-2 text-sm font-medium text-ink-800 hover:bg-brand-cream disabled:opacity-50"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <RotateCcw size={15} />}
              Reopen
            </button>
          ) : showReroute ? (
            <div className="flex flex-col gap-2">
              <label className="text-xs font-medium text-ink-700/60">
                Reject AI routing → hand off to:
              </label>
              <div className="flex gap-2">
                <select
                  value={queue}
                  onChange={(e) => setQueue(e.target.value)}
                  className="flex-1 rounded-lg border border-brand-purple/15 bg-white px-3 py-2 text-sm"
                >
                  {REROUTE_QUEUES.map((q) => (
                    <option key={q.value} value={q.value}>
                      {q.label}
                    </option>
                  ))}
                </select>
                <button
                  onClick={reroute}
                  disabled={busy}
                  className="flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
                >
                  {busy ? <Loader2 size={15} className="animate-spin" /> : "Confirm"}
                </button>
                <button
                  onClick={() => setShowReroute(false)}
                  disabled={busy}
                  className="rounded-lg border border-brand-purple/15 px-3 py-2 text-sm text-ink-700 hover:bg-brand-cream disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="flex gap-2">
              <button
                onClick={() => setStatus("resolved")}
                disabled={busy}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-green-600 px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                {busy ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle size={15} />}
                Mark resolved
              </button>
              <button
                onClick={() => setShowReroute(true)}
                disabled={busy}
                title="Reject the AI's triage and send to the right human queue"
                className="flex items-center gap-1.5 rounded-lg border border-red-300 px-3 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                <ArrowRightLeft size={15} />
                Re-route
              </button>
            </div>
          )}
        </footer>
      </aside>
    </div>
  );
}
