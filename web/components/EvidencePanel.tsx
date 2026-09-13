"use client";

/**
 * EvidencePanel — the claim ledger (Aughor Intelligence · 05 Evidence).
 *
 * A claim is a row, not a card: the sentence with the query beneath it, its confidence, the
 * owner's feedback and when it was recorded — so a reader sweeps a column instead of reading
 * cards. The selected claim opens in the inspector beside the ledger, with its whole query and
 * the feedback doors. Backed by /investigations/evidence/recent.
 *
 * Drawn only from what the ledger records (aughor/evidence). What the design shows and the ledger
 * does not carry is left out rather than invented:
 *   - guard columns and a verdict per claim — guard results are not stored with a claim;
 *   - refused claims — the ledger keeps what a deep analysis asserted, never what it refused;
 *   - a receipt id, run time and bytes read — not stored;
 *   - "used in" and an outcome — `downstream_recommendations` and `outcome_status` have no writer.
 * `data_freshness` is the investigation's completion time (evidence/linker.py), so the row reads
 * "recorded", never "data as of"; `metric_used` is a keyword guess, so it reads "mentions".
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { SkeletonRows } from "@/components/ui/motion";
import { Confidence } from "@/components/ui/trust";
import { getRecentEvidenceClaims, submitClaimFeedback, type EvidenceClaim } from "@/lib/api";
import { countNoun, formatTimestamp, relTime } from "@/lib/format";

type Feedback = "validated" | "disputed" | "needs_context";
type Filter = "all" | "unreviewed" | Feedback;

const FEEDBACK: Record<Feedback, { label: string; door: string; cls: string }> = {
  validated:     { label: "validated",     door: "Validated",     cls: "aug-ledger-fb-validated" },
  disputed:      { label: "disputed",      door: "Disputed",      cls: "aug-ledger-fb-disputed" },
  needs_context: { label: "needs context", door: "Needs context", cls: "aug-ledger-fb-context" },
};

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all",           label: "all" },
  { id: "unreviewed",    label: "unreviewed" },
  { id: "validated",     label: "validated" },
  { id: "disputed",      label: "disputed" },
  { id: "needs_context", label: "needs context" },
];

/** How many recent claims the layer reads. */
const LIMIT = 80;

/** A claim id short enough for a column. */
const shortId = (id: string) => `C-${id.replace(/[^a-z0-9]/gi, "").slice(-5)}`;

/** The query's first meaningful line, for the row; the inspector shows the query whole. */
function queryLine(sql: string | null): string | null {
  return sql?.split("\n").map(l => l.trim()).find(l => l && !l.startsWith("--")) ?? null;
}

