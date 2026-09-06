// @vitest-environment jsdom
/**
 * Experiments — the panel renders the SERVER's derived pairs and its per-case
 * reading; it derives nothing itself.
 *
 * Two claims worth pinning:
 * * **The paired subset is the headline.** A cell that never reached a case is
 *   `unrun`, excluded — and when any case was excluded the panel says so, because
 *   totals over unequal populations are the lie this surface exists to end.
 * * **The empty state teaches how an experiment comes to exist** (two runs, one
 *   axis) rather than offering a button this build cannot honestly provide —
 *   model-backed targets are not runnable from the API yet.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { EvalExperimentsPanel } from "@/components/EvalExperimentsPanel";
import type { EvalExperiment, ExperimentCompare } from "@/lib/api";

const api = vi.hoisted(() => ({
  getEvalExperiments: vi.fn(),
  compareEvalExperiment: vi.fn(),
  getEvalSuites: vi.fn(),
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
       cell: "off", pass_rate: 1, correct: 3, correctness_known: 5, total: 5 },
  b: { run_id: "r-on", status: "succeeded", started_at: "2026-09-06T11:00:00Z",
       cell: "on", pass_rate: 1, correct: 4, correctness_known: 5, total: 5 },
};

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

beforeEach(() => {
  vi.clearAllMocks();
  api.getEvalSuites.mockResolvedValue([{ id: "su1", name: "Golden SQL" }]);
  api.getEvalExperiments.mockResolvedValue([experiment]);
  api.compareEvalExperiment.mockResolvedValue(compare);
});

it("lists a derived pair with its axis and the a→b accuracy", async () => {
  render(<EvalExperimentsPanel />);
  expect(await screen.findByText("explore.route_wide")).toBeInTheDocument();
  expect(screen.getByText(/Golden SQL/)).toBeInTheDocument();
  expect(screen.getByText(/3\/5/)).toBeInTheDocument();
  expect(screen.getByText(/4\/5/)).toBeInTheDocument();
});

it("teaches how an experiment comes to exist when there are none", async () => {
  api.getEvalExperiments.mockResolvedValue([]);
  render(<EvalExperimentsPanel />);
  expect(await screen.findByText("No experiments yet")).toBeInTheDocument();
  expect(screen.getByText(/two runs of one suite/i)).toBeInTheDocument();
});

it("opens the per-case reading, leads with the paired subset, and names the exclusion", async () => {
  render(<EvalExperimentsPanel />);
  fireEvent.click(await screen.findByText("explore.route_wide"));
  await waitFor(() => expect(api.compareEvalExperiment).toHaveBeenCalledWith("r-off", "r-on"));

  expect(await screen.findByText("Paired cases")).toBeInTheDocument();
  expect(screen.getByText("revenue by region?")).toBeInTheDocument();
  expect(screen.getByText("gained")).toBeInTheDocument();
  // One case was unrun in a cell — the panel must say it was excluded, not fold it in.
  expect(screen.getByText("Unrun (excluded)")).toBeInTheDocument();
});
