// @vitest-environment jsdom

/**
 * Arc ON leftovers — the two declaration doors the panel was missing.
 *
 * The panel could BIND what the builder proposed and REMOVE what a person set, and that was all. A
 * timeseries binding was never proposed then (many rows per object was what the proposal check rejected)
 * and a keyed SELECT never is, so both were API-only; and a link kept the builder's generic name because
 * no web door named one. These pin what the forms HAND the doors — the spec and the name — because
 * that is where the bug would live: a form that looks right and posts a static binding with no time
 * column is refused by the server, silently, one round trip later.
 */
import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { BackingPreview, ObjectTypeDetail } from "@/lib/objectTypes";

const addBinding = vi.fn(async (..._args: unknown[]) => undefined);
const deleteLink = vi.fn(async (..._args: unknown[]) => undefined);
const restoreLink = vi.fn(async (..._args: unknown[]) => undefined);
const nameLink = vi.fn(async (..._args: unknown[]) => undefined);
const declareLink = vi.fn(async (..._args: unknown[]) => undefined);
const declareProcess = vi.fn(async (..._args: unknown[]) => ({ id: "order_fulfilment" }));
const declareRule = vi.fn(async (..._args: unknown[]) => ({ id: "shipped_orders" }));
const confirmProposals = vi.fn(async (..._args: unknown[]) => ({ confirmed: [], refused: [] as { why: string }[] }));
const previewBacking = vi.fn(async (..._args: unknown[]): Promise<unknown> => undefined);
const setQueryBacking = vi.fn(async (..._args: unknown[]) => undefined);
const withdrawBacking = vi.fn(async (..._args: unknown[]) => undefined);
/** The type the panel reads — the fixture below, unless a test shows another. */
const shown: { detail?: ObjectTypeDetail } = {};

vi.mock("@/lib/objectTypes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/objectTypes")>()),
  getObjectType: async () => shown.detail ?? detail,
  addBinding: (...a: unknown[]) => addBinding(...a),
  nameLink: (...a: unknown[]) => nameLink(...a),
  declareLink: (...a: unknown[]) => declareLink(...a),
  declareProcess: (...a: unknown[]) => declareProcess(...a),
  declareRule: (...a: unknown[]) => declareRule(...a),
  confirmProposals: (...a: unknown[]) => confirmProposals(...a),
  previewBacking: (...a: unknown[]) => previewBacking(...a),
  setQueryBacking: (...a: unknown[]) => setQueryBacking(...a),
  withdrawBacking: (...a: unknown[]) => withdrawBacking(...a),
  deleteLink: (...a: unknown[]) => deleteLink(...a),
  restoreLink: (...a: unknown[]) => restoreLink(...a),
}));

import { EntityTypePanel } from "@/components/ontology/EntityTypePanel";

const detail: ObjectTypeDetail = {
  path: "object_type",
  connection_id: "c1",
  schema_name: "s",
  object_type: "product",
  id: "products",
  display_name: "Product",
  description: "",
  role: "entity",
  domain: "",
  key: { property: "product_id", verified: true, rows: 1000, note: "1,000 of 1,000 distinct" },
  display_property: { property: "product_name", source: "proposed", is_key: false, verified: true,
                      rows: 1000, non_null: 1000, distinct: 990, note: "" },
  time: "",
  properties: [
    { name: "product_id", display_name: "product_id", role: "identifier", data_type: "VARCHAR", unit: "",
      is_key: true, null_rate: 0, description: "", source: { binding: "products", table: "products", column: "product_id" } },
    { name: "product_name", display_name: "product_name", role: "text", data_type: "VARCHAR", unit: "",
      is_key: false, null_rate: 0, description: "", source: { binding: "products", table: "products", column: "product_name" } },
  ],
  properties_truncated: false,
  bindings: [{ name: "products", primary: true, kind: "static", reads: "table", table: "products",
               key: "product_id", object_key: "product_id", source: "backing", verified: true, rows: 1000,
               note: "", supplies: 2, usable: true }],
  proposed_bindings: [],
  links: [{ name: "product_to_order_item", business_name: "", business_name_source: "", verb: "relates to",
            relationship: "rel_product_order_item", direction: "out", to: "order_item", to_type: "order_item",
            to_name: "Order Line", cardinality: "1:N", measured: true, kind: "to-many",
            on: "product_id = product_id", traversable: true }],
  actions: [],
  metrics: [],
  unverified_metrics: [],
  segments: [],
  lifecycle: null,
  counts: { properties: 2, bindings: 1, proposed_bindings: 0, links: 1, traversable_links: 1, actions: 0, metrics: 0 },
  summary: "Product — 1,000 objects.",
};

