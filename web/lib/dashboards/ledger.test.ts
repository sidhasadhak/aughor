/**
 * What a row of the Metrics dashboard says. The figures are LuxExperience's October 2026 as the live dashboard read them
 * (2026-11-04), so each word here is one a person met.
 */
import { describe, expect, it } from "vitest";

import type { BriefingEdition, BriefingRangeBlock, BriefingRangeMeasure, ExpectedBand, MetricTrend } from "@/lib/api";
import { measuredBeforeWords } from "@/lib/briefingEdition";
import {
  bandBasisWords, bandDoubt, bandWords, briefingRangeOf, changeWords, areasOf, editionFor, expectedWords, figureWords, keyMove, namesOfMetric,
  rankWords, readoutOf, shortOf, targetWords, toneOfMove, twinsOf, unitOf, workFor,
} from "@/lib/dashboards/ledger";

const m = (over: Partial<BriefingRangeMeasure>): BriefingRangeMeasure => ({
  name: "GMV (EUR)", metric: "gmv", unit: "EUR", time_kind: "flow", confirmed: true, current: 712125, previous: 721755,
  last_year: 704142, rel: -0.0133, rel_last_year: 0.0113, status: "final", ...over,
});

const months = (values: number[]) => values.map((value, i) => {
  const d = new Date(Date.UTC(2025, 9 + i, 1)).toISOString().slice(0, 10);
  return { start: d, last_day: d, label: d, value, value_text: String(value), partial: null, current: i === values.length - 1, settling: false };
});

const trend = (values: number[], usual: Partial<NonNullable<MetricTrend["usual"]>> | null = { n: 6, outside: "" }, over: Partial<MetricTrend> = {}) => (
  { metric: "x", found: true, name: "", unit: "", definition: "", tables: [], filters: [], caveats: "", owner: "", approved_by: "", version: 1,
    time_kind: "flow", time_source: "", confirmed: true, why: "", series: months(values),
    usual: usual ? { mean: 0, low: 0, high: 1, z: 0, n: 6, outside: "", ...usual } : null, ...over } as unknown as MetricTrend);

describe("a figure, in its metric's own terms", () => {
  it("reads a unit however it was declared, from its first word", () => {
    expect(unitOf("EUR, typically 300-2000 for luxury multi-brand orders")).toEqual({ kind: "money", symbol: "€" });
    expect(unitOf("ratio 0-1 (e-commerce typically 0.005-0.05)").kind).toBe("share");
    expect(unitOf("percent 0-100 (luxury fashion typically 40-70)").kind).toBe("percent");
    expect(unitOf("%").kind).toBe("percent");
    expect(unitOf("days").kind).toBe("days");
    expect(unitOf("count").kind).toBe("plain");
    expect(unitOf(null).kind).toBe("plain");
  });

  it("prints what the old cards printed bare", () => {
    expect(figureWords(712125.4, "EUR")).toBe("€712,125");
    expect(figureWords(623.03, "EUR, typically 300-2000")).toBe("€623");
    expect(figureWords(47.137, "%")).toBe("47.1%");
    expect(figureWords(0.206, "ratio 0..1")).toBe("20.6%");
    expect(figureWords(0.0212, "ratio 0-1 (e-commerce)")).toBe("2.12%");
    expect(figureWords(99.759, "%")).toBe("99.8%");
    expect(figureWords(1.145, "days")).toBe("1.15 days");
    expect(figureWords(-2500, "USD")).toBe("−$2,500");
  });

  it("keeps the server's words where it cannot print the unit, and says nothing is there when nothing is", () => {
    expect(figureWords(110, "$", "$110")).toBe("$110");
    expect(figureWords(1143, "count")).toBe("1,143");
    expect(figureWords(null, "EUR")).toBe("—");
    expect(expectedWords({ low: 100, high: 116, text: "$100 to $116" }, "$")).toBe("$100 to $116");
    expect(expectedWords({ low: 634257, high: 759558, text: "634,257 to 759,558" }, "EUR")).toBe("€634,257 – €759,558");
    expect(bandWords(6.49, 6.56, "days")).toBe("6.49 – 6.56 days");
  });
});

