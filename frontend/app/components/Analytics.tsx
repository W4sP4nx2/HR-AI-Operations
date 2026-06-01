"use client";

/**
 * Analytics panel — every number here is a **query over the audit log + cases**
 * via `GET /metrics`, never a value an agent stored. KPI cards show the headline
 * counters; the bar chart is real agent activity (audit rows per agent); the
 * donut is the live case-status mix. If the backend is unreachable the panel
 * says so rather than inventing data.
 */

import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import { CheckCircle2, AlertTriangle, Activity, Briefcase, ScanSearch } from "lucide-react";
import { api, type Metrics } from "../../lib/api";

const BRAND = {
  purple: "#5D1C6A",
  magenta: "#CA5995",
  peach: "#FFB090",
};

const STATUS_COLORS: Record<string, string> = {
  open: BRAND.peach,
  escalated: BRAND.magenta,
  resolved: BRAND.purple,
};

function StatCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2 text-ink-700/60">
        {icon}
        <span className="text-xs font-medium uppercase">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-semibold text-brand-purple">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-ink-700/50">{sub}</p>}
    </div>
  );
}

export default function Analytics() {
  const [m, setM] = useState<Metrics | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const data = await api.metrics();
        if (!mounted) return;
        setM(data);
        setOffline(false);
      } catch {
        if (mounted) setOffline(true);
      }
    };
    load();
    const id = setInterval(load, 10_000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  if (offline && !m) {
    return (
      <div className="rounded-2xl border border-brand-purple/10 bg-white p-10 text-center text-sm text-ink-700/60">
        Metrics unavailable — the backend isn’t reachable.
      </div>
    );
  }
  if (!m) {
    return <div className="p-10 text-center text-sm text-ink-700/50">Loading metrics…</div>;
  }

  const agentActivity = m.actions_by_agent.length
    ? m.actions_by_agent.map((a) => ({ agent: a.agent.replace(/_agent$/, ""), count: a.count }))
    : [{ agent: "—", count: 0 }];
  const statusData = m.cases_by_status.length
    ? m.cases_by_status
    : [{ status: "none", count: 1 }];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={<Activity size={16} />}
          label="Agent Actions"
          value={String(m.agent_actions_total)}
          sub="audited, all-time"
        />
        <StatCard
          icon={<Briefcase size={16} />}
          label="Active Cases"
          value={String(m.active_cases)}
          sub={`${m.cases_total} total`}
        />
        <StatCard
          icon={<CheckCircle2 size={16} />}
          label="Auto-Resolved"
          value={`${Math.round(m.auto_resolution_rate * 100)}%`}
          sub={`${m.resolved_cases} resolved · ${m.resolved_today} today`}
        />
        <StatCard
          icon={<AlertTriangle size={16} />}
          label="Human Escalations"
          value={String(m.escalations)}
          sub={`${Math.round(m.escalation_rate * 100)}% of cases`}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
          <h3 className="mb-1 font-semibold text-brand-purple">Agent Activity</h3>
          <p className="mb-3 text-xs text-ink-700/50">Audited actions per agent</p>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={agentActivity}>
              <XAxis dataKey="agent" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="count" fill={BRAND.magenta} radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-2xl border border-brand-purple/10 bg-white p-5 shadow-sm">
          <h3 className="mb-1 font-semibold text-brand-purple">Case Status Mix</h3>
          <p className="mb-3 text-xs text-ink-700/50">Live distribution from the cases store</p>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={statusData}
                dataKey="count"
                nameKey="status"
                innerRadius={60}
                outerRadius={95}
                paddingAngle={3}
              >
                {statusData.map((s, i) => (
                  <Cell key={i} fill={STATUS_COLORS[s.status] ?? BRAND.peach} />
                ))}
              </Pie>
              <Legend />
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 text-xs text-ink-700/60">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 shadow-sm">
          <ScanSearch size={13} className="text-brand-magenta" /> {m.resume_screens} resume screens
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 shadow-sm">
          {m.policy_queries} policy queries
        </span>
        {m.injection_blocks > 0 && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 shadow-sm">
            {m.injection_blocks} prompt-injection attempts blocked
          </span>
        )}
        <span className="ml-auto self-center text-ink-700/40">
          Derived live from the audit log · refreshes every 10s
        </span>
      </div>
    </div>
  );
}
