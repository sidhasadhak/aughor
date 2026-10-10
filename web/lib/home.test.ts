import { describe, expect, it } from "vitest";

import type { Claim, Decision } from "@/lib/record";
import {
  ASKED, SCHEDULED_HEADER, byDay, dayWords, daysBehind, leadFigure, metricWords, percentOf, pickLead, pickQuestion,
  pickWorthALook, rangeText, standingQuestions, weekAhead,
  type Analysis, type Finding,
} from "@/lib/home";

// The install's own records, 2026-10-02 to 10-06 (theLook): four daily runs and the asks around them.
const run = (id: string, at: string, headline: string): Analysis => ({
  id, started_at: at, status: "complete", headline, connection_id: "c1",
  question: `${SCHEDULED_HEADER}\nThis is a scheduled daily run.\n\nWhat changed in theLook in the last day?`,
});
const ask = (id: string, at: string, question: string, headline: string): Analysis =>
  ({ id, started_at: at, status: "complete", question, headline, connection_id: "c1" });

const RUNS = [
  run("r24", "2026-10-02T09:01:00Z", "Revenue decreased 19.7% on September 24, 2026, amid lower order volume and AOV"),
  run("r26", "2026-10-04T09:01:00Z", "Revenue for theLook increased by 20.1% on September 26, 2026, within normal variance."),
  run("r27", "2026-10-05T09:01:00Z", "Revenue decreased 15.0% on September 27, 2026, alongside a 23.2% decline in average order value."),
  run("r28", "2026-10-06T09:01:00Z", "Revenue and Order Volume Declined on September 28, 2026, While AOV Increased"),
];
const JULY = "What was total revenue and how many units were sold in July 2026?";
const ASKS = [
  ask("a1", "2026-10-03T07:46:00Z", JULY, "In July 2026, the total revenue was $338,523.13 and 6,835 units were sold"),
  ask("a2", "2026-10-03T09:57:00Z", JULY.toUpperCase() + "  ", "In July 2026, the total revenue was $338,523.13"),
  ask("a3", "2026-10-03T14:23:00Z", JULY, "In July 2026, the total revenue was $338,523.13 and 6,835 units were sold"),
  ask("aug", "2026-10-05T21:16:00Z", "Why did Revenue change by +13% for August 2026, against July 2026?",
    "August 2026 Revenue Increased by 13.2% Driven by Search Traffic and Men's Department Growth"),
];
const ALL = [...RUNS, ...ASKS];

describe("the one thing to know", () => {
  it("is the largest move since the last visit, skipping a run that called its own move normal", () => {
    const lead = pickLead(ALL, "2026-10-03T15:00:00Z", "c1");
    expect(lead?.run.id).toBe("r27");          // 23.2% and 15.0% beat 28 Sep's unstated move
    expect(lead?.stale).toBe(false);
  });

  it("with nothing new since the last visit, it is the newest notable move, said as such", () => {
    expect(pickLead(ALL, "2026-10-07T00:00:00Z", "c1")).toEqual({ run: RUNS[3], stale: true });
  });

  it("reads the largest percentage a headline states", () => {
    expect(percentOf(RUNS[2].headline)).toBe(23.2);
    expect(percentOf(RUNS[3].headline)).toBeNull();
  });
});

describe("your standing questions", () => {
  it("are questions asked three or more times, however they were typed, never a scheduled run", () => {
    const s = standingQuestions(ALL, "c1");
    expect(s).toHaveLength(1);
    expect(s[0].count).toBe(3);
    expect(s[0].latest.id).toBe("a3");
    expect(s[0].first_at).toBe("2026-10-03T07:46:00Z");
  });
});

describe("a question for you", () => {
  it("asks about the newest analysis that credits a cause, in words from its own headline", () => {
    const q = pickQuestion(ALL, "c1", new Set());
    expect(q?.about.id).toBe("aug");
    expect(q?.text).toBe("August 2026 Revenue Increased by 13.2% Driven by Search Traffic and Men's Department Growth. "
      + "Did the team do anything that explains it?");
  });

  it("does not ask again once a person has answered", () => {
    expect(pickQuestion(ALL, "c1", new Set(["aug"]))).toBeNull();
  });
});

describe("worth another look", () => {
  const F: Finding[] = [
    { id: "f1", text: "Email drives the most unique user activity.", domain: "Key Questions", generated_at: "2026-09-27" },
    { id: "f2", text: "Skirts has the highest return rate at 12.5%.", domain: "Key Questions", generated_at: "2026-09-27" },
    { id: "f0", text: "Accessories is the top-performing category.", domain: "Key Questions", generated_at: "2026-08-26" },
  ];
  it("is the newest finding nobody acted on", () => {
    expect(pickWorthALook(F, new Set())?.id).toBe("f1");
    expect(pickWorthALook(F, new Set(["f1"]))?.id).toBe("f2");
    expect(pickWorthALook(F, new Set(["f1"]), new Set(["f2"]))?.id).toBe("f0");
  });
});

describe("the week ahead", () => {
  const decision = (review_on: string, superseded_by = ""): Decision => ({ review_on, superseded_by, chosen: "Move West orders to Houston", question: "q" } as Decision);
  const forecast = (next_check: string, state = "open"): Claim =>
    ({ next_check, state, superseded_by: "", statement: { text: "September orders 9,000 to 9,800", range_end: "" } } as unknown as Claim);

  it("lists only what lands in the next seven days, soonest first", () => {
    const due = weekAhead([decision("2026-10-09"), decision("2026-10-20"), decision("2026-10-07")],
      [forecast("2026-10-12"), forecast("2026-10-10", "scored")], "2026-10-07");
    expect(due.map(d => d.on)).toEqual(["2026-10-09", "2026-10-12"]);
    expect(due[0].what).toContain("Move West orders to Houston");
  });
});


