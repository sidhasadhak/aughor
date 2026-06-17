"use client";

/* ════════════════════════════════════════════════════════════════════════════
   AUGHOR v2 — PRESENTATIONAL CHARTS (portable, dependency-free)
   ────────────────────────────────────────────────────────────────────────────
   Hand-built SVG charts for DASHBOARD surfaces (Briefing, Health, stat tiles) —
   NOT a replacement for the Vega analytical engine (keep that for query
   results; theme it with vega-theme-v2.ts). All colors reference CSS custom
   properties, so they flip with dark/light automatically. Motion is additive:
   resting state is fully drawn; grow/draw runs only under `html.av2-animate`
   (see elevation-motion.css + INTEGRATION.md), so SSR / print / reduced-motion
   never blank out.

   Requires: elevation-motion.css (for .av2-gv-bar / .av2-gv-barx / .av2-gv-draw
   keyframes) and tokens-v2.css (for --chart-1..6, --t1..4, --bg-*).

   Usage:
     import { BarChart, AreaChart, DonutChart, ParetoChart, Sparkline, Counter }
       from "@/aughor-v2/charts/Charts-v2";
     <AreaChart data={[{label:"Jan",v:4.2e6}, …]} accent="var(--chart-1)" valuePrefix="$" />
   ════════════════════════════════════════════════════════════════════════════ */

import React, { useEffect, useMemo, useRef, useState } from "react";

export interface Datum { label: string; v: number; }

const SERIES = ["var(--chart-1)","var(--chart-2)","var(--chart-3)","var(--chart-4)","var(--chart-5)","var(--chart-6)"];

export function fmtNum(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(a >= 1e10 ? 0 : 1) + "B";
  if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M";
  if (a >= 1e3) return (n / 1e3).toFixed(a >= 1e4 ? 0 : 1) + "k";
  return String(Math.round(n));
}
const uid = (p: string) => p + Math.random().toString(36).slice(2, 7);

