"use client";

import React, { useRef, useState } from "react";
import { SqlResultTable } from "@/components/AugTable";
import { VegaChart, type VLSpec } from "@/components/VegaChart";
import TableIcon         from "@atlaskit/icon/core/table";
import DownloadIcon      from "@atlaskit/icon/core/download";
import CloseIcon         from "@atlaskit/icon/core/close";
import CopyIcon          from "@atlaskit/icon/core/copy";
import CheckMarkIcon     from "@atlaskit/icon/core/check-mark";
import ChevronDownIcon   from "@atlaskit/icon/core/chevron-down";
import AngleBracketsIcon from "@atlaskit/icon/core/angle-brackets";
import InformationIcon   from "@atlaskit/icon/core/information";
import WarningIcon       from "@atlaskit/icon/core/warning";
import ArrowRightIcon    from "@atlaskit/icon/core/arrow-right";
import { ChatTurn } from "@/lib/useChat";
import type { ADAReport } from "@/lib/types";
import { InvestigationReportView } from "@/components/InvestigationReport";
import { ExplorationReportView } from "@/components/ExplorationReport";

// ── Public types (re-imported by ChatPanel) ───────────────────────────────────
export interface SourcePanelData {
  columns: string[];
  rows: unknown[][];        // already sorted for display
  sql: string | null;
  title: string;
}

// ── Shared helpers ────────────────────────────────────────────────────────────

const DATE_COL = /(_date|_at|_time|created_at|updated_at|timestamp)$/i;
const SHARE_COL = /(share|pct|percent|rate|ratio|proportion)/i;
// Change / delta / period-over-period metric column names.
// When ANY numeric column matches this pattern the question is a COMPARISON question
// (MoM, YoY, delta, growth rate) — heatmap and stacked-bar are the wrong charts.
// Also catches lag/prev/prior columns — their presence signals a POP query even when
// no explicit delta column was computed.
const CHANGE_METRIC_COL = /(change|delta|growth|mom|yoy|wow|qoq|pct_change|percent_change|_chg$|_diff$|vs_prev|^prev_|_prev$|^prior_|_prior$|^lag_|_lag$)/i;
const ORDINAL_COL = /(year|month|day|week|rank|_id$|^id$)/i;

function isNumeric(v: unknown): boolean {
  return v !== null && v !== "" && !isNaN(Number(v));
}

/** Scan the first up to 20 rows to find a non-null value for column colIdx.
 *  Falls back to rows[0]?.[colIdx] (which may be null) if all sampled rows are null.
 *  This prevents NULL-heavy leading rows (e.g. first month of MoM lag queries) from
 *  incorrectly classifying numeric columns as categorical. */
function firstNonNull(rows: unknown[][], colIdx: number): unknown {
  // Scan the full row set — a 20-row cap breaks LAG/LEAD queries where the
  // first N rows (one per category for the first period) are all NULL because
  // there is no previous period to compare. E.g. 27 states ordered by month
  // means the first 27 rows all have null mom_change_pct.
  for (let i = 0; i < rows.length; i++) {
    const v = (rows[i] as unknown[])[colIdx];
    if (v !== null && v !== undefined && v !== "") return v;
  }
  return rows[0]?.[colIdx as number];
}

// "2024-01-01 00:00:00" or "2024-01-01T00:00:00Z" → "Jan 2024"
// Returns the original string unchanged if it doesn't look like a timestamp
function normDateStr(v: string): string {
  // DuckDB returns "2024-01-01 00:00:00" — normalize space separator to T for Date parsing
  return v.replace(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})/, "$1T$2");
}

function fmtTimestampLabel(v: string): string {
  if (!/^\d{4}-\d{2}-\d{2}/.test(v)) return v;
  try {
    const d = new Date(normDateStr(v));
    if (isNaN(d.getTime())) return v;
    return d.toLocaleString("default", { month: "short", year: "numeric" });
  } catch {
    return v;
  }
}

