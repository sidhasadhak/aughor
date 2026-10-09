/**
 * The cockpit's rules (Arc CT, CT-2). Every refusal is asserted by a token of ITS OWN
 * sentence, never by `valid === false` alone: a spec refused for a different reason than the
 * one under test would otherwise pass as proof of a rule that never ran.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { COCKPIT_VOCABULARY_VERSION, COMPONENT_NAMES, cockpitCatalog } from "@/lib/cockpit/catalog";
import { MAX_CARDS, MAX_ELEMENTS, MAX_TABS, checkCockpitSpec, openingTab, vocabulary } from "@/lib/cockpit/rules";

type Spec = { root: string; state?: unknown; elements: Record<string, Record<string, unknown>> } & Record<string, unknown>;

const premise = (): Spec =>
  JSON.parse(readFileSync(resolve(process.cwd(), "lib/cockpit/premise.fixture.json"), "utf8"));

/** The premise with one change, and the sentences it is refused with. */
function refused(change: (s: Spec) => void): string {
  const spec = premise();
  change(spec);
  const check = checkCockpitSpec(spec);
  expect(check.valid).toBe(false);
  expect(check.cards).toEqual([]);
  expect(check.texts).toEqual([]);
  return check.issues.map(i => i.message).join("\n");
}

describe("the catalog", () => {
  it("declares seven components and no action", () => {
    expect(cockpitCatalog.componentNames).toEqual([...COMPONENT_NAMES]);
    expect(cockpitCatalog.actionNames).toEqual([]);
  });

  it("publishes its vocabulary for the server to read", () => {
    expect(vocabulary()).toEqual({
      version: COCKPIT_VOCABULARY_VERSION,
      components: ["Cockpit", "Tabs", "Tab", "Section", "Card", "Note", "Image"],
      tones: ["good", "warn", "bad", "info", "neutral"],
      sizes: ["small", "wide", "tall", "large", "full", "hero"],
      range_statuses: ["standing", "final", "provisional", "to_date"],
      card_statuses: ["within", "over", "unmeasured", "withheld"],
      limits: { elements: MAX_ELEMENTS, tabs: MAX_TABS, cards: MAX_CARDS },
    });
    expect(COCKPIT_VOCABULARY_VERSION).toBe(2);
  });
});

describe("a note, an image and a size (the canvas, 2026-10-08)", () => {
  const withStatics = (): Spec => {
    const spec = premise();
    spec.elements["note-1"] = { type: "Note", props: { text: "Target for Q4: under **10%**.", size: "wide" }, children: [] };
    spec.elements["image-1"] = { type: "Image", props: { object: "ab12cd34ef56", caption: "Q4 promo calendar", size: "tall" }, children: [] };
    (spec.elements["sec-headline"].children as string[]).push("note-1", "image-1");
    return spec;
  };

  it("are placed in a section like a card, counted as elements and not as cards", () => {
    const check = checkCockpitSpec(withStatics());
    expect(check.issues).toEqual([]);
    expect(check.cards).toEqual(["c7f3a001", "c91b2002"]);
    // A note's words are the person's: they are not reader text a model is held to.
    expect(check.texts.map(t => t.elementKey)).not.toContain("note-1");
  });

  it("take a size from the closed set, and only one of its names", () => {
    const spec = withStatics();
    (spec.elements["card-rate"].props as Record<string, unknown>).size = "large";
    expect(checkCockpitSpec(spec).valid).toBe(true);
    expect(refused(s => { (s.elements["card-rate"].props as Record<string, unknown>).size = "huge"; })).toContain("\"size\"");
    expect(refused(s => { (s.elements["card-rate"].props as Record<string, unknown>).size = { w: 2, h: 2 }; })).toContain("\"size\"");
  });

  it("hold nothing and may be shown by a condition", () => {
    const spec = withStatics();
    spec.elements["note-1"].visible = { $state: "/range/status", neq: "to_date" };
    expect(checkCockpitSpec(spec).valid).toBe(true);
    const said = refused(s => {
      s.elements["note-1"] = { type: "Note", props: { text: "x" }, children: ["card-net"] };
      (s.elements["sec-headline"].children as string[]).push("note-1");
    });
    expect(said).toContain("A Note holds nothing");
  });

  it("refuse an empty note, a note too long, an image with no caption and a tab holding a note", () => {
    expect(refused(s => { s.elements["note-1"] = { type: "Note", props: { text: "" }, children: [] }; (s.elements["sec-headline"].children as string[]).push("note-1"); }))
      .toContain("\"text\"");
    expect(refused(s => { s.elements["note-1"] = { type: "Note", props: { text: "x".repeat(2001) }, children: [] }; (s.elements["sec-headline"].children as string[]).push("note-1"); }))
      .toContain("\"text\"");
    expect(refused(s => { s.elements["image-1"] = { type: "Image", props: { object: "ab12" }, children: [] }; (s.elements["sec-headline"].children as string[]).push("image-1"); }))
      .toContain("\"caption\"");
    expect(refused(s => { s.elements["note-1"] = { type: "Note", props: { text: "x" }, children: [] }; (s.elements["tab-overview"].children as string[]).push("note-1"); }))
      .toContain("A Tab holds: Section");
  });
});

