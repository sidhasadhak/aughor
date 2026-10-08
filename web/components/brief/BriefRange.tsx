/**
 * Arc BR-3 — the Briefing of any range (flag `briefing.ranges`, ROADMAP §3.48).
 *
 * One control replaces the Standing · Day · Week · Month · Year switch: the standing view of
 * everything the platform knows, the four named periods (each the last one whose numbers have
 * settled), the month and the year to date, and any custom range. The range scopes the whole
 * page — its figures lead the hero — and every figure says whether it is final, still
 * provisional or to date. A figure is measured from an APPROVED metric by its own date
 * column; a metric that is not measured says why. Values arrive formatted by the server, so
 * the tiles, the table and the narrative cannot disagree about a figure.
 */
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { STATUS_LABEL, changeOf, rangeOf, useFollowBlock, useOpenMetric, useShownMetric } from "@/components/brief/MetricDetail";
import { StatTile, type StatDelta } from "@/components/brief/StatTile";
import { Ledger, StatusMark, useLoad, type LedgerColumn } from "@/components/record/kit";
import {
  readExpectedNext,
  type BriefingRange, type BriefingRangeBlock, type BriefingRangeMeasure, type ExpectedNext, type RangePreset,
} from "@/lib/api";
import { Segmented } from "@/components/ui/segmented";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Input } from "@/components/ui/input";

/** The control's value: the standing view, or a range. */
export type RangeChoice = { preset: "standing" } | BriefingRange;

const SEGMENTS: { value: "standing" | RangePreset; label: string; title: string }[] = [
  { value: "standing", label: "What we know", title: "Everything the platform has learned, not tied to dates" },
  { value: "yesterday", label: "Day", title: "The newest day whose numbers have settled" },
  { value: "last_week", label: "Week", title: "The last complete week whose numbers have settled" },
  { value: "last_month", label: "Month", title: "The last complete month whose numbers have settled" },
  { value: "last_year", label: "Year", title: "The last complete (fiscal) year" },
  { value: "month_to_date", label: "Month to date", title: "This month up to the newest settled day" },
  { value: "year_to_date", label: "Year to date", title: "This year up to the newest settled day" },
];

export function RangeControl({ value, onChange, disabled, standing, label = "Briefing range" }: {
  value: RangeChoice;
  onChange: (c: RangeChoice) => void;
  disabled?: boolean;
  /** What "no range" is called on this screen. The Briefing's is "What we know"; a cockpit's
   *  cards, read with no range, run as they were written — which is a different thing to say. */
  standing?: { label: string; title: string };
  /** The group's name for a screen reader. */
  label?: string;
}) {
  const [custom, setCustom] = useState(value.preset === "custom");
  const [start, setStart] = useState(value.preset === "custom" ? value.start ?? "" : "");
  const [end, setEnd] = useState(value.preset === "custom" ? value.end ?? "" : "");
  const ready = !!start && !!end && start <= end;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" as const, minWidth: 0 }}>
      <Segmented label={label} value={custom ? "custom" : value.preset} disabled={disabled}
        onChange={v => {
          if (v === "custom") { setCustom(true); return; }
          setCustom(false); onChange({ preset: v } as RangeChoice);
        }}
        options={[
          ...SEGMENTS.map(s => { const words = s.value === "standing" && standing ? standing : s; return { value: s.value, label: words.label, title: words.title }; }),
          { value: "custom" as const, label: "Custom", title: "Any range, first and last day" },
        ]} />
      {custom && (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Input type="date" aria-label="First day" value={start} max={end || undefined}
            onChange={e => setStart(e.target.value)} />
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>to</span>
          <Input type="date" aria-label="Last day" value={end} min={start || undefined}
            onChange={e => setEnd(e.target.value)} />
          <Button size="sm" variant="secondary" disabled={disabled || !ready}
            onClick={() => onChange({ preset: "custom", start, end })}>
            Show
          </Button>
        </span>
      )}
    </div>
  );
}

