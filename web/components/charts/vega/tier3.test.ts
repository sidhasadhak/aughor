/**
 * tier3.test.ts — do the hand-authored Vega specs actually run?
 *
 * The Phase 1 lesson applies double here: a spec that is well-formed JSON of the right
 * shape is not a spec Vega can parse, and a hand-authored spec has no compiler standing
 * between it and the runtime to catch a mistake. Every type is parsed AND run, and the
 * scenegraph is inspected, because a spec can parse cleanly and still draw nothing.
 */

import { describe, expect, it } from "vitest";
import { View, parse } from "vega";
import { resolveTier3Spec, TIER3_TYPES } from "@/components/charts/vega/tier3";
import { buildVegaRuntimeConfig, printVegaTokens } from "@/components/charts/vega/config";

const CASES: Record<string, { columns: string[]; rows: unknown[][] }> = {
  treemap: {
    columns: ["category", "gmv"],
    rows: [["Apparel", 4.2e6], ["Electronics", 3.1e6], ["Home", 2.4e6], ["Beauty", 1.8e6], ["Toys", 9e5]],
  },
  funnel: {
    columns: ["stage", "count"],
    rows: [["Visit", 10_000], ["Cart", 3_200], ["Checkout", 1_400], ["Paid", 900]],
  },
  gantt: {
    columns: ["task", "start", "end"],
    rows: [["Ingest", "2024-01-01", "2024-01-06"], ["Model", "2024-01-04", "2024-01-15"],
           ["Review", "2024-01-14", "2024-01-20"]],
  },
  sankey: {
    columns: ["source", "target", "value"],
    rows: [["Organic", "Signup", 500], ["Paid", "Signup", 300], ["Organic", "Bounce", 200],
           ["Referral", "Signup", 120], ["Paid", "Bounce", 80]],
  },
};

const TOKENS = printVegaTokens();
const config = buildVegaRuntimeConfig(TOKENS);
/** Every colour a tier-3 mark is allowed to be. */
const PALETTE = TOKENS.palette.map((c) => c.toLowerCase());

async function render(type: string) {
  const c = CASES[type];
  const out = resolveTier3Spec({ columns: c.columns, rows: c.rows, chartType: type });
  expect(out, `${type} produced no spec`).not.toBeNull();
  const view = new View(parse({ ...out!.spec, width: 600, height: out!.defaultH } as Parameters<typeof parse>[0], config), { renderer: "none" });
  await view.runAsync();
  return { out: out!, view };
}

