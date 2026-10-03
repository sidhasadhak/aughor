// @vitest-environment jsdom
/**
 * DE-5a/b/c (ROADMAP §3.51) — what the results grid shows about a column and what a right-click
 * on a cell does to the filter chips.
 *
 * jsdom measures every element as 0×0, so the row virtualizer would mount nothing; it is stubbed
 * to hand back every row. The assertions are about what the grid renders and what it HANDS the
 * chip bar — the phrase — not about geometry.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ResultsGrid } from "./ResultsGrid";
import type { Cell } from "@/lib/query/resultFilter";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, i) => ({ index: i, start: i * 30, size: 30, key: i })),
    getTotalSize: () => count * 30,
  }),
}));

const COLUMNS = ["status", "total"];
const TYPED = [{ name: "status", type: "VARCHAR" }, { name: "total", type: "BIGINT" }];
const ROWS: Cell[][] = [["Complete", 10], ["Shipped", 5], [null, 7]];

function texts(testid: string): string[] {
  return screen.queryAllByTestId(testid).map(el => el.textContent ?? "");
}

describe("DE-5a — the declared type under each column name, and a row-number column", () => {
  it("shows each column's declared type and numbers the rows", () => {
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} />);
    expect(texts("grid-col-type")).toEqual(["VARCHAR", "BIGINT"]);
    expect(screen.getByTestId("grid-rownum-header")).toHaveTextContent("#");
    expect(texts("grid-rownum")).toEqual(["1", "2", "3"]);
  });

  it("shows no type line for a legacy result that declares none, but still numbers the rows", () => {
    render(<ResultsGrid columns={COLUMNS} rows={ROWS} />);
    expect(screen.queryAllByTestId("grid-col-type")).toHaveLength(0);
    expect(texts("grid-rownum")).toEqual(["1", "2", "3"]);
  });
});

describe("DE-5b — the right-click menu feeds the filter chips", () => {
  it("filter to this value hands the chip bar the grammar's phrase", () => {
    const onAddFilter = vi.fn();
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={onAddFilter} />);
    fireEvent.contextMenu(screen.getByText("Complete"));
    expect(screen.getByTestId("cell-menu")).toHaveTextContent('status · "Complete"');
    fireEvent.click(screen.getByTestId("cell-filter-is"));
    expect(onAddFilter).toHaveBeenCalledWith('status = "Complete"');
    expect(screen.queryByTestId("cell-menu")).toBeNull();
  });

  it("exclude, only-null and only-non-null are the grammar's phrases too", () => {
    const onAddFilter = vi.fn();
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={onAddFilter} />);
    fireEvent.contextMenu(screen.getByText("Shipped"));
    fireEvent.click(screen.getByTestId("cell-filter-isnot"));
    fireEvent.contextMenu(screen.getByText("Shipped"));
    fireEvent.click(screen.getByTestId("cell-filter-null"));
    fireEvent.contextMenu(screen.getByText("Shipped"));
    fireEvent.click(screen.getByTestId("cell-filter-notnull"));
    expect(onAddFilter.mock.calls.map(c => c[0])).toEqual([
      'status != "Shipped"', "status is null", "status is not null",
    ]);
  });

  it("a NULL cell's filter-to is the null test, said as such", () => {
    const onAddFilter = vi.fn();
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={onAddFilter} />);
    fireEvent.contextMenu(screen.getByTitle("NULL"));
    expect(screen.getByTestId("cell-filter-is")).toHaveTextContent("Only null rows");
    expect(screen.queryByTestId("cell-filter-null")).toBeNull();
    fireEvent.click(screen.getByTestId("cell-filter-is"));
    expect(onAddFilter).toHaveBeenCalledWith("status is null");
  });

  it("a number is handed over as the grammar reads it", () => {
    const onAddFilter = vi.fn();
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={onAddFilter} />);
    fireEvent.contextMenu(screen.getByText("10"));
    fireEvent.click(screen.getByTestId("cell-filter-is"));
    expect(onAddFilter).toHaveBeenCalledWith('total = "10"');
  });

  it("open value shows the cell in the viewer", () => {
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}} />);
    fireEvent.contextMenu(screen.getByText("Shipped"));
    fireEvent.click(screen.getByTestId("cell-open"));
    expect(screen.getByTestId("grid-value-text")).toHaveTextContent("Shipped");
  });

  it("without a chip bar to feed, the menu offers copy and open only, and no column has a picker", () => {
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} />);
    expect(screen.queryAllByTestId("grid-col-pick")).toHaveLength(0);
    fireEvent.contextMenu(screen.getByText("Complete"));
    expect(screen.getByTestId("cell-menu")).toBeInTheDocument();
    expect(screen.queryByTestId("cell-filter-is")).toBeNull();
    expect(screen.queryByTestId("cell-pick-values")).toBeNull();
    expect(screen.getByTestId("cell-copy")).toBeInTheDocument();
    expect(screen.getByTestId("cell-copy-sql")).toBeInTheDocument();
    expect(screen.getByTestId("cell-open")).toBeInTheDocument();
  });

  it("Escape closes the menu", () => {
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}} />);
    fireEvent.contextMenu(screen.getByText("Complete"));
    expect(screen.getByTestId("cell-menu")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("cell-menu")).toBeNull();
  });
});

describe("DE-5c — the value picker says where its values come from", () => {
  it("a result that was not cut: from the rows shown, with counts, and a pick becomes one phrase", () => {
    const onAddFilter = vi.fn();
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={onAddFilter} />);
    fireEvent.click(screen.getAllByTestId("grid-col-pick")[0]);
    const picker = screen.getByTestId("column-value-picker");
    expect(screen.getByTestId("picker-source")).toHaveTextContent("From the 3 rows shown");
    expect(screen.getByTestId("picker-source")).not.toHaveTextContent("cut");
    const boxes = picker.querySelectorAll<HTMLInputElement>("input[type=checkbox]");
    expect(boxes).toHaveLength(3); // Complete, Shipped, NULL
    fireEvent.click(boxes[0]);
    fireEvent.click(boxes[1]);
    fireEvent.click(screen.getByTestId("picker-apply"));
    expect(onAddFilter).toHaveBeenCalledWith('status in "Complete", "Shipped"');
    expect(screen.queryByTestId("column-value-picker")).toBeNull();
  });

  it("a cut result with a table to read: the values come live from the table, and say so", async () => {
    const live = vi.fn(async (column: string) => ({
      values: ["Complete", "Shipped", "Returned", "Cancelled"], truncated: false, source: `shop.orders (${column})`,
    }));
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}}
      truncated fetchDistinct={live} />);
    fireEvent.click(screen.getAllByTestId("grid-col-pick")[0]);
    await waitFor(() => expect(screen.getByTestId("picker-source")).toHaveTextContent(
      "From the table shop.orders (status), read live"));
    expect(live).toHaveBeenCalledWith("status");
    // The live list holds a value the three rows on screen never showed.
    expect(screen.getByText("Returned")).toBeInTheDocument();
  });

  it("a cut live read says it is the first N", async () => {
    const live = async () => ({ values: ["a", "b"], truncated: true, source: "orders" });
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}}
      truncated fetchDistinct={live} />);
    fireEvent.click(screen.getAllByTestId("grid-col-pick")[0]);
    await waitFor(() => expect(screen.getByTestId("picker-source")).toHaveTextContent(
      "From the table orders, read live — the first 2"));
  });

  it("a cut result with no table to read says the rows are a sample", () => {
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}} truncated />);
    fireEvent.click(screen.getAllByTestId("grid-col-pick")[0]);
    expect(screen.getByTestId("picker-source")).toHaveTextContent(
      "From the 3 rows shown — the result was cut, so more values may exist");
  });

  it("a cut result whose table could not be read falls back to the rows and says so", async () => {
    const live = async () => null;
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}}
      truncated fetchDistinct={live} />);
    fireEvent.click(screen.getAllByTestId("grid-col-pick")[0]);
    await waitFor(() => expect(screen.getByTestId("picker-source")).toHaveTextContent(
      "the result was cut, so more values may exist"));
  });

  it("the menu's pick entry opens the same picker for that column", () => {
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}} />);
    fireEvent.contextMenu(screen.getByText("10"));
    fireEvent.click(screen.getByTestId("cell-pick-values"));
    expect(screen.getByTestId("column-value-picker")).toHaveTextContent("total");
    expect(screen.getByTestId("picker-source")).toHaveTextContent("From the 3 rows shown");
  });
});
