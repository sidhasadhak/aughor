"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import AtlasSendIcon      from "@atlaskit/icon/core/send";
import VideoStopIcon      from "@atlaskit/icon/core/video-stop";
import AngleBracketsIcon  from "@atlaskit/icon/core/angle-brackets";
import CloseIcon          from "@atlaskit/icon/core/close";
import ChevronDownIcon    from "@atlaskit/icon/core/chevron-down";
import ChevronRightIcon   from "@atlaskit/icon/core/chevron-right";
import CommentIcon        from "@atlaskit/icon/core/comment";
import AiSparkleIcon      from "@atlaskit/icon/core/ai-sparkle";
import { uploadDocument } from "@/lib/api";
import { useChat, type DebugEvent } from "@/lib/useChat";
import { ChatMessage, SourcePanel, type SourcePanelData } from "./ChatMessage";

import { API_BASE as BASE } from "@/lib/config";
import { FeedbackPrompt } from "@/components/FeedbackPrompt";

const FALLBACK_STARTERS = [
  { text: "Show me the top 10 rows from any table",  mode: "ask" as const },
  { text: "What tables are available?",              mode: "ask" as const },
  { text: "What was the average order value last month?", mode: "ask" as const },
  { text: "Why did a key metric change recently?",   mode: "investigate" as const },
  { text: "What is driving an unexpected trend?",    mode: "investigate" as const },
  { text: "Diagnose an anomaly in the data",         mode: "investigate" as const },
];

type Starter = { text: string; mode: "ask" | "investigate" };

interface Props {
  connectionId: string;
  canvasId?: string | null;
  restoreSessionId?: string | null;
  initialQuestion?: string;
  initialMode?: "ask" | "investigate";
  /** Optional landing block rendered atop the empty state (e.g. canvas Capabilities). */
  capabilities?: React.ReactNode;
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
  attachedFile?: File | null;
  onAttach?: (f: File | null) => void;
}

