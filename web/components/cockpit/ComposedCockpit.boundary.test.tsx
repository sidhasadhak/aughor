// @vitest-environment jsdom

/**
 * A card that throws while drawing. The library's own error boundary draws NOTHING in its
 * place (measured in CT-4: a card vanished with only a console line to say so). This pins
 * the boundary inside it: the card stays where it is and says what happened, and its
 * neighbours are drawn as if nothing had.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ComposedCockpit } from "@/components/cockpit/ComposedCockpit";
import type { CardState } from "@/components/brief/PinnedCardBody";
import type { DashboardCard } from "@/lib/api";

vi.mock("@/components/brief/PinnedCardBody", () => ({
  PinnedCardBody: ({ cs }: { cs: CardState }) => {
    if (cs.card.id === "c91b2002") throw new Error("the chart could not be built");
    return <div>{cs.card.title}</div>;
  },
}));
vi.mock("@/components/brief/PinnedCardsGrid", () => ({ CARD_H: 210 }));

const premise = () => JSON.parse(readFileSync(resolve(process.cwd(), "lib/cockpit/premise.fixture.json"), "utf8"));
const card = (id: string, title: string): CardState => ({ card: { id, title } as DashboardCard });
const CARDS = [card("c7f3a001", "Return rate"), card("c91b2002", "Net merchandise revenue")];
const HOST = { range: { status: "final" as const }, cards: { c7f3a001: { status: "within" as const }, c91b2002: { status: "within" as const } } };

describe("a card that throws while drawing", () => {
  let logged: ReturnType<typeof vi.spyOn>;
  beforeEach(() => { logged = vi.spyOn(console, "error").mockImplementation(() => {}); });
  afterEach(() => { logged.mockRestore(); });

  it("says so in its own place, and the card beside it is drawn", () => {
    render(<ComposedCockpit spec={premise()} cards={CARDS} host={HOST} doors={{ onRemove: vi.fn(), onRefresh: vi.fn() }} />);

    const [rate, net] = screen.getAllByTestId("cockpit-card");
    expect(within(rate).getByText("Return rate")).toBeInTheDocument();
    expect(net.dataset.card).toBe("c91b2002");
    expect(within(net).getByText("Could not be drawn")).toBeInTheDocument();
    expect(within(net).getByText(/drawing it failed: the chart could not be built/)).toBeInTheDocument();
  });
});
