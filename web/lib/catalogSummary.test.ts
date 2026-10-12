/**
 * The Catalog's fold, held on the shapes the live API returns (theLook, the BigQuery connection that lists the same
 * dataset, the Workspace's uploads with no row counts, a DuckDB file). Every guard here was broken once by hand and
 * seen to fail a test below — the duplicate rule most of all, since a wrong "listed twice" tells a person to doubt
 * a connection that is fine.
 */
import { describe, expect, it } from "vitest";

import type {
  CatalogEntry, DatasetSchema, DatasetTable, DatasetsView, KnowledgeStatus, Maturity, Metric, OntologyEntity,
  OntologyGraph, OntologyRelationship,
} from "./api";
import {
  approvedMetrics, catalogItems, catalogRows, columnMarks, columnRows, duplicateWords, explored, findDuplicates,
  findingsAbout, findingsIn, homeFigures, itemKey, largestTables, lifecycleOf, metricsReading, objectWords, ofCount,
  scopeState, scopeSummary, tableState, unsearchable, watchedWord,
} from "./catalogSummary";

// ── Fixtures, in the live shapes ──────────────────────────────────────────────────────────────────────────────────

const THELOOK_TABLES = [
  ["distribution_centers", 10], ["events", 2426096], ["inventory_items", 489869], ["order_items", 181458],
  ["orders", 125303], ["products", 29120], ["users", 100000],
] as const;
const lookTables = () => THELOOK_TABLES.map(([name, row_count]) => ({ name, row_count: row_count as number | null }));

const entry = (conn_id: string, name: string, conn_type: string, schemas: CatalogEntry["schemas"], builtin = false): CatalogEntry =>
  ({ conn_id, name, conn_type, builtin, schemas });

const theLook = () => entry("8233e4fd", "theLook", "bigquery", [{ name: "thelook", tables: lookTables() }]);
const bigQuery = () => entry("04465387", "BigQuery", "bigquery", [{ name: "thelook", tables: lookTables() }]);
const workspace = () => entry("workspace", "Workspace", "local_upload", [
  { name: "main", tables: [{ name: "airports", row_count: null }, { name: "flights", row_count: null }] },
  { name: "uber_ncr", tables: [{ name: "ncr_ride_bookings", row_count: null }] },
], true);
const duckdb = () => entry("baef6c3e", "DuckDB", "duckdb", [{ name: "main", tables: [{ name: "superstore", row_count: 9994 }] }]);
const ops = () => entry("aughor_ops", "Aughor Ops", "aughor_ops", [], true);

const bar = (share: number | null, note: string) => ({ share, note });
const maturity = (over: Partial<Maturity> = {}): Maturity => ({
  structure: bar(1, "structure learned"), questions: bar(1, "7 of 7 questions asked"),
  time: bar(1, "2 of 2 metrics dated · newest day read"), percent: 100, stage: "watching", ...over,
});
const dtable = (name: string, m: Maturity, off: DatasetTable["off"] = null): DatasetTable =>
  ({ name, layer: { set: null, proposed: null, effective: "business" }, off, maturity: m, copies: [] });

const learnedOnly = maturity({ questions: bar(null, "no question on its own"), stage: "learning" });

function lookSchema(over: Partial<DatasetSchema> = {}): DatasetSchema {
  return {
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
    tables: [
      dtable("distribution_centers", maturity({ questions: bar(null, "no question on its own"), time: bar(null, "no approved metric reads it"), stage: "learning" })),
      dtable("events", maturity()), dtable("inventory_items", maturity({ questions: bar(1, "18 of 18 questions asked") })),
      dtable("order_items", maturity()), dtable("orders", learnedOnly),
      dtable("products", maturity()), dtable("users", maturity()),
    ],
    ...over,
  };
}

const view = (connection_id: string, schemas: DatasetSchema[], spent = false): DatasetsView => ({
  connection_id, schemas, layers: [], exclusion_reasons: [],
  budget: { organisation: { limit: null, spent: null }, connection: { limit: null, spent: 0 }, remaining: null,
    held_by: null, spent_out: spent, sentence: spent ? "this month's budget is spent" : "no budget is set" },
});

