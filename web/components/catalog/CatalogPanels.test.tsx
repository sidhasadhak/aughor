// @vitest-environment jsdom
/**
 * The Catalog's right panel, redone to CLARITY.md from the approved mockup: every catalog (four figures, Needs you,
 * the catalogs beside the largest tables), one catalog (its figures, rows by table beside what the platform knows,
 * the tables) and one table (its figures, the lifecycle beside its columns). Held on theLook's shapes, with the
 * BigQuery connection that lists the same seven tables — said as exactly that, with Compare and no destructive door.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  CatalogEntry, CatalogTree, DatasetSchema, DatasetsView, KnowledgeStatus, Maturity, Metric, OntologyEntity, OntologyGraph,
} from "@/lib/api";
import { findDuplicates } from "@/lib/catalogSummary";

// ── Fixtures ──────────────────────────────────────────────────────────────────────────────────────────────────────

const LOOK = [
  ["distribution_centers", 10], ["events", 2426096], ["inventory_items", 489869], ["order_items", 181458],
  ["orders", 125303], ["products", 29120], ["users", 100000],
] as const;
const lookTables = () => LOOK.map(([name, row_count]) => ({ name, row_count: row_count as number | null }));
const entry = (conn_id: string, name: string, conn_type: string, schemas: CatalogEntry["schemas"], builtin = false): CatalogEntry =>
  ({ conn_id, name, conn_type, builtin, schemas });
const THELOOK = entry("8233e4fd", "theLook", "bigquery", [{ name: "thelook", tables: lookTables() }]);
const BIGQUERY = entry("04465387", "BigQuery", "bigquery", [{ name: "thelook", tables: lookTables() }]);
const WORKSPACE = entry("workspace", "Workspace", "local_upload", [
  { name: "main", tables: [{ name: "airports", row_count: null }, { name: "flights", row_count: null }] },
], true);
const DUCKDB = entry("baef6c3e", "DuckDB", "duckdb", [{ name: "main", tables: [{ name: "superstore", row_count: 9994 }] }]);
const TREE: CatalogTree = { sections: [{ id: "connections", label: "Catalogs", entries: [WORKSPACE, DUCKDB, BIGQUERY, THELOOK] }] };

const bar = (share: number | null, note: string) => ({ share, note });
const maturity = (over: Partial<Maturity> = {}): Maturity => ({
  structure: bar(1, "structure learned"), questions: bar(1, "7 of 7 questions asked"),
  time: bar(1, "2 of 2 metrics dated · newest day read"), percent: 100, stage: "watching", ...over,
});
const dtable = (name: string, m: Maturity) =>
  ({ name, layer: { set: null, proposed: null, effective: "business" }, off: null, maturity: m, copies: [] });
const learned = maturity({ questions: bar(null, "no question on its own"), time: bar(1, "1 of 1 metrics dated · newest day read"), stage: "learning" });

const lookSchema = (): DatasetSchema => ({
  name: "thelook", key: "8233e4fd",
  layer: { set: { layer: "business", set_by: "amit", set_at: "2026-10-08" },
    proposed: { layer: "business", label: "Business", evidence: [] }, effective: "business", policy: "", jobs: [] },
  off: null,
  maturity: maturity({ questions: bar(1, "52 of 52 questions asked"), time: bar(1, "11 of 11 metrics dated · newest day read") }),
  program: {
    held: null, reopened: null,
    last_run: { job: "questions", outcome: "complete", new_findings: 12, ended_at: "2026-10-08T23:17:32+00:00", reason: "" },
    watch: { day: { through: "2026-09-13", read_at: "2026-10-12T01:32:17+00:00", measured: 10, moved: [] } },
    failures: 0,
  },
  tables: LOOK.map(([name]) => dtable(name, name === "orders" || name === "distribution_centers" ? learned : maturity())),
});
const bqSchema = (): DatasetSchema => ({
  ...lookSchema(), key: "04465387",
  layer: { set: null, proposed: { layer: "business", label: "Business", evidence: [] }, effective: "", policy: "", jobs: [] },
  maturity: maturity({ structure: bar(0, "not explored yet"), questions: bar(0, "its questions wait for its layer to be set"),
    time: bar(null, "no approved metrics to watch"), percent: 0, stage: "exploring" }),
  program: { held: null, reopened: null, last_run: null, watch: {}, failures: 0 },
});
const view = (id: string, schemas: DatasetSchema[]): DatasetsView => ({
  connection_id: id, schemas, layers: [], exclusion_reasons: [],
  budget: { organisation: { limit: null, spent: null }, connection: { limit: null, spent: 0 }, remaining: null,
    held_by: null, spent_out: false, sentence: "no budget is set" },
});
const VIEWS = {
  workspace: view("workspace", [{ ...bqSchema(), name: "main", maturity: maturity({ percent: 54, stage: "exploring" }) }]),
  baef6c3e: view("baef6c3e", [{ ...bqSchema(), name: "main", maturity: maturity({ structure: bar(0.333, "partly"), percent: null, stage: "learning" }) }]),
  "04465387": view("04465387", [bqSchema()]),
  "8233e4fd": view("8233e4fd", [lookSchema()]),
};
const PCT: Record<string, number> = { "8233e4fd": 100, "04465387": 0 };
const DUPS = findDuplicates(TREE.sections[0].entries, id => PCT[id]);

const metric = (name: string, tables: string[], status = "approved"): Metric =>
  ({ name, label: name, tables, status, home_schema: "*" } as unknown as Metric);
const METRICS = [metric("revenue", ["order_items"]), metric("repeat_purchase_rate", ["orders", "users"]),
  metric("average_delivery_time", ["orders"], "proposed")];

const ORDER = {
  id: "Order", display_name: "Order", source_tables: ["orders"], identity_key: "order_id", lifecycle_column: "status",
  lifecycle_states: ["Shipped", "Complete", "Processing", "Cancelled", "Returned"],
  terminal_states: ["Complete", "Cancelled", "Returned"],
  properties: {
    order_id: { name: "order_id", description: "Unique identifier for each order", is_primary_key: true, semantic_type: "key" },
    user_id: { name: "user_id", description: "The customer who placed the order", is_primary_key: false, semantic_type: "key" },
    status: { name: "status", description: "Current status of the order", is_primary_key: false, semantic_type: "dimension" },
    created_at: { name: "created_at", description: "When the order was created", is_primary_key: false, semantic_type: "timestamp" },
  },
} as unknown as OntologyEntity;
const ITEMS = { ...ORDER, id: "InventoryItem", display_name: "Inventory Item", source_tables: ["inventory_items"],
  lifecycle_column: null, lifecycle_states: [], terminal_states: [], properties: {} } as unknown as OntologyEntity;
const GRAPH = {
  connection_id: "8233e4fd", schema_name: "thelook", entities: { Order: ORDER, InventoryItem: ITEMS },
  relationships: { r: { id: "r", from_table: "orders", from_col: "user_id", to_table: "users", to_col: "id" } },
} as unknown as OntologyGraph;

const STATUS = {
  consistency: { mismatched_documents: {
    "doctree::baef6c3e::ecommerce": { registry: 9, store: 0 }, "doctree::baef6c3e::main": { registry: 1, store: 0 },
  } },
} as unknown as KnowledgeStatus;

const api = vi.hoisted(() => ({
  getMetrics: vi.fn(),
  getOntology: vi.fn(),
  getTableColumns: vi.fn(),
  getExplorationFindings: vi.fn(),
  deleteConnectionTable: vi.fn(async () => undefined),
  listDocuments: vi.fn(async () => []),
  getConnectionSettings: vi.fn(async () => ({ ontology_refresh_hours: null })),
}));
vi.mock("@/lib/api", async importOriginal => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));
vi.mock("@/lib/schema-context", () => ({
  useRichSchema: () => ({ schema: null, loading: false, error: null, refresh: () => {} }),
  richSchemaKey: (id: string) => ["schema-rich", id],
}));

import { CatalogHome } from "./CatalogHome";
import { CatalogScope } from "./CatalogScope";
import { CatalogTable } from "./CatalogTable";

afterEach(() => { vi.clearAllMocks(); });

const label = (t: string) => ({ bigquery: "BigQuery", duckdb: "DuckDB" } as Record<string, string>)[t] ?? t;
const wrap = (ui: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient()}><Theme>{ui}</Theme></QueryClientProvider>);

// ── Every catalog ─────────────────────────────────────────────────────────────────────────────────────────────────

describe("the Catalog with nothing chosen", () => {
  const home = (onOpenCatalog = vi.fn()) => {
    wrap(<CatalogHome tree={TREE} treeError={null} onRetryTree={vi.fn()} views={VIEWS} dups={DUPS} status={STATUS} label={label}
      onOpenCatalog={onOpenCatalog} onRetryViews={vi.fn()} onPick={vi.fn()} />);
    return onOpenCatalog;
  };

  it("leads with four figures — each table once, and the tables listed twice beside them", () => {
    home();
    expect(screen.getByTestId("fig-catalogs-value")).toHaveTextContent("4");
    expect(screen.getByTestId("fig-tables-value")).toHaveTextContent("10");
    expect(screen.getByTestId("fig-tables-twice")).toHaveTextContent("+7 listed twice");
    expect(screen.getByTestId("fig-rows")).toHaveTextContent("in 8 tables · 2 not counted");
    expect(screen.getByTestId("fig-off")).toHaveTextContent("no schema or table set aside");
  });

  it("says what is visible about a repeated listing, offers Compare and nothing destructive", async () => {
    const open = home();
    const needs = screen.getByTestId("catalog-home-needs");
    const row = within(needs).getByTestId("needs-listed-twice");
    expect(row).toHaveTextContent("BigQuery lists the same 7 tables as theLook, with the same row counts");
    expect(within(needs).queryByText(/keep .* only/i)).toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: "Compare" }));
    expect(open).toHaveBeenCalledWith("04465387");
    expect(await within(needs).findByTestId("needs-unsearchable")).toHaveTextContent("2 DuckDB documents can't be searched");
  });

  it("lists each catalog with what it is, its rows (never 0 for uncounted) and how far it is explored", () => {
    home();
    const rows = screen.getAllByTestId("catalog-home-row");
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("uploaded files · main");
    expect(rows[0]).toHaveTextContent("not counted");
    expect(rows[0]).toHaveTextContent("54%");
    expect(rows[1]).toHaveTextContent("not given");
    expect(rows[2]).toHaveTextContent("the same tables as theLook");
    expect(rows[2]).toHaveTextContent("listed twice");
    expect(rows[3]).toHaveTextContent("✓ watched daily");
    const largest = screen.getByTestId("catalog-home-largest");
    expect(within(largest).getAllByText("events")).toHaveLength(1);
  });

  it("keeps Favorites and Recent one tap away", () => {
    home();
    fireEvent.click(screen.getByRole("radio", { name: /Favorites/ }));
    expect(screen.getByTestId("catalog-favorites")).toHaveTextContent("No favorites yet");
  });
});

// ── One catalog ───────────────────────────────────────────────────────────────────────────────────────────────────

describe("one catalog", () => {
  const scope = (over: Partial<React.ComponentProps<typeof CatalogScope>> = {}) => {
    api.getMetrics.mockResolvedValue(METRICS);
    api.getOntology.mockResolvedValue(GRAPH);
    const props = {
      entry: THELOOK, view: VIEWS["8233e4fd"], dups: DUPS, label,
      status: { consistency: { mismatched_documents: {} } } as unknown as KnowledgeStatus,
      conn: { id: "8233e4fd", name: "theLook", conn_type: "bigquery", dsn_preview: "", schema_name: "thelook", builtin: false },
      onOpenTable: vi.fn(), onOpenSchema: vi.fn(), onOpenCatalog: vi.fn(), onProgramChanged: vi.fn(), onAsk: vi.fn(),
      onTest: vi.fn(), onDelete: vi.fn(), ...over,
    };
    wrap(<CatalogScope {...props} />);
    return props;
  };

  it("opens on its figures, the other listing under Needs you, and its tables with their business objects", async () => {
    const p = scope();
    expect(screen.getByTestId("catalog-scope-head")).toHaveTextContent("BigQuery · thelook");
    expect(screen.getByTestId("catalog-state-chip")).toHaveTextContent("✓ watched daily · 100%");
    expect(screen.getByTestId("fig-scope-tables")).toHaveTextContent("5 watched daily · 2 learned");
    expect(screen.getByTestId("fig-scope-explored")).toHaveTextContent("12 new findings · nothing failed");
    await waitFor(() => expect(screen.getByTestId("fig-scope-metrics-value")).toHaveTextContent("2"));
    const needs = screen.getByTestId("catalog-scope-needs");
    expect(needs).toHaveTextContent("Its 7 tables are also listed under BigQuery");
    fireEvent.click(within(needs).getByRole("button", { name: "Compare" }));
    expect(p.onOpenCatalog).toHaveBeenCalledWith("04465387");
    const rows = await screen.findAllByTestId("catalog-table-row");
    expect(rows).toHaveLength(7);
    await waitFor(() => expect(rows.find(r => r.textContent?.includes("inventory_items"))).toHaveTextContent("Inventory item"));
    fireEvent.click(within(rows[0]).getByRole("button", { name: "events" }));
    expect(p.onOpenTable).toHaveBeenCalledWith("thelook", { name: "events", row_count: 2426096 });
  });

  it("offers the Diagram as a tab — on a one-schema connection and at schema scope — not as a tool", async () => {
    // 2026-10-14: #610 had moved the schema's ERD into Tools ▾, and the user read it as removed.
    scope();
    expect(screen.getByRole("tab", { name: "Diagram" })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByTestId("catalog-tools"), { key: "Enter" });
    expect(screen.queryByRole("menuitem", { name: "Diagram" })).toBeNull();
    fireEvent.keyDown(screen.getByTestId("catalog-tools"), { key: "Escape" });
    cleanup();
    scope({ schema: THELOOK.schemas[0] });
    expect(screen.getByRole("tab", { name: "Diagram" })).toBeInTheDocument();
    cleanup();
    scope({ entry: entry("two", "Two", "postgres", [{ name: "a", tables: [] }, { name: "b", tables: [] }]) });
    expect(screen.queryByRole("tab", { name: "Diagram" })).toBeNull();   // which schema? none chosen yet
  });

  it("keeps every tool reachable behind Tools ▾ — removing the connection goes to its own confirmation", async () => {
    const p = scope();
    fireEvent.keyDown(screen.getByTestId("catalog-tools"), { key: "Enter" });
    const items = (await screen.findAllByRole("menuitem")).map(i => i.textContent);
    expect(items).toEqual(["Test connection", "Volumes", "Permissions", "Add to favorites", "Remove connection…"]);
    fireEvent.click(screen.getByRole("menuitem", { name: "Remove connection…" }));
    expect(p.onDelete).toHaveBeenCalled();
  });

  it("says a copy as a copy, and asks in words", async () => {
    const p = scope({ entry: BIGQUERY, view: VIEWS["04465387"] });
    expect(screen.getByTestId("catalog-scope-head")).toHaveTextContent("the same tables as theLook");
    expect(screen.getByTestId("catalog-scope-needs")).toHaveTextContent("BigQuery lists the same 7 tables as theLook");
    fireEvent.click(screen.getByRole("button", { name: "Ask about it" }));
    expect(p.onAsk).toHaveBeenCalledWith("Tell me about BigQuery");
  });

  it("shows no Needs you when nothing needs a person", () => {
    scope({ dups: [] });
    expect(screen.queryByTestId("catalog-scope-needs")).toBeNull();
  });
});

// ── One table ─────────────────────────────────────────────────────────────────────────────────────────────────────

describe("one table", () => {
  const table = () => {
    api.getMetrics.mockResolvedValue(METRICS);
    api.getOntology.mockResolvedValue(GRAPH);
    api.getTableColumns.mockResolvedValue([
      { name: "order_id", type: "INT64" }, { name: "user_id", type: "INT64" }, { name: "status", type: "STRING" },
      { name: "gender", type: "STRING" }, { name: "created_at", type: "TIMESTAMP" }, { name: "shipped_at", type: "TIMESTAMP" },
      { name: "num_of_item", type: "INT64" },
    ]);
    api.getExplorationFindings.mockResolvedValue({ distributions: {}, findings: [
      { id: "a", finding: "Shipped orders lead revenue", angle: "Revenue by status", signature: { tables: ["orders"] } },
      { id: "b", finding: "Men lead retail value", angle: "Retail value", signature: { tables: ["order_items"] } },
    ] });
    const onRemoved = vi.fn();
    wrap(<CatalogTable connId="8233e4fd" catalogName="theLook" schemaName="thelook" table={{ name: "orders", row_count: 125303 }}
      view={VIEWS["8233e4fd"]} onAsk={vi.fn()} onRemoved={onRemoved} onProgramChanged={vi.fn()} />);
    return onRemoved;
  };

  it("opens on its figures, its lifecycle's states without invented counts, and its columns' marks", async () => {
    table();
    expect(screen.getByTestId("catalog-table-head")).toHaveTextContent("theLook ›thelook ›orders");
    expect(screen.getByTestId("fig-table-rows")).toHaveTextContent("125,303 in all");
    expect(screen.getByTestId("fig-table-questions")).toHaveTextContent("none asked of it alone");
    await waitFor(() => expect(screen.getByTestId("fig-table-columns")).toHaveTextContent("1 key · 1 link · 2 times"));
    await waitFor(() => expect(screen.getByTestId("fig-table-metrics-value")).toHaveTextContent("1"));
    expect(await screen.findByTestId("catalog-table-object")).toHaveTextContent("Order");
    const lc = screen.getByTestId("catalog-table-lifecycle");
    await waitFor(() => expect(lc).toHaveTextContent("3 of 5 states end it"));
    expect(within(lc).getAllByText("ends")).toHaveLength(3);
    expect(lc).toHaveTextContent("How many sit in each state is not read here.");
    expect(lc.textContent).not.toMatch(/\d{2,}/);
    expect(screen.getByTestId("catalog-table-columns")).toHaveTextContent("→ users");
    expect(await screen.findByRole("tab", { name: "Findings · 1" })).toBeInTheDocument();
  });

  it("keeps the tools behind Tools ▾ — removing it asks first", async () => {
    const onRemoved = table();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.keyDown(screen.getByTestId("catalog-tools"), { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Remove table…" }));
    expect(confirm).toHaveBeenCalled();
    await waitFor(() => expect(api.deleteConnectionTable).toHaveBeenCalledWith("8233e4fd", "orders", "thelook"));
    await waitFor(() => expect(onRemoved).toHaveBeenCalled());
    confirm.mockRestore();
  });
});
