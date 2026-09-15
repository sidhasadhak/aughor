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
import { EmptyState } from "@/components/ui/empty-state";
import { SkeletonRows } from "@/components/ui/motion";
import { formatCount } from "@/lib/format";
import {
  deleteProcess,
  getProcesses,
  type DerivedRow,
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

export function ProcessPanel({ connectionId, schema, processId, version, onOpenType, onClose, onChanged }: {
  connectionId: string;
  schema?: string;
  processId: string;
  /** Bumped when the map re-reads, so the panel re-reads with it. */
  version: number;
  onOpenType: (objectType: string) => void;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [process, setProcess] = useState<ProcessDetail | null | undefined>(undefined);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setError("");
    getProcesses(connectionId, schema)
      .then((all) => { if (live) setProcess(all.processes.find((p) => p.id === processId) ?? null); })
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
      onClose={onClose} onChanged={onChanged} />;
  }
  return (
    <aside aria-label="Process" data-testid="process-panel"
      style={{ width: 360, flexShrink: 0, borderLeft: RULE, display: "flex", flexDirection: "column", minHeight: 0,
               background: "var(--bg-0)" }}>
      <div style={{ flex: 1, overflowY: "auto" }}>{body}</div>
    </aside>
  );
}

function ProcessView({ process, connectionId, schema, onOpenType, onClose, onChanged }: {
  process: ProcessDetail;
  connectionId: string;
  schema?: string;
  onOpenType: (objectType: string) => void;
  onClose: () => void;
  onChanged: () => void;
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
        {process.measured_at && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>counted {process.measured_at}</div>
        )}
        <WithdrawProcess process={process} connectionId={connectionId} schema={schema} onClose={onClose}
          onChanged={onChanged} />
      </header>
      <Section title="Stages" aside={`${process.stages.length} in order`}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {process.stages.map((stage, i) => (
            <StageRow key={stage.name} stage={stage} index={i} onOpenType={onOpenType} />
          ))}
        </div>
      </Section>
      <Section title="Derives" aside="what the object door compiles">
        <DerivedList rows={derived} />
      </Section>
    </>
  );
}

function anchorWords(stage: ProcessStageDetail): string {
  return "timestamp" in stage.anchor ? stage.anchor.timestamp : `${stage.anchor.property} in ${stage.anchor.state.join(", ")}`;
}

function StageRow({ stage, index, onOpenType }: {
  stage: ProcessStageDetail;
  index: number;
  onOpenType: (objectType: string) => void;
}) {
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
      {stage.promise && <PromiseBlock promise={stage.promise} stage={stage.name} onOpenType={onOpenType} />}
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