function deltaOf(m: BriefingRangeMeasure): StatDelta | null {
  const text = changeOf(m, "previous");
  if (!text || m.rel === null) return null;
  // Direction-neutral: whether a move is good depends on the metric (a falling return rate is),
  // and nothing declares that yet — colour would be a judgement the data does not carry.
  return { text, sign: Math.sign(m.rel), favorable: null };
}

/** The measured metrics that lead the hero: the largest moves first, at most `n`. Shared with
 *  the Key Metrics row (BR-9), which shows the REST, so no figure is on the page twice. */
export function rangeTop(block: BriefingRangeBlock, n = 4): BriefingRangeMeasure[] {
  return [...block.measured]
    .sort((a, b) => Math.abs(b.rel ?? 0) - Math.abs(a.rel ?? 0))
    .slice(0, n);
}

/** One measured metric as a tile: the server's formatted value, its change against the
 *  previous range, and its status — final, provisional or to date. */
export function RangeMeasureTile({ m }: { m: BriefingRangeMeasure }) {
  return (
    <StatTile label={m.name} value={m.current_text ?? ""}
      delta={deltaOf(m)}
      caption={`${STATUS_LABEL[m.status]} · against ${m.previous_text ?? "no comparison"}`}
      title={m.time_source ?? undefined} />
  );
}

