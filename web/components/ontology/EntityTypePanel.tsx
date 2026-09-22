"use client";

/**
 * ON-3b — the entity-type panel (ROADMAP §3.15, amended 2026-09-11): one object type, as the data measured it.
 *
 * Everything here is `GET /object-types/{type}` — the dict the agent also reads through `describe_entity` — so a
 * person and an agent asking what a Shipment is read one answer: the key and whether the data proved it unique;
 * the property that names one object, with its measurement and the door to declare another; every property with
 * its SOURCE; the bindings it is read from — its backing, the further sources a person bound and the ones the data
 * proposes (ON-1b); its links, each followed by the compiler or refused with the reason;
 * the declared actions that take it; its verified metrics; and a path finder that answers "how does this reach
 * that?" hop by hop. Nothing is inferred on the way to the screen — an unmeasured fact says so.
 */
import React, { useEffect, useState } from "react";
import Link from "next/link";

import { DerivedList } from "@/components/ontology/ProcessPanel";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { SkeletonRows } from "@/components/ui/motion";
import { countNoun, formatCount } from "@/lib/format";
import { declaredActionsHref } from "@/lib/objectLinks";
import {
  addBinding,
  confirmProposals,
  declareDisplayProperty,
  declareLink,
  declareProcess,
  declareRule,
  deleteEntity,
  deleteLink,
  getObjectType,
  getTypePaths,
  measureOntology,
  nameLink,
  previewBacking,
  removeBinding, restoreBinding, restoreLink, declareExpression, removeExpression,
  scopeDomain,
  setPartOf,
  setQueryBacking,
  withdrawBacking,
  type BackingPreview,
  type BindingSpec,
  type ConfirmTarget,
  type DeclaredLinkSpec,
  type DeclaredProcessSpec,
  type DeclaredRuleSpec,
  type FrameSpec,
  type ObjectTypeDetail,
  type PropertySource,
  type ProposedBinding,
  type RollupSpec,
  type TypeBinding,
  type TypeLink,
  type TypeMapRow,
  type TypePath,
  type TypePaths,
  type TypeProperty,
  type TypeRefusal,
} from "@/lib/objectTypes";

const MONO: React.CSSProperties = { fontFamily: "var(--font-mono)" };
const RULE = "1px solid var(--b1)";
const ROLE: Record<string, string> = {
  reference_data: "reference", business_object: "business object", event: "event", standalone: "standalone",
};
const RISK_TAG: Record<string, string> = { read_only: "aug-tag-green", low: "aug-tag-green", high: "aug-tag-red" };
const SELECT: React.CSSProperties = {
  ...MONO, background: "var(--bg-2)", color: "var(--t1)", border: RULE, borderRadius: "var(--r2)", padding: "2px 6px",
  maxWidth: 200,
};

const FIELD: React.CSSProperties = {
  ...MONO, background: "var(--bg-2)", color: "var(--t1)", border: RULE, borderRadius: "var(--r2)", padding: "2px 6px",
  minWidth: 0,
};

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
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

export function EntityTypePanel({ connectionId, schema, objectType, types, version, onOpen, onOpenProcess, onChanged,
  sources }: {
  connectionId: string;
  schema?: string;
  objectType: string;
  types: TypeMapRow[];
  /** Bumped when the map re-reads, so the panel re-reads with it. */
  version: number;
  onOpen: (objectType: string) => void;
  /** ON-9 — open a declared process this type takes part in. */
  onOpenProcess?: (processId: string) => void;
  /** A write here (a declaration, a measurement) changes what the map shows. */
  onChanged: () => void;
  /** ON-8 — set in an organisation's ontology: its connections by id, for the type, its bindings and a new binding. */
  sources?: Record<string, string>;
}) {
  const [detail, setDetail] = useState<ObjectTypeDetail | TypeRefusal | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setError("");
    getObjectType(objectType, connectionId, schema)
      .then((next) => { if (live) setDetail(next); })
      .catch((e: unknown) => { if (live) setError(errorText(e)); });
    return () => { live = false; };
  }, [objectType, connectionId, schema, version]);

  let body: React.ReactNode;
  if (error) body = <EmptyState icon="alert" title="This type could not be read">{error}</EmptyState>;
  else if (!detail || (detail.path === "object_type" && detail.object_type !== objectType)) {
    body = <div style={{ padding: 16 }}><SkeletonRows rows={8} /></div>;
  } else if (detail.path === "refused") {
    body = <EmptyState icon="info" title={`No object type “${objectType}”`}>{detail.refused}</EmptyState>;
  } else {
    body = <TypeDetail detail={detail} connectionId={connectionId} schema={schema} types={types}
      onOpen={onOpen} onOpenProcess={onOpenProcess} onChanged={onChanged} sources={sources} />;
  }
  return (
    <aside aria-label="Entity type" data-testid="entity-type-panel"
      style={{ width: 360, flexShrink: 0, borderLeft: RULE, display: "flex", flexDirection: "column", minHeight: 0,
               background: "var(--bg-0)" }}>
      <div style={{ flex: 1, overflowY: "auto" }}>{body}</div>
    </aside>
  );
}

function TypeDetail({ detail, connectionId, schema, types, onOpen, onOpenProcess, onChanged, sources }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  types: TypeMapRow[];
  onOpen: (objectType: string) => void;
  onOpenProcess?: (processId: string) => void;
  onChanged: () => void;
  sources?: Record<string, string>;
}) {
  const declared = detail.origin === "human" || detail.origin === "model";
  // ON-8 — in an organisation's ontology the doors that read one connection's graph (a display property, a part mark, a
  // link's name, an explorer's proposal, declared actions) are not offered: they would read a connection nobody holds.
  const inDomain = !!scopeDomain(connectionId);
  return (
    <>
      <header style={{ padding: "14px 16px 12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <h2 className="aug-fs-h2" style={{ margin: 0, color: "var(--t1)" }}>{detail.display_name}</h2>
          <span className="aug-tag aug-tag-gray">{ROLE[detail.role] ?? detail.role}</span>
          {detail.domain && <span className="aug-tag aug-tag-violet">{detail.domain}</span>}
          {declared && (
            <span className={`aug-tag ${detail.origin === "model" ? "aug-tag-violet" : "aug-tag-blue"}`}
              title={detail.origin === "model" ? `proposed by ${detail.provenance || "an explorer"}, not yet confirmed`
                : detail.provenance ? `declared — first proposed by ${detail.provenance}` : "declared by a person"}>
              {detail.origin === "model" ? "proposed" : "declared"}
            </span>
          )}
        </div>
        <div className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)", marginTop: 2 }}>{detail.object_type}</div>
        {sources && detail.connection_id && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }} data-testid="entity-connection">
            read from {sources[detail.connection_id] ?? detail.connection_id}
          </div>
        )}
        {detail.description && (
          <p className="aug-fs-sm" style={{ margin: "8px 0 0", color: "var(--t2)", lineHeight: 1.5 }}>{detail.description}</p>
        )}
        <PartOfLine detail={detail} connectionId={connectionId} schema={schema} onOpen={onOpen} onChanged={onChanged} />
        {detail.origin === "model" && !inDomain && (
          <div className="aug-fs-xs" style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span style={{ ...MONO, color: "var(--t3)" }}>{detail.provenance || "proposed by a model"}</span>
            <ConfirmProposal target={{ kind: "entity", entity: detail.id }} connectionId={connectionId} schema={schema}
              onChanged={onChanged} />
          </div>
        )}
        {declared && <WithdrawEntity detail={detail} connectionId={connectionId} schema={schema} onChanged={onChanged} />}
      </header>
      <KeySection detail={detail} />
      <DisplaySection detail={detail} connectionId={connectionId} schema={schema} onChanged={onChanged} readOnly={inDomain} />
      <PropertiesSection detail={detail} />
      {!inDomain && <ExpressionsSection detail={detail} connectionId={connectionId} schema={schema} onChanged={onChanged} />}
      <BindingsSection detail={detail} connectionId={connectionId} schema={schema} onChanged={onChanged} sources={sources} />
      <PartsSection detail={detail} types={types} connectionId={connectionId} schema={schema} onOpen={onOpen} onChanged={onChanged} />
      <LinksSection detail={detail} types={types} connectionId={connectionId} schema={schema} onOpen={onOpen} onChanged={onChanged}
        inDomain={inDomain} />
      <WithdrawnSection detail={detail} connectionId={connectionId} schema={schema} onChanged={onChanged} />
      {!inDomain && <ActionsSection detail={detail} connectionId={connectionId} />}
      <MetricsSection detail={detail} />
      <ProcessesSection detail={detail} connectionId={connectionId} schema={schema} onOpenProcess={onOpenProcess}
        onChanged={onChanged} />
      <PathFinder detail={detail} types={types} connectionId={connectionId} schema={schema} onOpen={onOpen} />
    </>
  );
}

/** ON-9 — the processes this type takes part in, and every name a declared process or rule derives on it: a segment,
 *  a lag, a breach rate — each read by the compiler once its declaration is measured, and refused with the reason
 *  until then. A process the type goes through and a rule over it are declared here, and counted before anything is
 *  written. */