const bqSchema = (): DatasetSchema => ({
  ...lookSchema(), key: "04465387", layer: { set: null, proposed: { layer: "business", label: "Business", evidence: [] },
    effective: "", policy: "", jobs: [] },
  maturity: maturity({ structure: bar(0, "not explored yet"), questions: bar(0, "its questions wait for its layer to be set"),
    time: bar(null, "no approved metrics to watch"), percent: 0, stage: "exploring" }),
  program: { held: null, reopened: null, last_run: null, watch: {}, failures: 0 },
});

const metric = (name: string, tables: string[], status = "approved", home_schema = "*"): Metric =>
  ({ name, label: name, tables, status, home_schema } as unknown as Metric);

const LOOK_METRICS = [
  metric("revenue", ["order_items"]), metric("units_sold", ["inventory_items"]),
  metric("gross_margin_rate", ["inventory_items", "order_items", "products"], "deprecated"),
  metric("repeat_purchase_rate", ["orders", "users"]), metric("dau", ["bigquery-public-data.thelook_ecommerce.events"]),
  metric("average_delivery_time", ["orders"], "proposed"),
];

const ORDER: OntologyEntity = {
  id: "Order", display_name: "Order", description: "", source_tables: ["orders"], identity_key: "order_id",
  grain_verified: true, domain: null, entity_type: "business_object", has_lifecycle: true, lifecycle_column: "status",
  lifecycle_states: ["Shipped", "Complete", "Processing", "Cancelled", "Returned"],
  terminal_states: ["Complete", "Cancelled", "Returned"], active_filter: null, segments: {}, created_at_col: "created_at",
  default_filters: [], exclude_when: [],
  properties: {
    order_id: { name: "order_id", description: "Unique identifier for each order", is_primary_key: true, semantic_type: "key", data_type: "INT64" },
    user_id: { name: "user_id", description: "Identifier for the customer who placed the order", is_primary_key: false, semantic_type: "key", data_type: "INT64" },
    status: { name: "status", description: "Current status of the order", is_primary_key: false, semantic_type: "dimension", data_type: "STRING" },
    created_at: { name: "created_at", description: "Timestamp when the order was created", is_primary_key: false, semantic_type: "timestamp", data_type: "TIMESTAMP" },
  } as unknown as OntologyEntity["properties"],
  computed_properties: [], implements: [],
} as unknown as OntologyEntity;

const ent = (id: string, display: string, table: string): OntologyEntity =>
  ({ ...ORDER, id, display_name: display, source_tables: [table], has_lifecycle: false, lifecycle_column: null,
    lifecycle_states: [], terminal_states: [], properties: {} } as OntologyEntity);

const LINK: OntologyRelationship = {
  id: "Order_placed_by_User", from_entity: "Order", to_entity: "User", verb: "placed_by", cardinality: "N:1", join_sql: "",
  from_table: "orders", from_col: "user_id", to_table: "users", to_col: "id", join_confidence: "exact", nullable: false,
};

const graph = (schema_name: string, entities: OntologyEntity[]): OntologyGraph => ({
  connection_id: "8233e4fd", schema_name, schema_fingerprint: "", generated_at: "", enriched: true,
  entities: Object.fromEntries(entities.map(e => [e.id, e])), relationships: { [LINK.id]: LINK }, metrics: {},
  actions: {}, interfaces: {},
});

const LOOK_GRAPH = graph("thelook", [
  ORDER, ent("InventoryItem", "Inventory Item", "inventory_items"), ent("OrderItem", "Order Line", "order_items"),
  ent("Event", "User Event", "events"), ent("User", "Customer", "users"), ent("Product", "Product", "products"),
  ent("DistributionCenter", "Distribution Center", "distribution_centers"), ent("Case", "Case", ""),
]);

// ── Words ─────────────────────────────────────────────────────────────────────────────────────────────────────────

