"use client";
/**
 * Evals ▸ Runs — redone to `aughor-v2/CLARITY.md` (2026-10-13). A measurement is a BAND, never a point: repeated
 * runs of one suite under one set-up are its replicates, so they fold into one row — ×N, the trend of every run, and
 * the score as its band ("79.5% ± 9.1 · 4 replicates"), or "no band" when it ran once. Four figures lead: runs, how
 * many set-ups have a band, how many held within the noise floor, how many runs did not finish. Each run, and each
 * run's cases, sit behind the row's Details.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import type { TableColumnsType } from "antd";
import { EvalResult, EvalRun, EvalSuite, getEvalRun, getEvalRuns, getEvalSuite, getEvalSuites } from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { AugTable } from "@/components/AugTable";
import { TableActions } from "@/components/TableActions";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Loading, ReadFailed } from "@/components/ui/states";
import { Tooltip } from "@/components/ui/tooltip";
import {
  CARD, Chip, Empty, Figure, Figures, Label, MUTED, NUM, ONE_LINE, Page, ROW, RULE, type Tone,
} from "@/components/clarity/kit";
import { formatCount } from "@/lib/format";
import {
  bandText, day, floorOf, groupRuns, measuresConsistency, noteOf, passRate, plural, points, rate, runState, when, words, type RunGroup,
  type RunState,
} from "@/lib/evalSummary";

interface Props {
  connId?: string;
  workspaceId?: string;
}

/** How many runs the page reads; the list says so when it is cut there. */
const RUN_LIMIT = 200;

const REMOVED = "Suite no longer listed";