describe("the premise spec", () => {
  it("is accepted, and hands back what only the server can check", () => {
    const check = checkCockpitSpec(premise());
    expect(check.issues).toEqual([]);
    expect(check.valid).toBe(true);
    expect(check.cards).toEqual(["c7f3a001", "c91b2002"]);
    expect(check.stateCards).toEqual(["c7f3a001"]);
    expect(check.texts).toEqual([
      { elementKey: "cockpit", prop: "title", text: "Returns" },
      { elementKey: "tab-overview", prop: "label", text: "Overview" },
      { elementKey: "sec-headline", prop: "title", text: "Headline" },
      { elementKey: "tab-watches", prop: "label", text: "Watches" },
      { elementKey: "sec-limits", prop: "title", text: "Limits" },
    ]);
  });

  it("opens on the tab it seeds, and on its first tab when it seeds none", () => {
    expect(openingTab(premise())).toBe("overview");
    const spec = premise();
    delete spec.state;
    spec.elements.tabs.children = ["tab-watches", "tab-overview"];
    expect(checkCockpitSpec(spec).valid).toBe(true);
    expect(openingTab(spec)).toBe("watches");
  });

  it("may be sections with no tabs at all", () => {
    const spec = premise();
    delete spec.state;
    spec.elements.cockpit.children = ["sec-headline"];
    for (const k of ["tabs", "tab-overview", "tab-watches", "sec-limits", "watch-rate"]) delete spec.elements[k];
    const check = checkCockpitSpec(spec);
    expect(check.issues).toEqual([]);
    expect(openingTab(spec)).toBeNull();
  });
});

describe("what the library's own validator lets through, and these rules do not", () => {
  // Measured in CT-1: `catalog.validate` accepted all three. They are the reason `checkProps` exists.
  it("a tone outside the list", () => {
    expect(refused(s => { s.elements["alert-rate"].props = { card: "c7f3a001", tone: "loud" }; }))
      .toMatch(/"alert-rate" has a problem with "tone"/);
  });

  it("a number where a card id belongs", () => {
    expect(refused(s => { s.elements["card-net"].props = { card: 42 }; }))
      .toMatch(/"card-net" has a problem with "card"/);
  });

  it("a prop nobody declared", () => {
    expect(refused(s => { s.elements["card-net"].props = { card: "c91b2002", value: "8.1M" }; }))
      .toMatch(/"card-net" has a problem with its props: Unrecognized key/);
  });
});

