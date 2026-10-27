// @vitest-environment jsdom
/**
 * A board (Arc SH, SH-3): a card moves by the keyboard as well as by dragging — ← and → to the lane beside, the "Move
 * to" list for whoever does not know the keys — and each move is the column's edit at the version the board read.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const setCells = vi.fn(async () => ({ change_id: "c1", cells: [] }));
vi.mock("@/lib/sheets", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/sheets")>()),
  setCells: (...a: unknown[]) => setCells(...(a as [])),
  readBoard: async () => ({
    column: "c2", total: 3, movable: true, columns: ["c1", "c2"], not_shown: [], marks: {},
    changed: { "4": { c2: { by: "user:ana", at: "2026-10-27T10:00:00", version: 2 } } },
    // row 7 was moved and then undone: it holds no edit, but its cell stands at version 2
    versions: { "4": { c2: 2 }, "7": { c2: 2 } },
    lanes: [
      { value: "shipped", rows: 2, cards: [[3, "o3", "shipped"], [4, "o4", "shipped"]] },
      { value: "invoiced", rows: 1, cards: [[7, "o7", "invoiced"]] },
      { value: "approved", rows: 0, cards: [] },
    ],
  }),
}));

import { SheetBoard } from "./SheetBoard";
import type { Sheet } from "@/lib/sheets";

const col = (id: string, name: string, kind: string, choices: string[] = []) => ({
  id, name, kind, choices, integer: false, description: "", role: "stored", source: name, currency: "", hidden: false,
  expression: "", link: null, via: "", of: "", sheet: "", key: "", by: "", how: "", made_by: "",
});
const SHEET = {
  id: "s1", name: "Olist orders", key: "", rules: [], views: [],
  columns: [col("c1", "order_id", "text"), col("c2", "order_status", "choice", ["shipped", "invoiced", "approved"])],
} as unknown as Sheet;

const board = (onMoved = vi.fn(), onOpenRow = vi.fn()) =>
  render(<SheetBoard sheet={SHEET} query={{}} column="c2" card={[]} editable tick={0} onMoved={onMoved} onOpenRow={onOpenRow} />);

beforeEach(() => setCells.mockClear());

describe("SheetBoard by the keyboard", () => {
  it("moves a card to the lane beside with → and ←, at the version the board read", async () => {
    const onMoved = vi.fn();
    board(onMoved);
    const card = await screen.findByRole("group", { name: "Row 4, in shipped" });
    fireEvent.keyDown(card, { key: "ArrowRight" });
    await waitFor(() => expect(setCells).toHaveBeenCalledWith("s1", [{ row: 4, column: "c2", value: "invoiced", version: 2 }]));
    expect(onMoved).toHaveBeenCalledWith("Row 4 moved to invoiced");
    setCells.mockClear();
    fireEvent.keyDown(await screen.findByRole("group", { name: "Row 7, in invoiced" }), { key: "ArrowLeft" });
    // the version its undo left, not 0 — a move at 0 was refused as stale
    await waitFor(() => expect(setCells).toHaveBeenCalledWith("s1", [{ row: 7, column: "c2", value: "shipped", version: 2 }]));
  });

  it("does not move a card past the first or the last lane, and Enter opens it", async () => {
    const onOpenRow = vi.fn();
    board(vi.fn(), onOpenRow);
    const card = await screen.findByRole("group", { name: "Row 3, in shipped" });
    fireEvent.keyDown(card, { key: "ArrowLeft" });
    fireEvent.keyDown(card, { key: "Enter" });
    expect(setCells).not.toHaveBeenCalled();
    expect(onOpenRow).toHaveBeenCalledWith(3);
  });

  it("lists the other lanes under Move to, an empty lane among them", async () => {
    board();
    fireEvent.click(await screen.findByRole("button", { name: "Move row 3 to another lane" }));
    const to = screen.getByRole("group", { name: "Move row 3 to" });
    expect(to).toHaveTextContent("invoiced");
    expect(to).toHaveTextContent("approved");
    fireEvent.click(screen.getByRole("button", { name: "approved" }));
    await waitFor(() => expect(setCells).toHaveBeenCalledWith("s1", [{ row: 3, column: "c2", value: "approved", version: 0 }]));
  });
});
