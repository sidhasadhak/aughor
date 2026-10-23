/**
 * The builder's logic (Arc AP-1; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.4): what each element is called, the
 * edits the builder makes, a chart's split and the rules it is held to, what a dashboard's writer is told, and the rail
 * folded for the builder without the person's preference being written.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { canMove, outline, setProps, takeOffAll, type DashboardSpec } from "@/lib/dashboards/edit";
import { grammar } from "@/lib/dashboards/grammar";
import { kindWord, lineOf, nameOf } from "@/lib/dashboards/names";
import { splitOnDays, splitValue, topValues } from "@/lib/dashboards/objectView";
import { checkDashboardSpec } from "@/lib/dashboards/rules";
import { foldNavFor, NAV_COLLAPSED_KEY } from "@/lib/navCollapse";

const premise = (): DashboardSpec => JSON.parse(readFileSync(resolve(process.cwd(), "lib/dashboards/premise.fixture.json"), "utf8"));

/** A dashboard started from an object, with a detail and its buttons. */
function objectDashboard(): DashboardSpec {
  return {
    root: "cockpit",
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Orders" }, children: ["filters", "sec", "sec-2"] },
      filters: { type: "ObjectFilters", props: { entity: "order", properties: [{ path: "status", label: "Status" }] }, children: [] },
      sec: { type: "Section", props: { title: "Orders" }, children: ["figure-0", "chart", "table", "detail"] },
      "figure-0": { type: "ObjectFigure", props: { entity: "order", label: "Orders", agg: "count", size: "small" }, children: [] },
      chart: { type: "ObjectChart", props: { entity: "order", label: "Orders per day", time: "created_at", size: "full" }, children: [] },
      table: { type: "ObjectTable", props: { entity: "order", segment: "overdue_dispatch", size: "wide" }, children: [] },
      detail: { type: "ObjectDetail", props: { follows: "table", size: "small" }, children: ["flag"] },
      flag: { type: "ActionButton", props: { action: "flag_for_review" }, children: [] },
      "sec-2": { type: "Section", props: { title: "Notes" }, children: ["note"] },
      note: { type: "Note", props: { text: "Watch the   overdue\nones first", size: "small" }, children: [] },
    },
  };
}

const issues = (s: unknown) => checkDashboardSpec(s).issues.map(i => i.message);

describe("what each element is called (the study's defects 1 and 5)", () => {
  it("names a piece by what it reads, never by its key or a blank", () => {
    const els = objectDashboard().elements;
    expect(lineOf(els, "table")).toBe("Objects table · order, overdue dispatch");
    expect(lineOf(els, "detail")).toBe("Object detail · Chosen in order, overdue dispatch");
    expect(lineOf(els, "flag")).toBe("Action button · flag for review");
    expect(lineOf(els, "filters")).toBe("Filter column · order");
    expect(lineOf(els, "figure-0")).toBe("Figure · Orders");
    expect(lineOf(els, "chart")).toBe("Chart · Orders per day");
    expect(lineOf(els, "note")).toBe("Note · Watch the overdue ones first");
    expect(lineOf(els, "sec")).toBe("Section · Orders");
  });

  it("names a card by its title, and by its id when its title is not known", () => {
    const els = premise().elements;
    expect(nameOf(els, "card-rate", id => (id === "c7f3a001" ? "Return rate" : undefined))).toEqual({ kind: "card", title: "Return rate" });
    expect(nameOf(els, "card-net").title).toBe("c91b2002");
  });

  it("has a word for every component, so the pin strip never falls back to a key", () => {
    for (const t of ["ObjectFilters", "ObjectFigure", "ObjectChart", "ProcessBoard", "ObjectTable", "ObjectDetail", "ActionButton"]) {
      expect(kindWord(t)).not.toBe(t);
    }
    expect(kindWord("Nonsense")).toBe("Nonsense");
  });
});

describe("the builder's edits", () => {
  it("sets some props and keeps the rest; null takes one off", () => {
    const s = setProps(objectDashboard(), "table", { columns: ["status"], segment: null });
    expect(s.elements.table.props).toEqual({ entity: "order", size: "wide", columns: ["status"] });
    expect(objectDashboard().elements.table.props.segment).toBe("overdue_dispatch");     // the spec given is not touched
    expect(issues(s)).toEqual([]);
  });

  it("moves nothing before the filter column and never moves the column itself", () => {
    const s = objectDashboard();
    expect(canMove(s, "sec", -1)).toBe(false);
    expect(canMove(s, "sec", 1)).toBe(true);
    expect(canMove(s, "filters", 1)).toBe(false);
    expect(canMove(s, "figure-0", -1)).toBe(false);
    expect(canMove(s, "chart", -1)).toBe(true);
    expect(canMove(s, "cockpit", 1)).toBe(false);
  });

  it("takes a section off with everything it holds, and the dashboard left is one the rules accept", () => {
    const s = takeOffAll(objectDashboard(), "sec");
    expect(Object.keys(s.elements).sort()).toEqual(["cockpit", "filters", "note", "sec-2"]);
    expect(s.elements.cockpit.children).toEqual(["filters", "sec-2"]);
    expect(issues(s)).toEqual([]);
  });

  it("takes a tab off with its sections and their cards", () => {
    const s = takeOffAll(premise(), "tab-watches");
    expect(s.elements["tab-watches"]).toBeUndefined();
    expect(s.elements["sec-limits"]).toBeUndefined();
    expect(s.elements["watch-rate"]).toBeUndefined();
    expect(issues(s)).toEqual([]);
  });

  it("outlines a dashboard in the order it is drawn, the row of tabs not a line", () => {
    expect(outline(objectDashboard()).map(l => `${l.depth}:${l.key}`)).toEqual([
      "0:cockpit", "1:filters", "1:sec", "2:figure-0", "2:chart", "2:table", "2:detail", "3:flag", "1:sec-2", "2:note",
    ]);
    expect(outline(premise()).map(l => l.key)).toEqual([
      "cockpit", "tab-overview", "sec-headline", "alert-rate", "card-rate", "card-net", "tab-watches", "sec-limits", "watch-rate",
    ]);
  });
});

