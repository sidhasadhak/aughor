"use client";

/**
 * Corrections — what the platform was wrong about, as a page of its own (the 2027 study §N and
 * §V, screen 9): a number that later changed, a cause that tested false, a move a person found
 * that nothing flagged, a prediction that fell outside its band, a decision that went worse than
 * expected. Each row says what was believed and what replaced it.
 *
 * A kind with a count of zero has none recorded — which is not the same as none having happened,
 * and the page says so.
 */
import { useMemo, useState } from "react";

import type { Connection } from "@/lib/api";
import { countNoun } from "@/lib/format";
import { connectionLabel } from "@/lib/names";
import { getCorrections, type CorrectionEntry, type CorrectionKind } from "@/lib/record";
import { Absent, Gate, Ledger, Page, day, useLoad, type LedgerColumn } from "@/components/record/kit";
import { Button } from "@/components/ui/button";

const ORDER: CorrectionKind[] = [
  "restatement", "refuted_hypothesis", "missed_move", "prediction_outside_interval", "decision_worse_than_expected",
];

const SHORT: Record<CorrectionKind, string> = {
  restatement: "Restated",
  refuted_hypothesis: "Refuted causes",
  missed_move: "Missed moves",
  prediction_outside_interval: "Predictions that missed",
  decision_worse_than_expected: "Decisions that went worse",
};

export function CorrectionsPanel({ connections, onOpenClaim, onOpenDecision, onOpenInquiryKey }: {
  connections: Connection[];
  onOpenClaim: (id: string) => void;
  onOpenDecision: (id: string) => void;
  /** A refuted cause names its inquiry by key; the shell finds it. */
  onOpenInquiryKey: (key: string) => void;
}) {
  const [kind, setKind] = useState<CorrectionKind | "">("");
  const load = useLoad(() => getCorrections({ limit: 500 }), []);
  // A re-booking that changed no words is bookkeeping, not a correction a reader was owed.
  const entries = useMemo(
    () => (load.data?.entries ?? []).filter(e => e.believed !== e.replaced_by).filter(e => !kind || e.kind === kind),
    [load.data, kind]);
  const shownCount = (k: CorrectionKind) => (load.data?.entries ?? []).filter(e => e.kind === k && e.believed !== e.replaced_by).length;
  const many = new Set((load.data?.entries ?? []).map(e => e.connection_id)).size > 1;

  const columns: LedgerColumn<CorrectionEntry>[] = [
    { head: "What was believed", cell: e => e.believed },
    { head: "What replaced it", cell: e => e.replaced_by },
    { head: "Kind", cell: e => load.data?.labels[e.kind] ?? e.kind, width: 260 },
    { head: "Recorded", cell: e => day(e.at), width: 110 },
    ...(many ? [{ head: "Connection", cell: (e: CorrectionEntry) => connectionLabel(e.connection_id, connections), width: 150 }] : []),
  ];

  const open = (e: CorrectionEntry) => {
    if (e.kind === "decision_worse_than_expected" && e.decision) return onOpenDecision(e.decision);
    if (e.kind === "refuted_hypothesis" && e.inquiry) return onOpenInquiryKey(e.inquiry);
    if (e.kind !== "missed_move" && e.ref) return onOpenClaim(e.ref);
  };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <div className="aug-toolbar" style={{ flexWrap: "wrap", height: "auto", minHeight: 36, rowGap: 6, paddingTop: 4, paddingBottom: 4 }}>
        <div role="group" aria-label="Kind of correction" className="aug-segmented">
          <Button variant="ghost" size="xs" aria-pressed={kind === ""} className={`aug-seg-item${kind === "" ? " active" : ""}`}
            onClick={() => setKind("")}>All</Button>
          {ORDER.map(k => (
            <Button key={k} variant="ghost" size="xs" aria-pressed={kind === k} title={load.data?.labels[k]}
              className={`aug-seg-item${kind === k ? " active" : ""}`} onClick={() => setKind(k)}>
              {SHORT[k]}{load.data ? ` · ${shownCount(k)}` : ""}
            </Button>
          ))}
        </div>
        {load.data && <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>{countNoun(entries.length, "correction")} · every connection</span>}
      </div>
      <Page wide>
        <Gate load={load} what="corrections">
          {c => (
            <>
              <Ledger name="corrections" columns={columns} rows={entries}
                rowKey={e => `${e.kind}:${e.ref}:${e.at}`} onOpen={open}
                empty={kind
                  ? `No ${SHORT[kind].toLowerCase()} recorded. That means none was recorded, not that none happened.`
                  : "Nothing is recorded as corrected yet: no figure restated, no cause refuted, no prediction scored outside its band, no decision reviewed as worse than expected."} />
              <Absent>{c.note}</Absent>
            </>
          )}
        </Gate>
      </Page>
    </div>
  );
}
