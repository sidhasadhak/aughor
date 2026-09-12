// @vitest-environment jsdom

/**
 * Arc ON leftovers — the two declaration doors the panel was missing.
 *
 * The panel could BIND what the builder proposed and REMOVE what a person set, and that was all. A
 * timeseries binding is never proposed (many rows per object is what the proposal check rejects) and
 * neither is a keyed SELECT, so both were API-only; and a link kept the builder's generic name because
 * no web door named one. These pin what the forms HAND the doors — the spec and the name — because
 * that is where the bug would live: a form that looks right and posts a static binding with no time
 * column is refused by the server, silently, one round trip later.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ObjectTypeDetail } from "@/lib/objectTypes";

const addBinding = vi.fn(async (..._args: unknown[]) => undefined);
const nameLink = vi.fn(async (..._args: unknown[]) => undefined);

vi.mock("@/lib/objectTypes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/objectTypes")>()),
  getObjectType: async () => detail,
  addBinding: (...a: unknown[]) => addBinding(...a),
  nameLink: (...a: unknown[]) => nameLink(...a),
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

function panel() {
  return render(
    <EntityTypePanel connectionId="c1" schema="s" objectType="product" types={[]} version={0}
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
