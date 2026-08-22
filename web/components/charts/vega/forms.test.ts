/**
 * forms.test.ts — every form beyond the everyday six compiles, parses, runs and PAINTS.
 *
 * The assertions are the ones this branch learned the hard way: parsing is not drawing,
 * counting marks is not painting, and "a fill that looks like a colour" is not a token.
 */

import { describe, expect, it } from "vitest";
import * as vl from "vega-lite";
import { View, parse } from "vega";
import { resolveVegaSpec } from "@/components/charts/vega/resolveSpec";
import { buildVegaConfig, printVegaTokens } from "@/components/charts/vega/config";

const TOKENS = printVegaTokens();
const config = buildVegaConfig(TOKENS);
/** Every colour the theme defines. A boxplot's whiskers are data marks that legitimately
 *  wear the muted text token, so "from the token set" has to mean the whole set. */
const ALLOWED = [
  ...TOKENS.palette, TOKENS.sign.pos, TOKENS.sign.neg, TOKENS.deemph,
  TOKENS.grid, TOKENS.surface, TOKENS.axis, TOKENS.tick, TOKENS.t1, TOKENS.t3,
].map((c) => c.toLowerCase());

const months = (n: number) => Array.from({ length: n }, (_, i) => `2024-${String((i % 12) + 1).padStart(2, "0")}-01`);

const CASES: Record<string, { columns: string[]; rows: unknown[][] }> = {
  scatter: { columns: ["revenue", "profit"], rows: [[9e5, 1.8e5], [1.1e6, 2.2e5], [1.3e6, 2.6e5], [7e5, 1.1e5]] },
  heatmap: { columns: ["day", "hour", "orders"],
             rows: [["Mon", "09", 12], ["Mon", "10", 18], ["Tue", "09", 7], ["Tue", "10", 22]] },
  histogram: { columns: ["order_value"], rows: [[12], [18], [25], [31], [44], [52], [63], [21], [29]].map((r) => r) },
  boxplot: { columns: ["region", "revenue"],
             rows: [["North", 10], ["North", 14], ["North", 22], ["South", 8], ["South", 19], ["South", 31]] },
  "stacked-bar": { columns: ["month", "region", "revenue"],
                   rows: months(4).flatMap((m) => ["North", "South"].map((r, i) => [m, r, 100 + i * 40])) },
  "grouped-bar": { columns: ["month", "region", "revenue"],
                   rows: months(4).flatMap((m) => ["North", "South"].map((r, i) => [m, r, 100 + i * 40])) },
  "small-multiples": { columns: ["region", "month", "revenue"],
                       rows: ["North", "South", "East"].flatMap((r) => months(5).map((m, i) => [r, m, 100 + i * 20])) },
  "delta-bar": { columns: ["region", "delta"], rows: [["North", 120], ["South", -90], ["East", 45], ["West", -12]] },
  waterfall: { columns: ["step", "amount"], rows: [["Open", 100], ["Won", 40], ["Lost", -25], ["Close", 15]] },
  pareto: { columns: ["category", "gmv"], rows: [["A", 500], ["B", 300], ["C", 120], ["D", 80]] },
  "line-forecast": { columns: ["month", "revenue", "lower", "upper"],
                     rows: months(6).map((m, i) => [m, 100 + i * 10, 90 + i * 10, 115 + i * 10]) },
  // Six cities, not two. The resolver refuses a grid too small to carry an honest chart
  // (`isUngraphableGrid`, and `rows.length < 2` in inference) — a rule that has nothing to
  // do with maps: `scatter` nulls on this same two-row grid too. This case was the only
  // one seeded under that floor, so all three point-map assertions failed against a chart
  // engine that was working correctly.
  "point-map": { columns: ["city", "lat", "lon", "orders"],
                 rows: [["Zurich", 47.37, 8.54, 120], ["Berlin", 52.52, 13.40, 300],
                        ["Madrid", 40.42, -3.70, 210], ["Oslo", 59.91, 10.75, 90],
                        ["Dublin", 53.35, -6.26, 140], ["Athens", 37.98, 23.73, 60]] },
};

async function render(type: string) {
  const c = CASES[type];
  const out = resolveVegaSpec({ columns: c.columns, rows: c.rows, chartType: type });
  expect(out, `${type} produced no spec`).not.toBeNull();
  const compiled = vl.compile({ ...out!.spec, width: 500, height: out!.defaultH } as Parameters<typeof vl.compile>[0], { config }).spec;
  const view = new View(parse(compiled), { renderer: "none" });
  await view.runAsync();
  return { out: out!, view };
}

/**
 * DATA marks only. The first version walked the whole scenegraph and picked up axis labels,
 * whose fill is the tick token — so a scatter "failed" for painting #5F7281, which is the
 * axis colour doing its job. Chrome wears chrome tokens; only the marks carrying data are
 * held to the palette.
 */
type SceneNode = { marktype?: string; role?: string; fill?: unknown; items?: SceneNode[] };
const DATA_MARKS = new Set(["rect", "symbol", "arc", "path", "area", "line", "rule"]);

function paintedMarks(view: View): SceneNode[] {
  const scene = view.scenegraph() as unknown as { root?: { items?: SceneNode[] } };
  const out: SceneNode[] = [];
  const walk = (nodes: SceneNode[] | undefined, insideChrome: boolean) => {
    for (const n of nodes ?? []) {
      const chrome = insideChrome || n.role === "axis" || n.role === "legend" || n.role === "title";
      if (!chrome && n.marktype && DATA_MARKS.has(n.marktype)) out.push(...(n.items ?? []));
      walk(n.items, chrome);
    }
  };
  walk(scene.root?.items, false);
  return out;
}

