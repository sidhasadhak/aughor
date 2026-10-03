// @vitest-environment jsdom
/**
 * Arc AO-3 — a fetch that REJECTS must never render the empty state.
 *
 * Measured 2026-10-03: five Agent Ops surfaces answered a failed read with "nothing here"
 * — the Overview's run chart and "Needs you", the roster lists, the Automations list and
 * an agent's Runs tab — teaching the reader the data did not exist. Each site here is
 * driven with its fetch rejecting, and the assertion is two-sided: the failure is said with
 * a Retry, and the empty-state sentence is absent.
 *
 * Every API function a mounted panel calls is stubbed: an unmocked one would reach the
 * live API from jsdom (the repo's own trap), and a test that passes because :8000 answered
 * is not a test.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FleetOverview, UserAgent } from "@/lib/api";

const boom = () => Promise.reject(new Error("502 from the API"));
const quiet = () => Promise.resolve([]);

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    // roster
    getAgents: (...a: unknown[]) => stubs.getAgents(...a),
    listUserAgents: (...a: unknown[]) => stubs.listUserAgents(...a),
    getFleetOverview: (...a: unknown[]) => stubs.getFleetOverview(...a),
    // fleet
    getJobs: quiet,
    getNeedsHuman: (...a: unknown[]) => stubs.getNeedsHuman(...a),
    getObsTimeseries: (...a: unknown[]) => stubs.getObsTimeseries(...a),
    // agent page
    getAgentObservability: (...a: unknown[]) => stubs.getAgentObservability(...a),
    // automations
    getAutomations: (...a: unknown[]) => stubs.getAutomations(...a),
    getAutomationRuns: quiet,
    getConnections: quiet,
    getGrants: () => Promise.resolve({ grants: [] }),
    getProposals: () => Promise.resolve({ proposals: [] }),
  };
});

const stubs: Record<string, (...a: unknown[]) => Promise<unknown>> = {
  getAgents: quiet, listUserAgents: quiet, getFleetOverview: boom,
  getNeedsHuman: boom, getObsTimeseries: boom, getAgentObservability: boom,
  getAutomations: boom,
};

// The Overview opens a live SSE stream on mount; jsdom has no EventSource, and this test
// is about the fetches, so a silent stand-in is enough.
class _NoStream {
  onmessage: unknown = null; onerror: unknown = null;
  addEventListener() {} removeEventListener() {} close() {}
}
(globalThis as unknown as { EventSource: unknown }).EventSource = _NoStream;

const { AgentRuns, CustomAgentOverview, AgenticAgentsPanel } =
  await import("@/components/AgenticAgentsPanel");
const { FleetOverviewPanel } = await import("@/components/FleetOverviewPanel");
const { AutomationsPanel } = await import("@/components/AutomationsPanel");

const agent: UserAgent = {
  id: "ua_1", name: "The Look Analyst", instructions: "", connection_id: "c1",
  schema_scope: "", doc_ids: [], pack_ids: [], tool_grants: [], owner: "", enabled: true,
  last_eval: null, config_rev: "", eval_basis: "current" as UserAgent["eval_basis"],
  created_at: "", updated_at: "",
};

const range = { key: "24h" as const, since: null, until: null };

function overviewFixture(): FleetOverview {
  const window = { since: "2026-10-02T00:00:00Z", until: "2026-10-03T00:00:00Z",
    bucket_seconds: 3600, buckets: 24, range: "24h" };
  return {
    tiles: {
      active_jobs: 0, window_minutes: 1440, runs_started: 0, runs_per_min: 0,
      p95_duration_ms: null, p50_duration_ms: null, error_rate: null, failed_runs: 0,
      orphaned_runs: 0, tokens: { total: 0, metered_runs: 0, unmetered_runs: 0, per_hour: null },
      concurrency: { max_concurrent_jobs: 0, unbounded_kinds: [] }, runner_runs: 0,
      include_runners: false, window,
      cost: { usd: null, unpriced_calls: null, is_complete: false, calls: 0 },
    } as unknown as FleetOverview["tiles"],
    rows: [], runners: [], window, edges: [], session_log_recording: true,
  };
}

describe("a rejected read is said, never rendered as the empty state", () => {
  it("the agent's Runs tab", async () => {
    stubs.getAgentObservability = boom;
    render(<AgentRuns agent={agent} range={range} />);
    await screen.findByText(/Could not read this agent's runs/);
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText(/No runs in/)).toBeNull();
  });

  it("the agent's Overview figures", async () => {
    stubs.getAgentObservability = boom;
    render(<CustomAgentOverview agent={agent} range={range} />);
    await screen.findByText(/Could not read this agent's figures/);
    expect(screen.queryByText(/No runs in/)).toBeNull();
    expect(screen.queryByText(/No observability data/)).toBeNull();
  });

  it("the roster lists", async () => {
    stubs.getAgents = boom;
    stubs.listUserAgents = quiet;
    stubs.getFleetOverview = () => Promise.resolve(overviewFixture());
    render(<AgenticAgentsPanel range={range} />);
    await screen.findByText(/Could not read the agent roster/);
    expect(screen.queryByText(/Loading built-in agents/)).toBeNull();
  });

  it("the roster's run figures", async () => {
    stubs.getAgents = quiet;
    stubs.listUserAgents = quiet;
    stubs.getFleetOverview = boom;
    render(<AgenticAgentsPanel range={range} />);
    await screen.findByText(/Could not read the roster's run figures/);
  });

  it("the Overview's run chart and what needs a human", async () => {
    stubs.getFleetOverview = () => Promise.resolve(overviewFixture());
    stubs.getObsTimeseries = boom;
    stubs.getNeedsHuman = boom;
    render(<FleetOverviewPanel range={range} onBrush={() => {}} onClearBrush={() => {}} />);
    await screen.findByText(/Could not read the run chart/);
    await screen.findByText(/Could not read what needs a human/);
    expect(screen.queryByText(/No agent runs in this window/)).toBeNull();
    expect(screen.queryByText(/Nothing needs a human/)).toBeNull();
  });

  it("the Automations list", async () => {
    stubs.getAutomations = boom;
    render(<AutomationsPanel connId="c1" />);
    await waitFor(() => expect(screen.getByText(/Could not read the automations/)).toBeInTheDocument());
    expect(screen.queryByText(/No automations yet/)).toBeNull();
    expect(screen.queryByText(/No automations on this connection/)).toBeNull();
  });
});
