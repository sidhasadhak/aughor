"use client";

/**
 * The surface's one range control, rendered into `Workspace.toolbar` — the 36px row under the
 * header for what SCOPES the view. It lived in the header until 2026-09-25, where at 1024px it
 * drew under the layer switcher (docs/UI_UX_STUDY_2026-09-25.md §2.3).
 *
 * When a brush is active the picker says so and offers to clear it, rather than silently
 * showing "24h" selected while the panels below draw forty minutes. A control that lies
 * about the window is worse than no control.
 *
 * Drawn as the segmented control (INSTRUMENT.md §5), the same grammar as the layer switcher
 * beside it: the selected range is filled and --b2 hairlines divide the rest. The keys are
 * figures, set like every figure in the UI face with tabular numerals.
 */
import { Button } from "@/components/ui/button";

import { RANGE_KEYS, RANGE_LABELS, type RangeKey, type TimeRange } from "./useTimeRange";
import { Segmented } from "@/components/ui/segmented";

export function RangePicker({ range, onKey, onClearBrush }: {
  range: TimeRange;
  onKey: (k: RangeKey) => void;
  onClearBrush: () => void;
}) {
  const brushed = Boolean(range.since && range.until);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
      <span className="aug-label" style={{ whiteSpace: "nowrap" }}>Range</span>
      {/* A brushed window is none of the named ranges, so none is chosen while it stands. */}
      <Segmented label="Time range" value={brushed ? "" : range.key} onChange={onKey}
        options={RANGE_KEYS.map(k => ({ value: k, label: k, title: RANGE_LABELS[k] }))} />
      {brushed && (
        <Button variant="link" size="xs" onClick={onClearBrush}
          title="Clear the brushed window and go back to the named range">
          brushed · clear
        </Button>
      )}
    </div>
  );
}