function ProcessesSection({ detail, connectionId, schema, onOpenProcess, onChanged }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  onOpenProcess?: (processId: string) => void;
  onChanged: () => void;
}) {
  const processes = detail.processes ?? [];
  const derived = detail.derived ? [...detail.derived.segments, ...detail.derived.metrics, ...detail.derived.properties] : [];
  return (
    <Section title="Processes and rules" aside="what declarations derive here">
      {processes.map((p) => (
        <div key={p.id} style={{ display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap", marginBottom: 4 }}
          data-testid="type-process">
          <Button variant="minimal" size="xs" disabled={!onOpenProcess} onClick={() => onOpenProcess?.(p.id)}>
            {p.display_name}
          </Button>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{p.roles.join(" · ")}</span>
          {p.verified === false && <span className="aug-tag aug-tag-red">measured false</span>}
        </div>
      ))}
      {derived.length > 0 && <DerivedList rows={derived} />}
      {!processes.length && !derived.length && (
        <p className="aug-fs-xs" style={{ margin: "0 0 6px", color: "var(--t3)" }}>
          No declared process or rule touches this type yet.
        </p>
      )}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
        <DeclareProcess detail={detail} connectionId={connectionId} schema={schema} onOpenProcess={onOpenProcess}
          onChanged={onChanged} />
        <DeclareRule detail={detail} connectionId={connectionId} schema={schema} onChanged={onChanged} />
      </div>
    </Section>
  );
}

const SNAKE = /^[a-z][a-z0-9_]{0,63}$/;

function isMoment(p: TypeProperty): boolean {
  return p.role === "timestamp" || /DATE|TIME/i.test(p.data_type);
}

function listOf(text: string): string[] {
  return text.split(",").map((v) => v.trim()).filter(Boolean);
}

type StageDraft = { name: string; timestamp: string; terms: "" | "within_days" | "within_hours"; amount: string };
const NO_STAGE: StageDraft = { name: "", timestamp: "", terms: "", amount: "" };

/** ON-9 — declare a process the type goes through: its stages in order, each at the moment an object reaches it, and on
 *  a stage after the first the promise about reaching it — within N calendar days, or N hours, of the stage before.
 *  The server resolves every moment and counts the whole process before anything is written. A deadline promise, kept
 *  per another type, is declared through the API. */
function DeclareProcess({ detail, connectionId, schema, onOpenProcess, onChanged }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  onOpenProcess?: (processId: string) => void;
  onChanged: () => void;
}) {
  const moments = detail.properties.filter(isMoment);
  const [open, setOpen] = useState(false);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [stages, setStages] = useState<StageDraft[]>([NO_STAGE, NO_STAGE]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const edit = (i: number, change: Partial<StageDraft>) =>
    setStages((all) => all.map((s, j) => (j === i ? { ...s, ...change } : s)));
  const ready = SNAKE.test(id.trim()) && stages.length >= 2 && stages.every((s, i) =>
    SNAKE.test(s.name.trim()) && !!s.timestamp && (!s.terms || (i > 0 && /^\d+$/.test(s.amount.trim()))));
  const submit = async () => {
    setBusy(true);
    setProblem("");
    const spec: DeclaredProcessSpec = {
      id: id.trim(), entity: detail.id, ...(name.trim() ? { display_name: name.trim() } : {}),
      stages: stages.map((s) => ({
        name: s.name.trim(), timestamp: s.timestamp,
        ...(s.terms === "within_hours" ? { promise: { within_hours: Number(s.amount.trim()) } }
          : s.terms === "within_days" ? { promise: { within_days: Number(s.amount.trim()) } } : {}),
      })),
    };
    try {
      const made = await declareProcess(connectionId, spec, schema);
      setOpen(false);
      setId(""); setName(""); setStages([NO_STAGE, NO_STAGE]);
      onChanged();
      onOpenProcess?.(made.id);
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  if (!open) {
    return (
      <Button variant="outline" size="xs" onClick={() => setOpen(true)} disabled={moments.length < 2}
        title={moments.length < 2 ? "A process runs between two moments of this type, and it has fewer"
          : "Declare a process this type goes through — its stages, and the promises about reaching them"}>
        <Icon name="plus" size={12} /> Declare a process
      </Button>
    );
  }
  return (
    <div style={{ flexBasis: "100%", display: "flex", flexDirection: "column", gap: 6, padding: "8px 0", borderTop: RULE }}
      data-testid="process-declare">
      <p className="aug-fs-xs" style={{ margin: 0, color: "var(--t3)", lineHeight: 1.45 }}>
        A process {detail.display_name} goes through: its stages in order, each at the moment an object reaches it. Every
        moment is resolved and the whole process counted before anything is written.
      </p>
      <div style={{ display: "flex", gap: 6 }}>
        <input className="aug-fs-xs" style={{ ...FIELD, flex: 1 }} value={id} placeholder="id — order_fulfilment"
          aria-label="Process id" onChange={(e) => setId(e.target.value)} />
        <input className="aug-fs-xs" style={{ ...FIELD, flex: 1 }} value={name} placeholder="Display name (optional)"
          aria-label="Process display name" onChange={(e) => setName(e.target.value)} />
      </div>
      {stages.map((s, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <input className="aug-fs-xs" style={{ ...FIELD, width: 110 }} value={s.name} placeholder={i ? "shipped" : "placed"}
            aria-label={`Stage ${i + 1} name`} onChange={(e) => edit(i, { name: e.target.value })} />
          <select className="aug-fs-xs" style={SELECT} value={s.timestamp} aria-label={`Stage ${i + 1} moment`}
            onChange={(e) => edit(i, { timestamp: e.target.value })}>
            <option value="">moment…</option>
            {moments.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
          {i > 0 && (
            <select className="aug-fs-xs" style={SELECT} value={s.terms} aria-label={`Stage ${i + 1} promise`}
              onChange={(e) => edit(i, { terms: e.target.value as StageDraft["terms"] })}>
              <option value="">no promise</option>
              <option value="within_days">within days</option>
              <option value="within_hours">within hours</option>
            </select>
          )}
          {i > 0 && s.terms && (
            <input className="aug-fs-xs" style={{ ...FIELD, width: 56 }} value={s.amount} inputMode="numeric"
              placeholder={s.terms === "within_hours" ? "24" : "2"}
              aria-label={`Stage ${i + 1} promise ${s.terms === "within_hours" ? "hours" : "days"}`}
              onChange={(e) => edit(i, { amount: e.target.value })} />
          )}
          {i > 1 && (
            <Button variant="ghost" size="xs" disabled={busy}
              onClick={() => setStages((all) => all.filter((_, j) => j !== i))}>Remove</Button>
          )}
        </div>
      ))}
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <Button variant="ghost" size="xs" disabled={busy} onClick={() => setStages((all) => [...all, NO_STAGE])}>
          Add a stage
        </Button>
        <Button variant="outline" size="xs" disabled={busy || !ready} onClick={submit}>
          {busy ? "Counting…" : "Declare the process"}
        </Button>
        <Button variant="ghost" size="xs" disabled={busy} onClick={() => setOpen(false)}>Cancel</Button>
      </div>
      {problem && <p className="aug-fs-xs" style={{ margin: 0, color: "var(--red5)", lineHeight: 1.45 }}>{problem}</p>}
    </div>
  );
}

const OPS = ["=", "!=", "in", "not_in", ">", ">=", "<", "<=", "is_null", "not_null"];
const NO_VALUE = new Set(["is_null", "not_null"]);
const LISTED = new Set(["in", "not_in"]);

/** ON-9 — declare a rule over the type: a value set — the values of one property grouped under one name — or a
 *  condition, and the verified metrics of the type it scopes, each read within the rule wherever it is read. Compiled
 *  and counted before anything is written; the object door reads the rule as a segment named by its id. */
function DeclareRule({ detail, connectionId, schema, onChanged }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const groupable = detail.properties.filter((p) => !p.is_key && !isMoment(p));
  const [open, setOpen] = useState(false);
  const [id, setId] = useState("");
  const [kind, setKind] = useState<"value_set" | "condition">("condition");
  const [property, setProperty] = useState("");
  const [values, setValues] = useState("");
  const [op, setOp] = useState("=");
  const [value, setValue] = useState("");
  const [scopes, setScopes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const ready = SNAKE.test(id.trim()) && !!property && (kind === "value_set" ? listOf(values).length > 0
    : NO_VALUE.has(op) || (LISTED.has(op) ? listOf(value).length > 0 : !!value.trim()));
  const submit = async () => {
    setBusy(true);
    setProblem("");
    const condition = { path: property, op,
      ...(NO_VALUE.has(op) ? {} : LISTED.has(op) ? { values: listOf(value) } : { value: value.trim() }) };
    const spec: DeclaredRuleSpec = { id: id.trim(), entity: detail.id, kind,
      ...(kind === "value_set" ? { property, values: listOf(values) } : { conditions: [condition] }),
      ...(scopes.length ? { scopes } : {}) };
    try {
      await declareRule(connectionId, spec, schema);
      setOpen(false);
      setId(""); setProperty(""); setValues(""); setOp("="); setValue(""); setScopes([]);
      onChanged();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  if (!open) {
    return (
      <Button variant="outline" size="xs" onClick={() => setOpen(true)}
        title="Declare a rule over this type — a value set or a condition, and the metrics it scopes">
        <Icon name="plus" size={12} /> Declare a rule
      </Button>
    );
  }
  return (
    <div style={{ flexBasis: "100%", display: "flex", flexDirection: "column", gap: 6, padding: "8px 0", borderTop: RULE }}
      data-testid="rule-declare">
      <p className="aug-fs-xs" style={{ margin: 0, color: "var(--t3)", lineHeight: 1.45 }}>
        A rule over {detail.display_name}: the values of one property grouped under one name, or a condition. It is
        compiled and counted before anything is written, and read as a segment named by its id.
      </p>
      <div style={{ display: "flex", gap: 6 }}>
        <input className="aug-fs-xs" style={{ ...FIELD, flex: 1 }} value={id} placeholder="id — fulfilled_orders"
          aria-label="Rule id" onChange={(e) => setId(e.target.value)} />
        <select className="aug-fs-xs" style={SELECT} value={kind} aria-label="Rule kind"
          onChange={(e) => { setKind(e.target.value as "value_set" | "condition"); setProperty(""); }}>
          <option value="condition">condition</option>
          <option value="value_set">value set</option>
        </select>
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <select className="aug-fs-xs" style={SELECT} value={property} aria-label="Rule property"
          onChange={(e) => setProperty(e.target.value)}>
          <option value="">property…</option>
          {(kind === "value_set" ? groupable : detail.properties).map((p) => (
            <option key={p.name} value={p.name}>{p.name}</option>
          ))}
        </select>
        {kind === "value_set" ? (
          <input className="aug-fs-xs" style={{ ...FIELD, flex: 1 }} value={values} placeholder="DE, AT, CH"
            aria-label="Rule values" onChange={(e) => setValues(e.target.value)} />
        ) : (
          <>
            <select className="aug-fs-xs" style={SELECT} value={op} aria-label="Rule operator"
              onChange={(e) => setOp(e.target.value)}>
              {OPS.map((o) => <option key={o} value={o}>{o.replace("_", " ")}</option>)}
            </select>
            {!NO_VALUE.has(op) && (
              <input className="aug-fs-xs" style={{ ...FIELD, flex: 1 }} value={value}
                placeholder={LISTED.has(op) ? "cancelled, refunded" : "value"} aria-label="Rule value"
                onChange={(e) => setValue(e.target.value)} />
            )}
          </>
        )}
      </div>
      {detail.metrics.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>scopes</span>
          {detail.metrics.map((m) => (
            <label key={m.id} className="aug-fs-xs" style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "var(--t2)" }}>
              <input type="checkbox" checked={scopes.includes(m.id)}
                onChange={(e) => setScopes((all) => (e.target.checked ? [...all, m.id] : all.filter((s) => s !== m.id)))} />
              {m.display_name || m.id}
            </label>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <Button variant="outline" size="xs" disabled={busy || !ready} onClick={submit}>
          {busy ? "Counting…" : "Declare the rule"}
        </Button>
        <Button variant="ghost" size="xs" disabled={busy} onClick={() => setOpen(false)}>Cancel</Button>
      </div>
      {problem && <p className="aug-fs-xs" style={{ margin: 0, color: "var(--red5)", lineHeight: 1.45 }}>{problem}</p>}
    </div>
  );
}

function KeySection({ detail }: { detail: ObjectTypeDetail }) {
  const { key } = detail;
  const verdict = key.verified === true ? ["aug-tag-green", "unique per object"]
    : key.verified === false ? ["aug-tag-red", "not unique per row"] : ["aug-tag-gray", "not yet measured"];
  return (
    <Section title="Key" aside={key.rows == null ? undefined : `measured over ${formatCount(key.rows)} rows`}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: "var(--t3)", display: "inline-flex" }}><Icon name="key" size={14} /></span>
        <span className="aug-fs-sm" style={{ ...MONO, color: "var(--t1)" }}>{key.property}</span>
        <span className={`aug-tag ${verdict[0]}`} data-testid="entity-key-verdict">{verdict[1]}</span>
      </div>
      {key.note && <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--t3)", lineHeight: 1.45 }}>{key.note}</p>}
    </Section>
  );
}

/** ON-7 — the type this one is a part of: named, openable, and releasable. A mark that no longer holds — the parent
 *  dropped the binding this type was read through — says so rather than pretending. */
function PartOfLine({ detail, connectionId, schema, onOpen, onChanged }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  onOpen: (objectType: string) => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const part = detail.part_of;
  if (!part) return null;
  const release = async () => {
    setBusy(true);
    setProblem("");
    try {
      await setPartOf(connectionId, detail.id, "", schema);
      onChanged();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="aug-fs-xs" style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}
      data-testid="entity-part-of">
      <span className={`aug-tag ${part.holds ? "aug-tag-blue" : "aug-tag-amber"}`}>{part.holds ? "part of" : "was a part of"}</span>
      {part.holds
        ? <Button variant="ghost" size="xs" onClick={() => onOpen(part.object_type)} title={`Open ${part.display_name}`}>{part.display_name}</Button>
        : <span style={{ color: "var(--t2)" }}>{part.display_name}</span>}
      <Button variant="minimal" size="xs" disabled={busy} onClick={release}
        title="Stand this type on its own again — its binding on the parent stays">
        {busy ? "Releasing…" : "Release"}
      </Button>
      {!part.holds && <span style={{ color: "var(--t3)", flexBasis: "100%", lineHeight: 1.45 }}>{part.note}</span>}
      {problem && <span style={{ color: "var(--red5)", flexBasis: "100%" }}>{problem}</span>}
    </div>
  );
}

/** ON-7 — withdraw a declared type. Two clicks, because the second one takes the type with it. A type the builder
 *  made from a table has no such door: it is absorbed into another, never deleted. */
function WithdrawEntity({ detail, connectionId, schema, onChanged }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const withdraw = async () => {
    setBusy(true);
    setProblem("");
    try {
      await deleteEntity(connectionId, detail.id, schema);
      onChanged();
    } catch (e) {
      setProblem(errorText(e));
      setArmed(false);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      {armed ? (
        <>
          <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>Withdraw {detail.display_name} and every link declared on it?</span>
          <Button variant="outline" size="xs" disabled={busy} onClick={withdraw} data-testid="entity-withdraw-confirm">
            {busy ? "Withdrawing…" : "Withdraw"}
          </Button>
          <Button variant="ghost" size="xs" disabled={busy} onClick={() => setArmed(false)}>Keep</Button>
        </>
      ) : (
        <Button variant="minimal" size="xs" onClick={() => setArmed(true)} data-testid="entity-withdraw"
          title="Withdraw this declared type">
          <Icon name="trash" size={12} /> Withdraw
        </Button>
      )}
      {problem && <span className="aug-fs-xs" style={{ color: "var(--red5)", flexBasis: "100%" }}>{problem}</span>}
    </div>
  );
}

/** ON-7b — make an explorer's proposal a person's. The declaration and its measurement stay exactly as they are; `origin`
 *  becomes human and the model that proposed it is kept beside it. A target that is not a model's proposal is refused
 *  with the reason, shown here. */
function ConfirmProposal({ target, connectionId, schema, onChanged }: {
  target: ConfirmTarget;
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const confirm = async () => {
    setBusy(true);
    setProblem("");
    try {
      const out = await confirmProposals(connectionId, { targets: [target] }, schema);
      if (out.refused.length) setProblem(out.refused.map((r) => r.why).join("; "));
      else onChanged();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button variant="outline" size="xs" disabled={busy} onClick={confirm} data-testid="proposal-confirm"
        title="Make this proposal yours — it stays exactly as it was measured">
        {busy ? "Confirming…" : "Confirm"}
      </Button>
      {problem && <span className="aug-fs-xs" style={{ color: "var(--red5)", flexBasis: "100%" }}>{problem}</span>}
    </>
  );
}

/** ON-7 — the types that are parts of this one: an order's lines, a return's logistics row. Each is still a type,
 *  openable by name, and read through the binding shown beside it. */
function PartsSection({ detail, types, connectionId, schema, onOpen, onChanged }: {
  detail: ObjectTypeDetail;
  types: TypeMapRow[];
  connectionId: string;
  schema?: string;
  onOpen: (objectType: string) => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const parts = detail.parts ?? [];
  if (parts.length === 0) return null;
  // The write doors take the entity id; the map row has it, and the api name resolves there too.
  const partId = (objectType: string) => types.find((t) => t.object_type === objectType)?.id ?? objectType;
  const release = async (part: string, id: string) => {
    setBusy(part);
    setProblem("");
    try {
      await setPartOf(connectionId, id, "", schema);
      onChanged();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy("");
    }
  };
  return (
    <Section title="Parts" aside="types folded into this one">
      {parts.map((part, i) => (
        <div key={part.object_type} style={{ padding: "6px 0", borderTop: i ? RULE : undefined, display: "flex",
                                              alignItems: "center", gap: 6, flexWrap: "wrap" }} data-testid="entity-part">
          <Button variant="ghost" size="xs" onClick={() => onOpen(part.object_type)} title={`Open ${part.display_name}`}>
            {part.display_name}
          </Button>
          <span className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)" }}>through {part.binding} · {part.kind}</span>
          {part.origin === "model" && (
            <>
              <span className="aug-tag aug-tag-violet" title={`proposed by ${part.provenance || "an explorer"} — confirm it, or release it`}>
                proposed
              </span>
              <ConfirmProposal target={{ kind: "binding", entity: detail.id, binding: part.binding }}
                connectionId={connectionId} schema={schema} onChanged={onChanged} />
            </>
          )}
          <Button variant="minimal" size="xs" disabled={busy === part.object_type} style={{ marginLeft: "auto" }}
            onClick={() => release(part.object_type, partId(part.object_type))}
            title="Stand this type on its own again — the binding stays">
            {busy === part.object_type ? "Releasing…" : "Release"}
          </Button>
        </div>
      ))}
      {problem && <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--red5)" }}>{problem}</p>}
    </Section>
  );
}

function DisplaySection({ detail, connectionId, schema, onChanged, readOnly }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  onChanged: () => void;
  /** ON-8 — shown, and measured, but not declared from here. */
  readOnly?: boolean;
}) {
  const shown = detail.display_property;
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  // A display property is measured over the backing, so only a property the backing supplies can be declared.
  const choices = detail.properties.filter((p) => p.source.binding !== "overlay" && !p.source.kind
    && (p.is_key || p.role === "dimension" || p.role === "text"));
  const act = async (write: () => Promise<void>) => {
    setBusy(true);
    setProblem("");
    try {
      await write();
      onChanged();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const warrant = shown.source === "human" ? "declared by a person"
    : shown.source === "proposed" ? "proposed from the profile" : "no other property names it";
  let verdict: React.ReactNode = null;
  if (shown.source !== "key") {
    verdict = shown.verified === true
      ? <span className="aug-tag aug-tag-green">names objects</span>
      : shown.verified === false
        ? <span className="aug-tag aug-tag-amber">does not name objects</span>
        : <span className="aug-tag aug-tag-gray">not yet measured</span>;
  }
  return (
    <Section title="Named by" aside={warrant}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }} data-testid="entity-display-property">
        <span className="aug-fs-sm" style={{ ...MONO, color: "var(--t1)" }}>{shown.property}</span>
        {verdict}
      </div>
      {shown.note && <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--t3)", lineHeight: 1.45 }}>{shown.note}</p>}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
        {!readOnly && (
          <>
            <label className="aug-fs-xs" htmlFor={`display-${detail.object_type}`} style={{ color: "var(--t3)" }}>Declare</label>
            <select id={`display-${detail.object_type}`} className="aug-fs-xs" style={SELECT} value={shown.property}
              disabled={busy} onChange={(e) => act(() => declareDisplayProperty(connectionId, detail.id, e.target.value, schema))}>
              {choices.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
          </>
        )}
        <Button variant="minimal" size="xs" disabled={busy} onClick={() => act(() => measureOntology(connectionId, schema))}
          title="Count keys, link cardinalities, lifecycles and display properties against the data — no model call">
          {busy ? "Working…" : "Measure"}
        </Button>
      </div>
      {problem && <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--red5)" }}>{problem}</p>}
    </Section>
  );
}

/** Where a property is read from: `table.column` (the binding's full name on hover), or the overlay of edits. */
function sourceText(source: PropertySource): { short: string; full: string } {
  if (source.expression) return { short: `= ${source.expression}`, full: `an expression over the row: ${source.expression}` };
  if (source.binding === "overlay") {
    const text = `overlay · ${countNoun(source.edits ?? 0, "accepted edit")}`;
    return { short: text, full: text };
  }
  const table = source.table ?? source.binding;
  const bare = table.split(".").pop() ?? table;
  const column = source.column ?? "";
  // ON-5 — a frame has no column: it is computed over the readings, so the row says what it is.
  if (source.frame) {
    return { short: source.frame, full: `${source.frame} · the timeseries binding ${source.binding}` };
  }
  // ON-7 — a rollup likewise: computed over the object's rows, not read from one.
  if (source.rollup) {
    return { short: source.rollup, full: `${source.rollup} · the detail binding ${source.binding}` };
  }
  const how = source.kind
    ? ` · the ${source.kind} binding ${source.binding}`
      + (source.read === false ? ", not read yet" : source.kind === "timeseries" ? ", its latest value"
         : source.kind === "detail" ? ", rolled up" : "")
    : "";
  return { short: `${bare}.${column}`, full: `${table}.${column}${how}` };
}

/** 2026-09-22 — typed properties a person mapped to an expression over the type's own row (ON-1b's deferred half).
 *  Declared here, checked and run on one row by the server, listed with its verdict, and removed here. */
function ExpressionsSection({ detail, connectionId, schema, onChanged }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [expression, setExpression] = useState("");
  const [role, setRole] = useState<"measure" | "dimension">("measure");
  const [unit, setUnit] = useState("");
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const rows = detail.expressions ?? [];
  const act = async (key: string, write: () => Promise<void>) => {
    setBusy(key);
    setProblem("");
    try {
      await write();
      onChanged();
      setOpen(false);
      setName(""); setExpression(""); setUnit("");
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy("");
    }
  };
  return (
    <Section title="Expressions" aside="properties computed from the row, in SQL a person wrote">
      {rows.map((e) => (
        <div key={e.name} className="aug-fs-xs" data-testid="entity-expression"
          style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0", flexWrap: "wrap" }}>
          <span style={{ ...MONO, color: "var(--t1)" }}>{e.name}</span>
          <span style={{ ...MONO, color: "var(--t3)" }}>= {e.expression}</span>
          <span className="aug-tag aug-tag-gray">{e.role}{e.unit ? ` · ${e.unit}` : ""}</span>
          {e.verified === true
            ? <span className="aug-tag aug-tag-green">runs</span>
            : <span className="aug-tag aug-tag-amber" title={e.note}>did not bind</span>}
          <Button variant="minimal" size="xs" disabled={busy === e.name} style={{ marginLeft: "auto" }}
            onClick={() => act(e.name, () => removeExpression(connectionId, detail.id, e.name, schema))}>
            Remove
          </Button>
        </div>
      ))}
      {!open ? (
        <Button variant="ghost" size="xs" onClick={() => setOpen(true)} style={{ marginTop: 4 }}>Declare an expression</Button>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }} data-testid="declare-expression">
          <input className="aug-fs-xs" style={FIELD} value={name} placeholder="days_to_ship" aria-label="Expression name"
            onChange={(e) => setName(e.target.value)} />
          <input className="aug-fs-xs" style={{ ...FIELD, ...MONO }} value={expression} aria-label="Expression SQL"
            placeholder="date_diff('day', order_date, shipped_at)" onChange={(e) => setExpression(e.target.value)} />
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <select className="aug-fs-xs" style={SELECT} value={role} aria-label="Expression role"
              onChange={(e) => setRole(e.target.value as "measure" | "dimension")}>
              <option value="measure">measure</option>
              <option value="dimension">dimension</option>
            </select>
            <input className="aug-fs-xs" style={{ ...FIELD, width: 90 }} value={unit} placeholder="unit" aria-label="Expression unit"
              onChange={(e) => setUnit(e.target.value)} />
            <Button variant="outline" size="xs" disabled={!!busy || !name.trim() || !expression.trim()}
              onClick={() => act("declare", () => declareExpression(connectionId, detail.id, name.trim(),
                { expression: expression.trim(), semantic_type: role, unit: unit.trim() }, schema))}>
              {busy === "declare" ? "Checking…" : "Declare"}
            </Button>
            <Button variant="ghost" size="xs" disabled={!!busy} onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </div>
      )}
      {problem && <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--red5)" }}>{problem}</p>}
    </Section>
  );
}

function PropertiesSection({ detail }: { detail: ObjectTypeDetail }) {
  const cell: React.CSSProperties = { padding: "4px 8px 4px 0", verticalAlign: "top" };
  const clip: React.CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
  return (
    <Section title="Properties"
      aside={`${formatCount(detail.counts.properties)}${detail.properties_truncated ? `, the first ${detail.properties.length} shown` : ""}`}>
      <table className="aug-fs-xs" style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}
        data-testid="entity-properties">
        <colgroup>
          <col style={{ width: "36%" }} />
          <col style={{ width: "24%" }} />
          <col />
        </colgroup>
        <thead>
          <tr style={{ color: "var(--t3)", textAlign: "left" }}>
            <th style={{ ...cell, fontWeight: 500 }}>Property</th>
            <th style={{ ...cell, fontWeight: 500 }}>Role</th>
            <th style={{ ...cell, fontWeight: 500 }}>Source</th>
          </tr>
        </thead>
        <tbody>
          {detail.properties.map((p) => {
            const source = sourceText(p.source);
            return (
              <tr key={p.name} style={{ borderTop: RULE }}>
                <td style={{ ...cell, ...MONO, ...clip, color: "var(--t1)" }} title={p.description || p.name}>
                  {p.is_key && <span style={{ color: "var(--t3)", marginRight: 3, display: "inline-flex" }}><Icon name="key" size={11} label="Key" /></span>}
                  {p.name}
                </td>
                <td style={{ ...cell, ...clip, color: "var(--t2)" }} title={p.data_type || undefined}>{p.role || "—"}</td>
                <td style={{ ...cell, ...MONO, ...clip, color: "var(--t2)" }} title={source.full}>{source.short}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Section>
  );
}

/** A further binding's verdict: read by the compiler, and HOW — a timeseries binding is read as each object's
 *  latest value (ON-5), which is a different claim from a static one — or the reason it is not read. The backing
 *  carries none. */
/** ON-5 — the frames a binding computes, each in the declaration's own words. */
function FrameLines({ binding }: { binding: TypeBinding }) {
  const frames = Object.entries(binding.frames ?? {});
  if (frames.length === 0) return null;
  return (
    <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 3 }}>
      {frames.map(([name, said]) => (
        <div key={name} style={{ overflowWrap: "anywhere" }}>
          <span style={MONO}>{name}</span> — {said}
        </div>
      ))}
    </div>
  );
}

/** ON-7 — the rollups a detail binding computes, each in the declaration's own words. */
function RollupLines({ binding }: { binding: TypeBinding }) {
  const rollups = Object.entries(binding.rollups ?? {});
  if (rollups.length === 0) return null;
  return (
    <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 3 }}>
      {rollups.map(([name, said]) => (
        <div key={name} style={{ overflowWrap: "anywhere" }}>
          <span style={MONO}>{name}</span> — {said}
        </div>
      ))}
    </div>
  );
}

function bindingVerdict(b: TypeBinding): [string, string] | null {
  if (b.primary) return null;
  if (b.usable) {
    return ["aug-tag-green", b.kind === "timeseries" ? `read · latest by ${b.time_column}`
      : b.kind === "detail" ? "read · rolled up" : "read"];
  }
  if (b.kind === "timeseries" && !b.time_column) return ["aug-tag-gray", "no time column"];
  return b.verified === false ? ["aug-tag-red", "refuted"] : ["aug-tag-gray", "not yet measured"];
}

function BindingRow({ binding: b, first, busy, onRemove, confirm, source }: {
  binding: TypeBinding;
  first: boolean;
  busy: boolean;
  onRemove?: () => void;
  /** ON-7b — the door that makes an explorer's binding a person's, given only for one. */
  confirm?: React.ReactNode;
  /** ON-8 — in an organisation's ontology, the name of the connection the source lives on. */
  source?: string;
}) {
  const verdict = bindingVerdict(b);
  const term: React.CSSProperties = { color: "var(--t3)" };
  const value: React.CSSProperties = { margin: 0, color: "var(--t1)" };
  const skipped = Object.entries(b.skipped ?? {});
  return (
    <div style={{ padding: "8px 0", borderTop: first ? undefined : RULE }} data-testid="entity-binding">
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span className="aug-fs-sm" style={{ ...MONO, color: "var(--t1)" }}>{b.name}</span>
        <span className="aug-tag aug-tag-gray">{b.primary ? "backing" : b.kind}</span>
        {verdict && <span className={`aug-tag ${verdict[0]}`}>{verdict[1]}</span>}
        {b.source === "model" && (
          <span className="aug-tag aug-tag-violet" title={`proposed by ${b.provenance || "an explorer"}, not yet confirmed`}>
            proposed
          </span>
        )}
        {confirm}
        {onRemove && (
          <Button variant="minimal" size="xs" disabled={busy} onClick={onRemove} style={{ marginLeft: "auto" }}
            title="Remove this binding — the properties it supplies stop resolving">
            {busy ? "Removing…" : "Remove"}
          </Button>
        )}
      </div>
      <dl className="aug-fs-xs"
        style={{ display: "grid", gridTemplateColumns: "max-content minmax(0, 1fr)", columnGap: 12, rowGap: 3, margin: "6px 0 0" }}>
        <dt style={term}>{b.reads === "table" ? "Table" : "Query"}</dt>
        <dd style={{ ...value, ...MONO, overflowWrap: "anywhere" }}>{b.reads === "table" ? b.table : b.sql}</dd>
        {source && (
          <>
            <dt style={term}>Connection</dt>
            <dd style={value} data-testid="entity-binding-connection">{source}</dd>
          </>
        )}
        <dt style={term}>Key</dt>
        <dd style={{ ...value, ...MONO }}>{b.primary ? b.key : `${b.key} → ${b.object_key}`}</dd>
        {b.time_column && (
          <>
            <dt style={term}>Time</dt>
            <dd style={{ ...value, ...MONO }}>{b.time_column}</dd>
          </>
        )}
        <dt style={term}>Rows</dt>
        <dd style={value}>{b.rows == null ? "not yet measured" : formatCount(b.rows)}</dd>
        {!b.primary && b.covered != null && b.objects != null && (
          <>
            <dt style={term}>Covers</dt>
            <dd style={value}>
              {formatCount(b.covered)} of {formatCount(b.objects)} objects
              {b.orphans ? ` · ${countNoun(b.orphans, "key")} reach no object` : ""}
            </dd>
          </>
        )}
        <dt style={term}>Supplies</dt>
        <dd style={value}>{countNoun(b.supplies, "property", "properties")}</dd>
      </dl>
      <FrameLines binding={b} />
      <RollupLines binding={b} />
      {!b.primary && (b.why_not || b.note) && (
        <p className="aug-fs-xs" style={{ margin: "4px 0 0", color: "var(--t3)", lineHeight: 1.45 }}>{b.why_not || b.note}</p>
      )}
      {skipped.length > 0 && (
        <p className="aug-fs-xs" style={{ margin: "4px 0 0", color: "var(--t3)", lineHeight: 1.45 }}>
          Not supplied: {skipped.map(([column, why]) => `${column} (${why})`).join("; ")}
        </p>
      )}
    </div>
  );
}

/** What a proposal's kind says about its rows, beside what it would supply. */
function proposalShape(p: ProposedBinding): string {
  if (p.kind === "detail") return " — many rows per object: a part";
  if (p.kind === "timeseries") return ` — readings over ${p.spec.time_column ?? "time"}: read as each object's latest`;
  return "";
}

function ProposalRow({ proposal: p, busy, onBind }: { proposal: ProposedBinding; busy: boolean; onBind: () => void }) {
  return (
    <div style={{ padding: "7px 0", borderTop: RULE }} data-testid="entity-binding-proposal">
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span className="aug-fs-sm" style={{ ...MONO, color: "var(--t1)" }}>{p.table}</span>
        <span className="aug-tag aug-tag-violet">proposed · {p.kind}</span>
        <Button variant="outline" size="xs" disabled={busy} onClick={onBind} style={{ marginLeft: "auto" }}
          title={`Bind ${p.table} on ${p.key} — its columns are checked and it is counted against the objects first`}>
          {busy ? "Binding…" : "Bind"}
        </Button>
      </div>
      <p className="aug-fs-xs" style={{ margin: "3px 0 0", color: "var(--t3)", lineHeight: 1.45 }}>
        <span style={MONO}>{p.key} → {p.object_key}</span> · {p.note}
      </p>
      <p className="aug-fs-xs" style={{ ...MONO, margin: "3px 0 0", color: "var(--t2)", overflowWrap: "anywhere" }}>
        would supply {p.supplies.join(", ")}{proposalShape(p)}
      </p>
    </div>
  );
}

/** ON-1 — read this type from a keyed SELECT. The preview says, before anything is written, whether the SELECT reads,
 *  how many rows it holds, whether its key is unique over them, and which of the type's properties it keeps, drops —
 *  the compiler reads every property from the backing, so a dropped one would stop resolving — and adds. It is set
 *  only when its key is unique and it drops nothing; withdrawn, the type reads its table again. */
function BackingEditor({ detail, busy, onPreview, onSet, onWithdraw }: {
  detail: ObjectTypeDetail;
  busy: boolean;
  onPreview: (sql: string, key: string) => Promise<BackingPreview>;
  onSet: (sql: string, key: string) => void;
  onWithdraw: () => void;
}) {
  const primary = detail.bindings.find((b) => b.primary);
  const readsQuery = primary?.reads === "query";
  const [open, setOpen] = useState(false);
  const [sql, setSql] = useState(readsQuery ? primary?.sql ?? "" : "");
  const [key, setKey] = useState(detail.key.property);
  const [preview, setPreview] = useState<BackingPreview | null>(null);
  const [looking, setLooking] = useState(false);
  const [problem, setProblem] = useState("");
  const look = async () => {
    setLooking(true);
    setProblem("");
    try {
      setPreview(await onPreview(sql.trim(), key.trim()));
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setLooking(false);
    }
  };
  const blocked = !preview ? "preview it first"
    : !preview.readable ? preview.note
    : preview.dropped.length > 0
      ? `it drops ${preview.dropped.join(", ")} — select ${preview.dropped.length === 1 ? "it" : "them"} too`
    : preview.unique !== true ? (preview.note || preview.unique_note || "its key is not unique over these rows")
    : "";
  const term: React.CSSProperties = { color: "var(--t3)" };
  if (!open) {
    return (
      <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
        <Button variant="minimal" size="xs" onClick={() => setOpen(true)}>
          {readsQuery ? "Edit its SELECT" : "Read from a SELECT"}
        </Button>
        {readsQuery && (
          <Button variant="minimal" size="xs" disabled={busy} onClick={onWithdraw}
            title="Withdraw the SELECT — the type reads its table again, and its other edits stay">
            Read its table again
          </Button>
        )}
      </div>
    );
  }
  return (
    <div style={{ marginTop: 10, paddingTop: 8, borderTop: RULE }} data-testid="backing-editor">
      <p className="aug-fs-xs" style={{ margin: "0 0 6px", color: "var(--t3)", lineHeight: 1.45 }}>
        Read {detail.display_name} from a keyed SELECT: its rows are the objects, and every property is read from it.
        Nothing is written until it is set.
      </p>
      <textarea className="aug-fs-xs" style={{ ...FIELD, ...MONO, width: "100%", minHeight: 64 }} value={sql}
        aria-label="Backing SELECT" placeholder="SELECT c.customer_id, c.name, p.lifetime_spend FROM …"
        onChange={(e) => { setSql(e.target.value); setPreview(null); }} />
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 6 }}>
        <span className="aug-fs-xs" style={term}>key</span>
        <input className="aug-fs-xs" style={{ ...FIELD, width: 150 }} value={key} aria-label="Backing key"
          onChange={(e) => { setKey(e.target.value); setPreview(null); }} />
        <Button variant="outline" size="xs" disabled={looking || !sql.trim() || !key.trim()} onClick={look}>
          {looking ? "Reading…" : "Preview"}
        </Button>
        <Button variant="outline" size="xs" disabled={busy || !!blocked} onClick={() => onSet(sql.trim(), key.trim())}
          title={blocked || "Read the type from this SELECT"}>
          {busy ? "Setting…" : "Set as backing"}
        </Button>
      </div>
      {preview && preview.readable && (
        <dl className="aug-fs-xs" data-testid="backing-preview"
          style={{ display: "grid", gridTemplateColumns: "max-content minmax(0, 1fr)", columnGap: 12, rowGap: 3, margin: "6px 0 0" }}>
          <dt style={term}>Now</dt>
          <dd style={{ margin: 0, ...MONO, overflowWrap: "anywhere" }}>
            {preview.current.source} · {preview.current.rows == null ? "rows not yet measured" : `${formatCount(preview.current.rows)} rows`}
          </dd>
          <dt style={term}>Rows</dt>
          <dd style={{ margin: 0 }}>
            {preview.rows == null ? "not counted" : formatCount(preview.rows)} · key{" "}
            {preview.unique === true ? "unique" : preview.unique === false ? "NOT unique" : "not counted"}
          </dd>
          <dt style={term}>Keeps</dt>
          <dd style={{ margin: 0 }}>{countNoun(preview.kept.length, "property", "properties")}</dd>
          {preview.dropped.length > 0 && (
            <>
              <dt style={term}>Drops</dt>
              <dd style={{ margin: 0, ...MONO, color: "var(--red5)" }}>{preview.dropped.join(", ")}</dd>
            </>
          )}
          {preview.added.length > 0 && (
            <>
              <dt style={term}>Adds</dt>
              <dd style={{ margin: 0, ...MONO }}>{preview.added.join(", ")}</dd>
            </>
          )}
        </dl>
      )}
      {(problem || (preview && blocked)) && (
        <p className="aug-fs-xs" style={{ margin: "4px 0 0", color: "var(--red5)", lineHeight: 1.45 }}>{problem || blocked}</p>
      )}
    </div>
  );
}

function BindingsSection({ detail, connectionId, schema, onChanged, sources }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  onChanged: () => void;
  /** ON-8 — set in an organisation's ontology: each binding names its connection, and a new one may pick another. */
  sources?: Record<string, string>;
}) {
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const sourceOf = (b: TypeBinding) => {
    const where = b.connection_id || detail.connection_id;
    return sources && where ? sources[where] ?? where : undefined;
  };
  // An API older than ON-1b sends no proposals; the panel must not fall over while the two deploy apart.
  const proposals = detail.proposed_bindings ?? [];
  const act = async (name: string, write: () => Promise<void>) => {
    setBusy(name);
    setProblem("");
    try {
      await write();
      onChanged();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy("");
    }
  };
  return (
    <Section title="Bindings" aside="where its properties are read from">
      {detail.bindings.map((b, i) => (
        <BindingRow key={b.name} binding={b} first={i === 0} busy={busy === b.name} source={sourceOf(b)}
          onRemove={!b.primary
            ? () => act(b.name, () => removeBinding(connectionId, detail.id, b.name, schema)) : undefined}
          confirm={b.source === "model" && !sources ? (
            <ConfirmProposal target={{ kind: "binding", entity: detail.id, binding: b.name }} connectionId={connectionId}
              schema={schema} onChanged={onChanged} />
          ) : undefined} />
      ))}
      {proposals.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            Proposed from the data — another table carries the {detail.key.property} key. Nothing reads a proposal
            until it is bound.
          </div>
          {proposals.map((p) => (
            <ProposalRow key={p.name} proposal={p} busy={busy === p.name}
              onBind={() => act(p.name, () => addBinding(connectionId, detail.id, p.name, p.spec, schema))} />
          ))}
        </div>
      )}
      <DeclareBinding detail={detail} busy={!!busy} sources={sources} onDeclare={(name, spec) =>
        act(name, () => addBinding(connectionId, detail.id, name, spec, schema))} />
      {!sources && (
        <BackingEditor detail={detail} busy={busy === "backing"}
          onPreview={(sql, key) => previewBacking(connectionId, detail.id, sql, key, schema)}
          onSet={(sql, key) => act("backing", () => setQueryBacking(connectionId, detail.id, sql, key, schema))}
          onWithdraw={() => act("backing", () => withdrawBacking(connectionId, detail.id, schema))} />
      )}
      {problem && <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--red5)" }}>{problem}</p>}
    </Section>
  );
}

/** ON-1b/ON-5 — declare a binding the data did not propose. The builder proposes only what another table carrying
 *  this type's key shows it: one row per object (static), many rows that are objects of their own (a part), or many
 *  rows placed in time with no identity of their own (a timeseries). A keyed SELECT is never proposed, and a
 *  timeseries source used to be API-only too — the live Lux price history had to be bound with a hand-written PUT.
 *  The server reads the source's columns and counts it against the objects before it answers; a spec that does not
 *  bind is refused with the reason and nothing is written. */
function DeclareBinding({ detail, busy, onDeclare, sources }: {
  detail: ObjectTypeDetail;
  busy: boolean;
  onDeclare: (name: string, spec: BindingSpec) => void;
  /** ON-8 — set in an organisation's ontology: the source may live on any of these connections. */
  sources?: Record<string, string>;
}) {
  const [open, setOpen] = useState(false);
  const [connection, setConnection] = useState(detail.connection_id || "");
  const [schemaName, setSchemaName] = useState("");
  /** A source on another connection than the type's own is read by key, one row per object — static only. */
  const crosses = !!sources && !!connection && connection !== detail.connection_id;
  const [name, setName] = useState("");
  const [reads, setReads] = useState<"table" | "query">("table");
  const [source, setSource] = useState("");
  const [key, setKey] = useState(detail.key.property);
  const [kind, setKind] = useState<BindingSpec["kind"]>("static");
  const [timeColumn, setTimeColumn] = useState("");
  const [frames, setFrames] = useState<FrameRow[]>([]);
  // ON-7 — a detail binding's rollups, and whether the bound table's own type becomes a part of this one.
  const [rollups, setRollups] = useState<RollupRow[]>([{ name: "", agg: "sum", column: "" }]);
  const [absorb, setAbsorb] = useState(true);
  const usable = kind === "timeseries" ? frames.filter((f) => f.name.trim() && f.column.trim()) : [];
  const rolled = kind === "detail" ? rollups.filter((r) => r.name.trim() && r.column.trim()) : [];
  const ready = !!name.trim() && !!source.trim() && !!key.trim()
    && (kind !== "timeseries" || !!timeColumn.trim())
    && (kind !== "detail" || rolled.length > 0)
    && (!crosses || kind === "static")
    && usable.every((f) => f.what !== "avg-trailing" || Number(f.window) >= 1);
  const declare = () => {
    const spec: BindingSpec = { kind, key: key.trim() };
    if (reads === "table") spec.table = source.trim();
    else spec.sql = source.trim();
    if (crosses) spec.connection_id = connection;
    if (sources && reads === "table" && schemaName.trim()) spec.schema_name = schemaName.trim();
    if (kind === "timeseries") spec.time_column = timeColumn.trim();
    if (usable.length) spec.frames = Object.fromEntries(usable.map((f) => [f.name.trim(), frameSpec(f)]));
    if (kind === "detail") {
      spec.rollups = Object.fromEntries(rolled.map((r) => [r.name.trim(), { column: r.column.trim(), agg: r.agg }]));
      if (reads === "table" && absorb && !sources) spec.absorb = true;
    }
    onDeclare(name.trim(), spec);
  };
  if (!open) {
    return (
      <Button variant="minimal" size="xs" style={{ marginTop: 10, alignSelf: "flex-start" }} onClick={() => setOpen(true)}>
        Declare a binding
      </Button>
    );
  }
  return (
    <div style={{ marginTop: 10, paddingTop: 8, borderTop: RULE }} data-testid="declare-binding">
      <p className="aug-fs-xs" style={{ margin: "0 0 6px", color: "var(--t3)", lineHeight: 1.45 }}>
        A source joined to {detail.display_name} on its key. A <strong>static</strong> binding must hold one row per
        object; a <strong>timeseries</strong> holds many over a time column and is read as each object&rsquo;s latest
        row; a <strong>detail</strong> holds many with no clock — an order&rsquo;s lines — and supplies only what its
        rollups declare, each one value per object. Every column but the key is supplied under its own name; one the
        type already uses is skipped with the reason.
      </p>
      {sources && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 6 }}>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>from</span>
          <select className="aug-fs-xs" style={SELECT} value={connection} aria-label="Binding connection"
            data-testid="declare-binding-connection" onChange={(e) => setConnection(e.target.value)}>
            {Object.entries(sources).map(([cid, label]) => (
              <option key={cid} value={cid}>{cid === detail.connection_id ? `${label} (its own)` : label}</option>
            ))}
          </select>
          {reads === "table" && (
            <input className="aug-fs-xs" style={{ ...FIELD, width: 110 }} value={schemaName} placeholder="schema"
              aria-label="Binding schema" onChange={(e) => setSchemaName(e.target.value)} />
          )}
          {crosses && (
            <span className="aug-fs-xs" style={{ color: "var(--t3)", flexBasis: "100%", lineHeight: 1.45 }}
              data-testid="declare-binding-crosses">
              On another connection a binding is read by key, one row per {detail.display_name} — a static one only.
            </span>
          )}
        </div>
      )}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <input className="aug-fs-xs" style={{ ...FIELD, width: 150 }} value={name} placeholder="binding name"
          aria-label="Binding name" onChange={(e) => setName(e.target.value)} />
        <select className="aug-fs-xs" style={SELECT} value={reads} aria-label="Source kind"
          onChange={(e) => setReads(e.target.value as "table" | "query")}>
          <option value="table">table</option>
          <option value="query">SELECT</option>
        </select>
        <input className="aug-fs-xs" style={{ ...FIELD, flex: 1, minWidth: 220 }} value={source}
          aria-label={reads === "table" ? "Table" : "SELECT"}
          placeholder={reads === "table" ? "price_history" : "SELECT product_id, AVG(price) AS price FROM … GROUP BY 1"}
          onChange={(e) => setSource(e.target.value)} />
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 6 }}>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>on</span>
        <input className="aug-fs-xs" style={{ ...FIELD, width: 150 }} value={key} aria-label="Key column"
          placeholder={detail.key.property} onChange={(e) => setKey(e.target.value)} />
        <select className="aug-fs-xs" style={SELECT} value={kind} aria-label="Binding kind"
          onChange={(e) => setKind(e.target.value as BindingSpec["kind"])}>
          <option value="static">static</option>
          <option value="timeseries">timeseries</option>
          <option value="detail">detail</option>
        </select>
        {kind === "timeseries" && (
          <>
            <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>over</span>
            <input className="aug-fs-xs" style={{ ...FIELD, width: 150 }} value={timeColumn} aria-label="Time column"
              placeholder="observed_at" onChange={(e) => setTimeColumn(e.target.value)} />
          </>
        )}
        <Button variant="outline" size="xs" disabled={busy || !ready} onClick={declare}>
          {busy ? "Binding…" : "Bind"}
        </Button>
        <Button variant="ghost" size="xs" disabled={busy} onClick={() => setOpen(false)}>Cancel</Button>
      </div>
      {kind === "timeseries" && (
        <div style={{ marginTop: 8 }}>
          <p className="aug-fs-xs" style={{ margin: "0 0 4px", color: "var(--t3)", lineHeight: 1.45 }}>
            Frames over those readings — each becomes a property of the type, computed across the object&rsquo;s own
            readings and read at its latest one.
          </p>
          {frames.map((f, i) => (
            <div key={i} style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 4 }}>
              <input className="aug-fs-xs" style={{ ...FIELD, width: 150 }} value={f.name}
                aria-label={`Frame ${i + 1} property`} placeholder="avg_price_3"
                onChange={(e) => setFrames((fs) => fs.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
              <select className="aug-fs-xs" style={SELECT} value={f.what} aria-label={`Frame ${i + 1} shape`}
                onChange={(e) => setFrames((fs) => fs.map((x, j) => j === i ? { ...x, what: e.target.value as Shape } : x))}>
                <option value="avg-trailing">average of the last N</option>
                <option value="sum-cumulative">total to date</option>
                <option value="min-all">lowest ever</option>
                <option value="max-all">highest ever</option>
                <option value="count-all">how many readings</option>
                <option value="previous">the reading before</option>
              </select>
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>of</span>
              <input className="aug-fs-xs" style={{ ...FIELD, width: 150 }} value={f.column}
                aria-label={`Frame ${i + 1} column`} placeholder="price"
                onChange={(e) => setFrames((fs) => fs.map((x, j) => j === i ? { ...x, column: e.target.value } : x))} />
              {f.what === "avg-trailing" && (
                <input className="aug-fs-xs" style={{ ...FIELD, width: 60 }} value={f.window} type="number" min={1}
                  aria-label={`Frame ${i + 1} readings`}
                  onChange={(e) => setFrames((fs) => fs.map((x, j) => j === i ? { ...x, window: e.target.value } : x))} />
              )}
              <Button variant="ghost" size="xs" onClick={() => setFrames((fs) => fs.filter((_, j) => j !== i))}>
                Remove
              </Button>
            </div>
          ))}
          <Button variant="ghost" size="xs" style={{ marginTop: 4 }}
            onClick={() => setFrames((fs) => [...fs, { name: "", what: "avg-trailing", column: "", window: "3" }])}>
            + Add a frame
          </Button>
        </div>
      )}
      {kind === "detail" && (
        <div style={{ marginTop: 8 }} data-testid="declare-rollups">
          <p className="aug-fs-xs" style={{ margin: "0 0 4px", color: "var(--t3)", lineHeight: 1.45 }}>
            Rollups over those rows — each becomes a property of the type, computed across the object&rsquo;s own rows
            before the join, so it can never multiply the objects.
          </p>
          {rollups.map((r, i) => (
            <div key={i} style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 4 }}>
              <input className="aug-fs-xs" style={{ ...FIELD, width: 150 }} value={r.name}
                aria-label={`Rollup ${i + 1} property`} placeholder="units"
                onChange={(e) => setRollups((rs) => rs.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
              <select className="aug-fs-xs" style={SELECT} value={r.agg} aria-label={`Rollup ${i + 1} agg`}
                onChange={(e) => setRollups((rs) => rs.map((x, j) => j === i ? { ...x, agg: e.target.value as RollupAgg } : x))}>
                <option value="sum">sum of</option>
                <option value="count">how many carry</option>
                <option value="avg">average of</option>
                <option value="min">lowest</option>
                <option value="max">highest</option>
              </select>
              <input className="aug-fs-xs" style={{ ...FIELD, width: 150 }} value={r.column}
                aria-label={`Rollup ${i + 1} column`} placeholder="quantity"
                onChange={(e) => setRollups((rs) => rs.map((x, j) => j === i ? { ...x, column: e.target.value } : x))} />
              <Button variant="ghost" size="xs" onClick={() => setRollups((rs) => rs.filter((_, j) => j !== i))}>
                Remove
              </Button>
            </div>
          ))}
          <Button variant="ghost" size="xs" style={{ marginTop: 4 }}
            onClick={() => setRollups((rs) => [...rs, { name: "", agg: "sum", column: "" }])}>
            + Add a rollup
          </Button>
          {reads === "table" && !sources && (
            <label className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6, color: "var(--t2)" }}>
              <input type="checkbox" checked={absorb} aria-label="Absorb its type as a part"
                onChange={(e) => setAbsorb(e.target.checked)} />
              Fold that table&rsquo;s own type into {detail.display_name} as a part — hidden from the map, listed here
            </label>
          )}
        </div>
      )}
    </div>
  );
}

