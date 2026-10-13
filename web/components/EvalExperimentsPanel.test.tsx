// @vitest-environment jsdom
/**
 * Experiments — the panel renders the SERVER's derived pairs and its per-case
 * reading; the only thing it works out itself is whether a pair's difference
 * clears the baseline's own noise floor, from the baseline's replicates.
 *
 * Claims worth pinning:
 * * **A row is A against B and whether the gap is real.** A baseline run once has
 *   no floor, so the pair says it cannot be called — never a bare "+2.0 pts".
 * * **The paired subset is the headline.** A cell that never reached a case is
 *   `unrun`, excluded — and when any case was excluded the panel says so, because
 *   totals over unequal populations are the lie this surface exists to end.
 * * **The empty state teaches how an experiment comes to exist** (two runs, one
 *   axis) rather than offering a button this build cannot honestly provide —
 *   model-backed targets are not runnable from the API yet.
 */
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { EvalExperimentsPanel } from "@/components/EvalExperimentsPanel";
import type { EvalExperiment, EvalRun, ExperimentCompare } from "@/lib/api";

const api = vi.hoisted(() => ({
  getEvalExperiments: vi.fn(),
  compareEvalExperiment: vi.fn(),
  getEvalSuites: vi.fn(),
  getEvalRuns: vi.fn(),
  getSystemFlags: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

// antd's table measures scrollbars and observes resize — neither exists in jsdom, and
// per web/AGENTS.md the honest assertion is the render HANDOFF: what rows the panel
// hands its table, not what rc-table draws with them.
vi.mock("@/components/AugTable", () => ({
  AugTable: ({ dataSource }: { dataSource: Array<Record<string, unknown>> }) => (
    <div data-testid="table">
      {dataSource.map((r, i) => (
        <div key={i}>
          <span>{String(r.question ?? "")}</span>
          <span>{String(r.kind ?? "")}</span>
        </div>
      ))}
    </div>
  ),
}));

const experiment: EvalExperiment = {
  suite_id: "su1",
  axis: { kind: "flag", name: "explore.route_wide" },
  a: { run_id: "r-off", status: "succeeded", started_at: "2026-09-06T10:00:00Z",
       cell: "off", pass_rate: 0.8, correct: 3, correctness_known: 5, total: 5 },
  b: { run_id: "r-on", status: "succeeded", started_at: "2026-09-06T11:00:00Z",
       cell: "on", pass_rate: 1, correct: 4, correctness_known: 5, total: 5 },
};

const run = (id: string, cell: string, pass: number): EvalRun => ({
  id, suite_id: "su1", status: "succeeded", iterations: 1, started_at: "2026-09-05T10:00:00Z", finished_at: null,
  trace_id: "", config: { cell }, summary: { pass_rate: pass },
});

const compare: ExperimentCompare = {
  suite_id: "su1",
  axis: { kind: "flag", name: "explore.route_wide" },
  a: experiment.a, b: experiment.b,
  accuracy: { a: { correct: 3, known: 5 }, b: { correct: 4, known: 5 },
              paired: { cases: 4, a_correct: 3, b_correct: 4 } },
  flips: { same: 3, gained: 1, lost: 0, other: 0, unrun: 1 },
  rows: [{ case_id: "c1", question: "revenue by region?", a: "wrong", b: "correct",
           kind: "gained", a_sql: "SELECT 1", b_sql: "SELECT 2", a_error: "", b_error: "" }],
  sql_available: true,
};

const panel = () => render(<Theme><EvalExperimentsPanel /></Theme>);

beforeEach(() => {
  vi.clearAllMocks();
  api.getEvalSuites.mockResolvedValue([{ id: "su1", name: "Golden SQL", description: "" }]);
  api.getEvalExperiments.mockResolvedValue([experiment]);
  api.compareEvalExperiment.mockResolvedValue(compare);
  api.getEvalRuns.mockResolvedValue([run("r-off", "off", 0.8), run("r-on", "on", 1)]);
  api.getSystemFlags.mockResolvedValue({});
});

it("lists a derived pair as A against B, with its axis in words and the a→b accuracy", async () => {
  panel();
  expect(await screen.findByText("explore route wide")).toBeInTheDocument();
  expect(screen.getByText(/Golden SQL/)).toBeInTheDocument();
  expect(screen.getByText(/3\/5 → 4\/5/)).toBeInTheDocument();
  expect(screen.getByText("+20.0 pts")).toBeInTheDocument();
});

it("will not call a difference when the baseline ran once — there is no floor", async () => {
  panel();
  expect(await screen.findByTestId("experiment-verdict")).toHaveTextContent("can't call — Off ran once");
  expect(screen.getByTestId("fig-clears-value")).toHaveTextContent("0 of 1");
});

it("calls a difference wider than the baseline's own spread, and names noise inside it", async () => {
  api.getEvalRuns.mockResolvedValue([run("r-off", "off", 0.8), run("r-off2", "off", 0.82), run("r-off3", "off", 0.79)]);
  panel();
  expect(await screen.findByTestId("experiment-verdict")).toHaveTextContent("On better by 20.0 pts");

  api.getEvalExperiments.mockResolvedValue([{ ...experiment, b: { ...experiment.b, pass_rate: 0.81 } }]);
  fireEvent.click(screen.getByText("Refresh"));
  await waitFor(() => expect(screen.getByTestId("experiment-verdict")).toHaveTextContent("within noise"));
});

it("teaches how an experiment comes to exist when there are none", async () => {
  api.getEvalExperiments.mockResolvedValue([]);
  panel();
  expect(await screen.findByText(/No experiments yet/)).toBeInTheDocument();
  expect(screen.getByText(/two runs of one suite/i)).toBeInTheDocument();
});

it("opens the per-case reading behind Details, leads with the paired subset, and names the exclusion", async () => {
  panel();
  fireEvent.click(await screen.findByText("Details"));
  await waitFor(() => expect(api.compareEvalExperiment).toHaveBeenCalledWith("r-off", "r-on"));

  expect(await screen.findByText("Paired cases")).toBeInTheDocument();
  expect(screen.getByText("revenue by region?")).toBeInTheDocument();
  expect(screen.getByText("gained")).toBeInTheDocument();
  // One case was unrun in a cell — the panel must say it was excluded, not fold it in.
  expect(screen.getByText("Left out")).toBeInTheDocument();
  expect(screen.getByText("unrun by one side — excluded")).toBeInTheDocument();
});
