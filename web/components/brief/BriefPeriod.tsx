/**
 * Briefings by period (idea 3, flag `briefing.by_period`).
 *
 * The standing Briefing reads everything the platform knows; a period brief reads one
 * complete day, week, month or year and says what moved in it against the period before.
 * This file holds the two pieces the Briefing panel adds for it: the switch that picks
 * which version to read, and the table of what was MEASURED for the period — every
 * headline metric with its value, its comparison and the change, and every metric that
 * could not be measured with the reason. A missing number is said, never implied.
 *
 * Values arrive formatted by the server (the same rule the brief's sentences use), so the
 * table and the narrative cannot disagree about a figure; only the change is formatted here.
 */
import { Button } from "@/components/ui/button";
import type { BriefingPeriod, BriefingPeriodBlock } from "@/lib/api";
import { formatVariance } from "@/lib/format";

const OPTIONS: { value: BriefingPeriod; label: string }[] = [
  { value: "history", label: "Standing" },
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Year" },
];

export function PeriodSwitch({ value, onChange, disabled }: {
  value: BriefingPeriod;
  onChange: (p: BriefingPeriod) => void;
  disabled?: boolean;
}) {
  return (
    <div role="group" aria-label="Briefing period" className="flex items-center gap-1">
      {OPTIONS.map((o) => (
        <Button key={o.value} size="xs" variant={o.value === value ? "secondary" : "ghost"}
          aria-pressed={o.value === value} disabled={disabled} onClick={() => onChange(o.value)}>
          {o.label}
        </Button>
      ))}
    </div>
  );
}

/** The sentence shown when a period has nothing to brief on: which period, and why. */
export function periodUnavailable(block: BriefingPeriodBlock | undefined): string {
  if (!block) return "Nothing to brief on for this period.";
  const reasons = block.unmeasured.map((u) => `${u.name}: ${u.reason}`).join("; ");
  return `Nothing to brief on for ${block.covers}` + (reasons ? ` — ${reasons}.` : ": no metric moved and nothing was recorded.");
}

const COLUMN: Record<BriefingPeriodBlock["period"], string> = {
  day: "This day", week: "This week", month: "This month", year: "This year",
};

function change(m: BriefingPeriodBlock["measured"][number]): string {
  if (m.rel !== null && m.rel !== undefined) return formatVariance(m.rel);
  if (m.current_partial) return `no change stated: data covers only ${m.current_partial}`;
  if (m.previous_partial) return `no change stated: comparison covers only ${m.previous_partial}`;
  if (m.previous === null || m.previous === undefined) return "no comparison rows";
  return "no change stated";
}

export function PeriodMeasures({ block }: { block: BriefingPeriodBlock }) {
  return (
    <div className="aug-fs-sm" data-testid="period-measures" style={{ marginBottom: 14 }}>
      <div className="aug-label" style={{ marginBottom: 6 }}>
        Measured for {block.covers} · against {block.compared_with}
      </div>
      {block.lag_days > 1 && (
        <div style={{ color: "var(--t3)", marginBottom: 6 }}>
          {block.lag_source === "beyond_horizon"
            ? <>Ends {block.lag_days} days before today: {(block.still_moving ?? []).join(", ") || "a table"} was
                still changing {block.lag_days - 1} days after a day ended, so its figures may still move.</>
            : <>Ends {block.lag_days} days before today: newer days are still settling
                {block.lag_source === "learned" ? ", a lag the platform measured" : ""}.</>}
        </div>
      )}
      {block.measured.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ color: "var(--t3)", textAlign: "left" }}>
              <th style={{ fontWeight: 500, padding: "2px 8px 2px 0" }}>Metric</th>
              <th style={{ fontWeight: 500, padding: "2px 8px" }}>{COLUMN[block.period]}</th>
              <th style={{ fontWeight: 500, padding: "2px 8px" }}>Comparison</th>
              <th style={{ fontWeight: 500, padding: "2px 0 2px 8px" }}>Change</th>
            </tr>
          </thead>
          <tbody>
            {block.measured.map((m) => (
              <tr key={m.name} style={{ borderTop: "1px solid var(--b1)" }}>
                <td style={{ padding: "4px 8px 4px 0", color: "var(--t1)" }}>{m.name}</td>
                <td style={{ padding: "4px 8px" }}>{m.current_text ?? ""}</td>
                <td style={{ padding: "4px 8px", color: "var(--t2)" }}>{m.previous_text ?? ""}</td>
                <td style={{ padding: "4px 0 4px 8px", color: "var(--t2)" }}>{change(m)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {block.unmeasured.length > 0 && (
        <ul style={{ margin: "8px 0 0", paddingLeft: 16, color: "var(--t3)" }}>
          {block.unmeasured.map((u) => (
            <li key={u.name}>Not measured: {u.name} — {u.reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
