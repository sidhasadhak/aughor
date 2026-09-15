/**
 * The schedule trigger as a person states one — parse/format round trips, the
 * plain-words summary with the clock named, and a next run stated only when its
 * arithmetic is exact. The bug this guards: the When drawer rendered the time as a
 * bare cron fragment ("0 9"), and a shape the editor cannot say must round-trip
 * through Custom untouched rather than being rewritten.
 */
import { describe, expect, it } from "vitest";

import { cronWords, nextFireUtc, parseCron, toCron } from "@/components/automations/ScheduleEditor";

describe("parseCron / toCron", () => {
  it("round-trips the platform's own shapes", () => {
    for (const cron of ["0 9 * * *", "30 7 * * *", "0 9 * * 1", "0 9 * * 1,3,5",
                        "15 * * * *", "0 6 15 * *"]) {
      expect(toCron(parseCron(cron))).toBe(cron);
    }
  });
  it("reads daily, weekly, monthly and hourly into their parts", () => {
    expect(parseCron("30 7 * * *")).toMatchObject({ occurrence: "daily", time: "07:30" });
    expect(parseCron("0 9 * * 1,3")).toMatchObject({ occurrence: "weekly", weekdays: [1, 3] });
    expect(parseCron("0 6 15 * *")).toMatchObject({ occurrence: "monthly", dayOfMonth: 15 });
    expect(parseCron("15 * * * *")).toMatchObject({ occurrence: "hourly", minute: 15 });
    expect(parseCron("0 9 * * 7")).toMatchObject({ occurrence: "weekly", weekdays: [0] }); // cron's two Sundays
  });
  it("leaves a shape it cannot say as custom, untouched", () => {
    for (const cron of ["*/5 * * * *", "0 9 * * 1-5", "0 9 1 6 *", "not cron"]) {
      const s = parseCron(cron);
      expect(s.occurrence).toBe("custom");
      expect(toCron(s)).toBe(cron);
    }
  });
});

describe("cronWords", () => {
  it("says the schedule with the clock named", () => {
    expect(cronWords("0 9 * * *")).toBe("Every day at 09:00 UTC");
    expect(cronWords("0 9 * * 1,5")).toBe("Every Mon, Fri at 09:00 UTC");
    expect(cronWords("30 6 15 * *")).toBe("Monthly on day 15 at 06:30 UTC");
    expect(cronWords("15 * * * *")).toBe("Every hour at minute 15");
    expect(cronWords("0 9 * * 1-5")).toBe("On the cron schedule 0 9 * * 1-5 (UTC)");
  });
});

describe("nextFireUtc", () => {
  const now = new Date(Date.UTC(2026, 8, 15, 20, 0)); // Tue 15 Sep 2026, 20:00Z
  it("daily: later today or tomorrow", () => {
    expect(nextFireUtc("0 21 * * *", now)?.toISOString()).toBe("2026-09-15T21:00:00.000Z");
    expect(nextFireUtc("0 9 * * *", now)?.toISOString()).toBe("2026-09-16T09:00:00.000Z");
  });
  it("weekly: the next listed weekday", () => {
    expect(nextFireUtc("0 9 * * 1", now)?.toISOString()).toBe("2026-09-21T09:00:00.000Z");
    expect(nextFireUtc("0 9 * * 2,4", now)?.toISOString()).toBe("2026-09-17T09:00:00.000Z");
  });
  it("monthly rolls into the next month when the day has passed", () => {
    expect(nextFireUtc("0 9 1 * *", now)?.toISOString()).toBe("2026-10-01T09:00:00.000Z");
  });
  it("guesses nothing for a custom expression", () => {
    expect(nextFireUtc("*/5 * * * *", now)).toBeNull();
  });
});
