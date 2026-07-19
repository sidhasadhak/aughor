"use client";

/**
 * NewCardComposer — Door 3 of the briefing cockpit (Slice 4): author a card inline, without
 * leaving the briefing, and pin it through the SAME guarded pin-query path as the Query-Builder
 * door. Two ways in:
 *
 *   • From metric — pick one of the connection's grounded north-star metrics (value or trend).
 *   • Build      — free-form: pick a table, a measure + aggregation, and (optionally) a dimension
 *                  to break down by, straight from the connection's real schema. The SQL is
 *                  composed from those parts, previewed live, and only pinnable once the preview
 *                  binds — so an ungrounded pick is caught before the guard ever sees it.
 *
 * The Card primitive, persistence, guarding and render already exist from Doors 1–2, so this is
 * the cheapest door.
 */
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Sparkline } from "@/components/brief/Sparkline";
import { cleanLabel, formatMetricValue } from "@/lib/format";
import {
  getBusinessProfile, getSchemaRich, runDirectQuery, pinQueryToDashboard,
  type NorthStarMetric, type DirectQueryResult, type SchemaTable,
} from "@/lib/api";
import { toast } from "@/components/ui/toast";

const inputStyle = {
  fontSize: 11, background: "var(--bg-1)", border: "1px solid var(--b1)",
  borderRadius: "var(--r2)", color: "var(--t1)", padding: "4px 7px", outline: "none",
} as const;

// Column-type buckets — a measure must be numeric; everything else can be a break-down dimension.
const NUMERIC_RE = /^(BIG|SMALL|TINY|HUGE)?INT|INTEGER|DECIMAL|NUMERIC|DOUBLE|FLOAT|REAL|DEC\b/i;

const AGGS: { v: string; t: string; needsMeasure: boolean }[] = [
  { v: "count", t: "Count of rows", needsMeasure: false },
  { v: "sum", t: "Sum", needsMeasure: true },
  { v: "avg", t: "Average", needsMeasure: true },
  { v: "min", t: "Min", needsMeasure: true },
  { v: "max", t: "Max", needsMeasure: true },
];

/** Quote a SQL identifier; a schema-qualified name is quoted part-by-part. */
function qid(id: string): string {
  return id.split(".").map(p => `"${p.replace(/"/g, '""')}"`).join(".");
}

/** Compose grounded SQL from the picked parts (mirrors the governed /metrics/{name}/value shape). */
function buildSql(table: string, agg: string, measure: string, dim: string): string {
  const isCount = agg === "count";
  const sel = isCount ? "COUNT(*)" : `${agg.toUpperCase()}(${qid(measure)})`;
  const alias = qid(isCount ? "count" : `${agg}_${measure}`);
  const from = qid(table);
  if (!dim) return `SELECT ${sel} AS ${alias} FROM ${from}`;
  return `SELECT ${qid(dim)}, ${sel} AS ${alias} FROM ${from} GROUP BY ${qid(dim)} ORDER BY 2 DESC LIMIT 50`;
}

/** Numbers from the last column of a preview result → the value / sparkline. */
function seriesValues(r: DirectQueryResult | null): number[] {
  if (!r || r.error || !r.rows?.length) return [];
  const c = Math.max(0, r.columns.length - 1);
  return r.rows.map(row => Number(row[c])).filter(v => Number.isFinite(v));
}

