"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { PartsMessage } from "@/components/chat/PartsMessage";
import type { SourcePanelData } from "@/components/ChatMessage";
import { projectThread, newSessionId } from "@/lib/chatTurn";
import { useAughorChat } from "@/lib/useAughorChat";

export interface ThreadRunOpts {
  connectionId: string;
  /** Scope a non-canvas investigation to a specific schema (multi-schema connections). */
  schema?: string | null;
  canvasId?: string | null;
  /** The exact query the seed finding came from — anchors the deep analysis on the real tables/window. */
  seedSql?: string | null;
  /** Free-text seed (e.g. the briefing claim being pulled on). */
  seedContext?: string;
  /** The originating finding's insight id. When it resolves to a dossier, the deep analysis is
   *  seeded with the RICH dossier (grounded values + verified structure) instead of
   *  just seedContext/seedSql — the same seed the chat "Investigate deeper" uses. */
  insightId?: string | null;
  /** Bypass the similar-investigation cache so you observe live execution. */
  skipCache?: boolean;
}

export interface InlineInvestigationThreadProps {
  /** The natural-language question that drives the deep analysis' phase routing. */
  question: string;
  /** connectionId + schema + canvasId + seedSql/seedContext (see ThreadRunOpts). */
  opts: ThreadRunOpts;
  /** Collapse / dismiss the thread. */
  onClose?: () => void;
  /** Escape hatch — re-open the same question in the full Ask surface. */
  onOpenInAsk?: (q: string) => void;
  /** Open the SQL + rows source panel (optional; threaded into PartsMessage). */
  onShowSource?: (data: SourcePanelData) => void;
}

/**
 * Capability A "pull the thread": an investigation that streams IN PLACE inside the
 * briefing. CA-1: one `useAughorChat` conversation per thread instance (its own
 * session, its own abort), fired once on mount with the seeded `/investigate`
 * options riding the send's body; the turn renders through the same
 * `projectThread` → `PartsMessage` path as the chat surfaces. Aborts its stream
 * on unmount.
 */
export function InlineInvestigationThread({
  question,
  opts,
  onClose,
  onOpenInAsk,
  onShowSource,
}: InlineInvestigationThreadProps) {
  const [sessionId] = useState(() => newSessionId());
  const { messages, sendMessage, stop, status, error } = useAughorChat({
    connectionId: opts.connectionId,
    sessionId,
  });
  const streaming = status === "submitted" || status === "streaming";
  const startedRef = useRef(false);

  useEffect(() => {
    if (!startedRef.current) {
      startedRef.current = true;
      // skip_cache so an inline drill always runs LIVE against the seeded query/window
      // rather than replaying a similar cached investigation.
      void sendMessage(
        { text: question, metadata: { mode: "investigate" } },
        { body: {
          mode: "investigate",
          schema: opts.schema ?? null,
          canvas_id: opts.canvasId ?? null,
          seed_sql: opts.seedSql ?? null,
          seed_context: opts.seedContext ?? "",
          insight_id: opts.insightId ?? null,
          // This surface always runs the live investigation in place — never the
          // Tier-0 dossier card — so bypass the short-circuit while still feeding
          // the dossier (when present) as the seed.
          deep: true,
          skip_cache: opts.skipCache ?? true,
        } },
      );
    }
    return () => { stop(); };  // abort the SSE stream when the thread is collapsed/unmounted
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const turns = useMemo(() => projectThread(messages, {
    streaming,
    transportError: status === "error" ? (error?.message ?? "The investigation failed.") : null,
  }), [messages, streaming, status, error]);
  const last = turns[turns.length - 1];

  return (
    <div
      style={{
        marginTop: 10,
        border: "1px solid var(--b1)",
        borderRadius: "var(--r3)",
        background: "var(--bg-1)",
        padding: "12px 14px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <span
          className="aug-label"
          style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--t3)", letterSpacing: ".04em" }}
        >
          <span
            style={{
              width: 6, height: 6, borderRadius: "50%",
              background: streaming ? "var(--blue4, #6aa3ff)" : "var(--t4)",
              boxShadow: streaming ? "0 0 0 3px color-mix(in srgb, var(--blue4, #6aa3ff) 22%, transparent)" : "none",
            }}
          />
          {streaming ? "Pulling the thread…" : "Investigation"}
        </span>
        <span style={{ display: "inline-flex", gap: 10 }}>
          {streaming && (
            <button className="aug-label" onClick={() => stop()} style={_linkBtn} title="Stop this investigation">
              Stop
            </button>
          )}
          {onOpenInAsk && (
            <button className="aug-label" onClick={() => onOpenInAsk(question)} style={_linkBtn} title="Open in the Ask workspace">
              Open in Ask ↗
            </button>
          )}
          {onClose && (
            <button className="aug-label" onClick={onClose} style={_linkBtn} title="Collapse">
              Close
            </button>
          )}
        </span>
      </div>

      {last ? (
        <PartsMessage
          turn={last.turn}
          message={last.assistantMsg}
          onFollowUp={onOpenInAsk}
          onRunFresh={onOpenInAsk}
          onShowSource={onShowSource}
        />
      ) : (
        <span className="aug-text-ui" style={{ color: "var(--t3)" }}>Starting investigation…</span>
      )}
    </div>
  );
}

const _linkBtn: React.CSSProperties = {
  background: "none",
  border: "none",
  cursor: "pointer",
  color: "var(--t3)",
  padding: 0,
};
