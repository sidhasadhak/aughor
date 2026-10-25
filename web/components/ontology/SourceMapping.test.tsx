// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { connector, SourceMapping } from "@/components/ontology/SourceMapping";
import type { ObjectTypeDetail, TypeBinding, TypeProperty } from "@/lib/objectTypes";

const binding = {
  name: "orders", primary: true, kind: "static", reads: "table", table: "orders", key: "order_id", object_key: "order_id",
  source: "backing", verified: true, rows: 10, note: "", supplies: 2, usable: true,
} as TypeBinding;

const prop = (name: string, over: Partial<TypeProperty> = {}): TypeProperty => ({
  name, display_name: name.replace(/_/g, " "), role: "", data_type: "VARCHAR", unit: "", is_key: false, null_rate: null,
  description: "", source: { binding: "orders", table: "orders", column: name }, ...over,
});

const detail = {
  display_name: "Order",
  display_property: { property: "order_id", is_key: true, source: "key" },
  properties: [
    prop("order_id", { is_key: true, data_type: "BIGINT" }),
    prop("placed_at", { data_type: "TIMESTAMP", null_rate: 0.02, description: "when the order was placed" }),
    prop("total_eur", { source: { binding: "orders", expression: "amount * 1.1" } }),
  ],
} as unknown as ObjectTypeDetail;

const columns = [
  { name: "order_id", type: "BIGINT" }, { name: "placed_at", type: "TIMESTAMP" },
  { name: "amount", type: "DOUBLE" }, { name: "note", type: "VARCHAR" },
];

describe("the source mapping", () => {
  afterEach(cleanup);

  it("draws a right-angled connector from each column read to its property, and says what is not read", () => {
    render(<SourceMapping detail={detail} binding={binding} columns={columns} />);
    const lines = screen.getAllByTestId("mapping-line");
    expect(lines).toHaveLength(2);
    expect(lines[0].querySelector("path")?.getAttribute("d")).toBe(connector(0, 0));
    expect(connector(1, 1)).toBe("M 0 39 H 36 V 39 H 72");            // level out, upright, level in — no curve
    const cols = screen.getAllByTestId("mapping-column");
    expect(cols.map((c) => c.getAttribute("data-read"))).toEqual(["true", "true", "false", "false"]);
    expect(cols[2]).toHaveTextContent("not read");
    const props = screen.getAllByTestId("mapping-property");
    expect(props[2]).toHaveTextContent("= expression");
    expect(screen.getByTestId("source-mapping")).toHaveTextContent("2 of 3 properties are read from orders");
  });

  it("the chosen pair takes the accent and shows the property's facts; choosing it again lets go", () => {
    render(<SourceMapping detail={detail} binding={binding} columns={columns} />);
    fireEvent.click(screen.getAllByTestId("mapping-property")[1]);
    expect(screen.getAllByTestId("mapping-line")[1].getAttribute("data-chosen")).toBe("true");
    expect(screen.getAllByTestId("mapping-line")[0].getAttribute("data-chosen")).toBe("false");
    let box = screen.getByTestId("mapping-inspector");
    expect(box).toHaveTextContent("placed_at");
    expect(box).toHaveTextContent("orders.placed_at");
    expect(box).toHaveTextContent("2.0% of rows");
    expect(box).toHaveTextContent("when the order was placed");
    // a column picks the property read from it
    fireEvent.click(screen.getAllByTestId("mapping-column")[0]);
    box = screen.getByTestId("mapping-inspector");
    expect(box).toHaveTextContent("order_id");
    expect(box).toHaveTextContent("key · display property");
    // the same row again lets go
    fireEvent.click(screen.getAllByTestId("mapping-property")[0]);
    expect(screen.queryByTestId("mapping-inspector")).toBeNull();
  });

  it("says when there are no columns to draw: still reading, unreadable, or a binding that reads a query", () => {
    render(<SourceMapping detail={detail} binding={binding} columns={null} />);
    expect(screen.getByTestId("mapping-columns")).toHaveTextContent("Reading the table’s columns");
    expect(screen.queryAllByTestId("mapping-line")).toHaveLength(0);
    cleanup();
    render(<SourceMapping detail={detail} binding={binding} columns={[]} said="The table’s columns could not be read: timed out" />);
    expect(screen.getByTestId("mapping-columns")).toHaveTextContent("could not be read: timed out");
    cleanup();
    render(<SourceMapping detail={detail} binding={{ ...binding, reads: "query", table: undefined, sql: "select 1" }} columns={[]} />);
    expect(screen.getByTestId("mapping-columns")).toHaveTextContent("reads a query");
    expect(screen.getByTestId("source-mapping")).toHaveTextContent("3 properties; the binding reads a query");
    expect(screen.getAllByTestId("mapping-property")).toHaveLength(3);
  });
});
