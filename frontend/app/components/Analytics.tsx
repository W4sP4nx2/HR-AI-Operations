"use client";

/**
 * Analytics panel — every number here is a **query over the audit log + cases**
 * via `GET /metrics`, never a value an agent stored. KPI cards show the headline
 * counters; the bar chart is real agent activity (audit rows per agent); the
 * donut is the live case-status mix. If the backend is unreachable the panel
 * says so rather than inventing data.
 */

import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import {
  CheckCircle2,
  AlertTriangle,
  Activity,
  Briefcase,
  ScanSearch,
  ThumbsUp,
  Search,
  Loader2,
  Clock3,
  ShieldCheck,
  Network,
  Coins,
} from "lucide-react";
import {
  api,
  type Metrics,
  type FeedbackStat,
  type FireworksBatchStatus,
  type CostControlsCertification,
  type CapabilitySnapshot,
  type CapabilityStatus,
  type BiasAudit,
  type InferenceUsage,
} from "../../lib/api";
import Governance3D from "./Governance3D";

// Humanise the snake_case attrition drivers for display.
const DRIVER_LABELS: Record<string, string> = {
  performance_score: "Performance",
  manager_rating: "Manager rating",
  absence_days: "Absence",
  last_promotion_months: "Time since promotion",
  salary_band: "Salary band",
  tenure_months: "Tenure",
  disengagement_index: "Slow-burn disengagement",
};

const BRAND = {
  purple: "#5D1C6A",
  magenta: "#CA5995",
  peach: "#FFB090",
};

const STATUS_COLORS: Record<string, string> = {
  open: BRAND.peach,
  escalated: BRAND.magenta,
  resolved: BRAND.purple,
};

function StatCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2 text-ink-700/60">
        {icon}
        <span className="text-xs font-medium uppercase">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-semibold text-brand-purple">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-ink-700/50">{sub}</p>}
    </div>
  );
}

