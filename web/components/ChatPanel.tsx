"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";
import { useChat } from "@/lib/useChat";
import { ChatMessage } from "./ChatMessage";

const BASE = "http://localhost:8000";

const FALLBACK_STARTERS = [
  { text: "Show me the top 10 rows from any table",  mode: "ask" as const },
  { text: "What tables are available?",              mode: "ask" as const },
  { text: "Why did a key metric change recently?",   mode: "investigate" as const },
  { text: "What is driving an unexpected trend?",    mode: "investigate" as const },
  { text: "Summarise the most recent data",          mode: "ask" as const },
  { text: "Diagnose an anomaly in the data",         mode: "investigate" as const },
];

type Starter = { text: string; mode: "ask" | "investigate" };

interface Props {
  connectionId: string;
  restoreSessionId?: string | null;
}

export function ChatPanel({ connectionId, restoreSessionId }: Props) {
  const { state, ask, stop, clear, restore } = useChat();
  const [input, setInput]       = useState("");
  const [mode, setMode]         = useState<"ask" | "investigate">("ask");
  const [starters, setStarters] = useState<Starter[]>(FALLBACK_STARTERS);
  const [loadingStarters, setLoadingStarters] = useState(false);
  const bottomRef               = useRef<HTMLDivElement>(null);
  const textareaRef             = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    clear();
    setStarters(FALLBACK_STARTERS);
    setLoadingStarters(true);
    fetch(`${BASE}/suggestions?connection_id=${encodeURIComponent(connectionId)}`)
      .then(r => r.json())
      .then(data => {
        const suggestions: Starter[] = (data.suggestions ?? []).map((s: { text: string; mode: string }) => ({
          text: s.text,
          mode: (s.mode === "investigate" ? "investigate" : "ask") as "ask" | "investigate",
        }));
        if (suggestions.length > 0) setStarters(suggestions);
      })
      .catch(() => { /* keep fallback */ })
      .finally(() => setLoadingStarters(false));
  }, [connectionId]);

  // Restore a prior session when session ID is provided
  useEffect(() => {
    if (!restoreSessionId) return;
    fetch(`${BASE}/chat-sessions/${restoreSessionId}/turns`)
      .then(r => r.ok ? r.json() : [])
      .then((turns: { id: string; question: string; headline: string; sql: string }[]) => {
        if (!turns.length) return;
        restore(turns.map(t => ({
          id: t.id,
          question: t.question,
          mode: "ask" as const,
          status: "done" as const,
          sql: t.sql || null,
          columns: [],
          rows: [],
          headline: t.headline || null,
          chartType: null,
          statusText: null,
          phases: [],
          adaReport: null,
          report: null,
          queryMode: null,
          tablesUsed: [],
          followups: [],
          error: null,
        })));
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restoreSessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state.turns.length, state.turns[state.turns.length - 1]?.status]);

  const handleSend = (q?: string, m?: "ask" | "investigate") => {
    const question = (q ?? input).trim();
    if (!question || state.streaming) return;
    setInput("");
    ask(question, connectionId, m ?? mode);
    textareaRef.current?.focus();
  };

  const isEmpty = state.turns.length === 0;

  const modeToggle = (
    <div className="flex items-center gap-1 bg-zinc-900/60 rounded-lg p-0.5 border border-zinc-700/50">
      <button
        onClick={() => setMode("ask")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
          mode === "ask"
            ? "bg-zinc-700 text-zinc-100 shadow-sm"
            : "text-zinc-500 hover:text-zinc-400"
        }`}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M10 1H2a1 1 0 00-1 1v6a1 1 0 001 1h1.5L5 11l1.5-2H10a1 1 0 001-1V2a1 1 0 00-1-1z"
            stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
        </svg>
        Ask
      </button>
      <button
        onClick={() => setMode("investigate")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
          mode === "investigate"
            ? "bg-violet-600/25 text-violet-300 shadow-sm border border-violet-500/20"
            : "text-zinc-500 hover:text-zinc-400"
        }`}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M6 1v2M6 9v2M1 6h2M9 6h2M2.5 2.5l1.5 1.5M8 8l1.5 1.5M9.5 2.5L8 4M4 8l-1.5 1.5"
            stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          <circle cx="6" cy="6" r="1.5" stroke="currentColor" strokeWidth="1.2" />
        </svg>
        Investigate
      </button>
    </div>
  );

  const sendButton = state.streaming ? (
    <button
      onClick={stop}
      title="Stop"
      className="absolute right-3 bottom-3 w-8 h-8 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 flex items-center justify-center hover:bg-red-500/25 transition"
    >
      <Square size={12} strokeWidth={2} fill="currentColor" />
    </button>
  ) : (
    <button
      onClick={() => handleSend()}
      disabled={!input.trim()}
      className="absolute right-3 bottom-3 w-8 h-8 rounded-lg bg-zinc-100 text-zinc-900 flex items-center justify-center hover:bg-white disabled:opacity-30 disabled:cursor-not-allowed transition"
    >
      <ArrowUp size={14} strokeWidth={2.5} />
    </button>
  );

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

      {isEmpty ? (
        /* ── Empty state: centered ── */
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-8">
          <div className="w-full max-w-2xl flex flex-col gap-5">

            <div className="text-center">
              <p className="text-2xl font-semibold text-zinc-300">Ask your data anything</p>
              <p className="text-sm text-zinc-500 mt-1.5">
                Use <span className="text-zinc-400">Ask</span> for quick answers ·{" "}
                <span className="text-violet-400/80">Investigate</span> for deep root-cause analysis
              </p>
            </div>

            {/* Input + arrow */}
            <div className="relative">
              <textarea
                ref={textareaRef}
                rows={3}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
                }}
                disabled={state.streaming}
                placeholder="Ask anything about your data…"
                className="w-full rounded-xl bg-zinc-700/50 border border-zinc-600 text-sm text-zinc-100 placeholder:text-zinc-400 px-4 py-3 pr-14 resize-none focus:outline-none focus:ring-1 focus:ring-zinc-500 transition disabled:opacity-50"
              />
              {sendButton}
            </div>

            {/* Mode toggle */}
            <div className="flex items-center">
              {modeToggle}
            </div>

            {/* Disclaimer */}
            <p className="text-xs text-zinc-500">
              Always review the accuracy of responses.
            </p>

            {/* Suggestions */}
            <div className="flex flex-col gap-2 pt-1 border-t border-zinc-700/50">
              {loadingStarters
                ? Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="h-5 rounded bg-zinc-700/30 animate-pulse" />
                  ))
                : starters.map((s) => (
                    <button
                      key={s.text}
                      onClick={() => handleSend(s.text, s.mode)}
                      className="text-left flex items-baseline gap-2.5 group"
                    >
                      <span className={`text-[9px] font-semibold uppercase tracking-wider shrink-0 mt-0.5 ${
                        s.mode === "investigate" ? "text-violet-400/70" : "text-zinc-500"
                      }`}>
                        {s.mode}
                      </span>
                      <span className="text-sm text-zinc-400 group-hover:text-zinc-200 transition group-hover:underline underline-offset-2">
                        {s.text}
                      </span>
                    </button>
                  ))
              }
            </div>
          </div>
        </div>
      ) : (
        /* ── Active chat ── */
        <>
          <div className="flex-1 overflow-y-auto min-h-0">
            <div className="p-5 space-y-4 max-w-3xl mx-auto w-full">
              {state.turns.map((turn) => (
                <ChatMessage
                  key={turn.id}
                  turn={turn}
                  onFollowUp={(q) => handleSend(q)}
                />
              ))}
              <div ref={bottomRef} />
            </div>
          </div>

          {/* ── Input bar ── */}
          <div className="border-t border-zinc-600 px-4 pt-3 pb-3 shrink-0 bg-zinc-800">
            <div className="max-w-3xl mx-auto space-y-2">
              <div className="relative">
                <textarea
                  ref={textareaRef}
                  rows={1}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
                  }}
                  disabled={state.streaming}
                  placeholder="Follow up…"
                  className="w-full rounded-xl bg-zinc-700/50 border border-zinc-600 text-sm text-zinc-100 placeholder:text-zinc-400 px-4 py-2.5 pr-14 resize-none focus:outline-none focus:ring-1 focus:ring-zinc-500 transition disabled:opacity-50"
                />
                {sendButton}
              </div>
              <div className="flex items-center justify-between">
                {modeToggle}
                {!state.streaming && (
                  <button
                    onClick={clear}
                    className="text-xs text-zinc-500 hover:text-zinc-400 transition-colors"
                    title="Clear conversation"
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
