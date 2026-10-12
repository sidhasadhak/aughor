// @vitest-environment jsdom
/**
 * The SQL editor's empty results pane is a starting point (CLARITY, 2026-10-12): recent runs folded by statement,
 * the saved queries, the largest tables — each row a way to act. The audit read is stubbed; the assertions are about
 * what the pane lists and what a click hands back, never the network.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { AuditRecord, SavedQuery } from "@/lib/api";

const api = vi.hoisted(() => ({ getQueryHistory: vi.fn() }));
vi.mock("@/lib/api", () => api);

import { QueryStart } from "./QueryStart";

const run = (id: string, sql: string, over: Partial<AuditRecord> = {}): AuditRecord => ({
  id, ts: new Date(Date.now() - 3 * 3600_000).toISOString(), connection_id: "8233e4fd",
  hypothesis_id: "query_workbench", sql_digest: sql, sql_full: sql, verdict: "safe", row_count: 5, duration_ms: 768.86,
  error: null, ...over,
});
const saved = (id: string, name: string, spec: Record<string, unknown> = {}): SavedQuery => ({
  id, connection_id: "8233e4fd", name, sql: "SELECT 1", spec, created_at: "", updated_at: "",
});

function mount(over: Partial<Parameters<typeof QueryStart>[0]> = {}) {
  const p = {
    connId: "8233e4fd", connectionName: "theLook", refreshKey: 0,
    saved: [saved("q1", "Revenue by country"), saved("q2", "Orders by brand", { primaryTable: "orders" })],
    tables: [{ name: "thelook.users", rowCount: 100000 }, { name: "thelook.events", rowCount: 2426096 }],
    onOpenRun: vi.fn(), onOpenSaved: vi.fn(), onInsert: vi.fn(), onShowRuns: vi.fn(), ...over,
  };
  render(<QueryStart {...p} />);
  return p;
}

beforeEach(() => {
  api.getQueryHistory.mockReset();
});

describe("the starting point", () => {
  it("lists recent runs once each, with the person's own statement — and opens it", async () => {
    api.getQueryHistory.mockResolvedValue([
      run("a", "SELECT * FROM (SELECT country FROM users) __q LIMIT 501"),
      run("b", "SELECT * FROM (SELECT country FROM users) __q LIMIT 501"),
      run("c", "DROP SCHEMA s CASCADE", { verdict: "blocked", row_count: 0, duration_ms: 0,
        error: "DROP statements are not permitted in read-only mode" }),
    ]);
    const p = mount();
    const card = await screen.findByTestId("query-start-runs");
    await waitFor(() => expect(within(card).getAllByRole("button")).toHaveLength(2));
    expect(api.getQueryHistory).toHaveBeenCalledWith("8233e4fd", 30);
    expect(card).toHaveTextContent("SELECT country FROM users");
    expect(card).toHaveTextContent("×2");
    expect(card).toHaveTextContent("blocked");
    expect(card).not.toHaveTextContent("safe");
    fireEvent.click(within(card).getByText("SELECT country FROM users"));
    expect(p.onOpenRun).toHaveBeenCalledWith("SELECT country FROM users");
  });

  it("says a failed read as a failed read, not as nothing run", async () => {
    api.getQueryHistory.mockRejectedValue(new Error("Reading the query history: 503"));
    mount();
    const card = await screen.findByTestId("query-start-runs");
    await waitFor(() => expect(card).toHaveTextContent("503"));
    expect(card).not.toHaveTextContent("Nothing has run");
  });

  it("opens a saved query the Saved menu's way, and says which editor it was written in", async () => {
    api.getQueryHistory.mockResolvedValue([]);
    const p = mount();
    const card = screen.getByTestId("query-start-saved");
    expect(card).toHaveTextContent("Revenue by country");
    expect(card).toHaveTextContent("visual");
    fireEvent.click(within(card).getByText("Revenue by country"));
    expect(p.onOpenSaved).toHaveBeenCalledWith(expect.objectContaining({ id: "q1" }));
    expect(await screen.findByText("Nothing has run on this connection yet.")).toBeInTheDocument();
  });

  it("a Saved list that could not be read says so, rather than 'none saved'", () => {
    api.getQueryHistory.mockResolvedValue([]);
    mount({ saved: null });
    expect(screen.getByTestId("query-start-saved")).toHaveTextContent("could not be read");
  });

  it("puts a table at the cursor, the largest first", () => {
    api.getQueryHistory.mockResolvedValue([]);
    const p = mount();
    const card = screen.getByTestId("query-start-tables");
    const names = within(card).getAllByRole("button").map(b => b.textContent);
    expect(names).toEqual(["thelook.events", "thelook.users"]);
    expect(card).toHaveTextContent("2.4M");
    fireEvent.click(within(card).getByText("thelook.events"));
    expect(p.onInsert).toHaveBeenCalledWith("thelook.events");
  });
});
