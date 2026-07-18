"use client";

/**
 * NewCardComposer — Door 3 of the briefing cockpit (Slice 4): author a card inline from a
 * grounded metric, without leaving the briefing. Pick one of the connection's north-star
 * metrics, preview it live, and pin it through the SAME guarded pin-query path as the
 * Query-Builder door. The third authoring door — cheapest because the Card primitive,
 * persistence, guarding and render already exist from Doors 1–2.
 */
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Sparkline } from "@/components/brief/Sparkline";
import { formatMetricValue } from "@/lib/format";
import {
  getBusinessProfile, runDirectQuery, pinQueryToDashboard,
  type NorthStarMetric, type DirectQueryResult,
} from "@/lib/api";

const inputStyle = {
  fontSize: 11, background: "var(--bg-1)", border: "1px solid var(--b1)",
  borderRadius: "var(--r2)", color: "var(--t1)", padding: "4px 7px", outline: "none",
} as const;

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
  const [metrics, setMetrics] = useState<NorthStarMetric[]>([]);
  const [sel, setSel] = useState("");
  const [shape, setShape] = useState<"value" | "trend">("value");
  const [title, setTitle] = useState("");
  const [preview, setPreview] = useState<DirectQueryResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load the connection's grounded metrics when the composer opens.
  useEffect(() => {
    if (!open || !connectionId) return;
    getBusinessProfile(connectionId, schema)
      .then(p => setMetrics((p.profile?.north_star_metrics || []).filter(m => m.value_sql || m.chart_sql)))
      .catch(() => setMetrics([]));
  }, [open, connectionId, schema]);

  const metric = useMemo(() => metrics.find(m => m.name === sel), [metrics, sel]);
  const sql = metric ? (shape === "trend" ? (metric.chart_sql || "") : (metric.value_sql || "")) : "";

  // Live preview whenever the chosen metric / shape changes.
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
    setSel(name); setTitle(name);
    const m = metrics.find(x => x.name === name);
    setShape(m?.value_sql ? "value" : "trend");   // prefer a scalar KPI when the metric has one
  };
  const reset = () => { setOpen(false); setSel(""); setTitle(""); setPreview(null); setError(null); };

  const pin = async () => {
    if (!sql.trim() || !metric) return;
    setBusy(true); setError(null);
    try {
      await pinQueryToDashboard(connectionId, sql, title.trim() || metric.name, {
        scope: "connection", scopeRef: connectionId, schema,
        render: { chartType: shape === "trend" ? "line" : "auto" },
      });
      onCreated(); reset();
    } catch (e) {
      setError((e as Error).message || "Could not pin — the query failed the trust guards");
    } finally { setBusy(false); }
  };

  if (!open) {
    return (
      <div style={{ marginBottom: 12 }}>
        <Button variant="ghost" size="xs" onClick={() => setOpen(true)}
          title="Author a new cockpit card from a grounded metric"
          style={{ fontSize: 11, color: "var(--vio4)", padding: "3px 8px", border: "1px dashed color-mix(in srgb, var(--vio4) 40%, var(--b1))", borderRadius: "var(--r2)" }}>
          ＋ New card from a metric
        </Button>
      </div>
    );
  }

  const vals = seriesValues(preview);
  const canPin = !!sql && !previewing && !!preview && !preview.error && vals.length > 0;

  return (
    <div style={{
      marginBottom: 14, padding: "12px 14px", borderRadius: "var(--r3)",
      background: "var(--bg-2)", border: "1px solid var(--b1)",
      display: "flex", flexDirection: "column", gap: 9,
    }}>
      <div className="aug-label">New card from a metric</div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <select value={sel} onChange={e => pickMetric(e.target.value)} style={{ ...inputStyle, minWidth: 190 }}>
          <option value="">Choose a metric…</option>
          {metrics.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
        </select>

        {/* value ⟷ trend, offered only where the metric has that SQL. */}
        {metric && (
          <div style={{ display: "inline-flex", borderRadius: "var(--r2)", border: "1px solid var(--b1)", overflow: "hidden" }}>
            {([["value", "Value", !!metric.value_sql], ["trend", "Trend", !!metric.chart_sql]] as const).map(([s, label, avail]) => (
              <Button key={s} variant="ghost" size="xs" disabled={!avail} onClick={() => setShape(s)}
                style={{
                  fontSize: 10.5, padding: "4px 9px", height: "auto", borderRadius: 0, cursor: avail ? "pointer" : "not-allowed",
                  background: shape === s ? "var(--bg-1)" : "transparent",
                  color: !avail ? "var(--t4)" : shape === s ? "var(--vio4)" : "var(--t3)",
                }}>{label}</Button>
            ))}
          </div>
        )}

        {metric && (
          <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Card title"
            style={{ ...inputStyle, flex: "1 1 160px", minWidth: 140 }} />
        )}
      </div>

      {/* Live preview — the same query, run now. */}
      {metric && (
        <div style={{
          padding: "9px 11px", borderRadius: "var(--r2)", background: "var(--bg-1)",
          border: "1px solid var(--b1)", minHeight: 44, display: "flex", alignItems: "center", gap: 10,
        }}>
          {previewing ? (
            <span style={{ fontSize: 11, color: "var(--t3)" }}>Running preview…</span>
          ) : preview?.error ? (
            <span style={{ fontSize: 11, color: "var(--amb4)" }}>Query failed: {preview.error.slice(0, 90)}</span>
          ) : shape === "value" && vals.length ? (
            <span style={{ fontSize: 21, fontWeight: 600, color: "var(--t1)", fontVariantNumeric: "tabular-nums" }}>
              {formatMetricValue(vals[vals.length - 1])}
            </span>
          ) : vals.length ? (
            <>
              <Sparkline values={vals} width={200} height={30} color="var(--vio4)" />
              <span style={{ fontSize: 10, color: "var(--t4)" }}>{vals.length} points</span>
            </>
          ) : (
            <span style={{ fontSize: 11, color: "var(--t4)" }}>No preview</span>
          )}
        </div>
      )}

      {error && <div style={{ fontSize: 10.5, color: "var(--red4)" }}>{error}</div>}

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
