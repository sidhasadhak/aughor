"use client";

/**
 * EvidencePanel — the Evidence Ledger as a first-class intelligence layer.
 *
 * Every claim Aughor makes in a Deep Analysis is recorded with its source SQL,
 * confidence, freshness and the metric it leans on. This panel surfaces the recent
 * claims across the scope (connection / canvas) so the team can validate or dispute
 * them — closing the human-in-the-loop trust loop. Backed by /investigations/evidence/recent.
 */

import { useEffect, useState, useCallback } from "react";
import {
  getRecentEvidenceClaims,
  submitClaimFeedback,
  type EvidenceClaim,
} from "@/lib/api";

type Feedback = "validated" | "disputed" | "needs_context";

function confColor(c: number): string {
  // Console discipline: a confident claim carries the amber signal; a weak one recedes to ink.
  return c >= 0.5 ? "var(--blue3)" : "var(--t3)";
}

const FEEDBACK_META: Record<Feedback, { label: string; color: string }> = {
  validated:     { label: "Validated",     color: "var(--grn4, #2e8c63)" },
  disputed:      { label: "Disputed",      color: "var(--red4)" },
  needs_context: { label: "Needs context", color: "var(--amb4, #b6862b)" },
};

function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function ClaimCard({ claim, onInvestigate, onFeedback }: {
  claim:        EvidenceClaim;
  onInvestigate?: (q: string) => void;
  onFeedback:   (claim: EvidenceClaim, fb: Feedback) => void;
}) {
  const [showSql, setShowSql] = useState(false);
  const cColor = confColor(claim.confidence);
  const fb = claim.owner_feedback as Feedback | null;

  return (
    <div style={{
      background: "var(--bg-2)", border: "1px solid var(--b1)",
      borderLeft: `3px solid ${cColor}`, borderRadius: "var(--r3)",
      padding: "14px 16px", display: "flex", flexDirection: "column" as const, gap: 10,
    }}>
      {/* Badge row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" as const }}>
        <span title="confidence" style={{
          padding: "2px 8px", borderRadius: "var(--r2)", fontSize: 11, fontWeight: 700,
          background: `color-mix(in srgb, ${cColor} 16%, transparent)`, color: cColor,
        }}>{Math.round((claim.confidence ?? 0) * 100)}%</span>
        {claim.metric_used && (
          <span style={{
            padding: "2px 7px", borderRadius: "var(--r1)", fontSize: 10,
            background: "var(--bg-3)", border: "1px solid var(--b1)",
            color: "var(--t3)", fontFamily: "var(--font-mono)",
          }}>{claim.metric_used}</span>
        )}
        {fb && (
          <span style={{ fontSize: 10, fontWeight: 600, color: FEEDBACK_META[fb].color }}>
            ● {FEEDBACK_META[fb].label}
          </span>
        )}
        <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--t4)" }}>
          {fmtWhen(claim.created_at)}
        </span>
      </div>

      {/* Claim */}
      <div style={{ fontSize: 13, color: "var(--t1)", lineHeight: 1.6 }}>{claim.claim_text}</div>

      {/* Confidence meter — console provenance language (segmented, precise) */}
      <div className="aug-conf" aria-label={`confidence ${Math.round((claim.confidence ?? 0) * 100)} percent`}>
        {Array.from({ length: 10 }, (_, i) => (
          <i key={i} className={i < Math.round((claim.confidence ?? 0) * 10) ? "on" : ""} />
        ))}
      </div>

      {/* Meta row */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" as const, fontSize: 10, color: "var(--t4)" }}>
        {claim.data_freshness && <span>data as of {fmtWhen(claim.data_freshness)}</span>}
        {claim.sql_source && (
          <button onClick={() => setShowSql(s => !s)} style={{
            background: "transparent", border: "none", color: "var(--blue4)",
            cursor: "pointer", fontSize: 10, padding: 0,
          }}>{showSql ? "hide source query" : "show source query"}</button>
        )}
      </div>

      {showSql && claim.sql_source && (
        <pre style={{
          margin: 0, padding: "10px 12px", borderRadius: "var(--r2)",
          background: "var(--bg-1)", border: "1px solid var(--b1)",
          fontSize: 11, fontFamily: "var(--font-code)", color: "var(--t2)",
          whiteSpace: "pre-wrap" as const, wordBreak: "break-word" as const, lineHeight: 1.5,
        }}>{claim.sql_source}</pre>
      )}

      {/* Actions: validate / dispute / needs-context + investigate */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" as const, marginTop: 2 }}>
        {(Object.keys(FEEDBACK_META) as Feedback[]).map(k => {
          const active = fb === k;
          const meta = FEEDBACK_META[k];
          return (
            <button key={k} onClick={() => onFeedback(claim, k)} title={`Mark ${meta.label.toLowerCase()}`}
              style={{
                padding: "3px 9px", borderRadius: "var(--r2)", fontSize: 11, fontWeight: 500,
                background: active ? `color-mix(in srgb, ${meta.color} 16%, transparent)` : "transparent",
                border: `1px solid ${active ? meta.color : "var(--b2)"}`,
                color: active ? meta.color : "var(--t3)", cursor: "pointer", transition: "all .12s",
              }}
              onMouseEnter={e => { if (!active) e.currentTarget.style.borderColor = meta.color; }}
              onMouseLeave={e => { if (!active) e.currentTarget.style.borderColor = "var(--b2)"; }}>
              {meta.label}
            </button>
          );
        })}
        {onInvestigate && (
          <button onClick={() => onInvestigate(`Re-examine this claim: ${claim.claim_text}`)}
            style={{
              marginLeft: "auto", padding: "3px 10px", borderRadius: "var(--r2)", fontSize: 11, fontWeight: 500,
              background: "var(--bg-sel)", border: "1px solid var(--blue2)", color: "var(--blue4)", cursor: "pointer",
            }}>Re-examine →</button>
        )}
      </div>
    </div>
  );
}

export function EvidencePanel({ connectionId, canvasId, onInvestigate }: {
  connectionId:  string;
  canvasId?:     string;
  onInvestigate?: (q: string) => void;
}) {
  const [claims, setClaims]   = useState<EvidenceClaim[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    getRecentEvidenceClaims(connectionId, canvasId, 80)
      .then(setClaims)
      .catch(() => setClaims([]))
      .finally(() => setLoading(false));
  }, [connectionId, canvasId]);

  useEffect(() => { load(); }, [load]);

  const handleFeedback = useCallback(async (claim: EvidenceClaim, fb: Feedback) => {
    // optimistic toggle (clicking the active one is still a set — server is the source of truth)
    setClaims(cs => cs.map(c => c.id === claim.id ? { ...c, owner_feedback: fb } : c));
    try {
      await submitClaimFeedback(claim.investigation_id, claim.id, fb);
    } catch {
      load(); // revert to server state on failure
    }
  }, [load]);

  const validated = claims.filter(c => c.owner_feedback === "validated").length;
  const disputed  = claims.filter(c => c.owner_feedback === "disputed").length;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "20px 28px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 16 }}>
        <span className="aug-label">Evidence Ledger</span>
        <span style={{ fontSize: 11, color: "var(--t4)" }}>
          {claims.length} recent claim{claims.length === 1 ? "" : "s"}
          {validated ? ` · ${validated} validated` : ""}{disputed ? ` · ${disputed} disputed` : ""}
        </span>
        <button onClick={load} style={{
          marginLeft: "auto", padding: "3px 10px", borderRadius: "var(--r2)", fontSize: 11,
          background: "transparent", border: "1px solid var(--b1)", color: "var(--t3)", cursor: "pointer",
        }}>Refresh</button>
      </div>

      <p style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.6, marginTop: 0, marginBottom: 18, maxWidth: 720 }}>
        Every claim from a Deep Analysis is logged with its source query, confidence and freshness.
        Validate or dispute them to teach Aughor which findings hold up.
      </p>

      {loading ? (
        <div style={{ display: "flex", flexDirection: "column" as const, gap: 12 }}>
          {[1, 2, 3].map(i => (
            <div key={i} className="animate-pulse" style={{ height: 96, borderRadius: "var(--r3)", background: "var(--bg-2)" }} />
          ))}
        </div>
      ) : claims.length === 0 ? (
        <div style={{
          padding: "32px 24px", borderRadius: "var(--r3)", border: "1px dashed var(--b2)",
          background: "var(--bg-2)", textAlign: "center" as const, color: "var(--t3)",
        }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: "var(--t2)", marginBottom: 6 }}>No evidence yet</div>
          <div style={{ fontSize: 12, lineHeight: 1.6, maxWidth: 460, margin: "0 auto" }}>
            The ledger fills as you run Deep Analyses on this {canvasId ? "canvas" : "connection"}. Each
            investigation records the claims it makes and the queries behind them here.
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column" as const, gap: 12 }}>
          {claims.map(c => (
            <ClaimCard key={c.id} claim={c} onInvestigate={onInvestigate} onFeedback={handleFeedback} />
          ))}
        </div>
      )}
    </div>
  );
}