describe("a change", () => {
  it("is points for a share, days for days, a percentage otherwise", () => {
    expect(changeWords(m({}), "previous")).toEqual({ text: "▼ 1.3%", dir: -1 });
    expect(changeWords(m({ rel_last_year: 0.2 }), "last_year")).toEqual({ text: "▲ 20%", dir: 1 });
    expect(changeWords(m({ unit: "ratio 0..1", current: 0.206, previous: 0.185 }), "previous")).toEqual({ text: "▲ 2.1 pts", dir: 1 });
    expect(changeWords(m({ unit: "%", current: 47.14, previous: 43.97 }), "previous").text).toBe("▲ 3.2 pts");
    expect(changeWords(m({ unit: "days", current: 1.15, previous: 1.12 }), "previous")).toEqual({ text: "▲ 0.03 days", dir: 1 });
  });

  it("is flat when it rounds to nothing", () => {
    expect(changeWords(m({ unit: "days", current: 5.38, previous: 5.381 }), "previous")).toEqual({ text: "flat", dir: 0 });
    expect(changeWords(m({ rel: 0.0001 }), "previous")).toEqual({ text: "flat", dir: 0 });
  });

  it("says why when none is stated", () => {
    expect(changeWords(m({ current_partial: "1 to 3 Oct" }), "previous").why).toContain("covers only 1 to 3 Oct");
    expect(changeWords(m({ previous_partial: "1 to 3 Sep" }), "previous").why).toContain("comparison covers only");
    expect(changeWords(m({ previous: null, rel: null }), "previous").why).toBe("There is nothing to compare it with");
    expect(changeWords(m({ previous: 0, rel: null }), "previous").why).toContain("zero");
  });
});

describe("a key movement", () => {
  it("is a metric outside its usual range", () => {
    expect(keyMove(m({}), trend([1, 2, 3], { outside: "above" }))).toBe("above");
    expect(keyMove(m({}), trend([1, 2, 3], { outside: "" }))).toBe("");
    expect(keyMove(m({}), undefined)).toBe("");
  });

  it("is never a range still under way, which reads low against whole ones, or one covering part of its range", () => {
    expect(keyMove(m({ status: "to_date" }), trend([1, 2, 3], { outside: "below" }))).toBe("");
    expect(keyMove(m({ current_partial: "1 to 3 Oct" }), trend([1, 2, 3], { outside: "below" }))).toBe("");
    expect(keyMove(m({ status: "provisional" }), trend([1, 2, 3], { outside: "above" }))).toBe("above");
  });

  it("is good or bad only where someone has said which way is good", () => {
    expect(toneOfMove("above", "down")).toBe("bad");
    expect(toneOfMove("below", "up")).toBe("bad");
    expect(toneOfMove("above", "up")).toBe("good");
    expect(toneOfMove("above", undefined)).toBe("");
    expect(toneOfMove("", "up")).toBe("");
  });
});

