"use client";

/**
 * Govern.ai dashboard.
 *
 * Layout:
 *   - Left sidebar: navigation (Command, Cases, Analytics, Audit, Approvals).
 *   - Top bar: system health indicator + active agent count.
 *   - Main area: renders the active panel based on the selected nav item.
 *
 * The top bar uses a resilient live-status hook: WebSocket nudges plus HTTP
 * polling fallback, so active case counters keep moving through proxy drops.
 */

import { useEffect, useState } from "react";
import {
  Activity,
  Boxes,
  ClipboardList,
  BarChart3,
  ScrollText,
  CheckSquare,
  CircleDot,
  FileText,
  MessageCircle,
  ScanSearch,
  Gauge,
  ChevronDown,
  Sparkles,
  Settings,
  Menu,
  X,
} from "lucide-react";
import AgentFleet from "./components/AgentFleet";
import CaseFeed from "./components/CaseFeed";
import Analytics from "./components/Analytics";
import AuditLog from "./components/AuditLog";
import ApprovalQueue from "./components/ApprovalQueue";
import PoliciesPanel from "./components/PoliciesPanel";
import ChatPanel from "./components/ChatPanel";
import ResumeScreener from "./components/ResumeScreener";
import AttritionPanel from "./components/AttritionPanel";
import OpenAccessBanner from "./components/OpenAccessBanner";
import DemoWalkthrough from "./components/DemoWalkthrough";
import SettingsPanel from "./components/SettingsPanel";
import { useAuth } from "./auth/AuthContext";
import LoginScreen from "./auth/LoginScreen";
import Launchpad from "./auth/Launchpad";
import UserMenu from "./auth/UserMenu";
import RoleSwitcher from "./auth/RoleSwitcher";
import { useSystemStatus } from "./hooks/useSystemStatus";
import type { Role } from "../lib/api";

type Panel = "walkthrough" | "chat" | "fleet" | "cases" | "analytics" | "audit" | "approvals" | "policies" | "screener" | "attrition";
type NavGroup = "start" | "workspace" | "governance" | "advanced";

// Ascending privilege. Surfaces are gated by role when AUTH_ENFORCE is on:
//   viewer (employee)  → Chat only (self-service)
//   manager            → HR operating console, cases, analytics and governance
//   admin              → everything
const ROLE_LEVEL: Record<Role, number> = { viewer: 0, manager: 1, admin: 2 };

const NAV: { key: Panel; label: string; icon: React.ReactNode; minRole: Role; group: NavGroup }[] = [
  { key: "walkthrough", label: "Walkthrough", icon: <Sparkles size={18} />, minRole: "viewer", group: "start" },
  { key: "chat", label: "Chat", icon: <MessageCircle size={18} />, minRole: "viewer", group: "start" },
  { key: "cases", label: "Cases", icon: <ClipboardList size={18} />, minRole: "manager", group: "workspace" },
  { key: "policies", label: "Policies", icon: <FileText size={18} />, minRole: "manager", group: "workspace" },
  { key: "approvals", label: "Approvals", icon: <CheckSquare size={18} />, minRole: "manager", group: "governance" },
  { key: "audit", label: "Audit", icon: <ScrollText size={18} />, minRole: "manager", group: "governance" },
  { key: "fleet", label: "Command", icon: <Boxes size={18} />, minRole: "manager", group: "advanced" },
  { key: "screener", label: "Screener", icon: <ScanSearch size={18} />, minRole: "manager", group: "advanced" },
  { key: "analytics", label: "Analytics", icon: <BarChart3 size={18} />, minRole: "manager", group: "advanced" },
  { key: "attrition", label: "Attrition", icon: <Gauge size={18} />, minRole: "manager", group: "advanced" },
];

const NAV_GROUPS: { key: NavGroup; label: string }[] = [
  { key: "start", label: "Start here" },
  { key: "workspace", label: "Workspace" },
  { key: "governance", label: "Governance" },
];

