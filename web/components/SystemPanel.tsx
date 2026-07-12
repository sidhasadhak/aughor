"use client";

import { useEffect, useState, useCallback } from "react";
import { getDevStats, resetDevStats, getSystemFlags, setSystemFlag, setCapabilityState, type DevStats, type SystemFlag, type CapabilityState } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { PacksManager } from "@/components/PacksManager";
import { subscribeKernelEvents } from "@/lib/events";
import { formatCount, pct as fmtPct } from "@/lib/format";

function fmt(n: number | undefined | null): string {
  return n == null ? "—" : formatCount(n);
}

function pct(n: number | null | undefined): string {
  return n == null ? "—" : fmtPct(n, 1);
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
        {sub && <span className="aug-fs-xs text-zinc-500 ml-1.5">{sub}</span>}
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
      <p className="aug-fs-xs uppercase tracking-widest text-zinc-500 mb-2">{title}</p>
      <div className="bg-white/[0.03] rounded-[var(--r3)] px-3 py-0.5">
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
    // K2: node spans land as journal events; the interval is only a slow fallback.
    const t = setInterval(load, 60_000);
    const unsub = subscribeKernelEvents(() => load(), { kinds: ["node.span", "job."] });
    return () => { clearInterval(t); unsub(); };
  }, [load]);

  const handleReset = async () => {
    setResetting(true);
    await resetDevStats();
    await load();
    setResetting(false);
  };

  if (!stats) {
    return (
      <div className="flex items-center justify-center h-40 text-zinc-500 text-sm">
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
          <p className="aug-fs-xs text-zinc-500 mt-0.5">
            Uptime: {uptime(stats.uptime_seconds)}
            {lastRefresh && (
              <span className="ml-2">· refreshed {lastRefresh.toLocaleTimeString()}</span>
            )}
          </p>
        </div>
        <button
          onClick={handleReset}
          disabled={resetting}
          className="aug-fs-xs text-zinc-500 hover:text-zinc-300 border border-white/10 rounded px-2 py-1 transition-colors disabled:opacity-40"
        >
          {resetting ? "Resetting…" : "Reset counters"}
        </button>
      </div>

      {/* Capabilities — Auto-mode master + the self-gating guards (Wave 1 · E3) */}
      <Capabilities />

      {/* Feature flags */}
      <FeatureFlags />

      {/* Specialist packs — deploy console + flywheel changelog */}
      <PacksManager />

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

      <p className="aug-fs-xs text-zinc-500 text-center mt-2">
        Counters reset on server restart · auto-refreshes every 15s
      </p>
    </div>
  );
}

function FeatureFlags() {
  const [flags, setFlags] = useState<Record<string, SystemFlag>>({});
  const [busy, setBusy] = useState("");

  useEffect(() => { getSystemFlags().then(setFlags).catch(() => setFlags({})); }, []);

  const toggle = async (name: string, value: boolean) => {
    setBusy(name);
    const updated = await setSystemFlag(name, value);
    if (updated) setFlags(f => ({ ...f, [name]: updated }));
    setBusy("");
  };

  // Auto-eligible guards + the Auto-mode master live in the Capabilities section instead.
  const entries = Object.entries(flags).filter(([name, f]) => !f.auto_eligible && name !== "capabilities.auto");
  if (entries.length === 0) return null;

  return (
    <Section title="Feature flags">
      {entries.map(([name, f]) => (
        <div key={name} className="flex items-start justify-between gap-4 py-2 border-b border-white/5 last:border-0">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs text-zinc-200">{f.label}</span>
              <span className="text-[9.5px] font-mono px-1 py-0.5 rounded" style={{ background: "var(--bg-1)", color: "var(--t4)" }}>
                {f.source === "runtime" ? "override" : `env: ${f.env_var}`}
              </span>
            </div>
            <p className="aug-fs-xs text-zinc-500 mt-0.5 leading-snug">{f.description}</p>
          </div>
          <Toggle checked={f.value} disabled={busy === name} onChange={v => toggle(name, v)} />
        </div>
      ))}
    </Section>
  );
}

