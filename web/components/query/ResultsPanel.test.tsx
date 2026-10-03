// @vitest-environment jsdom
/**
 * DE-5d (ROADMAP §3.51) — what the results footer says about a cut result, and the two things it
 * offers next: "Count all rows" and "Load more". Both go to the server; the panel shows what came
 * back — a total with its as-of, a page handed to the owner of the results, or a refusal in the
 * server's own words. The API module is stubbed: the assertions are about what the panel asks for
 * and what it renders, never about the network.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ResultsPanel, cutNote } from "./ResultsPanel";
import type { TypedQueryPage, TypedQueryResult } from "@/lib/api";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, i) => ({ index: i, start: i * 30, size: 30, key: i })),
    getTotalSize: () => count * 30,
  }),
}));
vi.mock("@/components/charts/ResultChartCard", () => ({ ResultChartCard: () => null }));

const api = vi.hoisted(() => ({
  countQueryRows: vi.fn(),
  loadMoreRows: vi.fn(),
  getColumnDistinct: vi.fn(),
  pinQueryToDashboard: vi.fn(),
}));
// Partial: the panel's neighbours (the schedule popover, the quick-fix panel) import other
// functions from the same module at load, and only the four the footer calls are stubbed.
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const SQL = "SELECT id FROM t ORDER BY id";

function result(over: Partial<TypedQueryResult> = {}): TypedQueryResult {
  return {
    columns: ["id"], columns_typed: [{ name: "id", type: "BIGINT" }],
    rows: [[1], [2], [3]], row_count: 3, truncated: true, cut_by: "limit",
    duration_ms: 4, sql: SQL, cached: false, error: null, caveats: [], format: "typed",
    ...over,
  };
}

function mount(r: TypedQueryResult, extra: Partial<Parameters<typeof ResultsPanel>[0]> = {}) {
  return render(
    <ResultsPanel results={[r]} resultIdx={0} onResultIdx={() => {}} error="" running={false}
      connId="c1" pageSize={3} runKey={1} {...extra} />,
  );
}

beforeEach(() => {
  api.countQueryRows.mockReset();
  api.loadMoreRows.mockReset();
});

describe("DE-5d — the cut is said for what it is", () => {
  it("names the limit, the budget or the connector's cap", () => {
    expect(cutNote({ row_count: 500, cut_by: "limit" })).toBe("cut at 500 rows — more exist beyond this limit");
    expect(cutNote({ row_count: 10000, cut_by: "budget" }))
      .toBe("cut at 10,000 rows by this connection's row budget — more exist");
    expect(cutNote({ row_count: 500, cut_by: "cap" }))
      .toBe("cut at 500 rows — this connector returns at most that many a call, whatever the limit");
    expect(cutNote({ row_count: 500, cut_by: undefined })).toBe("truncated — more rows exist beyond this limit");
  });

  it("shows the note and both actions only on a cut result", () => {
    const { unmount } = mount(result({ cut_by: "budget", row_count: 10000 }), { onAppendRows: () => {} });
    expect(screen.getByTestId("cut-note")).toHaveTextContent("cut at 10,000 rows by this connection's row budget");
    expect(screen.getByTestId("count-all")).toHaveTextContent("Count all rows");
    expect(screen.getByTestId("load-more")).toHaveTextContent("Load 3 more");
    unmount();
    mount(result({ truncated: false, cut_by: null }), { onAppendRows: () => {} });
    expect(screen.queryByTestId("cut-note")).toBeNull();
    expect(screen.queryByTestId("count-all")).toBeNull();
    expect(screen.queryByTestId("load-more")).toBeNull();
  });

  it("offers no Load more when nobody owns the results", () => {
    mount(result());
    expect(screen.getByTestId("count-all")).toBeInTheDocument();
    expect(screen.queryByTestId("load-more")).toBeNull();
  });
});

describe("DE-5f — a result opened from a cell is a page of its own", () => {
  it("the pager names it, and its count runs with its own bound value", async () => {
    api.countQueryRows.mockResolvedValue({ total: 2, as_of: "2026-10-03T12:31:35+00:00", duration_ms: 1, sql: "", error: null, code: null });
    const related = result({
      sql: 'SELECT * FROM "orders" WHERE "buyer" = :v', params: { v: "c'1" },
      label: "orders rows related to customers.id = c'1", rows: [[1], [2]], row_count: 2,
      caveats: ["Related through customers.id = orders.buyer — 100% value overlap; declared foreign key."],
    });
    render(
      <ResultsPanel results={[result(), related]} resultIdx={1} onResultIdx={() => {}} error="" running={false}
        connId="c1" pageSize={3} runKey={1} params={{ lo: 0 }} />,
    );
    expect(screen.getByTestId("results-pager")).toHaveTextContent("Results 2 of 2 · orders rows related to customers.id = c'1");
    expect(screen.getByText(/Related through customers.id = orders.buyer/)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("count-all"));
    await waitFor(() => expect(screen.getByTestId("count-result")).toHaveTextContent("2 rows in all"));
    expect(api.countQueryRows).toHaveBeenCalledWith("c1", 'SELECT * FROM "orders" WHERE "buyer" = :v', { v: "c'1" });
  });
});

describe("DE-5d — Count all rows", () => {
  it("asks the server for the statement with the run's bound values and shows the total with its as-of", async () => {
    api.countQueryRows.mockResolvedValue({
      total: 12000, as_of: "2026-10-03T12:31:35+00:00", duration_ms: 4.7, sql: SQL, error: null, code: null,
    });
    mount(result(), { params: { lo: 0 } });
    fireEvent.click(screen.getByTestId("count-all"));
    await waitFor(() => expect(screen.getByTestId("count-result")).toHaveTextContent("12,000 rows in all · as of"));
    expect(api.countQueryRows).toHaveBeenCalledWith("c1", SQL, { lo: 0 });
  });

  it("shows a refusal in the server's words, never a zero", async () => {
    api.countQueryRows.mockResolvedValue({
      total: null, as_of: "2026-10-03T12:31:35+00:00", duration_ms: 1, sql: SQL,
      error: 'Binder Error: Referenced column "nope" not found', code: "FAILED",
    });
    mount(result());
    fireEvent.click(screen.getByTestId("count-all"));
    await waitFor(() => expect(screen.getByTestId("count-result"))
      .toHaveTextContent('Could not count — Binder Error: Referenced column "nope" not found'));
    expect(screen.getByTestId("count-result").textContent).not.toMatch(/\b0 rows/);
  });

  it("a failed request is said too", async () => {
    api.countQueryRows.mockRejectedValue(new Error("Query exceeded this connection's 60000ms time limit"));
    mount(result());
    fireEvent.click(screen.getByTestId("count-all"));
    await waitFor(() => expect(screen.getByTestId("count-result"))
      .toHaveTextContent("Could not count — Query exceeded this connection's 60000ms time limit"));
  });
});

describe("DE-5d — Load more", () => {
  const page = (over: Partial<TypedQueryPage> = {}): TypedQueryPage => ({
    ...result({ rows: [[4], [5]], row_count: 2, truncated: false, cut_by: null }),
    offset: 3, ordered: true, ...over,
  });

  it("asks for the next page after every row shown and hands it to the owner of the results", async () => {
    const onAppendRows = vi.fn();
    const p = page();
    api.loadMoreRows.mockResolvedValue(p);
    mount(result(), { onAppendRows, params: { lo: 0 } });
    fireEvent.click(screen.getByTestId("load-more"));
    await waitFor(() => expect(onAppendRows).toHaveBeenCalledWith(0, p));
    expect(api.loadMoreRows).toHaveBeenCalledWith("c1", SQL, 3, 3, { lo: 0 });
    expect(screen.queryByTestId("more-result")).toBeNull();
  });

  it("a refused page is said in the server's words and nothing is appended", async () => {
    const onAppendRows = vi.fn();
    api.loadMoreRows.mockResolvedValue(page({
      rows: [], row_count: 0, code: "PAGE_BILLED_AS_SCAN",
      error: "On BigQuery every statement is billed as a full scan of the tables it reads, so each page would cost what the whole result cost. Re-run with a higher limit instead — that is billed once.",
    }));
    mount(result(), { onAppendRows });
    fireEvent.click(screen.getByTestId("load-more"));
    await waitFor(() => expect(screen.getByTestId("more-result"))
      .toHaveTextContent("On BigQuery every statement is billed as a full scan"));
    expect(onAppendRows).not.toHaveBeenCalled();
  });

  it("the footer's count and the filter bar's total follow the rows the owner appended", () => {
    // The owner (SqlMode) merges the page; the panel reads the merged result like any other.
    const merged = result({ rows: [[1], [2], [3], [4], [5]], row_count: 5, truncated: false, cut_by: null,
      caveats: ["This statement has no ORDER BY on its outermost query, so the engine may hand back its rows in another order each time — a page can repeat or skip rows. Add an ORDER BY for pages that join up exactly."] });
    mount(merged, { onAppendRows: () => {} });
    expect(screen.getByText("5 rows")).toBeInTheDocument();
    expect(screen.getByText(/no ORDER BY on its outermost query/)).toBeInTheDocument();
    expect(screen.queryByTestId("cut-note")).toBeNull();
  });
});
