// @vitest-environment jsdom
/**
 * A column a model writes (Arc SH, SH-5), as the grid shows it: marked in its header, its empty cells said as not
 * filled, a value it wrote said as a model's reading — and Fill offered in its menu only where filling is allowed.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CellValue, GridHeader, cellOrigin, layoutColumns } from "./SheetGrid";
import type { Sheet } from "@/lib/sheets";

const base = {
  kind: "text", role: "stored", integer: false, description: "", currency: "", choices: [], hidden: false,
  expression: "", link: null, via: "", of: "", sheet: "", key: "", by: "", how: "", made_by: "",
};
const MESSAGE = { ...base, id: "c4", name: "review_comment_message", source: "review_comment_message" };
const TOPIC = { ...base, id: "c5", name: "Complaint topic", source: "", description: "written by a model: the complaint",
  model_writes: { instruction: "the complaint, in two or three words", reads: ["c4"] } };
const SHEET = { id: "s1", name: "Olist reviews", columns: [MESSAGE, TOPIC], rules: [], views: [], me: "user:ana" } as unknown as Sheet;

const header = (canFill: boolean) => {
  const onAction = vi.fn();
  render(<GridHeader sheet={SHEET} shown={layoutColumns(SHEET.columns, new Set())} onAction={onAction} canFill={canFill} />);
  return onAction;
};

describe("a column a model writes", () => {
  it("is marked in its header, and offers Fill in its menu where filling is allowed", () => {
    const onAction = header(true);
    expect(screen.getByText("written by a model")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("The Complaint topic column's menu"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Fill with the model…" }));
    expect(onAction).toHaveBeenCalledWith("fill", "c5");
  });

  it("offers no Fill where filling is not allowed, nor on a column a person writes", () => {
    header(false);
    fireEvent.click(screen.getByLabelText("The Complaint topic column's menu"));
    expect(screen.queryByRole("menuitem", { name: "Fill with the model…" })).not.toBeInTheDocument();
  });

  it("says an empty cell is not filled, and a value as a model's reading", () => {
    render(<CellValue column={TOPIC as never} value={null} />);
    expect(screen.getByText("not filled")).toBeInTheDocument();
    expect(cellOrigin(SHEET, TOPIC as never, 3, { by: "user:ana", at: "2026-10-28T09:00:00Z", version: 1, origin: "model:abc" }))
      .toMatch(/^Written by a model for you · .* · a reading, not a fact$/);
    expect(cellOrigin(SHEET, TOPIC as never, 3, { by: "user:bo", at: "2026-10-28T09:00:00Z", version: 1 }))
      .toMatch(/^Set by bo · /);
  });
});
