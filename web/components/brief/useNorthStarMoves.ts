"use client";

/**
 * The north-star metrics of a connection, each read for its latest move — the data behind the
 * Briefing's §1. The same queries the KPI tiles ran (value, then the trend), with the same
 * cache flag, so moving the numbers into the brief costs no extra query.
 *
 * Rows arrive one by one: every metric starts `pending` under its real name, and each row
 * lands when its own queries return, so a slow warehouse shows which figure is still being
 * computed instead of a blank table.
 */
import { useEffect, useState } from "react";

import { currencySymbol, getBusinessProfile, runDirectQuery } from "@/lib/api";
import { effectiveCurrencySymbol } from "@/lib/orgSettings";
import { useOrgSettings } from "@/lib/useOrgSettings";
import { buildMoveRow, type MoveRow, type QueryOutcome } from "@/components/brief/moves";

export interface NorthStarMoves {
  /** `none`: no business profile, or no metric with a value query. */
  status: "loading" | "none" | "ready";
  industry: string;
  rows: MoveRow[];
}

const asError = (e: unknown) => (e instanceof Error ? e : new Error(String(e)));

export function useNorthStarMoves(connectionId: string, schema?: string): NorthStarMoves {
  const [state, setState] = useState<NorthStarMoves>({ status: "loading", industry: "", rows: [] });
  // The currency symbol is baked into every formatted figure, so a changed org currency re-reads.
  const orgV = useOrgSettings();

  useEffect(() => {
    if (!connectionId) { setState({ status: "none", industry: "", rows: [] }); return; }
    let alive = true;
    setState({ status: "loading", industry: "", rows: [] });
    (async () => {
      const p = await getBusinessProfile(connectionId, schema).catch(() => null);
      if (!alive) return;
      if (!p?.available || !p.profile) { setState({ status: "none", industry: "", rows: [] }); return; }
      const industry = p.profile.industry || "";
      const sym = effectiveCurrencySymbol() || currencySymbol(p.profile.currency_code);
      const metrics = (p.profile.north_star_metrics || []).filter(m => m.value_sql?.trim());
      if (!metrics.length) { setState({ status: "none", industry, rows: [] }); return; }

      setState({
        status: "ready", industry,
        rows: metrics.map(m => ({ name: m.name, valueSql: m.value_sql, state: "pending" as const })),
      });

      // A network-level failure ("Failed to fetch" — a TypeError, never an HTTP answer) is the
      // transport, not the metric: measured on the first cold load, two of six value queries
      // dropped this way and answered 200 moments later. One retry, so a hiccup does not print
      // "no value" beside a metric that works. A query the API refuses is not retried.
      const run = (sql: string, limit: number) =>
        runDirectQuery(connectionId, sql, limit, { useCache: true }).catch(async (e: unknown) => {
          if (!(e instanceof TypeError)) throw e;
          await new Promise(r => setTimeout(r, 400));
          return runDirectQuery(connectionId, sql, limit, { useCache: true });
        });

      await Promise.all(metrics.map(async (m, i) => {
        const value: QueryOutcome | Error = await run(m.value_sql, 2).catch(asError);
        // The trend is only worth a query when the value itself came back.
        const valueOk = !(value instanceof Error) && !value.error;
        const chart: QueryOutcome | Error | null = valueOk && m.chart_sql?.trim()
          ? await run(m.chart_sql, 500).catch(asError)
          : null;
        if (!alive) return;
        const row = buildMoveRow({ name: m.name, unit: m.unit_or_range, sym, valueSql: m.value_sql, value, chart });
        setState(s => ({ ...s, rows: s.rows.map((r, j) => (j === i ? row : r)) }));
      }));
    })();
    return () => { alive = false; };
  }, [connectionId, schema, orgV]);

  return state;
}
