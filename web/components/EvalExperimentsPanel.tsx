"use client";
/**
 * Evals ▸ Experiments — redone to `aughor-v2/CLARITY.md` (2026-10-13). An experiment is a pair DERIVED from the run
 * history, never stored: two runs of one suite whose recorded requests differ on exactly one axis (a flag, or a model
 * pin). Each pair is one row — A against B, the difference in points, and whether that difference clears A's noise
 * floor (a chip: "within noise", "On better by 4.5 pts", or why it cannot be called). The per-case reading — which
 * cases moved, which way, and what their SQL became — sits behind Details.
 *
 * Runs are produced by `run_experiment` (today driven from `scripts/flag_ab_grid.py`, whose guards — the inertness
 * pre-check and the pinned temperature — are what make a pair worth reading).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import type { TableColumnsType } from "antd";
import {
  EvalExperiment,
  EvalRun,
  EvalSuite,
  ExperimentCompare,
  ExperimentCompareRow,
  compareEvalExperiment,
  getEvalExperiments,
  getEvalRuns,
  getEvalSuites,
  getSystemFlags,
} from "@/lib/api";
import { AugTable } from "@/components/AugTable";
import { TableActions } from "@/components/TableActions";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Loading, ReadFailed } from "@/components/ui/states";
import {
  CARD, Chip, Empty, Figure, Figures, Label, MUTED, NUM, ONE_LINE, Page, ROW, RULE, type Tone,
} from "@/components/clarity/kit";
import { formatCount, formatPoints } from "@/lib/format";
import {
  axisWords, day, measuresConsistency, plural, points, rate, sideWords, verdictOf, type Verdict,
} from "@/lib/evalSummary";

interface Props {
  connId?: string;
  workspaceId?: string;
}

/** Verdict → chip tone, the compare module's own vocabulary. */
const VERDICT_TONE: Record<string, Tone> = { correct: "up", wrong: "down", error: "down", "no-ref": "plain" };
const KIND_TONE: Record<string, Tone> = { gained: "up", lost: "down", other: "amber" };

/** The runs read to find each baseline's replicates — its noise floor. */
const RUN_LIMIT = 500;

/** Whether B's difference clears A's noise floor, as a chip — or why it cannot be called. */
function verdictChip(v: Verdict, exp: Pick<EvalExperiment, "axis">): { tone: Tone; text: string; title: string } {
  const A = sideWords(exp.axis, "a"), B = sideWords(exp.axis, "b");
  switch (v.kind) {
    case "failed": {
      const who = v.side === "both" ? "Both sides" : v.side === "a" ? A : B;
      return { tone: "down", text: `${who} failed — nothing to compare`,
        title: "A run that did not finish has no pass rate, so there is no difference to read" };
    }
    case "no-floor":
      return { tone: "plain", text: `can't call — ${A} ran once`,
        title: `${A} was never run against itself, so there is no noise floor to read a difference against. Run it at least twice.` };
    case "noisy":
      return { tone: "plain", text: `can't call — ${A} varies ${points(v.spread)}`,
        title: `${A} disagreed with itself by ${points(v.spread)} across ${v.n} runs — wider than the 5-point floor, so no difference measured against it can be attributed` };
    case "within":
      return { tone: "plain", text: "within noise",
        title: `The difference (${points(v.delta)}) is inside ${A}'s own run-to-run spread of ${points(v.spread)} over ${v.n} runs — not an observation` };
    case "clears":
      return { tone: v.delta > 0 ? "up" : "down", text: `${B} ${v.delta > 0 ? "better" : "worse"} by ${points(v.delta)}`,
        title: `Wider than ${A}'s run-to-run spread of ${points(v.spread)} over ${v.n} runs` };
  }
}

