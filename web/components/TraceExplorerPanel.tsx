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
import {
  getTrace, getTraces, getVerdicts, recordVerdict,
  type FindingVerdict, type SessionEvent, type TraceDetail, type TraceSpan,
  type TraceSummary,
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
  const [tab, setTab] = useState<"waterfall" | "feedback">("waterfall");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [verdicts, setVerdicts] = useState<FindingVerdict[]>([]);
  const [verdictBusy, setVerdictBusy] = useState(false);

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
  useEffect(() => { if (tab === "feedback") loadVerdicts(); }, [tab, loadVerdicts]);

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
            traces for deep analysis <code style={{ fontSize: 10 }}>{focusInvestigationId}</code>
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
            <span style={{ display: "block", fontSize: 11, color: "var(--t4)", marginTop: 2 }}>
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
                <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2 }}>
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
              <Button variant={tab === "waterfall" ? "secondary" : "ghost"} size="xs"
                onClick={() => setTab("waterfall")}>Waterfall</Button>
              <Button variant={tab === "feedback" ? "secondary" : "ghost"} size="xs"
                onClick={() => setTab("feedback")}>Feedback</Button>
            </div>

            {tab === "waterfall" ? (
              <div style={{ flex: 1, overflowY: "auto", padding: "10px 20px" }}>
                {detail.events.map(e => {
                  if (e.kind === "tool_call" && e.span_id && resultSpans.has(e.span_id)) return null;
                  const depth = e.span_id ? (depths.get(e.span_id) ?? 0) : 0;
                  const width = totalMs > 0 && e.duration_ms != null
                    ? Math.max(1.5, Math.min(100, (e.duration_ms / totalMs) * 100)) : null;
                  const isOpen = expanded === e.seq;
                  return (
                    <div key={e.seq}>
                      <Button variant="ghost" size="sm"
                        onClick={() => setExpanded(isOpen ? null : e.seq)}
                        style={{ display: "flex", width: "100%", height: "auto",
                          alignItems: "center", gap: 8, padding: "4px 6px",
                          marginLeft: depth * 18, textAlign: "left" }}>
                        <span style={{ fontSize: 11, color: "var(--t4)", width: 110,
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
                            <span style={{ fontSize: 10, color: "var(--amb4)" }}>
                              no result recorded — entry-side evidence of a hang or cancel
                            </span>
                          )}
                        </span>
                        {e.ok === false && <StatusChip hue="negative" strength="soft">
                          {e.error_class || "failed"}</StatusChip>}
                        {e.retries ? <span style={{ fontSize: 10, color: "var(--amb4)" }}>
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
                              color: "var(--t2)", fontSize: 10.5 }}>
                              {JSON.stringify(e.payload, null, 1)}
                            </pre>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
                {!invId ? (
                  <div style={{ fontSize: 12, color: "var(--t3)" }}>
                    This trace recorded no deep analysis id (a quick turn), so a verdict has
                    nothing durable to attach to. Feedback is available on deep runs.
                  </div>
                ) : (
                  <>
                    <div style={{ fontSize: 12, marginBottom: 8 }}>
                      Record a verdict on this run&apos;s finding — it lands in the
                      verify store and feeds the closed loop.
                    </div>
                    <textarea className="aug-input" value={note} rows={2}
                      placeholder="Optional note (what was right or wrong)"
                      onChange={e => setNote(e.target.value)}
                      style={{ width: "100%", marginBottom: 8, fontSize: 12 }} />
                    <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
                      <Button variant="secondary" size="sm" disabled={verdictBusy}
                        onClick={() => submitVerdict("accept")}>Accept</Button>
                      <Button variant="outline" size="sm" disabled={verdictBusy}
                        onClick={() => submitVerdict("correct")}>Needs correction</Button>
                      <Button variant="destructive" size="sm" disabled={verdictBusy}
                        onClick={() => submitVerdict("reject")}>Reject</Button>
                    </div>
                    <div className="aug-label" style={{ color: "var(--t3)", marginBottom: 6 }}>
                      Verdicts on record{connId ? ` · ${connId}` : ""}
                    </div>
                    {verdicts.length === 0 ? (
                      <div style={{ fontSize: 12, color: "var(--t4)" }}>None yet.</div>
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
                        <span style={{ color: "var(--t4)", fontSize: 11 }}>{relTime(v.created_at)}</span>
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
          <span style={{ color: "var(--t4)" }}>{k}</span>
          <span style={{ fontVariantNumeric: "tabular-nums" }}>{v}</span>
        </span>
      ))}
    </div>
  );
}
