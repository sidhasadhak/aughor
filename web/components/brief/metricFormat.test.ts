/**
 * A KPI tile shows a figure at the scale its unit/range text STATES, and hides it only by a bound that text states.
 *
 * The reading is not this file's to make: `GET /business-profile` ships it beside each metric's `unit_or_range` as
 * `stated_range`, from the one reader the value audit uses (`aughor/business_profile/validate.py::stated_range`).
 * The formatter used to read the text with regexes of its own, and every case below is one it got wrong (measured
 * 2026-09-17): it held anything containing "ratio" to 0..1, so an inventory turnover of 5 and a net review ratio of
 * -0.2 never showed; it read "0-1000" as "0-100", so a €404 AOV never showed; and it read the airline package's
 * 'ratio 0..1 (0..100%)' as a percent, so a 0.82 load factor showed "0.8%".
 *
 * The population is every range the industry packages ship (`packs/<industry>/industry.json`, read from disk) and
 * the live shapes, each formatted by the reading the route ships for it — `statedRanges.fixture.json`, which
 * `tests/unit/test_stated_range_display.py` holds to the route's own output. A range added to a package, or
 * reworded, fails here until that fixture is regenerated.
 */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import type { StatedRange } from "@/lib/api";

import { deltaInfo, formatMetric } from "./metricFormat";

// From the vitest root (`web/`), not `__dirname` — that is undefined under ESM.
const REPO = resolve(process.cwd(), "..");

const READINGS = JSON.parse(
  readFileSync(resolve(process.cwd(), "components/brief/statedRanges.fixture.json"), "utf8"),
) as Record<string, StatedRange>;

/** The reading the route ships for `text`; absent means the fixture is stale (see this file's header). */
function read(text: string): StatedRange {
  const range = READINGS[text];
  if (!range) throw new Error(`no reading for ${JSON.stringify(text)} — regenerate statedRanges.fixture.json`);
  return range;
}

interface Shipped { pack: string; metric: string; text: string }

function shippedRanges(): Shipped[] {
  const packs = resolve(REPO, "packs");
  return readdirSync(packs).sort().flatMap(pack => {
    const file = resolve(packs, pack, "industry.json");
    if (!existsSync(file)) return [];
    const metrics = JSON.parse(readFileSync(file, "utf8")).metrics as Record<string, unknown>[];
    return metrics.flatMap(m => (["sane_range", "unit_or_range"] as const)
      .filter(field => typeof m[field] === "string")
      .map(field => ({ pack, metric: String(m.name), text: m[field] as string })));
  });
}

const SHIPPED = shippedRanges();

/** The figure a display string carries, whatever glyphs ride with it ("€404.11" → 404.11, "5.0K" → 5000). */
function figure(display: string): number {
  const mag = { K: 1e3, M: 1e6, B: 1e9 }[display.slice(-1)] ?? 1;
  return Number(display.replace(/[^0-9.eE+-]/g, "")) * mag;
}

/** A value the audit keeps: inside a stated band, and outside a band the text only calls typical. */
function keptValue(range: StatedRange): number {
  const { kind, lo, hi } = range;
  if (kind === "ratio01") return 0.42;
  if (kind === "pct100") return 42;
  if (kind === "typical") return (hi ?? lo ?? 1) * 3 + 1;              // a typical band is never a bound
  if (kind === "band") {
    if (lo !== null && hi !== null) return (lo + hi) / 2;
    return lo !== null ? lo + Math.max(1, Math.abs(lo)) : (hi as number) - Math.max(1, Math.abs(hi as number));
  }
  return 5;                                                            // open: any magnitude is possible
}

/** A value outside a STATED band, past the 5%-of-the-band slack `audit_value_sql` allows. */
function outOfBand(range: StatedRange): number | null {
  const { lo, hi } = range;
  if (range.kind !== "band") return null;
  const width = lo !== null && hi !== null ? hi - lo : Math.abs((hi ?? lo) as number);
  return hi !== null ? hi + 0.2 * width : (lo as number) - 0.2 * width;
}