describe("a readout", () => {
  const conversion = [0.024, 0.026, 0.025, 0.026, 0.025, 0.025, 0.025, 0.022, 0.027, 0.027, 0.023, 0.023, 0.021];

  it("says which side of its usual range it left, and where that stands in its own past", () => {
    expect(readoutOf(m({}), trend(conversion, { outside: "below" }), "month").words).toBe("Below usual, lowest in 13 months");
    const returns = readoutOf(m({}), trend([.17, .16, .17, .16, .17, .17, .17, .19, .165, .196, .189, .185, .206], { outside: "above" }, { same_age: true }), "month");
    expect(returns.words).toBe("Above usual at this age, highest in 13 months");
    expect(returns.plain).toBe(false);
  });

  it("reads quietly in its usual range, unless a year ago or its own past says otherwise", () => {
    const flat = [10, 10, 10, 10, 10, 11, 9, 10, 11, 9, 10, 11, 10];
    expect(readoutOf(m({ rel_last_year: 0.01 }), trend(flat), "month")).toEqual({ words: "In usual range", plain: true });
    expect(readoutOf(m({ rel_last_year: 0.15, current: 154, last_year: 133 }), trend(flat), "month")).toEqual({ words: "In usual range, above a year ago", plain: false });
    expect(readoutOf(m({ unit: "ratio 0..1", current: 0.168, last_year: 0.192, rel_last_year: -0.12 }), trend(flat), "month").words).toBe("In usual range, below a year ago");
    // under two points on a share is not far from a year ago, whatever its percentage
    expect(readoutOf(m({ unit: "%", current: 6.67, last_year: 7.27, rel_last_year: -0.08 }), trend(flat), "month").plain).toBe(true);
    expect(readoutOf(m({}), trend(flat, { outside: "" }, { same_age: true }), "month").words).toBe("In usual range at this age");
  });

  it("says when it cannot say", () => {
    expect(readoutOf(m({}), undefined, "month").words).toBe("");
    expect(readoutOf(m({}), trend([], null, { why: "the connection could not be opened" }), "month").words).toBe("Its earlier ranges could not be read");
    expect(readoutOf(m({}), trend([1, 2], null), "month").words).toBe("Too few earlier readings to say what is usual");
    expect(readoutOf(m({ status: "to_date" }), trend([1, 2, 3], { outside: "below" }), "month").words).toBe("Under way, so not read against its usual range");
    expect(readoutOf(m({ current_partial: "1 to 3 Oct" }), trend([1, 2, 3]), "month").words).toBe("Covers only 1 to 3 Oct");
  });

  it("names the metric a row reads the same as", () => {
    expect(readoutOf(m({}), trend([1, 2, 3], { outside: "above" }), "month", "Gross Margin on Items").words).toBe("Reads the same as Gross Margin on Items");
  });

  it("states a rank since the month it last stood there, with the year when it is another", () => {
    expect(rankWords(trend([9, 1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1, 7]), "month")).toBe("highest since Oct ’25");
    expect(rankWords(trend([3, 3, 3, 9, 3, 3, 3, 3, 3, 3, 3, 3, 5]), "month")).toBe("highest since Jan");
    expect(rankWords(trend([7, 7, 7, 1, 7, 7, 7, 7, 7, 7, 7, 7, 5]), "month")).toBe("lowest since Jan");
    expect(rankWords(trend([5, 5, 5, 5, 5, 5, 5, 4, 6, 4, 6, 4, 5]), "month")).toBe("");
    expect(rankWords(trend([5, 6, 7], null), "month")).toBe("");
    expect(rankWords(trend([1, 2, 3, 4], { n: 3 }), "week")).toBe("highest in 4 weeks");
  });
});

describe("two names for one figure", () => {
  it("is found only when every range shown reads the same, and is named on the later row", () => {
    const a = m({ metric: "items", name: "Gross Margin on Items" }), b = m({ metric: "margin", name: "Gross Margin %" }), c = m({ metric: "other", name: "Other" });
    const twins = twinsOf([a, b, c], { items: trend([44.94, 46.19, 45.81]), margin: trend([44.94, 46.19, 45.81]), other: trend([44.94, 46.19, 45.82]) });
    expect(twins).toEqual({ margin: "Gross Margin on Items" });
    expect(twinsOf([a, b], { items: trend([1, 2]), margin: trend([1, 2]) })).toEqual({});     // too few readings to say
    const share = m({ metric: "rate", name: "A rate", unit: "ratio 0..1" });
    expect(twinsOf([a, share], { items: trend([1, 2, 3]), rate: trend([1, 2, 3]) })).toEqual({});   // two units, not one figure
  });
});