// theLook's daily run of 2026-10-10 (analysis 4b90a7ec), its baseline phase as the record holds it, trimmed.
const REPORT = {
  spec: { metric_label: "Revenue" },
  period_as_measured: { windows: [{ tool: "baseline", start: "2026-10-02", end: "2026-10-03" }] },
  phases: [
    { phase_id: "decomposition", findings: [{ key_numbers: [{ label: "Orders", value: "528", delta: "+308" }] }] },
    { phase_id: "baseline", findings: [
      { title: "13-Day Revenue Baseline", stat_note: "z = 1.15 — within normal range",
        key_numbers: [{ label: "Historical Mean Revenue", value: "$16,728.25", delta: null }] },
      { title: "Period-over-Period Revenue Change", stat_note: null,
        key_numbers: [{ label: "Oct 2 Revenue", value: "$19,087.76", delta: "+$209.55" }],
        columns: ["observation_date", "observation_revenue", "comparison_revenue", "absolute_change", "pct_change"],
        rows: [["2026-10-02", "19087.760056495667", "18878.21005678177", "209.5499997138977", "0.011100098954488505"]] },
    ] },
  ],
};

describe("the lead's figure", () => {
  it("is read from the baseline's own numbers: the metric, the day, the value and its change, and the verdict", () => {
    expect(leadFigure(REPORT)).toEqual({ metric: "Revenue", day: "2026-10-02", value: "$19,087.76", change: "+$209.55",
      pct: 0.011100098954488505, verdict: "within normal range", unusual: false });
  });

  it("is said unusual only when the baseline says so", () => {
    const outside = structuredClone(REPORT) as { phases: { findings: Record<string, unknown>[] }[] };
    outside.phases[1].findings[0].stat_note = "z = 3.40 — outside normal range";
    expect(leadFigure(outside)?.unusual).toBe(true);
  });

  it("is none when the analysis holds no baseline value with a change — the headline is said instead", () => {
    expect(leadFigure({ phases: [{ phase_id: "decomposition", findings: REPORT.phases[0].findings }] })).toBeNull();
    expect(leadFigure(null)).toBeNull();
  });

  it("says how far behind today it is", () => {
    expect(daysBehind("2026-10-02", "2026-10-10")).toBe(8);
    expect(daysBehind("2026-10-12", "2026-10-10")).toBe(0);
    expect(dayWords("2026-10-02")).toBe("Fri 2 Oct");
    expect(dayWords("2026-09-07")).toBe("Mon 7 Sep");
  });
});

describe("the question and the week, as Home draws them", () => {
  it("keeps what a question is about apart from what is asked", () => {
    const q = pickQuestion([ask("a1", "2026-10-06T10:00:00Z", "Why did returns rise?", "Returns rose 4%, driven by outerwear.")], "c1", new Set());
    expect(q?.subject).toBe("Returns rose 4%, driven by outerwear");
    expect(q?.text).toBe(`Returns rose 4%, driven by outerwear. ${ASKED}`);
  });

  it("groups what lands by day, a forecast with the range its record holds", () => {
    const f = (on: string, metric: string, low: number, high: number, unit: string): Claim => ({
      next_check: on, state: "open", superseded_by: "", extra: { low, high },
      statement: { text: "", metric, unit, range_start: "2026-09-07", range_end: "2026-09-13" } } as unknown as Claim);
    const due = weekAhead([], [f("2026-10-12", "revenue", 79400, 98000, "$"), f("2026-10-12", "return_rate", 9.2, 11.1, "%"),
                               f("2026-10-15", "units_sold", 1595, 1924, "units")], "2026-10-10");
    const days = byDay(due);
    expect(days.map(d => [d.on, d.forecasts.length])).toEqual([["2026-10-12", 2], ["2026-10-15", 1]]);
    // a day leads with money, then counts, then shares — whatever order the record holds them in
    const order = byDay(weekAhead([], [f("2026-10-12", "return_rate", 0.09, 0.11, "ratio 0..1"),
      f("2026-10-12", "units_sold", 1595, 1924, "count"), f("2026-10-12", "revenue", 79400, 98000, "$")], "2026-10-10"));
    expect(order[0].forecasts.map(d => d.metric)).toEqual(["revenue", "units_sold", "return_rate"]);
    expect(days[0].forecasts.map(d => `${metricWords(d.metric)} ${rangeText(d.low, d.high, d.unit)}`))
      .toEqual(["Revenue $79.4K – $98.0K", "Return rate 9.2% – 11.1%"]);
    // each as its unit says, in the words theLook's forecasts hold
    expect(rangeText(1595.4, 1924.2, "count")).toBe("1,595 – 1,924");
    expect(["average_order_value_aov", "daily_active_users_dau", "units_sold", "gross_margin_percentage"].map(metricWords))
      .toEqual(["Average order value", "Daily active users", "Units sold", "Gross margin percentage"]);
    expect(rangeText(76.3, 82.6, "USD")).toBe("$76 – $83");
    expect(rangeText(0.092011, 0.111332, "ratio 0..1")).toBe("9.2% – 11.1%");
    expect(rangeText(51.39, 52.29, "percent 0-100")).toBe("51.4% – 52.3%");
    expect(rangeText(1.8586, 2.1383, "days, roughly 0-30")).toBe("1.9 – 2.1 days");
  });
});
