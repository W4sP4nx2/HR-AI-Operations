"use client";

/**
 * Launchpad — open-access landing card.
 *
 * A visitor picks a starting **workspace role** (which mints a scoped JWT)
 * and lands straight in the app; the sidebar "View as" switcher then lets them
 * swap roles in real time. The **BYOK affordance row** is surfaced here so
 * evaluators immediately see the zero-data-retention "use your own key" sandbox.
 *
 * Shown only in open-access mode (AUTH_ENFORCE off). Enforced deployments fall back to
 * the email/password LoginScreen.
 */

import { useState } from "react";
import { Activity, User, BarChart3, ShieldCheck, Crown, ArrowRight, Loader2 } from "lucide-react";
import { useAuth } from "./AuthContext";
import ByokControl from "../components/ByokControl";
import { useSystemStatus } from "../hooks/useSystemStatus";
import type { Role } from "../../lib/api";

const PERSONAS: { role: Role; label: string; blurb: string; icon: React.ReactNode }[] = [
  { role: "viewer", label: "Employee", blurb: "Self-service chat assistant", icon: <User size={18} /> },
  { role: "analyst", label: "HR Analyst", blurb: "Fleet · Cases · Screener · Analytics", icon: <BarChart3 size={18} /> },
  { role: "manager", label: "HR Manager", blurb: "+ Policies · Approvals · Audit", icon: <ShieldCheck size={18} /> },
  { role: "admin", label: "Admin", blurb: "Full operator console", icon: <Crown size={18} /> },
];

export default function Launchpad() {
  const { switchRole } = useAuth();
  const { byokSupported, llmProvider } = useSystemStatus();
  const [busy, setBusy] = useState<Role | null>(null);
  const [error, setError] = useState<string | null>(null);
  const providerLabel =
    llmProvider === "amd_vllm"
      ? "AMD/vLLM Gemma"
      : llmProvider === "fireworks" || llmProvider === "unknown"
        ? "Fireworks"
        : llmProvider;

  const enter = async (role: Role) => {
    setBusy(role);
    setError(null);
    try {
      await switchRole(role);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-purple p-4">
      <div className="w-full max-w-lg rounded-3xl bg-white p-8 shadow-2xl">
        <div className="mb-1 flex items-center gap-2 text-lg font-semibold text-brand-purple">
          <Activity size={22} className="text-brand-magenta" />
          HR AI Command Center
        </div>
        <p className="mb-3 text-sm text-ink-700/60">
          A safe, audited AI layer for HR. Pick a workspace role — no login, no setup.
        </p>

        {/* Guardrails showcase — the safety posture as a feature, not fine print. */}
        <div
          className="mb-6 flex flex-wrap items-center gap-1.5"
          title="Answers are grounded only in your loaded policies; off-topic and jailbreak attempts are refused; PII is redacted before any write; every action is audited."
        >
          <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-[11px] font-semibold text-green-700">
            <ShieldCheck size={11} /> Strict guardrails active
          </span>
          <span className="rounded-full bg-brand-purple/10 px-2 py-0.5 text-[10px] font-medium text-brand-purple">
            Grounded answers
          </span>
          <span className="rounded-full bg-brand-purple/10 px-2 py-0.5 text-[10px] font-medium text-brand-purple">
            Jailbreak-resistant
          </span>
          <span className="rounded-full bg-brand-purple/10 px-2 py-0.5 text-[10px] font-medium text-brand-purple">
            PII redacted
          </span>
          <span className="rounded-full bg-brand-purple/10 px-2 py-0.5 text-[10px] font-medium text-brand-purple">
            Fully audited
          </span>
        </div>

        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-700/50">
          Enter as
        </p>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          {PERSONAS.map((p) => (
            <button
              key={p.role}
              onClick={() => enter(p.role)}
              disabled={busy !== null}
              className="group flex items-center gap-3 rounded-2xl border border-brand-purple/15 bg-white p-3.5 text-left transition hover:border-brand-magenta hover:bg-brand-cream/40 disabled:opacity-60"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-purple/10 text-brand-purple">
                {busy === p.role ? <Loader2 size={18} className="animate-spin" /> : p.icon}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1 font-semibold text-brand-purple">
                  {p.label}
                  <ArrowRight size={13} className="opacity-0 transition group-hover:opacity-100" />
                </span>
                <span className="block truncate text-[11px] text-ink-700/55">{p.blurb}</span>
              </span>
            </button>
          ))}
        </div>

        {error && <p className="mt-3 text-xs text-red-500">{error}</p>}

        {byokSupported ? (
          /* BYOK affordance row — teaches the secure, zero-retention sandbox up front. */
          <div className="mt-6 flex items-center justify-between gap-3 rounded-2xl border border-brand-purple/10 bg-brand-cream/40 p-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-brand-purple">
                Bring your own {providerLabel} key
              </p>
              <p className="text-[11px] leading-snug text-ink-700/55">
                Optional — get real LLM answers. Used per-request, <strong>never stored</strong>.
                Runs fully without one in deterministic mode.
              </p>
            </div>
            <ByokControl placement="up" providerLabel={providerLabel} />
          </div>
        ) : (
          <div className="mt-6 rounded-2xl border border-brand-purple/10 bg-brand-cream/40 p-3">
            <p className="text-sm font-medium text-brand-purple">AMD-hosted Gemma route</p>
            <p className="text-[11px] leading-snug text-ink-700/55">
              The backend authenticates to private vLLM with a server-managed service key.
              Browser API keys are disabled for this route.
            </p>
          </div>
        )}

        <p className="mt-5 text-center text-[11px] text-ink-700/40">
          Open access · roles are advisory · switch roles anytime with “View as”.
        </p>
      </div>
    </div>
  );
}
