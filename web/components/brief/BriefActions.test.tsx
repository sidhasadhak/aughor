// CB-6 / CB-7 — the line under a cited finding: the goal it bears on and the one action beside it.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BriefActions } from "./BriefActions";

const base = { insight_id: "i", domain: "ops", angle: "returns", finding: "f" };

describe("BriefActions", () => {
  it("names the goal and the play with its learned rate, and nothing for a bare citation", () => {
    render(<BriefActions citations={[
      { ...base, ref: "1", priority: "return rate", action: { kind: "play", text: "Pause the two lowest-margin carriers", why: "the playbook's best play", executable: false, success_rate: 0.8 } },
      { ...base, ref: "2" },
    ]} />);
    const list = screen.getByTestId("brief-actions");
    expect(list.textContent).toContain("bears on the goal: return rate");
    expect(list.textContent).toContain("Pause the two lowest-margin carriers");
    expect(list.textContent).toContain("worked 80% of the time");
    expect(list.querySelectorAll("li")).toHaveLength(1);
  });

  it("an executable recommendation opens the inbox through the caller", () => {
    const open = vi.fn();
    render(<BriefActions onOpenInvestigation={open} citations={[
      { ...base, ref: "1", action: { kind: "recommendation", text: "Move the cut-off", why: "the cited investigation's first recommendation", executable: true, inv_id: "inv9", rec_index: 0 } },
    ]} />);
    fireEvent.click(screen.getByText("execute in the inbox"));
    expect(open).toHaveBeenCalledWith("inv9");
  });

  it("renders nothing when no citation carries a goal or an action", () => {
    const { container } = render(<BriefActions citations={[{ ...base, ref: "1" }]} />);
    expect(container.textContent).toBe("");
  });
});
