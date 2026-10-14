// @vitest-environment jsdom
/**
 * P5 (canvas-output study, 2026-10-14): the code-written significance verdict is the badge, never a
 * bracket in the phase's prose — on a new report from its `verdict` slot, on an older one by keeping
 * "[stats.py: σ=…]" out of the summary it still carries. And a report whose analyst ran one phase
 * tool twice (two `decomposition` phases, ids `decomp_0..2` both times — 99201af8) renders every
 * result once, without React's duplicate-key warning (vitest.setup.ts fails the test on one).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/charts/ResultChartCard", () => ({
  ResultChartCard: ({ title }: { title: string }) => <div data-testid="chart">{title}</div>,
}));
vi.mock("@/components/Chart", () => ({ Chart: () => null }));

import { InvestigationReportView as ReportView } from "@/components/InvestigationReport";

let seq = 0;
// Distinct rows per result: the body folds a result whose series another chart already draws (`repeatedCharts`).
const finding = (id: string, title: string, rows?: (string | number)[][]) => ({
  finding_id: id, title, sql: `SELECT category, revenue FROM order_items -- ${id}`,
  columns: ["category", "revenue"], rows: rows ?? [["Jeans", 213177 + ++seq], ["Swim", 117253 + seq]],
  row_count: 2, error: null,
  interpretation: "", key_numbers: [], chart_type: "auto", stat_note: null, is_significant: false, trust_caveat: null,
});

const base = {
  headline: "Revenue rose 14.9% on August; order count carried the change",
  executive_summary: "September revenue rose €93.8K on August.",
  confidence: "MEDIUM", observation_period: "September 2026", comparison_basis: "August 2026",
  recommendations: [], data_gaps: [], attribution_waterfall: [],
};

describe("the phase verdict", () => {
  it("is drawn as the badge from the verdict slot, and its sigma is not in the prose", () => {
    const report = { ...base, phases: [
      { phase_id: "baseline", phase_name: "Baseline", phase_icon: "", status: "complete",
        summary: "September sits inside the 13-month range.",
        verdict: { sigma: 0.16, significant: false, text: "σ = 0.16 — within normal variance" },
        findings: [finding("baseline_0", "Monthly revenue")] },
    ] } as never;
    render(<ReportView report={report} />);
    expect(screen.getByTestId("phase-verdict")).toHaveTextContent("Within noise");
    expect(screen.getByTestId("phase-verdict")).toHaveTextContent("σ = 0.16 — within normal variance");
    expect(screen.getByText("September sits inside the 13-month range.")).toBeInTheDocument();
  });

  it("keeps an older report's bracket out of the summary the reader sees", () => {
    const report = { ...base, phases: [
      { phase_id: "baseline", phase_name: "Baseline", phase_icon: "", status: "complete",
        summary: "Traffic rose. [stats.py: σ=0.40 — within normal variance]",
        findings: [finding("baseline_0", "Monthly traffic")] },
    ] } as never;
    render(<ReportView report={report} />);
    expect(screen.getByText("Traffic rose.")).toBeInTheDocument();
    expect(screen.queryByText(/stats\.py/)).toBeNull();
  });

  it("says in a muted line when code could not assess significance", () => {
    const report = { ...base, phases: [
      { phase_id: "baseline", phase_name: "Baseline", phase_icon: "", status: "complete", summary: "Two months.",
        verdict: { sigma: null, significant: null, text: "significance not assessable — the baseline holds 2 period(s); at least 6 are needed" },
        findings: [finding("baseline_0", "Monthly revenue")] },
    ] } as never;
    render(<ReportView report={report} />);
    expect(screen.getByTestId("phase-verdict")).toHaveTextContent("significance not assessable");
    expect(screen.queryByText("Within noise")).toBeNull();
  });
});

describe("two runs of one phase tool", () => {
  const twice = {
    ...base,
    figures: [], gaps: "",
    exhibits: [{ finding_id: "decomp_1", claim: "Mytheresa and Mr Porter carry four-fifths of the rise" }],
    phases: [
      { phase_id: "decomposition", phase_name: "Decomposition", phase_icon: "", status: "complete", summary: "",
        findings: [finding("decomp_0", "Orders vs value"), finding("decomp_1", "By platform"), finding("decomp_2", "By brand")] },
      { phase_id: "decomposition", phase_name: "Decomposition", phase_icon: "", status: "complete", summary: "",
        findings: [finding("decomp_0", "Orders vs value, again"), finding("decomp_1", "By category"), finding("decomp_2", "By brand, again")] },
    ],
  } as never;

  it("renders a concluded body with every uncited result listed and no duplicate key", () => {
    render(<ReportView report={twice} />);
    // six results, one id cited — and both results carrying that id are treated as cited (an older
    // report; the analyst now renames the second run's ids before the model reads them)
    expect(screen.getByTestId("uncited-results")).toHaveTextContent("4 not drawn:");
    expect(screen.getByTestId("uncited-results")).toHaveTextContent("By brand, again");
  });

  it("renders the phase body with every finding and no duplicate key", () => {
    const { exhibits: _e, ...plain } = twice as { exhibits: unknown } & Record<string, unknown>;
    render(<ReportView report={plain as never} />);
    expect(screen.getAllByTestId("chart")).toHaveLength(6);
  });
});
