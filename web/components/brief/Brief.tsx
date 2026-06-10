"use client";

/**
 * Brief — the shared vocabulary both answer modes render into.
 *
 * The design thesis (from the Databricks/Palantir samples): an answer is a
 * *document*, not a dashboard. One linear column, prose carries the analysis,
 * charts and tables are the ONLY framed objects, and all the machinery (SQL,
 * confidence factors, attribution, data gaps) lives behind a single quiet
 * disclosure rather than a stack of colored boxes.
 *
 * Insight renders a SHORT brief; Deep Analysis renders a LONG one — same
 * primitives, different length. Reuses <Chart>, <SqlResultTable>, format.ts, and
 * the type.css scale (.aug-text-* / .aug-label). Nothing here is mode-specific.
 */

import React, { useState } from "react";
import { renderEmphasis } from "@/components/brief/BriefProse";

export { BriefProse, renderEmphasis } from "@/components/brief/BriefProse";

// ── Container ──────────────────────────────────────────────────────────────────
// Single column, generous vertical rhythm, capped at a comfortable reading width
// so prose never runs edge-to-edge (charts fit the same column, like the samples).
export function Brief({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-col gap-5 ${className}`} style={{ maxWidth: 760 }}>
      {children}
    </div>
  );
}

// ── Headline — the answer in one clean line ────────────────────────────────────
export function BriefHeadline({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <h2 className={`aug-text-h2 leading-snug ${className}`}>{children}</h2>;
}

// ── Section — an optional uppercase label + children. No box, no border. ────────
export function BriefSection({
  label,
  children,
  className = "",
}: {
  label?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex flex-col gap-2.5 ${className}`}>
      {label && <div className="aug-label">{label}</div>}
      {children}
    </section>
  );
}

// ── Meta line — one muted row of context (total change · comparison · etc.) ─────
// Plain text, no pills. Children are short spans separated by a faint dot.
export function BriefMeta({
  items,
  className = "",
}: {
  items: React.ReactNode[];
  className?: string;
}) {
  const shown = items.filter(Boolean);
  if (!shown.length) return null;
  return (
    <div className={`flex items-center flex-wrap gap-x-2 gap-y-1 aug-text-xs text-zinc-500 ${className}`}>
      {shown.map((it, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span className="text-zinc-500 select-none">·</span>}
          <span>{it}</span>
        </React.Fragment>
      ))}
    </div>
  );
}

// ── Bullets — bold-lead list items (the "• The **top 10 sellers** …" pattern) ───
export function BriefBullets({
  items,
  className = "",
}: {
  items: string[];
  className?: string;
}) {
  if (!items?.length) return null;
  return (
    <ul className={`flex flex-col gap-1.5 ${className}`}>
      {items.map((it, i) => (
        <li key={i} className="aug-text-ui leading-relaxed text-zinc-300 flex gap-2">
          <span className="shrink-0 text-zinc-500 select-none mt-px">•</span>
          <span>{renderEmphasis(it)}</span>
        </li>
      ))}
    </ul>
  );
}

// ── Metrics — inline KPI row. label / value / signed-delta / context. No card. ──
export interface BriefMetric {
  label: string;
  value: string;
  delta?: string;
  context?: string;
}

export function BriefMetrics({
  metrics,
  className = "",
}: {
  metrics: BriefMetric[];
  className?: string;
}) {
  if (!metrics?.length) return null;
  return (
    <div className={`flex flex-wrap gap-x-8 gap-y-3 ${className}`}>
      {metrics.map((m, i) => (
        <div key={i} className="flex flex-col gap-0.5 min-w-0">
          {m.label && <span className="aug-text-xs text-zinc-500">{m.label}</span>}
          <span className="font-mono tabular-nums text-zinc-100 text-[15px] leading-none">
            {m.value}
            {m.delta && (
              <span
                className={`text-[12px] ml-1.5 ${m.delta.trim().startsWith("-") ? "text-red-400" : "text-emerald-400"}`}
              >
                {m.delta}
              </span>
            )}
          </span>
          {m.context && <span className="aug-text-xs text-zinc-500">{m.context}</span>}
        </div>
      ))}
    </div>
  );
}

// ── Figure — the ONLY framed block. A caption + a chart/table on a dark canvas. ─
export function BriefFigure({
  caption,
  children,
  className = "",
}: {
  caption?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <figure
      className={`rounded-md border border-zinc-700/50 overflow-hidden p-3 m-0 ${className}`}
      style={{ background: "var(--bg-0)" }}
    >
      {caption && <figcaption className="aug-text-xs text-zinc-500 mb-2">{caption}</figcaption>}
      {children}
    </figure>
  );
}

// ── Details — one quiet disclosure for all the machinery ───────────────────────
// SQL, confidence factors, attribution, data gaps, tables used, elapsed — folded
// into a single collapsed footer instead of N colored boxes in the reading flow.
export function BriefDetails({
  summary = "Methodology & details",
  defaultOpen = false,
  children,
  className = "",
}: {
  summary?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`border-t border-zinc-800/60 pt-2.5 ${className}`}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 aug-text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
      >
        <span className={`transition-transform duration-150 inline-block ${open ? "rotate-90" : ""}`}>›</span>
        {summary}
      </button>
      {open && <div className="mt-3 flex flex-col gap-4">{children}</div>}
    </div>
  );
}

// A labeled sub-block inside <BriefDetails> (e.g. "Attribution", "Confidence").
export function BriefDetailBlock({
  label,
  children,
  className = "",
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <div className="aug-label">{label}</div>
      {children}
    </div>
  );
}
