import { describe, expect, it } from "vitest";

import type { Claim, Decision } from "@/lib/record";
import {
  SCHEDULED_HEADER, percentOf, pickLead, pickQuestion, pickWorthALook, standingQuestions, weekAhead,
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