describe("words", () => {
  it("names a business object as a reader writes it", () => {
    expect(objectWords("InventoryItem")).toBe("Inventory item");
    expect(objectWords("InventoryItem", "Inventory Item")).toBe("Inventory item");
    expect(objectWords("OrderItem", "Order Line")).toBe("Order line");
    expect(objectWords("order_item")).toBe("Order item");
    expect(objectWords("SKUCode")).toBe("SKU code");
    expect(objectWords("X", "SKU Code")).toBe("SKU code");
  });

  it("reads an 'n of m' count out of a reading's note, and nothing out of a note without one", () => {
    expect(ofCount("52 of 52 questions asked", "questions")).toEqual({ n: 52, of: 52 });
    expect(ofCount("7 of 93 questions asked — the rest wait", "questions")).toEqual({ n: 7, of: 93 });
    expect(ofCount("11 of 11 metrics dated · newest day read", "metrics dated")).toEqual({ n: 11, of: 11 });
    expect(ofCount("11 of 11 metrics dated", "questions")).toBeNull();
    expect(ofCount("no question on its own", "questions")).toBeNull();
    expect(ofCount(undefined)).toBeNull();
  });

  it("says how often a dataset is watched from the grains its program reads", () => {
    expect(watchedWord([lookSchema()])).toBe("watched daily");
    expect(watchedWord([bqSchema()])).toBe("watched");
  });
});

// ── States and explored ───────────────────────────────────────────────────────────────────────────────────────────

describe("a table's and a scope's state", () => {
  const s = lookSchema();
  it("is watched, exploring, learned or learning — or off, or not read", () => {
    expect(tableState(s.tables[1], s)).toEqual({ word: "watched daily", tone: "up", mark: "✓" });
    expect(tableState(s.tables[4], s)).toEqual({ word: "learned", tone: "muted", mark: "●" });
    expect(tableState(dtable("x", maturity({ structure: bar(0.333, "partly"), stage: "learning" })), s).word).toBe("learning");
    expect(tableState(dtable("x", maturity({ stage: "exploring" })), s).word).toBe("exploring");
    expect(tableState(dtable("x", maturity(), { table: "x", reason: "sensitive", note: "", declared_by: "amit" }), s).word).toBe("off");
    expect(tableState(s.tables[1], { ...s, off: { table: "*", reason: "other", note: "", declared_by: "" } }).word).toBe("off");
    expect(tableState(undefined, s).word).toBe("not read");
  });

  it("folds a scope's schemas: watched only when every schema that is on is watched", () => {
    expect(scopeState([lookSchema()]).word).toBe("watched daily");
    expect(scopeState([lookSchema(), bqSchema()]).word).toBe("exploring");
    expect(scopeState([]).word).toBe("nothing to read");
    expect(scopeState([{ ...lookSchema(), off: { table: "*", reason: "other", note: "", declared_by: "" } }]).word).toBe("turned off");
    expect(scopeState([{ ...bqSchema(), maturity: maturity({ structure: bar(0.333, "partly"), percent: null, stage: "learning" }) }]).word)
      .toBe("learning");
  });

  it("weights each schema's number by its tables, and says 'not given' rather than 0 when none has one", () => {
    const main = { ...bqSchema(), name: "main", maturity: maturity({ percent: 54, stage: "exploring" }), tables: Array(23).fill(dtable("t", maturity())) };
    const uber = { ...bqSchema(), name: "uber_ncr", maturity: maturity({ percent: 51, stage: "exploring" }), tables: [dtable("t", maturity())] };
    expect(explored([main, uber])).toEqual({ percent: 54, given: 2, of: 2 });
    expect(explored([{ ...main, maturity: maturity({ percent: null, stage: "learning" }) }])).toEqual({ percent: null, given: 0, of: 1 });
    expect(explored([main, { ...uber, maturity: maturity({ percent: null }) }])).toEqual({ percent: 54, given: 1, of: 2 });
  });
});

// ── Listed twice ──────────────────────────────────────────────────────────────────────────────────────────────────

