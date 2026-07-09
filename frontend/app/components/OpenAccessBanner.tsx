"use client";

/**
 * OpenAccessBanner — full-width strip shown when auth enforcement is off.
 *
 * Tells a reviewer three things at a glance:
 *   1. No login or password is required in the open workspace.
 *   2. Roles are advisory; use the sidebar "View as" switcher to change workspace role.
 *   3. Seed status — how many policies / cases are loaded, and the LLM mode,
 *      so it's obvious whether the system has data to work with.
 */

import { useEffect, useState } from "react";
import { Sparkles, Database, KeyRound, Cpu } from "lucide-react";
import { api } from "../../lib/api";
import { useAuth } from "../auth/AuthContext";

export default function OpenAccessBanner({ llmOn }: { llmOn: boolean }) {
  const [policies, setPolicies] = useState<number | null>(null);
  const [cases, setCases] = useState<number | null>(null);
  const { isAuthed, user } = useAuth();

  useEffect(() => {
    let mounted = true;
    const loadCounts = () =>
      Promise.allSettled([api.policies(), api.cases()]).then(([policyResult, caseResult]) => {
        if (!mounted) return;
        if (policyResult.status === "fulfilled") setPolicies(policyResult.value.length);
        if (caseResult.status === "fulfilled") setCases(caseResult.value.length);
      });

    void loadCounts();
    const retry = window.setTimeout(loadCounts, 750);
    const refresh = window.setInterval(loadCounts, 30_000);
    return () => {
      mounted = false;
      window.clearTimeout(retry);
      window.clearInterval(refresh);
    };
  }, [isAuthed, user?.id, user?.role]);

  const seeded = policies !== null && policies > 0;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-brand-purple/10 bg-brand-purple px-6 py-2 text-xs text-brand-cream">
      <span className="inline-flex items-center gap-1.5 font-semibold">
        <Sparkles size={13} className="text-brand-peach" />
        Open access
      </span>
      <span className="inline-flex items-center gap-1.5 text-brand-cream/80">
        <KeyRound size={12} /> No login needed — use <strong className="font-semibold">View&nbsp;as</strong> to switch roles
      </span>
      <span className="inline-flex items-center gap-1.5 text-brand-cream/80">
        <Cpu size={12} /> {llmOn ? "AI mode" : "Basic mode (no API key, deterministic)"}
      </span>
      <span className="ml-auto inline-flex items-center gap-1.5">
        <Database size={12} className={seeded ? "text-green-300" : "text-brand-peach"} />
        {policies === null && cases === null ? (
          "Data status unavailable"
        ) : seeded ? (
          <span className="text-brand-cream/90">
            <strong className="font-semibold">{policies}</strong> policies ·{" "}
            {cases === null ? (
              "cases unavailable"
            ) : (
              <>
                <strong className="font-semibold">{cases}</strong> cases loaded
              </>
            )}
          </span>
        ) : policies === null ? (
          <span className="text-brand-cream/90">
            <strong className="font-semibold">{cases}</strong> cases loaded
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
