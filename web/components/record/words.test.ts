import { describe, expect, it } from "vitest";

import {
  breakdown, chosenWords, countBy, firstSentence, inquiryLabel, inquiryStateShort, modeOf, periodWords, predictionView,
  shortLabel, waitingShort, whenWords,
} from "./words";

// The live install's scheduled inquiry, as the Record holds it: the grounding code wrote for the model, cut at 500
// characters — the person's own question did not survive the cut.
const SCHEDULED_CUT =
  "[Scheduled-run context — written by code, not inferred]\nThis is a scheduled daily run at 2026-10-06T09:00Z.\n" +
  "Observe 2026-09-28 (UTC), the most recent complete day given this automation's observation lag of 8 days.\n" +
  "Say in the report ";

describe("an inquiry's question as a row label", () => {
  it("names a scheduled run for what it is when the person's question was cut off", () => {
    expect(inquiryLabel(SCHEDULED_CUT)).toEqual({ text: "Scheduled daily run", full: SCHEDULED_CUT.trim(), scheduled: true });
  });

  it("reads the person's question when the record kept it after the grounding", () => {
    const kept = `${SCHEDULED_CUT}\n\nWhat changed in theLook in the last day? Give me the top three findings.`;
    expect(inquiryLabel(kept).text).toBe("What changed in theLook in the last day?");
  });

  it("keeps an ordinary question whole, its snake_case read as words", () => {
    expect(inquiryLabel("Why did the delivered stage of order_fulfilment slowed: p90 4.0 → 5.0 days?").text)
      .toBe("Why did the delivered stage of order fulfilment slowed: p90 4.0 → 5.0 days?");
  });
});

describe("short words for long ledger text", () => {
  it("turns a decision's kind prefix into words and keeps its first clause", () => {
    expect(shortLabel("open_case: order:2 is in overdue_dispatch; proposed by the OC-8 receipt script"))
      .toBe("Open case: order:2 is in overdue dispatch");
    expect(shortLabel("cockpit:Marketing Dashboard: I am creating a Marketing cockpit using the existing cards."))
      .toBe("Cockpit: Marketing Dashboard");
  });

  it("cuts at the first full stop, not at a decimal", () => {
    expect(firstSentence("Beauty loses only 4.62% of revenue to returns. It keeps the highest margin."))
      .toBe("Beauty loses only 4.62% of revenue to returns.");
  });

  it("folds a long waiting reason to its head", () => {
    expect(waitingShort("data that would settle the open items")).toBe("data");
    expect(waitingShort("the October close")).toBe("the October close");
    expect(inquiryStateShort({ state: "waiting", waiting_for: "data that would settle the open items", closed_as: "" }))
      .toBe("waiting for data");
  });

  it("says what was chosen in a word for an approval", () => {
    const options = [{ id: "approve", description: "approve the proposal" }, { id: "decline", description: "reject it" }] as never;
    expect(chosenWords({ chosen: "decline", options })).toBe("declined");
    expect(chosenWords({ chosen: "approve", options })).toBe("approved");
  });
});

describe("days as a reader says them", () => {
  const now = new Date("2026-10-13T10:00:00Z");
  it("names the day and how far off it is — never the ISO date", () => {
    expect(whenWords("2026-11-10", now)).toBe("Tue 10 Nov · in 28 days");
    expect(whenWords("2026-10-12T09:05:49Z", now)).toBe("Mon 12 Oct · yesterday");
    expect(whenWords("", now)).toBe("");
  });

  it("reads a range of days compactly", () => {
    expect(periodWords("2026-09-07", "2026-09-13")).toBe("7–13 Sep");
    expect(periodWords("2026-10-01", "2026-10-31")).toBe("Oct 2026");
    expect(periodWords("2026-09-28", "2026-10-04")).toBe("28 Sep – 4 Oct");
  });
});

describe("a prediction read off its booked fields", () => {
  it("gives the metric, the range, the band and the verdict", () => {
    const p = predictionView({
      kind: "prediction", state: "scored",
      statement: { text: "expected: Revenue $79,438 to $98,018 for 2026-09-07 to 2026-09-13 (its own past)" },
      extra: { low: "79437.73", high: "98017.62", actual: "100794.9", scored_against: "above", band_text: "$79,438 to $98,018" },
    });
    expect(p).toMatchObject({ metric: "Revenue", period: "7–13 Sep", band: "$79,438–$98,018", actual: "$100.8K", verdict: "above" });
  });

  it("reads a percent band as ratios and a single day as that day, with no band field", () => {
    const p = predictionView({
      kind: "prediction", state: "scored",
      statement: { text: "expected: Session-to-Purchase Conversion Rate 52% to 55% for 2026-09-10 (its own past)" },
      extra: { low: 0.517202, high: 0.553699, actual: 0.5581787, scored_against: "above" },
    });
    expect(p).toMatchObject({ metric: "Session-to-Purchase Conversion Rate", period: "10 Sep", band: "52%–55%", actual: "55.8%" });
  });

  it("is null for any other kind of claim", () => {
    expect(predictionView({ kind: "finding", state: "", statement: { text: "x" }, extra: {} })).toBeNull();
  });
});

describe("counting", () => {
  it("counts most first, names the mode, and folds the tail", () => {
    const rows = ["finding", "finding", "prediction", "said", "said", "finding"];
    expect(countBy(rows, r => r)).toEqual([["finding", 3], ["said", 2], ["prediction", 1]]);
    expect(modeOf(rows, r => r)).toBe("finding");
    expect(breakdown(countBy(rows, r => r), (k, n) => (n === 1 ? k : `${k}s`))).toBe("3 findings · 2 saids · 1 more");
  });
});
