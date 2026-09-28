"use client";

/**
 * CockpitTile — how a cockpit draws one card (Arc CT; the user's mock, 2026-09-28: "make the
 * cockpit look like the mockup").
 *
 * The first cut drew every card with `PinnedCardBody`, the Briefing's own card, unchanged. That
 * kept one rendering of a card, and it is why the cockpit looked like a pinned card and not like
 * the mock: a figure floating in a fixed-height box, the unit dropped, what stands behind the
 * figure unsaid, and three action buttons where the mock says where the figure came from.
 *
 * The law is unchanged — the spec arranges, the card store measures. Nothing here decides what a
 * card measures: the figure is the card's own run, the unit is its metric's, and the scale the
 * unit states is read by the Briefing's own reader (`metricFormat.formatMetric`, fed the
 * `stated_range` the server read). What this file adds is the face:
 *
 *   figure   the figure at its unit's scale; how it moved against the window its range is
 *            compared with (the card's own SQL cut to that window, `previous`), said as not at
 *            equal age before the range is final; its limit, and whether it is over it.
 *   trend    a series drawn as a line, its limit drawn on it, its newest point labelled.
 *   rows     a chart or a table, as the card's chart editor keeps it.
 *
 * Every tile's foot says where its figure comes from. Its doors — refresh, an alert, the
 * evidence, taking it off — show when the tile is pointed at or focused.
 */
import { useMemo, useState, type ReactNode } from "react";

import { CardAlertForm, usePersistViz, type CardState } from "@/components/brief/PinnedCardBody";
import { seriesTrend, type SeriesTrend } from "@/components/brief/Sparkline";
import { deltaInfo, formatMetric } from "@/components/brief/metricFormat";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { type ChartCustom } from "@/components/Chart";
import { type VizConfig } from "@/components/charts/vizConfig";
import { VegaChart } from "@/components/charts/vega/VegaChart";
import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import type { CardRunPrevious, CockpitCard, StatedRange } from "@/lib/api";
import { cardValue } from "@/lib/cockpit/hostStatus";
import type { CardStatus } from "@/lib/cockpit/hostState";
import { fmtDate, formatMetricValue } from "@/lib/format";

export type TileShape = "figure" | "trend" | "rows";

/** How a card is drawn, from its run. A failed run is a figure that says it failed. */
export function tileShape(cs: CardState): TileShape {
  const { run, failed } = cs;
  if (failed || !run || run.error) return "figure";
  if (seriesTrend(run.columns, run.rows)) return "trend";
  // One cell is one figure, even an empty one: a total over a period with no rows is NULL, and
  // that is "no figure for the period", never a one-cell table reading "NULL".
  const oneCell = (run.columns?.length ?? 0) === 1 && (run.rows?.length ?? 0) <= 1;
  if (cardValue(cs) !== null || oneCell) return "figure";
  return (run.columns?.length ?? 0) > 0 && (run.rows?.length ?? 0) > 0 ? "rows" : "figure";
}

/** A tile that needs the room of two columns. */
export const WIDE: Record<TileShape, boolean> = { figure: false, trend: true, rows: true };

export interface TileDoors {
  onRemove: (id: string) => void;
  onRefresh: (id: string) => void;
  onOpenSource?: (iid: string) => void;
  onEvidence?: (iid: string) => void;
}

/** What stands behind a card's figure, in the words the Briefing uses for each record. */
const MADE_FROM: Record<string, { icon: IconName; words: string }> = {
  metric: { icon: "shield", words: "Approved metric" },
  trusted_query: { icon: "db", words: "Trusted query" },
  finding: { icon: "idea", words: "Finding" },
};

function sourceOf(card: CockpitCard): { icon: IconName; words: string } {
  const made = card.made_from ?? (card.provenance.metric ? "metric" : card.provenance.insight_id ? "finding" : "");
  return MADE_FROM[made] ?? { icon: "sql", words: "Query" };
}

interface Limits { warning?: number | null; critical?: number | null; direction?: string; monitor_id?: string | null }

