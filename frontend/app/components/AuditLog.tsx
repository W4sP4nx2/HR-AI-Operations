"use client";

/**
 * AuditLog panel.
 *
 * Renders the compliance audit trail as a table: timestamp, agent, action,
 * input summary, output summary and status. Supports filtering by agent and a
 * date range, plus an "Export to CSV" button that hits the backend export
 * endpoint. Polls every 10 seconds.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Download } from "lucide-react";
import { api, type AuditRow } from "../../lib/api";

export default function AuditLog() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [agent, setAgent] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const load = useCallback(async () => {
    try {
      setRows(await api.audit(agent || undefined));
    } catch {
      /* ignore */
    }
  }, [agent]);

  useEffect(() => {
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, [load]);

  const agents = useMemo(
    () => Array.from(new Set(rows.map((r) => r.agent_name))),
    [rows]
  );

  const filtered = rows.filter((r) => {
    const t = new Date(r.timestamp).getTime();
    if (from && t < new Date(from).getTime()) return false;
    if (to && t > new Date(to).getTime() + 86_400_000) return false;
    return true;
  });

  const statusColor: Record<string, string> = {
    success: "text-green-600",
    error: "text-red-500",
    paused: "text-amber-500",
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={agent}
          onChange={(e) => setAgent(e.target.value)}
          className="rounded-lg border border-brand-purple/15 bg-white px-3 py-1.5 text-sm"
        >
          <option value="">All agents</option>
          {agents.map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
        <input
          type="date"
          value={from}
          onChange={(e) => setFrom(e.target.value)}
          className="rounded-lg border border-brand-purple/15 bg-white px-3 py-1.5 text-sm"
        />
        <span className="text-ink-700/50">→</span>
        <input
          type="date"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          className="rounded-lg border border-brand-purple/15 bg-white px-3 py-1.5 text-sm"
        />
        <a
          href={api.auditExportUrl(agent || undefined)}
          className="ml-auto flex items-center gap-1 rounded-lg bg-brand-purple px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          <Download size={15} />
          Export CSV
        </a>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-brand-purple/10 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-brand-cream/60 text-xs uppercase text-ink-700/70">
            <tr>
              <th className="px-4 py-2.5">Timestamp</th>
              <th className="px-4 py-2.5">Agent</th>
              <th className="px-4 py-2.5">Action</th>
              <th className="px-4 py-2.5">Input</th>
              <th className="px-4 py-2.5">Output</th>
              <th className="px-4 py-2.5">Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.id} className="border-t border-brand-purple/5">
                <td className="px-4 py-2 text-xs text-ink-700/70">
                  {new Date(r.timestamp).toLocaleString()}
                </td>
                <td className="px-4 py-2">{r.agent_name}</td>
                <td className="px-4 py-2">{r.action_type}</td>
                <td className="px-4 py-2 text-ink-700/70">
                  <div className="max-w-[240px] truncate" title={r.input}>{r.input}</div>
                </td>
                <td className="px-4 py-2 text-ink-700/70">
                  <div className="max-w-[240px] truncate" title={r.output}>{r.output}</div>
                </td>
                <td className={`px-4 py-2 font-medium ${statusColor[r.status] ?? ""}`}>
                  {r.status}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-ink-700/60">
                  No audit entries.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
