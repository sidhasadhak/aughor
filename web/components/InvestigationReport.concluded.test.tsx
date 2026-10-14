// @vitest-environment jsdom
/**
 * P1 (`analyst.conclude`): an answer that named its own headline, figures and exhibits is drawn
 * as it said — each cited result once, captioned by its claim, the rest named under Sources —
 * and a report without `exhibits` renders exactly as before (the other tests in this folder).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/charts/ResultChartCard", () => ({
  ResultChartCard: ({ title }: { title: string }) => <div data-testid="chart">{title}</div>,
}));
vi.mock("@/components/Chart", () => ({ Chart: () => null }));

import { InvestigationReportView as ReportView } from "@/components/InvestigationReport";

const finding = (id: string, title: string, rows: (string | number)[][]) => ({
  finding_id: id, title, sql: `SELECT category, revenue FROM order_items -- ${id}`,
  columns: ["category", "revenue"], rows, row_count: rows.length, error: null,
  interpretation: "", key_numbers: [], chart_type: "auto", stat_note: null, is_significant: false,
  trust_caveat: id === "adhoc_2_1" ? "possible over-count: the join repeats each order row" : null,
});

const REPORT = {
  headline: "Outerwear & Coats leads six-month revenue at $229.8K; Jeans is a close second",
  executive_summary: "Jeans follow at $213.2K; Sweaters at $139.5K.",
  confidence: "HIGH", observation_period: "5 Mar – 4 Sep 2026", comparison_basis: "",
  recommendations: [], data_gaps: [], attribution_waterfall: [],
  figures: [{ label: "Outerwear & Coats", value: "$229.8K", note: "$150.78 an order" },
            { label: "Jeans", value: "$213.2K", note: "$102.64 an order" }],
  gaps: "The data holds no cost, so margin is not measured.",
  exhibits: [{ finding_id: "adhoc_2_1", claim: "Revenue spans $80.4K to $229.8K across the ten" }],
  phases: [
    { phase_id: "intake", phase_name: "Question Intake", phase_icon: "", status: "complete", summary: "spec",
      findings: [finding("intake_spec", "Investigation Specification", [["x", 1]])] },
    { phase_id: "adhoc_1", phase_name: "Revenue by category", phase_icon: "", status: "complete", summary: "",
      findings: [finding("adhoc_1_1", "Revenue by category — first try", [["Jeans", 213177], ["Swim", 117253]])] },
    { phase_id: "adhoc_2", phase_name: "Revenue by category", phase_icon: "", status: "complete", summary: "",
      findings: [finding("adhoc_2_1", "Total revenue and average order value by category", [["Outerwear & Coats", 229793], ["Jeans", 213177]])] },
  ],
} as never;

describe("a concluded answer is drawn as it said", () => {
  it("leads with the headline and the figures it rests on", () => {
    render(<ReportView report={REPORT} />);
    expect(screen.getByText(/Outerwear & Coats leads six-month revenue/)).toBeInTheDocument();
    expect(screen.getByTestId("answer-figures")).toHaveTextContent("$229.8K");
    expect(screen.getByTestId("answer-figures")).toHaveTextContent("$102.64 an order");
  });

  it("draws each cited result once, captioned by its claim, with its caveat as a chip", () => {
    render(<ReportView report={REPORT} />);
    const exhibit = screen.getByTestId("exhibit-adhoc_2_1");
    expect(exhibit).toHaveTextContent("Revenue spans $80.4K to $229.8K across the ten");
    expect(screen.getAllByTestId("chart")).toHaveLength(1);
    expect(exhibit).toHaveTextContent("⚠ possible over-count");
    expect(exhibit).toHaveTextContent("order_items");
    expect(exhibit).toHaveTextContent("2 rows");
    // the query's own name stays off the caption — it is the Table/SQL affordance's
    expect(exhibit).not.toHaveTextContent("Total revenue and average order value by category");
  });

  it("names the results it did not cite under Sources, and never the intake's", () => {
    render(<ReportView report={REPORT} />);
    const sources = screen.getByTestId("uncited-results");
    expect(sources).toHaveTextContent("1 not drawn");
    expect(sources).toHaveTextContent("Revenue by category — first try");
    expect(screen.queryByText(/Investigation Specification/)).not.toBeInTheDocument();
    expect(screen.getByText("1 of 2 results drawn")).toBeInTheDocument();
  });

  it("says what the data could not answer, and the period when the answer does not", () => {
    render(<ReportView report={REPORT} />);
    expect(screen.getByText(/margin is not measured/)).toBeInTheDocument();
    expect(screen.getByText("5 Mar – 4 Sep 2026")).toBeInTheDocument();
  });

  it("renders a report without exhibits exactly as before — every result drawn", () => {
    const { exhibits: _e, figures: _f, gaps: _g, ...legacy } = REPORT as Record<string, unknown>;
    render(<ReportView report={legacy as never} />);
    expect(screen.getAllByTestId("chart")).toHaveLength(2);
    expect(screen.queryByText("Exhibits")).not.toBeInTheDocument();
  });
});
