"use client";

import {
  ArrowRight,
  BarChart3,
  Boxes,
  CheckSquare,
  ClipboardList,
  CheckCircle2,
  Clock3,
  FileCheck2,
  FileText,
  Gauge,
  KeyRound,
  MessageCircle,
  ScanSearch,
  UserRoundCheck,
} from "lucide-react";
import ByokControl from "./ByokControl";

type DemoWalkthroughProps = {
  byokSupported: boolean;
  byokActive: boolean;
  onByokActiveChange: (active: boolean) => void;
  providerLabel: string;
  onOpenChat: (prompt: string) => void;
  onOpenCases: () => void;
  onOpenPolicies: () => void;
  onOpenApprovals: () => void;
  onOpenAudit: () => void;
  onOpenCommand: () => void;
  onOpenScreener: () => void;
  onOpenAttrition: () => void;
  onOpenAnalytics: () => void;
};

const POLICY_PROMPT = "How many vacation days do I get?";
const TRIAGE_PROMPT = "Payroll fails today, urgent! Please triage this case.";

export default function DemoWalkthrough({
  byokSupported,
  byokActive,
  onByokActiveChange,
  providerLabel,
  onOpenChat,
  onOpenCases,
  onOpenPolicies,
  onOpenApprovals,
  onOpenAudit,
  onOpenCommand,
  onOpenScreener,
  onOpenAttrition,
  onOpenAnalytics,
}: DemoWalkthroughProps) {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <section className="rounded-3xl bg-brand-purple px-6 py-7 text-white shadow-lg sm:px-8 sm:py-9">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-peach">Govern.ai · end-to-end product walkthrough</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">Run a governed HR workflow end to end.</h2>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-white/75">
              Move from grounded Chat and human-reviewed cases through governance, multimodal screening, retention risk, and operating evidence.
            </p>
          </div>
          <div className="rounded-2xl border border-white/15 bg-white/10 px-4 py-3 text-right">
            <div className="text-[10px] uppercase tracking-[0.16em] text-white/55">Demo status</div>
            <div className="mt-1 flex items-center justify-end gap-2 text-sm font-semibold">
              <span className={`h-2 w-2 rounded-full ${byokActive ? "bg-emerald-300" : "bg-brand-peach"}`} />
              {byokActive ? "Fireworks live" : "Local demo ready"}
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-purple/10 text-brand-purple">
              <KeyRound size={18} />
            </span>
            <div>
              <h3 className="text-sm font-semibold text-brand-purple">1. Confirm the runtime route</h3>
              <p className="mt-1 max-w-xl text-xs leading-relaxed text-ink-700/60">
                {byokSupported
                  ? `Use your ${providerLabel} key for this tab only. It is verified before the first model request and never saved by the app.`
                  : "This environment is running the local deterministic route. The same walkthrough remains available without a provider key."}
              </p>
            </div>
          </div>
          {byokSupported && (
            <ByokControl onActiveChange={onByokActiveChange} providerLabel={providerLabel} />
          )}
        </div>
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-brand-magenta">Core operator sequence</p>
            <h3 className="mt-1 text-lg font-semibold text-brand-purple">Chat → Cases → Policies → Approvals → Audit</h3>
          </div>
          <p className="text-xs text-ink-700/50">Use these actions in order during the demo.</p>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
        <StepCard
          number="2"
          icon={<MessageCircle size={18} />}
          title="Chat: ground + triage"
          detail="Ask an employee question, then switch to an urgent payroll ticket to show governed escalation."
          action="Try policy question"
          secondaryAction="Run urgent triage"
          onClick={() => onOpenChat(POLICY_PROMPT)}
          onSecondaryClick={() => onOpenChat(TRIAGE_PROMPT)}
        />
        <StepCard
          number="3"
          icon={<ClipboardList size={18} />}
          title="Cases: resolve the escalation"
          detail="Open the queue, inspect the new case, and resolve it to create a visible human checkpoint."
          action="Open case queue"
          onClick={onOpenCases}
        />
        <StepCard
          number="4"
          icon={<FileText size={18} />}
          title="Policies: inspect sources"
          detail="Show the loaded policy documents and the evidence that grounds the employee answer."
          action="Review policies"
          onClick={onOpenPolicies}
        />
        <StepCard
          number="5"
          icon={<CheckSquare size={18} />}
          title="Approvals: review the gate"
          detail="Open the human approval queue and make the decision point explicit before action continues."
          action="Open approvals"
          onClick={onOpenApprovals}
        />
        <StepCard
          number="6"
          icon={<FileCheck2 size={18} />}
          title="Audit: prove the decision"
          detail="Show the case status, agent trace, human intervention, and final ledger event."
          action="Open audit trail"
          onClick={onOpenAudit}
        />
        </div>
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-brand-magenta">Advanced tools</p>
            <h3 className="mt-1 text-lg font-semibold text-brand-purple">Decision queue → Screener → Batch status → Attrition → Analytics</h3>
          </div>
          <p className="text-xs text-ink-700/50">Continue into the operator workbench after the governed decision.</p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <StepCard
            number="7"
            icon={<Boxes size={18} />}
            title="Command: act on priority work"
            detail="Open the cases and approvals that need a person, then follow the linked evidence into the governed decision."
            action="Open decision queue"
            onClick={onOpenCommand}
          />
          <StepCard
            number="8"
            icon={<ScanSearch size={18} />}
            title="Screener: interactive review"
            detail="Load the sample and screen it interactively. Image/PDF VLM is a separate Gemma capability and remains gated until deployed."
            action="Screen sample resume"
            onClick={onOpenScreener}
          />
          <StepCard
            number="9"
            icon={<Clock3 size={18} />}
            title="Batch: inspect readiness"
            detail="Use Analytics to distinguish interactive screens from a real Fireworks Batch job. No batch job is simulated."
            action="Open batch status"
            onClick={onOpenAnalytics}
          />
          <StepCard
            number="10"
            icon={<Gauge size={18} />}
            title="Attrition: spot risk"
            detail="Explore employee risk signals and see where a manager should investigate before acting."
            action="Open attrition"
            onClick={onOpenAttrition}
          />
          <StepCard
            number="11"
            icon={<BarChart3 size={18} />}
            title="Analytics: measure the system"
            detail="Close with throughput, case outcomes, provider-response usage, and control evidence."
            action="Open operating metrics"
            onClick={onOpenAnalytics}
          />
        </div>
      </section>

      <section className="grid gap-4 rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm sm:grid-cols-3 sm:p-6">
        <ProofItem icon={<FileCheck2 size={16} />} title="Grounded" detail="Policy citations stay attached to the answer." />
        <ProofItem icon={<UserRoundCheck size={16} />} title="Human-led" detail="Urgent work stops at a reviewable human checkpoint." />
        <ProofItem icon={<CheckCircle2 size={16} />} title="Auditable" detail="Every material action lands in the ledger." />
      </section>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-purple/10 bg-brand-cream/55 px-4 py-3 text-xs text-ink-700/65">
        <span>Workflow rule: resolve the escalated case before opening Audit so the human checkpoint is visible.</span>
        <button type="button" onClick={onOpenAudit} className="inline-flex items-center gap-1 font-semibold text-brand-purple hover:text-brand-magenta">
          Jump to audit <ArrowRight size={13} />
        </button>
      </div>
    </div>
  );
}

