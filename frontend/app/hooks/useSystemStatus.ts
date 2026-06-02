"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { WS_URL, api } from "../../lib/api";

type LiveTransport = "connecting" | "live" | "polling";

export interface SystemStatus {
  activeCases: number;
  byokActive: boolean;
  enforced: boolean;
  healthy: boolean;
  liveTransport: LiveTransport;
  llmOn: boolean;
  setByokActive: (active: boolean) => void;
}

const ACTIVE_STATUSES = new Set(["open", "escalated"]);

export function useSystemStatus(): SystemStatus {
  const [healthy, setHealthy] = useState(false);
  const [activeCases, setActiveCases] = useState(0);
  const [enforced, setEnforced] = useState(false);
  const [llmOn, setLlmOn] = useState(true);
  const [byokActive, setByokActive] = useState(false);
  const [liveTransport, setLiveTransport] = useState<LiveTransport>("connecting");
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const refresh = useCallback(async () => {
    const h = await api.health();
    setHealthy(h.status === "healthy");
    setEnforced(h.auth_enforced ?? true);
    setLlmOn(h.llm_enabled ?? true);

    try {
      const m = await api.metrics();
      setActiveCases(m.active_cases);
    } catch {
      const cases = await api.cases();
      setActiveCases(cases.filter((c) => ACTIVE_STATUSES.has(c.status)).length);
    }
  }, []);

  useEffect(() => {
    let mounted = true;

    const safeRefresh = async () => {
      try {
        await refresh();
      } catch {
        if (mounted) setHealthy(false);
      }
    };

    safeRefresh();
    const id = setInterval(safeRefresh, liveTransport === "live" ? 15_000 : 5_000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, [liveTransport, refresh]);

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;

    const connect = () => {
      if (cancelled) return;
      setLiveTransport((current) => (current === "live" ? current : "connecting"));

      try {
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          attempts = 0;
          setHealthy(true);
          setLiveTransport("live");
          void refresh();
        };

        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            if (msg.type === "new_case" || msg.type === "case_updated") void refresh();
          } catch {
            /* heartbeat messages are best-effort telemetry only */
          }
        };

        ws.onerror = () => setLiveTransport("polling");
        ws.onclose = () => {
          if (cancelled) return;
          setLiveTransport("polling");
          const delay = Math.min(30_000, 1_000 * 2 ** attempts);
          attempts += 1;
          reconnectTimer.current = setTimeout(connect, delay);
        };
      } catch {
        setLiveTransport("polling");
        reconnectTimer.current = setTimeout(connect, 5_000);
      }
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [refresh]);

  return {
    activeCases,
    byokActive,
    enforced,
    healthy,
    liveTransport,
    llmOn,
    setByokActive,
  };
}
