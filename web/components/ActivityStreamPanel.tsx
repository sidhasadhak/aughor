"use client";

/**
 * CR2 — the activity stream: a live tail over `session_events`.
 *
 * The filter chips are built from the `kinds` histogram the API folds FROM THE
 * DATA — the panel can never advertise an event kind nothing emits. A quiet
 * period with recording on renders as quiet ("recording — no events yet"),
 * which is a different claim from the flag-off empty state that names the
 * flag. Live via EventSource on /activity/stream with a slow poll fallback.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/brief/StatusChip";
import { getActivity, type SessionEvent } from "@/lib/api";
import { getApiBase, onApiBaseChange } from "@/lib/config";
import { fmtMs } from "@/lib/cost";
import { compactNumber, relTime } from "@/lib/format";

const KIND_HUE: Record<string, "positive" | "negative" | "caution" | "info" | "accent" | "muted"> = {
  user_request: "info",
  final_response: "positive",
  llm_call: "accent",
  tool_call: "muted",
  tool_call_result: "muted",
  execution_error: "negative",
};

const MAX_ROWS = 300;

export function ActivityStreamPanel({ onOpenTrace }: { onOpenTrace?: (traceId: string) => void }) {
  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [kinds, setKinds] = useState<Record<string, number>>({});
  const [kindFilter, setKindFilter] = useState<string | null>(null);
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [recording, setRecording] = useState(true);
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

  const load = useCallback(() => {
    getActivity({ kind: kindFilter ?? undefined, errors_only: errorsOnly, limit: 100 })
      .then(d => {
        setKinds(d.kinds);
        setRecording(d.recording);
        setEvents(d.events);
        lastSeq.current = d.events.reduce((m, e) => Math.max(m, e.seq), lastSeq.current);
      })
      .catch(() => {});
  }, [kindFilter, errorsOnly]);

  // Live tail — one EventSource per filter combination; poll as fallback.
  useEffect(() => {
    load();
    const qs = new URLSearchParams();
    if (kindFilter) qs.set("kind", kindFilter);
    if (errorsOnly) qs.set("errors_only", "true");
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
        // An EventSource auto-reconnect replays from its ORIGINAL since_seq —
        // dedupe by seq so a replayed row cannot appear twice.
        setEvents(prev => (prev.some(p => p.seq === ev.seq)
          ? prev : [ev, ...prev].slice(0, MAX_ROWS)));
      } catch { /* a malformed frame is dropped, not fatal */ }
    };
    const iv = setInterval(() => { if (!esRef.current || esRef.current.readyState === 2) load(); }, 15_000);
    return () => { es.close(); esRef.current = null; clearInterval(iv); };
  }, [load, kindFilter, errorsOnly, apiBase]);

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
        <Button variant={errorsOnly ? "secondary" : "ghost"} size="xs"
          onClick={() => setErrorsOnly(v => !v)}>errors only</Button>
        <StatusChip hue={live ? "positive" : "muted"} strength="soft"
          title={live ? "SSE tail connected" : "stream down — polling every 15s"}>
          {live ? "live" : "polling"}
        </StatusChip>
      </div>

      {/* ── the stream ── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 20px" }}>
        {events.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center", fontSize: 12, color: "var(--t3)" }}>
            {recording
              ? "Quiet — recording is on; events will appear the moment an agent does anything."
              : "No matching events."}
          </div>
        ) : (
          events.map(e => (
            <div key={e.seq} style={{ display: "flex", alignItems: "center", gap: 10,
              padding: "5px 0", borderBottom: "1px solid var(--b0)", fontSize: 12 }}>
              <span style={{ color: "var(--t4)", fontSize: 11, width: 34, flexShrink: 0 }}
                title={e.at}>{relTime(e.at)}</span>
              <span style={{ width: 118, flexShrink: 0 }}>
                <StatusChip hue={KIND_HUE[e.kind] ?? "muted"} strength="soft">{e.kind}</StatusChip>
              </span>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap" }}>
                {e.name || (e.payload as { question?: string })?.question || "—"}
                {e.model && <span style={{ color: "var(--t4)" }}> · {e.model}</span>}
                {e.error_class && <span style={{ color: "var(--red4)" }}> · {e.error_class}</span>}
              </span>
              {e.ok === false && <StatusChip hue="negative" strength="soft">failed</StatusChip>}
              {e.total_tokens != null && (
                <span style={{ color: "var(--t3)", fontVariantNumeric: "tabular-nums", fontSize: 11 }}>
                  {compactNumber(e.total_tokens)} tok
                </span>
              )}
              {e.duration_ms != null && (
                <span style={{ color: "var(--t3)", fontVariantNumeric: "tabular-nums", fontSize: 11 }}>
                  {fmtMs(e.duration_ms)}
                </span>
              )}
              {e.agent_id && <span style={{ color: "var(--vio4)", fontSize: 11 }}>{e.agent_id}</span>}
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