type RollupAgg = NonNullable<RollupSpec["agg"]>;

interface RollupRow {
  name: string;
  agg: RollupAgg;
  column: string;
}

/** The frames a person can declare from here, each a shape they would recognise rather than the algebra's
 *  vocabulary. The API takes the full algebra; this offers the frames people actually ask for. */
type Shape = "avg-trailing" | "sum-cumulative" | "min-all" | "max-all" | "count-all" | "previous";

interface FrameRow {
  name: string;
  what: Shape;
  column: string;
  window: string;
}

function frameSpec(row: FrameRow): FrameSpec {
  const column = row.column.trim();
  if (row.what === "previous") return { column, offset: 1 };
  const [agg, range] = row.what.split("-") as [FrameSpec["agg"], FrameSpec["range"]];
  return range === "trailing"
    ? { column, agg, range, window: Math.max(1, Number(row.window) || 1) }
    : { column, agg, range };
}

function LinkSentence({ detail, link, onOpen }: { detail: ObjectTypeDetail; link: TypeLink; onOpen: (t: string) => void }) {
  const other = (
    <Button variant="ghost" size="xs" onClick={() => onOpen(link.to)} title={`Light ${link.to_name} up on the map and open it here`}>
      {link.to_name}
    </Button>
  );
  const verb = <span style={{ color: "var(--t2)" }}>{link.verb || "relates to"}</span>;
  const here = <span style={{ color: "var(--t2)" }}>{detail.display_name}</span>;
  return link.direction === "out"
    ? <>{here}{verb}{other}</>
    : <>{other}{verb}{here}</>;
}

