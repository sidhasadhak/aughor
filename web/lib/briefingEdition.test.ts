/** Arc BG — the words an edition's page puts around what the server measured. */
import { describe, expect, it } from "vitest";

import type { EditionFigure } from "@/lib/api";
import { ORGANISATION, fromServerReader, groupIdOf, kickerOf, readerOptions, toServerReader, toneOf, writeLabel } from "./briefingEdition";

const fig = (over: Partial<EditionFigure> = {}): EditionFigure => ({
  id: "aov", label: "Average order", metric: null, unit: "EUR", better: "up", why: "", current: 645, previous: 623,
  last_year: null, rel: 0.035, rel_last_year: null, n: 259, status: "final",
  usual: { mean: 590, low: 566, high: 614, n: 8, mean_text: "€590", low_text: "€566", high_text: "€614" },
  z: 2.3, outside: true, floor: true, streak: 2, extreme: null, series: [], cells: {}, current_text: "€645",
  previous_text: "€623", last_year_text: null, like_for_like: "", sql: "", ...over,
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
    expect(toServerReader("finance")).toBe("finance");
    expect(fromServerReader("")).toBe(ORGANISATION);
    expect(fromServerReader(undefined)).toBe(ORGANISATION);
  });
  it("makes a function group's id from a typed name", () => {
    expect(groupIdOf("Buying & Merchandising")).toBe("buying-merchandising");
    expect(groupIdOf("  Mytheresa app team ")).toBe("mytheresa-app-team");
  });
});

describe("a story's kicker and a figure's tone", () => {
  it("says why a story is there, in the range's own word", () => {
    expect(kickerOf({ reason: "unusual" }, fig(), "week")).toBe("Far outside its usual range");
    expect(kickerOf({ reason: "unusual" }, fig({ floor: false, z: -1.4 }), "week")).toBe("Below its usual range");
    expect(kickerOf({ reason: "streak" }, fig({ streak: -3 }), "week")).toBe("3 weeks in a row down");
    expect(kickerOf({ reason: "streak" }, fig({ streak: 2 }), "month")).toBe("2 months in a row up");
    expect(kickerOf({ reason: "new_level" }, fig(), "week")).toBe("Holding a new level");
    expect(kickerOf({ reason: "watch" }, fig(), "week")).toBe("Your watch");
  });
  it("colours a figure only when the guide says which way is good", () => {
    expect(toneOf(fig())).toBe("good");
    expect(toneOf(fig({ better: "down" }))).toBe("bad");
    expect(toneOf(fig({ better: "none" }))).toBe("neutral");
    expect(toneOf(fig({ usual: null }))).toBe("neutral");
  });
  it("names the button after the range", () => {
    expect(writeLabel("week", false)).toBe("Write this week's edition");
    expect(writeLabel("month", false)).toBe("Write this month's edition");
    expect(writeLabel("range", true)).toBe("Write this range's edition");
  });
});
