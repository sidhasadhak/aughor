"use client";

/**
 * InvestigationConsole — the "operations console" Investigation screen.
 *
 * Renders a single investigate-mode turn as the three fixed columns from the
 * console design (design-mockups/aughor-console-direction.html):
 *
 *   reasoning  ·  finding + chart  ·  evidence / provenance
 *
 * It is a re-layout of data the turn already carries — it reuses ThinkingTrace
 * for the reasoning timeline, ResultChartCard for the figure, and this
 * investigation's recorded EvidenceClaims + trust receipt for provenance. No new
 * API surface; visual composition only.
 */

import { useEffect, useState } from "react";
import type { ChatTurn } from "@/lib/useChat";
import { ThinkingTrace, turnToTraceState } from "./ThinkingTrace";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import {
  getRecentEvidenceClaims,
  getAnswerReceipt,
  type EvidenceClaim,
  type InsightReceipt,
} from "@/lib/api";
import { fmtCompact, fmtMs } from "@/lib/cost";

const CONF_LABEL: Record<string, string> = { HIGH: "HIGH", MEDIUM: "MED", LOW: "LOW" };

// ADA headlines/summaries carry markdown **bold** — render it as emphasis instead
// of leaking literal asterisks.
function emphasize(text: string): React.ReactNode {
  return text.split(/(\*\*[^*]+\*\*)/g).map((seg, i) =>
    seg.startsWith("**") && seg.endsWith("**")
      ? <b key={i} style={{ color: "var(--t1)", fontWeight: 700 }}>{seg.slice(2, -2)}</b>
      : seg);
}

// A change label is only worth showing (and never in critical red) when it
// actually describes a change — drop "N/A"/"none"/empty placeholders.
function meaningfulChange(label?: string): string | null {
  const t = (label ?? "").trim();
  if (!t || /^(n\/?a|none|—|-|0)$/i.test(t)) return null;
  return t;
}

function DbIcon({ size = 15 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="6" rx="7" ry="3" />
      <path d="M5 6v12c0 1.6 3.1 3 7 3s7-1.4 7-3V6M5 12c0 1.6 3.1 3 7 3s7-1.4 7-3" />
    </svg>
  );
}

const colhead: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, height: 34, padding: "0 16px",
  borderBottom: "1px solid var(--b1)", position: "sticky", top: 0,
  background: "var(--bg-1)", zIndex: 2,
};

/* ── Evidence claim card (console form: text + segmented meter + provenance) ── */
function ClaimRow({ claim, onOpenQuery }: { claim: EvidenceClaim; onOpenQuery?: (sql: string) => void }) {
  const filled = Math.round((claim.confidence ?? 0) * 10);
  return (
    <div style={{ padding: "14px 0", borderBottom: "1px solid var(--b1)" }}>
      <div style={{ fontSize: 12, fontWeight: 500, lineHeight: 1.45, color: "var(--t1)" }}>{claim.claim_text}</div>
      <div className="aug-conf" style={{ marginTop: 9 }} aria-label={`confidence ${Math.round((claim.confidence ?? 0) * 100)} percent`}>
        {Array.from({ length: 10 }, (_, i) => <i key={i} className={i < filled ? "on" : ""} />)}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8, fontFamily: "var(--font-code)", fontSize: 9.5, color: "var(--t3)", letterSpacing: ".04em" }}>
        <span>conf {(claim.confidence ?? 0).toFixed(2)}</span>·
        {claim.sql_source
          ? <button onClick={() => onOpenQuery?.(claim.sql_source!)} className="aug-lbl-scan" style={{ background: "none", border: "none", padding: 0, cursor: "pointer", font: "inherit", letterSpacing: ".04em" }}>view sql ↗</button>
          : <span>recorded</span>}
      </div>
      {claim.metric_used && (
        <div className="aug-receipt" style={{ marginTop: 6 }}>
          <span className="aug-rc"><span className="d" />{claim.metric_used}</span>
        </div>
      )}
    </div>
  );
}

interface Props {
  turn: ChatTurn;
  running: boolean;
  connectionId: string;
  canvasId?: string;
  onOpenQuery?: (sql: string) => void;
  onConfirm?: () => void;
  onBranch?: () => void;
}

