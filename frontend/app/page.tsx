"use client";

/**
 * HR AI Command Center dashboard.
 *
 * Layout:
 *   - Left sidebar: navigation (Fleet, Cases, Analytics, Audit, Approvals).
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
import DemoBanner from "./components/DemoBanner";
import ByokControl from "./components/ByokControl";
import { useAuth } from "./auth/AuthContext";
import LoginScreen from "./auth/LoginScreen";
import Launchpad from "./auth/Launchpad";
import UserMenu from "./auth/UserMenu";
import RoleSwitcher from "./auth/RoleSwitcher";
import { useSystemStatus } from "./hooks/useSystemStatus";
import type { Role } from "../lib/api";

type Panel = "fleet" | "cases" | "analytics" | "audit" | "approvals" | "policies" | "chat" | "screener" | "attrition";

// Ascending privilege. Surfaces are gated by role when AUTH_ENFORCE is on:
//   viewer (employee)  → Chat only (self-service)
//   analyst (HR)       → + Fleet, Cases, Analytics
//   manager            → + Policies, Approvals, Audit
//   admin              → everything
const ROLE_LEVEL: Record<Role, number> = { viewer: 0, analyst: 1, manager: 2, admin: 3 };

const NAV: { key: Panel; label: string; icon: React.ReactNode; minRole: Role }[] = [
  { key: "chat", label: "Chat", icon: <MessageCircle size={18} />, minRole: "viewer" },
  { key: "fleet", label: "Fleet", icon: <Boxes size={18} />, minRole: "analyst" },
  { key: "cases", label: "Cases", icon: <ClipboardList size={18} />, minRole: "analyst" },
  { key: "screener", label: "Screener", icon: <ScanSearch size={18} />, minRole: "analyst" },
  { key: "analytics", label: "Analytics", icon: <BarChart3 size={18} />, minRole: "analyst" },
  { key: "attrition", label: "Attrition", icon: <Gauge size={18} />, minRole: "manager" },
  { key: "policies", label: "Policies", icon: <FileText size={18} />, minRole: "manager" },
  { key: "approvals", label: "Approvals", icon: <CheckSquare size={18} />, minRole: "manager" },
  { key: "audit", label: "Audit", icon: <ScrollText size={18} />, minRole: "manager" },
];

export default function Page() {
  const { loading, isAuthed, user } = useAuth();
  const [guest, setGuest] = useState(false);
  const [panel, setPanel] = useState<Panel>("chat");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const {
    activeCases,
    byokActive,
    enforced,
    healthy,
    liveTransport,
    llmOn,
    setByokActive,
  } = useSystemStatus();
  // A template prompt handed from the Fleet "Open Conversation" button to seed
  // the Chat input; cleared once the ChatPanel consumes it (one-shot).
  const [chatSeed, setChatSeed] = useState("");

  // Role-aware surfaces. Whenever a persona/account is active its role drives
  // visibility — so flipping the demo role switcher visibly changes the surface
  // (employee sees Chat-only self-service; HR roles unlock the operator console).
  // A not-signed-in guest sees everything so a reviewer can explore freely.
  const role: Role = user?.role ?? "viewer";
  const roleGated = isAuthed;
  const visibleNav = roleGated
    ? NAV.filter((n) => ROLE_LEVEL[role] >= ROLE_LEVEL[n.minRole])
    : NAV;
  const employeeView = roleGated && ROLE_LEVEL[role] < ROLE_LEVEL.analyst;

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

  // Auth gate: show the login screen until the user signs in or chooses guest.
  // (Backend advisory mode means guest is fully functional for demos.)
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-purple text-brand-cream">
        Loading…
      </div>
    );
  }
  // Demo (advisory) → the persona Launchpad replaces the login gate.
  // Enforced (production) → keep the real email/password sign-in.
  if (!isAuthed && !guest) {
    return enforced ? <LoginScreen onGuest={() => setGuest(true)} /> : <Launchpad />;
  }

  return (
    <div className="flex min-h-screen w-full max-w-full flex-col overflow-x-hidden bg-brand-cream text-ink-800">
      {!enforced && <DemoBanner llmOn={llmOn} />}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
        {/* Sidebar */}
        <aside className="hidden w-60 shrink-0 flex-col bg-brand-purple text-brand-cream lg:flex">
          <div className="px-6 py-6">
            <div className="flex items-center gap-2 text-lg font-semibold">
              <Activity size={20} className="text-brand-peach" />
              <span>{employeeView ? "HR Assistant" : "Command Center"}</span>
            </div>
            <p className="mt-1 text-xs text-brand-peach/80">
              {employeeView ? "Employee self-service" : "HR AI Operations"}
            </p>
          </div>
          <nav className="flex-1 space-y-1 px-3">
            {visibleNav.map((item) => (
              <button
                key={item.key}
                onClick={() => selectPanel(item.key)}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
                  panel === item.key
                    ? "bg-brand-magenta text-white"
                    : "text-brand-cream/80 hover:bg-white/10"
                }`}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </nav>
          {!enforced && <RoleSwitcher />}
          <UserMenu />
          <div className="px-6 pb-4 text-xs text-brand-cream/60">v1.0.0</div>
        </aside>

        {/* Main column */}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          {/* Top bar */}
          <header className="border-b border-brand-purple/10 bg-brand-cream/80 px-4 py-3 backdrop-blur sm:px-6 lg:px-8 lg:py-4">
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
                    {employeeView ? "HR Assistant" : "Command Center"}
                  </div>
                  <h1 className="truncate text-lg font-semibold text-brand-purple sm:text-xl">
                    {NAV.find((n) => n.key === panel)?.label}
                  </h1>
                </div>
              </div>
              <div className="flex max-w-full flex-wrap items-center justify-end gap-2 text-sm sm:gap-3">
                <ByokControl onActiveChange={setByokActive} />
                {!llmOn && !byokActive && (
                  <span
                    title="No ANTHROPIC_API_KEY — deterministic fallback mode"
                    className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-700"
                  >
                    basic mode
                  </span>
                )}
                {!enforced && (
                  <span
                    title="AUTH_ENFORCE is off — roles are advisory. Set AUTH_ENFORCE=true to enforce."
                    className="rounded-full bg-indigo-100 px-2.5 py-1 text-xs font-medium text-indigo-700"
                  >
                    demo · open access
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
              </div>
            </div>
            {mobileNavOpen && (
              <div className="mt-3 rounded-xl bg-brand-purple text-brand-cream shadow-lg lg:hidden">
                <nav className="grid grid-cols-1 gap-1 p-2 sm:grid-cols-2">
                  {visibleNav.map((item) => (
                    <button
                      key={item.key}
                      onClick={() => selectPanel(item.key)}
                      className={`flex w-full items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium transition ${
                        panel === item.key
                          ? "bg-brand-magenta text-white"
                          : "text-brand-cream/80 hover:bg-white/10"
                      }`}
                    >
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
            {panel === "fleet" && (
              <AgentFleet
                onOpenPanel={(p) => selectPanel(p as Panel)}
                onOpenChat={(seed) => {
                  setChatSeed(seed);
                  selectPanel("chat");
                }}
              />
            )}
            {panel === "cases" && <CaseFeed />}
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
    </div>
  );
}
