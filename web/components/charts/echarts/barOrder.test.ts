/**
 * A ranking bar sorts by its measure — the behaviour a "top routes" answer leans on.
 *
 * Written while chasing a report that a chart "did not match its own claim": an answer
 * naming ZRH-LHR the busiest route sat above a chart whose leading bars were other
 * routes entirely. The chart was right and the SENTENCE was invented (the numbers
 * appeared in no row — see the grounding guard). The ordering it was accused of getting
 * wrong had no test, so this pins it: the accusation should have been answerable by
 * running something.
 */
import { describe, expect, it } from "vitest";

import { barOption } from "./builders";

const ROWS = [
  { route: "ZRH-LHR", n: 28 },
  { route: "GVA-LHR", n: 42 },
  { route: "ZRH-CDG", n: 35 },
  { route: "ZRH-ORD", n: 7 },
];

/** The category labels in the order the chart will draw them. */
function categories(opt: ReturnType<typeof barOption>): string[] {
  const axes = [opt.xAxis, opt.yAxis].flat() as { type?: string; data?: string[] }[];
  const cat = axes.find((a) => a && a.type === "category" && Array.isArray(a.data));
  return (cat?.data ?? []) as string[];
}

describe("barOption ordering", () => {
  it("ranks largest first by default", () => {
    const opt = barOption({ rows: ROWS, x: "route", ys: ["n"], xKind: "category" });
    expect(categories(opt)).toEqual(["GVA-LHR", "ZRH-CDG", "ZRH-LHR", "ZRH-ORD"]);
  });

  it("keeps the query's own order when asked to", () => {
    const opt = barOption({ rows: ROWS, x: "route", ys: ["n"], xKind: "category" },
                          { order: "keep" });
    expect(categories(opt)).toEqual(["ZRH-LHR", "GVA-LHR", "ZRH-CDG", "ZRH-ORD"]);
  });

  it("leads with the smallest when the query asked for the bottom of the ranking", () => {
    // ORDER BY <measure> ASC LIMIT N — the row the query led with must lead the chart.
    const opt = barOption({ rows: ROWS, x: "route", ys: ["n"], xKind: "category",
                            exhibit: { order: "asc" } as never });
    expect(categories(opt)[0]).toBe("ZRH-ORD");
  });

  it("ties keep every member — a plateau is data, not a rendering fault", () => {
    const tied = [{ route: "A", n: 42 }, { route: "B", n: 42 }, { route: "C", n: 28 }];
    const opt = barOption({ rows: tied, x: "route", ys: ["n"], xKind: "category" });
    expect(categories(opt)).toHaveLength(3);
    expect(categories(opt)[2]).toBe("C");
  });
});
