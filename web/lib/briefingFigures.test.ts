/**
 * The Briefing's front holds six; the rest read under the desk, by area; a reader chooses front, below or hidden per
 * figure (the user, 2026-10-26). The fixture is LuxExperience's week of 19–25 October as the live API measured it:
 * 24 approved figures, 16 measured and 8 whose data ended.
 */
import { describe, expect, it } from "vitest";

import type { PaperNumber } from "@/components/brief/BriefPaper";

import { FRONT_MAX, arrange, idOf, moved, normalizeFigures, placeOf, scopeKey, withChoice } from "./briefingFigures";

const fig = (metric: string, area: string, extra: Partial<PaperNumber> = {}): PaperNumber =>
  ({ key: metric, metric, label: metric, value: "1", area, ...extra });
const ended = (metric: string, ends: string): PaperNumber =>
  ({ key: `unmeasured:${metric}`, metric, label: metric, value: "", unknown: "data ended", ended: true, ends, why: "its data ends" });

const LUX: PaperNumber[] = [
  fig("gmv", "Orders & sales"), fig("net_revenue_eur", "Orders & sales", { moved: true }),
  fig("item_gross_margin_pct", "Orders & sales"), fig("average_order_value_aov", "Orders & sales"),
  fig("item_return_rate", "Returns", { moved: true }), fig("cogs_per_unit", "Margin & pricing"),
  fig("gross_margin", "Margin & pricing"), fig("contribution_margin_eur", "Margin & pricing"),
  fig("avg_order_to_delivery_days", "Fulfilment"), fig("session_conversion_rate", "Traffic & conversion"),
  fig("repeat_purchase_rate", "Customers", { moved: true }),
  ended("markdown_penetration", "2024-04-05"), ended("marketing_consent_rate", "2025-05-19"),
  ended("email_open_rate", "2025-05-19"),
  { key: "unmeasured:roas", metric: "roas", label: "Marketing ROAS", value: "", unknown: "not measured", why: "its date is a fiscal year" },
];
const NONE = { front: [], hidden: [] };

describe("arrange", () => {
  it("reads exactly as before when every figure fits on the front and nothing is chosen", () => {
    const small = LUX.slice(0, 5);
    expect(arrange(small, NONE)).toEqual({ front: small, below: [], blanks: [], stopped: [], hidden: [], fits: true });
  });

  it("puts the first six measured figures on the front and the rest under the desk by area, in reading order", () => {
    const a = arrange(LUX, NONE);
    expect(a.fits).toBe(false);
    expect(a.front.map(idOf)).toEqual(["gmv", "net_revenue_eur", "item_gross_margin_pct", "average_order_value_aov",
                                       "item_return_rate", "cogs_per_unit"]);
    expect(a.below.map(g => [g.area, g.rows.map(idOf)])).toEqual([
      ["Margin & pricing", ["gross_margin", "contribution_margin_eur"]], ["Fulfilment", ["avg_order_to_delivery_days"]],
      ["Traffic & conversion", ["session_conversion_rate"]], ["Customers", ["repeat_purchase_rate"]]]);
    expect(a.stopped.map(g => [g.day, g.rows.map(idOf)])).toEqual([
      ["2024-04-05", ["markdown_penetration"]], ["2025-05-19", ["marketing_consent_rate", "email_open_rate"]]]);
    expect(a.blanks.map(idOf)).toEqual(["roas"]);                     // its reason stays in plain view
  });

  it("keeps the reader's front in their order, and a hidden figure nowhere", () => {
    const a = arrange(LUX, { front: ["repeat_purchase_rate", "gmv"], hidden: ["item_gross_margin_pct", "markdown_penetration"] });
    expect(a.front.map(idOf)).toEqual(["repeat_purchase_rate", "gmv"]);
    expect(a.hidden.map(idOf)).toEqual(["item_gross_margin_pct", "markdown_penetration"]);
    const everywhere = [...a.front, ...a.below.flatMap(g => g.rows), ...a.blanks, ...a.stopped.flatMap(g => g.rows)].map(idOf);
    expect(everywhere).not.toContain("item_gross_margin_pct");
    expect(new Set(everywhere).size).toBe(LUX.length - 2);           // every other figure exactly once
  });
});

describe("a reader's choice", () => {
  it("moves one figure without reshuffling the rest, and a full front takes no seventh", () => {
    let c = moved(LUX, NONE, "repeat_purchase_rate", "below");
    expect(c.front).toHaveLength(6);                                  // the default front, written down
    c = moved(LUX, c, "gmv", "below");
    c = moved(LUX, c, "repeat_purchase_rate", "front");
    expect(c.front.slice(-1)).toEqual(["repeat_purchase_rate"]);
    expect(placeOf(LUX, c, "gmv")).toBe("below");
    const full = moved(LUX, c, "contribution_margin_eur", "front");
    expect(moved(LUX, full, "session_conversion_rate", "front")).toBe(full);
    expect(full.front).toHaveLength(FRONT_MAX);
  });

  it("hiding a figure from the default front lets the next one take its place", () => {
    const c = moved(LUX, NONE, "item_gross_margin_pct", "hidden");
    expect(c).toEqual({ front: [], hidden: ["item_gross_margin_pct"] });
    expect(arrange(LUX, c).front.map(idOf)).toContain("gross_margin");
  });

  it("is kept per dataset, an empty one dropped, and a stored value read safely", () => {
    const scope = scopeKey("dcc63d83", "luxexperience");
    expect(scope).toBe("dcc63d83:luxexperience");
    const pref = withChoice({}, scope, { front: ["gmv"], hidden: [] });
    expect(withChoice(pref, scope, NONE)).toEqual({});
    expect(normalizeFigures({ x: { front: ["a", "b"], hidden: ["b"] }, y: "junk", z: { front: [] } }))
      .toEqual({ x: { front: ["a"], hidden: ["b"] } });
  });
});
