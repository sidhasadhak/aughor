"use client";

/**
 * The one time range for the whole Agent Ops surface.
 *
 * Every fold on this surface used to be row-windowed — "the last 5,000 rows" — so a quiet
 * week and a busy hour drew the same width, and the Overview showed minute buckets over an
 * hour beside hourly buckets over a day IN THE SAME TABLE. One range, held here, passed to
 * every panel, and written to the URL so a view can be sent to somebody.
 *
 * A brush over the chart narrows the SAME range rather than introducing a second one:
 * `since`/`until` win when set, and the picker shows which named range they came from. Two
 * independent windows on one page is the "silently divergent time ranges" anti-pattern —
 * two tiles disagreeing with no visible reason.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

export const RANGE_KEYS = ["1h", "6h", "24h", "7d", "30d"] as const;
export type RangeKey = (typeof RANGE_KEYS)[number];

export const RANGE_LABELS: Record<RangeKey, string> = {
  "1h": "Last hour", "6h": "Last 6 hours", "24h": "Last 24 hours",
  "7d": "Last 7 days", "30d": "Last 30 days",
};

export type TimeRange = {
  /** The named range the picker sits on. */
  key: RangeKey;
  /** A brushed sub-window, or null when the whole named range is in play. */
  since: string | null;
  until: string | null;
};

export const DEFAULT_RANGE: TimeRange = { key: "24h", since: null, until: null };

/** The query params for an API call — a brush wins over the named range. */
export function rangeParams(r: TimeRange): { range?: string; since?: string; until?: string } {
  if (r.since && r.until) return { since: r.since, until: r.until };
  return { range: r.key };
}

/** What the header should say this window is. */
export function rangeLabel(r: TimeRange): string {
  if (r.since && r.until) return "custom window";
  return RANGE_LABELS[r.key].toLowerCase();
}

const PARAM = "aoRange";

function readUrl(): TimeRange {
  if (typeof window === "undefined") return DEFAULT_RANGE;
  try {
    const p = new URLSearchParams(window.location.search);
    const raw = p.get(PARAM);
    if (!raw) return DEFAULT_RANGE;
    const [key, since, until] = raw.split("~");
    return {
      key: (RANGE_KEYS as readonly string[]).includes(key) ? (key as RangeKey) : "24h",
      since: since || null,
      until: until || null,
    };
  } catch {
    return DEFAULT_RANGE;
  }
}

/**
 * Range state, mirrored into the URL. `replaceState` rather than `push` — a range change
 * is a lens on the same page, not a new place, and filling the back button with twelve
 * range flips is how a dashboard becomes impossible to leave.
 */
export function useTimeRange(): {
  range: TimeRange;
  setKey: (k: RangeKey) => void;
  setBrush: (since: string, until: string) => void;
  clearBrush: () => void;
} {
  const [range, setRange] = useState<TimeRange>(DEFAULT_RANGE);

  // Read the URL after mount — during SSR there is no window, and reading it in the
  // initializer would hand the server and the client two different states to reconcile.
  useEffect(() => { setRange(readUrl()); }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const p = new URLSearchParams(window.location.search);
    const value = range.since && range.until
      ? `${range.key}~${range.since}~${range.until}` : range.key;
    if (value === "24h") p.delete(PARAM); else p.set(PARAM, value);
    const qs = p.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
  }, [range]);

  const setKey = useCallback((k: RangeKey) => setRange({ key: k, since: null, until: null }), []);
  const setBrush = useCallback((since: string, until: string) =>
    setRange(r => ({ ...r, since, until })), []);
  const clearBrush = useCallback(() => setRange(r => ({ ...r, since: null, until: null })), []);

  return useMemo(() => ({ range, setKey, setBrush, clearBrush }),
                 [range, setKey, setBrush, clearBrush]);
}
