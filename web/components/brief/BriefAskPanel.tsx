"use client";

/**
 * BriefAskPanel — "Ask this briefing" as a real side panel.
 *
 * What it replaces: `BriefAskBox`, which was neither a conversation nor an insight-mode ask.
 * Every question spawned an INDEPENDENT card with no shared history, and each one ran a full
 * ADA deep investigation (`POST /investigate`, `deep: true`) — so a two-word follow-up cost a
 * multi-minute research job and still couldn't see the previous answer.
 *
 * What this is instead:
 *   - ONE conversation. Turns accumulate; the last three completed turns ride along as history,
 *     so "break that down by platform" resolves against the answer above it.
 *   - INSIGHTS MODE ONLY, pinned deterministically with `depth: "quick"` — which the router
 *     honours with no model call and which also skips every `auto`-gated pre-router branch
 *     (overview tour, clarify gate, federation, plan-as-program). Deep analysis is deliberately
 *     deferred; a question that wants it should go to the full Ask surface via "Open in Ask".
 *   - SCOPED to the briefing's connection AND schema, so it queries the same data the brief is
 *     about (the quick path used to drop `schema` entirely).
 *   - GROUNDED in the brief on screen — assembled server-side from the same cache entry the
 *     Briefing rendered, behind the `ask.brief_context` flag. Nothing about the brief is sent
 *     from here, so the panel can't drift from what the user is reading.
 *
 * Layout follows ChatPanel's split: a fixed-width flex sibling that PUSHES the brief left
 * rather than overlaying it — a reader comparing an answer against the brief needs both.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ChatMessage } from "@/components/ChatMessage";
import { useChat } from "@/lib/useChat";

export const BRIEF_ASK_PANEL_WIDTH = 420;

export function BriefAskPanel({
  connectionId, schema, canvasId, onClose, onOpenInAsk,
}: {
  connectionId: string;
  /** The briefing's schema — pins the answer to the same data the brief is about. */
  schema?: string;
  canvasId?: string;
  onClose: () => void;
  /** Escalate to the full Ask surface (where deep analysis lives). */
  onOpenInAsk: (q: string) => void;
}) {
  const chat = useChat();
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const send = useCallback(() => {
    const q = draft.trim();
    if (!q || chat.state.streaming) return;
    setDraft("");
    // depth:"quick" is the whole contract. `mode` stays "auto" so the unified /ask door is
    // used (and still emits its route receipt); the explicit depth wins inside the router.
    void chat.ask(q, connectionId, "auto", {
      depth: "quick",
      schema: schema ?? null,
      canvasId: canvasId ?? undefined,
    });
  }, [draft, chat, connectionId, schema, canvasId]);

  // Follow the stream. Only auto-scrolls when the reader is already near the bottom, so
  // scrolling up to re-read an earlier answer isn't yanked away mid-stream.
  const turnCount = chat.state.turns.length;
  const streaming = chat.state.streaming;
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 240) {
      el.scrollTop = el.scrollHeight;
    }
  }, [turnCount, streaming]);

  return (
    <aside
      aria-label="Ask this briefing"
      style={{
        width: BRIEF_ASK_PANEL_WIDTH, flex: "0 0 auto", display: "flex", flexDirection: "column",
        minHeight: 0, borderLeft: "1px solid var(--b1)", background: "var(--bg-1)",
      }}
    >
      <div style={{
        display: "flex", alignItems: "center", gap: 8, padding: "12px 14px",
        borderBottom: "1px solid var(--b1)", flex: "0 0 auto",
      }}>
        <span className="aug-label">Ask this briefing</span>
        <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>quick answers</span>
        <Button variant="ghost" size="xs" onClick={onClose} title="Close" aria-label="Close"
          style={{ marginLeft: "auto", color: "var(--t3)", fontSize: 15, lineHeight: 1, height: "auto", padding: 2, cursor: "pointer" }}>
          ×
        </Button>
      </div>

      <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "12px 14px" }}>
        {chat.state.turns.length === 0 ? (
          <div className="aug-fs-xs" style={{ color: "var(--t4)", lineHeight: 1.6 }}>
            Ask a follow-up about this briefing — it already knows the verdict, the findings
            behind it, and which schema they came from.
            <div style={{ marginTop: 10, color: "var(--t4)" }}>
              For a full investigation, use <strong style={{ color: "var(--t3)" }}>Open in Ask</strong> on an answer.
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {chat.state.turns.map(turn => (
              <ChatMessage
                key={turn.id}
                turn={turn}
                connectionId={connectionId}
                onFollowUp={(q: string) => {
                  void chat.ask(q, connectionId, "auto", {
                    depth: "quick", schema: schema ?? null, canvasId: canvasId ?? undefined,
                  });
                }}
                // "Investigate deeper" hands the question to the full Ask surface rather than
                // running deep here — this panel is deliberately insights-only for now.
                onDeeper={(q: string) => onOpenInAsk(q)}
              />
            ))}
          </div>
        )}
      </div>

      <div style={{ flex: "0 0 auto", padding: "10px 14px", borderTop: "1px solid var(--b1)", display: "flex", gap: 8 }}>
        <input
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="Ask a follow-up…"
          className="aug-input"
          style={{ flex: 1, padding: "8px 11px" }}
          disabled={chat.state.streaming}
        />
        <Button variant="default" onClick={send} disabled={!draft.trim() || chat.state.streaming}
          style={{ padding: "8px 14px", height: "auto" }}>
          {chat.state.streaming ? "…" : "Ask →"}
        </Button>
      </div>
    </aside>
  );
}