/* ── Bar ─────────────────────────────────────────────────────────────────── */
export function BarChart({ data, height = 200, accent = "var(--chart-1)", valuePrefix = "" }:
  { data: Datum[]; height?: number; accent?: string; valuePrefix?: string }) {
  const [hi, setHi] = useState<number | null>(null);
  const max = Math.max(...data.map(d => d.v)) * 1.12;
  const n = data.length, gap = 0.34, VB = height / 3;
  const gid = useMemo(() => uid("bg"), []);
  return (
    <div style={{ width: "100%" }}>
      <svg viewBox={`0 0 100 ${VB}`} preserveAspectRatio="none" width="100%" height={height} style={{ overflow: "visible" }}>
        <defs><linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={accent} stopOpacity="1" /><stop offset="100%" stopColor={accent} stopOpacity="0.45" />
        </linearGradient></defs>
        {[0.25, 0.5, 0.75, 1].map(g => <line key={g} x1="0" x2="100" y1={VB * (1 - g)} y2={VB * (1 - g)} stroke="var(--chart-grid)" strokeWidth="0.4" vectorEffect="non-scaling-stroke" />)}
        {data.map((d, i) => {
          const bw = (100 / n) * (1 - gap), x = (100 / n) * i + (100 / n) * gap / 2;
          const h = (d.v / max) * VB, on = hi === i;
          return (
            <g key={i} onMouseEnter={() => setHi(i)} onMouseLeave={() => setHi(null)} style={{ cursor: "pointer" }}>
              <rect x={x} y="0" width={bw} height={VB} fill="transparent" />
              <rect className="av2-gv-bar" x={x} y={VB - h} width={bw} height={h} rx="1.4" fill={`url(#${gid})`}
                opacity={on ? 1 : 0.92} style={{ animationDelay: `${i * 55}ms`, filter: on ? "brightness(1.15)" : "none", transition: "opacity .15s, filter .15s" }} />
            </g>
          );
        })}
      </svg>
      <div style={{ display: "flex", marginTop: 8 }}>
        {data.map((d, i) => (
          <div key={i} style={{ flex: 1, minWidth: 0, textAlign: "center", fontSize: 10, padding: "0 2px" }}>
            <div style={{ fontVariantNumeric: "tabular-nums", color: "var(--t1)", fontWeight: 600, height: 13, opacity: hi === i ? 1 : 0, transition: "opacity .15s" }}>{valuePrefix}{fmtNum(d.v)}</div>
            <div style={{ marginTop: 2, color: hi === i ? "var(--t1)" : "var(--t3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Area + line ─────────────────────────────────────────────────────────── */
export function AreaChart({ data, height = 210, accent = "var(--chart-2)", valuePrefix = "$" }:
  { data: Datum[]; height?: number; accent?: string; valuePrefix?: string }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const pathRef = useRef<SVGPathElement>(null);
  const [hi, setHi] = useState<number | null>(null);
  const [len, setLen] = useState(0);
  const W = 100, H = 100;
  const max = Math.max(...data.map(d => d.v)), min = Math.min(...data.map(d => d.v));
  const span = (max - min) || 1, pad = span * 0.18, lo = min - pad, top = max + pad, rng = top - lo;
  const x = (i: number) => (i / (data.length - 1)) * W, y = (v: number) => H - ((v - lo) / rng) * H;
  const line = data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(d.v).toFixed(2)}`).join(" ");
  const area = `${line} L${W},${H} L0,${H} Z`;
  const gid = useMemo(() => uid("ag"), []);
  useEffect(() => { if (pathRef.current) setLen(pathRef.current.getTotalLength()); }, [line]);
  const move = (e: React.MouseEvent) => {
    const r = wrapRef.current!.getBoundingClientRect();
    setHi(Math.max(0, Math.min(data.length - 1, Math.round(((e.clientX - r.left) / r.width) * (data.length - 1)))));
  };
  return (
    <div ref={wrapRef} onMouseMove={move} onMouseLeave={() => setHi(null)} style={{ width: "100%", position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height={height} style={{ display: "block" }}>
        <defs><linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={accent} stopOpacity="0.34" /><stop offset="100%" stopColor={accent} stopOpacity="0" />
        </linearGradient></defs>
        {[0.25, 0.5, 0.75].map(g => <line key={g} x1="0" x2={W} y1={H * g} y2={H * g} stroke="var(--chart-grid)" strokeWidth="0.4" vectorEffect="non-scaling-stroke" />)}
        <path d={area} fill={`url(#${gid})`} />
        <path ref={pathRef} className="av2-gv-draw" d={line} fill="none" stroke={accent} strokeWidth="2" vectorEffect="non-scaling-stroke"
          strokeLinecap="round" strokeLinejoin="round" style={{ strokeDasharray: len || undefined, strokeDashoffset: 0, ["--len" as any]: len }} />
        {hi != null && <line x1={x(hi)} x2={x(hi)} y1="0" y2={H} stroke="var(--chart-axis)" strokeWidth="0.6" vectorEffect="non-scaling-stroke" />}
        {hi != null && <circle cx={x(hi)} cy={y(data[hi].v)} r="2.6" fill="var(--bg-0)" stroke={accent} strokeWidth="2" vectorEffect="non-scaling-stroke" />}
      </svg>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 10.5 }}>
        {data.map((d, i) => <span key={i} style={{ color: hi === i ? "var(--t1)" : "var(--t3)", fontWeight: hi === i ? 600 : 500 }}>{d.label}</span>)}
      </div>
      {hi != null && (
        <div style={{ position: "absolute", top: -6, left: `${(hi / (data.length - 1)) * 100}%`, transform: "translate(-50%,-100%)",
          background: "var(--bg-4)", border: "1px solid var(--b3)", borderRadius: "var(--r2)", padding: "4px 9px", fontSize: 11.5,
          fontWeight: 600, whiteSpace: "nowrap", boxShadow: "var(--shadow-md)", pointerEvents: "none", zIndex: 5 }}>
          <span style={{ color: "var(--t3)", marginRight: 6 }}>{data[hi].label}</span>
          <span style={{ fontVariantNumeric: "tabular-nums", color: "var(--t1)" }}>{valuePrefix}{fmtNum(data[hi].v)}</span>
        </div>
      )}
    </div>
  );
}

/* ── Donut ───────────────────────────────────────────────────────────────── */
export function DonutChart({ data, size = 168, thickness = 22 }:
  { data: Datum[]; size?: number; thickness?: number }) {
  const [hi, setHi] = useState<number | null>(null);
  const total = data.reduce((s, d) => s + d.v, 0);
  const R = (size - thickness) / 2, C = 2 * Math.PI * R, cx = size / 2;
  let acc = 0;
  return (
    <div style={{ display: "flex", gap: 22, alignItems: "center", flexWrap: "wrap" }}>
      <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
        <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
          <circle cx={cx} cy={cx} r={R} fill="none" stroke="var(--bg-4)" strokeWidth={thickness} opacity="0.5" />
          {data.map((d, i) => {
            const frac = d.v / total, dash = frac * C, off = -acc * C; acc += frac;
            return <circle key={i} cx={cx} cy={cx} r={R} fill="none" stroke={SERIES[i % SERIES.length]} strokeWidth={hi === i ? thickness + 3 : thickness}
              strokeDasharray={`${dash} ${C}`} strokeDashoffset={off} onMouseEnter={() => setHi(i)} onMouseLeave={() => setHi(null)}
              style={{ transition: "stroke-width .15s", cursor: "pointer" }} />;
          })}
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center" }}>
          <div>
            <div style={{ fontVariantNumeric: "tabular-nums", fontSize: 26, fontWeight: 700, letterSpacing: "-.02em", color: "var(--t1)" }}>
              {hi != null ? Math.round((data[hi].v / total) * 100) + "%" : fmtNum(total)}</div>
            <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>{hi != null ? data[hi].label : "Total"}</div>
          </div>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 9, flex: 1, minWidth: 120 }}>
        {data.map((d, i) => (
          <div key={i} onMouseEnter={() => setHi(i)} onMouseLeave={() => setHi(null)}
            style={{ display: "flex", alignItems: "center", gap: 9, cursor: "pointer", opacity: hi == null || hi === i ? 1 : 0.5, transition: "opacity .15s" }}>
            <span style={{ width: 9, height: 9, borderRadius: 3, background: SERIES[i % SERIES.length], flexShrink: 0 }} />
            <span style={{ fontSize: 12.5, color: "var(--t2)", flex: 1 }}>{d.label}</span>
            <span style={{ fontVariantNumeric: "tabular-nums", fontSize: 12.5, fontWeight: 600, color: "var(--t1)" }}>{Math.round((d.v / total) * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Pareto ──────────────────────────────────────────────────────────────── */
export function ParetoChart({ data, height = 230, accent = "var(--chart-4)" }:
  { data: Datum[]; height?: number; accent?: string }) {
  const [hi, setHi] = useState<number | null>(null);
  const lineRef = useRef<SVGPathElement>(null);
  const [len, setLen] = useState(0);
  const sorted = [...data].sort((a, b) => b.v - a.v);
  const total = sorted.reduce((s, d) => s + d.v, 0);
  let run = 0;
  const rows = sorted.map(d => { run += d.v; return { ...d, cum: run / total }; });
  const max = Math.max(...rows.map(d => d.v)) * 1.1;
  const n = rows.length, W = 100, H = 100;
  const gid = useMemo(() => uid("pg"), []);
  const cx = (i: number) => (100 / n) * i + (100 / n) / 2, cy = (c: number) => H - c * H;
  const cline = rows.map((d, i) => `${i ? "L" : "M"}${cx(i).toFixed(2)},${cy(d.cum).toFixed(2)}`).join(" ");
  useEffect(() => { if (lineRef.current) setLen(lineRef.current.getTotalLength()); }, [cline]);
  return (
    <div style={{ width: "100%" }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height={height} style={{ display: "block" }}>
        <defs><linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={accent} stopOpacity="0.95" /><stop offset="100%" stopColor={accent} stopOpacity="0.4" />
        </linearGradient></defs>
        {[0.25, 0.5, 0.75, 1].map(g => <line key={g} x1="0" x2={W} y1={H * (1 - g)} y2={H * (1 - g)} stroke="var(--chart-grid)" strokeWidth="0.4" vectorEffect="non-scaling-stroke" />)}
        <line x1="0" x2={W} y1={cy(0.8)} y2={cy(0.8)} stroke="var(--chart-3)" strokeWidth="0.7" strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
        {rows.map((d, i) => {
          const bw = (100 / n) * 0.6, x = (100 / n) * i + (100 / n) * 0.2, h = (d.v / max) * H;
          return <rect key={i} className="av2-gv-bar" x={x} y={H - h} width={bw} height={h} rx="1.2" fill={`url(#${gid})`}
            opacity={hi == null || hi === i ? 1 : 0.5} onMouseEnter={() => setHi(i)} onMouseLeave={() => setHi(null)}
            style={{ animationDelay: `${i * 55}ms`, transition: "opacity .15s", cursor: "pointer" }} />;
        })}
        <path ref={lineRef} className="av2-gv-draw" d={cline} fill="none" stroke="var(--chart-3)" strokeWidth="1.6" vectorEffect="non-scaling-stroke"
          strokeLinecap="round" strokeLinejoin="round" style={{ strokeDasharray: len || undefined, strokeDashoffset: 0, ["--len" as any]: len }} />
        {rows.map((d, i) => <circle key={i} cx={cx(i)} cy={cy(d.cum)} r="1.8" fill="var(--bg-0)" stroke="var(--chart-3)" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />)}
      </svg>
      <div style={{ display: "flex", marginTop: 8 }}>
        {rows.map((d, i) => <div key={i} style={{ flex: 1, textAlign: "center", fontSize: 10, color: hi === i ? "var(--t1)" : "var(--t3)", fontWeight: hi === i ? 600 : 500 }}>{d.label}</div>)}
      </div>
    </div>
  );
}

/* ── Sparkline ───────────────────────────────────────────────────────────── */
export function Sparkline({ values, width = 80, height = 26, up }:
  { values: number[]; width?: number; height?: number; up?: boolean }) {
  const pathRef = useRef<SVGPathElement>(null);
  const [len, setLen] = useState(0);
  const min = Math.min(...values), max = Math.max(...values), span = (max - min) || 1;
  const x = (i: number) => (i / (values.length - 1)) * width, y = (v: number) => 2 + (1 - (v - min) / span) * (height - 4);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const col = up === false ? "var(--chart-5)" : "var(--chart-2)";
  useEffect(() => { if (pathRef.current) setLen(pathRef.current.getTotalLength()); }, []);
  return (
    <svg width={width} height={height} style={{ display: "block", overflow: "visible" }}>
      <path ref={pathRef} className="av2-gv-draw" d={line} fill="none" stroke={col} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
        style={{ strokeDasharray: len || undefined, strokeDashoffset: 0, ["--len" as any]: len }} />
      <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r="2" fill={col} />
    </svg>
  );
}

/* ── Animated counter (frozen-timeline safe: initial state = final value) ──── */
export function Counter({ value, prefix = "", suffix = "", decimals = 0, dur = 900 }:
  { value: number; prefix?: string; suffix?: string; decimals?: number; dur?: number }) {
  const [n, setN] = useState(value);
  useEffect(() => {
    let raf = 0, start = 0;
    const tick = (t: number) => {
      if (!start) start = t;
      const p = Math.min(1, (t - start) / dur), e = 1 - Math.pow(1 - p, 3);
      setN(value * e);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, dur]);
  return <span style={{ fontVariantNumeric: "tabular-nums" }}>{prefix}{n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}{suffix}</span>;
}
