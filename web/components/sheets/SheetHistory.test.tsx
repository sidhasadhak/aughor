// @vitest-environment jsdom
/**
 * The history says which value changed, from what to what and what it holds now, and offers the way back for that one
 * value: a put back names the change, the cell or row, and the version it read.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SheetHistory } from "@/components/sheets/SheetHistory";
import { readChangeLines, readHistory, type HistoryChange, type HistoryLine, type HistoryRead, type Sheet } from "@/lib/sheets";

vi.mock("@/lib/sheets", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/sheets")>()), readHistory: vi.fn(), readChangeLines: vi.fn(),
}));

const SHEET = { id: "s1", name: "Orders", me: "user:ana", columns: [
  { id: "c1", name: "order_status", kind: "text", role: "stored" },
] } as unknown as Sheet;

const CELL: HistoryLine = { kind: "cell", row: 12, column: "c1", name: "order_status", title: "e481f51c", what: "set",
  from: "shipped", to: "delivered", stands: true, now: "delivered", current: 3, blocked: "", same: false };

const change = (over: Partial<HistoryChange>): HistoryChange => ({ id: "ch1", what: "1 value changed", by: "user:bo",
  at: "2026-11-04T09:00:00Z", origin: "", values: 1, definition: 0, lines: [CELL], lines_total: 1, ...over });

const read = (changes: HistoryChange[], more: Partial<HistoryRead> = {}): HistoryRead => ({ changes, more: false, scope: null, ...more });

function open(got: HistoryRead, over: Partial<Parameters<typeof SheetHistory>[0]> = {}) {
  vi.mocked(readHistory).mockResolvedValue(got);
  const onPutBack = vi.fn().mockResolvedValue(undefined);
  const onScope = vi.fn();
  render(<SheetHistory sheet={SHEET} tick={0} editable scope={null} canUndo="" onScope={onScope} onClose={() => undefined}
    onUndo={() => undefined} onPutBack={onPutBack} {...over} />);
  return { onPutBack, onScope };
}

describe("SheetHistory", () => {
  beforeEach(() => { vi.mocked(readHistory).mockReset(); vi.mocked(readChangeLines).mockReset(); });

  it("says which cell changed, from what to what, and who did it", async () => {
    open(read([change({})]));
    const line = await screen.findByTestId("history-line");
    expect(line.textContent).toContain("order_status · row 12");
    expect(line.textContent).toContain("shipped → delivered");
    expect(screen.getByTestId("history-change").textContent).toContain("bo");
  });

  it("puts back that one cell, naming the change and the version it read", async () => {
    const { onPutBack } = open(read([change({})]));
    const button = await screen.findByRole("button", { name: "Put back shipped" });
    expect(button.getAttribute("title")).toBe("Puts order_status in row 12 back to shipped. Nothing else changes.");
    fireEvent.click(button);
    await waitFor(() => expect(onPutBack).toHaveBeenCalledWith({ change: "ch1", row: 12, column: "c1", current: 3 }));
  });

  it("says what a cell holds now when it was changed since", async () => {
    open(read([change({ lines: [{ ...CELL, stands: false, now: "returned", current: 5 }] })]));
    expect((await screen.findByTestId("history-line")).textContent).toContain("shipped → delivered · now returned");
  });

  it("offers a removed row back, and takes an added one out with the values it came with", async () => {
    const removed: HistoryLine = { ...CELL, kind: "row", row: 7, column: "", name: "", what: "removed", title: "abc" };
    const added: HistoryLine = { ...CELL, kind: "row", row: 99, column: "", name: "", what: "added", title: "x1",
      values: { order_id: "x1", order_status: "created" }, current: 1 };
    const { onPutBack } = open(read([change({ id: "gone", lines: [removed] }), change({ id: "came", lines: [added] })]));
    const [one, two] = await screen.findAllByTestId("history-line");
    expect(one.textContent).toContain("Row 7 removed");
    expect(two.textContent).toContain("Row 99 added");
    expect(two.textContent).toContain("order_id x1 · order_status created");
    fireEvent.click(within(one).getByRole("button", { name: "Put back" }));
    await waitFor(() => expect(onPutBack).toHaveBeenCalledWith({ change: "gone", row: 7, column: "", current: 3 }));
    fireEvent.click(within(two).getByRole("button", { name: "Take out" }));
    await waitFor(() => expect(onPutBack).toHaveBeenCalledWith({ change: "came", row: 99, column: "", current: 1 }));
  });

  it("offers nothing to do when it already holds that, and says why when it cannot be done", async () => {
    open(read([change({ id: "a", lines: [{ ...CELL, same: true }] }),
      change({ id: "b", lines: [{ ...CELL, blocked: "row 12 has since been removed; put the row back first" }] })]));
    const [same, blocked] = await screen.findAllByTestId("history-line");
    expect(same.textContent).toContain("Already back");
    expect(within(same).queryByRole("button", { name: /Put back/ })).toBeNull();
    expect(blocked.textContent).toContain("Cannot be put back: row 12 has since been removed; put the row back first.");
    expect(within(blocked).queryByRole("button", { name: /Put back/ })).toBeNull();
  });

  it("shows a reader what changed and offers no way to change it", async () => {
    open(read([change({ lines_total: 2, what: "2 values changed" })]), { editable: false });
    await screen.findByTestId("history-line");
    expect(screen.queryByRole("button", { name: /Put back/ })).toBeNull();
  });

  it("puts a whole change back, and lists the rest of a long one when asked", async () => {
    const lines = [{ ...CELL, row: 1 }, { ...CELL, row: 2 }];
    vi.mocked(readChangeLines).mockResolvedValue({ lines: [...lines, { ...CELL, row: 3 }], total: 3 });
    const { onPutBack } = open(read([change({ what: "3 values changed", lines, lines_total: 3, values: 3 })]));
    fireEvent.click(await screen.findByRole("button", { name: "Put back all 3" }));
    await waitFor(() => expect(onPutBack).toHaveBeenCalledWith({ change: "ch1" }));
    expect(screen.getAllByTestId("history-line")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Show all 3" }));
    await waitFor(() => expect(screen.getAllByTestId("history-line")).toHaveLength(3));
    expect(readChangeLines).toHaveBeenCalledWith("s1", "ch1");
  });

  it("narrows to one cell's story from its line, and reads that story with where it came from", async () => {
    const { onScope } = open(read([change({})]));
    fireEvent.click(await screen.findByRole("button", { name: "order_status · row 12" }));
    expect(onScope).toHaveBeenCalledWith({ row: 12, column: "c1" });
  });

  it("reads one cell's story: what it holds now, each state it held, and where it began", async () => {
    const scope = { row: 12, column: "c1", name: "order_status", title: "e481f51c", removed: false, now: "returned",
      came_from: "imported from orders.csv, row 12" };
    const { onScope } = open(read([change({ id: "new", lines: [{ ...CELL, from: "delivered", to: "returned" }] }), change({ id: "old" })],
      { scope }), { scope: { row: 12, column: "c1" } });
    const head = await screen.findByTestId("history-scope");
    expect(head.textContent).toContain("order_status · row 12");
    expect(head.textContent).toContain("Holds returned now.");
    expect(readHistory).toHaveBeenCalledWith("s1", { row: 12, column: "c1" });
    expect(screen.getAllByTestId("history-line").map(l => l.textContent)).toEqual([
      expect.stringContaining("delivered → returned"), expect.stringContaining("shipped → delivered")]);
    expect(screen.getAllByTestId("history-line").some(l => /now /.test(l.textContent ?? ""))).toBe(false);
    expect(screen.queryByRole("button", { name: "order_status · row 12" })).toBeNull();
    expect(screen.getByText("Imported from orders.csv, row 12")).toBeTruthy();
    fireEvent.click(within(head).getByRole("button", { name: "All changes" }));
    expect(onScope).toHaveBeenCalledWith(null);
  });

  it("says older changes exist when it lists only the latest", async () => {
    open(read([change({})], { more: true }));
    expect((await screen.findByText(/older changes are kept too/)).textContent).toContain("The latest 1");
  });
});
