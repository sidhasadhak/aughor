// @vitest-environment jsdom
/**
 * Agent Ops · Overview, laid out to CLARITY: four figures first — each with its caveat as a chip, never dropped —
 * then what needs a person with its buttons on the row and the rest folded into a count, and the runs list
 * folding the same work ending the same way into one row with its count.
 *
 * And what the Activity tab folded into it (2026-10-13): the spend figure's calls and fallback share, the chart's
 * Runs | Tokens switch, the three token lists, the deep runs by question, and the two folds shut at the foot.
 *
 * Every API function the panel calls is stubbed: an unmocked one would reach the live API from jsdom.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TraceFocus } from "@/components/FleetOverviewPanel";
import type { FleetJob, FleetOverview, NeedsHumanRow } from "@/lib/api";
import { isBudgetStop, saidState } from "@/lib/runState";

/** The trace index's filter to one deep run — the wire's own name for it. */
const RUN_FILTER = "investigation_id";
const forRun = (c: unknown[]) => (c[0] as Record<string, unknown>)[RUN_FILTER];

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
  getUsageSummary: spy("getUsageSummary"),
  getActivityEvents: spy("getActivityEvents"),
  getTraces: spy("getTraces"),
  getTrace: spy("getTrace"),
  // The run list and one run's phases, stubbed as `runs` and `phases`.
  getInvestigationsList: spy("runs"),
  getInvestigationGraph: spy("phases"),
}));

/** Every stream the page opens (the kernel's job events always; the live events' tail only once its fold opens). */
const streams: string[] = [];
const tails = () => streams.filter(u => u.includes("/activity/stream"));
class _NoStream {
  onmessage: unknown = null; onerror: unknown = null; onopen: unknown = null; readyState = 0;
  constructor(url: string) { streams.push(url); }
  addEventListener() {} removeEventListener() {} close() {}
}
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

/** The usage read as the API serves it on theLook (2026-10-13), the models out of order as it sends them. */
function usage(over: Record<string, unknown> = {}) {
  const model = (provider: string, name: string, calls: number, tokens: number, failures = 0) => ({
    provider, model: name, calls, total_tokens: tokens, failures, failure_rate: failures / calls, mean_ms: 6_590,
    cost_usd: 0.01, cost_is_complete: true, calls_without_usage: 0 });
  return {
    measured: true, window, calls: 48, tokens: 344_850, cost_usd: 0.7541, unpriced_calls: 0, cost_is_complete: true,
    calls_without_usage: 6, usage_coverage: 0.875, fallback: { fell_back: 5, of_attributed: 48, rate: 0.104 },
    models: [model("anthropic", "claude-haiku-5-5", 6, 14_543, 4), model("anthropic", "claude-sonnet-5-5", 37, 281_018, 2),
      model("openrouter", "deepseek/deepseek-v4.1-flash", 5, 49_289), model("openai", "gpt-small", 1, 900)],
    sites: [
      { caller: "aughor.sql.writer:write", calls: 3, prompt_tokens: 110_881, total_tokens: 114_729, calls_without_usage: 0 },
      { caller: "aughor.explorer.agent:<lambda>", calls: 20, prompt_tokens: 80_885, total_tokens: 89_228, calls_without_usage: 0 },
      { caller: "aughor.agent.tool_loop:run_tool_loop", calls: 5, prompt_tokens: 34_776, total_tokens: 36_393, calls_without_usage: 0 },
      { caller: "aughor.judgment.seam:judge", calls: 2, prompt_tokens: 8_020, total_tokens: 9_342, calls_without_usage: 0 },
    ],
    roles: [{ role: "coder", calls: 39, total_tokens: 300_695 }, { role: "narrator", calls: 6, total_tokens: 25_377 },
      { role: "fast", calls: 3, total_tokens: 18_778 }],
    ...over,
  };
}

