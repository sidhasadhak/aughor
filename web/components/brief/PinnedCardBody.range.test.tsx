// @vitest-environment jsdom

/**
 * A card read for a range shows the RANGE's figure (Arc CT-4).
 *
 * Before this, a card that already had a standing value drew it under "for <the range>": the
 * run carried the range's figure in `rows`, as text, and the card drew `refresh`, which is the
 * card's standing value whatever the run was for. Seen live on the demo warehouse: 8.42M
 * labelled November, where November held 2.78M. It reached the Briefing's cockpit as well as
 * the canvas's, since both draw a card with this component.
 */
import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { PinnedCardBody, cardKind, type CardState } from "@/components/brief/PinnedCardBody";
import type { CardRunResult, DashboardCard } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  graduateCard: vi.fn(),
  updateDashboardCard: vi.fn(),
}));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
  // A result with no figure is drawn as a table, and the table asks the browser for its width.
  window.matchMedia = ((query: string) => ({
    matches: false, media: query, onchange: null, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

const STANDING = { cadence: "daily", last_run: "", last_value: 8416308.73, prev_value: 8100000, history: [7900000, 8100000, 8416308.73] };
const CARD = {
  id: "c1", connection_id: "fixture", scope: "canvas", scope_ref: "cv", source: "authored", kind: "kpi",
  title: "Revenue", sql: "SELECT 1", query_ref: null, render: {}, refresh: STANDING, thresholds: {},
  provenance: {} as DashboardCard["provenance"],            // no test here reads it
  links: [], body: "", author: "", created_at: "", updated_at: "",
} satisfies DashboardCard;

function run(more: Partial<CardRunResult>): CardState {
  return { card: CARD, run: { columns: ["revenue"], rows: [["8416308.73"]], row_count: 1, caveats: [], error: null, value: 8416308.73, refresh: STANDING, scoped: null, ...more } };
}
const NOVEMBER = { covers: "2025-11-01 to 2025-11-29 (29 days)", standing: false, why: "", grain: "daily_revenue.date" };
const show = (cs: CardState) => render(<PinnedCardBody cs={cs} onRemove={vi.fn()} onRefresh={vi.fn()} />);

describe("a card read as it was written", () => {
  it("shows its standing figure and how it moved", () => {
    const { container } = show(run({}));
    expect(screen.getByText("8.42M")).toBeInTheDocument();
    expect(container).toHaveTextContent("+316,308.73");
    expect(screen.queryByTestId("card-scoped")).toBeNull();
  });
});

describe("a card read for a range", () => {
  it("shows the range's figure under the range's label, and nothing of the standing one", () => {
    const { container } = show(run({ rows: [["2778117.83"]], value: 2778117.83, scoped: NOVEMBER }));

    expect(screen.getByText("2.78M")).toBeInTheDocument();
    expect(screen.queryByText("8.42M")).toBeNull();
    expect(container).not.toHaveTextContent("316,308.73");     // the standing value's change is not November's
    expect(screen.queryByText("trend builds as it refreshes")).toBeNull();
    expect(screen.getByTestId("card-scoped")).toHaveTextContent("for 2025-11-01 to 2025-11-29 (29 days)");
  });

  it("that could not be cut to it shows its standing figure, and says it is all history", () => {
    show(run({ scoped: { covers: "2025-11-01 to 2025-11-29 (29 days)", standing: true, why: "its tables carry no date", grain: null } }));
    expect(screen.getByText("8.42M")).toBeInTheDocument();
    expect(screen.getByTestId("card-scoped")).toHaveTextContent("all history, not 2025-11-01 to 2025-11-29 (29 days) — its tables carry no date");
  });

  it("from a server that does not say the figure shows no figure, rather than the wrong one", () => {
    const cs = run({ rows: [["2778117.83"]], scoped: NOVEMBER });
    delete cs.run!.value;
    show(cs);
    expect(screen.queryByText("8.42M")).toBeNull();
    expect(cardKind(cs)).not.toBe("kpi");
  });
});
