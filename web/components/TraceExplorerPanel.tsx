"use client";

/**
 * CR1 — the trace waterfall: pick a run, see everything it did.
 *
 * The tree renders what the data supports and nothing more: tool spans (which
 * carry span ids) nest and pair their entry/exit rows; LLM calls, the request
 * and the final response carry NO span id and render as trace-level events in
 * sequence order — no invented nesting. A tool_call with no matching result
 * row is rendered as exactly that ("no result recorded") because entry-side
 * evidence of a hang or cancel is the point of the log.
 *
 * The feedback tab closes the existing loop — `POST /verify/verdict` keyed by
 * the trace's investigation id — and then READS THE VERDICT BACK from
 * /verify/verdicts (the CR1 gate: recorded, not just POSTed).
 */
import type { TraceFilters } from "@/lib/api";
import { useCallback, useEffect, useMemo, useState } from "react";

import { soleSqlOfEvents } from "@/lib/verdictSql";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { StatusChip } from "@/components/brief/StatusChip";
import { ResizableSplit } from "@/components/ResizableSplit";
import { TraceFlow } from "@/components/agentops/TraceFlow";
import { originOf } from "@/components/agentops/RunNodes";
import { TraceWaterfall } from "@/components/agentops/TraceWaterfall";
import {
  getTrace, getTraceLogs, getTraces, getTraceFeedback, getVerdicts, recordTraceFeedback,
  recordVerdict,
  type FindingVerdict, type SessionEvent, type TraceDetail, type TraceFeedback,
  type TraceLogs, type TraceSpan, type TraceSummary,
} from "@/lib/api";
import { fmtMs } from "@/lib/cost";
import { compactNumber, relTime } from "@/lib/format";

/** Depth of every span id, walked from the tree the API assembled. */
function spanDepths(spans: TraceSpan[], depth = 1, out: Map<string, number> = new Map()) {
  for (const s of spans) {
    out.set(s.span_id, depth);
    spanDepths(s.children, depth + 1, out);
  }
  return out;
}

