"use client";
/**
 * Evals ▸ Suites — redone to `aughor-v2/CLARITY.md` (2026-10-13): four figures (suites, cases, how many passed in full
 * at their last run, how many never ran), then what needs a person — a suite whose last run fell or failed, a suite
 * never run — with Run on the row, then the suites as one line each (name · cases · what it runs as and where · its
 * last result). Authoring sits behind *New suite*, and a suite's cases, its run settings and Delete behind *Open*.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Connection,
  EvalCase,
  EvalEvaluator,
  EvalRun,
  EvalRunSummary,
  EvalSuite,
  addEvalCases,
  createEvalSuite,
  deleteEvalCase,
  deleteEvalSuite,
  getConnections,
  getEvalRuns,
  getEvalSuite,
  getEvalSuites,
  getEvaluators,
  runEvalSuite,
} from "@/lib/api";
import type { EvalsLayer } from "@/components/EvalsWorkspace";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { Loading, ReadFailed } from "@/components/ui/states";
import { Textarea } from "@/components/ui/textarea";
import {
  CARD, Chip, Empty, Figure, Figures, Label, MUTED, NeedsRow, NeedsYou, NUM, ONE_LINE, Page, ROW, RULE, type Tone,
} from "@/components/clarity/kit";
import { formatCount } from "@/lib/format";
import {
  bandOf, bandText, cellOf, day, floorOf, measuresConsistency, noteOf, passRate, plural, rate, runBlock, suiteState,
  targetWords, type RunState, type SuiteState,
} from "@/lib/evalSummary";

type View = "list" | "detail" | "form";
type Detail = EvalSuite & { cases: EvalCase[] };

interface Props {
  connId?: string;
  workspaceId?: string;
  onLayerChange?: (l: EvalsLayer) => void;
}

/** How many runs the page reads to find each suite's last result. A suite with no run among them reads as never run,
 *  so the page says when the read was cut at this. */
const RUN_LIMIT = 500;

/** Cases a suite shows before "Show all". */
const CASES_SHOWN = 25;

// ── Main component ────────────────────────────────────────────────────────────

