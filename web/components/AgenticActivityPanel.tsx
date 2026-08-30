"use client";

/**
 * Agent Ops · Activity — one layer over one substrate (`session_events`), three zoom
 * levels: **Usage** (what the fleet spent, by model / call site / role), the live
 * **Stream**, and one **Run** reconstructed as a trace. Folded together because they are
 * the same rows at three magnifications, and every drill between them is a zoom rather
 * than a navigation — clicking a model in Usage lands in the Stream already filtered to it.
 *
 * Usage leads, because "what did this cost and where did it go" is the question somebody
 * opens this layer with; the raw event tail is where you end up, not where you start.
 * Machine chatter as the primary feed is a named anti-pattern for exactly this surface.
 *
 * All three stay mounted once visited (display-toggled), so the stream's SSE tail and a
 * selected trace survive mode switches — the same keep-alive rule the Workspace shell
 * applies to layers.
 */
import { useEffect, useState } from "react";

import { UsagePanel } from "@/components/agentops/UsagePanel";
import { type TimeRange } from "@/components/agentops/useTimeRange";
import { Button } from "@/components/ui/button";
import { ActivityStreamPanel } from "@/components/ActivityStreamPanel";
import { TraceExplorerPanel } from "@/components/TraceExplorerPanel";
import { RunGraphsPanel } from "@/components/RunGraphsPanel";

type Mode = "usage" | "stream" | "runs" | "phases";

const MODE_BLURB: Record<Mode, string> = {
  usage: "what the fleet spent, and on what",
  stream: "every event as it happens",
  // "Traces", not "Runs". Agent Ops already has a top-level Runs layer, so this
  // sub-tab was the second control labelled "Runs" in one header. It is also the
  // more precise word for what this shows: the top layer lists runs, and this
  // reconstructs one from the telemetry `session_events` kept about it.
  runs: "one run, reconstructed from its trace",
  // B1 — moved here when the top-level Runs layer retired: the phase view's natural
  // neighbours are the traces its deep-analysis runs open in.
  phases: "deep analysis, phase by phase",
};

export function AgenticActivityPanel({ focusInvestigationId, focusTraceId, onTraceOpened,
  range, onBrush }: {
  /** The H3 drill-in: show traces for one investigation (runs mode). */
  focusInvestigationId?: string | null;
  /** A trace opened from another layer — forces runs mode with it selected. */
  focusTraceId?: string | null;
  onTraceOpened?: () => void;
  range: TimeRange;
  onBrush?: (since: string, until: string) => void;
}) {
  const [mode, setMode] = useState<Mode>("usage");
  const [visited, setVisited] = useState<Set<Mode>>(() => new Set<Mode>(["usage"]));
  const [innerTrace, setInnerTrace] = useState<string | null>(null);
  // A drill from Usage: the Stream opens already filtered to the row that was clicked.
  const [streamFilter, setStreamFilter] =
    useState<{ model?: string; provider?: string; role?: string } | null>(null);

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
      <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "8px 14px 0" }}>
        <Button variant={mode === "usage" ? "secondary" : "ghost"} size="xs"
          onClick={() => show("usage")}>Usage</Button>
        <Button variant={mode === "stream" ? "secondary" : "ghost"} size="xs"
          onClick={() => show("stream")}>Stream</Button>
        <Button variant={mode === "runs" ? "secondary" : "ghost"} size="xs"
          onClick={() => show("runs")}>Traces</Button>
        <Button variant={mode === "phases" ? "secondary" : "ghost"} size="xs"
          onClick={() => show("phases")}>Phases</Button>
        <span className="aug-fs-sm" style={{ color: "var(--t2)", marginLeft: 8 }}>
          {MODE_BLURB[mode]}
        </span>
        {mode === "stream" && streamFilter && (
          <Button variant="ghost" size="xs" onClick={() => setStreamFilter(null)}
            style={{ marginLeft: "auto", color: "var(--blue4)" }}>
            filtered to {streamFilter.model || streamFilter.role} — clear
          </Button>
        )}
      </div>
      <div style={{ flex: 1, position: "relative", overflow: "hidden", minHeight: 0 }}>
        {visited.has("usage") && (
          <div style={{ position: "absolute", inset: 0, display: mode === "usage" ? "flex" : "none",
            flexDirection: "column", overflow: "hidden" }}
            inert={mode !== "usage"} aria-hidden={mode !== "usage" || undefined}>
            <UsagePanel range={range} onBrush={onBrush ?? (() => {})}
              onOpenEvents={filter => { setStreamFilter(filter); show("stream"); }} />
          </div>
        )}
        {visited.has("stream") && (
          <div style={{ position: "absolute", inset: 0, display: mode === "stream" ? "flex" : "none",
            flexDirection: "column", overflow: "hidden" }}
            inert={mode !== "stream"} aria-hidden={mode !== "stream" || undefined}>
            <ActivityStreamPanel onOpenTrace={openTrace} filter={streamFilter} range={range} />
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
        {visited.has("phases") && (
          <div style={{ position: "absolute", inset: 0, display: mode === "phases" ? "flex" : "none",
            flexDirection: "column", overflow: "auto" }}
            inert={mode !== "phases"} aria-hidden={mode !== "phases" || undefined}>
            {/* A phase row's deep-analysis run opens as its TRACE one tab over — the
                two views describe the same run and hand off rather than compete. The id
                spaces coincide by construction: a deep run MINTS its trace from its own
                id (obs.py), so no mapping call is needed or wanted. */}
            <RunGraphsPanel onOpenInvestigation={openTrace} />
          </div>
        )}
      </div>
    </div>
  );
}
