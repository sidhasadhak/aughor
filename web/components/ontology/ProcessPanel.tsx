"use client";

/**
 * ON-9 — one declared process, as its measurement counted it (ROADMAP §3.15, the second movement).
 *
 * A process is a type's stages in order — each anchored to the moment an object reaches it, or to the states that
 * place it there — and on a stage the promise the business makes about reaching it. Everything here is what
 * `GET /ontology/processes` says the data COUNTED: how many objects reach each stage, how long the move from the
 * stage before takes (calendar days at the 50th, 90th and 95th percentile, and how many objects reach a stage before
 * the one before it), and for each promise how many objects broke it, how many have not reached the stage yet and how
 * many of those are already past it. A promise the data never or always breaks is flagged in red, because a deadline
 * read from the wrong column breaks nothing or everything. The names a promise derives — its late segment and its
 * breach rate — are shown under it: they are what the object door compiles.
 */
import React, { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { SkeletonRows } from "@/components/ui/motion";
import { toast } from "@/components/ui/toast";
import { overdueSegmentOf, processCockpitHolds, processCockpitSpec, startCockpit } from "@/lib/cockpit/start";
import { formatCount } from "@/lib/format";
import { requestTab } from "@/lib/navigate";
import {
  declareImpact,
  deleteImpact,
  deleteProcess,
  getProcesses,
  previewImpact,
  type DeclaredImpactSpec,
  type DerivedRow,
  type ImpactDetail,
  type ProcessDetail,
  type ProcessPromise,
  type ProcessStageDetail,
  type ProcessTransition,
} from "@/lib/objectTypes";

const MONO: React.CSSProperties = { fontFamily: "var(--font-mono)" };
const RULE = "1px solid var(--b1)";

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** A count exactly as the data gave it — never rounded to "10.4K" where a person checks it against a query. */
const count = formatCount;

function share(rate: number | null | undefined): string {
  if (rate == null) return "—";
  return `${(rate * 100).toFixed(2)}%`;
}

function days(n: number | null | undefined): string {
  if (n == null) return "—";
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function Section({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section style={{ padding: "12px 16px", borderTop: RULE }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
        <h3 className="aug-fs-xs"
          style={{ margin: 0, color: "var(--t2)", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".06em" }}>
          {title}
        </h3>
        {aside && <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{aside}</span>}
      </div>
      {children}
    </section>
  );
}

function VerdictTag({ verified }: { verified: boolean | null }) {
  if (verified === true) return <span className="aug-tag aug-tag-green">measured</span>;
  if (verified === false) return <span className="aug-tag aug-tag-red">measured false</span>;
  return <span className="aug-tag aug-tag-gray">not counted</span>;
}

export function ProcessPanel({ connectionId, schema, processId, version, onOpenType, onClose, onChanged, onChangeProcess }: {
  connectionId: string;
  schema?: string;
  processId: string;
  /** Bumped when the map re-reads, so the panel re-reads with it. */
  version: number;
  onOpenType: (objectType: string) => void;
  onClose: () => void;
  onChanged: () => void;
  /** Arc OC-5 — open the designer on this process, to change it (a promise added, the moves expected). */
  onChangeProcess?: (process: ProcessDetail) => void;
}) {
  const [process, setProcess] = useState<ProcessDetail | null | undefined>(undefined);
  const [scope, setScope] = useState<{ processes: ProcessDetail[]; impacts: ImpactDetail[] }>({ processes: [], impacts: [] });
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setError("");
    getProcesses(connectionId, schema)
      .then((all) => {
        if (!live) return;
        setProcess(all.processes.find((p) => p.id === processId) ?? null);
        setScope({ processes: all.processes, impacts: all.impacts ?? [] });
      })
      .catch((e: unknown) => { if (live) setError(errorText(e)); });
    return () => { live = false; };
  }, [connectionId, schema, processId, version]);

  let body: React.ReactNode;
  if (error) body = <EmptyState icon="alert" title="This process could not be read">{error}</EmptyState>;
  else if (process === undefined || (process !== null && process.id !== processId)) {
    body = <div style={{ padding: 16 }}><SkeletonRows rows={8} /></div>;
  } else if (process === null) {
    body = (
      <EmptyState icon="info" title={`No process “${processId}”`}
        action={<Button variant="outline" size="sm" onClick={onClose}>Close</Button>}>
        It may have been withdrawn.
      </EmptyState>
    );
  } else {
    body = <ProcessView process={process} connectionId={connectionId} schema={schema} onOpenType={onOpenType}
      onClose={onClose} onChanged={onChanged} onChangeProcess={onChangeProcess} scope={scope} />;
  }
  return (
    <aside aria-label="Process" data-testid="process-panel"
      style={{ width: 360, flexShrink: 0, borderLeft: RULE, display: "flex", flexDirection: "column", minHeight: 0,
               background: "var(--bg-0)" }}>
      <div style={{ flex: 1, overflowY: "auto" }}>{body}</div>
    </aside>
  );
}

/** A cockpit for this process — its board, its open-and-overdue objects and one of them beside the table (2026-10-09).
 *  The walk-through found it offered only in the designer's own session, never for a process published earlier. */
function StartCockpitFor({ process, connectionId }: { process: ProcessDetail; connectionId: string }) {
  const [busy, setBusy] = useState(false);
  const segment = overdueSegmentOf(process);
  const start = async () => {
    setBusy(true);
    try {
      await startCockpit(connectionId, process.display_name,
        processCockpitSpec(process.display_name, process.id, process.entity_id, segment),
        `Started from the process ${process.display_name}`);
      requestTab("cockpit", { conn: connectionId });
    } catch (e) {
      toast.error("The cockpit was not made", { description: errorText(e).slice(0, 240) });
    } finally { setBusy(false); }
  };
  return (
    <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      <Button size="xs" variant="outline" data-testid="process-start-cockpit" disabled={busy || process.verified === false}
        onClick={() => void start()}>
        <Icon name="plus" size={12} /> {busy ? "Starting…" : "Start a cockpit for this process"}
      </Button>
      <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
        {process.verified === false ? "Not until it counts — see the note above." : processCockpitHolds(process)}
      </span>
    </div>
  );
}

function ProcessView({ process, connectionId, schema, onOpenType, onClose, onChanged, onChangeProcess, scope }: {
  process: ProcessDetail;
  connectionId: string;
  schema?: string;
  onOpenType: (objectType: string) => void;
  onClose: () => void;
  onChanged: () => void;
  onChangeProcess?: (process: ProcessDetail) => void;
  scope: { processes: ProcessDetail[]; impacts: ImpactDetail[] };
}) {
  const derived = [...process.derived.segments, ...process.derived.metrics, ...process.derived.properties];
  return (
    <>
      <header style={{ padding: "14px 16px 12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <h2 className="aug-fs-h2" style={{ margin: 0, color: "var(--t1)" }}>{process.display_name}</h2>
          <span className="aug-tag aug-tag-gray">process</span>
          <VerdictTag verified={process.verified} />
          {process.origin !== "human" && (
            <span className="aug-tag aug-tag-violet" title={process.provenance || undefined}>
              {process.origin === "model" ? "proposed" : "from a pack"}
            </span>
          )}
        </div>
        <div className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)", marginTop: 2 }}>{process.id}</div>
        {process.description && (
          <p className="aug-fs-sm" style={{ margin: "8px 0 0", color: "var(--t2)", lineHeight: 1.5 }}>{process.description}</p>
        )}
        <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 8, display: "flex", alignItems: "center", gap: 4,
                                            flexWrap: "wrap" }}>
          <span>goes through it:</span>
          <Button variant="minimal" size="xs" onClick={() => onOpenType(process.entity)}>{process.entity}</Button>
          {process.owner && <span>· owned by {process.owner}</span>}
        </div>
        {process.note && (
          <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--t2)", lineHeight: 1.45 }} data-testid="process-note">
            {process.note}
          </p>
        )}
        {process.leaves && (
          <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--t2)", lineHeight: 1.45 }} data-testid="process-leaves">
            Leaves the process when {process.leaves.property} is {process.leaves.values.join(" or ")}
            {process.leaves.note ? ` — ${process.leaves.note}` : ""}
          </p>
        )}
        {process.measured_at && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>counted {process.measured_at}</div>
        )}
        <StartCockpitFor process={process} connectionId={connectionId} />
        {onChangeProcess && (
          <div style={{ marginTop: 8 }}>
            <Button size="xs" variant="outline" data-testid="process-change" onClick={() => onChangeProcess(process)}>
              <Icon name="edit" size={12} /> Change this process
            </Button>
          </div>
        )}
        <WithdrawProcess process={process} connectionId={connectionId} schema={schema} onClose={onClose}
          onChanged={onChanged} />
      </header>
      <Section title="Stages" aside={`${process.stages.length} in order`}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {process.stages.map((stage, i) => (
            <StageRow key={stage.name} stage={stage} index={i} onOpenType={onOpenType} process={process}
              scope={scope} connectionId={connectionId} schema={schema} onChanged={onChanged} />
          ))}
        </div>
      </Section>
      <MovesView process={process} />
      <Section title="Derives" aside="what the object door compiles">
        <DerivedList rows={derived} />
      </Section>
    </>
  );
}

