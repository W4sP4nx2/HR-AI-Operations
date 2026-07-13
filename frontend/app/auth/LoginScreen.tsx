"use client";

/**
 * LoginScreen — email/password sign-in + register, plus Google sign-in when the
 * backend reports it is configured. Brand-themed, minimalist.
 *
 * "Continue as guest" is offered because the backend can run in advisory mode
 * with no enforcement, so the app is usable without an account.
 */

import { useEffect, useState } from "react";
import { Activity, Loader2, LogIn } from "lucide-react";
import { api } from "../../lib/api";
import { useAuth } from "./AuthContext";

export default function LoginScreen({ onGuest }: { onGuest: () => void }) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);

  useEffect(() => {
    api.googleStatus().then((s) => setGoogleEnabled(s.enabled)).catch(() => {});
  }, []);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-purple p-4">
      <div className="w-full max-w-sm rounded-3xl bg-white p-8 shadow-2xl">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
	          <div className="flex items-center gap-2 text-lg font-semibold text-brand-purple">
	            <Activity size={22} className="text-brand-magenta" />
	            Govern.ai
	          </div>
	          <p className="text-xs text-ink-700/60">Governed HR operations</p>
	        </div>

        <div className="mb-4 flex rounded-xl bg-brand-cream p-1 text-sm">
          {(["login", "register"] as const).map((m) => (
            <button
              key={m}
              onClick={() => { setMode(m); setError(null); }}
              className={`flex-1 rounded-lg py-1.5 font-medium capitalize transition ${
                mode === m ? "bg-white text-brand-purple shadow-sm" : "text-ink-700/60"
              }`}
            >
              {m === "login" ? "Sign in" : "Create account"}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          {mode === "register" && (
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name (optional)"
              className="w-full rounded-xl border border-brand-purple/15 px-4 py-2.5 text-sm outline-none focus:border-brand-magenta"
            />
          )}
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            type="email"
            placeholder="you@company.com"
            className="w-full rounded-xl border border-brand-purple/15 px-4 py-2.5 text-sm outline-none focus:border-brand-magenta"
          />
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            type="password"
            placeholder={mode === "register" ? "Password (min 8 chars)" : "Password"}
            className="w-full rounded-xl border border-brand-purple/15 px-4 py-2.5 text-sm outline-none focus:border-brand-magenta"
          />

          {error && <p className="text-xs text-red-500">{error}</p>}

          <button
            onClick={submit}
            disabled={busy || !email || !password}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-magenta py-2.5 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-50"
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : <LogIn size={16} />}
            {mode === "login" ? "Sign in" : "Create account"}
          </button>

          {googleEnabled && (
            <a
              href={api.googleLoginUrl()}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-brand-purple/15 py-2.5 text-sm font-medium text-ink-800 transition hover:bg-brand-cream"
            >
              <GoogleIcon /> Continue with Google
            </a>
          )}

          <button
            onClick={onGuest}
            className="w-full py-1 text-xs text-ink-700/50 hover:text-brand-magenta"
          >
            Continue as guest →
          </button>
        </div>

        <p className="mt-5 text-center text-[11px] text-ink-700/40">
          Open access needs no password — <strong className="font-semibold">Continue as guest</strong>,
          then use <strong className="font-semibold">View&nbsp;as</strong> to switch roles.
        </p>
      </div>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.4 29.3 35 24 35c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 5.1 29.6 3 24 3 12.4 3 3 12.4 3 24s9.4 21 21 21c11 0 20.5-8 20.5-21 0-1.2-.1-2.3-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 16 19 13 24 13c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 5.1 29.6 3 24 3 16 3 9.1 7.6 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 45c5.2 0 10-2 13.6-5.2l-6.3-5.3C29.2 35.9 26.7 37 24 37c-5.3 0-9.7-2.6-11.3-7l-6.5 5C9 40.3 15.9 45 24 45z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.1-4 5.5l6.3 5.3C39.9 36.5 44.5 31 44.5 24c0-1.2-.1-2.3-.9-3.5z" />
    </svg>
  );
}
