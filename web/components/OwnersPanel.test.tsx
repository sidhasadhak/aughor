// CB-3 — the Owners panel: an unresolved owner offers a Link box; linking sends the typed
// principal and reloads; a linked owner shows its principal and Unlink. The API is mocked —
// a jsdom test must never reach the live API (registry-not-test-isolated).
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { OwnersPanel } from "./OwnersPanel";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, listOwners: vi.fn(), linkOwner: vi.fn(), unlinkOwner: vi.fn() };
});

const unresolved = { owner_text: "Ana (logistics)", owner_key: "ana (logistics)", uses: [{ kind: "metric", id: "revenue", connection_id: "" }],
  principal: null, resolved: false, how: "unresolved" as const, linked_by: "", linked_at: "" };
const linked = { ...unresolved, principal: "user:ana@corp", resolved: true, how: "linked" as const, linked_by: "user:admin@corp" };
const asWritten = { owner_text: "group:finance", owner_key: "group:finance", uses: [{ kind: "metric", id: "margin", connection_id: "" }],
  principal: "group:finance", resolved: true, how: "principal" as const, linked_by: "", linked_at: "" };

describe("OwnersPanel", () => {
  beforeEach(() => { vi.mocked(api.listOwners).mockReset(); vi.mocked(api.linkOwner).mockReset(); vi.mocked(api.unlinkOwner).mockReset(); });

  it("shows every owner with its uses and marks the unresolved one", async () => {
    vi.mocked(api.listOwners).mockResolvedValue({ owners: [unresolved, asWritten], links: [] });
    render(<OwnersPanel connectionId="c1" />);
    expect(await screen.findByText("Ana (logistics)")).toBeTruthy();
    expect(screen.getByText("unresolved")).toBeTruthy();
    expect(screen.getAllByText("1 metric")).toHaveLength(2);
    expect(screen.getAllByText("group:finance")).toHaveLength(2);   // the owner text and its principal badge
    expect(screen.getByText("as written")).toBeTruthy();
    expect(screen.getByText(/2 owners in use · 1 unresolved/)).toBeTruthy();
    expect(api.listOwners).toHaveBeenCalledWith("c1");
  });

  it("links the typed principal, once, and reloads", async () => {
    vi.mocked(api.listOwners).mockResolvedValueOnce({ owners: [unresolved], links: [] })
      .mockResolvedValueOnce({ owners: [linked], links: [] });
    vi.mocked(api.linkOwner).mockResolvedValue({ owner_text: "Ana (logistics)", owner_key: "ana (logistics)", principal: "user:ana@corp", linked_by: "", linked_at: "" });
    render(<OwnersPanel />);
    const box = await screen.findByLabelText("Principal for Ana (logistics)");
    fireEvent.change(box, { target: { value: "user:ana@corp" } });
    fireEvent.click(screen.getByText("Link"));
    await waitFor(() => expect(api.linkOwner).toHaveBeenCalledWith("Ana (logistics)", "user:ana@corp"));
    expect(await screen.findByText("user:ana@corp")).toBeTruthy();
    expect(screen.getByText("linked by user:admin@corp")).toBeTruthy();
    expect(screen.getByText("Unlink")).toBeTruthy();
    expect(screen.queryByText("unresolved")).toBeNull();
  });

  it("an empty box links nothing, and a refused link is said", async () => {
    vi.mocked(api.listOwners).mockResolvedValue({ owners: [unresolved], links: [] });
    vi.mocked(api.linkOwner).mockRejectedValue(new Error("the principal must be user:…, group:… or agent:…"));
    render(<OwnersPanel />);
    await screen.findByText("Ana (logistics)");
    fireEvent.click(screen.getByText("Link"));
    expect(api.linkOwner).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Principal for Ana (logistics)"), { target: { value: "Ana" } });
    fireEvent.click(screen.getByText("Link"));
    expect(await screen.findByRole("alert")).toHaveTextContent("the principal must be");
  });
});
