// @vitest-environment jsdom
/**
 * A report can hold several phases of one kind: scheduled runs routinely produce two or more
 * `decomposition` phases (26 of the last 100 reports, measured 2026-09-26). Keyed by
 * `phase_id`, React reported "two children with the same key" and could drop a phase.
 * vitest.setup.ts fails this test if a key collides; the assertions check no phase was dropped.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InvestigationReportView } from "@/components/InvestigationReport";
import type { AnswerReport, InvestigationPhase } from "@/lib/types";

const phase = (phase_id: string, phase_name: string): InvestigationPhase => ({
  phase_id, phase_name, phase_icon: "", status: "complete", summary: `${phase_name}: what it found.`, findings: [],
});

const report: AnswerReport = {
  headline: "Revenue fell in the South", executive_summary: "", metric: "revenue",
  observation_period: "", comparison_basis: "", total_change_label: "", attribution_waterfall: [],
  confidence: "MEDIUM", confidence_justification: "", recommendations: [], data_gaps: [],
  phases: [
    phase("decomposition", "Decomposition by region"),
    phase("baseline", "Baseline"),
    phase("decomposition", "Decomposition by channel"),
  ],
};

describe("InvestigationReportView", () => {
  it("renders every phase when two share a kind", () => {
    render(<InvestigationReportView report={report} />);
    expect(screen.getByText(/Decomposition by region/)).toBeInTheDocument();
    expect(screen.getByText(/Decomposition by channel/)).toBeInTheDocument();
  });
});
