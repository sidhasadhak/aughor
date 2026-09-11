/**
 * ON-3 — which answer columns become object links. A link claims that a value NAMES an object, so
 * the refusals are pinned as hard as the links: a name two types claim, a link the compiler
 * refuses, and a link from a column that is not the key all link nothing.
 */
import { describe, expect, it } from "vitest";

import type { ObjectCatalog, ObjectCatalogType } from "@/lib/objects";
import { declaredActionsHref, objectHref, objectKeyColumns } from "@/lib/objectLinks";

const objectType = (over: Partial<ObjectCatalogType>): ObjectCatalogType => ({
  object_type: "thing", id: "Thing", display_name: "Thing", key: "thing_id", key_unique: true,
  time: "", properties: {}, links: [], segments: [], metrics: [], ...over,
});

const catalog = (...types: ObjectCatalogType[]): ObjectCatalog => ({
  connection_id: "c1", schema_name: "ecommerce", object_types: types,
});

describe("objectHref", () => {
  it("puts the type and key in the path and the scope in the query", () => {
    expect(objectHref("customer", "C00042", "samples", "ecommerce"))
      .toBe("/objects/customer/C00042?conn=samples&schema=ecommerce");
  });

  it("encodes a key that is not a plain token, and omits an absent scope", () => {
    expect(objectHref("order", "A/1 2")).toBe("/objects/order/A%2F1%202");
  });
});

describe("declaredActionsHref", () => {
  it("opens Intelligence at a layer, scoped to the connection", () => {
    const url = new URL(declaredActionsHref("914df862"), "http://aughor.test");
    expect(url.pathname).toBe("/");
    expect(url.searchParams.get("tab")).toBe("intelligence");
    expect(url.searchParams.get("layer")).toBeTruthy();
    expect(url.searchParams.get("conn")).toBe("914df862");
  });
});

describe("objectKeyColumns", () => {
  const customer = objectType({
    object_type: "customer", id: "Customer", key: "customer_id",
    links: [{ name: "customer_to_order", to: "order", cardinality: "1:N", on: "customer_id = customer_id", usable: true }],
  });
  const order = objectType({
    object_type: "order", id: "Order", key: "order_id",
    links: [
      { name: "order_to_customer", to: "customer", cardinality: "N:1", on: "customer_id = customer_id", usable: true },
      { name: "order_to_order_item", to: "order_item", cardinality: "1:N", on: "order_id = parent_order", usable: true },
    ],
  });

  it("names a key's own type, and the type behind the column a link from that key joins to", () => {
    const keys = objectKeyColumns(catalog(customer, order));
    expect(keys.get("customer_id")).toBe("customer");
    expect(keys.get("order_id")).toBe("order");
    expect(keys.get("parent_order")).toBe("order");
  });

  it("claims nothing through a link from a column that is not the key", () => {
    // Order's customer_id names a customer, not an order.
    expect(objectKeyColumns(catalog(order)).has("customer_id")).toBe(false);
  });

  it("claims nothing through a link the compiler refuses", () => {
    const refused = objectType({
      object_type: "customer", key: "customer_id",
      links: [{ name: "customer_to_ticket", to: "ticket", cardinality: "N:N", on: "customer_id = requester",
                usable: false, why_not: "N:N" }],
    });
    expect(objectKeyColumns(catalog(refused)).has("requester")).toBe(false);
  });

  it("links a name two types claim to neither", () => {
    const keys = objectKeyColumns(catalog(objectType({ object_type: "store", key: "id" }),
                                          objectType({ object_type: "brand", key: "ID" })));
    expect(keys.has("id")).toBe(false);
  });

  it("links nothing without a catalog", () => {
    expect(objectKeyColumns(null).size).toBe(0);
  });
});