describe("what a spec may not carry", () => {
  it.each([
    ["watch", { "/tab": { action: "anything" } }, /runs nothing without a click/],
    ["on", { press: { action: "anything" } }, /defines no action of its own/],
    ["repeat", { statePath: "/cards" }, /places each card by its id/],
    ["slots", { header: ["card-net"] }, /holds its elements in "children"/],
  ])("%s", (field, value, sentence) => {
    const said = refused(s => { s.elements["card-rate"][field] = value; });
    expect(said).toMatch(sentence);
    expect(said).toContain(`"card-rate" carries "${field}"`);
  });

  it("a field it has never heard of", () => {
    expect(refused(s => { s.elements["card-rate"].script = "alert(1)"; }))
      .toMatch(/"card-rate" carries "script"\. An element holds "type", "props", "children" and "visible"/);
  });

  it("a component outside the catalog", () => {
    expect(refused(s => { s.elements["card-rate"].type = "Iframe"; }))
      .toMatch(/"card-rate" is a "Iframe"\. A cockpit is made of: Cockpit, Tabs, Tab, Section, Card/);
  });

  it.each([
    ["$state", { $state: "/cards/c7f3a001/status" }],
    ["$computed", { $computed: "pick", args: {} }],
    ["$template", { $template: "${/tab}" }],
    ["$cond", { $cond: { $state: "/tab" }, $then: "a", $else: "b" }],
  ])("a card id set from %s", (expr, value) => {
    expect(refused(s => { s.elements["card-net"].props = { card: value }; }))
      .toContain(`"card-net" sets "card" from an expression (${expr})`);
  });

  it("a title set from an expression, however deep it hides", () => {
    expect(refused(s => { s.elements["sec-headline"].props = { title: { a: [{ $state: "/tab" }] } }; }))
      .toContain("\"sec-headline\" sets \"title\" from an expression ($state)");
  });

  it("tabs bound to anything but the open tab", () => {
    expect(refused(s => { s.elements.tabs.props = { value: { $bindState: "/cards/c7f3a001/status" } }; }))
      .toMatch(/tabs "tabs" must carry "value": \{"\$bindState": "\/tab"\}/);
    expect(refused(s => { s.elements.tabs.props = { value: "overview" }; }))
      .toMatch(/tabs "tabs" must carry "value"/);
  });

  it("a top-level key beside root, elements and state", () => {
    expect(refused(s => { s.functions = { pick: "x" }; })).toMatch(/The spec carries "functions"/);
  });
});

describe("the state a spec may seed", () => {
  it("is the open tab and nothing else — a card's status is the host's to say", () => {
    const said = refused(s => { s.state = { tab: "overview", cards: { c7f3a001: { status: "over" } } }; });
    expect(said).toMatch(/The spec seeds "tab", "cards"/);
    expect(said).toMatch(/every card's status are the host's to say/);
  });

  it("names a tab the spec holds", () => {
    expect(refused(s => { s.state = { tab: "finance" }; }))
      .toMatch(/opens on the tab "finance", which it does not hold\. Its tabs are: overview, watches/);
  });
});

describe("the shape of a cockpit", () => {
  it("has a Cockpit at its root", () => {
    expect(refused(s => { s.root = "sec-headline"; })).toMatch(/The root "sec-headline" is a Section/);
  });

  it("holds a card only inside a section", () => {
    expect(refused(s => { s.elements["tab-overview"].children = ["sec-headline", "card-net"]; }))
      .toMatch(/tab "tab-overview" holds "card-net"\. A Tab holds: Section/);
  });

  it("a card holds nothing", () => {
    expect(refused(s => { s.elements["card-rate"].children = ["card-net"]; }))
      .toMatch(/card "card-rate" holds "card-net"\. A Card holds nothing/);
  });

  it("holds tabs or sections at its root, not both", () => {
    expect(refused(s => { s.elements.cockpit.children = ["tabs", "sec-limits"]; s.elements["tab-watches"].children = ["sec-headline"]; s.elements["tab-overview"].children = ["sec-headline"]; }))
      .toMatch(/holds tabs and sections side by side/);
  });

  it("an empty section is refused", () => {
    const said = refused(s => { s.elements["sec-limits"].children = []; delete s.elements["watch-rate"]; });
    expect(said).toMatch(/section "sec-limits" holds nothing\. An empty Section is refused/);
  });

  it("two tabs may not share a name", () => {
    expect(refused(s => { s.elements["tab-watches"].props = { name: "overview", label: "Watches" }; }))
      .toMatch(/"tab-overview" and "tab-watches" are both named "overview"/);
  });

  it("holds only what the spec defines", () => {
    expect(refused(s => { s.elements["sec-headline"].children = ["card-rate", "ghost"]; }))
      .toMatch(/section "sec-headline" holds "ghost", which the spec does not define/);
    expect(refused(s => { s.root = "nowhere"; }))
      .toMatch(/The root is "nowhere", which the spec does not define/);
  });

  it("an element nothing holds is refused, though it would draw — the library's own check", () => {
    expect(refused(s => { s.elements.spare = { type: "Card", props: { card: "c91b2002" }, children: [] }; }))
      .toMatch(/orphaned_element/);
  });

  it("is not more than it may be", () => {
    expect(refused(s => {
      for (let i = 0; i < MAX_ELEMENTS; i++) s.elements[`x${i}`] = { type: "Card", props: { card: "c91b2002" }, children: [] };
    })).toMatch(new RegExp(`A cockpit holds at most ${MAX_ELEMENTS}`));
    expect(refused(s => {
      const more = Array.from({ length: MAX_CARDS }, (_, i) => `m${i}`);
      for (const k of more) s.elements[k] = { type: "Card", props: { card: "c91b2002" }, children: [] };
      s.elements["sec-headline"].children = ["alert-rate", "card-rate", "card-net", ...more];
    })).toMatch(new RegExp(`A cockpit places at most ${MAX_CARDS}`));
  });

  it.each([null, 7, "spec", [], {}, { root: "cockpit" }, { elements: {} }])("%j is not a spec", (spec) => {
    const check = checkCockpitSpec(spec);
    expect(check.valid).toBe(false);
    expect(check.issues[0].code).toBe("not_a_spec");
  });
});