const rows = [
  { object_type: "product", id: "products", display_name: "Product" },
  { object_type: "brand", id: "Brand", display_name: "Brand" },
].map((t) => ({ ...t, role: "business_object", domain: "", key: `${t.object_type}_id`, key_verified: true, rows: 1,
                table: t.object_type, display_property: "", display_is_key: true, properties: 1, bindings: 1,
                proposed_bindings: 0, links: 0, traversable_links: 0, actions: 0, metrics: 0 }));

function panel() {
  return render(
    <EntityTypePanel connectionId="c1" schema="s" objectType="product" types={rows} version={0}
      onOpen={() => {}} onChanged={() => {}} />);
}

describe("EntityTypePanel — declaring what the builder cannot propose", () => {
  beforeEach(() => {
    addBinding.mockClear();
    nameLink.mockClear();
  });

  it("declares a TIMESERIES binding with its time column — the kind no proposal ever offers", async () => {
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "Declare a binding" }));

    await user.type(screen.getByLabelText("Binding name"), "price_history");
    await user.type(screen.getByLabelText("Table"), "price_history");
    await user.selectOptions(screen.getByLabelText("Binding kind"), "timeseries");
    await user.type(screen.getByLabelText("Time column"), "observed_at");
    await user.click(screen.getByRole("button", { name: "Bind" }));

    await waitFor(() => expect(addBinding).toHaveBeenCalled());
    const [conn, entity, name, spec, schema] = addBinding.mock.calls[0];
    expect([conn, entity, name, schema]).toEqual(["c1", "products", "price_history", "s"]);
    // The key defaults to the type's own — the join is on the object's key, not on a column the person retypes.
    expect(spec).toEqual({ kind: "timeseries", key: "product_id", table: "price_history", time_column: "observed_at" });
  });

  it("will not bind a timeseries source with no time column, and sends a SELECT as `sql`", async () => {
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "Declare a binding" }));
    await user.type(screen.getByLabelText("Binding name"), "paid");
    await user.selectOptions(screen.getByLabelText("Source kind"), "query");
    await user.type(screen.getByLabelText("SELECT"), "SELECT product_id, SUM(paid) AS paid FROM p GROUP BY 1");
    await user.selectOptions(screen.getByLabelText("Binding kind"), "timeseries");

    // A timeseries with no time column cannot be reduced to a latest row: the form refuses before the round trip.
    expect(screen.getByRole("button", { name: "Bind" })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText("Binding kind"), "static");
    await user.click(screen.getByRole("button", { name: "Bind" }));
    await waitFor(() => expect(addBinding).toHaveBeenCalled());
    expect(addBinding.mock.calls[0][3]).toEqual({
      kind: "static", key: "product_id", sql: "SELECT product_id, SUM(paid) AS paid FROM p GROUP BY 1" });
  });

  it("names a link by its business verb, sending the RELATIONSHIP id rather than the link's own name", async () => {
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "Name it" }));
    const field = screen.getByLabelText("Business name for product_to_order_item");
    await user.type(field, "sold_as");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(nameLink).toHaveBeenCalled());
    expect(nameLink.mock.calls[0]).toEqual(["c1", "rel_product_order_item", "sold_as", "s"]);
  });
});

