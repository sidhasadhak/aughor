/**
 * VA-5 — the waterfall's geometry, kept out of the component so it can be tested.
 *
 * Two numbers per bar, and three rules that are easy to get wrong:
 *
 * 1. A zero-duration node still needs to be VISIBLE. Plenty of real events record no
 *    duration at all (a `user_request` has nothing to measure), and a bar of width 0 is a
 *    node the reader cannot click or even see. It gets a floor.
 * 2. A bar must not run off the end. A node whose duration outlives the computed span —
 *    which happens when a run is still in progress — is clamped rather than allowed to
 *    overflow its track.
 * 3. A missing offset is not offset zero. An event we could not place in time is drawn at
 *    the start with no width claim, never given a confident position it does not have.
 */

export interface BarGeometry {
  /** Percent from the left of the track. */
  left: number;
  /** Percent of the track's width. */
  width: number;
  /** True when the node carried no duration and is drawn at the minimum. */
  floored: boolean;
}

/** The smallest bar that is still visible and clickable, as a percentage of the track. */
export const MIN_BAR_PCT = 0.4;

export function barGeometry(
  node: { offset_ms: number | null; duration_ms: number | null },
  spanMs: number,
): BarGeometry {
  if (!Number.isFinite(spanMs) || spanMs <= 0) {
    return { left: 0, width: MIN_BAR_PCT, floored: true };
  }
  const offset = node.offset_ms;
  const left = offset == null ? 0 : Math.min(100, Math.max(0, (offset / spanMs) * 100));
  const raw = ((node.duration_ms || 0) / spanMs) * 100;
  const floored = raw < MIN_BAR_PCT;
  const width = Math.min(100 - left, Math.max(MIN_BAR_PCT, raw));
  return { left, width, floored };
}

/** The axis a set of nodes needs: the run's wall time, or the furthest bar end when that
 *  is larger (a run still in progress reports a wall shorter than its own longest node). */
export function axisSpanMs(
  nodes: { offset_ms: number | null; duration_ms: number | null }[],
  wallMs: number | null | undefined,
): number {
  const ends = nodes
    .filter((n) => n.offset_ms != null)
    .map((n) => (n.offset_ms || 0) + (n.duration_ms || 0));
  return Math.max(wallMs || 0, ...(ends.length ? ends : [0]), 1);
}