export function TraceExplorerPanel({ focusInvestigationId, focusTraceId }: {
  focusInvestigationId?: string | null;
  /** A trace opened from another layer (activity → "trace") — wins over the default pick. */
  focusTraceId?: string | null;
}) {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  // VA-4e — the canvas leads. "Where did the time go" is a follow-up question; "what did
  // this run actually do" is the one a reader opens a run with, and the flow answers it.
  const [tab, setTab] = useState<"flow" | "timeline" | "events" | "logs" | "feedback">("flow");
  /** The index collapses to a rail. A 420px list beside a canvas leaves the canvas the
   *  narrower half of the pane — measured, 24-node runs fitted at 0.4 zoom — and once a
   *  run is picked, the list has done its job. */
  const [indexOpen, setIndexOpen] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [verdicts, setVerdicts] = useState<FindingVerdict[]>([]);
  const [verdictBusy, setVerdictBusy] = useState(false);
  const [correctedSql, setCorrectedSql] = useState("");
  const [runFeedback, setRunFeedback] = useState<TraceFeedback | null>(null);
  const [logs, setLogs] = useState<TraceLogs | null>(null);
  /** Session replay: how many events the run has "reached". null = show all,
   *  which is the resting state — replay is a thing you opt into, not a mode
   *  the panel starts in. */
  const [replayAt, setReplayAt] = useState<number | null>(null);
  const [runBusy, setRunBusy] = useState(false);

  /** Narrowing happens on the SERVER. Filtering a page in the browser looks the same to
   *  a reader and answers a different question — "the matching runs" versus "the matching
   *  runs among the fifty we happened to fetch" — and the count would confirm the wrong
   *  one. `total` below is what matched; `rows` is the page cut from it. */
  const [filters, setFilters] = useState<TraceFilters>({});
  const [pageSize, setPageSize] = useState(25);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [scanned, setScanned] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [listBusy, setListBusy] = useState(false);
  /** Whether ANY run in the loaded window records a user — see the filter below. */
  const [anyUser, setAnyUser] = useState(false);

  const loadList = useCallback(() => {
    setListBusy(true);
    getTraces({
      ...(focusInvestigationId ? { investigation_id: focusInvestigationId } : {}),
      ...filters,
      limit: pageSize,
      offset,
    })
      .then(d => {
        setTraces(d.traces);
        setAnyUser(prev => prev || d.traces.some(t => !!t.user_id));
        setTotal(d.total ?? d.traces.length);
        setScanned(d.scanned_events ?? null);
      })
      .catch(() => {})
      .finally(() => setListBusy(false));
  }, [focusInvestigationId, filters, pageSize, offset]);

  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => { setOffset(0); }, [filters, pageSize]);
  useEffect(() => { if (focusTraceId) setSelected(focusTraceId); }, [focusTraceId]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    getTrace(selected).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  const invId = detail?.measured ? detail.investigation_id : null;
  // MI-3 — the SQL a verdict on this run is ABOUT. `tool_call` events carry the executed
  // statement as `payload.input`; MI-1's `audit_log.trace_id` is the durable twin of this,
  // but the events are already loaded here so no round trip is needed.
  //
  // Only when ONE distinct statement ran. A run that issued several has no single query
  // its finding rests on, and naming one would be a fabricated attribution — a wrong
  // training pair is worse than a missing one (§3.9's reward-integrity law applies to the
  // corpus, not just the grader).
  const runSql = useMemo(
    () => (detail?.measured ? soleSqlOfEvents(detail.events) : ""), [detail]);
  const connId = detail?.measured ? detail.conn_id : null;

  const loadVerdicts = useCallback(() => {
    getVerdicts(connId ?? undefined, 50).then(setVerdicts).catch(() => {});
  }, [connId]);
  useEffect(() => { setReplayAt(null); }, [selected]);

  const loadLogs = useCallback(async () => {
    if (!selected) return;
    try { setLogs(await getTraceLogs(selected)); } catch { setLogs(null); }
  }, [selected]);

  const loadRunFeedback = useCallback(async () => {
    if (!selected) return;
    try { setRunFeedback(await getTraceFeedback(selected)); } catch { setRunFeedback(null); }
  }, [selected]);

  useEffect(() => { if (tab === "feedback") { loadVerdicts(); loadRunFeedback(); } },
    [tab, loadVerdicts, loadRunFeedback]);
  useEffect(() => { if (tab === "logs") loadLogs(); }, [tab, loadLogs]);

  const depths = useMemo(
    () => (detail?.measured ? spanDepths(detail.spans) : new Map<string, number>()),
    [detail]);

  // tool_call entry rows whose span produced a result — the result row renders
  // the pair, so the entry row is folded away. An entry with NO result renders.
  const resultSpans = useMemo(() => {
    const set = new Set<string>();
    if (detail?.measured) {
      for (const e of detail.events) {
        if (e.kind === "tool_call_result" && e.span_id) set.add(e.span_id);
      }
    }
    return set;
  }, [detail]);

  const totalMs = detail?.measured ? detail.duration_ms || 0 : 0;

  /** Where this run came from, from the rows it recorded. Shared with the canvas rail so
   *  the header and the rail cannot disagree about the same run. */
  const runOrigin = useMemo(
    () => (detail?.measured ? originOf(detail.events) : null), [detail]);

  /** The model that did the work. Named in the header because "which model was this" is
   *  the first thing asked of a slow or wrong run, and it was only ever visible by
   *  opening a node. A run that used more than one says so rather than picking one. */
  const runModel = useMemo(() => {
    if (!detail?.measured) return "";
    const models = new Set(detail.events.map(e => e.model).filter(Boolean) as string[]);
    if (models.size === 0) return "";
    if (models.size === 1) return [...models][0];
    return `${models.size} models`;
  }, [detail]);

  /** The answer headline. The detail endpoint does not carry one — every measured
   *  `final_response` row has a null payload — so it comes off the list row this run was
   *  picked from, which is where the API does compute it. */
  const runAnswer = useMemo(
    () => traces.find(t => t.trace_id === selected)?.answer ?? "",
    [traces, selected]);

  const submitRunFeedback = async (verdict: "helpful" | "unhelpful") => {
    if (!selected) return;
    setRunBusy(true);
    try {
      await recordTraceFeedback(selected, verdict, note);
      setNote("");
      loadRunFeedback();
    } finally {
      setRunBusy(false);
    }
  };

  const submitVerdict = async (verdict: "accept" | "correct" | "reject") => {
    if (!invId) return;
    setVerdictBusy(true);
    try {
      await recordVerdict({
        verdict, investigationId: invId, connectionId: connId ?? "",
        note, headline: headlineOf(detail),
        // Without these a verdict here is a label with nothing to learn from: measured
        // 2026-09-03, every `correct` row in the store had an empty `corrected_sql`
        // because chat was the only surface that sent one.
        sqlSource: runSql,
        correctedSql: verdict === "correct" ? correctedSql.trim() : "",
      });
      setNote("");
      setCorrectedSql("");
      loadVerdicts();
    } finally {
      setVerdictBusy(false);
    }
  };

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* ── the index ──────────────────────────────────────────────────────────────
          A run is found by narrowing, not by scrolling: who ran it, whether it failed,
          how long it took, what it cost. Every control here sends its value to the
          server, so a match on page four is reachable — the previous surface held a
          fixed fifty and offered no way to look past them. */}
      {!indexOpen && (
        // The collapsed rail. It states the count it is hiding, so reopening is a
        // decision rather than a guess about what is behind the tab.
        <div style={{ width: 30, flexShrink: 0, borderRight: "1px solid var(--b1)",
                      display: "flex", flexDirection: "column", alignItems: "center",
                      paddingTop: 8, gap: 6 }}>
          <Button variant="ghost" size="icon-sm" aria-label="Show the runs index"
            onClick={() => setIndexOpen(true)}>
            <Icon name="panel" size={14} />
          </Button>
          {/* `--t2`, not `--t4`. This is the only thing on a 30px rail, so it is content
              rather than a de-emphasised label, and `--t4` is 2.76:1 — below AA even for
              large text. The Agent Ops readability guard catches exactly this. */}
          <span className="aug-fs-xs" style={{ color: "var(--t2)", writingMode: "vertical-rl",
            letterSpacing: "0.1em", textTransform: "uppercase" }}>
            {total === 0 ? "runs" : `${total} runs`}
          </span>
        </div>
      )}

      {/* The index is how a run is FOUND; the canvas is what the surface is for, so the
          canvas gets the majority — and now the reader gets to say by how much.
          `ResizableSplit` owns the width: drag the divider, double-click to reset, and
          it persists. The previous fixed 420 (capped at 34% for an 820px viewport, where
          a fixed 420 left the canvas 180px and drew header, rail and cards on top of each
          other) is replaced by a 294 default — the same layout with 30% less index, which
          is what the canvas was short of. `min` keeps the list usable and `collapsed`
          hands the whole width over rather than fighting the existing hide control. */}
      <ResizableSplit
        storageKey="traces-index"
        initial={294} min={230} max={620}
        collapsed={!indexOpen}
        style={{ flex: 1, minWidth: 0 }}
        left={
      <div style={{ height: "100%", borderRight: "1px solid var(--b1)",
                    display: "flex", flexDirection: "column", overflow: "hidden" }}>

        <div style={{ padding: 10, borderBottom: "1px solid var(--b1)",
                      display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              className="aug-input aug-fs-sm"
              style={{ flex: 1, minWidth: 0 }}
              placeholder="Search question or answer…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter") setFilters(f => ({ ...f, q: search || undefined }));
              }}
              onBlur={() => setFilters(f => ({ ...f, q: search || undefined }))}
            />
            <Button variant="ghost" size="icon-sm" aria-label="Hide the runs index"
              onClick={() => setIndexOpen(false)}>
              <Icon name="panel" size={14} />
            </Button>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {/* "No result", not "Running": only the /ask and /chat door records a final
                response, so most runs without one are finished, not in flight. Measured
                live at 53 of 73, the oldest four days old. */}
            {([["", "All"], ["ok", "OK"], ["error", "Failed"], ["unfinished", "No result"]] as const)
              .map(([value, label]) => (
                <Button key={label} variant={(filters.status ?? "") === value ? "secondary" : "ghost"}
                  size="sm" className="aug-fs-xs"
                  onClick={() => setFilters(f => ({ ...f, status: value || undefined }))}>
                  {label}
                </Button>
              ))}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {/* Offered only when the data can answer it. `emit` accepts a user id and no
                caller passes one — measured at 0 of 73 runs — so on an install without
                identity this control could only ever return nothing, and a filter that
                cannot match is worse than no filter. It appears the moment a run records
                a user, which is also how an operator learns identity started arriving. */}
            <input
              className="aug-input aug-fs-xs" style={{ flex: 1 }}
              placeholder={anyUser ? "User ID" : "User ID — none recorded"}
              disabled={!anyUser}
              defaultValue={filters.user_id ?? ""}
              onBlur={e => setFilters(f => ({ ...f, user_id: e.target.value || undefined }))}
            />
            <select
              className="aug-input aug-fs-xs" style={{ flex: 1 }}
              value={filters.min_duration_ms ?? ""}
              onChange={e => setFilters(f => ({
                ...f, min_duration_ms: e.target.value ? Number(e.target.value) : undefined }))}
            >
              <option value="">Any duration</option>
              <option value="1000">over 1s</option>
              <option value="10000">over 10s</option>
              <option value="60000">over 1m</option>
            </select>
            <select
              className="aug-input aug-fs-xs" style={{ flex: 1 }}
              value={filters.min_tokens ?? ""}
              onChange={e => setFilters(f => ({
                ...f, min_tokens: e.target.value ? Number(e.target.value) : undefined }))}
            >
              <option value="">Any tokens</option>
              <option value="1000">over 1K</option>
              <option value="10000">over 10K</option>
              <option value="100000">over 100K</option>
            </select>
          </div>
          {(filters.status || filters.user_id || filters.q || filters.min_duration_ms
            || filters.min_tokens) && (
            <Button variant="ghost" size="sm" className="aug-fs-xs"
              onClick={() => { setFilters({}); setSearch(""); }}>
              Clear filters
            </Button>
          )}
        </div>

        {focusInvestigationId && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "6px 10px" }}>
            traces for deep analysis <code className="aug-fs-xs">{focusInvestigationId}</code>
          </div>
        )}

        <div style={{ flex: 1, overflowY: "auto", padding: 10 }}>
          {traces.length === 0 ? (
            <div className="aug-fs-sm" style={{ padding: 16, color: "var(--t3)" }}>
              {listBusy ? "Loading…"
                : total === 0 && (filters.q || filters.status || filters.user_id
                                  || filters.min_duration_ms || filters.min_tokens)
                  ? "No run matches these filters."
                  : "Recording is on — the next question asked will appear here as a trace."}
            </div>
          ) : traces.map(t => (
            <Button key={t.trace_id} variant="ghost" size="sm"
              onClick={() => setSelected(t.trace_id)}
              style={{
                display: "block", width: "100%", height: "auto", textAlign: "left",
                padding: "8px 10px", marginBottom: 2, whiteSpace: "normal",
                background: selected === t.trace_id ? "var(--bg-sel)" : undefined,
              }}>
              <span className="aug-fs-sm" style={{ display: "block", lineHeight: 1.35,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {t.question || t.trace_id}
              </span>
              {t.answer && (
                <span className="aug-fs-xs" style={{ display: "block", color: "var(--t3)",
                  marginTop: 1, overflow: "hidden", textOverflow: "ellipsis",
                  whiteSpace: "nowrap" }}>
                  → {t.answer}
                </span>
              )}
              <span className="aug-fs-xs" style={{ display: "block", color: "var(--t2)", marginTop: 2 }}>
                {relTime(t.started)}
                {t.user_id && <> · <span style={{ color: "var(--t3)" }}>u:{t.user_id}</span></>}
                {" · "}{t.llm_calls} llm · {t.tool_calls} tools
                {t.duration_ms != null && <> · {fmtMs(t.duration_ms)}</>}
                {!!t.total_tokens && <> · {compactNumber(t.total_tokens)} tok</>}
                {t.errors > 0 && <span style={{ color: "var(--red4)" }}> · {t.errors} err</span>}
                {t.ok === false && <span style={{ color: "var(--red4)" }}> · failed</span>}
                {t.ok == null && <span style={{ color: "var(--t3)" }}> · no result recorded</span>}
              </span>
              {/* Cost is a FLOOR. A $0.00 next to unpriced calls means nobody published a
                  rate for that model — printing it bare would read as free. */}
              {(t.cost_usd != null && (t.cost_usd > 0 || !!t.unpriced_calls)) && (
                <span className="aug-fs-xs" style={{ display: "block", color: "var(--t3)", marginTop: 1 }}>
                  ${t.cost_usd.toFixed(4)}
                  {!!t.unpriced_calls && ` · ${t.unpriced_calls} unpriced`}
                </span>
              )}
            </Button>
          ))}
        </div>

        {/* Paging over what MATCHED, with the window it was counted in stated rather
            than implied — a total with no window is a claim about all of history. */}
        <div style={{ borderTop: "1px solid var(--b1)", padding: "6px 10px",
                      display: "flex", alignItems: "center", gap: 6 }}>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            {total === 0 ? "0 runs" : `${offset + 1}–${Math.min(offset + pageSize, total)} of ${total}`}
            {scanned != null && <span style={{ color: "var(--t3)" }}> · last {compactNumber(scanned)} events</span>}
          </span>
          <select
            className="aug-input aug-fs-xs" style={{ width: 62, marginLeft: "auto" }}
            value={pageSize}
            onChange={e => setPageSize(Number(e.target.value))}
          >
            {[10, 25, 50, 100].map(n => <option key={n} value={n}>{n}</option>)}
          </select>
          <Button variant="ghost" size="sm" className="aug-fs-xs"
            disabled={offset === 0}
            onClick={() => setOffset(o => Math.max(0, o - pageSize))}>‹</Button>
          <Button variant="ghost" size="sm" className="aug-fs-xs"
            disabled={offset + pageSize >= total}
            onClick={() => setOffset(o => o + pageSize)}>›</Button>
        </div>
      </div>
        }
        right={
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {!detail || !detail.measured ? (
          <div style={{ padding: 32, fontSize: 12, color: "var(--t3)" }}>
            {detail && !detail.measured
              ? <>Not recorded — enable <code style={{ fontSize: 11 }}>obs.session_log</code>.</>
              : "Select a trace."}
          </div>
        ) : (
          <>
            {/* One header, two rows: WHAT this run is, then HOW to read it. They were
                one row of eight controls competing for the same horizontal space, and the
                title — the only part that is unique to the run — was the piece that got
                truncated. */}
            <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--b1)",
              display: "flex", flexDirection: "column", gap: 7 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="aug-fs-ui" style={{ fontWeight: 500, overflow: "hidden",
                    textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {detail.question || detail.trace_id}
                  </div>
                  <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2,
                    display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <span>{compactNumber(detail.events.length)} events</span>
                    {totalMs > 0 && <span>{fmtMs(totalMs)}</span>}
                    {runOrigin?.service && <span>via {runOrigin.service}</span>}
                    {runOrigin?.builtinAgent && <span>{runOrigin.builtinAgent}</span>}
                    {detail.agent_id && <span>custom agent {detail.agent_id}</span>}
                    {runModel && <span>{runModel}</span>}
                    {invId && <span>deep analysis {invId}</span>}
                  </div>
                </div>
                {detail.ok != null && (
                  <StatusChip hue={detail.ok ? "positive" : "negative"} strength="soft">
                    {detail.ok ? "ok" : "failed"}
                  </StatusChip>
                )}
              </div>
              {/* A segmented group rather than five loose buttons: these are five readings
                  of ONE run, and loose buttons read as five unrelated actions. */}
              <div style={{ display: "inline-flex", gap: 2, padding: 2, alignSelf: "flex-start",
                border: "1px solid var(--b1)", borderRadius: "var(--r-chip)",
                background: "var(--bg-1)" }}>
                {([["flow", "Flow"], ["timeline", "Waterfall"], ["events", "Events"],
                   ["logs", "Logs"], ["feedback", "Feedback"]] as const).map(([key, label]) => (
                  <Button key={key} variant={tab === key ? "secondary" : "ghost"} size="xs"
                    onClick={() => setTab(key)}>{label}</Button>
                ))}
              </div>
            </div>

            {tab === "timeline" ? (
              <div style={{ flex: 1, overflowY: "auto", padding: "12px 20px" }}>
                {detail.timeline
                  ? <TraceWaterfall timeline={detail.timeline} />
                  : <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
                      This run predates the laid-out timeline, or the API did not return
                      one. The Events tab reads the same run from its raw log.
                    </div>}
              </div>
            ) : tab === "flow" ? (
              // `overflow: hidden`, not `auto`: the canvas pans and its rail scrolls on
              // their own, and an outer scrollbar would let the whole surface slide
              // instead — the reason this tab used to feel smaller than its pane.
              <div style={{ flex: 1, overflow: "hidden", padding: "12px 16px",
                display: "flex", flexDirection: "column" }}>
                {detail.timeline
                  ? <TraceFlow timeline={detail.timeline} edges={detail.flow_edges ?? []}
                               events={detail.events ?? []} answer={runAnswer} />
                  : <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
                      This run predates the laid-out timeline, so there is no graph to
                      draw. The Events tab reads the same run from its raw log.
                    </div>}
              </div>
            ) : tab === "events" ? (
              <div style={{ flex: 1, overflowY: "auto", padding: "10px 20px" }}>
                {/* Replay — step the run forward in `session_events` order, which is the
                    order it actually happened in (`seq`, the store's own monotonic write
                    order, not a timestamp two events can share). Events past the cursor
                    are DIMMED rather than removed: the run's shape stays on screen, so
                    stepping shows what was known at step N against what was still to
                    come. Removing them would make every step look like a different run. */}
                <div style={{ display: "flex", gap: 8, alignItems: "center",
                  padding: "0 6px 8px" }}>
                  <Button variant="ghost" size="xs"
                    onClick={() => setReplayAt(a => Math.max(1, (a ?? detail.events.length) - 1))}
                    disabled={replayAt !== null && replayAt <= 1}>← Step</Button>
                  <Button variant="ghost" size="xs"
                    onClick={() => setReplayAt(a => a === null ? 1
                      : Math.min(detail.events.length, a + 1))}
                    disabled={replayAt !== null && replayAt >= detail.events.length}>Step →</Button>
                  <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>
                    {replayAt === null
                      ? `${detail.events.length} events`
                      : `step ${replayAt} of ${detail.events.length}`}
                  </span>
                  {replayAt !== null && (
                    <Button variant="ghost" size="xs" onClick={() => setReplayAt(null)}>
                      Show all
                    </Button>
                  )}
                </div>
                {detail.events.map((e, idx) => {
                  if (e.kind === "tool_call" && e.span_id && resultSpans.has(e.span_id)) return null;
                  const reached = replayAt === null || idx < replayAt;
                  const isCursor = replayAt !== null && idx === replayAt - 1;
                  const depth = e.span_id ? (depths.get(e.span_id) ?? 0) : 0;
                  const width = totalMs > 0 && e.duration_ms != null
                    ? Math.max(1.5, Math.min(100, (e.duration_ms / totalMs) * 100)) : null;
                  const isOpen = expanded === e.seq;
                  return (
                    <div key={e.seq} style={{
                      opacity: reached ? 1 : 0.28,
                      borderLeft: isCursor ? "2px solid var(--blue3)" : "2px solid transparent" }}>
                      <Button variant="ghost" size="sm"
                        onClick={() => setExpanded(isOpen ? null : e.seq)}
                        style={{ display: "flex", width: "100%", height: "auto",
                          alignItems: "center", gap: 8, padding: "4px 6px",
                          marginLeft: depth * 18, textAlign: "left" }}>
                        <span style={{ fontSize: 11, color: "var(--t2)", width: 110,
                          flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis",
                          whiteSpace: "nowrap" }}>{e.kind}</span>
                        <span style={{ fontSize: 12, minWidth: 90, flexShrink: 0,
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {e.name || "—"}
                        </span>
                        <span style={{ flex: 1, height: 8, position: "relative" }}>
                          {width != null && (
                            <span style={{ position: "absolute", left: 0, top: 1, height: 6,
                              width: `${width}%`, borderRadius: "var(--r1)",
                              background: e.ok === false ? "var(--red3)"
                                : e.kind === "llm_call" ? "var(--vio3)" : "var(--blue3)" }} />
                          )}
                          {e.kind === "tool_call" && !resultSpans.has(e.span_id || "") && (
                            <span style={{ fontSize: 11, color: "var(--amb4)" }}>
                              no result recorded — entry-side evidence of a hang or cancel
                            </span>
                          )}
                        </span>
                        {e.ok === false && <StatusChip hue="negative" strength="soft">
                          {e.error_class || "failed"}</StatusChip>}
                        {e.retries ? <span style={{ fontSize: 11, color: "var(--amb4)" }}>
                          ×{e.retries + 1}</span> : null}
                        {e.total_tokens != null && (
                          <span style={{ fontSize: 11, color: "var(--t3)",
                            fontVariantNumeric: "tabular-nums" }}>
                            {compactNumber(e.total_tokens)} tok</span>
                        )}
                        {e.duration_ms != null && (
                          <span style={{ fontSize: 11, color: "var(--t3)", width: 64,
                            textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                            {fmtMs(e.duration_ms)}</span>
                        )}
                      </Button>
                      {isOpen && (
                        <div style={{ margin: `2px 0 8px ${depth * 18 + 14}px`, padding: 10,
                          background: "var(--bg-2)", border: "1px solid var(--b1)",
                          borderRadius: "var(--r2)", fontSize: 11 }}>
                          <DetailGrid e={e} />
                          {e.content_captured && (
                            <div style={{ color: "var(--amb4)", margin: "6px 0 4px" }}>
                              prompt content captured (obs.prompt_capture was on for this call)
                            </div>
                          )}
                          {e.payload != null && (
                            <pre style={{ margin: "6px 0 0", whiteSpace: "pre-wrap",
                              wordBreak: "break-word", maxHeight: 220, overflowY: "auto",
                              color: "var(--t2)", fontSize: 11 }}>
                              {JSON.stringify(e.payload, null, 1)}
                            </pre>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : tab === "logs" ? (
              /* What the run SURVIVED, beside what it did. A tolerated error cannot
                 appear in the waterfall — the span it happened inside succeeded — so
                 these lines are the only place it exists. Scoped to this run, which
                 scopes it in time: the same journal read in aggregate shows 959
                 NameErrors from a guard that was fixed two months ago. */
              <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
                {!logs || logs.count === 0 ? (
                  <div className="aug-fs-sm" style={{ padding: 8, color: "var(--t3)" }}>
                    No kernel journal lines for this run. Spans are recorded separately —
                    the waterfall is unaffected.
                  </div>
                ) : (
                  <>
                    <div className="aug-fs-xs" style={{ color: "var(--t2)", padding: "0 4px 8px" }}>
                      {logs.count} journal {logs.count === 1 ? "line" : "lines"}
                      {logs.tolerated_errors > 0 && (
                        <span style={{ color: "var(--red4)" }}>
                          {" · "}{logs.tolerated_errors} swallowed
                          {logs.tolerated_errors === 1 ? " error" : " errors"}
                        </span>
                      )}
                    </div>
                    {logs.lines.map(line => (
                      <div key={`${line.seq}-${line.kind}`} className="aug-fs-sm"
                        style={{ padding: "6px 4px", borderBottom: "1px solid var(--b0)" }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <StatusChip strength="soft" hue={line.tolerated ? "negative" : "info"}>
                            {line.kind}
                          </StatusChip>
                          <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>
                            {relTime(line.at)}
                          </span>
                        </div>
                        {line.tolerated ? (
                          <div style={{ marginTop: 4 }}>
                            <div style={{ color: "var(--red4)" }}>{line.error}</div>
                            {/* The reason is what separates a designed degradation from
                                a bug nobody noticed. Without it the error is unreadable. */}
                            <div className="aug-fs-xs" style={{ color: "var(--t2)", marginTop: 2 }}>
                              tolerated because: {line.reason}
                              {line.counter ? ` · ${line.counter}` : ""}
                            </div>
                          </div>
                        ) : line.payload ? (
                          <pre className="aug-fs-xs" style={{ margin: "4px 0 0", color: "var(--t2)",
                            whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                            {JSON.stringify(line.payload)}
                          </pre>
                        ) : null}
                      </div>
                    ))}
                  </>
                )}
              </div>
            ) : (
              <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
                {/* Was this RUN any good — available on every trace. The verdict block
                    below judges a FINDING and needs a deep-analysis id, which 256 of 263
                    runs on this store do not have; it used to be the only control here,
                    so on a quick turn the buttons did nothing at all. */}
                <div className="aug-fs-sm" style={{ marginBottom: 8 }}>Was this run helpful?</div>
                <textarea className="aug-input aug-fs-sm" value={note} rows={2}
                  placeholder="Optional note (what was right or wrong)"
                  onChange={e => setNote(e.target.value)}
                  style={{ width: "100%", marginBottom: 8 }} />
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 18 }}>
                  <Button variant="secondary" size="sm" disabled={runBusy}
                    onClick={() => submitRunFeedback("helpful")}>Helpful</Button>
                  <Button variant="outline" size="sm" disabled={runBusy}
                    onClick={() => submitRunFeedback("unhelpful")}>Unhelpful</Button>
                  {runFeedback && runFeedback.count > 0 && (
                    <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>
                      {runFeedback.helpful} helpful · {runFeedback.unhelpful} unhelpful
                    </span>
                  )}
                </div>
                {runFeedback && runFeedback.items.length > 0 && (
                  <div style={{ marginBottom: 18 }}>
                    {runFeedback.items.map((f, i) => (
                      <div key={`${f.at}-${i}`} className="aug-fs-sm" style={{ display: "flex",
                        gap: 8, alignItems: "center", padding: "6px 0",
                        borderBottom: "1px solid var(--b0)" }}>
                        <StatusChip strength="soft"
                          hue={f.verdict === "helpful" ? "positive" : "negative"}>
                          {f.verdict}
                        </StatusChip>
                        <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {f.note || (f.by ? `by ${f.by}` : "no note")}
                        </span>
                        <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>{relTime(f.at)}</span>
                      </div>
                    ))}
                  </div>
                )}
                {!invId ? (
                  <div style={{ fontSize: 12, color: "var(--t3)" }}>
                    This trace recorded no deep analysis id (a quick turn), so there is no
                    finding to accept or reject — the run judgement above is the one that
                    applies here.
                  </div>
                ) : (
                  <>
                    <div style={{ fontSize: 12, marginBottom: 8 }}>
                      Record a verdict on this run&apos;s finding — it lands in the
                      verify store and feeds the closed loop. Uses the note above.
                    </div>
                    {/* The correction itself, not just the fact that one was needed. A
                        `correct` verdict with no corrected SQL is a judgement without a
                        lesson — the exporter drops it rather than invent a preference,
                        so without this field this surface could only ever produce
                        accepts. Offered only when ONE statement ran, because otherwise
                        there is no single query this would be correcting. */}
                    {runSql && (
                      <textarea className="aug-input aug-fs-sm font-code" rows={3}
                        value={correctedSql}
                        placeholder="Optional: the SQL that WOULD have been right (used with “Needs correction”)"
                        onChange={e => setCorrectedSql(e.target.value)}
                        style={{ width: "100%", marginBottom: 8 }} />
                    )}
                    <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
                      <Button variant="secondary" size="sm" disabled={verdictBusy}
                        onClick={() => submitVerdict("accept")}>Accept</Button>
                      <Button variant="outline" size="sm" disabled={verdictBusy}
                        onClick={() => submitVerdict("correct")}>Needs correction</Button>
                      <Button variant="destructive" size="sm" disabled={verdictBusy}
                        onClick={() => submitVerdict("reject")}>Reject</Button>
                    </div>
                    <div className="aug-label" style={{ color: "var(--t2)", marginBottom: 6 }}>
                      Verdicts on record{connId ? ` · ${connId}` : ""}
                    </div>
                    {verdicts.length === 0 ? (
                      <div style={{ fontSize: 12, color: "var(--t2)" }}>None yet.</div>
                    ) : verdicts.map(v => (
                      <div key={v.id} style={{ display: "flex", gap: 8, alignItems: "center",
                        padding: "6px 0", borderBottom: "1px solid var(--b0)", fontSize: 12 }}>
                        <StatusChip strength="soft"
                          hue={v.verdict === "accept" ? "positive"
                            : v.verdict === "reject" ? "negative" : "caution"}>
                          {v.verdict}
                        </StatusChip>
                        <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {v.headline || v.note || v.investigation_id}
                        </span>
                        {v.investigation_id === invId && (
                          <StatusChip hue="info" strength="soft">this run</StatusChip>
                        )}
                        <span style={{ color: "var(--t2)", fontSize: 11 }}>{relTime(v.created_at)}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>
        }
      />
    </div>
  );
}

function headlineOf(detail: TraceDetail | null): string {
  if (!detail?.measured) return "";
  const final = [...detail.events].reverse().find(e => e.kind === "final_response");
  return String((final?.payload as { headline?: string })?.headline || "");
}

function DetailGrid({ e }: { e: SessionEvent }) {
  const rows: [string, string][] = [];
  if (e.model) rows.push(["model", `${e.provider ? `${e.provider} · ` : ""}${e.model}`]);
  if (e.prompt_tokens != null) rows.push(["prompt tokens", compactNumber(e.prompt_tokens)]);
  if (e.completion_tokens != null) rows.push(["completion tokens", compactNumber(e.completion_tokens)]);
  if (e.retries != null) rows.push(["retries", String(e.retries)]);
  if (e.row_count != null) rows.push(["rows returned", String(e.row_count)]);
  if (e.error_class) rows.push(["error class", e.error_class]);
  if (e.session_id) rows.push(["session", e.session_id]);
  if (e.agent_id) rows.push(["agent", e.agent_id]);
  if (rows.length === 0) return null;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "2px 14px" }}>
      {rows.map(([k, v]) => (
        <span key={k} style={{ display: "contents" }}>
          <span style={{ color: "var(--t2)" }}>{k}</span>
          <span style={{ fontVariantNumeric: "tabular-nums" }}>{v}</span>
        </span>
      ))}
    </div>
  );
}
