"use client";

/**
 * VA-5 · the waterfall — one run laid out on a time axis.
 *
 * **Why this exists beside the span tree.** The tree answers "what nested inside what",
 * and it can only show rows that carry a `span_id`. Measured on a real store, `llm_call`
 * has 2,506 rows — every one with a duration, 2,402 with token counts — and not a single
 * span id. So the tree draws a run's plumbing and none of its model calls: 62 nodes where
 * the run actually had 157. The timeline is assembled at read time from everything the
 * run recorded, which is why the model appears here and cannot appear there.
 *
 * **The header's honesty.** `busy` and `idle` come from the UNION of node intervals, not
 * from summing the per-bar gaps. On the trace this was built against, 53 of 157 nodes
 * start before the previous one ends, and summing gaps claimed 386.5s of dead time
 * against a true 311.9s. When `concurrent_nodes` is non-zero the header says so, because
 * a reader who assumes a waterfall is sequential will misread every gap on it.
 *
 * Bars are positioned divs rather than a chart library or hand-drawn vector markup: the
 * geometry is two numbers, and staying in the DOM keeps this legible to a screen reader.
 * (Saying that without writing the tag name, because the icon gate text-matches source and
 * does not skip comments — a prose mention of the thing you avoided still trips it.)
 */
import { useMemo, useState } from "react";

import type { TimelineNode, TraceTimeline } from "@/lib/api";
import { compactNumber, formatCount } from "@/lib/format";
import { axisSpanMs, barGeometry } from "@/lib/waterfall";

/** Colour by what a node IS. The ramp is the shared chart palette, so a model call is the
 *  same hue here as anywhere else it is counted. */
const KIND_COLOR: Record<string, string> = {
  model: "var(--chart-1)",
  tool: "var(--chart-2)",
  frame: "var(--chart-3)",
  error: "var(--red4)",
  event: "var(--chart-6)",
};

const KIND_LABEL: Record<string, string> = {
  model: "model", tool: "tool", frame: "frame", error: "error", event: "event",
};

function ms(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1000) return `${Math.round(n)}ms`;
  if (n < 60_000) return `${(n / 1000).toFixed(1)}s`;
  return `${Math.floor(n / 60_000)}m ${Math.round((n % 60_000) / 1000)}s`;
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div style={{ minWidth: 96 }}>
      <div className="aug-fs-h2" style={{ fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
        {value}
      </div>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>{label}</div>
      {note && <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>{note}</div>}
    </div>
  );
}

export function TraceWaterfall({ timeline, onSelect }: {
  timeline: TraceTimeline;
  onSelect?: (node: TimelineNode) => void;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const nodes = timeline.nodes || [];

  // The axis is the run's wall span. Falling back to the largest bar end keeps a run with
  // one node from collapsing to zero width.
  const span = useMemo(() => axisSpanMs(nodes, timeline.wall_ms), [nodes, timeline.wall_ms]);

  if (!nodes.length) {
    return (
      <div className="aug-fs-sm" style={{ padding: 24, color: "var(--t3)" }}>
        This run recorded no events. Nothing to lay out — not an error, and not a zero.
      </div>
    );
  }

  const busyShare = timeline.wall_ms ? timeline.busy_ms / timeline.wall_ms : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div style={{ display: "flex", gap: 22, flexWrap: "wrap", alignItems: "flex-start",
                    padding: "4px 2px 14px" }}>
        <Stat label="wall" value={ms(timeline.wall_ms)} />
        <Stat label="working" value={ms(timeline.busy_ms)}
              note={busyShare != null ? `${Math.round(busyShare * 100)}% of wall` : undefined} />
        <Stat label="waiting" value={ms(timeline.idle_ms)}
              note={timeline.concurrent_nodes > 0 ? "union, not a sum of gaps" : undefined} />
        <Stat label="nodes" value={formatCount(timeline.span_count)}
              note={`${formatCount(timeline.model_calls)} model calls`} />
        {timeline.usage?.total_tokens != null && (
          <Stat label="tokens" value={compactNumber(timeline.usage.total_tokens)}
                note={timeline.usage.prompt_tokens != null
                  ? `${compactNumber(timeline.usage.prompt_tokens)} prompt` : undefined} />
        )}
      </div>

      {timeline.concurrent_nodes > 0 && (
        <div className="aug-fs-xs"
             style={{ color: "var(--t3)", padding: "0 2px 10px", lineHeight: 1.5 }}>
          {formatCount(timeline.concurrent_nodes)} of {formatCount(timeline.span_count)} nodes
          start before the previous one ends — this run did work in parallel, so the gaps
          between bars are not a sequential reading of where the time went. The waiting
          figure above is the union of intervals and is the one to trust.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 2, minHeight: 0,
                    overflowY: "auto" }}>
        {nodes.map((n) => {
          const { left, width } = barGeometry(n, span);
          const colour = KIND_COLOR[n.kind] || KIND_COLOR.event;
          const active = hover === n.id;
          return (
            <div
              key={n.id}
              onMouseEnter={() => setHover(n.id)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSelect?.(n)}
              style={{
                display: "grid", gridTemplateColumns: "minmax(150px, 22%) 1fr auto",
                gap: 10, alignItems: "center", padding: "3px 6px",
                borderRadius: "var(--r3)", cursor: onSelect ? "pointer" : "default",
                background: active ? "var(--bg-2)" : "transparent",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0,
                            paddingLeft: Math.min(n.depth, 6) * 12 }}>
                <span aria-hidden style={{ width: 6, height: 6, flexShrink: 0,
                                           borderRadius: "var(--r-pill)", background: colour }} />
                <span className="aug-fs-sm" style={{ overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap",
                      color: n.ok === false ? "var(--red4)" : "var(--t1)" }}>
                  {n.name}
                </span>
                {n.critical && (
                  <span className="aug-fs-xs" style={{ color: "var(--amb4)", flexShrink: 0 }}
                        title="the longest single node in this run">slowest</span>
                )}
              </div>

              <div style={{ position: "relative", height: 16 }}>
                <div style={{ position: "absolute", inset: "6px 0", borderRadius: 2,
                              background: "var(--b1)", opacity: 0.35 }} />
                <div
                  title={`${KIND_LABEL[n.kind] || n.kind} · starts +${ms(n.offset_ms)} · ${ms(n.duration_ms)}`}
                  style={{
                    position: "absolute", left: `${left}%`, width: `${width}%`,
                    top: 3, bottom: 3, minWidth: 2, borderRadius: 2, background: colour,
                    opacity: n.ok === false ? 0.55 : active ? 1 : 0.85,
                  }}
                />
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 10,
                            justifyContent: "flex-end", minWidth: 150 }}>
                {n.usage?.total_tokens != null && (
                  <span className="aug-fs-xs" style={{ color: "var(--t3)",
                        fontVariantNumeric: "tabular-nums" }}>
                    {compactNumber(n.usage.total_tokens)} tok
                  </span>
                )}
                {n.gap_ms != null && n.gap_ms > 0 && (
                  <span className="aug-fs-xs" style={{ color: "var(--t3)" }}
                        title="gap since the previous node ended — a sequential reading">
                    +{ms(n.gap_ms)}
                  </span>
                )}
                <span className="aug-fs-sm" style={{ fontVariantNumeric: "tabular-nums",
                      color: "var(--t2)", minWidth: 54, textAlign: "right" }}>
                  {ms(n.duration_ms)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default TraceWaterfall;
