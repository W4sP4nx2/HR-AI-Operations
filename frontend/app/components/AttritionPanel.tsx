"use client";

/**
 * AttritionPanel — enter six job-related employee features, get an advisory
 * attrition-risk score, the top contributing factors (as a chart), and a
 * plain-English explanation.
 *
 * Mission alignment: this is **advisory only, never an automated adverse
 * decision**, and the model takes **no protected attributes** (race/gender/age)
 * — only the six job features below. The UI states both explicitly and flags
 * high-risk predictions for human bias review.
 */

import { useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { Loader2, Gauge, ShieldCheck, AlertTriangle, Info, Check, X } from "lucide-react";
import {
  api,
  type AttritionFeatures,
  type AttritionResult,
  type RetentionSuggestion,
} from "../../lib/api";

type FieldKey = keyof AttritionFeatures;

const FIELDS: { key: FieldKey; label: string; min: number; max: number; step: number; hint: string }[] = [
  { key: "tenure_months", label: "Tenure (months)", min: 0, max: 120, step: 1, hint: "Time at the company" },
  { key: "performance_score", label: "Performance (1–5)", min: 1, max: 5, step: 0.1, hint: "Last review rating" },
  { key: "absence_days", label: "Absence days / yr", min: 0, max: 30, step: 1, hint: "Unplanned absence" },
  { key: "last_promotion_months", label: "Since promotion (months)", min: 0, max: 60, step: 1, hint: "Time since last promotion" },
  { key: "salary_band", label: "Salary band (1–5)", min: 1, max: 5, step: 1, hint: "1 lowest · 5 highest" },
  { key: "manager_rating", label: "Manager rating (1–5)", min: 1, max: 5, step: 0.1, hint: "Manager satisfaction" },
];

// A neutral starting point (matches the backend defaults).
const DEFAULTS: AttritionFeatures = {
  tenure_months: 24,
  performance_score: 3,
  absence_days: 5,
  last_promotion_months: 12,
  salary_band: 3,
  manager_rating: 3,
};

const FACTOR_LABELS: Record<string, string> = {
  tenure_months: "Tenure",
  performance_score: "Performance",
  absence_days: "Absence",
  last_promotion_months: "Time since promotion",
  salary_band: "Salary band",
  manager_rating: "Manager rating",
  disengagement_index: "Slow-burn disengagement",
};

function baselinePosition(field: (typeof FIELDS)[number]): string {
  const value = DEFAULTS[field.key];
  const pct = ((value - field.min) / (field.max - field.min)) * 100;
  return `${Math.max(0, Math.min(100, pct))}%`;
}

function riskBand(score: number): { label: string; color: string; chip: string } {
  if (score >= 0.66) return { label: "High", color: "#ef4444", chip: "bg-red-100 text-red-600" };
  if (score >= 0.33) return { label: "Medium", color: "#d97706", chip: "bg-amber-100 text-amber-700" };
  return { label: "Low", color: "#16a34a", chip: "bg-green-100 text-green-700" };
}

export default function AttritionPanel() {
  const [f, setF] = useState<AttritionFeatures>(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AttritionResult | null>(null);
  const [baselineRisk, setBaselineRisk] = useState<number | null>(null);

  const set = (key: FieldKey, value: number) => setF((prev) => ({ ...prev, [key]: value }));

  const predict = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const prediction = await api.predictAttrition(f);
      setResult(prediction);
      setBaselineRisk((prev) => prev ?? prediction.attrition_risk_score);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const band = result ? riskBand(result.attrition_risk_score) : null;
  const factorData =
    result?.top_risk_factors.map((r) => ({
      name: FACTOR_LABELS[r.factor] ?? r.factor,
      contribution: Number((r.contribution * 100).toFixed(1)),
    })) ?? [];

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {/* Inputs */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-brand-purple">Employee signals</h3>
          <button onClick={() => setF(DEFAULTS)} className="text-xs text-ink-700/50 hover:text-brand-magenta">
            Reset
          </button>
        </div>

        <div className="space-y-3 rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
          {FIELDS.map((field) => (
            <label key={field.key} className="block">
              <div className="flex items-baseline justify-between">
                <span className="text-sm font-medium text-ink-800">{field.label}</span>
                <span className="font-mono text-sm text-brand-magenta">{f[field.key]}</span>
              </div>
              <input
                type="range"
                min={field.min}
                max={field.max}
                step={field.step}
                value={f[field.key]}
                onChange={(e) => set(field.key, Number(e.target.value))}
                className="mt-1 w-full accent-brand-magenta"
              />
              <div className="relative mt-1 h-3">
                <span
                  className="absolute top-0 h-3 w-px bg-brand-purple/35"
                  style={{ left: baselinePosition(field) }}
                  title={`Baseline: ${DEFAULTS[field.key]}`}
                />
                <span className="text-[11px] text-ink-700/40">{field.hint}</span>
              </div>
            </label>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={predict}
            disabled={busy}
            className="flex items-center gap-2 rounded-xl bg-brand-magenta px-4 py-2.5 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-50"
          >
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Gauge size={15} />}
            Predict risk
          </button>
          <span className="inline-flex items-center gap-1 text-[11px] text-ink-700/50">
            <ShieldCheck size={12} className="text-brand-purple" />
            No protected attributes used — six job signals only
          </span>
        </div>
        {error && <p className="text-sm text-red-500">{error}</p>}
      </div>

      {/* Result */}
      <div className="rounded-2xl border border-brand-purple/10 bg-white p-6 shadow-sm">
        {!result || !band ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 py-16 text-center text-ink-700/50">
            <Gauge size={36} className="text-brand-magenta/40" />
            <p className="text-sm">Adjust the signals and predict to see the advisory risk score.</p>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex items-center gap-5">
              <div className="flex h-28 w-28 shrink-0 flex-col items-center justify-center rounded-full border-8" style={{ borderColor: band.color }}>
                <span className="text-3xl font-bold" style={{ color: band.color }}>
                  {Math.round(result.attrition_risk_score * 100)}%
                </span>
                <span className="text-[10px] uppercase tracking-wide text-ink-700/50">risk</span>
              </div>
              <div className="space-y-2">
                <span className={`inline-block rounded-full px-3 py-1 text-sm font-semibold ${band.chip}`}>
                  {band.label} risk
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {result.advisory_only && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-brand-purple/10 px-2 py-0.5 text-[11px] font-medium text-brand-purple">
                      <Info size={11} /> Advisory only
                    </span>
                  )}
                  {result._mode === "degraded" && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">basic mode</span>
                  )}
                  {result.needs_review && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                      <AlertTriangle size={11} /> Human review advised
                    </span>
                  )}
                </div>
              </div>
            </div>

            {baselineRisk !== null && (
              <div className="rounded-lg border border-brand-purple/10 bg-brand-cream/60 p-3">
                <div className="mb-2 flex items-center justify-between text-[11px] font-medium text-ink-700/60">
                  <span>Snapshot baseline</span>
                  <span>
                    {Math.round(baselineRisk * 100)}% ·{" "}
                    {result.attrition_risk_score >= baselineRisk ? "+" : ""}
                    {Math.round((result.attrition_risk_score - baselineRisk) * 100)} pts
                  </span>
                </div>
                <div className="relative h-2 rounded-full bg-brand-purple/10">
                  <span
                    className="absolute -top-1 h-4 w-0.5 rounded-full bg-brand-purple"
                    style={{ left: `${Math.max(0, Math.min(100, baselineRisk * 100))}%` }}
                    title={`Baseline ${Math.round(baselineRisk * 100)}%`}
                  />
                  <span
                    className="absolute -top-1 h-4 w-4 -translate-x-1/2 rounded-full border-2 border-white shadow-sm"
                    style={{
                      left: `${Math.max(0, Math.min(100, result.attrition_risk_score * 100))}%`,
                      backgroundColor: band.color,
                    }}
                    title={`Current ${Math.round(result.attrition_risk_score * 100)}%`}
                  />
                </div>
              </div>
            )}

            <div>
              <h4 className="mb-2 text-xs font-medium uppercase text-ink-700/60">Top risk factors</h4>
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={factorData} layout="vertical" margin={{ left: 20, right: 16 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(value) => [String(value ?? ""), "contribution"]}
                  />
                  <Bar dataKey="contribution" radius={[0, 6, 6, 0]}>
                    {factorData.map((_, i) => (
                      <Cell key={i} fill={band.color} fillOpacity={1 - i * 0.25} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div>
              <h4 className="mb-1 text-xs font-medium uppercase text-ink-700/60">What this means</h4>
              <p className="text-sm leading-relaxed text-ink-800">{result.explanation}</p>
            </div>

            {result.retention_context && result.retention_context.length > 0 && (
              <div className="rounded-lg border border-brand-purple/20 bg-brand-purple/5 p-3">
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-purple">
                  Policy-grounded retention options
                </h4>
                <ul className="space-y-2.5">
                  {result.retention_context.map((s, i) => (
                    <RetentionItem key={i} suggestion={s} caseId={result.case_id} />
                  ))}
                </ul>
                <p className="mt-2 text-[10px] italic text-ink-700/50">
                  Composed from the Policy Q&amp;A engine on the top drivers. Decision-support only —
                  your accept/reject is recorded for human review, never to steer future predictions.
                </p>
              </div>
            )}

            <p className="border-t border-brand-purple/10 pt-3 text-[11px] text-ink-700/40">
              A prompt to start a supportive retention conversation — never an automated decision.
              This prediction was written to the audit log.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/** One retention suggestion with accept/reject capture (append-only feedback). */
function RetentionItem({
  suggestion,
  caseId,
}: {
  suggestion: RetentionSuggestion;
  caseId?: string;
}) {
  const [recorded, setRecorded] = useState<"accepted" | "rejected" | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async (action: "accepted" | "rejected") => {
    if (!caseId || busy) return;
    setBusy(true);
    try {
      await api.submitRetentionFeedback({
        case_id: caseId,
        suggestion_id: suggestion.factor,
        risk_driver: suggestion.factor,
        action_taken: action,
      });
      setRecorded(action);
    } catch {
      /* advisory capture — stay silent on failure */
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="text-[12px] leading-snug">
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium text-ink-800">{suggestion.suggestion}</p>
        {caseId &&
          (recorded ? (
            <span className="shrink-0 rounded-full bg-ink-700/10 px-2 py-0.5 text-[10px] font-medium text-ink-700/70">
              {recorded === "accepted" ? "Accepted" : "Rejected"}
            </span>
          ) : (
            <span className="flex shrink-0 gap-1">
              <button
                onClick={() => send("accepted")}
                disabled={busy}
                aria-label="Accept suggestion"
                className="rounded-md border border-green-300 p-1 text-green-700 hover:bg-green-50 disabled:opacity-50"
              >
                <Check size={13} />
              </button>
              <button
                onClick={() => send("rejected")}
                disabled={busy}
                aria-label="Reject suggestion"
                className="rounded-md border border-red-300 p-1 text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                <X size={13} />
              </button>
            </span>
          ))}
      </div>
      <p className="mt-0.5 text-ink-700/70">
        {suggestion.grounded ? (
          <>
            From <span className="italic">{suggestion.policy_query}</span>
            {suggestion.sources.length > 0 && (
              <span className="text-ink-700/50"> · {suggestion.sources.join(", ")}</span>
            )}
          </>
        ) : (
          <span className="text-amber-700">
            No specific policy located — handle via manual review.
          </span>
        )}
      </p>
    </li>
  );
}