function anchorWords(stage: ProcessStageDetail): string {
  return "timestamp" in stage.anchor ? stage.anchor.timestamp : `${stage.anchor.property} in ${stage.anchor.state.join(", ")}`;
}

function StageRow({ stage, index, onOpenType, process, scope, connectionId, schema, onChanged }: {
  stage: ProcessStageDetail;
  index: number;
  onOpenType: (objectType: string) => void;
  process: ProcessDetail;
  scope: { processes: ProcessDetail[]; impacts: ImpactDetail[] };
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const before = Object.entries(stage.precedes ?? {}).filter(([name]) => name !== stage.transition?.from);
  return (
    <div data-testid="process-stage" style={{ borderLeft: RULE, paddingLeft: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap" }}>
        <span className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)" }}>{index + 1}</span>
        <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600 }}>{stage.display_name}</span>
        {stage.verified === false && <span className="aug-tag aug-tag-red">no object reaches it</span>}
      </div>
      <div className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)", overflowWrap: "anywhere" }}>{anchorWords(stage)}</div>
      <div className="aug-fs-xs" style={{ color: "var(--t2)" }} title={stage.note}>
        {count(stage.reached)} reached{stage.share != null ? ` · ${share(stage.share)}` : ""}
      </div>
      {stage.transition && <TransitionLine transition={stage.transition} />}
      {before.map(([name, n]) => (
        <div key={name} className="aug-fs-xs" style={{ color: "var(--red5)" }} data-testid="process-stage-precedes">
          {count(n)} reached {stage.display_name} before {name}
        </div>
      ))}
      {!!stage.roles?.length && <RolesLine roles={stage.roles} onOpenType={onOpenType} />}
      {stage.promise && <PromiseBlock promise={stage.promise} stage={stage.name} onOpenType={onOpenType} />}
      {stage.promise && (
        <ImpactsOf process={process} noun={stage.promise.name} scope={scope} connectionId={connectionId} schema={schema}
          onChanged={onChanged} />
      )}
    </div>
  );
}