/** ON-3b — name a link by the verb the business uses. The builder's generic name (`order_item_associated_with_
 *  shipment`) is what the data proposes; only a person knows the business said "shipped as". The mechanical name
 *  keeps working — this one is accepted beside it — so naming a link breaks no query and no saved path. */
function NameLink({ link, connectionId, schema, onChanged }: {
  link: TypeLink;
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(link.business_name || "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const save = async () => {
    setBusy(true);
    setProblem("");
    try {
      await nameLink(connectionId, link.relationship, name.trim(), schema);
      setOpen(false);
      onChanged();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  if (!open) {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        {link.business_name_source === "model" && (
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}
            title="The explorer proposed this name — confirm it in the draft rail, or rename it here">
            proposed by the explorer
          </span>
        )}
        <Button variant="ghost" size="xs" onClick={() => setOpen(true)}
          title="Name this link the way the business says it — the mechanical name keeps working beside it">
          {link.business_name_source === "human" || link.business_name_source === "model" ? "Rename" : "Name it"}
        </Button>
      </span>
    );
  }
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
      <input className="aug-fs-xs" style={{ ...FIELD, width: 220 }} value={name} autoFocus disabled={busy}
        placeholder="shipped_as" aria-label={`Business name for ${link.name}`}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) void save(); if (e.key === "Escape") setOpen(false); }} />
      <Button variant="outline" size="xs" disabled={busy || !name.trim()} onClick={save}>
        {busy ? "Naming…" : "Save"}
      </Button>
      <Button variant="ghost" size="xs" disabled={busy} onClick={() => setOpen(false)}>Cancel</Button>
      {problem && <span className="aug-fs-xs" style={{ color: "var(--red5)" }}>{problem}</span>}
    </span>
  );
}