describe("a refusal names every kind of fault, in one round (CT-5)", () => {
  // The writer is a model, and a round spent learning of one fault at a time is a model call.
  it("a bad prop, a child nobody defined, a card outside a section and a bad condition, together", () => {
    const said = refused(s => {
      s.elements["alert-rate"].props = { card: "c7f3a001", tone: "loud" };            // its props
      s.elements["sec-limits"].children = ["watch-rate", "ghost"];                     // a key nobody defined
      s.elements["tab-overview"].children = ["sec-headline", "card-net"];              // the shape
      s.elements["sec-headline"].children = ["alert-rate", "card-rate"];
      s.elements["card-rate"].visible = { $state: "/tab", eq: "overview" };           // a condition
      s.state = { tab: "finance" };                                                    // the state
    });
    expect(said).toMatch(/"alert-rate" has a problem with "tone"/);
    expect(said).toMatch(/section "sec-limits" holds "ghost", which the spec does not define/);
    expect(said).toMatch(/tab "tab-overview" holds "card-net"\. A Tab holds: Section/);
    expect(said).toMatch(/The condition on "card-rate" reads "\/tab"/);
    expect(said).toMatch(/opens on the tab "finance", which it does not hold/);
  });

  it("a root that is no Cockpit does not hide what is wrong beneath it", () => {
    const said = refused(s => { s.root = "sec-headline"; s.elements["card-net"].props = { card: 42 }; });
    expect(said).toMatch(/The root "sec-headline" is a Section/);
    expect(said).toMatch(/"card-net" has a problem with "card"/);
  });

  it("and one fault is not told twice in other words", () => {
    // Two tabs with no name are refused for having none. They are not namesakes.
    const unnamed = refused(s => {
      s.elements["tab-overview"].props = { label: "Overview" };
      s.elements["tab-watches"].props = { label: "Watches" };
      delete s.state;
    });
    expect(unnamed).toMatch(/"tab-overview" has a problem with "name"/);
    expect(unnamed).not.toMatch(/are both named/);
    // A section whose only child is undefined holds something it should not. It is not empty.
    const ghost = refused(s => { s.elements["sec-limits"].children = ["ghost"]; delete s.elements["watch-rate"]; });
    expect(ghost).toMatch(/holds "ghost", which the spec does not define/);
    expect(ghost).not.toMatch(/holds nothing/);
    // An element that is not a component is refused as that, and its holder is not blamed for holding it.
    const unknown = refused(s => { s.elements["card-rate"].type = "Iframe"; });
    expect(unknown).toMatch(/"card-rate" is a "Iframe"/);
    expect(unknown).not.toMatch(/section "sec-headline" holds/);
  });
});

