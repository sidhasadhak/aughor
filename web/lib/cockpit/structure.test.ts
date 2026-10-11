/**
 * A structure of pieces (Arc AP-4; the user, 2026-10-11, showing Workshop's blank app: "a widget based structure would be
 * really helpful"; design-mockups/cockpit-builder.html screens 8 and 9). A section holds pieces on its own grid, or is
 * laid out in columns, rows or tabs of sections of its own; a section may hold nothing yet; a section side by side says
 * its width in twelfths. Every edit leaves a cockpit the rules accept, and the writer of a cockpit hears of none of it
 * while the structure is off.
 */
import { describe, expect, it } from "vitest";

import { GRID, MAX_DEPTH } from "@/lib/cockpit/catalog";
import {
  NEW_SECTION, addDrawer, addSectionInside, duplicate, inColumns, layOut, nameByPiece, placeNote, placePiece, sectionsOf,
  setSectionWidth, splitSection, takeOff, takeOffAll, type CockpitSpec,
} from "@/lib/cockpit/edit";
import { grammar } from "@/lib/cockpit/grammar";
import { checkCockpitSpec } from "@/lib/cockpit/rules";

function desk(): CockpitSpec {
  return {
    root: "cockpit",
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["today"] },
      today: { type: "Section", props: { title: "Today", grid: 12 }, children: ["note"] },
      note: { type: "Note", props: { text: "Watch the oldest first", w: 6, h: 3 }, children: [] },
    },
  };
}
const issues = (s: unknown) => checkCockpitSpec(s).issues.map(i => i.message);
const ok = (s: unknown) => expect(issues(s)).toEqual([]);

describe("the rules a structure is held to", () => {
  const split = (): CockpitSpec => ({
    root: "cockpit",
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["body"] },
      body: { type: "Section", props: { layout: "columns" }, children: ["left", "right"] },
      left: { type: "Section", props: { title: "Today", grid: 12, w: 8 }, children: ["note"] },
      right: { type: "Section", props: { title: "The chosen order", grid: 12, w: 4 }, children: [] },
      note: { type: "Note", props: { text: "Oldest first", w: 6, h: 3 }, children: [] },
    },
  });

  it("accept sections side by side, each saying its width — an untitled one laid out, an empty one waiting", () => {
    ok(split());
  });

  it("hold a section to pieces or sections, never both, and a laid-out one to holding at least one", () => {
    const both = split();
    both.elements.body.children.push("note2");
    both.elements.note2 = { type: "Note", props: { text: "x" }, children: [] };
    expect(issues(both).join(" ")).toMatch(/laid out in columns and holds "note2"\. A section split into sections holds sections only/);
    const nested = split();
    nested.elements.left.children.push("right");
    nested.elements.body.children = ["left"];
    expect(issues(nested).join(" ")).toMatch(/holds "right" and is not laid out/);
    const hollow = split();
    hollow.elements.body.children = [];
    delete hollow.elements.left; delete hollow.elements.right; delete hollow.elements.note;
    expect(issues(hollow).join(" ")).toMatch(/laid out in columns and holds nothing\. Split it into sections, or take its layout off/);
  });

  it("hold a section side by side to a width, a tab to a title, and only a laid-out section may go untitled", () => {
    const noWidth = split();
    delete noWidth.elements.right.props.w;
    expect(issues(noWidth).join(" ")).toMatch(/"right" sits in columns in "body" and says no width/);
    const tabs = split();
    tabs.elements.body.props = { layout: "tabs" };
    delete tabs.elements.left.props.w; delete tabs.elements.right.props.w;
    ok(tabs);
    tabs.elements.right.props = { grid: 12 };
    expect(issues(tabs).join(" ")).toMatch(/"right" is a tab of "body" and has no title/);
    const untitled = split();
    untitled.elements.left.props = { grid: 12, w: 8 };
    expect(issues(untitled).join(" ")).toMatch(/"left" has no title\. A section that holds pieces says what it holds/);
  });

  it("refuse a width out of columns, a grid on a laid-out section, and sections deeper than three", () => {
    const stray = desk();
    stray.elements.today.props.w = 6;
    expect(issues(stray).join(" ")).toMatch(/"today" says a width of 6 columns and does not sit in columns/);
    const gridded = split();
    gridded.elements.body.props.grid = 12;
    expect(issues(gridded).join(" ")).toMatch(/laid out in columns and also says a grid/);
    // a split the same way joins the layout it sits in; one the other way wraps it once more
    let deep = desk();
    for (let i = 0; i < MAX_DEPTH; i++) deep = splitSection(deep, "today", i % 2 ? "right" : "below").spec;
    const twice = splitSection(splitSection(desk(), "today", "below").spec, "today", "below").spec;
    const rows = twice.elements[twice.elements.cockpit.children[0]];
    expect([rows.props.layout, rows.children.length, rows.children.every(k => !twice.elements[k].props.layout)]).toEqual(["rows", 3, true]);
    expect(issues(deep).join(" ")).toMatch(new RegExp(`"today" sits ${MAX_DEPTH + 1} sections deep\\. Sections sit at most ${MAX_DEPTH} deep`));
  });
});

