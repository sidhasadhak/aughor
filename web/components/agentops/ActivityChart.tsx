"use client";

/**
 * Runs per bucket, stacked by agent, on the surface's shared time axis.
 *
 * **Every bin is a query.** Hovering names the per-series values, clicking a bar narrows
 * the whole page to that bucket, and dragging brushes a span — the tiles, the table and the
 * jobs list all follow, because they read the same range this chart writes. That is the one
 * mechanic that turns a dashboard into an instrument; without it a chart is a picture of a
 * number you still cannot ask about.
 *
 * Stacked is a deliberate choice and a narrow one: stacking is the wrong form for COMPARING
 * series (only the bottom one sits on a common baseline), and it is the right form when the
 * TOTAL is the subject — here, "how much did the fleet do". Per-agent comparison is the
 * table's job, one row each, and the legend swatch is the join between them.
 *
 * Hand-rolled SVG rather than ECharts: this needs pointer semantics (drag-to-brush over
 * discrete buckets, click-vs-drag disambiguation) that would be fought for through a chart
 * library's event model, and it is ~120 lines of geometry. The colour ramp is the shared
 * `--chart-1..6` so a series is the same colour here, in the legend and in the table.
 */
import { useCallback, useMemo, useRef, useState } from "react";

import type { TimeSeries, TimeWindow } from "@/lib/api";
import { compactNumber, formatCount } from "@/lib/format";

export const SERIES_COLORS = [
  "var(--chart-1)", "var(--chart-2)", "var(--chart-3)",
  "var(--chart-4)", "var(--chart-5)", "var(--chart-6)",
];

/** Stable colour per series key, so a colour means one agent everywhere on the page. */
export function colorFor(key: string, order: string[]): string {
  const i = order.indexOf(key);
  return SERIES_COLORS[(i < 0 ? order.length : i) % SERIES_COLORS.length];
}

const PAD = { l: 36, r: 8, t: 10, b: 20 };
const VB = { w: 1000, h: 190 };

function niceMax(v: number): number {
  if (v <= 5) return 5;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / mag) * mag;
}

