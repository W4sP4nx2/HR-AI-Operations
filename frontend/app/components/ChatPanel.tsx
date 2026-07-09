"use client";

/**
 * ChatPanel — conversational HR assistant powered by Pydantic AI.
 *
 * Streams replies token-by-token via the /chat/stream SSE endpoint.
 * Tool-call badges appear inline when the agent queries policy documents,
 * triages tickets, looks up cases, or scores attrition risk.
 *
 * Runs in "degraded mode" when no API key is configured — the fallback
 * still calls tools deterministically and tells the user what it did.
 */

import { useEffect, useRef, useState } from "react";
import { Send, Loader2, Bot, User, Wrench, FileText } from "lucide-react";
import { API_BASE, authHeaders, type ChatMessage } from "../../lib/api";

type ToolCall = { name: string };
type Citation = { n: number; doc_id: string; title: string; score: number; text: string };

type Message =
  | { role: "user"; content: string }
  | {
      role: "assistant";
      content: string;
      toolCalls: ToolCall[];
      citations: Citation[];
      mode: string;
      streaming?: boolean;
    };

const SUGGESTED = [
  "How many vacation days do I get?",
  "Triage this: payroll fails today, urgent!",
  "List all open URGENT cases",
  "What is the parental leave policy?",
];

const TOOL_LABELS: Record<string, string> = {
  search_policy: "Searched policies",
  triage_ticket: "Triaged ticket",
  get_case_status: "Fetched case",
  list_open_cases: "Listed cases",
  check_attrition: "Scored attrition",
};

function ToolBadge({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-brand-purple/10 px-2 py-0.5 text-[11px] font-medium text-brand-purple">
      <Wrench size={10} />
      {TOOL_LABELS[name] ?? name}
    </span>
  );
}

