"use client";

/**
 * Your own query, set up in the builder (Arc AP-7; ROADMAP §3.57, the study's §9; design-mockups/cockpit-builder.html
 * screen 10). The user, 2026-10-11: the dashboard was "not flexible enough for the users to choose what they really want
 * to show" — an SQL statement over one table, across tables or another schema, shown as a table, a card or a chart.
 *
 * The person writes SQL beside the tables of the connection's schemas and runs it: how long it took, how many rows, its
 * typed columns and first rows. They choose how it is shown — a table, a figure, a bar, a line, an area, a scatter — and
 * set it up from the columns it returns: what runs along the bottom and in what buckets, what is summed, what splits it
 * and how. Keep runs it once more on the server, checks the setup against what it returns, and keeps a card of their
 * own; a change to one is a new card, and the one it replaces is superseded, so History reads each version. What cannot
 * run or be shown is said, as the server says it — nothing is kept then.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Icon, type IconName } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { SelectField } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  QueryRefused, getCatalogTree, keepDashboardQuery, previewDashboardQuery,
  type DashboardCard, type QueryAgg, type QueryBucket, type QueryPreview, type QueryShown, type QueryShownAs, type TypedColumn,
} from "@/lib/api";
import type { DashboardValueDef } from "@/lib/dashboards/catalog";
import { cellText } from "@/lib/dashboards/objectView";
import { typedValue, valuesRead, type ValuesSent } from "@/lib/dashboards/values";
import { formatCount, formatSeconds } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";

export const QUERY_DEFAULT: QueryShown = {
  as: "table", summed: true, x: "", bucket: "", series: [{ column: "", agg: "count" }], split: "", top: 5,
  segments: "stacked", running: false, labels: false, columns: [], sort: "", descending: true, label: "",
};
const SHOWN: { value: QueryShownAs; label: string; icon: IconName }[] = [
  { value: "table", label: "Table", icon: "table" }, { value: "figure", label: "Figure", icon: "num" },
  { value: "bar", label: "Bar", icon: "chart" }, { value: "line", label: "Line", icon: "trendup" },
  { value: "area", label: "Area", icon: "chart" }, { value: "scatter", label: "Scatter", icon: "graph" },
];
const AGGS: { value: QueryAgg; label: string }[] = [
  { value: "count", label: "Count" }, { value: "count_distinct", label: "Count of different" }, { value: "sum", label: "Sum" },
  { value: "avg", label: "Average" }, { value: "min", label: "Least" }, { value: "max", label: "Most" },
];
const BUCKETS: { value: Exclude<QueryBucket, "">; label: string }[] = [
  { value: "day", label: "Day" }, { value: "week", label: "Week" }, { value: "month", label: "Month" },
  { value: "quarter", label: "Quarter" }, { value: "year", label: "Year" },
];
const MAX_SERIES = 4;
const MAX_TOP = 12;
const PREVIEW_SHOWN = 5;

/** A column's kind as a chart reads it — `aughor/dashboards/queries.py` `kind_of`. */
export function kindOf(type: string): "number" | "date" | "time" | "text" {
  const t = (type || "").toUpperCase();
  if (t.startsWith("DATE") && !t.includes("TIME")) return "date";
  if (t.includes("TIMESTAMP") || t.includes("DATETIME")) return "time";
  if (/INT|DOUBLE|FLOAT|DECIMAL|NUMERIC|REAL|NUMBER|HUGEINT/.test(t)) return "number";
  return "text";
}

/** The setup kept beside a card, else the first one that reads the columns: what a new query starts as. */
function firstSetup(columns: TypedColumn[], as: QueryShownAs): QueryShown {
  const time = columns.find(c => ["date", "time"].includes(kindOf(c.type)));
  const num = columns.find(c => kindOf(c.type) === "number");
  const text = columns.find(c => kindOf(c.type) === "text");
  const series = [{ column: num?.name ?? "", agg: (num ? "sum" : "count") as QueryAgg }];
  if (as === "table") return { ...QUERY_DEFAULT, as };
  if (as === "figure") return { ...QUERY_DEFAULT, as, series };
  if (as === "scatter") {
    const nums = columns.filter(c => kindOf(c.type) === "number");
    return { ...QUERY_DEFAULT, as, summed: false, x: nums[0]?.name ?? time?.name ?? "", series: [{ column: nums[1]?.name ?? nums[0]?.name ?? "", agg: "sum" }] };
  }
  const x = time?.name ?? text?.name ?? columns[0]?.name ?? "";
  return { ...QUERY_DEFAULT, as, x, bucket: time ? "day" : "", series,
    split: text && text.name !== x && time ? text.name : "" };
}