describe("splitting and laying out, by hand", () => {
  it("splits a section to its right: a section in columns takes its place, holding it and an empty one, half each", () => {
    const { spec, key } = splitSection(desk(), "today", "right");
    ok(spec);
    const wrap = spec.elements.cockpit.children[0];
    expect(spec.elements[wrap].props).toEqual({ layout: "columns" });
    expect(spec.elements[wrap].children).toEqual(["today", key]);
    expect([spec.elements.today.props.w, spec.elements[key!].props.w]).toEqual([6, 6]);
    expect(spec.elements[key!]).toEqual({ type: "Section", props: { title: NEW_SECTION, grid: GRID.columns, w: 6 }, children: [] });
  });

  it("splits again among columns: the new section joins them, sharing the width of the one it splits", () => {
    const one = splitSection(desk(), "today", "right");
    const two = splitSection(one.spec, one.key!, "left");
    ok(two.spec);
    const wrap = two.spec.elements.cockpit.children[0];
    expect(two.spec.elements[wrap].children).toEqual(["today", two.key, one.key]);
    expect([two.spec.elements.today.props.w, two.spec.elements[two.key!].props.w, two.spec.elements[one.key!].props.w]).toEqual([6, 3, 3]);
    expect(inColumns(two.spec, two.key!)).toBe(true);
  });

  it("splits below: a section in rows, the new one under it, no widths", () => {
    const { spec, key } = splitSection(desk(), "today", "below");
    ok(spec);
    const wrap = spec.elements.cockpit.children[0];
    expect(spec.elements[wrap].props).toEqual({ layout: "rows" });
    expect(spec.elements[wrap].children).toEqual(["today", key]);
    expect(spec.elements.today.props.w).toBeUndefined();
  });

  it("lays an empty section out in columns, rows or tabs of two, and adds one more inside", () => {
    const { spec, key } = splitSection(desk(), "today", "right");
    for (const [layout, titles] of [["columns", [NEW_SECTION, NEW_SECTION]], ["rows", [NEW_SECTION, NEW_SECTION]], ["tabs", ["First tab", "Second tab"]]] as const) {
      const laid = layOut(spec, key!, layout);
      ok(laid);
      expect(laid.elements[key!].props.layout).toBe(layout);
      expect(laid.elements[key!].children.map(k => laid.elements[k].props.title)).toEqual(titles);
    }
    const cols = layOut(spec, key!, "columns");
    const more = addSectionInside(cols, key!);
    ok(more.spec);
    expect(more.spec.elements[more.key!].props.w).toBe(4);
    expect(layOut(desk(), "today", "columns")).toEqual(desk());             // a section that holds pieces is not laid out
  });

  it("steps a width one twelfth at a time, between one column and twelve", () => {
    const { spec, key } = splitSection(desk(), "today", "right");
    expect(setSectionWidth(spec, key!, 7).elements[key!].props.w).toBe(7);
    expect(setSectionWidth(spec, key!, 0).elements[key!].props.w).toBe(1);
    expect(setSectionWidth(spec, key!, 40).elements[key!].props.w).toBe(12);
  });
});

describe("what a structure does to the edits before it", () => {
  it("lists the sections that hold pieces, through the ones laid out in sections, an empty one included", () => {
    const { spec, key } = splitSection(desk(), "today", "right");
    expect(sectionsOf(spec).map(x => x.key)).toEqual(["today", key]);
  });

  it("keeps a section in a layout as an empty box when its last piece goes; one of the cockpit's own goes, as before", () => {
    const { spec } = splitSection(desk(), "today", "right");
    const emptied = takeOff(spec, "note");
    expect(emptied.elements.today).toEqual({ type: "Section", props: { title: "Today", grid: 12, w: 6 }, children: [] });
    ok(emptied);
    const two = placeNote(desk(), "Second", "today");
    expect("today" in takeOff(takeOff(two, "note"), Object.keys(two.elements).find(k => k.startsWith("note-"))!).elements).toBe(false);
  });

  it("duplicates a section and all it holds under keys of their own, naming no choice twice", () => {
    const s = desk();
    s.elements.note.props = { ...s.elements.note.props, chooses: "x" };
    const { spec, key } = duplicate(s, "today");
    expect(spec.elements.cockpit.children).toEqual(["today", key]);
    const copyNote = spec.elements[key!].children[0];
    expect(copyNote).not.toBe("note");
    expect(spec.elements[copyNote].props.chooses).toBeUndefined();
    expect(spec.elements.note.props.chooses).toBe("x");
  });

  it("names a new section by the first piece placed in it, and leaves a named one alone", () => {
    const { spec, key } = splitSection(desk(), "today", "right");
    expect(nameByPiece(spec, key!, "Waiting").elements[key!].props.title).toBe("Waiting");
    expect(nameByPiece(spec, "today", "Waiting").elements.today.props.title).toBe("Today");
  });
});