describe("every range the industry packages ship", () => {
  it("is read from the files, with a reading for each", () => {
    // Vacuity guard: an empty population would make every case below trivially satisfied.
    expect(SHIPPED.length).toBeGreaterThan(40);
    expect(SHIPPED.filter(s => !READINGS[s.text]).map(s => `${s.pack}: ${s.metric}`)).toEqual([]);
  });

  it.each(SHIPPED.map(s => [`${s.pack} · ${s.metric}`, s] as const))(
    "%s shows a value its text allows, at the scale its text states", (_id, { metric, text }) => {
      const range = read(text);
      const value = keptValue(range);
      const shown = formatMetric(value, text, "$", metric, range);

      expect(shown, `${text} → hid ${value}`).toMatchObject({ ok: true });
      if (range.kind === "ratio01") expect(shown.display).toBe("42.0%");
      else if (range.kind === "pct100") expect(shown.display).toBe("42.0%");
      else {
        expect(shown.display.endsWith("%"), `${text} → ${shown.display}`).toBe(false);
        expect(figure(shown.display)).toBeCloseTo(value, 2);
      }

      const impossible = outOfBand(range);
      if (impossible !== null) expect(formatMetric(impossible, text, "$", metric, range).ok).toBe(false);
    });
});

describe("the live shapes the formatter misread", () => {
  const cases: [name: string, text: string, value: number, display: string][] = [
    ["Inventory Turnover (by product-month)", "ratio (units sold per unit avg. inventory)", 5, "5"],
    ["Inventory Turnover (by SKU)", "ratio (units sold / avg units in stock)", 5.3, "5.30"],
    ["Average Order Value (AOV)", "ratio 0-1000 (USD per order)", 404.11, "$404.11"],
    ["Net Review Ratio", "ratio -1 to 1 (healthy: >0.2)", -0.2, "-0.20"],
    ["Average CSAT Score", "1-5 scale (measured ≈ 4.08)", 4.08, "4.08"],
    ["Average Popularity by Genre", "score 0-100 (measured ≈ 48.16)", 48.16, "48.2%"],
    ["Item Return Rate", "ratio 0-1 (measured ≈ 0.26)", 0.26, "26.0%"],
    ["Marketing ROAS by Channel", "ratio 0-∞ (measured ≈ 5.27)", 5.27, "5.27×"],
  ];

  it.each(cases)("%s reads %s as %s → %s", (name, text, value, display) => {
    expect(formatMetric(value, text, "$", name, read(text))).toMatchObject({ ok: true, display });
  });

  it("shows a load factor as the percent of a stated 0..1 rate, not a hundredth of one", () => {
    const text = SHIPPED.find(s => s.metric === "Load Factor")!.text;   // 'ratio 0..1 (0..100%); industry-typical …'
    const shown = formatMetric(0.82, text, "$", "Load Factor", read(text));
    expect(shown).toMatchObject({ ok: true, display: "82.0%" });
    expect(shown.flow).toMatchObject({ value: 82, suffix: "%" });       // the odometer paints what the string says
  });

  it("reads the unit where the text states it, not from its commentary", () => {
    const blockHours = SHIPPED.find(s => s.metric.includes("Block Hours"))!;
    const orders = SHIPPED.find(s => s.metric === "Orders per Active User")!.text;
    const stops = SHIPPED.find(s => s.metric === "Deliveries per Route / Driver")!.text;
    const transit = SHIPPED.find(s => s.metric === "Average Transit Time")!.text;
    const mrr = SHIPPED.find(s => s.metric.startsWith("Monthly / Annual"))!.text;

    // "per day" inside an hours unit is not days; "A value < 1 …" inside a ratio unit is not a currency.
    expect(formatMetric(11.5, blockHours.text, "$", blockHours.metric, read(blockHours.text)).display).toBe("11.50");
    expect(formatMetric(2, orders, "$", "Orders per Active User", read(orders)).display).toBe("2");
    expect(formatMetric(150, stops, "$", "Deliveries per Route / Driver", read(stops)).display).toBe("150");
    expect(formatMetric(36, transit, "$", "Average Transit Time", read(transit)).display).toBe("36");
    // …while a unit that says "currency" without naming one still shows the business's symbol.
    expect(formatMetric(2847126, mrr, "€", "Monthly Recurring Revenue", read(mrr)).display).toBe("€2.8M");
  });

  it("shows a downtime in minutes that no text bounds at 1", () => {
    const text = SHIPPED.find(s => s.metric.startsWith("Unplanned Downtime"))!.text;
    expect(formatMetric(42, text, "$", "Unplanned Downtime & MTBF / MTTR", read(text)))
      .toMatchObject({ ok: true, display: "42" });
  });
});