export default function Analytics() {
  const [m, setM] = useState<Metrics | null>(null);
  const [feedback, setFeedback] = useState<FeedbackStat[]>([]);
  const [costControls, setCostControls] = useState<CostControlsCertification | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilitySnapshot | null>(null);
  const [biasAudit, setBiasAudit] = useState<BiasAudit | null>(null);
  const [inferenceUsage, setInferenceUsage] = useState<InferenceUsage | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const data = await api.metrics();
        if (!mounted) return;
        setM(data);
        setOffline(false);
      } catch {
        if (mounted) setOffline(true);
      }
      // Load live usage before optional panels so the walkthrough shows the same evidence as Command.
      try {
        const usage = await api.inferenceUsage();
        if (mounted) setInferenceUsage(usage);
      } catch {
        // Keep the last good telemetry snapshot through a transient backend failure.
      }
      // Supporting panels are additive + role-gated; degrade quietly if absent.
      try {
        const fb = await api.feedbackStats();
        if (mounted) setFeedback(fb);
      } catch {
        if (mounted) setFeedback([]);
      }
      try {
        const controls = await api.costControls();
        if (mounted) setCostControls(controls);
      } catch {
        if (mounted) setCostControls(null);
      }
      try {
        const caps = await api.capabilities();
        if (mounted) setCapabilities(caps);
      } catch {
        if (mounted) setCapabilities(null);
      }
      try {
        const audit = await api.biasAudit();
        if (mounted) setBiasAudit(audit);
      } catch {
        if (mounted) setBiasAudit(null);
      }
    };
    load();
    const id = setInterval(load, 10_000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  if (offline && !m) {
    return (
      <div className="rounded-2xl border border-brand-purple/10 bg-white p-10 text-center text-sm text-ink-700/60">
        Metrics unavailable — the backend isn’t reachable.
      </div>
    );
  }
  if (!m) {
    return <div className="p-10 text-center text-sm text-ink-700/50">Loading metrics…</div>;
  }

  const agentActivity = m.actions_by_agent.length
    ? m.actions_by_agent.map((a) => ({ agent: a.agent.replace(/_agent$/, ""), count: a.count }))
    : [{ agent: "—", count: 0 }];
  const statusData = m.cases_by_status.length
    ? m.cases_by_status
    : [{ status: "none", count: 1 }];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={<Activity size={16} />}
          label="Agent Actions"
          value={String(m.agent_actions_total)}
          sub="audited, all-time"
        />
        <StatCard
          icon={<Briefcase size={16} />}
          label="Active Cases"
          value={String(m.active_cases)}
          sub={`${m.cases_total} total`}
        />
        <StatCard
          icon={<CheckCircle2 size={16} />}
          label="Auto-Resolved"
          value={`${Math.round(m.auto_resolution_rate * 100)}%`}
          sub={`${m.resolved_cases} resolved · ${m.resolved_today} today`}
        />
        <StatCard
          icon={<AlertTriangle size={16} />}
          label="Human Escalations"
          value={String(m.escalations)}
          sub={`${Math.round(m.escalation_rate * 100)}% of cases`}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
          <h3 className="mb-1 font-semibold text-brand-purple">Agent Activity</h3>
          <p className="mb-3 text-xs text-ink-700/50">Audited actions per agent</p>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={agentActivity}>
              <XAxis dataKey="agent" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="count" fill={BRAND.magenta} radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
          <h3 className="mb-1 font-semibold text-brand-purple">Case Status Mix</h3>
          <p className="mb-3 text-xs text-ink-700/50">Live distribution from the cases store</p>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={statusData}
                dataKey="count"
                nameKey="status"
                innerRadius={60}
                outerRadius={95}
                paddingAngle={3}
              >
                {statusData.map((s, i) => (
                  <Cell key={i} fill={STATUS_COLORS[s.status] ?? BRAND.peach} />
                ))}
              </Pie>
              <Legend />
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <WhatsWorkingCard stats={feedback} />
      <CapabilityEngineCard snapshot={capabilities} usage={inferenceUsage} />
      <Governance3D
        snapshot={capabilities}
        biasAudit={biasAudit}
        observedProviderResponses={inferenceUsage?.provider_observed.requests ?? 0}
        batchReady={inferenceUsage?.fireworks_batch.ready ?? false}
      />
      <InferenceUsageCard usage={inferenceUsage} />
      <CostControlsCard certification={costControls} />
      <BatchStatusPanel batchConfig={inferenceUsage?.fireworks_batch ?? null} />

      <div className="flex flex-wrap gap-3 text-xs text-ink-700/60">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 shadow-sm">
          <ScanSearch size={13} className="text-brand-magenta" /> {m.resume_screens} resume screens
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 shadow-sm">
          {m.policy_queries} policy queries
        </span>
        {m.injection_blocks > 0 && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 shadow-sm">
            {m.injection_blocks} prompt-injection attempts blocked
          </span>
        )}
        {m.triage_overrides > 0 && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 shadow-sm">
            {Math.round(m.triage_override_rate * 100)}% triage override rate ({m.triage_overrides})
          </span>
        )}
        <span className="ml-auto self-center text-ink-700/40">
          Derived live from the audit log · refreshes every 10s
        </span>
      </div>
    </div>
  );
}