/** A daily automation's deep run, its question exactly as the store keeps it on theLook (2026-10-13): two blocks of
 *  grounding the code writes for the model, then what the person asked. */
const SCHEDULED_QUESTION = "[Scheduled-run context \u2014 written by code, not inferred]\nThis is a scheduled daily run at 2026-10-13T09:00Z.\nObserve 2026-10-05 (UTC), the most recent complete day given this automation's observation lag of 8 days \u2014 periods younger than that are configured as not yet reliable for this source.\nNever treat the current, in-progress period (today is 2026-10-13 UTC and it is partial by construction) as an observation period, and never compare a partial period against a complete one.\nSay in the report which period you observed AND that it is 8 days behind today (2026-10-13 UTC), because this source restates its most recent days. A reader must never have to guess why the newest figure you quote is dated earlier than today \u2014 undated, a lagged report is indistinguishable from a broken one.\nThis source has been measured still changing days up to 29 days old, and this automation reads at 8 by its own setting: the figures you quote may still move. Say so beside them, and never call a later change to the same day a business change.\n\n[Previous scheduled report \u2014 for consistency checking]\nThe previous run of this automation (2026-10-12T09:00Z) reported:\n\"Governed revenue on the observed day 2026-10-04 (8 days behind today, 2026-10-12, because this source restates recent days) was $20,563.66 on 303 orders, up 17.22% (+$3,021.60) on the restated prior day of $17,542.06 on 283 orders. The rise coincided with 327 items against 311 and an average item price of $62.89 against $56.41. Both figures remain subject to restatement for up to 29 days and should be re-read once the day settles. A figure in this answer could not be traced to the query results, so the sentence stating it was withheld.\"\nThat report's definition: revenue \u2014 computed as `SUM(sale_price)`; over rows where `status <> 'Cancelled'` (its declared filter); on order_items; over data spanning 2019-01-09 \u2192 2026-10-16; and order count computed as `COUNT(DISTINCT CASE WHEN status <> 'Cancelled' THEN order_id END)`.\nIf your current measurements DISAGREE with numbers that report states for the same periods, compare the definition first: if your figure is over a different formula or different rows (a status filter) than that report's, the difference is the DEFINITION \u2014 say which definition each figure is over, and do not call it a restatement. Only when the definition is the same has the SOURCE restated its own history \u2014 say that explicitly, with both values, instead of narrating the difference as a business change.\n\nWhat changed in theLook in the last day? Give me the top three findings with the numbers. Use the governed Revenue metric exactly as defined, including its status filter. Also measure the previous day's figures, so any change is quoted from the results rather than calculated.";

const deepRun = (id: string, question: string, started_at: string, over: Record<string, unknown> = {}) => ({
  id, question, connection_id: "c1", status: "complete", started_at, completed_at: started_at, headline: null,
  agent_id: "", ...over,
});

const range = { key: "24h" as const, since: null, until: null };
type Focus = TraceFocus | null;
const mount = (connections: { id: string; name: string }[] = [], traceFocus: Focus = null) =>
  render(<Theme><FleetOverviewPanel range={range}
    onBrush={() => {}} onClearBrush={() => {}} onOpenAttention={() => {}} connections={connections}
    traceFocus={traceFocus} /></Theme>);