function limitsOf(card: CockpitCard): { values: number[]; below: boolean; watched: boolean } {
  const t = (card.thresholds ?? {}) as Limits;
  const values = [t.warning, t.critical].filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  return { values, below: t.direction === "below", watched: !!t.monitor_id };
}

/** One figure, at the scale its unit states. A figure its unit says cannot be is still shown —
 *  a cockpit hides nothing — plainly, and said to be outside its range. */
export function figureText(v: number, card: CockpitCard, sym: string): { text: string; outside: boolean } {
  const range = card.stated_range ?? undefined;
  const f = formatMetric(v, card.unit ?? "", sym, card.title, range);
  if (f.ok) return { text: f.display, outside: false };
  const bounded = !!range && ["ratio01", "pct100", "band"].includes(range.kind);
  return { text: formatMetricValue(v), outside: bounded && v !== 0 };
}

/** How the figure moved against what it is compared with: "0.4 pts lower than June". */
export function changeWords(cur: number, prev: number, card: CockpitCard, against: string): { text: string; sign: number } | null {
  const d = deltaInfo([prev, cur], card.unit ?? "", card.title, (card.stated_range ?? undefined) as StatedRange | undefined);
  if (!d) return null;
  if (d.sign === 0) return { text: `the same as ${against}`, sign: 0 };
  // A relative change has no base to stand on when what it is compared with is zero.
  if (!d.text.endsWith("pts") && !d.text.endsWith("×") && prev === 0) return null;
  const size = d.text.replace(/^[+-]/, "").replace(/pts$/, " pts");
  // A move too small to show at the precision it is written in is no move to a reader: "0.0 pts
  // lower" (seen on theLook's gross margin, 2026-09-28) says a direction the figure cannot carry.
  if (parseFloat(size) === 0) return { text: `the same as ${against}`, sign: 0 };
  return { text: `${size} ${d.sign > 0 ? "higher" : "lower"} than ${against}`, sign: d.sign };
}

/** Green or red only where the card says which way is bad — its limit's side. Otherwise the
 *  move is said in the reader's own colour: a rise is not good news for every figure. */
function moveColour(sign: number, card: CockpitCard): string {
  const { values, below } = limitsOf(card);
  if (!values.length || sign === 0) return "var(--t2)";
  const towardTheLimit = below ? sign < 0 : sign > 0;
  return towardTheLimit ? "var(--red4)" : "var(--grn4)";
}

function Frame({ testid, shape, over, dashed, children, doors }: {
  testid: string; shape?: TileShape; over?: boolean; dashed?: boolean; children: ReactNode; doors?: ReactNode;
}) {
  return (
    <div className="group" data-testid={testid} data-shape={shape} style={{
      position: "relative", height: "100%", boxSizing: "border-box", display: "flex", flexDirection: "column",
      gap: 6, padding: "14px 16px 12px", background: "var(--bg-2)", borderRadius: "var(--r3)",
      border: `1px ${dashed ? "dashed" : "solid"} ${over ? "color-mix(in srgb, var(--red4) 55%, var(--b1))" : "var(--b1)"}`,
    }}>
      {children}
      {doors}
    </div>
  );
}

function Title({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 10, minWidth: 0, paddingRight: 64 }}>
      <div className="aug-fs-ui" title={title} style={{
        flex: 1, minWidth: 0, color: "var(--t2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
      }}>{title}</div>
      {right}
    </div>
  );
}

function Foot({ icon, children, aside }: { icon: IconName; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="aug-fs-sm" style={{ marginTop: "auto", paddingTop: 4, display: "flex", alignItems: "center", gap: 6, color: "var(--t3)", minWidth: 0 }}>
      <Icon name={icon} size={13} />
      <span style={{ minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{children}</span>
      {aside && <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 6 }}>{aside}</span>}
    </div>
  );
}