function Row({ label, hint, right, children, testid }: { label: string; hint?: ReactNode; right?: ReactNode; children: ReactNode; testid?: string }) {
  return (
    <div data-testid={testid} style={{ display: "flex", flexDirection: "column", gap: 6, padding: "10px 14px" }}>
      <div className="aug-fs-xs" style={{ display: "flex", alignItems: "baseline", gap: 6, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>
        {label}{right && <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }}>{right}</span>}
      </div>
      {children}
      {hint && <div className="aug-fs-xs" style={{ color: "var(--t3)", lineHeight: 1.45 }}>{hint}</div>}
    </div>
  );
}

function Column({ label, value, columns, onPick, none, only }: {
  label: string; value: string; columns: TypedColumn[]; onPick: (v: string) => void; none?: string;
  only?: ("number" | "date" | "time" | "text")[];
}) {
  const offered = columns.filter(c => !only || only.includes(kindOf(c.type)));
  return (
    <SelectField aria-label={label} value={value} onChange={e => onPick(e.target.value)}>
      {none !== undefined && <option value="">{none}</option>}
      {!none && !value && <option value="">Choose a column</option>}
      {value && !offered.some(c => c.name === value) && <option value={value}>{value}</option>}
      {withUniqueKeys(offered, c => c.name).map(([k, c]) => <option key={k} value={c.name}>{c.name}</option>)}
    </SelectField>
  );
}

/** Arc AP-8 — what a value of the dashboard's is called and holds, as the setup offers it and tries a query with it. */
const NO_VALUES: Record<string, DashboardValueDef> = {};
const KIND_WORDS: Record<string, string> = { days: "days", number: "a number", text: "words", date: "a day" };
const startText = (def: DashboardValueDef) =>
  (def.from?.by ?? "author") === "author" || def.from?.by === "reader" ? (def.value === null || def.value === undefined ? "" : String(def.value)) : "";