/** ON-7 — declare a link the builder did not find: another type, the verb the business uses, and the column on
 *  each side that joins them. The server checks both columns exist, refuses a name already taken, measures each
 *  side and how many keys meet, and the compiler follows the link exactly as a found one — measured, not N:N. */
function AddRelationship({ detail, types, connectionId, schema, onChanged }: {
  detail: ObjectTypeDetail;
  types: TypeMapRow[];
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const others = types.filter((t) => t.object_type !== detail.object_type);
  const [open, setOpen] = useState(false);
  const [to, setTo] = useState("");
  const [name, setName] = useState("");
  const [fromColumn, setFromColumn] = useState("");
  const [toColumn, setToColumn] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const target = others.some((t) => t.object_type === to) ? to : (others[0]?.object_type ?? "");
  const ready = !!target && /^[a-z][a-z0-9_]{0,79}$/.test(name.trim()) && !!fromColumn.trim() && !!toColumn.trim();
  const declare = async () => {
    setBusy(true);
    setProblem("");
    const row = others.find((t) => t.object_type === target);
    const spec: DeclaredLinkSpec = { from_entity: detail.id, to_entity: row?.id ?? target, name: name.trim(),
      from_column: fromColumn.trim(), to_column: toColumn.trim() };
    try {
      await declareLink(connectionId, spec, schema);
      setOpen(false);
      setName(""); setFromColumn(""); setToColumn("");
      onChanged();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  if (!open) {
    return (
      <Button variant="minimal" size="xs" style={{ marginTop: 10 }} onClick={() => setOpen(true)} disabled={others.length === 0}
        title="Declare a link the builder did not find — a verb, and the column on each side that joins them">
        Add a relationship
      </Button>
    );
  }
  return (
    <div style={{ marginTop: 10, paddingTop: 8, borderTop: RULE }} data-testid="declare-link">
      <div className="aug-fs-xs" style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ color: "var(--t2)" }}>{detail.display_name}</span>
        <input className="aug-fs-xs" style={{ ...FIELD, width: 130 }} value={name} placeholder="placed_by"
          aria-label="Link verb" onChange={(e) => setName(e.target.value)} />
        <select className="aug-fs-xs" style={SELECT} value={target} aria-label="Link target type"
          onChange={(e) => setTo(e.target.value)}>
          {others.map((t) => <option key={t.object_type} value={t.object_type}>{t.display_name}</option>)}
        </select>
      </div>
      <div className="aug-fs-xs" style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 6 }}>
        <span style={{ color: "var(--t3)" }}>on</span>
        <input className="aug-fs-xs" style={{ ...FIELD, width: 130 }} value={fromColumn} placeholder={detail.key.property}
          aria-label="Link column on this type" onChange={(e) => setFromColumn(e.target.value)} />
        <span style={{ color: "var(--t3)" }}>=</span>
        <input className="aug-fs-xs" style={{ ...FIELD, width: 130 }} value={toColumn} placeholder="its column"
          aria-label="Link column on the other type" onChange={(e) => setToColumn(e.target.value)} />
        <Button variant="outline" size="xs" disabled={busy || !ready} onClick={declare}>
          {busy ? "Declaring…" : "Declare"}
        </Button>
        <Button variant="ghost" size="xs" disabled={busy} onClick={() => setOpen(false)}>Cancel</Button>
      </div>
      {problem && <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--red5)" }}>{problem}</p>}
    </div>
  );
}

