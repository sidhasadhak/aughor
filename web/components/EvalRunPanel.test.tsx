// @vitest-environment jsdom
/**
 * Runs — a measurement is a BAND, never a point. Repeated runs of one suite under one set-up are its replicates, so
 * they fold into ONE row with ×N, and the row's score is the band ("80.3% ± 1.5 · 3 replicates"); a set-up run once
 * says it has no band. The figures above count what the rows hold, and a run of a suite that is gone is named so —
 * never by its id.
 */
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { EvalRunPanel } from "@/components/EvalRunPanel";
import type { EvalRun } from "@/lib/api";

const api = vi.hoisted(() => ({
  getEvalRuns: vi.fn(),
  getEvalRun: vi.fn(),
  getEvalSuites: vi.fn(),
  getEvalSuite: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));
vi.mock("@/lib/events", () => ({ subscribeKernelEvents: () => () => {} }));
vi.mock("@/components/AugTable", () => ({
  AugTable: ({ dataSource }: { dataSource: Array<Record<string, unknown>> }) => (
    <div data-testid="table">{dataSource.map((r, i) => <div key={i}>{String(r.case_id)}</div>)}</div>
  ),
}));

let n = 0;
const run = (suite: string, cell: string | null, status: string, pass: number | null, at: string, note = ""): EvalRun => ({
  id: `r${++n}`, suite_id: suite, status, iterations: 1, started_at: at, finished_at: null, trace_id: "",
  config: cell ? { cell } : {},
  summary: pass == null ? (note ? { note } as EvalRun["summary"] : {})
    : { pass_rate: pass, total: 100, stable_pass: Math.round(pass * 100), flaky: 0, errors: 0 },
});

const RUNS = [
  run("s1", "readback_on", "succeeded", 0.8, "2026-07-27T08:00:00Z"),
  run("s1", "readback_on", "succeeded", 0.82, "2026-07-27T09:00:00Z"),
  run("s1", "readback_on", "failed", null, "2026-07-27T09:30:00Z", "TRANSPORT failure, not a measurement"),
  run("s1", "readback_on", "succeeded", 0.79, "2026-07-27T10:00:00Z"),
  run("s1", "readback_off", "succeeded", 0.9, "2026-07-27T11:00:00Z"),
  run("gone1234abcd", null, "succeeded", 1, "2026-07-20T11:00:00Z"),
];

const panel = () => render(<Theme><EvalRunPanel /></Theme>);

beforeEach(() => {
  vi.clearAllMocks();
  n = 0;
  api.getEvalRuns.mockResolvedValue(RUNS);
  api.getEvalSuites.mockResolvedValue([{ id: "s1", name: "Returns consistency", description: "" }]);
});

it("opens on figures that count runs, set-ups with a band, and runs that did not finish", async () => {
  panel();
  expect(await screen.findByTestId("fig-runs-value")).toHaveTextContent("6");
  expect(screen.getByTestId("fig-banded-value")).toHaveTextContent("1 of 3");
  expect(screen.getByTestId("fig-held-value")).toHaveTextContent("1 of 1");
  expect(screen.getByTestId("fig-unfinished-value")).toHaveTextContent("1");
});

it("folds repeated runs of one set-up into one row with ×N and the band, and says when there is no band", async () => {
  panel();
  const rows = await screen.findAllByTestId("run-group");
  expect(rows).toHaveLength(3);

  const on = rows.find(r => r.textContent?.includes("readback on"))!;
  expect(within(on).getByTestId("run-count")).toHaveTextContent("×4");
  expect(within(on).getByTestId("run-band")).toHaveTextContent("80.3% ± 1.5");
  expect(on).toHaveTextContent("3 replicates");
  expect(on).toHaveTextContent("holds within 3.0 pts");
  expect(on).toHaveTextContent("1 failed");

  const off = rows.find(r => r.textContent?.includes("readback off"))!;
  expect(off).toHaveTextContent("1 replicate — no band");
});

it("names a run of a suite that is gone, never by its id", async () => {
  panel();
  await screen.findAllByTestId("run-group");
  expect(screen.getByText("Suite no longer listed")).toBeInTheDocument();
  expect(screen.queryByText(/gone1234abcd/)).not.toBeInTheDocument();
});

it("keeps each run behind Details, with a failed run's own note still said", async () => {
  panel();
  const rows = await screen.findAllByTestId("run-group");
  const on = rows.find(r => r.textContent?.includes("readback on"))!;
  expect(within(on).queryAllByTestId("run-line")).toHaveLength(0);
  fireEvent.click(within(on).getByText("Details"));
  expect(within(on).getAllByTestId("run-line")).toHaveLength(4);
  expect(within(on).getByText("TRANSPORT failure, not a measurement")).toBeInTheDocument();
});