function InferenceUsageCard({ usage }: { usage: InferenceUsage | null }) {
  const tiers = usage
    ? (Object.entries(usage.tiers) as Array<[keyof InferenceUsage["tiers"], InferenceUsage["tiers"][keyof InferenceUsage["tiers"]]]>)
    : [];
  const totalTokens = usage
    ? usage.provider_observed.prompt_tokens + usage.provider_observed.completion_tokens
    : 0;
  const observedProviderResponses = usage?.provider_observed.requests ?? 0;
  const maxSpend = Math.max(0.000001, ...tiers.map(([, row]) => row.total_usd));

  return (
    <section className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-brand-purple">
            <Coins size={16} />
            <h3 className="font-semibold">Token Cost & Serverless Usage</h3>
          </div>
          <p className="mt-0.5 text-xs text-ink-700/50">
            Provider-response tokens are separated from local dollar estimates and billing exports.
          </p>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
            usage?.provider_observed.requests
              ? "bg-green-100 text-green-700"
              : "bg-amber-100 text-amber-700"
          }`}
        >
          {usage?.provider_observed.requests ? "provider tokens observed" : "local estimate only"}
        </span>
      </div>

      {usage ? (
        <>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MiniMetric label="Estimated spend" value={`$${usage.totals.estimated_usd.toFixed(6)}`} />
            <MiniMetric label="Provider responses" value={String(observedProviderResponses)} />
            <MiniMetric label="Provider tokens" value={totalTokens.toLocaleString()} />
            <MiniMetric
              label="Cache / prefilter"
              value={`${rateLabel(usage.cache_hit_rate)} / ${rateLabel(usage.prefilter_skip_rate)}`}
            />
          </div>

          <div className="mt-4 rounded-lg border border-brand-purple/10 bg-brand-cream/50 px-4 py-3 text-xs">
            <p className="font-semibold text-brand-purple">~35% blended cost target</p>
            <p className="mt-1 text-ink-700/60">
              {(usage.blended_cost_scenario.blended_reduction * 100).toFixed(1)}% is illustrative,
              based on the disclosed Batch/cache/retry mix. It is not an achieved saving until a
              Fireworks billing export validates the workload.
            </p>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-3">
            {tiers.map(([tier, row]) => (
              <div key={tier} className="rounded-lg border border-brand-purple/10 px-3 py-3 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold capitalize text-brand-purple">{tier}</span>
                  <span className="rounded-full bg-brand-cream px-2 py-0.5 text-[10px] text-ink-700/60">
                    {row.provider_calls} calls
                  </span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink-700/10">
                  <div
                    className="h-full rounded-full bg-brand-magenta"
                    style={{ width: `${Math.max(4, (row.total_usd / maxSpend) * 100)}%` }}
                  />
                </div>
                <div className="mt-2 flex justify-between text-ink-700/55">
                  <span>${row.total_usd.toFixed(6)}</span>
                  <span>{(row.input_tokens + row.output_tokens).toLocaleString()} tokens</span>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
            <div className="rounded-lg bg-brand-cream/50 px-4 py-3 text-xs">
              <p className="font-semibold text-brand-purple">Fireworks serverless attribution</p>
              <p className="mt-1 text-ink-700/60">
                {usage.fireworks_serverless.configured
                  ? "Provider route is configured for Fireworks."
                  : "Provider route is not currently Fireworks."}
              </p>
              <p className="mt-1 font-mono text-[10px] text-ink-700/45">
                {Object.entries(usage.fireworks_serverless.request_annotations)
                  .map(([key, value]) => `${key}=${value}`)
                  .join(", ")}
              </p>
            </div>
            <div className="rounded-lg bg-brand-cream/50 px-4 py-3 text-xs">
              <p className="font-semibold text-brand-purple">Budget circuit breaker</p>
              <p className={usage.budget_circuit_breaker.active ? "mt-1 text-red-700" : "mt-1 text-ink-700/60"}>
                {usage.budget_circuit_breaker.active
                  ? `Active; routing forced to ${usage.budget_circuit_breaker.forced_tier}.`
                  : "Inactive; spend remains below the configured threshold."}
              </p>
              <p className="mt-1 text-ink-700/45">
                ${usage.budget_circuit_breaker.estimated_spend_usd.toFixed(6)} / $
                {usage.budget_circuit_breaker.daily_threshold_usd.toFixed(2)}
              </p>
            </div>
          </div>

          <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
            {usage.fireworks_serverless.dashboard_note}
          </p>
        </>
      ) : (
        <p className="mt-3 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Inference usage telemetry could not be loaded. The backend may be offline or role-gated.
        </p>
      )}
    </section>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-brand-cream/50 px-4 py-3">
      <p className="text-xs font-medium text-ink-700/55">{label}</p>
      <p className="mt-1 text-lg font-semibold text-brand-purple">{value}</p>
    </div>
  );
}

function rateLabel(rate: number | null) {
  return rate === null ? "n/a" : `${Math.round(rate * 100)}%`;
}

function CapabilityEngineCard({
  snapshot,
  usage,
}: {
  snapshot: CapabilitySnapshot | null;
  usage: InferenceUsage | null;
}) {
  const providers = snapshot?.providers ?? [];
  const routes = snapshot?.routing ?? [];
  const observedProviderResponses = usage?.provider_observed.requests ?? 0;

  return (
    <section className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-brand-purple">
            <Network size={16} />
            <h3 className="font-semibold">Dynamic Capability Engine</h3>
          </div>
          <p className="mt-0.5 text-xs text-ink-700/50">
            Provider and hardware routing based on configured inputs and measured evidence.
          </p>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
            snapshot?.demo_mode ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700"
          }`}
        >
          {snapshot
            ? observedProviderResponses > 0
              ? "BYOK observed"
              : snapshot.demo_mode
                ? "demo mode"
                : "live route"
            : "unavailable"}
        </span>
      </div>

      {snapshot ? (
        <>
          <div className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-3">
            {providers.map((provider) => (
              <div
                key={provider.provider_id}
                className="rounded-lg border border-brand-purple/10 px-3 py-2 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-semibold text-ink-800">
                    {provider.provider_id.replaceAll("_", " ")}
                  </span>
                  <StatusPill status={provider.status} />
                </div>
                <p className="mt-1 text-ink-700/55">{provider.provider_type}</p>
                {provider.models_available.length > 0 && (
                  <p className="mt-1 truncate font-mono text-[10px] text-ink-700/45">
                    {provider.models_available.join(", ")}
                  </p>
                )}
                {provider.missing_inputs.length > 0 && (
                  <p className="mt-1 text-[11px] text-amber-700">
                    Needs: {provider.missing_inputs.slice(0, 2).join(", ")}
                    {provider.missing_inputs.length > 2 ? "…" : ""}
                  </p>
                )}
                {provider.provider_id === "fireworks" && observedProviderResponses > 0 && (
                  <p className="mt-1 text-[11px] text-green-700">
                    User-scoped BYOK: {observedProviderResponses} response{observedProviderResponses === 1 ? "" : "s"} observed.
                  </p>
                )}
                {provider.measurements[0] && (
                  <p className="mt-1 text-[11px] text-green-700">
                    {provider.measurements[0].name}: {provider.measurements[0].value}{" "}
                    {provider.measurements[0].unit}
                  </p>
                )}
                {provider.provider_id === "amd_vllm_gemma" && provider.status !== "proven" && (
                  <p className="mt-1 text-[11px] text-amber-700">
                    Deployment path only: no MI300X/ROCm runtime evidence is connected here.
                  </p>
                )}
              </div>
            ))}
          </div>

          <div className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-3">
            {routes.map((route) => (
              <div key={route.task_type} className="rounded-lg bg-brand-cream/50 px-3 py-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-brand-purple">
                    {route.task_type.replaceAll("_", " ")}
                  </span>
                  <span className="rounded-full bg-white px-2 py-0.5 text-[10px] text-ink-700/60">
                    {route.live_call_allowed ? "live allowed" : "no live call"}
                  </span>
                </div>
                <p className="mt-1 text-ink-700/65">{route.selected_provider}</p>
                <p className="mt-1 line-clamp-2 text-ink-700/45">{route.reason}</p>
              </div>
            ))}
          </div>

          <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
            {snapshot.claim_policy}
          </p>
        </>
      ) : (
        <p className="mt-3 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Capability discovery could not be loaded. The backend may be offline or role-gated.
        </p>
      )}
    </section>
  );
}

