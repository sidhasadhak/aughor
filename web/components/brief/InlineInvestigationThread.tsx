"use client";

import { useEffect, useRef } from "react";
import { useInvestigationThread, type ThreadRunOpts } from "@/lib/useInvestigationThread";
import { ChatMessage, type SourcePanelData } from "@/components/ChatMessage";

export interface InlineInvestigationThreadProps {
  /** The natural-language question that drives ADA's phase routing. */
  question: string;
  /** connectionId + schema + canvasId + seedSql/seedContext (see ThreadRunOpts). */
  opts: ThreadRunOpts;
  /** Collapse / dismiss the thread. */
  onClose?: () => void;
  /** Escape hatch — re-open the same question in the full Ask surface. */
  onOpenInAsk?: (q: string) => void;
  /** Open the SQL + rows source panel (optional; threaded into ChatMessage). */
  onShowSource?: (data: SourcePanelData) => void;
}

/**
 * Capability A "pull the thread": an investigation that streams IN PLACE inside the
 * briefing. It owns one useInvestigationThread (one SSE stream, one AbortController),
 * seeded with the originating finding + its SQL, and renders the live phases + ADA
 * report by reusing the chat surface's <ChatMessage>. Aborts its stream on unmount.
 */
export function InlineInvestigationThread({
  question,
  opts,
  onClose,
  onOpenInAsk,
  onShowSource,
}: InlineInvestigationThreadProps) {
  const { turn, streaming, run, stop } = useInvestigationThread();
  const startedRef = useRef(false);

  useEffect(() => {
    if (!startedRef.current) {
      startedRef.current = true;
      // skip_cache so an inline drill always runs LIVE against the seeded query/window
      // rather than replaying a similar cached investigation.
      run(question, { ...opts, skipCache: opts.skipCache ?? true });
    }
    return () => { stop(); };  // abort the SSE stream when the thread is collapsed/unmounted
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
            <button className="aug-label" onClick={stop} style={_linkBtn} title="Stop this investigation">
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

      {turn ? (
        <ChatMessage turn={turn} onFollowUp={onOpenInAsk} onRunFresh={onOpenInAsk} onShowSource={onShowSource} />
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
