// @vitest-environment jsdom

/**
 * A finding's open detail, under a range, draws the rows the figure on its tile is read from
 * (2026-10-09). theLook's Day view showed "217 vs 184" on the order-status tile and opened on the
 * finding's all-history chart — 37,483 shipped orders — which neither number is read from; the
 * user could not connect the two. The detail now opens on the range's own cut of the finding's
 * query, with the compared range's and the recorded evidence one switch away.
 */
import { fireEvent, render, screen } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { FindingDetail, type RangeFigure } from "@/components/BriefingPanel";
import type { ExplorationInsight, FindingReask } from "@/lib/api";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  runDirectQuery: vi.fn(),
}));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const RECORDED = "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY 1";
const R: FindingReask = {
  id: "pinned__1", domain: "Key Questions", grain: "orders.created_at", measure: "order_count", how: "total",
  current: 217, previous: 184, rel: 0.179, rows_current: 5, rows_previous: 5,
  sql: "SELECT status, COUNT(*) AS order_count FROM (orders cut to 2026-09-09) GROUP BY 1",
  sql_previous: "SELECT status, COUNT(*) AS order_count FROM (orders cut to 2026-09-02) GROUP BY 1",
};
const FIG: RangeFigure = { reask: R, covers: "2026-09-09 (Wednesday)", comparedWith: "the same weekday a week earlier, 2026-09-02" };
const INSIGHT = { id: "pinned__1", finding: "Shipped leads with 37,483 orders.", sql: RECORDED } as ExplorationInsight;
// One figure per statement, so the detail draws it as its big number and the test reads which ran.
const ANSWERS: Record<string, string> = { [R.sql]: "217", [R.sql_previous!]: "184", [RECORDED]: "124972" };

const run = vi.mocked(api.runDirectQuery);
beforeEach(() => {
  run.mockReset();
  run.mockImplementation(async (_conn: string, sql: string) =>
    ({ columns: ["order_count"], rows: [[ANSWERS[sql]]], error: null }) as unknown as Awaited<ReturnType<typeof api.runDirectQuery>>);
});

const show = (range: RangeFigure | null) => render(
  <FindingDetail insight={INSIGHT} domain="Key Questions" connectionId="8233e4fd" chartHeight={190}
    range={range} onInvestigate={vi.fn()} onEvidence={vi.fn()} />);

describe("a re-asked finding's detail", () => {
  it("opens on the range's rows, and says the tile's figure is their total", async () => {
    show(FIG);
    await screen.findByText("217");
    expect(run.mock.calls.map(c => c[1])).toEqual([R.sql]);
    expect(screen.getByTestId("finding-figure-note")).toHaveTextContent(
      "For 2026-09-09 (Wednesday), the finding's query returns the 5 rows below; 217 is the total of order_count across them.");
  });

  it("draws the compared range's rows behind the 'vs' figure, and the recorded evidence behind the statement", async () => {
    show(FIG);
    await screen.findByText("217");
    fireEvent.click(screen.getByRole("radio", { name: "Compared range" }));
    await screen.findByText("184");
    expect(screen.getByTestId("finding-figure-note")).toHaveTextContent("184 is the total of order_count across them.");
    fireEvent.click(screen.getByRole("radio", { name: "All history" }));
    await screen.findByText("124,972");
    expect(screen.getByTestId("finding-figure-note")).toHaveTextContent("The statement above reads these rows.");
    // Back to the range: drawn from what it already fetched, not asked again.
    fireEvent.click(screen.getByRole("radio", { name: "This range" }));
    await screen.findByText("217");
    expect(run.mock.calls.map(c => c[1])).toEqual([R.sql, R.sql_previous, RECORDED]);
  });

  it("offers no compared range when the re-ask carried no cut for it", async () => {
    show({ ...FIG, reask: { ...R, sql_previous: undefined } });
    await screen.findByText("217");
    expect(screen.queryByRole("radio", { name: "Compared range" })).toBeNull();
    expect(screen.getByRole("radio", { name: "All history" })).toBeInTheDocument();
  });

  it("on the standing view draws the recorded evidence, with no switch", async () => {
    show(null);
    await screen.findByText("124,972");
    expect(run.mock.calls.map(c => c[1])).toEqual([RECORDED]);
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByTestId("finding-figure-note")).toBeNull();
  });
});
