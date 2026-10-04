// @vitest-environment jsdom
/**
 * Idea 7 — the fact-check had API doors and a Slack verb, and no screen. A pasted memo goes to
 * the check on a press (never before), and the verdicts come back as the claims table.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const factCheckText = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    factCheckText: (...a: unknown[]) => factCheckText(...a),
    factCheckFile: () => Promise.reject(new Error("not this door")),
    // unstubbed, it would fetch the live API from jsdom
    getDocumentFormats: () => Promise.resolve(null),
  };
});

// antd's table measures and observes resize, neither of which jsdom has; per web/AGENTS.md the
// honest assertion is the handoff — the rows the panel gives its table.
vi.mock("@/components/AugTable", () => ({
  SqlResultTable: ({ rows }: { rows: unknown[][] }) => (
    <div data-testid="claims">
      {rows.map((r, i) => <div key={i}>{r.map((c, j) => <span key={j}>{String(c)}</span>)}</div>)}
    </div>
  ),
}));

import { FactCheckPanel } from "./FactCheckPanel";

describe("FactCheckPanel", () => {
  it("checks a pasted memo on a press and shows each claim's verdict", async () => {
    factCheckText.mockResolvedValue({
      investigation_id: "fc1",
      envelope: {
        headline: "2 numeric claims: 1 match the data, 1 contradicted, 0 could not be checked.",
        body: "- CONTRADICTED — \"Revenue was $60,000 in August\": said $60,000; the data shows 54,496.64 (10% off).",
        caveats: ["A contradicted claim is measured with the approved definition and the window the sentence names; the document may have used another."],
        grid: {
          columns: ["claim", "said", "measured", "verdict", "why"],
          rows: [
            ["Revenue was $60,000 in August", "$60,000", 54496.64, "contradicted", "said $60,000; the data shows 54,496.64 (10% off)"],
            ["We sold 573 pairs of jeans", "573", 573, "measured", "573 is what the data shows (573.00)"],
          ],
        },
      },
    });

    render(<FactCheckPanel connectionId="thelook" />);
    const press = screen.getByRole("button", { name: "Check the numbers" });
    expect(press).toBeDisabled();
    expect(factCheckText).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Memo to check"), {
      target: { value: "Revenue was $60,000 in August. We sold 573 pairs of jeans." } });
    fireEvent.click(press);

    expect(await screen.findByText(/1 match the data, 1 contradicted/)).toBeInTheDocument();
    expect(factCheckText).toHaveBeenCalledWith(
      "Revenue was $60,000 in August. We sold 573 pairs of jeans.", "thelook");
    expect(screen.getByText("contradicted")).toBeInTheDocument();
    expect(screen.getByText("measured")).toBeInTheDocument();
    // The body's contradicted line is the table's row already; it is not said twice.
    expect(screen.queryByText(/^CONTRADICTED/)).not.toBeInTheDocument();
  });
});
