// @vitest-environment jsdom
/**
 * "Ask this briefing" asks FROM the Briefing: its schema, the surface, and the range on screen
 * ride every turn, and the header says which scope the answers keep to. 2026-10-06: an answer
 * on `uber_ncr` came from two other datasets on the same connection, and nothing on the panel
 * said what it was scoped to.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const seen: { body?: Record<string, unknown> } = {};

vi.mock("@/lib/useAughorChat", () => ({
  useAughorChat: (opts: { body?: Record<string, unknown> }) => {
    seen.body = opts.body;
    return { messages: [], sendMessage: vi.fn(), status: "ready", error: undefined };
  },
}));

import { BRIEFING_SURFACE, BriefAskPanel } from "./BriefAskPanel";

const AUGUST = "range:last_month:2026-08-01..2026-08-31";

describe("BriefAskPanel", () => {
  it("asks from the Briefing, on its schema, about the period on screen", () => {
    render(<BriefAskPanel connectionId="workspace" schema="uber_ncr" periodKey={AUGUST}
      periodCovers="August 2026" onClose={() => {}} onOpenInAsk={() => {}} />);
    expect(seen.body).toMatchObject({
      depth: "quick", schema: "uber_ncr", surface: BRIEFING_SURFACE, brief_period: AUGUST,
    });
    expect(screen.getByText("uber_ncr · August 2026")).toBeInTheDocument();
  });

  it("with no range open it sends no period and still names its schema", () => {
    render(<BriefAskPanel connectionId="workspace" schema="uber_ncr"
      onClose={() => {}} onOpenInAsk={() => {}} />);
    expect(seen.body).toMatchObject({ schema: "uber_ncr", surface: BRIEFING_SURFACE, brief_period: "" });
    expect(screen.getAllByText("uber_ncr").length).toBeGreaterThan(0);
  });
});