export function EvidencePanel({ connectionId, canvasId, onInvestigate }: {
  connectionId:  string;
  canvasId?:     string;
  onInvestigate?: (q: string) => void;
}) {
  const [claims, setClaims]         = useState<EvidenceClaim[]>([]);
  const [loading, setLoading]       = useState(true);
  const [filter, setFilter]         = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving]         = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    getRecentEvidenceClaims(connectionId, canvasId, LIMIT)
      .then(setClaims)
      .catch(() => setClaims([]))
      .finally(() => setLoading(false));
  }, [connectionId, canvasId]);

  useEffect(() => { load(); }, [load]);

  const counts = useMemo<Record<Filter, number>>(() => ({
    all:           claims.length,
    unreviewed:    claims.filter(c => !c.owner_feedback).length,
    validated:     claims.filter(c => c.owner_feedback === "validated").length,
    disputed:      claims.filter(c => c.owner_feedback === "disputed").length,
    needs_context: claims.filter(c => c.owner_feedback === "needs_context").length,
  }), [claims]);

  const shown = useMemo(() => (
    filter === "all" ? claims
      : filter === "unreviewed" ? claims.filter(c => !c.owner_feedback)
      : claims.filter(c => c.owner_feedback === filter)
  ), [claims, filter]);

  const selected = shown.find(c => c.id === selectedId) ?? shown[0] ?? null;

  const handleFeedback = useCallback(async (claim: EvidenceClaim, fb: Feedback) => {
    setSaving(true);
    // Optimistic; clicking the active one is still a set — the server is the source of truth.
    setClaims(cs => cs.map(c => (c.id === claim.id ? { ...c, owner_feedback: fb } : c)));
    try {
      await submitClaimFeedback(claim.investigation_id, claim.id, fb);
    } catch {
      load();   // revert to the server's state on failure
    } finally {
      setSaving(false);
    }
  }, [load]);

  if (loading) {
    return <div className="aug-ledger-pad"><SkeletonRows rows={8} /></div>;
  }

  if (claims.length === 0) {
    return (
      <div className="aug-ledger-pad">
        <EmptyState icon="ok" title="No evidence yet">
          The ledger fills as deep analyses run on this {canvasId ? "canvas" : "connection"}: each one
          records the claims it made and the query behind each.
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="aug-ledger">
      <div className="aug-ledger-main">
        <div className="aug-ledger-bar">
          <div role="group" aria-label="Filter claims by feedback" className="aug-segmented">
            {FILTERS.map(f => (
              <Button key={f.id} variant="ghost" size="xs" aria-pressed={filter === f.id}
                className="aug-seg-item aug-seg-item-mono font-normal"
                onClick={() => setFilter(f.id)}>
                {f.label} {counts[f.id]}
              </Button>
            ))}
          </div>
          <span className="aug-ledger-meta">
            {claims.length >= LIMIT ? `the latest ${LIMIT} claims` : countNoun(claims.length, "claim")}
            {counts.disputed > 0 ? ` · ${counts.disputed} disputed` : ""}
          </span>
          <Button variant="ghost" size="xs" onClick={load}>Refresh</Button>
        </div>

        <div className="aug-ledger-scroll">
          <table className="aug-dt aug-ledger-table">
            <thead>
              <tr>
                <th className="aug-ledger-col-id">id</th>
                <th>claim · and the query behind it</th>
                <th className="aug-ledger-col-conf">confidence</th>
                <th className="aug-ledger-col-fb">feedback</th>
                <th className="num aug-ledger-col-when">when</th>
              </tr>
            </thead>
            <tbody>
              {shown.map(c => {
                const query = queryLine(c.sql_source);
                return (
                  <tr key={c.id} aria-selected={selected?.id === c.id || undefined} tabIndex={0}
                    onClick={() => setSelectedId(c.id)}
                    onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedId(c.id); } }}>
                    <td className="aug-ledger-id">{shortId(c.id)}</td>
                    <td className="aug-ledger-claim">
                      <span className="aug-ledger-text">{c.claim_text}</span>
                      <span className="aug-ledger-query">{query ?? "no query recorded"}</span>
                    </td>
                    <td><Confidence value={c.confidence ?? 0} /></td>
                    <td>
                      {c.owner_feedback
                        ? <span className={FEEDBACK[c.owner_feedback].cls}>{FEEDBACK[c.owner_feedback].label}</span>
                        : <span className="aug-ledger-none">—</span>}
                    </td>
                    <td className="num aug-ledger-when" title={formatTimestamp(c.created_at)}>{relTime(c.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {shown.length === 0 && (
            <p className="aug-ledger-empty">No claim here is {FILTERS.find(f => f.id === filter)?.label}.</p>
          )}
        </div>

        <div className="aug-ledger-foot">
          <span>showing {shown.length} of {claims.length}</span>
          <span className="aug-ledger-foot-note">
            guard results and refusals are not recorded with a claim, so the ledger has no guard or verdict column
          </span>
        </div>
      </div>

      {selected && (
        <aside className="aug-inspector" aria-label="The selected claim">
          <div className="aug-inspector-head">
            <span className="aug-brief-eyebrow">Claim</span>
            <span className="aug-inspector-id">{shortId(selected.id)}</span>
            <span className="aug-inspector-end"><Confidence value={selected.confidence ?? 0} title="confidence" /></span>
          </div>

          <div className="aug-inspector-sec">
            <p className="aug-inspector-claim">{selected.claim_text}</p>
            <dl className="aug-inspector-rows">
              <div>
                <dt>recorded</dt>
                <dd title={formatTimestamp(selected.created_at)}>{relTime(selected.created_at)} ago</dd>
              </div>
              <div>
                <dt>investigation</dt>
                <dd title={selected.investigation_id}>{selected.investigation_id}</dd>
              </div>
              {selected.metric_used && (
                <div>
                  <dt>mentions</dt>
                  <dd>{selected.metric_used}</dd>
                </div>
              )}
            </dl>
          </div>

          <div className="aug-inspector-sec aug-inspector-sql">
            <span className="aug-inspector-sub">the query behind it</span>
            {selected.sql_source
              ? <pre className="aug-inspector-pre">{selected.sql_source}</pre>
              : <p className="aug-inspector-note">No query was recorded for this claim.</p>}
          </div>

          <div className="aug-inspector-sec">
            <span className="aug-brief-eyebrow">Feedback</span>
            <div className="aug-inspector-doors">
              {(Object.keys(FEEDBACK) as Feedback[]).map(k => (
                <Button key={k} variant="outline" size="xs" disabled={saving}
                  aria-pressed={selected.owner_feedback === k}
                  className={`aug-fb-door aug-fb-door-${k}`}
                  onClick={() => handleFeedback(selected, k)}>
                  {FEEDBACK[k].door}
                </Button>
              ))}
            </div>
            <p className="aug-inspector-note">
              Recorded on this claim. The alert digest counts the claims no one has reviewed; nothing
              else reads feedback yet, so it does not change future claims.
            </p>
          </div>

          {onInvestigate && (
            <div className="aug-inspector-sec">
              <div className="aug-inspector-doors">
                <Button variant="secondary" size="xs"
                  onClick={() => onInvestigate(`Re-examine this claim: ${selected.claim_text}`)}>
                  Re-examine
                </Button>
              </div>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}
