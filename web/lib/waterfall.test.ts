import { describe, expect, it } from "vitest";

import { MIN_BAR_PCT, axisSpanMs, barGeometry } from "@/lib/waterfall";

describe("waterfall geometry", () => {
  it("places a bar by offset and sizes it by duration", () => {
    const g = barGeometry({ offset_ms: 2500, duration_ms: 5000 }, 10_000);
    expect(g.left).toBe(25);
    expect(g.width).toBe(50);
    expect(g.floored).toBe(false);
  });

  it("keeps a zero-duration node VISIBLE rather than drawing nothing", () => {
    // A user_request has nothing to measure. A bar of width 0 is a node the reader
    // cannot see or click, which reads as "this event did not happen".
    const g = barGeometry({ offset_ms: 0, duration_ms: null }, 10_000);
    expect(g.width).toBe(MIN_BAR_PCT);
    expect(g.floored).toBe(true);
  });

  it("clamps a bar that would run past the end of its track", () => {
    // Happens on a run still in progress: the node outlives the computed wall.
    const g = barGeometry({ offset_ms: 9000, duration_ms: 99_000 }, 10_000);
    expect(g.left).toBe(90);
    expect(g.left + g.width).toBeLessThanOrEqual(100);
  });

  it("does not pretend a missing offset is offset zero with a real width", () => {
    const g = barGeometry({ offset_ms: null, duration_ms: 5000 }, 10_000);
    expect(g.left).toBe(0);
    expect(g.width).toBe(50);
  });

  it("survives a zero or nonsense span instead of dividing by it", () => {
    for (const span of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      const g = barGeometry({ offset_ms: 10, duration_ms: 10 }, span);
      expect(Number.isFinite(g.left)).toBe(true);
      expect(Number.isFinite(g.width)).toBe(true);
    }
  });

  it("takes the axis from wall time when it is the larger", () => {
    expect(axisSpanMs([{ offset_ms: 0, duration_ms: 100 }], 5000)).toBe(5000);
  });

  it("extends the axis past a wall that is shorter than its own longest node", () => {
    // A run in progress reports a wall that has not caught up with its bars.
    expect(axisSpanMs([{ offset_ms: 1000, duration_ms: 9000 }], 5000)).toBe(10_000);
  });

  it("never returns a zero axis, so no caller divides by it", () => {
    expect(axisSpanMs([], null)).toBe(1);
  });
});
