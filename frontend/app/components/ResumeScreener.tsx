"use client";

/**
 * ResumeScreener — paste a job description + a candidate resume, get a
 * structured, **demographically-blinded** fit assessment from the resume
 * screener agent: a 0–100 score, hire / no-hire recommendation, the reasoning,
 * and matched vs. missing skills.
 *
 * Mission alignment: this is **decision-support, never an auto-reject**. The UI
 * makes that explicit (blinding badge, "advisory" framing, needs-review flag)
 * and every screen is written to the audit log by the backend.
 */

import { useRef, useState } from "react";
import {
  Loader2,
  ScanSearch,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Check,
  X,
  UploadCloud,
} from "lucide-react";
import { api, type ResumeScreenResult } from "../../lib/api";

// Client pre-flight: catch bad files before they ever hit the network.
const MAX_RESUME_BYTES = 2 * 1024 * 1024; // 2 MB
const PDF_MAGIC = "%PDF-";

const SAMPLE_JD =
  "Senior Backend Engineer. Required: Python, FastAPI, PostgreSQL, async programming, " +
  "Docker, REST API design, unit testing. Nice to have: Kubernetes, RAG, vector databases.";
const SAMPLE_RESUME =
  "Backend engineer with 6 years building Python services. Shipped FastAPI microservices " +
  "backed by PostgreSQL with async SQLAlchemy. Containerised everything with Docker and wrote " +
  "extensive pytest suites. Designed REST APIs used by web and mobile clients. Recently built a " +
  "retrieval-augmented generation feature over a vector database.";

function scoreColor(score: number): string {
  if (score >= 75) return "text-green-600";
  if (score >= 50) return "text-amber-600";
  return "text-red-500";
}

