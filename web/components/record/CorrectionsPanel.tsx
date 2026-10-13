"use client";

/**
 * Corrections — what the platform was wrong about, as a page of its own (the 2027 study §N and
 * §V, screen 9): a number that later changed, a cause that tested false, a move a person found
 * that nothing flagged, a prediction that fell outside its band, a decision that went worse than
 * expected. Each row says what was believed and what replaced it.
 *
 * Laid out to CLARITY: the counts by kind first, then when they happened, then one card per kind
 * with one row per correction — the long texts behind a click. A re-booking that changed no words
 * is bookkeeping, not a correction a reader was owed: it is counted once, as noise, and not
 * listed. A kind with a count of zero has none recorded — which is not the same as none having
 * happened, and the page says so.
 */
import type { Connection } from "@/lib/api";
import { countNoun, formatCount } from "@/lib/format";
import { dayMonth, dayWords } from "@/lib/home";
import { connectionLabel } from "@/lib/names";
import { getCorrections, type Corrections, type CorrectionEntry, type CorrectionKind } from "@/lib/record";
import { Gate, ListCard, ListRow, day, useLoad, type ListColumn } from "@/components/record/kit";
import { Chip, Columns, Card, Dot, Figure, Figures, NUM, NeedsYou, Page } from "@/components/clarity/kit";
import { dateWords, firstSentence, predictionView, VERDICT_SHORT } from "@/components/record/words";

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

/** How many days the picture covers. */
const DAYS = 14;

export function CorrectionsPanel({ connections, onOpenClaim, onOpenDecision, onOpenInquiryKey }: {
  connections: Connection[];
  onOpenClaim: (id: string) => void;
  onOpenDecision: (id: string) => void;
  /** A refuted cause names its inquiry by key; the shell finds it. */
  onOpenInquiryKey: (key: string) => void;
}) {
  const load = useLoad(() => getCorrections({ limit: 500 }), []);
  const open = (e: CorrectionEntry): (() => void) | undefined => {
    if (e.kind === "decision_worse_than_expected" && e.decision) return () => onOpenDecision(e.decision!);
    if (e.kind === "refuted_hypothesis" && e.inquiry) return () => onOpenInquiryKey(e.inquiry!);
    if (e.kind !== "missed_move" && e.ref) return () => onOpenClaim(e.ref);
    return undefined;
  };
  return (
    <Page testId="corrections-page">
      <Gate load={load} what="corrections">
        {c => <CorrectionsOverview c={c} connections={connections} open={open} />}
      </Gate>
    </Page>
  );
}

/** The entry's extra fields the ledger books on a scored prediction (`low`, `high`, `actual`, `against`). */
type Scored = CorrectionEntry & { low?: unknown; high?: unknown; actual?: unknown; against?: unknown };

/** A prediction that missed, read the way a prediction claim is: its metric, its range, its band and the actual. */
function missed(e: Scored) {
  return predictionView({
    kind: "prediction", state: "scored", statement: { text: e.believed },
    extra: { low: e.low, high: e.high, actual: e.actual, scored_against: e.against },
  });
}