export default function Page() {
  const { loading, isAuthed, user } = useAuth();
  const [guest, setGuest] = useState(false);
  const [panel, setPanel] = useState<Panel>("walkthrough");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [advancedNavOpen, setAdvancedNavOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<"ai" | "llm" | "integrations">("ai");
  const {
    activeCases,
    byokActive,
    byokSupported,
    enforced,
    healthy,
    llmConfigIssues,
    liveTransport,
    llmOn,
    llmProvider,
    setByokActive,
  } = useSystemStatus();
  // A template prompt handed from the Fleet "Open Conversation" button to seed
  // the Chat input; cleared once the ChatPanel consumes it (one-shot).
  const [chatSeed, setChatSeed] = useState("");
  const [caseFocusId, setCaseFocusId] = useState<string | null>(null);

  // Role-aware surfaces. Whenever a role/account is active its role drives
  // visibility — so flipping the role switcher visibly changes the surface
  // (employee sees Chat-only self-service; HR roles unlock the operator console).
  // A not-signed-in guest sees everything so a reviewer can explore freely.
  const role: Role = user?.role ?? "viewer";
  const roleGated = isAuthed;
  const visibleNav = roleGated
    ? NAV.filter((n) => ROLE_LEVEL[role] >= ROLE_LEVEL[n.minRole])
    : NAV;
  const employeeView = roleGated && ROLE_LEVEL[role] < ROLE_LEVEL.manager;
  const providerLabel =
    llmProvider === "fireworks"
      ? "Fireworks"
      : llmProvider === "amd_vllm"
        ? "AMD/vLLM Gemma"
        : llmProvider && llmProvider !== "unknown"
          ? llmProvider
          : "model";
  const providerTitle =
    llmConfigIssues.length > 0
      ? `${providerLabel} config issue: ${llmConfigIssues.join("; ")}`
      : `Live provider route: ${providerLabel}`;
  // Keep the active panel within the user's allowed surfaces.
  useEffect(() => {
    if (!visibleNav.some((n) => n.key === panel)) {
      setPanel(visibleNav[0]?.key ?? "chat");
    }
  }, [visibleNav, panel]);

  const selectPanel = (nextPanel: Panel) => {
    setPanel(nextPanel);
    setMobileNavOpen(false);
  };

  const openSettings = (tab: "ai" | "llm" | "integrations") => {
    setSettingsTab(tab);
    setSettingsOpen(true);
  };

  // Auth gate: enforced deployments require sign-in. In open-access local mode,
  // the launchpad lets a reviewer enter without credentials.
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-purple text-brand-cream">
        Loading…
      </div>
    );
  }
  // Open access (advisory) → the role Launchpad replaces the login gate.
  // Enforced (production) → keep the real email/password sign-in.
  if (!isAuthed && !guest) {
    return enforced ? <LoginScreen onGuest={() => setGuest(true)} /> : <Launchpad />;
  }

  return (
    <div className="flex min-h-screen w-full max-w-full flex-col overflow-x-hidden bg-brand-cream text-ink-800">
      {!enforced && <OpenAccessBanner llmOn={llmOn} />}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
        {/* Sidebar */}
        <aside className="hidden w-60 shrink-0 flex-col border-r border-brand-purple/10 bg-white text-ink-800 lg:flex">
          <div className="px-6 py-6">
	            <div className="flex items-center gap-2 text-lg font-semibold text-brand-purple">
	              <Activity size={20} className="text-brand-magenta" />
	              <span>Govern.ai</span>
	            </div>
	            <p className="mt-1 text-xs text-ink-700/55">
	              {employeeView ? "Employee self-service" : "Governed HR operations"}
	            </p>
          </div>
          <nav className="flex-1 space-y-5 px-3">
            {NAV_GROUPS.map((group) => {
              const items = visibleNav.filter((item) => item.group === group.key);
              if (!items.length) return null;
              return (
                <div key={group.key}>
                  <p className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-700/35">{group.label}</p>
                  <div className="space-y-1">
                    {items.map((item) => (
                      <button key={item.key} onClick={() => selectPanel(item.key)} className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${panel === item.key ? "bg-brand-purple text-white shadow-sm" : "text-ink-700/75 hover:bg-brand-cream/70 hover:text-brand-purple"}`}>
                        {item.icon}
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
            {visibleNav.some((item) => item.group === "advanced") && (
              <div className="pt-1">
                <button
                  type="button"
                  aria-expanded={advancedNavOpen}
                  onClick={() => setAdvancedNavOpen((open) => !open)}
                  className="flex w-full items-center justify-between px-3 pb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-700/35 hover:text-brand-purple"
                >
                  Advanced tools
                  <ChevronDown size={13} className={`transition ${advancedNavOpen ? "rotate-180" : ""}`} />
                </button>
                {advancedNavOpen && (
                  <div className="space-y-1">
                    {visibleNav.filter((item) => item.group === "advanced").map((item) => (
                      <button key={item.key} onClick={() => selectPanel(item.key)} className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${panel === item.key ? "bg-brand-purple text-white shadow-sm" : "text-ink-700/75 hover:bg-brand-cream/70 hover:text-brand-purple"}`}>
                        {item.icon}
                        {item.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </nav>
          {!enforced && <RoleSwitcher />}
          <UserMenu />
          <div className="px-6 pb-4 text-xs text-ink-700/40">v1.0.0</div>
        </aside>

        {/* Main column */}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          {/* Top bar */}
          <header className="border-b border-brand-purple/10 bg-white/90 px-4 py-3 backdrop-blur sm:px-6 lg:px-8 lg:py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <button
                  type="button"
                  aria-label={mobileNavOpen ? "Close navigation" : "Open navigation"}
                  aria-expanded={mobileNavOpen}
                  onClick={() => setMobileNavOpen((open) => !open)}
                  className="rounded-lg border border-brand-purple/15 p-2 text-brand-purple transition hover:bg-brand-purple/10 lg:hidden"
                >
                  {mobileNavOpen ? <X size={18} /> : <Menu size={18} />}
                </button>
                <div className="min-w-0">
	                  <div className="flex items-center gap-2 text-xs font-medium text-brand-purple/60 lg:hidden">
	                    <Activity size={14} className="text-brand-magenta" />
	                    Govern.ai
	                  </div>
                  <h1 className="truncate text-lg font-semibold text-brand-purple sm:text-xl">
                    {NAV.find((n) => n.key === panel)?.label}
                  </h1>
                </div>
              </div>
              <div className="flex max-w-full flex-wrap items-center justify-end gap-2 text-sm sm:gap-3">
                <button
                  type="button"
                  onClick={() => openSettings("ai")}
                  title="Open AI and LLM settings"
                  className="flex shrink-0 items-center gap-1.5 rounded-lg border border-brand-purple/15 bg-white px-3 py-2 text-xs font-medium text-brand-purple transition hover:bg-brand-purple/10"
                >
                  <Settings size={14} />
                  <span className="hidden sm:inline">Advanced controls</span>
                </button>
                {!llmOn && !byokActive && (
                  <span
                    title="The walkthrough is ready in local mode. Add a Fireworks key from the Walkthrough page for live responses."
                    className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-700"
                  >
                    local demo
                  </span>
                )}
                {(llmOn || byokActive) && (
                  <span
                    title={
                      byokActive
                        ? `Using request-scoped BYOK auth for ${providerLabel}`
                        : providerTitle
                    }
                    className="rounded-full bg-green-100 px-2.5 py-1 text-xs font-medium text-green-700"
                  >
                    {byokActive ? "Fireworks live" : `${providerLabel} ready`}
                  </span>
                )}
                {!enforced && (
                  <span
                    title="AUTH_ENFORCE is off — roles are advisory. Set AUTH_ENFORCE=true to enforce."
                    className="rounded-full bg-indigo-100 px-2.5 py-1 text-xs font-medium text-indigo-700"
                  >
                    open access
                  </span>
                )}
                <div className="flex items-center gap-2">
                  <CircleDot
                    size={16}
                    className={healthy ? "text-green-500" : "text-red-500"}
                  />
                  <span className="text-ink-700">
                    {healthy ? "System Healthy" : "System Offline"}
                  </span>
                </div>
                <span
                  title="Realtime transport state. Polling keeps metrics fresh when WebSocket is unavailable."
                  className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                    liveTransport === "live"
                      ? "bg-green-100 text-green-700"
                      : liveTransport === "connecting"
                      ? "bg-amber-100 text-amber-700"
                      : "bg-ink-700/10 text-ink-700/70"
                  }`}
                >
                  {liveTransport === "live"
                    ? "live sync"
                    : liveTransport === "connecting"
                    ? "syncing"
                    : "polling sync"}
                </span>
                <div className="rounded-full bg-brand-magenta/15 px-3 py-1 font-medium text-brand-magenta">
                  {activeCases} active {activeCases === 1 ? "case" : "cases"}
                </div>
                <UserMenu variant="top" />
              </div>
            </div>
            {mobileNavOpen && (
              <div className="mt-3 rounded-xl border border-brand-purple/10 bg-white shadow-lg lg:hidden">
                <nav className="grid grid-cols-1 gap-1 p-2 sm:grid-cols-2">
                  {visibleNav.filter((item) => item.group !== "advanced").map((item) => (
                    <button
                      key={item.key}
                      onClick={() => selectPanel(item.key)}
                      className={`flex w-full items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium transition ${
                        panel === item.key
                          ? "bg-brand-magenta text-white"
                          : "text-ink-700/75 hover:bg-brand-cream/70"
                      }`}
                    >
                      {item.icon}
                      {item.label}
                    </button>
                  ))}
                  {visibleNav.some((item) => item.group === "advanced") && (
                    <button type="button" onClick={() => setAdvancedNavOpen((open) => !open)} className="col-span-full flex items-center justify-between rounded-lg px-3 py-3 text-sm font-medium text-ink-700/75 hover:bg-brand-cream/70">
                      Advanced tools <ChevronDown size={15} className={advancedNavOpen ? "rotate-180" : ""} />
                    </button>
                  )}
                  {advancedNavOpen && visibleNav.filter((item) => item.group === "advanced").map((item) => (
                    <button key={item.key} onClick={() => selectPanel(item.key)} className={`flex w-full items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium transition ${panel === item.key ? "bg-brand-magenta text-white" : "text-ink-700/75 hover:bg-brand-cream/70"}`}>
                      {item.icon}
                      {item.label}
                    </button>
                  ))}
                </nav>
                <div className="border-t border-white/10 py-3">
                  {!enforced && <RoleSwitcher />}
                  <UserMenu />
                  <div className="px-6 pt-1 text-xs text-brand-cream/60">v1.0.0</div>
                </div>
              </div>
            )}
          </header>

          {/* Panel */}
          <main className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden p-4 sm:p-6 lg:p-8">
            {panel === "walkthrough" && (
              <DemoWalkthrough
                byokSupported={byokSupported}
                byokActive={byokActive}
                onByokActiveChange={setByokActive}
                providerLabel={providerLabel}
                onOpenChat={(prompt) => { setChatSeed(prompt); selectPanel("chat"); }}
                onOpenCases={() => selectPanel("cases")}
                onOpenPolicies={() => selectPanel("policies")}
                onOpenApprovals={() => selectPanel("approvals")}
                onOpenAudit={() => selectPanel("audit")}
                onOpenCommand={() => { setAdvancedNavOpen(true); selectPanel("fleet"); }}
                onOpenScreener={() => { setAdvancedNavOpen(true); selectPanel("screener"); }}
                onOpenAttrition={() => { setAdvancedNavOpen(true); selectPanel("attrition"); }}
                onOpenAnalytics={() => { setAdvancedNavOpen(true); selectPanel("analytics"); }}
              />
            )}
            {panel === "fleet" && (
              <AgentFleet
                onOpenCase={(caseId) => {
                  setCaseFocusId(caseId);
                  selectPanel("cases");
                }}
                onOpenCases={() => selectPanel("cases")}
                onOpenApprovals={() => selectPanel("approvals")}
                onOpenAudit={() => selectPanel("audit")}
              />
            )}
            {panel === "cases" && (
              <CaseFeed focusCaseId={caseFocusId} onFocusConsumed={() => setCaseFocusId(null)} />
            )}
            {panel === "analytics" && <Analytics />}
            {panel === "audit" && <AuditLog />}
            {panel === "approvals" && <ApprovalQueue />}
            {panel === "policies" && <PoliciesPanel />}
            {panel === "screener" && <ResumeScreener />}
            {panel === "attrition" && <AttritionPanel />}
            {panel === "chat" && (
              <ChatPanel seed={chatSeed} onSeedConsumed={() => setChatSeed("")} />
            )}
          </main>
        </div>
      </div>
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        initialTab={settingsTab}
        providerLabel={providerLabel}
        llmProvider={llmProvider}
        llmOn={llmOn}
        byokSupported={byokSupported}
        byokActive={byokActive}
        onByokActiveChange={setByokActive}
        configIssues={llmConfigIssues}
      />
    </div>
  );
}