describe("the areas", () => {
  const area = (id: string, name: string, order: number) => ({ id, name, order });
  const sales = area("orders_sales", "Orders & sales", 0), margin = area("margin_pricing", "Margin & pricing", 2), crm = area("crm", "CRM & consent", 8);
  const block = {
    measured: [m({ metric: "gm", name: "Gross Margin %", area: margin }), m({ metric: "gmv", area: sales }), m({ metric: "aov", name: "AOV", area: sales }), m({ metric: "free", name: "Unplaced", area: null })],
    unmeasured: [
      { name: "Email open rate", metric: "o", reason: "its data ends 2025-05-19, before this range", data_ends: "2025-05-19", area: crm },
      { name: "Email click rate", metric: "c", reason: "its data ends 2025-05-19, before this range", data_ends: "2025-05-19", area: crm },
      { name: "Markdown Penetration", metric: "md", reason: "its data ends 2024-04-05, before this range", data_ends: "2024-04-05", area: margin },
      { name: "Marketing ROAS", reason: "its definition was deprecated, so it is not measured under this name", area: null },
    ],
  } as unknown as BriefingRangeBlock;

  it("are the industry's areas in the order its business reads them, what could not be placed last", () => {
    expect(areasOf(block).map(d => d.name)).toEqual(["Orders & sales", "Margin & pricing", "CRM & consent", "Everything else"]);
  });

  it("hold each row in the order it came, whatever it reads", () => {
    expect(areasOf(block)[0].rows.map(r => r.metric)).toEqual(["gmv", "aov"]);
  });

  it("keep what was not measured inside them, those with one reason as one row", () => {
    const [, mar, c, other] = areasOf(block);
    expect(mar.notMeasured).toEqual([{ names: ["Markdown Penetration"], why: "Data ended Apr 2024", ended: true, deprecated: false }]);
    expect(c.rows).toEqual([]);
    expect(c.notMeasured[0].names).toEqual(["Email open rate", "Email click rate"]);
    expect(other.notMeasured[0]).toMatchObject({ deprecated: true, ended: false });
    expect(other.rows.map(r => r.metric)).toEqual(["free"]);
  });
});

describe("what the platform knows of a metric", () => {
  const source = (id: string, kind: string, facts: Record<string, unknown>) => ({ id, kind, facts, label: "", columns: [], rows: [], sql: "", status: "", receipts: [], caveats: [], note: "", error: "", unit: "", better: "none" });
  const edition = {
    built: true, scope_key: "c",
    period: { measured: [{ id: "gross_margin_items", metric: "item_gross_margin_pct", why: "Margin before returns." }] },
    sources: {
      analysis_1: source("analysis_1", "analysis", { confidence: "MEDIUM", completed: "3 Nov", inv_id: "b52cba32" }),
      decision_1: source("decision_1", "decision", { state: "due for review 26 Nov", decision_id: "7b3f" }),
      gross_margin_items: source("gross_margin_items", "check", {}),
    },
    blocks: [
      { id: "a", type: "context", source: "analysis_1", text: "Unarrived returns explain most of the rise in net revenue and profit per order." },
      { id: "d", type: "context", source: "decision_1", text: "The decision was in force during the Mytheresa GMV dip of {€262,743|gmv_oct}." },
      { id: "f", type: "figure", source: "gross_margin_items", text: "Item margin is above its usual range." },
    ],
  } as unknown as BriefingEdition;

  it("is the line under its own figure, word for word", () => {
    expect(workFor(m({ metric: "item_gross_margin_pct", name: "Gross Margin on Items" }), edition)).toEqual([
      { kind: "The Briefing", when: "", text: "Item margin is above its usual range." }]);
  });

  it("is the platform's work that names it, however the sentence shortens the name", () => {
    const net = workFor(m({ metric: "net", name: "Net Revenue (EUR, after refunds)" }), edition);
    expect(net).toEqual([{ kind: "Deep analysis", when: "3 Nov · medium confidence", text: expect.stringContaining("net revenue"), run: "b52cba32" }]);
    expect(workFor(m({ metric: "gp", name: "Gross Profit per Order (excl. returned items)" }), edition)[0].run).toBe("b52cba32");
    const gmv = workFor(m({}), edition);
    expect(gmv).toEqual([{ kind: "Decision", when: "due for review 26 Nov", text: "The decision was in force during the Mytheresa GMV dip of €262,743.", decision: "7b3f" }]);
  });

  it("is nothing for a metric nothing names, and nothing when no Briefing was written", () => {
    expect(workFor(m({ metric: "conv", name: "Session Conversion Rate" }), edition)).toEqual([]);
    expect(workFor(m({ metric: "net", name: "Net Revenue" }), { ...edition, built: false })).toEqual([]);
    expect(workFor(m({}), null)).toEqual([]);
  });

  it("never takes one word of a name for the name", () => {
    expect(namesOfMetric("Gross Profit per Order (excl. returned items)")).toEqual(["gross profit per order", "profit per order"]);
    expect(namesOfMetric("Average Order Value (AOV)")).toEqual(["average order value", "aov"]);
    expect(namesOfMetric("GMV (EUR)")).toEqual(["gmv", "eur"].slice(0, 2));
    const said = { ...edition, blocks: [{ id: "x", type: "context", source: "analysis_1", text: "Margin moved on returns." }] } as unknown as BriefingEdition;
    expect(workFor(m({ metric: "gm", name: "Gross Margin" }), said)).toEqual([]);
  });
});