function ScoreRing({ score }: { score: number }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const stroke = score >= 75 ? "#16a34a" : score >= 50 ? "#d97706" : "#ef4444";
  return (
    <div className="relative h-32 w-32 shrink-0">
      <svg viewBox="0 0 120 120" className="h-32 w-32 -rotate-90">
        <circle cx="60" cy="60" r={r} fill="none" stroke="#00000010" strokeWidth="10" />
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          stroke={stroke}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-3xl font-bold ${scoreColor(score)}`}>{score}</span>
        <span className="text-[10px] uppercase tracking-wide text-ink-700/50">fit score</span>
      </div>
    </div>
  );
}

function SkillChips({ skills, kind }: { skills: string[]; kind: "matched" | "missing" }) {
  if (!skills.length)
    return <p className="text-xs text-ink-700/40">{kind === "matched" ? "None matched" : "None missing"}</p>;
  const cls =
    kind === "matched"
      ? "border-green-200 bg-green-50 text-green-700"
      : "border-red-200 bg-red-50 text-red-600";
  const Icon = kind === "matched" ? Check : X;
  return (
    <div className="flex flex-wrap gap-1.5">
      {skills.map((s) => (
        <span key={s} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>
          <Icon size={10} />
          {s}
        </span>
      ))}
    </div>
  );
}

export default function ResumeScreener() {
  const [jd, setJd] = useState("");
  const [resume, setResume] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ResumeScreenResult | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const screen = async () => {
    if (!jd.trim() || !resume.trim() || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.screenResume(jd, resume));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // Drag-drop / file-picker path: client pre-flight guards → upload → score.
  const handleFile = async (file: File) => {
    setError(null);
    setResult(null);
    const sizeMB = file.size / 1024 / 1024;
    if (file.size > MAX_RESUME_BYTES) {
      setError(`File too large (${sizeMB.toFixed(1)} MB). Resumes must be under 2 MB.`);
      return;
    }
    // Magic-byte check: a real PDF starts with "%PDF-".
    const head = new TextDecoder().decode(new Uint8Array(await file.slice(0, 5).arrayBuffer()));
    if (head !== PDF_MAGIC) {
      setError("That file isn't a PDF (missing %PDF- signature).");
      return;
    }
    setUploading(true);
    setLog([
      `[OK] File size verified (${sizeMB.toFixed(1)} MB)`,
      "[OK] PDF structure signature authenticated.",
      "[RUNNING] Splitting career nodes and parsing layout boundaries…",
    ]);
    try {
      const env = await api.triggerUpload("resume_screener_agent", {
        file,
        jobDescription: jd,
      });
      if (env.success && env.data) {
        const data = env.data as { result?: ResumeScreenResult };
        const r = (data.result ?? data) as ResumeScreenResult;
        setLog((l) => [...l.slice(0, 2), "[OK] Layout parsed · candidate scored."]);
        setResult(r);
      } else {
        setError(env.error ?? "screening failed");
        setLog([]);
      }
    } catch (e) {
      setError((e as Error).message);
      setLog([]);
    } finally {
      setUploading(false);
    }
  };

  const hire = result?.recommendation?.toLowerCase() === "hire";
  const keywordFallback = result?.skill_audit_mode === "keyword_fallback";

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {/* Inputs */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-brand-purple">Candidate screening</h3>
          <button
            onClick={() => { setJd(SAMPLE_JD); setResume(SAMPLE_RESUME); }}
            className="text-xs text-ink-700/50 hover:text-brand-magenta"
          >
            Load sample
          </button>
        </div>

        <label className="block">
          <span className="mb-1 block text-xs font-medium uppercase text-ink-700/60">Job description</span>
          <textarea
            value={jd}
            onChange={(e) => setJd(e.target.value)}
            rows={6}
            placeholder="Paste the role's requirements…"
            className="w-full resize-y rounded-xl border border-brand-purple/15 px-3 py-2 text-sm outline-none focus:border-brand-magenta"
          />
          <InputShieldBadge text={jd} minWords={3} />
        </label>

        <div>
          <span className="mb-1 block text-xs font-medium uppercase text-ink-700/60">Candidate resume</span>
          {/* Drop zone — layout-aware PDF parsing on the backend (two-column safe). */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const f = e.dataTransfer.files?.[0];
              if (f) handleFile(f);
            }}
            onClick={() => fileRef.current?.click()}
            className={`mb-2 flex cursor-pointer items-center justify-center gap-2 rounded-xl border-2 border-dashed px-3 py-4 text-xs transition ${
              dragOver
                ? "border-brand-magenta bg-brand-magenta/5 text-brand-magenta"
                : "border-brand-purple/20 text-ink-700/60 hover:border-brand-magenta"
            }`}
          >
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
            />
            <UploadCloud size={16} />
            Drop a resume PDF here, or click to browse — or paste text below
          </div>
          <textarea
            value={resume}
            onChange={(e) => setResume(e.target.value)}
            rows={6}
            placeholder="…or paste the candidate's resume text"
            className="w-full resize-y rounded-xl border border-brand-purple/15 px-3 py-2 text-sm outline-none focus:border-brand-magenta"
          />
          <InputShieldBadge text={resume} minWords={8} />
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={screen}
            disabled={busy || !jd.trim() || !resume.trim()}
            className="flex items-center gap-2 rounded-xl bg-brand-magenta px-4 py-2.5 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-50"
          >
            {busy ? <Loader2 size={15} className="animate-spin" /> : <ScanSearch size={15} />}
            Screen candidate
          </button>
          <span className="inline-flex items-center gap-1 text-[11px] text-ink-700/50">
            <ShieldCheck size={12} className="text-brand-purple" />
            Names &amp; protected attributes are blinded before scoring
          </span>
        </div>
        {error && <p className="text-sm text-red-500">{error}</p>}
      </div>

      {/* Result */}
      <div className="rounded-2xl border border-brand-purple/10 bg-white p-6 shadow-sm">
        {uploading ? (
          <div className="font-mono text-xs">
            <p className="mb-3 flex items-center gap-2 text-sm font-semibold text-brand-purple">
              <Loader2 size={15} className="animate-spin" /> Extracting career structure…
            </p>
            <div className="space-y-1.5 rounded-lg bg-ink-900 p-3 text-[11px] leading-relaxed">
              {log.map((line, i) => (
                <div
                  key={i}
                  className={line.startsWith("[RUNNING]") ? "text-amber-300" : "text-green-300"}
                >
                  {line}
                </div>
              ))}
            </div>
          </div>
        ) : !result ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 py-16 text-center text-ink-700/50">
            <ScanSearch size={36} className="text-brand-magenta/40" />
            <p className="text-sm">Run a screen to see the fit score, recommendation and skill match.</p>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex items-center gap-5">
              <ScoreRing score={result.score} />
              <div className="space-y-2">
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold ${
                    keywordFallback
                      ? "bg-amber-100 text-amber-800"
                      : hire
                        ? "bg-green-100 text-green-700"
                        : "bg-red-100 text-red-600"
                  }`}
                >
                  {keywordFallback ? (
                    <AlertTriangle size={15} />
                  ) : hire ? (
                    <CheckCircle2 size={15} />
                  ) : (
                    <XCircle size={15} />
                  )}
                  {keywordFallback
                    ? "Review required: fallback mode"
                    : hire
                      ? "Recommend: advance"
                      : "Recommend: do not advance"}
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {result.blinded && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-brand-purple/10 px-2 py-0.5 text-[11px] font-medium text-brand-purple">
                      <ShieldCheck size={11} /> Demographics blinded
                    </span>
                  )}
                  {result._mode === "degraded" && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                      basic mode
                    </span>
                  )}
                  {result.needs_review && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                      <AlertTriangle size={11} /> Needs review
                    </span>
                  )}
                  {/* Honesty signal: a keyword-only score is blind to negation —
                      never let it look like a context-validated one. */}
                  {result.skill_audit_mode === "validated" ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-[11px] font-medium text-green-700">
                      <ShieldCheck size={11} /> Context-validated
                    </span>
                  ) : (
                    result.skill_audit_mode === "keyword_fallback" && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-ink-700/10 px-2 py-0.5 text-[11px] font-medium text-ink-700/70">
                        <AlertTriangle size={11} /> Keyword match — context not verified
                      </span>
                    )
                  )}
                </div>
              </div>
            </div>

            <div>
              <h4 className="mb-1 text-xs font-medium uppercase text-ink-700/60">Reasoning</h4>
              <p className="text-sm leading-relaxed text-ink-800">{result.reasoning}</p>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <h4 className="mb-2 text-xs font-medium uppercase text-ink-700/60">
                  Matched skills ({result.matched_skills.length})
                </h4>
                <SkillChips skills={result.matched_skills} kind="matched" />
              </div>
              <div>
                <h4 className="mb-2 text-xs font-medium uppercase text-ink-700/60">
                  Missing skills ({result.missing_skills.length})
                </h4>
                <SkillChips skills={result.missing_skills} kind="missing" />
              </div>
            </div>

            {result.unverified_skills && result.unverified_skills.length > 0 && (
              <div>
                <h4 className="mb-2 text-xs font-medium uppercase text-amber-700">
                  Discounted — keyword present, context not demonstrated (
                  {result.unverified_skills.length})
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {result.unverified_skills.map((s) => (
                    <span
                      key={s}
                      className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700 line-through"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {result.consistency_flags && result.consistency_flags.length > 0 && (
              <div className="rounded-lg border border-amber-300/60 bg-amber-50 p-3">
                <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-amber-700">
                  Timeline checks ({result.consistency_flags.length})
                </h4>
                <ul className="space-y-1">
                  {result.consistency_flags.map((f, i) => (
                    <li key={i} className="text-[12px] leading-snug text-amber-800">
                      • {f}
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[10px] italic text-amber-700/70">
                  Advisory data-integrity flags — they do not affect the score. Employment gaps are
                  intentionally never flagged.
                </p>
              </div>
            )}

            <p className="border-t border-brand-purple/10 pt-3 text-[11px] text-ink-700/40">
              Decision-support only — a human recruiter makes the final call. This screen was written
              to the audit log.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/** Pre-flight input shield — a live character/word counter + validation badge.
 *  Mirrors the backend's "insufficient input" guard and the defensive input
 *  truncation, so a recruiter sees the boundary before dispatching. */
function InputShieldBadge({ text, minWords }: { text: string; minWords: number }) {
  const chars = text.length;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const MAX = 20000; // mirrors backend MAX_TEXT_CHARS (sanitize_text cap)

  let state: { label: string; cls: string };
  if (chars === 0) state = { label: "awaiting input", cls: "text-ink-700/40" };
  else if (words < minWords)
    state = { label: `too short — need ≥ ${minWords} words for a reliable read`, cls: "text-amber-600" };
  else if (chars > MAX)
    state = { label: `over ${MAX.toLocaleString()} chars — will be truncated`, cls: "text-amber-600" };
  else state = { label: "ready", cls: "text-green-600" };

  return (
    <div className="mt-1 flex items-center justify-between text-[10px]">
      <span className="text-ink-700/40">
        {chars.toLocaleString()} chars · {words} words
      </span>
      <span className={`flex items-center gap-1 font-medium ${state.cls}`}>
        <ShieldCheck size={11} /> {state.label}
      </span>
    </div>
  );
}