// ── Human-readable label: "revenue_usd" → "Revenue USD", "payment_method" → "Payment Method" ──
const ABBREVS = /^(usd|id|uk|us|eu|vat|sku|url|api|crm|gmv|mrr|arr|ltv|cac|ctr|aov|roi|pnl|gp|kpi)$/i;
function cleanLabel(s: string): string {
  return s
    .replace(/_/g, " ")
    .replace(/\b\w+/g, w => ABBREVS.test(w) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
}

// ── Smart source-panel title derived from column semantics ────────────────────
const DATE_VALUE_RE = /^\d{4}-\d{2}-\d{2}/;
function inferSourceTitle(columns: string[], rows: unknown[][]): string {
  if (!columns.length) return "Query result";

  const dateColIdx = columns.findIndex((c, i) => {
    const v = rows[0]?.[i];
    return DATE_COL.test(c) || (typeof v === "string" && DATE_VALUE_RE.test(v as string));
  });
  const numColNames = columns.filter((c, i) =>  isNumeric(firstNonNull(rows, i)) && !ORDINAL_COL.test(c));
  const catColNames = columns.filter((c, i) => !isNumeric(firstNonNull(rows, i)) && i !== dateColIdx && !DATE_COL.test(c));

  const measure = numColNames[0] ? cleanLabel(numColNames[0]) : "";
  const dim     = catColNames[0] ? cleanLabel(catColNames[0]) : "";
  const hasDate = dateColIdx >= 0;

  if (measure && dim && hasDate) return `Monthly ${measure} by ${dim}`;
  if (measure && dim)            return `${measure} by ${dim}`;
  if (measure && hasDate)        return `Monthly ${measure}`;
  if (measure)                   return measure;
  if (dim)                       return dim;
  return "Query result";
}

// ── Sort rows: date dims first (ISO-sort = chronological), then text dims A→Z ─
function sortRowsForDisplay(columns: string[], rows: unknown[][]): unknown[][] {
  const dimIdxs = columns
    .map((_, i) => i)
    .filter(i => !isNumeric(firstNonNull(rows, i)));
  if (!dimIdxs.length) return rows;

  return [...rows].sort((a, b) => {
    for (const i of dimIdxs) {
      const va = String((a as unknown[])[i] ?? "");
      const vb = String((b as unknown[])[i] ?? "");
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      if (cmp !== 0) return cmp;
    }
    return 0;
  });
}

// ── CSV download helper ───────────────────────────────────────────────────────
function downloadCsv(columns: string[], rows: unknown[][], title: string) {
  const esc = (v: unknown) => {
    const s = String(v ?? "");
    return /[,"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = [
    columns.map(esc).join(","),
    ...rows.map(r => (r as unknown[]).map(esc).join(",")),
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement("a"), {
    href: url,
    download: `${title.replace(/[^a-z0-9]+/gi, "_").toLowerCase()}.csv`,
  });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function fmt(col: string, val: unknown): string {
  if (val === null || val === "NULL") return "—";
  const s = String(val);
  // Format ISO timestamps as readable month labels (e.g. "2025-05-01 00:00:00" → "May 2025")
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return fmtTimestampLabel(s);
  if (ORDINAL_COL.test(col)) return s;
  const n = Number(val);
  if (!isNaN(n)) {
    if (SHARE_COL.test(col)) {
      // Ratio stored as decimal fraction (e.g. 0.118 = 11.8%) — multiply ×100
      if (Math.abs(n) <= 1)          return `${(n * 100).toFixed(2)}%`;
      // Already a percentage (e.g. 11.8 or -60.89) — display as-is with % suffix
      return `${n.toFixed(2)}%`;
    }
    if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    if (!Number.isInteger(n)) return n.toFixed(2);
    return n.toLocaleString();
  }
  return s;
}

// ── KPI cards (single-row numeric result) ────────────────────────────────────
// KPI values — inline typography, no box, no border.
// Single metric: just the value (headline already names it).
// Multi-metric: compact label + value pairs side by side.
function KPICards({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  const row = rows[0];
  const numericCols = columns.filter(
    (c, i) => isNumeric(row[i]) && !ORDINAL_COL.test(c)
  );
  if (!numericCols.length) return null;
  const isSingle = numericCols.length === 1;
  return (
    <div className={`flex flex-wrap mt-1.5 ${isSingle ? "" : "gap-6"}`}>
      {numericCols.map((col) => {
        const idx = columns.indexOf(col);
        return (
          <div key={col}>
            {!isSingle && (
              <p className="text-[12px] text-zinc-500 mb-0.5">
                {cleanLabel(col)}
              </p>
            )}
            <p className="text-[12px] font-bold tabular-nums text-zinc-100">
              {fmt(col, row[idx])}
            </p>
          </div>
        );
      })}
    </div>
  );
}

// ── Mini table — Ant Design via AugTable ─────────────────────────────────────
function MiniTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  return (
    <div className="mt-2 rounded-lg overflow-hidden">
      <SqlResultTable columns={columns} rows={rows} maxHeight={320} />
    </div>
  );
}

// ── Inline chart (Vega-Lite) ─────────────────────────────────────────────────
// Columns whose values are already human-formatted time labels (Month - Year, Q1 2024, etc.)
// → preserve SQL ordering, don't parse as dates, don't re-sort
const TIME_LABEL_COL = /(month|quarter|week|half|period)/i;

function InlineChart({
  columns,
  rows,
  chartType = "auto",
  title = "chart",
}: {
  columns: string[];
  rows: unknown[][];
  chartType?: string | null;
  title?: string;
}) {
  const outerRef  = useRef<HTMLDivElement>(null);
  const chartRef  = useRef<HTMLDivElement>(null);
  // userH = null means "use computed default height". Set by drag handle.
  const [userH, setUserH] = useState<number | null>(null);
  // expanded = false caps chart height to CLIP_H; true shows full chart
  const [expanded, setExpanded] = useState(false);

  function startDrag(e: React.MouseEvent) {
    e.preventDefault();
    const startY = e.clientY;
    const startH = outerRef.current?.clientHeight ?? 300;

    function onMove(ev: MouseEvent) {
      const newH = Math.max(80, startH + (ev.clientY - startY));
      if (outerRef.current) outerRef.current.style.minHeight = `${newH}px`;
    }
    function onUp(ev: MouseEvent) {
      // clear the inline style; re-render will set chart height via prop
      if (outerRef.current) outerRef.current.style.minHeight = "";
      setUserH(Math.max(80, startH + (ev.clientY - startY)));
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup",   onUp);
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup",   onUp);
  }

  function handleDownloadPng() {
    const svg = chartRef.current?.querySelector("svg");
    if (!svg) return;
    const w = svg.clientWidth  || 640;
    const h = svg.clientHeight || 320;
    const clone = svg.cloneNode(true) as SVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width",  String(w));
    clone.setAttribute("height", String(h));
    const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    bg.setAttribute("width",  String(w));
    bg.setAttribute("height", String(h));
    bg.setAttribute("fill", "#131c27");
    clone.insertBefore(bg, clone.firstChild);
    const svgStr = new XMLSerializer().serializeToString(clone);
    const url    = URL.createObjectURL(new Blob([svgStr], { type: "image/svg+xml;charset=utf-8" }));
    const img    = new Image();
    img.onload = () => {
      const scale  = 2;
      const canvas = Object.assign(document.createElement("canvas"), { width: w * scale, height: h * scale });
      const ctx    = canvas.getContext("2d")!;
      ctx.scale(scale, scale);
      ctx.fillStyle = "#131c27";
      ctx.fillRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0, w, h);
      URL.revokeObjectURL(url);
      canvas.toBlob(blob => {
        if (!blob) return;
        const pngUrl = URL.createObjectURL(blob);
        const fname  = title.replace(/[^a-z0-9]+/gi, "_").toLowerCase() + ".png";
        const a = Object.assign(document.createElement("a"), { href: pngUrl, download: fname });
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        URL.revokeObjectURL(pngUrl);
      }, "image/png");
    };
    img.src = url;
  }

  if (!rows.length || !columns.length) return null;

  // ── Column classification ──────────────────────────────────────────────────
  const data: Record<string, unknown>[] = rows.map(r =>
    Object.fromEntries(columns.map((c, i) => [c, (r as unknown[])[i]])),
  );

  const DATE_VALUE_RE = /^\d{4}-\d{2}-\d{2}/;
  const looksLikeDate = (colIdx: number) => {
    const v = firstNonNull(rows, colIdx);
    return typeof v === "string" && DATE_VALUE_RE.test(v);
  };

  const dateCol =
    columns.find(c => DATE_COL.test(c)) ||
    columns.find((c, i) => !isNumeric(firstNonNull(rows, i)) && looksLikeDate(i));

  const catCols = columns.filter(
    (c, i) => c !== dateCol && !DATE_COL.test(c) && !isNumeric(firstNonNull(rows, i)),
  );
  const PREFER_COL = /(pct|percent|share|rate|ratio|proportion)/i;
  const numericCols = columns.filter((c, i) => !DATE_COL.test(c) && isNumeric(firstNonNull(rows, i)));
  // True when ANY numeric column is a change/delta/growth metric.
  // These are COMPARISON questions — heatmap/stacked-bar are inappropriate.
  const _isChangeMetric = numericCols.some(c => CHANGE_METRIC_COL.test(c));
  // For change metrics, prefer the change column as the primary numeric
  const CHANGE_PREFER_COL = /(change|delta|growth|pct_change|percent_change|_chg$|_diff$)/i;
  const numCol  = _isChangeMetric
    ? (numericCols.find(c => CHANGE_PREFER_COL.test(c)) ?? numericCols.find(c => PREFER_COL.test(c)) ?? numericCols[0])
    : (numericCols.find(c => PREFER_COL.test(c)) ?? numericCols[0]);
  const catCol  = catCols[0];
  const catCol2 = catCols[1];
  const hint    = (chartType ?? "auto").toLowerCase();
  const isTimeLabel = catCol ? TIME_LABEL_COL.test(catCol) : false;

  if (!numCol) return null;

  // ── Axis format ────────────────────────────────────────────────────────────
  const isPctCol = SHARE_COL.test(numCol);
  const sampleVals = data.slice(0, 10).map(d => Number(d[numCol])).filter(v => !isNaN(v));
  const maxSampleVal = Math.max(...sampleVals.map(Math.abs), 0);
  const isPctFraction = isPctCol && maxSampleVal <= 1;
  // Axis tick format: SI adaptive (removes trailing zeros)
  const yFmt   = isPctFraction ? ".2%" : "~s";
  // Data-label format: 3 significant figures SI (e.g. "2.14M", "891k" not "2.14438M")
  // Percentages always 2 decimal places
  const lblFmt = isPctFraction ? ".2%" : ".3s";

  // ── Build spec ─────────────────────────────────────────────────────────────
  const xTitle = catCol  ? cleanLabel(catCol)  : (dateCol ? cleanLabel(dateCol) : "");
  const yTitle = numCol  ? cleanLabel(numCol)  : "";

  let spec: VLSpec | null = null;
  let vegaData: Record<string, unknown>[] = data;
  let defaultH = 220;

  // ── PIE / DONUT ─────────────────────────────────────────────────────────────
  if (hint === "pie" && catCol) {
    const agg = new Map<string, number>();
    data.forEach(d => {
      const k = String(d[catCol]);
      agg.set(k, (agg.get(k) ?? 0) + Number(d[numCol]));
    });
    vegaData = [...agg.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([label, value]) => ({ label, value }));

    spec = {
      mark: { type: "arc", innerRadius: 44, outerRadius: 100 },
      encoding: {
        theta: { field: "value", type: "quantitative" },
        color: { field: "label", type: "nominal", legend: { title: cleanLabel(catCol), orient: "right" } },
        tooltip: [
          { field: "label", type: "nominal",     title: cleanLabel(catCol) },
          { field: "value", type: "quantitative", format: lblFmt, title: yTitle },
        ],
      },
    };
    defaultH = 240;
  }

  // ── HEATMAP ───────────────────────────────────────────────────────────────────
  // Only rendered when the LLM explicitly returns chart_type = "heatmap".
  // Auto-heatmap is intentionally removed — temporal data defaults to multi-line
  // so users always see the trend. Change/delta metrics are additionally blocked
  // even on explicit hint (period-over-period is comparison, not distribution).
  const _stackUnique = catCol ? new Set(data.map(d => d[catCol])).size : 0;

  if (hint === "heatmap" && !_isChangeMetric) {
    const xSrc = dateCol ?? catCol2 ?? "";

    // Build raw key→value map first, then fill the FULL grid so every
    // group × stack cell gets a rect (prevents background bleeding through
    // as "black" gaps where a state simply had no orders in a given period).
    const rawRows = data.map(d => ({
      group: xSrc === dateCol ? fmtTimestampLabel(String(d[xSrc])) : String(d[xSrc]),
      stack: String(d[catCol!]),
      val:   Number(d[numCol]),
    }));
    const heatGroupOrder = [...new Set(rawRows.map(d => d.group))];
    const heatStacks     = [...new Set(rawRows.map(d => d.stack))];
    const cellMap        = new Map(rawRows.map(d => [`${d.group}__${d.stack}`, d.val]));

    // Full grid — missing cells get val: null (rendered as a neutral fill)
    vegaData = heatGroupOrder.flatMap(g =>
      heatStacks.map(s => ({
        group: g,
        stack: s,
        val:   cellMap.get(`${g}__${s}`) ?? null,
      })),
    );

    // Compute non-null max for scale calibration
    const heatVals    = rawRows.map(d => d.val).filter(v => isFinite(v) && v > 0);
    const heatMax     = heatVals.length ? Math.max(...heatVals) : 1;

    // Use sqrt scale so dominant outliers (e.g. SP with 10× others' revenue)
    // don't compress everything else to the same near-white shade.
    const heatColorScale = isPctCol
      ? { scheme: "redblue", domainMid: 0 }
      : { scheme: "blues", type: "sqrt", domainMin: 0, domainMax: heatMax, null: "#0e1520" };

    spec = {
      mark: { type: "rect", stroke: "#0e1520", strokeWidth: 0.5 },
      encoding: {
        x: {
          field: "group", type: "ordinal", sort: heatGroupOrder,
          axis: { labelAngle: -40, title: cleanLabel(xSrc), labelLimit: 80 },
        },
        y: {
          field: "stack", type: "ordinal",
          sort: { field: "val", op: "sum", order: "descending" },
          axis: { title: catCol ? cleanLabel(catCol) : "", labelLimit: 100 },
        },
        color: {
          field: "val", type: "quantitative",
          scale: heatColorScale,
          legend: { title: yTitle, orient: "right", format: yFmt },
        },
        tooltip: [
          { field: "group", type: "nominal",      title: cleanLabel(xSrc) },
          { field: "stack", type: "nominal",      title: catCol ? cleanLabel(catCol) : "" },
          { field: "val",   type: "quantitative", format: lblFmt, title: yTitle },
        ],
      },
    };
    defaultH = Math.max(220, Math.min(_stackUnique * 18 + 80, 600));
  }

  // ── MULTI-LINE (one line per category over time) ──────────────────────────────
  // Triggered explicitly with hint="multi_line"
  else if (hint === "multi_line" && catCol && dateCol) {
    // Drop rows where the value is null/NaN — LAG/LEAD queries produce null for the
    // first partition row; Number(null)=0 would create a false zero spike.
    vegaData = data
      .filter(d => { const v = d[numCol]; return v !== null && v !== undefined && v !== "" && !isNaN(Number(v)); })
      .map(d => ({
        date:   normDateStr(String(d[dateCol])),
        series: String(d[catCol]),
        val:    Number(d[numCol]),
      }));

    // For change metrics stored as large-scale percentages (e.g. 15.2 meaning 15.2%),
    // use a plain numeric format and append "(%)". For 0-1 fractions, use ".2%".
    const mlYFmt   = _isChangeMetric && !isPctFraction ? ".0f" : yFmt;
    const mlYTitle = _isChangeMetric && !isPctFraction && isPctCol ? `${yTitle} (%)` : yTitle;
    const mlSeriesCount = new Set(vegaData.map(d => d.series as string)).size;

    // symbolType "stroke" renders a short line segment that matches the chart mark.
    // symbolSize 200 gives a visible ~14 px line; symbolStrokeWidth matches chart line weight.
    const mlLegend = mlSeriesCount > 12
      ? { orient: "right", direction: "vertical", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          labelFontSize: 10, title: cleanLabel(catCol), titleLimit: 160 }
      : { direction: "horizontal", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          title: cleanLabel(catCol), titleLimit: 160 };
    const mlStrokeW = mlSeriesCount > 20 ? 0.9 : mlSeriesCount > 10 ? 1.1 : 1.5;

    const mlXEnc = { field: "date", type: "temporal", axis: { tickCount: 12, format: "%b %y", labelAngle: -40, title: cleanLabel(dateCol) } };
    const mlYEnc = { field: "val",  type: "quantitative", axis: { format: mlYFmt, grid: true, title: mlYTitle } };
    const mlColorEnc = { field: "series", type: "nominal", legend: mlLegend };
    const mlTooltip = [
      { field: "date",   type: "temporal",     title: cleanLabel(dateCol), format: "%b %Y" },
      { field: "series", type: "nominal",      title: cleanLabel(catCol) },
      { field: "val",    type: "quantitative", format: mlYFmt, title: mlYTitle },
    ];
    spec = {
      layer: [
        {
          mark: { type: "line", strokeWidth: mlStrokeW },
          encoding: { x: mlXEnc, y: mlYEnc, color: mlColorEnc },
        },
        {
          // Invisible hover points — nearest: true snaps to closest x date so the
          // user doesn't have to click exactly on the line.
          mark: { type: "point", filled: true, size: 60 },
          params: [{ name: "mlHover", select: { type: "point", fields: ["date"], nearest: true, on: "pointerover", clear: "pointerout" } }],
          encoding: {
            x: mlXEnc,
            y: mlYEnc,
            color: mlColorEnc,
            opacity: { condition: { param: "mlHover", empty: false, value: 1 }, value: 0 },
            tooltip: mlTooltip,
          },
        },
      ],
    };
    defaultH = mlSeriesCount > 15 ? 360 : 300;
  }

  // ── TREEMAP ───────────────────────────────────────────────────────────────────
  // Aggregates catCol → shows proportional area tiles
  else if (hint === "treemap" && catCol) {
    const tmAgg = new Map<string, number>();
    data.forEach(d => {
      const k = String(d[catCol]);
      tmAgg.set(k, (tmAgg.get(k) ?? 0) + Number(d[numCol]));
    });
    vegaData = [...tmAgg.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 40)
      .map(([name, value]) => ({ id: name, parent: "root", value, name }));
    // Add root node
    vegaData.unshift({ id: "root", parent: "", value: 0, name: "root" } as Record<string, unknown>);

    // Vega 6 treemap spec (not Vega-Lite)
    spec = {
      $schema: "https://vega.github.io/schema/vega/v6.json",
      background: "transparent",
      padding: 4,
      signals: [{ name: "width", value: 0 }, { name: "height", value: 0 }],
      data: [
        {
          name: "tree",
          values: vegaData,
          transform: [
            { type: "stratify", key: "id", parentKey: "parent" },
            {
              type: "treemap",
              field: "value",
              sort: { field: "value", order: "descending" },
              round: true,
              method: "squarify",
              ratio: 1.618,
              size: [{ signal: "width" }, { signal: "height" }],
            },
          ],
        },
        {
          name: "leaves",
          source: "tree",
          transform: [{ type: "filter", expr: "datum.parent !== ''" }],
        },
      ],
      marks: [
        {
          type: "rect",
          from: { data: "leaves" },
          encode: {
            update: {
              x: { field: "x0" },
              x2: { field: "x1" },
              y: { field: "y0" },
              y2: { field: "y1" },
              fill: { scale: "color", field: "name" },
              stroke: { value: "#131c27" },
              strokeWidth: { value: 1.5 },
              opacity: { value: 0.88 },
              tooltip: { signal: `{"${cleanLabel(catCol)}": datum.name, "${yTitle}": format(datum.value, "${lblFmt}")}` },
            },
          },
        },
        {
          type: "text",
          from: { data: "leaves" },
          encode: {
            update: {
              x: { signal: "(datum.x0 + datum.x1) / 2" },
              y: { signal: "(datum.y0 + datum.y1) / 2" },
              text: { signal: "(datum.x1 - datum.x0) > 50 ? datum.name : ''" },
              align: { value: "center" },
              baseline: { value: "middle" },
              fill: { value: "rgba(255,255,255,0.80)" },
              fontSize: { signal: "min(12, (datum.x1 - datum.x0) / 6)" },
              fontWeight: { value: "500" },
            },
          },
        },
      ],
      scales: [
        {
          name: "color",
          type: "ordinal",
          range: { scheme: "tableau20" },
          domain: { data: "leaves", field: "name" },
        },
      ],
    };
    defaultH = 340;
  }

  // ── PERIOD-OVER-PERIOD / CHANGE METRIC (auto only) ───────────────────────────
  // When the result contains a change/delta/growth column alongside date + category:
  //   X axis  = period (the date column)
  //   Y axis  = the delta/change metric
  //   Lines   = one per category (state, channel, product, …)
  // Always multi-line regardless of series count.
  else if (hint === "auto" && _isChangeMetric && catCol && dateCol) {
    vegaData = data
      .filter(d => { const v = d[numCol]; return v !== null && v !== undefined && v !== "" && !isNaN(Number(v)); })
      .map(d => ({
        date:   normDateStr(String(d[dateCol])),
        series: String(d[catCol]),
        val:    Number(d[numCol]),
      }));
    const changeYFmt   = isPctFraction ? ".2%" : (isPctCol ? ".0f" : "~s");
    const changeYTitle = isPctFraction ? yTitle : isPctCol ? `${yTitle} (%)` : yTitle;
    const seriesCount  = new Set(vegaData.map(d => d.series as string)).size;

    // With many series, use a right-side legend and thinner lines so colours still
    // scan left-to-right without the legend row eating half the chart height.
    const manyLegend = seriesCount > 12
      ? { orient: "right", direction: "vertical", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          labelFontSize: 10, title: cleanLabel(catCol), titleLimit: 160 }
      : { direction: "horizontal", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          title: cleanLabel(catCol), titleLimit: 160 };
    const strokeW = seriesCount > 20 ? 0.9 : seriesCount > 10 ? 1.1 : 1.5;

    const chgXEnc = { field: "date", type: "temporal", axis: { tickCount: 12, format: "%b %y", labelAngle: -40, title: cleanLabel(dateCol) } };
    const chgYEnc = { field: "val",  type: "quantitative", axis: { format: changeYFmt, grid: true, title: changeYTitle } };
    const chgColorEnc = { field: "series", type: "nominal", legend: manyLegend };
    const chgTooltip = [
      { field: "date",   type: "temporal",     title: cleanLabel(dateCol), format: "%b %Y" },
      { field: "series", type: "nominal",      title: cleanLabel(catCol) },
      { field: "val",    type: "quantitative", format: changeYFmt, title: changeYTitle },
    ];
    spec = {
      layer: [
        {
          mark: { type: "line", strokeWidth: strokeW },
          encoding: { x: chgXEnc, y: chgYEnc, color: chgColorEnc },
        },
        {
          mark: { type: "point", filled: true, size: 60 },
          params: [{ name: "chgHover", select: { type: "point", fields: ["date"], nearest: true, on: "pointerover", clear: "pointerout" } }],
          encoding: {
            x: chgXEnc,
            y: chgYEnc,
            color: chgColorEnc,
            opacity: { condition: { param: "chgHover", empty: false, value: 1 }, value: 0 },
            tooltip: chgTooltip,
          },
        },
      ],
    };
    defaultH = seriesCount > 15 ? 360 : 300;
  }

  // ── STACKED BAR (temporal or categorical) ────────────────────────────────────
  // Auto-trigger only when the category has ≤ 6 unique values — beyond that,
  // stacked bars become unreadable colour-salads. High-cardinality date+category
  // falls through to the multi-line auto path below.
  else if (hint === "stacked_bar" || (hint === "auto" && catCol && (catCol2 || dateCol) && !_isChangeMetric && _stackUnique <= 6)) {
    const isTemporalStack = !!(catCol && dateCol);
    vegaData = isTemporalStack && dateCol
      ? data.map(d => ({
          group: fmtTimestampLabel(String(d[dateCol])),
          stack: String(d[catCol]),
          val:   Number(d[numCol]),
        }))
      : data.map(d => ({
          group: String(d[catCol]),
          stack: catCol2 ? String(d[catCol2]) : "",
          val:   Number(d[numCol]),
        }));

    const groupTotals = new Map<string, number>();
    vegaData.forEach(d => groupTotals.set(
      d.group as string,
      (groupTotals.get(d.group as string) ?? 0) + (d.val as number),
    ));
    const groupOrder = (isTemporalStack || isTimeLabel)
      ? [...new Set(vegaData.map(d => d.group as string))]
      : [...groupTotals.entries()].sort((a, b) => b[1] - a[1]).map(([g]) => g);

    const stackLegendTitle = isTemporalStack
      ? cleanLabel(catCol)
      : (catCol2 ? cleanLabel(catCol2) : null);

    spec = {
      mark: { type: "bar" },
      encoding: {
        x: {
          field: "group", type: "ordinal", sort: groupOrder,
          axis: {
            labelAngle: groupOrder.length > 8 ? -40 : -20,
            title: isTemporalStack ? cleanLabel(dateCol ?? "") : cleanLabel(catCol),
          },
        },
        y: {
          field: "val", type: "quantitative", stack: "zero",
          axis: { format: yFmt, grid: true, title: yTitle },
        },
        color: {
          field: "stack", type: "nominal",
          legend: { title: stackLegendTitle },
        },
        tooltip: [
          { field: "group", type: "nominal",     title: isTemporalStack ? cleanLabel(dateCol ?? "") : cleanLabel(catCol) },
          { field: "stack", type: "nominal",     title: stackLegendTitle ?? undefined },
          { field: "val",   type: "quantitative", format: lblFmt, title: yTitle },
        ],
      },
    };
    defaultH = 280;
  }

  // ── TEMPORAL MULTI-LINE AUTO (date + category, many series, absolute metric) ──
  // Fires when stacked-bar auto was skipped (_stackUnique > 6) and no other branch
  // matched. Shows one line per category value over time — always better than a
  // heatmap for surfacing trends.  Uses P90 clipping + right legend when > 12 series.
  else if (hint === "auto" && dateCol && catCol && !_isChangeMetric) {
    vegaData = data
      .filter(d => { const v = d[numCol]; return v !== null && v !== undefined && v !== "" && !isNaN(Number(v)); })
      .map(d => ({
        date:   normDateStr(String(d[dateCol])),
        series: String(d[catCol]),
        val:    Number(d[numCol]),
      }));
    const tmSeriesCount = new Set(vegaData.map(d => d.series as string)).size;

    const tmLegend = tmSeriesCount > 12
      ? { orient: "right", direction: "vertical", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          labelFontSize: 10, title: cleanLabel(catCol), titleLimit: 160 }
      : { direction: "horizontal", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          title: cleanLabel(catCol), titleLimit: 160 };
    const tmStrokeW = tmSeriesCount > 20 ? 0.9 : tmSeriesCount > 10 ? 1.1 : 1.5;

    const tmXEnc = { field: "date", type: "temporal", axis: { tickCount: 12, format: "%b %y", labelAngle: -40, title: cleanLabel(dateCol) } };
    const tmYEnc = { field: "val",  type: "quantitative", axis: { format: yFmt, grid: true, title: yTitle } };
    const tmColorEnc = { field: "series", type: "nominal", legend: tmLegend };
    const tmTooltip = [
      { field: "date",   type: "temporal",     title: cleanLabel(dateCol), format: "%b %Y" },
      { field: "series", type: "nominal",      title: cleanLabel(catCol) },
      { field: "val",    type: "quantitative", format: lblFmt, title: yTitle },
    ];
    spec = {
      layer: [
        {
          mark: { type: "line", strokeWidth: tmStrokeW },
          encoding: { x: tmXEnc, y: tmYEnc, color: tmColorEnc },
        },
        {
          mark: { type: "point", filled: true, size: 60 },
          params: [{ name: "tmHover", select: { type: "point", fields: ["date"], nearest: true, on: "pointerover", clear: "pointerout" } }],
          encoding: {
            x: tmXEnc,
            y: tmYEnc,
            color: tmColorEnc,
            opacity: { condition: { param: "tmHover", empty: false, value: 1 }, value: 0 },
            tooltip: tmTooltip,
          },
        },
      ],
    };
    defaultH = tmSeriesCount > 15 ? 360 : 300;
  }

  // ── DATE BAR (explicit bar on date + measure, no category) ──────────────────
  else if (dateCol && !catCol && (hint === "bar" || hint === "bar_horizontal")) {
    vegaData = data.map(d => ({
      date: normDateStr(String(d[dateCol])),
      val:  Number(d[numCol]),
    }));
    spec = {
      padding: { top: 24 },   // room for above-bar labels
      layer: [
        {
          mark: { type: "bar", color: "#818cf8", opacity: 0.85 },
        },
        {
          // Value label above each bar, inside top padding
          mark: { type: "text", dy: -6, fontSize: 11, color: "#9AA0A8" },
          encoding: { text: { field: "val", type: "quantitative", format: lblFmt } },
        },
      ],
      encoding: {
        x: {
          field: "date", type: "temporal", timeUnit: "yearmonth",
          axis: { format: "%b %y", labelAngle: -30, title: cleanLabel(dateCol) },
        },
        y: { field: "val", type: "quantitative", axis: { format: yFmt, grid: true, title: yTitle } },
        tooltip: [
          { field: "date", type: "temporal", timeUnit: "yearmonth", title: cleanLabel(dateCol) },
          { field: "val",  type: "quantitative", format: lblFmt, title: yTitle },
        ],
      },
    };
    defaultH = 220;
  }

  // ── LINE / AREA (timeseries) ─────────────────────────────────────────────────
  else if (dateCol && !catCol && (hint === "line" || hint === "area" || hint === "auto")) {
    vegaData = data.map(d => ({
      ...d,
      [dateCol]: normDateStr(String(d[dateCol])),
      [numCol]:  Number(d[numCol]),
    }));
    const color = "#10b981";
    spec = {
      layer: [
        { mark: { type: "area", color, opacity: 0.08 } },
        { mark: { type: "line", color, strokeWidth: 1.5 } },
        {
          mark: { type: "point", color, size: 30, filled: true, opacity: 0.9 },
          encoding: {
            tooltip: [
              { field: dateCol, type: "temporal",     title: cleanLabel(dateCol) },
              { field: numCol,  type: "quantitative", format: lblFmt, title: yTitle },
            ],
          },
        },
      ],
      encoding: {
        x: {
          field: dateCol, type: "temporal",
          axis: { format: "%b %y", labelAngle: -30, title: cleanLabel(dateCol) },
        },
        y: {
          field: numCol, type: "quantitative",
          axis: { format: yFmt, grid: true, title: yTitle },
        },
      },
      resolve: { scale: { y: "shared" } },
    };
    defaultH = 200;
  }

  // ── VERTICAL BAR ─────────────────────────────────────────────────────────────
  else if (catCol && hint === "bar_vertical") {
    const agg = new Map<string, number>();
    data.forEach(d => {
      const k = String(d[catCol]);
      agg.set(k, (agg.get(k) ?? 0) + Number(d[numCol]));
    });
    vegaData = (isTimeLabel
      ? [...agg.entries()]
      : [...agg.entries()].sort((a, b) => b[1] - a[1])
    ).map(([cat, val]) => ({ cat, val }));

    spec = {
      padding: { top: 24 },   // room for above-bar labels
      layer: [
        {
          mark: { type: "bar", color: "#818cf8", opacity: 0.85, cornerRadiusEnd: 2 },
        },
        {
          mark: { type: "text", dy: -6, fontSize: 11, color: "#9AA0A8" },
          encoding: { text: { field: "val", type: "quantitative", format: lblFmt } },
        },
      ],
      encoding: {
        x: {
          field: "cat", type: "ordinal",
          sort: isTimeLabel ? null : { field: "val", order: "descending" },
          axis: { labelAngle: vegaData.length > 10 ? -40 : -20, title: xTitle },
        },
        y: {
          field: "val", type: "quantitative",
          axis: { format: yFmt, grid: true, title: yTitle },
        },
        tooltip: [
          { field: "cat", type: "nominal",     title: xTitle },
          { field: "val", type: "quantitative", format: lblFmt, title: yTitle },
        ],
      },
    };
    defaultH = 260;
  }

  // ── SCATTER ──────────────────────────────────────────────────────────────────
  else if (hint === "scatter" && numericCols.length >= 2) {
    const xNum = numericCols[0];
    const yNum = numericCols[1];
    const colorField = catCol || undefined;
    spec = {
      mark: { type: "point", filled: true, size: 40, opacity: 0.7 },
      encoding: {
        x: {
          field: xNum, type: "quantitative",
          axis: { format: "~s", grid: true, title: cleanLabel(xNum) },
        },
        y: {
          field: yNum, type: "quantitative",
          axis: { format: "~s", grid: true, title: cleanLabel(yNum) },
        },
        ...(colorField ? { color: { field: colorField, type: "nominal", legend: { title: cleanLabel(colorField) } } } : {}),
        tooltip: [
          { field: xNum, type: "quantitative", format: ",.2~f", title: cleanLabel(xNum) },
          { field: yNum, type: "quantitative", format: ",.2~f", title: cleanLabel(yNum) },
          ...(colorField ? [{ field: colorField, type: "nominal", title: cleanLabel(colorField) }] : []),
        ],
      },
    };
    defaultH = 300;
  }

  // ── HORIZONTAL BAR — default for all categorical data ────────────────────────
  else if (catCol) {
    const agg = new Map<string, number>();
    data.forEach(d => {
      const k = String(d[catCol]);
      agg.set(k, (agg.get(k) ?? 0) + Number(d[numCol]));
    });

    if (_isChangeMetric) {
      // ── CHANGE METRIC BAR ──────────────────────────────────────────────────
      // Sort by absolute magnitude so biggest movers (positive OR negative) appear first.
      // Use a symmetric x domain so negative bars extend to the left.
      // Diverging colours: green = growth, red = decline.
      vegaData = [...agg.entries()]
        .map(([cat, val]) => ({ cat, val }))
        .sort((a, b) => Math.abs(b.val as number) - Math.abs(a.val as number))
        .slice(0, 20);

      const maxAbsVal = Math.max(...vegaData.map(d => Math.abs(d.val as number)), 1);
      // Format: if values look like stored-as-100x percentages (e.g. 15.2 for 15.2%)
      // keep ~g format with an axis title suffix; if they're 0-1 fractions use .2%
      const changeFmt = isPctFraction ? "+.2%" : "+.1f";
      const changeAxisTitle = isPctFraction ? yTitle : `${yTitle}${isPctCol ? " (%)" : ""}`;

      spec = {
        mark: { type: "bar", opacity: 0.85, cornerRadiusEnd: 2 },
        encoding: {
          x: {
            field: "val", type: "quantitative",
            scale: { domain: [-maxAbsVal * 1.18, maxAbsVal * 1.18] },
            axis: { format: changeFmt, grid: true, title: changeAxisTitle },
          },
          y: {
            field: "cat", type: "ordinal",
            sort: { field: "val", op: "sum", order: "descending" },
            axis: { labelLimit: 160, title: cleanLabel(catCol) },
          },
          color: {
            condition: { test: "datum.val >= 0", value: "#2EC87B" },
            value: "#E64848",
          },
          tooltip: [
            { field: "cat", type: "nominal",      title: cleanLabel(catCol) },
            { field: "val", type: "quantitative",  format: changeFmt, title: changeAxisTitle },
          ],
        },
      };
      defaultH = Math.max(160, vegaData.length * 28 + 60);

    } else {
      // ── STANDARD BAR ──────────────────────────────────────────────────────
      vegaData = (isTimeLabel
        ? [...agg.entries()]
        : [...agg.entries()].sort((a, b) => b[1] - a[1])
      ).map(([cat, val]) => ({ cat, val }));

      // cap at 15 bars
      if (vegaData.length > 15) vegaData = vegaData.slice(0, 15);

      // Extend x domain 14% past the max so the label of the widest bar has room.
      const maxBarVal = Math.max(...vegaData.map(d => d.val as number), 1);

      spec = {
        layer: [
          {
            mark: { type: "bar", color: "#818cf8", opacity: 0.85, cornerRadiusEnd: 2 },
          },
          // Single text layer — always positioned just past the bar's right edge.
          {
            mark: { type: "text", align: "left", dx: 5, fontSize: 11, color: "#9AA0A8" },
            encoding: { text: { field: "val", type: "quantitative", format: lblFmt } },
          },
        ],
        encoding: {
          y: {
            field: "cat", type: "ordinal",
            sort: isTimeLabel ? null : { field: "val", order: "descending" },
            axis: { labelLimit: 160, title: cleanLabel(catCol) },
          },
          x: {
            field: "val", type: "quantitative",
            scale: { domainMax: maxBarVal * 1.14 },
            axis: { format: yFmt, grid: true, title: yTitle },
          },
          tooltip: [
            { field: "cat", type: "nominal",     title: xTitle },
            { field: "val", type: "quantitative", format: lblFmt, title: yTitle },
          ],
        },
      };
      defaultH = Math.max(120, vegaData.length * 28 + 60);
    }
  }

  if (!spec) return null;

  // Cap chart height to ~60% of typical panel height unless user has dragged or expanded
  const CLIP_H  = 400;
  const isLong  = defaultH > CLIP_H && !userH;
  const chartH  = userH ?? (expanded ? defaultH : Math.min(defaultH, CLIP_H));

  return (
    <div className="mt-2 w-full group/chart">
      {/* Header row: download button appears on hover, sits above the chart */}
      <div className="flex justify-end h-6 mb-0.5 opacity-0 group-hover/chart:opacity-100 transition-opacity">
        <button
          onClick={handleDownloadPng}
          title="Download chart as PNG"
          className="w-6 h-6 flex items-center justify-center rounded bg-zinc-800/80 hover:bg-zinc-700 text-zinc-500 hover:text-zinc-200 transition-colors"
        >
          <DownloadIcon label="Download chart as PNG" size="small" />
        </button>
      </div>

      {/* Chart — no overflow:hidden so axes are never clipped */}
      <div ref={outerRef}>
        <div ref={chartRef}>
          <VegaChart spec={spec} data={vegaData} height={chartH} />
        </div>
      </div>

      {/* Expand / Collapse when chart is taller than CLIP_H */}
      {isLong && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="mt-1 flex items-center gap-1 text-[11px] text-zinc-600 hover:text-zinc-300 transition-colors"
        >
          <span style={{ display: "inline-flex", transform: expanded ? "rotate(180deg)" : "none", transition: "transform .2s" }}>
            <ChevronDownIcon label="" size="small" />
          </span>
          {expanded ? "Collapse chart" : "Show full chart"}
        </button>
      )}

      {/* Drag-to-resize handle */}
      <div
        onMouseDown={startDrag}
        className="flex items-center justify-center h-3 cursor-ns-resize group/drag"
      >
        <div className="w-10 h-0.5 rounded-full bg-zinc-800 group-hover/drag:bg-zinc-600 transition-colors" />
      </div>
    </div>
  );
}

// ── Data summary ──────────────────────────────────────────────────────────────
// Computes a 1-2 sentence actionable insight from the result rows.
// Pure computation — no LLM call, zero latency.
function computeSummary(columns: string[], rows: unknown[][]): string | null {
  if (!rows.length || !columns.length) return null;
  const n = rows.length;

  const numIdx = columns.findIndex(
    (c, i) => !ORDINAL_COL.test(c) && rows.slice(0, 5).every((r) => isNumeric((r as unknown[])[i]))
  );
  const catIdx = columns.findIndex(
    (c, i) => i !== numIdx && !isNumeric(rows[0]?.[i as number]) && !ORDINAL_COL.test(c)
  );
  const cat2Idx = columns.findIndex(
    (c, i) => i !== numIdx && i !== catIdx && !isNumeric(rows[0]?.[i as number]) && !ORDINAL_COL.test(c)
  );

  if (numIdx === -1) {
    return n === 1 ? "1 result." : `${n.toLocaleString()} rows returned.`;
  }

  const numCol = columns[numIdx];
  const isShare = SHARE_COL.test(numCol) &&
    rows.slice(0, 5).every((r) => { const v = Number((r as unknown[])[numIdx]); return !isNaN(v) && v <= 1; });
  const fmtVal = (v: number) => fmt(numCol, v);

  if (n === 1) {
    const label = catIdx >= 0 ? String((rows[0] as unknown[])[catIdx]) : cleanLabel(numCol);
    return `${label}: ${fmtVal(Number((rows[0] as unknown[])[numIdx]))}`;
  }

  // No category — just a numeric summary
  if (catIdx < 0) {
    const nums = rows.map((r) => Number((r as unknown[])[numIdx])).filter((v) => !isNaN(v));
    const total = nums.reduce((a, b) => a + b, 0);
    return isShare ? `avg ${fmtVal(total / nums.length)}` : `${fmtVal(total)} total across ${n} rows.`;
  }

  // Aggregate by primary category
  const aggMap = new Map<string, number>();
  rows.forEach((r) => {
    const k = String((r as unknown[])[catIdx]);
    const v = Number((r as unknown[])[numIdx]);
    if (!isNaN(v)) aggMap.set(k, (aggMap.get(k) ?? 0) + v);
  });
  const sorted = [...aggMap.entries()].sort((a, b) => b[1] - a[1]);
  if (!sorted.length) return null;

  const aggTotal = sorted.reduce((s, [, v]) => s + v, 0);
  const [topName, topVal] = sorted[0];
  const topPct = aggTotal > 0 ? Math.round((topVal / aggTotal) * 100) : 0;

  const parts: string[] = [];

  if (isShare) {
    parts.push(`${topName} leads at ${fmtVal(topVal)}.`);
  } else {
    const concLabel = topPct >= 30 ? "highly concentrated" : topPct >= 18 ? "concentrated" : "spread";
    parts.push(`${cleanLabel(numCol)} is ${concLabel} — ${topName} alone accounts for ${topPct}% of ${fmtVal(aggTotal)}.`);
  }

  // Top-3 tier sentence
  if (sorted.length >= 4) {
    const top3Sum = sorted.slice(0, 3).reduce((s, [, v]) => s + v, 0);
    const top3Pct = aggTotal > 0 ? Math.round((top3Sum / aggTotal) * 100) : 0;
    const top3Names = sorted.slice(0, 3).map(([k]) => k).join(", ");
    parts.push(`${top3Names} together make up ${top3Pct}%.`);
  }

  // Stack dimension: which segment dominates overall
  if (cat2Idx >= 0 && parts.length < 2) {
    const stackAgg = new Map<string, number>();
    rows.forEach((r) => {
      const sk = String((r as unknown[])[cat2Idx]);
      const v = Number((r as unknown[])[numIdx]);
      if (!isNaN(v)) stackAgg.set(sk, (stackAgg.get(sk) ?? 0) + v);
    });
    if (stackAgg.size > 0) {
      const [topStack] = [...stackAgg.entries()].sort((a, b) => b[1] - a[1])[0];
      parts.push(`${topStack} is the dominant ${cleanLabel(columns[cat2Idx])} across all ${cleanLabel(columns[catIdx])}s.`);
    }
  }

  return parts.slice(0, 2).join(" ") || null;
}

// ── Result body ───────────────────────────────────────────────────────────────
function ResultBody({
  turn, onShowSource,
}: {
  turn: ChatTurn;
  onShowSource?: (data: SourcePanelData) => void;
}) {
  const { columns, rows, chartType } = turn;
  if (!columns.length) return null;

  const isSingleRow = rows.length === 1;
  const hasDate = columns.some((c) => DATE_COL.test(c));
  const hasCat  = columns.some((c, i) => !isNumeric(rows[0]?.[i]));
  const hasNum  = columns.some((c, i) => isNumeric(rows[0]?.[i]) && !ORDINAL_COL.test(c));

  const explicitChart = chartType && chartType !== "auto";
  const showChart = explicitChart
    ? hasNum
    : rows.length >= 3 && hasNum && (hasDate || hasCat);

  const summary     = computeSummary(columns, rows);
  const sourceTitle = inferSourceTitle(columns, rows);

  function handleSourceClick() {
    onShowSource?.({
      columns,
      rows: sortRowsForDisplay(columns, rows),
      sql: turn.sql,
      title: sourceTitle,
    });
  }

  return (
    <>
      {isSingleRow && hasNum ? (
        <KPICards columns={columns} rows={rows} />
      ) : showChart ? (
        /* Chart card — source panel is a top-level drawer in ChatPanel, not inlined here */
        <div className="mt-2 rounded-md border border-zinc-700/50 overflow-hidden p-3" style={{ background: '#13151a' }}>
          {/* Summary above the chart so it's seen first */}
          {summary && (
            <p className="text-[12px] italic text-zinc-400 mb-2 leading-relaxed">{summary}</p>
          )}
          <InlineChart columns={columns} rows={rows} chartType={chartType} title={sourceTitle} />
          {/* Source chip — bottom-right, opens the global source drawer */}
          <div className="flex justify-end mt-2">
            <button
              onClick={handleSourceClick}
              className="flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-md border border-zinc-700/40 text-zinc-500 hover:text-zinc-300 hover:border-zinc-600 transition-colors"
            >
              <TableIcon label="Table" size="small" />
              Source: {sourceTitle}
            </button>
          </div>
        </div>
      ) : (
        <>
          <MiniTable columns={columns} rows={rows} />
          {summary && (
            <p className="text-[12px] italic text-zinc-500 mt-2 leading-relaxed">{summary}</p>
          )}
        </>
      )}
    </>
  );
}

// ── SQL block with copy button ────────────────────────────────────────────────
function SqlBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(sql).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="relative group/sql">
      <pre className="text-[12px] font-mono text-zinc-400 rounded p-2.5 pr-10 overflow-x-auto whitespace-pre-wrap leading-relaxed" style={{ background: "#0d131a" }}>
        {sql}
      </pre>
      <button
        onClick={handleCopy}
        title={copied ? "Copied!" : "Copy SQL"}
        className="absolute top-2 right-2 w-6 h-6 rounded flex items-center justify-center text-zinc-600 hover:text-zinc-300 hover:bg-zinc-700/60 transition opacity-0 group-hover/sql:opacity-100"
      >
        {copied
          ? <span className="text-emerald-400"><CheckMarkIcon label="Copied" size="small" /></span>
          : <CopyIcon label="Copy SQL" size="small" />}
      </button>
    </div>
  );
}