describe("the writer of a cockpit", () => {
  it("hears nothing of the structure while it is off — the text is the one before it, byte for byte", () => {
    expect(grammar()).toBe(grammar({ grid: false, structure: false }));
    expect(grammar()).not.toMatch(/layout/);
    expect(grammar()).toMatch(/Holds Card, Note, Image, at least one\./);
  });

  it("is told of it while it is on, and only that is added", () => {
    const on = grammar({ structure: true });
    expect(on).toMatch(/layout \(optional, one of: columns, rows, tabs/);
    expect(on).toMatch(/or, laid out, Section — at most 3 deep\. It may hold nothing yet\./);
    expect(on.replace(/, layout \(optional[^)]*\), w \(1 to 12[^)]*\)/, "").replace(/Holds Card, Note, Image; or, laid out, Section — at most 3 deep\. It may hold nothing yet\./, "Holds Card, Note, Image, at least one."))
      .toBe(grammar());
  });
});

describe("a drawer (Arc AP-4: what opens beside the page)", () => {
  function chosen(): CockpitSpec {
    const s = desk();
    s.elements.today.children.push("orders");
    s.elements.orders = { type: "ObjectList", props: { entity: "order", chooses: "chosen-order", w: 6, h: 8 }, children: [] };
    return s;
  }

  it("is added after the page, opening on a choice and holding the chosen one's detail — and the rules accept it", () => {
    const { spec, key } = addDrawer(chosen(), "The order", "chosen-order");
    ok(spec);
    expect(spec.elements.cockpit.children).toEqual(["today", key]);
    expect(spec.elements[key!]).toMatchObject({ type: "Drawer", props: { title: "The order", opens_on: "chosen-order" } });
    const [detail] = spec.elements[key!].children;
    expect(spec.elements[detail]).toEqual({ type: "ObjectDetail", props: { follows: "chosen-order" }, children: [] });
    expect(sectionsOf(spec).map(x => [x.key, !!x.drawer])).toEqual([["today", false], [key, true]]);
  });

  it("opens only on an object a click chooses, and is no cockpit's only child", () => {
    const { spec, key } = addDrawer(chosen(), "The order", "chosen-order");
    const stray = structuredClone(spec);
    stray.elements[key!].props.opens_on = "ticked-orders";
    expect(issues(stray).join(" ")).toMatch(/The drawer "drawer-chosen-order" opens on "ticked-orders", and no click chooses "ticked-orders"/);
    const alone = structuredClone(spec);
    alone.elements.cockpit.children = [key!];
    expect(issues(alone).join(" ")).toMatch(/holds only drawers\. It holds one Tabs, or sections, for a drawer to open beside/);
  });

  it("holds the pieces placed in it, stays when its last piece goes, and goes with its pieces when taken off", () => {
    const { spec, key } = addDrawer(chosen(), "The order", "chosen-order");
    const placed = placePiece(spec, "ObjectTable", { entity: "order_item" }, key!);
    expect(placed.spec.elements[key!].children).toHaveLength(2);
    expect(placed.spec.elements[placed.key!].props.w).toBeUndefined();            // a drawer stacks; it is no grid
    ok(placed.spec);
    const [detail] = spec.elements[key!].children;
    const emptied = takeOff(spec, detail);
    expect(emptied.elements[key!]?.children).toEqual([]);
    ok(emptied);                                                                     // an empty drawer waits for a piece
    const gone = takeOffAll(placed.spec, key!);
    expect(Object.keys(gone.elements).filter(k => !(k in chosen().elements))).toEqual([]);
    ok(gone);
  });

  it("places a choose-one and a search half a section wide beside what is there — never too narrow to read their title", () => {
    for (const type of ["ChooseOne", "ObjectSearch"] as const) {
      const placed = placePiece(desk(), type, type === "ChooseOne"
        ? { entity: "distribution_center", chooses: "chosen-centre", label: "name" } : { entity: "order", path: "status", label: "Find orders" }, "today");
      expect(placed.spec.elements[placed.key!].props.w).toBe(6);
    }
  });

  it("is never told to the writer of a cockpit", () => {
    expect(grammar({ grid: true, structure: true })).not.toMatch(/Drawer|drawer/);
  });
});