/** 2026-09-22 — what a person withdrew on this type, and the door back: a builder-found binding or a found link
 *  the builder guessed wrong leaves the served graph on withdrawal (the compiler stops following it) and returns on
 *  Restore. Rendered only when something was withdrawn, so an untouched type's panel is unchanged. */
function WithdrawnSection({ detail, connectionId, schema, onChanged }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const gone = detail.withdrawn;
  if (!gone || (gone.bindings.length === 0 && gone.links.length === 0)) return null;
  const act = async (key: string, write: () => Promise<void>) => {
    setBusy(key);
    setProblem("");
    try {
      await write();
      onChanged();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy("");
    }
  };
  return (
    <Section title="Withdrawn" aside="left out of the served ontology by a person">
      {gone.bindings.map((name) => (
        <div key={`b:${name}`} className="aug-fs-xs" data-testid="entity-withdrawn"
          style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0" }}>
          <span style={{ ...MONO, color: "var(--t2)" }}>{name}</span>
          <span style={{ color: "var(--t3)" }}>binding</span>
          <Button variant="ghost" size="xs" disabled={busy === `b:${name}`} style={{ marginLeft: "auto" }}
            onClick={() => act(`b:${name}`, () => restoreBinding(connectionId, detail.id, name, schema))}>
            Restore
          </Button>
        </div>
      ))}
      {gone.links.map((l) => (
        <div key={`l:${l.relationship}`} className="aug-fs-xs" data-testid="entity-withdrawn"
          style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0" }}>
          <span style={{ ...MONO, color: "var(--t2)" }}>{l.relationship}</span>
          <span style={{ color: "var(--t3)" }}>link · {l.from_entity} → {l.to_entity}</span>
          <Button variant="ghost" size="xs" disabled={busy === `l:${l.relationship}`} style={{ marginLeft: "auto" }}
            onClick={() => act(`l:${l.relationship}`, () => restoreLink(connectionId, l.relationship, schema))}>
            Restore
          </Button>
        </div>
      ))}
      {problem && <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--red5)" }}>{problem}</p>}
    </Section>
  );
}

