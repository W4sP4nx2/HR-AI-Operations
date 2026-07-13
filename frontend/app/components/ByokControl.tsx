"use client";

/**
 * ByokControl — "bring your own key" control + provider-verified pulse.
 *
 * The key is stored only in memory and sent as `X-Client-LLM-Key`; reload or tab
 * close clears it, and the backend uses it per request without persistence. On save we hit
 * `/byok/verify`, which actually authenticates the key against the provider:
 *   • verified    → green pulse ("your key · verified"),
 *   • rejected    → cleared + error (bad/expired key — caught before any agent run),
 *   • unverifiable → kept, amber dot ("unverified" — provider unreachable / offline run).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { KeyRound, Check, Loader2, X, AlertTriangle } from "lucide-react";
import { byokStore, verifyByok } from "../../lib/api";

type State = "idle" | "verified" | "unverified";

export default function ByokControl({
  onActiveChange,
  placement = "down",
  providerLabel = "Fireworks",
}: {
  onActiveChange?: (active: boolean) => void;
  placement?: "up" | "down";
  providerLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [state, setState] = useState<State>("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);

  const apply = useCallback(
    (s: State) => {
      setState(s);
      onActiveChange?.(s !== "idle"); // a key is attached for verified OR unverified
    },
    [onActiveChange]
  );

  // On remount: if this page runtime still has a key, re-verify it.
  useEffect(() => {
    const existing = byokStore.get();
    if (!existing) return;
    setValue(existing);
    verifyByok().then((r) => {
      if (r.status === "unsupported") {
        byokStore.clear();
        setValue("");
        apply("idle");
        return;
      }
      apply(r.status === "verified" ? "verified" : "unverified");
    });
  }, [apply]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const save = async () => {
    setBusy(true);
    setError(null);
    byokStore.set(value.trim());
    const r = await verifyByok();
    setBusy(false);
    if (r.status === "verified") {
      apply("verified");
      setOpen(false);
    } else if (
      r.status === "rejected" ||
      r.status === "malformed" ||
      r.status === "unsupported"
    ) {
      byokStore.clear();
      apply("idle");
      setError(
        r.status === "malformed"
          ? "That key's format looks wrong."
          : r.status === "unsupported"
            ? "Browser keys are disabled for this private model route."
            : "The provider rejected that key."
      );
    } else {
      // unverifiable — keep the key (offline/network); let the user proceed.
      apply("unverified");
      setOpen(false);
    }
  };

  const clear = () => {
    byokStore.clear();
    setValue("");
    setError(null);
    apply("idle");
  };

  const chip =
    state === "verified"
      ? { cls: "bg-green-100 text-green-700", label: "Your key · verified" }
      : state === "unverified"
        ? { cls: "bg-amber-100 text-amber-700", label: "Your key · unverified" }
        : { cls: "bg-brand-purple/10 text-brand-purple hover:bg-brand-purple/15", label: "Use your key" };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        title={state === "idle" ? "Use your own API key" : "Manage your API key"}
        className={`flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium transition ${chip.cls}`}
      >
        {state === "verified" ? (
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-500 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
          </span>
        ) : state === "unverified" ? (
          <span className="inline-flex h-2 w-2 rounded-full bg-amber-500" />
        ) : (
          <KeyRound size={12} />
        )}
        {chip.label}
      </button>

      {open && (
        <div
          className={`absolute right-0 z-50 w-72 rounded-xl border border-brand-purple/10 bg-white p-3 shadow-xl ${
            placement === "up" ? "bottom-full mb-2" : "top-full mt-2"
          }`}
        >
            <p className="mb-1 text-xs font-semibold text-brand-purple">
              Bring your own {providerLabel} key
            </p>
          <p className="mb-2 text-[11px] leading-snug text-ink-700/60">
            Verified against the provider on save. Stored only in this tab; sent
            per-request; <strong>never saved on the server</strong>.
          </p>
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && value.trim() && save()}
            placeholder={`Paste ${providerLabel} API key`}
            className="w-full rounded-lg border border-brand-purple/15 px-3 py-1.5 text-sm outline-none focus:border-brand-magenta"
          />
          {error && <p className="mt-1.5 text-[11px] text-red-500">{error}</p>}
          {state === "unverified" && !error && (
            <p className="mt-1.5 flex items-center gap-1 text-[11px] text-amber-600">
              <AlertTriangle size={11} /> Saved, but couldn’t reach the provider to verify.
            </p>
          )}
          <div className="mt-2 flex items-center gap-2">
            <button
              onClick={save}
              disabled={busy || !value.trim()}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-brand-magenta py-1.5 text-xs font-medium text-white transition hover:opacity-90 disabled:opacity-50"
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
              {state !== "idle" ? "Re-verify" : "Verify & use"}
            </button>
            {state !== "idle" && (
              <button
                onClick={clear}
                aria-label="Remove browser API key"
                title="Remove browser API key"
                className="flex items-center gap-1 rounded-lg border border-brand-purple/15 px-2.5 py-1.5 text-xs text-ink-700/70 hover:bg-brand-cream"
              >
                <X size={13} /> Remove key
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