describe("a Briefing under its own name", () => {
  it("reads a dashboard's previous range under the name the Briefing keeps it", () => {
    expect(briefingRangeOf({ preset: "previous_week" })).toEqual({ preset: "last_week" });
    expect(briefingRangeOf({ preset: "previous_month" })).toEqual({ preset: "last_month" });
    expect(briefingRangeOf({ preset: "previous_year" })).toEqual({ preset: "last_year" });
  });

  it("leaves every other range as it is", () => {
    expect(briefingRangeOf({ preset: "last_month" })).toEqual({ preset: "last_month" });
    expect(briefingRangeOf({ preset: "custom", start: "2026-01-01", end: "2026-01-31" })).toEqual({ preset: "custom", start: "2026-01-01", end: "2026-01-31" });
  });

  it("takes an edition only if it is of this very range", () => {
    const block = { start: "2026-10-01", last_day: "2026-10-31" } as BriefingRangeBlock;
    const of = (start: string, last_day: string) => ({ built: true, period: { start, last_day } }) as BriefingEdition;
    const october = of("2026-10-01", "2026-10-31");
    expect(editionFor(october, block)).toBe(october);
    expect(editionFor(of("2026-09-01", "2026-09-30"), block)).toBeNull();
    expect(editionFor(of("2026-10-01", "2026-10-30"), block)).toBeNull();
    expect(editionFor(null, block)).toBeNull();
    expect(editionFor({ built: false } as BriefingEdition, block)).toBeNull();
  });
});

describe("what a band stands on", () => {
  const band = (over: Partial<ExpectedBand>) => ({
    claim_id: "", low: 1, mid: 2, high: 3, text: "1 to 3", state: "open", scored_against: null, n: 6, held: 3, cases: 4, coverage: 0.8,
    must_say: ["6 earlier ranges, each read at the same age: 1 to 3 at 80% stated coverage", "on this metric the interval held 3 of 4 times"], ...over,
  }) as ExpectedBand;

  it("says what it is built from, what it claims, and how it has done, without repeating itself", () => {
    expect(bandBasisWords(band({}))).toBe("A band from its own past, not a target, stated to hold 80% of the time. From 6 earlier ranges, each read at the same age. On this metric it has held 3 of 4 times.");
  });

  it("says when it could not be tested", () => {
    expect(bandBasisWords(band({ cases: 0, held: 0 }))).toContain("too few ranges to test it on");
  });

  it("claims nothing it did not book", () => {
    expect(bandBasisWords(band({ coverage: null, must_say: [] }))).toBe("A band from its own past, not a target. On this metric it has held 3 of 4 times.");
  });

  it("is doubted on the row only when wrong more often than right", () => {
    expect(bandDoubt(band({ held: 1, cases: 4 }))).toBe("held 1 of 4");
    expect(bandDoubt(band({ held: 2, cases: 4 }))).toBe("");
    expect(bandDoubt(band({ held: 0, cases: 0 }))).toBe("");
    expect(bandDoubt(null)).toBe("");
  });
});

