/**
 * The Evals screen's reading of its runs — pure arithmetic over what `GET /evals/runs` and
 * `GET /evals/experiments` return, so the three layers say the same thing the same way.
 *
 * A measurement is a BAND, never a point: repeated runs of one configuration (a suite under one
 * recorded cell) are its replicates, and how far they disagree with each other is its noise floor.
 * A difference between two configurations is only read when it is wider than that floor, and a
 * configuration run once has no floor at all — it is not a floor of zero. The line, 5 points, is
 * the platform's own (`DEFAULT_FLOOR_THRESHOLD` in the backend's fidelity module); the screen
 * mirrors it rather than inventing a second one.
 */
import type { EvalExperiment, EvalRun, EvalSuite, ExperimentAxis } from "@/lib/api";
import { MONTHS_SHORT, pct } from "@/lib/format";

/** Two runs of one configuration further apart than this disagree with each other. */
export const FLOOR = 0.05;

/** A run still marked running after a day never finished: a suite run is synchronous, so a row that old has lost
 *  the process that was writing it. */
export const STALE_MS = 24 * 3600_000;

/** A share as the screen writes it: 0.7353 → "73.5%". */
export const rate = (r: number | null | undefined) => pct(r, 1);

/** A gap between two shares in points, unsigned: 0.0196 → "2.0 pts". */
export const points = (d: number) => `${(Math.abs(d) * 100).toFixed(1)} pts`;

