/**
 * Hand edits (Arc CT, CT-8). Every edit must leave a spec the rules accept — the same rules the
 * server keeps it by — and must not touch the spec it was given.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  addAction, cardsPlaced, moveCardTo, moveCardToNewSection, moveSectionTo, moveSectionToNewTab, moveWithin,
  placeCard, placePiece, rename, sectionsOf, tabsOf, takeOff, takeOffCard, type CockpitSpec,
} from "@/lib/cockpit/edit";
import { checkCockpitSpec } from "@/lib/cockpit/rules";

const premise = (): CockpitSpec =>
  JSON.parse(readFileSync(resolve(process.cwd(), "lib/cockpit/premise.fixture.json"), "utf8"));

/** A spec the rules accept, or the rules' own sentences as the failure. */
function accepted(spec: CockpitSpec): CockpitSpec {
  const check = checkCockpitSpec(spec);
  expect(check.issues.map(i => i.message)).toEqual([]);
  return spec;
}

const children = (s: CockpitSpec, key: string) => s.elements[key]?.children;

describe("reading a spec", () => {
  it("lists the sections in draw order, with the tab each is on", () => {
    expect(sectionsOf(premise())).toEqual([
      { key: "sec-headline", title: "Headline", tabKey: "tab-overview", tabLabel: "Overview" },
      { key: "sec-limits", title: "Limits", tabKey: "tab-watches", tabLabel: "Watches" },
    ]);
    expect(tabsOf(premise()).map(t => t.label)).toEqual(["Overview", "Watches"]);
    expect(cardsPlaced(premise())).toEqual(["c7f3a001", "c91b2002"]);      // placed three times, listed once
  });
});

describe("each edit", () => {
  it("leaves the spec it was given as it was", () => {
    const before = premise();
    const frozen = JSON.stringify(before);
    takeOff(before, "card-net");
    moveWithin(before, "card-net", -1);
    moveCardTo(before, "card-net", "sec-limits");
    rename(before, "sec-headline", "At a glance");
    moveSectionToNewTab(before, "sec-limits", "Later");
    expect(JSON.stringify(before)).toBe(frozen);
  });

  it("takes a card off, and a section, tab and row of tabs left empty go with it", () => {
    const one = accepted(takeOff(premise(), "card-net"));
    expect(children(one, "sec-headline")).toEqual(["alert-rate", "card-rate"]);
    expect(one.elements["card-net"]).toBeUndefined();

    const noLimits = accepted(takeOff(premise(), "watch-rate"));          // the section's only card
    expect(noLimits.elements["sec-limits"]).toBeUndefined();
    expect(noLimits.elements["tab-watches"]).toBeUndefined();
    expect(children(noLimits, "tabs")).toEqual(["tab-overview"]);
  });

  it("takes a card off wherever it is placed, and nothing else", () => {
    const s = takeOffCard(premise(), "c7f3a001");
    expect(cardsPlaced(s)).toEqual(["c91b2002"]);
    expect(children(s, "sec-headline")).toEqual(["card-net"]);
    // A condition that read the card's status went with the section it stood on.
    expect(s.elements["sec-limits"]).toBeUndefined();
    accepted(s);
  });

  it("does not leave the cockpit opening on a tab it took away", () => {
    const s = premise();
    s.state = { tab: "watches" };
    const after = accepted(takeOff(s, "watch-rate"));
    expect(after.state).toEqual({ tab: "overview" });
  });

  it("moves a card earlier and later among its neighbours, and no further", () => {
    const s = accepted(moveWithin(premise(), "card-net", -1));
    expect(children(s, "sec-headline")).toEqual(["alert-rate", "card-net", "card-rate"]);
    expect(children(moveWithin(premise(), "alert-rate", -1), "sec-headline")).toEqual(["alert-rate", "card-rate", "card-net"]);
    expect(children(moveWithin(premise(), "card-net", 1), "sec-headline")).toEqual(["alert-rate", "card-rate", "card-net"]);
  });

  it("moves a card to another section, and to a new one after its own", () => {
    const s = accepted(moveCardTo(premise(), "card-net", "sec-limits"));
    expect(children(s, "sec-limits")).toEqual(["watch-rate", "card-net"]);
    expect(children(s, "sec-headline")).toEqual(["alert-rate", "card-rate"]);

    const fresh = accepted(moveCardToNewSection(premise(), "card-net", "Revenue"));
    const added = children(fresh, "tab-overview")!;
    expect(added[0]).toBe("sec-headline");
    expect(fresh.elements[added[1]]).toEqual({ type: "Section", props: { title: "Revenue" }, children: ["card-net"] });
    expect(moveCardToNewSection(premise(), "card-net", "   ")).toEqual(premise());   // no name, no section
  });

  it("moving a section's last card out takes the emptied section away", () => {
    const s = accepted(moveCardTo(premise(), "watch-rate", "sec-headline"));
    expect(s.elements["sec-limits"]).toBeUndefined();
    expect(s.elements["tab-watches"]).toBeUndefined();
    expect(children(s, "sec-headline")).toEqual(["alert-rate", "card-rate", "card-net", "watch-rate"]);
  });

  it("places a card the person has, in a section of its own key", () => {
    const s = accepted(placeCard(premise(), "c0ffee01", "sec-limits"));
    expect(children(s, "sec-limits")).toEqual(["watch-rate", "card-c0ffee01"]);
    const twice = accepted(placeCard(s, "c0ffee01", "sec-headline"));
    expect(children(twice, "sec-headline")).toContain("card-c0ffee01-2");  // a key is an element's own
    expect(children(placeCard(premise(), "c0ffee01"), "sec-headline")).toContain("card-c0ffee01");  // the first section
  });

  it("renames the cockpit, a section and a tab, and an empty name changes nothing", () => {
    let s = rename(premise(), "cockpit", "Returns watch");
    s = rename(s, "sec-headline", "At a glance");
    s = accepted(rename(s, "tab-watches", "Limits"));
    expect(s.elements["cockpit"].props.title).toBe("Returns watch");
    expect(s.elements["sec-headline"].props.title).toBe("At a glance");
    expect(s.elements["tab-watches"].props.label).toBe("Limits");
    expect(s.elements["tab-watches"].props.name).toBe("watches");          // what a condition reads stays put
    expect(rename(premise(), "sec-headline", "  ")).toEqual(premise());
    expect(rename(premise(), "card-net", "Anything")).toEqual(premise());   // a card's title is the card's
  });

  it("moves a section to another tab, and to a new tab", () => {
    const s = accepted(moveSectionTo(premise(), "sec-limits", "tab-overview"));
    expect(children(s, "tab-overview")).toEqual(["sec-headline", "sec-limits"]);
    expect(s.elements["tab-watches"]).toBeUndefined();

    const t = accepted(moveSectionToNewTab(premise(), "sec-limits", "Watching"));
    expect(tabsOf(t).map(x => [x.name, x.label])).toEqual([["overview", "Overview"], ["watching", "Watching"]]);
  });

  it("gives a cockpit with no tabs its first two: what it held, and the new one", () => {
    const flat: CockpitSpec = { root: "c", elements: {
      c: { type: "Cockpit", props: { title: "Returns" }, children: ["s1", "s2"] },
      s1: { type: "Section", props: { title: "Headline" }, children: ["k1"] },
      s2: { type: "Section", props: { title: "Detail" }, children: ["k2"] },
      k1: { type: "Card", props: { card: "c1" }, children: [] },
      k2: { type: "Card", props: { card: "c2" }, children: [] },
    } };
    const t = accepted(moveSectionToNewTab(flat, "s2", "Detail"));
    expect(tabsOf(t).map(x => x.label)).toEqual(["Overview", "Detail"]);
    expect(sectionsOf(t).map(x => [x.title, x.tabLabel])).toEqual([["Headline", "Overview"], ["Detail", "Detail"]]);
    expect(t.state).toEqual({ tab: "overview" });
  });

  it("taking the last card off leaves an empty cockpit, which the rules refuse in their own words", () => {
    let s: CockpitSpec = { root: "c", elements: {
      c: { type: "Cockpit", props: { title: "One" }, children: ["s"] },
      s: { type: "Section", props: { title: "Only" }, children: ["k"] },
      k: { type: "Card", props: { card: "c1" }, children: [] },
    } };
    s = takeOff(s, "k");
    expect(checkCockpitSpec(s).valid).toBe(false);
    expect(checkCockpitSpec(s).issues.map(i => i.message).join(" ")).toContain("holds nothing");
  });
});

