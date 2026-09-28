// @vitest-environment jsdom

/**
 * CT-1's premise, as a test: ONE hand-written spec — tabs, sections, two cards from the card
 * store, one card shown by a condition — drawn through the library, with every card handed to
 * `PinnedCardBody` unchanged.
 *
 * What this cannot show is geometry: jsdom reports every element as 0×0. Whether the grid
 * looks right is a browser question, and CT-1's receipt answers it there.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { ComposedCockpit, type CockpitDoors } from "@/components/cockpit/ComposedCockpit";
import type { CardState } from "@/components/brief/PinnedCardBody";
import type { DashboardCard } from "@/lib/api";
import type { CardStatus, CockpitHostState, RangeStatus } from "@/lib/cockpit/hostState";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  graduateCard: vi.fn(),
  updateDashboardCard: vi.fn(),
}));

beforeAll(() => {
  // PinnedCardBody measures itself to size its sparkline; jsdom has nothing to measure with.
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const premise = () => JSON.parse(readFileSync(resolve(process.cwd(), "lib/cockpit/premise.fixture.json"), "utf8"));

function card(id: string, title: string, value: number): CardState {
  const refresh = { cadence: "daily", last_run: "2026-09-28T06:00:00Z", last_value: value, prev_value: null, history: [value] };
  const c: DashboardCard = {
    id, connection_id: "thelook", scope: "canvas", scope_ref: "cv_returns", source: "authored", kind: "kpi",
    title, sql: "SELECT 1", query_ref: null, render: {}, refresh, thresholds: {},
    provenance: {} as DashboardCard["provenance"],          // no test here reads it
    links: [], body: "", author: "", created_at: "", updated_at: "",
  };
  return { card: c, run: { columns: ["v"], rows: [[value]], row_count: 1, caveats: [], error: null, refresh } };
}

const CARDS = [card("c7f3a001", "Return rate", 0.1003), card("c91b2002", "Net merchandise revenue", 341000)];
const DOORS: CockpitDoors = { onRemove: vi.fn(), onRefresh: vi.fn() };

function host(range: RangeStatus, rate: CardStatus, net: CardStatus = "within"): CockpitHostState {
  return { range: { status: range }, cards: { c7f3a001: { status: rate }, c91b2002: { status: net } } };
}

const placed = () => screen.queryAllByTestId("cockpit-card").map(el => `${el.dataset.card}${el.dataset.tone ? `:${el.dataset.tone}` : ""}`);

describe("the premise spec, drawn", () => {
  it("draws its tabs, its section, and both cards through PinnedCardBody", () => {
    render(<ComposedCockpit spec={premise()} cards={CARDS} host={host("final", "within")} doors={DOORS} />);

    expect(screen.getByRole("region", { name: "Returns" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map(t => t.textContent)).toEqual(["Overview", "Watches"]);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Headline")).toBeInTheDocument();

    // The card that waits on its condition is not drawn, and the section says one is waiting.
    expect(placed()).toEqual(["c7f3a001", "c91b2002"]);
    expect(screen.getByTestId("cockpit-waiting")).toHaveTextContent("1 card waits on a condition");

    // The card's own title, drawn by the card's own component.
    const [rate, net] = screen.getAllByTestId("cockpit-card");
    expect(within(rate).getByText("Return rate")).toBeInTheDocument();
    expect(within(net).getByText("Net merchandise revenue")).toBeInTheDocument();
  });

  it("shows the conditional card when the host says the watch is over its limit, and only then", () => {
    // ONE spec object throughout. A fresh object per render would rebuild the state from
    // scratch and pass this test without the host's change ever reaching a cockpit that is
    // already open — which is the case that matters, and the one a mutation showed was untested.
    const spec = premise();
    const { rerender } = render(<ComposedCockpit spec={spec} cards={CARDS} host={host("final", "within")} doors={DOORS} />);
    expect(placed()).toEqual(["c7f3a001", "c91b2002"]);

    rerender(<ComposedCockpit spec={spec} cards={CARDS} host={host("final", "over")} doors={DOORS} />);
    expect(placed()).toEqual(["c7f3a001:bad", "c7f3a001", "c91b2002"]);
    expect(screen.queryByTestId("cockpit-waiting")).toBeNull();

    rerender(<ComposedCockpit spec={spec} cards={CARDS} host={host("final", "unmeasured")} doors={DOORS} />);
    expect(placed()).toEqual(["c7f3a001", "c91b2002"]);
    expect(screen.getByTestId("cockpit-waiting")).toHaveTextContent("1 card waits on a condition");
  });

  it("opens the other tab on a click, and keeps it open when the cards refresh", () => {
    const spec = premise();
    const { rerender } = render(<ComposedCockpit spec={spec} cards={CARDS} host={host("final", "within")} doors={DOORS} />);

    fireEvent.click(screen.getByRole("tab", { name: "Watches" }));
    expect(screen.getByRole("tab", { name: "Watches" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Limits")).toBeInTheDocument();
    expect(screen.queryByText("Headline")).toBeNull();
    expect(placed()).toEqual(["c7f3a001"]);

    rerender(<ComposedCockpit spec={spec} cards={CARDS} host={host("provisional", "over")} doors={DOORS} />);
    expect(screen.getByRole("tab", { name: "Watches" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Limits")).toBeInTheDocument();
  });

  it("keeps the tab open when the same spec arrives as a new object", () => {
    const { rerender } = render(<ComposedCockpit spec={premise()} cards={CARDS} host={host("final", "within")} doors={DOORS} />);
    fireEvent.click(screen.getByRole("tab", { name: "Watches" }));

    rerender(<ComposedCockpit spec={premise()} cards={CARDS} host={host("final", "over")} doors={DOORS} />);
    expect(screen.getByRole("tab", { name: "Watches" })).toHaveAttribute("aria-selected", "true");
  });

  it("opens on its own first tab again when the spec itself changes", () => {
    const { rerender } = render(<ComposedCockpit spec={premise()} cards={CARDS} host={host("final", "within")} doors={DOORS} />);
    fireEvent.click(screen.getByRole("tab", { name: "Watches" }));

    const edited = premise();
    edited.elements["sec-headline"].props.title = "At a glance";
    rerender(<ComposedCockpit spec={edited} cards={CARDS} host={host("final", "within")} doors={DOORS} />);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("At a glance")).toBeInTheDocument();
  });

  it("says a section is waiting, rather than showing an empty tab", () => {
    render(<ComposedCockpit spec={premise()} cards={CARDS} host={host("to_date", "within")} doors={DOORS} />);
    fireEvent.click(screen.getByRole("tab", { name: "Watches" }));
    expect(screen.queryByText("Limits")).toBeNull();
    expect(screen.getByTestId("cockpit-waiting-sections")).toHaveTextContent("1 section waits on a condition");
  });
});

describe("what a reader may not see", () => {
  it("stays in its place and says it is withheld — it is never drawn, and never missing", () => {
    render(<ComposedCockpit spec={premise()} cards={CARDS} host={host("final", "within", "withheld")} doors={DOORS} />);
    expect(placed()).toEqual(["c7f3a001", "c91b2002"]);
    const net = screen.getAllByTestId("cockpit-card")[1];
    expect(within(net).getByText("Withheld")).toBeInTheDocument();
    expect(within(net).queryByText("Net merchandise revenue")).toBeNull();
  });

  it("a card the canvas does not hold says so", () => {
    render(<ComposedCockpit spec={premise()} cards={[CARDS[0]]} host={host("final", "within")} doors={DOORS} />);
    const net = screen.getAllByTestId("cockpit-card")[1];
    expect(within(net).getByText("Not one of your cards")).toBeInTheDocument();
  });
});

describe("a spec the rules refuse", () => {
  it("is not drawn at all, and says why in the rules' own sentence", () => {
    const spec = premise();
    spec.elements["card-rate"].watch = { "/tab": { action: "anything" } };
    render(<ComposedCockpit spec={spec} cards={CARDS} host={host("final", "over")} doors={DOORS} />);

    expect(screen.queryAllByTestId("cockpit-card")).toEqual([]);
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.getByTestId("cockpit-refusal")).toHaveTextContent("A cockpit runs nothing without a click");
  });

  it("a spec that seeds a card's status cannot forge what the host says", () => {
    const spec = premise();
    spec.state = { tab: "overview", cards: { c7f3a001: { status: "over" } } };
    render(<ComposedCockpit spec={spec} cards={CARDS} host={host("final", "within")} doors={DOORS} />);
    expect(screen.queryAllByTestId("cockpit-card")).toEqual([]);
    expect(screen.getByTestId("cockpit-refusal")).toHaveTextContent("every card's status are the host's to say");
  });
});