describe("listed twice", () => {
  it("finds two connections of one type listing the same tables with the same row counts — the less explored is the copy", () => {
    const pct: Record<string, number> = { "8233e4fd": 100, "04465387": 0 };
    const dups = findDuplicates([workspace(), bigQuery(), theLook(), duckdb()], id => pct[id]);
    expect(dups).toHaveLength(1);
    expect(dups[0].copy).toEqual({ id: "04465387", name: "BigQuery", schemas: ["thelook"] });
    expect(dups[0].of).toEqual({ id: "8233e4fd", name: "theLook", schemas: ["thelook"] });
    expect(dups[0].tables).toBe(7);
    expect(duplicateWords(dups[0])).toBe("BigQuery lists the same 7 tables as theLook, with the same row counts");
  });

  it("with neither explored number read, keeps the first in the tree as the one counted", () => {
    expect(findDuplicates([bigQuery(), theLook()])[0].copy.id).toBe("8233e4fd");
    expect(findDuplicates([theLook(), bigQuery()])[0].copy.id).toBe("04465387");
  });

  it("says nothing when one row count differs, a count is unknown, or the listings hold nothing", () => {
    const off = bigQuery();
    off.schemas[0].tables[1] = { name: "events", row_count: 2426097 };
    expect(findDuplicates([theLook(), off])).toEqual([]);

    const unknown = bigQuery();
    unknown.schemas[0].tables[0] = { name: "distribution_centers", row_count: null };
    const lookUnknown = theLook();
    lookUnknown.schemas[0].tables[0] = { name: "distribution_centers", row_count: null };
    expect(findDuplicates([lookUnknown, unknown])).toEqual([]);

    const empty = (id: string) => entry(id, id, "postgres", [{ name: "public", tables: [{ name: "migrations", row_count: 0 }] }]);
    expect(findDuplicates([empty("a"), empty("b")])).toEqual([]);

    const uploads = (id: string) => entry(id, id, "local_upload", [{ name: "main", tables: [{ name: "airports", row_count: null }] }]);
    expect(findDuplicates([uploads("a"), uploads("b")])).toEqual([]);
  });

  it("never pairs two connections of different types, nor two schemas of one connection", () => {
    const pg = entry("pg", "Postgres", "postgres", [{ name: "thelook", tables: lookTables() }]);
    expect(findDuplicates([theLook(), pg])).toEqual([]);
    const twoSchemas = entry("x", "X", "bigquery", [{ name: "a", tables: lookTables() }, { name: "b", tables: lookTables() }]);
    expect(findDuplicates([twoSchemas])).toEqual([]);
  });
});

// ── Every catalog ─────────────────────────────────────────────────────────────────────────────────────────────────

describe("every catalog", () => {
  const entries = [workspace(), ops(), duckdb(), bigQuery(), theLook()];
  const pct: Record<string, number> = { "8233e4fd": 100, "04465387": 0 };
  const dups = findDuplicates(entries, id => pct[id]);
  const views = {
    workspace: view("workspace", [{ ...bqSchema(), name: "main", maturity: maturity({ percent: 54, stage: "exploring" }) }]),
    aughor_ops: view("aughor_ops", []),
    baef6c3e: view("baef6c3e", [{ ...bqSchema(), name: "main", maturity: maturity({ structure: bar(0.333, "partly"), percent: null, stage: "learning" }),
      tables: [dtable("superstore", maturity(), { table: "superstore", reason: "sensitive", note: "", declared_by: "amit" })] }]),
    "04465387": view("04465387", [bqSchema()]),
    "8233e4fd": view("8233e4fd", [lookSchema()]),
  };

  it("counts each table once, and the listing a second connection repeats beside it", () => {
    const f = homeFigures(entries, dups, views);
    expect(f.catalogs).toEqual(["Workspace", "Aughor Ops", "DuckDB", "BigQuery", "theLook"]);
    expect(f.tables).toBe(3 + 1 + 7);
    expect(f.twice).toBe(7);
    expect(f.rows).toBe(THELOOK_TABLES.reduce((a, [, n]) => a + n, 0) + 9994);
    expect(f.counted).toBe(8);
    expect(f.uncounted).toBe(3);
    expect(f.off).toEqual({ schemas: 0, tables: 1, read: 5, failed: 0, of: 5 });
  });

  it("says a read that failed, and no rows as unknown rather than 0", () => {
    const f = homeFigures([workspace()], [], { workspace: null });
    expect(f.rows).toBeNull();
    expect(f.off.failed).toBe(1);
    expect(homeFigures([workspace()], [], {}).off.read).toBe(0);
  });

  it("gives each catalog what it is, its size, how far it is explored and its state", () => {
    const rows = catalogRows(entries, dups, views, t => (t === "bigquery" ? "BigQuery" : t === "duckdb" ? "DuckDB" : t));
    const by = Object.fromEntries(rows.map(r => [r.id, r]));
    expect(by.workspace.what).toBe("uploaded files · 2 schemas");
    expect(by.workspace.rows).toBeNull();
    expect(by.workspace.uncounted).toBe(3);
    expect(by.workspace.explored).toEqual({ percent: 54, given: 1, of: 1 });
    expect(by.aughor_ops.what).toBe("the platform itself");
    expect(by.aughor_ops.state.word).toBe("nothing to read");
    expect(by.baef6c3e.what).toBe("DuckDB · main");
    expect(by.baef6c3e.explored).toEqual({ percent: null, given: 0, of: 1 });
    expect(by["04465387"].what).toBe("the same tables as theLook");
    expect(by["04465387"].state).toEqual({ word: "listed twice", tone: "amber", mark: "" });
    expect(by["04465387"].copyOf).toEqual({ id: "8233e4fd", name: "theLook" });
    expect(by["8233e4fd"].state.word).toBe("watched daily");
    expect(by["8233e4fd"].rows).toBe(3351856);

    const pending = catalogRows([theLook()], [], { "8233e4fd": undefined }, t => t)[0];
    expect(pending.explored).toBe("reading");
    expect(pending.state.word).toBe("reading…");
    const failed = catalogRows([theLook()], [], { "8233e4fd": null }, t => t)[0];
    expect(failed.explored).toBe("failed");
    expect(failed.state.word).toBe("not read");
  });

  it("lists the largest counted tables, each once, largest first", () => {
    const top = largestTables(entries, dups, 3);
    expect(top.map(t => `${t.catalog}.${t.name}`)).toEqual(["theLook.events", "theLook.inventory_items", "theLook.order_items"]);
    const all = largestTables(entries, dups, 50);
    expect(all.filter(t => t.catalog === "BigQuery")).toEqual([]);
    expect(all.some(t => t.catalog === "Workspace")).toBe(false);
    expect(all.map(t => t.name)).toContain("superstore");
  });
});

