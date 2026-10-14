"use client";

/**
 * CR2 — the activity stream: a live tail over `session_events`.
 *
 * The filter chips are built from the `kinds` histogram the API folds FROM THE
 * DATA — the panel can never advertise an event kind nothing emits. A quiet
 * period with recording on renders as quiet ("recording — no events yet"),
 * which is a different claim from the flag-off empty state that names the
 * flag. Live via EventSource on /activity/stream with a slow poll fallback.
 *
 * Routine guardrail checks — a PII check that let the call through — are hidden until asked for. The platform runs
 * one on every model call and on the automation engine's per-minute check, so on a quiet install they are most of the
 * tail (1,652 of the newest 2,000 events on theLook, 2026-10-13) and bury the calls they guard. A check that BLOCKED is
 * never hidden; the hidden ones are counted where the filters are, one click from showing.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { rangeParams, type TimeRange } from "@/components/agentops/useTimeRange";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/brief/StatusChip";
import { getActivityEvents, type SessionEvent } from "@/lib/api";
import { ReadFailed } from "@/components/ui/states";
import { getApiBase, onApiBaseChange } from "@/lib/config";
import { fmtMs } from "@/lib/cost";
import { compactNumber, formatCount, relTime } from "@/lib/format";

const KIND_HUE: Record<string, "positive" | "negative" | "caution" | "info" | "accent" | "muted"> = {
  user_request: "info",
  final_response: "positive",
  llm_call: "accent",
  tool_call: "muted",
  tool_call_result: "muted",
  execution_error: "negative",
};

const MAX_ROWS = 300;

/** A guardrail check that let its call through — the same line the governance feed draws between an allow and a block
 *  (`aughor/govern/audit_categories.py`): blocked when its payload says so or the event failed. */
export function isRoutineCheck(e: Pick<SessionEvent, "kind" | "ok" | "payload">): boolean {
  if (e.kind !== "guardrail") return false;
  const blocked = Boolean((e.payload as { blocked?: unknown } | null | undefined)?.blocked);
  return !blocked && e.ok !== false;
}

/** "PII checks" when every hidden check is the PII guardrail, the general word otherwise. */
function checksWord(hidden: SessionEvent[]): string {
  return hidden.length > 0 && hidden.every(e => e.name === "pii") ? "PII checks" : "guardrail checks";
}

