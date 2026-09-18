// @vitest-environment jsdom
/**
 * A finding's statistical verdict has to reach the web reader too.
 *
 * Found by the producer→surface ratchet on 2026-09-18, AFTER the PDF and the deck were
 * fixed: `stat_note` was declared on this file's finding interface and read NOWHERE under
 * `web/`, and `SignificanceBadge` — the component written to display it — was imported by
 * nothing. So the warning run 29c3c169 lost was missing from all THREE surfaces, and the
 * fix that "restored it for the reader" had restored it for two of them.
 *
 * The clean-output policy in that file is right about half of a stat note and wrong about
 * the other half, so the note is SPLIT rather than the policy overruled:
 *
 *   "z = 8.2 — significant"                  machinery  → the verification row
 *   "PARTIAL FINAL PERIOD: … 21 of 30 days"  meaning    → the body, beside the number
 *
 * A reader who is not told the month is 70% over reads "$342,313 in September 2026 … an
 * increase of 27.4%" as a fact about a month. That is what shipped.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/charts/ResultChartCard", () => ({ ResultChartCard: () => null }));
vi.mock("@/components/Chart", () => ({ Chart: () => null }));

import { InvestigationReportView as ReportView } from "@/components/InvestigationReport";

const WARNING =
  "PARTIAL FINAL PERIOD: September 2026 holds 21 of 30 days (70%) — its total is not " +
  "comparable to a full month; compare per-day rates, and do not read the smaller total " +
  "as a drop or a correction. Per day: September 2026 16,301 vs previous month 8,664.";

/** Render the report view for a finding carrying `stat_note`. Named once, here: the view
 *  is the component under test, so its real name has to appear — see the exemption in
 *  tests/unit/test_vocabulary_ratchet.py. */
const view = (stat_note: string) => render(<ReportView report={reportWith(stat_note)} />);

function reportWith(stat_note: string) {
  return {
    headline: "Gross margin rose 27.4%",
    executive_summary: "It reached $342,313 in September 2026.",
    confidence: "HIGH",
    phases: [{
      phase_id: "baseline", phase_name: "Baseline & Anomaly Assessment",
      phase_icon: "", status: "complete", summary: "Margin grew.", caveats: [],
      findings: [{
        finding_id: "b0", title: "Monthly Gross Margin Baseline",
        claim: "Gross margin rose 27.4%",
        interpretation: "Gross margin reached $342,313 in September 2026.",
        sql: "SELECT 1", columns: [], rows: [], row_count: 0,
        key_numbers: [], chart_type: "line", stat_note, is_significant: true,
      }],
    }],
  } as never;
}

describe("the completeness warning reaches the body", () => {
  it("shows the warning the reader needs to interpret the number", () => {
    view(`z = 8.2 — significant ${WARNING}`);
    expect(screen.getByText(/21 of 30 days \(70%\)/)).toBeInTheDocument();
    expect(screen.getByText(/not\s+comparable to a full month/)).toBeInTheDocument();
  });

  it("keeps the per-day rates, which are the actionable half", () => {
    view(`z = 8.2 — significant ${WARNING}`);
    expect(screen.getByText(/16,301 vs previous month 8,664/)).toBeInTheDocument();
  });

  it("does not put the z-score in the body prose", () => {
    view(`z = 8.2 — significant ${WARNING}`);
    // The verdict rides the verification row as a badge, so it appears once, as a label —
    // not inside the amber advisory beside the number.
    const advisory = screen.getByText(/21 of 30 days/);
    expect(advisory.textContent).not.toMatch(/z = 8\.2/);
  });
});

describe("the verdict reaches the verification row", () => {
  it("renders the badge with the machinery half", () => {
    view(`z = 8.2 — significant ${WARNING}`);
    expect(screen.getByText("Significant")).toBeInTheDocument();
    expect(screen.getByText(/z = 8\.2/)).toBeInTheDocument();
  });

  it("a note with no warning still shows its verdict", () => {
    view("z = 3.7 — significant");
    expect(screen.getByText(/z = 3\.7/)).toBeInTheDocument();
    expect(screen.queryByText(/PARTIAL FINAL PERIOD/)).not.toBeInTheDocument();
  });

  it("a finding with no stat note renders neither", () => {
    view("");
    expect(screen.queryByText("Significant")).not.toBeInTheDocument();
    expect(screen.queryByText(/⚠/)).not.toBeInTheDocument();
  });
});

describe("the split is declared, not sniffed", () => {
  it("does not split on a retailer's name quoted out of the data", () => {
    // 9 of the 630 stored notes contain "THE OUTNET". A capitals scan would treat it as a
    // marker and render a brand name as a completeness warning.
    view("z = 1.2 — within normal range for THE OUTNET");
    expect(screen.getByText(/z = 1\.2/)).toBeInTheDocument();
    expect(screen.queryByText(/⚠/)).not.toBeInTheDocument();
  });

  it("splits on EXPOSURE CHECK too", () => {
    view(
      "z = 0.4 — within normal range EXPOSURE CHECK: Men holds 54.2% of the metric and 53.9% of the rows — PROPORTIONAL");
    expect(screen.getByText(/EXPOSURE CHECK/)).toBeInTheDocument();
    expect(screen.getByText(/z = 0\.4/)).toBeInTheDocument();
  });
});