describe("EntityTypePanel — frames over a timeseries binding's readings", () => {
  beforeEach(() => addBinding.mockClear());

  it("declares the frames beside the binding, in the algebra the API takes", async () => {
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "Declare a binding" }));
    await user.type(screen.getByLabelText("Binding name"), "price_history");
    await user.type(screen.getByLabelText("Table"), "price_history");
    await user.selectOptions(screen.getByLabelText("Binding kind"), "timeseries");
    await user.type(screen.getByLabelText("Time column"), "observed_at");

    await user.click(screen.getByRole("button", { name: "+ Add a frame" }));
    await user.type(screen.getByLabelText("Frame 1 property"), "avg_price_3");
    await user.type(screen.getByLabelText("Frame 1 column"), "price");
    await user.clear(screen.getByLabelText("Frame 1 readings"));
    await user.type(screen.getByLabelText("Frame 1 readings"), "3");

    await user.click(screen.getByRole("button", { name: "+ Add a frame" }));
    await user.type(screen.getByLabelText("Frame 2 property"), "price_before");
    await user.selectOptions(screen.getByLabelText("Frame 2 shape"), "previous");
    await user.type(screen.getByLabelText("Frame 2 column"), "price");

    await user.click(screen.getByRole("button", { name: "Bind" }));
    await waitFor(() => expect(addBinding).toHaveBeenCalled());
    expect(addBinding.mock.calls[0][3]).toEqual({
      kind: "timeseries", key: "product_id", table: "price_history", time_column: "observed_at",
      frames: {
        // "the reading before" carries neither an aggregate nor a window: it is one row, not a span.
        avg_price_3: { column: "price", agg: "avg", range: "trailing", window: 3 },
        price_before: { column: "price", offset: 1 },
      },
    });
  });

  it("sends no frames on a static binding — a frame over one row is that row", async () => {
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "Declare a binding" }));
    await user.type(screen.getByLabelText("Binding name"), "flags");
    await user.type(screen.getByLabelText("Table"), "order_flags");

    expect(screen.queryByRole("button", { name: "+ Add a frame" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Bind" }));
    await waitFor(() => expect(addBinding).toHaveBeenCalled());
    expect(addBinding.mock.calls[0][3]).not.toHaveProperty("frames");
  });
});

describe("EntityTypePanel — ON-7: a part, and a link the builder did not find", () => {
  beforeEach(() => {
    addBinding.mockClear();
    declareLink.mockClear();
  });

  it("declares a DETAIL binding with its rollups, and folds the table's type in as a part", async () => {
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "Declare a binding" }));
    await user.type(screen.getByLabelText("Binding name"), "lines");
    await user.type(screen.getByLabelText("Table"), "order_items");
    await user.selectOptions(screen.getByLabelText("Binding kind"), "detail");

    // a detail binding with no rollup supplies nothing: the form refuses before the round trip
    expect(screen.getByRole("button", { name: "Bind" })).toBeDisabled();
    await user.type(screen.getByLabelText("Rollup 1 property"), "units");
    await user.type(screen.getByLabelText("Rollup 1 column"), "quantity");
    await user.click(screen.getByRole("button", { name: "+ Add a rollup" }));
    await user.type(screen.getByLabelText("Rollup 2 property"), "line_count");
    await user.selectOptions(screen.getByLabelText("Rollup 2 agg"), "count");
    await user.type(screen.getByLabelText("Rollup 2 column"), "item_id");
    expect(screen.getByLabelText("Absorb its type as a part")).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Bind" }));
    await waitFor(() => expect(addBinding).toHaveBeenCalled());
    expect(addBinding.mock.calls[0][3]).toEqual({
      kind: "detail", key: "product_id", table: "order_items",
      rollups: { units: { column: "quantity", agg: "sum" }, line_count: { column: "item_id", agg: "count" } },
      absorb: true,
    });
  });

  it("sends no absorb on a keyed SELECT — there is no table whose type could fold in", async () => {
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "Declare a binding" }));
    await user.type(screen.getByLabelText("Binding name"), "lines");
    await user.selectOptions(screen.getByLabelText("Source kind"), "query");
    await user.type(screen.getByLabelText("SELECT"), "SELECT product_id, quantity FROM order_items");
    await user.selectOptions(screen.getByLabelText("Binding kind"), "detail");
    expect(screen.queryByLabelText("Absorb its type as a part")).toBeNull();
    await user.type(screen.getByLabelText("Rollup 1 property"), "units");
    await user.type(screen.getByLabelText("Rollup 1 column"), "quantity");
    await user.click(screen.getByRole("button", { name: "Bind" }));
    await waitFor(() => expect(addBinding).toHaveBeenCalled());
    expect(addBinding.mock.calls[0][3]).toEqual({
      kind: "detail", key: "product_id", sql: "SELECT product_id, quantity FROM order_items",
      rollups: { units: { column: "quantity", agg: "sum" } },
    });
  });

  it("declares a relationship by ENTITY ids, with the verb and the column on each side", async () => {
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "Add a relationship" }));
    await user.type(screen.getByLabelText("Link verb"), "made_by");
    await user.selectOptions(screen.getByLabelText("Link target type"), "brand");
    expect(screen.getByRole("button", { name: "Declare" })).toBeDisabled();
    await user.type(screen.getByLabelText("Link column on this type"), "brand_id");
    await user.type(screen.getByLabelText("Link column on the other type"), "brand_id");
    await user.click(screen.getByRole("button", { name: "Declare" }));
    await waitFor(() => expect(declareLink).toHaveBeenCalled());
    expect(declareLink.mock.calls[0]).toEqual(["c1", {
      from_entity: "products", to_entity: "Brand", name: "made_by", from_column: "brand_id", to_column: "brand_id",
    }, "s"]);
  });
});