beforeEach(() => {
  for (const k of Object.keys(calls)) delete calls[k];
  stubs.getFleetOverview = () => Promise.resolve(overview());
  stubs.getJobs = () => Promise.resolve([]);
  stubs.getNeedsHuman = () => Promise.resolve({ count: 0, sources: {}, rows: [] });
  stubs.getObsTimeseries = () => Promise.resolve({ measured: true, window, edges: [], group: "agent", measure: "runs",
    series: [], scanned: 0, attributed: 0, coverage: null });
  stubs.getUsageSummary = () => Promise.resolve(usage());
  stubs.getActivityEvents = () => Promise.resolve({ measured: true, events: [], window: null,
    kinds: { guardrail: 1_652, llm_call: 62, tool_call: 125, tool_call_result: 129, step: 32 } });
  stubs.getTraces = () => Promise.resolve({ measured: true, recording: true, traces: [], total: 2_478, scanned_events: 4_000 });
  stubs.getTrace = () => Promise.resolve(null);
  stubs.runs = () => Promise.resolve([]);
  stubs.phases = () => Promise.resolve(null);
  streams.length = 0;
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

  it("accepts and rejects an automation's approval by its proposal id, never the row's own id", async () => {
    stubs.getNeedsHuman = () => Promise.resolve({ count: 1, sources: {}, rows: needs(1) });
    stubs.acceptProposal = () => Promise.resolve({});
    stubs.rejectProposal = () => Promise.resolve(true);
    mount();
    const card = await screen.findByTestId("ao-needs");
    fireEvent.click(await within(card).findByRole("button", { name: "Accept" }));
    await vi.waitFor(() => expect(calls.acceptProposal).toHaveLength(1));
    fireEvent.click(await within(card).findByRole("button", { name: "Reject" }));
    await vi.waitFor(() => expect(calls.rejectProposal).toHaveLength(1));
    // the row is "r0"; the inbox resolves the proposal it carries, "p1"
    expect(calls.acceptProposal[0][0]).toBe("p1");
    expect(calls.rejectProposal[0][0]).toBe("p1");
  });

  it("opens what each waiting row is about: a paused run itself, a broken automation, an alert in Attention", async () => {
    const at = { since: "2026-10-11T20:00:00Z", waiting_ms: 60_000, connection_id: "c1" };
    stubs.getNeedsHuman = () => Promise.resolve({ count: 3, sources: {}, rows: [
      { ...at, source: "paused_run", id: "inv-7", title: "Why did revenue fall?", resolve: { feedback: "/investigations/inv-7/feedback" } },
      { ...at, source: "automation_broken", id: "a9:broken", title: "Hourly pulse — cannot dispatch: unknown trigger",
        resolve: { surface: "automation", automation_id: "a9", run_id: "r1" } },
      { ...at, source: "agent_alert", id: "e1", title: "Error rate: crossed 40%", resolve: { ack: "/obs/agent-alerts/events/e1/ack" } },
    ] as NeedsHumanRow[] });
    const opened: string[] = [];
    render(<Theme><FleetOverviewPanel range={range} onBrush={() => {}} onClearBrush={() => {}} connections={[]}
      traceFocus={null} onOpenInvestigation={id => opened.push(`run ${id}`)}
      onOpenAutomation={id => opened.push(`automation ${id}`)} onOpenAttention={() => opened.push("attention")} /></Theme>);
    const card = await screen.findByTestId("ao-needs");
    fireEvent.click(await within(card).findByRole("button", { name: "Open & resume" }));
    fireEvent.click(within(card).getByRole("button", { name: "Open automation" }));
    fireEvent.click(within(card).getByRole("button", { name: "Open in Attention" }));
    // the paused run's own id — "Open & resume" read an id the API never sends and only ever opened Attention
    expect(opened).toEqual(["run inv-7", "automation a9", "attention"]);
  });
});

