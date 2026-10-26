/**
 * Arc FA-2 — the subject a question carries from a dashboard, held in memory: said in a line, sent as the ask door's
 * focus (references, or a set by name — never what the set reads), and the dashboard named by a page's key.
 */
import { afterEach, describe, expect, it } from "vitest";

import { askSubject, dashboardOf, focusOf, nounOf, setAskSubject, subjectWords, type AskSubject } from "@/lib/askSubject";

const TICKED: AskSubject = { kind: "objects", connectionId: "thelook", noun: nounOf("Order"), label: "Late dispatch",
  refs: Array.from({ length: 12 }, (_, i) => `order:${48200 + i}`) };
const SET: AskSubject = { kind: "set", connectionId: "thelook", noun: nounOf("DistributionCenter"), dashboard: "desk-3f2a1c",
  set: "late", label: "Late dispatch", total: 1400, values: { window: 14 }, chosen: {}, filters: [], narrowed: false };

afterEach(() => setAskSubject(null));

describe("the subject a question carries", () => {
  it("is said in a line, as the canvas shows it above its input", () => {
    expect(subjectWords(TICKED)).toBe("Asking about 12 orders · from Late dispatch");
    expect(subjectWords({ ...TICKED, refs: ["order:1"], label: undefined })).toBe("Asking about 1 order");
    expect(subjectWords(SET)).toBe("Asking about Late dispatch · 1,400 distribution centers");
    expect(subjectWords({ ...SET, total: null, narrowed: true })).toBe("Asking about Late dispatch · narrowed by your filters");
  });

  it("is sent as references, or as a set by its name with the page's values — never what the set reads", () => {
    expect(focusOf(TICKED)).toEqual({ kind: "objects", objects: TICKED.kind === "objects" ? TICKED.refs : [], label: "Late dispatch" });
    expect(focusOf(SET)).toEqual({ kind: "set", dashboard: "desk-3f2a1c", set: "late", values: { window: 14 }, chosen: {}, filters: [] });
    const segment: AskSubject = { kind: "segment", connectionId: "thelook", noun: nounOf("Order"), entity: "order",
      segment: "overdue_dispatch", label: "overdue dispatch", total: 24934, filters: [], narrowed: false };
    expect(focusOf(segment)).toEqual({ kind: "set", entity: "order", segment: "overdue_dispatch", label: "overdue dispatch",
      filters: [], narrowed: false });
    expect(subjectWords(segment)).toBe("Asking about overdue dispatch · 24,934 orders");
    const many = { ...TICKED, refs: Array.from({ length: 70 }, (_, i) => `order:${i}`) };
    expect((focusOf(many).objects as string[]).length).toBe(50);
  });

  it("is held in memory until it is taken off", () => {
    setAskSubject(TICKED);
    expect(askSubject()).toBe(TICKED);
    setAskSubject(null);
    expect(askSubject()).toBeNull();
  });

  it("names the dashboard a page's key names, and none for a key that names none", () => {
    expect(dashboardOf("thelook:desk-3f2a1c", "thelook")).toEqual({ dashboard: "desk-3f2a1c" });
    expect(dashboardOf("thelook:desk-3f2a1c:preview", "thelook")).toEqual({ dashboard: "desk-3f2a1c" });
    expect(dashboardOf("shared:ana:desk-3f2a1c", "thelook")).toEqual({ dashboard: "desk-3f2a1c", owner: "ana" });
    expect(dashboardOf("thelook:shared:ana:desk-3f2a1c", "thelook")).toEqual({ dashboard: "desk-3f2a1c", owner: "ana" });
    expect(dashboardOf(undefined, "thelook")).toBeNull();
    expect(dashboardOf("other:desk", "thelook")).toBeNull();
    expect(dashboardOf("thelook:Not An Id", "thelook")).toBeNull();
  });
});
