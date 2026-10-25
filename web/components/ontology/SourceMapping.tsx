"use client";

/**
 * The mapping picture (2026-10-25, the look study §10: "see how ontology is getting created"): the table's
 * columns on the left, the type's properties on the right, and a connector from each column to the property read
 * from it — straight, bending at right angles, as every connector in this product does — with the chosen pair in
 * the accent and the property's facts beneath. Read first: nothing here writes; Edit's doors stand below as before.
 *
 * Endpoints are computed, not measured: every row is ROW px tall on both sides, so a connector's y is its row's
 * index — jsdom reports no geometry, and a picture that needs none can be held by a test. A column no property
 * reads is said to be "not read"; a property read elsewhere says from where, or what computes it.
 */
import React, { useState } from "react";

import { ColumnTypeSquare } from "@/components/icons/columnType";
import { Icon } from "@/components/ui/icon";
import type { TableColumn } from "@/lib/api";
import { COLUMN_KIND_LABEL, columnTypeKind, formatCount, pct } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import type { ObjectTypeDetail, TypeBinding, TypeProperty } from "@/lib/objectTypes";

/** One row's height on both sides, so a connector's end is its row's index. */
export const ROW = 26;
/** The gutter the connectors cross; each bends at its middle. */
export const GUTTER = 72;
const MONO: React.CSSProperties = { fontFamily: "var(--font-mono)" };
const CLIP: React.CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 };

/** What computes a property that no column of this table supplies. */
function computedBy(p: TypeProperty): string {
  const s = p.source;
  if (s.expression) return "= expression";
  if (s.rollup) return "a rollup";
  if (s.frame) return "a frame";
  if (s.edits) return "edits";
  return "";
}

/** The connector's path: out level, upright at the gutter's middle, in level — right angles only. */
export function connector(fromRow: number, toRow: number): string {
  const y1 = fromRow * ROW + ROW / 2;
  const y2 = toRow * ROW + ROW / 2;
  return `M 0 ${y1} H ${GUTTER / 2} V ${y2} H ${GUTTER}`;
}

function Term({ children }: { children: React.ReactNode }) {
  return <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{children}</span>;
}
function Val({ children, mono }: { children: React.ReactNode; mono?: boolean }) {
  return <span className="aug-fs-sm" style={{ color: "var(--t1)", ...(mono ? MONO : {}), minWidth: 0, overflowWrap: "anywhere" }}>{children}</span>;
}

