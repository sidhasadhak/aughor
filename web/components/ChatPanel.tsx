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
import { uploadDocument, listUserAgents, type UserAgent } from "@/lib/api";
import { useChat, type DebugEvent, type ChatTurn } from "@/lib/useChat";
import { useStickToBottom } from "@/lib/useStickToBottom";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/brief/StatusChip";
import { ChatMessage, SourcePanel, type SourcePanelData } from "./ChatMessage";
import { ErrorBoundary } from "./ErrorBoundary";
import { TrustReceipt } from "./TrustReceipt";
import { WhyThisNumber } from "./WhyThisNumber";

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
  /** When the seeded question is a drill into a known finding, its insight id —
   *  routes the first turn to the Tier-0 Finding Dossier instead of a fresh ADA run. */
  initialInsightId?: string;
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
  mode: "auto" | "ask" | "investigate";
  setMode: (m: "auto" | "ask" | "investigate") => void;
  onSend: () => void;
  onStop: () => void;
  onClear: () => void;
  attachedFile?: File | null;
  onAttach?: (f: File | null) => void;
  // User-defined agents (flag `agents.user_defined`) — empty roster hides the picker.
  agents?: UserAgent[];
  agentId?: string;
  setAgentId?: (id: string) => void;
}

function InputBox({ textareaRef, multiline, input, setInput, streaming, mode, setMode, onSend, onStop, onClear, attachedFile, onAttach, agents, agentId, setAgentId }: InputBoxProps) {
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
        background: "var(--bg-1)",
        // Focus ring rides the v2 accent tokens (the old rgba(45,114,210,…) was the
        // retired v1 Blueprint blue, invisible to theme flips).
        border: focused
          ? "1px solid var(--bfocus)"
          : "1px solid var(--b2)",
        boxShadow: focused
          ? "0 0 0 3px var(--acc-dim), var(--shadow-md), 0 1px 0 rgba(255,255,255,0.04) inset"
          : "var(--shadow-md), 0 1px 0 rgba(255,255,255,0.04) inset",
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
            <Button variant="ghost" size="icon-xs" onClick={() => onAttach?.(null)} title="Remove attachment"
              className="h-auto w-auto p-0 hover:bg-transparent dark:hover:bg-transparent"
              style={{ marginLeft: 2, opacity: .6, lineHeight: 1, color: "inherit", fontSize: 12 }}>×</Button>
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
        className="w-full bg-transparent aug-fs-sm text-zinc-100 placeholder:text-zinc-500 px-4 pt-3 pb-2 resize-none focus:outline-none disabled:opacity-50"
      />

      {/* Toggle row — mode buttons left, actions right */}
      <div className="flex items-center justify-between px-3 pb-2">
        {/* Mode toggle — Auto decides depth for you; Insight/Deep force it. */}
        <div style={{ display: "flex", alignItems: "center", gap: 2, padding: "2px", background: "var(--bg-0)", borderRadius: "var(--r2)", border: "1px solid var(--b1)" }}>
          <button
            onClick={() => setMode("auto")}
            title="Let the agent choose how deep to go"
            style={{
              display: "flex", alignItems: "center", gap: 5, padding: "3px 10px",
              borderRadius: "var(--r1)", fontSize: 11, fontWeight: 500, fontFamily: "var(--font-ui)",
              cursor: "pointer", border: mode === "auto" ? "1px solid var(--blue2)" : "1px solid transparent",
              transition: "all .12s",
              background: mode === "auto" ? "var(--blue1)" : "transparent",
              color: mode === "auto" ? "var(--blue5)" : "var(--t3)",
              boxShadow: mode === "auto" ? "0 1px 3px rgba(0,0,0,.3)" : "none",
            }}
          >
            <AiSparkleIcon label="Auto" size="small" />
            Auto
          </button>
          <button
            onClick={() => setMode("ask")}
            style={{
              display: "flex", alignItems: "center", gap: 5, padding: "3px 10px",
              borderRadius: "var(--r1)", fontSize: 11, fontWeight: 500, fontFamily: "var(--font-ui)",
              cursor: "pointer", border: "1px solid transparent", transition: "all .12s",
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
            Deep
          </button>
        </div>

        {/* Agent picker (flag `agents.user_defined`) — answer AS a saved persona.
            Hidden when the roster is empty (flag off → the list endpoint 404s → []). */}
        {(agents?.length ?? 0) > 0 && setAgentId && (
          <select
            value={agentId ?? ""}
            onChange={(e) => setAgentId(e.target.value)}
            disabled={streaming}
            title="Answer as a saved agent (its instructions, documents and connection apply)"
            style={{
              marginLeft: 8, marginRight: "auto", padding: "3px 8px", fontSize: 11, fontWeight: 500,
              fontFamily: "var(--font-ui)", borderRadius: "var(--r1)",
              background: agentId ? "var(--grn1)" : "var(--bg-0)",
              border: `1px solid ${agentId ? "var(--grn2)" : "var(--b1)"}`,
              color: agentId ? "var(--grn5)" : "var(--t3)", cursor: "pointer",
            }}
          >
            <option value="">No agent</option>
            {agents!.filter(a => a.enabled).map(a => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        )}

        {/* Actions: clear · attach · send/stop */}
        <div className="flex items-center gap-1.5">
          {!multiline && !streaming && (
            <Button
              variant="ghost"
              size="xs"
              onClick={onClear}
              className="aug-fs-sm px-1"
              style={{ color: "var(--t3)" }}
              title="Clear conversation"
            >
              Clear
            </Button>
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
            className="flex items-center justify-center rounded-[var(--r3)] transition-colors disabled:opacity-30"
            style={{
              width: 30, height: 30,
              color: attachedFile ? "var(--blue4)" : "var(--t3)",
              background: attachedFile ? "var(--acc-dim)" : "transparent",
            }}
            onMouseEnter={e => { if (!attachedFile) (e.currentTarget as HTMLElement).style.color = "var(--t1)"; }}
            onMouseLeave={e => { if (!attachedFile) (e.currentTarget as HTMLElement).style.color = "var(--t3)"; }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
            </svg>
          </button>

          {/* Send / Stop */}
          {streaming ? (
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onStop}
              title="Stop"
              className="rounded-[var(--r3)] bg-red-500/15 border-red-500/30 text-red-400 hover:bg-red-500/25 hover:text-red-400"
              style={{ width: 30, height: 30 }}
            >
              <VideoStopIcon label="Stop" size="small" />
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => onSend()}
              disabled={!input.trim()}
              title="Send"
              className="aug-pressable rounded-[var(--r3)] text-zinc-500 hover:text-zinc-100 disabled:opacity-25"
              style={{ width: 30, height: 30 }}
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </Button>
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
    <div className="fixed bottom-0 right-0 z-50 flex flex-col bg-zinc-950 border border-zinc-700/80 rounded-tl-[var(--r3)] shadow-2xl" style={{ width: 520, height: 380 }}>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800 shrink-0">
        <span className="text-emerald-400"><AngleBracketsIcon label="Debug log" size="small" /></span>
        <span className="aug-fs-xs font-mono text-zinc-300 flex-1">SSE Event Log · {events.length} events</span>
        <span className="aug-fs-xs text-zinc-500 mr-2">⌘⇧L to close</span>
        <Button variant="ghost" size="icon-xs" onClick={onClose} className="text-zinc-500 hover:text-zinc-300 hover:bg-transparent"><CloseIcon label="Close" size="small" /></Button>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0 font-mono aug-fs-xs">
        {events.length === 0 ? (
          <p className="text-zinc-500 p-3">No events yet. Send a message to start.</p>
        ) : events.map((ev, i) => (
          <div key={i} className="border-b border-zinc-900 hover:bg-zinc-900/40">
            <button
              className="w-full flex items-center gap-2 px-3 py-1.5 text-left"
              onClick={() => setExpanded(expanded === i ? null : i)}
            >
              {expanded === i
                ? <span className="text-zinc-500 shrink-0"><ChevronDownIcon label="" size="small" /></span>
                : <span className="text-zinc-500 shrink-0"><ChevronRightIcon label="" size="small" /></span>}
              <span className="text-zinc-500 shrink-0">{new Date(ev.ts).toLocaleTimeString()}</span>
              <span className={`shrink-0 w-28 truncate ${TYPE_COLOR[ev.type] ?? "text-zinc-300"}`}>{ev.type}</span>
              <span className="text-zinc-500 truncate flex-1">{ev.summary}</span>
            </button>
            {expanded === i && (
              <pre className="px-4 py-2 aug-fs-xs text-zinc-400 bg-zinc-900/60 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                {JSON.stringify(ev.payload, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Depth banner — the auto+transparency receipt on each /ask turn ──
   Shows the depth the router chose + why, with a one-click re-run at the
   other depth. Renders nothing on legacy/explicit and restored turns. */
function DepthBanner({ turn, onRerun }: { turn: ChatTurn; onRerun: (depth: "quick" | "deep") => void }) {
  const r = turn.route;
  if (!r) return null;
  const deep = r.depth === "deep";
  const done = turn.status !== "loading";
  return (
    <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
      <StatusChip
        hue={deep ? "accent" : "info"}
        icon={deep ? <AiSparkleIcon label="" size="small" /> : <CommentIcon label="" size="small" />}
      >
        {deep ? "Deep analysis" : "Quick answer"}
      </StatusChip>
      <span style={{ fontSize: 11.5, color: "var(--t3)" }}>{r.why}</span>
      {r.downgradedFrom && (
        <span style={{ fontSize: 11, fontStyle: "italic", color: "var(--t3)" }}>· deep analysis needs an upgrade</span>
      )}
      {done && (
        <Button
          variant="ghost"
          size="xs"
          onClick={() => onRerun(deep ? "quick" : "deep")}
          title={deep ? "Re-run as a quick answer" : "Re-run as a deep investigation"}
          className="h-auto p-0 hover:bg-transparent dark:hover:bg-transparent"
          style={{ marginLeft: "auto", fontSize: 11, fontWeight: 500, color: "var(--blue4)" }}
        >
          {deep ? "Answer quickly instead →" : "Investigate instead →"}
        </Button>
      )}
    </div>
  );
}

/* ── Agent badge — the user-agent receipt on a turn (flag `agents.user_defined`).
   Mirrors DepthBanner: reads turn.agent, renders nothing on plain turns. */
function AgentBadge({ turn }: { turn: ChatTurn }) {
  const a = turn.agent;
  if (!a) return null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
      <StatusChip hue="positive" icon={<AiSparkleIcon label="" size="small" />}>
        Answering as {a.name}
      </StatusChip>
      {a.docCount > 0 && (
        <span style={{ fontSize: 11.5, color: "var(--t3)" }}>
          {a.docCount} bound document{a.docCount === 1 ? "" : "s"}
        </span>
      )}
    </div>
  );
}

/* ── Clarify card — the ask-vs-guess prompt (Phase 3) ──
   Shown when the agent asked one targeted question instead of guessing. The user's
   reply (an option chip, a typed detail, or "answer anyway") re-asks the original
   question with skip_clarify so we don't loop. */
function ClarifyCard({ turn, onClarify, onAnswerAnyway }: {
  turn: ChatTurn;
  onClarify: (detail: string) => void;
  onAnswerAnyway: () => void;
}) {
  const c = turn.clarify;
  const [val, setVal] = useState("");
  if (!c) return null;
  const submit = () => { const v = val.trim(); if (v) { onClarify(v); setVal(""); } };
  return (
    <div style={{ marginTop: 8, padding: "12px 14px", borderRadius: "var(--r2)", background: "var(--blue1)", border: "1px solid var(--blue2)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: c.reason ? 4 : 8 }}>
        <span style={{ color: "var(--blue5)", display: "inline-flex" }}><CommentIcon label="" size="small" /></span>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--blue5)" }}>{c.question}</span>
      </div>
      {c.reason && <p style={{ fontSize: 11.5, color: "var(--t3)", margin: "0 0 8px 23px" }}>{c.reason}</p>}
      {c.options.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {c.options.map((o, i) => (
            <Button key={`${i}:${o}`} variant="outline" size="xs" onClick={() => onClarify(o)}
              className="h-auto flex-col items-start gap-px whitespace-normal text-left"
              style={{ fontSize: 12, fontWeight: 500, padding: "4px 10px", background: "var(--bg-1)", borderColor: "var(--blue2)", color: "var(--blue5)" }}>
              <span>{o}</span>
              {c.previews?.[i] && <span style={{ fontSize: 10.5, fontWeight: 400, color: "var(--t3)" }}>{c.previews[i]}</span>}
            </Button>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input
          value={val}
          onChange={e => setVal(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); submit(); } }}
          placeholder="Add the detail…"
          style={{ flex: 1, fontSize: 12, padding: "6px 10px", borderRadius: "var(--r1)", background: "var(--bg-1)", border: "1px solid var(--b2)", color: "var(--t1)", outline: "none" }}
        />
        <Button variant="ghost" size="xs" onClick={submit} disabled={!val.trim()}
          className="h-auto hover:bg-transparent dark:hover:bg-transparent disabled:opacity-40"
          style={{ fontSize: 12, fontWeight: 500, color: "var(--blue4)", padding: "6px 4px" }}>
          Send
        </Button>
        <Button variant="ghost" size="xs" onClick={onAnswerAnyway} title="Answer with a best guess"
          className="h-auto font-normal hover:bg-transparent dark:hover:bg-transparent"
          style={{ fontSize: 11.5, color: "var(--t3)", padding: "6px 4px" }}>
          Answer anyway →
        </Button>
      </div>
    </div>
  );
}

/* ── Escalation bar — progressive escalation (Phase 5) ──
   Shown when a quick answer was inconclusive; one click re-runs the question as a
   deep investigation (auto + transparency — the agent offers, the user decides). */
function EscalateBar({ turn, onEscalate }: { turn: ChatTurn; onEscalate: () => void }) {
  const e = turn.escalate;
  if (!e || turn.status === "loading") return null;
  return (
    <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8, marginTop: 8,
                  padding: "8px 12px", borderRadius: "var(--r2)", background: "var(--vio1)", border: "1px solid var(--vio2)" }}>
      <span style={{ color: "var(--vio5)", display: "inline-flex" }}><AiSparkleIcon label="" size="small" /></span>
      <span style={{ fontSize: 12, color: "var(--t2)", flex: 1, minWidth: 180 }}>{e.reason}</span>
      <Button
        variant="ghost"
        size="xs"
        onClick={onEscalate}
        className="h-auto p-0 hover:bg-transparent dark:hover:bg-transparent"
        style={{ fontSize: 12, fontWeight: 500, color: "var(--vio5)" }}
      >
        Investigate this →
      </Button>
    </div>
  );
}

export function ChatPanel({ connectionId, canvasId, restoreSessionId, initialQuestion, initialMode, initialInsightId, capabilities }: Props) {
  const { state, ask, stop, clear, restore, resumePlan, rejectPlan, resumeClarify, eventLogRef } = useChat();
  const [input, setInput]           = useState("");
  const [mode, setMode]             = useState<"auto" | "ask" | "investigate">("auto");
  // User-defined agents (flag `agents.user_defined`): the roster + the picked persona.
  const [agents, setAgents]         = useState<UserAgent[]>([]);
  const [agentId, setAgentId]       = useState<string>("");
  useEffect(() => { listUserAgents().then(setAgents).catch(() => {}); }, []);
  const [starters, setStarters]     = useState<Starter[]>(FALLBACK_STARTERS);
  const [loadingStarters, setLoadingStarters] = useState(false);
  const [showDebug, setShowDebug]   = useState(false);
  const [feedbackDone, setFeedbackDone] = useState<Set<string>>(new Set());
  const [sourcePanel, setSourcePanel] = useState<SourcePanelData | null>(null);
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
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
          route: null,
          agent: null,
          clarify: null,
          escalate: null,
          // Restored turns: the turn id IS the receipt key; the component 404-noops
          // gracefully if this turn predates receipts.
          receiptId: t.sql ? t.id : null,
          publicReceiptId: null,   // restored turns use the per-mode receipt route (receiptId)
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
          dossierReport: null,
          dossierInsightId: null,
          queriesExecuted: [],
          latestScore: null,
          hypotheses: [],
          investigationId: null,
          tablesUsed: t.tables_used || [],
          contextManifest: null,
          planPending: null,
          clarifyPending: null,
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
          insightStream: null,   // deltas are live-only; history restores the final insight
          clarifyingQuestions: [],
          clarifyingContext: "",
        })));
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restoreSessionId]);

  // ── Scroll: follow the newest content while pinned to the bottom, release
  //    the moment the user scrolls up to read, snap back on completion. ───────
  const streamingKey = state.turns.map(t => `${t.id}:${t.phases.length}:${t.statusText}`).join("|");
  const { scrollRef, pinned, scrollToBottom } = useStickToBottom(streamingKey, { active: state.streaming });

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
    if (initialMode) setMode(initialMode);
    // Small delay so the component is fully mounted and mode is set.
    // The fired-latch is set INSIDE the timer: StrictMode's dev double-invoke
    // (setup → cleanup → setup) clears the first timer, and latching eagerly
    // would make the second setup bail — auto-submit would never fire in dev.
    const t = setTimeout(() => {
      initialFiredRef.current = true;
      ask(initialQuestion, connectionId, initialMode ?? "investigate", { canvasId: canvasId ?? undefined, insightId: initialInsightId });
    }, 80);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);

  const handleSend = useCallback(async (q?: string, m?: "auto" | "ask" | "investigate", opts?: { skipCache?: boolean }) => {
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
    ask(question, connectionId, m ?? mode, { ...opts, canvasId: canvasId ?? undefined, agentId: agentId || undefined });
    textareaRef.current?.focus();
  }, [input, state.streaming, ask, connectionId, canvasId, mode, attachedFile, agentId]);

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
    agents,
    agentId,
    setAgentId,
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden" style={{ background: "var(--bg-1)" }}>

      {isEmpty ? (
        /* ── Empty state ── */
        <div className="flex-1 flex flex-col items-center justify-center py-10">
          <div className="w-[90%] max-w-[var(--measure-chat)] flex flex-col gap-5">

            {capabilities}

            {!capabilities && (
              <div className="text-center">
                <p className="aug-fs-sm font-bold text-zinc-200">Ask your data anything</p>
                <p className="aug-fs-sm text-zinc-500 mt-1.5">
                  <span className="text-zinc-400 font-bold">Auto</span> picks the right depth for each question —
                  or choose <span className="text-zinc-400 font-bold">Insight</span> /{" "}
                  <span className="text-violet-400/90 font-bold">Deep</span> yourself.
                </p>
              </div>
            )}

            <InputBox {...inputBoxProps} multiline />

            <p className="aug-fs-sm text-center" style={{ color: "var(--t3)" }}>Always review the accuracy of responses.</p>

            {/* Suggestions */}
            <div className="pt-1">
              <p className="text-[9.5px] uppercase tracking-[0.08em] mb-2" style={{ color: "var(--b3)" }}>Suggested questions</p>
              {loadingStarters ? (
                <div className="grid grid-cols-2 gap-1.5">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="h-14 rounded-[var(--r3)] animate-pulse" style={{ background: "var(--bg-1)" }} />
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-1.5">
                  {starters.map((s) => (
                    <button
                      key={s.text}
                      onClick={() => handleSend(s.text, s.mode)}
                      className="aug-pressable flex items-start gap-1.5 px-3 py-2 rounded-[var(--r3)] text-[11.5px] text-left leading-snug transition-all"
                      style={s.mode === "investigate" ? {
                        background: "var(--bg-1)",
                        border: "0.5px solid var(--grn1)",
                        color: "var(--grn4)",
                      } : {
                        background: "var(--bg-1)",
                        border: "0.5px solid var(--b2)",
                        color: "var(--t3)",
                      }}
                      onMouseEnter={e => {
                        if (s.mode === "investigate") {
                          (e.currentTarget as HTMLElement).style.borderColor = "var(--grn2)";
                          (e.currentTarget as HTMLElement).style.color = "var(--grn4)";
                        } else {
                          (e.currentTarget as HTMLElement).style.borderColor = "var(--b2)";
                          (e.currentTarget as HTMLElement).style.color = "var(--t1)";
                        }
                      }}
                      onMouseLeave={e => {
                        if (s.mode === "investigate") {
                          (e.currentTarget as HTMLElement).style.borderColor = "var(--grn1)";
                          (e.currentTarget as HTMLElement).style.color = "var(--grn4)";
                        } else {
                          (e.currentTarget as HTMLElement).style.borderColor = "var(--bg-3)";
                          (e.currentTarget as HTMLElement).style.color = "var(--t3)";
                        }
                      }}
                    >
                      <span className="shrink-0 mt-0.5 opacity-70 aug-fs-ui">
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
              <div className="py-8 w-[90%] max-w-[var(--measure-chat)] mx-auto">
                {state.turns.map((turn, i) => (
                  <div
                    key={turn.id}
                    className="aug-anim-up"
                    ref={el => {
                      if (el) turnTopRefs.current.set(turn.id, el);
                      else turnTopRefs.current.delete(turn.id);
                    }}
                  >
                    {i > 0 && <div className="border-t border-zinc-800 my-8" />}
                    <DepthBanner
                      turn={turn}
                      onRerun={(depth) => ask(turn.question, connectionId, "auto", { canvasId: canvasId ?? undefined, depth })}
                    />
                    <AgentBadge turn={turn} />
                    {/* WP-2 — isolate a single answer's render: a throw here (a malformed
                        report, a recovered-report shape mismatch) must not white-screen the
                        conversation or kill the composer. */}
                    <ErrorBoundary label="This answer couldn't be displayed.">
                      <ChatMessage
                        turn={turn}
                        connectionId={connectionId}
                        onFollowUp={(q) => handleSend(q)}
                        onRunFresh={(q) => handleSend(q, "investigate", { skipCache: true })}
                        onShowSource={setSourcePanel}
                        onDeeper={(q, insightId) => ask(q, connectionId, "investigate", { canvasId: canvasId ?? undefined, insightId: insightId ?? undefined, deep: true })}
                        onApprovePlan={(invId, keep) => resumePlan(invId, keep)}
                        onRejectPlan={(invId) => rejectPlan(invId)}
                        onChooseClarify={(invId, opt) => resumeClarify(invId, opt)}
                      />
                    </ErrorBoundary>
                    {turn.clarify && (
                      <ClarifyCard
                        turn={turn}
                        onClarify={(detail) => ask(`${turn.question} — ${detail}`, connectionId, "auto", { canvasId: canvasId ?? undefined, skipClarify: true, clarifyReading: detail, clarifySubject: turn.question, clarifySource: turn.clarify?.source })}
                        onAnswerAnyway={() => ask(turn.question, connectionId, "auto", { canvasId: canvasId ?? undefined, skipClarify: true })}
                      />
                    )}
                    {turn.escalate && (
                      <EscalateBar
                        turn={turn}
                        onEscalate={() => ask(turn.question, connectionId, "auto", { canvasId: canvasId ?? undefined, depth: "deep", skipClarify: true })}
                      />
                    )}
                    {/* B-9 — Trust Receipt on every answered turn that has one:
                        a chat answer (receiptId) or an agentic ADA report
                        (investigationId). */}
                    {turn.status === "done" && turn.receiptId && (
                      <TrustReceipt connectionId={connectionId} receiptId={turn.receiptId} />
                    )}
                    {turn.status === "done" && turn.adaReport && turn.investigationId && (
                      <TrustReceipt connectionId={connectionId} receiptId={turn.investigationId} kind="ada" />
                    )}
                    {/* WP-10 — "Why this number": opens the unified signed receipt (GET /receipt/{id}). */}
                    {turn.status === "done" && turn.publicReceiptId && (
                      <WhyThisNumber receiptId={turn.publicReceiptId} />
                    )}
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
              background: "linear-gradient(to bottom, transparent 0%, var(--bg-1) 68%)",
            }} />

            {/* ── Jump to latest — shown only when the user has scrolled up off
                 the newest content (stick-to-bottom released). ── */}
            {!pinned && (
              <div style={{
                position: "absolute", bottom: 96, left: 0, right: 0,
                zIndex: 3, display: "flex", justifyContent: "center", pointerEvents: "none",
              }}>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => scrollToBottom()}
                  title="Jump to latest"
                  className="aug-pressable aug-anim-fade gap-1.5 rounded-[var(--r-pill)] h-auto"
                  style={{
                    pointerEvents: "all", padding: "5px 12px 5px 9px",
                    fontSize: 11.5, fontWeight: 500, fontFamily: "var(--font-ui)",
                    color: "var(--t2)", background: "var(--bg-3)", border: "1px solid var(--b2)",
                    boxShadow: "0 4px 14px rgba(0,0,0,0.4)",
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "var(--t1)"; (e.currentTarget as HTMLElement).style.borderColor = "var(--b3)"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "var(--t2)"; (e.currentTarget as HTMLElement).style.borderColor = "var(--b2)"; }}
                >
                  <ChevronDownIcon label="" size="small" />
                  Jump to latest
                </Button>
              </div>
            )}

            {/* ── Floating input ── */}
            <div style={{
              position: "absolute", bottom: 20, left: 0, right: 0,
              zIndex: 2, pointerEvents: "none",
            }}>
              <div className="w-[90%] max-w-[var(--measure-chat)] mx-auto space-y-2" style={{ pointerEvents: "all" }}>
                <InputBox {...inputBoxProps} />
                <p className="aug-fs-sm text-center" style={{ color: "var(--t3)" }}>Always review the accuracy of responses.</p>
              </div>
            </div>

          </div>

          {/* Agent trace now renders inline within each assistant turn (ChatMessage). */}

          {/* ── Source panel drawer (right side, pushes chat left) ── */}
          {sourcePanel && (
            <div
              className="flex-shrink-0 flex flex-col border-l border-zinc-700/60"
              style={{ width: 380, background: "var(--blue1)" }}
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