export function ActivityStreamPanel({ onOpenTrace, filter, range }: {
  onOpenTrace?: (traceId: string) => void;
  /** A drill from the Usage page — the tail opens already narrowed to that row. */
  filter?: { model?: string; provider?: string; role?: string } | null;
  /** The surface's shared window. Absent → the unbounded live tail, as before. */
  range?: TimeRange;
}) {
  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [kinds, setKinds] = useState<Record<string, number>>({});
  const [kindFilter, setKindFilter] = useState<string | null>(null);
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [showRoutine, setShowRoutine] = useState(false);
  // Asking for the guardrail kind by name is asking to see its checks.
  const hiding = !showRoutine && kindFilter !== "guardrail";
  const [recording, setRecording] = useState(true);
  // A failed read is said, never drawn as the quiet "recording is on" line (2026-10-13).
  const [readError, setReadError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const lastSeq = useRef(0);
  const esRef = useRef<EventSource | null>(null);

  // Re-open the tail when the user points the app at a different backend. Held in state
  // so it is a dependency of the streaming effect below: React then tears the old
  // EventSource down and opens a new one, which is the only thing that actually moves a
  // live stream — an open connection keeps talking to the host it was opened against.
  // The cursor resets with it: `since_seq` indexes the OLD host's journal, and the new
  // host's numbering is unrelated, so carrying it over would skip or replay rows.
  const [apiBase, setApiBaseState] = useState(getApiBase);
  useEffect(() => onApiBaseChange(next => {
    lastSeq.current = 0;
    setApiBaseState(next);
  }), []);

  // The drill and the window, as query params. Memoised on their VALUES rather than the
  // object identity — a fresh `{}` every render would restart the EventSource on every
  // render, which is how a live tail turns into a reconnect loop.
  const drill = useMemo(() => ({
    model: filter?.model, provider: filter?.provider, role: filter?.role,
    ...(range ? rangeParams(range) : {}),
  }), [filter?.model, filter?.provider, filter?.role, range]);

  const load = useCallback(() => {
    // The route cannot leave a kind out, so while routine checks are hidden the backfill reads deeper — enough that
    // the hours the checks crowd out still reach the screen.
    getActivityEvents({ kind: kindFilter ?? undefined, errors_only: errorsOnly,
                        limit: hiding ? MAX_ROWS : 100, ...drill })
      .then(d => {
        setKinds(d.kinds);
        setRecording(d.measured);
        setEvents(d.events);
        lastSeq.current = d.events.reduce((m, e) => Math.max(m, e.seq), lastSeq.current);
        setReadError(null);
      })
      .catch(e => setReadError(e instanceof Error && e.message ? e.message : "the read failed"));
  }, [kindFilter, errorsOnly, drill, hiding]);

  // Live tail — one EventSource per filter combination; poll as fallback.
  useEffect(() => {
    load();
    const qs = new URLSearchParams();
    if (kindFilter) qs.set("kind", kindFilter);
    if (errorsOnly) qs.set("errors_only", "true");
    // The SSE route filters on kind/agent/conn only. A drill narrows the BACKFILL above;
    // live rows still arrive unfiltered and are screened client-side, which is honest
    // about what the stream can do rather than pretending the tail is narrowed.
    qs.set("since_seq", String(lastSeq.current));
    const es = new EventSource(`${getApiBase()}/activity/stream?${qs.toString()}`);
    esRef.current = es;
    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    es.onmessage = msg => {
      try {
        const ev = JSON.parse(msg.data);
        if (ev.kind === "stream.open") { setRecording(Boolean(ev.recording)); return; }
        lastSeq.current = Math.max(lastSeq.current, ev.seq || 0);
        if (drill.model && ev.model !== drill.model) return;
        if (drill.role && ev.role !== drill.role) return;
        // An EventSource auto-reconnect replays from its ORIGINAL since_seq —
        // dedupe by seq so a replayed row cannot appear twice.
        setEvents(prev => (prev.some(p => p.seq === ev.seq)
          ? prev : [ev, ...prev].slice(0, MAX_ROWS)));
      } catch { /* a malformed frame is dropped, not fatal */ }
    };
    const iv = setInterval(() => { if (!esRef.current || esRef.current.readyState === 2) load(); }, 15_000);
    return () => { es.close(); esRef.current = null; clearInterval(iv); };
  }, [load, kindFilter, errorsOnly, apiBase, drill]);

  const hidden = hiding ? events.filter(isRoutineCheck) : [];
  const shown = hidden.length ? events.filter(e => !isRoutineCheck(e)) : events;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* ── filter bar: kinds come from the data ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "12px 20px",
        borderBottom: "1px solid var(--b1)", flexWrap: "wrap" }}>
        <Button variant={kindFilter === null ? "secondary" : "ghost"} size="xs"
          onClick={() => setKindFilter(null)}>all</Button>
        {Object.entries(kinds).map(([k, n]) => (
          <Button key={k} variant={kindFilter === k ? "secondary" : "ghost"} size="xs"
            onClick={() => setKindFilter(kindFilter === k ? null : k)}>
            {k} · {compactNumber(n)}
          </Button>
        ))}
        <span style={{ flex: 1 }} />
        {hidden.length > 0 ? (
          <Button variant="ghost" size="xs" data-testid="stream-routine" onClick={() => setShowRoutine(true)}
            title="Guardrail checks that let their call through. A check that blocked always shows.">
            {formatCount(hidden.length)} routine {checksWord(hidden)} hidden · show
          </Button>
        ) : showRoutine && (
          <Button variant="secondary" size="xs" data-testid="stream-routine" onClick={() => setShowRoutine(false)}>
            routine checks shown · hide
          </Button>
        )}
        <Button variant={errorsOnly ? "secondary" : "ghost"} size="xs"
          onClick={() => setErrorsOnly(v => !v)}>errors only</Button>
        <StatusChip hue={live ? "positive" : "muted"} strength="soft"
          title={live ? "SSE tail connected" : "stream down — polling every 15s"}>
          {live ? "live" : "polling"}
        </StatusChip>
      </div>

      {/* ── the stream ── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 20px" }}>
        {readError && <ReadFailed what="the live events" error={readError} onRetry={load} style={{ padding: "8px 0" }} />}
        {readError && shown.length === 0 ? null : shown.length === 0 ? (
          <div className="aug-fs-sm" style={{ padding: 32, textAlign: "center", color: "var(--t2)" }}>
            {hidden.length > 0
              ? `Only routine ${checksWord(hidden)} among the newest ${formatCount(events.length)} events.`
              : filter?.model || filter?.role
              ? `No events for ${filter.model ?? filter.role} in this window.`
              : recording
                ? "Quiet — recording is on; events will appear the moment an agent does anything."
                : "No matching events."}
          </div>
        ) : (
          shown.map(e => (
            <div key={e.seq} style={{ display: "flex", alignItems: "center", gap: 10,
              padding: "5px 0", borderBottom: "1px solid var(--b0)", fontSize: 12 }}>
              <span style={{ color: "var(--t2)", fontSize: 12, width: 34, flexShrink: 0 }}
                title={e.at}>{relTime(e.at)}</span>
              <span style={{ width: 118, flexShrink: 0 }}>
                <StatusChip hue={KIND_HUE[e.kind] ?? "muted"} strength="soft">{e.kind}</StatusChip>
              </span>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap" }}>
                {e.name || (e.payload as { question?: string })?.question || "—"}
                {e.model && <span style={{ color: "var(--t2)" }}> · {e.model}</span>}
                {e.error_class && <span style={{ color: "var(--red4)" }}> · {e.error_class}</span>}
              </span>
              {e.ok === false && <StatusChip hue="negative" strength="soft">failed</StatusChip>}
              {e.total_tokens != null && (
                <span style={{ color: "var(--t3)", fontVariantNumeric: "tabular-nums", fontSize: 12 }}>
                  {compactNumber(e.total_tokens)} tok
                </span>
              )}
              {e.duration_ms != null && (
                <span style={{ color: "var(--t3)", fontVariantNumeric: "tabular-nums", fontSize: 12 }}>
                  {fmtMs(e.duration_ms)}
                </span>
              )}
              {/* Migration 10's attribution, shown where it is useful: which agent ran this
                  call, what it was for, and whether the primary backend refused. */}
              {e.charter_id && (
                <span className="aug-fs-xs" style={{ color: "var(--cyn4)" }}
                  title="the built-in agent that owned this run">{e.charter_id}</span>
              )}
              {e.role && (
                <span className="aug-fs-xs" style={{ color: "var(--t2)" }}
                  title="what the call was for">{e.role}</span>
              )}
              {e.fallback === true && (
                <StatusChip hue="caution" strength="soft"
                  title="the primary backend refused and another provider answered">
                  fell back
                </StatusChip>
              )}
              {e.agent_id && <span className="aug-fs-xs" style={{ color: "var(--vio4)" }}>{e.agent_id}</span>}
              {onOpenTrace && (
                <Button variant="ghost" size="xs" onClick={() => onOpenTrace(e.trace_id)}>trace</Button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
