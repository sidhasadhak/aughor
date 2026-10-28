/**
 * The Evals screen's arithmetic: a measurement is a band over replicates of ONE set-up, a set-up run once has no
 * band (not a band of zero), and a difference is only read when it is wider than the baseline's own spread — the
 * backend fidelity module's rules, mirrored so the screen cannot report jitter as an effect.
 */
import { describe, expect, it } from "vitest";

import type { EvalExperiment, EvalRun } from "@/lib/api";
import {
  bandOf, bandText, floorOf, groupRuns, runState, suiteState, verdictOf, axisWords, targetWords, runBlock,
} from "./evalSummary";

const NOW = Date.parse("2026-10-13T12:00:00Z");
let seq = 0;
function run(suite: string, cell: string | null, status: string, pass: number | null, at: string, extra: Record<string, unknown> = {}): EvalRun {
  seq += 1;
  return {
    id: `r${seq}`, suite_id: suite, status, iterations: 1, started_at: at, finished_at: null, trace_id: "",
    config: cell ? { cell } : {},
    summary: pass == null ? {} : { pass_rate: pass, total: 10, stable_pass: Math.round(pass * 10), flaky: 0, ...extra },
  };
}

describe("a band", () => {
  it("is the mean and the spread of the replicates", () => {
    const b = bandOf([0.8, 0.82, 0.79])!;
    expect(b.n).toBe(3);
    expect(b.spread).toBeCloseTo(0.03);
    expect(bandText(b)).toBe("80.3% ± 1.5");
  });

  it("is absent with nothing measured, and a single run has no floor — not a floor of zero", () => {
    expect(floorOf(bandOf([]))).toBe("none");
    expect(floorOf(bandOf([0.9]))).toBe("single");
    expect(bandText(bandOf([0.9]))).toBe("90.0%");
  });

  it("holds within 5 points and is noisy beyond them", () => {
    expect(floorOf(bandOf([0.8, 0.85]))).toBe("held");
    expect(floorOf(bandOf([0.6818, 0.8636]))).toBe("noisy");
  });
});

describe("runs folded by set-up", () => {
  const runs = [
    run("s1", "on", "succeeded", 0.8, "2026-07-27T10:00:00Z"),
    run("s1", "on", "succeeded", 0.82, "2026-07-27T11:00:00Z"),
    run("s1", "on", "failed", null, "2026-07-27T12:00:00Z"),
    run("s1", "off", "succeeded", 0.9, "2026-07-27T13:00:00Z"),
    run("s1", "on", "running", null, "2026-07-27T14:00:00Z"),
  ];

  it("folds repeats of one suite under one set-up into one group, newest first", () => {
    const gs = groupRuns(runs, NOW);
    expect(gs.map(g => [g.cell, g.runs.length])).toEqual([["on", 4], ["off", 1]]);
    const on = gs[0];
    expect(on.band?.n).toBe(2);
    expect(on.failed).toBe(1);
    // Marked running two months ago: it never finished.
    expect(on.unfinished).toBe(1);
    expect(on.running).toBe(0);
  });

  it("says a run started a moment ago is running, not stuck", () => {
    expect(runState(run("s1", null, "running", null, "2026-10-13T11:30:00Z"), NOW)).toBe("running");
  });
});

describe("a suite's last result", () => {
  it("reads a fall wider than the floor, against the run before of the same set-up", () => {
    const st = suiteState("s1", [
      run("s1", null, "succeeded", 1, "2026-07-28T10:00:00Z"),
      run("s1", null, "succeeded", 0.875, "2026-07-28T11:00:00Z"),
    ], NOW);
    expect(st.lastRate).toBe(0.875);
    expect(st.regressed).toEqual({ from: 1, to: 0.875 });
  });

  it("does not call a different set-up's lower score a fall", () => {
    const st = suiteState("s1", [
      run("s1", "off", "succeeded", 0.9, "2026-07-28T10:00:00Z"),
      run("s1", "on", "succeeded", 0.7, "2026-07-28T11:00:00Z"),
    ], NOW);
    expect(st.regressed).toBeNull();
  });

  it("has no last run when the suite never ran", () => {
    expect(suiteState("s9", [], NOW).last).toBeNull();
  });
});

describe("an A/B pair against the noise floor", () => {
  const pair = (a: number | null, b: number | null, bStatus = "succeeded"): EvalExperiment => ({
    suite_id: "s1", axis: { kind: "flag", name: "closed_loop" },
    a: { run_id: "ra", status: "succeeded", started_at: "2026-07-27T10:00:00Z", cell: "off", pass_rate: a, correct: 0, correctness_known: 0, total: 10 },
    b: { run_id: "rb", status: bStatus, started_at: "2026-07-27T11:00:00Z", cell: "on", pass_rate: b, correct: 0, correctness_known: 0, total: 10 },
  });
  const reps = (...v: number[]) => v.map((p, i) => run("s1", "off", "succeeded", p, `2026-07-2${i}T10:00:00Z`));

  it("cannot be called when the baseline ran once", () => {
    expect(verdictOf(pair(0.75, 0.73), []).kind).toBe("no-floor");
  });

  it("cannot be called when the baseline disagrees with itself by more than 5 points", () => {
    const v = verdictOf(pair(0.625, 0.625), reps(0.625, 0.75));
    expect(v.kind).toBe("noisy");
  });

  it("is noise inside the baseline's spread, and an effect beyond it", () => {
    expect(verdictOf(pair(0.8, 0.81), reps(0.8, 0.82, 0.79)).kind).toBe("within");
    const v = verdictOf(pair(0.8, 0.9), reps(0.8, 0.82, 0.79));
    expect(v).toMatchObject({ kind: "clears" });
    expect((v as { delta: number }).delta).toBeCloseTo(0.1);
  });

  it("names the side that failed rather than comparing against nothing", () => {
    expect(verdictOf(pair(0.75, null, "failed"), [])).toEqual({ kind: "failed", side: "b" });
  });
});

describe("words", () => {
  it("names a flag by its label when the registry has one, else spells its name out", () => {
    expect(axisWords({ kind: "flag", name: "closed_loop" })).toBe("closed loop");
    expect(axisWords({ kind: "flag", name: "monitors.recovery" }, { "monitors.recovery": "Alerts that close when a metric recovers" }))
      .toBe("Alerts that close when a metric recovers");
  });

  it("names what a suite runs as, and says when the app cannot run it", () => {
    expect(targetWords("reference")).toBe("SQL replay");
    expect(targetWords("session_log_receipt")).toBe("Session log");
    const base = { id: "s", name: "s", description: "", config: {}, created_at: "" };
    expect(runBlock({ ...base, target: "equivalence", connection_id: "" })?.chip).toBe("runs outside the app");
    expect(runBlock({ ...base, target: "reference", connection_id: "" })?.chip).toBe("no connection");
    expect(runBlock({ ...base, target: "reference", connection_id: "c1" })).toBeNull();
  });
});
