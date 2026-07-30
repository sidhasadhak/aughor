"use client";

/**
 * Agentic Ops · Activity — one layer over one substrate (`session_events`),
 * two modes: the live STREAM and the reconstructed RUNS (trace waterfall +
 * feedback). Folded together because they are the same data at two zoom
 * levels, and every "trace" click in the stream is a zoom, not a navigation.
 *
 * Both modes stay mounted once visited (display-toggled), so the stream's SSE
 * tail and a selected trace survive mode switches — the same keep-alive rule
 * the Workspace shell applies to layers.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ActivityStreamPanel } from "@/components/ActivityStreamPanel";
import { TraceExplorerPanel } from "@/components/TraceExplorerPanel";

type Mode = "stream" | "runs";

export function AgenticActivityPanel({ focusInvestigationId, focusTraceId, onTraceOpened }: {
  /** The H3 drill-in: show traces for one investigation (runs mode). */
  focusInvestigationId?: string | null;
  /** A trace opened from another layer — forces runs mode with it selected. */
  focusTraceId?: string | null;
  onTraceOpened?: () => void;
}) {
  const [mode, setMode] = useState<Mode>("stream");
  const [visited, setVisited] = useState<Set<Mode>>(() => new Set<Mode>(["stream"]));
  const [innerTrace, setInnerTrace] = useState<string | null>(null);

  const show = (m: Mode) => {
    setVisited(v => (v.has(m) ? v : new Set(v).add(m)));
    setMode(m);
  };

  // External focus (fleet/agents/attention → a trace) switches to runs mode.
  const effectiveTrace = focusTraceId ?? innerTrace;
  useEffect(() => {
    if (focusTraceId || focusInvestigationId) {
      setVisited(v => (v.has("runs") ? v : new Set(v).add("runs")));
      setMode("runs");
      onTraceOpened?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusTraceId, focusInvestigationId]);

  const openTrace = (traceId: string) => {
    setInnerTrace(traceId);
    show("runs");
  };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "8px 20px 0" }}>
        <Button variant={mode === "stream" ? "secondary" : "ghost"} size="xs"
          onClick={() => show("stream")}>Stream</Button>
        <Button variant={mode === "runs" ? "secondary" : "ghost"} size="xs"
          onClick={() => show("runs")}>Runs</Button>
        <span style={{ fontSize: 11, color: "var(--t4)", marginLeft: 8 }}>
          {mode === "stream" ? "every event as it happens" : "one run, reconstructed"}
        </span>
      </div>
      <div style={{ flex: 1, position: "relative", overflow: "hidden", minHeight: 0 }}>
        {visited.has("stream") && (
          <div style={{ position: "absolute", inset: 0, display: mode === "stream" ? "flex" : "none",
            flexDirection: "column", overflow: "hidden" }}
            inert={mode !== "stream"} aria-hidden={mode !== "stream" || undefined}>
            <ActivityStreamPanel onOpenTrace={openTrace} />
          </div>
        )}
        {visited.has("runs") && (
          <div style={{ position: "absolute", inset: 0, display: mode === "runs" ? "flex" : "none",
            flexDirection: "column", overflow: "hidden" }}
            inert={mode !== "runs"} aria-hidden={mode !== "runs" || undefined}>
            <TraceExplorerPanel focusInvestigationId={focusInvestigationId}
              focusTraceId={effectiveTrace} />
          </div>
        )}
      </div>
    </div>
  );
}