describe("the ontology's pieces (Arc OC-4)", () => {
  const built = () => {
    const first = sectionsOf(premise())[0].key;
    let { spec, key: board } = placePiece(premise(), "ProcessBoard", { process: "order_fulfilment", size: "full" }, first);
    const t = placePiece(spec, "ObjectTable", { entity: "Order", segment: "overdue_dispatch", columns: [], sort: null }, first);
    const d = placePiece(t.spec, "ObjectDetail", { follows: t.key }, first);
    spec = addAction(d.spec, d.key as string, "flag_for_review");
    return { spec, board: board as string, table: t.key as string, detail: d.key as string };
  };

  it("places a board, a table and a detail that follows it, with a declared action's button — and the rules accept it", () => {
    const { spec, board, table, detail } = built();
    accepted(spec);
    expect(spec.elements[table].props).toEqual({ entity: "Order", segment: "overdue_dispatch" });   // empties left out
    expect(spec.elements[detail].props).toEqual({ follows: table });
    const [button] = children(spec, detail);
    expect(spec.elements[button]).toEqual({ type: "ActionButton", props: { action: "flag_for_review" }, children: [] });
    expect(addAction(spec, detail, "flag_for_review")).toEqual(spec);                               // once
    expect(spec.elements[board].props.process).toBe("order_fulfilment");
  });

  it("taking a table off takes the detail that follows it, and the detail's buttons", () => {
    const { spec, table, detail } = built();
    const [button] = children(spec, detail);
    const after = accepted(takeOff(spec, table));
    for (const k of [table, detail, button]) expect(after.elements[k]).toBeUndefined();
  });

  it("taking the last button off leaves the detail standing, empty", () => {
    const { spec, detail } = built();
    const after = accepted(takeOff(spec, children(spec, detail)[0]));
    expect(after.elements[detail]?.children).toEqual([]);
  });
});
