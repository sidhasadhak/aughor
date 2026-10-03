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

/** A report can hold several phases of one KIND: scheduled runs routinely produce two or more
 *  `decomposition` phases (26 of the last 100 reports, measured 2026-09-26). Keyed by `phase_id`,
 *  React reported "two children with the same key" and could drop one. vitest.setup.ts fails this
 *  test on a colliding key; the assertions check that no phase was dropped. */
describe("phases that share a kind all render", () => {
  it("renders both decomposition phases", () => {
    const phase = (phase_id: string, phase_name: string) => ({
      phase_id, phase_name, phase_icon: "", status: "complete", summary: `${phase_name}: what it found.`, findings: [],
    });
    render(<ReportView report={{
      headline: "Revenue fell in the South", executive_summary: "", confidence: "MEDIUM",
      phases: [
        phase("decomposition", "Decomposition by region"),
        phase("baseline", "Baseline"),
        phase("decomposition", "Decomposition by channel"),
      ],
    } as never} />);
    expect(screen.getByText(/Decomposition by region/)).toBeInTheDocument();
    expect(screen.getByText(/Decomposition by channel/)).toBeInTheDocument();
  });
});

describe("an answer in the analyst's own words", () => {
  it("renders its table as a table and has no empty headline", () => {
    // Item 3 (2026-09-30): a question that asks to see the data is answered by the
    // analyst's conclusion, whose table must read as a table rather than as pipes.
    const report = {
      ...(reportWith("") as object), headline: "",
      executive_summary: "Fulfilment takes about 3 days.\n\n| Centre | Days |\n| :--- | :--- |\n| NY/NJ | 3.12 |",
    } as never;
    const { container } = render(<ReportView report={report} />);
    expect(container.querySelector("table")?.textContent).toContain("NY/NJ");
    expect(container.textContent).not.toContain("| NY/NJ |");
    expect(container.querySelector("h2")).toBeNull();
  });
});

/** "If it's a single number being displayed, does one really need a table?" (2026-10-02): a finding of
 *  one row reads as its figures; a finding of many rows with no chart keeps its table. */
describe("a finding of one row reads as its figures", () => {
  const withRows = (columns: string[], rows: (string | number | null)[][], chart_type = "auto") => ({
    headline: "In July 2026, 7,027 units were sold", executive_summary: "", confidence: "HIGH",
    phases: [{ phase_id: "adhoc_2", phase_name: "units_sold — 2026-07-01 → 2026-07-31", phase_icon: "",
      status: "complete", summary: "", caveats: [],
      findings: [{ finding_id: "f1", title: "units_sold — 2026-07-01 → 2026-07-31", claim: "", interpretation: "",
        sql: "SELECT 1", columns, rows, row_count: rows.length, key_numbers: [], chart_type,
        stat_note: null, is_significant: false }] }],
  }) as never;

  it("not as a one-row table under a disclosure", () => {
    const report = { ...(withRows(["units_sold"], [["7027"]]) as object), headline: "Units were sold in July 2026" } as never;
    render(<ReportView report={report} />);
    expect(screen.getByText("7,027")).toBeInTheDocument();
    expect(screen.queryByText(/Data · 1 rows/)).not.toBeInTheDocument();
  });

  it("many rows with no chart keep their table", () => {
    render(<ReportView report={withRows(["name"], [["a"], ["b"]], "none")} />);
    expect(screen.getByText(/Data · 2 rows/)).toBeInTheDocument();
  });
});

/** "Such a simple question and it got answered — then why do we have two different figures shown as the
 *  evidence below?" (2026-10-02). Q1's sentence stated both figures; the body printed both again, each
 *  under its own raw title. A simple answer — every result one record — keeps its sentence and gains one
 *  line of where each figure came from. */