export function EvalExperimentsPanel({ }: Props) {
  const [experiments, setExperiments] = useState<EvalExperiment[]>([]);
  const [suites, setSuites] = useState<Record<string, EvalSuite>>({});
  const [runs, setRuns] = useState<EvalRun[] | null>([]);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [readFailed, setReadFailed] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ cmp: ExperimentCompare; exp: EvalExperiment } | null>(null);

  const load = useCallback(async () => {
    try {
      const [exps, ss, rs, flags] = await Promise.all([
        getEvalExperiments(undefined, 50),
        getEvalSuites().catch(() => [] as EvalSuite[]),
        getEvalRuns(undefined, RUN_LIMIT).catch(() => null),
        getSystemFlags().catch(() => ({})),
      ]);
      setExperiments(exps);
      setSuites(Object.fromEntries(ss.map(s => [s.id, s])));
      setRuns(rs);
      setLabels(Object.fromEntries(Object.entries(flags).map(([k, f]) => [k, f.label]).filter(([, l]) => !!l)));
      setReadFailed(null);
    } catch (e) {
      setReadFailed(e instanceof Error ? e.message : "the read failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function openPair(exp: EvalExperiment) {
    setError(null);
    try { setOpen({ cmp: await compareEvalExperiment(exp.a.run_id, exp.b.run_id), exp }); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not compare the two runs"); }
  }

  const verdicts = useMemo(() => experiments.map(e => (runs ? verdictOf(e, runs) : null)), [experiments, runs]);
  const nameOf = (id: string) => suites[id]?.name ?? "Suite no longer listed";

  if (open) {
    const i = experiments.indexOf(open.exp);
    return <CompareDetail cmp={open.cmp} exp={open.exp} suiteName={nameOf(open.cmp.suite_id)} suite={suites[open.cmp.suite_id]} labels={labels}
      verdict={i >= 0 ? verdicts[i] : null} onBack={() => setOpen(null)} />;
  }

  const known = verdicts.filter((v): v is Verdict => v !== null);
  const clears = known.filter((v): v is Extract<Verdict, { kind: "clears" }> => v.kind === "clears");
  const better = clears.filter(v => v.delta > 0).length;
  const noFloor = known.filter(v => v.kind === "no-floor").length;
  const noisy = known.filter(v => v.kind === "noisy").length;
  const failed = known.filter(v => v.kind === "failed").length;
  const pairedSuites = new Set(experiments.map(e => e.suite_id)).size;

  return (
    <Page testId="eval-experiments">
      {error && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>{error}</div>}
      {readFailed && <ReadFailed what="the experiments" error={readFailed} onRetry={load} />}
      {loading && <Loading what="experiments" />}

      {!loading && !readFailed && experiments.length === 0 && (
        <section aria-label="Experiments" style={CARD}>
          <Label>Experiments</Label>
          <Empty>No experiments yet. An experiment is two runs of one suite that differ on exactly one setting — a flag,
            or a model; run a suite under both (the A/B grid runner) and the pair appears here.</Empty>
        </section>
      )}

      {!loading && !readFailed && experiments.length > 0 && (
        <>
          <Figures testId="experiment-figures">
            <Figure label="Pairs" value={formatCount(experiments.length)} testId="fig-pairs"
              sub={`on ${plural(pairedSuites, "suite")}`} />
            <Figure label="Clear the noise floor" testId="fig-clears"
              value={runs ? `${clears.length} of ${experiments.length}` : "—"}
              title="B's difference from A is wider than A's own run-to-run spread"
              sub={runs ? (clears.length ? `${better} better · ${clears.length - better} worse` : "no difference is wider than the noise")
                : "runs could not be read"} />
            <Figure label="Can't be called" testId="fig-cant" value={runs ? formatCount(noFloor + noisy) : "—"}
              sub={runs ? (noFloor + noisy ? [noFloor && `${noFloor} baseline ran once`, noisy && `${noisy} baseline too noisy`].filter(Boolean).join(" · ")
                : "every baseline has a floor") : "runs could not be read"} />
            <Figure label="A side failed" testId="fig-failed" value={runs ? formatCount(failed) : "—"}
              tone={failed ? "red" : undefined} sub={failed ? "nothing to compare" : "both sides finished"} />
          </Figures>

          <section aria-label="Pairs" data-testid="experiment-list" style={CARD}>
            <Label right={<>
              <span>A is the baseline</span>
              <Button size="xs" variant="ghost" onClick={load}><Icon name="refresh" size={12} />Refresh</Button>
            </>}>Pairs</Label>
            {experiments.map((exp, i) => (
              <PairRow key={`${exp.a.run_id}-${exp.b.run_id}`} exp={exp} first={i === 0} verdict={verdicts[i]}
                suiteName={nameOf(exp.suite_id)} suite={suites[exp.suite_id]} labels={labels} onOpen={() => openPair(exp)} />
            ))}
          </section>
        </>
      )}
    </Page>
  );
}

function accuracyWords(exp: EvalExperiment): string {
  const of = (r: EvalExperiment["a"]) => (r.correctness_known ? `${r.correct}/${r.correctness_known}` : "—");
  return exp.a.correctness_known || exp.b.correctness_known ? `accuracy ${of(exp.a)} → ${of(exp.b)}` : "";
}

function PairRow({ exp, first, verdict, suiteName, suite, labels, onOpen }: {
  exp: EvalExperiment;
  first: boolean;
  verdict: Verdict | null;
  suiteName: string;
  suite?: EvalSuite;
  labels: Record<string, string>;
  onOpen: () => void;
}) {
  const chip = verdict ? verdictChip(verdict, exp) : { tone: "plain" as Tone, text: "floor unread", title: "The runs could not be read" };
  const meta = [suiteName, exp.a.total != null ? plural(exp.a.total, "case") : "", day(exp.b.started_at), accuracyWords(exp)]
    .filter(Boolean).join(" · ");
  const side = (s: "a" | "b") => {
    const r = exp[s];
    return (
      <span className="aug-fs-sm" style={{ ...NUM, color: "var(--t2)" }}>
        {sideWords(exp.axis, s)}{" "}
        <span style={{ color: "var(--t1)", fontWeight: 600 }}>{r.pass_rate != null ? rate(r.pass_rate) : r.status}</span>
      </span>
    );
  };
  const diff = exp.a.pass_rate != null && exp.b.pass_rate != null ? formatPoints(exp.a.pass_rate, exp.b.pass_rate) : "—";
  return (
    <div data-testid="experiment-row" style={{ ...(first ? {} : RULE), padding: "9px 2px", display: "grid",
      gridTemplateColumns: "minmax(0, 1fr) auto 84px auto auto", gap: 14, alignItems: "center" }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span className="aug-fs-chrome" title={exp.axis.name ?? undefined}
            style={{ ...ONE_LINE, fontWeight: 600, color: "var(--t1)" }}>{axisWords(exp.axis, labels)}</span>
          <Chip>{exp.axis.kind}</Chip>
          {suite && measuresConsistency(suite) && <Chip title={suite.description}>consistency, not correctness</Chip>}
        </div>
        <div className="aug-fs-xs" title={meta} style={{ ...MUTED, ...ONE_LINE }}>{meta}</div>
      </div>
      <div style={{ ...ROW, flexWrap: "nowrap", gap: 6 }}>{side("a")}<span style={MUTED}>→</span>{side("b")}</div>
      <span className="aug-fs-sm" title="B's pass rate minus A's, in percentage points"
        style={{ ...NUM, textAlign: "right", color: "var(--t1)" }}>{diff}</span>
      <Chip tone={chip.tone} title={chip.title} testId="experiment-verdict">{chip.text}</Chip>
      <Button size="xs" variant="ghost" onClick={onOpen}>Details</Button>
    </div>
  );
}

// ── The per-case reading ─────────────────────────────────────────────────────────

type Row = ExperimentCompareRow & { key: React.Key };

function CompareDetail({ cmp, exp, suiteName, suite, labels, verdict, onBack }: {
  cmp: ExperimentCompare;
  exp: EvalExperiment;
  suiteName: string;
  suite?: EvalSuite;
  labels: Record<string, string>;
  verdict: Verdict | null;
  onBack: () => void;
}) {
  const paired = cmp.accuracy.paired;
  const axis = cmp.axis ?? exp.axis;
  const A = sideWords(axis, "a"), B = sideWords(axis, "b");
  const chip = verdict ? verdictChip(verdict, { axis }) : null;

  const columns: TableColumnsType<Row> = [
    { title: "Question", dataIndex: "question", key: "question",
      render: (v: string) => <span className="aug-fs-sm">{v || "—"}</span> },
    { title: A, dataIndex: "a", key: "a", width: 100,
      render: (v: string) => <Chip tone={VERDICT_TONE[v] ?? "plain"}>{v}</Chip> },
    { title: B, dataIndex: "b", key: "b", width: 100,
      render: (v: string) => <Chip tone={VERDICT_TONE[v] ?? "plain"}>{v}</Chip> },
    { title: "Change", dataIndex: "kind", key: "kind", width: 90,
      render: (v: string) => <Chip tone={KIND_TONE[v] ?? "plain"}>{v}</Chip> },
    { title: `SQL (${A} → ${B})`, key: "sql",
      render: (_: unknown, r: ExperimentCompareRow) => (
        (r.a_sql || r.b_sql)
          ? <div className="aug-fs-xs" style={{ fontFamily: "var(--font-code)", maxWidth: 420 }}>
              <div title={r.a_sql} style={{ ...ONE_LINE, color: "var(--t2)" }}>{r.a_sql || "—"}</div>
              <div title={r.b_sql} style={{ ...ONE_LINE, color: "var(--t1)" }}>{r.b_sql || "—"}</div>
            </div>
          : <span className="aug-fs-xs" style={MUTED} title={r.a_error || r.b_error}>
              {(r.a_error || r.b_error) ? (r.a_error || r.b_error).slice(0, 60) : "—"}
            </span>
      ) },
  ];
  const table = () => ({
    columns: ["Question", A, B, "Change", `SQL ${A}`, `SQL ${B}`, `Error ${A}`, `Error ${B}`],
    rows: cmp.rows.map(r => [r.question, r.a, r.b, r.kind, r.a_sql || null, r.b_sql || null, r.a_error || null, r.b_error || null]),
  });

  return (
    <Page testId="eval-experiment-detail">
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Button size="xs" variant="ghost" onClick={onBack}><Icon name="back" size={12} />All experiments</Button>
        <span className="aug-fs-h2" title={axis?.name ?? undefined} style={{ fontWeight: 600, color: "var(--t1)" }}>
          {axisWords(axis, labels)}
        </span>
        <Chip>{axis?.kind ?? "pair"}</Chip>
        <span className="aug-fs-sm" style={MUTED}>{suiteName}</span>
        {suite && measuresConsistency(suite) && <Chip title={suite.description}>consistency, not correctness</Chip>}
        {chip && <Chip tone={chip.tone} title={chip.title}>{chip.text}</Chip>}
      </div>

      <Figures testId="compare-figures">
        <Figure label="Paired cases" value={formatCount(paired.cases)} sub={`${cmp.flips.same} gave the same verdict`} />
        <Figure label={`${A} correct`} value={`${paired.a_correct} of ${paired.cases}`} />
        <Figure label={`${B} correct`} value={`${paired.b_correct} of ${paired.cases}`}
          tone={paired.b_correct < paired.a_correct ? "red" : undefined}
          sub={`${cmp.flips.gained} gained · ${cmp.flips.lost} lost${cmp.flips.other ? ` · ${cmp.flips.other} other` : ""}`} />
        <Figure label="Left out" value={formatCount(cmp.flips.unrun)} tone={cmp.flips.unrun ? "amber" : undefined}
          title="A case one side never reached counts as unrun — excluded, never a flip"
          sub={cmp.flips.unrun ? "unrun by one side — excluded" : "both sides reached every case"} />
      </Figures>

      <div style={ROW}>
        <Chip title="Accuracy is read over the cases both sides reached — totals over unequal sets would mislead">
          accuracy over paired cases only
        </Chip>
        {!cmp.sql_available && <Chip title="These runs predate per-case SQL capture">verdicts only — no SQL captured</Chip>}
        <Chip>{`${A} ${day(cmp.a.started_at)} · ${B} ${day(cmp.b.started_at)}`}</Chip>
      </div>

      <section aria-label="Cases that changed" style={CARD}>
        <Label right={<>
          <span style={NUM}>{plural(cmp.rows.length, "case")}</span>
          {cmp.rows.length > 0 && <TableActions read={table} name={`${axisWords(axis, labels)} experiment`} />}
        </>}>Cases that changed</Label>
        {cmp.rows.length === 0 ? (
          <Empty>{`No case changed verdict between the two — ${cmp.flips.same} agreed.`}</Empty>
        ) : (
          <AugTable<Row>
            columns={columns}
            dataSource={cmp.rows.map((r, i) => ({ ...r, key: i }))}
            pagination={cmp.rows.length > 50 ? { pageSize: 50, size: "small" } : false}
            scroll={{ x: "max-content" }}
          />
        )}
      </section>
    </Page>
  );
}
