"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleAlert,
  Loader2,
  Network,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import {
  api,
  type HierarchicalCrewEnvelope,
  type HierarchicalCrewManifest,
} from "../../lib/api";
type RunMode = "auto" | "deterministic" | "live";
type GovernedCrewPanelProps = {
  onOpenApprovals: () => void;
};

export default function GovernedCrewPanel({ onOpenApprovals }: GovernedCrewPanelProps) {
  const [manifest, setManifest] = useState<HierarchicalCrewManifest | null>(null);
  const [systemId, setSystemId] = useState("policy_case_resolution");
  const [mode, setMode] = useState<RunMode>("deterministic");
  const [ticket, setTicket] = useState("Urgent safety issue: what policy and escalation path apply?");
  const [policyContext, setPolicyContext] = useState(
    "Safety concerns must be routed to Employee Relations and a human HR manager. Do not auto-resolve urgent cases.",
  );
  const [jobDescription, setJobDescription] = useState("Python Docker Kubernetes engineer");
  const [resume, setResume] = useState("Built Python and Docker services with audited CI pipelines.");
  const [result, setResult] = useState<HierarchicalCrewEnvelope | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let mounted = true;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    const load = async () => {
      try {
        const next = await api.hierarchicalCrews();
        if (!mounted) return;
        setManifest(next);
        setError(null);
      } catch (reason: unknown) {
        if (!mounted) return;
        setError(errorMessage(reason));
        // Local proxies and cold API replicas can become ready just after the
        // Command surface mounts. Retry discovery until it succeeds; the
        // action button remains disabled, so no workflow can run early.
        retryTimer = setTimeout(load, 2_000);
      }
    };
    load();
    return () => {
      mounted = false;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, []);

  const selectedSystem = useMemo(
    () => manifest?.systems.find((system) => system.system_id === systemId) ?? null,
    [manifest, systemId],
  );
  const isResume = systemId === "resume_review";

  const runCrew = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const inputs = isResume
        ? { job_description: jobDescription, resume }
        : { ticket, policy_context: policyContext, policy_version: "endpoint-demo-v1" };
      setResult(await api.runHierarchicalCrew(systemId, inputs, mode));
    } catch (reason: unknown) {
      setError(errorMessage(reason));
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="relative z-10 mb-4 rounded-xl border border-[#00D4FF]/30 bg-[rgba(8,14,28,0.92)] p-5 shadow-[0_20px_70px_rgba(0,212,255,0.09)] backdrop-blur-xl">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-[#00D4FF]">
            <Network size={15} /> Governed CrewAI run
          </div>
          <h3 className="mt-1 text-lg font-semibold text-white">Manager-led evidence, then a real human checkpoint.</h3>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-white/55">
            Inputs arrive as validated API parameters. No agent reads from or writes to GitHub. Live mode uses an allowlisted Fireworks or AMD/vLLM endpoint; deterministic mode proves the same contracts without spend.
          </p>
        </div>
        <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white/65">
          <div className="font-semibold text-white/85">Runtime boundary</div>
          <div>{manifest?.runtime.crewai_importable ? "CrewAI installed" : "CrewAI unavailable"} · {manifest?.context_source?.replaceAll("_", " ") ?? "loading"}</div>
        </div>
      </div>

      <form onSubmit={runCrew} className="mt-4 grid gap-4 xl:grid-cols-[0.9fr_1.35fr]">
        <div className="space-y-3 rounded-lg border border-white/10 bg-black/20 p-4">
          <label className="block text-xs font-semibold text-white/70" htmlFor="crew-system">
            Governed workflow
          </label>
          <select
            id="crew-system"
            value={systemId}
            onChange={(event) => setSystemId(event.target.value)}
            className="min-h-10 w-full rounded-lg border border-white/15 bg-[#0B1325] px-3 text-sm text-white outline-none focus:border-[#00D4FF]"
          >
            {(manifest?.systems ?? []).map((system) => (
              <option key={system.system_id} value={system.system_id}>{system.label}</option>
            ))}
          </select>

          <label className="block text-xs font-semibold text-white/70" htmlFor="crew-mode">
            Execution mode
          </label>
          <select
            id="crew-mode"
            value={mode}
            onChange={(event) => setMode(event.target.value as RunMode)}
            className="min-h-10 w-full rounded-lg border border-white/15 bg-[#0B1325] px-3 text-sm text-white outline-none focus:border-[#00D4FF]"
          >
            <option value="deterministic">Deterministic · zero provider calls</option>
            <option value="auto">Auto · live when configured</option>
            <option value="live">Live · require Fireworks or AMD/vLLM</option>
          </select>

          {selectedSystem && (
            <div className="rounded-lg border border-[#00FF88]/20 bg-[#00FF88]/[0.06] p-3 text-xs text-white/65">
              <div className="font-semibold text-[#D8FFE8]">{selectedSystem.manager_agent.role}</div>
              <div className="mt-1">{selectedSystem.worker_agents.map((worker) => worker.role).join(" + ")}</div>
              <div className="mt-2 text-white/45">{selectedSystem.human_decision_boundary}</div>
            </div>
          )}
        </div>

        <div className="space-y-3 rounded-lg border border-white/10 bg-black/20 p-4">
          {isResume ? (
            <>
              <Field label="Job description" value={jobDescription} onChange={setJobDescription} />
              <Field label="Resume evidence" value={resume} onChange={setResume} rows={4} />
            </>
          ) : (
            <>
              <Field label="HR request" value={ticket} onChange={setTicket} />
              <Field label="Policy context supplied by endpoint" value={policyContext} onChange={setPolicyContext} rows={4} />
            </>
          )}
          <button
            type="submit"
            disabled={running || !manifest}
            className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg border border-[#00D4FF]/40 bg-[#00D4FF]/15 px-4 py-2 text-sm font-semibold text-[#BFF5FF] hover:bg-[#00D4FF]/25 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? <Loader2 size={16} className="animate-spin" /> : <Bot size={16} />}
            {running ? "Running governed crew…" : "Run governed crew"}
          </button>
        </div>
      </form>

      {error && (
        <div role="alert" className="mt-4 flex items-start gap-2 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm text-red-100">
          <CircleAlert size={16} className="mt-0.5 shrink-0" /> {error}
        </div>
      )}

      {result && (
        <div className="mt-4 grid gap-4 xl:grid-cols-[1.3fr_0.7fr]">
          <div className="rounded-lg border border-white/10 bg-black/20 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-white">
                <CheckCircle2 size={16} className="text-[#00FF88]" /> Certified handoff path
              </div>
              <span className="rounded-full border border-[#00D4FF]/25 bg-[#00D4FF]/10 px-2 py-1 text-[11px] text-[#BFF5FF]">
                {result.payload.execution_mode.replaceAll("_", " ")}
              </span>
            </div>
            <div className="mt-3 space-y-2">
              {result.payload.handoffs.map((handoff, index) => (
                <div key={`${handoff.source}-${handoff.target}`} className="flex items-center gap-2 rounded-md bg-white/[0.05] px-3 py-2 text-xs">
                  <span className="font-mono text-white/75">{index + 1}. {handoff.source}</span>
                  <ArrowRight size={13} className="shrink-0 text-[#00D4FF]" />
                  <span className="font-mono text-white/75">{handoff.target}</span>
                  <span className="ml-auto text-right text-white/40">{handoff.status.replaceAll("_", " ")}</span>
                </div>
              ))}
            </div>
            <p className="mt-3 text-sm leading-relaxed text-white/60">{result.payload.summary}</p>
          </div>

          <div className="rounded-lg border border-[#00FF88]/25 bg-[#00FF88]/[0.06] p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-[#D8FFE8]">
              <UserCheck size={16} />
              {result.metadata.human_review_task_id ? "Human review queued" : "No escalation required"}
            </div>
            <div className="mt-3 space-y-2 text-xs text-white/60">
              <ResultRow label="Certification" value={result.certification.is_valid ? "passed" : "failed"} />
              <ResultRow label="Queue state" value={String(result.metadata.hitl_status ?? "not queued").replaceAll("_", " ")} />
              <ResultRow label="Task" value={result.metadata.human_review_task_id ?? "not created"} />
              <ResultRow label="Provider call" value={result.metadata.provider_call ? "yes" : "no"} />
            </div>
            {result.metadata.human_review_task_id && (
              <button
                type="button"
                onClick={onOpenApprovals}
                className="mt-4 inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg border border-[#00FF88]/35 bg-[#00FF88]/10 px-3 py-2 text-xs font-semibold text-[#D8FFE8] hover:bg-[#00FF88]/20"
              >
                <ShieldCheck size={14} /> Open approval checkpoint
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
  rows = 2,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
}) {
  const id = label.toLowerCase().replaceAll(" ", "-");
  return (
    <label className="block text-xs font-semibold text-white/70" htmlFor={id}>
      {label}
      <textarea
        id={id}
        value={value}
        rows={rows}
        required
        maxLength={20_000}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full resize-y rounded-lg border border-white/15 bg-[#0B1325] px-3 py-2 text-sm font-normal text-white outline-none focus:border-[#00D4FF]"
      />
    </label>
  );
}

function ResultRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-black/20 px-3 py-2">
      <span className="text-white/45">{label}</span>
      <span className="font-mono text-white/80">{value}</span>
    </div>
  );
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "The governed crew run failed.";
}
