/**
 * Arc BG (ROADMAP §3.66) — an edition's figures, drawn by code from what was measured.
 *
 * Two pictures, each showing what its story says: a figure's ranges as bars with its USUAL RANGE shaded
 * behind them (the range itself last, in the accent), and a figure's segments as the change each made on
 * its own usual — a change drawn as the change. A segment behind fewer than 30 rows is drawn grey: too
 * few to call. The model never draws; the server never sends a picture, only the numbers.
 */
import type { EditionCell, EditionFigure } from "@/lib/api";
import { rangeWord, toneOf } from "@/lib/briefingEdition";

const W = 360;

function dayMonth(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

const TONE: Record<string, string> = { good: "var(--grn4)", bad: "var(--amb4)", neutral: "var(--blue4)" };

/** The figure's ranges as bars, the usual range shaded behind them. */
export function RangeBars({ figure, period }: { figure: EditionFigure; period: string }) {
  const pts = figure.series.filter(p => p.value !== null) as { label: string; start: string; value: number }[];
  if (pts.length < 2) return null;
  const u = figure.usual;
  const h = 118, pad = { l: 48, r: 6, t: 8, b: 18 };
  const values = pts.map(p => p.value).concat(u ? [u.low, u.high] : []);
  const lo = Math.min(...values), hi = Math.max(...values);
  const y0 = lo - (hi - lo) * 0.35, y1 = hi + (hi - lo) * 0.08 || hi + 1;
  const Y = (v: number) => pad.t + (h - pad.t - pad.b) * (1 - (v - y0) / (y1 - y0 || 1));
  const bw = (W - pad.l - pad.r) / pts.length;
  const every = pts.length > 10 ? 3 : 2;
  const tone = TONE[toneOf(figure)];
  return (
    <svg viewBox={`0 0 ${W} ${h}`} width="100%" role="img" data-testid="edition-range-bars"
      aria-label={`${figure.label} by ${rangeWord(period)}, this ${rangeWord(period)} last`}>
      {u && (
        <>
          <rect x={pad.l} y={Y(u.high)} width={W - pad.l - pad.r} height={Math.max(1, Y(u.low) - Y(u.high))}
            fill="var(--bg-3)" data-testid="edition-usual-band" />
          <text x={pad.l - 4} y={Y(u.high) + 3} textAnchor="end" fontSize={10.5} fill="var(--t3)">{u.high_text}</text>
          <text x={pad.l - 4} y={Y(u.low) + 3} textAnchor="end" fontSize={10.5} fill="var(--t3)">{u.low_text}</text>
        </>
      )}
      {pts.map((p, i) => {
        const last = i === pts.length - 1;
        const x = pad.l + i * bw + bw * 0.18;
        return (
          <g key={`${p.label}-${p.start}`}>
            <rect x={x} y={Y(p.value)} width={bw * 0.64} height={Math.max(1, h - pad.b - Y(p.value))} rx={2}
              fill={last ? tone : "var(--chart-deemph)"} data-current={last ? "true" : undefined}>
              <title>{dayMonth(p.start)}</title>
            </rect>
            {(i % every === (pts.length - 1) % every) && (
              <text x={x + bw * 0.32} y={h - 5} textAnchor="middle" fontSize={10.5} fill={last ? "var(--t1)" : "var(--t3)"}>
                {dayMonth(p.start)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function changeText(c: EditionCell): string {
  if (c.rel !== null && Number.isFinite(c.rel)) return `${c.rel >= 0 ? "+" : "−"}${Math.abs(c.rel * 100).toFixed(0)}%`;
  if (c.delta !== null) return `${c.delta >= 0 ? "+" : "−"}${Math.abs(c.delta).toFixed(1)}`;
  return "";
}

/** A figure's segments, each as the change it made on its own usual range. */
export function SegmentBars({ cells, better }: { cells: EditionCell[]; better: EditionFigure["better"] }) {
  const rows = cells.filter(c => c.delta !== null);
  if (!rows.length) return null;
  const rowH = 20, h = rows.length * rowH + 8, lab = 120, room = 46;
  const half = (W - lab - 2 * room) / 2, mid = lab + room + half;
  const span = Math.max(...rows.map(c => Math.abs(c.delta as number))) || 1;
  const sx = half / span;
  return (
    <svg viewBox={`0 0 ${W} ${h}`} width="100%" role="img" aria-label="each segment against its usual range"
      data-testid="edition-segment-bars">
      <line x1={mid} x2={mid} y1={2} y2={h - 4} stroke="var(--b1)" />
      {rows.map((c, i) => {
        const d = c.delta as number, y = 4 + i * rowH;
        const good = better === "none" ? null : (d >= 0) === (better === "up");
        const fill = c.thin ? "var(--chart-deemph)" : good === null ? "var(--blue4)" : good ? "var(--grn4)" : "var(--amb4)";
        const x = d >= 0 ? mid : mid + d * sx;
        const tx = d >= 0 ? mid + d * sx + 5 : mid + d * sx - 5;
        return (
          <g key={`${c.group}-${i}`} data-thin={c.thin ? "true" : undefined}>
            <text x={lab - 8} y={y + 12} textAnchor="end" fontSize={11} fill={c.thin ? "var(--t3)" : "var(--t2)"}>
              {c.group || "(none)"}
            </text>
            <rect x={x} y={y + 3} width={Math.max(1.5, Math.abs(d) * sx)} height={11} rx={2} fill={fill}>
              <title>{`${c.group}: ${c.current_text ?? ""} this range, ${c.usual_text ?? ""} usually${c.thin ? " — too few to call" : ""}`}</title>
            </rect>
            <text x={tx} y={y + 12} textAnchor={d >= 0 ? "start" : "end"} fontSize={10.5} fill="var(--t3)">{changeText(c)}</text>
          </g>
        );
      })}
    </svg>
  );
}
