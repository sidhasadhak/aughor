// @vitest-environment jsdom
/**
 * Suites — read first: four figures, then what needs a person (a suite whose last run fell, one never run) with Run
 * on the row, then each suite as one line naming what it runs as and where — a connection by its name, never an id.
 * Authoring stays behind New suite / Add case: no form is open in the reading view.
 */
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { EvalSuitesPanel } from "@/components/EvalSuitesPanel";
import type { EvalRun, EvalSuite } from "@/lib/api";

const api = vi.hoisted(() => ({
  getEvalSuites: vi.fn(),
  getEvalSuite: vi.fn(),
  getEvalRuns: vi.fn(),
  getEvaluators: vi.fn(),
  getConnections: vi.fn(),
  runEvalSuite: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

const suite = (id: string, name: string, target: string, connection_id: string, description = ""): EvalSuite => ({
  id, name, description, target, connection_id, config: {}, created_at: "2026-07-24T10:00:00Z",
});
const SUITES = [
  suite("sa", "Returns regression", "reference", "c-ops"),
  suite("sb", "Golden revenue", "reference", "c-ops"),
  suite("sc", "Monitor equivalence", "equivalence", ""),
  suite("sd", "Answer consistency", "reference", "c-ops", "These measure CONSISTENCY, NOT correctness."),
];
const CASES: Record<string, number> = { sa: 8, sb: 2, sc: 9, sd: 22 };

let n = 0;
const run = (suite_id: string, pass: number, at: string): EvalRun => ({
  id: `r${++n}`, suite_id, status: "succeeded", iterations: 1, started_at: at, finished_at: null, trace_id: "",
  config: {}, summary: { pass_rate: pass, total: 8, stable_pass: Math.round(pass * 8), flaky: 0 },
});

const panel = () => render(<Theme><EvalSuitesPanel /></Theme>);

beforeEach(() => {
  vi.clearAllMocks();
  n = 0;
  api.getEvalSuites.mockResolvedValue(SUITES);
  api.getEvalSuite.mockImplementation(async (id: string) => ({
    ...SUITES.find(s => s.id === id)!,
    cases: Array.from({ length: CASES[id] }, (_, i) => ({ id: `${id}-c${i}`, suite_id: id, question: `q${i}`,
      artifact: "SELECT 1", expected: {}, tags: [], created_at: "" })),
  }));
  api.getEvalRuns.mockResolvedValue([
    run("sa", 1, "2026-07-27T08:00:00Z"),
    run("sa", 0.875, "2026-07-28T08:00:00Z"),
    run("sc", 1, "2026-07-27T09:00:00Z"),
    run("sd", 1, "2026-07-27T10:00:00Z"),
  ]);
  api.getEvaluators.mockResolvedValue({ evaluators: [], deterministic_count: 0 });
  api.getConnections.mockResolvedValue([{ id: "c-ops", name: "Aughor Ops" }]);
  api.runEvalSuite.mockResolvedValue({ pass_rate: 1, stable_pass: 2, total: 2 });
});

it("opens on four figures: suites, cases, passed in full at the last run, never run", async () => {
  panel();
  expect(await screen.findByTestId("fig-suites-value")).toHaveTextContent("4");
  expect(screen.getByTestId("fig-suites")).toHaveTextContent("3 have run · 1 never");
  await waitFor(() => expect(screen.getByTestId("fig-cases-value")).toHaveTextContent("41"));
  expect(screen.getByTestId("fig-full-value")).toHaveTextContent("2 of 3");
  expect(screen.getByTestId("fig-never-value")).toHaveTextContent("1");
});

it("puts a suite that fell and a suite never run under Needs you, each with Run on its row", async () => {
  panel();
  const needs = await screen.findByLabelText("Needs you");
  await waitFor(() => expect(needs).toHaveAttribute("data-waiting", "true"));
  const fell = within(needs).getByTestId("needs-fell");
  expect(fell).toHaveTextContent("Returns regression fell to 87.5%");
  expect(fell).toHaveTextContent("from 100.0%");
  const never = within(needs).getByTestId("needs-never");
  expect(never).toHaveTextContent("Golden revenue has never run");

  fireEvent.click(within(never).getByText("Run"));
  await waitFor(() => expect(api.runEvalSuite).toHaveBeenCalledWith("sb", { iterations: 1 }));
});

it("lists each suite on one line, naming its connection and saying when the app cannot run it", async () => {
  panel();
  const rows = await screen.findAllByTestId("suite-row");
  expect(rows).toHaveLength(4);
  const ops = rows.find(r => r.textContent?.includes("Golden revenue"))!;
  expect(ops).toHaveTextContent("Aughor Ops");
  expect(ops).not.toHaveTextContent("c-ops");
  const eq = rows.find(r => r.textContent?.includes("Monitor equivalence"))!;
  expect(eq).toHaveTextContent("runs outside the app");
  expect(within(eq).queryByText("Run")).not.toBeInTheDocument();
  expect(within(eq).getByTestId("suite-result")).toHaveTextContent("100.0%");
  // The suite's own caveat — its pass rate is consistency, not correctness — reaches the row.
  const cons = rows.find(r => r.textContent?.includes("Answer consistency"))!;
  expect(cons).toHaveTextContent("consistency, not correctness");
});

it("keeps authoring behind New suite — no form is open in the reading view", async () => {
  panel();
  await screen.findAllByTestId("suite-row");
  expect(screen.queryByPlaceholderText(/Golden SQL — revenue questions/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("New suite"));
  expect(screen.getByPlaceholderText(/Golden SQL — revenue questions/)).toBeInTheDocument();
});
