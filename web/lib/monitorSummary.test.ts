/**
 * Monitors says each monitor's rule, schedule and proof in a few words, counts the checks a day the set costs, and
 * folds identical alerts into one row with a count (CLARITY.md).
 */
import { describe, expect, it } from "vitest";

import type { MonitorAlert, MonitorProof } from "./api";
import {
  alertText, alertsByWeek, checksPerDay, foldAlerts, proofState, proofWords, ruleWords, scheduleMix, short,
} from "./monitorSummary";

const proof = (over: Partial<MonitorProof>): MonitorProof => ({ monitor_id: "m", sentence: "", last_drill: null, ...over });
const drill = (fired: boolean, delivered: boolean | null) =>
  ({ monitor_id: "m", at: "2026-09-23T12:16:05+00:00", fired, delivered, detail: "", channel: "in_app" });

describe("proofState", () => {
  it("reads the server's record the way its sentence does", () => {
    expect(proofState(proof({}))).toBe("never");
    expect(proofState(proof({ last_drill: drill(true, null) }))).toBe("checked");
    expect(proofState(proof({ last_drill: drill(true, true) }))).toBe("proven");
    expect(proofState(proof({ last_drill: drill(true, false) }))).toBe("undelivered");
    expect(proofState(proof({ last_drill: drill(false, null) }))).toBe("silent");
    expect(proofState(proof({ last_real_delivery: { fired_at: "2026-10-01T00:00:00Z" } }))).toBe("delivered");
    // a proof that could not be read is never shown as "never proven"
    expect(proofState(null)).toBe("unknown");
  });

  it("says it as a chip's few words", () => {
    expect(proofWords(proof({}))).toBe("never proven");
    expect(proofWords(proof({ last_drill: drill(true, null) }))).toBe("rule checked 23 Sep · not delivered");
  });
});

describe("checksPerDay", () => {
  it("counts the form's schedules and their plain variants, and refuses to guess the rest", () => {
    expect(checksPerDay("0 * * * *")).toBe(24);
    expect(checksPerDay("0 */6 * * *")).toBe(4);
    expect(checksPerDay("0 9 * * *")).toBe(1);
    expect(checksPerDay("0 9 * * 1")).toBeCloseTo(1 / 7);
    expect(checksPerDay("0 9 * * 1-5")).toBeCloseTo(5 / 7);
    expect(checksPerDay("*/15 * * * *")).toBe(96);
    expect(checksPerDay("0 9 1 * *")).toBeNull();
    expect(checksPerDay("nonsense")).toBeNull();
  });

  it("says the set's schedules most common first", () => {
    expect(scheduleMix([{ check_cron: "0 * * * *" }, { check_cron: "0 9 * * *" }, { check_cron: "0 * * * *" }, { check_cron: "5 4 * * *" }]))
      .toBe("2 hourly · 1 daily · 1 on 5 4 * * *");
  });
});

describe("words for a rule and an alert", () => {
  const base = { warning_threshold: null, critical_threshold: null, threshold_direction: "below" as const, sigma_threshold: 2.5,
    history_days: 30, dimension_column: null, freshness_table: null, freshness_sla_hours: 24 };
  it("says what a monitor watches for in a few words, numbers humanised", () => {
    expect(ruleWords({ ...base, alert_on: "threshold_cross", warning_threshold: 86 })).toBe("Threshold · below 86");
    expect(ruleWords({ ...base, alert_on: "threshold_cross", threshold_direction: "above", warning_threshold: 200000 }))
      .toBe("Threshold · above 200K");
    expect(ruleWords({ ...base, alert_on: "anomaly" })).toBe("Anomaly · 2.5σ over 30 days");
    expect(ruleWords({ ...base, alert_on: "data_freshness", freshness_table: "orders" })).toBe("Freshness · orders within 24 h");
    expect(short(20261)).toBe("20.3K");
  });

  it("writes an alert's float noise as a person reads it", () => {
    expect(alertText("Active Customer Count: 2.026e+04 above warning threshold 2e+04"))
      .toBe("Active Customer Count: 20,260 above warning threshold 20,000");
  });
});

function alert(over: Partial<MonitorAlert>): MonitorAlert {
  return {
    id: Math.random().toString(36).slice(2), monitor_id: "m1", monitor_name: "Active Customer Count", conn_id: "c",
    metric_name: null, triggered_at: "2026-08-24T06:00:00Z", alert_on: "threshold_cross", severity: "warning",
    current_value: 20261, previous_value: 20261, threshold: 20000, message: "Active Customer Count: 2.026e+04 above 2e+04",
    caveat: null, acknowledged: true, acknowledged_at: null, ...over,
  };
}

describe("foldAlerts", () => {
  it("says the same alert once, with its count, its span and the ids still open", () => {
    const a = alert({ triggered_at: "2026-08-23T21:03:00Z", acknowledged: false });
    const groups = foldAlerts([
      alert({ triggered_at: "2026-08-24T06:00:00Z" }), alert({ triggered_at: "2026-08-24T02:00:00Z" }), a,
      alert({ monitor_id: "m2", monitor_name: "Other", message: "different" }),
    ]);
    expect(groups).toHaveLength(2);
    // the group holding an open alert comes first
    expect(groups[0]).toMatchObject({ count: 3, first: "2026-08-23T21:03:00Z", last: "2026-08-24T06:00:00Z", open: [a.id] });
  });

  it("counts alerts per week over the last twelve weeks", () => {
    const now = new Date(2026, 9, 12, 12); // Mon 12 Oct 2026, local
    const weeks = alertsByWeek([
      alert({ triggered_at: new Date(2026, 7, 24, 6).toISOString() }),
      alert({ triggered_at: new Date(2026, 7, 23, 21).toISOString(), severity: "critical" }),
      alert({ triggered_at: new Date(2026, 6, 1).toISOString() }), // before the window
    ], now);
    expect(weeks).toHaveLength(12);
    expect(weeks[11].start.getDate()).toBe(12);
    expect(weeks.reduce((s, w) => s + w.n, 0)).toBe(2);
    const aug = weeks.filter(w => w.n > 0);
    // Sun 23 Aug falls in the week of Mon 17 Aug, Mon 24 Aug starts the next
    expect(aug.map(w => [w.start.getDate(), w.n])).toEqual([[17, 1], [24, 1]]);
    expect(aug[0].bySeverity).toEqual({ critical: 1 });
  });
});
