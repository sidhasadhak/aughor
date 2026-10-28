// @vitest-environment jsdom
/**
 * Who a sheet is shared with (Arc SH, SH-8): off, the pop-up says what it always said; on, the maker chooses people and
 * groups, each to read or to edit, and anyone else is told who it is shared with and that only its maker changes it.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SheetSharing } from "@/lib/sheets";

const GROUPS: SheetSharing["groups"] = [
  { kind: "group", id: "finance", name: "Finance" },
  { kind: "role", id: "analyst", name: "Editor" },
];
let held: SheetSharing;
const saveSharing = vi.fn(async (_id: string, sharing: string, shared_with: unknown[]) =>
  ({ ...held, sharing, shared_with }) as SheetSharing);
vi.mock("@/lib/sheets", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/sheets")>()),
  readSharing: async () => held,
  saveSharing: (...a: unknown[]) => saveSharing(...(a as [string, string, unknown[]])),
}));

import { SharePop, typedShare } from "./SheetSharing";

const asMaker = (over: Partial<SheetSharing> = {}): SheetSharing => ({
  sharing: "workspace", shared_with: [], maker: "ana", access: "own", why: "made it", may_change: true,
  people: ["bo", "cy"], groups: GROUPS, ...over,
});

beforeEach(() => saveSharing.mockClear());

describe("typedShare", () => {
  it("reads a group's or a built-in group's name or id as that group, and anything else as a person", () => {
    expect(typedShare("finance", GROUPS, "view")).toEqual({ kind: "group", id: "finance", level: "view", name: "Finance" });
    expect(typedShare(" Editor ", GROUPS, "edit")).toEqual({ kind: "role", id: "analyst", level: "edit", name: "Editor" });
    expect(typedShare("user:bo", GROUPS, "view")).toEqual({ kind: "person", id: "bo", level: "view", name: "bo" });
    expect(typedShare("   ", GROUPS, "view")).toBeNull();
  });
});

describe("SharePop", () => {
  it("lets the maker share it with a person to edit and a group to read, and saves exactly that", async () => {
    held = asMaker();
    const onChanged = vi.fn();
    render(<SharePop name="Olist orders" sheetId="s1" me="user:ana" onDone={vi.fn()} onChanged={onChanged} />);
    fireEvent.click(await screen.findByRole("radio", { name: "Only people chosen" }));
    expect(screen.getByText(/You made it, and can always read and edit it/)).toBeInTheDocument();
    const add = screen.getByRole("combobox", { name: "Add a person or a group" });
    fireEvent.change(add, { target: { value: "cy" } });
    fireEvent.click(screen.getByRole("radio", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.change(add, { target: { value: "Finance" } });
    fireEvent.click(screen.getByRole("radio", { name: "Read" }));
    fireEvent.keyDown(add, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(saveSharing).toHaveBeenCalledTimes(1));
    expect(saveSharing).toHaveBeenCalledWith("s1", "chosen", [
      { kind: "person", id: "cy", level: "edit", name: "cy" },
      { kind: "group", id: "finance", level: "view", name: "Finance" },
    ]);
    expect(await screen.findByText("Shared with the people and groups chosen")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("refuses the maker as a share, saying they always hold it", async () => {
    held = asMaker({ sharing: "chosen", shared_with: [{ kind: "person", id: "bo", level: "view", name: "bo" }] });
    render(<SharePop name="Olist orders" sheetId="s1" me="user:ana" onDone={vi.fn()} />);
    const add = await screen.findByRole("combobox", { name: "Add a person or a group" });
    fireEvent.change(add, { target: { value: "ana" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByRole("alert")).toHaveTextContent("You made it, and can always read and edit it.");
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();     // nothing changed
  });

  it("shows anyone else who it is shared with, what they may do, and that only its maker changes it", async () => {
    held = asMaker({
      sharing: "chosen", access: "view", may_change: false,
      shared_with: [{ kind: "person", id: "bo", level: "view", name: "bo" }, { kind: "group", id: "finance", level: "edit", name: "Finance" }],
    });
    render(<SharePop name="Olist orders" sheetId="s1" me="user:bo" onDone={vi.fn()} />);
    expect(await screen.findByText(/You can read it\. Only ana, who made it, can change who it is shared with\./)).toBeInTheDocument();
    expect(screen.getByText("can edit")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Add a person or a group" })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Only people chosen" })).not.toBeInTheDocument();
  });
});