/** The pill switch shared by Feature flags and the Capabilities Auto-mode master. */
function Toggle({ checked, disabled, onChange }: { checked: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
      className="shrink-0 mt-0.5 rounded-[var(--r-pill)] transition-colors disabled:opacity-50"
      style={{ width: 36, height: 20, padding: 2, background: checked ? "var(--grn2)" : "var(--bg-3)", border: "1px solid var(--b1)" }}
    >
      <span style={{ display: "block", width: 14, height: 14, borderRadius: "9999px", background: "#fff",
        transform: checked ? "translateX(16px)" : "translateX(0)", transition: "transform .15s" }} />
    </button>
  );
}

function TriState({ value, disabled, onChange }: { value: CapabilityState; disabled: boolean; onChange: (s: CapabilityState) => void }) {
  const opts: CapabilityState[] = ["auto", "on", "off"];
  return (
    <div className="inline-flex shrink-0 overflow-hidden rounded-[var(--r2)]" style={{ border: "1px solid var(--b1)" }}>
      {opts.map(o => (
        <Button key={o} size="xs" variant={value === o ? "secondary" : "ghost"} disabled={disabled}
          onClick={() => onChange(o)} className="h-6 rounded-none px-2 capitalize">
          {o}
        </Button>
      ))}
    </div>
  );
}

function Capabilities() {
  const [flags, setFlags] = useState<Record<string, SystemFlag>>({});
  const [busy, setBusy] = useState("");

  useEffect(() => { getSystemFlags().then(setFlags).catch(() => setFlags({})); }, []);

  const patch = (u: SystemFlag | null, name: string) => { if (u) setFlags(f => ({ ...f, [name]: u })); setBusy(""); };
  // The master flips EVERY auto-eligible guard's effective state, so re-fetch all flags (not just the master).
  const setMaster = async (v: boolean) => { setBusy("capabilities.auto"); await setSystemFlag("capabilities.auto", v); setFlags(await getSystemFlags()); setBusy(""); };
  const setOne = async (name: string, s: CapabilityState) => { setBusy(name); patch(await setCapabilityState(name, s), name); };

  const master = flags["capabilities.auto"];
  const caps = Object.entries(flags).filter(([, f]) => f.auto_eligible).sort((a, b) => a[1].label.localeCompare(b[1].label));
  if (!master && caps.length === 0) return null;
  const autoOn = !!master?.value;

  return (
    <Section title="Capabilities">
      {master && (
        <div className="flex items-start justify-between gap-4 py-2 border-b border-white/5">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs text-zinc-200">Auto-mode</span>
              <span className="text-[9.5px] font-mono px-1 py-0.5 rounded" style={{ background: "var(--bg-1)", color: "var(--t4)" }}>master</span>
            </div>
            <p className="aug-fs-xs text-zinc-500 mt-0.5 leading-snug">
              Run the deterministic guards below on their own triggers with one switch — each one set to Auto activates only when its trigger fires.
            </p>
          </div>
          <Toggle checked={autoOn} disabled={busy === "capabilities.auto"} onChange={setMaster} />
        </div>
      )}
      {caps.map(([name, f]) => {
        const setting: CapabilityState = f.override === true ? "on" : f.override === false ? "off" : "auto";
        const active = !!f.value;
        return (
          <div key={name} className="flex items-start justify-between gap-4 py-2 border-b border-white/5 last:border-0">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs text-zinc-200">{f.label}</span>
                <span className="text-[9.5px]" style={{ color: active ? "var(--grn2)" : "var(--t4)" }}>{active ? "active" : "inactive"}</span>
              </div>
              {f.trigger && <p className="aug-fs-xs text-zinc-500 mt-0.5 leading-snug">Fires when {f.trigger}.</p>}
            </div>
            <TriState value={setting} disabled={busy === name} onChange={s => setOne(name, s)} />
          </div>
        );
      })}
    </Section>
  );
}


