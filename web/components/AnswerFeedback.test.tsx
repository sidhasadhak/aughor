// @vitest-environment jsdom
/**
 * The one feedback control on an answer. A quick answer used to carry two thumbs pairs — the
 * panel's under the answer and a second inside "Methodology & details" — both posting the same
 * verdict for the same receipt. This is the survivor: one 👍 posts ONE accept; one 👎 posts the
 * signal and opens the what-was-wrong form, whose correction goes to the verdict ledger.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnswerFeedback } from "@/components/AnswerFeedback";
import { EMPTY_TURN, type ChatTurn } from "@/lib/chatTurn";

const calls: { url: string; body: Record<string, unknown> }[] = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), body: JSON.parse(String(init?.body ?? "{}")) });
    return new Response(JSON.stringify({ accepted: true }), { status: 200 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

const turn = (over: Partial<ChatTurn> = {}): ChatTurn => ({
  ...EMPTY_TURN, id: "t1", mode: "ask", status: "done",
  question: "How many attendance rows match an event?",
  sql: "SELECT COUNT(*) AS att_rows FROM event_attendance",
  receiptId: "inv-1", headline: "All 1,642 attendance rows match an event.",
  ...over,
} as ChatTurn);

const posted = (suffix: string) => calls.filter((c) => c.url.endsWith(suffix));

describe("the feedback control on an answer", () => {
  it("draws one thumbs pair, and nothing for a turn without a receipt", () => {
    const { container, rerender } = render(<AnswerFeedback turn={turn()} connectionId="c1" />);
    expect(screen.getAllByLabelText("Helpful")).toHaveLength(1);
    expect(screen.getAllByLabelText("Not helpful")).toHaveLength(1);
    rerender(<AnswerFeedback turn={turn({ receiptId: null })} connectionId="c1" />);
    expect(container.textContent).toBe("");
  });

  it("a 👍 posts one accept for the receipt, says so, and is not asked again", async () => {
    render(<AnswerFeedback turn={turn()} connectionId="c1" />);
    fireEvent.click(screen.getByLabelText("Helpful"));
    await waitFor(() => expect(screen.getByText(/recorded as accepted/)).toBeInTheDocument());
    expect(posted("/chat/feedback")).toHaveLength(1);
    expect(posted("/chat/feedback")[0].body).toMatchObject({ conn_id: "c1", turn_id: "inv-1", verdict: "helpful" });
    expect(screen.queryByLabelText("Helpful")).toBeNull();
  });

  it("a 👎 posts the signal and opens the what-was-wrong form; the correction reaches the verdict ledger", async () => {
    render(<AnswerFeedback turn={turn()} connectionId="c1" />);
    fireEvent.click(screen.getByLabelText("Not helpful"));
    expect(posted("/chat/feedback")[0].body).toMatchObject({ turn_id: "inv-1", verdict: "unhelpful" });
    const note = await screen.findByPlaceholderText(/What was wrong/);
    fireEvent.change(note, { target: { value: "revenue should exclude cancelled orders" } });
    fireEvent.click(screen.getByText("Record correction"));
    await waitFor(() => expect(screen.getByText(/Correction recorded/)).toBeInTheDocument());
    expect(posted("/verify/verdict")).toHaveLength(1);
    expect(posted("/verify/verdict")[0].body).toMatchObject({
      verdict: "reject", connection_id: "c1", investigation_id: "inv-1",
      note: "revenue should exclude cancelled orders",
      sql_source: "SELECT COUNT(*) AS att_rows FROM event_attendance",
    });
    expect(posted("/chat/feedback")).toHaveLength(1);
  });
});
