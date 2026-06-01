"use client";

/**
 * AgentFleet panel.
 *
 * A grid of agent cards. Each card shows the agent's status badge
 * (IDLE/RUNNING/ERROR), last action, last run and run count, and an inline
 * trigger that accepts **typed text, a PDF attachment, or a URL to scrape**.
 *
 * The trigger result is shown inline as one of three states that mirror the
 * backend status contract: Success (ok) · Failed (error) · Unavailable
 * (a capability/dependency is missing). Status is polled every 10 seconds.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Play, Loader2, Paperclip, X, Eye, ArrowRight } from "lucide-react";
import { api, type Agent, type Role, type TriggerStatus, type IntakeSummary } from "../../lib/api";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "./Toast";

// Tiered Fleet: monitoring is read for everyone who can see the panel; *control*
// (triggering agents) is manager+. The backend independently enforces each
// agent's own min_role, so this is UX, not the security boundary itself.
const ROLE_RANK: Record<Role, number> = { viewer: 0, analyst: 1, manager: 2, admin: 3 };

function StatusBadge({ status }: { status: Agent["status"] }) {
  const map: Record<Agent["status"], string> = {
    IDLE: "bg-brand-peach/40 text-ink-800",
    RUNNING: "bg-green-500 text-white animate-pulseGreen",
    ERROR: "bg-red-500 text-white",
  };
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${map[status]}`}>
      {status}
    </span>
  );
}

type Outcome = {
  status: TriggerStatus;
  message: string;
  intake?: IntakeSummary;
};

/** Inline result chip mirroring the ok / error / unavailable status. */
function OutcomeChip({ outcome }: { outcome: Outcome }) {
  const styles: Record<TriggerStatus, string> = {
    ok: "bg-green-50 text-green-700 border-green-200",
    error: "bg-red-50 text-red-700 border-red-200",
    unavailable: "bg-amber-50 text-amber-700 border-amber-200",
  };
  const label: Record<TriggerStatus, string> = {
    ok: "Success",
    error: "Failed",
    unavailable: "Unavailable",
  };
  return (
    <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${styles[outcome.status]}`}>
      <div className="flex items-center justify-between font-semibold">
        <span>{label[outcome.status]}</span>
        {outcome.intake && (
          <span className="font-normal opacity-70">
            {outcome.intake.source_type} · {outcome.intake.chars} chars
          </span>
        )}
      </div>
      <p className="mt-0.5 font-normal leading-snug">{outcome.message}</p>
    </div>
  );
}

/** One-line human summary of an agent result for the success chip. */
function summarise(data: unknown): string {
  const inner =
    data && typeof data === "object" && "result" in (data as Record<string, unknown>)
      ? (data as Record<string, unknown>).result
      : data;
  if (inner && typeof inner === "object") {
    const o = inner as Record<string, unknown>;
    if ("category" in o && o.category) {
      const c = (o.case as Record<string, unknown>) || {};
      return `Triaged as ${o.category} → ${c.status ?? "open"}`;
    }
    if ("recommendation" in o)
      return o.needs_review
        ? `⚠ Needs review — insufficient input`
        : `Score ${o.score} · ${o.recommendation}`;
    if ("attrition_risk_score" in o)
      return `Attrition risk ${Math.round(Number(o.attrition_risk_score) * 100)}%`;
    if ("answer" in o) return String(o.answer).slice(0, 120);
    if ("status" in o && o.status === "paused") return "Paused for human approval";
  }
  return "Completed.";
}

// Agents whose Fleet card hands off instead of showing a chat-style input row:
//  • `panel`    → jump to a purpose-built structured panel (e.g. attrition sliders).
//  • `chatSeed` → open the Chat tab pre-seeded with a template prompt (Policy Q&A
//    is a conversation, not a fire-and-forget trigger).
type Routed = { label: string; panel?: string; chatSeed?: string };
const ROUTED_AGENTS: Record<string, Routed> = {
  attrition_agent: { label: "Open Attrition panel", panel: "attrition" },
  policy_qa_agent: {
    label: "Open Conversation",
    chatSeed: "What is our policy on parental leave?",
  },
};

export default function AgentFleet({
  onOpenPanel,
  onOpenChat,
}: {
  onOpenPanel?: (panel: string) => void;
  onOpenChat?: (seed: string) => void;
}) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
  const fileRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const toast = useToast();
  const { user } = useAuth();
  const canControl = ROLE_RANK[(user?.role as Role) ?? "viewer"] >= ROLE_RANK.manager;

  const load = useCallback(async () => {
    try {
      setAgents(await api.agents());
    } catch {
      /* keep last known state on transient errors */
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, [load]);

  const trigger = async (name: string) => {
    setBusy((b) => ({ ...b, [name]: true }));
    setOutcomes((o) => {
      const next = { ...o };
      delete next[name];
      return next;
    });
    try {
      const raw = (inputs[name] ?? "").trim();
      const isUrl = /^https?:\/\//i.test(raw);
      const env = await api.triggerUpload(name, {
        file: files[name] ?? undefined,
        url: isUrl ? raw : undefined,
        text: !isUrl && raw ? raw : undefined,
      });
      const status: TriggerStatus = env.status ?? (env.success ? "ok" : "error");
      const intake = (env.data as { intake?: IntakeSummary } | null)?.intake;
      const message =
        status === "ok"
          ? summarise(env.data)
          : env.error ?? "Something went wrong.";
      setOutcomes((o) => ({ ...o, [name]: { status, message, intake } }));
      if (status === "unavailable") toast.notify(message, "warning");
      await load();
    } catch (e) {
      setOutcomes((o) => ({
        ...o,
        [name]: { status: "error", message: (e as Error).message },
      }));
      toast.notifyError(e);
    } finally {
      setBusy((b) => ({ ...b, [name]: false }));
    }
  };

  return (
    <div className="space-y-4">
      {!canControl && (
        <div className="flex items-center gap-2 rounded-xl border border-brand-purple/15 bg-brand-cream/50 px-4 py-2.5 text-sm text-ink-700/70">
          <Eye size={15} className="text-brand-purple" />
          Read-only monitoring — agent health, last action and run counts. Triggering
          agents requires the <strong className="mx-1 font-semibold">HR Manager</strong> role.
        </div>
      )}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
      {agents.map((agent) => {
        const file = files[agent.name];
        return (
          <div
            key={agent.name}
            className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm"
          >
            <div className="flex items-start justify-between">
              <div>
                <h3 className="font-semibold text-brand-purple">{agent.label}</h3>
                <p className="text-xs text-ink-700/60">{agent.framework}</p>
              </div>
              <StatusBadge status={agent.status} />
            </div>

            <dl className="mt-4 space-y-1 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-700/60">Last action</dt>
                <dd className="max-w-[55%] truncate text-right">
                  {agent.last_action ?? "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-700/60">Last run</dt>
                <dd>
                  {agent.last_run
                    ? new Date(agent.last_run).toLocaleTimeString()
                    : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-700/60">Total runs</dt>
                <dd className="font-medium">{agent.total_runs}</dd>
              </div>
            </dl>

            {/* Control surface — manager+ only. Read-only roles see status above. */}
            {canControl && ROUTED_AGENTS[agent.name] ? (
              // A chat box is the wrong control for this agent — hand off instead:
              // structured agents → their panel; Policy Q&A → a seeded conversation.
              <button
                onClick={() => {
                  const cfg = ROUTED_AGENTS[agent.name];
                  if (cfg.panel) onOpenPanel?.(cfg.panel);
                  else if (cfg.chatSeed !== undefined) onOpenChat?.(cfg.chatSeed);
                }}
                className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-lg border border-brand-purple/20 px-3 py-2 text-sm font-medium text-brand-purple transition hover:border-brand-magenta hover:bg-brand-cream/50"
              >
                {ROUTED_AGENTS[agent.name].label}
                <ArrowRight size={15} />
              </button>
            ) : canControl ? (
              <>
                <div className="mt-4 flex gap-2">
                  <input
                    value={inputs[agent.name] ?? ""}
                    onChange={(e) =>
                      setInputs((i) => ({ ...i, [agent.name]: e.target.value }))
                    }
                    placeholder="Type text or paste a URL…"
                    className="flex-1 rounded-lg border border-brand-purple/15 px-3 py-1.5 text-sm outline-none focus:border-brand-magenta"
                  />
                  {/* PDF attach */}
                  <input
                    ref={(el) => {
                      fileRefs.current[agent.name] = el;
                    }}
                    type="file"
                    accept="application/pdf"
                    className="hidden"
                    onChange={(e) =>
                      setFiles((f) => ({
                        ...f,
                        [agent.name]: e.target.files?.[0] ?? null,
                      }))
                    }
                  />
                  <button
                    title="Attach a PDF"
                    aria-label={`Attach a PDF for ${agent.label}`}
                    onClick={() => fileRefs.current[agent.name]?.click()}
                    className={`rounded-lg border px-2 py-1.5 transition ${
                      file
                        ? "border-brand-magenta text-brand-magenta"
                        : "border-brand-purple/15 text-ink-700/60 hover:border-brand-magenta"
                    }`}
                  >
                    <Paperclip size={15} />
                  </button>
                  <button
                    onClick={() => trigger(agent.name)}
                    disabled={busy[agent.name]}
                    className="flex items-center gap-1 rounded-lg bg-brand-magenta px-3 py-1.5 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-50"
                  >
                    {busy[agent.name] ? (
                      <Loader2 size={15} className="animate-spin" />
                    ) : (
                      <Play size={15} />
                    )}
                    Trigger
                  </button>
                </div>

                {/* Selected file chip */}
                {file && (
                  <div className="mt-2 flex items-center gap-1.5 text-xs text-ink-700/70">
                    <Paperclip size={12} />
                    <span className="max-w-[70%] truncate">{file.name}</span>
                    <button
                      onClick={() =>
                        setFiles((f) => ({ ...f, [agent.name]: null }))
                      }
                      className="text-ink-700/50 hover:text-red-500"
                    >
                      <X size={13} />
                    </button>
                  </div>
                )}

                {outcomes[agent.name] && <OutcomeChip outcome={outcomes[agent.name]} />}
              </>
            ) : (
              <p className="mt-4 flex items-center gap-1.5 text-xs text-ink-700/45">
                <Eye size={12} /> Monitoring only
              </p>
            )}
          </div>
        );
      })}
      {agents.length === 0 && (
        <p className="text-sm text-ink-700/60">No agents reporting yet…</p>
      )}
      </div>
    </div>
  );
}
