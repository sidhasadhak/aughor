// @vitest-environment jsdom
/**
 * The platform's proposal under a mission (the decision-framework study §3.1, reading B): a decision of each declared
 * kind that moves the objective, each option with what the Record predicts for it. Choosing books a decision of that
 * kind toward the mission, through the declare door; nothing is booked before.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MissionDetail, MissionProposal } from "@/lib/record";
import { fireEvent, render, screen, waitFor } from "@/lib/testing";

const rec = vi.hoisted(() => ({ listMissionProposals: vi.fn(), declareDecision: vi.fn() }));
vi.mock("@/lib/record", async original => ({ ...(await original<typeof import("@/lib/record")>()), ...rec }));

const { Proposals } = await import("@/components/missions/MissionsPanel");

const MISSION = { id: "m1", version: 2, state: "active", objective: { metric: "gmv", direction: "up" } } as unknown as MissionDetail;
const PROPOSAL: MissionProposal = {
  kind: "decision_kind:a_price_change", kind_name: "a price change", mission: "m1",
  question: "a price change toward “Grow GMV in Canada”?",
  options: [
    { option: "a price change", predicted: { method: "intervention", says: "3 past decisions", effect: 5, effect_low: 2, effect_high: 8 } },
    { option: "not act", predicted: { method: "history", says: "6 prior windows", value: 1000, low: 900, high: 1100 } },
  ],
  approvers: ["person:ana"], expectation_required: true, expectation: { metric: "gmv", direction: "up" }, review_days: 14,
  connection_id: "lux", composed_by: "code, from the declared kind, the mission and the Record — no model",
};

beforeEach(() => {
  rec.listMissionProposals.mockReset().mockResolvedValue({ mission: "m1", proposals: [PROPOSAL], objective: {} });
  rec.declareDecision.mockReset().mockResolvedValue({ id: "dec-9", review_on: "2026-11-09" });
});

describe("the platform's proposal under a mission", () => {
  it("shows each option with what the Record predicts, and books nothing until a person chooses", async () => {
    render(<Proposals m={MISSION} onOpenDecision={() => {}} />);
    const row = await screen.findByTestId("mission-proposal");
    expect(row).toHaveTextContent("past decisions of this kind moved it 2 to 8");
    expect(row).toHaveTextContent("its own history predicts 900 to 1,100");
    expect(row).toHaveTextContent("no model");
    expect(rec.declareDecision).not.toHaveBeenCalled();
  });

  it("choosing books a decision of the kind toward the mission; not acting expects a hold", async () => {
    const opened: string[] = [];
    render(<Proposals m={MISSION} onOpenDecision={id => opened.push(id)} />);
    await screen.findByTestId("mission-proposal");
    fireEvent.click(screen.getAllByRole("button", { name: "Choose" })[1]);
    await waitFor(() => expect(rec.declareDecision).toHaveBeenCalled());
    expect(rec.declareDecision.mock.calls[0][0]).toMatchObject({
      question: PROPOSAL.question, chosen: "not act", options: ["a price change", "not act"], connection_id: "lux",
      kind: PROPOSAL.kind, objective: "m1", expectation: { metric: "gmv", direction: "hold" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Open it →" }));
    expect(opened).toEqual(["dec-9"]);
  });

  it("with no declared kind for the objective, says how one is made", async () => {
    rec.listMissionProposals.mockResolvedValue({ mission: "m1", proposals: [], objective: {} });
    render(<Proposals m={MISSION} onOpenDecision={() => {}} />);
    expect(await screen.findByText(/No declared kind of decision moves gmv/)).toBeInTheDocument();
  });
});