/** "15 Aug" — the day a person reads. */
export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "—" : `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
}

/** "15 Aug 09:37" — a run among several on one day. */
export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${day(iso)} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// ── A run ────────────────────────────────────────────────────────────────────────

/** The pass rate a run measured — null unless it finished and reported one. */
export function passRate(run: EvalRun): number | null {
  const r = run.summary?.pass_rate;
  return run.status === "succeeded" && typeof r === "number" ? r : null;
}

/** The configuration a run recorded it was asked for (`config.cell`), or null for a plain run. */
export function cellOf(run: EvalRun): string | null {
  const c = (run.config ?? {})["cell"];
  return typeof c === "string" && c ? c : null;
}

/** A recorded configuration in words: "closed_loop_on" → "closed loop on". */
export function words(name: string | null | undefined): string {
  return (name ?? "").replace(/[._]+/g, " ").trim();
}

export type RunState = "measured" | "failed" | "running" | "unfinished" | "no-result";

export function runState(run: EvalRun, now = Date.now()): RunState {
  if (run.status === "failed") return "failed";
  if (run.status === "succeeded") return passRate(run) == null ? "no-result" : "measured";
  const started = Date.parse(run.started_at);
  return !isNaN(started) && now - started > STALE_MS ? "unfinished" : "running";
}

/** The run's own annotation — a person's note on what it was ("TRANSPORT failure, not a measurement…"). */
export function noteOf(run: EvalRun): string {
  const n = (run.summary as Record<string, unknown> | undefined)?.["note"];
  return typeof n === "string" ? n : "";
}

// ── A band ───────────────────────────────────────────────────────────────────────

export interface Band { n: number; mean: number; lo: number; hi: number; spread: number }

export function bandOf(values: number[]): Band | null {
  if (!values.length) return null;
  const lo = Math.min(...values), hi = Math.max(...values);
  return { n: values.length, mean: values.reduce((s, v) => s + v, 0) / values.length, lo, hi, spread: hi - lo };
}

/** none — nothing measured · single — run once, no floor · held — within 5 pts of itself · noisy — wider. */
export type FloorState = "none" | "single" | "held" | "noisy";

export function floorOf(b: Band | null): FloorState {
  if (!b) return "none";
  if (b.n < 2) return "single";
  return b.spread <= FLOOR + 1e-9 ? "held" : "noisy";
}

/** The band as one figure: "79.5% ± 9.1" — the mean and half the spread, so it covers every replicate. */
export function bandText(b: Band | null): string {
  if (!b) return "—";
  if (b.n < 2 || b.spread === 0) return rate(b.mean);
  return `${rate(b.mean)} ± ${(b.spread * 50).toFixed(1)}`;
}

// ── Runs folded by configuration ────────────────────────────────────────────────

export interface RunGroup {
  key: string;
  suiteId: string;
  cell: string | null;
  /** Oldest first — the order the trend is drawn in. */
  runs: EvalRun[];
  latest: EvalRun;
  band: Band | null;
  accuracy: Band | null;
  failed: number;
  unfinished: number;
  running: number;
  /** Cases that passed some iterations but not all, at the latest measured run. */
  flaky: number;
}

/** Repeated runs of one suite under one configuration fold into one group — those are its replicates. Newest first. */
export function groupRuns(runs: EvalRun[], now = Date.now()): RunGroup[] {
  const by = new Map<string, EvalRun[]>();
  for (const r of runs) {
    const key = `${r.suite_id}|${cellOf(r) ?? ""}`;
    by.set(key, [...(by.get(key) ?? []), r]);
  }
  const groups = [...by.entries()].map(([key, rs]): RunGroup => {
    const ordered = [...rs].sort((a, b) => a.started_at.localeCompare(b.started_at));
    const measured = ordered.filter(r => passRate(r) != null);
    const acc = measured.map(r => r.summary?.accuracy).filter((v): v is number => typeof v === "number");
    const states = ordered.map(r => runState(r, now));
    return {
      key, suiteId: ordered[0].suite_id, cell: cellOf(ordered[0]), runs: ordered, latest: ordered[ordered.length - 1],
      band: bandOf(measured.map(r => passRate(r) as number)), accuracy: bandOf(acc),
      failed: states.filter(s => s === "failed").length,
      unfinished: states.filter(s => s === "unfinished").length,
      running: states.filter(s => s === "running").length,
      flaky: measured.length ? measured[measured.length - 1].summary?.flaky ?? 0 : 0,
    };
  });
  return groups.sort((a, b) => b.latest.started_at.localeCompare(a.latest.started_at));
}

// ── A suite ──────────────────────────────────────────────────────────────────────

export interface SuiteState {
  /** Newest first. */
  runs: EvalRun[];
  last: EvalRun | null;
  lastState: RunState | null;
  /** The last run's pass rate, when the last run measured one. */
  lastRate: number | null;
  /** The last run fell further than the floor below the run before it of the same configuration. */
  regressed: { from: number; to: number } | null;
}

export function suiteState(suiteId: string, runs: EvalRun[], now = Date.now()): SuiteState {
  const mine = runs.filter(r => r.suite_id === suiteId).sort((a, b) => b.started_at.localeCompare(a.started_at));
  const last = mine[0] ?? null;
  const lastRate = last ? passRate(last) : null;
  let regressed: SuiteState["regressed"] = null;
  if (last && lastRate != null) {
    const prev = mine.slice(1).find(r => cellOf(r) === cellOf(last) && passRate(r) != null);
    const from = prev ? passRate(prev) : null;
    if (from != null && from - lastRate > FLOOR + 1e-9) regressed = { from, to: lastRate };
  }
  return { runs: mine, last, lastState: last ? runState(last, now) : null, lastRate, regressed };
}

/** What a suite runs as, in words: the reference target replays SQL; the rest are named for what they check. */
export function targetWords(target: string): string {
  if (target === "reference") return "SQL replay";
  const w = words(target.replace(/_receipt$/, ""));
  return w ? w[0].toUpperCase() + w.slice(1) : "Custom";
}

/** Whether this screen can run the suite — only a SQL replay with a connection is runnable from the app. */
export function runBlock(suite: EvalSuite): null | { chip: string; why: string } {
  if (suite.target !== "reference") {
    return { chip: "runs outside the app", why: "Only SQL-replay suites run from here; this one is run by its own harness" };
  }
  if (!suite.connection_id) return { chip: "no connection", why: "A SQL replay needs a connection to replay its cases on" };
  return null;
}

/** The suite's own description says its pass rate is consistency, not correctness. */
export const measuresConsistency = (s: EvalSuite) => /not correctness/i.test(s.description ?? "");

// ── An A/B pair ──────────────────────────────────────────────────────────────────

export type Verdict =
  | { kind: "failed"; side: "a" | "b" | "both" }
  | { kind: "no-floor"; delta: number }
  | { kind: "noisy"; delta: number; spread: number; n: number }
  | { kind: "within"; delta: number; spread: number; n: number }
  | { kind: "clears"; delta: number; spread: number; n: number };

/**
 * Whether B's difference from A clears A's noise floor — A's own replicates (its configuration's other measured runs
 * of the same suite) decide how far A disagrees with itself. Mirrors the backend's `compare`: no floor below two
 * replicates, no attribution when the floor is wider than 5 points, and a difference inside the floor is noise.
 */
export function verdictOf(exp: EvalExperiment, runs: EvalRun[]): Verdict {
  const aOk = exp.a.status === "succeeded" && exp.a.pass_rate != null;
  const bOk = exp.b.status === "succeeded" && exp.b.pass_rate != null;
  if (!aOk || !bOk) return { kind: "failed", side: !aOk && !bOk ? "both" : !aOk ? "a" : "b" };
  const delta = (exp.b.pass_rate as number) - (exp.a.pass_rate as number);
  const reps = runs.filter(r => r.suite_id === exp.suite_id && cellOf(r) === exp.a.cell && passRate(r) != null);
  const values = reps.map(r => passRate(r) as number);
  if (!reps.some(r => r.id === exp.a.run_id)) values.push(exp.a.pass_rate as number);
  const b = bandOf(values) as Band;
  if (b.n < 2) return { kind: "no-floor", delta };
  if (b.spread > FLOOR + 1e-9) return { kind: "noisy", delta, spread: b.spread, n: b.n };
  return Math.abs(delta) <= b.spread + 1e-9
    ? { kind: "within", delta, spread: b.spread, n: b.n }
    : { kind: "clears", delta, spread: b.spread, n: b.n };
}

/** The two sides by what they are: a flag's Off and On, a model's name — A is always the baseline. */
export function sideWords(axis: ExperimentAxis | null | undefined, side: "a" | "b"): string {
  if (axis?.kind === "flag") return side === "a" ? "Off" : "On";
  if (axis?.kind === "model") return (side === "a" ? axis.a_model : axis.b_model) || (side === "a" ? "A" : "B");
  return side === "a" ? "A" : "B";
}

/** What the pair varies, in words: a flag by its label when the registry has one, else its name spelled out. */
export function axisWords(axis: ExperimentAxis | null | undefined, labels: Record<string, string> = {}): string {
  if (!axis) return "Pair";
  if (axis.kind === "flag") return (axis.name && labels[axis.name]) || words(axis.name) || "a flag";
  if (axis.kind === "model") return `${axis.a_model ?? "?"} vs ${axis.b_model ?? "?"}`;
  return words(axis.name) || axis.kind;
}