describe("a simple answer", () => {
  const record = (id: string, column: string, value: string, sql: string) => ({
    phase_id: id, phase_name: `${column} — 2026-07-01 → 2026-07-31`, phase_icon: "", status: "complete",
    summary: "", caveats: [],
    findings: [{ finding_id: `${id}_1`, title: `${column} — 2026-07-01 → 2026-07-31`, claim: null, interpretation: "",
      sql, columns: [column], rows: [[value]], row_count: 1, key_numbers: [], chart_type: "auto",
      stat_note: null, is_significant: false }],
  });
  const UNITS = "SELECT COUNT(id) AS units_sold FROM inventory_items WHERE sold_at IS NOT NULL";
  const q1 = (headline: string, extra: object = {}) => ({
    headline, executive_summary: "The revenue figure excludes cancelled orders.", confidence: "HIGH",
    observation_period: "July 2026", comparison_basis: "",
    phases: [
      { phase_id: "intake", phase_name: "Question Intake", phase_icon: "", status: "complete", summary: "", findings: [] },
      record("adhoc_2", "units_sold", "7027", UNITS),
      record("adhoc_3", "total_revenue", "359224.30043935776", "SELECT SUM(sale_price) AS total_revenue FROM order_items"),
    ],
    ...extra,
  }) as never;
  const STATED = "In July 2026, the total revenue was $359,224.30 and 7,027 units were sold";

  it("does not print a figure the sentence states, nor the period it names", () => {
    render(<ReportView report={q1(STATED)} onShowSource={vi.fn()} />);
    expect(screen.queryByText("7,027")).not.toBeInTheDocument();
    expect(screen.queryByText("359,224.30")).not.toBeInTheDocument();
    expect(screen.queryByText("July 2026")).not.toBeInTheDocument();
    expect(screen.queryByText(/units_sold/)).not.toBeInTheDocument();
  });

  it("names each figure's source on one line, in the sentence's order, and opens its SQL", () => {
    const show = vi.fn();
    render(<ReportView report={q1(STATED)} onShowSource={show} />);
    const sources = screen.getAllByRole("button", { name: /Table/ });
    expect(sources.map((b) => b.textContent)).toEqual(["Total Revenue", "Units Sold"]);
    sources[1].click();
    expect(show).toHaveBeenCalledWith(expect.objectContaining({ sql: UNITS, columns: ["units_sold"] }));
  });

  it("prints a figure the sentence leaves out, and the period it does not name", () => {
    render(<ReportView report={q1("Revenue was $359,224.30")} onShowSource={vi.fn()} />);
    expect(screen.getByText("7,027")).toBeInTheDocument();
    expect(screen.queryByText("359,224.30")).not.toBeInTheDocument();
    expect(screen.getByText("July 2026")).toBeInTheDocument();
  });

  it("prints the sentence once when the summary is the headline with its full stop", () => {
    const { container } = render(<ReportView report={q1(STATED, { executive_summary: `${STATED}.` })} onShowSource={vi.fn()} />);
    expect(container.textContent?.split("7,027 units were sold")).toHaveLength(2);
  });

  it("names no period the answer names in other words", () => {
    // Q2 (2026-10-03): "between March 5, 2026, and September 4, 2026", then "5 March – 4 September 2026" beneath
    const days = render(<ReportView report={q1("Revenue between March 5, 2026, and September 4, 2026 was $359,224.30 "
      + "from 7,027 units", { observation_period: "5 March – 4 September 2026" })} onShowSource={vi.fn()} />);
    expect(days.queryByText("5 March – 4 September 2026")).not.toBeInTheDocument();
    days.unmount();
    const months = render(<ReportView report={q1("Revenue grew from $359,224.30 in September 2025 to 7,027 units in "
      + "August 2026", { observation_period: "September 2025–August 2026" })} onShowSource={vi.fn()} />);
    expect(months.queryByText("September 2025–August 2026")).not.toBeInTheDocument();
    months.unmount();
    render(<ReportView report={q1(STATED, { observation_period: "5 March – 4 September 2026" })} onShowSource={vi.fn()} />);
    expect(screen.getByText("5 March – 4 September 2026")).toBeInTheDocument();
  });

  it("keeps the full layout when a result carries more than its figures", () => {
    const report = q1(STATED) as unknown as { phases: { findings: { interpretation: string }[] }[] };
    report.phases[1].findings[0].interpretation = "Units fell short of the plan.";
    render(<ReportView report={report as never} onShowSource={vi.fn()} />);
    expect(screen.getByText("Units fell short of the plan.")).toBeInTheDocument();
    expect(screen.getByText(/units_sold — 2026-07-01/)).toBeInTheDocument();
    expect(screen.queryByText("7,027")).not.toBeInTheDocument();     // still not printed twice
  });
});

