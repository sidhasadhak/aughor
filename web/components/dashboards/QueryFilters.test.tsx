// @vitest-environment jsdom
/** The filter column of a dashboard made from a file: what a reader ticks narrows every card that reads the table, and is theirs. */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ previewDashboardQuery: vi.fn() }));
vi.mock("@/lib/api", async importOriginal => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));

import { QueryFiltersPiece, QueryNarrowingProvider, readsTable, useQueryNarrowing } from "./QueryFilters";

const COLUMNS = [{ column: "channel", label: "Channel" }, { column: "ordered_on", label: "Month", grain: "month" }];

function Narrowing() {
  const { narrowing } = useQueryNarrowing();
  return <output data-testid="narrowing">{JSON.stringify(narrowing)}</output>;
}

function draw() {
  render(<Theme><QueryNarrowingProvider table="orders"><QueryFiltersPiece connectionId="sheets" table="orders" columns={COLUMNS} /><Narrowing /></QueryNarrowingProvider></Theme>);
}

beforeEach(() => {
  api.previewDashboardQuery.mockImplementation(async (_c: string, q: { sql: string }) => {
    if (q.sql.startsWith("SELECT COUNT(*)")) return { refused: [], rows: [[7]] };
    if (q.sql.includes("strftime")) return { refused: [], rows: [["2026-07", 3], ["2026-08", 4]] };
    return { refused: [], rows: [["Search", 4], ["Email", 3]] };
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("a dashboard's filter column over a table", () => {
  it("shows each value with how many rows hold it, and how many are left of how many", async () => {
    draw();
    await waitFor(() => expect(screen.getAllByTestId("query-facet-row")).toHaveLength(4));
    expect(screen.getByTestId("query-filters-left")).toHaveTextContent("7");
    expect(screen.getByRole("checkbox", { name: "Channel: Search" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Month: Jul 2026" })).toBeInTheDocument();
  });

  it("narrows by what is ticked, and a date by its month", async () => {
    draw();
    await screen.findByRole("checkbox", { name: "Channel: Email" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Channel: Email" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Month: Aug 2026" }));
    await waitFor(() => expect(JSON.parse(screen.getByTestId("narrowing").textContent ?? "[]")).toEqual([
      { table: "orders", column: "channel", values: ["Email"] },
      { table: "orders", column: "ordered_on", values: ["2026-08"], grain: "month" },
    ]));
    fireEvent.click(screen.getByTestId("query-filters-clear"));
    await waitFor(() => expect(screen.getByTestId("narrowing")).toHaveTextContent("[]"));
  });

  it("counts a column's values under the other filters, not its own", async () => {
    draw();
    await screen.findByRole("checkbox", { name: "Channel: Email" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Channel: Email" }));
    await waitFor(() => {
      const months = api.previewDashboardQuery.mock.calls.filter(c => c[1].sql.includes("strftime")).at(-1);
      expect(months?.[1].filters).toEqual([{ table: "orders", column: "channel", values: ["Email"] }]);
    });
    const channels = api.previewDashboardQuery.mock.calls.filter(c => c[1].sql.includes('"channel" AS value')).at(-1);
    expect(channels?.[1].filters).toEqual([]);
  });

  it("knows which cards read the table", () => {
    expect(readsTable("SELECT SUM(x) FROM orders", "orders")).toBe(true);
    expect(readsTable('SELECT SUM(x) FROM "ORDERS"', "orders")).toBe(true);
    expect(readsTable("SELECT SUM(x) FROM orders_old", "orders")).toBe(false);
    expect(readsTable("SELECT 1", null)).toBe(false);
  });
});