function CorrectionsOverview({ c, connections, open }: {
  c: Corrections; connections: Connection[]; open: (e: CorrectionEntry) => (() => void) | undefined;
}) {
  const all = c.entries;
  const same = all.filter(e => e.believed === e.replaced_by);
  // The noise, named: what kind of claim was re-booked with its words unchanged (a prediction re-booked as scored).
  const sameKinds = [...new Set(same.map(e => String((e as { claim_kind?: unknown }).claim_kind ?? "")))];
  const sameWhat = sameKinds.length === 1 && sameKinds[0] ? `${sameKinds[0]}s` : "more";
  const shown = all.filter(e => e.believed !== e.replaced_by);
  const of = (k: CorrectionKind) => shown.filter(e => e.kind === k);
  const ranked = [...ORDER].sort((a, b) => of(b).length - of(a).length);
  const [first, second, ...rest] = ranked;
  const restCount = rest.reduce((s, k) => s + of(k).length, 0);

  // The picture: corrections a day, the last fortnight, ending today.
  const today = new Date();
  const days = Array.from({ length: DAYS }, (_, i) => {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - (DAYS - 1 - i)));
    return d.toISOString().slice(0, 10);
  });
  const inDays = shown.filter(e => days.includes(day(e.at)));

  const columns: ListColumn<CorrectionEntry>[] = [
    { head: "Kind", value: e => c.labels[e.kind] ?? e.kind },
    { head: "What was believed", value: e => e.believed },
    { head: "What replaced it", value: e => e.replaced_by },
    { head: "Why", value: e => e.why },
    { head: "Recorded", value: e => day(e.at) },
    { head: "Connection", value: e => connectionLabel(e.connection_id, connections) },
  ];

  return (
    <>
      <Figures testId="correction-figures">
        <Figure label="Corrections" value={formatCount(shown.length)} testId="fig-corrections"
          title="A re-booking that changed no words is bookkeeping, not a correction a reader was owed"
          sub={same.length ? `not counted: ${formatCount(same.length)} ${sameWhat} re-booked, same words` : "each one changed what was said"} />
        {[first, second].map(k => (
          <Figure key={k} label={SHORT[k]} value={formatCount(of(k).length)} testId={`fig-correction-${k}`}
            sub={c.labels[k] ?? ""} />
        ))}
        <Figure label="Other kinds" value={formatCount(restCount)} testId="fig-correction-rest"
          title={c.note}
          sub={<>
            <span>{rest.map(k => SHORT[k].toLowerCase()).join(" · ")}</span>
            <Chip title={c.note} testId="corrections-note">none recorded is not none happened</Chip>
          </>} />
      </Figures>

      <NeedsYou testId="correction-needs" empty="Nothing needs you · each correction is booked as it happens">{[]}</NeedsYou>

      {inDays.length > 0 && (
        <Card label="When" right={`${countNoun(inDays.length, "correction")} · last ${DAYS} days`} testId="correction-days">
          <Columns columns={days.map(d => {
            const on = inDays.filter(e => day(e.at) === d);
            const kinds = ORDER.map(k => [k, on.filter(e => e.kind === k).length] as const).filter(([, n]) => n > 0);
            return {
              key: d, value: on.length, label: dayMonth(d),
              tip: `${dayWords(d)}: ${countNoun(on.length, "correction")}${kinds.length
                ? ` — ${kinds.map(([k, n]) => `${n} ${SHORT[k].toLowerCase()}`).join(", ")}` : ""}`,
            };
          })} />
        </Card>
      )}

      {shown.length === 0 && (
        <Card label="Corrections" testId="correction-empty">
          <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
            Nothing is recorded as corrected yet: no figure restated, no cause refuted, no prediction scored outside its band.
          </div>
        </Card>
      )}

      {ORDER.filter(k => of(k).length > 0).map(k => {
        // A connection every row of the card shares is named once, at the card's label.
        const here = [...new Set(of(k).map(e => e.connection_id).filter(Boolean))];
        return (
        <ListCard<CorrectionEntry> key={k} label={SHORT[k]} name={`corrections-${k}`} testId={`correction-list-${k}`}
          rows={of(k)} rowKey={e => `${e.kind}:${e.ref}:${e.at}`} columns={columns} page={8}
          tools={<span className="aug-fs-xs" style={NUM} title={c.labels[k]}>
            {formatCount(of(k).length)}{here.length === 1 ? ` · ${connectionLabel(here[0], connections)}` : ""}
          </span>}
          group={{ key: e => day(e.at), head: d => dateWords(d) || "Not dated", meta: (_, rs) => countNoun(rs.length, "correction") }}
          empty={`No ${SHORT[k].toLowerCase()} recorded.`}
          renderRow={(e, isFirst) => {
            const where = here.length > 1 ? connectionLabel(e.connection_id, connections) : "";
            if (k === "prediction_outside_interval") {
              const p = missed(e as Scored);
              if (p) {
                return (
                  <ListRow first={isFirst} testId="correction-row" onOpen={open(e)}
                    title={[p.metric, p.period].filter(Boolean).join(" · ")} full={`${e.believed}\n${e.replaced_by}`}
                    mark={<Dot hue="red" title={VERDICT_SHORT[p.verdict]} />}
                    chips={<Chip tone={p.verdict === "cannot_tell" ? "plain" : "down"}>{VERDICT_SHORT[p.verdict]}</Chip>}
                    figure={p.actual || undefined} figureTitle={e.replaced_by}
                    meta={[p.bandFull ? `expected ${p.bandFull}` : "", where].filter(Boolean).join(" · ")} />
                );
              }
            }
            return (
              <ListRow first={isFirst} testId="correction-row" onOpen={open(e)}
                title={firstSentence(e.believed)} full={`Believed: ${e.believed}\n\nReplaced by: ${e.replaced_by}`}
                mark={<Dot hue="grey" title={c.labels[e.kind] ?? e.kind} />}
                meta={[where, `${k === "refuted_hypothesis" ? "tested false" : "now"}: ${firstSentence(e.replaced_by)}`]
                  .filter(Boolean).join(" · ")}
                metaTitle={e.replaced_by} />
            );
          }} />
        );
      })}
    </>
  );
}
