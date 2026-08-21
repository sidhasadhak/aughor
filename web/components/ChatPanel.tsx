"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { listUserAgents, recordOverviewDrill, cancelInvestigation, type UserAgent } from "@/lib/api";
import { uploadAttachment, type AttachmentResult } from "@/lib/attachments";
import { projectThread, newSessionId, type AughorUIMessage, type ChatTurn } from "@/lib/chatTurn";
import { useAughorChat } from "@/lib/useAughorChat";
import { useStickToBottom } from "@/lib/useStickToBottom";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/brief/StatusChip";
import { SourcePanel, type SourcePanelData } from "./ChatMessage";
import { PartsMessage } from "./chat/PartsMessage";
import { ErrorBoundary } from "./ErrorBoundary";
import { WhyThisNumber } from "./WhyThisNumber";

import { getApiBase } from "@/lib/config";
import { FeedbackPrompt } from "@/components/FeedbackPrompt";
import { Icon } from "@/components/ui/icon";

const FALLBACK_STARTERS = [
  { text: "Show me the top 10 rows from any table",  mode: "ask" as const },
  { text: "What tables are available?",              mode: "ask" as const },
  { text: "What was the average order value last month?", mode: "ask" as const },
  { text: "Why did a key metric change recently?",   mode: "investigate" as const },
  { text: "What is driving an unexpected trend?",    mode: "investigate" as const },
  { text: "Diagnose an anomaly in the data",         mode: "investigate" as const },
];

// The Genie-style default first-look — always the FIRST, featured starter on a
// fresh chat. Auto mode routes it to the deterministic overview fact tour.
const OVERVIEW_STARTER: Starter = {
  text: "Show me interesting facts about this schema",
  mode: "ask",
};

// requestMode/purpose (R13): a named research starter's declared route — sent on
// /ask so the router pins investigate|explore deterministically; chips style deep.
type Starter = { text: string; mode: "ask" | "investigate"; requestMode?: "investigate" | "explore"; purpose?: string };