// ── Documents the search cannot reach ────────────────────────────────────────────────────────────────────────────

describe("documents the search cannot reach", () => {
  const status = (mismatched: KnowledgeStatus["consistency"]["mismatched_documents"]) =>
    ({ consistency: { mismatched_documents: mismatched } } as unknown as KnowledgeStatus);

  it("groups the registered parts the index lacks by the connection a schema document belongs to", () => {
    const got = unsearchable(status({
      "doctree::baef6c3e::ecommerce": { registry: 9, store: 0 },
      "doctree::baef6c3e::main": { registry: 1, store: 0 },
      "doctree::8233e4fd::thelook": { registry: 7, store: 9 },
      "policy.pdf": { registry: 4, store: 1 },
    }));
    expect(got).toEqual([
      { connId: "baef6c3e", schemas: ["ecommerce", "main"], documents: 2, missing: 10, claimed: 10 },
      { connId: null, schemas: [], documents: 1, missing: 3, claimed: 4 },
    ]);
  });

  it("is empty for a status that was not read", () => {
    expect(unsearchable(null)).toEqual([]);
  });
});

// ── One catalog, one schema ───────────────────────────────────────────────────────────────────────────────────────

describe("one catalog", () => {
  it("keeps the approved metrics, of one schema when asked", () => {
    const ms = [...LOOK_METRICS, metric("other", ["fact_gl"], "approved", "gold_finance")];
    expect(approvedMetrics(ms).map(m => m.name)).toEqual(["revenue", "units_sold", "repeat_purchase_rate", "dau", "other"]);
    expect(approvedMetrics(ms, "thelook").map(m => m.name)).toEqual(["revenue", "units_sold", "repeat_purchase_rate", "dau"]);
    expect(metricsReading(approvedMetrics(LOOK_METRICS), "events")).toBe(1);
    expect(metricsReading(approvedMetrics(LOOK_METRICS), "products")).toBe(0);
  });

  const look = scopeSummary({
    entry: theLook(), view: view("8233e4fd", [lookSchema()]), metrics: LOOK_METRICS, ontology: [LOOK_GRAPH],
  });

  it("says its tables by rows, each with its business object, questions, metrics and state", () => {
    expect(look.tables.map(t => t.name)).toEqual(["events", "inventory_items", "order_items", "orders", "users", "products", "distribution_centers"]);
    const orders = look.tables.find(t => t.name === "orders")!;
    expect(orders.object).toEqual({ id: "Order", words: "Order" });
    expect(orders.questions).toBeNull();
    expect(orders.questionsNote).toBe("no question on its own");
    expect(orders.metrics).toBe(1);
    expect(orders.state.word).toBe("learned");
    const items = look.tables.find(t => t.name === "inventory_items")!;
    expect(items.object?.words).toBe("Inventory item");
    expect(items.questions).toEqual({ n: 18, of: 18 });
    expect(look.stages).toBe("5 watched daily · 2 learned");
    expect(look.rows).toBe(3351856);
    expect(look.uncounted).toBe(0);
    expect(look.metrics).toBe(4);
  });

  it("says when it last ran, what it found and the newest day it read", () => {
    expect(look.lastRun).toEqual({ at: "2026-10-08T23:17:32+00:00", newFindings: 12, outcome: "complete", failures: 0 });
    expect(look.newest).toEqual({ through: "2026-09-13", readAt: "2026-10-12T01:32:17+00:00", grain: "day" });
    expect(look.state.word).toBe("watched daily");
    expect(look.explored).toEqual({ percent: 100, given: 1, of: 1 });
  });

  it("says what the platform knows as shares of the whole", () => {
    const k = Object.fromEntries(look.knows.map(x => [x.key, x]));
    expect([k.structure.n, k.structure.of]).toEqual([7, 7]);
    expect([k.questions.n, k.questions.of]).toEqual([52, 52]);
    expect([k.metrics.n, k.metrics.of]).toEqual([11, 11]);
    expect([k.objects.n, k.objects.of]).toEqual([7, 7]);
  });

  it("draws a reading with no count by its own share, and says the rest in a word", () => {
    const copy = scopeSummary({ entry: bigQuery(), view: view("04465387", [bqSchema()]), metrics: [], ontology: null });
    const k = Object.fromEntries(copy.knows.map(x => [x.key, x]));
    expect(k.structure).toMatchObject({ n: 7, of: 7, share: 1, short: "" });
    expect(k.questions).toMatchObject({ n: null, share: 0, short: "0%", note: "its questions wait for its layer to be set" });
    expect(k.metrics).toMatchObject({ n: null, share: null, short: "no metric" });
    expect(k.objects).toMatchObject({ share: null, short: "not built" });
    const look = scopeSummary({ entry: theLook(), view: view("8233e4fd", [lookSchema()]), metrics: [], ontology: [LOOK_GRAPH] });
    expect(look.knows.every(x => x.share === 1 && x.short === "")).toBe(true);
  });

  it("finds a table's business object by its schema — or, with one graph read, by its name alone", () => {
    const named = (schema_name: string) => ({ ...LOOK_GRAPH, schema_name });
    const objects = (graphs: OntologyGraph[]) => scopeSummary({ entry: theLook(), view: null, metrics: null, ontology: graphs })
      .tables.find(t => t.name === "orders")!.object;
    expect(objects([named("thelook_ecommerce")])).toEqual({ id: "Order", words: "Order" });
    expect(objects([named("thelook_ecommerce"), named("other")])).toBeNull();
  });

  it("says unknown as unknown — no datasets, no metrics, no ontology", () => {
    const bare = scopeSummary({ entry: workspace(), view: null, metrics: null, ontology: null });
    expect(bare.rows).toBeNull();
    expect(bare.uncounted).toBe(3);
    expect(bare.metrics).toBeNull();
    expect(bare.tables.every(t => t.metrics === null && t.object === null)).toBe(true);
    expect(bare.state.word).toBe("not read");
    expect(bare.knows.every(x => x.n === null && x.of === null && x.note)).toBe(true);
    expect(bare.knows.find(x => x.key === "objects")!.note).toBe("the ontology is not built");
    const reading = scopeSummary({ entry: workspace(), view: undefined, metrics: undefined, ontology: undefined });
    expect(reading.tables[0].state.word).toBe("reading…");
    expect(reading.knows.find(x => x.key === "structure")!.note).toBe("reading…");
  });

  it("scopes to one schema, and names what waits for a person", () => {
    const pg = entry("pg", "PostgreSQL", "postgres", [
      { name: "gold_finance", tables: [{ name: "fact_gl_posting", row_count: 67860 }] },
      { name: "luxexperience", tables: [{ name: "orders", row_count: 145378 }] },
    ]);
    const fin = { ...bqSchema(), name: "gold_finance", tables: [dtable("fact_gl_posting", maturity({ stage: "exploring" }))] };
    const lux = { ...lookSchema(), name: "luxexperience", tables: [dtable("orders", maturity())] };
    const s = scopeSummary({ entry: pg, schema: "gold_finance", view: view("pg", [fin, lux], true), metrics: [], ontology: [] });
    expect(s.tables.map(t => t.name)).toEqual(["fact_gl_posting"]);
    expect(s.waiting).toEqual(["gold_finance"]);
    expect(s.budgetSpent).toBe("this month's budget is spent");
    expect(scopeSummary({ entry: pg, view: view("pg", [fin, lux]), metrics: [], ontology: [] }).tables).toHaveLength(2);
  });
});