describe("EntityTypePanel — ON-7b: what an explorer proposed, and a person's confirmation", () => {
  beforeEach(() => {
    confirmProposals.mockClear();
    shown.detail = {
      ...detail,
      origin: "model",
      provenance: "model:m@1",
      bindings: [...detail.bindings, {
        name: "lines", primary: false, kind: "detail", reads: "table", table: "order_items", key: "product_id",
        object_key: "product_id", source: "model", provenance: "model:m@1", verified: true, rows: 10, note: "",
        supplies: 1, usable: true, rollups: { units: "the sum of quantity over each object's lines rows" } }],
      links: detail.links.map((l) => ({ ...l, origin: "model" as const, provenance: "model:m@1" })),
    };
  });
  afterEach(() => { shown.detail = undefined; });

  it("marks the type, its binding and its link proposed, and confirms each by the declaration it was written as", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(
      <EntityTypePanel connectionId="c1" schema="s" objectType="product" types={rows} version={0}
        onOpen={() => {}} onChanged={changed} />);
    const confirms = await screen.findAllByTestId("proposal-confirm");
    expect(confirms).toHaveLength(3);                                      // the type, its binding, its link
    expect(screen.getByText("model:m@1")).toBeInTheDocument();
    for (const button of confirms) await user.click(button);
    await waitFor(() => expect(confirmProposals).toHaveBeenCalledTimes(3));
    expect(confirmProposals.mock.calls.map((call) => call[1])).toEqual([
      { targets: [{ kind: "entity", entity: "products" }] },
      { targets: [{ kind: "binding", entity: "products", binding: "lines" }] },
      { targets: [{ kind: "link", relationship: "rel_product_order_item" }] },
    ]);
    expect(changed).toHaveBeenCalledTimes(3);
  });

  it("says why when a confirmation is refused, and changes nothing", async () => {
    confirmProposals.mockResolvedValueOnce({
      confirmed: [], refused: [{ why: "products was declared by a person — there is no proposal to confirm" }] });
    const user = userEvent.setup();
    const changed = vi.fn();
    render(
      <EntityTypePanel connectionId="c1" schema="s" objectType="product" types={rows} version={0}
        onOpen={() => {}} onChanged={changed} />);
    const [first] = await screen.findAllByTestId("proposal-confirm");
    await user.click(first);
    expect(await screen.findByText(/there is no proposal to confirm/)).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
  });
});

