/**
 * An edit to a cockpit, applied strictly (Arc CT, CT-5). Every refusal is asserted by a token
 * of its own sentence, and every one of them leaves the spec it was handed untouched.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { applySpecPatch } from "@json-render/core";
import { describe, expect, it } from "vitest";

import { MAX_PATCHES, applyCockpitPatches } from "@/lib/cockpit/patch";
import { checkCockpitSpec } from "@/lib/cockpit/rules";

type Spec = { root: string; state?: unknown; elements: Record<string, Record<string, unknown>> };

const premise = (): Spec =>
  JSON.parse(readFileSync(resolve(process.cwd(), "lib/cockpit/premise.fixture.json"), "utf8"));

function edited(patches: unknown[]): Spec {
  const before = premise();
  const out = applyCockpitPatches(before, patches);
  expect(out.issues).toEqual([]);
  expect(out.ok).toBe(true);
  expect(before).toEqual(premise());          // the spec handed in is never changed
  return out.spec as Spec;
}

function refused(patches: unknown, spec: unknown = premise()): string {
  const before = JSON.stringify(spec);
  const out = applyCockpitPatches(spec, patches);
  expect(out.ok).toBe(false);
  expect(out.spec).toBeNull();
  expect(JSON.stringify(spec)).toBe(before);
  return out.issues.map(i => `${i.index}: ${i.message}`).join("\n");
}

describe("an edit that does what it says", () => {
  it("renames a section", () => {
    const spec = edited([{ op: "replace", path: "/elements/sec-headline/props/title", value: "At a glance" }]);
    const before = premise().elements["sec-headline"].props as Record<string, unknown>;
    expect(spec.elements["sec-headline"].props).toEqual({ ...before, title: "At a glance" });
    expect(checkCockpitSpec(spec).valid).toBe(true);
  });

  it("moves a card to the end of another section, in two operations that depend on each other", () => {
    const spec = edited([
      { op: "remove", path: "/elements/sec-headline/children/2" },
      { op: "add", path: "/elements/sec-limits/children/-", value: "card-net" },
    ]);
    expect(spec.elements["sec-headline"].children).toEqual(["alert-rate", "card-rate"]);
    expect(spec.elements["sec-limits"].children).toEqual(["watch-rate", "card-net"]);
    expect(checkCockpitSpec(spec).valid).toBe(true);
  });

  it("adds at a position, moves, copies and tests", () => {
    const spec = edited([
      { op: "test", path: "/elements/cockpit/props/title", value: "Returns" },
      { op: "add", path: "/elements/sec-headline/children/0", value: "first" },
      { op: "copy", from: "/elements/card-net", path: "/elements/first" },
      { op: "move", from: "/elements/sec-headline/children/0", path: "/elements/sec-headline/children/-" },
    ]);
    expect(spec.elements["sec-headline"].children).toEqual(["alert-rate", "card-rate", "card-net", "first"]);
    expect(spec.elements.first).toEqual(premise().elements["card-net"]);
  });

  it("reads a key that holds a slash or a tilde", () => {
    const spec = { root: "a", elements: { "a/b": { v: 1 }, "c~d": { v: 2 } } };
    const out = applyCockpitPatches(spec, [
      { op: "replace", path: "/elements/a~1b/v", value: 10 },
      { op: "replace", path: "/elements/c~0d/v", value: 20 },
    ]);
    expect(out.spec).toEqual({ root: "a", elements: { "a/b": { v: 10 }, "c~d": { v: 20 } } });
  });

  it("keeps no hold on the value it was given", () => {
    const value = { type: "Card", props: { card: "c91b2002" }, children: [] as string[] };
    const spec = edited([{ op: "add", path: "/elements/spare", value }]);
    value.props.card = "changed-after";
    expect((spec.elements.spare.props as { card: string }).card).toBe("c91b2002");
  });
});

describe("an edit that is refused whole", () => {
  it.each([
    ["replacing what is not there", { op: "replace", path: "/elements/ghost/props/title", value: "x" }, /"\/elements\/ghost\/props\/title" is not in the spec/],
    // Its holder is there and the key is not: the case a lenient applier turns into an add.
    ["replacing a key its holder does not have", { op: "replace", path: "/elements/cockpit/props/subtitle", value: "x" }, /"\/elements\/cockpit\/props\/subtitle" is not in the spec/],
    ["replacing a position a list does not have", { op: "replace", path: "/elements/sec-limits/children/3", value: "x" }, /"\/elements\/sec-limits\/children\/3" is not in the spec/],
    ["removing what is not there", { op: "remove", path: "/elements/ghost" }, /"\/elements\/ghost" is not in the spec/],
    ["adding beneath what is not there", { op: "add", path: "/elements/ghost/props/title", value: "x" }, /is not in the spec/],
    ["an operation nobody has heard of", { op: "explode", path: "/elements/cockpit" }, /its "op" is "explode"; an operation is one of: add, remove, replace, move, copy, test/],
    ["the whole spec at once", { op: "replace", path: "", value: { root: "x", elements: {} } }, /is the whole spec; an edit changes a part/],
    ["a path with no slash", { op: "remove", path: "elements/cockpit" }, /does not begin with "\/"/],
    ["a path that is no string", { op: "remove", path: 7 }, /its path is 7/],
    ["a position past the end", { op: "add", path: "/elements/sec-limits/children/5", value: "x" }, /position "5" of a list of 1/],
    ["a position that is no number", { op: "add", path: "/elements/sec-limits/children/last", value: "x" }, /position "last"/],
    ["a test that does not hold", { op: "test", path: "/elements/cockpit/props/title", value: "Sales" }, /holds "Returns", not "Sales"; the cockpit is not as the edit took it to be/],
    ["a value left out", { op: "replace", path: "/elements/cockpit/props/title" }, /"replace" carries no "value"/],
    ["a move into itself", { op: "move", from: "/elements/cockpit", path: "/elements/cockpit/props/x" }, /moves "\/elements\/cockpit" into itself/],
    ["a copy from nowhere", { op: "copy", from: "/elements/ghost", path: "/elements/new" }, /"\/elements\/ghost" is not in the spec/],
    ["a reach for the prototype", { op: "add", path: "/elements/__proto__/polluted", value: true }, /names "__proto__", which no spec holds/],
    ["something that is no operation", "remove the title", /an operation is an object/],
  ])("%s", (_what, patch, sentence) => {
    const said = refused([patch]);
    expect(said).toMatch(sentence);
    expect(said).toMatch(/^1: Operation 1 of 1 is refused/);
    expect(said).toMatch(/Nothing was changed\.$/);
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });

  it("names the operation that failed, and keeps nothing of the ones before it", () => {
    const said = refused([
      { op: "replace", path: "/elements/cockpit/props/title", value: "Changed" },
      { op: "remove", path: "/elements/ghost" },
      { op: "replace", path: "/elements/sec-limits/props/title", value: "Never reached" },
    ]);
    expect(said).toMatch(/^2: Operation 2 of 3 is refused/);
  });

  it.each([
    ["no operations", []],
    ["something that is no list", { op: "remove", path: "/elements/cockpit" }],
    ["nothing", undefined],
  ])("an edit of %s", (_what, patches) => {
    expect(refused(patches)).toMatch(/An edit is a list of operations, and this one holds none/);
  });

  it("an edit larger than an edit may be", () => {
    const many = Array.from({ length: MAX_PATCHES + 1 }, () => ({ op: "test", path: "/root", value: "cockpit" }));
    expect(refused(many)).toMatch(new RegExp(`holds ${MAX_PATCHES + 1} operations\\. An edit holds at most ${MAX_PATCHES}`));
  });

  it("an edit of no cockpit", () => {
    expect(refused([{ op: "remove", path: "/root" }], null)).toMatch(/There is no cockpit to edit/);
  });
});

describe("why the library's own function is not used", () => {
  // Measured on 0.21.0. If a later version turns strict these fail, and this file can be reconsidered.
  it("it creates what a replace did not find", () => {
    const spec = premise();
    applySpecPatch(spec as never, { op: "replace", path: "/elements/ghost/props/title", value: "x" } as never);
    expect(spec.elements.ghost).toEqual({ props: { title: "x" } });
  });

  it("it passes over a remove of nothing, and an operation it has never heard of", () => {
    const spec = premise();
    applySpecPatch(spec as never, { op: "remove", path: "/elements/ghost" } as never);
    applySpecPatch(spec as never, { op: "explode", path: "/elements/cockpit" } as never);
    expect(spec).toEqual(premise());
  });
});