// ── One table ─────────────────────────────────────────────────────────────────────────────────────────────────────

describe("one table", () => {
  const cols = [
    { name: "order_id", type: "INT64" }, { name: "user_id", type: "INT64" }, { name: "status", type: "STRING" },
    { name: "gender", type: "STRING", description: "from the schema" }, { name: "created_at", type: "TIMESTAMP" },
    { name: "shipped_at", type: "TIMESTAMP" }, { name: "num_of_item", type: "INT64" },
  ];
  const rows = columnRows(cols, ORDER, [LINK], "thelook.orders");

  it("marks each column — key, linked table, states, time — with what it means", () => {
    const by = Object.fromEntries(rows.map(r => [r.name, r]));
    expect(by.order_id).toMatchObject({ key: true, link: null, means: "Unique identifier for each order" });
    expect(by.user_id).toMatchObject({ key: false, link: "users" });
    expect(by.status).toMatchObject({ states: 5, time: false });
    expect(by.gender.means).toBe("from the schema");
    expect(by.created_at.time).toBe(true);
    expect(by.shipped_at.time).toBe(true);
    expect(by.num_of_item).toMatchObject({ key: false, link: null, states: null, time: false, means: "" });
    expect(columnMarks(rows)).toBe("1 key · 1 link · 2 times");
    expect(columnMarks(columnRows([{ name: "a", type: "STRING" }], null, [], "t"))).toBe("no key, link or time read");
  });

  it("draws the lifecycle's states, each that ends it marked — and none for an object without one", () => {
    const lc = lifecycleOf(ORDER)!;
    expect(lc.column).toBe("status");
    expect(lc.states.filter(s => s.ends).map(s => s.name)).toEqual(["Complete", "Cancelled", "Returned"]);
    expect(lc.ends).toBe(3);
    expect(lifecycleOf(ent("User", "Customer", "users"))).toBeNull();
    expect(lifecycleOf(null)).toBeNull();
  });

  it("finds the findings about a table by what each read, else by its business object", () => {
    const list = findingsIn({ findings: [
      { id: "a", finding: "x", signature: { tables: ["orders"] }, entities_involved: [] },
      { id: "b", finding: "y", signature: { tables: ["order_items", "products"] }, entities_involved: ["Order"] },
      { id: "c", finding: "z", entities_involved: ["Order"] },
      { id: "d", finding: "w", entities_involved: ["User"] },
    ] })!;
    expect(findingsAbout(list, "orders", "Order").map(f => f.id)).toEqual(["a", "c"]);
    expect(findingsAbout(list, "orders", null).map(f => f.id)).toEqual(["a"]);
    expect(findingsIn({})).toBeNull();
    expect(findingsIn(null)).toBeNull();
  });
});

describe("favorites and recents", () => {
  it("lists every catalog, schema and table under the keys they were always stored by", () => {
    const items = catalogItems({ sections: [{ id: "connections", label: "Catalogs", entries: [duckdb()] }] });
    expect(items.map(i => i.key)).toEqual(["baef6c3e::", "baef6c3e:main:", "baef6c3e:main:superstore"]);
    expect(items.map(i => i.key)).toEqual([itemKey.catalog("baef6c3e"), itemKey.schema("baef6c3e", "main"),
      itemKey.table("baef6c3e", "main", "superstore")]);
    expect(items[2]).toMatchObject({ type: "Table", path: "DuckDB.main", rows: 9994, schemaName: "main", tableName: "superstore" });
    expect(catalogItems(null)).toEqual([]);
  });
});