describe("what the tile still refuses to show", () => {
  const rate = "ratio 0-1 (measured ≈ 0.26)";
  const percent = "percent 0-100 (measured ≈ 2.2)";

  it("hides a stated rate that overshoots its bound or rounds to a boundary", () => {
    expect(formatMetric(1.2, rate, "$", "Item Return Rate", read(rate)).ok).toBe(false);
    expect(formatMetric(0.9996, rate, "$", "Item Return Rate", read(rate)).ok).toBe(false);
    expect(formatMetric(0.0004, rate, "$", "Item Return Rate", read(rate)).ok).toBe(false);
    expect(formatMetric(-0.5, rate, "$", "Item Return Rate", read(rate)).ok).toBe(false);
    expect(formatMetric(120, percent, "$", "Defect Rate", read(percent)).ok).toBe(false);
    expect(formatMetric(99.97, percent, "$", "Defect Rate", read(percent)).ok).toBe(false);
    expect(formatMetric(0.04, percent, "$", "Defect Rate", read(percent)).ok).toBe(false);
  });

  it("hides a figure outside a band the text states", () => {
    const hours = SHIPPED.find(s => s.metric.includes("Block Hours"))!;   // '… per day, 0..24 …'
    expect(formatMetric(11.5, hours.text, "$", hours.metric, read(hours.text)).ok).toBe(true);
    expect(formatMetric(26, hours.text, "$", hours.metric, read(hours.text)).ok).toBe(false);
  });

  it("shows a figure outside a band the text only calls typical", () => {
    const nrr = SHIPPED.find(s => s.metric.startsWith("Net Revenue Retention"))!.text;   // 'ratio, typically 0.8..1.4'
    expect(formatMetric(1.6, nrr, "$", "Net Revenue Retention (NRR / NDR)", read(nrr)))
      .toMatchObject({ ok: true, display: "1.60" });
  });

  it("reads a metric the API shipped no reading for as open — never a guessed bound", () => {
    expect(formatMetric(5, "ratio 0-1", "$", "Inventory Turnover")).toMatchObject({ ok: true, display: "5" });
  });
});

describe("a move reads in its metric's own terms", () => {
  const rate = "ratio 0-1 (measured ≈ 0.26)";
  const percent = "percent 0-100 (measured ≈ 2.2)";
  const turnover = "ratio (units sold per unit avg. inventory)";
  const aov = "ratio 0-1000 (USD per order)";

  it("is points for a rate the text states", () => {
    expect(deltaInfo([0.24, 0.26], rate, "Item Return Rate", read(rate))?.text).toBe("+2.0pts");
    expect(deltaInfo([2.2, 1.2], percent, "Defect Rate", read(percent))?.text).toBe("-1.0pts");
  });

  it("is relative for a figure no text bounds", () => {
    expect(deltaInfo([4, 5], turnover, "Inventory Turnover", read(turnover))?.text).toBe("+25.0%");
    expect(deltaInfo([400, 404], aov, "Average Order Value (AOV)", read(aov))?.text).toBe("+1.0%");
  });

  it("is still a multiplier for a return on spend", () => {
    const roas = "ratio 0-∞ (measured ≈ 5.27)";
    expect(deltaInfo([4.9, 5.27], roas, "Marketing ROAS by Channel", read(roas))?.text).toBe("+0.37×");
  });
});