/** The card's doors, shown when the tile is pointed at or focused. */
function Doors({ card, doors, onAlert }: { card: CockpitCard; doors: TileDoors; onAlert?: () => void }) {
  const iid = card.provenance.insight_id;
  return (
    <div className="opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
      data-testid="cockpit-tile-doors"
      style={{ position: "absolute", top: 8, right: 8, display: "flex", gap: 2, background: "var(--bg-2)", borderRadius: "var(--r2)" }}>
      {iid && doors.onEvidence && (
        <Button variant="ghost" size="icon-xs" aria-label="Evidence" title="See the evidence behind this finding"
          onClick={() => doors.onEvidence?.(iid)}><Icon name="shield" /></Button>
      )}
      {iid && doors.onOpenSource && (
        <Button variant="ghost" size="icon-xs" aria-label="Why" title="Open the finding that explains this figure's move"
          onClick={() => doors.onOpenSource?.(iid)}><Icon name="external" /></Button>
      )}
      {onAlert && (
        <Button variant="ghost" size="icon-xs" aria-label="Set an alert" title="Alert me when this figure crosses a threshold (schedules a monitor)"
          onClick={onAlert}><Icon name="bell" /></Button>
      )}
      <Button variant="ghost" size="icon-xs" aria-label="Refresh" title="Run this card again"
        onClick={() => doors.onRefresh(card.id)}><Icon name="refresh" /></Button>
      <Button variant="ghost" size="icon-xs" aria-label="Take off this cockpit" title="Take it off this cockpit. The card is kept."
        onClick={() => doors.onRemove(card.id)}><Icon name="close" /></Button>
    </div>
  );
}

function Moved({ value, previous, card }: { value: number; previous: CardRunPrevious; card: CockpitCard }) {
  if (previous.value === null) {
    return (
      <div className="aug-fs-sm" data-testid="tile-change" title={previous.why} style={{ color: "var(--t3)" }}>
        No figure for {previous.word} to compare with
      </div>
    );
  }
  const moved = changeWords(value, previous.value, card, previous.word);
  if (!moved) return null;
  return (
    <div className="aug-fs-sm" data-testid="tile-change" title={`Against ${previous.covers}`}
      style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap", color: moveColour(moved.sign, card) }}>
      {moved.sign !== 0 && <Icon name={moved.sign > 0 ? "rises" : "falls"} size={13} />}
      <span>{moved.text}</span>
      {!previous.equal_age && (
        <span data-testid="tile-not-equal-age" style={{ color: "var(--amb4)" }}
          title="The range has not settled and what it is compared with has, so part of the difference is age, not a move.">
          · not at equal age
        </span>
      )}
    </div>
  );
}

