"use client";

/**
 * HR AI Command Center dashboard.
 *
 * Layout:
 *   - Left sidebar: navigation (Fleet, Cases, Analytics, Audit, Approvals).
 *   - Top bar: system health indicator + active agent count.
 *   - Main area: renders the active panel based on the selected nav item.
 *
 * Polls /health every 10s for the top-bar indicator; individual panels manage
 * their own data (WebSocket for the case feed, polling fallback elsewhere).
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
} from "lucide-react";
import { api } from "../lib/api";
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
  const [healthy, setHealthy] = useState(false);
  const [activeCases, setActiveCases] = useState(0);
  // Default to demo posture (not enforced) so the Launchpad shows immediately;
  // /health flips this to the real value within the first poll.
  const [enforced, setEnforced] = useState(false);
  const [llmOn, setLlmOn] = useState(true);
  const [byokActive, setByokActive] = useState(false);
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

  // Poll health every 10 seconds for the top-bar indicator.
  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const h = await api.health();
        if (!mounted) return;
        setHealthy(h.status === "healthy");
        setEnforced(h.auth_enforced ?? true);
        setLlmOn(h.llm_enabled ?? true);
        // Active = open + escalated cases (real work in flight), from the
        // audit-derived metrics — not idle agent process count.
        try {
          const m = await api.metrics();
          if (mounted) setActiveCases(m.active_cases);
        } catch {
          /* metrics optional for the header */
        }
      } catch {
        if (mounted) setHealthy(false);
      }
    };
    load();
    const id = setInterval(load, 10_000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

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
    <div className="flex min-h-screen flex-col bg-brand-cream text-ink-800">
      {!enforced && <DemoBanner llmOn={llmOn} />}
      <div className="flex flex-1 overflow-hidden">
      {/* Sidebar */}
      <aside className="flex w-60 flex-col bg-brand-purple text-brand-cream">
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
              onClick={() => setPanel(item.key)}
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
      <div className="flex flex-1 flex-col">
        {/* Top bar */}
        <header className="flex items-center justify-between border-b border-brand-purple/10 bg-brand-cream/80 px-8 py-4 backdrop-blur">
          <h1 className="text-xl font-semibold text-brand-purple">
            {NAV.find((n) => n.key === panel)?.label}
          </h1>
          <div className="flex items-center gap-3 text-sm">
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
            <div className="rounded-full bg-brand-magenta/15 px-3 py-1 font-medium text-brand-magenta">
              {activeCases} active {activeCases === 1 ? "case" : "cases"}
            </div>
          </div>
        </header>

        {/* Panel */}
        <main className="flex-1 overflow-y-auto p-8">
          {panel === "fleet" && (
            <AgentFleet
              onOpenPanel={(p) => setPanel(p as Panel)}
              onOpenChat={(seed) => {
                setChatSeed(seed);
                setPanel("chat");
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
          {panel === "chat" && <ChatPanel seed={chatSeed} onSeedConsumed={() => setChatSeed("")} />}
        </main>
      </div>
      </div>
    </div>
  );
}