describe("what a refusal hands back beside its sentences (CT-5)", () => {
  it("what it read, so the server can name what only it knows in the same refusal", () => {
    const spec = premise();
    spec.elements["card-net"].on = { press: { action: "anything" } };
    spec.elements["sec-headline"].props = { title: "Returns up 14%" };
    const check = checkCockpitSpec(spec);
    expect(check.valid).toBe(false);
    expect(check.issues.map(i => i.code)).toEqual(["refused_field"]);
    // Nothing is licensed by it: what is drawn and kept comes from these, and they are empty.
    expect(check.cards).toEqual([]);
    expect(check.stateCards).toEqual([]);
    expect(check.texts).toEqual([]);
    expect(check.seen?.cards).toEqual(["c7f3a001", "c91b2002"]);
    expect(check.seen?.stateCards).toEqual(["c7f3a001"]);
    expect(check.seen?.texts).toContainEqual({ elementKey: "sec-headline", prop: "title", text: "Returns up 14%" });
    expect(check.seen?.texts).toHaveLength(5);
  });

  it("but nothing from props that were refused, which have been told already", () => {
    const spec = premise();
    spec.elements["card-net"].props = { card: "not an id!" };
    spec.elements["sec-headline"].props = { title: 7 };
    spec.elements["card-rate"].visible = { $state: "/cards/c91b2002/status", eq: "breached" };
    const check = checkCockpitSpec(spec);
    expect(check.issues.map(i => i.elementKey).sort()).toEqual(["card-net", "card-rate", "sec-headline"]);
    expect(check.seen?.cards).toEqual(["c7f3a001"]);
    expect(check.seen?.stateCards).toEqual(["c7f3a001"]);      // not the card a refused condition named
    expect(check.seen?.texts.map(t => t.elementKey)).not.toContain("sec-headline");
  });

  it("and nothing at all from what is not a spec, or from an accepted one", () => {
    expect(checkCockpitSpec({ root: "cockpit" }).seen).toEqual({ cards: [], stateCards: [], texts: [] });
    expect(checkCockpitSpec(premise()).seen).toBeUndefined();
  });
});

describe("what a condition may read", () => {
  const on = (key: string, visible: unknown) => (s: Spec) => { s.elements[key].visible = visible; };

  it("a card's status and the range's, joined as the writer likes", () => {
    const spec = premise();
    spec.elements["card-net"].visible = {
      $or: [
        { $state: "/cards/c91b2002/status", neq: "withheld" },
        [{ $state: "/range/status", eq: "final" }, { $state: "/cards/c7f3a001/status", eq: "within", not: true }],
      ],
    };
    const check = checkCockpitSpec(spec);
    expect(check.issues).toEqual([]);
    expect(check.stateCards.sort()).toEqual(["c7f3a001", "c91b2002"]);
  });

  it.each([
    ["the open tab", "/tab"],
    ["a figure", "/cards/c7f3a001/last_value"],
    ["anything it likes", "/secrets/token"],
  ])("not %s", (_what, path) => {
    expect(refused(on("card-net", { $state: path, eq: "over" })))
      .toContain(`The condition on "card-net" reads "${path}". A condition may read "/range/status"`);
  });

  it("a status is compared with a word from its own list", () => {
    expect(refused(on("card-net", { $state: "/cards/c7f3a001/status", eq: "breached" })))
      .toMatch(/with "breached"\. It may be compared with: within, over, unmeasured, withheld/);
    expect(refused(on("card-net", { $state: "/range/status", eq: "over" })))
      .toMatch(/with "over"\. It may be compared with: standing, final, provisional, to_date/);
  });

  it("never with another path, which would let a spec compare what it likes", () => {
    expect(refused(on("card-net", { $state: "/range/status", eq: { $state: "/tab" } })))
      .toMatch(/It may be compared with: standing, final, provisional, to_date/);
  });

  it("by eq or neq, once — a status has no greater or lesser", () => {
    expect(refused(on("card-net", { $state: "/range/status", gt: "final" })))
      .toMatch(/compares "\/range\/status" with "gt"\. A status is compared with "eq" or "neq", once/);
    expect(refused(on("card-net", { $state: "/range/status" })))
      .toMatch(/compares "\/range\/status" with nothing/);
  });

  it("a constant is not a condition", () => {
    expect(refused(on("card-net", false))).toMatch(/The condition on "card-net" is false/);
  });

  it("a tab is never conditional", () => {
    expect(refused(on("tab-watches", { $state: "/range/status", eq: "final" })))
      .toMatch(/tab "tab-watches" is shown by a condition\. Only these may be: Section, Card/);
  });

  it("a comparison the library has never heard of is refused in this file's words", () => {
    expect(refused(on("card-net", { $state: "/range/status", equals: "final" })))
      .toMatch(/compares "\/range\/status" with "equals"\. A status is compared with "eq" or "neq", once/);
  });

  it("nor may it read a repeat's item, since there is no repeat", () => {
    expect(refused(on("card-net", { $item: "status", eq: "over" })))
      .toMatch(/The condition on "card-net" reads "\$item", "eq"\. A condition reads "\$state" and nothing else/);
  });
});