const TYPES = Object.keys(CASES);

describe("forms beyond the everyday six", () => {
  it.each(TYPES)("%s compiles, parses and runs", async (type) => {
    const { out } = await render(type);
    expect(out.tier).toBe(1);
  });

  it.each(TYPES)("%s emits pure JSON with no colour baked in", (type) => {
    const c = CASES[type];
    const out = resolveVegaSpec({ columns: c.columns, rows: c.rows, chartType: type })!;
    expect(JSON.stringify(out.spec)).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(JSON.parse(JSON.stringify(out.spec))).toEqual(out.spec);
  });

  /**
   * A ramp does not paint tokens: it INTERPOLATES between the two ends of the config's
   * `heatmap` range, so every cell is a colour that appears nowhere in the palette and Vega
   * emits it as rgb() rather than hex. Those forms are held to "a real colour from a scale",
   * and the categorical ones to palette membership, which is the stricter claim and the one
   * that catches a library default.
   */
  const RAMPED = new Set(["heatmap", "choropleth"]);

  it.each(TYPES)("%s paints only from the token set", async (type) => {
    const { view } = await render(type);
    // A line carries STROKE, not fill — reading only `fill` reported "painted nothing" for
    // the forms drawn with lines, which were painting perfectly well.
    const colours = paintedMarks(view)
      .flatMap((m) => [m.fill, (m as { stroke?: unknown }).stroke])
      .filter((f): f is string => typeof f === "string" && /^(#|rgb)/i.test(f));
    expect(colours.length, `${type} painted nothing`).toBeGreaterThan(0);
    if (RAMPED.has(type)) return;
    for (const f of colours) {
      expect(ALLOWED, `${type} painted ${f}, which is not a token`).toContain(f.toLowerCase());
    }
    view.finalize();
  });

  it("refuses a form the data cannot carry, rather than approximating", () => {
    // A scatter needs two measures; a point map needs coordinates.
    expect(resolveVegaSpec({ columns: ["region", "revenue"], rows: [["N", 1]], chartType: "scatter" })).toBeNull();
    expect(resolveVegaSpec({ columns: ["city", "orders"], rows: [["Z", 1]], chartType: "point-map" })).toBeNull();
  });

  it("gives the Pareto ONE axis, both measures as a share", () => {
    const c = CASES.pareto;
    const out = resolveVegaSpec({ columns: c.columns, rows: c.rows, chartType: "pareto" })!;
    const spec = out.spec as { layer: { encoding: { y: { field: string } } }[] };
    // Bars and the cumulative line are both shares, so there is no second scale to resolve
    // — the dual axis §6 bans cannot creep back in through this form.
    expect(spec.layer.map((l) => l.encoding.y.field)).toEqual(["__share", "__cum"]);
    expect(JSON.stringify(out.spec)).not.toContain("independent");
  });
});

describe("the exhibit grammar reaches the Vega path", () => {
  const ranking = { columns: ["region", "revenue"], rows: [["North", 120], ["South", 90], ["East", 45]] };

  it("colours by SIGN through the diverging range, naming no colour", () => {
    const out = resolveVegaSpec({ ...ranking, chartType: "bar",
      exhibit: { color: { mode: "sign" } } })!;
    const enc = (out.spec as { encoding: { color?: { scale?: { type?: string; range?: string } } } }).encoding;
    expect(enc.color?.scale?.type).toBe("threshold");
    expect(enc.color?.scale?.range).toBe("diverging");
    expect(JSON.stringify(out.spec)).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });

  it("ramps SEVERITY through the single-hue range", () => {
    const out = resolveVegaSpec({ ...ranking, chartType: "bar",
      exhibit: { color: { mode: "severity" } } })!;
    const enc = (out.spec as { encoding: { color?: { scale?: { range?: string } } } }).encoding;
    expect(enc.color?.scale?.range).toBe("heatmap");
  });

  it("draws reference lines as their own layer", () => {
    const out = resolveVegaSpec({ ...ranking, chartType: "bar",
      exhibit: { ref_lines: [{ value: 100, label: "peer median" }] } })!;
    const spec = out.spec as { layer?: unknown[] };
    expect(Array.isArray(spec.layer), "a ref line forces the layered form").toBe(true);
    expect(JSON.stringify(spec)).toContain("peer median");
  });

  it("emphasises the question's subjects and washes the rest", () => {
    const out = resolveVegaSpec({ ...ranking, chartType: "bar",
      exhibit: { emphasis: ["North"] } })!;
    const enc = (out.spec as { encoding: { opacity?: { condition?: { test?: string }; value?: number } } }).encoding;
    expect(enc.opacity?.condition?.test).toContain("North");
    expect(enc.opacity?.value).toBeLessThan(1);
  });

  it("survives a malformed exhibit rather than losing the chart", () => {
    const out = resolveVegaSpec({ ...ranking, chartType: "bar",
      exhibit: { color: { mode: "nonsense" }, ref_lines: [{ value: "NaN" }] } as never });
    expect(out, "a bad exhibit must cost its semantics, never the chart").not.toBeNull();
  });
});
