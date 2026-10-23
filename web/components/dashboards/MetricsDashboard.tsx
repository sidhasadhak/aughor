"use client";

/**
 * The dashboard a person opens on (ROADMAP §6 item 43; asked 2026-10-05): the connection's approved
 * metrics, measured for a period — this range, its comparison, the change, a year earlier and
 * whether each figure has settled. It is the Briefing's own measured table, read without writing
 * a Briefing: no narrative, no model call. A metric's name opens it beside the page.
 *
 * It belongs to the connection, not to the person, so it is not in "Your dashboards" and cannot be
 * arranged or retired. A person's own dashboards sit beside it, as before.
 */
import type { RangeChoice } from "@/components/brief/BriefRange";
import { Chip, MUTED } from "@/components/clarity/kit";
import { MetricsFigures } from "@/components/dashboards/MetricsFigures";
import { PeriodPicker, choiceName } from "@/components/dashboards/PeriodPicker";
import { Absent, Gate, useLoad } from "@/components/record/kit";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/ui/states";
import { measureRange, type BriefingRange, type BriefingRangeBlock, type DashboardRange } from "@/lib/api";
import { periodShort } from "@/lib/dashboards/figures";
import { formatDateTime, relTime } from "@/lib/format";

/** The strip's id for it. No dashboard a person keeps can carry it. */
export const METRICS_DASHBOARD = "::metrics";

/** The period as the picker says it: its words, and whether every figure in it has settled. */
function showing(block: BriefingRangeBlock): DashboardRange {
  const statuses = new Set(block.measured.map(m => m.status));
  const status = block.under_way || statuses.has("to_date") ? "to_date"
    : statuses.has("provisional") ? "provisional" : "final";
  return {
    status, preset: block.preset, start: block.start, last_day: block.last_day, covers: block.covers,
    as_of: block.as_of, lag_days: block.lag_days, still_moving: block.still_moving,
  };
}

export function MetricsDashboard({ connectionId, schema, rangesOn, value, onChange }: {
  connectionId: string;
  schema?: string;
  /** Whether this install reads a period at all (`briefing.ranges`); null while that is unknown. */
  rangesOn: boolean | null;
  value: RangeChoice;
  onChange: (c: RangeChoice) => void;
}) {
  const range: BriefingRange | null = value.preset === "standing" ? null : value;
  const rangeKey = JSON.stringify(range);
  const load = useLoad(
    () => (rangesOn && range ? measureRange(connectionId, range, schema) : Promise.resolve(null)),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
    [connectionId, schema, rangeKey, rangesOn]);
  // A new period is being read while the one before it is still on screen: said once, under the
  // picker (the user, 2026-10-08: one indicator), and the table it is about to replace is dimmed,
  // so nobody reads the old figures as the new period's. The first read has no table yet; the
  // gate below says it is loading, in the same place.
  const reading = load.loading && !!range && rangesOn === true;

  if (rangesOn === false) {
    return (
      <div data-testid="metrics-dashboard">
        <Absent>A metric is measured for a period, and periods are off on this install — they need the Briefing ranges flag.</Absent>
      </div>
    );
  }
  const block = !reading && load.data ? load.data.period : null;
  return (
    <div data-testid="metrics-dashboard">
      {/* The bar (the mockup's): the period, what it is against, how far behind the data is read, when it was measured. */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
        <PeriodPicker value={value} onChange={onChange} reading={reading}
          showing={load.data && !reading ? showing(load.data.period) : null} />
        {block && (
          <span data-testid="metrics-period" style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <Chip title={`Measured for ${block.covers}`}>{periodShort(block.start, block.end, block.period) || block.covers}</Chip>
            <Chip title={`Against ${block.compared_with}`}>
              {`vs ${periodShort(block.previous_start, block.previous_end, block.period) || block.compared_with}`}
            </Chip>
            {block.lag_days > 1 && (
              <Chip tone="amber" testId="metrics-lag" title={block.lag_source === "beyond_horizon"
                ? `${block.still_moving.join(", ") || "A table"} ${block.still_moving.length > 1 ? "were" : "was"} still changing ${block.lag_days - 1} days after a day ended, so recent figures may still move`
                : "Newer days are still settling"}>
                {`data ${block.lag_days} days behind`}
              </Chip>
            )}
            <span className="aug-fs-sm" data-testid="metrics-measured-at" style={MUTED} title={formatDateTime(load.data!.measured_at)}>
              {load.data!.from_briefing ? "as the Briefing measured it" : "measured"}{" "}
              {!load.data!.measured_at ? "" : Date.now() - Date.parse(load.data!.measured_at) < 60_000 ? "just now"
                : `${relTime(load.data!.measured_at)} ago`}
            </span>
          </span>
        )}
      </div>
      {block?.edge_note && (
        <div className="aug-fs-sm" data-testid="metrics-edge-note" style={{ color: "var(--t2)", margin: "-6px 0 12px" }}>{block.edge_note}</div>
      )}
      {reading && load.data !== null && (
        <Loading what={`the metrics for ${choiceName(value)}`} style={{ padding: "12px 0" }} />
      )}
      {!range ? (
        <Absent>“As written” is for cards. A metric is measured for a period — pick one above.</Absent>
      ) : rangesOn === null ? null : (
        <div data-testid="metrics-body" aria-busy={reading || undefined}
          style={{ opacity: reading ? 0.45 : 1, transition: "opacity 120ms ease-out", pointerEvents: reading ? "none" : undefined }}>
          <Gate load={load} what={`the metrics for ${choiceName(value)}`}>
            {d => d?.period.unreachable ? (
              // Said of the data, never as a metric waiting on a person (LuxExperience, 2026-10-23: a Postgres
              // that was down showed as "1 approved metric can't be measured · Set their dates", and the user
              // approved a metric to clear it).
              <div data-testid="metrics-unreachable" style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                <Absent>
                  {`The data could not be reached, so nothing was measured — ${d.period.unreachable}. `}
                  No metric needs anything from you; the figures are read again when the data answers.
                </Absent>
                <Button size="xs" variant="secondary" onClick={load.reload}>Try again</Button>
              </div>
            ) : (d && (d.period.measured.length > 0 || d.period.unmeasured.length > 0)
              ? <MetricsFigures connectionId={connectionId} schema={schema} block={d.period} />
              : <Absent>No approved metric is on this connection yet. Approve one in the Semantic Layer and it is measured here.</Absent>)}
          </Gate>
        </div>
      )}
    </div>
  );
}
