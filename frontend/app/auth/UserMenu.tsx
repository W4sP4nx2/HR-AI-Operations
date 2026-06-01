"use client";

/** Sidebar footer: shows the signed-in user, their role, and a logout control. */

import { useState } from "react";
import { LogOut, ChevronUp } from "lucide-react";
import { useAuth } from "./AuthContext";

const ROLE_COLORS: Record<string, string> = {
  admin: "bg-brand-magenta text-white",
  manager: "bg-brand-peach text-ink-800",
  analyst: "bg-indigo-400 text-white",
  viewer: "bg-white/20 text-brand-cream",
};

export default function UserMenu() {
  const { user, isAuthed, logout } = useAuth();
  const [open, setOpen] = useState(false);

  // No signed-in persona → render nothing. The Launchpad sets the initial
  // persona and the sidebar "View as" switcher handles changes; a separate
  // sign-in button here would be redundant.
  if (!isAuthed || !user) return null;

  const initial = (user.name || user.email)[0]?.toUpperCase() ?? "?";

  return (
    <div className="relative mx-3 mb-3">
      {open && (
        <div className="absolute bottom-full mb-2 w-full overflow-hidden rounded-xl bg-white shadow-xl">
          <button
            onClick={() => { logout(); setOpen(false); }}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-ink-800 hover:bg-brand-cream"
          >
            <LogOut size={15} /> Sign out
          </button>
        </div>
      )}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 rounded-lg bg-white/10 px-3 py-2 text-left hover:bg-white/15"
      >
        {user.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={user.avatar_url} alt="" className="h-7 w-7 rounded-full" />
        ) : (
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-magenta text-xs font-semibold text-white">
            {initial}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-brand-cream">{user.name || user.email}</p>
          <span className={`mt-0.5 inline-block rounded-full px-1.5 py-px text-[10px] font-semibold ${ROLE_COLORS[user.role] ?? ROLE_COLORS.viewer}`}>
            {user.role}
          </span>
        </div>
        <ChevronUp size={15} className={`text-brand-cream/60 transition ${open ? "" : "rotate-180"}`} />
      </button>
    </div>
  );
}