/** Clickable source citations: chips that expand to reveal the cited excerpt. */
function Citations({ items }: { items: Citation[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!items.length) return null;
  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex flex-wrap gap-1.5">
        {items.map((c) => (
          <button
            key={c.n}
            onClick={() => setOpen((o) => (o === c.n ? null : c.n))}
            title={`Relevance ${(c.score * 100).toFixed(0)}% · click to view excerpt`}
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition ${
              open === c.n
                ? "border-brand-magenta bg-brand-magenta/10 text-brand-magenta"
                : "border-brand-purple/20 bg-white text-brand-purple hover:border-brand-magenta"
            }`}
          >
            <FileText size={10} />
            <span className="font-mono">[{c.n}]</span> {c.title}
          </button>
        ))}
      </div>
      {open !== null && (
        <div className="rounded-lg border border-brand-purple/10 bg-brand-cream/60 px-3 py-2 text-xs text-ink-700">
          {(() => {
            const c = items.find((x) => x.n === open)!;
            return (
              <>
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-semibold text-brand-purple">{c.title}</span>
                  <span className="text-ink-700/50">{(c.score * 100).toFixed(0)}% match</span>
                </div>
                <p className="leading-relaxed">{c.text}</p>
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}

function ModeChip({ mode }: { mode: string }) {
  if (mode === "full") return null;
  return (
    <span className="ml-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">
      basic mode
    </span>
  );
}

/** Render Markdown-ish content: bold, bullets, code — minimal, no dep. */
function Prose({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div className="space-y-1 text-sm leading-relaxed">
      {lines.map((line, i) => {
        if (!line.trim()) return <div key={i} className="h-1" />;
        // Bold **text**
        const parts = line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, j) => {
          if (p.startsWith("**") && p.endsWith("**"))
            return <strong key={j}>{p.slice(2, -2)}</strong>;
          if (p.startsWith("`") && p.endsWith("`"))
            return <code key={j} className="rounded bg-ink-700/10 px-1 font-mono text-[11px]">{p.slice(1, -1)}</code>;
          return p;
        });
        if (line.startsWith("- ") || line.startsWith("• "))
          return <div key={i} className="flex gap-2"><span className="text-brand-magenta">·</span><span>{parts.slice(1)}</span></div>;
        if (line.startsWith("#"))
          return <p key={i} className="font-semibold text-brand-purple">{parts}</p>;
        return <p key={i}>{parts}</p>;
      })}
    </div>
  );
}

export default function ChatPanel({
  seed = "",
  onSeedConsumed,
}: {
  seed?: string;
  onSeedConsumed?: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // Seed the input from a Fleet "Open Conversation" hand-off (one-shot): prefill
  // a template prompt the user can edit or send, then clear it upstream.
  useEffect(() => {
    if (seed) {
      setInput(seed);
      onSeedConsumed?.();
    }
  }, [seed, onSeedConsumed]);

  const send = async (text: string) => {
    if (!text.trim() || streaming) return;
    const userMsg: Message = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setStreaming(true);

    // Build history for context
    const history: ChatMessage[] = messages.slice(-10).map((m) => ({
      role: m.role,
      content: m.content,
    }));

    // Seed an empty assistant message we'll stream into
    const assistantIdx = messages.length + 1;
    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: "", toolCalls: [], citations: [], mode: "degraded", streaming: true },
    ]);

    try {
      // EventSource only supports GET; the stream endpoint is POST, so we read
      // the SSE response off a fetch ReadableStream instead.
      const res = await fetch(`${API_BASE}/chat/stream`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ message: text, history }),
      });

      const reader = res.body?.getReader();
      const dec = new TextDecoder();
      let buf = "";
      const toolCalls: ToolCall[] = [];
      let mode = "degraded";

      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "token") {
              setMessages((prev) =>
                prev.map((m, i) =>
                  i === assistantIdx
                    ? { ...m, content: m.content + ev.content }
                    : m
                )
              );
            } else if (ev.type === "tool") {
              const tc: ToolCall = { name: ev.name };
              toolCalls.push(tc);
              setMessages((prev) =>
                prev.map((m, i) =>
                  i === assistantIdx ? { ...m, toolCalls: [...toolCalls] } : m
                )
              );
            } else if (ev.type === "citations") {
              const items: Citation[] = ev.items ?? [];
              setMessages((prev) =>
                prev.map((m, i) =>
                  i === assistantIdx && m.role === "assistant" ? { ...m, citations: items } : m
                )
              );
            } else if (ev.type === "done") {
              mode = ev.mode ?? "degraded";
              setMessages((prev) =>
                prev.map((m, i) =>
                  i === assistantIdx ? { ...m, mode, streaming: false } : m
                )
              );
            }
          } catch { /* malformed event */ }
        }
      }
    } catch (e) {
      setMessages((prev) =>
        prev.map((m, i) =>
          i === assistantIdx
            ? { ...m, content: `Error: ${(e as Error).message}`, mode: "error", streaming: false }
            : m
        )
      );
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-9rem)] flex-col">
      {/* Messages */}
      <div
        role="log"
        aria-label="Conversation"
        aria-live="polite"
        className="flex-1 overflow-y-auto space-y-4 pr-1"
      >
        {messages.length === 0 && (
          <div className="flex flex-col items-center gap-6 pt-16 text-center">
            <Bot size={40} className="text-brand-magenta/50" />
            <div>
              <p className="font-semibold text-brand-purple">HR Assistant</p>
              <p className="mt-1 text-sm text-ink-700/60">
                Ask a policy question, triage a ticket, or check a case.
              </p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTED.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-full border border-brand-purple/15 bg-white px-3 py-1.5 text-xs text-brand-purple hover:border-brand-magenta hover:text-brand-magenta transition"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            {msg.role === "assistant" && (
              <div className="mt-1 self-start shrink-0 rounded-full bg-brand-magenta p-1.5">
                <Bot size={14} className="text-white" />
              </div>
            )}
            <div className={`max-w-[80%] ${msg.role === "user" ? "order-first" : ""}`}>
              {msg.role === "assistant" && msg.toolCalls.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1">
                  {msg.toolCalls.map((tc, j) => <ToolBadge key={j} name={tc.name} />)}
                  <ModeChip mode={msg.mode} />
                </div>
              )}
              <div
                className={`rounded-2xl px-4 py-3 ${
                  msg.role === "user"
                    ? "bg-brand-magenta text-white rounded-tr-sm"
                    : "bg-white border border-brand-purple/10 text-ink-800 rounded-tl-sm shadow-sm"
                }`}
              >
                {msg.role === "user" ? (
                  <p className="text-sm">{msg.content}</p>
                ) : (
                  <>
                    <Prose text={msg.content || " "} />
                    {msg.streaming && <span className="ml-1 inline-block h-3.5 w-0.5 animate-pulse bg-brand-magenta align-middle" />}
                    {msg.citations.length > 0 && <Citations items={msg.citations} />}
                  </>
                )}
              </div>
            </div>
            {msg.role === "user" && (
              <div className="mt-1 shrink-0 rounded-full bg-brand-purple/15 p-1.5">
                <User size={14} className="text-brand-purple" />
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="mt-4 flex gap-2 border-t border-brand-purple/10 pt-4">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send(input))}
          placeholder="Ask about a policy, triage a ticket, or check a case…"
          className="flex-1 rounded-xl border border-brand-purple/15 px-4 py-2.5 text-sm outline-none focus:border-brand-magenta"
          disabled={streaming}
        />
        <button
          aria-label="Send message"
          onClick={() => send(input)}
          disabled={streaming || !input.trim()}
          className="flex items-center gap-1.5 rounded-xl bg-brand-magenta px-4 py-2.5 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-50"
        >
          {streaming ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
        </button>
      </div>
    </div>
  );
}
