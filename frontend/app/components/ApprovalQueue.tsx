"use client";

/**
 * ApprovalQueue panel.
 *
 * Lists all paused agent tasks awaiting human approval. Each item shows the
 * agent name, the step it is waiting at and a context summary, with Approve /
 * Reject buttons. Approve issues PATCH /cases/{id}/approve; Reject sends the
 * task back to the agent with a rejection reason. Polls every 10 seconds.
 */

import { useCallback, useEffect, useState } from "react";
import { Check, X, Loader2, History, ShieldCheck } from "lucide-react";
import { api, type PendingTask, type ApprovalDecision } from "../../lib/api";
import { useToast } from "./Toast";

export default function ApprovalQueue() {
  const [tasks, setTasks] = useState<PendingTask[]>([]);
  const [history, setHistory] = useState<ApprovalDecision[]>([]);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      setTasks(await api.pendingApprovals());
    } catch {
      /* ignore transient errors */
    }
    try {
      setHistory(await api.approvalHistory());
    } catch {
      /* history is best-effort */
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, [load]);

  const approveTask = async (task: PendingTask) => {
    setBusy((b) => ({ ...b, [task.id]: true }));
    try {
      // The task may relate to a case; the backend resolves it from the task id.
      await api.approve("TASK", task.id);
      toast.notify(
        task.agent_name === "onboarding_agent"
          ? `Approved — ${task.agent_name} resumed`
          : `Approved — ${task.agent_name} review recorded`,
        "success",
      );
      await load();
    } catch (e) {
      toast.notifyError(e);
    } finally {
      setBusy((b) => ({ ...b, [task.id]: false }));
    }
  };

  const confirmReject = async (task: PendingTask) => {
    const reason = (reasons[task.id] || "").trim() || "rejected by reviewer";
    setBusy((b) => ({ ...b, [task.id]: true }));
    try {
      await api.reject("TASK", task.id, reason);
      toast.notify(`Rejected — ${reason}`, "warning");
      setRejecting(null);
      await load();
    } catch (e) {
      toast.notifyError(e);
    } finally {
      setBusy((b) => ({ ...b, [task.id]: false }));
    }
  };

  return (
    <div className="space-y-4">
      {tasks.map((task) => (
        <div
          key={task.id}
          className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm"
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-brand-purple">{task.agent_name}</h3>
                <span className="rounded-full bg-brand-peach/40 px-2 py-0.5 text-xs font-medium">
                  waiting at: {task.step}
                </span>
              </div>
              <p className="mt-2 text-sm text-ink-800">{task.context}</p>
              <p className="mt-1 text-xs text-ink-700/50">
                {new Date(task.created_at).toLocaleString()}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <button
                onClick={() => approveTask(task)}
                disabled={busy[task.id]}
                className="flex items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                {busy[task.id] ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
                Approve
              </button>
              <button
                onClick={() => setRejecting(rejecting === task.id ? null : task.id)}
                disabled={busy[task.id]}
                className="flex items-center gap-1 rounded-lg bg-red-500 px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                <X size={15} />
                Reject
              </button>
            </div>
          </div>

          {/* Inline rejection reason — no native prompt() (blocked in sandboxes). */}
          {rejecting === task.id && (
            <div className="mt-3 flex flex-col gap-2 rounded-xl bg-brand-cream/50 p-3 sm:flex-row sm:items-center">
              <input
                autoFocus
                value={reasons[task.id] ?? ""}
                onChange={(e) => setReasons((r) => ({ ...r, [task.id]: e.target.value }))}
                onKeyDown={(e) => e.key === "Enter" && confirmReject(task)}
                placeholder="Reason for rejection (captured in the audit log)…"
                className="flex-1 rounded-lg border border-brand-purple/15 px-3 py-1.5 text-sm outline-none focus:border-brand-magenta"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => confirmReject(task)}
                  disabled={busy[task.id]}
                  className="rounded-lg bg-red-500 px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
                >
                  Confirm reject
                </button>
                <button
                  onClick={() => setRejecting(null)}
                  className="rounded-lg border border-brand-purple/15 px-3 py-1.5 text-sm text-ink-700/70 hover:bg-white"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
      {tasks.length === 0 && (
        <div className="rounded-2xl border border-dashed border-brand-purple/20 bg-white/50 p-10 text-center text-sm text-ink-700/60">
          No tasks awaiting approval. 🎉
        </div>
      )}

      {/* Decision history — queried live from the immutable audit log, so the
          record of who approved/rejected what (and why) is the source of truth. */}
      <div className="pt-2">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-brand-purple">
          <History size={15} /> Decision history
          <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-brand-purple/10 px-2 py-0.5 text-[10px] font-medium text-brand-purple">
            <ShieldCheck size={10} /> from audit log
          </span>
        </div>
        {history.length === 0 ? (
          <p className="text-xs text-ink-700/50">No decisions recorded yet.</p>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-brand-purple/10 bg-white shadow-sm">
            <table className="w-full text-left text-sm">
              <thead className="bg-brand-cream/60 text-xs uppercase text-ink-700/70">
                <tr>
                  <th className="px-4 py-2">Decision</th>
                  <th className="px-4 py-2">Agent · step</th>
                  <th className="px-4 py-2">By (role)</th>
                  <th className="px-4 py-2">Reason</th>
                  <th className="px-4 py-2">When</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id} className="border-t border-brand-purple/5">
                    <td className="px-4 py-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                          h.decision === "approved"
                            ? "bg-green-100 text-green-700"
                            : "bg-red-100 text-red-600"
                        }`}
                      >
                        {h.decision}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-ink-700/80">
                      {h.agent_name}
                      {h.step ? ` · ${h.step}` : ""}
                    </td>
                    <td className="px-4 py-2 text-ink-700/70">
                      {h.role ?? "—"}
                      <span className="ml-1 font-mono text-[11px] text-ink-700/40">
                        {h.decided_by_id ?? ""}
                      </span>
                    </td>
                    <td className="max-w-[220px] truncate px-4 py-2 text-ink-700/70">
                      {h.reason || "—"}
                    </td>
                    <td className="px-4 py-2 text-xs text-ink-700/60">
                      {new Date(h.timestamp).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