/** Arc OC-5 — the objects a stage touches, each with its role; the promise's lead object says why it is the one. */
function RolesLine({ roles, onOpenType }: { roles: NonNullable<ProcessStageDetail["roles"]>; onOpenType: (t: string) => void }) {
  return (
    <div className="aug-fs-xs" style={{ color: "var(--t3)", display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}
      data-testid="process-stage-roles">
      <span>touches</span>
      {roles.map((r) => (
        <span key={`${r.entity}:${r.role}`} title={r.why || undefined} style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
          <Button variant="minimal" size="xs" onClick={() => onOpenType(r.entity)}>{r.entity}</Button>
          <span>({r.role})</span>
        </span>
      ))}
    </div>
  );
}

/** Arc OC-5 — how objects move between the stages: each move the data makes with its count, those declared marked,
 *  and where the two disagree. */
function MovesView({ process }: { process: ProcessDetail }) {
  const observed = process.observed ?? [];
  if (!observed.length) return null;
  const c = process.conformance ?? {};
  const name = (id: string) => (id === "left" ? "leaves" : process.stages.find((s) => s.name === id)?.display_name ?? id);
  return (
    <Section title="How objects move" aside={process.transitions?.length ? "the moves declared are marked" : "each stage to the next is expected"}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {observed.map((m) => (
          <div key={`${m.from_stage}>${m.to_stage}`} className="aug-fs-xs" data-testid="process-move"
            style={{ display: "flex", alignItems: "center", gap: 6, color: m.declared ? "var(--t1)" : "var(--t2)" }}>
            <span>{name(m.from_stage)} → {name(m.to_stage)}</span>
            <span style={{ color: "var(--t3)" }}>{count(m.objects)}</span>
            {m.declared ? <span className="aug-tag aug-tag-gray">expected</span>
              : m.objects ? <span className="aug-tag aug-tag-amber">nobody declared it</span> : null}
            {m.declared && !m.objects && <span className="aug-tag aug-tag-gray">never happens</span>}
          </div>
        ))}
      </div>
      {!!c.untimed?.length && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 6 }}>
          Not counted as moves: {c.untimed.join(", ")} — reached by a status, which has no moment.
        </div>
      )}
    </Section>
  );
}