describe("a chart's split (Arc AP-1)", () => {
  // (period, value, measure), as the object door answers a query by day and by a property
  const rows = [
    ["2026-10-01 00:00:00+00:00", "Shipped", "70"], ["2026-10-01 00:00:00+00:00", "Complete", "76"],
    ["2026-10-01 00:00:00+00:00", "Returned", "34"], ["2026-10-02 00:00:00+00:00", "Shipped", "60"],
    ["2026-10-02 00:00:00+00:00", null, "5"], ["2026-10-02 00:00:00+00:00", "Complete", "1"],
  ];

  it("draws the values that hold the most over the window, most first, ties by name", () => {
    expect(topValues(rows, 2)).toEqual(["Shipped", "Complete"]);
    expect(topValues(rows, 9)).toEqual(["Shipped", "Complete", "Returned", "None"]);
    expect(splitValue(null)).toBe("None");
    expect(topValues([["d", "B", "1"], ["d", "A", "1"]], 2)).toEqual(["A", "B"]);
  });

  it("lays each day's values in their order and folds the rest into Other, last; a day with none holds nothing", () => {
    expect(splitOnDays(["2026-10-01", "2026-10-02", "2026-10-03"], rows, ["Shipped", "Complete"])).toEqual([
      [70, 76, 34], [60, 1, 5], [0, 0, 0],
    ]);
  });
});

describe("a chart's measure and split are held to one sense", () => {
  const chart = (props: Record<string, unknown>) => {
    const s = objectDashboard();
    s.elements.chart.props = { ...s.elements.chart.props, ...props };
    return issues(s);
  };

  it("accepts a count or a sum split by a property, and a measure of a property", () => {
    expect(chart({ split: "status" })).toEqual([]);
    expect(chart({ split: "status", top: 3, agg: "sum", path: "revenue", format: "money" })).toEqual([]);
    expect(chart({ agg: "avg", path: "num_of_item" })).toEqual([]);
  });

  it("refuses an aggregate of nothing, a split of what does not add up, and a top of no split", () => {
    expect(chart({ agg: "sum" }).join(" ")).toMatch(/measures the sum of nothing/);
    expect(chart({ agg: "avg", path: "num_of_item", split: "status" }).join(" ")).toMatch(/a count or a sum/);
    expect(chart({ top: 3 }).join(" ")).toMatch(/splits by nothing/);
    expect(chart({ top: 7, split: "status" }).join(" ")).toMatch(/top/);                   // six colours at most
  });
});

describe("what a dashboard's writer is told", () => {
  it("says nothing of the grid while dashboards are not built in place, and two fragments more while they are", () => {
    const off = grammar();
    const on = grammar({ grid: true });
    expect(off).not.toMatch(/grid/);
    expect(on.replace(", grid (optional: 12)", "").replace(/ In a section with "grid": 12[^\n]*/, "")).toBe(off);
  });
});

describe("the rail folded for the builder (the study §4.7)", () => {
  /** A document of the shape `foldNavFor` reads: its root's attributes, and the person's storage. */
  function fakeDoc(collapsed: boolean, stored: string | null) {
    const attrs = new Map<string, string>(collapsed ? [["data-nav", "collapsed"]] : []);
    const store = new Map<string, string>(stored === null ? [] : [[NAV_COLLAPSED_KEY, stored]]);
    let writes = 0;
    const doc = {
      documentElement: {
        getAttribute: (k: string) => attrs.get(k) ?? null,
        setAttribute: (k: string, v: string) => { attrs.set(k, v); },
        removeAttribute: (k: string) => { attrs.delete(k); },
      },
      defaultView: { localStorage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { writes++; store.set(k, v); } } },
    } as unknown as Document;
    return { doc, attrs, store, writes: () => writes };
  }

  it("folds an open rail and gives it back open, writing nothing the person keeps", () => {
    const d = fakeDoc(false, null);
    const back = foldNavFor(d.doc);
    expect(d.attrs.get("data-nav")).toBe("collapsed");
    back();
    expect(d.attrs.has("data-nav")).toBe(false);
    expect(d.writes()).toBe(0);
    expect(d.store.has(NAV_COLLAPSED_KEY)).toBe(false);
  });

  it("gives back a rail the person keeps folded as folded", () => {
    const d = fakeDoc(true, "1");
    foldNavFor(d.doc)();
    expect(d.attrs.get("data-nav")).toBe("collapsed");
  });

  it("gives the rail back as the person chose meanwhile — their own toggle stands", () => {
    const d = fakeDoc(false, null);
    const back = foldNavFor(d.doc);
    d.store.set(NAV_COLLAPSED_KEY, "1");                      // ⌘\\ twice while building: folded, and stored
    back();
    expect(d.attrs.get("data-nav")).toBe("collapsed");
  });
});