describe("EntityTypePanel — ON-8: a type of the organisation's ontology", () => {
  const sources = { shop1: "Shop", crm1: "CRM" };
  const onShop: ObjectTypeDetail = {
    ...detail, connection_id: "shop1", schema_name: "",
    bindings: [
      { ...detail.bindings[0], connection_id: "shop1" },
      { name: "reviews", primary: false, kind: "static", reads: "table", table: "support.reviews", key: "product_id",
        object_key: "product_id", source: "human", verified: true, rows: 90, objects: 1000, covered: 90, orphans: 0,
        note: "", supplies: 1, usable: true, connection_id: "crm1" },
    ],
    links: [{ ...detail.links[0], traversal: "cross-source" }],
  };

  beforeEach(() => {
    shown.detail = onShop;
    addBinding.mockClear();
  });
  afterEach(() => { shown.detail = undefined; });

  function inDomain() {
    return render(
      <EntityTypePanel connectionId="domain:default" objectType="product" types={rows} version={0}
        onOpen={() => {}} onChanged={() => {}} sources={sources} />);
  }

  it("says where the type and each binding are read from, marks a cross-source link, and offers no one-connection door", async () => {
    inDomain();
    expect(await screen.findByTestId("entity-connection")).toHaveTextContent("read from Shop");
    expect(screen.getAllByTestId("entity-binding-connection").map((n) => n.textContent)).toEqual(["Shop", "CRM"]);
    expect(screen.getByTestId("entity-link-cross-source")).toHaveTextContent("cross-source");
    // 2026-09-22 — naming is declarative and opens on a far link; the explorer's confirm and the SQL-bound doors do not.
    expect(screen.getByRole("button", { name: /Name it|Rename/ })).toBeInTheDocument();
    expect(screen.queryByLabelText("Declare")).toBeNull();
    expect(screen.getByRole("button", { name: "Measure" })).toBeInTheDocument();
  });

  it("binds from another connection only as a static binding, naming that connection and its schema in the spec", async () => {
    const user = userEvent.setup();
    inDomain();
    await user.click(await screen.findByRole("button", { name: "Declare a binding" }));
    await user.selectOptions(screen.getByTestId("declare-binding-connection"), "crm1");
    expect(screen.getByTestId("declare-binding-crosses")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Binding name"), "tickets");
    await user.type(screen.getByLabelText("Table"), "tickets");
    await user.type(screen.getByLabelText("Binding schema"), "support");
    await user.selectOptions(screen.getByLabelText("Binding kind"), "timeseries");
    await user.type(screen.getByLabelText("Time column"), "opened_at");
    expect(screen.getByRole("button", { name: "Bind" })).toBeDisabled();    // across two connections: static only
    await user.selectOptions(screen.getByLabelText("Binding kind"), "static");
    await user.click(screen.getByRole("button", { name: "Bind" }));
    await waitFor(() => expect(addBinding).toHaveBeenCalled());
    const [conn, entity, name, spec] = addBinding.mock.calls[0];
    expect([conn, entity, name]).toEqual(["domain:default", "products", "tickets"]);
    expect(spec).toEqual({ kind: "static", key: "product_id", table: "tickets", connection_id: "crm1", schema_name: "support" });
  });

  it("sends no connection when the source is on the type's own connection", async () => {
    const user = userEvent.setup();
    inDomain();
    await user.click(await screen.findByRole("button", { name: "Declare a binding" }));
    expect(screen.getByTestId("declare-binding-connection")).toHaveValue("shop1");
    expect(screen.queryByTestId("declare-binding-crosses")).toBeNull();
    await user.type(screen.getByLabelText("Binding name"), "stock");
    await user.type(screen.getByLabelText("Table"), "stock");
    await user.click(screen.getByRole("button", { name: "Bind" }));
    await waitFor(() => expect(addBinding).toHaveBeenCalled());
    expect(addBinding.mock.calls[0][3]).toEqual({ kind: "static", key: "product_id", table: "stock" });
  });
});

describe("EntityTypePanel — ON-9: a process and a rule declared from the type they are about", () => {
  const property = (name: string, role: string, dataType: string) => ({
    name, display_name: name, role, data_type: dataType, unit: "", is_key: false, null_rate: 0, description: "",
    source: { binding: "products", table: "products", column: name } });
  const timed: ObjectTypeDetail = {
    ...detail,
    properties: [...detail.properties, property("created_at", "timestamp", "TIMESTAMP"),
                 property("shipped_at", "timestamp", "DATE"), property("status", "dimension", "VARCHAR")],
    metrics: [{ id: "revenue", display_name: "Revenue", unit: "EUR", formula_sql: "SUM(total)" }],
  };
  beforeEach(() => {
    shown.detail = timed;
    declareProcess.mockClear();
    declareRule.mockClear();
  });
  afterEach(() => { shown.detail = undefined; });

  it("declares a process in stages at the type's moments, with a promise in hours on a stage after the first", async () => {
    const user = userEvent.setup();
    const onOpenProcess = vi.fn();
    render(<EntityTypePanel connectionId="c1" schema="s" objectType="product" types={rows} version={0}
      onOpen={() => {}} onChanged={() => {}} onOpenProcess={onOpenProcess} />);
    await user.click(await screen.findByRole("button", { name: "Declare a process" }));
    const declare = screen.getByRole("button", { name: "Declare the process" });
    await user.type(screen.getByLabelText("Process id"), "order_fulfilment");
    await user.type(screen.getByLabelText("Stage 1 name"), "placed");
    await user.selectOptions(screen.getByLabelText("Stage 1 moment"), "created_at");
    await user.type(screen.getByLabelText("Stage 2 name"), "shipped");
    await user.selectOptions(screen.getByLabelText("Stage 2 moment"), "shipped_at");
    expect(declare).toBeEnabled();
    await user.selectOptions(screen.getByLabelText("Stage 2 promise"), "within_hours");
    expect(declare).toBeDisabled();                                  // a promise names its hours first
    await user.type(screen.getByLabelText("Stage 2 promise hours"), "48");
    await user.click(declare);
    await waitFor(() => expect(declareProcess).toHaveBeenCalled());
    expect(declareProcess.mock.calls[0]).toEqual(["c1", { id: "order_fulfilment", entity: "products", stages: [
      { name: "placed", timestamp: "created_at" },
      { name: "shipped", timestamp: "shipped_at", promise: { within_hours: 48 } }] }, "s"]);
    await waitFor(() => expect(onOpenProcess).toHaveBeenCalledWith("order_fulfilment"));
  });

  it("declares a condition rule that scopes a metric, and a value set by its values", async () => {
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "Declare a rule" }));
    await user.type(screen.getByLabelText("Rule id"), "shipped_orders");
    await user.selectOptions(screen.getByLabelText("Rule property"), "status");
    await user.selectOptions(screen.getByLabelText("Rule operator"), "not_in");
    await user.type(screen.getByLabelText("Rule value"), "cancelled, refunded");
    await user.click(screen.getByRole("checkbox", { name: "Revenue" }));
    await user.click(screen.getByRole("button", { name: "Declare the rule" }));
    await waitFor(() => expect(declareRule).toHaveBeenCalled());
    expect(declareRule.mock.calls[0]).toEqual(["c1", { id: "shipped_orders", entity: "products", kind: "condition",
      conditions: [{ path: "status", op: "not_in", values: ["cancelled", "refunded"] }], scopes: ["revenue"] }, "s"]);

    await user.click(await screen.findByRole("button", { name: "Declare a rule" }));
    await user.type(screen.getByLabelText("Rule id"), "dach");
    await user.selectOptions(screen.getByLabelText("Rule kind"), "value_set");
    await user.selectOptions(screen.getByLabelText("Rule property"), "status");
    await user.type(screen.getByLabelText("Rule values"), "DE, AT , CH");
    await user.click(screen.getByRole("button", { name: "Declare the rule" }));
    await waitFor(() => expect(declareRule).toHaveBeenCalledTimes(2));
    expect(declareRule.mock.calls[1]).toEqual(["c1", { id: "dach", entity: "products", kind: "value_set",
      property: "status", values: ["DE", "AT", "CH"] }, "s"]);
  });

  it("offers no process on a type with fewer than two moments to run between", async () => {
    shown.detail = undefined;
    panel();
    expect(await screen.findByRole("button", { name: "Declare a process" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Declare a rule" })).toBeEnabled();
  });
});

describe("EntityTypePanel — reading a type from a keyed SELECT", () => {
  beforeEach(() => {
    previewBacking.mockReset();
    setQueryBacking.mockClear();
    withdrawBacking.mockClear();
    shown.detail = undefined;
  });

  const preview = (over: Partial<BackingPreview>): BackingPreview => ({
    readable: true, note: "", rows: 3, unique: true, unique_note: "", columns: ["product_id", "name"],
    kept: ["product_id", "name"], dropped: [], added: [],
    current: { reads: "table", source: "products", key: "product_id", rows: 3, unique: true }, ...over,
  });

  it("previews the SELECT and sets it only when its key is unique and it drops nothing", async () => {
    const user = userEvent.setup();
    previewBacking.mockResolvedValueOnce(preview({ dropped: ["price"] }))
      .mockResolvedValueOnce(preview({ added: ["avg_rating"] }));
    render(<EntityTypePanel connectionId="c1" schema="s" objectType="product" types={rows} version={0}
      onOpen={() => {}} onChanged={() => {}} onOpenProcess={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "Read from a SELECT" }));
    await user.type(screen.getByLabelText("Backing SELECT"), "SELECT product_id, name FROM products");
    await user.clear(screen.getByLabelText("Backing key"));
    await user.type(screen.getByLabelText("Backing key"), "product_id");
    expect(screen.getByRole("button", { name: "Set as backing" })).toBeDisabled();       // never before a preview

    await user.click(screen.getByRole("button", { name: "Preview" }));
    expect(within(await screen.findByTestId("backing-preview")).getByText("price")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set as backing" })).toBeDisabled();       // it drops a property
    expect(screen.getByText("it drops price — select it too")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Preview" }));
    expect(within(await screen.findByTestId("backing-preview")).getByText("avg_rating")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Set as backing" }));
    expect(previewBacking).toHaveBeenLastCalledWith("c1", "products", "SELECT product_id, name FROM products", "product_id", "s");
    expect(setQueryBacking).toHaveBeenCalledWith("c1", "products", "SELECT product_id, name FROM products", "product_id", "s");
  });
});

describe("withdrawing what the builder found (2026-09-22)", () => {
  it("offers Withdraw on a found link and lists a withdrawal with its door back", async () => {
    const user = userEvent.setup();
    deleteLink.mockClear();
    restoreLink.mockClear();
    shown.detail = {
      ...detail,
      withdrawn: { bindings: ["lines"], links: [{ relationship: "product_to_supplier", from_entity: "Product", to_entity: "Supplier" }] },
    };
    render(<EntityTypePanel connectionId="c1" objectType="product" types={rows} version={0} onOpen={() => {}} onChanged={() => {}} />);
    const link = await screen.findByTestId("entity-link");
    await user.click(within(link).getByRole("button", { name: "Withdraw" }));
    await user.click(within(link).getByRole("button", { name: /Withdraw/ }));
    await waitFor(() => expect(deleteLink).toHaveBeenCalled());
    const rows_ = screen.getAllByTestId("entity-withdrawn");
    expect(rows_).toHaveLength(2);
    expect(rows_[1]).toHaveTextContent("product_to_supplier");
    await user.click(within(rows_[1]).getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(restoreLink).toHaveBeenCalledWith("c1", "product_to_supplier", undefined));
    shown.detail = undefined;
  });
});
