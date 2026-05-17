"use client";

import { useEffect, useRef, useState } from "react";
import { ChatTurn } from "@/lib/useChat";

// ── Shared helpers ────────────────────────────────────────────────────────────

const DATE_COL = /(_date|_at|_time|created_at|updated_at|timestamp)$/i;
const SHARE_COL = /(share|pct|percent|rate|ratio|proportion)/i;
const ORDINAL_COL = /(year|month|day|week|rank|_id$|^id$)/i;

function isNumeric(v: unknown): boolean {
  return v !== null && v !== "" && !isNaN(Number(v));
}

// "2024-01-01 00:00:00" or "2024-01-01T00:00:00Z" → "Jan 2024"
// Returns the original string unchanged if it doesn't look like a timestamp
function fmtTimestampLabel(v: string): string {
  if (!/^\d{4}-\d{2}-\d{2}/.test(v)) return v;
  try {
    const d = new Date(v);
    if (isNaN(d.getTime())) return v;
    return d.toLocaleString("default", { month: "short", year: "numeric" });
  } catch {
    return v;
  }
}

function fmt(col: string, val: unknown): string {
  if (val === null || val === "NULL") return "—";
  const s = String(val);
  if (ORDINAL_COL.test(col)) return s;
  const n = Number(val);
  if (!isNaN(n)) {
    if (SHARE_COL.test(col) && n >= 0 && n <= 1) return `${(n * 100).toFixed(2)}%`;
    if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    if (!Number.isInteger(n)) return n.toFixed(2);
    return n.toLocaleString();
  }
  return s;
}

// ── KPI cards (single-row numeric result) ────────────────────────────────────
const KPI_PALETTES = [
  { border: "border-violet-500/30", bg: "bg-violet-500/10", value: "text-violet-300", label: "text-violet-400/60" },
  { border: "border-blue-500/30",   bg: "bg-blue-500/10",   value: "text-blue-300",   label: "text-blue-400/60"   },
  { border: "border-emerald-500/30",bg: "bg-emerald-500/10",value: "text-emerald-300",label: "text-emerald-400/60"},
  { border: "border-amber-500/30",  bg: "bg-amber-500/10",  value: "text-amber-300",  label: "text-amber-400/60"  },
];