/** The range's headline figures — its measured metrics, largest move first. */
export function RangeFigures({ block }: { block: BriefingRangeBlock }) {
  const top = rangeTop(block);
  if (top.length === 0) return null;
  return (
    <div data-brief-range-figures style={{ marginTop: 18 }}>
      <div className="aug-label" style={{ marginBottom: 8, color: "var(--t3)" }}>
        Measured for {block.covers}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(4, top.length)}, minmax(0, 1fr))`, gap: 12 }}>
        {top.map(m => <RangeMeasureTile key={m.metric} m={m} />)}
      </div>
    </div>
  );
}

/** Unmeasured metrics grouped by why: eight north stars with no approved definition are one
 *  line, not eight (theLook, 2026-09-25). */
function byReason(items: { name: string; reason: string }[]): [string, string[]][] {
  const out = new Map<string, string[]>();
  for (const u of items) out.set(u.reason, [...(out.get(u.reason) ?? []), u.name]);
  return [...out.entries()];
}

/** The one-line proof for a range: what was measured and as of when. */
export function rangeStats(block: BriefingRangeBlock): string {
  const measured = block.measured.length;
  const missing = block.unmeasured.length;
  return `${measured} measured${missing ? ` · ${missing} not measured` : ""} · as of ${block.as_of}`;
}

/** The measured table with what each metric is expected to read next (ROADMAP §6 item 42c). The
 *  bands are asked for once the table is on the page — the first ask for a range books them as
 *  predictions, later asks read them back. Until they arrive, and where they cannot be read, the
 *  table stands without the column. */
export function RangeMeasuresExpected({ connectionId, schema, workspaceId, block }: {
  connectionId: string; schema?: string; workspaceId?: string; block: BriefingRangeBlock;
}) {
  const load = useLoad(() => readExpectedNext(connectionId, rangeOf(block), schema, workspaceId),
    [connectionId, schema, workspaceId, block.key]);
  // Bands read for the period before are not this period's: none shown until this one's arrive.
  return <RangeMeasures block={block} expected={load.loading ? null : load.data} />;
}

/** The range's measured metrics. Under a page that offers the metric drawer (`MetricDetailHost`),
 *  a metric's name opens it: the trend, what moved inside it, how it is defined. With `expected`,
 *  each metric also says the band its own past puts on the next range, or that none is stated. */
export function RangeMeasures({ block, expected }: { block: BriefingRangeBlock; expected?: ExpectedNext | null }) {
  const hasYear = block.measured.some(m => m.last_year !== null) && !!block.last_year_label;
  const open = useOpenMetric();
  const shown = useShownMetric(block.key);
  const bands = new Map((expected?.items ?? []).map(i => [i.metric, i]));
  const expectedOf = useCallback((metric: string) => (expected?.target
    ? { target: expected.target, item: (expected.items ?? []).find(i => i.metric === metric) } : undefined), [expected]);
  useFollowBlock(block, expectedOf);
  // An industry that declares an income statement reads its metrics as one: each line of it heads
  // the metrics on it, top to bottom, as a profit and loss statement reads.
  const byLine = block.measured.some(m => m.line);
  const columns: LedgerColumn<BriefingRangeMeasure>[] = [
    { head: "Metric", cell: m => <span title={m.time_source ?? undefined}>{m.name}</span> },
    { head: "This range", cell: m => m.current_text ?? "", num: true, width: 130 },
    { head: "Comparison", cell: m => m.previous_text ?? "", num: true, width: 130 },
    { head: "Change", width: 190, cell: m => {
        if (m.current_partial || m.previous_partial) return `no change stated: data covers only ${m.current_partial ?? m.previous_partial}`;
        const change = changeOf(m, "previous");
        if (!change) return "no comparison rows";
        if (!m.equal_age || m.equal_age.equal) return change;
        // Said beside the number, as the cockpit's cards say it: part of this difference is age.
        return (
          <span title={m.equal_age.why}>
            {change}<span data-testid="change-not-equal-age" style={{ color: "var(--amb4)" }}> · not at equal age</span>
          </span>
        );
      } },
    ...(hasYear ? [{
      head: "A year earlier", width: 190,
      cell: (m: BriefingRangeMeasure) => {
        const change = m.last_year !== null ? changeOf(m, "last_year") : "";
        return `${m.last_year_text ?? ""}${change ? ` (${change})` : ""}`;
      },
    }] : []),
    ...(expected?.target ? [{
      head: "Expected next", width: 210,
      cell: (m: BriefingRangeMeasure) => {
        const e = bands.get(m.metric);
        return e?.expected
          ? <span title={e.expected.must_say.join(" · ")}>{e.expected.text}</span>
          : <span title={e?.why || "no band was stated for it"} style={{ color: "var(--t3)" }}>not predicted</span>;
      },
    }] : []),
    { head: "Status", cell: m => <StatusMark status={STATUS_LABEL[m.status]} />, width: 120 },
  ];
  return (
    <div className="aug-fs-sm" data-testid="range-measures" style={{ marginBottom: 14 }}>
      <div className="aug-label" style={{ marginBottom: 6 }}>
        Measured for {block.covers} · against {block.compared_with}
      </div>
      {block.edge_note && (
        <div data-testid="range-edge-note" style={{ color: "var(--t2)", marginBottom: 6 }}>{block.edge_note}</div>
      )}
      {block.lag_days > 1 && (
        <div style={{ color: "var(--t3)", marginBottom: 6 }}>
          {block.lag_source === "beyond_horizon"
            ? <>Read {block.lag_days} days behind today: {block.still_moving.join(", ") || "a table"}{" "}
                {block.still_moving.length > 1 ? "were" : "was"} still changing {block.lag_days - 1} days
                after a day ended, so recent figures may still move.</>
            : <>Read {block.lag_days} days behind today: newer days are still settling.</>}
        </div>
      )}
      {block.measured.length > 0 && (
        <Ledger name="measured-metrics" columns={columns} rows={block.measured} rowKey={m => m.metric}
          onOpen={open ? m => open({ measure: m, block, expected: expected?.target ? { target: expected.target, item: bands.get(m.metric) } : undefined }) : undefined}
          group={byLine ? m => m.line?.label ?? "Other" : undefined}
          selected={shown} empty="No metric was measured for this range." />
      )}
      {block.measured.length > 0 && expected?.target && (
        <div data-testid="range-expected-note" style={{ color: "var(--t3)", marginTop: 4 }}>
          Expected next is for {expected.target.label}: the band each metric&apos;s own earlier ranges put on it,
          checked on {expected.target.settles_on}, when that range has settled.
        </div>
      )}
      {block.measured.length > 0 && expected && !expected.target && expected.why && (
        <div data-testid="range-expected-note" style={{ color: "var(--t3)", marginTop: 4 }}>
          Nothing is predicted from this range: {expected.why}.
        </div>
      )}
      {block.unmeasured.length > 0 && (
        <ul style={{ margin: "8px 0 0", paddingLeft: 16, color: "var(--t3)" }}>
          {byReason(block.unmeasured).map(([reason, names]) => (
            <li key={reason}>Not measured: {names.join(", ")} — {reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Arc BR-4 — the recipe's own sections ─────────────────────────────────────────────────────

const RECIPE_JOB: Record<string, string> = {
  day: "The Day — for acting today", week: "The Week — for steering", month: "The Month — for review",
  year: "The Year — for strategy", custom: "A custom range — for exploring",
};

export function RangeSections({ block }: { block: BriefingRangeBlock }) {
  const moves = block.moves ?? [];
  const thin = block.thin ?? [];
  const why = block.why ?? [];
  const early = block.early;
  return (
    <div className="aug-fs-sm" data-testid="range-sections" style={{ display: "grid", gap: 12, marginBottom: 14 }}>
      {block.recipe && (
        <div className="aug-label" style={{ color: "var(--t3)" }}>{RECIPE_JOB[block.recipe] ?? ""}</div>
      )}
      {early && early.start && early.figures.length > 0 && (
        <div>
          <div className="aug-label" style={{ marginBottom: 4 }}>Still settling — early read</div>
          <div style={{ color: "var(--t2)" }}>
            {early.start === early.end ? early.start : `${early.start} to ${early.end}`}:{" "}
            {early.figures.map(f => `${f.name} ${f.value_text ?? ""}`).join(" · ")}
            <span style={{ color: "var(--t3)" }}> — early: these days are still changing, so no figure here is final.</span>
          </div>
        </div>
      )}
      {moves.length > 0 && (
        <div>
          <div className="aug-label" style={{ marginBottom: 4 }}>What moved</div>
          <Table>
            <TableHeader>
              <TableRow style={{ color: "var(--t3)", textAlign: "left" }}>
                <TableHead style={{ fontWeight: 500, padding: "2px 8px 2px 0" }}>Metric</TableHead>
                <TableHead style={{ fontWeight: 500, padding: "2px 8px" }}>Segment</TableHead>
                <TableHead style={{ fontWeight: 500, padding: "2px 8px" }}>This range</TableHead>
                <TableHead style={{ fontWeight: 500, padding: "2px 8px" }}>Comparison</TableHead>
                <TableHead style={{ fontWeight: 500, padding: "2px 0 2px 8px" }}>Change</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {moves.map(c => (
                <TableRow key={`${c.metric}:${c.dimension}:${c.group}`} style={{ borderTop: "1px solid var(--b1)" }}>
                  <TableCell style={{ padding: "4px 8px 4px 0", color: "var(--t1)" }}>{c.name}</TableCell>
                  <TableCell style={{ padding: "4px 8px" }}>{c.dimension}: {c.group}</TableCell>
                  <TableCell style={{ padding: "4px 8px" }}>{c.current_text ?? ""}</TableCell>
                  <TableCell style={{ padding: "4px 8px", color: "var(--t2)" }}>{c.previous_text ?? ""}</TableCell>
                  <TableCell style={{ padding: "4px 0 4px 8px", color: "var(--t2)" }}>{c.change_text ?? ""}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {thin.length > 0 && (
            <div style={{ color: "var(--t3)", marginTop: 4 }}>
              Too few to call: {thin.map(c => `${c.dimension} ${c.group} (${c.n} rows)`).join(", ")}.
            </div>
          )}
        </div>
      )}
      {why.length > 0 && (
        <div>
          <div className="aug-label" style={{ marginBottom: 4 }}>What we know about what moved</div>
          <ul style={{ margin: 0, paddingLeft: 16, color: "var(--t2)" }}>
            {why.map((w, i) => <li key={`${w.segment}:${i}`}><span style={{ color: "var(--t1)" }}>{w.segment}</span> — {w.finding}</li>)}
          </ul>
        </div>
      )}
      {block.recipe_error && (
        <div data-testid="range-recipe-error" style={{ color: "var(--t3)" }}>
          This range's own sections are missing: {block.recipe_error}.
        </div>
      )}
    </div>
  );
}
