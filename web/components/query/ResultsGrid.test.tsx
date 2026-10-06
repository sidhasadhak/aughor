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

  describe("DE-5e — the viewer shows a value by what it is, and says how it read it", () => {
    const RICH_COLUMNS = ["doc", "shape", "pic"];
    const RICH_TYPED = [{ name: "doc", type: "JSON" }, { name: "shape", type: "VARCHAR" }, { name: "pic", type: "VARCHAR" }];
    const RICH_ROWS: Cell[][] = [['{"a": [1, 2], "b": {"c": null}}', "POINT (4.9 52.37)", "https://img.example.com/cat.png"]];
    const open = (text: string) => {
      render(<ResultsGrid columns={RICH_COLUMNS} columnsTyped={RICH_TYPED} rows={RICH_ROWS} onAddFilter={() => {}} />);
      fireEvent.contextMenu(screen.getByText(text));
      fireEvent.click(screen.getByTestId("cell-open"));
    };

    it("a JSON document is a tree, with the text one toggle away", () => {
      open('{"a": [1, 2], "b": {"c": null}}');
      expect(screen.getByTestId("viewer-kind")).toHaveTextContent("JSON · declared JSON");
      const tree = screen.getByTestId("json-tree");
      expect(tree).toHaveTextContent("{2 keys}");
      expect(tree).toHaveTextContent("a: [2 items]");
      expect(tree).toHaveTextContent("c: ∅");
      // Collapsing a node hides its children and keeps its summary.
      fireEvent.click(screen.getAllByTestId("json-node")[1]);
      expect(tree).not.toHaveTextContent("0: 1");
      expect(tree).toHaveTextContent("a: [2 items]");
      fireEvent.click(screen.getByTestId("viewer-raw"));
      expect(screen.getByTestId("grid-value-text")).toHaveTextContent('"a": [');
    });

    it("a geometry is drawn to its own bounds, and the caption says what it is drawn from", () => {
      open("POINT (4.9 52.37)");
      expect(screen.getByTestId("viewer-kind")).toHaveTextContent("geometry · WKT, read from the text, declared VARCHAR");
      expect(screen.getByTestId("geometry-outline")).toBeInTheDocument();
      expect(screen.getByTestId("geometry-caption"))
        .toHaveTextContent("Point · 1 position · longitude 4.9 to 4.9, latitude 52.37 to 52.37");
      expect(screen.getByTestId("geometry-caption")).toHaveTextContent("not on a map");
    });

    it("an image URL is not loaded until asked, and says why", () => {
      const { container } = (() => { open("https://img.example.com/cat.png"); return { container: document.body }; })();
      expect(screen.getByTestId("viewer-kind")).toHaveTextContent("image URL · img.example.com, declared VARCHAR");
      expect(container.querySelector("img")).toBeNull();
      expect(screen.getByTestId("image-note")).toHaveTextContent("loading it tells img.example.com that you looked");
      fireEvent.click(screen.getByTestId("image-load"));
      expect(screen.getByTestId("image-view")).toHaveAttribute("src", "https://img.example.com/cat.png");
    });
  });

  describe("DE-5f — related rows through the joins the data bears out", () => {
    const JOINS = {
      table: "orders", column: "status", ontology: "not built" as const,
      joins: [
        { table: "orders", column: "status", other_table: "statuses", other_column: "code", match: "declared" as const,
          overlap: 1, verdict: "verified" as const, cardinality: null, source: "join_map" as const, openable: true,
          sentence: "100% value overlap; declared foreign key" },
        { table: "orders", column: "status", other_table: "shipments", other_column: "status", match: "inferred" as const,
          overlap: 0, verdict: "rejected" as const, cardinality: null, source: "join_map" as const, openable: false,
          sentence: "0% value overlap — the columns share a name and not their values" },
      ],
    };

    it("is not offered when the statement reads no one table", () => {
      render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}} />);
      fireEvent.contextMenu(screen.getByText("Complete"));
      expect(screen.queryByTestId("cell-related")).toBeNull();
    });

    const ordersOwnsAll = (c: string) => ({ table: "orders", column: c });

    it("lists each join with its evidence, offers the ones the data bears out, and opens through the owner", async () => {
      const fetchRelated = vi.fn(async () => JOINS);
      const onOpenRelated = vi.fn();
      render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}}
        columnSource={ordersOwnsAll} fetchRelated={fetchRelated} onOpenRelated={onOpenRelated} />);
      fireEvent.contextMenu(screen.getByText("Complete"));
      fireEvent.click(screen.getByTestId("cell-related"));
      await waitFor(() => expect(screen.getAllByTestId("related-join")).toHaveLength(2));
      expect(fetchRelated).toHaveBeenCalledWith("status");
      const [open, closed] = screen.getAllByTestId("related-open");
      expect(open).toHaveTextContent('statuses · code = "Complete"');
      expect(open).not.toBeDisabled();
      expect(closed).toBeDisabled();
      const sentences = screen.getAllByTestId("related-sentence").map(el => el.textContent ?? "");
      expect(sentences[0]).toContain("100% value overlap; declared foreign key · the schema");
      expect(sentences[1]).toContain("0% value overlap — the columns share a name and not their values");
      fireEvent.click(open);
      expect(onOpenRelated).toHaveBeenCalledWith(JOINS.joins[0], "status", "Complete");
      expect(screen.queryByTestId("related-rows-picker")).toBeNull();
    });

    it("says when no verified join touches the column, and whether an ontology is built", async () => {
      render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}}
        columnSource={ordersOwnsAll} fetchRelated={async () => ({ ...JOINS, joins: [] })} onOpenRelated={() => {}} />);
      fireEvent.contextMenu(screen.getByText("Shipped"));
      fireEvent.click(screen.getByTestId("cell-related"));
      await waitFor(() => expect(screen.getByTestId("related-note")).toHaveTextContent(
        "No verified join touches orders.status — nothing to open. No ontology is built for this connection"));
    });

    it("is not offered on a NULL", () => {
      render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}}
        columnSource={ordersOwnsAll} fetchRelated={async () => JOINS} onOpenRelated={() => {}} />);
      fireEvent.contextMenu(screen.getByText("∅"));
      expect(screen.getByTestId("cell-menu")).toBeInTheDocument();
      expect(screen.queryByTestId("cell-related")).toBeNull();
    });

    it("DE-close — on a joined statement, offered only on a column some table owns", () => {
      // `status` is orders'; `total` is a computed column with no one source.
      const ownsStatusOnly = (c: string) => (c === "status" ? { table: "orders", column: "status" } : null);
      render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}}
        columnSource={ownsStatusOnly} fetchRelated={async () => JOINS} onOpenRelated={() => {}} />);
      fireEvent.contextMenu(screen.getByText("10"));
      expect(screen.queryByTestId("cell-related")).toBeNull();
      fireEvent.keyDown(window, { key: "Escape" });
      fireEvent.contextMenu(screen.getByText("Complete"));
      expect(screen.getByTestId("cell-related")).toBeInTheDocument();
    });
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
    const boxes = picker.querySelectorAll<HTMLElement>('[role="checkbox"]');
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

  it("DE-5d — a live read the engine refused is said in the engine's words, and the rows speak", async () => {
    const live = async () => ({ values: [], truncated: false, source: "orders", error: "Catalog Error: Table with name orders does not exist!" });
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}}
      truncated fetchDistinct={live} />);
    fireEvent.click(screen.getAllByTestId("grid-col-pick")[0]);
    await waitFor(() => expect(screen.getByTestId("picker-source")).toHaveTextContent(
      "The table orders could not be read live (Catalog Error: Table with name orders does not exist!) — from the 3 rows shown"));
    // The values on offer are the rows' own: "Complete" is in the grid AND in the picker's list.
    expect(screen.getAllByText("Complete")).toHaveLength(2);
  });

  it("the menu's pick entry opens the same picker for that column", () => {
    render(<ResultsGrid columns={COLUMNS} columnsTyped={TYPED} rows={ROWS} onAddFilter={() => {}} />);
    fireEvent.contextMenu(screen.getByText("10"));
    fireEvent.click(screen.getByTestId("cell-pick-values"));
    expect(screen.getByTestId("column-value-picker")).toHaveTextContent("total");
    expect(screen.getByTestId("picker-source")).toHaveTextContent("From the 3 rows shown");
  });
});