interface Props {
  connectionId: string;
  canvasId?: string | null;
  restoreSessionId?: string | null;
  initialQuestion?: string;
  initialMode?: "ask" | "investigate";
  /** When the seeded question is a drill into a known finding, its insight id —
   *  routes the first turn to the Tier-0 Finding Dossier instead of a fresh deep analysis. */
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
  // User-defined agents — an empty roster hides the picker.
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
      className="flex flex-col overflow-hidden"
      style={{
        // A generous composer pill (CK-grade): soft corners, a surface one step up
        // from the page, and shadow-only elevation — the border stays a whisper
        // until focus lights the v2 accent ring.
        borderRadius: "var(--r-composer)",
        background: "var(--bg-2)",
        border: focused
          ? "1px solid var(--bfocus)"
          : "1px solid var(--b1)",
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
            <Icon name="attach" size={11} className="shrink-0" />
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
        /* P5 — the input is NEVER disabled. A user who has thought of the next question
           while an answer streams should be able to type it; sending interrupts the run
           in flight (useChat.ask aborts before it starts, and the backend stops the core
           at its next checkpoint). Disabling here made the product argue with the user
           about whose turn it was. */
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
            <Icon name="spark" size={16} label="Auto" />
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
            <Icon name="chat" size={16} label="Quick" />
            Quick
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
            <Icon name="spark" size={16} label="Deep analysis" />
            Deep analysis
          </button>
        </div>

        {/* Agent picker — answer AS a saved user-defined persona.
            Hidden when the roster is empty (flag off → the list endpoint 404s → []). */}
        {(agents?.length ?? 0) > 0 && setAgentId && (
          <select
            value={agentId ?? ""}
            onChange={(e) => setAgentId(e.target.value)}
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
            className="flex items-center justify-center rounded-[var(--r3)] transition-colors disabled:opacity-30"
            style={{
              width: 30, height: 30,
              color: attachedFile ? "var(--blue4)" : "var(--t3)",
              background: attachedFile ? "var(--acc-dim)" : "transparent",
            }}
            onMouseEnter={e => { if (!attachedFile) (e.currentTarget as HTMLElement).style.color = "var(--t1)"; }}
            onMouseLeave={e => { if (!attachedFile) (e.currentTarget as HTMLElement).style.color = "var(--t3)"; }}
          >
            <Icon name="attach" size={15} label="Attach a file" />
          </button>

          {/* Send ⇄ Stop — one solid circular button that morphs in place (CK-grade):
              a filled interactive-blue disc with an up-arrow while composing, a filled
              square while a run streams (kept enabled so Stop is always one click away). */}
          {streaming ? (
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onStop}
              title="Stop"
              className="aug-pressable rounded-[var(--r-pill)] hover:bg-transparent dark:hover:bg-transparent"
              style={{ width: 32, height: 32, background: "var(--t2)", color: "var(--bg-1)" }}
            >
              <Icon name="stop" size={12} className="aug-icon-filled" />
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => onSend()}
              disabled={!input.trim()}
              title="Send"
              className="aug-pressable rounded-[var(--r-pill)] hover:bg-transparent dark:hover:bg-transparent disabled:opacity-100"
              style={{
                width: 32, height: 32,
                background: input.trim() ? "var(--blue-solid)" : "var(--bg-3)",
                color: input.trim() ? "#fff" : "var(--t3)",
              }}
            >
              <Icon name="send" size={16} stroke={2.2} />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Debug log drawer ──────────────────────────────────────────────────────────
// CA-1: fed from the SDK's onData callback (every typed data part as it arrives)
// rather than the retired reducer's SSE tap. Text deltas don't appear — the
// drawer's job is "which frames arrived", and every frame that isn't pure text
// is a data part now.

export interface DebugEvent {
  ts: number;            // Date.now()
  type: string;          // data part name (the wire frame's type)
  summary: string;       // brief human-readable summary
  payload: unknown;      // full payload (shown on expand)
}
const MAX_LOG = 300;

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

  // Keyed by SSE event TYPE — wire names, frozen (`ada_report` is the backend's spelling).
  const TYPE_COLOR: Record<string, string> = {
    start: "text-sky-400", done: "text-emerald-400", error: "text-red-400",
    ada_report: "text-violet-400", explore_report: "text-teal-400", report: "text-blue-400",
    phase_complete: "text-amber-400", tables_used: "text-zinc-400", followups: "text-zinc-400",
  };

  return (
    <div className="fixed bottom-0 right-0 z-50 flex flex-col bg-zinc-950 border border-zinc-700/80 rounded-tl-[var(--r3)] shadow-2xl" style={{ width: 520, height: 380 }}>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800 shrink-0">
        <span className="text-emerald-400"><Icon name="sql" size={16} label="Debug log" /></span>
        <span className="aug-fs-xs font-mono text-zinc-300 flex-1">SSE Event Log · {events.length} events</span>
        <span className="aug-fs-xs text-zinc-500 mr-2">⌘⇧L to close</span>
        <Button variant="ghost" size="icon-xs" onClick={onClose} className="text-zinc-500 hover:text-zinc-300 hover:bg-transparent"><Icon name="close" size={16} label="Close" /></Button>
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
                ? <span className="text-zinc-500 shrink-0"><Icon name="chevd" size={16} /></span>
                : <span className="text-zinc-500 shrink-0"><Icon name="chevr" size={16} /></span>}
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
  const overview = r.depth === "overview";
  const done = turn.status !== "loading";
  return (
    <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
      <StatusChip
        hue={deep ? "accent" : "info"}
        icon={deep ? <Icon name="spark" size={16} /> : <Icon name="chat" size={16} />}
      >
        {deep ? "Deep analysis" : overview ? "Overview" : "Quick answer"}
      </StatusChip>
      <span style={{ fontSize: 12, color: "var(--t3)" }}>{r.why}</span>
      {r.downgradedFrom && (
        <span style={{ fontSize: 11, fontStyle: "italic", color: "var(--t3)" }}>· deep analysis needs an upgrade</span>
      )}
      {done && !overview && (
        <Button
          variant="ghost"
          size="xs"
          onClick={() => onRerun(deep ? "quick" : "deep")}
          title={deep ? "Re-run as a quick answer" : "Re-run as a deep analysis"}
          className="h-auto p-0 hover:bg-transparent dark:hover:bg-transparent"
          style={{ marginLeft: "auto", fontSize: 11, fontWeight: 500, color: "var(--blue4)" }}
        >
          {deep ? "Answer quickly instead →" : "Investigate instead →"}
        </Button>
      )}
    </div>
  );
}

/* ── Agent badge — the user-agent receipt on a turn.
   Mirrors DepthBanner: reads turn.agent, renders nothing on plain turns. */
function AgentBadge({ turn }: { turn: ChatTurn }) {
  const a = turn.agent;
  if (!a) return null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
      <StatusChip hue="positive" icon={<Icon name="spark" size={16} />}>
        Answering as {a.name}
      </StatusChip>
      {a.docCount > 0 && (
        <span style={{ fontSize: 12, color: "var(--t3)" }}>
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
        <span style={{ color: "var(--blue5)", display: "inline-flex" }}><Icon name="chat" size={16} /></span>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--blue5)" }}>{c.question}</span>
      </div>
      {c.reason && <p style={{ fontSize: 12, color: "var(--t3)", margin: "0 0 8px 23px" }}>{c.reason}</p>}
      {c.options.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {c.options.map((o, i) => (
            <Button key={`${i}:${o}`} variant="outline" size="xs" onClick={() => onClarify(o)}
              className="h-auto flex-col items-start gap-px whitespace-normal text-left"
              style={{ fontSize: 12, fontWeight: 500, padding: "4px 10px", background: "var(--bg-1)", borderColor: "var(--blue2)", color: "var(--blue5)" }}>
              <span>{o}</span>
              {c.previews?.[i] && <span style={{ fontSize: 11, fontWeight: 400, color: "var(--t3)" }}>{c.previews[i]}</span>}
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
          style={{ fontSize: 12, color: "var(--t3)", padding: "6px 4px" }}>
          Answer anyway →
        </Button>
      </div>
    </div>
  );
}

/* ── Escalation bar — progressive escalation (Phase 5) ──
   Shown when a quick answer was inconclusive; one click re-runs the question as a
   deep analysis (auto + transparency — the agent offers, the user decides). */
function EscalateBar({ turn, onEscalate }: { turn: ChatTurn; onEscalate: () => void }) {
  const e = turn.escalate;
  if (!e || turn.status === "loading") return null;
  return (
    <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8, marginTop: 8,
                  padding: "8px 12px", borderRadius: "var(--r2)", background: "var(--vio1)", border: "1px solid var(--vio2)" }}>
      <span style={{ color: "var(--vio5)", display: "inline-flex" }}><Icon name="spark" size={16} /></span>
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

//: The `?chat=` id may be adopted exactly once per page load.
//
// A browser RELOAD and the "New conversation" button both remount this component — the
// button resets it by bumping a React key — so mounting is not enough to tell them
// apart, and a component that resumed on every mount would make "New conversation" reopen
// the conversation the user just dismissed. A page load happens once; a reset can happen
// all afternoon. Module scope is exactly that lifetime.
let _urlSessionUnclaimed = true;

export function ChatPanel({ connectionId, canvasId, restoreSessionId, initialQuestion, initialMode, initialInsightId, capabilities }: Props) {
  // Read during the first render, into a ref, because both this component and page.tsx's
  // URL-sync effect rewrite the query string — whichever ran first would erase the id
  // before the restore below could read it. A ref initializer is safe here specifically
  // because this value is never rendered: what made the nav mismatch in #290 was
  // URL-seeded state that the server had no way to agree with, and a ref has no server
  // rendering to disagree with.
  const resumeIdRef = useRef<string | null>(null);
  if (resumeIdRef.current === null && typeof window !== "undefined") {
    const fromUrl = _urlSessionUnclaimed
      ? new URLSearchParams(window.location.search).get("chat")
      : null;
    _urlSessionUnclaimed = false;
    resumeIdRef.current = restoreSessionId || fromUrl || "";
  }
  const resumeId = resumeIdRef.current || null;

  // The conversation's identity. A resumed thread adopts its own id (reading a
  // session back and continuing it are the same act); "Clear" mints a fresh one,
  // which rebuilds the Chat instance and with it an empty message list.
  const [sessionId, setSessionId] = useState<string>(() => resumeId || newSessionId());

  // Debug event log — ring buffer, never triggers re-render; read on demand.
  const eventLogRef = useRef<DebugEvent[]>([]);

  // Wall-clock per turn, keyed by the turn's USER message id. The SDK message
  // carries no clock, so the surface that watches the stream measures it — the
  // "Completed in …" line and the arrival-fade both read from here. STATE, not a
  // ref: the projection reads it during render, and a ref written after the
  // stream settles would leave "Completed in" invisible until an unrelated
  // re-render. Restored turns are absent (inert), as the old restore left them.
  const [timings, setTimings] = useState<Map<string, { startedAt: number; elapsedMs: number | null }>>(new Map());

  const {
    messages, sendMessage, setMessages, regenerate, stop: sdkStop, status, error, clearError,
  } = useAughorChat({
    connectionId,
    sessionId,
    body: canvasId ? { canvas_id: canvasId } : undefined,
    onData: (part) => {
      const payload = (part as { data: unknown }).data;
      eventLogRef.current = [...eventLogRef.current.slice(-(MAX_LOG - 1)), {
        ts: Date.now(),
        type: part.type.slice("data-".length),
        summary: JSON.stringify(payload ?? {}).slice(0, 80),
        payload,
      }];
    },
  });

  const busy = status === "submitted" || status === "streaming";

  // ── messages → turns: the projection that replaced the reducer ─────────────
  // `projectThread` is pure, so this is a derivation, not a second store.
  const turns = useMemo(() => projectThread(messages, {
    streaming: busy,
    transportError: status === "error" ? (error?.message ?? "The turn failed.") : null,
    timingFor: (id) => timings.get(id),
  }), [messages, busy, status, error, timings]);

  // Wall-clock bookkeeping: stamp a turn when its stream opens, freeze it when
  // the stream settles. Mirrors the reducer's ASK / finish() pair.
  useEffect(() => {
    const last = turns[turns.length - 1];
    if (!last) return;
    const t = timings.get(last.userMsg.id);
    if (busy && !t) {
      setTimings((prev) => new Map(prev).set(last.userMsg.id, { startedAt: Date.now(), elapsedMs: null }));
    } else if (!busy && t && t.elapsedMs == null) {
      setTimings((prev) => new Map(prev).set(last.userMsg.id, { ...t, elapsedMs: Date.now() - t.startedAt }));
    }
  }, [busy, turns, timings]);

  const [input, setInput]           = useState("");
  const [mode, setMode]             = useState<"auto" | "ask" | "investigate">("auto");
  // User-defined agents: the roster + the picked persona.
  const [agents, setAgents]         = useState<UserAgent[]>([]);
  const [agentId, setAgentId]       = useState<string>("");
  useEffect(() => { listUserAgents().then(setAgents).catch(() => {}); }, []);
  const [starters, setStarters]     = useState<Starter[]>(FALLBACK_STARTERS);
  const [loadingStarters, setLoadingStarters] = useState(false);
  const [showDebug, setShowDebug]   = useState(false);
  const [feedbackDone, setFeedbackDone] = useState<Set<string>>(new Set());
  // R10 — thumbs on quick answers: turn receiptId → the verdict sent (one per turn).
  const [thumbsDone, setThumbsDone] = useState<Map<string, "helpful" | "unhelpful">>(new Map());
  const [sourcePanel, setSourcePanel] = useState<SourcePanelData | null>(null);
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
  // CA-5 — attachments land NOW, not at send: a file whose upload is deferred to the
  // next question can fail silently after the question has already gone. `pending` is
  // the in-flight name; `results` are the outcomes, each of which must be rendered.
  const [uploading, setUploading] = useState<string | null>(null);
  const [uploads, setUploads] = useState<AttachmentResult[]>([]);
  const [dragging, setDragging] = useState(false);
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
    // `resumeId`, not `restoreSessionId`: a reload resuming from `?chat=` must not be
    // cleared out from under the restore that is about to run.
    //
    // Dropping the id belongs HERE, to the reset, and nowhere else. Keying it off "the
    // turn list is empty" looked equivalent and is not: a resumed conversation is also
    // empty for as long as its fetch is in flight, so that version deleted the id a beat
    // before the turns arrived — and the id is the only handle the conversation has.
    if (!resumeId) {
      setSessionId(newSessionId()); // a fresh Chat instance — the conversation resets with it
      const params = new URLSearchParams(window.location.search);
      if (params.has("chat")) {
        params.delete("chat");
        const qs = params.toString();
        window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
      }
    }
    setStarters(FALLBACK_STARTERS);
    // No connection yet — ask the backend nothing. `selectedConn` is DERIVED and reads
    // "" for as long as the workspace clamp is fail-closed (and again whenever the
    // active connection is deleted), and this panel is mounted on every tab, so that
    // window used to spend two requests on a connection with no id on every single
    // load. The prewarm is the one that draws blood: an empty path segment makes
    // Vercel's EDGE answer `/connections//prewarm` with a 308 before the request ever
    // reaches the app, an edge redirect carries no Access-Control-Allow-Origin, so the
    // browser blocks it and the UI paints "Failed to fetch" — an error belonging to a
    // request that should never have been made, sitting on top of whatever the user
    // was actually doing. Settle on the fallback starters instead of a spinner: with
    // no connections at all this state is the destination, not a way station. The
    // effect re-runs the moment a real id arrives.
    if (!connectionId) {
      setLoadingStarters(false);
      return;
    }
    setLoadingStarters(true);
    // R5 — composer-open prewarm (the Databricks preload analog): warm the profile
    // cache + entity-value samples before the first question. Fire-and-forget; the
    // backend job is supervised, idempotent, and Curator-governance-gated.
    fetch(`${getApiBase()}/connections/${encodeURIComponent(connectionId)}/prewarm`, { method: "POST" })
      .catch(() => {});
    fetch(`${getApiBase()}/suggestions?connection_id=${encodeURIComponent(connectionId)}`)
      .then(r => r.json())
      .then(data => {
        const suggestions: Starter[] = (data.suggestions ?? []).map((s: { text: string; mode: string }) => ({
          text: s.text,
          mode: (s.mode === "investigate" ? "investigate" : "ask") as "ask" | "investigate",
        }));
        // R13 — named research-starter playbooks: lead the
        // grid, styled as deep chips, carrying their declared route + purpose tag.
        const library: Starter[] = (data.starters ?? []).map((s: { text: string; mode: string; purpose?: string }) => ({
          text: s.text,
          mode: "investigate" as const,
          requestMode: (s.mode === "explore" ? "explore" : "investigate") as "investigate" | "explore",
          purpose: s.purpose,
        }));
        const merged = [...library, ...suggestions].slice(0, 9);
        if (merged.length > 0) setStarters(merged);
      })
      .catch(() => {})
      .finally(() => setLoadingStarters(false));
  }, [connectionId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!resumeId) return;
    let cancelled = false;

    // "Is this chat still generating?" — the reconnect half of P5.2, and the reason this
    // is a retry rather than a fetch. A reload does not find a settled conversation: it
    // CAUSES the turn it interrupted to settle. The client goes away, the backend notices
    // at its next cancellation checkpoint, and only then writes the partial. Ask once and
    // you race that write and lose — the session reads empty a beat before its last turn
    // exists. Measured: the row landed, and the single-shot version had already given up.
    //
    // Bounded and silent. It gives up after ~12s rather than polling forever, and an
    // empty session (a stale or shared link) simply stays empty — the same outcome as
    // before, reached a few seconds later.
    //
    // CA-1: the endpoint returns `UIMessage[]` — the same shape the stream
    // accumulates — so restoring a thread IS `setMessages`. The 40-field manual
    // turn literal this used to build is gone; `projectTurn` derives the turn
    // from the same parts either way.
    const attempt = (tries: number) => {
      fetch(`${getApiBase()}/chat-sessions/${encodeURIComponent(resumeId)}/messages`)
        .then(r => (r.ok ? r.json() : []))
        .then((msgs: AughorUIMessage[]) => {
          if (cancelled) return;
          if (!Array.isArray(msgs) || !msgs.length) {
            if (tries > 0) setTimeout(() => { if (!cancelled) attempt(tries - 1); }, 1500);
            return;
          }
          setMessages(msgs);
        })
        .catch(() => {});
    };
    attempt(8);
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── The actions (the reducer hook's verbs, on the SDK's transport) ──────────

  /** Per-turn options, exactly the reducer path's `ask` opts. */
  interface AskOpts {
    skipCache?: boolean; schema?: string | null; insightId?: string;
    seedSql?: string | null; seedContext?: string; deep?: boolean;
    depth?: "quick" | "deep"; skipClarify?: boolean; clarifyReading?: string;
    clarifySubject?: string; clarifySource?: string;
    requestMode?: "investigate" | "explore"; purpose?: string;
  }

  const sendQuestion = useCallback((question: string, m: "auto" | "ask" | "investigate" = "auto", opts: AskOpts = {}) => {
    // An interrupt — the user sent this while a turn was still streaming. The SDK
    // abort settles the outgoing turn with whatever it produced (the projection
    // reads a non-streaming message as done), and the new send is its own turn.
    if (busy) sdkStop();
    if (status === "error") clearError();
    // The turn's initial mode drives the loading UI until the router's `route`
    // receipt corrects it; a starter's requestMode always routes deep.
    const initialMode: "ask" | "investigate" = m === "investigate" || opts.requestMode ? "investigate" : "ask";
    void sendMessage(
      { text: question, metadata: { mode: initialMode } },
      { body: {
        mode: m,
        depth: opts.depth ?? "auto",
        schema: opts.schema ?? null,
        agent_id: agentId || null,
        skip_clarify: opts.skipClarify ?? false,
        clarify_reading: opts.clarifyReading ?? "",
        clarify_subject: opts.clarifySubject ?? "",
        clarify_source: opts.clarifySource ?? "",
        insight_id: opts.insightId ?? null,
        deep: opts.deep ?? false,
        seed_sql: opts.seedSql ?? null,
        seed_context: opts.seedContext ?? "",
        skip_cache: opts.skipCache ?? false,
        request_mode: opts.requestMode ?? null,
        purpose: opts.purpose ?? "",
      } },
    );
  }, [busy, status, sdkStop, clearError, sendMessage, agentId]);

  const stop = useCallback(() => { sdkStop(); }, [sdkStop]);

  const clear = useCallback(() => {
    sdkStop();
    setTimings(new Map());
    eventLogRef.current = [];
    setSessionId(newSessionId()); // a fresh Chat instance — empty conversation, new session row
  }, [sdkStop]);

  // P3/P4 gate approvals — still side POSTs keyed by investigation id (the route
  // maps `resume` onto the feedback endpoint); the user's decision is a visible
  // turn, and the resumed run streams back as its answer.
  const resumePlan = useCallback((invId: string, keep: number[]) => {
    void sendMessage(
      { text: `Proceed with ${keep.length || "all"} sub-question${keep.length === 1 ? "" : "s"}.`,
        metadata: { mode: "investigate" } },
      { body: { resume: { kind: "plan", investigation_id: invId, keep_subquestions: keep } } },
    );
  }, [sendMessage]);

  const rejectPlan = useCallback((invId: string) => {
    void cancelInvestigation(invId).catch(() => { /* best-effort */ });
  }, []);

  const resumeClarify = useCallback((invId: string, choice: string) => {
    void sendMessage(
      { text: choice, metadata: { mode: "investigate" } },
      { body: { resume: { kind: "clarify", investigation_id: invId, choice } } },
    );
  }, [sendMessage]);

  // ── The conversation's id lives in the URL, so a reload resumes it ──────────
  // Written once the conversation has something worth coming back to, and removed when it
  // does not, so a stale id can never outlive the turns it names — reload after "New
  // conversation" would otherwise reopen exactly what was just dismissed.
  //
  // `replaceState`, never `pushState`: continuing a conversation is not a navigation, and
  // a history entry per turn would make Back walk the conversation instead of leaving the
  // screen. Only the `chat` key is touched, and the rest of the query string is read fresh
  // each time, so this and page.tsx's tab/conn/layer sync can both write without either
  // erasing the other's keys.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!messages.length) return;   // see below: emptiness is not a reason to forget
    const params = new URLSearchParams(window.location.search);
    if (params.get("chat") === sessionId) return;
    params.set("chat", sessionId);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, [messages.length, sessionId]);

  // ── Scroll: follow the newest content while pinned to the bottom, release
  //    the moment the user scrolls up to read, snap back on completion. ───────
  const streamingKey = turns.map(({ turn: t }) => `${t.id}:${t.phases.length}:${t.statusText}`).join("|");
  const { scrollRef, pinned, scrollToBottom } = useStickToBottom(streamingKey, { active: busy });

  useEffect(() => {
    if (wasStreamingRef.current && !busy && turns.length > 0) {
      const lastTurn = turns[turns.length - 1].turn;
      setTimeout(() => {
        const el = turnTopRefs.current.get(lastTurn.id);
        el?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 150);
    }
    wasStreamingRef.current = busy;
  }, [busy]); // eslint-disable-line

  // Auto-submit a question injected from outside (e.g. "Investigate" from the Ontology canvas)
  const initialFiredRef = useRef(false);
  useEffect(() => {
    if (!initialQuestion || initialFiredRef.current || busy) return;
    if (initialMode) setMode(initialMode);
    // Small delay so the component is fully mounted and mode is set.
    // The fired-latch is set INSIDE the timer: StrictMode's dev double-invoke
    // (setup → cleanup → setup) clears the first timer, and latching eagerly
    // would make the second setup bail — auto-submit would never fire in dev.
    const t = setTimeout(() => {
      initialFiredRef.current = true;
      sendQuestion(initialQuestion, initialMode ?? "investigate", { insightId: initialInsightId });
    }, 80);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);

  /** Upload one attachment through the door its kind names, and SHOW the outcome. */
  const takeFile = useCallback(async (file: File) => {
    setAttachedFile(null);
    setUploading(file.name);
    const res = await uploadAttachment(file, connectionId);
    setUploading(null);
    setUploads((prev) => [...prev, res]);
  }, [connectionId]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer?.files ?? []);
    for (const f of files) void takeFile(f);
  }, [takeFile]);

  const handleSend = useCallback(async (q?: string, m?: "auto" | "ask" | "investigate", opts?: { skipCache?: boolean; requestMode?: "investigate" | "explore"; purpose?: string }) => {
    const question = (q ?? input).trim();
    // Only an EMPTY question is refused. Sending while a turn streams is not an error —
    // it is the interrupt: `sendQuestion` aborts the in-flight request before starting,
    // and the backend's core stops at its next cancellation checkpoint rather than
    // running on for a client that has moved on. Refusing here (as this did) made an
    // enabled input worse than a disabled one: it accepted the text and silently
    // dropped it.
    if (!question) return;
    setInput("");
    // A file still sitting in the composer goes through the SAME door a dropped one
    // does — and its outcome is rendered rather than swallowed. The old path caught
    // and discarded upload errors, then asked the question anyway: the answer that
    // came back was about whatever else was in scope, with nothing on screen saying
    // the file never arrived.
    if (attachedFile) await takeFile(attachedFile);
    sendQuestion(question, m ?? mode, opts ?? {});
    textareaRef.current?.focus();
  }, [input, sendQuestion, mode, attachedFile, takeFile]);

  const isEmpty = messages.length === 0;

  // R10 — THUMBS→priors: a helpful verdict teaches the learned table prior
  // (the same counter overview drills + query popularity feed). Fire-and-forget.
  const handleThumbs = useCallback((turnId: string, verdict: "helpful" | "unhelpful") => {
    setThumbsDone(prev => new Map(prev).set(turnId, verdict));
    fetch(`${getApiBase()}/chat/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conn_id: connectionId, turn_id: turnId, verdict }),
    }).catch(() => {});
  }, [connectionId]);

  // ── Feedback submission ───────────────────────────────────────────────────────
  async function handleFeedbackSubmit(invId: string, feedback: string) {
    try {
      await fetch(`${getApiBase()}/investigations/${invId}/feedback`, {
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
    streaming: busy,
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
    <div
      className="flex-1 flex flex-col min-w-0 overflow-hidden"
      style={{ background: "var(--bg-1)", position: "relative" }}
      onDragOver={(e) => { e.preventDefault(); if (!dragging) setDragging(true); }}
      onDragLeave={(e) => {
        // Only the drag leaving the PANEL counts — crossing a child's edge fires
        // dragleave too, and clearing on those makes the overlay strobe.
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={onDrop}
    >
      {/* CA-5 — drop a file straight into the conversation. A data file becomes a
          queryable table on this connection; anything else becomes retrieval context. */}
      {dragging && (
        <div
          style={{
            position: "absolute", inset: 0, zIndex: 20,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: "var(--bg-0)", opacity: .94,
            border: "2px dashed var(--blue3)", borderRadius: "var(--r3)",
            pointerEvents: "none",
          }}
        >
          <div style={{ textAlign: "center" }}>
            <div className="aug-fs-md" style={{ color: "var(--t1)", fontWeight: 600 }}>
              Drop to add to this conversation
            </div>
            <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 4 }}>
              A CSV or spreadsheet becomes a table you can ask about · other files become context
            </div>
          </div>
        </div>
      )}

      {/* What actually happened to each attachment — including the failures the old
          path swallowed. */}
      {(uploading || uploads.length > 0) && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "8px 16px 0" }}>
          {uploading && (
            <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
              Importing {uploading}…
            </span>
          )}
          {uploads.map((u, i) => (
            <span
              key={`${u.filename}-${i}`}
              className="aug-fs-xs"
              style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "2px 8px", borderRadius: "var(--r2)",
                background: u.error ? "var(--red1)" : "var(--bg-2)",
                border: `1px solid ${u.error ? "var(--red3)" : "var(--b1)"}`,
                color: u.error ? "var(--red5)" : "var(--t2)",
                maxWidth: 460,
              }}
              title={u.error || (u.table ? `Imported as ${u.table}` : "Added as context")}
            >
              <span aria-hidden>{u.error ? "⚠" : u.table ? "▦" : "📄"}</span>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {u.error
                  ? `${u.filename} — ${u.error}`
                  : u.table
                    ? `${u.filename} → ${u.table}`
                    : `${u.filename} added as context`}
              </span>
              <Button
                variant="ghost"
                size="icon-xs"
                title="Dismiss"
                aria-label="Dismiss"
                onClick={() => setUploads((prev) => prev.filter((_, j) => j !== i))}
                className="h-auto w-auto p-0 hover:bg-transparent dark:hover:bg-transparent"
                style={{ marginLeft: 2, opacity: .6, lineHeight: 1, color: "inherit" }}
              >
                ×
              </Button>
            </span>
          ))}
        </div>
      )}

      {isEmpty ? (
        /* ── Empty state ── */
        <div className="flex-1 flex flex-col items-center justify-center py-10">
          <div className="w-full max-w-[var(--measure-chat)] px-[var(--chat-gutter)] flex flex-col gap-5">

            {capabilities}

            {!capabilities && (
              <div className="text-center">
                <p className="aug-fs-sm font-bold text-zinc-200">Ask your data anything</p>
                <p className="aug-fs-sm text-zinc-500 mt-1.5">
                  <span className="text-zinc-400 font-bold">Auto</span> picks the right depth for each question —
                  or choose <span className="text-zinc-400 font-bold">Quick</span> /{" "}
                  <span className="text-violet-400/90 font-bold">Deep analysis</span> yourself.
                </p>
              </div>
            )}

            <InputBox {...inputBoxProps} multiline />

            <p className="aug-fs-sm text-center" style={{ color: "var(--t3)" }}>Always review the accuracy of responses.</p>

            {/* Suggestions */}
            <div className="pt-1">
              <p className="text-[11px] uppercase tracking-[0.08em] mb-2" style={{ color: "var(--b3)" }}>Suggested questions</p>
              {loadingStarters ? (
                <div className="grid grid-cols-2 gap-1.5">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="h-14 rounded-[var(--r3)] animate-pulse" style={{ background: "var(--bg-1)" }} />
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-1.5">
                  {[OVERVIEW_STARTER, ...starters.filter(s => s.text !== OVERVIEW_STARTER.text)].map((s) => {
                    const isOverview = s.text === OVERVIEW_STARTER.text;
                    return (
                    <button
                      key={s.text}
                      onClick={() => handleSend(
                        s.text,
                        // A starter with a declared route goes through /ask ("auto") so the
                        // backend's deterministic mode override routes it (R13).
                        isOverview || s.requestMode ? "auto" : s.mode,
                        s.requestMode ? { requestMode: s.requestMode, purpose: s.purpose } : undefined,
                      )}
                      className={`aug-pressable flex items-start gap-1.5 px-3 py-2 rounded-[var(--r3)] text-[12px] text-left leading-snug transition-all${isOverview ? " col-span-2" : ""}`}
                      style={isOverview ? {
                        background: "var(--acc-dim)",
                        border: "0.5px solid var(--blue2)",
                        color: "var(--blue4)",
                      } : s.mode === "investigate" ? {
                        background: "var(--bg-1)",
                        border: "0.5px solid var(--grn1)",
                        color: "var(--grn4)",
                      } : {
                        background: "var(--bg-1)",
                        border: "0.5px solid var(--b2)",
                        color: "var(--t3)",
                      }}
                      onMouseEnter={e => {
                        if (isOverview) {
                          (e.currentTarget as HTMLElement).style.borderColor = "var(--blue3)";
                          (e.currentTarget as HTMLElement).style.color = "var(--blue5)";
                        } else if (s.mode === "investigate") {
                          (e.currentTarget as HTMLElement).style.borderColor = "var(--grn2)";
                          (e.currentTarget as HTMLElement).style.color = "var(--grn4)";
                        } else {
                          (e.currentTarget as HTMLElement).style.borderColor = "var(--b2)";
                          (e.currentTarget as HTMLElement).style.color = "var(--t1)";
                        }
                      }}
                      onMouseLeave={e => {
                        if (isOverview) {
                          (e.currentTarget as HTMLElement).style.borderColor = "var(--blue2)";
                          (e.currentTarget as HTMLElement).style.color = "var(--blue4)";
                        } else if (s.mode === "investigate") {
                          (e.currentTarget as HTMLElement).style.borderColor = "var(--grn1)";
                          (e.currentTarget as HTMLElement).style.color = "var(--grn4)";
                        } else {
                          (e.currentTarget as HTMLElement).style.borderColor = "var(--bg-3)";
                          (e.currentTarget as HTMLElement).style.color = "var(--t3)";
                        }
                      }}
                    >
                      <span className={`shrink-0 mt-0.5 aug-fs-ui${isOverview ? "" : " opacity-70"}`}>
                        {isOverview
                          ? <Icon name="compass" size={16} />
                          : s.mode === "investigate"
                          ? <Icon name="spark" size={16} />
                          : <Icon name="chat" size={16} />}
                      </span>
                      <span className="min-w-0">
                        {isOverview && <span className="font-medium">A great starting point · </span>}
                        {s.text}
                      </span>
                    </button>
                    );
                  })}
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
              <div className="py-8 w-full max-w-[var(--measure-chat)] px-[var(--chat-gutter)] mx-auto">
                {turns.map(({ turn, userMsg, assistantMsg }, i) => (
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
                      onRerun={(depth) => sendQuestion(turn.question, "auto", { depth })}
                    />
                    <AgentBadge turn={turn} />
                    {/* WP-2 — isolate a single answer's render: a throw here (a malformed
                        report, a recovered-report shape mismatch) must not white-screen the
                        conversation or kill the composer. */}
                    <ErrorBoundary label="This answer couldn't be displayed.">
                      <PartsMessage
                        turn={turn}
                        message={assistantMsg}
                        connectionId={connectionId}
                        // Wave 2 / 2.1 — tag the turn so chip adoption is QUERYABLE. A
                        // clicked follow-up was indistinguishable from a typed question,
                        // so "do the suggestions get used" had no answer. `purpose` is
                        // the existing starter-provenance column (investigations.purpose),
                        // so this needs no new store.
                        onFollowUp={(q) => handleSend(q, undefined, { purpose: "followup" })}
                        onRunFresh={(q) => handleSend(q, "investigate", { skipCache: true })}
                        onShowSource={setSourcePanel}
                        onDeeper={(q, insightId) => sendQuestion(q, "investigate", { insightId: insightId ?? undefined, deep: true })}
                        onExploreFact={(q, o) => { recordOverviewDrill(connectionId, { canvasId: canvasId ?? undefined, lens: o.lens, table: o.table }); sendQuestion(q, "investigate", { seedSql: o.seedSql, seedContext: o.seedContext, deep: true }); }}
                        onApprovePlan={(invId, keep) => resumePlan(invId, keep)}
                        onRejectPlan={(invId) => rejectPlan(invId)}
                        onChooseClarify={(invId, opt) => resumeClarify(invId, opt)}
                        // Wave R4 — the blessed recovery. Routed through the SAME handleSend
                        // the composer uses, so a retry is an ordinary new turn: the failed
                        // one keeps its partial and its error tail, and nothing is mutated in
                        // place. That is what makes "never a dropped or duplicated turn" true
                        // by construction rather than by care.
                        onRetry={(q) => handleSend(q)}
                        // CA-1 — edit-and-resend: replaces THIS user message and re-sends;
                        // the SDK truncates the thread from here (branching, the cheap way).
                        onEdit={(q) => void sendMessage(
                          { text: q, messageId: userMsg.id, metadata: { mode: "ask" } },
                          { body: { mode: "auto" } },
                        )}
                      />
                    </ErrorBoundary>
                    {turn.clarify && (
                      <ClarifyCard
                        turn={turn}
                        onClarify={(detail) => sendQuestion(`${turn.question} — ${detail}`, "auto", { skipClarify: true, clarifyReading: detail, clarifySubject: turn.question, clarifySource: turn.clarify?.source })}
                        onAnswerAnyway={() => sendQuestion(turn.question, "auto", { skipClarify: true })}
                      />
                    )}
                    {turn.escalate && (
                      <EscalateBar
                        turn={turn}
                        onEscalate={() => sendQuestion(turn.question, "auto", { depth: "deep", skipClarify: true })}
                      />
                    )}
                    {/* Wave S2 — ONE receipt surface per answer. Two panels used to render
                        here (B-9's inline badge row over the per-mode route, and WP-10's
                        drawer over the unified /receipt/{id}); they overlapped on SQL,
                        metrics and cost and disagreed on everything else. The unified
                        receipt now carries what only the old one showed — resolved
                        readings, the Learning Receipt, activations and "Add as eval case" —
                        so the duplicate could go without losing evidence. */}
                    {turn.status === "done" && turn.receiptId && (
                      <div className="flex items-center gap-1.5">
                        {/* R10 — thumbs: helpful teaches the learned table prior */}
                        {thumbsDone.has(turn.receiptId) ? (
                          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
                            {thumbsDone.get(turn.receiptId) === "helpful" ? "Thanks — noted 👍" : "Noted 👎"}
                          </span>
                        ) : (
                          <>
                            <Button variant="ghost" size="icon-xs" aria-label="Helpful"
                                    onClick={() => handleThumbs(turn.receiptId!, "helpful")}>
                              👍
                            </Button>
                            <Button variant="ghost" size="icon-xs" aria-label="Not helpful"
                                    onClick={() => handleThumbs(turn.receiptId!, "unhelpful")}>
                              👎
                            </Button>
                          </>
                        )}
                      </div>
                    )}
                    {/* WP-10 — "Why this number": opens the unified signed receipt (GET /receipt/{id}). */}
                    {turn.status === "done" && turn.publicReceiptId && (
                      <WhyThisNumber receiptId={turn.publicReceiptId} />
                    )}
                    {/* CA-1 — regenerate: re-run the LAST turn's question as a fresh
                        answer (the SDK re-sends the same user message). Last turn only —
                        regenerating an earlier turn would truncate the thread below it. */}
                    {i === turns.length - 1 && turn.status !== "loading" && assistantMsg && (
                      <div style={{ display: "inline-flex" }}>
                        <Button
                          variant="ghost"
                          size="xs"
                          onClick={() => { if (busy) sdkStop(); void regenerate(); }}
                          title="Ask this again — a fresh answer replaces this one"
                          className="h-auto gap-1 px-1.5 py-0.5 aug-fs-xs font-normal text-zinc-500 hover:text-zinc-300 hover:bg-transparent dark:hover:bg-transparent"
                        >
                          ↺ Regenerate
                        </Button>
                      </div>
                    )}
                    {/* Post-run feedback — shown once per completed deep analysis with hypotheses */}
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
                    fontSize: 12, fontWeight: 500, fontFamily: "var(--font-ui)",
                    color: "var(--t2)", background: "var(--bg-3)", border: "1px solid var(--b2)",
                    boxShadow: "var(--shadow-lg)",
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "var(--t1)"; (e.currentTarget as HTMLElement).style.borderColor = "var(--b3)"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "var(--t2)"; (e.currentTarget as HTMLElement).style.borderColor = "var(--b2)"; }}
                >
                  <Icon name="chevd" size={16} />
                  Jump to latest
                </Button>
              </div>
            )}

            {/* ── Floating input ── */}
            <div style={{
              position: "absolute", bottom: 20, left: 0, right: 0,
              zIndex: 2, pointerEvents: "none",
            }}>
              <div className="w-full max-w-[var(--measure-chat)] px-[var(--chat-gutter)] mx-auto space-y-2" style={{ pointerEvents: "all" }}>
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
