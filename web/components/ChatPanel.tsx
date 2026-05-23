"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Square, Terminal, X, ChevronDown, ChevronRight } from "lucide-react";
import { useChat, type DebugEvent } from "@/lib/useChat";
import { ChatMessage, SourcePanel, type SourcePanelData } from "./ChatMessage";

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

/* ── Paper-airplane send icon (45° clockwise) ── */
function SendIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" style={{ transform: "rotate(45deg)" }}>
      <path d="M22 2L11 13" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ── Input box — module-level so React never remounts it on parent re-render ── */
interface InputBoxProps {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  multiline?: boolean;
  input: string;
  setInput: (v: string) => void;
  streaming: boolean;
  mode: "ask" | "investigate";
  setMode: (m: "ask" | "investigate") => void;
  onSend: () => void;
  onStop: () => void;
  onClear: () => void;
}

function InputBox({ textareaRef, multiline, input, setInput, streaming, mode, setMode, onSend, onStop, onClear }: InputBoxProps) {
  return (
    <div
      className="rounded-xl flex flex-col overflow-hidden"
      style={{
        background: "#11171D",
        border: "1px solid rgba(255,255,255,0.09)",
        boxShadow: "0 6px 20px rgba(0,0,0,0.5), 0 1px 0 rgba(255,255,255,0.04) inset",
      }}
    >
      {/* Textarea row */}
      <textarea
        ref={textareaRef}
        rows={multiline ? 3 : 1}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); }
        }}
        disabled={streaming}
        placeholder={multiline ? "Ask anything about your data…" : "Ask your question…"}
        className="w-full bg-transparent text-[12px] text-zinc-100 placeholder:text-zinc-500 px-4 pt-3 pb-2 resize-none focus:outline-none disabled:opacity-50"
      />

      {/* Toggle row — mode buttons left, send/stop right */}
      <div className="flex items-center justify-between px-3 pb-2.5">
        {/* Mode toggle */}
        <div className="flex items-center gap-0.5">
          <button
            onClick={() => setMode("ask")}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-medium transition-all ${
              mode === "ask"
                ? "bg-zinc-700 text-zinc-100 shadow-sm"
                : "text-zinc-500 hover:text-zinc-400"
            }`}
          >
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
              <path d="M10 1H2a1 1 0 00-1 1v6a1 1 0 001 1h1.5L5 11l1.5-2H10a1 1 0 001-1V2a1 1 0 00-1-1z"
                stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
            </svg>
            Quick
          </button>
          <button
            onClick={() => setMode("investigate")}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-medium transition-all ${
              mode === "investigate"
                ? "bg-violet-600/25 text-violet-300 shadow-sm border border-violet-500/20"
                : "text-zinc-500 hover:text-zinc-400"
            }`}
          >
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
              <path d="M6 1v2M6 9v2M1 6h2M9 6h2M2.5 2.5l1.5 1.5M8 8l1.5 1.5M9.5 2.5L8 4M4 8l-1.5 1.5"
                stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              <circle cx="6" cy="6" r="1.5" stroke="currentColor" strokeWidth="1.2" />
            </svg>
            Agentic
          </button>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          {!multiline && !streaming && (
            <button
              onClick={onClear}
              className="text-[12px] transition-colors"
              style={{ color: "#687986" }}
              title="Clear conversation"
            >
              Clear
            </button>
          )}
          {streaming ? (
            <button
              onClick={onStop}
              title="Stop"
              className="w-7 h-7 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 flex items-center justify-center hover:bg-red-500/25 transition"
            >
              <Square size={11} strokeWidth={2} fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={() => onSend()}
              disabled={!input.trim()}
              title="Send"
              className="w-7 h-7 rounded-lg text-zinc-500 flex items-center justify-center hover:text-zinc-100 disabled:opacity-25 disabled:cursor-not-allowed transition"
            >
              <SendIcon />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Debug log drawer ──────────────────────────────────────────────────────────

function DebugLogDrawer({ eventLogRef, onClose }: { eventLogRef: React.RefObject<DebugEvent[]>; onClose: () => void }) {
  const [events, setEvents] = useState<DebugEvent[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Refresh every 500 ms while open
  useEffect(() => {
    const refresh = () => setEvents([...eventLogRef.current]);
    refresh();
    const id = setInterval(refresh, 500);
    return () => clearInterval(id);
  }, [eventLogRef]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [events.length]);

  const TYPE_COLOR: Record<string, string> = {
    start: "text-sky-400", done: "text-emerald-400", error: "text-red-400",
    ada_report: "text-violet-400", explore_report: "text-teal-400", report: "text-blue-400",
    phase_complete: "text-amber-400", tables_used: "text-zinc-400", followups: "text-zinc-400",
  };

  return (
    <div className="fixed bottom-0 right-0 z-50 flex flex-col bg-zinc-950 border border-zinc-700/80 rounded-tl-xl shadow-2xl" style={{ width: 520, height: 380 }}>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800 shrink-0">
        <Terminal size={13} className="text-emerald-400" />
        <span className="text-[11px] font-mono text-zinc-300 flex-1">SSE Event Log · {events.length} events</span>
        <span className="text-[10px] text-zinc-600 mr-2">⌘⇧L to close</span>
        <button onClick={onClose} className="text-zinc-600 hover:text-zinc-300 transition"><X size={13} /></button>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0 font-mono text-[11px]">
        {events.length === 0 ? (
          <p className="text-zinc-600 p-3">No events yet. Send a message to start.</p>
        ) : events.map((ev, i) => (
          <div key={i} className="border-b border-zinc-900 hover:bg-zinc-900/40">
            <button
              className="w-full flex items-center gap-2 px-3 py-1.5 text-left"
              onClick={() => setExpanded(expanded === i ? null : i)}
            >
              {expanded === i ? <ChevronDown size={10} className="text-zinc-600 shrink-0" /> : <ChevronRight size={10} className="text-zinc-600 shrink-0" />}
              <span className="text-zinc-600 shrink-0">{new Date(ev.ts).toLocaleTimeString()}</span>
              <span className={`shrink-0 w-28 truncate ${TYPE_COLOR[ev.type] ?? "text-zinc-300"}`}>{ev.type}</span>
              <span className="text-zinc-500 truncate flex-1">{ev.summary}</span>
            </button>
            {expanded === i && (
              <pre className="px-4 py-2 text-[10px] text-zinc-400 bg-zinc-900/60 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                {JSON.stringify(ev.payload, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ChatPanel({ connectionId, restoreSessionId }: Props) {
  const { state, ask, stop, clear, restore, eventLogRef } = useChat();
  const [input, setInput]           = useState("");
  const [mode, setMode]             = useState<"ask" | "investigate">("ask");
  const [starters, setStarters]     = useState<Starter[]>(FALLBACK_STARTERS);
  const [loadingStarters, setLoadingStarters] = useState(false);
  const [showDebug, setShowDebug]   = useState(false);
  const [sourcePanel, setSourcePanel] = useState<SourcePanelData | null>(null);
  const scrollRef               = useRef<HTMLDivElement>(null);
  const turnTopRefs             = useRef<Map<string, HTMLElement>>(new Map());
  const textareaRef             = useRef<HTMLTextAreaElement>(null);
  const wasStreamingRef         = useRef(false);

  // ── Keyboard shortcut: ⌘⇧L toggles debug log ──────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "L") {
        e.preventDefault();
        setShowDebug(v => !v);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  useEffect(() => {
    if (!restoreSessionId) clear();
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
      .catch(() => {})
      .finally(() => setLoadingStarters(false));
  }, [connectionId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!restoreSessionId) return;
    fetch(`${BASE}/chat-sessions/${restoreSessionId}/turns`)
      .then(r => r.ok ? r.json() : [])
      .then((turns: { id: string; question: string; headline: string; sql: string; columns: string[]; rows: unknown[][]; chart_type: string }[]) => {
        if (!turns.length) return;
        restore(turns.map(t => ({
          id: t.id,
          question: t.question,
          mode: "ask" as const,
          status: "done" as const,
          sql: t.sql || null,
          columns: t.columns || [],
          rows: t.rows || [],
          headline: t.headline || null,
          chartType: t.chart_type || null,
          statusText: null,
          phases: [],
          adaReport: null,
          report: null,
          queryMode: null,
          subQuestions: [],
          subqAnswers: [],
          exploreReport: null,
          tablesUsed: [],
          followups: [],
          error: null,
          fromCache: false,
          cachedQuestion: null,
        })));
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restoreSessionId]);

  // ── Scroll: bottom during streaming, back to question on completion ─────────
  const streamingKey = state.turns.map(t => `${t.id}:${t.phases.length}:${t.statusText}`).join("|");
  useEffect(() => {
    if (!state.streaming) return;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streamingKey]);

  useEffect(() => {
    if (wasStreamingRef.current && !state.streaming && state.turns.length > 0) {
      const lastTurn = state.turns[state.turns.length - 1];
      setTimeout(() => {
        const el = turnTopRefs.current.get(lastTurn.id);
        el?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 150);
    }
    wasStreamingRef.current = state.streaming;
  }, [state.streaming]); // eslint-disable-line

  const handleSend = useCallback((q?: string, m?: "ask" | "investigate", opts?: { skipCache?: boolean }) => {
    const question = (q ?? input).trim();
    if (!question || state.streaming) return;
    setInput("");
    ask(question, connectionId, m ?? mode, opts);
    textareaRef.current?.focus();
  }, [input, state.streaming, ask, connectionId, mode]);

  const isEmpty = state.turns.length === 0;

  const inputBoxProps: InputBoxProps = {
    textareaRef,
    input,
    setInput,
    streaming: state.streaming,
    mode,
    setMode,
    onSend: handleSend,
    onStop: stop,
    onClear: clear,
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden" style={{ background: "#11171D" }}>

      {isEmpty ? (
        /* ── Empty state ── */
        <div className="flex-1 flex flex-col items-center justify-center py-10">
          <div className="w-[90%] flex flex-col gap-5">

            <div className="text-center">
              <p className="text-[12px] font-bold text-zinc-200">Ask your data anything</p>
              <p className="text-[12px] text-zinc-500 mt-1.5">
                Use <span className="text-zinc-400 font-bold">Quick</span> for fast SQL answers ·{" "}
                <span className="text-violet-400/90 font-bold">Agentic</span> for deep root-cause analysis
              </p>
            </div>

            <InputBox {...inputBoxProps} multiline />

            <p className="text-[12px] text-center" style={{ color: "#687986" }}>Always review the accuracy of responses.</p>

            {/* Suggestions */}
            <div className="pt-1">
              <p className="text-[12px] text-zinc-600 uppercase tracking-widest mb-3">Suggested questions</p>
              {loadingStarters ? (
                <div className="flex flex-wrap gap-2">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="h-7 w-48 rounded-full bg-zinc-800/60 animate-pulse" />
                  ))}
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {starters.map((s) => (
                    <button
                      key={s.text}
                      onClick={() => handleSend(s.text, s.mode)}
                      className={`flex items-center gap-1.5 pl-3 pr-4 py-1.5 rounded-full border text-[12px] font-medium transition hover:text-zinc-100 ${
                        s.mode === "investigate"
                          ? "border-violet-500/30 bg-violet-500/8 text-violet-300/80 hover:bg-violet-500/15 hover:border-violet-400/40"
                          : "border-zinc-700 bg-zinc-800/60 text-zinc-400 hover:bg-zinc-700/60 hover:border-zinc-600"
                      }`}
                    >
                      <svg width="10" height="10" viewBox="0 0 10 10" className="shrink-0 opacity-60">
                        {s.mode === "investigate"
                          ? <><path d="M5 1v1.5M5 7.5V9M1 5h1.5M7.5 5H9M2.1 2.1l1.1 1.1M6.8 6.8l1.1 1.1M7.9 2.1L6.8 3.2M3.2 6.8l-1.1 1.1" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round"/><circle cx="5" cy="5" r="1.2" stroke="currentColor" strokeWidth="1.1"/></>
                          : <path d="M8.5 1H1.5a.5.5 0 00-.5.5v5a.5.5 0 00.5.5H3L4.5 9 6 7h2.5a.5.5 0 00.5-.5v-5a.5.5 0 00-.5-.5z" stroke="currentColor" strokeWidth="1" strokeLinejoin="round"/>
                        }
                      </svg>
                      {s.text}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        /* ── Active chat ── */
        <>
          {/* Flex row: [scrollable chat] [source panel drawer] */}
          <div className="flex flex-1 min-h-0 overflow-hidden">
            {/* ── Chat scroll area ── */}
            <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0">
              <div className="py-8 w-[90%] mx-auto">
                {state.turns.map((turn, i) => (
                  <div
                    key={turn.id}
                    ref={el => {
                      if (el) turnTopRefs.current.set(turn.id, el);
                      else turnTopRefs.current.delete(turn.id);
                    }}
                  >
                    {i > 0 && <div className="border-t border-zinc-800 my-8" />}
                    <ChatMessage
                      turn={turn}
                      onFollowUp={(q) => handleSend(q)}
                      onRunFresh={(q) => handleSend(q, "investigate", { skipCache: true })}
                      onShowSource={setSourcePanel}
                    />
                  </div>
                ))}
                <div className="h-4" />
              </div>
            </div>

            {/* ── Source panel drawer (right side, pushes chat left) ── */}
            {sourcePanel && (
              <div
                className="flex-shrink-0 flex flex-col border-l border-zinc-700/60"
                style={{ width: 380, background: "#0f1923" }}
              >
                <SourcePanel
                  columns={sourcePanel.columns}
                  rows={sourcePanel.rows}
                  sql={sourcePanel.sql}
                  title={sourcePanel.title}
                  onClose={() => setSourcePanel(null)}
                />
              </div>
            )}
          </div>

          {/* ── Input bar ── */}
          <div className="border-t border-zinc-800 pt-3 pb-3 shrink-0" style={{ background: "#11171D" }}>
            <div className="w-[90%] mx-auto space-y-2">
              <InputBox {...inputBoxProps} />
              <p className="text-[12px] text-center" style={{ color: "#687986" }}>Always review the accuracy of responses.</p>
            </div>
          </div>
        </>
      )}

      {/* ── Debug log drawer ── */}
      {showDebug && (
        <DebugLogDrawer eventLogRef={eventLogRef} onClose={() => setShowDebug(false)} />
      )}
    </div>
  );
}