describe("tier 3 — hand-authored Vega", () => {
  it("covers exactly the four Vega-Lite cannot express", () => {
    expect([...TIER3_TYPES].sort()).toEqual(["funnel", "gantt", "sankey", "treemap"]);
  });

  /** Scenegraph mark counts, BY TYPE. */
  function marksByType(view: View): Record<string, number> {
    const scene = view.scenegraph() as unknown as { root?: { items?: { items?: unknown[] }[] } };
    const groups = (scene.root?.items?.[0]?.items ?? []) as { marktype?: string; items?: unknown[] }[];
    const out: Record<string, number> = {};
    for (const g of groups) if (g.marktype) out[g.marktype] = (out[g.marktype] ?? 0) + (g.items?.length ?? 0);
    return out;
  }

  // Counting marks BY TYPE, not in total. The first version summed every scenegraph item
  // and passed while the sankey drew nothing but its text labels: an unrecognised colour
  // scheme killed every mark bound to the scale and left the ones that were not, so the
  // chart was half-drawn and the assertion could not tell.
  const EXPECT: Record<string, { type: string; least: number }> = {
    treemap: { type: "rect", least: 5 },
    funnel:  { type: "rect", least: 4 },
    gantt:   { type: "rect", least: 3 },
    sankey:  { type: "path", least: 5 },
  };

  it.each([...TIER3_TYPES])("%s draws the marks that carry its meaning", async (type) => {
    const { out, view } = await render(type);
    expect(out.tier).toBe(3);
    const marks = marksByType(view);
    const want = EXPECT[type];
    expect(marks[want.type] ?? 0, `${type} drew ${JSON.stringify(marks)}`).toBeGreaterThanOrEqual(want.least);
    view.finalize();
  });

  // Counting marks is still not enough. A bad scale does not REMOVE marks -- it leaves them
  // in the scenegraph with an undefined fill, so they are present, invisible, and every
  // count-based assertion passes while the chart shows nothing but its labels. The only
  // assertion that catches it is the one that asks what colour the mark actually is.
  it.each([...TIER3_TYPES])("%s paints its marks a real colour", async (type) => {
    const { view } = await render(type);
    const scene = view.scenegraph() as unknown as { root?: { items?: { items?: unknown[] }[] } };
    const groups = (scene.root?.items?.[0]?.items ?? []) as { marktype?: string; items?: { fill?: unknown }[] }[];
    const painted = groups.filter((g) => g.marktype === "rect" || g.marktype === "path" || g.marktype === "arc");
    expect(painted.length, `${type} has no filled marks at all`).toBeGreaterThan(0);
    for (const g of painted) {
      for (const item of g.items ?? []) {
        expect(typeof item.fill, `${type}: a ${g.marktype} has no fill`).toBe("string");
        // FROM THE PALETTE, not merely "a colour". Checking the shape of the string is what
        // let Vega's own #4c78a8 through on the funnel and the gantt: a mark with no colour
        // encoding falls back to the library default, which is a plausible blue and passes
        // every test that only asks whether a fill exists.
        expect(PALETTE, `${type}: a ${g.marktype} is ${item.fill}, which is not a token`)
          .toContain(String(item.fill).toLowerCase());
      }
    }
    view.finalize();
  });

  it("draws sankey NODES as well as its ribbons", async () => {
    const { view } = await render("sankey");
    const marks = marksByType(view);
    expect(marks.rect ?? 0, "the node columns are missing").toBeGreaterThanOrEqual(5);
    view.finalize();
  });

  it.each([...TIER3_TYPES])("%s bakes no colour and survives JSON", async (type) => {
    const c = CASES[type];
    const out = resolveTier3Spec({ columns: c.columns, rows: c.rows, chartType: type })!;
    // Same rule as tier 1: the theme arrives as config at render time. A hand-authored
    // spec is exactly where a stray hex would creep back in.
    expect(JSON.stringify(out.spec)).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(JSON.parse(JSON.stringify(out.spec))).toEqual(out.spec);
  });

  it("declines anything that is not its business", () => {
    expect(resolveTier3Spec({ columns: ["a", "b"], rows: [["x", 1]], chartType: "bar" })).toBeNull();
    expect(resolveTier3Spec({ columns: [], rows: [], chartType: "treemap" })).toBeNull();
    expect(resolveTier3Spec({ columns: ["a"], rows: [], chartType: "sankey" })).toBeNull();
  });

  it("computes the sankey layout as DATA, never as a function", () => {
    const c = CASES.sankey;
    const out = resolveTier3Spec({ columns: c.columns, rows: c.rows, chartType: "sankey" })!;
    const data = (out.spec as { data: { name: string; values?: unknown[] }[] }).data;
    const nodes = data.find((d) => d.name === "nodes")!.values as { name: string; y0: number; y1: number }[];
    const ribbons = data.find((d) => d.name === "ribbons")!.values as { value: number }[];
    // 3 sources + 2 targets, and one ribbon per link.
    expect(nodes.length).toBe(5);
    expect(ribbons.length).toBe(c.rows.length);
    // Node heights are proportional to flow: Organic (700) outranks Paid (380).
    const h = (n: string) => { const x = nodes.find((v) => v.name === n)!; return x.y1 - x.y0; };
    expect(h("Organic")).toBeGreaterThan(h("Paid"));
    expect(h("Paid")).toBeGreaterThan(h("Referral"));
  });
});
