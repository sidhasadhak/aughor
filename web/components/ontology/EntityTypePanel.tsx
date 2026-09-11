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

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { SkeletonRows } from "@/components/ui/motion";
import { countNoun, formatCount } from "@/lib/format";
import { declaredActionsHref } from "@/lib/objectLinks";
import {
  addBinding,
  declareDisplayProperty,
  getObjectType,
  getTypePaths,
  measureOntology,
  removeBinding,
  type ObjectTypeDetail,
  type PropertySource,
  type ProposedBinding,
  type TypeBinding,
  type TypeLink,
  type TypeMapRow,
  type TypePath,
  type TypePaths,
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

export function EntityTypePanel({ connectionId, schema, objectType, types, version, onOpen, onChanged }: {
  connectionId: string;
  schema?: string;
  objectType: string;
  types: TypeMapRow[];
  /** Bumped when the map re-reads, so the panel re-reads with it. */
  version: number;
  onOpen: (objectType: string) => void;
  /** A write here (a declaration, a measurement) changes what the map shows. */
  onChanged: () => void;
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
      onOpen={onOpen} onChanged={onChanged} />;
  }
  return (
    <aside aria-label="Entity type" data-testid="entity-type-panel"
      style={{ width: 360, flexShrink: 0, borderLeft: RULE, display: "flex", flexDirection: "column", minHeight: 0,
               background: "var(--bg-0)" }}>
      <div style={{ flex: 1, overflowY: "auto" }}>{body}</div>
    </aside>
  );
}

function TypeDetail({ detail, connectionId, schema, types, onOpen, onChanged }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  types: TypeMapRow[];
  onOpen: (objectType: string) => void;
  onChanged: () => void;
}) {
  return (
    <>
      <header style={{ padding: "14px 16px 12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <h2 className="aug-fs-h2" style={{ margin: 0, color: "var(--t1)" }}>{detail.display_name}</h2>
          <span className="aug-tag aug-tag-gray">{ROLE[detail.role] ?? detail.role}</span>
          {detail.domain && <span className="aug-tag aug-tag-violet">{detail.domain}</span>}
        </div>
        <div className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)", marginTop: 2 }}>{detail.object_type}</div>
        {detail.description && (
          <p className="aug-fs-sm" style={{ margin: "8px 0 0", color: "var(--t2)", lineHeight: 1.5 }}>{detail.description}</p>
        )}
      </header>
      <KeySection detail={detail} />
      <DisplaySection detail={detail} connectionId={connectionId} schema={schema} onChanged={onChanged} />
      <PropertiesSection detail={detail} />
      <BindingsSection detail={detail} connectionId={connectionId} schema={schema} onChanged={onChanged} />
      <LinksSection detail={detail} onOpen={onOpen} />
      <ActionsSection detail={detail} connectionId={connectionId} />
      <MetricsSection detail={detail} />
      <PathFinder detail={detail} types={types} connectionId={connectionId} schema={schema} onOpen={onOpen} />
    </>
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

function DisplaySection({ detail, connectionId, schema, onChanged }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  onChanged: () => void;
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
        <label className="aug-fs-xs" htmlFor={`display-${detail.object_type}`} style={{ color: "var(--t3)" }}>Declare</label>
        <select id={`display-${detail.object_type}`} className="aug-fs-xs" style={SELECT} value={shown.property}
          disabled={busy} onChange={(e) => act(() => declareDisplayProperty(connectionId, detail.id, e.target.value, schema))}>
          {choices.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
        </select>
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
  if (source.binding === "overlay") {
    const text = `overlay · ${countNoun(source.edits ?? 0, "accepted edit")}`;
    return { short: text, full: text };
  }
  const table = source.table ?? source.binding;
  const bare = table.split(".").pop() ?? table;
  const column = source.column ?? "";
  const how = source.kind
    ? ` · the ${source.kind} binding ${source.binding}`
      + (source.read === false ? ", not read yet" : source.kind === "timeseries" ? ", its latest value" : "")
    : "";
  return { short: `${bare}.${column}`, full: `${table}.${column}${how}` };
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
function bindingVerdict(b: TypeBinding): [string, string] | null {
  if (b.primary) return null;
  if (b.usable) {
    return ["aug-tag-green", b.kind === "timeseries" ? `read · latest by ${b.time_column}` : "read"];
  }
  if (b.kind === "timeseries" && !b.time_column) return ["aug-tag-gray", "no time column"];
  return b.verified === false ? ["aug-tag-red", "refuted"] : ["aug-tag-gray", "not yet measured"];
}

function BindingRow({ binding: b, first, busy, onRemove }: {
  binding: TypeBinding;
  first: boolean;
  busy: boolean;
  onRemove?: () => void;
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
        would supply {p.supplies.join(", ")}
      </p>
    </div>
  );
}

function BindingsSection({ detail, connectionId, schema, onChanged }: {
  detail: ObjectTypeDetail;
  connectionId: string;
  schema?: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
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
        <BindingRow key={b.name} binding={b} first={i === 0} busy={busy === b.name}
          onRemove={b.source === "human" ? () => act(b.name, () => removeBinding(connectionId, detail.id, b.name, schema)) : undefined} />
      ))}
      {proposals.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            Proposed from the data — another table carries the {detail.key.property} key, one row per object. Nothing
            reads a proposal until it is bound.
          </div>
          {proposals.map((p) => (
            <ProposalRow key={p.name} proposal={p} busy={busy === p.name}
              onBind={() => act(p.name, () => addBinding(connectionId, detail.id, p.name, p.spec, schema))} />
          ))}
        </div>
      )}
      {problem && <p className="aug-fs-xs" style={{ margin: "6px 0 0", color: "var(--red5)" }}>{problem}</p>}
    </Section>
  );
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

function LinksSection({ detail, onOpen }: { detail: ObjectTypeDetail; onOpen: (objectType: string) => void }) {
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
          </div>
          <div className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)", marginTop: 3, overflowWrap: "anywhere" }}>
            {link.business_name && <>{link.business_name}{link.business_name_source === "human" ? " (declared)" : ""} · </>}
            {link.name} · {link.on}
          </div>
          {link.why_not && <p className="aug-fs-xs" style={{ margin: "3px 0 0", color: "var(--t3)", lineHeight: 1.45 }}>{link.why_not}</p>}
        </div>
      ))}
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
