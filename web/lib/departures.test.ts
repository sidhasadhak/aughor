import { describe, expect, it } from "vitest";

import {
  addressedText, departureFromUrl, filterDepartures, guardRows, normalizeDeparture, owes,
  readingsOf, stateHue, stateLabel, summaryLine,
} from "@/lib/departures";

const row = (over: Record<string, unknown> = {}) => normalizeDeparture({
  id: "d1", ts: "2026-09-17T09:00:12Z", kind: "slack_post", state: "departed",
  automation_name: "Dispatch promise watch", target: "sb_1:#ops",
  reasons: [], checks: { trust: "clean" }, guards: { trust: "passed" },
  receipt: {}, question: {}, verdict: "", answer: "",
  ...over,
});

describe("normalizeDeparture", () => {
  it("decodes the JSON columns an older API served as strings", () => {
    const d = normalizeDeparture({
      id: "old", state: "held", reasons: '["a failing tie-out"]', checks: '{"trust":"clean"}',
      guards: "", receipt: "not json", question: "{}",
    });
    expect(d.reasons).toEqual(["a failing tie-out"]);
    expect(d.checks).toEqual({ trust: "clean" });
    expect(d.guards).toEqual({});
    expect(d.receipt).toEqual({});
    expect(d.verdict).toBe("");
  });
});

describe("what a person owes", () => {
  it("a probation departure wants its declarer's mark until marked", () => {
    expect(owes(row({ state: "held_probation" }))).toBe("mark");
    expect(owes(row({ state: "held_probation", verdict: "accept" }))).toBeNull();
    expect(stateLabel(row({ state: "held_probation" }))).toBe("awaiting its declarer");
    expect(stateHue(row({ state: "held_probation", verdict: "reject" }))).toBe("muted");
  });

  it("a question wants its owner's answer until answered — whatever its state", () => {
    const question = { readings: [{ label: "Governed", sql: "x" }, { label: "Parsed", sql: "y" }],
                       previews: ["= 2.10%", "= 7.80%"] };
    expect(owes(row({ state: "held_owner", question }))).toBe("answer");
    expect(owes(row({ state: "held", question }))).toBe("answer");
    expect(owes(row({ state: "held_owner", question, answer: "Governed" }))).toBeNull();
    expect(readingsOf(question)).toEqual([
      { label: "Governed", preview: "= 2.10%" }, { label: "Parsed", preview: "= 7.80%" }]);
    expect(addressedText(row({ state: "held_owner", question })))
      .toBe("no owner is routable — anyone who can answer may");
    expect(addressedText(row({ state: "held_owner", question, addressed_to: "group:finance" })))
      .toBe("waiting on group:finance");
  });

  it("filters to what needs a person, what was held, what departed", () => {
    const rows = [row({ id: "a" }), row({ id: "b", state: "held" }),
                  row({ id: "c", state: "held_probation" })];
    expect(filterDepartures(rows, "owed").map(r => r.id)).toEqual(["c"]);
    expect(filterDepartures(rows, "held").map(r => r.id)).toEqual(["b", "c"]);
    expect(filterDepartures(rows, "departed").map(r => r.id)).toEqual(["a"]);
    expect(filterDepartures(rows, "all")).toHaveLength(3);
  });
});

describe("the guards and the summary line", () => {
  it("lists guards in the order the gate ran them, never guessing an outcome", () => {
    const d = row({
      checks: { probation: "not on probation", trust: "clean", remeasure: "2 numbers grounded",
                held_lines: "one cut" },
      guards: { remeasure: "passed", trust: "passed" },
    });
    expect(guardRows(d).map(g => [g.guard, g.outcome])).toEqual([
      ["trust", "passed"], ["remeasure", "passed"], ["probation", "recorded"],
      ["held_lines", "recorded"]]);
  });

  it("says what the owner is asked, why it was held, or what ran", () => {
    expect(summaryLine(row({ state: "held_owner", question: { question: "Which reading?" } })))
      .toBe("Which reading?");
    expect(summaryLine(row({ state: "held", reasons: ["re-measured at departure: 99,441 is not in …"] })))
      .toContain("99,441");
    expect(summaryLine(row())).toBe("checked: trust");
  });

  it("reads the departure a receipt's link names", () => {
    expect(departureFromUrl("?tab=agentic-ops&layer=departures&departure=abc123")).toBe("abc123");
    expect(departureFromUrl("?tab=agentic-ops")).toBe("");
  });
});