describe("the runs list", () => {
  it("names a run in words — its kind as a phrase, its connection by name — with the raw title on hover", async () => {
    stubs.getJobs = (...a: unknown[]) => Promise.resolve((a[0] as { state?: string }).state === "active" ? [
      job({ id: "w", kind: "alert_proposals", title: "alert_proposals", state: "RUNNING", conn_id: "c0ffee12" }),
      job({ id: "x", kind: "exploration", title: "Exploring c0ffee12", state: "RUNNING", conn_id: "c0ffee12" }),
    ] : []);
    mount([{ id: "c0ffee12", name: "LuxExperience" }]);
    const rows = await screen.findAllByTestId("ao-active-run");
    expect(rows.map(r => r.firstElementChild?.firstElementChild?.textContent)).toEqual(["Proposing alerts", "Exploring LuxExperience"]);
    expect(within(rows[0]).getByTitle("alert_proposals")).toHaveTextContent("Proposing alerts");
    expect(within(rows[1]).getByTitle("Exploring c0ffee12")).toHaveTextContent("Exploring LuxExperience");
    expect(screen.queryByText("alert_proposals")).toBeNull();
    expect(screen.queryByText(/c0ffee12/)).toBeNull();
  });

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

describe("what the Activity tab folded in", () => {
  it("says the calls and the share that fell back beside the spend, the share in amber when any did", async () => {
    mount();
    const spend = await screen.findByTestId("ao-fig-spend");
    await within(spend).findByTestId("ao-fallback");
    expect(within(spend).getByTestId("ao-spend-calls")).toHaveTextContent("48 calls");
    expect(within(spend).getByTestId("ao-fallback")).toHaveTextContent("10% fell back");
    expect(within(spend).getByTestId("ao-fallback")).toHaveStyle({ color: "var(--amb4)" });
    // One read for the spend figure and the token lists, over the page's range.
    expect(calls.getUsageSummary?.[0]?.[0]).toEqual({ range: "24h" });
  });

  it("does not wear amber when nothing fell back, and says nothing of a share no call recorded", async () => {
    stubs.getUsageSummary = () => Promise.resolve(usage({ fallback: { fell_back: 0, of_attributed: 48, rate: 0 } }));
    const { unmount } = mount();
    const share = await screen.findByTestId("ao-fallback");
    expect(share).toHaveTextContent("0% fell back");
    expect(share).not.toHaveStyle({ color: "var(--amb4)" });
    unmount();
    stubs.getUsageSummary = () => Promise.resolve(usage({ fallback: { fell_back: 0, of_attributed: 0, rate: null } }));
    mount();
    await screen.findByTestId("ao-spend-calls");
    expect(screen.queryByTestId("ao-fallback")).toBeNull();
  });

  it("says a usage read that failed — on the figure and where the lists would be, never as empty lists", async () => {
    stubs.getUsageSummary = () => Promise.reject(new Error("502 from the API"));
    mount();
    expect(await screen.findByTestId("ao-spend-calls-failed")).toHaveTextContent("calls not read");
    expect(await screen.findByText(/Could not read where the tokens went/)).toBeInTheDocument();
    expect(screen.queryByText("No model calls in this range.")).toBeNull();
  });

  it("switches the one chart between runs by agent and tokens by model, reading tokens only once asked", async () => {
    stubs.getObsTimeseries = (...a: unknown[]) => {
      const p = a[0] as { group?: string };
      const series = p.group === "model"
        ? [{ key: "claude-sonnet-5-5", label: "claude-sonnet-5-5", values: [0, 90_000], total: 90_000 },
           { key: "deepseek-v4.1-flash", label: "deepseek-v4.1-flash", values: [27_000, 0], total: 27_000 }]
        : [{ key: "scout", label: "Explorer", values: [1, 0], total: 1 }, { key: "curator", label: "Curator", values: [0, 1], total: 1 }];
      return Promise.resolve({ measured: true, window, edges: ["2026-10-11T00:00:00Z", "2026-10-11T01:00:00Z"],
        group: p.group ?? "agent", measure: "x", series, scanned: 0, attributed: 0, coverage: p.group === "model" ? 0.875 : null });
    };
    mount();
    const chart = await screen.findByTestId("ao-chart");
    await within(chart).findByRole("button", { name: /Explorer/ });
    expect(chart).toHaveAttribute("aria-label", "Runs by agent");
    expect((calls.getObsTimeseries ?? []).some(c => (c[0] as { group?: string }).group === "model")).toBe(false);

    fireEvent.click(within(chart).getByRole("radio", { name: "Tokens by model" }));
    await within(chart).findByRole("button", { name: /claude-sonnet-5-5/ });
    expect(chart).toHaveAttribute("aria-label", "Tokens by model");
    const read = (calls.getObsTimeseries ?? []).find(c => (c[0] as { group?: string }).group === "model")![0];
    expect(read).toEqual({ group: "model", measure: "tokens", range: "24h" });
    expect(within(chart).queryByRole("button", { name: /Explorer/ })).toBeNull();
    expect(chart).toHaveTextContent("88% of calls named a model");
    expect(within(chart).queryByText(/background runs/)).toBeNull();

    fireEvent.click(within(chart).getByRole("radio", { name: "Runs by agent" }));
    await within(chart).findByRole("button", { name: /Explorer/ });
  });

  it("lists the tokens by model, by role and by where in the code — the top three each, the rest behind all", async () => {
    mount();
    const models = await screen.findByTestId("ao-usage-models");
    const rows = within(models).getAllByTestId("ao-usage-models-row");
    // Ranked by tokens, not in the order the API sent them.
    expect(rows.map(r => r.firstElementChild?.firstElementChild?.textContent))
      .toEqual(["claude-sonnet-5-5", "deepseek/deepseek-v4.1-flash", "claude-haiku-5-5"]);
    expect(rows[2]).toHaveTextContent("67% failed");
    fireEvent.click(within(models).getByRole("button", { name: "top 3 of 4 · all ›" }));
    expect(within(models).getAllByTestId("ao-usage-models-row")).toHaveLength(4);

    const roles = screen.getByTestId("ao-usage-roles");
    expect(within(roles).getAllByTestId("ao-usage-roles-row").map(r => r.firstElementChild?.firstElementChild?.textContent))
      .toEqual(["coder", "narrator", "fast"]);
    expect(within(roles).queryByRole("button", { name: /all/ })).toBeNull();

    const sites = screen.getByTestId("ao-usage-sites");
    // As the data spells them; a call site opens no events (the tail cannot be filtered by one).
    expect(within(sites).getAllByTestId("ao-usage-sites-row")[0]).toHaveTextContent("aughor.sql.writer:write");
    expect(sites).toHaveTextContent("prompt tokens");
    expect(within(sites).queryByRole("button", { name: /Explore/ })).toBeNull();
  });

  it("opens the live events filtered to a model when its row is explored", async () => {
    mount();
    const models = await screen.findByTestId("ao-usage-models");
    const fold = screen.getByTestId("ao-fold-events");
    expect(fold).toHaveAttribute("data-open", "false");
    fireEvent.click(within(within(models).getAllByTestId("ao-usage-models-row")[0]).getByRole("button", { name: /Explore/ }));
    expect(fold).toHaveAttribute("data-open", "true");
    await vi.waitFor(() => expect((calls.getActivityEvents ?? []).some(c =>
      (c[0] as { model?: string }).model === "claude-sonnet-5-5")).toBe(true));
    const read = (calls.getActivityEvents ?? []).find(c => (c[0] as { model?: string }).model)![0] as Record<string, unknown>;
    expect(read).toMatchObject({ model: "claude-sonnet-5-5", provider: "anthropic", range: "24h" });
    expect(within(fold).getByRole("button", { name: "filtered to claude-sonnet-5-5 — clear" })).toBeInTheDocument();
  });
});

describe("the deep runs, by their question", () => {
  it("titles a scheduled run by what the person asked, never by the grounding, and folds its repeats", async () => {
    stubs.runs = () => Promise.resolve([
      deepRun("9ee01977", SCHEDULED_QUESTION, "2026-10-13T09:00:37Z"),
      deepRun("d3ab0467", SCHEDULED_QUESTION.replace("2026-10-13T09:00Z", "2026-10-12T09:00Z"), "2026-10-12T09:00:45Z"),
      deepRun("f7a6d188", "What is causing delivery delays?", "2026-10-10T08:21:22Z"),
      deepRun("d6e4b65b", "What is causing delivery delays?", "2026-10-10T01:20:03Z"),
      deepRun("c0", "What is DAU for last month?", "2026-10-08T21:53:31Z", { kind: "chat" }),
    ]);
    mount();
    const card = await screen.findByTestId("ao-deep-runs");
    const rows = await within(card).findAllByTestId("ao-deep-run");
    expect(rows.map(r => within(r).getByTestId("ao-deep-run-title").textContent))
      .toEqual(["What changed in theLook in the last day?", "What is causing delivery delays?"]);
    expect(within(rows[0]).getByTestId("ao-deep-run-scheduled")).toHaveTextContent("scheduled");
    expect(rows[0]).toHaveTextContent("×2");
    expect(rows[1]).toHaveTextContent("asked");
    expect(within(rows[1]).queryByTestId("ao-deep-run-scheduled")).toBeNull();
    // The plumbing never reaches the screen's text — only the hover carries the whole question.
    expect(card.textContent).not.toMatch(/Scheduled-run context|Previous scheduled report/);
    // A conversation is not a deep run.
    expect(card.textContent).not.toMatch(/DAU/);
  });

  it("opens a row on its phases and, beside them, the trace the index names for it", async () => {
    stubs.runs = () => Promise.resolve([deepRun("9ee01977", SCHEDULED_QUESTION, "2026-10-13T09:00:37Z")]);
    // A scheduled run runs inside its automation's trace — the index names it; the run's own id has none.
    stubs.getTraces = (...a: unknown[]) => Promise.resolve(forRun(a)
      ? { measured: true, recording: true, traces: [{ trace_id: "25c6cf71" }] }
      : { measured: true, recording: true, traces: [], total: 2_478, scanned_events: 4_000 });
    mount();
    const row = (await screen.findAllByTestId("ao-deep-run"))[0];
    fireEvent.click(within(row).getByRole("button", { name: "Open" }));
    await within(row).findByTestId("ao-deep-run-detail");
    await vi.waitFor(() => expect(calls.getTrace?.[0]?.[0]).toBe("25c6cf71"));
    expect(calls.phases?.[0]?.[0]).toBe("9ee01977");
    expect((calls.getTraces ?? []).some(c => forRun(c) === "9ee01977")).toBe(true);
  });

  it("falls back to the run's own id when the index names no trace for it — an asked run's trace IS its id", async () => {
    stubs.runs = () => Promise.resolve([deepRun("f7a6d188", "What is causing delivery delays?", "2026-10-10T08:21:22Z")]);
    mount();
    const row = (await screen.findAllByTestId("ao-deep-run"))[0];
    fireEvent.click(within(row).getByRole("button", { name: "Open" }));
    await vi.waitFor(() => expect(calls.getTrace?.[0]?.[0]).toBe("f7a6d188"));
    // The log holds none under that id either: said, not "select a trace".
    expect(await within(row).findByText("The log holds no trace under this id.")).toBeInTheDocument();
  });

  it("says a failed read of the deep runs, never that there are none", async () => {
    stubs.runs = () => Promise.reject(new Error("502 from the API"));
    mount();
    expect(await screen.findByText(/Could not read the deep runs/)).toBeInTheDocument();
    expect(screen.queryByText(/No deep runs/)).toBeNull();
  });
});

describe("the two folds at the foot", () => {
  it("are shut until asked for, and nothing inside them reads or streams — only what they hold is counted", async () => {
    mount();
    const events = await screen.findByTestId("ao-fold-events");
    const traces = screen.getByTestId("ao-fold-traces");
    expect(events).toHaveAttribute("data-open", "false");
    expect(traces).toHaveAttribute("data-open", "false");
    expect(screen.queryByTestId("ao-fold-events-body")).toBeNull();
    expect(screen.queryByTestId("ao-fold-traces-body")).toBeNull();
    // Each fold's count — one small read each, said as read.
    await within(events).findByText(/2\.0K recent events · 1\.7K of them guardrail checks/);
    await within(traces).findByText(/2,478 traces in the newest 4\.0K events/);
    expect(calls.getActivityEvents).toEqual([[{ limit: 1 }]]);
    expect(calls.getTraces).toEqual([[{ limit: 1 }]]);
    expect(tails()).toHaveLength(0);

    fireEvent.click(within(events).getByRole("button", { name: /Show/ }));
    expect(events).toHaveAttribute("data-open", "true");
    await vi.waitFor(() => expect(tails()).toHaveLength(1));
    expect(screen.getByTestId("ao-fold-events-body")).toBeInTheDocument();
  });

  it("says no trace count when the index did not say what matched — never the page's own length", async () => {
    stubs.getTraces = () => Promise.resolve({ measured: true, recording: true, traces: [{ trace_id: "t1" }] });
    mount();
    const traces = await screen.findByTestId("ao-fold-traces");
    await vi.waitFor(() => expect(calls.getTraces).toHaveLength(1));
    await screen.findByTestId("ao-figures");
    expect(traces).not.toHaveTextContent(/\d+ traces?/);
  });

  it("opens every trace on the one another layer opened, and scrolls it into view", async () => {
    const scrolled: Element[] = [];
    const before = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element) { scrolled.push(this); };
    try {
      mount([], { investigationId: "9ee01977" });
      const traces = await screen.findByTestId("ao-fold-traces");
      expect(traces).toHaveAttribute("data-open", "true");
      expect(screen.getByTestId("ao-fold-events")).toHaveAttribute("data-open", "false");
      await vi.waitFor(() => expect(scrolled).toContain(traces));
      await vi.waitFor(() => expect((calls.getTraces ?? []).some(c => forRun(c) === "9ee01977")).toBe(true));
      // "Every trace", narrowed to one deep analysis's, says so and lets go.
      fireEvent.click(within(traces).getByRole("button", { name: "one deep analysis's traces — show all" }));
      expect(within(traces).queryByRole("button", { name: /show all/ })).toBeNull();
    } finally {
      Element.prototype.scrollIntoView = before;
    }
  });

  it("opens on a trace by its id, too", async () => {
    mount([], { traceId: "25c6cf71" });
    expect(await screen.findByTestId("ao-fold-traces")).toHaveAttribute("data-open", "true");
    await vi.waitFor(() => expect(calls.getTrace?.[0]?.[0]).toBe("25c6cf71"));
  });
});

// A run its budget stopped is said so, not "cancelled" (the Olist study, Gap 20): the kernel records it CANCELLED and keeps
// the cause in its error; Agent Ops reads the cause and never folds a budget stop into a person's cancel of the same run.
const budgetJob = (id: string, state: string, error: string | null = null): FleetJob => ({
  id, kind: "exploration", state, conn_id: "workspace", canvas_id: null, created_at: "2026-10-22T22:50:00Z",
  started_at: null, finished_at: null, error, agent: { agent: "Scout", blurb: "", icon: "" }, title: "Explore olist",
  cost: null, duration_ms: null,
});

describe("a budget stop", () => {
  it("is its own said state; a person's cancel and a failure stay as they were", () => {
    expect(isBudgetStop("budget exceeded: token budget (200,000 tokens)")).toBe(true);
    expect(saidState("CANCELLED", "budget exceeded: token budget (200,000 tokens)")).toBe("BUDGET_STOP");
    expect(saidState("CANCELLED", null)).toBe("CANCELLED");
    expect(saidState("FAILED", "budget exceeded: time budget (900s)")).toBe("FAILED");
  });

  it("is folded apart from a person's cancel of the same run", () => {
    const groups = foldRuns([budgetJob("a", "CANCELLED", "budget exceeded: token budget (200,000 tokens)"), budgetJob("b", "CANCELLED")]);
    expect(groups.map(g => g.state).sort()).toEqual(["BUDGET_STOP", "CANCELLED"]);
  });
});
