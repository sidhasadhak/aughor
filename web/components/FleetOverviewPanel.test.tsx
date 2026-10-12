// @vitest-environment jsdom
/**
 * Agent Ops · Overview, laid out to CLARITY: four figures first — each with its caveat as a chip, never dropped —
 * then what needs a person with its buttons on the row and the rest folded into a count, and the runs list
 * folding the same work ending the same way into one row with its count.
 *
 * Every API function the panel calls is stubbed: an unmocked one would reach the live API from jsdom.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FleetJob, FleetOverview, NeedsHumanRow } from "@/lib/api";

const calls: Record<string, unknown[][]> = {};
const stubs: Record<string, (...a: unknown[]) => Promise<unknown>> = {};
const spy = (name: string) => (...a: unknown[]) => { (calls[name] ??= []).push(a); return stubs[name](...a); };

vi.mock("@/lib/api", async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getFleetOverview: spy("getFleetOverview"),
  getJobs: spy("getJobs"),
  getNeedsHuman: spy("getNeedsHuman"),
  getObsTimeseries: spy("getObsTimeseries"),
  acceptProposal: spy("acceptProposal"),
  rejectProposal: spy("rejectProposal"),
  cancelJob: spy("cancelJob"),
  patchAgent: spy("patchAgent"),
  patchUserAgent: spy("patchUserAgent"),
}));

class _NoStream { onmessage: unknown = null; onerror: unknown = null; addEventListener() {} removeEventListener() {} close() {} }
(globalThis as unknown as { EventSource: unknown }).EventSource = _NoStream;

const { FleetOverviewPanel, duration, foldRuns } = await import("@/components/FleetOverviewPanel");
const { BUILT_IN_AGENT_KIND } = await import("@/lib/api");

const window = { since: "2026-10-11T00:00:00Z", until: "2026-10-12T00:00:00Z", bucket_seconds: 3600, buckets: 24, range: "24h" };

function overview(over: Partial<FleetOverview["tiles"]> = {}): FleetOverview {
  return {
    tiles: {
      active_jobs: 0, window_minutes: 1440, runs_started: 10, runs_per_min: 0.01,
      p95_duration_ms: 600_164, p50_duration_ms: 3_208, error_rate: 0, failed_runs: 0, orphaned_runs: 0,
      tokens: { total: 397_794, metered_runs: 10, unmetered_runs: 0, per_hour: 16_575 },
      concurrency: { max_concurrent_jobs: 8, unbounded_kinds: [] }, runner_runs: 10_774, include_runners: false,
      truncated: false, window, cost: { usd: 0.0226, unpriced_calls: 485, is_complete: false, calls: 497 },
      ...over,
    } as FleetOverview["tiles"],
    rows: [
      { kind: BUILT_IN_AGENT_KIND, id: "scout", name: "Explorer", role: "Autonomous data explorer", icon: "", lane: "", enabled: true,
        job_kinds: ["exploration"], spend_source: "job_metering", runs: 5, failed: 0, orphaned: 0, tokens: 299_234, queries: 3,
        metered_runs: 5, unmetered_runs: 0, last_run_at: "2026-10-11T22:56:24Z", spark: [0, 1, 4] },
      { kind: BUILT_IN_AGENT_KIND, id: "curator", name: "Curator", role: "Semantic-layer keeper", icon: "", lane: "", enabled: false,
        job_kinds: ["profile"], spend_source: "job_metering", runs: 0, failed: 0, orphaned: 0, tokens: 0, queries: 0,
        metered_runs: 0, unmetered_runs: 0, last_run_at: null, spark: [] },
    ] as FleetOverview["rows"],
    runners: [], window, edges: [], session_log_recording: true,
  };
}

const needs = (n: number): NeedsHumanRow[] => Array.from({ length: n }, (_, i) => ({
  // An automation's approval carries its proposal, so it is decided on the row; a paused run opens its run.
  source: i === 0 ? "automation_approval" : "paused_run", id: `r${i}`, title: `monitor:Units Sold watch: pause the feed ${i}?`,
  connection_id: "c1", since: "2026-10-11T20:00:00Z", waiting_ms: 3_900_000, resolve: (i === 0 ? { proposal_id: "p1" } : {}) as Record<string, string>,
}));

const job = (over: Partial<FleetJob>): FleetJob => ({
  id: "j", kind: "exploration", state: "SUCCEEDED", conn_id: "c1", canvas_id: null, created_at: "2026-10-11T22:00:00Z",
  started_at: null, finished_at: null, error: null, agent: { agent: "Explorer", blurb: "", icon: "" }, title: "Exploring theLook",
  cost: null, duration_ms: 3_000, ...over,
});

const range = { key: "24h" as const, since: null, until: null };
const mount = () => render(<Theme><FleetOverviewPanel range={range} onBrush={() => {}} onClearBrush={() => {}}
  onOpenAttention={() => {}} /></Theme>);

beforeEach(() => {
  for (const k of Object.keys(calls)) delete calls[k];
  stubs.getFleetOverview = () => Promise.resolve(overview());
  stubs.getJobs = () => Promise.resolve([]);
  stubs.getNeedsHuman = () => Promise.resolve({ count: 0, sources: {}, rows: [] });
  stubs.getObsTimeseries = () => Promise.resolve({ measured: true, window, edges: [], group: "agent", measure: "runs",
    series: [], scanned: 0, attributed: 0, coverage: null });
});

describe("the figures row", () => {
  it("opens on four figures: runs, failed, running now and model spend", async () => {
    mount();
    const figures = await screen.findByTestId("ao-figures");
    expect(within(figures).getByTestId("ao-fig-runs-value")).toHaveTextContent("10");
    expect(within(figures).getByTestId("ao-fig-runs")).toHaveTextContent("typical 3.2 s · slow 10 min");
    expect(within(figures).getByTestId("ao-fig-failed-value")).toHaveTextContent("0");
    expect(within(figures).getByTestId("ao-fig-live")).toHaveTextContent("1 of 2 agents on · 1 paused");
    expect(within(figures).getByTestId("ao-fig-spend-value")).toHaveTextContent("$0.02");
    expect(within(figures).getAllByRole("button")).toHaveLength(4); // each figure is the door to where it comes from
  });

  it("says each caveat as a chip: unpriced calls, a capped read, runs a restart cut off, unmetered runs", async () => {
    stubs.getFleetOverview = () => Promise.resolve(overview({ truncated: true, orphaned_runs: 2, failed_runs: 1,
      tokens: { total: 1000, metered_runs: 3, unmetered_runs: 4, per_hour: null } }));
    mount();
    expect(await screen.findByTestId("ao-unpriced")).toHaveTextContent("2% of calls priced");
    expect(screen.getByTestId("ao-fig-spend")).toHaveTextContent("Model spend · at least");
    expect(screen.getByTestId("ao-fig-spend")).toHaveTextContent("4 unmetered");
    expect(screen.getByTestId("ao-fig-runs")).toHaveTextContent("a floor");
    expect(screen.getByTestId("ao-fig-failed")).toHaveTextContent("+2 cut off by a restart");
  });

  it("opens where a figure comes from, with the list whose count equals it", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("ao-fig-runs"));
    const drawer = screen.getByRole("dialog", { name: "Where this number comes from" });
    expect(drawer).toHaveTextContent("10,774 background runs counted apart");
    expect(within(drawer).getByRole("button", { name: /Open these runs/ })).toBeInTheDocument();
  });
});

describe("needs you", () => {
  it("is one muted line on a plain card when nothing waits", async () => {
    mount();
    expect(await screen.findByText("Nothing waits on a person.")).toBeInTheDocument();
    expect(screen.getByTestId("ao-needs")).toHaveAttribute("data-waiting", "false");
  });

  it("puts each row's buttons on the row, shows three and folds the rest into a count", async () => {
    stubs.getNeedsHuman = () => Promise.resolve({ count: 5, sources: {}, rows: needs(5) });
    mount();
    const card = await screen.findByTestId("ao-needs");
    await within(card).findByText("+2 more in Attention");
    expect(card).toHaveAttribute("data-waiting", "true");
    expect(card).toHaveTextContent("5 items waiting");
    expect(within(card).getAllByRole("button", { name: "Accept" })).toHaveLength(1);
    expect(within(card).getAllByRole("button", { name: "Open & resume" })).toHaveLength(2);
    // the action key's name leads; its sentence is the muted line under it
    expect(within(card).getAllByText("Units Sold watch")).toHaveLength(3);
  });
});

describe("the runs list", () => {
  it("reads the range one kind of agent work at a time, and folds the same run ending the same way", async () => {
    stubs.getJobs = (...a: unknown[]) => {
      const p = a[0] as { kind?: string; state?: string };
      if (p.state === "active") return Promise.resolve([]);
      return Promise.resolve(p.kind === "exploration"
        ? [job({ id: "a" }), job({ id: "b" }), job({ id: "c", state: "FAILED", error: "boom" })] : []);
    };
    mount();
    fireEvent.click(await screen.findByRole("radio", { name: "All" }));
    const groups = await screen.findAllByTestId("ao-run-group");
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveTextContent("×2");
    expect(groups[0]).toHaveTextContent("succeeded");
    expect(groups[1]).toHaveTextContent("failed");
    const kinds = (calls.getJobs ?? []).map(c => (c[0] as { kind?: string }).kind).filter(Boolean).sort();
    expect(kinds).toEqual(["exploration", "profile"]); // the built-in agents' kinds, never the background check's
    expect((calls.getJobs ?? []).every(c => (c[0] as { range?: string; state?: string }).range === "24h"
      || (c[0] as { state?: string }).state === "active")).toBe(true);
  });
});

describe("pure helpers", () => {
  it("says a run's length as a person reads it", () => {
    expect(duration(820)).toBe("820 ms");
    expect(duration(3_208)).toBe("3.2 s");
    expect(duration(600_164)).toBe("10 min");
    expect(duration(3_900_000)).toBe("1 h 5 min");
    expect(duration(null)).toBe("—");
  });

  it("folds runs by agent, title and how they ended — a scheduled run's plumbing never becomes its title", () => {
    const scheduled = "[Scheduled-run context — written by code, not inferred]\nThis is a scheduled daily run.\n\nWhat changed?";
    const groups = foldRuns([job({ id: "1", title: scheduled }), job({ id: "2", title: scheduled }), job({ id: "3" })]);
    expect(groups.map(g => [g.title, g.runs.length])).toEqual([["What changed?", 2], ["Exploring theLook", 1]]);
  });
});
