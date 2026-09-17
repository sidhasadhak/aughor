// @vitest-environment jsdom
/**
 * IP-1 — a deep report that states a move lists the known ways that move can be the data rather than
 * the business ("Rule out first"), each with its fix, and says in the same breath that none was checked
 * against the data. The shape is the backend's `aughor/playbook/rule_outs.py` payload.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RuleOutsSection } from "@/components/brief/RuleOuts";
import type { RuleOuts } from "@/lib/types";

const ruleOuts = (over: Partial<RuleOuts> = {}): RuleOuts => ({
  direction: "down",
  metric: "GMV",
  matched: ["Gross Merchandise Value (GMV)"],
  note: "Not checked against your data.",
  lead: "Known ways Gross Merchandise Value (GMV) can read lower than it is. Not checked against your data.",
  items: [
    { cause: "Late-arriving orders not yet loaded for the most recent period", fix: "Exclude the open period",
      play_id: "kb_ec_gmv_deflation_late_a1b2c3", version: 1, receipt: "pbk_1" },
    { cause: "Currency conversion applied twice", fix: "",
      play_id: "kb_ec_gmv_deflation_fx_d4e5f6", version: 2, receipt: "pbk_2" },
  ],
  ...over,
});

describe("Rule out first", () => {
  it("lists each cause with its fix under the lead the backend sent", () => {
    render(<RuleOutsSection ruleOuts={ruleOuts()} />);

    expect(screen.getByText("Rule out first")).toBeInTheDocument();
    expect(screen.getByText(
      "Known ways Gross Merchandise Value (GMV) can read lower than it is. Not checked against your data.",
    )).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Late-arriving orders not yet loaded for the most recent period")).toBeInTheDocument();
    expect(screen.getByText("Fix: Exclude the open period")).toBeInTheDocument();
    expect(screen.getByText("Currency conversion applied twice")).toBeInTheDocument();
    expect(screen.getAllByText(/^Fix:/)).toHaveLength(1);          // a cause without a fix shows none
  });

  it("still says nothing was checked when a payload carries no lead", () => {
    render(<RuleOutsSection ruleOuts={ruleOuts({ lead: "" })} />);
    expect(screen.getByText("Not checked against your data.")).toBeInTheDocument();
  });

  it("renders nothing when the report states no move or nothing matched", () => {
    const { container, rerender } = render(<RuleOutsSection ruleOuts={undefined} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<RuleOutsSection ruleOuts={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<RuleOutsSection ruleOuts={ruleOuts({ items: [] })} />);
    expect(container).toBeEmptyDOMElement();
  });
});
