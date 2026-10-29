/** Arc BG/BC — the words an edition's page puts around what the server measured. */
import { describe, expect, it } from "vitest";

import type { EditionBlock, EditionFigure, EditionSource } from "@/lib/api";
import {
  ORGANISATION, bridgeSteps, drillOptions, fmtChange, fmtValue, fromServerReader, groupIdOf, parseCited, readerOptions,
  toServerReader, toneOf, writeLabel,
} from "./briefingEdition";

const src = (over: Partial<EditionSource>): EditionSource => ({
  id: "s", label: "S", kind: "query", columns: [], rows: [], sql: "", status: "final", facts: {}, receipts: [],
  caveats: [], note: "", error: "", unit: "", better: "none", ...over,
});

describe("readers", () => {
  it("offers the organisation first, then function groups by name — never a built-in role", () => {
    expect(readerOptions([
      { id: "product", name: "Product", kind: "function" }, { id: "viewer", name: "Viewer", kind: "builtin" },
      { id: "finance", name: "Finance", kind: "function" },
    ])).toEqual([{ value: ORGANISATION, label: "The organisation" }, { value: "finance", label: "Finance" },
                 { value: "product", label: "Product" }]);
  });
  it("speaks the server's empty string for the organisation, both ways", () => {
    expect(toServerReader(ORGANISATION)).toBe("");
    expect(fromServerReader("")).toBe(ORGANISATION);
    expect(fromServerReader("finance")).toBe("finance");
  });
  it("makes a function group's id from a typed name", () => {
    expect(groupIdOf("Buying & Merchandising")).toBe("buying-merchandising");
  });
  it("names the button after the range", () => {
    expect(writeLabel("week", false)).toBe("Write this week's edition");
    expect(writeLabel("range", true)).toBe("Write this range's edition");
  });
  it("colours a figure only when the guide says which way is good", () => {
    const fig = { better: "up", current: 645, usual: { mean: 590 } } as unknown as EditionFigure;
    expect(toneOf(fig)).toBe("good");
    expect(toneOf({ ...fig, better: "none" })).toBe("neutral");
  });
});

describe("an edition's numbers", () => {
  it("words a value by its unit", () => {
    expect(fmtValue(0.0205, "ratio 0..1")).toBe("2.05%");
    expect(fmtValue(0.476, "ratio 0..1")).toBe("47.6%");
    expect(fmtValue(47.55, "%")).toBe("47.5%");
    expect(fmtValue(166988, "EUR")).toBe("€167.0K");
    expect(fmtValue(259, "")).toBe("259");
    expect(fmtValue(null, "EUR")).toBe("—");
  });
  it("words a change with its sign — a share in points", () => {
    expect(fmtChange(38840, 29849, "EUR")).toBe("+30%");
    expect(fmtChange(9845, 11051, "")).toBe("−11%");
    expect(fmtChange(0.0205, 0.0227, "ratio 0..1")).toBe("−0.22 pt");
  });
  it("reads citations out of the words", () => {
    expect(parseCited("Sales were {€167.0k|sales}, an ordinary week.")).toEqual([
      { text: "Sales were " }, { text: "€167.0k", source: "sales" }, { text: ", an ordinary week." }]);
  });
});

describe("bridges and drills", () => {
  const breakdown = src({ id: "by_top", kind: "breakdown", columns: ["segment", "this_range", "usual", "change", "change_pct", "rows", "too_few"],
    rows: [[true, 85349, 75932, 9417, 0.124, 70, false], [false, 81640, 85028, -3388, -0.04, 189, false]],
    facts: { check: "sales", by: "is_top", within: {} } });
  it("bridges a breakdown from its usual total through each segment to this range's total", () => {
    expect(bridgeSteps({ id: "b", type: "bridge", source: "by_top" }, { by_top: breakdown })).toEqual([
      { label: "A usual range", value: 160960, kind: "base" }, { label: "Yes", value: 9417, kind: "delta" },
      { label: "No", value: -3388, kind: "delta" }, { label: "This range", value: 166989, kind: "total" }]);
  });
  it("bridges a chain of checks through their differences", () => {
    const s = { a: src({ id: "a", label: "Sales", kind: "check", facts: { current: 166988 } }),
                b: src({ id: "b", label: "Net revenue", kind: "check", facts: { current: 150773 } }) };
    expect(bridgeSteps({ id: "x", type: "bridge", chain: ["a", "b"] } as EditionBlock, s).map(x => x.value))
      .toEqual([166988, -16215, 150773]);
  });
  it("offers a check's drill columns, and a breakdown's others within its top segment", () => {
    const check = src({ id: "sales", kind: "check" });
    const cols = { sales: ["platform", "is_top", "channel"] };
    expect(drillOptions({ id: "f", type: "figure", source: "sales" }, { sales: check }, cols).map(d => d.column))
      .toEqual(["platform", "is_top", "channel"]);
    expect(drillOptions({ id: "b", type: "bridge", source: "by_top" }, { by_top: breakdown }, cols))
      .toEqual([{ column: "platform", segment: true }, { column: "channel", segment: true }]);
    expect(drillOptions({ id: "t", type: "table", source: "q" }, { q: src({ id: "q" }) }, cols)).toEqual([]);
  });
});
