// @vitest-environment jsdom

/**
 * A limit is not an alert (Arc CT-5).
 *
 * A card said "Alerting when above threshold" — with the title "This card is now a scheduled
 * monitor" — whenever it carried a limit. That was true while the only way to a limit was to
 * graduate the card, which creates the monitor. A cockpit proposal gives a card a limit and
 * schedules nothing, and the card went on saying it was alerting. Seen on the live run, on the
 * first card a proposal made.
 */
import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { PinnedCardBody, type CardState } from "@/components/brief/PinnedCardBody";
import type { DashboardCard } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  graduateCard: vi.fn(),
  updateDashboardCard: vi.fn(),
}));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const REFRESH = { cadence: "daily", last_run: "", last_value: 1.59, prev_value: null, history: [] };

function card(thresholds: DashboardCard["thresholds"]): CardState {
  return {
    card: {
      id: "c1", connection_id: "fixture", scope: "canvas", scope_ref: "cv", source: "authored", kind: "kpi",
      title: "Payment failure rate", sql: "SELECT 1", query_ref: null, render: {}, refresh: REFRESH, thresholds,
      provenance: {} as DashboardCard["provenance"],          // no test here reads it
      links: [], body: "", author: "", created_at: "", updated_at: "",
    },
    run: { columns: ["v"], rows: [["1.59"]], row_count: 1, caveats: [], error: null, value: 1.59, refresh: REFRESH, scoped: null },
  };
}
const show = (cs: CardState) => render(<PinnedCardBody cs={cs} onRemove={vi.fn()} onRefresh={vi.fn()} />);

describe("a card with a limit and no monitor behind it", () => {
  it("says its limit, says no alert is set, and keeps the door to one", () => {
    const { container } = show(card({ warning: 1.5, direction: "above" }));
    expect(screen.getByTestId("card-limit")).toHaveTextContent("Limit: at or above 1.5 · no alert is set");
    expect(container).not.toHaveTextContent("Alerting");
    expect(screen.getByRole("button", { name: "Set alert" })).toBeInTheDocument();
  });

  it("says both limits, and which way they are crossed", () => {
    show(card({ warning: 95, critical: 90, direction: "below" }));
    expect(screen.getByTestId("card-limit")).toHaveTextContent("Limit: at or below 95, 90 · no alert is set");
  });

  it("a limit left empty by the server is not a limit", () => {
    show(card({ warning: 1.7, critical: null, direction: "above" }));
    expect(screen.getByTestId("card-limit")).toHaveTextContent("Limit: at or above 1.7 · no alert is set");
  });
});

describe("a card that was graduated to a monitor", () => {
  it("says it is alerting, as it did", () => {
    const { container } = show(card({ warning: 1.7, critical: null, direction: "above", monitor_id: "mon-1" }));
    expect(container).toHaveTextContent("Alerting when above threshold");
    expect(screen.queryByTestId("card-limit")).toBeNull();
    expect(screen.queryByRole("button", { name: "Set alert" })).toBeNull();
  });
});

describe("a card with no limit", () => {
  it("says nothing of one", () => {
    const { container } = show(card({}));
    expect(screen.queryByTestId("card-limit")).toBeNull();
    expect(container).not.toHaveTextContent("Alerting");
    expect(screen.getByRole("button", { name: "Set alert" })).toBeInTheDocument();
  });
});
