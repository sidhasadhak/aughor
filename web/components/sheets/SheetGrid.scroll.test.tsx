// @vitest-environment jsdom
/**
 * A sort keeps your place across (the user, 2026-10-27: "I sorted the last column … and my sheet moves back to left
 * extreme scroll each time and then I have to right scroll again"). The grid was keyed by its reading, so every sort
 * built a new grid, scrolled to the first column. It is now the same grid: a new reading starts at the first row with
 * nothing selected, and the scroll across stays where the person left it.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SheetGrid } from "./SheetGrid";
import type { RowBlocks } from "./useRowBlocks";
import type { Sheet } from "@/lib/sheets";

const SHEET = {
  id: "s1", name: "Olist orders", table: "olist_orders", views: [], rules: [],
  columns: Array.from({ length: 11 }, (_, i) => ({ id: `c${i}`, name: `col${i}`, kind: "text", role: "stored" })),
} as unknown as Sheet;

const ROWS: RowBlocks = {
  total: 1000, stale: false, totals: {}, columns: SHEET.columns.map(c => c.id), failed: null,
  rowAt: () => undefined, rowByNumber: () => undefined, changedOf: () => undefined, versionOf: () => 0,
  marksOf: () => [], onVisible: () => {}, retry: () => {},
};

const grid = (reading: string) => (
  <SheetGrid sheet={SHEET} rows={ROWS} hidden={new Set()} editable onEdit={async () => ({ ok: true })}
    onOpenRow={() => {}} reading={reading} />
);

describe("a sort", () => {
  it("keeps the same grid and the scroll across, and starts at the first row", () => {
    const { rerender } = render(grid("by nothing"));
    const before = screen.getByRole("grid");
    before.scrollLeft = 900;
    before.scrollTop = 4000;
    rerender(grid("by col10, highest first"));
    const after = screen.getByRole("grid");
    expect(after).toBe(before);                 // not a new grid
    expect(after.scrollLeft).toBe(900);         // where the person left it across
    expect(after.scrollTop).toBe(0);            // the first rows of the new order
  });

  it("leaves the scroll alone when the reading is the same", () => {
    const { rerender } = render(grid("by col10"));
    const g = screen.getByRole("grid");
    g.scrollTop = 4000;
    rerender(grid("by col10"));
    expect(g.scrollTop).toBe(4000);
  });
});

it("the sheet never builds a new grid per reading", () => {
  // the cause, one level up: SheetView keyed the grid by its query, so React threw it away on every sort
  const view = readFileSync(join(__dirname, "SheetView.tsx"), "utf8");
  expect(view).toMatch(/<SheetGrid reading=/);
  expect(view).not.toMatch(/<SheetGrid key=/);
});