/** ON-7 — withdraw a link a person declared; since 2026-09-22 a FOUND link too (the join the builder guessed wrong
 *  leaves the served graph, and comes back from the Withdrawn section). */
function WithdrawLink({ link, connectionId, schema, onChanged }: {
  link: TypeLink;
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const withdraw = async () => {
    setBusy(true);
    setProblem("");
    try {
      await deleteLink(connectionId, link.relationship, schema);
      onChanged();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button variant="ghost" size="xs" disabled={busy} onClick={withdraw} title="Withdraw this declared link">
        {busy ? "Withdrawing…" : "Withdraw"}
      </Button>
      {problem && <span className="aug-fs-xs" style={{ color: "var(--red5)" }}>{problem}</span>}
    </>
  );
}

function LinksSection({ detail, types, connectionId, schema, onOpen, onChanged, inDomain }: {
  detail: ObjectTypeDetail;
  types: TypeMapRow[];
  connectionId: string;
  schema?: string;
  onOpen: (objectType: string) => void;
  onChanged: () => void;
  /** ON-8 — in an organisation's ontology an explorer's proposal is not confirmed from here (the explorer stays
   *  home-only); naming a link is declarative and opens there (2026-09-22). */
  inDomain?: boolean;
}) {
  return (
    <Section title="Links" aside={`${detail.counts.traversable_links} of ${detail.counts.links} followed by the compiler`}>
      {detail.links.length === 0 && <EmptyState variant="inline" title={`No link reaches out from ${detail.display_name}.`} />}
      {detail.links.map((link, i) => (
        <div key={`${link.relationship}:${link.name}`} style={{ padding: "7px 0", borderTop: i ? RULE : undefined }}
          data-testid="entity-link">
          <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
            <LinkSentence detail={detail} link={link} onOpen={onOpen} />
            <span className="aug-tag aug-tag-gray" style={MONO}>{link.cardinality}</span>
            <span className={`aug-tag ${link.traversable ? "aug-tag-green" : "aug-tag-amber"}`}>
              {link.traversable ? "followed" : "refused"}
            </span>
            {link.traversal === "cross-source" && (
              <span className="aug-tag aug-tag-gray" data-testid="entity-link-cross-source"
                title="Its two types live on two connections: the compiler reads the far side by key and joins it in the answer">
                cross-source
              </span>
            )}
            {link.origin === "human" && (
              <span className="aug-tag aug-tag-blue"
                title={link.provenance ? `declared — first proposed by ${link.provenance}` : "declared by a person"}>
                declared
              </span>
            )}
            {link.origin === "model" && !inDomain && (
              <>
                <span className="aug-tag aug-tag-violet" title={`proposed by ${link.provenance || "an explorer"}, not yet confirmed`}>
                  proposed
                </span>
                <ConfirmProposal target={{ kind: "link", relationship: link.relationship }} connectionId={connectionId}
                  schema={schema} onChanged={onChanged} />
              </>
            )}
            <NameLink link={link} connectionId={connectionId} schema={schema} onChanged={onChanged} />
            {(link.origin === "human" || link.origin === "model" || !inDomain) && (
              <WithdrawLink link={link} connectionId={connectionId} schema={schema} onChanged={onChanged} />
            )}
          </div>
          <div className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)", marginTop: 3, overflowWrap: "anywhere" }}>
            {link.business_name && <>{link.business_name}{link.business_name_source === "human" ? " (declared)" : ""} · </>}
            {link.name} · {link.on}
          </div>
          {link.why_not && <p className="aug-fs-xs" style={{ margin: "3px 0 0", color: "var(--t3)", lineHeight: 1.45 }}>{link.why_not}</p>}
        </div>
      ))}
      <AddRelationship detail={detail} types={types} connectionId={connectionId} schema={schema} onChanged={onChanged} />
    </Section>
  );
}

function ActionsSection({ detail, connectionId }: { detail: ObjectTypeDetail; connectionId: string }) {
  const href = declaredActionsHref(connectionId);
  if (detail.actions.length === 0) {
    return (
      <Section title="Declared actions">
        <EmptyState variant="inline" title={`No declared action takes a ${detail.display_name.toLowerCase()}.`}
          action={<Link href={href}><Button variant="outline" size="xs">Open Actions</Button></Link>} />
      </Section>
    );
  }
  return (
    <Section title="Declared actions" aside={countNoun(detail.actions.length, "action")}>
      {detail.actions.map((a, i) => (
        <div key={a.id} style={{ padding: "7px 0", borderTop: i ? RULE : undefined }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span style={{ color: "var(--t3)", display: "inline-flex" }}><Icon name="bolt" size={13} /></span>
            <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600 }}>{a.display_name}</span>
            <span className="aug-tag aug-tag-gray">{a.kind}</span>
            {a.risk && <span className={`aug-tag ${RISK_TAG[a.risk] ?? "aug-tag-gray"}`}>{a.risk}</span>}
          </div>
          <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>{a.why}</div>
          <div className="aug-fs-xs" style={{ ...MONO, color: "var(--t2)", marginTop: 3, overflowWrap: "anywhere" }}>
            ({a.params.map((p) => `${p.name}${p.kind === "object" ? `: ${p.object_type}` : ""}${p.required ? "" : "?"}`).join(", ")})
            {a.edits.length > 0 && <> → sets {a.edits.map((e) => `${e.object}.${e.property}`).join(", ")}</>}
          </div>
        </div>
      ))}
      <Link href={href}><Button variant="minimal" size="xs" style={{ marginTop: 6 }}>Open in Actions</Button></Link>
    </Section>
  );
}