export function QuerySetup({ connectionId, card, onKept, onClose, values = NO_VALUES }: {
  connectionId: string;
  /** The card of the person's own query being changed; none — a new one. */
  card?: DashboardCard | null;
  /** The card kept — a new one, or the one that replaces `card` — for the page to place or to swap in. */
  onKept: (kept: DashboardCard, replaced: string | null) => void;
  onClose?: () => void;
  /** Arc AP-8 — the dashboard's values: each may be read in the SQL as `{{name}}`. */
  values?: Record<string, DashboardValueDef>;
}) {
  const render = (card?.render ?? {}) as { shown?: QueryShown; columns?: TypedColumn[] };
  const [sql, setSql] = useState(card?.sql ?? "");
  const [title, setTitle] = useState(card?.title ?? "");
  const [setup, setSetup] = useState<QueryShown>(render.shown ? { ...QUERY_DEFAULT, ...render.shown } : QUERY_DEFAULT);
  const [preview, setPreview] = useState<{ sql: string; got: QueryPreview } | null>(null);
  const [refused, setRefused] = useState<string[]>([]);
  const [busy, setBusy] = useState<"" | "run" | "keep">("");
  const [tables, setTables] = useState<string[] | null>(null);
  const [showTables, setShowTables] = useState(false);
  // Arc AP-8 — the values it reads, and what each is tried with here: the value it starts from, or one typed to try
  const [showValues, setShowValues] = useState(false);
  const [tried, setTried] = useState<Record<string, string>>({});
  const reads = valuesRead(sql);
  const box = useRef<HTMLTextAreaElement>(null);
  const columns = useMemo(() => preview?.got.columns ?? render.columns ?? [], [preview, render.columns]);
  const ranThis = !!preview && preview.sql === sql;
  const changed = !card || sql !== card.sql || title !== card.title || JSON.stringify(setup) !== JSON.stringify({ ...QUERY_DEFAULT, ...render.shown });

  useEffect(() => {
    if (!showTables || tables) return;
    let alive = true;
    getCatalogTree().then(t => {
      if (!alive) return;
      const entry = t.sections.flatMap(s => s.entries).find(e => e.conn_id === connectionId);
      setTables(entry ? entry.schemas.flatMap(s => s.tables.map(tb => `${s.name}.${tb.name}`)) : []);
    }).catch(() => { if (alive) setTables([]); });
    return () => { alive = false; };
  }, [showTables, tables, connectionId]);

  const insert = (text: string) => {
    const el = box.current;
    const at = el ? el.selectionStart : sql.length;
    setSql(sql.slice(0, at) + text + sql.slice(el ? el.selectionEnd : at));
    // the writing goes on where it was, after what was put in
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(at + text.length, at + text.length); });
  };
  /** The values the SQL reads as the query is tried with them — or what stops it, said here before anything runs. */
  const sent = (): { values: ValuesSent } | { refused: string[] } => {
    const out: ValuesSent = {};
    const said: string[] = [];
    for (const name of reads) {
      const def = values[name];
      if (!def) { said.push(`{{${name}}} is not one of this dashboard's values.`); continue; }
      const v = typedValue(def.kind, tried[name] ?? startText(def));
      if (v === null) said.push(`Give ${def.label} ${KIND_WORDS[def.kind] ?? "a value"} to try the query with.`);
      else out[name] = { kind: def.kind, value: v };
    }
    return said.length ? { refused: said } : { values: out };
  };
  const run = async () => {
    setBusy("run"); setRefused([]);
    const given = sent();
    if ("refused" in given) { setRefused(given.refused); setBusy(""); return; }
    try {
      const got = await previewDashboardQuery(connectionId, { sql, shown: setup, title, ...(reads.length ? { values: given.values } : {}) });
      setPreview({ sql, got });
      setRefused(got.refused);
    } catch (e) {
      setRefused([(e as Error).message]);
    } finally { setBusy(""); }
  };
  const keep = async () => {
    setBusy("keep"); setRefused([]);
    const given = sent();
    if ("refused" in given) { setRefused(given.refused); setBusy(""); return; }
    try {
      const out = await keepDashboardQuery(connectionId, { sql, shown: setup, title: title.trim() || undefined, ...(card ? { replaces: card.id } : {}),
        ...(reads.length ? { values: given.values } : {}) });
      setPreview({ sql, got: out.preview });
      onKept(out.card, card?.id ?? null);
    } catch (e) {
      setRefused(e instanceof QueryRefused ? e.reasons : [(e as Error).message]);
    } finally { setBusy(""); }
  };
  const put = (patch: Partial<QueryShown>) => setSetup(s => ({ ...s, ...patch }));
  const shownAs = (as: QueryShownAs) => setSetup(s => (columns.length && (s.as === "table" || !s.x) ? firstSetup(columns, as) : { ...s, as,
    summed: as === "scatter" ? false : s.summed, segments: as === "line" || as === "scatter" ? "stacked" : s.segments }));
  const xKind = kindOf(columns.find(c => c.name === setup.x)?.type ?? "");
  const chart = setup.as !== "table" && setup.as !== "figure";

  return (
    <div data-testid="query-setup" style={{ display: "flex", flexDirection: "column", paddingBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "center", padding: "12px 14px 4px", gap: 8 }}>
        <div style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}>
          <span className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>Card · your own query</span>
          <span className="aug-fs-chrome" style={{ color: "var(--t1)", fontWeight: 600 }}>{card?.title || "A new query"}</span>
        </div>
        {onClose && <Button size="xs" variant="ghost" onClick={onClose}>Close</Button>}
      </div>
      <Row label="Name">
        <Input aria-label="Name" value={title} placeholder="What it shows — Sales by day, by country" maxLength={80} onChange={e => setTitle(e.target.value)} />
      </Row>
      <Row label="SQL" right={<span className="aug-fs-xs" style={{ color: "var(--t3)" }}>read-only · one SELECT</span>}
        hint="One table, several, or another schema — name it with its schema. Checked before it runs and again when kept.">
        <Textarea ref={box} aria-label="SQL" data-testid="query-sql" value={sql} rows={9} spellCheck={false}
          placeholder={"SELECT day, country, SUM(sales) AS sales\nFROM schema.table\nGROUP BY 1, 2"}
          onChange={e => setSql(e.target.value)} onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && sql.trim()) { e.preventDefault(); void run(); } }}
          style={{ fontFamily: "var(--font-mono)" }} />
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Button size="xs" variant="ghost" aria-expanded={showTables} data-testid="query-tables-open" onClick={() => { setShowTables(o => !o); setShowValues(false); }}>
            <Icon name="db" size={13} /> Tables
          </Button>
          <Button size="xs" variant="ghost" aria-expanded={showValues} data-testid="query-values-open" onClick={() => { setShowValues(o => !o); setShowTables(false); }}
            title="One of the dashboard's values, read as a bound parameter: the engine binds it, never pasted into the statement.">
            <Icon name="plus" size={13} /> A variable
          </Button>
          <Button size="xs" variant="secondary" data-testid="query-run" disabled={!sql.trim() || !!busy} onClick={() => void run()} style={{ marginLeft: "auto" }}>
            <Icon name="run" size={13} /> {busy === "run" ? "Running…" : "Run"}
          </Button>
        </div>
        {showTables && (
          <div data-testid="query-tables" role="list" style={{ display: "flex", flexDirection: "column", maxHeight: 160, overflow: "auto", border: "1px solid var(--b1)", borderRadius: "var(--r2)" }}>
            {tables === null ? <span className="aug-fs-xs" style={{ padding: 6, color: "var(--t3)" }}>Reading the tables…</span>
              : tables.length === 0 ? <span className="aug-fs-xs" style={{ padding: 6, color: "var(--t3)" }}>No tables are listed for this connection.</span>
                : withUniqueKeys(tables, t => t).map(([k, t]) => (
                  <Button key={k} role="listitem" size="xs" variant="ghost" onClick={() => insert(t)} style={{ justifyContent: "flex-start", fontFamily: "var(--font-mono)" }}>{t}</Button>
                ))}
          </div>
        )}
        {showValues && (
          <div data-testid="query-values" role="list" style={{ display: "flex", flexDirection: "column", maxHeight: 160, overflow: "auto", border: "1px solid var(--b1)", borderRadius: "var(--r2)" }}>
            {Object.keys(values).length === 0
              ? <span className="aug-fs-xs" style={{ padding: 6, color: "var(--t3)" }}>This dashboard holds no value yet: add one in Variables.</span>
              : Object.entries(values).map(([name, def]) => (
                <Button key={name} role="listitem" size="xs" variant="ghost" onClick={() => { insert(`{{${name}}}`); setShowValues(false); }}
                  style={{ justifyContent: "flex-start", gap: 8 }}>
                  <span style={{ fontFamily: "var(--font-mono)" }}>{`{{${name}}}`}</span>
                  <span style={{ color: "var(--t3)" }}>{def.label} · {KIND_WORDS[def.kind] ?? def.kind}</span>
                </Button>
              ))}
          </div>
        )}
        {reads.length > 0 && (
          <div data-testid="query-tried" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>Tried here with these; on the page it reads what the page holds.</span>
            {reads.map(name => {
              const def = values[name];
              return (
                <label key={name} className="aug-fs-xs" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 120px", alignItems: "center", gap: 6, color: "var(--t2)" }}>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    <span style={{ fontFamily: "var(--font-mono)" }}>{`{{${name}}}`}</span>{def ? ` ${def.label}` : " — not a value of this dashboard"}
                  </span>
                  {def && (
                    <Input aria-label={`Try ${def.label} as`} value={tried[name] ?? startText(def)} type={def.kind === "date" ? "date" : def.kind === "text" ? "text" : "number"}
                      onChange={e => setTried(t => ({ ...t, [name]: e.target.value }))} />
                  )}
                </label>
              );
            })}
          </div>
        )}
        {refused.length > 0 && (
          <Callout tone="amber" data-testid="query-refused" role="alert">
            <span style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {withUniqueKeys(refused, r => r).map(([k, r]) => <span key={k} className="aug-fs-xs">{r}</span>)}
            </span>
          </Callout>
        )}
        {preview && !preview.got.refused.length && preview.got.columns && (
          <div data-testid="query-ran" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--t2)" }}>
              <Icon name="check" size={13} />
              {formatSeconds(preview.got.duration_ms ?? 0)} · {formatCount(preview.got.rows?.length ?? 0)}{preview.got.more ? "+" : ""} rows · {preview.got.columns.map(c => c.name).join(", ")}
              {!ranThis && <span style={{ color: "var(--t3)" }}> · the SQL changed since</span>}
            </span>
            <div style={{ overflow: "auto" }}>
              <table className="aug-fs-xs" style={{ width: "100%", borderCollapse: "collapse", fontVariantNumeric: "tabular-nums" }}>
                <thead><tr>{preview.got.columns.map((c, j) => <th key={`${c.name}-${j}`} style={{ textAlign: "left", color: "var(--t3)", fontWeight: 500, padding: "3px 5px", whiteSpace: "nowrap" }}>{c.name}</th>)}</tr></thead>
                <tbody>{(preview.got.rows ?? []).slice(0, PREVIEW_SHOWN).map((r, i) => (
                  <tr key={i}>{r.map((v, j) => <td key={j} style={{ padding: "3px 5px", whiteSpace: "nowrap", borderTop: "1px solid var(--b1)" }}>{cellText(v, preview.got.columns?.[j]?.type)}</td>)}</tr>
                ))}</tbody>
              </table>
            </div>
          </div>
        )}
      </Row>
      <Row label="Shown as" testid="query-shown-as">
        <div role="radiogroup" aria-label="Shown as" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4 }}>
          {SHOWN.map(o => (
            <Button key={o.value} size="xs" role="radio" aria-checked={setup.as === o.value} variant={setup.as === o.value ? "secondary" : "ghost"}
              data-testid="query-shown" onClick={() => shownAs(o.value)} style={{ flexDirection: "column", height: "auto", padding: "6px 0", gap: 3 }}>
              <Icon name={o.icon} size={14} />{o.label}
            </Button>
          ))}
        </div>
      </Row>
      {setup.as === "table" && (
        <>
          <Row label="Columns" hint="None ticked: every column, as the query returns them.">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {columns.length === 0 && <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>Run the query to choose its columns.</span>}
              {withUniqueKeys(columns, c => c.name).map(([k, c]) => {
                const on = setup.columns.includes(c.name);
                return (
                  <Button key={k} size="xs" variant={on ? "secondary" : "ghost"} aria-pressed={on}
                    onClick={() => put({ columns: on ? setup.columns.filter(x => x !== c.name) : [...setup.columns, c.name] })}>{c.name}</Button>
                );
              })}
            </div>
          </Row>
          <Row label="Sorted by">
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 6, alignItems: "center" }}>
              <Column label="Sorted by" value={setup.sort} columns={columns} none="As the query returns them" onPick={v => put({ sort: v })} />
              <Segmented label="Order" value={setup.descending ? "desc" : "asc"} onChange={v => put({ descending: v === "desc" })}
                options={[{ value: "desc", label: "Largest first" }, { value: "asc", label: "Smallest" }]} disabled={!setup.sort} />
            </div>
          </Row>
        </>
      )}
      {setup.as === "figure" && (
        <>
          <Row label="The value">
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 6 }}>
              <SelectField aria-label="Calculation" value={setup.series[0]?.agg ?? "count"} onChange={e => put({ series: [{ column: setup.series[0]?.column ?? "", agg: e.target.value as QueryAgg }] })}>
                {AGGS.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
              </SelectField>
              <Column label="Of" value={setup.series[0]?.column ?? ""} columns={columns} none={setup.series[0]?.agg === "count" ? "Rows" : undefined}
                only={["sum", "avg"].includes(setup.series[0]?.agg ?? "") ? ["number"] : undefined}
                onPick={v => put({ series: [{ agg: setup.series[0]?.agg ?? "count", column: v }] })} />
            </div>
          </Row>
          <Row label="Label"><Input aria-label="Label" value={setup.label} maxLength={60} placeholder="Said under the figure" onChange={e => put({ label: e.target.value })} /></Row>
        </>
      )}
      {chart && (
        <>
          <Row label="Along the bottom" right={setup.as !== "scatter" && ["date", "time"].includes(xKind) ? "buckets" : undefined}>
            <Column label="Along the bottom" value={setup.x} columns={columns} only={setup.as === "scatter" ? ["number", "date", "time"] : undefined}
              onPick={v => put({ x: v, bucket: ["date", "time"].includes(kindOf(columns.find(c => c.name === v)?.type ?? "")) && setup.as !== "scatter" ? (setup.bucket || "day") : "" })} />
            {setup.as !== "scatter" && ["date", "time"].includes(xKind) && (
              <Segmented label="Buckets" value={setup.bucket || "day"} onChange={v => put({ bucket: v })} options={BUCKETS} />
            )}
          </Row>
          <Row label="Height" right={setup.as !== "scatter" && setup.series.length < MAX_SERIES && !setup.split ? (
            <Button size="xs" variant="ghost" onClick={() => put({ series: [...setup.series, { column: "", agg: "count" }] })}><Icon name="plus" size={12} /> Another series</Button>
          ) : undefined}>
            {setup.series.map((s, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: setup.as === "scatter" ? "minmax(0,1fr)" : "minmax(0,1fr) minmax(0,1fr) auto", gap: 6, alignItems: "center" }}>
                {setup.as !== "scatter" && setup.summed && (
                  <SelectField aria-label={`Calculation ${i + 1}`} value={s.agg}
                    onChange={e => put({ series: setup.series.map((x, j) => (j === i ? { ...x, agg: e.target.value as QueryAgg } : x)) })}>
                    {AGGS.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
                  </SelectField>
                )}
                <Column label={`Of ${i + 1}`} value={s.column} columns={columns} none={setup.summed && s.agg === "count" ? "Rows" : undefined}
                  only={!setup.summed || setup.as === "scatter" || ["sum", "avg"].includes(s.agg) ? ["number"] : undefined}
                  onPick={v => put({ series: setup.series.map((x, j) => (j === i ? { ...x, column: v } : x)) })} />
                {setup.series.length > 1 && (
                  <Button size="xs" variant="ghost" aria-label={`Take off series ${i + 1}`} onClick={() => put({ series: setup.series.filter((_, j) => j !== i) })}><Icon name="close" size={12} /></Button>
                )}
              </div>
            ))}
            {setup.as !== "scatter" && (
              <span className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--t2)" }}>
                <Switch aria-label="Summed by the platform" checked={setup.summed} onChange={e => put({ summed: e.target.checked })} />
                {setup.summed ? "Summed here" : "As the query returns it"}
                <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 8 }}>
                  <Switch aria-label="Running total" checked={setup.running} onChange={e => put({ running: e.target.checked })} />Running total
                </span>
              </span>
            )}
          </Row>
          <Row label="Split by" hint={setup.series.length > 1 ? "A chart of more than one series is split by its series." : undefined}>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 6, alignItems: "center" }}>
              <Column label="Split by" value={setup.split} columns={columns.filter(c => c.name !== setup.x)} none="Nothing" onPick={v => put({ split: v })} />
              <SelectField aria-label="Top" value={String(setup.top)} onChange={e => put({ top: Number(e.target.value) })} disabled={!setup.split}>
                {Array.from({ length: MAX_TOP }, (_, i) => i + 1).map(n => <option key={n} value={n}>{`Top ${n} · the rest as Other`}</option>)}
              </SelectField>
            </div>
          </Row>
          {(setup.as === "bar" || setup.as === "area") && (
            <Row label="Segments">
              <Segmented label="Segments" value={setup.segments} onChange={v => put({ segments: v })}
                options={[{ value: "stacked", label: "Stacked" }, { value: "side_by_side", label: setup.as === "area" ? "Over each other" : "Side by side" }, { value: "shares", label: "Shares" }]} />
            </Row>
          )}
          {setup.as !== "scatter" && (
            <Row label="Labels">
              <span className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--t2)" }}>
                <Switch aria-label="Labels" checked={setup.labels} onChange={e => put({ labels: e.target.checked })} />
                {xKind === "text" ? "Each bar's value" : "The value at the last place along the bottom"}
              </span>
            </Row>
          )}
        </>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 14px 0", borderTop: "1px solid var(--b1)", marginTop: 6 }}>
        <span className="aug-fs-xs" style={{ color: "var(--t3)", flex: 1 }}>
          {card ? "A change is kept as a new version of this card; History keeps the one before." : "Kept as a card of yours, in this section."}
        </span>
        <Button size="sm" data-testid="query-keep" disabled={!sql.trim() || !!busy || !changed} onClick={() => void keep()}>
          {busy === "keep" ? "Keeping…" : card ? "Keep the change" : "Keep"}
        </Button>
      </div>
    </div>
  );
}
