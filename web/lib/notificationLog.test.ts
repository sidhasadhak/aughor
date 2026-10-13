/**
 * The delivery log folds the way a person reads it: fifty failures from two triggers are two rows with a count, a
 * trigger that no longer exists is history, and a webhook's path — where a Slack hook keeps its secret — never reaches
 * the screen. The fixtures are the live install's own log, 2026-10-13: 46 sends through "slack-ops" while it was off,
 * 4 through "DS-7 blackhole" to a port nothing listens on, both triggers since removed.
 */
import { describe, expect, it } from "vitest";

import {
  failingStreak, foldDeliveries, hostOf, latestByTrigger, redactError, shortError, SOURCE_FIELD, sourceWords,
  type DeliveryLog,
} from "./notificationLog";

const REFUSED = "HTTPConnectionPool(host='127.0.0.1', port=9): Max retries exceeded with url: /hook "
  + "(Caused by NewConnectionError(\"HTTPConnection(host='127.0.0.1', port=9): Failed to establish a new connection\"))";

function log(i: number, over: Partial<DeliveryLog>): DeliveryLog {
  return {
    id: `l${i}`, trigger_id: "t1", trigger_name: "slack-ops", recommendation: "hi", status: "failed", http_status: null,
    error: "Trigger is disabled", fired_at: `2026-07-08T11:${String(i % 60).padStart(2, "0")}:00+00:00`, ...over,
  };
}

const LIVE_SHAPE: DeliveryLog[] = [
  ...Array.from({ length: 46 }, (_, i) => log(i, {})),
  ...Array.from({ length: 4 }, (_, i) => log(100 + i, {
    trigger_id: "744ec96b", trigger_name: "DS-7 blackhole", error: REFUSED, recommendation: i % 2 ? "right lane" : "left lane",
    fired_at: `2026-08-31T21:0${i}:00+00:00`, [SOURCE_FIELD]: "automation:f2aa4864",
  })),
];

describe("foldDeliveries", () => {
  it("folds fifty sends from two triggers into two rows with their counts, newest first", () => {
    const groups = foldDeliveries(LIVE_SHAPE, new Set());
    expect(groups.map(g => [g.triggerName, g.outcome, g.count])).toEqual([
      ["DS-7 blackhole", "failed", 4],
      ["slack-ops", "failed", 46],
    ]);
    expect(groups.every(g => g.removed)).toBe(true);
    expect(groups[0].messages).toEqual(["right lane", "left lane"]);
    expect(groups[0].sources).toEqual(["an automation"]);
    expect(groups[1].sources).toEqual(["an action"]);
  });

  it("keeps a live trigger's rows live, and splits one trigger's outcomes", () => {
    const groups = foldDeliveries([
      log(1, { status: "ok", error: null, http_status: 200 }), log(2, {}), log(3, { status: "ok", error: null }),
    ], new Set(["t1"]));
    expect(groups.map(g => [g.outcome, g.count, g.removed])).toEqual([["ok", 2, false], ["failed", 1, false]]);
  });
});

describe("errors in a few words, with no secret", () => {
  it("says the two live errors plainly", () => {
    expect(shortError(LIVE_SHAPE[0])).toBe("the trigger was off");
    expect(shortError(LIVE_SHAPE[49])).toBe("could not connect to 127.0.0.1:9");
    expect(shortError({ error: "", status: "timeout", http_status: null })).toBe("no answer in time");
    expect(shortError({ error: "", status: "failed", http_status: 403 })).toBe("HTTP 403");
  });

  it("cuts every URL path, where a Slack hook keeps its secret", () => {
    const e = "POST https://hooks.slack.com/services/T000/B000/XXXXSECRET failed; with url: /services/T000/B000/XXXXSECRET";
    const clean = redactError(e);
    expect(clean).not.toContain("XXXXSECRET");
    expect(clean).toContain("https://hooks.slack.com/…");
    expect(shortError({ error: e, status: "failed", http_status: null })).not.toContain("XXXXSECRET");
  });

  it("keeps only the host of a masked trigger URL", () => {
    expect(hostOf("https://hooks.slack.com/••••••")).toBe("hooks.slack.com");
    expect(hostOf("")).toBe("");
  });
});

describe("what sent it, and the newest send", () => {
  it("names the sender in a reader's words", () => {
    expect(sourceWords(log(1, { [SOURCE_FIELD]: "monitor:m1" }))).toBe("a monitor");
    expect(sourceWords(log(1, { [SOURCE_FIELD]: "brief:b1" }))).toBe("the Briefing");
    expect(sourceWords(log(1, { [SOURCE_FIELD]: "test_inv" }))).toBe("a test fire");
    expect(sourceWords(log(1, { [SOURCE_FIELD]: "run-123" }))).toBe("a recommendation acted on");
  });

  it("finds each trigger's newest send and how many failed in a row", () => {
    const logs = [log(1, { status: "ok", error: null }), log(2, {}), log(3, { status: "timeout" })];
    expect(latestByTrigger(logs).get("t1")?.id).toBe("l3");
    expect(failingStreak(logs, "t1")).toBe(2);
  });
});