/** Bucket edge → the label a human reads on the axis. */
function edgeLabel(iso: string, bucketSeconds: number): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (bucketSeconds >= 86400) {
    return d.toLocaleDateString(undefined, { day: "2-digit", month: "short" });
  }
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function ActivityChart({
  window: win, edges, series, runners, showRunners, hidden, onBrush, onPickBucket,
  selection, order,
}: {
  window: TimeWindow;
  edges: string[];
  series: TimeSeries[];
  runners: TimeSeries[];
  showRunners: boolean;
  hidden: Set<string>;
  onBrush: (since: string, until: string) => void;
  onPickBucket: (since: string, until: string) => void;
  /** [startBucket, endBucket] currently selected, for the highlight overlay. */
  selection: [number, number] | null;
  order: string[];
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [drag, setDrag] = useState<{ from: number; to: number } | null>(null);

  const n = Math.max(1, edges.length);
  const drawn = useMemo(() => {
    const base = series.filter(s => !hidden.has(s.key));
    return showRunners ? [...base, ...runners] : base;
  }, [series, runners, showRunners, hidden]);

  const totals = useMemo(() => {
    const out = new Array(n).fill(0);
    for (const s of drawn) for (let i = 0; i < n; i++) out[i] += s.values[i] ?? 0;
    return out;
  }, [drawn, n]);

  const max = niceMax(Math.max(1, ...totals));
  const iw = VB.w - PAD.l - PAD.r;
  const ih = VB.h - PAD.t - PAD.b;
  const bw = iw / n;
  const gap = Math.max(1, Math.min(4, bw * 0.18));

  const bucketAt = useCallback((clientX: number): number => {
    const el = svgRef.current;
    if (!el) return 0;
    const r = el.getBoundingClientRect();
    const x = ((clientX - r.left) / r.width) * VB.w;
    return Math.max(0, Math.min(n - 1, Math.floor((x - PAD.l) / bw)));
  }, [bw, n]);

  const endOf = useCallback((i: number): string =>
    new Date(new Date(edges[i]).getTime() + win.bucket_seconds * 1000).toISOString(),
    [edges, win.bucket_seconds]);

  const onDown = useCallback((e: React.PointerEvent) => {
    const b = bucketAt(e.clientX);
    setDrag({ from: b, to: b });
    (e.target as Element).setPointerCapture?.(e.pointerId);
  }, [bucketAt]);

  const onMove = useCallback((e: React.PointerEvent) => {
    const b = bucketAt(e.clientX);
    setHover(b);
    setDrag(d => (d ? { ...d, to: b } : d));
  }, [bucketAt]);

  const onUp = useCallback((e: React.PointerEvent) => {
    if (!drag) return;
    const b = bucketAt(e.clientX);
    const [lo, hi] = [Math.min(drag.from, b), Math.max(drag.from, b)];
    setDrag(null);
    // A click and a drag arrive through the same gesture; the distinction is whether the
    // bucket moved. Both narrow the SAME window — one bucket, or a span of them.
    if (lo === hi) onPickBucket(edges[lo], endOf(lo));
    else onBrush(edges[lo], endOf(hi));
  }, [drag, bucketAt, edges, endOf, onBrush, onPickBucket]);

  const marked = drag ? [Math.min(drag.from, drag.to), Math.max(drag.from, drag.to)] as [number, number]
    : selection;

  const hoverRows = hover === null ? [] : drawn
    .map(s => ({ key: s.key, label: s.label, v: s.values[hover] ?? 0 }))
    .filter(r => r.v > 0)
    .reverse();

  return (
    <div style={{ position: "relative", userSelect: "none" }}>
      <svg ref={svgRef} viewBox={`0 0 ${VB.w} ${VB.h}`} preserveAspectRatio="none"
        role="img" aria-label={`Runs per bucket, stacked by agent, over ${win.range || "the window"}`}
        style={{ width: "100%", height: 190, display: "block", cursor: "crosshair", touchAction: "none" }}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}
        onPointerLeave={() => { setHover(null); setDrag(null); }}>
        <defs>
          {/* Runners are hatched, not coloured: they are on the chart so their volume is
              visible, and visibly NOT one of the agents. */}
          <pattern id="ao-hatch" width="5" height="5" patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)">
            <rect width="5" height="5" fill="var(--bg-3)" />
            <line x1="0" y1="0" x2="0" y2="5" stroke="var(--t3)" strokeWidth="2" />
          </pattern>
        </defs>

        {[0, 0.5, 1].map(f => {
          const y = PAD.t + ih - f * ih;
          return (
            <g key={f}>
              <line x1={PAD.l} x2={VB.w - PAD.r} y1={y} y2={y}
                stroke="var(--chart-grid)" strokeWidth="1" />
              <text x={PAD.l - 6} y={y + 3.5} textAnchor="end"
                fill="var(--chart-tick)" fontSize="10" fontFamily="var(--font-mono)">
                {compactNumber(Math.round(max * f))}
              </text>
            </g>
          );
        })}

        {Array.from({ length: n }, (_, i) => {
          let y = PAD.t + ih;
          const x = PAD.l + i * bw + gap / 2;
          const dim = marked && (i < marked[0] || i > marked[1]);
          return (
            <g key={i}>
              {drawn.map(s => {
                const v = s.values[i] ?? 0;
                if (!v) return null;
                const h = (v / max) * ih;
                y -= h;
                const isRunner = runners.some(r => r.key === s.key);
                return (
                  <rect key={s.key} x={x} y={y} width={Math.max(0.5, bw - gap)}
                    height={Math.max(0.5, h)} rx="1"
                    fill={isRunner ? "url(#ao-hatch)" : colorFor(s.key, order)}
                    opacity={dim ? 0.25 : 0.92} />
                );
              })}
            </g>
          );
        })}

        {marked && (
          <rect x={PAD.l + marked[0] * bw} y={PAD.t}
            width={(marked[1] - marked[0] + 1) * bw} height={ih}
            fill="var(--blue3)" fillOpacity="0.12" stroke="var(--blue4)" strokeWidth="1"
            pointerEvents="none" />
        )}
        {hover !== null && (
          <line x1={PAD.l + hover * bw + bw / 2} x2={PAD.l + hover * bw + bw / 2}
            y1={PAD.t} y2={PAD.t + ih} stroke="var(--blue4)" strokeDasharray="3 3"
            opacity="0.6" pointerEvents="none" />
        )}

        {edges.map((e, i) => {
          const step = n <= 12 ? 1 : n <= 24 ? 3 : n <= 28 ? 4 : 5;
          if (i % step) return null;
          return (
            <text key={e} x={PAD.l + i * bw + bw / 2} y={VB.h - 6} textAnchor="middle"
              fill="var(--t2)" fontSize="10" fontFamily="var(--font-mono)">
              {edgeLabel(e, win.bucket_seconds)}
            </text>
          );
        })}
      </svg>

      {hover !== null && (
        <div role="tooltip"
          style={{
            position: "absolute", top: 4, right: 4, pointerEvents: "none",
            background: "var(--bg-4)", border: "1px solid var(--b3)",
            borderRadius: "var(--r3)", padding: "8px 10px", minWidth: 172,
            boxShadow: "0 10px 30px -10px rgba(0,0,0,.6)",
          }}>
          <div className="aug-fs-xs" style={{ color: "var(--t2)", fontFamily: "var(--font-mono)", marginBottom: 5 }}>
            {edgeLabel(edges[hover], win.bucket_seconds)} · {formatCount(totals[hover])} runs
          </div>
          {hoverRows.length === 0
            ? <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>nothing ran in this bucket</div>
            : hoverRows.map(r => (
              <div key={r.key} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <span className="aug-fs-xs" style={{ color: "var(--t1)" }}>
                  <i style={{
                    display: "inline-block", width: 8, height: 8, borderRadius: 2, marginRight: 6,
                    background: runners.some(x => x.key === r.key) ? "var(--t3)" : colorFor(r.key, order),
                  }} />
                  {r.label}
                </span>
                <b className="aug-fs-xs" style={{ color: "var(--t1)", fontFamily: "var(--font-mono)", fontWeight: 500 }}>
                  {formatCount(r.v)}
                </b>
              </div>
            ))}
          <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 4 }}>
            click to filter · drag to brush
          </div>
        </div>
      )}
    </div>
  );
}
