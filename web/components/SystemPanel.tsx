"use client";

import { useEffect, useState, useCallback } from "react";
import { getDevStats, resetDevStats, type DevStats } from "@/lib/api";

function fmt(n: number | undefined | null): string {
  if (n == null) return "—";
  return n.toLocaleString();
}

function pct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function ms(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}s`;
  return `${n.toFixed(0)}ms`;
}

function uptime(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

interface StatRowProps {
  label: string;
  value: string;
  sub?: string;
  highlight?: "good" | "warn" | "neutral";
}

function StatRow({ label, value, sub, highlight }: StatRowProps) {
  const valColor =
    highlight === "good" ? "text-emerald-400" :
    highlight === "warn" ? "text-amber-400" :
    "text-zinc-200";
  return (
    <div className="flex items-baseline justify-between py-1.5 border-b border-white/5 last:border-0">
      <span className="text-xs text-zinc-400">{label}</span>
      <div className="text-right">
        <span className={`text-xs font-mono ${valColor}`}>{value}</span>
        {sub && <span className="text-[10px] text-zinc-600 ml-1.5">{sub}</span>}
      </div>
    </div>
  );
}

interface SectionProps {
  title: string;
  children: React.ReactNode;
}

function Section({ title, children }: SectionProps) {
  return (
    <div className="mb-5">
      <p className="text-[10px] uppercase tracking-widest text-zinc-600 mb-2">{title}</p>
      <div className="bg-white/[0.03] rounded-lg px-3 py-0.5">
        {children}
      </div>
    </div>
  );
}

export function SystemPanel() {
  const [stats, setStats] = useState<DevStats | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [resetting, setResetting] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await getDevStats();
      setStats(s);
      setLastRefresh(new Date());
    } catch {
      // API not reachable
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15_000);
    return () => clearInterval(t);
  }, [load]);

  const handleReset = async () => {
    setResetting(true);
    await resetDevStats();
    await load();
    setResetting(false);
  };

  if (!stats) {
    return (
      <div className="flex items-center justify-center h-40 text-zinc-600 text-sm">
        Loading stats…
      </div>
    );
  }

  const c = stats.counters;
  const t = stats.timings;
  const d = stats.derived;

  const ragHits = c.rag_hits ?? 0;
  const ragMisses = c.rag_misses ?? 0;
  const ragTotal = ragHits + ragMisses;

  const corrections = c.sql_correction_retries ?? 0;
  const correctionOk = c.sql_correction_successes ?? 0;

  return (
    <div className="p-4 overflow-y-auto h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-medium text-zinc-200">System Stats</h2>
          <p className="text-[11px] text-zinc-600 mt-0.5">
            Uptime: {uptime(stats.uptime_seconds)}
            {lastRefresh && (
              <span className="ml-2">· refreshed {lastRefresh.toLocaleTimeString()}</span>
            )}
          </p>
        </div>
        <button
          onClick={handleReset}
          disabled={resetting}
          className="text-[10px] text-zinc-500 hover:text-zinc-300 border border-white/10 rounded px-2 py-1 transition-colors disabled:opacity-40"
        >
          {resetting ? "Resetting…" : "Reset counters"}
        </button>
      </div>

      {/* Ontology */}
      <Section title="Ontology (M12)">
        <StatRow
          label="ACTION token expansions"
          value={fmt(c.action_expansions)}
          highlight={c.action_expansions > 0 ? "good" : "neutral"}
        />
        <StatRow
          label="Enrichment runs (LLM)"
          value={fmt(c.enrichment_runs)}
          highlight={c.enrichment_runs > 0 ? "warn" : "neutral"}
        />
        <StatRow
          label="Enrichment cache hits"
          value={fmt(c.enrichment_cache_hits)}
          highlight={c.enrichment_cache_hits > 0 ? "good" : "neutral"}
        />
      </Section>

      {/* ADA Investigation */}
      <Section title="ADA Investigation">
        <StatRow
          label="Tier 0 skips (baseline only)"
          value={fmt(c.tier0_skips)}
          sub="within normal variance"
          highlight={c.tier0_skips > 0 ? "good" : "neutral"}
        />
        <StatRow
          label="Tier 1 skips (no dimensional)"
          value={fmt(c.tier1_skips)}
          highlight={c.tier1_skips > 0 ? "good" : "neutral"}
        />
        <StatRow
          label="Tier 2 skips (no behavioral)"
          value={fmt(c.tier2_skips)}
          highlight={c.tier2_skips > 0 ? "good" : "neutral"}
        />
      </Section>

      {/* SQL Quality */}
      <Section title="SQL Quality">
        <StatRow
          label="Self-correction retries"
          value={fmt(corrections)}
          highlight={corrections > 0 ? "warn" : "neutral"}
        />
        <StatRow
          label="Corrections succeeded"
          value={fmt(correctionOk)}
          highlight={correctionOk > 0 ? "good" : "neutral"}
        />
        <StatRow
          label="Correction success rate"
          value={pct(d.sql_correction_success_rate)}
          highlight={
            d.sql_correction_success_rate != null
              ? d.sql_correction_success_rate > 0.7 ? "good" : "warn"
              : "neutral"
          }
        />
      </Section>

      {/* Prior Analysis RAG */}
      <Section title="Prior Analysis RAG (M1d)">
        <StatRow
          label="RAG cache hits"
          value={fmt(ragHits)}
          sub={ragTotal > 0 ? `of ${fmt(ragTotal)} investigations` : undefined}
          highlight={ragHits > 0 ? "good" : "neutral"}
        />
        <StatRow label="RAG misses (fresh)" value={fmt(ragMisses)} />
        <StatRow
          label="Hit rate"
          value={pct(d.rag_hit_rate)}
          highlight={d.rag_hit_rate != null ? (d.rag_hit_rate > 0.2 ? "good" : "neutral") : "neutral"}
        />
      </Section>

      <p className="text-[10px] text-zinc-700 text-center mt-2">
        Counters reset on server restart · auto-refreshes every 15s
      </p>
    </div>
  );
}
