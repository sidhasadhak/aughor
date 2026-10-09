/**
 * What the writer of a cockpit is told (Arc CT, CT-5). The grammar is held to the rules it
 * describes: a text that taught a spec the rules refuse would cost a model call every time it
 * was followed.
 */
import { describe, expect, it } from "vitest";

import { WRITTEN, PIECE_NAMES, MAY_BE_CONDITIONAL, TONES, cockpitCatalog } from "@/lib/cockpit/catalog";
import { GRAMMAR_EXAMPLE, grammar } from "@/lib/cockpit/grammar";
import { CARD_STATUSES, RANGE_STATUSES } from "@/lib/cockpit/hostState";
import { MAX_PATCHES } from "@/lib/cockpit/patch";
import { MAX_CARDS, MAX_ELEMENTS, MAX_TABS, checkCockpitSpec } from "@/lib/cockpit/rules";

describe("the grammar", () => {
  const text = grammar();

  it("teaches an example the rules accept", () => {
    const check = checkCockpitSpec(JSON.parse(JSON.stringify(GRAMMAR_EXAMPLE)));
    expect(check.issues).toEqual([]);
    expect(check.cards).toEqual(["return-rate", "net-revenue", "returns-by-category"]);
    expect(check.stateCards).toEqual(["return-rate"]);
    expect(text).toContain(JSON.stringify(GRAMMAR_EXAMPLE));
  });

  it("shows both kinds of condition, and a card placed twice", () => {
    const els = Object.values(GRAMMAR_EXAMPLE.elements) as { type: string; props: { card?: string }; visible?: unknown }[];
    const read = els.filter(e => e.visible).map(e => JSON.stringify(e.visible));
    expect(read.some(v => v.includes("/cards/"))).toBe(true);
    expect(read.some(v => v.includes("/range/status"))).toBe(true);
    expect(els.filter(e => e.props.card === "return-rate")).toHaveLength(2);
  });

  it("names every component, tone, status and limit the catalog holds", () => {
    for (const name of WRITTEN) expect(text).toContain(`- ${name}: `);
    // Arc OC-4 — the ontology's pieces are a person's to place, by hand: a writer is never taught one, so the text a
    // model reads is what it was before they existed.
    for (const name of PIECE_NAMES) expect(text).not.toContain(name);
    expect(text).toContain(`one of: ${TONES.join(", ")}`);
    expect(text).toContain(`one of: ${CARD_STATUSES.join(", ")}`);
    expect(text).toContain(`one of: ${RANGE_STATUSES.join(", ")}`);
    expect(text).toContain(`Only these may carry "visible": ${MAY_BE_CONDITIONAL.join(", ")}.`);
    expect(text).toContain(`At most ${MAX_ELEMENTS} elements, ${MAX_TABS} tabs, and ${MAX_CARDS} cards placed.`);
    expect(text).toContain(`at most ${MAX_PATCHES} operations`);
  });

  it("does not teach what a cockpit refuses", () => {
    // The library's own prompt spends most of its length on these.
    for (const word of ["\"on\"", "watch", "repeat", "$computed", "$template", "$cond", "action"]) {
      expect(text).not.toContain(word);
    }
  });

  it("is a tenth of the library's", () => {
    const theirs = cockpitCatalog.prompt().length;
    expect(theirs).toBeGreaterThan(10_000);
    expect(text.length).toBeLessThan(theirs / 3);
    expect(text.length).toBeLessThan(5_000);
  });
});
