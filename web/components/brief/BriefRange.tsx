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
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { StatTile, type StatDelta } from "@/components/brief/StatTile";
import type { BriefingRange, BriefingRangeBlock, BriefingRangeMeasure, RangePreset } from "@/lib/api";
import { formatPoints, formatVariance } from "@/lib/format";

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

export function RangeControl({ value, onChange, disabled }: {
  value: RangeChoice;
  onChange: (c: RangeChoice) => void;
  disabled?: boolean;
}) {
  const [custom, setCustom] = useState(value.preset === "custom");
  const [start, setStart] = useState(value.preset === "custom" ? value.start ?? "" : "");
  const [end, setEnd] = useState(value.preset === "custom" ? value.end ?? "" : "");
  const ready = !!start && !!end && start <= end;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" as const, minWidth: 0 }}>
      <div role="group" aria-label="Briefing range" className="aug-segmented">
        {SEGMENTS.map(s => {
          const on = !custom && value.preset === s.value;
          return (
            <Button key={s.value} variant="ghost" size="sm" className="aug-seg-item"
              aria-pressed={on} title={s.title} disabled={disabled}
              onClick={() => { setCustom(false); onChange({ preset: s.value } as RangeChoice); }}>
              {s.label}
            </Button>
          );
        })}
        <Button variant="ghost" size="sm" className="aug-seg-item" aria-pressed={custom}
          title="Any range, first and last day" disabled={disabled} onClick={() => setCustom(true)}>
          Custom
        </Button>
      </div>
      {custom && (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <input type="date" aria-label="First day" value={start} max={end || undefined}
            onChange={e => setStart(e.target.value)} className="aug-input aug-fs-sm" />
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>to</span>
          <input type="date" aria-label="Last day" value={end} min={start || undefined}
            onChange={e => setEnd(e.target.value)} className="aug-input aug-fs-sm" />
          <Button size="sm" variant="secondary" disabled={disabled || !ready}
            onClick={() => onChange({ preset: "custom", start, end })}>
            Show
          </Button>
        </span>
      )}
    </div>
  );
}

const STATUS_LABEL: Record<BriefingRangeMeasure["status"], string> = {
  final: "Final", provisional: "Provisional", to_date: "To date",
};

/** A share's change is in points; everything else is relative. */
function changeOf(m: BriefingRangeMeasure, against: "previous" | "last_year"): string {
  const other = m[against];
  if (m.current === null || other === null) return "";
  if (m.unit === "ratio 0..1") return formatPoints(other, m.current);
  return formatVariance(against === "previous" ? m.rel : m.rel_last_year, 0);
}

function deltaOf(m: BriefingRangeMeasure): StatDelta | null {
  const text = changeOf(m, "previous");
  if (!text || m.rel === null) return null;
  // Direction-neutral: whether a move is good depends on the metric (a falling return rate is),
  // and nothing declares that yet — colour would be a judgement the data does not carry.
  return { text, sign: Math.sign(m.rel), favorable: null };
}

/** The range's headline figures — its measured metrics, largest move first. */
export function RangeFigures({ block }: { block: BriefingRangeBlock }) {
  const top = [...block.measured]
    .sort((a, b) => Math.abs(b.rel ?? 0) - Math.abs(a.rel ?? 0))
    .slice(0, 4);
  if (top.length === 0) return null;
  return (
    <div data-brief-range-figures style={{ marginTop: 18 }}>
      <div className="aug-label" style={{ marginBottom: 8, color: "var(--t3)" }}>
        Measured for {block.covers}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(4, top.length)}, minmax(0, 1fr))`, gap: 12 }}>
        {top.map(m => (
          <StatTile key={m.metric} label={m.name} value={m.current_text ?? ""}
            delta={deltaOf(m)}
            caption={`${STATUS_LABEL[m.status]} · against ${m.previous_text ?? "no comparison"}`}
            title={m.time_source ?? undefined} />
        ))}
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

export function RangeMeasures({ block }: { block: BriefingRangeBlock }) {
  const hasYear = block.measured.some(m => m.last_year !== null) && !!block.last_year_label;
  return (
    <div className="aug-fs-sm" data-testid="range-measures" style={{ marginBottom: 14 }}>
      <div className="aug-label" style={{ marginBottom: 6 }}>
        Measured for {block.covers} · against {block.compared_with}
      </div>
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
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ color: "var(--t3)", textAlign: "left" }}>
              <th style={{ fontWeight: 500, padding: "2px 8px 2px 0" }}>Metric</th>
              <th style={{ fontWeight: 500, padding: "2px 8px" }}>This range</th>
              <th style={{ fontWeight: 500, padding: "2px 8px" }}>Comparison</th>
              <th style={{ fontWeight: 500, padding: "2px 8px" }}>Change</th>
              {hasYear && <th style={{ fontWeight: 500, padding: "2px 8px" }}>A year earlier</th>}
              <th style={{ fontWeight: 500, padding: "2px 0 2px 8px" }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {block.measured.map(m => (
              <tr key={m.metric} style={{ borderTop: "1px solid var(--b1)" }}>
                <td style={{ padding: "4px 8px 4px 0", color: "var(--t1)" }} title={m.time_source ?? undefined}>
                  {m.name}
                </td>
                <td style={{ padding: "4px 8px" }}>{m.current_text ?? ""}</td>
                <td style={{ padding: "4px 8px", color: "var(--t2)" }}>{m.previous_text ?? ""}</td>
                <td style={{ padding: "4px 8px", color: "var(--t2)" }}>
                  {m.current_partial || m.previous_partial
                    ? `no change stated: data covers only ${m.current_partial ?? m.previous_partial}`
                    : changeOf(m, "previous") || "no comparison rows"}
                </td>
                {hasYear && (
                  <td style={{ padding: "4px 8px", color: "var(--t2)" }}>
                    {m.last_year_text ?? ""}{m.last_year !== null ? ` (${changeOf(m, "last_year")})` : ""}
                  </td>
                )}
                <td style={{ padding: "4px 0 4px 8px", color: m.status === "final" ? "var(--t2)" : "var(--amb4)" }}>
                  {STATUS_LABEL[m.status]}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
