// @vitest-environment jsdom
/**
 * Removing a sheet from the Spreadsheets page: offered only to its maker, on a button with an edge, confirmed in its own
 * row and never a pop-up, saying what goes, what stays and what reads it — and nothing is removed until that is known.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SheetDependents, SheetSummary, UploadedFile, WithheldSheet } from "@/lib/sheets";

const summary = (over: Partial<SheetSummary>): SheetSummary => ({
  id: "s1", name: "Olist orders", table: "olist_orders", rows: 99441, columns: 8, came_from: "from olist_orders_dataset.csv",
  source: { kind: "file", file: "olist_orders_dataset.csv", tab: "", rows: 99441, sql: "", connection_id: "", schema_name: "",
    upload: { schema: "olist", file: "olist_orders_dataset.csv" }, imported_at: "" },
  last_change: { id: "c", what: "made from olist_orders_dataset.csv", by: "user:ana", at: "2026-11-01T09:00:00Z", origin: "" },
  created_by: "user:ana", created_at: "2026-11-01T09:00:00Z", version: 1, shared_with: "workspace", access: "own", shares: 0,
  ...over,
});
const UPLOAD: UploadedFile = { schema: "olist", file: "olist_orders_dataset.csv", size: 1 << 20 };
const NOTHING: SheetDependents = { sheets: [], dashboards: [], cards: [] };

let held: { sheets: (SheetSummary | WithheldSheet)[]; uploads: UploadedFile[]; shared_with: string; me: string };
const readDependents = vi.fn(async (_id: string): Promise<SheetDependents> => NOTHING);
const removeSheet = vi.fn(async (id: string) => {
  held = { ...held, sheets: held.sheets.filter(s => s.id !== id) };
  return { removed: id };
});
vi.mock("@/lib/sheets", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/sheets")>()),
  listSheets: async () => held,
  readDependents: (id: string) => readDependents(id),
  removeSheet: (id: string) => removeSheet(id),
}));

import { SheetsHome } from "./SheetsHome";

const home = async () => {
  render(<SheetsHome onOpen={() => {}} />);
  await screen.findByText("Sheets in this workspace");
};
const open = async (name = "Olist orders") => {
  fireEvent.click(await screen.findByRole("button", { name: `Remove ${name}` }));
  return screen.findByRole("group", { name: `Remove ${name}` });
};

beforeEach(() => {
  readDependents.mockReset();
  readDependents.mockImplementation(async () => NOTHING);
  removeSheet.mockClear();
  held = { sheets: [summary({})], uploads: [UPLOAD], shared_with: "workspace", me: "user:ana" };
});

describe("who is offered it", () => {
  it("its maker is, and anyone else is told who may", async () => {
    held.sheets = [summary({}), summary({ id: "s2", name: "Bo's", created_by: "user:bo", access: "edit" }),
      summary({ id: "s3", name: "Read only", created_by: "user:cy", access: "view" })];
    await home();
    expect(screen.getByRole("button", { name: "Remove Olist orders" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove Bo's" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Read only" })).toBeNull();
    expect(screen.getByText("Only bo can remove it")).toBeInTheDocument();
    expect(screen.getByText("Only cy can remove it")).toBeInTheDocument();
  });

  it("a sheet not shared with the reader offers nothing, and the table keeps its columns", async () => {
    held.sheets = [{ id: "s9", name: "Secret", created_by: "user:bo", created_at: "", shared_with: "chosen", access: "",
      withheld: "\"Secret\" was not shared with you." }];
    await home();
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
    const cells = screen.getByText("Not shared with you").closest("tr")!.querySelectorAll("td");
    expect([...cells].reduce((n, c) => n + c.colSpan, 0)).toBe(7);
  });

  it("the button has an edge at rest: an action, never a word", async () => {
    await home();
    expect(screen.getByRole("button", { name: "Remove Olist orders" })).toHaveClass("rt-variant-outline");
  });
});

describe("the confirmation", () => {
  it("opens in the sheet's own row, never a pop-up, saying what goes and what stays", async () => {
    await home();
    const asked = await open();
    expect(asked.closest("td")).toHaveAttribute("colspan", "7");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(asked).toHaveTextContent("This cannot be undone.");
    expect(asked).toHaveTextContent("Its 99,441 rows go for everyone, with every edit and its history.");
    expect(asked).toHaveTextContent("The uploaded file olist_orders_dataset.csv stays and can make a new sheet, though not with those edits.");
    expect(await within(asked).findByText("No other sheet and no dashboard card reads it.")).toBeInTheDocument();
  });

  it("does not say a file stays that went with the sheet", async () => {
    held.sheets = [summary({ source: { ...summary({}).source, upload: {} } })];
    await home();
    const asked = await open();
    expect(asked).not.toHaveTextContent("stays");
    expect(asked).toHaveTextContent("The copy of olist_orders_dataset.csv kept with it goes too.");
  });

  it("names what reads it, and what happens to each", async () => {
    readDependents.mockImplementation(async () => ({
      sheets: [{ id: "s5", name: "Orders", maker: "ana", empties: ["customer_city", "paid"], links: ["customer_id"], withheld: false }],
      dashboards: [{ title: "Sales board", yours: true, owner: "", cards: ["The customers"], count: 1, pieces: ["filters", "add_row"], withheld: false }],
      cards: [],
    }));
    await home();
    const asked = await open();
    expect(await within(asked).findByText("What reads it")).toBeInTheDocument();
    expect(asked).toHaveTextContent("The sheet Orders: customer_city, paid go empty; customer_id keeps its values and links to nothing.");
    expect(asked).toHaveTextContent("Your dashboard Sales board: The customers, its filters, its Add a row button will say the sheet was removed.");
    expect(asked).not.toHaveTextContent("No other sheet");
  });

  it("waits for that read, and says so when it fails", async () => {
    let fail = true;
    readDependents.mockImplementation(async () => {
      if (fail) throw new Error("the server is away");
      return NOTHING;
    });
    await home();
    const asked = await open();
    const remove = within(asked).getByRole("button", { name: "Remove the sheet" });
    expect(await within(asked).findByRole("alert")).toHaveTextContent("so it is not removed yet: the server is away");
    expect(remove).toBeDisabled();
    fail = false;
    fireEvent.click(within(asked).getByRole("button", { name: "Try again" }));
    await within(asked).findByText("No other sheet and no dashboard card reads it.");
    expect(remove).toBeEnabled();
  });

  it("Keep it, the first thing focused, closes it and removes nothing; so does Escape", async () => {
    await home();
    let asked = await open();
    const keep = within(asked).getByRole("button", { name: "Keep it" });
    expect(document.activeElement).toBe(keep);
    fireEvent.click(keep);
    expect(screen.queryByRole("group", { name: "Remove Olist orders" })).toBeNull();
    asked = await open();
    fireEvent.keyDown(asked, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Remove Olist orders" })).toBeNull();
    expect(removeSheet).not.toHaveBeenCalled();
  });

  it("removes it: the row is gone, the page says so, and a second read still leaves it out", async () => {
    await home();
    const asked = await open();
    await within(asked).findByText("No other sheet and no dashboard card reads it.");
    fireEvent.click(within(asked).getByRole("button", { name: "Remove the sheet" }));
    await waitFor(() => expect(removeSheet).toHaveBeenCalledWith("s1"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Remove Olist orders" })).toBeNull());
    expect(screen.getByRole("status")).toHaveTextContent("Olist orders was removed.");
    expect(screen.queryByRole("group", { name: "Remove Olist orders" })).toBeNull();
    // the file stays on the page, one click from a new sheet
    expect(screen.getByRole("button", { name: "Make a sheet" })).toBeInTheDocument();
  });

  it("a refusal stays in the row, in the server's own words", async () => {
    removeSheet.mockImplementationOnce(async () => { throw new Error('Only bo, who made "Olist orders", can change who it is shared with or remove it.'); });
    await home();
    const asked = await open();
    await within(asked).findByText("No other sheet and no dashboard card reads it.");
    fireEvent.click(within(asked).getByRole("button", { name: "Remove the sheet" }));
    expect(await within(asked).findByRole("alert")).toHaveTextContent("Only bo, who made");
    expect(screen.getByRole("group", { name: "Remove Olist orders" })).toBeInTheDocument();
  });
});
