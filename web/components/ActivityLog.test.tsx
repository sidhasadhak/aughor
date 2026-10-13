// @vitest-environment jsdom
/**
 * Activity, redone to CLARITY.md as a log read like a document: one line of what it holds and how the run stands, what
 * needs a person, then the queries under a heading per day, newest first. A run repeated back to back folds into one row
 * that counts it; a failed read says so instead of passing for an empty log.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ExplorationEpisode, ExplorationStatus } from "@/lib/api";

const api = vi.hoisted(() => ({
  getExplorationEpisodes: vi.fn(),
  getExplorationStatus: vi.fn(),
  fixAll: vi.fn(),
}));
vi.mock("@/lib/api", async importOriginal => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));
vi.mock("@/lib/events", () => ({ subscribeKernelEvents: () => () => {} }));

import { ActivityLog } from "./ActivityLog";

const HOUR = 3600;
// Noon today, local: the runs below sit on two days whatever hour the suite runs at.
const noon = new Date();
noon.setHours(12, 0, 0, 0);
const now = noon.getTime() / 1000;
let n = 0;
const ep = (over: Partial<ExplorationEpisode>): ExplorationEpisode => ({
  episode_id: "run-1", connection_id: "c1", phase: "domain_intel", ts: now - HOUR + n++,
  think: "Domain Customer | angle=Return Rate:headline | What is total Return Rate?",
  sql: "SELECT AVG(returned) FROM `bigquery-public-data.thelook_ecommerce.order_items`",
  observation: "1 rows\ncols: ['f0_']\n['9.9']", ...over,
});

/** The status fields the page reads (the findings count's wire name is a retired word; it is left out here). */
const STATUS = {
  connection_id: "c1", phase: "complete", paused: false, tables_total: 7, columns_total: 75, joins_total: 8,
  queries_executed: 26, facts_discovered: 49, started_at: null, completed_at: null, error: null, interrupted: false,
} as unknown as ExplorationStatus;

const FAILED = "ERROR: 400 Syntax error: Expected \"(\" but got keyword GROUP at [1:37]; reason: invalidQuery, location: query";

function log() {
  const same = ep({ ts: now - 2 * HOUR });
  return [
    // yesterday: a percentile query that failed twice, on two columns
    ep({ phase: "exploration", ts: now - 24 * HOUR, think: "Percentiles for users.age.", sql: "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY age) FROM users", observation: FAILED }),
    ep({ phase: "exploration", ts: now - 24 * HOUR + 1, think: "Percentiles for users.id.", sql: "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY id) FROM users", observation: FAILED }),
    // today: the same question run three times back to back, then a synthesis the log cut short
    same, { ...same, ts: same.ts + 1 }, { ...same, ts: same.ts + 2 },
    ep({ think: "[synth:share] What is the ratio of the total cost of inventory f", sql: "SELECT EXTRACT(YEAR FROM created_at) FROM inventory_items" }),
  ];
}

const view = (connectionId = "c1") => render(<Theme><ActivityLog connectionId={connectionId} isActive /></Theme>);

afterEach(() => { vi.clearAllMocks(); n = 0; });

