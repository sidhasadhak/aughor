// @vitest-environment jsdom
/**
 * AV-1 — every declared part kind renders as its organ, an action is a DOOR, and an
 * unknown kind degrades to a named quiet line, never raw JSON and never silence.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AnswerPart } from "@/lib/chatTurn";

const getProposalById = vi.fn().mockResolvedValue(null);
vi.mock("@/lib/api", async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getProposalById: (...a: unknown[]) => getProposalById(...a),
}));

const { AnswerParts } = await import("@/components/chat/AnswerParts");

describe("AnswerParts", () => {
  it("renders fact rows, a badge and a real-denominator bar", () => {
    const parts: AnswerPart[] = [
      { kind: "fact_set", title: "Automations", facts: [
        { label: "Morning anomalies", value: "daily at 09:00 UTC", status: "warn" }] },
      { kind: "status", label: "muted until first run", tone: "warn" },
      { kind: "progress", label: "backfill", done: 3, total: 8 },
    ];
    const { container } = render(<AnswerParts parts={parts} />);
    expect(screen.getByText("Morning anomalies")).toBeInTheDocument();
    expect(screen.getByText("daily at 09:00 UTC")).toBeInTheDocument();
    expect(screen.getByText("muted until first run")).toBeInTheDocument();
    expect(screen.getByText("3/8")).toBeInTheDocument();
    expect(container.textContent).not.toContain('{"kind"');
  });

  it("folds a collapsed section and opens it on its title", async () => {
    render(<AnswerParts parts={[
      { kind: "section", title: "How this was measured", body: "Counted rows.", collapsed: true }]} />);
    expect(screen.queryByText("Counted rows.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /How this was measured/ }));
    expect(screen.getByText("Counted rows.")).toBeInTheDocument();
  });

  it("a follow_up action rides the follow-up door, nothing else", async () => {
    const onFollowUp = vi.fn();
    render(<AnswerParts onFollowUp={onFollowUp} parts={[
      { kind: "action_set", actions: [
        { action: "follow_up", label: "Why muted?", question: "Why is the chain muted?" }] }]} />);
    await userEvent.click(screen.getByRole("button", { name: "Why muted?" }));
    expect(onFollowUp).toHaveBeenCalledWith("Why is the chain muted?");
  });

  it("a proposal_ref fetches the record and renders the card wrapper", () => {
    render(<AnswerParts parts={[{ kind: "proposal_ref", proposal_id: "prop-9" }]} />);
    expect(getProposalById).toHaveBeenCalledWith("prop-9");
  });

  it("an unknown kind degrades to a named quiet line", () => {
    const { container } = render(
      <AnswerParts parts={[{ kind: "hologram" } as unknown as AnswerPart]} />);
    expect(container.textContent).toContain("hologram");
    expect(container.textContent).not.toContain("{");
  });
});
