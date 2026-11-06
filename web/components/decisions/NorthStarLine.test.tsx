// @vitest-environment jsdom
/**
 * Track G5 — the North Star at the head of Decisions: the pair with its n, and "Why" opening the reasons by
 * rule and the calibration table in place. The fixture is the live install's reading on 2026-11-06.
 */
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type { NorthStar } from "@/lib/record";

const HINDSIGHT = "the prediction was booked after the decision it predicts (hindsight)";
const live: NorthStar = {
  quarter: "2026-Q4", from: "2026-10-01", until: "2027-01-01",
  loops_closed: 0, outcomes_written: 16, reliance_without_expectation: 0, closed: [],
  not_closed: Array.from({ length: 16 }, (_, i) => ({
    decision: `d${i}`, question: "Pause paid social on Mytheresa", owner: "user:amit", outcome_written: "2026-10-26",
    verdict: "cannot_tell", not_closed: `the prediction was booked 2026-10-25, after the decision it predicts (2026-09-0${i % 9 + 1}): hindsight, not a prediction`,
    rule: HINDSIGHT,
  })),
  calibration: { error: 0.402, n: 101, classes: [
    { method: "history", metric: "units_sold", judged: 9, cannot_tell: 0, stated: 0.8, observed: 0.111, gap: 0.689 },
    { method: "history", metric: "return_rate", judged: 10, cannot_tell: 1, stated: 0.8, observed: 0.7, gap: 0.1 },
    { method: "declared", metric: "gmv", judged: 0, cannot_tell: 1, gap: null },
  ] },
  sentence: "2026-Q4: 0 loops closed of 16 outcomes written · calibration error 0.40 over 101 settled predictions",
};

// The calibration table's grid reads the viewport; jsdom has no matchMedia.
beforeAll(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: false, media: q, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  }));
});

vi.mock("@/lib/record", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/record")>()),
  getNorthStar: vi.fn(async () => live),
}));

import { NorthStarLine, reasonsByRule } from "./NorthStarLine";
import { bookedAfter } from "./DecisionsPanel";

describe("reasonsByRule", () => {
  it("groups the reasons by their rule, not by the dates in their sentences", () => {
    expect(reasonsByRule(live)).toEqual([{ rule: HINDSIGHT, n: 16 }]);
  });
});

describe("NorthStarLine", () => {
  it("says the pair with its n, and opens the reasons and the table in place", async () => {
    render(<Theme><NorthStarLine /></Theme>);
    const sentence = await screen.findByTestId("north-star-sentence");
    expect(sentence.textContent).toContain("0 loops closed of 16 outcomes written");
    expect(sentence.textContent).toContain("calibration error 0.40 over 101 settled predictions");
    expect(screen.queryByTestId("north-star-why")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /why/i }));
    await waitFor(() => expect(screen.getByTestId("north-star-why")).toBeTruthy());
    const reasons = screen.getAllByTestId("north-star-reason").map(li => li.textContent);
    expect(reasons).toEqual([`16 not closed — ${HINDSIGHT}`]);
    const why = screen.getByTestId("north-star-why");
    expect(why.textContent).toContain("units_sold");
    expect(why.textContent).not.toContain("gmv");                 // a class that judged nothing has no gap to show
    const text = why.textContent ?? "";
    expect(text.indexOf("units_sold")).toBeLessThan(text.indexOf("return_rate"));   // worst-calibrated first
    expect(why.textContent).toContain("0.11");                     // two places, not 0.111
  });
});

describe("bookedAfter (the reader's hindsight note)", () => {
  it("is the North Star's rule, with its five minutes' grace", () => {
    expect(bookedAfter("2026-10-25T22:13:16Z", "2026-09-01T09:00:00Z")).toBe(true);
    expect(bookedAfter("2026-11-05T10:29:52Z", "2026-11-05T10:29:51Z")).toBe(false);
    expect(bookedAfter("", "2026-09-01T09:00:00Z")).toBe(false);
  });
});
