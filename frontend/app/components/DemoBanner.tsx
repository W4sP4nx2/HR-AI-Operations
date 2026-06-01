"use client";

/**
 * DemoBanner — full-width strip shown only in advisory/demo mode.
 *
 * Tells a reviewer three things at a glance:
 *   1. This is a demo — no login or password is required.
 *   2. Roles are advisory; use the sidebar "View as" switcher to change persona.
 *   3. Seed status — how many policies / cases are loaded, and the LLM mode,
 *      so it's obvious whether the system has data to work with.
 */

import { useEffect, useState } from "react";
import { Sparkles, Database, KeyRound, Cpu } from "lucide-react";
import { api } from "../../lib/api";

export default function DemoBanner({ llmOn }: { llmOn: boolean }) {
  const [policies, setPolicies] = useState<number | null>(null);
  const [cases, setCases] = useState<number | null>(null);

  useEffect(() => {
    let mounted = true;
    Promise.all([api.policies().catch(() => []), api.cases().catch(() => [])]).then(
      ([p, c]) => {
        if (!mounted) return;
        setPolicies(p.length);
        setCases(c.length);
      }
    );
    return () => {
      mounted = false;
    };
  }, []);

  const seeded = (policies ?? 0) > 0;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-brand-purple/10 bg-brand-purple px-6 py-2 text-xs text-brand-cream">
      <span className="inline-flex items-center gap-1.5 font-semibold">
        <Sparkles size={13} className="text-brand-peach" />
        Demo mode
      </span>
      <span className="inline-flex items-center gap-1.5 text-brand-cream/80">
        <KeyRound size={12} /> No login needed — use <strong className="font-semibold">View&nbsp;as</strong> to switch roles
      </span>
      <span className="inline-flex items-center gap-1.5 text-brand-cream/80">
        <Cpu size={12} /> {llmOn ? "AI mode" : "Basic mode (no API key, deterministic)"}
      </span>
      <span className="ml-auto inline-flex items-center gap-1.5">
        <Database size={12} className={seeded ? "text-green-300" : "text-brand-peach"} />
        {policies === null ? (
          "Checking data…"
        ) : seeded ? (
          <span className="text-brand-cream/90">
            <strong className="font-semibold">{policies}</strong> policies ·{" "}
            <strong className="font-semibold">{cases ?? 0}</strong> cases loaded
          </span>
        ) : (
          <span className="text-brand-peach">
            No data — run <code className="rounded bg-white/10 px-1 font-mono">python -m scripts.seed_data</code>
          </span>
        )}
      </span>
    </div>
  );
}
