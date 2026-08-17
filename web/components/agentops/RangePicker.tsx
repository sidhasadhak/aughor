"use client";

/**
 * The surface's one range control, rendered into `Workspace.headerControls` — the slot the
 * shell has always had for exactly this and that Agent Ops never used.
 *
 * When a brush is active the picker says so and offers to clear it, rather than silently
 * showing "24h" selected while the panels below draw forty minutes. A control that lies
 * about the window is worse than no control.
 */
import { Button } from "@/components/ui/button";

import { RANGE_KEYS, RANGE_LABELS, type RangeKey, type TimeRange } from "./useTimeRange";

export function RangePicker({ range, onKey, onClearBrush }: {
  range: TimeRange;
  onKey: (k: RangeKey) => void;
  onClearBrush: () => void;
}) {
  const brushed = Boolean(range.since && range.until);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
      <span className="aug-label" style={{ color: "var(--t2)", whiteSpace: "nowrap" }}>Range</span>
      <div role="group" aria-label="Time range"
        style={{
          display: "flex", gap: 1, padding: 2, background: "var(--bg-2)",
          border: "1px solid var(--b1)", borderRadius: "var(--r3)",
        }}>
        {RANGE_KEYS.map(k => {
          const on = range.key === k && !brushed;
          return (
            <Button key={k} variant="ghost" size="sm"
              onClick={() => onKey(k)}
              title={RANGE_LABELS[k]}
              aria-pressed={on}
              className="aug-fs-sm"
              style={{
                height: 22, padding: "0 9px", borderRadius: "var(--r2)",
                fontFamily: "var(--font-mono)",
                background: on ? "var(--blue2)" : "transparent",
                color: on ? "var(--blue5)" : "var(--t2)",
              }}>
              {k}
            </Button>
          );
        })}
      </div>
      {brushed && (
        <Button variant="ghost" size="sm" onClick={onClearBrush}
          className="aug-fs-sm"
          title="Clear the brushed window and go back to the named range"
          style={{ height: 22, padding: "0 8px", color: "var(--blue4)" }}>
          brushed · clear
        </Button>
      )}
    </div>
  );
}