function KPICards({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  const row = rows[0];
  const numericCols = columns.filter(
    (c, i) => isNumeric(row[i]) && !ORDINAL_COL.test(c)
  );
  if (!numericCols.length) return null;
  return (
    <div className="flex flex-wrap gap-3 mt-2">
      {numericCols.map((col, ki) => {
        const idx = columns.indexOf(col);
        const p = KPI_PALETTES[ki % KPI_PALETTES.length];
        return (
          <div key={col} className={`${p.bg} border ${p.border} rounded-lg px-4 py-3 min-w-[110px]`}>
            <p className={`text-[10px] uppercase tracking-wide font-medium mb-1 ${p.label}`}>
              {col.replace(/_/g, " ")}
            </p>
            <p className={`text-xl font-semibold tabular-nums ${p.value}`}>{fmt(col, row[idx])}</p>
          </div>
        );
      })}
    </div>
  );
}

// ── Mini table ───────────────────────────────────────────────────────────────
function MiniTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  return (
    <div className="mt-2 overflow-x-auto rounded-lg border border-zinc-800">
      <table className="text-xs w-full">
        <thead>
          <tr className="border-b border-violet-500/20 bg-violet-500/8">
            {columns.map((c) => (
              <th key={c} className="px-3 py-2 text-left font-medium text-violet-300/70 whitespace-nowrap font-mono uppercase tracking-wide text-[10px]">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-800/30 transition-colors">
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
  );
}

// ── Inline chart (Observable Plot + d3-shape for pie) ────────────────────────
const NUM_FMT = (v: number) =>
  Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(0)}k` : String(v);

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
    text.style.cssText = "font-size:10px;color:#a1a1aa;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:130px";
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
}: {
  columns: string[];
  rows: unknown[][];
  chartType?: string | null;
}) {
  // outerRef = scrollable shell; innerRef = Observable Plot / SVG mount point
  const outerRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  // userH = null means "use natural height". Set by drag handle.
  const [userH, setUserH] = useState<number | null>(null);

  function startDrag(e: React.MouseEvent) {
    e.preventDefault();
    const startY = e.clientY;
    const startH = outerRef.current?.clientHeight ?? 320;

    function onMove(ev: MouseEvent) {
      const newH = Math.max(80, startH + (ev.clientY - startY));
      // CSS-only during drag — no React re-render, stays smooth
      if (outerRef.current) {
        outerRef.current.style.height = `${newH}px`;
        outerRef.current.style.maxHeight = "none";
      }
    }
    function onUp(ev: MouseEvent) {
      const newH = Math.max(80, startH + (ev.clientY - startY));
      setUserH(newH); // single re-render at final size
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
    const dateCol = columns.find((c) => DATE_COL.test(c));
    const catCols = columns.filter((c, i) => !DATE_COL.test(c) && !isNumeric(rows[0]?.[i]));
    const numCol = columns.find((c, i) => !DATE_COL.test(c) && isNumeric(rows[0]?.[i]));
    const catCol = catCols[0];   // primary grouping / y-axis
    const catCol2 = catCols[1];  // secondary grouping / stack fill

    if (!numCol) return;
    const hint = (chartType ?? "auto").toLowerCase();

    // Preserve SQL order when the group column represents a time label (month, quarter …)
    const isTimeLabel = catCol ? TIME_LABEL_COL.test(catCol) : false;

    // Available width (use outer scroll shell width if mounted, fallback 640)
    const availW = outerRef.current?.clientWidth || 640;

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
      const isStacked = hint === "stacked_bar" || (hint === "auto" && catCol && catCol2 && !dateCol);

      // ── STACKED BAR — vertical by default (groups on X, measure on Y) ────
      if (isStacked && catCol && catCol2) {
        const stackData = data.map((d) => ({
          group: fmtTimestampLabel(String(d[catCol])),
          stack: fmtTimestampLabel(String(d[catCol2])),
          val: Number(d[numCol]),
        }));
        const groups = [...new Set(stackData.map((d) => d.group))];
        const stacks = [...new Set(stackData.map((d) => d.stack))];

        const legendW = stacks.length > 12 ? 280 : 150;
        const chartW = Math.max(availW - legendW - 24, Math.max(300, groups.length * 40));

        chart = Plot.plot({
          width: chartW,
          height: userH ?? 280,
          marginBottom: isTimeLabel || groups.length > 8 ? 70 : 50,
          marginLeft: 60,
          marginRight: 8,
          marginTop: 16,
          style: { background: "transparent", color: "#a1a1aa", fontSize: "11px" },
          x: { label: catCol, tickRotate: groups.length > 8 ? -40 : 0 },
          y: { grid: true, tickFormat: NUM_FMT, label: numCol },
          color: { scheme: "tableau10" },
          marks: [
            Plot.barY(stackData, Plot.stackY({
              x: "group",
              y: "val",
              fill: "stack",
              title: (d: { group: string; stack: string; val: number }) =>
                `${d.stack}: ${NUM_FMT(d.val)}`,
            })),
            Plot.ruleY([0]),
          ],
        });

        const legendItems = stacks.map((s, i) => ({ label: s, color: T10[i % T10.length] }));
        const wrapper = document.createElement("div");
        wrapper.style.cssText = "display:flex;gap:16px;align-items:flex-start;width:100%";
        wrapper.appendChild(chart);
        wrapper.appendChild(buildHtmlLegend(legendItems));
        innerRef.current.appendChild(wrapper);
        return;
      }

      // ── LINE / AREA (time-series) — time on X, measure on Y ───────────────
      else if (dateCol && (hint === "line" || hint === "area" || hint === "auto")) {
        const parsed = data.map((d) => ({
          ...d,
          [dateCol]: new Date(d[dateCol] as string),
          [numCol]: Number(d[numCol]),
        }));
        chart = Plot.plot({
          width: availW,
          height: userH ?? 200,
          marginLeft: 60,
          marginRight: 16,
          style: { background: "transparent", color: "#a1a1aa", fontSize: "11px" },
          x: { type: "time", label: dateCol },
          y: { grid: true, tickFormat: NUM_FMT, label: numCol },
          marks: [
            Plot.areaY(parsed, { x: dateCol, y: numCol, fill: "#10b981", fillOpacity: 0.08 }),
            Plot.lineY(parsed, { x: dateCol, y: numCol, stroke: "#10b981", strokeWidth: 1.5 }),
            Plot.dot(parsed.length <= 60 ? parsed : [], { x: dateCol, y: numCol, fill: "#10b981", r: 2.5 }),
          ],
        });
      }

      // ── VERTICAL BAR — only when explicitly requested ─────────────────────
      else if (catCol && hint === "bar") {
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

        chart = Plot.plot({
          width: chartW,
          height: userH ?? 260,
          marginBottom: barData.length > 10 ? 70 : 48,
          marginLeft: 60,
          marginRight: 16,
          style: { background: "transparent", color: "#a1a1aa", fontSize: "11px" },
          x: {
            label: catCol,
            tickRotate: barData.length > 10 ? -40 : 0,
            ...(isTimeLabel ? {} : { sort: null }),
          },
          y: { grid: true, tickFormat: NUM_FMT, label: numCol },
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
                text: (d: { cat: string; val: number }) => NUM_FMT(d.val),
                dy: -6,
                textAnchor: "middle",
                fill: "#a1a1aa",
                fontSize: 10,
              }
            ),
            Plot.ruleY([0]),
          ],
        });
      }

      // ── HORIZONTAL BAR — default for categorical data ────────────────────
      else if (catCol && (hint === "bar_horizontal" || hint === "auto")) {
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
        const labelMargin = Math.min(140, Math.max(60, Math.max(...barData.map((d) => d.cat.length)) * 7));

        chart = Plot.plot({
          width: availW,
          height: userH ?? Math.max(100, barData.length * 26),
          marginLeft: labelMargin,
          marginRight: 72,
          style: { background: "transparent", color: "#a1a1aa", fontSize: "11px" },
          x: { grid: true, tickFormat: NUM_FMT, label: numCol },
          y: { label: catCol },
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
                text: (d: { cat: string; val: number }) => NUM_FMT(d.val),
                dx: 6,
                textAnchor: "start",
                fill: "#a1a1aa",
                fontSize: 10,
              }
            ),
            Plot.ruleX([0]),
          ],
        });
      }

      if (chart && innerRef.current) innerRef.current.appendChild(chart);
    });

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  // userH intentionally omitted: drag-resize only changes the CSS container height.
  // Re-running the effect on every resize created a duplicate chart flash.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columns, rows, chartType]);

  return (
    <div className="mt-2 w-full">
      <div
        ref={outerRef}
        className="overflow-x-auto overflow-y-auto"
        style={{ maxHeight: userH ? "none" : "380px", height: userH ? `${userH}px` : undefined }}
      >
        <div ref={innerRef} />
      </div>
      <div
        onMouseDown={startDrag}
        className="flex items-center justify-center h-3 cursor-ns-resize group"
      >
        <div className="w-10 h-0.5 rounded-full bg-zinc-800 group-hover:bg-zinc-600 transition-colors" />
      </div>
    </div>
  );
}

// ── Data summary ──────────────────────────────────────────────────────────────
// Computes a 1-2 sentence natural-language summary from the result rows.
// Pure computation — no LLM call, zero latency.
function computeSummary(columns: string[], rows: unknown[][]): string | null {
  if (!rows.length || !columns.length) return null;
  const n = rows.length;

  // Identify numeric and categorical column indices
  const numIdx = columns.findIndex(
    (c, i) => !ORDINAL_COL.test(c) && rows.slice(0, 5).every((r) => isNumeric((r as unknown[])[i]))
  );
  const catIdx = columns.findIndex(
    (c, i) => i !== numIdx && !isNumeric(rows[0]?.[i as number]) && !ORDINAL_COL.test(c)
  );

  if (numIdx === -1) {
    return n === 1 ? "1 result." : `${n.toLocaleString()} rows returned.`;
  }

  const numCol = columns[numIdx];
  const nums = rows.map((r) => Number((r as unknown[])[numIdx])).filter((v) => !isNaN(v));
  const total = nums.reduce((a, b) => a + b, 0);
  const maxVal = Math.max(...nums);
  const isShare = SHARE_COL.test(numCol) && maxVal <= 1;

  const fmtVal = (v: number) => fmt(numCol, v);

  if (n === 1) {
    const label = catIdx >= 0 ? String((rows[0] as unknown[])[catIdx]) : numCol;
    return `${label}: ${fmtVal(nums[0])}`;
  }

  if (catIdx >= 0) {
    const topCat = String((rows[0] as unknown[])[catIdx]);
    const topVal = fmtVal(maxVal);
    const tail = isShare
      ? `avg ${fmtVal(total / nums.length)}`
      : `${fmtVal(total)} total`;
    return `${n.toLocaleString()} rows · top: ${topCat} at ${topVal} · ${tail}`;
  }

  const tail = isShare ? `avg ${fmtVal(total / nums.length)}` : `total ${fmtVal(total)}`;
  return `${n.toLocaleString()} rows · ${numCol} ${tail}`;
}

// ── Result body ───────────────────────────────────────────────────────────────
function ResultBody({ turn }: { turn: ChatTurn }) {
  const { columns, rows, chartType } = turn;
  if (!columns.length) return null;

  const isSingleRow = rows.length === 1;
  const hasDate = columns.some((c) => DATE_COL.test(c));
  const hasCat = columns.some((c, i) => !isNumeric(rows[0]?.[i]));
  const hasNum = columns.some((c, i) => isNumeric(rows[0]?.[i]) && !ORDINAL_COL.test(c));

  // Explicit chart type overrides auto-detect; pie/stacked can chart even with 1-2 rows
  const explicitChart = chartType && chartType !== "auto";
  const showChart = explicitChart
    ? hasNum
    : rows.length >= 3 && hasNum && (hasDate || hasCat);

  const summary = computeSummary(columns, rows);

  return (
    <>
      {isSingleRow && hasNum && !explicitChart ? (
        <KPICards columns={columns} rows={rows} />
      ) : showChart ? (
        <InlineChart columns={columns} rows={rows} chartType={chartType} />
      ) : (
        <MiniTable columns={columns} rows={rows} />
      )}
      {summary && !isSingleRow && (
        <p className="text-[11px] text-zinc-500 mt-2 leading-relaxed">{summary}</p>
      )}
    </>
  );
}

// ── SQL collapsible ───────────────────────────────────────────────────────────
function SQLCollapsible({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors flex items-center gap-1"
      >
        <span>{open ? "▲" : "▼"}</span> SQL
      </button>
      {open && (
        <pre className="mt-1 text-[10px] font-mono text-zinc-500 bg-zinc-900 rounded p-2 overflow-x-auto whitespace-pre-wrap">
          {sql}
        </pre>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export function ChatMessage({ turn }: { turn: ChatTurn }) {
  return (
    <div className="space-y-2">
      {/* Question bubble — right */}
      <div className="flex justify-end">
        <div className="max-w-[80%] bg-zinc-800 rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm text-zinc-100">
          {turn.question}
        </div>
      </div>

      {/* Answer bubble — left */}
      <div className="flex justify-start">
        <div className="w-full min-w-[200px]">
          {turn.status === "loading" && (
            <div className="flex items-center gap-2 px-4 py-3 bg-zinc-900 border border-zinc-800 rounded-2xl rounded-tl-sm">
              <span className="flex gap-1">
                {[0, 150, 300].map((d) => (
                  <span
                    key={d}
                    className="w-1.5 h-1.5 rounded-full bg-zinc-600 animate-bounce"
                    style={{ animationDelay: `${d}ms` }}
                  />
                ))}
              </span>
            </div>
          )}

          {turn.status === "error" && (
            <div className="px-4 py-3 bg-red-500/5 border border-red-500/20 rounded-2xl rounded-tl-sm">
              <p className="text-xs text-red-400">{turn.error}</p>
              {turn.sql && <SQLCollapsible sql={turn.sql} />}
            </div>
          )}

          {turn.status === "done" && (
            <div className="px-2 py-2">
              {turn.headline && (
                <p className="text-sm text-zinc-300 mb-2">{turn.headline}</p>
              )}
              <ResultBody turn={turn} />
              {turn.sql && <SQLCollapsible sql={turn.sql} />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