function FigureTile({ cs, status, sym, doors }: { cs: CardState & { card: CockpitCard }; status: CardStatus; sym: string; doors: TileDoors }) {
  const { card, run, failed } = cs;
  const errored = failed || !!run?.error;
  const value = cardValue(cs);
  const ranged = !!run?.scoped && !run.scoped.standing;
  const { values: limits, below, watched } = limitsOf(card);
  const [alertOpen, setAlertOpen] = useState(false);
  const [alerting, setAlerting] = useState(watched);
  const source = sourceOf(card);
  const over = status === "over";
  const shown = value !== null ? figureText(value, card, sym) : null;
  // Standing: what it moved by since the card last ran, if it did.
  const standingPrev = !ranged ? (run?.refresh?.prev_value ?? null) : null;
  const caveats = run?.caveats ?? [];

  return (
    <Frame testid="cockpit-tile" shape="figure" over={over}
      doors={<Doors card={card} doors={doors} onAlert={value !== null && !alerting ? () => setAlertOpen(o => !o) : undefined} />}>
      <Title title={card.title} />
      {errored ? (
        <div className="aug-fs-ui" style={{ color: "var(--amb4)" }}>Could not be read</div>
      ) : shown ? (
        <div className="aug-fs-display" data-testid="tile-figure" title={shown.outside ? `Outside what its unit states (${card.unit})` : undefined}
          style={{ fontWeight: 600, lineHeight: 1.15, color: over ? "var(--red4)" : "var(--t1)", fontVariantNumeric: "tabular-nums" }}>
          {shown.text}
        </div>
      ) : (
        <div className="aug-fs-ui" data-testid="tile-no-figure" style={{ color: "var(--t3)" }}>
          {!run ? "…" : ranged ? `No figure for ${run.scoped?.covers}` : "No figure"}
        </div>
      )}
      {shown?.outside && (
        <div className="aug-fs-sm" style={{ color: "var(--amb4)" }}>Outside what its unit states</div>
      )}
      {value !== null && ranged && run?.previous && <Moved value={value} previous={run.previous} card={card} />}
      {value !== null && !ranged && standingPrev !== null && standingPrev !== value && (() => {
        const moved = changeWords(value, standingPrev, card, "its last run");
        return moved && (
          <div className="aug-fs-sm" data-testid="tile-change" style={{ display: "flex", alignItems: "center", gap: 4, color: moveColour(moved.sign, card) }}>
            <Icon name={moved.sign > 0 ? "rises" : "falls"} size={13} />{moved.text}
          </div>
        );
      })()}
      {run?.scoped?.standing && (
        <div className="aug-fs-sm" data-testid="card-scoped" title={run.scoped.why} style={{ color: "var(--amb4)" }}>
          All history, not {run.scoped.covers} — {run.scoped.why}
        </div>
      )}
      {limits.length > 0 && (
        <div className="aug-fs-sm" data-testid="card-limit" style={{ color: over ? "var(--red4)" : "var(--t3)" }}
          title={alerting ? "A monitor watches this limit" : "This card carries a limit. Nothing is scheduled to watch it."}>
          {over ? "Past its limit" : "Limit"}: {below ? "at or below" : "at or above"} {limits.map(v => figureText(v, card, sym).text).join(", ")}
          {alerting ? " · alerting" : ""}
        </div>
      )}
      {alertOpen && !alerting && (
        <CardAlertForm card={card} direction={below ? "below" : "above"}
          onSet={() => { setAlerting(true); setAlertOpen(false); }} />
      )}
      <Foot icon={source.icon} aside={caveats.length > 0 && (
        <span title={caveats.join("; ")} style={{ color: "var(--amb4)" }}>
          {caveats.length} guard caveat{caveats.length > 1 ? "s" : ""}
        </span>
      )}>
        {source.words}
      </Foot>
    </Frame>
  );
}

/** A Vega-Lite spec for a series: the line, its newest point labelled, and the card's limit
 *  drawn across it. Colours come from the chart theme (`charts/vega/config.ts`), never here. */
