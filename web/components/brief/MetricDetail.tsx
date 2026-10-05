"use client";

/**
 * What a measured figure opens to (ROADMAP §6 item 43; asked 2026-10-05: each metric clickable,
 * to learn more about it).
 *
 * A metric's row on the Briefing or the Cockpit opens a drawer beside the page: the figure with
 * its comparisons, the metric over the range and the ranges before it (one warehouse statement,
 * no model call), the segments that moved inside it when the range's Briefing read any, and how
 * the metric is defined and dated. The drawer only reads. "Ask why it moved" hands the question
 * to the Agent as a deep analysis — a run the reader starts, never one the drawer starts.
 */
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import { Sparkline } from "@/components/brief/Sparkline";
import { Beside, Box, Part, Title, useEscape } from "@/components/record/beside";
import { Absent, Gate, Ledger, StatusMark, useLoad, type LedgerColumn } from "@/components/record/kit";
import { Button } from "@/components/ui/button";
import {
  readMetricTrend,
  type BriefingRange, type BriefingRangeBlock, type BriefingRangeMeasure, type MetricTrend, type MetricTrendPoint,
} from "@/lib/api";
import { countNoun, formatPoints, formatVariance } from "@/lib/format";

export interface MetricOpened { measure: BriefingRangeMeasure; block: BriefingRangeBlock }
type OpenMetric = (what: MetricOpened) => void;

const Opener = createContext<{ open: OpenMetric; shown: MetricOpened | null } | null>(null);

/** The function that opens a metric beside the page, or null where no page offers the drawer. */
export function useOpenMetric(): OpenMetric | null {
  return useContext(Opener)?.open ?? null;
}

/** The metric open beside the page when it was opened from this range's table, else undefined. */
export function useShownMetric(rangeKey: string): string | undefined {
  const shown = useContext(Opener)?.shown;
  return shown && shown.block.key === rangeKey ? shown.measure.metric : undefined;
}

export const STATUS_LABEL: Record<BriefingRangeMeasure["status"], string> = {
  final: "Final", provisional: "Provisional", to_date: "To date",
};

/** A share's change is in points; everything else is relative. */
export function changeOf(m: BriefingRangeMeasure, against: "previous" | "last_year"): string {
  const other = m[against];
  if (m.current === null || other === null) return "";
  if (m.unit === "ratio 0..1") return formatPoints(other, m.current);
  return formatVariance(against === "previous" ? m.rel : m.rel_last_year, 0);
}

/** The range a block was measured for, as a request names it. */
export function rangeOf(block: BriefingRangeBlock): BriefingRange {
  return block.preset === "custom" ? { preset: "custom", start: block.start, end: block.last_day } : { preset: block.preset };
}

/**
 * Gives a page the metric drawer. Every measured table under it gets rows that open; the drawer
 * belongs to the page it was opened from, so when `pageKey` changes it is gone.
 */