function MetricsSection({ detail }: { detail: ObjectTypeDetail }) {
  return (
    <Section title="Verified metrics">
      {detail.metrics.length === 0 && <EmptyState variant="inline" title="No verified metric is defined on this type." />}
      {detail.metrics.map((m) => (
        <div key={m.id} style={{ padding: "5px 0" }} title={m.formula_sql}>
          <span className="aug-fs-sm" style={{ color: "var(--t1)" }}>{m.display_name}</span>
          {m.unit && <span className="aug-fs-xs" style={{ color: "var(--t3)" }}> {m.unit}</span>}
          <div className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)", overflowWrap: "anywhere" }}>{m.formula_sql}</div>
        </div>
      ))}
      {detail.unverified_metrics.length > 0 && (
        <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--t3)" }}>
          {countNoun(detail.unverified_metrics.length, "unverified metric")} not used by the compiler:{" "}
          <span style={MONO}>{detail.unverified_metrics.join(", ")}</span>
        </p>
      )}
    </Section>
  );
}

function PathFinder({ detail, types, connectionId, schema, onOpen }: {
  detail: ObjectTypeDetail;
  types: TypeMapRow[];
  connectionId: string;
  schema?: string;
  onOpen: (objectType: string) => void;
}) {
  const others = types.filter((t) => t.object_type !== detail.object_type);
  const [target, setTarget] = useState("");
  const [found, setFound] = useState<TypePaths | TypeRefusal | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const chosen = others.some((t) => t.object_type === target) ? target : (others[0]?.object_type ?? "");

  useEffect(() => {
    setFound(null);
    setProblem("");
  }, [detail.object_type]);

  const find = async () => {
    setBusy(true);
    setProblem("");
    try {
      setFound(await getTypePaths(detail.object_type, chosen, connectionId, schema));
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Path to" aside="how this type reaches another, hop by hop">
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <select className="aug-fs-xs" style={SELECT} value={chosen} aria-label="Target entity type"
          onChange={(e) => { setTarget(e.target.value); setFound(null); }}>
          {others.map((t) => <option key={t.object_type} value={t.object_type}>{t.display_name}</option>)}
        </select>
        <Button variant="minimal" size="xs" onClick={find} disabled={busy || !chosen} data-testid="entity-find-paths">
          {busy ? "Finding…" : "Find paths"}
        </Button>
      </div>
      {problem && <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--red5)" }}>{problem}</p>}
      {found?.path === "refused" && <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--t3)" }}>{found.refused}</p>}
      {found?.path === "paths" && (
        found.paths.length === 0 ? (
          <EmptyState variant="inline" title={`No chain of links reaches ${found.to_name} within ${found.max_hops} hops.`} />
        ) : (
          <>
            <p className="aug-fs-xs" style={{ margin: "8px 0 2px", color: "var(--t3)" }}>
              {countNoun(found.found, "path")}{found.truncated ? `, the first ${found.paths.length} shown` : ""} · the
              compiler crosses at most {found.compiler_max_hops} links in one path
            </p>
            {found.paths.map((p) => <PathRow key={p.path} path={p} onOpen={onOpen} />)}
          </>
        )
      )}
    </Section>
  );
}

function PathRow({ path, onOpen }: { path: TypePath; onOpen: (objectType: string) => void }) {
  return (
    <div style={{ padding: "8px 0", borderTop: RULE }} data-testid="entity-path">
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span className={`aug-tag ${path.traversable ? "aug-tag-green" : "aug-tag-amber"}`}>
          {path.traversable ? "followed" : "refused"}
        </span>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          {countNoun(path.length, "hop")} · {path.reach}
          {path.compiles_as.length > 0 ? ` · compiles as a ${path.compiles_as.join(" or a ")}` : ""}
        </span>
      </div>
      <ol style={{ listStyle: "none", margin: "6px 0 0", padding: 0 }}>
        {path.hops.map((hop, i) => (
          <li key={`${hop.link}:${i}`} className="aug-fs-xs" style={{ padding: "2px 0" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
              <span style={{ color: hop.traversable ? "var(--grn4)" : "var(--amb4)", display: "inline-flex" }}>
                <Icon name={hop.traversable ? "check" : "close"} size={12} label={hop.traversable ? "Followed" : "Refused"} />
              </span>
              <span style={{ color: "var(--t1)" }}>{hop.from_name}</span>
              <span style={{ color: "var(--t3)" }}>
                {hop.direction === "out" ? `— ${hop.verb || "relates to"} →` : `← ${hop.verb || "relates to"} —`}
              </span>
              <Button variant="ghost" size="xs" onClick={() => onOpen(hop.to)} title={`Light ${hop.to_name} up on the map and open it here`}>
                {hop.to_name}
              </Button>
              <span style={{ ...MONO, color: "var(--t3)" }}>{hop.cardinality}</span>
            </div>
            <div style={{ ...MONO, color: "var(--t3)", paddingLeft: 17 }}>{hop.link}</div>
            {hop.why_not && <div style={{ color: "var(--t3)", paddingLeft: 17, lineHeight: 1.45 }}>{hop.why_not}</div>}
          </li>
        ))}
      </ol>
      {path.why_not && <p className="aug-fs-xs" style={{ margin: "4px 0 0", color: "var(--t3)", lineHeight: 1.45 }}>{path.why_not}</p>}
    </div>
  );
}
