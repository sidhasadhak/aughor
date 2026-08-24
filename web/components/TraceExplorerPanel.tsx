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
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/brief/StatusChip";
import { TraceFlow } from "@/components/agentops/TraceFlow";
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
  const [tab, setTab] = useState<"timeline" | "flow" | "events" | "logs" | "feedback">("timeline");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [verdicts, setVerdicts] = useState<FindingVerdict[]>([]);
  const [verdictBusy, setVerdictBusy] = useState(false);
  const [runFeedback, setRunFeedback] = useState<TraceFeedback | null>(null);
  const [logs, setLogs] = useState<TraceLogs | null>(null);
  /** Session replay: how many events the run has "reached". null = show all,
   *  which is the resting state — replay is a thing you opt into, not a mode
   *  the panel starts in. */
  const [replayAt, setReplayAt] = useState<number | null>(null);
  const [runBusy, setRunBusy] = useState(false);

  const loadList = useCallback(() => {
    getTraces(focusInvestigationId ? { investigation_id: focusInvestigationId } : { limit: 50 })
      .then(d => {
        setTraces(d.traces);
        if (d.traces.length > 0) {
          setSelected(prev => (prev && d.traces.some(t => t.trace_id === prev)
            ? prev : d.traces[0].trace_id));
        }
      })
      .catch(() => {});
  }, [focusInvestigationId]);

  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => { if (focusTraceId) setSelected(focusTraceId); }, [focusTraceId]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    getTrace(selected).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  const invId = detail?.measured ? detail.investigation_id : null;
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
      });
      setNote("");
      loadVerdicts();
    } finally {
      setVerdictBusy(false);
    }
  };

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* ── trace list ── */}
      <div style={{ width: 300, flexShrink: 0, borderRight: "1px solid var(--b1)",
        overflowY: "auto", padding: 10 }}>
        {focusInvestigationId && (
          <div style={{ fontSize: 11, color: "var(--t3)", padding: "2px 6px 8px" }}>
            traces for deep analysis <code style={{ fontSize: 11 }}>{focusInvestigationId}</code>
          </div>
        )}
        {traces.length === 0 ? (
          <div style={{ padding: 16, fontSize: 12, color: "var(--t3)" }}>
            Recording is on — the next question asked will appear here as a trace.
          </div>
        ) : traces.map(t => (
          <Button key={t.trace_id} variant="ghost" size="sm"
            onClick={() => setSelected(t.trace_id)}
            style={{
              display: "block", width: "100%", height: "auto", textAlign: "left",
              padding: "8px 10px", marginBottom: 2, whiteSpace: "normal",
              background: selected === t.trace_id ? "var(--bg-sel)" : undefined,
            }}>
            <span style={{ display: "block", fontSize: 12, lineHeight: 1.35,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {t.question || t.trace_id}
            </span>
            <span style={{ display: "block", fontSize: 11, color: "var(--t2)", marginTop: 2 }}>
              {relTime(t.started)} · {t.llm_calls} llm · {t.tool_calls} tools
              {t.errors > 0 && <span style={{ color: "var(--red4)" }}> · {t.errors} err</span>}
              {t.ok === false && <span style={{ color: "var(--red4)" }}> · failed</span>}
            </span>
          </Button>
        ))}
      </div>

      {/* ── waterfall / feedback ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {!detail || !detail.measured ? (
          <div style={{ padding: 32, fontSize: 12, color: "var(--t3)" }}>
            {detail && !detail.measured
              ? <>Not recorded — enable <code style={{ fontSize: 11 }}>obs.session_log</code>.</>
              : "Select a trace."}
          </div>
        ) : (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 10,
              padding: "12px 20px", borderBottom: "1px solid var(--b1)" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500, overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{detail.question || detail.trace_id}</div>
                <div style={{ fontSize: 11, color: "var(--t2)", marginTop: 2 }}>
                  {detail.events.length} events
                  {totalMs > 0 && ` · ${fmtMs(totalMs)}`}
                  {detail.agent_id && ` · agent ${detail.agent_id}`}
                  {invId && ` · deep analysis ${invId}`}
                </div>
              </div>
              {detail.ok != null && (
                <StatusChip hue={detail.ok ? "positive" : "negative"} strength="soft">
                  {detail.ok ? "ok" : "failed"}
                </StatusChip>
              )}
              <Button variant={tab === "timeline" ? "secondary" : "ghost"} size="xs"
                onClick={() => setTab("timeline")}>Waterfall</Button>
              <Button variant={tab === "flow" ? "secondary" : "ghost"} size="xs"
                onClick={() => setTab("flow")}>Flow</Button>
              <Button variant={tab === "events" ? "secondary" : "ghost"} size="xs"
                onClick={() => setTab("events")}>Events</Button>
              <Button variant={tab === "logs" ? "secondary" : "ghost"} size="xs"
                onClick={() => setTab("logs")}>Logs</Button>
              <Button variant={tab === "feedback" ? "secondary" : "ghost"} size="xs"
                onClick={() => setTab("feedback")}>Feedback</Button>
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
              <div style={{ flex: 1, overflowY: "auto", padding: "12px 20px" }}>
                {detail.timeline
                  ? <TraceFlow timeline={detail.timeline} edges={detail.flow_edges ?? []}
                               events={detail.events ?? []} />
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
