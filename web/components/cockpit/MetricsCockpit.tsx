"use client";

/**
 * The cockpit a person opens on (ROADMAP §6 item 43; asked 2026-10-05): the connection's approved
 * metrics, measured for a period — this range, its comparison, the change, a year earlier and
 * whether each figure has settled. It is the Briefing's own measured table, read without writing
 * a Briefing: no narrative, no model call. A metric's name opens it beside the page.
 *
 * It belongs to the connection, not to the person, so it is not in "Your cockpits" and cannot be
 * arranged or retired. A person's own cockpits sit beside it, as before.
 */
import { RangeMeasuresExpected, type RangeChoice } from "@/components/brief/BriefRange";
import { PeriodPicker, choiceName } from "@/components/cockpit/PeriodPicker";
import { Absent, Gate, useLoad } from "@/components/record/kit";
import { Loading } from "@/components/ui/states";
import { measureRange, type BriefingRange, type BriefingRangeBlock, type CockpitRange } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

/** The strip's id for it. No cockpit a person keeps can carry it. */
export const METRICS_COCKPIT = "::metrics";

/** The period as the picker says it: its words, and whether every figure in it has settled. */
function showing(block: BriefingRangeBlock): CockpitRange {
  const statuses = new Set(block.measured.map(m => m.status));
  const status = block.under_way || statuses.has("to_date") ? "to_date"
    : statuses.has("provisional") ? "provisional" : "final";
  return {
    status, preset: block.preset, start: block.start, last_day: block.last_day, covers: block.covers,
    as_of: block.as_of, lag_days: block.lag_days, still_moving: block.still_moving,
  };
}

export function MetricsCockpit({ connectionId, schema, rangesOn, value, onChange }: {
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
      <div data-testid="metrics-cockpit">
        <Absent>A metric is measured for a period, and periods are off on this install — they need the Briefing ranges flag.</Absent>
      </div>
    );
  }
  return (
    <div data-testid="metrics-cockpit">
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
        <PeriodPicker value={value} onChange={onChange} reading={reading}
          showing={load.data && !reading ? showing(load.data.period) : null} />
        {!reading && load.data && (
          <span className="aug-fs-sm" data-testid="metrics-measured-at" style={{ marginLeft: "auto", color: "var(--t3)" }}>
            {load.data.from_briefing ? "As the Briefing measured it" : "Measured"} {formatDateTime(load.data.measured_at)}
          </span>
        )}
      </div>
      {reading && load.data !== null && (
        <Loading what={`the metrics for ${choiceName(value)}`} style={{ padding: "12px 0" }} />
      )}
      {!range ? (
        <Absent>“As written” is for cards. A metric is measured for a period — pick one above.</Absent>
      ) : rangesOn === null ? null : (
        <div data-testid="metrics-body" aria-busy={reading || undefined}
          style={{ opacity: reading ? 0.45 : 1, transition: "opacity 120ms ease-out", pointerEvents: reading ? "none" : undefined }}>
          <Gate load={load} what={`the metrics for ${choiceName(value)}`}>
            {d => (d && (d.period.measured.length > 0 || d.period.unmeasured.length > 0)
              ? <RangeMeasuresExpected connectionId={connectionId} schema={schema} block={d.period} />
              : <Absent>No approved metric is on this connection yet. Approve one in the Semantic Layer and it is measured here.</Absent>)}
          </Gate>
        </div>
      )}
    </div>
  );
}
