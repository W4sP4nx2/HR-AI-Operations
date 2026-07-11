"use client";

/**
 * SettingsPanel — operator-visible runtime controls and integration posture.
 *
 * Provider secrets are deliberately delegated to ByokControl, whose key store
 * is memory-only. This panel reports capability evidence and bounded runtime
 * controls; it does not offer a browser setting that could persist a secret.
 */

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  CircleAlert,
  Cpu,
  Gauge,
  KeyRound,
  Link2,
  Network,
  PlugZap,
  Settings,
  ShieldCheck,
  X,
} from "lucide-react";
import ByokControl from "./ByokControl";
import { api, type CapabilitySnapshot, type CapabilityStatus } from "../../lib/api";

type Tab = "ai" | "llm" | "integrations";

const STATUS_LABELS: Record<string, string> = {
  proven: "proven",
  measured_local: "measured locally",
  configured: "configured",
  live_gated: "live gated",
  not_configured: "not configured",
  unavailable: "unavailable",
};

function statusStyle(status: string) {
  if (status === "proven" || status === "configured") {
    return "bg-green-100 text-green-700";
  }
  if (status === "measured_local") return "bg-brand-purple/10 text-brand-purple";
  if (status === "live_gated") return "bg-amber-100 text-amber-700";
  return "bg-ink-700/10 text-ink-700/70";
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${statusStyle(status)}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

export default function SettingsPanel({
  open,
  onClose,
  initialTab = "ai",
  providerLabel,
  llmProvider,
  llmOn,
  byokSupported,
  byokActive,
  onByokActiveChange,
  configIssues,
}: {
  open: boolean;
  onClose: () => void;
  initialTab?: Tab;
  providerLabel: string;
  llmProvider: string;
  llmOn: boolean;
  byokSupported: boolean;
  byokActive: boolean;
  onByokActiveChange: (active: boolean) => void;
  configIssues: string[];
}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [snapshot, setSnapshot] = useState<CapabilitySnapshot | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => setTab(initialTab), [initialTab, open]);

  useEffect(() => {
    if (!open) return;
    let mounted = true;
    void api.capabilities().then((data) => {
      if (mounted) {
        setSnapshot(data);
        setOffline(false);
      }
    }).catch(() => {
      if (mounted) setOffline(true);
    });
    return () => {
      mounted = false;
    };
  }, [open]);

  const providers = snapshot?.providers ?? [];
  const integrations = snapshot?.integrations ?? [
    {
      integration_id: "a2a",
      label: "A2A handoffs",
      status: "proven" as CapabilityStatus,
      detail: "Certified local handoff path.",
      missing_inputs: [],
    },
    {
      integration_id: "crewai",
      label: "CrewAI adapter",
      status: "configured" as CapabilityStatus,
      detail: "Optional CrewAI path with deterministic fallback.",
      missing_inputs: [],
    },
    {
      integration_id: "langsmith",
      label: "LangSmith tracing",
      status: "not_configured" as const,
      detail: "Optional observability; no tracing key is active in preview.",
      missing_inputs: ["LANGCHAIN_API_KEY", "LANGCHAIN_TRACING_V2=true"],
    },
  ];
  const controls = snapshot?.runtime_controls;
  const fireworks = providers.find((item) => item.provider_id === "fireworks");
  const amd = providers.find((item) => item.provider_id === "amd_vllm_gemma");
  const fallback = providers.find((item) => item.provider_id === "deterministic_fallback");
  const selectedProvider = snapshot?.active_provider || llmProvider || "deterministic";
  const routeCards = useMemo(() => snapshot?.routing ?? [], [snapshot]);

  if (!open) return null;

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "ai", label: "AI settings", icon: <Settings size={15} /> },
    { key: "llm", label: "LLM route", icon: <Cpu size={15} /> },
    { key: "integrations", label: "Integrations", icon: <PlugZap size={15} /> },
  ];

  return (
    <div className="fixed inset-0 z-[70] flex justify-end bg-ink-900/30" role="dialog" aria-modal="true" aria-label="AI settings">
      <button aria-label="Close settings" className="absolute inset-0 cursor-default" onClick={onClose} />
      <section className="relative flex h-full w-full max-w-xl flex-col bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b border-brand-purple/10 px-5 py-5">
          <div>
            <div className="flex items-center gap-2 text-brand-purple">
              <Settings size={18} />
              <h2 className="text-base font-semibold">Runtime settings</h2>
            </div>
            <p className="mt-1 text-xs text-ink-700/60">Evidence, routing, and secure integration controls</p>
          </div>
          <button onClick={onClose} aria-label="Close settings" title="Close settings" className="rounded-lg p-2 text-ink-700/60 hover:bg-brand-cream hover:text-brand-purple">
            <X size={18} />
          </button>
        </header>

        <nav className="grid grid-cols-3 gap-1 border-b border-brand-purple/10 bg-brand-cream/50 p-2" aria-label="Settings sections">
          {tabs.map((item) => (
            <button key={item.key} onClick={() => setTab(item.key)} className={`flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-semibold transition ${tab === item.key ? "bg-brand-purple text-white" : "text-brand-purple hover:bg-brand-purple/10"}`}>
              {item.icon}
              {item.label}
            </button>
          ))}
        </nav>

        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {offline && <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">Capability endpoint unavailable. Showing safe local defaults.</div>}

          {tab === "ai" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-brand-purple/10 bg-brand-cream/40 p-4">
                  <div className="flex items-center gap-2 text-xs font-semibold text-ink-700/70"><Activity size={14} /> Active mode</div>
                  <p className="mt-2 text-lg font-semibold text-brand-purple">{llmOn || byokActive ? "Live route" : "Deterministic"}</p>
                  <p className="mt-1 text-[11px] text-ink-700/60">{selectedProvider}</p>
                </div>
                <div className="rounded-xl border border-brand-purple/10 bg-brand-cream/40 p-4">
                  <div className="flex items-center gap-2 text-xs font-semibold text-ink-700/70"><Gauge size={14} /> Policy retrieval</div>
                  <p className="mt-2 text-lg font-semibold text-brand-purple">Top {controls?.retrieval_top_k ?? 5}</p>
                  <p className="mt-1 text-[11px] text-ink-700/60">cosine-ranked chunks</p>
                </div>
              </div>
              <div className="rounded-xl border border-brand-purple/10 p-4">
                <h3 className="text-sm font-semibold text-brand-purple">Context window controls</h3>
                <div className="mt-3 grid grid-cols-2 gap-x-5 gap-y-3 text-xs">
                  <div><span className="text-ink-700/55">Input cap</span><strong className="ml-2 text-ink-800">{controls?.max_input_tokens ?? 4000} tokens</strong></div>
                  <div><span className="text-ink-700/55">Output cap</span><strong className="ml-2 text-ink-800">{controls?.max_output_tokens ?? 1000} tokens</strong></div>
                  <div><span className="text-ink-700/55">Policy timeout</span><strong className="ml-2 text-ink-800">{controls?.policy_timeout_seconds ?? 15}s</strong></div>
                  <div><span className="text-ink-700/55">Cache TTL</span><strong className="ml-2 text-ink-800">{controls?.semantic_cache_ttl_seconds ?? 3600}s</strong></div>
                </div>
                <p className="mt-3 text-[11px] leading-relaxed text-ink-700/60">Caps bound latency and spend. Resume and policy inputs are truncated before provider calls; fallback mode remains available when live dependencies are absent.</p>
              </div>
              <div className="rounded-xl border border-green-200 bg-green-50/60 p-4 text-xs text-green-800"><div className="flex items-center gap-2 font-semibold"><ShieldCheck size={15} /> Governance posture</div><p className="mt-1">Human review, audit logging, prompt-injection blocking, and no-key deterministic evaluation remain active.</p></div>
            </div>
          )}

          {tab === "llm" && (
            <div className="space-y-4">
              <div className="rounded-xl border border-brand-purple/10 p-4">
                <div className="flex items-center justify-between gap-3"><div><h3 className="text-sm font-semibold text-brand-purple">Selected provider</h3><p className="mt-1 text-xs text-ink-700/60">{providerLabel} · {selectedProvider}</p></div><StatusPill status={llmOn || byokActive ? "configured" : "live_gated"} /></div>
                {configIssues.length > 0 && <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-xs text-amber-700"><CircleAlert size={15} className="mt-0.5 shrink-0" /><span>{configIssues.join("; ")}</span></div>}
              </div>
              {byokSupported && <div className="rounded-xl border border-brand-purple/10 p-4"><div className="mb-3 flex items-center gap-2 text-sm font-semibold text-brand-purple"><KeyRound size={15} /> Secure browser key</div><ByokControl placement="down" onActiveChange={onByokActiveChange} providerLabel={providerLabel} /></div>}
              <div className="space-y-2">
                {[fallback, fireworks, amd].filter(Boolean).map((provider) => provider && (
                  <div key={provider.provider_id} className="rounded-xl border border-brand-purple/10 p-4">
                    <div className="flex items-center justify-between gap-3"><div><h3 className="text-sm font-semibold text-ink-800">{provider.provider_id}</h3><p className="mt-1 text-[11px] text-ink-700/60">{provider.provider_type}</p></div><StatusPill status={provider.status} /></div>
                    <p className="mt-2 text-xs text-ink-700/70">{provider.live_enabled ? "Live calls allowed by current evidence." : provider.status === "live_gated" ? `Missing: ${provider.missing_inputs.join(", ") || "live evidence"}` : "Available for local evaluation."}</p>
                    {provider.models_available.length > 0 && <p className="mt-2 truncate font-mono text-[10px] text-ink-700/55" title={provider.models_available.join(", ")}>{provider.models_available.join(", ")}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {tab === "integrations" && (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-3">
                {integrations.map((integration) => <div key={integration.integration_id} className="rounded-xl border border-brand-purple/10 p-3"><div className="flex items-center gap-2 text-brand-purple"><Link2 size={14} /><span className="text-xs font-semibold">{integration.label}</span></div><div className="mt-2"><StatusPill status={integration.status} /></div><p className="mt-2 text-[11px] leading-relaxed text-ink-700/60">{integration.detail}</p></div>)}
              </div>
              <div className="rounded-xl border border-brand-purple/10 p-4"><h3 className="flex items-center gap-2 text-sm font-semibold text-brand-purple"><Network size={15} /> Certified routing examples</h3><div className="mt-3 space-y-2">{routeCards.length === 0 ? <p className="text-xs text-ink-700/60">No routing snapshot available.</p> : routeCards.map((route) => <div key={route.task_type} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-brand-cream/40 px-3 py-2 text-xs"><span className="font-medium text-ink-800">{route.task_type.replaceAll("_", " ")}</span><span className="text-ink-700/60">{route.selected_provider}</span><StatusPill status={route.status} /></div>)}</div></div>
              <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 text-xs text-amber-800"><div className="flex items-center gap-2 font-semibold"><CircleAlert size={15} /> Live integration boundary</div><p className="mt-1 leading-relaxed">A2A and CrewAI certification is testable locally. Fireworks, AMD/Gemma, and LangSmith require injected credentials or runtime evidence; this preview does not claim those live paths.</p></div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
