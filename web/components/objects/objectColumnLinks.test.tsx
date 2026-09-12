// @vitest-environment jsdom

/**
 * ON-3b — an answer's key columns link to object pages, and now read as NAMES.
 *
 * `MYT-O00003141` is what the warehouse stores and not what anyone recognises. Every type already declares
 * the property that names its objects, measured against its backing; it never reached the table. What is
 * pinned here: one request per type for the whole page of keys (not one per row), the key still shown when
 * no name comes back, and — the part that must not regress — a failing or refusing titles door leaving the
 * table exactly as it was. A name is decoration on a link; it may never gate one.
 */
import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import type { ObjectCatalog } from "@/lib/objects";

const catalog: ObjectCatalog = {
  connection_id: "c1",
  schema_name: "s",
  object_types: [
    { object_type: "customer", id: "Customer", display_name: "Customer", key: "customer_id", key_unique: true,
      time: "", properties: {}, links: [], segments: [], metrics: [] },
    { object_type: "order", id: "Order", display_name: "Order", key: "order_id", key_unique: true,
      time: "", properties: {}, links: [], segments: [], metrics: [] },
  ],
};

const getObjectTitles = vi.fn(async (objectType: string, keys: string[]) => (
  objectType === "customer"
    ? { path: "titles" as const, connection_id: "c1", schema_name: "s", object_type: "customer",
        type_id: "Customer", key: "customer_id", property: "full_name", truncated: false,
        titles: Object.fromEntries(keys.filter((k) => k !== "C3").map((k) => [k, `Name of ${k}`])) }
    : { path: "titles" as const, connection_id: "c1", schema_name: "s", object_type: "order", type_id: "Order",
        key: "order_id", property: "order_id", truncated: false, titles: {}, note: "named by its key" }
));

vi.mock("@/lib/objects", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/objects")>()),
  cachedObjectCatalog: async () => catalog,
  getObjectTitles: (...a: unknown[]) => getObjectTitles(...(a as [string, string[]])),
}));

import { useObjectColumnLinks } from "@/components/objects/objectColumnLinks";

const COLUMNS = ["customer_id", "order_id", "total"];
const ROWS: unknown[][] = [["C1", "O1", 10], ["C2", "O2", 20], ["C3", "O3", 30], ["C1", "O4", 40]];

/** The cells `SqlResultTable` would draw, without the table: the overrides ARE the contract. */
function Table({ rows }: { rows: unknown[][] }) {
  const overrides = useObjectColumnLinks(COLUMNS, "c1", { rows });
  return (
    <table><tbody>
      {rows.map((row, ri) => (
        <tr key={ri}>
          {COLUMNS.map((column, ci) => (
            <td key={column}>
              {(overrides[column]?.render?.(row[ci], {}, ri) as React.ReactNode) ?? String(row[ci])}
            </td>
          ))}
        </tr>
      ))}
    </tbody></table>
  );
}

describe("an answer table reads objects by name", () => {
  beforeEach(() => getObjectTitles.mockClear());

  it("asks once per type for the whole page and renders the name, keeping the key on hover", async () => {
    render(<Table rows={ROWS} />);

    await waitFor(() => expect(screen.getAllByText("Name of C1")).toHaveLength(2));   // C1 is on two rows
    // One call per TYPE — four rows, two object columns, two requests — with each key asked for once.
    expect(getObjectTitles).toHaveBeenCalledTimes(2);
    expect(getObjectTitles.mock.calls.find((c) => c[0] === "customer")![1]).toEqual(["C1", "C2", "C3"]);
    expect(screen.getAllByTitle("Open customer C1 — Name of C1")).toHaveLength(2);
  });

  it("shows the key when the type is named by its key, or when one key resolved to nothing", async () => {
    render(<Table rows={ROWS} />);

    await waitFor(() => expect(screen.getAllByText("Name of C1")).toHaveLength(2));
    expect(screen.getByText("C3")).toBeInTheDocument();          // the key nothing named, unchanged
    expect(screen.getByTitle("Open order O1")).toHaveTextContent("O1");   // Order is named by its own key
  });

  it("leaves the table on its keys when the titles door fails — a name never gates a link", async () => {
    getObjectTitles.mockRejectedValueOnce(new Error("titles are down"));
    render(<Table rows={ROWS} />);

    await waitFor(() => expect(getObjectTitles).toHaveBeenCalled());
    const cells = await screen.findAllByTitle("Open customer C1");
    expect(cells).toHaveLength(2);
    expect(cells[0]).toHaveTextContent("C1");
  });
});
