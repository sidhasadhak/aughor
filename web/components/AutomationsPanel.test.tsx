/**
 * The runs rail — asserted on the pure collapse, not on rendered rows.
 *
 * Measured on this deployment 2026-09-03 before any of this was written: **99 of the last
 * 100 runs were `not_fired`**, pure scheduler ticks reading "schedule(0 9 * * *): next due
 * …", carrying no effects and no error. One fired run sat under ninety-nine identical
 * cards. The ledger line said the fired run "drowns in scheduler noise"; the number is what
 * turned that from a complaint into a defect.
 *
 * The one property every test here defends: **collapsing must never HIDE.** A rail that
 * quietly dropped ticks would be the catalogue-that-lies failure wearing a tidier coat, so
 * a group states its exact count, its span, and only claims a shared reason when every tick
 * in it actually gives the same one.
 */
import { describe, expect, it } from "vitest";

import { collapseQuietTicks } from "@/components/AutomationsPanel";
import type { AutomationRun } from "@/lib/api";

const run = (over: Partial<AutomationRun> = {}): AutomationRun => ({
  id: Math.random().toString(36).slice(2),
  automation_id: "a1",
  outcome: "not_fired",
  reason: "schedule(0 9 * * *): next due 2026-09-04T09:00:00+00:00",
  started_at: "2026-09-03T10:00:00Z",
  duration_ms: 3,
  effects: [],
  error: "",
  ...over,
} as AutomationRun);

const kinds = (rows: ReturnType<typeof collapseQuietTicks>) => rows.map(r => r.kind);

describe("collapseQuietTicks", () => {
  it("collapses a run of identical quiet ticks into ONE row that counts them", () => {
    const rows = collapseQuietTicks([run(), run(), run()]);
    expect(kinds(rows)).toEqual(["quiet"]);
    expect(rows[0]).toMatchObject({ count: 3 });
  });

  it("keeps a fired run as its own card, and does not swallow it", () => {
    // The whole point. Ninety-nine quiet ticks must not cost the reader the one run that
    // did something.
    const rows = collapseQuietTicks([
      run(), run(),
      run({ outcome: "fired", reason: "due", id: "the-real-one" }),
      run(), run(),
    ]);
    expect(kinds(rows)).toEqual(["quiet", "run", "quiet"]);
  });

  it("collapses only ADJACENT ticks — the stacking rule, not a global filter", () => {
    // A global "hide not_fired" would also be tidier and would lie about the order things
    // happened in. Two separate quiet stretches stay two rows.
    const rows = collapseQuietTicks([run(), run({ outcome: "error", error: "boom" }), run()]);
    expect(kinds(rows)).toEqual(["quiet", "run", "quiet"]);
    expect(rows[0]).toMatchObject({ count: 1 });
    expect(rows[2]).toMatchObject({ count: 1 });
  });

  it("REFUSES to collapse a not_fired run that carried an effect", () => {
    // "The schedule was not due" and "something happened and was not recorded as firing"
    // are different sentences, and only one of them is boring.
    const rows = collapseQuietTicks([
      run(),
      run({ effects: [{ kind: "notify", target: "x", status: "failed", message: "",
                        attempts: 1 }] as AutomationRun["effects"] }),
    ]);
    expect(kinds(rows)).toEqual(["quiet", "run"]);
  });

  it("REFUSES to collapse a not_fired run that carried an error", () => {
    const rows = collapseQuietTicks([run(), run({ error: "cron parse failed" })]);
    expect(kinds(rows)).toEqual(["quiet", "run"]);
  });

  it("carries the shared reason, and DROPS it the moment the ticks disagree", () => {
    // Showing the first tick's reason for a group that does not share it would attribute a
    // sentence to runs that never said it.
    const same = collapseQuietTicks([run(), run()]);
    expect(same[0]).toMatchObject({ reason: expect.stringContaining("next due") });

    const differing = collapseQuietTicks([run(), run({ reason: "a different reason" })]);
    expect(differing).toHaveLength(1);
    expect(differing[0]).toMatchObject({ count: 2, reason: "" });
  });

  it("spans from the OLDEST to the NEWEST tick it covers", () => {
    // `runs` arrives newest-first, so each further tick extends the older end. Getting this
    // backwards would render a span that runs the wrong way.
    const rows = collapseQuietTicks([
      run({ started_at: "2026-09-03T10:00:00Z" }),
      run({ started_at: "2026-09-03T09:00:00Z" }),
      run({ started_at: "2026-09-03T08:00:00Z" }),
    ]);
    expect(rows[0]).toMatchObject({
      newest: "2026-09-03T10:00:00Z", oldest: "2026-09-03T08:00:00Z", count: 3,
    });
  });

  it("returns nothing for no runs, rather than an empty group", () => {
    expect(collapseQuietTicks([])).toEqual([]);
  });

  it("reproduces the measured shape: 99 quiet ticks and one fired run become 2 rows", () => {
    const many = [...Array(50)].map(() => run());
    const rest = [...Array(49)].map(() => run());
    const rows = collapseQuietTicks([...many, run({ outcome: "fired" }), ...rest]);
    expect(kinds(rows)).toEqual(["quiet", "run", "quiet"]);
    expect(rows[0]).toMatchObject({ count: 50 });
    expect(rows[2]).toMatchObject({ count: 49 });
  });
});
