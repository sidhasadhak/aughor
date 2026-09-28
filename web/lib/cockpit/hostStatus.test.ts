/**
 * A card's status, read off its run (Arc CT, CT-4). The conditions of a cockpit stand on
 * these words, so each is pinned by the values either side of its edge.
 */
import { describe, expect, it } from "vitest";

import type { CardState } from "@/components/brief/PinnedCardBody";
import type { CardRunResult, DashboardCard } from "@/lib/api";
import { cardStatus, cardValue, hostStateOf } from "@/lib/cockpit/hostStatus";

/** A card and its run, as the server answers: `rows` are TEXT, `value` is the run's own
 *  figure as a number, and `refresh` is the card's standing value whatever the run was for. */
function state(opts: {
  id?: string; limits?: Record<string, unknown>; standing?: number | null;
  ranged?: (string | number | null)[][]; value?: number | null; standingRun?: boolean;
  error?: string; failed?: boolean; noRun?: boolean;
}): CardState {
  const refresh = { cadence: "daily", last_run: "", last_value: opts.standing ?? null, prev_value: null, history: [] };
  const card = {
    id: opts.id ?? "c1", connection_id: "thelook", scope: "canvas", scope_ref: "cv", source: "authored",
    kind: "kpi", title: "Return rate", sql: "SELECT 1", query_ref: null, render: {}, refresh,
    thresholds: opts.limits ?? {},
    provenance: {} as DashboardCard["provenance"],          // no test here reads it
    links: [], body: "", author: "", created_at: "", updated_at: "",
  } satisfies DashboardCard;
  if (opts.noRun) return { card };
  const run: CardRunResult = {
    columns: ["v"], rows: opts.ranged ?? [[opts.standing == null ? null : String(opts.standing)]], row_count: 1, caveats: [],
    error: opts.error ?? null, refresh,
    ...("value" in opts ? { value: opts.value } : opts.ranged ? {} : { value: opts.standing ?? null }),
    scoped: opts.ranged ? { covers: "August 2026", standing: !!opts.standingRun, why: "", grain: "orders.created_at" } : null,
  };
  return { card, run, failed: opts.failed };
}

const above = (warning: number | null, critical: number | null = null) => ({ warning, critical, direction: "above" });
const below = (warning: number | null, critical: number | null = null) => ({ warning, critical, direction: "below" });

describe("a card's status", () => {
  it.each([
    [0.119, "within"], [0.12, "over"], [0.121, "over"],
  ])("a limit above: %f is %s", (value, expected) => {
    expect(cardStatus(state({ limits: above(0.12), standing: value }))).toBe(expected);
  });

  it.each([
    [301_000, "within"], [300_000, "over"], [299_000, "over"],
  ])("a limit below: %d is %s", (value, expected) => {
    expect(cardStatus(state({ limits: below(300_000), standing: value }))).toBe(expected);
  });

  it("crossing the warning is already over, whatever the critical says", () => {
    expect(cardStatus(state({ limits: above(0.10, 0.15), standing: 0.11 }))).toBe("over");
    expect(cardStatus(state({ limits: above(null, 0.15), standing: 0.11 }))).toBe("within");
  });

  it("a direction nobody set reads as above, as the card's own alert does", () => {
    expect(cardStatus(state({ limits: { warning: 5 }, standing: 6 }))).toBe("over");
    expect(cardStatus(state({ limits: { warning: 5 }, standing: 4 }))).toBe("within");
  });

  it.each([
    ["no limit", state({ standing: 0.2 })],
    ["limits that are not numbers", state({ limits: { warning: "12%", critical: null, direction: "above" }, standing: 0.2 })],
    ["no value", state({ limits: above(0.12), standing: null })],
    ["a run that failed", state({ limits: above(0.12), standing: 0.2, failed: true })],
    ["a run that errored", state({ limits: above(0.12), standing: 0.2, error: "[BLOCKED]" })],
    ["no run at all", state({ limits: above(0.12), standing: 0.2, noRun: true })],
  ])("%s is unmeasured, never within", (_what, cs) => {
    expect(cardStatus(cs)).toBe("unmeasured");
  });

  it("zero is a value", () => {
    expect(cardValue(state({ standing: 0 }))).toBe(0);
    expect(cardStatus(state({ limits: above(0), standing: 0 }))).toBe("over");
  });
});

describe("the value a limit is held against", () => {
  it("is the range's own figure when the run was cut to a range", () => {
    const cs = state({ limits: above(0.12), standing: 0.09, ranged: [["0.13"]], value: 0.13 });
    expect(cardValue(cs)).toBe(0.13);
    expect(cardStatus(cs)).toBe("over");      // standing says within; the range asked for says over
  });

  it("is the standing figure when the card could not be cut to the range", () => {
    const cs = state({ limits: above(0.12), standing: 0.09, ranged: [["0.09"]], value: 0.09, standingRun: true });
    expect(cardValue(cs)).toBe(0.09);
  });

  it("is nothing when the range's run is a table, not a figure", () => {
    expect(cardValue(state({ standing: 0.09, ranged: [["Jeans", "84"], ["Swim", "52"]], value: null }))).toBeNull();
    expect(cardValue(state({ standing: 0.09, ranged: [], value: null }))).toBeNull();
  });

  it("is never read out of the rows, which the server sends as text", () => {
    // A server from before `value` sends a ranged run with the figure in `rows` alone. The
    // honest reading is "not measured" — not the standing figure, and not a guess at the text.
    const cs = state({ limits: above(0.12), standing: 0.09, ranged: [["0.13"]] });
    expect(cardValue(cs)).toBeNull();
    expect(cardStatus(cs)).toBe("unmeasured");
  });
});

describe("the tree a cockpit reads", () => {
  it("gives every card the canvas holds a status, and says nothing of any other", () => {
    const host = hostStateOf("to_date", [
      state({ id: "a", limits: above(0.12), standing: 0.2 }),
      state({ id: "b", limits: above(0.12), standing: 0.1 }),
      state({ id: "c", standing: 5 }),
    ]);
    expect(host).toEqual({
      range: { status: "to_date" },
      cards: { a: { status: "over" }, b: { status: "within" }, c: { status: "unmeasured" } },
    });
  });

  it("never says withheld: no rule for it exists yet", () => {
    const all = [state({ id: "a", error: "[BLOCKED] policy" }), state({ id: "b", failed: true })];
    expect(Object.values(hostStateOf("final", all).cards).map(c => c.status)).toEqual(["unmeasured", "unmeasured"]);
  });
});
