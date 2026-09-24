/**
 * Idea 5 — "we told you 1,744; it is now 1,902". Shown under a restored chat answer when a
 * later re-check re-ran the answer's own query and a number it gave had moved past the noise
 * band. What the answer said above stays as it was said; this is the dated reading beside it,
 * with whether the change is late rows or a restatement — or that the platform cannot tell.
 */
import type { AnswerRecheck as Recheck } from "@/lib/api";
import { formatTimestamp, formatVariance, formatMetricValue } from "@/lib/format";

const SHOWN = 3;

function what(c: Recheck["changes"][number]): string {
  const label = Object.values(c.label || {}).filter((v) => v !== null && v !== "").join(", ");
  return label ? `${c.column} for ${label}` : c.column;
}

function cause(r: Recheck): string {
  if (r.cause === "late_rows")
    return `Late rows: this source settles after ${r.lag_days} days, and the day was still settling when this was answered.`;
  if (r.cause === "restated")
    return "The source has restated a day that had already settled when this was answered.";
  if (r.lag_days === null)
    return "The platform has not yet learned when this source settles, so it cannot say whether these are late rows or a restatement.";
  return "The answer has no date column, so the change cannot be placed in time.";
}

export function AnswerRecheck({ recheck }: { recheck: Recheck }) {
  const gone = recheck.missing_rows ?? 0;
  if (recheck.status !== "changed" || (!recheck.changes?.length && !gone)) return null;
  const more = (recheck.changed ?? recheck.changes.length) - Math.min(SHOWN, recheck.changes.length);
  const firstGone = Object.values(recheck.missing?.[0] ?? {}).filter((v) => v !== null && v !== "").join(", ");
  return (
    <div data-testid="answer-recheck" className="aug-fs-sm"
      style={{ border: "1px solid var(--amb2)", background: "var(--amb1)", borderRadius: "var(--r2)",
        padding: "8px 10px", margin: "8px 0", color: "var(--t1)" }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>
        Re-checked {formatTimestamp(recheck.checked_at, "short")}: this answer has changed
      </div>
      <ul style={{ margin: 0, paddingLeft: 16 }}>
        {recheck.changes.slice(0, SHOWN).map((c, i) => (
          <li key={i}>
            {what(c)} was {formatMetricValue(c.old)}, now {formatMetricValue(c.new)}
            {c.rel !== null && c.rel !== undefined ? ` (${formatVariance(c.rel)})` : ""}
          </li>
        ))}
      </ul>
      {more > 0 && <div style={{ color: "var(--t2)" }}>{more} more number{more === 1 ? "" : "s"} changed too.</div>}
      {gone > 0 && (
        <div style={{ color: "var(--t2)" }}>
          {gone} row{gone === 1 ? "" : "s"} this answer gave {gone === 1 ? "is" : "are"} no longer returned
          {firstGone ? ` (such as ${firstGone})` : ""}.
        </div>
      )}
      {recheck.changes.length > 0 && <div style={{ color: "var(--t2)", marginTop: 4 }}>{cause(recheck)}</div>}
    </div>
  );
}