describe("ActivityLog", () => {
  it("reads as a log: a line of what it holds, the run's state, then the queries by day, newest first", async () => {
    api.getExplorationEpisodes.mockResolvedValue(log());
    api.getExplorationStatus.mockResolvedValue(STATUS);
    view();
    await screen.findByText(/What the explorer ran here, newest first/);
    expect(screen.getByText(/6 queries since/)).toBeInTheDocument();
    expect(within(screen.getByTestId("run-state")).getByText("complete")).toBeInTheDocument();
    expect(screen.getByText(/last run 26 queries · 49 facts · 7 tables · 8 joins/)).toBeInTheDocument();

    const list = screen.getByTestId("activity-log");
    // two days, each under its own heading, today's first
    expect(list.querySelectorAll("[data-list-group]")).toHaveLength(2);
    const rows = within(list).getAllByTestId("activity-row");
    // three identical runs fold into one row that counts them: 6 runs, 4 rows
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("What is the ratio of the total cost of inventory f…");
    expect(rows[0]).toHaveTextContent("synthesis · inventory_items");
    expect(rows[1]).toHaveTextContent("What is total Return Rate?");
    expect(within(rows[1]).getByText("×3")).toBeInTheDocument();
    expect(rows[1]).toHaveTextContent("Customer questions · order_items");
    expect(rows[1]).toHaveTextContent("1 row");
    expect(rows[2]).toHaveTextContent("failed");
    expect(rows[2]).toHaveTextContent("400 Syntax error: Expected \"(\" but got keyword GROUP at [1:37]");
    expect(rows[2]).not.toHaveTextContent("reason: invalidQuery");
  });

  it("opens a row on its statement and its result", async () => {
    api.getExplorationEpisodes.mockResolvedValue(log());
    api.getExplorationStatus.mockResolvedValue(STATUS);
    view();
    const rows = await screen.findAllByTestId("activity-row");
    fireEvent.click(within(rows[2]).getAllByRole("button")[0]);
    expect(within(rows[2]).getByText(/PERCENTILE_CONT\(0.5\) WITHIN GROUP \(ORDER BY id\)/)).toBeInTheDocument();
    expect(within(rows[2]).getByText("Retry with a fix")).toBeInTheDocument();
  });

  it("puts the failed queries under Needs you, and Fix all repairs every one of them", async () => {
    api.getExplorationEpisodes.mockResolvedValue(log());
    api.getExplorationStatus.mockResolvedValue(STATUS);
    api.fixAll.mockResolvedValue({ summary: { total: 2, fixed: 2, saved: 1, flagged: 0, failed: 0 }, results: [] });
    view();
    const needs = await screen.findByTestId("needs-failed");
    expect(needs).toHaveTextContent("2 queries failed");
    fireEvent.click(within(needs).getByRole("button", { name: "Fix all 2" }));
    await waitFor(() => expect(api.fixAll).toHaveBeenCalledTimes(1));
    expect(api.fixAll.mock.calls[0][1]).toHaveLength(2);
    expect(await within(needs).findByText(/fixed 2 of 2 · saved 1/)).toBeInTheDocument();
  });

  it("with nothing failed or stopped, Needs you is one muted line", async () => {
    api.getExplorationEpisodes.mockResolvedValue(log().filter(e => !e.observation.startsWith("ERROR")));
    api.getExplorationStatus.mockResolvedValue(STATUS);
    view();
    const needs = await screen.findByTestId("activity-needs");
    await waitFor(() => expect(needs).toHaveAttribute("data-waiting", "false"));
    expect(needs).toHaveTextContent("Nothing needs you");
  });

  it("an interrupted run waits on a person, with Continue on its row", async () => {
    api.getExplorationEpisodes.mockResolvedValue(log());
    api.getExplorationStatus.mockResolvedValue({ ...STATUS, phase: "join_verification", interrupted: true,
      interrupted_note: "Interrupted — the run stopped when the platform restarted. Its progress is saved: Continue resumes it." });
    view();
    const row = await screen.findByTestId("needs-interrupted");
    expect(row).toHaveTextContent("The run stopped at joins");
    expect(within(row).getByRole("button", { name: "Continue" })).toBeInTheDocument();
  });

  it("says a failed read and offers to read again — never 'nothing has run'", async () => {
    api.getExplorationEpisodes.mockRejectedValue(new Error("Reading the log failed (500)"));
    api.getExplorationStatus.mockResolvedValue(STATUS);
    view();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Reading the log failed \(500\)/);
    expect(screen.getByRole("button", { name: /Retry/ })).toBeInTheDocument();
    expect(screen.queryByText(/Nothing has run here yet/)).toBeNull();
  });

  it("without a connection says so and reads nothing", () => {
    view("");
    expect(screen.getByText(/No connection is open/)).toBeInTheDocument();
    expect(api.getExplorationEpisodes).not.toHaveBeenCalled();
  });
});
