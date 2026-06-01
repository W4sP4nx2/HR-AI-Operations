"use client";

/**
 * Minimal toast system — a context + a stack of auto-dismissing notifications.
 *
 * Used to surface action outcomes (especially RBAC 401/403 → a clear
 * "you need <role> access" message) instead of silent failures.
 */

import { createContext, useCallback, useContext, useState } from "react";
import { CheckCircle, AlertTriangle, XCircle, X } from "lucide-react";

type ToastKind = "success" | "error" | "warning";
interface ToastAction {
  label: string;
  onClick: () => void;
}
interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  action?: ToastAction;
}

interface ToastApi {
  notify: (message: string, kind?: ToastKind, action?: ToastAction) => void;
  /** Map a thrown API error into a friendly toast (handles auth phrasing). */
  notifyError: (err: unknown) => void;
}

const ToastCtx = createContext<ToastApi | null>(null);

const STYLES: Record<ToastKind, string> = {
  success: "border-green-200 bg-green-50 text-green-800",
  error: "border-red-200 bg-red-50 text-red-700",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
};
const ICONS: Record<ToastKind, React.ReactNode> = {
  success: <CheckCircle size={16} className="text-green-600" />,
  error: <XCircle size={16} className="text-red-500" />,
  warning: <AlertTriangle size={16} className="text-amber-500" />,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = useCallback(
    (message: string, kind: ToastKind = "success", action?: ToastAction) => {
      const id = Date.now() + Math.random();
      setToasts((t) => [...t, { id, kind, message, action }]);
      // Give an actionable toast (e.g. Undo) longer to be clicked.
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), action ? 8000 : 5000);
    },
    []
  );

  const notifyError = useCallback(
    (err: unknown) => {
      const raw = err instanceof Error ? err.message : String(err);
      const lower = raw.toLowerCase();
      if (lower.includes("role") || lower.includes("requires")) {
        notify(`Access denied — ${raw}`, "warning");
      } else if (lower.includes("auth") || lower.includes("token") || lower.includes("401")) {
        notify("Please sign in to perform this action.", "warning");
      } else {
        notify(raw || "Something went wrong.", "error");
      }
    },
    [notify]
  );

  return (
    <ToastCtx.Provider value={{ notify, notifyError }}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed bottom-5 right-5 z-[60] flex flex-col gap-2"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-start gap-2 rounded-xl border px-4 py-3 text-sm shadow-lg ${STYLES[t.kind]} animate-in`}
            style={{ maxWidth: 360 }}
          >
            {ICONS[t.kind]}
            <span className="flex-1 leading-snug">{t.message}</span>
            {t.action && (
              <button
                onClick={() => {
                  t.action!.onClick();
                  setToasts((arr) => arr.filter((x) => x.id !== t.id));
                }}
                className="shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold underline underline-offset-2 hover:opacity-80"
              >
                {t.action.label}
              </button>
            )}
            <button
              aria-label="Dismiss notification"
              onClick={() => setToasts((arr) => arr.filter((x) => x.id !== t.id))}
              className="opacity-50 hover:opacity-100"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastCtx);
  if (!ctx) return { notify: () => {}, notifyError: () => {} };
  return ctx;
}
