"use client";

/**
 * SettingsPanel — persisted AI controls with explicit secret and capability
 * boundaries. The form is intentionally server-backed: a visual toggle is
 * not presented as active until the API accepts and persists it.
 */

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  CheckCircle2,
  CircleAlert,
  Cpu,
  Database,
  Gauge,
  KeyRound,
  Link2,
  Network,
  PlugZap,
  RotateCcw,
  Save,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Wifi,
  X,
} from "lucide-react";
import ByokControl from "./ByokControl";
import {
  api,
  type AIConnectionTest,
  type AIProvider,
  type AISettings,
  type AISettingsUpdate,
  type CapabilitySnapshot,
  type CapabilityStatus,
} from "../../lib/api";

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
  if (status === "proven" || status === "configured") return "bg-green-100 text-green-700";
  if (status === "measured_local") return "bg-brand-purple/10 text-brand-purple";
  if (status === "live_gated") return "bg-amber-100 text-amber-700";
  return "bg-ink-700/10 text-ink-700/70";
}

function StatusPill({ status }: { status: string }) {
  return <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${statusStyle(status)}`}>{STATUS_LABELS[status] ?? status}</span>;
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
  const [aiSettings, setAISettings] = useState<AISettings | null>(null);
  const [draft, setDraft] = useState<AISettingsUpdate>({});
  const [secretInput, setSecretInput] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [testState, setTestState] = useState<AIConnectionTest | null>(null);
  const [testBusy, setTestBusy] = useState(false);
  const [offline, setOffline] = useState(false);

  useEffect(() => setTab(initialTab), [initialTab, open]);

  useEffect(() => {
    if (!open) return;
    let mounted = true;
    void Promise.allSettled([api.aiSettings(), api.capabilities()]).then(([settingsResult, capabilities]) => {
      if (!mounted) return;
      if (settingsResult.status === "fulfilled") {
        const value = settingsResult.value;
        setAISettings(value);
        setDraft({
          provider: value.provider || "deterministic",
          selected_model: value.selected_model,
          temperature: value.temperature,
          max_tokens: value.max_tokens,
          reasoning_effort: value.reasoning_effort,
          daily_budget_usd: value.daily_budget_usd,
          caching_enabled: value.caching_enabled,
          batch_processing_enabled: value.batch_processing_enabled,
          pii_redaction_enabled: value.pii_redaction_enabled,
          human_review_required: value.human_review_required,
        });
        setOffline(false);
      } else {
        setOffline(true);
      }
      if (capabilities.status === "fulfilled") setSnapshot(capabilities.value);
    });
    return () => {
      mounted = false;
    };
  }, [open]);

  const integrations = (snapshot?.integrations ?? [
    { integration_id: "orchestrator", label: "Governed orchestrator", status: "proven" as CapabilityStatus, detail: "Route, cost, cache, certification, audit, fallback, and human review are visible.", missing_inputs: [], architecture: "single_orchestrator" },
    { integration_id: "langsmith", label: "LangSmith tracing", status: "not_configured" as const, detail: "Privacy-safe nested manager/worker tracing is inactive in preview.", missing_inputs: ["LANGSMITH_API_KEY", "LANGSMITH_TRACING=true"] },
  ]).filter((integration) => !["a2a", "crewai"].includes(integration.integration_id));
  const routeCards = useMemo(() => snapshot?.routing ?? [], [snapshot]);

  if (!open) return null;

  const selectedProvider = (draft.provider ?? aiSettings?.provider ?? "deterministic") as AIProvider;
  const selectedModel = draft.selected_model ?? aiSettings?.selected_model ?? "";
  const currentKey = aiSettings?.api_keys[selectedProvider];
  const selectedModelInfo = aiSettings?.models.find((model) => model.id === selectedModel);

  const updateDraft = <K extends keyof AISettingsUpdate>(key: K, value: AISettingsUpdate[K]) => {
    setDraft((previous) => ({ ...previous, [key]: value }));
    setSaveState("idle");
  };

  const save = async () => {
    setSaveState("saving");
    try {
      const payload: AISettingsUpdate = { ...draft, clear_api_key: clearKey };
      if (secretInput.trim()) payload.api_key = secretInput.trim();
      const saved = await api.updateAISettings(payload);
      setAISettings(saved);
      setSecretInput("");
      setClearKey(false);
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  };

  const reset = async () => {
    setSaveState("saving");
    try {
      const resetValue = await api.resetAISettings();
      setAISettings(resetValue);
      setDraft({ provider: resetValue.provider || "deterministic", selected_model: resetValue.selected_model, temperature: resetValue.temperature, max_tokens: resetValue.max_tokens, reasoning_effort: resetValue.reasoning_effort, daily_budget_usd: resetValue.daily_budget_usd, caching_enabled: resetValue.caching_enabled, batch_processing_enabled: resetValue.batch_processing_enabled, pii_redaction_enabled: resetValue.pii_redaction_enabled, human_review_required: resetValue.human_review_required });
      setSecretInput("");
      setClearKey(false);
      setTestState(null);
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  };

  const testConnection = async () => {
    setTestBusy(true);
    try {
      const result = await api.testAIConnection({ provider: selectedProvider, model: selectedModel || undefined, api_key: secretInput.trim() || undefined });
      setTestState(result);
    } catch {
      setTestState({ provider: selectedProvider, model: selectedModel || null, valid: false, detail: "Connection test request failed", latency_ms: 0, persisted: false });
    } finally {
      setTestBusy(false);
    }
  };

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "ai", label: "Runtime", icon: <Settings size={15} /> },
    { key: "llm", label: "Provider", icon: <Cpu size={15} /> },
    { key: "integrations", label: "Advanced", icon: <PlugZap size={15} /> },
  ];

  return (
    <div className="fixed inset-0 z-[70] flex justify-end bg-ink-900/30" role="dialog" aria-modal="true" aria-label="AI settings">
      <button aria-label="Close settings" className="absolute inset-0 cursor-default" onClick={onClose} />
      <section className="relative flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b border-brand-purple/10 px-5 py-5">
          <div><div className="flex items-center gap-2 text-brand-purple"><Settings size={18} /><h2 className="text-base font-semibold">Advanced controls</h2></div><p className="mt-1 text-xs text-ink-700/60">Optional operator controls. The guided walkthrough is the default demo path.</p></div>
          <button onClick={onClose} aria-label="Close settings" title="Close settings" className="rounded-lg p-2 text-ink-700/60 hover:bg-brand-cream hover:text-brand-purple"><X size={18} /></button>
        </header>
        <nav className="grid grid-cols-3 gap-1 border-b border-brand-purple/10 bg-brand-cream/50 p-2" aria-label="Settings sections">
          {tabs.map((item) => <button key={item.key} onClick={() => setTab(item.key)} className={`flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-semibold transition ${tab === item.key ? "bg-brand-purple text-white" : "text-brand-purple hover:bg-brand-purple/10"}`}>{item.icon}{item.label}</button>)}
        </nav>

        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {offline && <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">Settings endpoint unavailable. Changes are not being applied.</div>}

          {tab === "ai" && <div className="space-y-4">
            <div className="flex items-center justify-between rounded-xl border border-brand-purple/10 bg-brand-cream/35 p-4"><div><div className="flex items-center gap-2 text-xs font-semibold text-ink-700/70"><Activity size={14} /> Runtime control plane</div><p className="mt-1 text-sm font-semibold text-brand-purple">{aiSettings ? "Connected to persistent settings" : "Loading settings"}</p><p className="mt-1 text-[11px] text-ink-700/55">{aiSettings?.updated_at ? `Last saved ${new Date(aiSettings.updated_at).toLocaleString()}` : "No saved operator override"}</p></div><StatusPill status={saveState === "error" ? "unavailable" : saveState === "saved" ? "configured" : "measured_local"} /></div>

            <section className="rounded-xl border border-brand-purple/10 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-brand-purple"><Cpu size={16} /> Provider and model</div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-xs font-medium text-ink-700/70">Provider<select value={selectedProvider} onChange={(event) => updateDraft("provider", event.target.value as AIProvider)} className="mt-1 w-full rounded-lg border border-brand-purple/15 bg-white px-3 py-2 text-sm text-ink-800 outline-none focus:border-brand-purple"><option value="deterministic">Deterministic fallback</option><option value="fireworks">Fireworks Cloud</option><option value="anthropic">Anthropic</option><option value="amd_vllm">AMD vLLM</option></select></label><div className="rounded-lg bg-brand-cream/55 p-3 text-xs"><div className="font-semibold text-brand-purple">Active route</div><div className="mt-1 text-ink-700/70">{selectedProvider === "deterministic" ? "Offline baseline" : providerLabel || llmProvider}</div><div className="mt-2">{llmOn ? <StatusPill status="configured" /> : <StatusPill status="live_gated" />}</div></div></div>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">{(aiSettings?.models ?? []).map((model) => <button key={model.id} type="button" onClick={() => updateDraft("selected_model", model.id)} className={`rounded-lg border p-3 text-left transition ${selectedModel === model.id ? "border-brand-purple bg-brand-purple/5 ring-1 ring-brand-purple" : "border-brand-purple/10 hover:border-brand-purple/40"}`}><div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold text-ink-800">{model.label}</span>{selectedModel === model.id && <CheckCircle2 size={15} className="text-brand-purple" />}</div><div className="mt-1 text-[10px] text-ink-700/55">{model.family} · <span className="font-mono">{model.id}</span></div><div className="mt-2"><StatusPill status={model.live_allowed ? "configured" : "live_gated"} /></div></button>)}</div>
              {selectedModelInfo && !selectedModelInfo.live_allowed && <p className="mt-3 flex items-center gap-2 text-[11px] text-amber-700"><CircleAlert size={14} /> This catalog model is visible but not in the deployment allow-list, so live calls remain gated.</p>}
            </section>

            <section className="rounded-xl border border-brand-purple/10 p-4"><div className="flex items-center gap-2 text-sm font-semibold text-brand-purple"><SlidersHorizontal size={16} /> Inference parameters</div><div className="mt-4 space-y-4"><RangeControl label="Temperature" value={Number(draft.temperature ?? 0.2)} min={0} max={1} step={0.05} display={Number(draft.temperature ?? 0.2).toFixed(2)} onChange={(value) => updateDraft("temperature", value)} /><RangeControl label="Max output tokens" value={Number(draft.max_tokens ?? 1000)} min={64} max={4096} step={64} display={`${draft.max_tokens ?? 1000}`} onChange={(value) => updateDraft("max_tokens", value)} /><RangeControl label="Reasoning effort" value={Number(draft.reasoning_effort ?? 0.3)} min={0} max={1} step={0.05} display={Number(draft.reasoning_effort ?? 0.3) < 0.34 ? "low" : Number(draft.reasoning_effort ?? 0.3) < 0.67 ? "medium" : "high"} onChange={(value) => updateDraft("reasoning_effort", value)} /></div><p className="mt-3 text-[11px] text-ink-700/55">These values are applied to subsequent structured and text inference requests after save.</p></section>

            <section className="rounded-xl border border-brand-purple/10 p-4"><div className="flex items-center gap-2 text-sm font-semibold text-brand-purple"><Gauge size={16} /> Cost controls</div><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-xs font-medium text-ink-700/70">Daily budget (USD)<input type="number" min="0" step="0.01" value={draft.daily_budget_usd ?? 0} onChange={(event) => updateDraft("daily_budget_usd", Number(event.target.value))} className="mt-1 w-full rounded-lg border border-brand-purple/15 px-3 py-2 text-sm" /></label><Toggle label="Semantic caching" checked={Boolean(draft.caching_enabled)} onChange={(value) => updateDraft("caching_enabled", value)} /><Toggle label="Batch processing" checked={Boolean(draft.batch_processing_enabled)} onChange={(value) => updateDraft("batch_processing_enabled", value)} /></div><p className="mt-3 text-[11px] text-ink-700/55">A zero budget leaves the existing circuit breaker disabled. Nonzero budgets are enforced by the runtime cost guard.</p></section>

            <section className="rounded-xl border border-brand-purple/10 p-4"><div className="flex items-center gap-2 text-sm font-semibold text-brand-purple"><ShieldCheck size={16} /> Compliance controls</div><div className="mt-3 grid gap-3 sm:grid-cols-2"><Toggle label="PII redaction" checked={Boolean(draft.pii_redaction_enabled)} onChange={(value) => updateDraft("pii_redaction_enabled", value)} /><Toggle label="Require human review" checked={Boolean(draft.human_review_required)} onChange={(value) => updateDraft("human_review_required", value)} /></div><p className="mt-3 text-[11px] text-ink-700/55">Redaction and review thresholds are applied by the backend before audit or agent completion.</p></section>
          </div>}

          {tab === "llm" && <div className="space-y-4"><section className="rounded-xl border border-brand-purple/10 p-4"><div className="flex items-center gap-2 text-sm font-semibold text-brand-purple"><KeyRound size={16} /> Secure provider key</div><p className="mt-1 text-xs text-ink-700/60">Keys are encrypted before database storage and never returned to the browser.</p><div className="mt-3 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end"><label className="text-xs font-medium text-ink-700/70">New {selectedProvider || "provider"} key<input type="password" value={secretInput} onChange={(event) => setSecretInput(event.target.value)} placeholder={currentKey?.masked || "Paste a key to replace or test"} className="mt-1 w-full rounded-lg border border-brand-purple/15 px-3 py-2 text-sm" autoComplete="off" /></label><button type="button" onClick={() => setClearKey((value) => !value)} className={`rounded-lg border px-3 py-2 text-xs font-semibold ${clearKey ? "border-red-200 bg-red-50 text-red-700" : "border-brand-purple/15 text-brand-purple"}`}>{clearKey ? "Key will clear" : "Clear saved key"}</button></div><div className="mt-3 flex flex-wrap items-center gap-2"><button type="button" onClick={testConnection} disabled={testBusy} className="inline-flex items-center gap-2 rounded-lg border border-brand-purple px-3 py-2 text-xs font-semibold text-brand-purple disabled:opacity-50"><Wifi size={14} />{testBusy ? "Testing…" : "Test connection"}</button>{testState && <span className={`inline-flex items-center gap-1 text-xs ${testState.valid ? "text-green-700" : "text-amber-700"}`}>{testState.valid ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}{testState.detail} · {testState.latency_ms} ms</span>}</div></section><div className="rounded-xl border border-brand-purple/10 p-4"><h3 className="text-sm font-semibold text-brand-purple">Environment and key status</h3><div className="mt-3 grid gap-2 sm:grid-cols-3">{["anthropic", "fireworks", "amd_vllm"].map((provider) => { const status = aiSettings?.api_keys[provider]; return <div key={provider} className="rounded-lg bg-brand-cream/50 p-3 text-xs"><div className="font-semibold text-ink-800">{provider}</div><div className="mt-2"><StatusPill status={status?.configured ? "configured" : "not_configured"} /></div><p className="mt-2 text-[10px] text-ink-700/55">{status?.source === "settings" ? status.masked : status?.source === "environment" ? "environment-managed" : "No key configured"}</p></div>; })}</div></div>{byokSupported && <div className="rounded-xl border border-brand-purple/10 p-4"><div className="mb-3 flex items-center gap-2 text-sm font-semibold text-brand-purple"><KeyRound size={15} /> Ephemeral browser key</div><ByokControl placement="down" onActiveChange={onByokActiveChange} providerLabel={providerLabel} /></div>}<div className="rounded-xl border border-brand-purple/10 p-4"><div className="flex items-center justify-between gap-3"><div><h3 className="text-sm font-semibold text-brand-purple">Selected provider</h3><p className="mt-1 text-xs text-ink-700/60">{providerLabel} · {llmProvider}</p></div><StatusPill status={llmOn || byokActive ? "configured" : "live_gated"} /></div>{configIssues.length > 0 && <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-xs text-amber-700"><CircleAlert size={15} className="mt-0.5 shrink-0" /><span>{configIssues.join("; ")}</span></div>}</div></div>}

          {tab === "integrations" && <div className="space-y-4"><div className="grid gap-3 sm:grid-cols-3">{integrations.map((integration) => <div key={integration.integration_id} className="rounded-xl border border-brand-purple/10 p-3"><div className="flex items-center gap-2 text-brand-purple"><Link2 size={14} /><span className="text-xs font-semibold">{integration.label}</span></div><div className="mt-2"><StatusPill status={integration.status} /></div><p className="mt-2 text-[11px] leading-relaxed text-ink-700/60">{integration.detail}</p>{integration.system_ids?.length ? <div className="mt-2 space-y-1">{integration.system_ids.map((systemId) => <div key={systemId} className="rounded bg-brand-cream/60 px-2 py-1 text-[10px] font-medium text-ink-700/70">{systemId.replaceAll("_", " ")}</div>)}</div> : null}</div>)}</div><div className="rounded-xl border border-brand-purple/10 p-4"><h3 className="flex items-center gap-2 text-sm font-semibold text-brand-purple"><Network size={15} /> Certified routing examples</h3><div className="mt-3 space-y-2">{routeCards.length === 0 ? <p className="text-xs text-ink-700/60">No routing snapshot available.</p> : routeCards.map((route) => <div key={route.task_type} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-brand-cream/40 px-3 py-2 text-xs"><span className="font-medium text-ink-800">{route.task_type.replaceAll("_", " ")}</span><span className="text-ink-700/60">{route.selected_provider}</span><StatusPill status={route.status} /></div>)}</div></div><div className="rounded-xl border border-brand-purple/10 p-4"><h3 className="flex items-center gap-2 text-sm font-semibold text-brand-purple"><Database size={15} /> Operational runtime</h3><div className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2"><RuntimeCapability title="Single orchestration" detail="One route decision exposes model, serving path, cost tier, cache state, certification, and human review." /><RuntimeCapability title="Memory & retention" detail="SQLite task history, encrypted settings, append-only audit events, and bounded semantic cache." /><RuntimeCapability title="Safety & recovery" detail="RBAC, PII redaction, prompt-injection blocking, HITL gates, deterministic fallback, and budget circuit breakers." /><RuntimeCapability title="Evaluation & observability" detail="Golden behavior tests, contract validation, cost ledger, capability evidence, and privacy-safe tracing." /></div></div><div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 text-xs text-amber-800"><div className="flex items-center gap-2 font-semibold"><CircleAlert size={15} /> Live integration boundary</div><p className="mt-1 leading-relaxed">Deterministic execution and orchestration controls are proven locally. Live Fireworks, AMD/Gemma, and LangSmith require credentials or runtime evidence.</p></div></div>}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-brand-purple/10 bg-brand-cream/30 px-5 py-3"><div className="flex items-center gap-2 text-xs">{saveState === "saved" && <span className="text-green-700">Saved to database</span>}{saveState === "error" && <span className="text-red-700">Save failed</span>}{saveState === "saving" && <span className="text-brand-purple">Saving…</span>}</div><div className="flex items-center gap-2"><button type="button" onClick={reset} disabled={saveState === "saving"} className="inline-flex items-center gap-2 rounded-lg border border-brand-purple/15 px-3 py-2 text-xs font-semibold text-ink-700/70 hover:bg-white disabled:opacity-50"><RotateCcw size={14} /> Reset defaults</button><button type="button" onClick={save} disabled={saveState === "saving" || offline} className="inline-flex items-center gap-2 rounded-lg bg-brand-purple px-4 py-2 text-xs font-semibold text-white hover:bg-brand-purple/90 disabled:opacity-50"><Save size={14} /> Save settings</button></div></footer>
      </section>
    </div>
  );
}

function RangeControl({ label, value, min, max, step, display, onChange }: { label: string; value: number; min: number; max: number; step: number; display: string; onChange: (value: number) => void }) {
  return <label className="block text-xs font-medium text-ink-700/70"><span className="flex items-center justify-between"><span>{label}</span><strong className="text-brand-purple">{display}</strong></span><input type="range" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} className="mt-2 w-full accent-brand-purple" /></label>;
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="flex items-center justify-between gap-3 rounded-lg bg-brand-cream/50 px-3 py-3 text-xs font-medium text-ink-700/75"><span>{label}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="h-4 w-4 accent-brand-purple" /></label>;
}

function RuntimeCapability({ title, detail }: { title: string; detail: string }) {
  return <div className="rounded-lg bg-brand-cream/45 p-3"><div className="font-semibold text-brand-purple">{title}</div><p className="mt-1 leading-relaxed text-ink-700/60">{detail}</p></div>;
}