function StatusPill({ status }: { status: CapabilityStatus }) {
  const cls: Record<CapabilityStatus, string> = {
    proven: "bg-green-100 text-green-700",
    measured_local: "bg-green-100 text-green-700",
    configured: "bg-blue-100 text-blue-700",
    live_gated: "bg-amber-100 text-amber-700",
    not_configured: "bg-ink-700/10 text-ink-700/60",
    unavailable: "bg-ink-700/10 text-ink-700/60",
  };
  return (
    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${cls[status]}`}>
      {status.replace("_", " ")}
    </span>
  );
}

function CostControlsCard({
  certification,
}: {
  certification: CostControlsCertification | null;
}) {
  const healthy = certification?.ok === true;
  const gates = certification?.gates ?? [];

  return (
    <section className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-brand-purple">
            <ShieldCheck size={16} />
            <h3 className="font-semibold">Cost Controls</h3>
          </div>
          <p className="mt-0.5 text-xs text-ink-700/50">
            Zero-spend certification before any provider call.
          </p>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
            healthy ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"
          }`}
        >
          {certification
            ? `${certification.passed_count}/${certification.gate_count} passed`
            : "unavailable"}
        </span>
      </div>

      {certification ? (
        <>
          <div className="mt-3 grid grid-cols-1 gap-3 text-xs sm:grid-cols-3">
            <div className="rounded-lg bg-brand-cream/50 px-3 py-2">
              <p className="font-semibold text-brand-purple">Provider key</p>
              <p className="text-ink-700/60">
                {certification.provider_key_required ? "required" : "not required"}
              </p>
            </div>
            <div className="rounded-lg bg-brand-cream/50 px-3 py-2">
              <p className="font-semibold text-brand-purple">Network</p>
              <p className="text-ink-700/60">
                {certification.network_required ? "required" : "not required"}
              </p>
            </div>
            <div className="rounded-lg bg-brand-cream/50 px-3 py-2">
              <p className="font-semibold text-brand-purple">Verdict</p>
              <p className={healthy ? "text-green-700" : "text-amber-700"}>
                {healthy ? "certified" : "needs review"}
              </p>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-2">
            {gates.map((gate) => (
              <div
                key={gate.name}
                className="rounded-lg border border-brand-purple/10 px-3 py-2 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-semibold text-ink-800">
                    {gate.name.replaceAll("_", " ")}
                  </span>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 font-semibold ${
                      gate.ok ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                    }`}
                  >
                    {gate.ok ? "pass" : "fail"}
                  </span>
                </div>
                <p className="mt-1 line-clamp-2 text-ink-700/55">{gate.detail}</p>
              </div>
            ))}
          </div>
        </>
      ) : (
        <p className="mt-3 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Cost-control certification could not be loaded. The backend may be offline or the
          lifecycle route may be role-gated.
        </p>
      )}
    </section>
  );
}

function BatchStatusPanel({
  batchConfig,
}: {
  batchConfig: InferenceUsage["fireworks_batch"] | null;
}) {
  const [jobId, setJobId] = useState("");
  const [trackedJobId, setTrackedJobId] = useState("");
  const [status, setStatus] = useState<FireworksBatchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const inspect = async () => {
    const normalized = jobId.trim();
    if (!normalized || busy) return;
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      setStatus(await api.fireworksBatchStatus(normalized));
      setTrackedJobId(normalized);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Batch status unavailable");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!status || status.terminal || !status.poll_after_seconds || !trackedJobId) return;
    const timer = window.setTimeout(() => {
      void api
        .fireworksBatchStatus(trackedJobId)
        .then((next) => {
          setStatus(next);
          setError(null);
        })
        .catch((err: unknown) => {
          setError(err instanceof Error ? err.message : "Batch status unavailable");
        });
    }, status.poll_after_seconds * 1000);
    return () => window.clearTimeout(timer);
  }, [status, trackedJobId]);

  return (
    <section className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2 text-brand-purple">
        <ScanSearch size={16} />
        <h3 className="font-semibold">Fireworks batch status</h3>
      </div>
      <div className={`mt-3 flex items-start gap-3 rounded-lg border px-4 py-3 ${batchConfig?.ready ? "border-blue-200 bg-blue-50" : "border-amber-200 bg-amber-50"}`}>
        <Clock3 size={16} className={`mt-0.5 shrink-0 ${batchConfig?.ready ? "text-blue-700" : "text-amber-700"}`} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${batchConfig?.ready ? "bg-blue-200 text-blue-900" : "bg-amber-200 text-amber-900"}`}>
              {batchConfig?.ready ? "Provider ready" : "Not configured"}
            </span>
            <span className={`text-xs font-medium ${batchConfig?.ready ? "text-blue-900" : "text-amber-900"}`}>
              {status ? `Job ${status.status}` : "No provider job selected"}
            </span>
          </div>
          <p className={`mt-1 text-xs leading-relaxed ${batchConfig?.ready ? "text-blue-900/80" : "text-amber-900/80"}`}>
            {status
              ? status.explanation
              : batchConfig?.ready
                ? "No batch call has been made from this screen. Enter an existing Fireworks job ID to poll its real provider state."
                : `${batchConfig?.detail ?? "Batch readiness is unavailable."} Missing: ${(batchConfig?.issues ?? []).join(", ") || "provider configuration"}. Interactive resume screening remains available.`}
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <label className="sr-only" htmlFor="fireworks-batch-job-id">
          Fireworks Batch job ID
        </label>
        <input
          id="fireworks-batch-job-id"
          value={jobId}
          onChange={(event) => setJobId(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && void inspect()}
          placeholder="resume-demo-001"
          className="min-w-0 flex-1 rounded-lg border border-brand-purple/15 px-3 py-2 text-sm outline-none focus:border-brand-magenta"
        />
        <button
          type="button"
          onClick={() => void inspect()}
          disabled={busy || !jobId.trim() || !batchConfig?.ready}
          className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-brand-purple px-4 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
          Inspect
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      {status && (
        <div className="mt-3 rounded-lg bg-brand-cream/50 px-4 py-3 text-sm">
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-brand-purple px-2.5 py-0.5 text-xs font-semibold text-white">
              {status.label}
            </span>
            <span className="break-all font-mono text-xs text-ink-700/60">{status.job_id}</span>
            {status.progress_percent !== null && (
              <span className="ml-auto text-xs font-medium text-brand-purple">
                {Math.round(status.progress_percent)}%
              </span>
            )}
          </div>
          <p className="mt-2 text-xs leading-relaxed text-ink-700/70">{status.explanation}</p>
          {status.total_requests !== null && (
            <p className="mt-1 text-xs text-ink-700/50">
              {status.processed_requests ?? 0} of {status.total_requests} requests processed
              {status.failed_requests ? ` · ${status.failed_requests} failed` : ""}
            </p>
          )}
          {status.provider_message && (
            <p className="mt-1 text-xs text-ink-700/50">{status.provider_message}</p>
          )}
          {!status.terminal && status.poll_after_seconds && (
            <p className="mt-1 text-[11px] text-ink-700/40">
              Provider state: {status.provider_state} · checking again in{" "}
              {status.poll_after_seconds}s
            </p>
          )}
        </div>
      )}
    </section>
  );
}

/** "What's Working" — human-facing aggregate of manager feedback on retention
 *  suggestions. Advisory: it informs a person; it never steers the agents. */
function WhatsWorkingCard({ stats }: { stats: FeedbackStat[] }) {
  const totalDecisions = stats.reduce((n, s) => n + s.total, 0);
  return (
    <div className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2 text-brand-purple">
        <ThumbsUp size={16} />
        <h3 className="font-semibold">What’s Working</h3>
      </div>
      <p className="mb-3 mt-0.5 text-xs text-ink-700/50">
        How often managers accept each retention suggestion — advisory only; it informs you, it
        never steers the model.
      </p>

      {totalDecisions === 0 ? (
        <p className="rounded-lg bg-brand-cream/50 px-4 py-5 text-center text-sm text-ink-700/55">
          No retention feedback captured yet. Accept or reject suggestions in the Attrition panel to
          populate this.
        </p>
      ) : (
        <ul className="space-y-2.5">
          {stats.map((s) => {
            const pct = Math.round(s.acceptance_rate * 100);
            return (
              <li key={s.risk_driver} className="text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-ink-800">
                    {DRIVER_LABELS[s.risk_driver] ?? s.risk_driver}
                  </span>
                  <span className="text-xs text-ink-700/60">
                    {pct}% accepted{" "}
                    <span className="text-ink-700/40">
                      · {s.accepted}/{s.total}
                      {s.total < 5 ? " (small sample)" : ""}
                    </span>
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-700/10">
                  <div className="h-full bg-brand-magenta" style={{ width: `${pct}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {totalDecisions > 0 && (
        <p className="mt-3 text-[10px] italic text-ink-700/40">
          Based on {totalDecisions} manager decision{totalDecisions === 1 ? "" : "s"} · from the
          append-only feedback ledger.
        </p>
      )}
    </div>
  );
}
