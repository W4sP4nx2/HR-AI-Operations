"use client";

/**
 * RoleSwitcher — demo-mode "view as" control in the sidebar.
 *
 * Instead of juggling three separate logins, a reviewer flips between personas
 * (Employee / HR / Manager / Admin) and the dashboard surface changes to match.
 * Each switch mints a real JWT for a pre-seeded demo persona via
 * `/auth/demo/switch`, so role-gated API calls work too — not just UI visibility.
 *
 * Only rendered in advisory/demo mode (AUTH_ENFORCE off). When enforcement is on
 * the switcher is hidden because the backend disables the endpoint.
 */

import { useState } from "react";
import { Eye, ChevronDown, Loader2 } from "lucide-react";
import { useAuth } from "./AuthContext";
import type { Role } from "../../lib/api";

const PERSONAS: { role: Role; label: string; blurb: string }[] = [
  { role: "viewer", label: "Employee", blurb: "Self-service chat only" },
  { role: "analyst", label: "HR Analyst", blurb: "+ Fleet, Cases, Analytics" },
  { role: "manager", label: "HR Manager", blurb: "+ Policies, Approvals, Audit" },
  { role: "admin", label: "Admin", blurb: "Full access" },
];

export default function RoleSwitcher() {
  const { user, switchRole } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<Role | null>(null);
  const current = user?.role ?? "viewer";
  const currentLabel = PERSONAS.find((p) => p.role === current)?.label ?? "Employee";

  const pick = async (role: Role) => {
    setBusy(role);
    try {
      await switchRole(role);
      setOpen(false);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="relative mx-3 mb-2">
      {open && (
        <div className="absolute bottom-full mb-2 w-full overflow-hidden rounded-xl bg-white shadow-xl">
          {PERSONAS.map((p) => (
            <button
              key={p.role}
              onClick={() => pick(p.role)}
              disabled={busy !== null}
              className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm transition hover:bg-brand-cream disabled:opacity-60 ${
                p.role === current ? "bg-brand-cream/60" : ""
              }`}
            >
              <span className="min-w-0">
                <span className="block font-medium text-ink-800">{p.label}</span>
                <span className="block text-[11px] text-ink-700/50">{p.blurb}</span>
              </span>
              {busy === p.role ? (
                <Loader2 size={13} className="shrink-0 animate-spin text-brand-magenta" />
              ) : p.role === current ? (
                <span className="shrink-0 text-[10px] font-semibold text-brand-magenta">current</span>
              ) : null}
            </button>
          ))}
        </div>
      )}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 rounded-lg bg-white/10 px-3 py-2 text-left text-sm text-brand-cream/90 hover:bg-white/15"
      >
        <Eye size={15} className="shrink-0 text-brand-peach" />
        <span className="min-w-0 flex-1">
          <span className="block text-[10px] uppercase tracking-wide text-brand-cream/50">View as</span>
          <span className="block truncate font-medium">{currentLabel}</span>
        </span>
        <ChevronDown size={14} className={`shrink-0 text-brand-cream/60 transition ${open ? "rotate-180" : ""}`} />
      </button>
    </div>
  );
}