export function MetricDetailHost({ connectionId, schema, workspaceId, pageKey, top = 0, onAskWhy, children }: {
  connectionId: string;
  schema?: string;
  workspaceId?: string;
  pageKey: string;
  top?: number;
  /** Hand a question to the Agent. Absent, the drawer offers no such button. */
  onAskWhy?: (question: string) => void;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState<{ what: MetricOpened; on: string } | null>(null);
  const shown = open && open.on === pageKey ? open.what : null;
  const openMetric = useCallback<OpenMetric>(what => setOpen({ what, on: pageKey }), [pageKey]);
  const close = useCallback(() => setOpen(null), []);
  useEscape(!!shown, close);
  const offered = useMemo(() => ({ open: openMetric, shown }), [openMetric, shown]);
  return (
    <Opener.Provider value={offered}>
      <div style={{ position: "relative", flex: 1, display: "flex", flexDirection: "column", minHeight: 0, minWidth: 0 }}>
        {children}
        {shown && (
          <MetricDetail what={shown} connectionId={connectionId} schema={schema} workspaceId={workspaceId}
            top={top} onClose={close}
            onAskWhy={onAskWhy ? q => { close(); onAskWhy(q); } : undefined} />
        )}
      </div>
    </Opener.Provider>
  );
}

/** The question "Ask why it moved" asks, in the page's own words for the range. */
export function whyQuestion(m: BriefingRangeMeasure, block: BriefingRangeBlock): string {
  const change = changeOf(m, "previous");
  const moved = change ? `change by ${change}` : "come out as it did";
  return `Why did ${m.name} ${moved} for ${block.covers}, against ${block.compared_with}?`;
}

function MetricDetail({ what, connectionId, schema, workspaceId, top, onClose, onAskWhy }: {
  what: MetricOpened; connectionId: string; schema?: string; workspaceId?: string; top: number;
  onClose: () => void; onAskWhy?: (question: string) => void;
}) {
  const { measure: m, block } = what;
  const load = useLoad(() => readMetricTrend(connectionId, m.metric, rangeOf(block), schema, workspaceId),
    [connectionId, m.metric, block.key, schema, workspaceId]);
  const change = changeOf(m, "previous");
  const yearChange = m.last_year !== null ? changeOf(m, "last_year") : "";
  const moves = (block.moves ?? []).filter(c => c.metric === m.metric);
  const partial = m.current_partial || m.previous_partial;
  return (
    <Beside kind="Metric" top={top} onClose={onClose} testId="metric-detail" focusKey={`${block.key}:${m.metric}`}
      foot={<>
        {onAskWhy && (
          <Button size="xs" variant="outline" style={{ width: "100%" }} onClick={() => onAskWhy(whyQuestion(m, block))}>
            Ask why it moved
          </Button>
        )}
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
          Esc closes it.{onAskWhy ? " Asking starts a deep analysis by the Agent." : ""}
        </span>
      </>}>
      <Title marks={<StatusMark status={STATUS_LABEL[m.status]} />}>{m.name}</Title>

      <Part label={`Measured for ${block.covers}`}>
        <Box foot={partial
          ? `No change stated: its data covers only ${partial}.`
          : change ? `${change} against ${block.compared_with}` : `No comparison rows for ${block.compared_with}.`}>
          {m.current_text ?? "no figure"}
        </Box>
        {m.previous_text && <Box foot={`The comparison: ${block.compared_with}`}>{m.previous_text}</Box>}
        {m.last_year !== null && m.last_year_text && (
          <Box foot={`${block.last_year_label ?? "A year earlier"}${yearChange ? ` · ${yearChange} since` : ""}`}>{m.last_year_text}</Box>
        )}
      </Part>

      <Part label="How it ran">
        <Gate load={load} what="this metric's earlier ranges">
          {t => <Trend trend={t} />}
        </Gate>
      </Part>

      {moves.length > 0 && (
        <Part label="What moved inside it">
          {moves.map(c => (
            <Box key={`${c.dimension}:${c.group}`}
              foot={`${c.current_text ?? ""} against ${c.previous_text ?? "no comparison"}${c.change_text ? ` · ${c.change_text}` : ""}`}>
              {c.dimension}: {c.group}
            </Box>
          ))}
        </Part>
      )}

      {load.data && <Definition trend={load.data} />}
    </Beside>
  );
}

function Trend({ trend }: { trend: MetricTrend }) {
  if (trend.why) return <Absent>Its earlier ranges could not be read: {trend.why}.</Absent>;
  const read = trend.series.filter(p => p.value !== null);
  if (read.length === 0) return <Absent>No range before this one has rows.</Absent>;
  const columns: LedgerColumn<MetricTrendPoint>[] = [
    { head: "Range", cell: p => (p.current ? `${p.label} (this range)` : p.label), width: 210 },
    { head: "Value", cell: p => p.value_text ?? "no rows", num: true },
  ];
  const short = trend.series.filter(p => p.partial);
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {read.length > 1 && (
        <div className="aug-beside-box" aria-hidden="true">
          <Sparkline values={read.map(p => p.value as number)} width={360} height={44} showDot={false} />
        </div>
      )}
      <Ledger name={`trend-${trend.metric}`} columns={columns} rows={trend.series} rowKey={p => p.start}
        empty="No earlier range was read." />
      <Absent>
        {countNoun(trend.series.length, "range")}, oldest first, each read at the same age as this one.
        {short.length > 0 ? ` ${countNoun(short.length, "range")} had rows for only part of its days: ${short.map(p => p.label).join("; ")}.` : ""}
      </Absent>
    </div>
  );
}

const KIND_WORDS: Record<string, string> = {
  flow: "counted on the day it happens",
  stock: "a level, read as it stands at the end of the range",
  cohort: "a share of the rows that began in the range, counted once their outcome has arrived",
};

function Definition({ trend: t }: { trend: MetricTrend }) {
  const from = t.tables.length ? `From ${t.tables.join(", ")}` : "";
  const only = t.filters.length ? `only where ${t.filters.join(" and ")}` : "";
  return (
    <Part label="How it is measured">
      <Box foot={[from, only].filter(Boolean).join(" · ") || undefined}>
        <code className="aug-fs-sm aug-mono" style={{ wordBreak: "break-word" }}>{t.definition}</code>
      </Box>
      {(t.time_kind || t.time_source) && (
        <Box foot={t.time_source ? `Its dates were ${t.time_source}${t.confirmed ? "" : " — not yet confirmed by a person"}.` : undefined}>
          {t.time_kind ? `${t.time_kind[0].toUpperCase()}${t.time_kind.slice(1)}: ${KIND_WORDS[t.time_kind] ?? ""}` : "Its dates"}
        </Box>
      )}
      {t.caveats && <Box foot="Caveat on the definition">{t.caveats}</Box>}
      <Absent>
        Version {t.version}{t.approved_by ? `, approved by ${t.approved_by}` : ""}{t.owner ? ` · owned by ${t.owner}` : ""}. Its definition is edited in the Semantic Layer.
      </Absent>
    </Part>
  );
}