// ── SQL syntax highlighter ───────────────────────────────────────────────────
function FormattedSql({ sql }: { sql: string }) {
  // Multi-word keywords must come first in the alternation
  const TOKEN_RE = /(`[^`]*`|'[^']*'|\b(?:GROUP\s+BY|ORDER\s+BY|IS\s+NOT\s+NULL|IS\s+NOT|IS\s+NULL|NOT\s+IN|NOT\s+LIKE|SELECT|FROM|WHERE|JOIN|LEFT|INNER|RIGHT|OUTER|CROSS|ON|AS|IS|NOT|NULL|AND|OR|IN|LIKE|BETWEEN|DISTINCT|COUNT|SUM|AVG|MIN|MAX|CASE|WHEN|THEN|ELSE|END|WITH|UNION|ALL|HAVING|LIMIT|OFFSET|ROUND|DATE_TRUNC|STRFTIME|COALESCE|NULLIF|CAST|ILIKE|LOWER|UPPER|TRIM|LENGTH|REPLACE|SUBSTR|EXTRACT|IF|IIF|ASC|DESC)\b)/gi;

  const parts: React.ReactNode[] = [];
  let lastIdx = 0;
  TOKEN_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = TOKEN_RE.exec(sql)) !== null) {
    if (match.index > lastIdx)
      parts.push(<span key={`p${lastIdx}`}>{sql.slice(lastIdx, match.index)}</span>);
    const tok = match[0];
    if (tok.startsWith("`") || tok.startsWith('"'))
      parts.push(<span key={`p${match.index}`} style={{ color: "#93c5fd" }}>{tok}</span>);
    else if (tok.startsWith("'"))
      parts.push(<span key={`p${match.index}`} style={{ color: "#fbbf24" }}>{tok}</span>);
    else
      parts.push(<span key={`p${match.index}`} style={{ color: "#60a5fa", fontWeight: 500 }}>{tok}</span>);
    lastIdx = match.index + tok.length;
  }
  if (lastIdx < sql.length) parts.push(<span key="tail">{sql.slice(lastIdx)}</span>);

  return (
    <pre className="text-[12px] font-mono text-zinc-300 p-3 overflow-x-auto whitespace-pre leading-[1.65]" style={{ background: "transparent" }}>
      {parts}
    </pre>
  );
}

