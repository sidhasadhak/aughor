// @vitest-environment jsdom
/**
 * The inquiry in a decision's reader (the decision-framework study §3.1, §3.3): every stage from where it arose to
 * what was learned, each step a line and its why, the receipt only when asked, the loops, and the decisions it
 * revises and that revised it.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { InquiryView } from "@/lib/record";
import { fireEvent, render, screen, within } from "@/lib/testing";

const rec = vi.hoisted(() => ({ getInquiryView: vi.fn() }));
vi.mock("@/lib/record", async original => ({ ...(await original<typeof import("@/lib/record")>()), ...rec }));
const nav = vi.hoisted(() => ({ requestTab: vi.fn() }));
vi.mock("@/lib/navigate", async original => ({ ...(await original<typeof import("@/lib/navigate")>()), ...nav }));

const { InquirySection } = await import("@/components/decisions/DecisionsPanel");

const step = (line: string, why = "", receipt: Record<string, unknown> = {}) => ({ kind: "x", line, why, receipt, at: "", ref: "" });
const VIEW: InquiryView = {
  decision: "d2", question: "Pause paid social?", connection_id: "lux",
  stages: [
    { stage: "arising", words: "Where it arose", steps: [step("an inquiry · waiting", "“What did paid social bring?”, opened by person")] },
    { stage: "gathering", words: "What it stood on", steps: [step("observation · measured", "“Paid social brought 132 of 923 orders”", { claim: "c1", warrants: ["run rcpt-1"] })] },
    { stage: "reviewed", words: "Reviewed", steps: [step("missed", "the metric moved +10 against its comparison group", { effect: 10, method: "comparison" })] },
  ],
  loops: [step("reopened: a claim it stood on moved", "the attribution channel was wrong; waiting for a person's answer")],
  backwards: [{ decision: "d1", question: "Paid social budget", chosen: "keep it", decided_at: "2026-05-01", why: "this decision revises it" }],
  forwards: [],
  composed_by: "code, from the Record's own fields — no model",
};

beforeEach(() => { rec.getInquiryView.mockReset().mockResolvedValue(VIEW); nav.requestTab.mockReset(); });

describe("the inquiry, as people read it", () => {
  it("reads every stage as a line and its why, with the loops and what it revises", async () => {
    render(<InquirySection id="d2" version={3} />);
    const t = await screen.findByTestId("decision-inquiry");
    expect(t).toHaveTextContent("Where it arose");
    expect(t).toHaveTextContent("Paid social brought 132 of 923 orders");
    expect(t).toHaveTextContent("missed");
    expect(t).toHaveTextContent("Loops");
    expect(t).toHaveTextContent("the attribution channel was wrong");
    expect(t).toHaveTextContent("no model");
    fireEvent.click(within(t).getByRole("button", { name: "Open it →" }));
    expect(nav.requestTab).toHaveBeenCalledWith("decisions", { id: "d1" });
  });

  it("shows a step's receipt only when asked", async () => {
    render(<InquirySection id="d2" version={3} />);
    await screen.findByTestId("decision-inquiry");
    expect(screen.queryByTestId("inquiry-receipt")).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "Receipt" })[0]);
    expect(screen.getByTestId("inquiry-receipt")).toHaveTextContent("warrants: run rcpt-1");
  });
});