/** A chart is captioned by what it draws (2026-10-03): Q2's revenue bars sat under "Revenue and average order
 *  value by category"; the source link keeps the result's own title. */
describe("a chart's caption", () => {
  it("names the measure drawn, not every measure the result holds", () => {
    const title = "Revenue and average order value by category — 4 Mar – 3 Sep 2026";
    const report = {
      headline: "Outerwear & Coats led", executive_summary: "", confidence: "HIGH",
      phases: [{ phase_id: "adhoc_2", phase_name: title, phase_icon: "", status: "complete", summary: "", caveats: [],
        findings: [{ finding_id: "f1", title, claim: null, interpretation: "", sql: "SELECT 1",
          columns: ["category", "revenue", "average_order_value"],
          rows: [["Outerwear & Coats", "237836.63", "150.82"], ["Jeans", "214128.38", "102.26"], ["Intimates", "85036.08", "36.72"]],
          row_count: 3, key_numbers: [], chart_type: "auto", stat_note: null, is_significant: false }] }],
    } as never;
    const { container } = render(<ReportView report={report} onShowSource={vi.fn()} />);
    expect(container.querySelector("figcaption")?.textContent).toBe("Revenue by category — 4 Mar – 3 Sep 2026");
    expect(screen.getByTitle(`Data + SQL behind “${title}”`)).toBeInTheDocument();
  });
});

/** Q3 (2026-10-03) drew monthly revenue twice: September to August with its order count, and again from the August
 *  before. A chart another chart already draws is not drawn again; its source stays. */
describe("a chart another chart already draws", () => {
  it("is not drawn again, and its data and SQL stay a click away", () => {
    const months = ["2025-08-01", "2025-09-01", "2025-10-01", "2025-11-01"];
    const revenue = ["57130.02", "54076.37", "60410.18", "64012.67"];
    const result = (id: string, title: string, columns: string[], rows: string[][]) => ({
      phase_id: id, phase_name: title, phase_icon: "", status: "complete", summary: "", caveats: [],
      findings: [{ finding_id: id, title, claim: null, interpretation: "", sql: "SELECT 1", columns, rows,
        row_count: rows.length, key_numbers: [], chart_type: "auto", stat_note: null, is_significant: false }] });
    const shorter = "Monthly revenue and order count by month — Sep – Nov 2025";
    const report = { headline: "Revenue grew", executive_summary: "", confidence: "HIGH", phases: [
      result("adhoc_2", shorter, ["month", "monthly_revenue", "orders"], months.slice(1).map((m, i) => [m, revenue[i + 1], String(655 + i)])),
      result("adhoc_3", "Monthly revenue by month — Aug – Nov 2025", ["month", "monthly_revenue"], months.map((m, i) => [m, revenue[i]])),
    ] } as never;
    const { container } = render(<ReportView report={report} onShowSource={vi.fn()} />);
    expect([...container.querySelectorAll("figcaption")].map((f) => f.textContent)).toEqual(["Monthly revenue by month — Aug – Nov 2025"]);
    expect(screen.getByTitle(`Data + SQL behind “${shorter}”`)).toBeInTheDocument();
    expect(screen.queryByText(/Data · 3 rows/)).not.toBeInTheDocument();
  });

  it("draws two different series both", () => {
    const result = (id: string, title: string, rows: string[][]) => ({
      phase_id: id, phase_name: title, phase_icon: "", status: "complete", summary: "", caveats: [],
      findings: [{ finding_id: id, title, claim: null, interpretation: "", sql: "SELECT 1", columns: ["month", "value"], rows,
        row_count: rows.length, key_numbers: [], chart_type: "auto", stat_note: null, is_significant: false }] });
    const report = { headline: "Revenue grew", executive_summary: "", confidence: "HIGH", phases: [
      result("adhoc_2", "Revenue by month — Sep – Nov 2025", [["2025-09-01", "54076.37"], ["2025-10-01", "60410.18"], ["2025-11-01", "64012.67"]]),
      result("adhoc_3", "Orders by month — Aug – Nov 2025", [["2025-08-01", "663"], ["2025-09-01", "655"], ["2025-10-01", "707"], ["2025-11-01", "703"]]),
    ] } as never;
    const { container } = render(<ReportView report={report} onShowSource={vi.fn()} />);
    expect(container.querySelectorAll("figcaption")).toHaveLength(2);
  });
});
