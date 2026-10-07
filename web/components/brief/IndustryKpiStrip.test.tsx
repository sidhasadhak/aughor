// @vitest-environment jsdom
/**
 * The Key Metrics row says where its tiles stand in the Semantic Layer. On `workspace` /
 * `uber_ncr` six tiles rendered as confidently as approved definitions while the Semantic Layer
 * listed none of them (2026-10-07).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/useVizConfigs", () => ({ useVizConfigs: () => ({ configFor: () => null, save: () => {} }) }));

import { KpiStripView, type Kpi } from "./IndustryKpiStrip";

const kpi = (name: string, standing?: Kpi["standing"]): Kpi => ({
  name, display: "62.0%", sql: "SELECT 1", raw: 0.62, color: "var(--blue4)", standing,
  trend: { values: [1, 2], deltaText: "-2.6pts", sign: -1, favorable: false, caption: "slipping" },
});

describe("KpiStripView standing", () => {
  it("says once that no tile is an approved definition", () => {
    render(<KpiStripView kpis={[kpi("Ride Completion Rate", "proposed"), kpi("Average Driver Rating", "proposed")]} />);
    expect(screen.getByTestId("kpi-strip-standing")).toHaveTextContent("none is an approved definition yet");
    expect(screen.queryByText(/proposed — not approved/)).toBeNull();
  });

  it("marks only the tiles that are not approved when some are", () => {
    render(<KpiStripView kpis={[kpi("Revenue", "approved"), kpi("Ride Completion Rate", "proposed")]} />);
    expect(screen.queryByTestId("kpi-strip-standing")).toBeNull();
    expect(screen.getByText("slipping · proposed — not approved")).toBeInTheDocument();
  });

  it("makes no claim before the catalogue has answered", () => {
    render(<KpiStripView kpis={[kpi("Ride Completion Rate")]} />);
    expect(screen.queryByTestId("kpi-strip-standing")).toBeNull();
    expect(screen.getByText("slipping")).toBeInTheDocument();
  });
});
