// @vitest-environment jsdom
/**
 * A sheet opened by its link after it was removed: said with who and when and the way back, never a failure to retry.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

let refusal: { message: string; status: number };
vi.mock("@/lib/sheets", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/sheets")>()),
  readSheet: async () => { throw Object.assign(new Error(refusal.message), { status: refusal.status }); },
  readChanges: async () => ({ changes: [], can_undo: "", can_redo: "" }),
}));

import { SheetView } from "./SheetView";

describe("a sheet that cannot be read", () => {
  it("removed: says so, offers the way back and no retry", async () => {
    refusal = { message: 'The sheet "Customers" was removed by ana on 2026-11-03.', status: 404 };
    const onBack = vi.fn();
    render(<SheetView sheetId="0123456789" onBack={onBack} onOpen={() => {}} />);
    expect(await screen.findByText(/was removed by ana on 2026-11-03/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Back to Spreadsheets" }));
    expect(onBack).toHaveBeenCalled();
  });

  it("a failure to read is still a failure to retry", async () => {
    refusal = { message: "the server is away", status: 500 };
    render(<SheetView sheetId="0123456789" onBack={() => {}} onOpen={() => {}} />);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
