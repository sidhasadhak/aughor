"use client";

import React, { useEffect, useRef, useState } from "react";
import TableIcon         from "@atlaskit/icon/core/table";
import DownloadIcon      from "@atlaskit/icon/core/download";
import CloseIcon         from "@atlaskit/icon/core/close";
import CopyIcon          from "@atlaskit/icon/core/copy";
import CheckMarkIcon     from "@atlaskit/icon/core/check-mark";
import ChevronDownIcon   from "@atlaskit/icon/core/chevron-down";
import AngleBracketsIcon from "@atlaskit/icon/core/angle-brackets";
import InformationIcon   from "@atlaskit/icon/core/information";
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
const ORDINAL_COL = /(year|month|day|week|rank|_id$|^id$)/i;

function isNumeric(v: unknown): boolean {
  return v !== null && v !== "" && !isNaN(Number(v));
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
  const numColNames = columns.filter((c, i) =>  isNumeric(rows[0]?.[i]) && !ORDINAL_COL.test(c));
  const catColNames = columns.filter((c, i) => !isNumeric(rows[0]?.[i]) && i !== dateColIdx && !DATE_COL.test(c));

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
    .filter(i => !isNumeric(rows[0]?.[i]));
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
      if (n >= 0 && n <= 1)   return `${(n * 100).toFixed(2)}%`; // decimal fraction
      if (n >= 0 && n <= 100) return `${n.toFixed(2)}%`;          // already a percentage
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

// ── Mini table ───────────────────────────────────────────────────────────────
function MiniTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  return (
    <div className="mt-2 rounded-lg border border-zinc-700/50 overflow-hidden" style={{ background: "#131c27" }}>
      <div className="overflow-x-auto overflow-y-auto" style={{ maxHeight: "320px" }}>
        <table className="text-[12px] w-full">
          <thead className="sticky top-0 z-10">
            <tr className="border-b border-zinc-700/60" style={{ background: "#1a2535" }}>
              {columns.map((c) => (
                <th key={c} className="px-3 py-1.5 text-left font-semibold text-zinc-400 whitespace-nowrap">
                  {cleanLabel(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-zinc-700/30 last:border-0 hover:bg-white/[0.02] transition-colors">
                {columns.map((col, j) => (
                  <td key={j} className="px-3 py-1.5 text-zinc-300 font-mono whitespace-nowrap">
                    {fmt(col, (row as unknown[])[j])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Inline chart (Observable Plot + d3-shape for pie) ────────────────────────
/** Generic axis/label formatter — never shows raw floats */
const NUM_FMT = (v: number) =>
  Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(1)}M`
  : Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(0)}k`
  : Number.isInteger(v) ? String(v)
  : v.toFixed(2);

/**
 * Column-aware formatter for chart labels.
 * If the column looks like a rate/pct and the values are > 1 (already ×100),
 * append "%" and round to 1 dp.  If values are ≤ 1, treat as fraction → ×100.
 * Delegates to NUM_FMT for everything else.
 */
function makeColFmt(colName: string, sampleValues: number[]) {
  const isShareCol = SHARE_COL.test(colName);
  if (isShareCol) {
    const maxV = Math.max(...sampleValues.map(Math.abs));
    const isAlready100 = maxV > 1; // already multiplied ×100
    return (v: number) => isAlready100 ? `${v.toFixed(1)}%` : `${(v * 100).toFixed(1)}%`;
  }
  return NUM_FMT;
}

// Columns whose values are already human-formatted time labels (Month - Year, Q1 2024, etc.)
// → preserve SQL ordering, don't parse as dates, don't re-sort
const TIME_LABEL_COL = /(month|quarter|week|half|period)/i;

// Tableau-10 palette — matches Observable Plot's "tableau10" scheme order
const T10 = ["#4e79a7","#f28e2b","#e15759","#76b7b2","#59a14f",
              "#edc948","#b07aa1","#ff9da7","#9c755f","#bab0ac"];
const PIE_COLORS = ["#818cf8","#34d399","#f59e0b","#f87171","#38bdf8","#c084fc","#fb923c","#a3e635"];

/** Build a right-side HTML legend div for stacked / pie charts */
function buildHtmlLegend(items: { label: string; color: string }[]): HTMLDivElement {
  const div = document.createElement("div");
  div.style.cssText = "display:flex;flex-direction:column;gap:4px;padding:4px 0;min-width:110px;max-width:160px;flex-shrink:0";

  // Two-column layout when >12 items
  const twoCol = items.length > 12;
  if (twoCol) {
    div.style.flexDirection = "row";
    div.style.flexWrap = "wrap";
    div.style.columnGap = "8px";
    div.style.maxWidth = "280px";
  }

  items.forEach(({ label, color }) => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:5px;" + (twoCol ? "width:calc(50% - 4px);" : "");
    const swatch = document.createElement("span");
    swatch.style.cssText = `display:inline-block;width:9px;height:9px;border-radius:2px;background:${color};flex-shrink:0`;
    const text = document.createElement("span");
    text.style.cssText = "font-size:12px;color:#a1a1aa;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:130px";
    text.title = label;
    text.textContent = label;
    row.appendChild(swatch);
    row.appendChild(text);
    div.appendChild(row);
  });
  return div;
}

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
  // outerRef = scrollable shell; innerRef = Observable Plot / SVG mount point
  const outerRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  // userH = null means "use natural height". Set by drag handle.
  const [userH, setUserH] = useState<number | null>(null);
  // containerW tracks the live pixel width of outerRef so the chart re-draws
  // correctly whenever the container narrows/widens (e.g. source panel opens).
  const [containerW, setContainerW] = useState(0);
  useEffect(() => {
    const el = outerRef.current;
    if (!el) return;
    setContainerW(el.clientWidth);
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width);
      if (w > 0) setContainerW(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  function startDrag(e: React.MouseEvent) {
    e.preventDefault();
    const startY = e.clientY;
    const startH = outerRef.current?.clientHeight ?? 320;

    function onMove(ev: MouseEvent) {
      const newH = Math.max(80, startH + (ev.clientY - startY));
      // Grow the container to follow the handle
      if (outerRef.current) {
        outerRef.current.style.maxHeight = "none";
        outerRef.current.style.height = `${newH}px`;
      }
      // Grow the SVG in lock-step so there is no gap between chart and container.
      // viewBox stays fixed so content is pinned to the top; empty space appears
      // below — on mouseup the chart re-renders at the final height to fill it.
      const svg = innerRef.current?.querySelector("svg");
      if (svg) svg.setAttribute("height", String(newH));
    }
    function onUp(ev: MouseEvent) {
      const newH = Math.max(80, startH + (ev.clientY - startY));
      setUserH(newH); // triggers effect → chart re-renders at final height
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  useEffect(() => {
    if (!innerRef.current || !rows.length) return;
    let cancelled = false;
    innerRef.current.innerHTML = "";

    const data: Record<string, unknown>[] = rows.map((r) => {
      const obj: Record<string, unknown> = {};
      columns.forEach((c, i) => { obj[c] = (r as unknown[])[i]; });
      return obj;
    });

    // Column classification
    // Value-based date detection: if NAME doesn't match DATE_COL but value looks like
    // an ISO date string (e.g. "order_month" → "2025-01-01 00:00:00"), treat as date.
    const DATE_VALUE_RE = /^\d{4}-\d{2}-\d{2}/;
    const looksLikeDate = (colIdx: number) => {
      const v = rows[0]?.[colIdx];
      return typeof v === "string" && DATE_VALUE_RE.test(v);
    };
    const dateCol =
      columns.find((c) => DATE_COL.test(c)) ||
      columns.find((c, i) => !isNumeric(rows[0]?.[i]) && looksLikeDate(i));

    const catCols = columns.filter(
      (c, i) => c !== dateCol && !DATE_COL.test(c) && !isNumeric(rows[0]?.[i])
    );
    // Prefer percentage/share/rate columns over raw counts when multiple numeric columns exist
    const PREFER_COL = /(pct|percent|share|rate|ratio|proportion)/i;
    const numericCols = columns.filter((c, i) => !DATE_COL.test(c) && isNumeric(rows[0]?.[i]));
    const numCol = numericCols.find(c => PREFER_COL.test(c)) ?? numericCols[0];
    const catCol = catCols[0];   // primary grouping / y-axis
    const catCol2 = catCols[1];  // secondary grouping / stack fill

    if (!numCol) return;
    const hint = (chartType ?? "auto").toLowerCase();

    // Preserve SQL order when the group column represents a time label (month, quarter …)
    const isTimeLabel = catCol ? TIME_LABEL_COL.test(catCol) : false;

    // Available width — use the live ResizeObserver value so the chart re-draws
    // at the correct width whenever the source panel opens or closes.
    const availW = containerW > 0 ? containerW : (outerRef.current?.clientWidth || 640);

    // ── PIE / DONUT ─────────────────────────────────────────────────────────
    if (hint === "pie" && catCol) {
      import("d3-shape").then(({ pie, arc }) => {
        if (cancelled || !innerRef.current) return;
        innerRef.current.innerHTML = "";

        const agg = new Map<string, number>();
        data.forEach((d) => {
          const k = String(d[catCol]);
          agg.set(k, (agg.get(k) ?? 0) + Number(d[numCol]));
        });
        const slices = [...agg.entries()]
          .sort((a, b) => b[1] - a[1])
          .map(([label, value], i) => ({ label, value, color: PIE_COLORS[i % PIE_COLORS.length] }));
        const total = slices.reduce((s, d) => s + d.value, 0);

        const R_OUTER = 100, R_INNER = 44;
        const pieGen = pie<typeof slices[0]>().value((d) => d.value).sort(null);
        const arcGen = arc<{ startAngle: number; endAngle: number }>().innerRadius(R_INNER).outerRadius(R_OUTER);
        const labelArc = arc<{ startAngle: number; endAngle: number }>().innerRadius(72).outerRadius(R_OUTER);

        const H = 240;
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("width", String(H));
        svg.setAttribute("height", String(H));
        svg.setAttribute("viewBox", `0 0 ${H} ${H}`);
        svg.style.background = "transparent";

        const g = document.createElementNS(ns, "g");
        g.setAttribute("transform", `translate(${H / 2},${H / 2})`);
        svg.appendChild(g);

        pieGen(slices).forEach((seg, i) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const d = arcGen(seg as any) || "";
          const path = document.createElementNS(ns, "path");
          path.setAttribute("d", d);
          path.setAttribute("fill", seg.data.color);
          path.setAttribute("stroke", "#09090b");
          path.setAttribute("stroke-width", "1.5");
          g.appendChild(path);

          const pct = (seg.data.value / total) * 100;
          if (pct >= 5) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const [cx, cy] = labelArc.centroid(seg as any);
            const text = document.createElementNS(ns, "text");
            text.setAttribute("x", String(cx));
            text.setAttribute("y", String(cy));
            text.setAttribute("text-anchor", "middle");
            text.setAttribute("dominant-baseline", "middle");
            text.setAttribute("fill", "white");
            text.setAttribute("font-size", "9");
            text.textContent = `${pct.toFixed(0)}%`;
            g.appendChild(text);
          }
        });

        // Flex wrapper: pie SVG + right legend
        const wrapper = document.createElement("div");
        wrapper.style.cssText = "display:flex;gap:16px;align-items:center;flex-wrap:wrap";
        wrapper.appendChild(svg);
        wrapper.appendChild(buildHtmlLegend(slices));
        innerRef.current.appendChild(wrapper);
      });
      return () => { cancelled = true; };
    }

    // ── All other chart types — Observable Plot ──────────────────────────────
    import("@observablehq/plot").then((Plot) => {
      if (cancelled || !innerRef.current) return;
      innerRef.current.innerHTML = "";

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let chart: any = null;

      // Temporal stack: date + one category + one measure → stacked bar over time
      // e.g. "monthly revenue by source" → month on X, source as stack colour
      const isTemporalStack = catCol && dateCol && (hint === "stacked_bar" || hint === "auto");
      // Category stack: two category columns + one measure, no date
      const isCatStack = catCol && catCol2 && !dateCol && (hint === "stacked_bar" || hint === "auto");
      const isStacked = isTemporalStack || isCatStack || hint === "stacked_bar";

      // ── STACKED BAR — groups on X (date or primary cat), stack fill = secondary ──
      if (isStacked && catCol) {
        const stackData = isTemporalStack && dateCol
          ? data.map((d) => ({
              group: fmtTimestampLabel(String(d[dateCol])),
              stack: String(d[catCol]),
              val: Number(d[numCol]),
            }))
          : data.map((d) => ({
              group: fmtTimestampLabel(String(d[catCol])),
              stack: catCol2 ? fmtTimestampLabel(String(d[catCol2])) : "",
              val: Number(d[numCol]),
            }));
        const stacks = [...new Set(stackData.map((d) => d.stack))];

        // Keep date order for temporal stacks; sort by total descending for categorical
        const groupTotalsMap = new Map<string, number>();
        stackData.forEach((d) => groupTotalsMap.set(d.group, (groupTotalsMap.get(d.group) ?? 0) + d.val));
        const groups = (isTemporalStack || isTimeLabel)
          ? [...new Set(stackData.map((d) => d.group))]   // preserve chronological order
          : [...groupTotalsMap.entries()].sort((a, b) => b[1] - a[1]).map(([g]) => g);

        const legendW = stacks.length > 12 ? 280 : 150;
        const chartW = Math.max(availW - legendW - 24, Math.max(300, groups.length * 40));

        chart = Plot.plot({
          width: chartW,
          height: userH ?? 280,
          marginBottom: isTimeLabel || groups.length > 8 ? 70 : 50,
          marginLeft: 60,
          marginRight: 8,
          marginTop: 16,
          style: { background: "transparent", color: "#a1a1aa", fontSize: "12px" },
          x: { label: cleanLabel(catCol), domain: groups, tickRotate: groups.length > 8 ? -40 : 0 },
          y: { grid: true, tickFormat: makeColFmt(numCol, stackData.map(d => d.val)), label: cleanLabel(numCol) },
          color: { scheme: "tableau10" },
          marks: [
            Plot.barY(stackData, Plot.stackY({
              x: "group",
              y: "val",
              fill: "stack",
              title: (d: { group: string; stack: string; val: number }) =>
                `${d.stack}: ${makeColFmt(numCol, stackData.map(s => s.val))(d.val)}`,
            })),
            Plot.ruleY([0]),
          ],
        });

        const legendItems = stacks.map((s, i) => ({ label: s, color: T10[i % T10.length] }));
        // Pin height only — width is handled by re-rendering at the new containerW.
        // Prevents Observable Plot's height:auto from proportionally shrinking the chart
        // on any residual CSS scaling edge-cases.
        const stackH = chart.getAttribute("height");
        if (stackH) chart.style.height = `${stackH}px`;

        const wrapper = document.createElement("div");
        wrapper.style.cssText = "display:flex;gap:16px;align-items:flex-start;width:100%";
        wrapper.appendChild(chart);
        wrapper.appendChild(buildHtmlLegend(legendItems));
        innerRef.current.appendChild(wrapper);
        return;
      }

      // ── DATE BAR — explicit bar request on date+numeric data (no categories) ─
      // Uses rectY (continuous/time scale) instead of barY (band scale) to avoid
      // the "scale incompatible with channel: time !== band" error.
      else if (dateCol && !catCol && (hint === "bar" || hint === "bar_horizontal")) {
        const barData = data.map((d) => ({
          date: new Date(normDateStr(String(d[dateCol]))),
          val: Number(d[numCol]),
        }));
        chart = Plot.plot({
          width: availW,
          height: userH ?? 240,
          marginLeft: 60,
          marginRight: 16,
          marginBottom: 40,
          style: { background: "transparent", color: "#a1a1aa", fontSize: "12px" },
          x: { type: "time", label: cleanLabel(dateCol) },
          y: { grid: true, tickFormat: NUM_FMT, label: cleanLabel(numCol) },
          marks: [
            Plot.rectY(barData, { x: "date", y: "val", fill: "#818cf8", interval: "month", inset: 0.5 }),
            Plot.ruleY([0]),
          ],
        });
      }

      // ── LINE / AREA (time-series) — time on X, measure on Y ───────────────
      // Only fires when there is no category column alongside the date.
      // date + category + measure is handled above as a temporal stacked bar.
      else if (dateCol && !catCol && (hint === "line" || hint === "area" || hint === "auto")) {
        const parsed = data.map((d) => ({
          ...d,
          [dateCol]: new Date(normDateStr(String(d[dateCol]))),
          [numCol]: Number(d[numCol]),
        }));
        chart = Plot.plot({
          width: availW,
          height: userH ?? 200,
          marginLeft: 60,
          marginRight: 16,
          style: { background: "transparent", color: "#a1a1aa", fontSize: "12px" },
          x: { type: "time", label: cleanLabel(dateCol) },
          y: { grid: true, tickFormat: makeColFmt(numCol, parsed.map((d: Record<string, unknown>) => Number(d[numCol]))), label: cleanLabel(numCol) },
          marks: [
            Plot.areaY(parsed, { x: dateCol, y: numCol, fill: "#10b981", fillOpacity: 0.08 }),
            Plot.lineY(parsed, { x: dateCol, y: numCol, stroke: "#10b981", strokeWidth: 1.5 }),
            Plot.dot(parsed.length <= 60 ? parsed : [], { x: dateCol, y: numCol, fill: "#10b981", r: 2.5 }),
          ],
        });
      }

      // ── VERTICAL BAR — only when user explicitly says "vertical bar" ────────
      else if (catCol && hint === "bar_vertical") {
        const agg = new Map<string, number>();
        data.forEach((d) => {
          const k = String(d[catCol]);
          agg.set(k, (agg.get(k) ?? 0) + Number(d[numCol]));
        });
        const sorted = isTimeLabel
          ? [...agg.entries()]
          : [...agg.entries()].sort((a, b) => b[1] - a[1]);
        const maxVal = Math.max(...sorted.map(([, v]) => v), 1);
        const barData = sorted.map(([cat, val]) => ({ cat, val }));
        // Expand width so each bar has at least 36px; scrolls horizontally when needed
        const chartW = Math.max(availW, barData.length * 36);
        const colFmt = makeColFmt(numCol, barData.map(d => d.val));

        chart = Plot.plot({
          width: chartW,
          height: userH ?? 260,
          marginBottom: barData.length > 10 ? 70 : 48,
          marginLeft: 60,
          marginRight: 16,
          style: { background: "transparent", color: "#a1a1aa", fontSize: "12px" },
          x: {
            label: cleanLabel(catCol),
            tickRotate: barData.length > 10 ? -40 : 0,
            ...(isTimeLabel ? {} : { sort: null }),
          },
          y: { grid: true, tickFormat: colFmt, label: cleanLabel(numCol) },
          marks: [
            Plot.barY(barData, {
              x: "cat",
              y: "val",
              fill: "#818cf8",
              ...(isTimeLabel ? {} : { sort: { x: "-y" } }),
            }),
            Plot.text(
              barData.filter((d) => d.val >= maxVal * 0.08),
              {
                x: "cat",
                y: "val",
                text: (d: { cat: string; val: number }) => colFmt(d.val),
                dy: -6,
                textAnchor: "middle",
                fill: "#a1a1aa",
                fontSize: 12,
              }
            ),
            Plot.ruleY([0]),
          ],
        });
      }

      // ── HORIZONTAL BAR — default for ALL categorical data (bar / bar_horizontal / auto) ─
      else if (catCol && (hint === "bar" || hint === "bar_horizontal" || hint === "auto")) {
        const agg = new Map<string, number>();
        data.forEach((d) => {
          const k = String(d[catCol]);
          agg.set(k, (agg.get(k) ?? 0) + Number(d[numCol]));
        });
        const sorted = isTimeLabel
          ? [...agg.entries()]
          : [...agg.entries()].sort((a, b) => b[1] - a[1]);
        const maxVal = Math.max(...sorted.map(([, v]) => v), 1);
        const barData = sorted.map(([cat, val]) => ({ cat, val }));
        // Left margin: space for category labels only — no rotated Y-axis label
        const labelMargin = Math.min(160, Math.max(70, Math.max(...barData.map((d) => d.cat.length)) * 7));
        const colFmt = makeColFmt(numCol, barData.map(d => d.val));

        chart = Plot.plot({
          width: availW,
          height: userH ?? Math.max(100, barData.length * 28),
          marginLeft: labelMargin,
          marginRight: 72,
          marginBottom: 44,
          style: { background: "transparent", color: "#a1a1aa", fontSize: "12px" },
          // X: centered label, no rotated Y label (categories already visible as tick labels)
          x: { grid: true, tickFormat: colFmt, label: cleanLabel(numCol), labelAnchor: "center" },
          y: { label: null },
          marks: [
            Plot.barX(barData, {
              x: "val",
              y: "cat",
              fill: "#818cf8",
              ...(isTimeLabel ? {} : { sort: { y: "-x" } }),
            }),
            Plot.text(
              barData.filter((d) => d.val >= maxVal * 0.08),
              {
                x: "val",
                y: "cat",
                text: (d: { cat: string; val: number }) => colFmt(d.val),
                dx: 6,
                textAnchor: "start",
                fill: "#a1a1aa",
                fontSize: 12,
              }
            ),
            Plot.ruleX([0]),
          ],
        });
      }

      if (chart && innerRef.current) {
        // Pin height — chart re-draws at the correct containerW so no CSS width-scaling
        // occurs; the height pin prevents height:auto edge-cases.
        const ch = (chart as SVGElement).getAttribute?.("height");
        if (ch) (chart as SVGElement).style.height = `${ch}px`;
        innerRef.current.appendChild(chart);
      }
    });

    return () => { cancelled = true; };
  // containerW triggers a re-draw when the source panel opens/closes (container width changes).
  // userH triggers a re-draw only on mouseup (end of drag), not during the drag itself.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columns, rows, chartType, userH, containerW]);

  // ── PNG download ─────────────────────────────────────────────────────────────
  function handleDownloadPng() {
    const svg = innerRef.current?.querySelector("svg");
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
        const fname = title.replace(/[^a-z0-9]+/gi, "_").toLowerCase() + ".png";
        const a = Object.assign(document.createElement("a"), { href: pngUrl, download: fname });
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        URL.revokeObjectURL(pngUrl);
      }, "image/png");
    };
    img.src = url;
  }

  return (
    <div className="mt-2 w-full relative group/chart">
      {/* PNG download — top-right, appears on hover */}
      <button
        onClick={handleDownloadPng}
        title="Download chart as PNG"
        className="absolute top-0 right-0 z-10 opacity-0 group-hover/chart:opacity-100 transition-opacity w-7 h-7 flex items-center justify-center rounded-md bg-zinc-800/90 hover:bg-zinc-700 text-zinc-500 hover:text-zinc-200"
      >
        <DownloadIcon label="Download chart as PNG" size="small" />
      </button>
      <div
        ref={outerRef}
        className="overflow-x-auto overflow-y-hidden"
        style={{ maxHeight: userH ? "none" : "380px" }}
      >
        <div ref={innerRef} />
      </div>
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
        <div className="mt-2 rounded-xl border border-zinc-700/50 overflow-hidden p-3" style={{ background: "#131c27" }}>
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
                    <span className="text-zinc-600 font-mono text-[10px] select-none">
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
  // Show streaming ADA phases even while still loading
  const showStreamingBody = isInvestigate && turn.status === "loading" && turn.phases.length > 0;

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
            className="px-3 py-2 rounded-xl text-[12px] font-semibold text-white leading-snug"
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
              {turn.statusText || (isInvestigate ? "Investigating…" : "Thinking…")}
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

          {/* Tables used */}
          {turn.tablesUsed.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap mb-3">
              <span className="text-[12px] text-zinc-600">Found relevant data</span>
              {turn.tablesUsed.map(t => <TableChip key={t} name={t} />)}
            </div>
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
