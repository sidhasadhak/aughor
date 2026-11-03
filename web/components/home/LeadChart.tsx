"use client";

/**
 * The lead's metric, day by day, as the warehouse reads it now — the one drawn thing Home has, and the proof beside its
 * figure. The days this source still changes are hatched and dashed (hatched means unknown, CLARITY §4), and when the
 * analysis reported another number for the lead's day, that number stands above the one the day became.
 *
 * Hand-drawn because it marks things no chart form holds: a band of unsettled days and a restatement.
 */
import { useEffect, useRef, useState } from "react";

import { compactNumber } from "@/lib/format";
import { dayMonth, wholeFigure, type TrendPoint } from "@/lib/home";

const H = 272, LEFT = 44, RIGHT = 12, TOP = 8, BOTTOM = 24;

/** The top of the axis and its four steps: round numbers a reader can hold. */
function axis(max: number): number[] {
  const rough = (max || 1) / 4;
  const scale = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map(m => m * scale).find(s => s >= rough) ?? rough;
  return [0, 1, 2, 3, 4].map(i => i * step);
}

export function LeadChart({ points, day, reported }: {
  points: TrendPoint[];
  /** The lead's day: marked on the line. */
  day: string;
  /** What the analysis reported for that day, when today's reading differs from it. */
  reported: { value: number; text: string; on: string } | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const read = () => setWidth(el.clientWidth);
    read();
    const seen = new ResizeObserver(read);
    seen.observe(el);
    return () => seen.disconnect();
  }, []);

  const sample = points[points.length - 1]?.text ?? "";
  const money = (v: number) => wholeFigure(v, sample);
  const ticks = axis(Math.max(...points.map(p => p.value), reported?.value ?? 0));
  const top = ticks[ticks.length - 1];
  const prefix = /^[^\d-]+/.exec(sample)?.[0] ?? "";
  const x = (i: number) => LEFT + (i * (width - LEFT - RIGHT)) / Math.max(points.length - 1, 1);
  const y = (v: number) => TOP + (1 - v / top) * (H - TOP - BOTTOM);
  const line = (from: number, to: number) => points.slice(from, to + 1)
    .map((p, i) => `${i ? "L" : "M"}${x(from + i).toFixed(1)} ${y(p.value).toFixed(1)}`).join("");

  const firstSettling = points.findIndex(p => p.settling);
  const lastSure = firstSettling < 0 ? points.length - 1 : firstSettling - 1;
  const sure = points.slice(0, lastSure + 1);
  const usual = sure.length >= 7 ? sure.reduce((n, p) => n + p.value, 0) / sure.length : null;
  const at = points.findIndex(p => p.day === day);
  const peak = points.reduce((best, p, i) => (p.value > points[best].value ? i : best), 0);
  const labelled = at >= 0 && x(at) < 240;
  const every = Math.max(1, Math.round(points.length / 4));
  const held = hover === null ? null : points[hover];
  const said = `${points.length} days of this metric, from ${dayMonth(points[0]?.day ?? "")} to ${dayMonth(points[points.length - 1]?.day ?? "")}`
    + (usual !== null ? `. Settled days average ${money(usual)}` : "")
    + (reported && at >= 0 ? `. ${dayMonth(day)} was reported at ${reported.text} on ${reported.on} and reads ${money(points[at].value)} now` : "");

  return (
    <div ref={box} data-testid="home-lead-chart" role="img" aria-label={said} style={{ position: "relative", height: H, marginTop: 12 }}
      onMouseLeave={() => setHover(null)}
      onMouseMove={e => {
        const left = e.currentTarget.getBoundingClientRect().left;
        const i = Math.round((e.clientX - left - LEFT) / ((width - LEFT - RIGHT) / Math.max(points.length - 1, 1)));
        setHover(Math.max(0, Math.min(points.length - 1, i)));
      }}>
      {width > 0 && points.length > 1 && (
        <svg width={width} height={H} aria-hidden="true" style={{ display: "block" }}>
          <defs>
            <pattern id="lead-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--chart-deemph)" strokeWidth="1" opacity=".45" />
            </pattern>
            <linearGradient id="lead-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--accent)" stopOpacity=".22" />
              <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
            </linearGradient>
          </defs>
          {ticks.map(v => (
            <g key={v}>
              <line x1={LEFT} x2={width - RIGHT} y1={y(v)} y2={y(v)} stroke="var(--chart-grid)" />
              <text x={LEFT - 8} y={y(v) + 4} textAnchor="end" fill="var(--t3)" className="aug-fs-sm">{v ? `${prefix}${compactNumber(v, 0)}` : `${prefix}0`}</text>
            </g>
          ))}
          {points.map((p, i) => (i + 2 < points.length && (points.length - 1 - i) % every === 0) || i === points.length - 1 ? (
            <text key={p.day} x={x(i)} y={H - 6} textAnchor={i === points.length - 1 ? "end" : "middle"} fill="var(--t3)" className="aug-fs-sm">{dayMonth(p.day)}</text>
          ) : null)}
          {firstSettling >= 0 && (
            <>
              <rect x={x(Math.max(firstSettling - 0.5, 0))} y={TOP} width={width - RIGHT - x(Math.max(firstSettling - 0.5, 0))} height={H - TOP - BOTTOM} fill="url(#lead-hatch)" />
              <text x={width - RIGHT - 4} y={TOP + 14} textAnchor="end" fill="var(--t2)" className="aug-fs-sm">still settling</text>
            </>
          )}
          {lastSure >= 1 && (
            <>
              <path d={`${line(0, lastSure)}L${x(lastSure)} ${y(0)}L${x(0)} ${y(0)}Z`} fill="url(#lead-fill)" />
              <path d={line(0, lastSure)} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
            </>
          )}
          {firstSettling >= 0 && (
            <path d={line(Math.max(firstSettling - 1, 0), points.length - 1)} fill="none" stroke="var(--t2)" strokeWidth="2" strokeDasharray="4 4" strokeLinejoin="round" strokeLinecap="round" />
          )}
          {usual !== null && (
            <text x={LEFT + 6} y={y(usual) - 34} fill="var(--t3)" className="aug-fs-sm">Settled days average {money(usual)}</text>
          )}
          {peak !== at && points[peak].value > (usual ?? 0) * 1.5 && (
            <text x={x(peak) - 10} y={y(points[peak].value) + 4} textAnchor="end" fill="var(--t2)" className="aug-fs-sm">{money(points[peak].value)} on {dayMonth(points[peak].day)}</text>
          )}
          {at >= 0 && reported && (
            <>
              <line x1={x(at)} x2={x(at)} y1={y(reported.value) + 6} y2={y(points[at].value) - 6} stroke="var(--amb3)" strokeDasharray="2 3" />
              <circle cx={x(at)} cy={y(reported.value)} r="5" fill="var(--bg-2)" stroke="var(--amb3)" strokeWidth="2" />
              <text x={x(at) + (labelled ? 10 : -10)} y={y(reported.value) + 4} textAnchor={labelled ? "start" : "end"} fill="var(--t1)" className="aug-fs-chrome">
                <tspan fontWeight="500">{reported.text}</tspan><tspan fill="var(--t2)"> reported {reported.on}</tspan>
              </text>
            </>
          )}
          {at >= 0 && (
            <>
              <circle cx={x(at)} cy={y(points[at].value)} r="5" fill="var(--accent)" stroke="var(--bg-2)" strokeWidth="2" />
              <text x={x(at) + (labelled ? 10 : -10)} y={y(points[at].value) - 12} textAnchor={labelled ? "start" : "end"} fill="var(--t1)" className="aug-fs-chrome">
                <tspan fontWeight="500">{money(points[at].value)}</tspan><tspan fill="var(--t2)"> now</tspan>
              </text>
            </>
          )}
          {held && hover !== null && (
            <>
              <line x1={x(hover)} x2={x(hover)} y1={TOP} y2={H - BOTTOM} stroke="var(--b2)" />
              <circle cx={x(hover)} cy={y(held.value)} r="4" fill="var(--t1)" stroke="var(--bg-2)" strokeWidth="2" />
            </>
          )}
        </svg>
      )}
      {held && hover !== null && (
        <div className="aug-fs-sm" data-testid="home-lead-tip" style={{ position: "absolute", pointerEvents: "none", zIndex: 2, whiteSpace: "nowrap",
          left: Math.max(70, Math.min(width - 70, x(hover))), top: Math.max(44, y(held.value)), transform: "translate(-50%, -120%)",
          background: "var(--bg-3)", border: "1px solid var(--b2)", borderRadius: "var(--r2)", padding: "4px 8px", color: "var(--t1)",
          fontVariantNumeric: "tabular-nums" }}>
          <div style={{ color: "var(--t3)" }}>{dayMonth(held.day)}{held.settling ? " · still settling" : ""}</div>
          {money(held.value)}
        </div>
      )}
    </div>
  );
}