export function trendSpec(trend: SeriesTrend, card: CockpitCard, sym: string): Record<string, unknown> {
  const n = trend.values.length;
  const values = trend.dates.map((d, i) => ({ x: fmtDate(d, trend.gran), y: trend.values[i], i }));
  const last = figureText(trend.values[n - 1], card, sym).text;
  const range = card.stated_range?.kind;
  const big = Math.max(...trend.values.map(Math.abs)) >= 1000;
  const q = (s: string) => `'${s.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;
  const money = formatMetric(1234, card.unit ?? "", sym, card.title, card.stated_range ?? undefined).display.startsWith(sym) && !!sym;
  // Three significant figures: a line that moves within a narrow band (2.78M to 2.92M) needs
  // them, or its ticks read "2.9M, 2.9M, 2.8M". "~" trims the zeros a round tick does not need.
  const digits = big ? ".3~s" : ".3~r";
  const axis: Record<string, unknown> = range === "ratio01" ? { format: ".1~%" }
    : range === "pct100" ? { labelExpr: "format(datum.value, '.1~f') + '%'" }
    : money ? { labelExpr: `${q(sym)} + format(datum.value, '${digits}')` }
    : { format: digits };
  const x = { field: "x", type: "ordinal", sort: null, axis: { title: null, labelAngle: 0, labelOverlap: "parity", grid: false, ticks: false } };
  const y = { field: "y", type: "quantitative", scale: { zero: false }, axis: { title: null, tickCount: 4, ...axis } };
  const isLast = { filter: `datum.i === ${n - 1}` };
  const { values: limits } = limitsOf(card);
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    background: null,
    layer: [
      { data: { values }, mark: { type: "line" }, encoding: { x, y } },
      { data: { values }, transform: [isLast], mark: { type: "point" }, encoding: { x, y } },
      { data: { values }, transform: [isLast], mark: { type: "text", dy: 14, align: "right" }, encoding: { x, y, text: { value: last } } },
      ...limits.flatMap(limit => [
        { data: { values: [{ y: limit }] }, mark: { type: "rule" }, encoding: { y: { field: "y", type: "quantitative" } } },
        { data: { values: [{ y: limit }] }, mark: { type: "text", align: "left", dx: 4, dy: -7, x: 0 },
          encoding: { y: { field: "y", type: "quantitative" }, text: { value: "Limit" } } },
      ]),
    ],
  };
}

function TrendTile({ cs, trend, status, sym, doors }: { cs: CardState & { card: CockpitCard }; trend: SeriesTrend; status: CardStatus; sym: string; doors: TileDoors }) {
  const { card } = cs;
  const source = sourceOf(card);
  const spec = useMemo(() => trendSpec(trend, card, sym), [trend, card, sym]);
  const n = trend.values.length;
  const newest = `${fmtDate(trend.dates[n - 1], trend.gran)} · ${figureText(trend.values[n - 1], card, sym).text}`;
  return (
    <Frame testid="cockpit-tile" shape="trend" over={status === "over"} doors={<Doors card={card} doors={doors} />}>
      <Title title={card.title} right={
        <span className="aug-fs-sm" data-testid="tile-newest" style={{ color: "var(--t1)", fontWeight: 500, whiteSpace: "nowrap" }}>{newest}</span>
      } />
      <div style={{ flex: 1, minHeight: 0 }}>
        <VegaChart spec={spec} tier={2} height={170} />
      </div>
      <Foot icon={source.icon}>{source.words}, by {trend.gran}</Foot>
    </Frame>
  );
}

function RowsTile({ cs, doors }: { cs: CardState & { card: CockpitCard }; doors: TileDoors }) {
  const { card, run } = cs;
  const persistViz = usePersistViz(card);
  const source = sourceOf(card);
  const render = (card.render || {}) as {
    chartType?: string; chartConfig?: Record<string, unknown>; custom?: ChartCustom; showDataLabels?: boolean; viz?: VizConfig;
  };
  return (
    <Frame testid="cockpit-tile" shape="rows" doors={<Doors card={card} doors={doors} />}>
      <Title title={card.title} />
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        {run && (
          <ResultChartCard columns={run.columns} rows={run.rows as unknown[][]}
            chartType={render.chartType ?? null} chartConfig={render.chartConfig ?? null} custom={render.custom ?? null}
            defaultShowLabels={render.showDataLabels} fillHeight={200} config={render.viz ?? null} onConfigChange={persistViz} />
        )}
      </div>
      <Foot icon={source.icon}>{source.words}{run?.scoped && !run.scoped.standing ? `, for ${run.scoped.covers}` : ""}</Foot>
    </Frame>
  );
}

export function CockpitTile({ cs, status, sym, doors }: {
  cs: CardState & { card: CockpitCard }; status: CardStatus; sym: string; doors: TileDoors;
}) {
  const shape = tileShape(cs);
  const trend = shape === "trend" && cs.run ? seriesTrend(cs.run.columns, cs.run.rows) : null;
  if (trend) return <TrendTile cs={cs} trend={trend} status={status} sym={sym} doors={doors} />;
  if (shape === "rows") return <RowsTile cs={cs} doors={doors} />;
  return <FigureTile cs={cs} status={status} sym={sym} doors={doors} />;
}

/** A card the reader may not see, in its place: said, never an empty box. */
export function WithheldTile() {
  return (
    <Frame testid="cockpit-card-said">
      <div className="aug-fs-ui" style={{ color: "var(--t2)" }}>Withheld</div>
      <div className="aug-fs-h1" style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600, color: "var(--t1)" }}>
        <Icon name="eyeoff" size={18} /> Not shown
      </div>
      <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>You may not see this card.</div>
      <Foot icon="info">It is here, and it is not empty</Foot>
    </Frame>
  );
}

/** A placed card the reader does not have, or one that failed to draw. */
export function SaidTile({ what, children }: { what: string; children: ReactNode }) {
  return (
    <Frame testid="cockpit-card-said" dashed>
      <div className="aug-fs-ui" style={{ color: "var(--t1)", fontWeight: 500 }}>{what}</div>
      <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>{children}</div>
    </Frame>
  );
}