/** Arc OC-5 — the impacts into a promise and out of it, each in its reader's words, and a way to declare one. */
function ImpactsOf({ process, noun, scope, connectionId, schema, onChanged }: {
  process: ProcessDetail;
  noun: string;
  scope: { processes: ProcessDetail[]; impacts: ImpactDetail[] };
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const ref = `${process.id}.${noun}`;
  const into = scope.impacts.filter((i) => i.downstream === ref);
  const outOf = scope.impacts.filter((i) => i.upstream === ref);
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 6 }} data-testid="process-impacts">
      {into.map((i) => <ImpactLine key={i.id} impact={i} side="upstream" connectionId={connectionId} schema={schema} onChanged={onChanged} />)}
      {outOf.map((i) => <ImpactLine key={i.id} impact={i} side="downstream" connectionId={connectionId} schema={schema} onChanged={onChanged} />)}
      {open ? (
        <ImpactForm downstream={ref} scope={scope} connectionId={connectionId} schema={schema}
          onDone={(made) => { setOpen(false); if (made) onChanged(); }} />
      ) : (
        <Button size="xs" variant="ghost" data-testid="impact-new" onClick={() => setOpen(true)}>
          <Icon name="plus" size={12} /> What bears on this promise?
        </Button>
      )}
    </div>
  );
}

const MECHANISM_WORDS: Record<ImpactDetail["mechanism"], string> = {
  influence: "influence, measured",
  validated: "validated on evidence",
  formula: "by definition",
};

function ImpactLine({ impact: i, side, connectionId, schema, onChanged }: {
  impact: ImpactDetail;
  side: "upstream" | "downstream";
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const withdraw = async () => {
    setBusy(true);
    try { await deleteImpact(connectionId, i.id, schema); onChanged(); }
    catch (e) { toast.error("Not withdrawn", { description: errorText(e).slice(0, 240) }); setBusy(false); }
  };
  return (
    <div className="aug-panel" data-testid="impact-line" style={{ padding: "6px 8px", marginTop: 4 }}>
      <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span style={{ color: "var(--t2)", fontWeight: 600 }}>{side === "upstream" ? "Upstream of it" : "Downstream of it"}</span>
        <span className="aug-tag aug-tag-gray">{MECHANISM_WORDS[i.mechanism]}</span>
        <VerdictTag verified={i.verified} />
        <Button size="xs" variant="minimal" disabled={busy} style={{ marginLeft: "auto" }} onClick={() => void withdraw()}>
          Withdraw
        </Button>
      </div>
      <div className="aug-fs-xs" style={{ color: "var(--t1)", lineHeight: 1.45 }} data-testid="impact-reading">{i.reading}</div>
      {/* a reading that did not hold already ends with what was measured — said once */}
      {i.verified !== true && i.note && !i.reading.includes(i.note) && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>{i.note}</div>
      )}
      {i.flags.map((f) => <div key={f} className="aug-fs-xs" style={{ color: "var(--t3)" }}>{f}</div>)}
      {i.window && <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>read over {i.window}</div>}
    </div>
  );
}