export function SourceMapping({ detail, binding, columns, said }: {
  detail: ObjectTypeDetail;
  /** The binding drawn — the primary one, the table the type is read from. */
  binding: TypeBinding;
  /** The table's columns with their types; null while they are being read. */
  columns: TableColumn[] | null;
  /** Why the columns could not be read, when they could not. */
  said?: string;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const props = detail.properties;
  const cols = columns ?? [];
  const colIndex = new Map(cols.map((c, i) => [c.name.toLowerCase(), i] as const));
  // property → the index of the column it is read from, through THIS binding
  const from = new Map<string, number>();
  for (const p of props) {
    if (p.source.binding === binding.name && p.source.column) {
      const i = colIndex.get(p.source.column.toLowerCase());
      if (i !== undefined) from.set(p.name, i);
    }
  }
  const readColumns = new Set(from.values());
  const height = Math.max(cols.length, props.length, 1) * ROW;
  const chosenProp = chosen ? props.find((p) => p.name === chosen) ?? null : null;
  const chosenColumn = chosenProp && from.has(chosenProp.name) ? cols[from.get(chosenProp.name) as number] : null;
  const pick = (name: string) => setChosen((c) => (c === name ? null : name));
  const pickColumn = (i: number) => {
    const p = props.find((q) => from.get(q.name) === i);
    if (p) pick(p.name);
  };
  const onKey = (act: () => void) => (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(); }
  };
  const row = (active: boolean, muted: boolean): React.CSSProperties => ({
    height: ROW, display: "flex", alignItems: "center", gap: 8, padding: "0 8px", minWidth: 0, cursor: "pointer",
    background: active ? "var(--bg-sel)" : undefined, borderRadius: "var(--r1)", color: muted ? "var(--t3)" : "var(--t1)",
  });
  const column: React.CSSProperties = { background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r2)", padding: 4 };
  const head: React.CSSProperties = { color: "var(--t3)", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".06em", padding: "0 8px 6px", ...CLIP };
  const note: React.CSSProperties = { margin: 0, padding: "6px 8px", color: "var(--t3)" };
  const readsTable = binding.reads === "table" && !!binding.table;
  const isDisplay = (p: TypeProperty) => detail.display_property?.property === p.name;
  return (
    <div data-testid="source-mapping" style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: `minmax(0, 1fr) ${GUTTER}px minmax(0, 1fr)`, alignItems: "start" }}>
        <div className="aug-fs-xs" style={head} title={readsTable ? binding.table : undefined}>{readsTable ? binding.table : "Columns"}</div>
        <div />
        <div className="aug-fs-xs" style={head}>{detail.display_name}</div>

        <div style={column} data-testid="mapping-columns">
          {!readsTable ? (
            <p className="aug-fs-xs" style={note}>This binding reads a query; the picture needs a table.</p>
          ) : said ? (
            <p className="aug-fs-xs" style={note}>{said}</p>
          ) : columns === null ? (
            <p className="aug-fs-xs" style={note}>Reading the table&rsquo;s columns…</p>
          ) : cols.length === 0 ? (
            <p className="aug-fs-xs" style={note}>The table lists no columns.</p>
          ) : withUniqueKeys(cols, (c) => c.name).map(([key, c], i) => {
            const read = readColumns.has(i);
            const active = !!chosenColumn && chosenColumn.name === c.name;
            return (
              <div key={key} role="button" tabIndex={0} data-testid="mapping-column" data-read={read ? "true" : "false"}
                aria-pressed={active} style={row(active, !read)} onClick={() => pickColumn(i)} onKeyDown={onKey(() => pickColumn(i))}
                title={read ? `${c.name} · ${c.type}` : `${c.name} · ${c.type} — no property of ${detail.display_name} reads it`}>
                <ColumnTypeSquare type={c.type} />
                <span className="aug-fs-sm" style={{ ...MONO, ...CLIP }}>{c.name}</span>
                <span className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--t3)", whiteSpace: "nowrap" }}>{read ? c.type : "not read"}</span>
              </div>
            );
          })}
        </div>

        <svg width={GUTTER} height={height} aria-hidden style={{ display: "block", overflow: "visible", marginTop: 4 }}>
          {withUniqueKeys(props.filter((p) => from.has(p.name)), (p) => p.name).map(([key, p]) => {
            const active = chosen === p.name;
            const i = from.get(p.name) as number;
            const j = props.indexOf(p);
            const ink = active ? "var(--accent)" : "var(--t4)";
            return (
              <g key={key} data-testid="mapping-line" data-chosen={active ? "true" : "false"}>
                <path d={connector(i, j)} fill="none" stroke={ink} strokeWidth={active ? 1.5 : 1} />
                <circle cx={0} cy={i * ROW + ROW / 2} r={3} fill="var(--bg-2)" stroke={ink} />
                <circle cx={GUTTER} cy={j * ROW + ROW / 2} r={3} fill="var(--bg-2)" stroke={ink} />
              </g>
            );
          })}
        </svg>

        <div style={column} data-testid="mapping-properties">
          {withUniqueKeys(props, (p) => p.name).map(([key, p]) => {
            const active = chosen === p.name;
            const read = from.has(p.name);
            const word = read ? "" : computedBy(p)
              || (p.source.binding && p.source.binding !== binding.name ? `via ${p.source.binding}` : "not read here");
            return (
              <div key={key} role="button" tabIndex={0} data-testid="mapping-property" aria-pressed={active}
                style={row(active, false)} onClick={() => pick(p.name)} onKeyDown={onKey(() => pick(p.name))}
                title={p.description || p.display_name || p.name}>
                <ColumnTypeSquare type={p.data_type} />
                <span className="aug-fs-sm" style={{ ...MONO, ...CLIP }}>{p.name}</span>
                {p.is_key && <span style={{ color: "var(--t3)", display: "inline-flex" }}><Icon name="key" size={11} label="Key" /></span>}
                {isDisplay(p) && <span style={{ color: "var(--t3)", display: "inline-flex" }}><Icon name="bookmark" size={11} label="Display property" /></span>}
                <span className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--t3)", whiteSpace: "nowrap" }}>{word}</span>
              </div>
            );
          })}
        </div>
      </div>

      {chosenProp && (
        <div data-testid="mapping-inspector"
          style={{ background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r2)", padding: "10px 12px",
                   display: "grid", gridTemplateColumns: "auto minmax(0, 1fr)", gap: "4px 14px", alignItems: "baseline" }}>
          <Term>Property</Term><Val mono>{chosenProp.name}</Val>
          <Term>Display name</Term><Val>{chosenProp.display_name || "—"}</Val>
          <Term>Kind</Term>
          <Val>{COLUMN_KIND_LABEL[columnTypeKind(chosenProp.data_type)]}{chosenProp.data_type ? ` · ${chosenProp.data_type}` : ""}</Val>
          <Term>Read from</Term>
          <Val mono>{chosenColumn ? `${binding.table}.${chosenColumn.name}` : computedBy(chosenProp) || "not this table"}</Val>
          {chosenProp.role && <><Term>Role</Term><Val>{chosenProp.role}</Val></>}
          <Term>Marks</Term>
          <Val>{[chosenProp.is_key && "key", isDisplay(chosenProp) && "display property"].filter(Boolean).join(" · ") || "—"}</Val>
          {chosenProp.null_rate != null && <><Term>Empty</Term><Val>{pct(chosenProp.null_rate, 1)} of rows</Val></>}
          {chosenProp.description && <><Term>About</Term><Val>{chosenProp.description}</Val></>}
        </div>
      )}

      <p className="aug-fs-xs" style={{ margin: 0, color: "var(--t3)" }}>
        {readsTable
          ? `${formatCount(from.size)} of ${formatCount(props.length)} properties are read from ${binding.table}; a line is a column read as a property.`
          : `${formatCount(props.length)} properties; the binding reads a query, so no column is drawn.`}
      </p>
    </div>
  );
}