export function NewCardComposer({ connectionId, schema, onCreated }: {
  connectionId: string;
  schema?: string;
  onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"metric" | "build">("metric");

  // ── From-metric state ──
  const [metrics, setMetrics] = useState<NorthStarMetric[]>([]);
  const [sel, setSel] = useState("");
  const [shape, setShape] = useState<"value" | "trend">("value");

  // ── Build state ──
  const [tables, setTables] = useState<SchemaTable[]>([]);
  const [bTable, setBTable] = useState("");
  const [bAgg, setBAgg] = useState("count");
  const [bMeasure, setBMeasure] = useState("");
  const [bDim, setBDim] = useState("");

  const [title, setTitle] = useState("");
  const [preview, setPreview] = useState<DirectQueryResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load the connection's grounded north-star metrics when the composer opens.
  useEffect(() => {
    if (!open || !connectionId) return;
    getBusinessProfile(connectionId, schema)
      .then(p => setMetrics((p.profile?.north_star_metrics || []).filter(m => m.value_sql || m.chart_sql)))
      .catch(() => setMetrics([]));
  }, [open, connectionId, schema]);

  // Load the real schema (tables + typed columns, one call) when the Build tab is first used.
  useEffect(() => {
    if (!open || mode !== "build" || !connectionId || tables.length) return;
    getSchemaRich(connectionId).then(s => setTables(s.tables || [])).catch(() => setTables([]));
  }, [open, mode, connectionId, tables.length]);

  const metric = useMemo(() => metrics.find(m => m.name === sel), [metrics, sel]);
  const tableObj = useMemo(() => tables.find(t => t.name === bTable), [tables, bTable]);
  const numericCols = useMemo(() => (tableObj?.columns || []).filter(c => NUMERIC_RE.test(c.type)), [tableObj]);
  const dimCols = useMemo(() => (tableObj?.columns || []).filter(c => !NUMERIC_RE.test(c.type)), [tableObj]);
  const aggDef = AGGS.find(a => a.v === bAgg);
  const buildReady = mode === "build" && !!bTable && (!aggDef?.needsMeasure || !!bMeasure);

  // Unified SQL for whichever door is active.
  const sql = useMemo(() => {
    if (mode === "metric") return metric ? (shape === "trend" ? (metric.chart_sql || "") : (metric.value_sql || "")) : "";
    return buildReady ? buildSql(bTable, bAgg, bMeasure, bDim) : "";
  }, [mode, metric, shape, buildReady, bTable, bAgg, bMeasure, bDim]);

  // A sensible default title for whichever door is active (used until the user types one).
  const defaultTitle = useMemo(() => {
    if (mode === "metric") return metric?.name || "";
    if (!buildReady) return "";
    // "Count of rows" already reads as a full phrase; a measure agg appends its column.
    const meas = aggDef?.needsMeasure ? ` ${cleanLabel(bMeasure)}` : "";
    return `${aggDef?.t || bAgg}${meas}${bDim ? ` by ${cleanLabel(bDim)}` : ""}`;
  }, [mode, metric, buildReady, aggDef, bMeasure, bDim, bAgg]);

  // Live preview whenever the composed SQL changes.
  useEffect(() => {
    if (!sql) { setPreview(null); return; }
    let cancelled = false;
    setPreviewing(true); setError(null);
    runDirectQuery(connectionId, sql, 60, { useCache: true })
      .then(r => { if (!cancelled) setPreview(r); })
      .catch(() => { if (!cancelled) setPreview(null); })
      .finally(() => { if (!cancelled) setPreviewing(false); });
    return () => { cancelled = true; };
  }, [sql, connectionId]);

  const pickMetric = (name: string) => {
    setSel(name); setTitle("");
    const m = metrics.find(x => x.name === name);
    setShape(m?.value_sql ? "value" : "trend");
  };
  const pickTable = (name: string) => {
    setBTable(name); setBMeasure(""); setBDim(""); setTitle("");
  };
  const reset = () => {
    setOpen(false); setSel(""); setTitle(""); setPreview(null); setError(null);
    setBTable(""); setBMeasure(""); setBDim(""); setBAgg("count");
  };

  const chartType = mode === "metric"
    ? (shape === "trend" ? "line" : "auto")
    : (bDim ? "bar" : "auto");

  const pin = async () => {
    if (!sql.trim()) return;
    setBusy(true); setError(null);
    try {
      await pinQueryToDashboard(connectionId, sql, title.trim() || defaultTitle || "New card", {
        scope: "connection", scopeRef: connectionId, schema,
        render: { chartType },
      });
      toast.success("Pinned to your cockpit");
      onCreated(); reset();
    } catch (e) {
      const msg = (e as Error).message || "Could not pin — the query failed the trust guards";
      setError(msg);
      toast.error("Card refused by the trust guards", { description: msg.slice(0, 140) });
    } finally { setBusy(false); }
  };

  if (!open) {
    return (
      <div style={{ marginBottom: 12 }}>
        <Button variant="ghost" size="xs" onClick={() => setOpen(true)}
          title="Author a new cockpit card from a grounded metric"
          style={{ fontSize: 11, color: "var(--vio4)", padding: "3px 8px", border: "1px dashed color-mix(in srgb, var(--vio4) 40%, var(--b1))", borderRadius: "var(--r2)" }}>
          ＋ New card
        </Button>
      </div>
    );
  }

  const vals = seriesValues(preview);
  const isScalar = !!preview && !preview.error && preview.rows?.length === 1 && preview.columns.length === 1;
  const canPin = !!sql && !previewing && !!preview && !preview.error && vals.length > 0;

  return (
    <div style={{
      marginBottom: 14, padding: "12px 14px", borderRadius: "var(--r3)",
      background: "var(--bg-2)", border: "1px solid var(--b1)",
      display: "flex", flexDirection: "column", gap: 9,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div className="aug-label">New card</div>
        {/* Door picker: curated metric vs free-form build. */}
        <div style={{ display: "inline-flex", borderRadius: "var(--r2)", border: "1px solid var(--b1)", overflow: "hidden" }}>
          {([["metric", "From metric"], ["build", "Build"]] as const).map(([m, label]) => (
            <Button key={m} variant="ghost" size="xs" onClick={() => setMode(m)} className="aug-fs-xs"
              style={{
                padding: "4px 10px", height: "auto", borderRadius: 0,
                background: mode === m ? "var(--bg-1)" : "transparent",
                color: mode === m ? "var(--vio4)" : "var(--t3)",
              }}>{label}</Button>
          ))}
        </div>
      </div>

      {/* ── From metric ── */}
      {mode === "metric" && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <select value={sel} onChange={e => pickMetric(e.target.value)} style={{ ...inputStyle, minWidth: 190 }}>
            <option value="">Choose a metric…</option>
            {metrics.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
          </select>
          {metric && (
            <div style={{ display: "inline-flex", borderRadius: "var(--r2)", border: "1px solid var(--b1)", overflow: "hidden" }}>
              {([["value", "Value", !!metric.value_sql], ["trend", "Trend", !!metric.chart_sql]] as const).map(([s, label, avail]) => (
                <Button key={s} variant="ghost" size="xs" disabled={!avail} onClick={() => setShape(s)} className="aug-fs-xs"
                  style={{
                    padding: "4px 9px", height: "auto", borderRadius: 0, cursor: avail ? "pointer" : "not-allowed",
                    background: shape === s ? "var(--bg-1)" : "transparent",
                    color: !avail ? "var(--t4)" : shape === s ? "var(--vio4)" : "var(--t3)",
                  }}>{label}</Button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Build (free-form metric + dimension) ── */}
      {mode === "build" && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <select value={bTable} onChange={e => pickTable(e.target.value)} style={{ ...inputStyle, minWidth: 170 }}
            title="Table">
            <option value="">{tables.length ? "Choose a table…" : "Loading schema…"}</option>
            {tables.map(t => <option key={t.name} value={t.name}>{t.name.split(".").pop()}</option>)}
          </select>
          {bTable && (
            <>
              <select value={bAgg} onChange={e => setBAgg(e.target.value)} style={{ ...inputStyle, minWidth: 118 }} title="Aggregation">
                {AGGS.map(a => <option key={a.v} value={a.v}>{a.t}</option>)}
              </select>
              {aggDef?.needsMeasure && (
                <select value={bMeasure} onChange={e => setBMeasure(e.target.value)} style={{ ...inputStyle, minWidth: 150 }} title="Measure (numeric column)">
                  <option value="">{numericCols.length ? "Measure…" : "No numeric columns"}</option>
                  {numericCols.map(c => <option key={c.name} value={c.name}>{cleanLabel(c.name)}</option>)}
                </select>
              )}
              <select value={bDim} onChange={e => setBDim(e.target.value)} style={{ ...inputStyle, minWidth: 150 }} title="Break down by (optional)">
                <option value="">By: nothing (single value)</option>
                {dimCols.map(c => <option key={c.name} value={c.name}>By {cleanLabel(c.name)}</option>)}
              </select>
            </>
          )}
        </div>
      )}

      {/* Title — shared. */}
      {sql && (
        <input value={title} onChange={e => setTitle(e.target.value)} placeholder={defaultTitle || "Card title"}
          style={{ ...inputStyle, width: "100%" }} />
      )}

      {/* Live preview — the composed query, run now. */}
      {sql && (
        <div style={{
          padding: "9px 11px", borderRadius: "var(--r2)", background: "var(--bg-1)",
          border: "1px solid var(--b1)", minHeight: 44, display: "flex", alignItems: "center", gap: 10,
        }}>
          {previewing ? (
            <span style={{ fontSize: 11, color: "var(--t3)" }}>Running preview…</span>
          ) : preview?.error ? (
            <span style={{ fontSize: 11, color: "var(--amb4)" }}>Query failed: {preview.error.slice(0, 90)}</span>
          ) : isScalar && vals.length ? (
            <span className="aug-fs-display" style={{ fontWeight: 600, color: "var(--t1)", fontVariantNumeric: "tabular-nums" }}>
              {formatMetricValue(vals[vals.length - 1])}
            </span>
          ) : vals.length ? (
            <>
              <Sparkline values={vals} width={200} height={30} color="var(--vio4)" />
              <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>{vals.length} {bDim && mode === "build" ? "groups" : "points"}</span>
            </>
          ) : (
            <span style={{ fontSize: 11, color: "var(--t4)" }}>No preview</span>
          )}
        </div>
      )}

      {error && <div className="aug-fs-xs" style={{ color: "var(--red4)" }}>{error}</div>}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Button variant="ghost" size="xs" onClick={reset}
          style={{ fontSize: 11, color: "var(--t3)", padding: "3px 9px" }}>Cancel</Button>
        <Button variant="ghost" size="xs" onClick={pin} disabled={!canPin || busy}
          title="Pin to the cockpit — re-run through the trust guards on save"
          style={{
            fontSize: 11, padding: "3px 11px", borderRadius: "var(--r2)", fontWeight: 500,
            background: "var(--vio4)", color: "var(--bg-0)", opacity: (!canPin || busy) ? 0.4 : 1,
          }}>{busy ? "Pinning…" : "Pin to cockpit"}</Button>
      </div>
    </div>
  );
}