export function InvestigationConsole({ turn, running, connectionId, canvasId, onOpenQuery, onConfirm, onBranch }: Props) {
  const [claims, setClaims] = useState<EvidenceClaim[]>([]);
  const [receipt, setReceipt] = useState<InsightReceipt | null>(null);

  // This investigation's recorded evidence claims (filtered from the scope ledger).
  useEffect(() => {
    if (!turn.investigationId) { setClaims([]); return; }
    let alive = true;
    getRecentEvidenceClaims(connectionId, canvasId, 80)
      .then(cs => { if (alive) setClaims(cs.filter(c => c.investigation_id === turn.investigationId)); })
      .catch(() => { if (alive) setClaims([]); });
    return () => { alive = false; };
  }, [connectionId, canvasId, turn.investigationId, turn.status]);

  // Trust receipt (for the key/value provenance block).
  useEffect(() => {
    if (!turn.investigationId) { setReceipt(null); return; }
    let alive = true;
    getAnswerReceipt("ada", connectionId, turn.investigationId)
      .then(r => { if (alive) setReceipt(r); })
      .catch(() => { if (alive) setReceipt(null); });
    return () => { alive = false; };
  }, [connectionId, turn.investigationId, turn.status]);

  const ada = turn.adaReport;
  const headline = ada?.headline ?? turn.headline ?? turn.question;
  const lede = ada?.executive_summary ?? turn.insight?.narrative ?? null;
  const confLabel = ada ? CONF_LABEL[ada.confidence] ?? ada.confidence : null;
  const hasChart = turn.columns.length > 0 && turn.rows.length > 0;

  const traceState = turnToTraceState(turn, running);
  const tables = turn.tablesUsed ?? [];

  // Trust receipt key/values — derived from real receipt lineage + cost.
  const cost = receipt?.cost ?? null;
  const guards = (receipt?.lineage ?? []).filter(l => l.relation === "validated_by").length;
  const governed = (receipt?.lineage ?? []).some(l => l.relation === "metric_used");
  const wallMs = cost ? (cost.llm_ms ?? 0) + (cost.query_ms ?? 0) : null;
  const kv: [string, string, boolean?][] = [];
  if (wallMs) kv.push(["Wall time", fmtMs(wallMs)]);
  if (cost?.rows_returned) kv.push(["Rows scanned", fmtCompact(cost.rows_returned)]);
  if (cost?.query_count) kv.push(["Queries", String(cost.query_count)]);
  if (cost?.total_tokens) kv.push(["Tokens", fmtCompact(cost.total_tokens)]);
  if (receipt) kv.push(["Guards fired", String(guards)]);
  if (receipt) kv.push(["Metric lineage", governed ? "GOVERNED" : "—", governed]);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "300px 1fr 320px", height: "100%", minHeight: 0 }}>

      {/* ── Reasoning ── */}
      <div style={{ overflowY: "auto", minHeight: 0, borderRight: "1px solid var(--b1)", paddingBottom: 96 }}>
        <div style={colhead}>
          <span className="aug-lbl">Reasoning</span>
          {running && <span className="aug-lbl aug-lbl-sig" style={{ marginLeft: "auto" }}>● live</span>}
        </div>
        <ThinkingTrace state={traceState} />
        <div className="aug-lbl" style={{ padding: "14px 16px 4px" }}>Objects in scope</div>
        <div style={{ padding: "0 12px 16px" }}>
          {tables.length === 0
            ? <div style={{ padding: "4px 4px", fontSize: 11, color: "var(--t4)" }}>—</div>
            : tables.map(t => (
              <div key={t} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 8px", borderRadius: "var(--r2)" }}>
                <span style={{ color: "var(--cyn3)", flexShrink: 0 }}><DbIcon /></span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontFamily: "var(--font-code)", fontSize: 12, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t}</div>
                  <div style={{ fontFamily: "var(--font-code)", fontSize: 9.5, color: "var(--t3)" }}>table</div>
                </div>
              </div>
            ))}
        </div>
      </div>

      {/* ── Finding ── */}
      <div style={{ overflowY: "auto", minHeight: 0, background: "var(--bg-0)", paddingBottom: 120 }}>
        <div style={colhead}>
          <span className="aug-lbl">{running ? "Finding · live" : "Finding"}</span>
          {confLabel && <span className="aug-lbl" style={{ marginLeft: "auto" }}>CONFIDENCE {confLabel}</span>}
        </div>
        <div style={{ padding: 20 }}>
          <div className="aug-lbl aug-lbl-sig" style={{ marginBottom: 10 }}>Primary signal</div>
          <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-.02em", lineHeight: 1.3, color: "var(--t1)", maxWidth: "46ch" }}>
            {emphasize(headline)}
          </div>
          {meaningfulChange(ada?.total_change_label) && (
            <div className="aug-lbl aug-lbl-crit" style={{ marginTop: 10 }}>{meaningfulChange(ada?.total_change_label)}</div>
          )}
          {lede && (
            <p style={{ color: "var(--t2)", fontSize: 13, margin: "10px 0 0", maxWidth: "62ch", lineHeight: 1.55 }}>{emphasize(lede)}</p>
          )}

          {hasChart && (
            <div style={{ marginTop: 20 }}>
              <ResultChartCard columns={turn.columns} rows={turn.rows} chartType={turn.chartType} chartConfig={turn.chartConfig} title={ada?.metric || turn.question} />
            </div>
          )}

          {!running && (
            <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap" }}>
              <button onClick={onConfirm} className="aug-btn aug-btn-primary aug-btn-sm">Confirm &amp; draft report</button>
              <button onClick={onBranch} className="aug-btn aug-btn-secondary aug-btn-sm">Branch hypothesis</button>
            </div>
          )}
        </div>
      </div>

      {/* ── Evidence / provenance ── */}
      <div style={{ overflowY: "auto", minHeight: 0, borderLeft: "1px solid var(--b1)", paddingBottom: 96 }}>
        <div style={colhead}>
          <span className="aug-lbl">Evidence · provenance</span>
          {claims.length > 0 && <span className="aug-lbl" style={{ marginLeft: "auto" }}>{claims.length} CLAIM{claims.length === 1 ? "" : "S"}</span>}
        </div>
        <div style={{ padding: "8px 16px 16px" }}>
          {claims.length === 0 ? (
            <div style={{ padding: "16px 0", fontSize: 12, color: "var(--t3)", lineHeight: 1.6 }}>
              {running ? "Gathering evidence…" : "No recorded claims for this investigation yet."}
            </div>
          ) : (
            claims.map(c => <ClaimRow key={c.id} claim={c} onOpenQuery={onOpenQuery} />)
          )}

          {kv.length > 0 && (
            <>
              <div className="aug-lbl" style={{ padding: "14px 0 4px" }}>Trust receipt</div>
              <div>
                {kv.map(([k, v, ok]) => (
                  <div className="aug-kv" key={k} style={{ paddingLeft: 0, paddingRight: 0 }}>
                    <span className="k">{k}</span>
                    <span className="v mono" style={ok ? { color: "var(--grn3)" } : undefined}>{v}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