function InputBox({ textareaRef, multiline, input, setInput, streaming, mode, setMode, onSend, onStop, onClear, attachedFile, onAttach }: InputBoxProps) {
  const [focused, setFocused] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    onAttach?.(file);
    e.target.value = ""; // reset so same file can be re-selected
  };

  return (
    <div
      className="rounded-md flex flex-col overflow-hidden"
      style={{
        background: "#0d0e11",
        border: focused
          ? "1px solid rgba(45,114,210,0.55)"
          : "1px solid rgba(255,255,255,0.09)",
        boxShadow: focused
          ? "0 0 0 3px rgba(45,114,210,0.12), 0 6px 20px rgba(0,0,0,0.5), 0 1px 0 rgba(255,255,255,0.04) inset"
          : "0 6px 20px rgba(0,0,0,0.5), 0 1px 0 rgba(255,255,255,0.04) inset",
        transition: "border-color .15s, box-shadow .15s",
      }}
    >
      {/* Attached file chip */}
      {attachedFile && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 12px 0" }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 5,
            padding: "2px 8px", borderRadius: "var(--r2)",
            background: "var(--blue1)", border: "1px solid var(--blue2)",
            fontSize: 11, color: "var(--blue5)", maxWidth: 320,
          }}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
            </svg>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{attachedFile.name}</span>
            <button onClick={() => onAttach?.(null)} style={{ marginLeft: 2, opacity: .6, lineHeight: 1, background: "none", border: "none", color: "inherit", cursor: "pointer", padding: 0, fontSize: 12 }}>×</button>
          </div>
        </div>
      )}

      {/* Textarea row */}
      <textarea
        ref={textareaRef}
        rows={multiline ? 2 : 1}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); }
        }}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        disabled={streaming}
        placeholder={multiline ? "Ask anything about your data…" : "Ask your question…"}
        className="w-full bg-transparent text-[12px] text-zinc-100 placeholder:text-zinc-500 px-4 pt-3 pb-2 resize-none focus:outline-none disabled:opacity-50"
      />

      {/* Toggle row — mode buttons left, actions right */}
      <div className="flex items-center justify-between px-3 pb-2">
        {/* Mode toggle */}
        <div style={{ display: "flex", alignItems: "center", gap: 2, padding: "2px", background: "var(--bg-0)", borderRadius: "var(--r2)", border: "1px solid var(--b1)" }}>
          <button
            onClick={() => setMode("ask")}
            style={{
              display: "flex", alignItems: "center", gap: 5, padding: "3px 10px",
              borderRadius: "var(--r1)", fontSize: 11, fontWeight: 500, fontFamily: "var(--font-ui)",
              cursor: "pointer", border: "none", transition: "all .12s",
              background: mode === "ask" ? "var(--bg-3)" : "transparent",
              color: mode === "ask" ? "var(--t1)" : "var(--t3)",
              boxShadow: mode === "ask" ? "0 1px 3px rgba(0,0,0,.3)" : "none",
            }}
          >
            <CommentIcon label="Insight" size="small" />
            Insight
          </button>
          <button
            onClick={() => setMode("investigate")}
            style={{
              display: "flex", alignItems: "center", gap: 5, padding: "3px 10px",
              borderRadius: "var(--r1)", fontSize: 11, fontWeight: 500, fontFamily: "var(--font-ui)",
              cursor: "pointer", border: mode === "investigate" ? "1px solid var(--vio2)" : "1px solid transparent",
              transition: "all .12s",
              background: mode === "investigate" ? "var(--vio1)" : "transparent",
              color: mode === "investigate" ? "var(--vio5)" : "var(--t3)",
              boxShadow: mode === "investigate" ? "0 1px 3px rgba(0,0,0,.3)" : "none",
            }}
          >
            <AiSparkleIcon label="Deep Analysis" size="small" />
            Deep Analysis
          </button>
        </div>

        {/* Actions: clear · attach · send/stop */}
        <div className="flex items-center gap-1.5">
          {!multiline && !streaming && (
            <button
              onClick={onClear}
              className="text-[12px] transition-colors px-1"
              style={{ color: "#687986" }}
              title="Clear conversation"
            >
              Clear
            </button>
          )}

          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.csv,.txt,.md"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />

          {/* Attach button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            title="Attach file (PDF, CSV)"
            disabled={streaming}
            className="flex items-center justify-center rounded-lg transition-colors disabled:opacity-30"
            style={{
              width: 30, height: 30,
              color: attachedFile ? "var(--blue4)" : "#687986",
              background: attachedFile ? "rgba(45,114,210,0.1)" : "transparent",
            }}
            onMouseEnter={e => { if (!attachedFile) (e.currentTarget as HTMLElement).style.color = "#c0bfbc"; }}
            onMouseLeave={e => { if (!attachedFile) (e.currentTarget as HTMLElement).style.color = "#687986"; }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
            </svg>
          </button>

          {/* Send / Stop */}
          {streaming ? (
            <button
              onClick={onStop}
              title="Stop"
              className="rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 flex items-center justify-center hover:bg-red-500/25 transition"
              style={{ width: 30, height: 30 }}
            >
              <VideoStopIcon label="Stop" size="small" />
            </button>
          ) : (
            <button
              onClick={() => onSend()}
              disabled={!input.trim()}
              title="Send"
              className="rounded-lg text-zinc-500 flex items-center justify-center hover:text-zinc-100 disabled:opacity-25 disabled:cursor-not-allowed transition"
              style={{ width: 30, height: 30 }}
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
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
        <span className="text-emerald-400"><AngleBracketsIcon label="Debug log" size="small" /></span>
        <span className="text-[11px] font-mono text-zinc-300 flex-1">SSE Event Log · {events.length} events</span>
        <span className="text-[11px] text-zinc-600 mr-2">⌘⇧L to close</span>
        <button onClick={onClose} className="text-zinc-600 hover:text-zinc-300 transition"><CloseIcon label="Close" size="small" /></button>
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
              {expanded === i
                ? <span className="text-zinc-600 shrink-0"><ChevronDownIcon label="" size="small" /></span>
                : <span className="text-zinc-600 shrink-0"><ChevronRightIcon label="" size="small" /></span>}
              <span className="text-zinc-600 shrink-0">{new Date(ev.ts).toLocaleTimeString()}</span>
              <span className={`shrink-0 w-28 truncate ${TYPE_COLOR[ev.type] ?? "text-zinc-300"}`}>{ev.type}</span>
              <span className="text-zinc-500 truncate flex-1">{ev.summary}</span>
            </button>
            {expanded === i && (
              <pre className="px-4 py-2 text-[11px] text-zinc-400 bg-zinc-900/60 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                {JSON.stringify(ev.payload, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ChatPanel({ connectionId, canvasId, restoreSessionId, initialQuestion, initialMode, capabilities }: Props) {
  const { state, ask, stop, clear, restore, eventLogRef } = useChat();
  const [input, setInput]           = useState("");
  const [mode, setMode]             = useState<"ask" | "investigate">("ask");
  const [starters, setStarters]     = useState<Starter[]>(FALLBACK_STARTERS);
  const [loadingStarters, setLoadingStarters] = useState(false);
  const [showDebug, setShowDebug]   = useState(false);
  const [feedbackDone, setFeedbackDone] = useState<Set<string>>(new Set());
  const [sourcePanel, setSourcePanel] = useState<SourcePanelData | null>(null);
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
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
      .then((turns: { id: string; question: string; headline: string; sql: string; columns: string[]; rows: unknown[][]; chart_type: string; tables_used: string[]; intent: string; approach: string[]; insight: { narrative: string; anomalies: string[]; trend: string; confidence: string } | null }[]) => {
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
          queriesExecuted: [],
          latestScore: null,
          hypotheses: [],
          investigationId: null,
          tablesUsed: t.tables_used || [],
          analysis: (t.intent || t.approach?.length) ? { intent: t.intent || "", steps: t.approach || [] } : null,
          followups: [],
          error: null,
          startedAt: 0,
          elapsedMs: null,
          fromCache: false,
          cachedQuestion: null,
          inspectWarning: null,
          playbookRefs: [],
          insight: t.insight || null,
          clarifyingQuestions: [],
          clarifyingContext: "",
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

  // Auto-submit a question injected from outside (e.g. "Investigate" from the Ontology canvas)
  const initialFiredRef = useRef(false);
  useEffect(() => {
    if (!initialQuestion || initialFiredRef.current || state.streaming) return;
    initialFiredRef.current = true;
    if (initialMode) setMode(initialMode);
    // Small delay so the component is fully mounted and mode is set
    const t = setTimeout(() => {
      ask(initialQuestion, connectionId, initialMode ?? "investigate", { canvasId: canvasId ?? undefined });
    }, 80);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);

  const handleSend = useCallback(async (q?: string, m?: "ask" | "investigate", opts?: { skipCache?: boolean }) => {
    const question = (q ?? input).trim();
    if (!question || state.streaming) return;
    setInput("");
    // Upload attached file first, then send the question
    if (attachedFile) {
      try {
        await uploadDocument(attachedFile);
      } catch {
        // Non-fatal: still send the question even if upload fails
      }
      setAttachedFile(null);
    }
    ask(question, connectionId, m ?? mode, { ...opts, canvasId: canvasId ?? undefined });
    textareaRef.current?.focus();
  }, [input, state.streaming, ask, connectionId, canvasId, mode, attachedFile]);

  const isEmpty = state.turns.length === 0;

  // ── Feedback submission ───────────────────────────────────────────────────────
  async function handleFeedbackSubmit(invId: string, feedback: string) {
    try {
      await fetch(`${BASE}/investigations/${invId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback }),
      });
    } catch { /* non-fatal */ }
    setFeedbackDone(prev => new Set([...prev, invId]));
  }

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
    attachedFile,
    onAttach: setAttachedFile,
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden" style={{ background: "#0d0e11" }}>

      {isEmpty ? (
        /* ── Empty state ── */
        <div className="flex-1 flex flex-col items-center justify-center py-10">
          <div className="w-[90%] flex flex-col gap-5">

            {capabilities}

            {!capabilities && (
              <div className="text-center">
                <p className="text-[12px] font-bold text-zinc-200">Ask your data anything</p>
                <p className="text-[12px] text-zinc-500 mt-1.5">
                  Use <span className="text-zinc-400 font-bold">Quick</span> for fast SQL answers ·{" "}
                  <span className="text-violet-400/90 font-bold">Agentic</span> for deep root-cause analysis
                </p>
              </div>
            )}

            <InputBox {...inputBoxProps} multiline />

            <p className="text-[12px] text-center" style={{ color: "#687986" }}>Always review the accuracy of responses.</p>

            {/* Suggestions */}
            <div className="pt-1">
              <p className="text-[9.5px] uppercase tracking-[0.08em] mb-2" style={{ color: "#3e3f47" }}>Suggested questions</p>
              {loadingStarters ? (
                <div className="grid grid-cols-2 gap-1.5">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="h-14 rounded-lg animate-pulse" style={{ background: "#13141a" }} />
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-1.5">
                  {starters.map((s) => (
                    <button
                      key={s.text}
                      onClick={() => handleSend(s.text, s.mode)}
                      className="flex items-start gap-1.5 px-3 py-2 rounded-lg text-[11.5px] text-left leading-snug transition-all"
                      style={s.mode === "investigate" ? {
                        background: "#13141a",
                        border: "0.5px solid #1e2a1e",
                        color: "#4a7a55",
                      } : {
                        background: "#13141a",
                        border: "0.5px solid #1e1f24",
                        color: "#6e6f78",
                      }}
                      onMouseEnter={e => {
                        if (s.mode === "investigate") {
                          (e.currentTarget as HTMLElement).style.borderColor = "#2a4a2a";
                          (e.currentTarget as HTMLElement).style.color = "#4ade80";
                        } else {
                          (e.currentTarget as HTMLElement).style.borderColor = "#2a2b30";
                          (e.currentTarget as HTMLElement).style.color = "#c0bfbc";
                        }
                      }}
                      onMouseLeave={e => {
                        if (s.mode === "investigate") {
                          (e.currentTarget as HTMLElement).style.borderColor = "#1e2a1e";
                          (e.currentTarget as HTMLElement).style.color = "#4a7a55";
                        } else {
                          (e.currentTarget as HTMLElement).style.borderColor = "#1e1f24";
                          (e.currentTarget as HTMLElement).style.color = "#6e6f78";
                        }
                      }}
                    >
                      <span className="shrink-0 mt-0.5 opacity-70 text-[13px]">
                        {s.mode === "investigate"
                          ? <AiSparkleIcon label="" size="small" />
                          : <CommentIcon label="" size="small" />}
                      </span>
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
        <div className="flex flex-1 min-h-0 overflow-hidden">

          {/* ── Chat column (scroll + floating input) ── */}
          <div className="flex-1 min-h-0 overflow-hidden" style={{ position: "relative" }}>

            {/* Scrollable messages */}
            <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0 h-full">
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
                    {/* Post-investigation feedback — shown once per completed investigation with hypotheses */}
                    {turn.mode === "investigate" &&
                     turn.status === "done" &&
                     turn.hypotheses.length > 0 &&
                     turn.investigationId &&
                     !feedbackDone.has(turn.investigationId) && (
                      <div className="mt-4">
                        <FeedbackPrompt
                          investigationId={turn.investigationId}
                          hypotheses={turn.hypotheses}
                          postCompletion
                          onSubmit={(feedback) => handleFeedbackSubmit(turn.investigationId!, feedback)}
                        />
                      </div>
                    )}
                  </div>
                ))}
                {/* Spacer so last message clears the floating input */}
                <div style={{ height: 172 }} />
              </div>
            </div>

            {/* Gradient fade — blends messages into the float */}
            <div style={{
              position: "absolute", bottom: 0, left: 0, right: 0,
              height: 200, pointerEvents: "none", zIndex: 1,
              background: "linear-gradient(to bottom, transparent 0%, #0d0e11 68%)",
            }} />

            {/* ── Floating input ── */}
            <div style={{
              position: "absolute", bottom: 20, left: 0, right: 0,
              zIndex: 2, pointerEvents: "none",
            }}>
              <div className="w-[90%] mx-auto space-y-2" style={{ pointerEvents: "all" }}>
                <InputBox {...inputBoxProps} />
                <p className="text-[12px] text-center" style={{ color: "#687986" }}>Always review the accuracy of responses.</p>
              </div>
            </div>

          </div>

          {/* Agent trace now renders inline within each assistant turn (ChatMessage). */}

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
      )}

      {/* ── Debug log drawer ── */}
      {showDebug && (
        <DebugLogDrawer eventLogRef={eventLogRef} onClose={() => setShowDebug(false)} />
      )}
    </div>
  );
}
