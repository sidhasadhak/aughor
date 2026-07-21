/**
 * useVizConfigs — one scope's worth of saved chart display configs, read once and written back
 * debounced.
 *
 * Charts in the Briefing that are NOT pinned cards (findings-ledger rows, digest tiles, KPI
 * trends) had nowhere to persist a display choice, so every edit died with the component — and
 * because the ledger opens one row at a time, expanding a second row destroyed the first row's
 * edits without so much as a reload. This hook gives those charts the same durability a pinned
 * card gets from `card.render`, keyed by the insight the chart is about.
 *
 * Reads the whole scope in ONE request on mount (a brief renders many charts; N round-trips as
 * rows expand would be worse than one upfront). Writes are debounced per target, because
 * `ResultChartCard` emits on every interaction — dragging a legend or typing an axis title
 * would otherwise be one PUT per keystroke.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getVizConfigs, saveVizConfig } from "@/lib/api";
import { isEmptyVizConfig, sameVizConfig, type VizConfig } from "@/components/charts/vizConfig";

const SAVE_DEBOUNCE_MS = 600;

export function useVizConfigs(scopeKey: string) {
  // Both the data AND the scope it belongs to, in ONE state value. Keeping them together is
  // what lets `loaded` be DERIVED rather than set — no synchronous setState in the effect, and
  // no window where a previous scope's configs are still readable under a new scopeKey.
  const [state, setState] = useState<{ scope: string | null; configs: Record<string, VizConfig> }>(
    { scope: null, configs: {} },
  );
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  // Latest scope wins: a schema switch mid-flight must not paint the previous scope's configs.
  const scopeRef = useRef(scopeKey);

  useEffect(() => {
    scopeRef.current = scopeKey;
    if (!scopeKey) { setState({ scope: "", configs: {} }); return; }
    let alive = true;
    getVizConfigs(scopeKey)
      .then(r => {
        if (alive && scopeRef.current === scopeKey) {
          setState({ scope: scopeKey, configs: (r ?? {}) as Record<string, VizConfig> });
        }
      })
      .catch(() => {
        // Best-effort — a missing display preference must never block the brief. Mark the
        // scope loaded with nothing, so charts render at their defaults instead of waiting.
        if (alive && scopeRef.current === scopeKey) setState({ scope: scopeKey, configs: {} });
      });
    return () => { alive = false; };
  }, [scopeKey]);

  const configs = state.scope === scopeKey ? state.configs : {};
  // `loaded` gates the charts: rendering before the fetch lands would mount them with the
  // DEFAULT config, and `ResultChartCard` seeds its controls once — the saved config would
  // then never be applied. Callers use it to hold off mounting a chart.
  const loaded = state.scope === scopeKey;

  // Flush nothing on unmount by design: a pending debounce that fires after the user has left
  // would write a config for a scope they are no longer in. Clear them instead.
  useEffect(() => {
    const t = timers.current;
    return () => { t.forEach(clearTimeout); t.clear(); };
  }, []);

  const save = useCallback((targetId: string, config: VizConfig) => {
    if (!targetId) return;
    setState(prev => (sameVizConfig(prev.configs[targetId], config)
      ? prev
      : { ...prev, configs: { ...prev.configs, [targetId]: config } }));
    const existing = timers.current.get(targetId);
    if (existing) clearTimeout(existing);
    const scopeAtEdit = scopeRef.current;
    timers.current.set(targetId, setTimeout(() => {
      timers.current.delete(targetId);
      // An empty config means "back to default" — the backend deletes the row rather than
      // pinning a copy of today's default.
      void saveVizConfig(scopeAtEdit, targetId, isEmptyVizConfig(config) ? {} : (config as Record<string, unknown>));
    }, SAVE_DEBOUNCE_MS));
  }, []);

  const configFor = useCallback((targetId: string): VizConfig | null => configs[targetId] ?? null, [configs]);

  return { configFor, save, loaded };
}