function StepCard({
  number,
  icon,
  title,
  detail,
  action,
  secondaryAction,
  onClick,
  onSecondaryClick,
}: {
  number: string;
  icon: React.ReactNode;
  title: string;
  detail: string;
  action: string;
  secondaryAction?: string;
  onClick: () => void;
  onSecondaryClick?: () => void;
}) {
  return (
    <article className="flex min-h-[220px] flex-col rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between text-brand-purple">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-purple/10">{icon}</span>
        <span className="text-xs font-semibold text-ink-700/35">STEP {number}</span>
      </div>
      <h3 className="mt-5 text-sm font-semibold text-brand-purple">{title}</h3>
      <p className="mt-2 flex-1 text-xs leading-relaxed text-ink-700/60">{detail}</p>
      <button type="button" onClick={onClick} className="mt-5 inline-flex items-center justify-center gap-2 rounded-xl bg-brand-purple px-3 py-2.5 text-xs font-semibold text-white transition hover:bg-brand-purple/90">
        {action} <ArrowRight size={14} />
      </button>
      {secondaryAction && onSecondaryClick && (
        <button type="button" onClick={onSecondaryClick} className="mt-2 inline-flex items-center justify-center gap-2 rounded-xl border border-brand-purple/15 px-3 py-2 text-xs font-semibold text-brand-purple transition hover:bg-brand-cream/70">
          {secondaryAction} <ArrowRight size={13} />
        </button>
      )}
    </article>
  );
}

function ProofItem({ icon, title, detail }: { icon: React.ReactNode; title: string; detail: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">{icon}</span>
      <div>
        <div className="text-xs font-semibold text-brand-purple">{title}</div>
        <p className="mt-1 text-xs leading-relaxed text-ink-700/55">{detail}</p>
      </div>
    </div>
  );
}
