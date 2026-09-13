/**
 * SE-8C — the resolution rules: what a widget's stored value becomes at bind time.
 * The wrong answer here binds silently — a token as a literal string, an empty
 * string as a value — so each case asserts the exact bind value.
 */
import { describe, expect, it } from "vitest";
import {
  isDynamicDate, resolveDynamicDate, resolveParamValue,
} from "@/lib/query/paramDefs";

// A Wednesday: 2026-09-16. Fixed so week/month arithmetic is assertable.
const NOW = new Date(2026, 8, 16, 14, 30);

describe("resolveDynamicDate", () => {
  it.each([
    ["today", "2026-09-16"],
    ["yesterday", "2026-09-15"],
    ["start of this week", "2026-09-14"],   // the Monday
    ["start of last week", "2026-09-07"],
    ["start of this month", "2026-09-01"],
    ["start of last month", "2026-08-01"],
    ["start of this year", "2026-01-01"],
  ])("%s → %s", (token, expected) => {
    expect(resolveDynamicDate(token, NOW)).toBe(expected);
  });

  it("returns null for a literal date, which then binds as typed", () => {
    expect(resolveDynamicDate("2026-01-05", NOW)).toBeNull();
  });

  it("start of this week on a Monday is that Monday, not the week before", () => {
    expect(resolveDynamicDate("start of this week", new Date(2026, 8, 14))).toBe("2026-09-14");
  });

  it("start of last month in January crosses the year", () => {
    expect(resolveDynamicDate("start of last month", new Date(2026, 0, 15))).toBe("2025-12-01");
  });
});

describe("resolveParamValue", () => {
  it("an empty string is UNFILLED, never a bound empty string", () => {
    expect(resolveParamValue({ widget: "text" }, "  ")).toBeUndefined();
    expect(resolveParamValue(undefined, undefined)).toBeUndefined();
  });

  it("a number widget binds a real number when the text parses", () => {
    expect(resolveParamValue({ widget: "number" }, "42")).toBe(42);
    expect(resolveParamValue({ widget: "number" }, "4.5")).toBe(4.5);
    // Unparseable text passes through — the engine's own error names the problem.
    expect(resolveParamValue({ widget: "number" }, "abc")).toBe("abc");
  });

  it("a date widget resolves a ⚡ token at bind time", () => {
    expect(resolveParamValue({ widget: "date" }, "today", NOW)).toBe("2026-09-16");
    expect(resolveParamValue({ widget: "date" }, "2026-02-02", NOW)).toBe("2026-02-02");
  });

  it("a multiselect binds its array, and an empty selection is unfilled", () => {
    expect(resolveParamValue({ widget: "multiselect" }, ["a", "b"])).toEqual(["a", "b"]);
    expect(resolveParamValue({ widget: "multiselect" }, [])).toBeUndefined();
  });

  it("isDynamicDate recognises tokens and only tokens", () => {
    expect(isDynamicDate("today")).toBe(true);
    expect(isDynamicDate("2026-09-16")).toBe(false);
    expect(isDynamicDate(["today"])).toBe(false);
  });
});
