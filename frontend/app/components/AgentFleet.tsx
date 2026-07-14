"use client";

/**
 * Enterprise command-center view.
 *
 * This replaces generic agent status cards with a visual operations surface:
 * hybrid routing topology, deterministic cost-arbitrage benchmark, Four-Fifths
 * bias radar, and live workflow telemetry. Provider/GPU paths remain honest:
 * when Fireworks or AMD evidence is missing, the UI renders them as gated.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CheckSquare,
  ClipboardList,
  Cpu,
  Gauge,
  GitBranch,
  ShieldCheck,
  Zap,
} from "lucide-react";
import {
  api,
  type BiasAudit,
  type BiasAuditDimension,
  type CapabilitySnapshot,
  type HRCase,
  type InferenceUsage,
  type Metrics,
  type OpsOverview,
  type PendingTask,
} from "../../lib/api";
import GovernedCrewPanel from "./GovernedCrewPanel";

const NEON = {
  amd: "#ED1C24",
  fireworks: "#00D4FF",
  compliance: "#00FF88",
  amber: "#FFB020",
  red: "#FF4444",
  ink: "#050813",
  panel: "rgba(8, 14, 28, 0.72)",
};

type AgentFleetProps = {
  onOpenCase: (caseId: string) => void;
  onOpenCases: () => void;
  onOpenApprovals: () => void;
  onOpenAudit: () => void;
};

export default function AgentFleet({ onOpenCase, onOpenCases, onOpenApprovals, onOpenAudit }: AgentFleetProps) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilitySnapshot | null>(null);
  const [usage, setUsage] = useState<InferenceUsage | null>(null);
  const [biasAudit, setBiasAudit] = useState<BiasAudit | null>(null);
  const [cases, setCases] = useState<HRCase[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<PendingTask[]>([]);
  const [ops, setOps] = useState<OpsOverview | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      const [nextMetrics, nextCapabilities, nextUsage, nextBias, nextCases, nextApprovals, nextOps] = await Promise.allSettled([
        api.metrics(),
        api.capabilities(),
        api.inferenceUsage(),
        api.biasAudit(),
        api.cases(),
        api.pendingApprovals(),
        api.opsOverview(),
      ]);
      if (!mounted) return;
      let loaded = false;
      if (nextMetrics.status === "fulfilled") {
        setMetrics(nextMetrics.value);
        loaded = true;
      }
      if (nextCapabilities.status === "fulfilled") {
        setCapabilities(nextCapabilities.value);
        loaded = true;
      }
      if (nextUsage.status === "fulfilled") {
        setUsage(nextUsage.value);
        loaded = true;
      }
      if (nextBias.status === "fulfilled") {
        setBiasAudit(nextBias.value);
        loaded = true;
      }
      if (nextCases.status === "fulfilled") {
        setCases(nextCases.value);
        loaded = true;
      }
      if (nextApprovals.status === "fulfilled") {
        setPendingApprovals(nextApprovals.value);
        loaded = true;
      }
      if (nextOps.status === "fulfilled") {
        setOps(nextOps.value);
        loaded = true;
      }
      setOffline(!loaded);
    };
    load();
    const id = window.setInterval(load, 10_000);
    return () => {
      mounted = false;
      window.clearInterval(id);
    };
  }, []);

  const benchmark = usage?.cost_benchmark ?? null;
  const savingsPct = benchmark?.cost_reduction ? benchmark.cost_reduction * 100 : 0;
  const fireworkProvider = capabilities?.providers.find((p) => p.provider_id === "fireworks");
  const amdProvider = capabilities?.providers.find((p) => p.provider_id === "amd_vllm_gemma");
  const amdHardware = capabilities?.hardware.find((h) => h.vendor === "amd");
  const observedProviderCalls = usage?.provider_observed.requests ?? 0;
  const observedProviderTokens = (usage?.provider_observed.prompt_tokens ?? 0) + (usage?.provider_observed.completion_tokens ?? 0);
  const observedFireworksModels = Object.entries(usage?.provider_observed.models ?? {});
  const observedFireworksModel = observedFireworksModels.sort(([, left], [, right]) => right.requests - left.requests)[0]?.[0] ?? null;
  const fireworksObservedLive = observedProviderCalls > 0;
  const batchConfig = usage?.fireworks_batch ?? null;
  const batchReady = batchConfig?.ready ?? false;
  const batchIssues = batchConfig?.issues ?? [];
  const dimensions = biasAudit?.dimensions?.length
    ? biasAudit.dimensions
    : fallbackBiasDimensions();
  const worstDimension = dimensions.reduce((worst, current) =>
    current.adverse_impact_ratio < worst.adverse_impact_ratio ? current : worst
  );
  const priorityCases = [...cases]
    .filter((caseRow) => caseRow.status === "escalated" || caseRow.status === "open")
    .sort((left, right) => caseRank(left) - caseRank(right))
    .slice(0, 3);
  const urgentCases = cases.filter((caseRow) => caseRow.category === "URGENT" && caseRow.status !== "resolved").length;
  const openCases = cases.filter((caseRow) => caseRow.status !== "resolved").length;
  const needsHumanReview = priorityCases.length + pendingApprovals.length;

  return (
    <div className="-m-4 min-h-full overflow-hidden bg-[#050813] p-4 text-white sm:-m-6 sm:p-6 lg:-m-8 lg:p-8">
      <div className="pointer-events-none fixed inset-0 -z-0 bg-[linear-gradient(rgba(0,212,255,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(0,212,255,0.08)_1px,transparent_1px)] bg-[size:40px_40px]" />
      <div className="pointer-events-none fixed inset-0 -z-0 bg-[radial-gradient(circle_at_18%_12%,rgba(237,28,36,0.22),transparent_28%),radial-gradient(circle_at_76%_18%,rgba(0,212,255,0.18),transparent_30%),radial-gradient(circle_at_54%_82%,rgba(0,255,136,0.12),transparent_34%)]" />

      <header className="relative z-10 mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.28em] text-[#00D4FF]">
            <Activity size={15} />
            HR Operations Command
          </div>
          <h2 className="mt-2 text-2xl font-semibold text-white sm:text-3xl">
            Make the next HR decision clear.
          </h2>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-white/58">
            Start with the cases and approvals that need a person. The system evidence below
            explains what the assistant did; it does not replace an HR decision.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3 lg:grid-cols-6">
          <StatusTile label="Needs review" value={String(needsHumanReview)} tone={needsHumanReview ? "red" : "green"} />
          <StatusTile label="Urgent cases" value={String(urgentCases)} tone={urgentCases ? "red" : "green"} />
          <StatusTile label="Pending approvals" value={String(pendingApprovals.length)} tone={pendingApprovals.length ? "red" : "green"} />
          <StatusTile label="Open cases" value={String(openCases)} tone={openCases ? "blue" : "green"} />
          <StatusTile label="Resolved today" value={String(metrics?.resolved_today ?? 0)} tone="green" />
          <StatusTile label="Live assistant" value={fireworksObservedLive ? "verified" : "not used"} tone={fireworksObservedLive ? "green" : "blue"} />
        </div>
      </header>

      {offline && (
        <div className="relative z-10 mb-4 rounded-lg border border-amber-300/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          Backend telemetry is temporarily unavailable. The command surface will refresh every 10s.
        </div>
      )}

      <ActionQueue
        priorityCases={priorityCases}
        pendingApprovals={pendingApprovals}
        onOpenCase={onOpenCase}
        onOpenCases={onOpenCases}
        onOpenApprovals={onOpenApprovals}
        onOpenAudit={onOpenAudit}
        observedModel={observedFireworksModel}
        observedCalls={observedProviderCalls}
      />

      <LiveOperationalMap snapshot={ops} />

      <GovernedCrewPanel onOpenApprovals={onOpenApprovals} />

      <details className="relative z-10 rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white">
        <summary className="cursor-pointer list-none text-sm font-semibold text-white/75 marker:content-none">
          <span className="inline-flex items-center gap-2">
            <Gauge size={15} className="text-[#00D4FF]" /> System evidence (optional)
          </span>
          <span className="ml-2 text-xs font-normal text-white/40">Open only when a reviewer asks how a decision was supported.</span>
        </summary>
        <div className="mt-4">
      <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <GlassPanel
          title="Assistant operating context"
          eyebrow="evidence only — not an HR action"
          icon={<GitBranch size={16} />}
          className="min-h-[440px]"
        >
          <RoutingTopologyScene
            fireworksLive={fireworksObservedLive || fireworkProvider?.live_enabled === true}
            amdLive={amdProvider?.live_enabled ?? false}
          />
          <PanelLegend
            items={[
              {
                label: "AMD MI300X",
                value: amdProvider?.live_enabled ? "live route" : "runtime gated",
                color: NEON.amd,
              },
              {
                label: "Fireworks Cloud",
                value: fireworksObservedLive ? "BYOK response observed" : fireworkProvider?.live_enabled ? "live route" : "credential gated",
                color: NEON.fireworks,
              },
              { label: "Cache ring", value: "local measured", color: NEON.compliance },
            ]}
          />
        </GlassPanel>

        <GlassPanel
          title="Cost guardrails"
          eyebrow="benchmark, not realized savings"
          icon={<BarChart3 size={16} />}
          className="min-h-[440px]"
        >
          <CostWaterfallScene usage={usage} />
          <div className="absolute bottom-5 left-5 right-5 grid grid-cols-3 gap-2 text-xs">
            <MetricPill
              label="Savings"
              value={benchmark ? `${savingsPct.toFixed(1)}% benchmark` : "n/a"}
              tone="green"
            />
            <MetricPill
              label="Naive"
              value={benchmark ? dollars(benchmark.uncontrolled.estimated_usd) : "n/a"}
              tone="red"
            />
            <MetricPill
              label="Optimized"
              value={benchmark ? dollars(benchmark.controlled.estimated_usd) : "n/a"}
              tone="green"
            />
          </div>
        </GlassPanel>

        <GlassPanel
          title="Fairness watch"
          eyebrow="review alert, not a decision"
          icon={<ShieldCheck size={16} />}
          className="min-h-[440px]"
        >
          <BiasAuditRadarScene dimensions={dimensions} />
          <div className="absolute bottom-5 left-5 right-5 space-y-2 text-xs">
            <div
              className={`rounded-lg border px-3 py-2 ${
                worstDimension.violates_four_fifths_rule
                  ? "border-red-400/40 bg-red-500/16 text-red-100"
                  : "border-[#00FF88]/35 bg-[#00FF88]/10 text-[#D7FFE9]"
              }`}
            >
              {worstDimension.violates_four_fifths_rule ? "VIOLATION DETECTED" : "COMPLIANT"} ·{" "}
              {worstDimension.dimension} ratio {worstDimension.adverse_impact_ratio.toFixed(2)}
            </div>
            <MetricPill
              label="ATS records"
              value={biasAudit?.available ? biasAudit.record_count.toLocaleString() : "fixture"}
              tone="blue"
            />
          </div>
        </GlassPanel>
      </section>

      <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr_1.6fr]">
        <GlassPanel title="Service evidence" eyebrow="live assistant telemetry" icon={<Gauge size={16} />}>
          <div className="grid grid-cols-2 gap-3">
            <MetricCard
              label="Provider calls"
              value={String(observedProviderCalls)}
              sub={fireworksObservedLive ? "provider responses observed" : "no live calls"}
              accent={NEON.fireworks}
            />
            <MetricCard
              label="Observed tokens"
              value={String(observedProviderTokens)}
              sub={fireworksObservedLive ? "provider response usage" : "application ledger"}
              accent={NEON.compliance}
            />
            <MetricCard
              label="Cache hit rate"
              value={rateLabel(usage?.cache_hit_rate ?? null)}
              sub="semantic cache"
              accent={NEON.compliance}
            />
            <MetricCard
              label="Estimated spend"
              value={dollars(usage?.totals.estimated_usd ?? 0)}
              sub={usage?.fireworks_serverless.billing_export_ready ? "billing export ready" : "local estimate"}
              accent={NEON.amd}
            />
          </div>
          <div className="mt-4 grid grid-cols-3 gap-3">
            <GpuStat label="Utilization" value={amdHardware && amdHardware.status !== "unavailable" ? "evidence" : "gated"} color={NEON.amd} />
            <GpuStat label="Memory" value={amdHardware?.device_names[0] ? "reported" : "gated"} color={NEON.amd} />
            <GpuStat label="Thermals" value="not claimed" color={NEON.compliance} />
          </div>
        </GlassPanel>

        <GlassPanel title="Capacity & controls" eyebrow="operating context" icon={<Zap size={16} />}>
          <div className="space-y-3">
            <WorkflowRow
              name="Interactive resume screens"
              detail={`${metrics?.resume_screens ?? 0} audited screens · text/PDF review`}
              progress={workflowProgress(metrics?.resume_screens ?? 0, 50)}
              color={NEON.fireworks}
              value={`${metrics?.resume_screens ?? 0} screens`}
            />
            <WorkflowRow
              name="Fireworks Batch"
              detail={batchReady
                ? "Control plane ready · no provider job submitted"
                : `Not configured · ${batchIssues.join(", ") || "control-plane credentials required"}`}
              progress={batchReady ? 1 : 0}
              color={batchReady ? NEON.compliance : NEON.amber}
              value={batchReady ? "Ready" : "Not configured"}
            />
            <WorkflowRow
              name="Policy Q&A"
              detail={`${metrics?.policy_queries ?? 0} policy queries · semantic cache protected`}
              progress={workflowProgress(metrics?.policy_queries ?? 0, 20)}
              color={NEON.compliance}
              value={`${metrics?.policy_queries ?? 0} queries`}
            />
            <WorkflowRow
              name="Cost Controls"
              detail={benchmark
                ? `${benchmark.controlled.provider_calls} controlled calls vs ${benchmark.uncontrolled.provider_calls} naive`
                : "Awaiting cost telemetry from the backend ledger"}
              progress={benchmark?.cost_reduction ?? 0}
              color={NEON.compliance}
              value={benchmark ? `${savingsPct.toFixed(1)}% benchmark` : "n/a"}
            />
            <WorkflowRow
              name="Bias Audit"
              detail={biasAudit?.headline ?? "Synthetic Four-Fifths audit fixture"}
              progress={Math.min(1, worstDimension.adverse_impact_ratio / 0.8)}
              color={worstDimension.violates_four_fifths_rule ? NEON.red : NEON.compliance}
              value={`${worstDimension.adverse_impact_ratio.toFixed(2)} AIR`}
            />
            <WorkflowRow
              name="Active Cases"
              detail={`${metrics?.resolved_cases ?? 0} resolved · ${metrics?.escalations ?? 0} escalated`}
              progress={metrics?.auto_resolution_rate ?? 0}
              color={NEON.fireworks}
              value={`${Math.round((metrics?.auto_resolution_rate ?? 0) * 100)}% auto`}
            />
          </div>
        </GlassPanel>
      </section>
        </div>
      </details>
    </div>
  );
}

function LiveOperationalMap({ snapshot }: { snapshot: OpsOverview | null }) {
  const nodes = snapshot?.agents ?? [];
  const pending = snapshot?.queues.human_review.pending ?? 0;
  const resumeState = snapshot?.queues.resume.state ?? "unknown";
  return (
    <section className="relative z-10 mb-4 overflow-hidden rounded-xl border border-[#00D4FF]/25 bg-[rgba(8,14,28,0.88)] p-5 shadow-[0_20px_70px_rgba(0,212,255,0.08)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-[#00D4FF]">
            <GitBranch size={15} /> Live workflow state
          </div>
          <h3 className="mt-1 text-lg font-semibold text-white">Agents, gates, and work queues</h3>
          <p className="mt-1 max-w-2xl text-sm text-white/55">
            This map is a projection of the operational snapshot, not a decorative health claim.
            Data freshness: {snapshot ? `${snapshot.fresh_for_seconds}s window` : "unavailable"}.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
          <StatusTile label="Provenance" value={snapshot?.provenance === "live_runtime" ? "live" : "demo"} tone={snapshot?.provenance === "live_runtime" ? "green" : "blue"} />
          <StatusTile label="Human gate" value={pending ? `${pending} pending` : "clear"} tone={pending ? "red" : "green"} />
          <StatusTile label="Resume queue" value={resumeState} tone="blue" />
        </div>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[1.35fr_1fr]">
        <div className="relative h-[280px] overflow-hidden rounded-lg border border-white/10 bg-[#050813]" aria-label="Three-dimensional workflow map">
          {snapshot ? <LiveOpsScene snapshot={snapshot} /> : <div className="flex h-full items-center justify-center text-sm text-white/45">Operational snapshot unavailable.</div>}
        </div>
        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-white/45">Accessible state table</div>
          <div className="space-y-2" role="table" aria-label="Agent operational state">
            {nodes.length ? nodes.map((agent) => (
              <div key={agent.name} className="flex items-center justify-between gap-3 rounded-md bg-white/[0.06] px-3 py-2 text-xs" role="row">
                <span className="min-w-0 truncate text-white/80">{agent.name.replace(/_agent$/, "")}</span>
                <span className={`shrink-0 rounded-full px-2 py-0.5 font-semibold ${statusClass(agent.status)}`}>{agent.status}</span>
              </div>
            )) : <p className="text-sm text-white/45">No agent state available.</p>}
          </div>
        </div>
      </div>
    </section>
  );
}

function LiveOpsScene({ snapshot }: { snapshot: OpsOverview }) {
  const nodes = snapshot.agents.slice(0, 6);
  const positions = nodes.map((_, index) => {
    const angle = (index / Math.max(nodes.length, 1)) * Math.PI * 2 - Math.PI / 2;
    return [Math.cos(angle) * 2.1, Math.sin(angle) * 0.9, Math.sin(angle) * 0.35] as [number, number, number];
  });
  const byName = new Map(nodes.map((node, index) => [node.name, positions[index]]));
  return (
    <Canvas camera={{ position: [0, 0.25, 6], fov: 44 }} dpr={[1, 1.5]}>
      <color attach="background" args={[NEON.ink]} />
      <ambientLight intensity={0.38} />
      <pointLight position={[0, 2, 3]} intensity={18} color={NEON.fireworks} />
      <group>
        <NodeSphere position={[0, 0, 0]} radius={0.34} color={NEON.compliance} intensity={1.6} />
        {snapshot.workflow_edges.map((edge) => {
          const start = byName.get(edge.source);
          const end = byName.get(edge.target);
          if (!start || !end) return null;
          return <CylinderBeam key={`${edge.source}-${edge.target}`} start={start} end={end} color={NEON.fireworks} opacity={0.32} radius={0.012} />;
        })}
        {nodes.map((node, index) => (
          <NodeSphere key={node.name} position={positions[index]} radius={0.18} color={statusColor(node.status)} intensity={node.status === "RUNNING" ? 2.2 : 1.1} />
        ))}
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[2.35, 0.012, 12, 96]} />
          <meshBasicMaterial color={NEON.compliance} transparent opacity={0.24} />
        </mesh>
      </group>
    </Canvas>
  );
}

function statusColor(status: string) {
  if (status === "ERROR") return NEON.red;
  if (status === "RUNNING") return NEON.fireworks;
  if (status === "PAUSED" || status === "BLOCKED") return NEON.amber;
  return NEON.compliance;
}

function statusClass(status: string) {
  if (status === "ERROR") return "bg-red-500/20 text-red-200";
  if (status === "RUNNING") return "bg-cyan-400/20 text-cyan-100";
  if (status === "PAUSED" || status === "BLOCKED") return "bg-amber-400/20 text-amber-100";
  return "bg-emerald-400/20 text-emerald-100";
}

function ActionQueue({
  priorityCases,
  pendingApprovals,
  onOpenCase,
  onOpenCases,
  onOpenApprovals,
  onOpenAudit,
  observedModel,
  observedCalls,
}: {
  priorityCases: HRCase[];
  pendingApprovals: PendingTask[];
  onOpenCase: (caseId: string) => void;
  onOpenCases: () => void;
  onOpenApprovals: () => void;
  onOpenAudit: () => void;
  observedModel: string | null;
  observedCalls: number;
}) {
  const hasWork = priorityCases.length > 0 || pendingApprovals.length > 0;
  return (
    <section className="relative z-10 mb-4 rounded-xl border border-[#00FF88]/30 bg-[rgba(8,14,28,0.9)] p-5 shadow-[0_20px_70px_rgba(0,255,136,0.1)] backdrop-blur-xl">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-[#00FF88]">
            <ClipboardList size={15} /> Start with human work
          </div>
          <h3 className="mt-1 text-lg font-semibold text-white">
            {hasWork ? "These decisions need attention now." : "The review queue is clear."}
          </h3>
          <p className="mt-1 max-w-2xl text-sm text-white/55">
            Review the case context, make the HR decision, and keep the evidence attached. The assistant can recommend and route; it cannot close the loop for you.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={onOpenCases} className="inline-flex items-center gap-1.5 rounded-lg border border-[#00D4FF]/35 bg-[#00D4FF]/10 px-3 py-2 text-xs font-semibold text-[#BFF5FF] hover:bg-[#00D4FF]/20">
            Review cases <ArrowRight size={13} />
          </button>
          <button type="button" onClick={onOpenApprovals} className="inline-flex items-center gap-1.5 rounded-lg border border-[#00FF88]/35 bg-[#00FF88]/10 px-3 py-2 text-xs font-semibold text-[#D8FFE8] hover:bg-[#00FF88]/20">
            Review approvals <CheckSquare size={13} />
          </button>
        </div>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-white/45">
            <AlertTriangle size={13} className="text-[#FFB020]" /> Priority cases
          </div>
          <div className="mt-2 space-y-2">
            {priorityCases.length ? priorityCases.map((caseRow) => (
              <button key={caseRow.id} type="button" onClick={() => onOpenCase(caseRow.id)} className="flex w-full items-center justify-between gap-3 rounded-md bg-white/[0.06] px-3 py-2 text-left hover:bg-white/[0.1]">
                <span className="min-w-0">
                  <span className="block font-mono text-[11px] text-[#BFF5FF]">{caseRow.id} · {caseRow.category}</span>
                  <span className="mt-0.5 block truncate text-xs text-white/70">{caseRow.summary}</span>
                </span>
                <span className="shrink-0 text-[11px] font-semibold text-[#FFB020]">Review</span>
              </button>
            )) : <p className="text-sm text-white/50">No open or escalated cases are waiting.</p>}
          </div>
        </div>
        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-white/45">
            <CheckSquare size={13} className="text-[#00FF88]" /> Approval checkpoints
          </div>
          <div className="mt-2 space-y-2">
            {pendingApprovals.length ? pendingApprovals.slice(0, 3).map((approval) => (
              <button key={approval.id} type="button" onClick={onOpenApprovals} className="flex w-full items-center justify-between gap-3 rounded-md bg-white/[0.06] px-3 py-2 text-left hover:bg-white/[0.1]">
                <span className="min-w-0">
                  <span className="block text-xs font-semibold text-white/85">{approval.step}</span>
                  <span className="mt-0.5 block truncate text-[11px] text-white/55">{approval.context || approval.agent_name}</span>
                </span>
                <span className="shrink-0 text-[11px] font-semibold text-[#00FF88]">Decide</span>
              </button>
            )) : <p className="text-sm text-white/50">No approval is blocking work right now.</p>}
          </div>
        </div>
      </div>
      {observedModel && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#00D4FF]/25 bg-[#00D4FF]/10 px-3 py-2 text-xs text-[#BFF5FF]">
          <span>Assistant evidence: {observedCalls} live provider response{observedCalls === 1 ? "" : "s"} from {shortModel(observedModel)}. Use Audit to verify a specific decision.</span>
          <button type="button" onClick={onOpenAudit} className="inline-flex items-center gap-1 font-semibold hover:text-white">Open audit <ArrowRight size={12} /></button>
        </div>
      )}
    </section>
  );
}

function caseRank(caseRow: HRCase) {
  if (caseRow.category === "URGENT" && caseRow.status === "escalated") return 0;
  if (caseRow.status === "escalated") return 1;
  if (caseRow.category === "URGENT") return 2;
  return 3;
}

function RoutingTopologyScene({
  fireworksLive,
  amdLive,
}: {
  fireworksLive: boolean;
  amdLive: boolean;
}) {
  return (
    <div className="absolute inset-0">
      <Canvas camera={{ position: [0, 1.15, 7.2], fov: 44 }} dpr={[1, 1.7]}>
        <color attach="background" args={["#050813"]} />
        <ambientLight intensity={0.35} />
        <pointLight position={[-3, 3, 3]} intensity={30} color={NEON.amd} />
        <pointLight position={[3, 3, 3]} intensity={30} color={NEON.fireworks} />
        <RoutingTopology3D fireworksLive={fireworksLive} amdLive={amdLive} />
      </Canvas>
      <NodeLabel className="left-[10%] top-[30%]" color={NEON.amd} title="AMD MI300X" sub={amdLive ? "live local route" : "runtime gated"} />
      <NodeLabel className="right-[8%] top-[24%]" color={NEON.fireworks} title="Fireworks Cloud" sub={fireworksLive ? "serverless live" : "credential gated"} />
      <NodeLabel className="left-1/2 top-[48%] -translate-x-1/2" color={NEON.compliance} title="Semantic Cache" sub="local deterministic" />
    </div>
  );
}

function RoutingTopology3D({
  fireworksLive,
  amdLive,
}: {
  fireworksLive: boolean;
  amdLive: boolean;
}) {
  const group = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    if (group.current) {
      group.current.rotation.y = Math.sin(clock.elapsedTime * 0.18) * 0.12;
      group.current.rotation.x = Math.sin(clock.elapsedTime * 0.12) * 0.04;
    }
  });
  return (
    <group ref={group}>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[2.85, 0.018, 12, 160]} />
        <meshBasicMaterial color={NEON.compliance} transparent opacity={0.55} />
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[3.35, 0.006, 12, 160]} />
        <meshBasicMaterial color={NEON.compliance} transparent opacity={0.22} />
      </mesh>
      <NodeSphere position={[-3, 0, 0]} radius={0.52} color={NEON.amd} intensity={amdLive ? 2.2 : 0.9} />
      <NodeSphere position={[3, 0.18, 0]} radius={0.68} color={NEON.fireworks} intensity={fireworksLive ? 2.3 : 1.0} />
      <NodeSphere position={[0, -0.25, 0]} radius={0.36} color={NEON.compliance} intensity={1.4} />
      <CylinderBeam start={[-3, 0, 0]} end={[0, -0.25, 0]} color={NEON.amd} opacity={0.45} />
      <CylinderBeam start={[0, -0.25, 0]} end={[3, 0.18, 0]} color={NEON.fireworks} opacity={0.55} />
      <CylinderBeam start={[-3, 0, 0]} end={[3, 0.18, 0]} color="#ffffff" opacity={0.16} />
      {Array.from({ length: 38 }, (_, index) => (
        <FlowParticle key={index} index={index} reverse={index % 5 === 0} />
      ))}
    </group>
  );
}

function CostWaterfallScene({ usage }: { usage: InferenceUsage | null }) {
  const benchmark = usage?.cost_benchmark ?? null;
  const naive = benchmark?.uncontrolled.estimated_usd ?? 0;
  const optimized = benchmark?.controlled.estimated_usd ?? 0;
  const optimizedHeight = benchmark
    ? Math.max(0.34, 3.2 * (optimized / Math.max(naive, 0.000001)))
    : 0;
  const savings = benchmark ? benchmark.cost_reduction * 100 : 0;
  const observedCalls = usage?.totals.provider_calls ?? 0;

  return (
    <div className="absolute inset-0">
      <Canvas camera={{ position: [0, 2.8, 6.4], fov: 42 }} dpr={[1, 1.7]}>
        <color attach="background" args={["#050813"]} />
        <ambientLight intensity={0.42} />
        <directionalLight position={[2, 4, 3]} intensity={3.5} color="#ffffff" />
        <pointLight position={[-2, 3, 2]} intensity={20} color={NEON.red} />
        <pointLight position={[2.5, 3, 2]} intensity={18} color={NEON.compliance} />
        <CostBlocks3D optimizedHeight={optimizedHeight} savings={savings} />
      </Canvas>
      <div className="absolute left-7 top-24 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-100">
        <div className="font-semibold">Naive API Cost</div>
        <div className="font-mono">{benchmark ? dollars(naive) : "n/a"}</div>
      </div>
      <div className="absolute right-7 top-40 rounded-lg border border-[#00FF88]/30 bg-[#00FF88]/10 px-3 py-2 text-xs text-[#D8FFE8]">
        <div className="font-semibold">Optimized Cost</div>
        <div className="font-mono">{benchmark ? dollars(optimized) : "n/a"}</div>
      </div>
      <div className="absolute right-5 top-20 max-w-none whitespace-nowrap rounded-full border border-[#00FF88]/40 bg-[#00FF88]/10 px-3 py-1.5 text-center text-[11px] font-semibold text-[#D8FFE8] shadow-[0_0_30px_rgba(0,255,136,0.25)]">
        {benchmark ? `${savings.toFixed(1)}% benchmark` : "No benchmark"}
      </div>
      <div className="absolute bottom-24 left-1/2 -translate-x-1/2 rounded-full border border-white/10 bg-black/35 px-3 py-1 text-[10px] uppercase tracking-[0.15em] text-white/55">
        {observedCalls > 0 ? `${observedCalls} live calls observed` : "No live spend observed"}
      </div>
    </div>
  );
}

function CostBlocks3D({
  optimizedHeight,
  savings,
}: {
  optimizedHeight: number;
  savings: number;
}) {
  const group = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    if (group.current) {
      group.current.rotation.y = -0.28 + Math.sin(clock.elapsedTime * 0.14) * 0.05;
    }
  });
  return (
    <group ref={group}>
      {optimizedHeight > 0 && (
        <>
          <mesh position={[-1.6, 0, 0]}>
            <boxGeometry args={[1.75, 3.2, 1.2]} />
            <meshStandardMaterial color={NEON.red} emissive={NEON.red} emissiveIntensity={0.38} transparent opacity={0.72} />
          </mesh>
          <mesh position={[1.65, -1.6 + optimizedHeight / 2, 0.1]}>
            <boxGeometry args={[0.82, optimizedHeight, 1.2]} />
            <meshStandardMaterial color={NEON.compliance} emissive={NEON.compliance} emissiveIntensity={0.65} transparent opacity={0.78} />
          </mesh>
          <CylinderBeam start={[-0.55, 1.25, 0]} end={[1.05, -0.55, 0.05]} color={NEON.compliance} opacity={0.4} radius={0.018} />
          {Array.from({ length: 28 }, (_, index) => (
            <SavingsParticle key={index} index={index} savings={savings} />
          ))}
        </>
      )}
    </group>
  );
}

function BiasAuditRadarScene({ dimensions }: { dimensions: BiasAuditDimension[] }) {
  return (
    <div className="absolute inset-0">
      <Canvas camera={{ position: [0, 0.45, 5], fov: 42 }} dpr={[1, 1.7]}>
        <color attach="background" args={["#050813"]} />
        <ambientLight intensity={0.5} />
        <pointLight position={[1.8, 3, 2.8]} intensity={18} color={NEON.compliance} />
        <pointLight position={[-2, 2, 2]} intensity={10} color={NEON.red} />
        <BiasRadar3D dimensions={dimensions} />
      </Canvas>
      <div className="absolute right-5 top-20 space-y-2">
        {dimensions.slice(0, 4).map((dimension) => (
          <div key={dimension.dimension} className="rounded-lg border border-white/10 bg-black/25 px-3 py-1.5 text-[11px] text-white/74">
            <span className="font-semibold capitalize">{dimension.dimension.replaceAll("_", " ")}</span>{" "}
            <span className={dimension.violates_four_fifths_rule ? "text-red-200" : "text-[#D8FFE8]"}>
              {dimension.adverse_impact_ratio.toFixed(2)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function BiasRadar3D({ dimensions }: { dimensions: BiasAuditDimension[] }) {
  const group = useRef<THREE.Group>(null);
  const bars = useMemo(
    () =>
      dimensions.map((dimension, index) => ({
        ...dimension,
        angle: index * ((Math.PI * 2) / Math.max(dimensions.length, 1)),
      })),
    [dimensions]
  );
  useFrame(({ clock }) => {
    if (group.current) {
      group.current.rotation.y = clock.elapsedTime * 0.16;
      group.current.rotation.x = Math.sin(clock.elapsedTime * 0.13) * 0.08;
    }
  });
  return (
    <group ref={group}>
      <mesh>
        <sphereGeometry args={[1.48, 64, 32]} />
        <meshBasicMaterial color={NEON.compliance} transparent opacity={0.13} wireframe />
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[1.48, 0.014, 12, 128]} />
        <meshBasicMaterial color={NEON.compliance} transparent opacity={0.62} />
      </mesh>
      {bars.map((bar) => {
        const violates = bar.adverse_impact_ratio < 0.8;
        const radius = violates ? 2.18 : 0.7 + bar.adverse_impact_ratio;
        const end: [number, number, number] = [
          Math.cos(bar.angle) * radius,
          violates ? 0.48 : 0.12,
          Math.sin(bar.angle) * radius,
        ];
        return (
          <group key={bar.dimension}>
            <CylinderBeam start={[0, 0, 0]} end={end} color={violates ? NEON.red : NEON.compliance} opacity={violates ? 0.72 : 0.44} radius={violates ? 0.026 : 0.018} />
            <NodeSphere position={end} radius={violates ? 0.115 : 0.085} color={violates ? NEON.red : NEON.compliance} intensity={violates ? 2.1 : 1.3} />
          </group>
        );
      })}
    </group>
  );
}

function NodeSphere({
  position,
  radius,
  color,
  intensity,
}: {
  position: [number, number, number];
  radius: number;
  color: string;
  intensity: number;
}) {
  return (
    <mesh position={position}>
      <sphereGeometry args={[radius, 40, 40]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={intensity} roughness={0.28} metalness={0.22} />
    </mesh>
  );
}

function CylinderBeam({
  start,
  end,
  color,
  opacity = 0.5,
  radius = 0.014,
}: {
  start: [number, number, number];
  end: [number, number, number];
  color: string;
  opacity?: number;
  radius?: number;
}) {
  const transform = useMemo(() => {
    const a = new THREE.Vector3(...start);
    const b = new THREE.Vector3(...end);
    const mid = a.clone().add(b).multiplyScalar(0.5);
    const direction = b.clone().sub(a);
    const length = direction.length();
    const quaternion = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      direction.clone().normalize()
    );
    return { mid, length, quaternion };
  }, [start, end]);
  return (
    <mesh position={transform.mid} quaternion={transform.quaternion}>
      <cylinderGeometry args={[radius, radius, transform.length, 12]} />
      <meshBasicMaterial color={color} transparent opacity={opacity} />
    </mesh>
  );
}

function FlowParticle({ index, reverse }: { index: number; reverse: boolean }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    const cycle = ((clock.elapsedTime * 0.22 + index * 0.035) % 1 + 1) % 1;
    const t = reverse ? 1 - cycle : cycle;
    const x = -3 + t * 6;
    const y = Math.sin(t * Math.PI) * 0.46 - 0.05 + Math.sin(index) * 0.04;
    const z = Math.cos(t * Math.PI * 2 + index) * 0.26;
    if (ref.current) ref.current.position.set(x, y, z);
  });
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[0.035, 10, 10]} />
      <meshBasicMaterial color={reverse ? NEON.amd : NEON.fireworks} transparent opacity={0.85} />
    </mesh>
  );
}

function SavingsParticle({ index, savings }: { index: number; savings: number }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    const angle = clock.elapsedTime * 0.55 + index * 0.7;
    const radius = 1.05 + (index % 5) * 0.16;
    if (ref.current) {
      ref.current.position.set(
        Math.cos(angle) * radius,
        -0.05 + Math.sin(angle * 1.4) * 0.52,
        Math.sin(angle) * 0.62
      );
      ref.current.scale.setScalar(0.75 + (savings / 100) * 0.45);
    }
  });
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[0.028, 10, 10]} />
      <meshBasicMaterial color={NEON.compliance} transparent opacity={0.74} />
    </mesh>
  );
}

function GlassPanel({
  title,
  eyebrow,
  icon,
  className = "",
  children,
}: {
  title: string;
  eyebrow: string;
  icon: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`relative overflow-hidden rounded-xl border border-white/10 bg-[rgba(8,14,28,0.72)] shadow-[0_24px_80px_rgba(0,0,0,0.38)] backdrop-blur-xl ${className}`}
    >
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.11),transparent_32%,rgba(0,212,255,0.06))]" />
      <div className="absolute left-5 top-5 z-10">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-[#00D4FF]/80">
          {icon}
          {eyebrow}
        </div>
        <h3 className="mt-2 text-lg font-semibold text-white">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function StatusTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "blue" | "red" | "green";
}) {
  const color = tone === "blue" ? NEON.fireworks : tone === "red" ? NEON.amd : NEON.compliance;
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.06] px-3 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
      <div className="text-[10px] uppercase tracking-[0.16em] text-white/45">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold capitalize" style={{ color }}>
        {value.replaceAll("_", " ")}
      </div>
    </div>
  );
}

function PanelLegend({
  items,
}: {
  items: { label: string; value: string; color: string }[];
}) {
  return (
    <div className="absolute bottom-5 left-5 right-5 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
      {items.map((item) => (
        <div key={item.label} className="rounded-lg border border-white/10 bg-black/25 px-3 py-2">
          <div className="flex items-center gap-2 text-white/55">
            <span className="h-2 w-2 rounded-full" style={{ background: item.color, boxShadow: `0 0 14px ${item.color}` }} />
            {item.label}
          </div>
          <div className="mt-1 font-semibold text-white">{item.value}</div>
        </div>
      ))}
    </div>
  );
}

function NodeLabel({
  className,
  color,
  title,
  sub,
}: {
  className: string;
  color: string;
  title: string;
  sub: string;
}) {
  return (
    <div className={`absolute z-10 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs backdrop-blur ${className}`}>
      <div className="font-semibold" style={{ color }}>
        {title}
      </div>
      <div className="text-white/48">{sub}</div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub: string;
  accent: string;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/24 px-4 py-3">
      <div className="text-[10px] uppercase tracking-[0.16em] text-white/42">{label}</div>
      <div className="mt-2 text-xl font-semibold" style={{ color: accent }}>
        {value}
      </div>
      <div className="mt-1 text-xs text-white/42">{sub}</div>
    </div>
  );
}

function MetricPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "red" | "green" | "blue";
}) {
  const color = tone === "red" ? NEON.red : tone === "green" ? NEON.compliance : NEON.fireworks;
  return (
    <div className="rounded-lg border border-white/10 bg-black/24 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.14em] text-white/40">{label}</div>
      <div className="mt-1 font-semibold" style={{ color }}>
        {value}
      </div>
    </div>
  );
}

function GpuStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/24 px-3 py-3 text-center">
      <Cpu size={15} className="mx-auto" style={{ color }} />
      <div className="mt-1 text-[10px] uppercase tracking-[0.13em] text-white/40">{label}</div>
      <div className="mt-1 text-sm font-semibold" style={{ color }}>
        {value}
      </div>
    </div>
  );
}

function WorkflowRow({
  name,
  detail,
  progress,
  color,
  value,
}: {
  name: string;
  detail: string;
  progress: number;
  color: string;
  value: string;
}) {
  const width = `${Math.max(3, Math.min(100, progress * 100))}%`;
  return (
    <div className="rounded-lg border border-white/10 bg-black/24 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-semibold text-white">{name}</div>
          <div className="mt-0.5 line-clamp-1 text-xs text-white/46">{detail}</div>
        </div>
        <div className="shrink-0 font-mono text-xs" style={{ color }}>
          {value}
        </div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/8">
        <div className="h-full rounded-full" style={{ width, background: color, boxShadow: `0 0 18px ${color}` }} />
      </div>
    </div>
  );
}

function fallbackBiasDimensions(): BiasAuditDimension[] {
  return [
    {
      dimension: "gender",
      reference_group: "M",
      reference_rate: 0.96,
      lowest_group: "F",
      lowest_rate: 0.91,
      adverse_impact_ratio: 0.95,
      threshold: 0.8,
      violates_four_fifths_rule: false,
      groups: [],
    },
    {
      dimension: "age_group",
      reference_group: "31-50",
      reference_rate: 0.72,
      lowest_group: "51+",
      lowest_rate: 0.62,
      adverse_impact_ratio: 0.86,
      threshold: 0.8,
      violates_four_fifths_rule: false,
      groups: [],
    },
    {
      dimension: "race",
      reference_group: "White",
      reference_rate: 0.7,
      lowest_group: "Black",
      lowest_rate: 0.5,
      adverse_impact_ratio: 0.71,
      threshold: 0.8,
      violates_four_fifths_rule: true,
      groups: [],
    },
  ];
}

function workflowProgress(value: number, target: number) {
  return Math.max(0, Math.min(1, value / Math.max(1, target)));
}

function rateLabel(rate: number | null) {
  return rate === null ? "n/a" : `${Math.round(rate * 100)}%`;
}

function shortModel(modelId?: string) {
  if (!modelId) return "n/a";
  const parts = modelId.split("/");
  return parts.at(-1) || modelId;
}

function dollars(value: number) {
  return `$${value.toFixed(6)}`;
}