export function EvalSuitesPanel({ connId, onLayerChange }: Props) {
  const [view, setView] = useState<View>("list");
  const [suites, setSuites] = useState<EvalSuite[]>([]);
  const [runs, setRuns] = useState<EvalRun[] | null>([]);
  /** Each suite's cases — null where the read failed, absent while it is being read. */
  const [cases, setCases] = useState<Record<string, EvalCase[] | null>>({});
  const [connections, setConnections] = useState<Connection[]>([]);
  const [evaluators, setEvaluators] = useState<EvalEvaluator[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [readFailed, setReadFailed] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", description: "", connection_id: connId ?? "" });
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState<Detail | null>(null);
  /** The suite a row's Run is running, and what each finished run said. */
  const [running, setRunning] = useState<string | null>(null);
  const [ran, setRan] = useState<Record<string, string>>({});

  const readRuns = useCallback(async () => {
    setRuns(await getEvalRuns(undefined, RUN_LIMIT).catch(() => null));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ss, cs, evs] = await Promise.all([
        getEvalSuites(),
        getConnections().catch(() => [] as Connection[]),
        getEvaluators().then(r => r.evaluators).catch(() => [] as EvalEvaluator[]),
        readRuns(),
      ]);
      setSuites(ss);
      setConnections(cs);
      setEvaluators(evs);
      setReadFailed(null);
      setLoaded(true);
      // The case counts come from each suite's own read — the list carries none.
      const reads = await Promise.allSettled(ss.map(s => getEvalSuite(s.id)));
      setCases(Object.fromEntries(ss.map((s, i) => {
        const r = reads[i];
        return [s.id, r.status === "fulfilled" ? r.value.cases : null];
      })));
    } catch (e) {
      setReadFailed(e instanceof Error ? e.message : "the read failed");
    } finally {
      setLoading(false);
    }
  }, [readRuns]);

  useEffect(() => { load(); }, [load]);

  const connName = useCallback((id: string) => {
    if (!id) return "no connection";
    return connections.find(c => c.id === id)?.name ?? "a connection no longer listed";
  }, [connections]);

  // ── Actions ──────────────────────────────────────────────────────────────────

  function openCreate() {
    setForm({ name: "", description: "", connection_id: connId ?? "" });
    setError(null);
    setView("form");
  }

  async function openDetail(suiteId: string) {
    setError(null);
    try {
      const d = await getEvalSuite(suiteId);
      setDetail(d);
      setCases(p => ({ ...p, [suiteId]: d.cases }));
      setView("detail");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open the suite");
    }
  }

  async function saveSuite() {
    if (!form.name.trim()) { setError("A suite needs a name"); return; }
    setSaving(true);
    setError(null);
    try {
      const created = await createEvalSuite({
        name: form.name.trim(),
        description: form.description.trim(),
        target: "reference",
        connection_id: form.connection_id,
      });
      await load();
      await openDetail(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the suite");
    } finally {
      setSaving(false);
    }
  }

  async function removeSuite(id: string) {
    if (!confirm("Delete this suite and all its cases and runs?")) return;
    try {
      await deleteEvalSuite(id);
      if (detail?.id === id) { setDetail(null); setView("list"); }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  async function refreshDetail() {
    if (!detail) return;
    try {
      const d = await getEvalSuite(detail.id);
      setDetail(d);
      setCases(p => ({ ...p, [d.id]: d.cases }));
    } catch { /* keep the prior read */ }
  }

  /** Run a suite once from its row; the row's result chip reads the new run when it lands. */
  async function runFromRow(s: EvalSuite) {
    setRunning(s.id);
    setRan(p => ({ ...p, [s.id]: "" }));
    try {
      const sum = await runEvalSuite(s.id, { iterations: 1 });
      setRan(p => ({ ...p, [s.id]: `Finished · ${rate(sum.pass_rate)} · ${sum.stable_pass} of ${sum.total} stable` }));
    } catch (e) {
      setRan(p => ({ ...p, [s.id]: e instanceof Error ? e.message : "The run failed" }));
    } finally {
      setRunning(null);
      await readRuns();
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <Page testId={view === "list" ? "eval-suites" : view === "form" ? "eval-suite-new" : "eval-suite-detail"}>
      {error && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>{error}</div>}
      {readFailed && <ReadFailed what="the eval suites" error={readFailed} onRetry={load} />}
      {!loaded && loading && <Loading what="eval suites" />}

      {view === "list" && loaded && !readFailed && (suites.length === 0
        ? <NoSuites onNew={openCreate} />
        : <Overview suites={suites} runs={runs} cases={cases} connName={connName} running={running} ran={ran}
            onNew={openCreate} onOpen={openDetail} onRun={runFromRow} />)}

      {view === "form" && (
        <SuiteForm form={form} setForm={setForm} connections={connections} saving={saving}
          onSave={saveSuite} onCancel={() => setView("list")} />
      )}

      {view === "detail" && detail && (
        <SuiteDetail suite={detail} runs={runs} connName={connName(detail.connection_id)} evaluators={evaluators}
          onBack={() => { setView("list"); load(); }} onChanged={refreshDetail} onRan={readRuns}
          onDelete={() => removeSuite(detail.id)} onViewRuns={() => onLayerChange?.("runs")} setError={setError} />
      )}
    </Page>
  );
}

// ── The overview: figures, Needs you, the list ───────────────────────────────────

function Overview({ suites, runs, cases, connName, running, ran, onNew, onOpen, onRun }: {
  suites: EvalSuite[];
  runs: EvalRun[] | null;
  cases: Record<string, EvalCase[] | null>;
  connName: (id: string) => string;
  running: string | null;
  ran: Record<string, string>;
  onNew: () => void;
  onOpen: (id: string) => void;
  onRun: (s: EvalSuite) => void;
}) {
  const state = useMemo(() => Object.fromEntries(suites.map(s => [s.id, suiteState(s.id, runs ?? [])])) as
    Record<string, SuiteState>, [suites, runs]);
  const runsRead = runs !== null;
  const cut = runsRead && runs.length >= RUN_LIMIT;
  const ranOnce = suites.filter(s => state[s.id].last);
  const never = suites.filter(s => !state[s.id].last);
  const measured = suites.filter(s => state[s.id].lastRate != null);
  const full = measured.filter(s => (state[s.id].lastRate as number) >= 0.9995);
  const caseReads = suites.map(s => cases[s.id]);
  const casesPending = caseReads.some(c => c === undefined);
  const casesFailed = caseReads.filter(c => c === null).length;
  const totalCases = caseReads.reduce((n, c) => n + (c?.length ?? 0), 0);
  const count = (s: EvalSuite) => {
    const c = cases[s.id];
    return c === undefined ? "… cases" : c === null ? "cases unread" : plural(c.length, "case");
  };

  const runButton = (s: EvalSuite, variant: "secondary" | "outline") => {
    const block = runBlock(s);
    const n = cases[s.id]?.length;
    return block ? null : (
      <Button size="xs" variant={variant} disabled={running !== null} onClick={() => onRun(s)}
        title={`Replays ${n != null ? plural(n, "query", "queries") : "each case's SQL"} on ${connName(s.connection_id)} once — no model calls`}>
        {running === s.id ? "Running…" : "Run"}
      </Button>
    );
  };
  const openButton = (s: EvalSuite) => <Button size="xs" variant="ghost" onClick={() => onOpen(s.id)}>Open</Button>;

  const needs = runsRead ? suites.flatMap(s => {
    const st = state[s.id];
    const block = runBlock(s);
    const where = [count(s), targetWords(s.target), s.connection_id ? connName(s.connection_id) : ""].filter(Boolean).join(" · ");
    const actions = <>{block && <Chip title={block.why}>{block.chip}</Chip>}{runButton(s, "secondary")}{openButton(s)}</>;
    if (!st.last) {
      return [<NeedsRow key={`never-${s.id}`} testId="needs-never" title={`${s.name} has never run`}
        detail={cut ? `${where} · no run among the latest ${formatCount(RUN_LIMIT)}` : where} actions={actions} />];
    }
    if (st.regressed) {
      return [<NeedsRow key={`fell-${s.id}`} testId="needs-fell"
        title={`${s.name} fell to ${rate(st.regressed.to)}`}
        detail={`from ${rate(st.regressed.from)} the run before, same set-up · ${day(st.last.started_at)}`} actions={actions} />];
    }
    if (st.lastState === "failed") {
      return [<NeedsRow key={`failed-${s.id}`} testId="needs-failed" title={`${s.name}: its last run failed`}
        detail={`${day(st.last.started_at)}${noteOf(st.last) ? ` · ${noteOf(st.last)}` : " · no result came back"}`}
        actions={actions} />];
    }
    if (st.lastState === "unfinished") {
      return [<NeedsRow key={`stuck-${s.id}`} testId="needs-unfinished" title={`${s.name}: its last run never finished`}
        detail={`marked running since ${day(st.last.started_at)}`} actions={actions} />];
    }
    return [];
  }) : [];

  return (
    <>
      <Figures testId="suite-figures">
        <Figure label="Suites" value={formatCount(suites.length)} testId="fig-suites"
          sub={runsRead ? `${ranOnce.length} have run · ${never.length} never` : "runs could not be read"} />
        <Figure label="Cases" testId="fig-cases" value={casesPending || casesFailed ? "—" : formatCount(totalCases)}
          sub={casesPending ? "reading each suite…"
            : casesFailed ? `${plural(casesFailed, "suite")} could not be read` : `across ${plural(suites.length, "suite")}`} />
        <Figure label="Passed in full" testId="fig-full" value={runsRead ? `${full.length} of ${measured.length}` : "—"}
          title="Every case passed in every iteration of the suite's last run"
          sub={!runsRead ? "runs could not be read" : measured.length === full.length
            ? "every last run passed every case" : `${measured.length - full.length} below 100% at their last run`} />
        <Figure label="Never run" testId="fig-never" value={runsRead ? formatCount(never.length) : "—"}
          tone={runsRead && never.length ? "amber" : undefined}
          sub={!runsRead ? "runs could not be read" : never.length ? "no measurement yet" : "every suite has a result"} />
      </Figures>

      {runsRead ? (
        <NeedsYou testId="suite-needs" empty="Nothing needs you · every suite has run, and none fell or failed at its last run">
          {needs}
        </NeedsYou>
      ) : <Empty>{"Could not read the runs, so no suite's last result is known."}</Empty>}

      <section aria-label="Suites" data-testid="suite-list" style={CARD}>
        <Label right={<>
          <Chip title="A run replays each case's own SQL on the suite's connection and scores it — no model is called">
            a run replays SQL · no model calls
          </Chip>
          <Button size="xs" variant="outline" onClick={onNew}><Icon name="plus" size={12} />New suite</Button>
        </>}>Suites</Label>
        {suites.map((s, i) => (
          <SuiteRow key={s.id} suite={s} first={i === 0} state={state[s.id]} runsRead={runsRead} cases={count(s)}
            conn={connName(s.connection_id)} ran={ran[s.id]} runButton={runButton(s, "outline")}
            onOpen={() => onOpen(s.id)} />
        ))}
      </section>
    </>
  );
}

/** The last result as a chip: green at 100%, amber where it fell, red where it failed, plain otherwise. */
function resultChip(st: SuiteState, runsRead: boolean): { tone: Tone; text: string; title?: string } {
  if (!runsRead) return { tone: "plain", text: "result unread" };
  if (!st.last) return { tone: "amber", text: "never run" };
  if (st.lastState === "failed") return { tone: "down", text: "last run failed", title: noteOf(st.last) || undefined };
  if (st.lastState === "unfinished") return { tone: "plain", text: "never finished", title: `Marked running since ${day(st.last.started_at)}` };
  if (st.lastState === "running") return { tone: "accent", text: "running" };
  if (st.lastRate == null) return { tone: "plain", text: "no result" };
  const s = st.last.summary;
  const of = s?.total != null ? ` · ${s.stable_pass ?? 0}/${s.total}` : "";
  if (st.regressed) return { tone: "amber", text: `${rate(st.lastRate)}${of}`, title: `Fell from ${rate(st.regressed.from)}` };
  return { tone: st.lastRate >= 0.9995 ? "up" : "plain", text: `${rate(st.lastRate)}${of}`,
    title: "The share of cases that passed in every iteration of the last run" };
}

function SuiteRow({ suite, first, state, runsRead, cases, conn, ran, runButton, onOpen }: {
  suite: EvalSuite;
  first: boolean;
  state: SuiteState;
  runsRead: boolean;
  cases: string;
  conn: string;
  ran?: string;
  runButton: React.ReactNode;
  onOpen: () => void;
}) {
  const chip = resultChip(state, runsRead);
  const block = runBlock(suite);
  // The connection is named where there is one; a suite without one says why it cannot run in its chip instead.
  const meta = [cases, targetWords(suite.target), suite.connection_id ? conn : "",
    state.runs.length ? `×${state.runs.length} ${state.runs.length === 1 ? "run" : "runs"} · last ${day(state.last?.started_at)}` : "",
  ].filter(Boolean).join(" · ");
  return (
    <div data-testid="suite-row" style={{ ...(first ? {} : RULE), padding: "9px 2px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto auto", gap: 12, alignItems: "center" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span className="aug-fs-chrome" title={suite.description || suite.name}
              style={{ ...ONE_LINE, fontWeight: 600, color: "var(--t1)" }}>{suite.name}</span>
            {measuresConsistency(suite) && (
              <Chip title={suite.description}>consistency, not correctness</Chip>
            )}
          </div>
          <div className="aug-fs-xs" title={meta} style={{ ...MUTED, ...ONE_LINE }}>{meta}</div>
        </div>
        <Chip tone={chip.tone} title={chip.title} testId="suite-result">{chip.text}</Chip>
        {block ? <Chip title={block.why}>{block.chip}</Chip> : runButton}
        <Button size="xs" variant="ghost" onClick={onOpen}>Open</Button>
      </div>
      {ran && <div role="status" className="aug-fs-xs" style={{ ...MUTED, marginTop: 4 }}>{ran}</div>}
    </div>
  );
}

function NoSuites({ onNew }: { onNew: () => void }) {
  return (
    <section aria-label="Suites" style={CARD}>
      <Label right={<Button size="xs" variant="outline" onClick={onNew}><Icon name="plus" size={12} />New suite</Button>}>
        Suites
      </Label>
      <Empty>No eval suites yet — a suite replays the same cases and reports its score as a band, never a single run.</Empty>
    </section>
  );
}

// ── New suite ─────────────────────────────────────────────────────────────────

function SuiteForm({ form, setForm, connections, saving, onSave, onCancel }: {
  form: { name: string; description: string; connection_id: string };
  setForm: React.Dispatch<React.SetStateAction<{ name: string; description: string; connection_id: string }>>;
  connections: Connection[];
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <section aria-label="New suite" style={CARD}>
      <Label right={<Button size="xs" variant="ghost" onClick={onCancel}><Icon name="back" size={12} />All suites</Button>}>
        New suite
      </Label>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 560 }}>
        <Field label="Name">
          <Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            placeholder="e.g. Golden SQL — revenue questions" style={{ width: "100%" }} />
        </Field>
        <Field label="Description">
          <Textarea rows={2} value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            placeholder="What this suite measures" style={{ width: "100%", resize: "vertical" }} />
        </Field>
        <Field label="Connection" hint="Each case's SQL is replayed here and scored against itself — no model; expect about 100%.">
          <SelectField value={form.connection_id} onChange={e => setForm(f => ({ ...f, connection_id: e.target.value }))}
            style={{ width: "100%" }}>
            <option value="">Select a connection…</option>
            {connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </SelectField>
        </Field>
        <div style={ROW}>
          <Button size="xs" onClick={onSave} disabled={saving}>{saving ? "Creating…" : "Create suite"}</Button>
          <Button size="xs" variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
      </div>
    </section>
  );
}

// ── A suite, opened ──────────────────────────────────────────────────────────────

const STATE_WORDS: Record<RunState, string> = {
  measured: "finished", "no-result": "no result", failed: "failed", running: "running", unfinished: "never finished",
};

function SuiteDetail({ suite, runs, connName, evaluators, onBack, onChanged, onRan, onDelete, onViewRuns, setError }: {
  suite: Detail;
  /** Null when the runs could not be read — the figures then say so rather than "never run". */
  runs: EvalRun[] | null;
  connName: string;
  evaluators: EvalEvaluator[];
  onBack: () => void;
  onChanged: () => void;
  onRan: () => void;
  onDelete: () => void;
  onViewRuns: () => void;
  setError: (s: string | null) => void;
}) {
  const [iterations, setIterations] = useState(1);
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<EvalRunSummary | null>(null);
  const st = suiteState(suite.id, runs ?? []);
  const block = runBlock(suite);
  const det = evaluators.filter(e => e.deterministic).length;
  const lastCell = st.last ? cellOf(st.last) : null;
  const band = bandOf(st.runs.filter(r => cellOf(r) === lastCell).map(passRate).filter((v): v is number => v != null));
  const floor = floorOf(band);

  async function run() {
    setRunning(true);
    setError(null);
    setSummary(null);
    try {
      setSummary(await runEvalSuite(suite.id, { iterations }));
      onRan();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The run failed");
    } finally {
      setRunning(false);
    }
  }

  const s = st.last?.summary;
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Button size="xs" variant="ghost" onClick={onBack}><Icon name="back" size={12} />All suites</Button>
        <span className="aug-fs-h2" style={{ fontWeight: 600, color: "var(--t1)" }}>{suite.name}</span>
        <Chip>{targetWords(suite.target)}</Chip>
        <Chip>{connName}</Chip>
        {measuresConsistency(suite) && <Chip title={suite.description}>consistency, not correctness</Chip>}
      </div>
      {suite.description && (
        <div className="aug-fs-sm" title={suite.description} style={{ ...MUTED, ...ONE_LINE, marginTop: -6 }}>
          {suite.description}
        </div>
      )}

      <Figures testId="suite-detail-figures">
        <Figure label="Cases" value={formatCount(suite.cases.length)}
          sub={suite.target === "reference"
            ? `${suite.cases.filter(c => c.artifact.trim()).length} with SQL to replay` : "each checks one claim"} />
        <Figure label="Last result" testId="fig-last"
          value={runs && st.lastRate != null ? rate(st.lastRate) : !runs || st.last ? "—" : "never run"}
          tone={st.regressed ? "amber" : st.lastState === "failed" ? "red" : undefined}
          sub={!runs ? "runs could not be read" : !st.last ? "no measurement yet"
            : st.lastRate == null ? `${STATE_WORDS[st.lastState ?? "no-result"]} · ${day(st.last.started_at)}`
            : `${s?.stable_pass ?? 0} of ${s?.total ?? 0} stable · ${day(st.last.started_at)}${st.regressed ? ` · fell from ${rate(st.regressed.from)}` : ""}`} />
        <Figure label="Runs" value={runs ? formatCount(st.runs.length) : "—"}
          title="Runs of the last run's set-up are its replicates; their spread is its band"
          sub={!runs ? "runs could not be read" : floor === "none" ? "nothing measured yet" : floor === "single" ? "1 replicate — no band"
            : `${bandText(band)} over ${band?.n} replicates`} />
      </Figures>

      <section aria-label="Run" style={CARD}>
        <Label right={block ? undefined : <>
          <Chip>no model calls</Chip>
          <Chip title="Each iteration replays every case once">
            {`replays ${formatCount(suite.cases.length * iterations)} ${suite.cases.length * iterations === 1 ? "query" : "queries"} on ${connName}`}
          </Chip>
          {det > 0 && <Chip title="Checks that read the SQL itself, the same way every time">{`${det} deterministic checks`}</Chip>}
        </>}>Run</Label>
        {block ? <Empty title={block.why}>{`${block.why}.`}</Empty> : (
          <>
            <div style={ROW}>
              <span className="aug-fs-xs" style={MUTED}>Iterations</span>
              <Input type="number" min={1} max={10} value={iterations} aria-label="Iterations"
                onChange={e => setIterations(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} style={{ width: 64 }}
                title="Repeat each case this many times — a case that passes some but not all is flaky, not rounded to a pass" />
              <Button size="xs" onClick={run} disabled={running || suite.cases.length === 0}>
                {running ? "Running…" : "Run suite"}
              </Button>
              {!summary && <span className="aug-fs-xs" style={MUTED}>
                A case that passes only some iterations counts as flaky — never rounded into the pass rate.
              </span>}
            </div>
            {summary && <RunSummaryView summary={summary} onViewRuns={onViewRuns} />}
          </>
        )}
      </section>

      <CasesCard suite={suite} onChanged={onChanged} setError={setError} />

      <div>
        <Button size="xs" variant="destructive" onClick={onDelete}><Icon name="trash" size={12} />Delete suite</Button>
      </div>
    </>
  );
}

function RunSummaryView({ summary, onViewRuns }: { summary: EvalRunSummary; onViewRuns: () => void }) {
  const fired = Object.entries(summary.fired_counts || {}).sort((a, b) => b[1] - a[1]);
  return (
    <div data-testid="run-summary" style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
      <Figures>
        <Figure label="Pass rate (stable)" value={rate(summary.pass_rate)}
          sub={`${summary.stable_pass} of ${summary.total} · ${plural(summary.iterations, "iteration")}`} />
        <Figure label="Flaky" value={formatCount(summary.flaky)} tone={summary.flaky ? "amber" : undefined}
          sub="passed some iterations, not all" />
        <Figure label="Errors" value={formatCount(summary.errors)} tone={summary.errors ? "red" : undefined}
          sub={`${summary.stable_fail} failed every iteration`} />
        {(summary.accuracy != null || summary.robustness != null) && (
          <Figure label={summary.accuracy != null ? "Accuracy" : "Robustness"}
            value={rate(summary.accuracy ?? summary.robustness)}
            sub={summary.accuracy != null && summary.robustness != null ? `robustness ${rate(summary.robustness)}`
              : summary.accuracy != null ? `${summary.correct} of ${summary.correctness_known} declared an answer` : undefined} />
        )}
      </Figures>
      <div style={ROW}>
        {fired.map(([name, n]) => (
          <Chip key={name} title="A check that failed on at least one case">
            <code style={{ fontFamily: "var(--font-code)" }}>{name}</code> ×{n}
          </Chip>
        ))}
        <span style={{ flex: 1 }} />
        <Button size="xs" variant="ghost" onClick={onViewRuns}>See runs</Button>
      </div>
    </div>
  );
}

function CasesCard({ suite, onChanged, setError }: {
  suite: Detail;
  onChanged: () => void;
  setError: (s: string | null) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [question, setQuestion] = useState("");
  const [artifact, setArtifact] = useState("");
  const [saving, setSaving] = useState(false);
  const [all, setAll] = useState(false);
  const shown = all ? suite.cases : suite.cases.slice(0, CASES_SHOWN);

  async function addCase() {
    if (!artifact.trim()) { setError("A case needs SQL to replay"); return; }
    setSaving(true);
    setError(null);
    try {
      await addEvalCases(suite.id, [{ question: question.trim(), artifact: artifact.trim() }]);
      setQuestion(""); setArtifact(""); setAdding(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add the case");
    } finally {
      setSaving(false);
    }
  }

  async function removeCase(id: string) {
    try { await deleteEvalCase(id); onChanged(); }
    catch (e) { setError(e instanceof Error ? e.message : "Delete failed"); }
  }

  return (
    <section aria-label="Cases" data-testid="suite-cases" style={CARD}>
      <Label right={<>
        <span style={NUM}>{formatCount(suite.cases.length)}</span>
        {!adding && <Button size="xs" variant="outline" onClick={() => setAdding(true)}><Icon name="plus" size={12} />Add case</Button>}
      </>}>Cases</Label>

      {adding && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 10, maxWidth: 720 }}>
          <Input value={question} onChange={e => setQuestion(e.target.value)} aria-label="Question"
            placeholder="Question (a label, e.g. 'Total revenue by month')" style={{ width: "100%" }} />
          <Textarea rows={3} value={artifact} onChange={e => setArtifact(e.target.value)} aria-label="SQL"
            placeholder="SELECT … — the SQL this case replays" style={{ width: "100%", resize: "vertical" }} />
          <div style={ROW}>
            <Button size="xs" onClick={addCase} disabled={saving}>{saving ? "Adding…" : "Add case"}</Button>
            <Button size="xs" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
          </div>
        </div>
      )}

      {suite.cases.length === 0 ? <Empty>No cases yet — a case is a question and the SQL it replays.</Empty> : (
        <>
          {shown.map((c, i) => (
            <div key={c.id} data-testid="case-row" style={{ ...(i === 0 ? {} : RULE), padding: "7px 2px",
              display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12, alignItems: "center" }}>
              <div style={{ minWidth: 0 }}>
                <div className="aug-fs-sm" title={c.question} style={{ ...ONE_LINE, color: "var(--t1)" }}>
                  {c.question || <span style={MUTED}>No question</span>}
                </div>
                {c.artifact.trim() ? (
                  <code className="aug-fs-xs" title={c.artifact} style={{ ...ONE_LINE, display: "block", ...MUTED,
                    fontFamily: "var(--font-code)" }}>{c.artifact.replace(/\s+/g, " ")}</code>
                ) : suite.target === "reference" && <Chip>no SQL</Chip>}
              </div>
              <Button size="xs" variant="ghost" onClick={() => removeCase(c.id)}>Remove</Button>
            </div>
          ))}
          {suite.cases.length > CASES_SHOWN && (
            <Button size="xs" variant="ghost" onClick={() => setAll(a => !a)} style={{ marginTop: 6 }}>
              {all ? "Show fewer" : `Show all ${formatCount(suite.cases.length)}`}
            </Button>
          )}
        </>
      )}
    </section>
  );
}

// ── Small helpers ─────────────────────────────────────────────────────────────

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <span className="aug-fs-xs" style={MUTED}>{label}</span>
      {children}
      {hint && <span className="aug-fs-xs" style={MUTED}>{hint}</span>}
    </div>
  );
}
