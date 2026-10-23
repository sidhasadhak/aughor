// @vitest-environment jsdom

/**
 * Your own query, set up in the builder (Arc AP-7). What is pinned: Run asks the server for the query and the setup and
 * says what came back — time, rows, typed columns — or each refusal as the server says it; Shown as starts a setup from
 * the columns the query returns; Keep sends the SQL, the setup and the card it replaces, and hands the kept card on.
 */
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuerySetup } from "@/components/dashboards/QuerySetup";
import type { DashboardCard, QueryPreview } from "@/lib/api";

const api = vi.hoisted(() => ({ previewDashboardQuery: vi.fn(), keepDashboardQuery: vi.fn(), getCatalogTree: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

const SQL = "SELECT DATE(o.created_at) AS day, u.country, SUM(oi.sale_price) AS sales FROM thelook.orders o GROUP BY 1, 2";
const COLUMNS = [{ name: "day", type: "DATE" }, { name: "country", type: "VARCHAR" }, { name: "sales", type: "DOUBLE" }];
const RAN: QueryPreview = {
  connection_id: "thelook", refused: [], columns: COLUMNS, more: true, duration_ms: 1089.8, tables: ["orders"],
  rows: [["2026-09-27", "United States", 4268.09], ["2026-09-27", "China", 4023.22]],
  setup: { as: "table", summed: true, x: "", bucket: "", series: [{ column: "", agg: "count" }], split: "", top: 5, segments: "stacked",
    running: false, labels: false, columns: [], sort: "", descending: true, label: "" },
};
const card = (extra: Partial<DashboardCard> = {}) => ({
  id: "q1", title: "Sales by day, by country", kind: "chart", own: true, connection_id: "thelook", scope: "user", scope_ref: "default",
  source: "authored", sql: SQL, thresholds: {}, provenance: {}, links: [],
  render: { shown: { as: "bar", summed: true, x: "day", bucket: "day", series: [{ column: "sales", agg: "sum" }], split: "country", top: 4,
    segments: "stacked", running: false, labels: true, columns: [], sort: "", descending: true, label: "" }, columns: COLUMNS },
  ...extra,
}) as unknown as DashboardCard;

beforeEach(() => {
  vi.clearAllMocks();
  api.previewDashboardQuery.mockResolvedValue(RAN);
  api.getCatalogTree.mockResolvedValue({ sections: [{ id: "connections", label: "Catalogs", entries: [
    { conn_id: "thelook", name: "theLook", conn_type: "bigquery", builtin: false,
      schemas: [{ name: "thelook", tables: [{ name: "orders", row_count: null }, { name: "users", row_count: null }] }] },
    { conn_id: "other", name: "Other", conn_type: "duckdb", builtin: false, schemas: [{ name: "x", tables: [{ name: "nope", row_count: null }] }] },
  ] }] });
});

describe("your own query, set up in the builder", () => {
  it("runs the SQL as written, and says how long it took, how many rows and which columns came back", async () => {
    render(<QuerySetup connectionId="thelook" onKept={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("SQL"), { target: { value: SQL } });
    fireEvent.click(screen.getByTestId("query-run"));
    const ran = await screen.findByTestId("query-ran");
    expect(api.previewDashboardQuery).toHaveBeenCalledWith("thelook", expect.objectContaining({ sql: SQL, shown: expect.objectContaining({ as: "table" }) }));
    expect(ran).toHaveTextContent("1.1 s · 2+ rows · day, country, sales");
    expect(within(ran).getAllByRole("row")).toHaveLength(3);                                 // the header and two rows
  });

  it("says each refusal as the server says it, and keeps nothing", async () => {
    api.previewDashboardQuery.mockResolvedValue({ connection_id: "thelook", refused: [
      "This query reads orders straight from its table, and Order has a row policy: a query cannot be narrowed to each reader. Read Order through a set instead."] });
    const onKept = vi.fn();
    render(<QuerySetup connectionId="thelook" onKept={onKept} />);
    fireEvent.change(screen.getByLabelText("SQL"), { target: { value: SQL } });
    fireEvent.click(screen.getByTestId("query-run"));
    expect(await screen.findByTestId("query-refused")).toHaveTextContent("Order has a row policy");
    expect(screen.queryByTestId("query-ran")).toBeNull();
    expect(onKept).not.toHaveBeenCalled();
  });

  it("starts a chart's setup from the columns the query returned: a date along the bottom by day, a number summed, words split", async () => {
    render(<QuerySetup connectionId="thelook" onKept={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("SQL"), { target: { value: SQL } });
    fireEvent.click(screen.getByTestId("query-run"));
    await screen.findByTestId("query-ran");
    fireEvent.click(screen.getByRole("radio", { name: /Bar/ }));
    expect(screen.getByLabelText("Along the bottom")).toHaveTextContent("day");
    expect(screen.getByLabelText("Calculation 1")).toHaveTextContent("Sum");
    expect(screen.getByLabelText("Of 1")).toHaveTextContent("sales");
    expect(screen.getByLabelText("Split by")).toHaveTextContent("country");
    expect(screen.getByRole("radiogroup", { name: "Buckets" })).toBeInTheDocument();
  });

  it("keeps a new query as a card of the person's own and hands it on", async () => {
    const kept = card({ id: "q9" });
    api.keepDashboardQuery.mockResolvedValue({ card: kept, preview: RAN });
    const onKept = vi.fn();
    render(<QuerySetup connectionId="thelook" onKept={onKept} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Sales by day" } });
    fireEvent.change(screen.getByLabelText("SQL"), { target: { value: SQL } });
    fireEvent.click(screen.getByTestId("query-keep"));
    await waitFor(() => expect(onKept).toHaveBeenCalledWith(kept, null));
    expect(api.keepDashboardQuery).toHaveBeenCalledWith("thelook", { sql: SQL, shown: expect.objectContaining({ as: "table" }), title: "Sales by day" });
  });

  it("keeps a change to a card as a new one replacing it, and says a refusal in its own words", async () => {
    const { QueryRefused } = await import("@/lib/api");
    api.keepDashboardQuery.mockRejectedValueOnce(new QueryRefused(["Along the bottom names “nowhere”, which this query does not return."]));
    const onKept = vi.fn();
    render(<QuerySetup connectionId="thelook" card={card()} onKept={onKept} />);
    expect(screen.getByTestId("query-keep")).toBeDisabled();                       // nothing changed yet
    fireEvent.click(screen.getByRole("radio", { name: /Line/ }));
    fireEvent.click(screen.getByTestId("query-keep"));
    expect(await screen.findByTestId("query-refused")).toHaveTextContent("names “nowhere”");
    expect(api.keepDashboardQuery).toHaveBeenCalledWith("thelook", expect.objectContaining({ replaces: "q1", shown: expect.objectContaining({ as: "line", x: "day" }) }));
    api.keepDashboardQuery.mockResolvedValueOnce({ card: card({ id: "q2" }), preview: RAN });
    fireEvent.click(screen.getByTestId("query-keep"));
    await waitFor(() => expect(onKept).toHaveBeenCalledWith(expect.objectContaining({ id: "q2" }), "q1"));
  });

  it("lists the connection's own tables by their schema, and puts one in the SQL where the cursor is", async () => {
    render(<QuerySetup connectionId="thelook" onKept={vi.fn()} />);
    fireEvent.click(screen.getByTestId("query-tables-open"));
    const list = await screen.findByTestId("query-tables");
    await waitFor(() => expect(within(list).getAllByRole("listitem").map(b => b.textContent)).toEqual(["thelook.orders", "thelook.users"]));
    fireEvent.click(within(list).getByText("thelook.users"));
    expect(screen.getByLabelText("SQL")).toHaveValue("thelook.users");
  });
});