describe("a range in a person's words", () => {
  it("prints when it began, with its year unless that is the year named", () => {
    expect(shortOf("2025-10-01", "month")).toBe("Oct ’25");
    expect(shortOf("2025-10-01", "month", "2025-12-01")).toBe("Oct");
    expect(shortOf("2025-10-01", "month", "2026-10-01")).toBe("Oct ’25");
    expect(shortOf("2026-10-26", "week")).toBe("26 Oct ’26");
    expect(shortOf("2025-01-01", "year")).toBe("2025");
  });

  it("names the range a band is for as the columns do", () => {
    expect(targetWords({ start: "2026-11-01", last_day: "2026-11-30", label: "2026-11-01 to 2026-11-30", settles_on: "" }, "month")).toBe("Nov 2026");
  });
});

describe("work done before a definition changed", () => {
  const analysis = (changed: unknown) => ({ id: "a", kind: "analysis", facts: { inv_id: "b52", completed: "2026-11-03", definitions_changed: changed } });
  const edition = (changed: unknown) => ({
    built: true, scope_key: "c", period: { measured: [] }, sources: { a: analysis(changed) },
    blocks: [{ id: "x", type: "context", source: "a", text: "Unarrived returns explain the rise in net revenue." }],
  }) as unknown as BriefingEdition;
  const net = { metric: "net_revenue_eur", label: "Net Revenue (EUR, after refunds)", on: "2026-11-04" };

  it("says so on the metric's row, whatever the words around it say", () => {
    expect(workFor(m({ metric: "net", name: "Net Revenue" }), edition([net]))[0].note)
      .toBe("Finished before the definition of Net Revenue changed on 4 Nov 2026, so what it says of it is about the old figures.");
  });

  it("names every metric, and the last day when they changed on different ones", () => {
    const gp = { metric: "gp", label: "Gross Profit per Order (excl. returned items)", on: "2026-10-30" };
    expect(measuredBeforeWords(analysis([net, gp]) as never))
      .toBe("Finished before the definition of Net Revenue and Gross Profit per Order changed, last on 4 Nov 2026, so what it says of them is about the old figures.");
  });

  it("says nothing of work that was not, or of another kind of source", () => {
    expect(workFor(m({ metric: "net", name: "Net Revenue" }), edition([]))[0].note).toBeUndefined();
    expect(measuredBeforeWords(analysis(undefined) as never)).toBe("");
    expect(measuredBeforeWords({ kind: "finding", facts: { definitions_changed: [net] } } as never)).toBe("");
    expect(measuredBeforeWords(undefined)).toBe("");
  });
});

describe("a figure not at equal age", () => {
  // theLook, 2026-11-04: Revenue's 662,967 "highest in 13 months" against months whose rows have stopped being written
  const young = m({ status: "provisional", equal_age: { equal: false, why: "part of any difference is the difference in age" } });
  const outside = trend([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 9], { n: 6, outside: "above", low: 0.9, high: 1.1, mean: 1, z: 3 });

  it("is not a key movement, however far it sits from its past", () => {
    expect(keyMove(young, outside)).toBe("");
    expect(keyMove({ ...young, equal_age: { equal: true, why: "" } }, outside)).toBe("above");
    expect(keyMove({ ...young, equal_age: undefined }, outside)).toBe("above");
  });

  it("says why it is not read, and claims no rank", () => {
    const said = readoutOf(young, outside, "month");
    expect(said).toEqual({ words: "Not read against its usual range", plain: true });
  });
});