export function EvalRunPanel({ }: Props) {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [suites, setSuites] = useState<Record<string, EvalSuite>>({});
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [readFailed, setReadFailed] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<(EvalRun & { results: EvalResult[] }) | null>(null);
  const [openRows, setOpenRows] = useState<ReadonlySet<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const [rs, ss] = await Promise.all([
        getEvalRuns(undefined, RUN_LIMIT),
        getEvalSuites().catch(() => [] as EvalSuite[]),
      ]);
      setRuns(rs);
      setSuites(Object.fromEntries(ss.map(s => [s.id, s])));
      setReadFailed(null);
      setLoaded(true);
    } catch (e) {
      setReadFailed(e instanceof Error ? e.message : "the read failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    load();
    // Eval runs are SYNCHRONOUS today (the run route blocks and returns the summary),
    // so nothing streams `eval.*` yet. The 60s interval is the real refresh — it makes a
    // run started elsewhere appear — and the kernel subscription is the forward-looking
    // hook for when runs move onto the job kernel (then `job.state` will fire per run).
    const t = setInterval(load, 60_000);
    const unsub = subscribeKernelEvents(() => load(), { kinds: ["eval.", "job.state"] });
    return () => { clearInterval(t); unsub(); };
  }, [load]);

  async function open(runId: string) {
    setError(null);
    try { setOpenRun(await getEvalRun(runId)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not open the run"); }
  }

  const nameOf = (id: string) => suites[id]?.name ?? REMOVED;
  const groups = useMemo(() => groupRuns(runs), [runs]);

  if (openRun) {
    return <RunDetail run={openRun} suiteName={nameOf(openRun.suite_id)} suite={suites[openRun.suite_id]}
      onBack={() => { setOpenRun(null); load(); }} />;
  }

  return (
    <Page testId="eval-runs">
      {error && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>{error}</div>}
      {readFailed && <ReadFailed what="the eval runs" error={readFailed} onRetry={load} />}
      {!loaded && loading && <Loading what="the eval runs" />}
      {loaded && !readFailed && (runs.length === 0
        ? (
          <section aria-label="Runs" style={CARD}>
            <Label>Runs</Label>
            <Empty>No runs yet — run a suite from Suites, and its result lands here as a band.</Empty>
          </section>
        )
        : <Overview runs={runs} groups={groups} nameOf={nameOf} suites={suites} openRows={openRows} onOpen={open}
            onToggle={k => setOpenRows(p => { const n = new Set(p); if (n.has(k)) n.delete(k); else n.add(k); return n; })}
            onRefresh={load} />)}
    </Page>
  );
}

// ── Figures and the folded list ─────────────────────────────────────────────────

function Overview({ runs, groups, nameOf, suites, openRows, onOpen, onToggle, onRefresh }: {
  runs: EvalRun[];
  groups: RunGroup[];
  nameOf: (id: string) => string;
  suites: Record<string, EvalSuite>;
  openRows: ReadonlySet<string>;
  onOpen: (runId: string) => void;
  onToggle: (key: string) => void;
  onRefresh: () => void;
}) {
  const suiteCount = new Set(runs.map(r => r.suite_id)).size;
  const banded = groups.filter(g => (g.band?.n ?? 0) >= 2);
  const held = banded.filter(g => floorOf(g.band) === "held");
  const failed = groups.reduce((n, g) => n + g.failed, 0);
  const unfinished = groups.reduce((n, g) => n + g.unfinished, 0);
  const latest = runs.reduce((a, r) => (r.started_at > a ? r.started_at : a), "");
  const cut = runs.length >= RUN_LIMIT;

  return (
    <>
      <Figures testId="run-figures">
        <Figure label="Runs" value={formatCount(runs.length)} testId="fig-runs"
          sub={`${plural(groups.length, "set-up")} of ${plural(suiteCount, "suite")} · last ${day(latest)}`} />
        <Figure label="With a band" value={`${banded.length} of ${groups.length}`} testId="fig-banded"
          title="A set-up run twice or more has a band — how far it disagrees with itself"
          sub={banded.length === groups.length ? "every set-up ran 2+ times" : `${groups.length - banded.length} ran once — no band`} />
        <Figure label="Held the noise floor" value={banded.length ? `${held.length} of ${banded.length}` : "—"} testId="fig-held"
          title="Replicates of one set-up within 5 points of each other — a difference from it wider than that can be read"
          sub={banded.length ? "replicates within 5 pts of each other" : "no set-up has a band yet"} />
        <Figure label="Didn't finish" value={formatCount(failed + unfinished)} testId="fig-unfinished"
          sub={failed + unfinished ? `${failed} failed · ${unfinished} never finished` : "every run finished"} />
      </Figures>

      <section aria-label="Runs by set-up" data-testid="run-groups" style={CARD}>
        <Label right={<>
          <span style={NUM}>{`${formatCount(runs.length)} runs as ${plural(groups.length, "row")}${cut ? ` · the latest ${RUN_LIMIT}` : ""}`}</span>
          <Button size="xs" variant="ghost" onClick={onRefresh}><Icon name="refresh" size={12} />Refresh</Button>
        </>}>Runs by set-up</Label>
        {groups.map((g, i) => (
          <GroupRow key={g.key} group={g} first={i === 0} name={nameOf(g.suiteId)} suite={suites[g.suiteId]} open={openRows.has(g.key)}
            onToggle={() => onToggle(g.key)} onOpen={onOpen} />
        ))}
      </section>
    </>
  );
}

const FLOOR_CHIP: Record<ReturnType<typeof floorOf>, (g: RunGroup) => { tone: Tone; text: string; title: string }> = {
  none: () => ({ tone: "plain", text: "nothing measured", title: "No run of this set-up returned a pass rate" }),
  single: () => ({ tone: "plain", text: "no band",
    title: "Run once: there is nothing to say how far it disagrees with itself, so no difference from it can be read" }),
  held: g => ({ tone: "up", text: g.band?.spread ? `holds within ${points(g.band.spread)}` : "steady — no spread",
    title: `${rate(g.band?.lo)}–${rate(g.band?.hi)} across ${g.band?.n} runs — within the 5-point noise floor` }),
  noisy: g => ({ tone: "plain", text: `varies ${points(g.band?.spread ?? 0)}`,
    title: `${rate(g.band?.lo)}–${rate(g.band?.hi)} across ${g.band?.n} runs — wider than the 5-point floor, so a difference from it cannot be read` }),
};

function GroupRow({ group: g, first, name, suite, open, onToggle, onOpen }: {
  group: RunGroup;
  first: boolean;
  name: string;
  suite?: EvalSuite;
  open: boolean;
  onToggle: () => void;
  onOpen: (runId: string) => void;
}) {
  const floor = floorOf(g.band);
  const chip = FLOOR_CHIP[floor](g);
  const meta = [
    `last ${day(g.latest.started_at)}`,
    g.failed ? `${g.failed} failed` : "",
    g.unfinished ? `${g.unfinished} never finished` : "",
    g.running ? `${g.running} running` : "",
    g.flaky ? `${g.flaky} flaky` : "",
    g.accuracy ? `accuracy ${bandText(g.accuracy)}` : "",
  ].filter(Boolean).join(" · ");
  return (
    <div data-testid="run-group" style={{ ...(first ? {} : RULE), padding: "9px 2px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto 128px auto", gap: 14, alignItems: "center" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span className="aug-fs-chrome" title={name} style={{ ...ONE_LINE, fontWeight: 600, color: "var(--t1)" }}>{name}</span>
            {suite && measuresConsistency(suite) && <Chip title={suite.description}>consistency, not correctness</Chip>}
            {g.runs.length > 1 && <Chip testId="run-count">{`×${g.runs.length}`}</Chip>}
            {g.cell && <Chip title="The set-up these runs recorded they were asked for">{words(g.cell)}</Chip>}
            <Chip tone={chip.tone} title={chip.title}>{chip.text}</Chip>
          </div>
          <div className="aug-fs-xs" title={meta} style={{ ...MUTED, ...ONE_LINE }}>{meta}</div>
        </div>
        <Trend runs={g.runs} />
        <div style={{ textAlign: "right" }}>
          <div className="aug-fs-h2" data-testid="run-band" style={{ fontWeight: 600, color: "var(--t1)", ...NUM }}>{bandText(g.band)}</div>
          <div className="aug-fs-xs" style={MUTED}>
            {g.band ? `${plural(g.band.n, "replicate")}${g.band.n < 2 ? " — no band" : ""}` : "no measurement"}
          </div>
        </div>
        <Button size="xs" variant="ghost" aria-expanded={open} onClick={onToggle}>
          Details <Icon name={open ? "chevu" : "chevd"} size={12} />
        </Button>
      </div>
      {open && (
        <div data-testid="run-group-details" style={{ padding: "8px 0 2px 14px" }}>
          {[...g.runs].reverse().map(r => <RunLine key={r.id} run={r} onOpen={() => onOpen(r.id)} />)}
        </div>
      )}
    </div>
  );
}

const STATE_CHIP: Record<RunState, { tone: Tone; text: string }> = {
  measured: { tone: "up", text: "finished" },
  "no-result": { tone: "plain", text: "no result" },
  failed: { tone: "down", text: "failed" },
  running: { tone: "accent", text: "running" },
  unfinished: { tone: "plain", text: "never finished" },
};

/** One run inside a folded row: when · how it ended · its score · what it says about itself. */
function RunLine({ run, onOpen }: { run: EvalRun; onOpen: () => void }) {
  const st = runState(run);
  const s = run.summary ?? {};
  const note = noteOf(run);
  return (
    <div data-testid="run-line" style={{ display: "grid", gridTemplateColumns: "96px auto minmax(0, 1fr) auto", gap: 10,
      alignItems: "center", padding: "4px 0" }}>
      <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>{when(run.started_at)}</span>
      <Chip tone={STATE_CHIP[st].tone} title={st === "unfinished" ? "Still marked running a day later — it never finished" : undefined}>
        {STATE_CHIP[st].text}
      </Chip>
      <div style={{ ...ROW, flexWrap: "nowrap", minWidth: 0 }}>
        {passRate(run) != null && (
          <span className="aug-fs-sm" style={{ color: "var(--t1)", ...NUM }}>
            {`${rate(passRate(run))} · ${s.stable_pass ?? 0} of ${s.total ?? 0} stable`}
          </span>
        )}
        {run.iterations > 1 && <Chip>{`${run.iterations} iterations`}</Chip>}
        {(s.flaky ?? 0) > 0 && <Chip tone="amber">{`${s.flaky} flaky`}</Chip>}
        {(s.errors ?? 0) > 0 && <Chip tone="down">{plural(s.errors ?? 0, "error")}</Chip>}
        {s.accuracy != null && <Chip title="Correct answers among the cases that declared one">{`accuracy ${rate(s.accuracy)}`}</Chip>}
        {note && <span className="aug-fs-xs" title={note} style={{ ...MUTED, ...ONE_LINE }}>{note}</span>}
      </div>
      <Button size="xs" variant="ghost" onClick={onOpen}>Cases</Button>
    </div>
  );
}

/**
 * A set-up's runs in order, one mark each — the trend. A run that measured is a column at its pass rate; a failed
 * run a short red mark; one that never finished a hatched stub. Every mark names itself on hover. (A primitive the
 * kit's `Columns` does not cover: it has no per-mark state and draws axis labels a 24px row has no room for.)
 */
function Trend({ runs }: { runs: EvalRun[] }) {
  const H = 24;
  const shown = runs.slice(-24);
  return (
    <div role="group" aria-label="Every run, oldest first" style={{ display: "flex", alignItems: "flex-end", gap: 2,
      height: H, borderBottom: "1px solid var(--chart-grid)", minWidth: 20 }}>
      {shown.map(r => {
        const st = runState(r);
        const v = passRate(r);
        const tip = `${when(r.started_at)} · ${v != null ? `${rate(v)} stable pass`
          : st === "failed" ? "failed" : st === "unfinished" ? "never finished" : st}`;
        const bg = st === "measured" ? "var(--chart-1)" : st === "failed" ? "var(--red3)"
          : "repeating-linear-gradient(135deg, var(--chart-deemph) 0 2px, transparent 2px 4px)";
        return (
          <Tooltip key={r.id} content={tip}>
            <div role="img" aria-label={tip} style={{ width: 6, height: "100%", display: "flex", alignItems: "flex-end" }}>
              <div style={{ width: "100%", height: v != null ? Math.max(2, v * H) : 4, borderRadius: "2px 2px 0 0", background: bg }} />
            </div>
          </Tooltip>
        );
      })}
    </div>
  );
}

// ── One run's cases ───────────────────────────────────────────────────────────────

type Row = EvalResult & { key: React.Key };

function RunDetail({ run, suiteName, suite, onBack }: {
  run: EvalRun & { results: EvalResult[] }; suiteName: string; suite?: EvalSuite; onBack: () => void;
}) {
  const s = run.summary ?? {};
  const st = runState(run);
  const note = noteOf(run);
  const fired = Object.entries(s.fired_counts ?? {}).sort((a, b) => b[1] - a[1]);
  /** The suite's cases by id, to name each result by its question; null where the suite cannot be read. */
  const [questions, setQuestions] = useState<Record<string, string> | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    getEvalSuite(run.suite_id)
      .then(d => { if (live) setQuestions(Object.fromEntries(d.cases.map(c => [c.id, c.question]))); })
      .catch(() => { if (live) setQuestions(null); });
    return () => { live = false; };
  }, [run.suite_id]);
  const caseName = (id: string) => questions?.[id] || id;
  const cell = typeof run.config?.["cell"] === "string" ? words(run.config["cell"] as string) : "";

  const yesNo = (v: boolean | null, yes: string, no: string) => (v == null ? "—" : v ? yes : no);
  const columns: TableColumnsType<Row> = [
    { title: "Case", dataIndex: "case_id", key: "case_id",
      render: (v: string) => (questions?.[v]
        ? <span className="aug-fs-sm" title={questions[v]}>{questions[v]}</span>
        : <code className="aug-fs-xs" style={{ fontFamily: "var(--font-mono)" }}>{v}</code>) },
    { title: "Iteration", dataIndex: "iteration", key: "iteration", width: 80, align: "right" },
    { title: "Passed", dataIndex: "passed", key: "passed", width: 90,
      render: (v: boolean | null) => <BoolChip v={v} yes="pass" no="fail" /> },
    { title: "Correct", dataIndex: "correct", key: "correct", width: 90,
      render: (v: boolean | null) => <BoolChip v={v} yes="correct" no="wrong" /> },
    { title: "Time", dataIndex: "duration_ms", key: "duration_ms", width: 80, align: "right",
      render: (v: number | null) => <span style={NUM}>{v == null ? "—" : `${formatCount(Math.round(v))} ms`}</span> },
    { title: "Checks failed", dataIndex: "fired", key: "fired",
      render: (v: string[]) => v && v.length
        ? <span className="aug-fs-xs">{v.map(n => <code key={n} style={{ fontFamily: "var(--font-code)", color: "var(--amb4)", marginRight: 6 }}>{n}</code>)}</span>
        : <span style={MUTED}>—</span> },
    { title: "Error", dataIndex: "error", key: "error",
      render: (v: string) => v
        ? <span className="aug-fs-xs" title={v} style={{ color: "var(--red4)" }}>{v.slice(0, 60)}</span>
        : <span style={MUTED}>—</span> },
  ];
  const dataSource: Row[] = run.results.map((r, i) => ({ ...r, key: i }));
  const table = () => ({
    columns: ["Case", "Iteration", "Passed", "Correct", "Time (ms)", "Checks failed", "Error"],
    rows: run.results.map(r => [caseName(r.case_id), r.iteration, yesNo(r.passed, "pass", "fail"),
      yesNo(r.correct, "correct", "wrong"), r.duration_ms == null ? null : Math.round(r.duration_ms), (r.fired ?? []).join(" "), r.error || null]),
  });

  return (
    <Page testId="eval-run-detail">
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Button size="xs" variant="ghost" onClick={onBack}><Icon name="back" size={12} />All runs</Button>
        <span className="aug-fs-h2" style={{ fontWeight: 600, color: "var(--t1)" }}>{suiteName}</span>
        {cell && <Chip>{cell}</Chip>}
        {suite && measuresConsistency(suite) && <Chip title={suite.description}>consistency, not correctness</Chip>}
        <Chip tone={STATE_CHIP[st].tone}>{STATE_CHIP[st].text}</Chip>
        <Chip>{`started ${when(run.started_at)}`}</Chip>
        <Chip>{plural(run.iterations, "iteration")}</Chip>
        {questions === null && <Chip title="The suite's cases could not be read, so each result is named by its case id">questions unread</Chip>}
      </div>
      {note && <div className="aug-fs-sm" title={note} style={{ color: "var(--t2)", ...ONE_LINE, marginTop: -6 }}>{note}</div>}

      <Figures testId="run-detail-figures">
        <Figure label="Pass rate (stable)" value={rate(s.pass_rate)} tone={st === "failed" ? "red" : undefined}
          sub={s.total != null ? `${s.stable_pass ?? 0} of ${s.total} passed every iteration` : "no result came back"} />
        <Figure label="Flaky" value={formatCount(s.flaky ?? 0)} tone={(s.flaky ?? 0) > 0 ? "amber" : undefined}
          sub="passed some iterations, not all" />
        <Figure label="Errors" value={formatCount(s.errors ?? 0)} tone={(s.errors ?? 0) > 0 ? "red" : undefined}
          sub={s.stable_fail != null ? `${s.stable_fail} failed every iteration` : undefined} />
        {(s.accuracy != null || s.robustness != null) && (
          <Figure label={s.accuracy != null ? "Accuracy" : "Robustness"} value={rate(s.accuracy ?? s.robustness)}
            sub={s.accuracy != null && s.robustness != null ? `robustness ${rate(s.robustness)}`
              : s.accuracy != null ? `${s.correct ?? 0} of ${s.correctness_known ?? 0} declared an answer` : undefined} />
        )}
      </Figures>

      {fired.length > 0 && (
        <section aria-label="Checks that failed" style={CARD}>
          <Label right={<span style={NUM}>{plural(fired.length, "check")}</span>}>Checks that failed</Label>
          <div style={ROW}>
            {fired.map(([name, n]) => (
              <Chip key={name}><code style={{ fontFamily: "var(--font-code)" }}>{name}</code> ×{n}</Chip>
            ))}
          </div>
        </section>
      )}

      <section aria-label="Cases" style={CARD}>
        <Label right={<>
          <span style={NUM}>{plural(run.results.length, "result")}</span>
          {run.results.length > 0 && <TableActions read={table} name={`${suiteName} run`} />}
        </>}>Cases</Label>
        {run.results.length === 0 ? <Empty>This run recorded no case results.</Empty> : (
          <AugTable<Row>
            columns={columns}
            dataSource={dataSource}
            pagination={run.results.length > 50 ? { pageSize: 50, size: "small" } : false}
            scroll={{ x: "max-content" }}
          />
        )}
      </section>
    </Page>
  );
}

function BoolChip({ v, yes, no }: { v: boolean | null; yes: string; no: string }) {
  if (v == null) return <span style={MUTED}>—</span>;
  return <Chip tone={v ? "up" : "down"}>{v ? yes : no}</Chip>;
}