/** Declare what bears on a promise: another promise, the mechanism, the window — counted first, written on the word. */
function ImpactForm({ downstream, scope, connectionId, schema, onDone }: {
  downstream: string;
  scope: { processes: ProcessDetail[]; impacts: ImpactDetail[] };
  connectionId: string;
  schema?: string;
  onDone: (made: boolean) => void;
}) {
  const promises = scope.processes.flatMap((p) => p.stages.filter((s) => s.promise)
    .map((s) => ({ ref: `${p.id}.${s.promise!.name}`, label: `${p.display_name} · ${s.promise!.name}` })))
    .filter((x) => x.ref !== downstream);
  const [upstream, setUpstream] = useState(promises[0]?.ref ?? "");
  const [mechanism, setMechanism] = useState<ImpactDetail["mechanism"]>("influence");
  const [windowDays, setWindowDays] = useState("");
  const [says, setSays] = useState("");
  const [counted, setCounted] = useState<ImpactDetail | null>(null);
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const spec = (): DeclaredImpactSpec => {
    const id = `${upstream.split(".").pop()}_bears_on_${downstream.split(".").pop()}`.replace(/[^a-z0-9_]/gi, "_").toLowerCase();
    return { id, upstream, downstream, mechanism,
             ...(windowDays.trim() ? { window_days: Number(windowDays) } : {}),
             ...(mechanism === "formula" ? { formula: says.trim() } : mechanism === "validated" ? { evidence: says.trim() } : {}) };
  };
  const notReady = !upstream ? "No other promise is declared here to bear on this one."
    : windowDays.trim() && !/^\d+$/.test(windowDays.trim()) ? "The window is a whole number of days."
    : mechanism !== "influence" && !says.trim() ? (mechanism === "formula" ? "Say the definition that makes it exact." : "Name the recorded evidence.")
    : "";
  const run = async (what: "count" | "declare") => {
    setBusy(what);
    setProblem("");
    try {
      if (what === "count") setCounted(await previewImpact(connectionId, spec(), schema));
      else {
        await declareImpact(connectionId, spec(), schema);
        toast.success("Declared. It reaches readers when the release is published.");
        onDone(true);
      }
    } catch (e) { setProblem(errorText(e)); }
    finally { setBusy(""); }
  };
  return (
    <div className="aug-panel" data-testid="impact-form" style={{ padding: "8px", marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
      <SelectField value={upstream} aria-label="The promise that bears on it" onChange={(e) => { setUpstream(e.target.value); setCounted(null); }}>
        {promises.map((x) => <option key={x.ref} value={x.ref}>{x.label}</option>)}
      </SelectField>
      <SelectField value={mechanism} aria-label="How it bears on it"
        onChange={(e) => { setMechanism(e.target.value as ImpactDetail["mechanism"]); setCounted(null); }}>
        <option value="influence">An influence — measured on the data</option>
        <option value="validated">Validated — shown by recorded evidence</option>
        <option value="formula">By definition — exact, not measured</option>
      </SelectField>
      {mechanism !== "influence" && (
        <Input value={says} aria-label={mechanism === "formula" ? "The definition" : "The evidence"}
          placeholder={mechanism === "formula" ? "the delivery window starts when the order ships" : "decision d-123's outcome"}
          onChange={(e) => setSays(e.target.value)} />
      )}
      <Input value={windowDays} aria-label="Window in days" placeholder="all of the data — or the last N days"
        onChange={(e) => { setWindowDays(e.target.value); setCounted(null); }} />
      {counted && (
        <div className="aug-fs-xs" data-testid="impact-counted" style={{ color: "var(--t1)", lineHeight: 1.45 }}>
          {counted.reading}
          {counted.verified === false && !counted.reading.includes(counted.note) && (
            <div style={{ color: "var(--t3)" }}>{counted.note}</div>
          )}
        </div>
      )}
      {(problem || notReady) && <div className="aug-fs-xs" style={{ color: problem ? "var(--red5)" : "var(--t3)" }}>{problem || notReady}</div>}
      <div style={{ display: "flex", gap: 6 }}>
        <Button size="xs" variant="outline" disabled={!!busy || !!notReady} data-testid="impact-count" onClick={() => void run("count")}>
          {busy === "count" ? "Counting…" : "Count it"}
        </Button>
        <Button size="xs" disabled={!!busy || !!notReady || (!counted && mechanism !== "formula")} data-testid="impact-declare"
          onClick={() => void run("declare")}>
          {busy === "declare" ? "Declaring…" : "Declare it"}
        </Button>
        <Button size="xs" variant="ghost" onClick={() => onDone(false)}>Cancel</Button>
      </div>
    </div>
  );
}

function TransitionLine({ transition: t }: { transition: ProcessTransition }) {
  return (
    <div className="aug-fs-xs" style={{ color: "var(--t2)", marginTop: 2 }} data-testid="process-transition"
      title={`the per-object lag reads as ${t.lag}`}>
      from {t.from}: p50 {days(t.p50_days)} · p90 {days(t.p90_days)} · p95 {days(t.p95_days)} days
      {t.out_of_order ? <span style={{ color: "var(--red5)" }}> · {count(t.out_of_order)} before {t.from}</span> : null}
      {t.skipped ? <span style={{ color: "var(--t3)" }}> · {count(t.skipped)} with no {t.from} moment</span> : null}
    </div>
  );
}

function PromiseBlock({ promise: p, stage, onOpenType }: {
  promise: ProcessPromise;
  stage: string;
  onOpenType: (objectType: string) => void;
}) {
  const terms = p.kind === "deadline"
    ? `by ${p.deadline}`
    : p.kind === "within_hours"
      ? `within ${p.within_hours} hour${p.within_hours === 1 ? "" : "s"} of the stage before`
      : `within ${p.within_days} calendar day${p.within_days === 1 ? "" : "s"} of the stage before`;
  return (
    <div className="aug-panel" data-testid="process-promise" style={{ marginTop: 6, padding: "6px 8px" }}>
      <div className="aug-fs-xs" style={{ color: "var(--t1)", fontWeight: 600 }}>The {p.name} promise — {terms}</div>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
        <span>kept per</span>
        <Button variant="minimal" size="xs" onClick={() => onOpenType(p.grain)}>{p.grain}</Button>
        {p.via && <span style={MONO}>via {p.via}</span>}
        {p.target != null && <span>· target {share(p.target)} kept</span>}
      </div>
      {p.verified === null ? (
        <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>not counted yet</div>
      ) : (
        <>
          <div className="aug-fs-sm" style={{ color: "var(--t1)" }} data-testid="process-promise-rate">
            {share(p.breach_rate)} broken
          </div>
          <div className="aug-fs-xs" style={{ color: "var(--t2)" }}>
            {count(p.breached)} of {count(p.reached)} that reached {stage} broke it
          </div>
          {!!p.open && (
            <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
              {count(p.open)} not {stage} yet
              {p.open_overdue != null ? ` · ${count(p.open_overdue)} already past it as of ${p.as_of}` : ""}
            </div>
          )}
        </>
      )}
      {p.flags.map((flag) => (
        <div key={flag} className="aug-fs-xs" style={{ color: "var(--red5)", lineHeight: 1.45 }} data-testid="process-promise-flag">
          {flag}
        </div>
      ))}
      <div className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)", marginTop: 4 }}>{p.segment} · {p.metric}</div>
    </div>
  );
}

/** ON-9 — the names a declared process or rule derives, and whether the compiler reads each yet. */
export function DerivedList({ rows }: { rows: DerivedRow[] }) {
  if (!rows.length) return <EmptyState variant="inline" title="Nothing derived yet." />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.map((d) => (
        <div key={`${d.kind}:${d.name}`} data-testid="derived-row" title={d.source}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap" }}>
            <span className="aug-fs-xs" style={{ ...MONO, color: d.usable ? "var(--t1)" : "var(--t3)" }}>{d.name}</span>
            <span className="aug-tag aug-tag-gray">{d.kind}</span>
            {!d.usable && <span className="aug-tag aug-tag-red">refused</span>}
          </div>
          <div className="aug-fs-xs" style={{ color: "var(--t3)", lineHeight: 1.45 }}>{d.usable ? d.description : d.why_not}</div>
        </div>
      ))}
    </div>
  );
}

function WithdrawProcess({ process, connectionId, schema, onClose, onChanged }: {
  process: ProcessDetail;
  connectionId: string;
  schema?: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const withdraw = async () => {
    if (!armed) {
      setArmed(true);
      return;
    }
    setBusy(true);
    setProblem("");
    try {
      await deleteProcess(connectionId, process.id, schema);
      onChanged();
      onClose();
    } catch (e) {
      setProblem(errorText(e));
      setBusy(false);
    }
  };
  return (
    <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      <Button variant="ghost" size="xs" disabled={busy} onClick={withdraw} data-testid="process-withdraw"
        title="Withdraw this declared process — every name it derives stops resolving">
        {armed ? "Withdraw — sure?" : "Withdraw"}
      </Button>
      {armed && !busy && <Button variant="minimal" size="xs" onClick={() => setArmed(false)}>Keep it</Button>}
      {problem && <span className="aug-fs-xs" style={{ color: "var(--red5)" }}>{problem}</span>}
    </div>
  );
}
