// @vitest-environment jsdom
/**
 * Idea 5 — a restored answer whose own query now returns different numbers says so under the
 * answer: what it said, what it is now, and why (late rows, a restatement, or "cannot tell").
 * The shape is `aughor/answer/recheck.py`'s entry, as `data-recheck` carries it.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnswerRecheck } from "@/components/AnswerRecheck";
import type { AnswerRecheck as Recheck } from "@/lib/api";
import { projectTurn } from "@/lib/chatTurn";

const entry = (over: Partial<Recheck> = {}): Recheck => ({
  checked_at: "2026-09-23T06:00:00Z", status: "changed", cause: "late_rows", lag_days: 3,
  changed: 4,
  changes: [
    { label: { day: "2026-09-20" }, column: "orders", old: 1744, new: 1902, rel: 0.0906, day: "2026-09-20", cause: "late_rows" },
    { label: { day: "2026-09-20" }, column: "revenue", old: 135943, new: 144633, rel: 0.0639, day: "2026-09-20", cause: "late_rows" },
    { label: { day: "2026-09-19" }, column: "orders", old: 1744, new: 1830, rel: 0.049, day: "2026-09-19", cause: "late_rows" },
    { label: { day: "2026-09-18" }, column: "orders", old: 1744, new: 1840, rel: 0.055, day: "2026-09-18", cause: "late_rows" },
  ],
  ...over,
});

describe("AnswerRecheck", () => {
  it("says what the answer said, what it is now, and why", () => {
    render(<AnswerRecheck recheck={entry()} />);
    expect(screen.getByText(/this answer has changed/)).toBeTruthy();
    expect(screen.getByText(/orders for 2026-09-20 was 1,744, now 1,902 \(\+9\.1%\)/)).toBeTruthy();
    expect(screen.getByText("1 more number changed too.")).toBeTruthy();
    expect(screen.getByText(/Late rows: this source settles after 3 days/)).toBeTruthy();
  });

  it("does not guess a cause it cannot know", () => {
    render(<AnswerRecheck recheck={entry({ cause: "unknown", lag_days: null })} />);
    expect(screen.getByText(/cannot say whether these are late rows or a restatement/)).toBeTruthy();
  });

  it("renders nothing for an answer that did not change", () => {
    const { container } = render(<AnswerRecheck recheck={entry({ status: "unchanged", changes: [] })} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("projectTurn", () => {
  it("puts a restored answer's re-check on the turn, and leaves other turns without one", () => {
    const withRecheck = projectTurn("How many orders?", {
      id: "a1", role: "assistant",
      parts: [{ type: "data-headline", data: { headline: "1,744 a day" } },
              { type: "data-recheck", data: entry() }],
    } as never);
    expect(withRecheck.recheck?.changes[0].new).toBe(1902);
    const plain = projectTurn("How many orders?", {
      id: "a2", role: "assistant", parts: [{ type: "data-headline", data: { headline: "1,744 a day" } }],
    } as never);
    expect(plain.recheck).toBeNull();
  });
});
