// @vitest-environment jsdom
/**
 * A wrong note on a column could not be removed from the app (2026-10-02): theLook's `order_items.status`
 * carried an agent's false note that rode into every prompt reading the column, and the only way out was to
 * edit the YAML by hand. The Comments tab shows the note and who wrote it, and Clear replaces it with nothing.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  getGlossary: vi.fn(async () => ({})),
  lookupGlossaryTable: vi.fn(() => ({})),
  updateTableGlossary: vi.fn(),
  updateColumnGlossary: vi.fn(),
  getColumnNotes: vi.fn(async () => ({ order_items: { status: {
    note: "revenue and units_sold exclude 'Cancelled' orders (agent-observed: …)", source: "agent", edited_at: "" } } })),
  setColumnNote: vi.fn(async () => {}),
}));

import { getColumnNotes, setColumnNote } from "@/lib/api";
import { GlossaryPanel } from "@/components/catalog/GlossaryPanel";

describe("a column's note in the Catalog", () => {
  it("is shown with who wrote it, and Clear replaces it with nothing", async () => {
    render(<GlossaryPanel table="order_items" columns={["status", "sale_price"]} schema="thelook" connectionId="8233e4fd" />);
    await waitFor(() => screen.getByText(/written by the agent/));
    expect(screen.getByText(/exclude 'Cancelled' orders/)).toBeTruthy();
    expect(vi.mocked(getColumnNotes)).toHaveBeenCalledWith("8233e4fd", "thelook");
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(setColumnNote).toHaveBeenCalledWith("8233e4fd", "thelook", "order_items", "status", ""));
  });

  it("shows no note without a connection", async () => {
    render(<GlossaryPanel table="order_items" columns={["status"]} schema="thelook" />);
    await waitFor(() => screen.getByText("Columns"));
    expect(screen.queryByText(/Note the agent reads/)).toBeNull();
  });
});