// ── Source panel (Databricks-style: table + expandable SQL) — exported so ────
// ChatPanel can render it as a top-level right-side drawer.             ────────
export function SourcePanel({
  columns, rows, sql, title, onClose,
}: {
  columns: string[]; rows: unknown[][]; sql: string | null; title: string; onClose: () => void;
}) {
  const [showCode, setShowCode] = useState(false);
  const [copied,   setCopied]   = useState(false);

  function handleCopySql() {
    if (!sql) return;
    navigator.clipboard.writeText(sql).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); });
  }

  return (
    <div className="flex flex-col h-full" style={{ background: "#0f1923" }}>
      {/* ── Header ── */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-700/60 flex-shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="shrink-0 text-zinc-400">
            <TableIcon label="Table" size="small" />
          </span>
          <span className="text-[12px] font-medium text-zinc-200 truncate">{title}</span>
        </div>
        <div className="flex items-center gap-0.5 flex-shrink-0 ml-2">
          {/* Download CSV */}
          <button
            onClick={() => downloadCsv(columns, rows, title)}
            title="Download as CSV"
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-zinc-700/60 text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <DownloadIcon label="Download CSV" size="small" />
          </button>
          {/* Copy SQL */}
          {sql && (
            <button onClick={handleCopySql} title={copied ? "Copied!" : "Copy SQL"}
              className="w-6 h-6 flex items-center justify-center rounded hover:bg-zinc-700/60 text-zinc-500 hover:text-zinc-300 transition-colors">
              {copied
                ? <span className="text-emerald-400"><CheckMarkIcon label="Copied" size="small" /></span>
                : <CopyIcon label="Copy SQL" size="small" />}
            </button>
          )}
          {/* Close */}
          <button onClick={onClose} title="Close"
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-zinc-700/60 text-zinc-500 hover:text-zinc-300 transition-colors">
            <CloseIcon label="Close" size="small" />
          </button>
        </div>
      </div>

      {/* Data table — scrollable */}
      <div className="flex-1 overflow-auto min-h-0">
        <table className="text-[12px] w-full">
          <thead className="sticky top-0 z-10" style={{ background: "#0f1923" }}>
            <tr className="border-b border-zinc-700/60">
              {columns.map((c, ci) => (
                <th key={ci} className="px-3 py-1.5 text-left text-zinc-400 whitespace-nowrap font-medium">
                  <div className="flex items-center gap-1">
                    <span className="text-zinc-600 font-mono text-[11px] select-none">
                      {isNumeric(rows[0]?.[ci]) ? "1.2" : "Ac"}
                    </span>
                    {cleanLabel(c)}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className="border-b border-zinc-700/20 last:border-0 hover:bg-white/[0.02]">
                {columns.map((col, ci) => (
                  <td key={ci} className="px-3 py-1.5 text-zinc-300 font-mono whitespace-nowrap">
                    {fmt(col, (row as unknown[])[ci])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* SQL toggle — pinned to bottom */}
      {sql && (
        <div className="flex-shrink-0 border-t border-zinc-700/60">
          <button
            onClick={() => setShowCode(v => !v)}
            className="flex items-center gap-1.5 w-full px-3 py-1.5 text-[12px] text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700/20 transition-colors"
          >
            <AngleBracketsIcon label="Code" size="small" />
            {showCode ? "Hide code" : "Show code"}
            <span className={`ml-auto transition-transform duration-150 inline-block ${showCode ? "rotate-180" : ""}`}>
              <ChevronDownIcon label="" size="small" />
            </span>
          </button>
          {showCode && (
            <div className="border-t border-zinc-700/40 overflow-x-auto" style={{ background: "#0a1018" }}>
              <FormattedSql sql={sql} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Collapsible section ───────────────────────────────────────────────────────
function Section({
  label, defaultOpen = false, children,
}: { label: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-[12px] text-zinc-600 hover:text-zinc-400 transition-colors py-1"
      >
        <span className={`transition-transform duration-150 inline-block ${open ? "rotate-90" : ""}`}>›</span>
        {label}
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  );
}

// ── Table icon chip ───────────────────────────────────────────────────────────
function TableChip({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-[12px] font-mono px-2 py-0.5 rounded-md border border-zinc-700/60 text-zinc-400" style={{ background: "#1e2d3d" }}>
      <span className="shrink-0 text-zinc-500">
        <TableIcon label="Table" size="small" />
      </span>
      {name}
    </span>
  );
}

// ── Analysis section — collapsible "how I approached this" block ──────────────
function AnalysisSection({ intent, steps }: { intent: string; steps: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-3 rounded-md border border-zinc-800/60 overflow-hidden" style={{ background: "#0f1520" }}>
      {/* Header — always visible, click to toggle */}
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-zinc-800/30 transition-colors"
      >
        <span className="flex items-center gap-2 text-[12px] text-zinc-400 font-medium">
          <span className="text-zinc-600">◎</span>
          Analysis
        </span>
        <span className={`text-zinc-600 transition-transform duration-150 ${open ? "rotate-180" : ""}`}>
          <ChevronDownIcon label="" size="small" />
        </span>
      </button>

      {/* Body */}
      {open && (
        <div className="px-3 pb-3 space-y-2 border-t border-zinc-800/60">
          {intent && (
            <p className="text-[12px] text-zinc-400 leading-relaxed pt-2">{intent}</p>
          )}
          {steps.length > 0 && (
            <div>
              <p className="text-[11px] text-zinc-600 uppercase tracking-wide font-medium mt-1 mb-1.5">Calculated based on these steps</p>
              <ol className="space-y-1">
                {steps.map((s, i) => (
                  <li key={i} className="flex gap-2 text-[12px] text-zinc-400 leading-snug">
                    <span className="shrink-0 text-zinc-600 font-mono">{i + 1}.</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Investigate body — delegates to the appropriate rich report view ──────────
function InvestigateBody({
  turn, onShowSource,
}: {
  turn: ChatTurn;
  onShowSource?: (data: SourcePanelData) => void;
}) {
  const qm = turn.queryMode;

  if (qm === "investigate" || turn.adaReport) {
    return (
      <InvestigationReportView
        report={turn.adaReport ?? undefined}
        streamingPhases={turn.adaReport ? undefined : turn.phases}
      />
    );
  }

  if (qm === "explore" && turn.exploreReport) {
    return (
      <ExplorationReportView
        report={turn.exploreReport}
        subQuestions={turn.subQuestions}
        subqAnswers={turn.subqAnswers}
        queryCount={turn.subqAnswers.length}
      />
    );
  }

  // Direct route — renders like Quick mode, source chip available
  if (qm === "direct") {
    const rep = turn.report as Record<string, unknown> | null;
    const headline = rep ? ((rep.headline ?? rep.summary ?? "") as string) : null;
    return (
      <>
        {headline && <p className="text-[12px] text-zinc-300 leading-relaxed mb-2">{headline}</p>}
        <ResultBody turn={turn} onShowSource={onShowSource} />
      </>
    );
  }

  return null;
}

// ── Collapsible chevron ───────────────────────────────────────────────────────
function Chevron({ open }: { open: boolean }) {
  return (
    <span className={`text-zinc-500 transition-transform duration-150 inline-block ${open ? "rotate-180" : ""}`}>
      <ChevronDownIcon label="" size="small" />
    </span>
  );
}

// ── Inspect warning banner ────────────────────────────────────────────────────
function InspectWarningBanner({ issues, suggestedFix }: { issues: string[]; suggestedFix: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-4 px-3 py-2 rounded-lg bg-amber-950/30 border border-amber-700/50 text-[11px] text-amber-300 leading-snug">
      <button
        className="flex items-start gap-2 w-full text-left"
        onClick={() => setOpen(v => !v)}
      >
        <span className="shrink-0 mt-0.5 text-amber-400">
          <WarningIcon label="Warning" size="small" />
        </span>
        <span className="flex-1">
          <span className="text-amber-200 font-medium">Result may be incomplete</span>
          <span className="text-amber-400/70 ml-1">— Semantic inspector flagged a potential issue.</span>
        </span>
        <span className="shrink-0 text-amber-600 mt-0.5">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="mt-2 ml-6 space-y-1">
          {issues.map((issue, i) => (
            <p key={i} className="text-amber-300/80">• {issue}</p>
          ))}
          {suggestedFix && (
            <p className="mt-1.5 text-amber-400/60 italic">Suggestion: {suggestedFix}</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export function ChatMessage({
  turn,
  onFollowUp,
  onRunFresh,
  onShowSource,
}: {
  turn: ChatTurn;
  onFollowUp?: (q: string) => void;
  onRunFresh?: (q: string) => void;
  onShowSource?: (data: SourcePanelData) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const isInvestigate = turn.mode === "investigate";
  const hasResult = isInvestigate
    ? !!(turn.adaReport ?? turn.report ?? turn.exploreReport)
    : turn.status === "done";
  const isDone = turn.status === "done" || hasResult;
  // Show streaming ADA phases even while still loading (not for direct/explore routes)
  const showStreamingBody = isInvestigate && turn.status === "loading" && turn.phases.length > 0
    && turn.queryMode !== "direct";

  // Context-aware loading text: once the backend tells us the route, use a specific label
  function defaultStatusText(): string {
    if (!isInvestigate) return "Thinking…";
    switch (turn.queryMode) {
      case "direct":  return "Running query…";
      case "explore": return "Investigating…";
      default:        return "Investigating…";
    }
  }

  return (
    /* No card — content flows directly on the page background */
    <div className="group">

      {/* ── Question (right-aligned bubble) ── */}
      <div className="flex justify-end mb-4">
        <div className="flex items-start gap-2 max-w-[75%]">
          {isDone && (
            <button
              onClick={() => setCollapsed(v => !v)}
              className="text-zinc-700 hover:text-zinc-500 transition-colors p-0.5 mt-2 opacity-0 group-hover:opacity-100 shrink-0"
              title={collapsed ? "Expand" : "Collapse"}
            >
              <Chevron open={!collapsed} />
            </button>
          )}
          <div
            className="px-3 py-2 rounded-md text-[12px] font-semibold text-white leading-snug"
            style={{ background: isInvestigate ? "#633D96" : "#05355D" }}
          >
            {turn.question}
          </div>
        </div>
      </div>

      {/* ── Loading state ── */}
      {turn.status === "loading" && (
        <div>
          <div className="flex items-center gap-3 py-2">
            <span className="flex gap-1">
              {[0, 150, 300].map(d => (
                <span key={d} className="w-1.5 h-1.5 rounded-full bg-zinc-700 animate-bounce" style={{ animationDelay: `${d}ms` }} />
              ))}
            </span>
            <span className="text-[12px] text-zinc-600">
              {turn.statusText || defaultStatusText()}
            </span>
          </div>
          {/* Live ADA phase stream — show completed phases as they arrive */}
          {showStreamingBody && <InvestigateBody turn={turn} />}
        </div>
      )}

      {/* ── Error state ── */}
      {turn.status === "error" && (
        <p className="text-[12px] text-red-400 py-1">{turn.error}</p>
      )}

      {/* ── Always-visible table chips (outside collapsible) ── */}
      {isDone && turn.tablesUsed.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap mb-3">
          <span className="text-[12px] text-zinc-600">Found relevant data</span>
          {turn.tablesUsed.map(t => <TableChip key={t} name={t} />)}
        </div>
      )}

      {/* ── Body ── */}
      {!collapsed && isDone && (
        <>
          {/* Cache provenance banner — shown when result came from a semantically similar past investigation */}
          {turn.fromCache && (
            <div className="flex items-start gap-2 mb-4 px-3 py-2 rounded-lg bg-amber-950/30 border border-amber-800/40 text-[11px] text-amber-400 leading-snug">
              <span className="shrink-0 mt-0.5 text-amber-500">
                <InformationIcon label="Info" size="small" />
              </span>
              <span className="flex-1">
                <span className="text-amber-300 font-medium">From a similar past investigation</span>
                {turn.cachedQuestion && turn.cachedQuestion !== turn.question && (
                  <span className="text-amber-400/70"> — originally asked: &ldquo;{turn.cachedQuestion}&rdquo;</span>
                )}
              </span>
              {onRunFresh && (
                <button
                  onClick={() => onRunFresh(turn.question)}
                  className="shrink-0 px-2 py-0.5 rounded bg-amber-800/50 hover:bg-amber-700/60 text-amber-200 hover:text-white transition-colors whitespace-nowrap"
                >
                  Run fresh ↺
                </button>
              )}
            </div>
          )}

          {/* Semantic inspect warning — shown when post-execution validator finds a logical issue */}
          {turn.inspectWarning && turn.inspectWarning.issues.length > 0 && (
            <InspectWarningBanner
              issues={turn.inspectWarning.issues}
              suggestedFix={turn.inspectWarning.suggestedFix}
            />
          )}

          {/* Analysis section — collapsed by default */}
          {turn.analysis && (turn.analysis.intent || turn.analysis.steps.length > 0) && (
            <AnalysisSection intent={turn.analysis.intent} steps={turn.analysis.steps} />
          )}

          {/* Main answer */}
          <div className="mb-1">
            {isInvestigate ? (
              <InvestigateBody turn={turn} onShowSource={onShowSource} />
            ) : (
              <>
                {turn.headline && (
                  <p className="text-[12px] text-zinc-300 leading-relaxed mb-2">{turn.headline}</p>
                )}
                <ResultBody turn={turn} onShowSource={onShowSource} />
              </>
            )}
          </div>

          {/* Follow-up chips */}
          {turn.followups.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-4">
              {turn.followups.map((q, i) => (
                <button
                  key={i}
                  onClick={() => onFollowUp?.(q)}
                  className="flex items-center gap-1 text-[12px] text-zinc-500 hover:text-zinc-200 border border-zinc-700/50 hover:border-zinc-600 rounded-full px-2.5 py-[3px] transition-all"
                >
                  <span className="text-zinc-600 shrink-0">
                    <ArrowRightIcon label="" size="small" />
                  </span>
                  {q}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
