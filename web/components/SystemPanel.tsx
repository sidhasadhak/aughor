"use client";

import { useEffect, useState, useCallback } from "react";
import { getDevStats, resetDevStats, getSystemFlags, setSystemFlag, setCapabilityState, type DevStats, type SystemFlag, type CapabilityState } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { PacksManager } from "@/components/PacksManager";
import { subscribeKernelEvents } from "@/lib/events";
import { getApiBase, getApiBaseSource, setApiBase, normalizeApiBase, API_BASE_DEFAULT } from "@/lib/config";
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

/**
 * Which backend this browser talks to.
 *
 * The UI can be served from anywhere while the engine runs on the user's own machine, so
 * the base URL is a per-browser setting rather than something baked into the build. The
 * panel states where the current value came from, because "why is it reading the wrong
 * data" is otherwise an invisible question.
 */
function Backend() {
  const [draft, setDraft] = useState("");
  const [effective, setEffective] = useState("");
  const [source, setSource] = useState<string>("default");
  const [probe, setProbe] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const sync = useCallback(() => {
    const now = getApiBase();
    setEffective(now);
    setDraft(now);
    setSource(getApiBaseSource());
    setProbe(null);
  }, []);

  useEffect(() => { sync(); }, [sync]);

  // Probe the URL the user TYPED, not the one in force — the whole point is to find out
  // whether it works before committing the app to it.
  const test = useCallback(async (url: string) => {
    const clean = normalizeApiBase(url);
    if (!clean) { setProbe({ ok: false, text: "Not a valid http(s) URL" }); return false; }
    setBusy(true);
    try {
      const res = await fetch(`${clean}/health`, { signal: AbortSignal.timeout(5000) });
      if (!res.ok) { setProbe({ ok: false, text: `Reached it, but it answered ${res.status}` }); return false; }
      const body = await res.json().catch(() => null);
      setProbe({ ok: true, text: body?.status === "ok" ? "Connected" : "Reached it, but it is not an Aughor backend" });
      return body?.status === "ok";
    } catch {
      // Most often: nothing listening, or the browser blocked it. Say both — a user on
      // Safari hitting the mixed-content block would otherwise read this as "server down".
      setProbe({ ok: false, text: "Could not reach it — is the backend running, and does it allow this origin?" });
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const save = useCallback(async () => {
    const clean = normalizeApiBase(draft);
    if (!clean) { setProbe({ ok: false, text: "Not a valid http(s) URL" }); return; }
    // Saved whether or not the probe succeeds: a user may legitimately point at a backend
    // they are about to start. But never saved unparseable — the settings screen that would
    // undo the mistake is itself reached through the app.
    setApiBase(clean);
    sync();
    await test(clean);
  }, [draft, sync, test]);

  const reset = useCallback(() => { setApiBase(null); sync(); }, [sync]);

  const dirty = normalizeApiBase(draft) !== effective;
  const sourceLabel =
    source === "user" ? "your setting (this browser)" :
    source === "demo" ? "the built-in demo — completed analyses only, no live engine" :
    source === "env" ? "NEXT_PUBLIC_API_URL at build time" :
    "the built-in default";

  return (
    <Section title="Backend">
      <div className="py-2">
        <p className="aug-fs-xs text-zinc-500 mb-2">
          Where this browser sends every request. Stored per browser — your data never leaves
          the machine running the backend.
        </p>
        <div className="flex items-center gap-2 mb-2">
          <input
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") void save(); }}
            spellCheck={false}
            placeholder={API_BASE_DEFAULT}
            aria-label="Backend URL"
            className="flex-1 bg-white/[0.04] rounded-[var(--r2)] px-2 py-1 aug-fs-xs
                       text-zinc-200 outline-none focus:bg-white/[0.07]"
          />
          <Button size="xs" variant="secondary" disabled={busy || !dirty} onClick={() => void save()}>
            {busy ? "checking…" : "Save"}
          </Button>
          <Button size="xs" variant="ghost" disabled={busy} onClick={() => void test(draft)}>
            Test
          </Button>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="aug-fs-xs text-zinc-500">
            In force: <span className="text-zinc-300">{effective}</span> — from {sourceLabel}.
          </span>
          {source === "user" && (
            <Button size="xs" variant="ghost" onClick={reset}>Reset to default</Button>
          )}
        </div>
        {probe && (
          <p className={`aug-fs-xs mt-1 ${probe.ok ? "text-emerald-400" : "text-amber-400"}`}>
            {probe.text}
          </p>
        )}
      </div>
    </Section>
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

      {/* Which backend this browser talks to */}
      <Backend />

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

      {/* Deep analysis */}
      <Section title="Deep analysis">
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
          sub={ragTotal > 0 ? `of ${fmt(ragTotal)} deep analyses` : undefined}
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
  const [query, setQuery] = useState("");

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

  // The disposition ratchet (flag strategy §5.1): group by declared KIND instead of one
  // flat list of ~80 toggles. Order runs decision-first: the deliberate opt-ins an
  // operator might actually change, then queued/experimental work, then what is simply on.
  // The two biggest groups collapse by default — receipted defaults are not decisions the
  // operator owes — and a search query reopens everything it matches.
  const GROUPS: Array<{ key: string; title: string; hint: string; open?: boolean }> = [
    { key: "intentionally_off", title: "Deliberate opt-ins", open: true,
      hint: "Off for a stated reason (cost, privacy, outward sends). The only toggles meant to be flipped by hand." },
    { key: "performance_profile", title: "Performance", open: true,
      hint: "Wall-clock vs concurrent LLM requests. Pick a profile matched to your provider's rate limits — it sets these four together." },
    { key: "experiment", title: "Experiments", open: true,
      hint: "Each adds model calls for a claimed gain; the note names the measurement that settles it." },
    { key: "migration", title: "Migrations", open: true,
      hint: "Temporary forks of old vs new code paths — these flags are scheduled to be deleted, not tuned." },
    { key: "graduation_queue", title: "Queued to graduate",
      hint: "Dispositioned default-on pending their receipt — safe to try, expected to become default." },
    { key: "default_on", title: "Graduated (on by default)",
      hint: "Receipted defaults. The toggle is the operator escape hatch, not a decision you owe." },
  ];
  const q = query.trim().toLowerCase();
  const matches = ([name, f]: [string, SystemFlag]) =>
    !q || name.includes(q) || f.label.toLowerCase().includes(q)
    || f.description.toLowerCase().includes(q) || (f.disposition_note || "").toLowerCase().includes(q);
  const byGroup = new Map<string, Array<[string, SystemFlag]>>();
  for (const [name, f] of entries) {
    if (!matches([name, f])) continue;
    const key = f.disposition && GROUPS.some(g => g.key === f.disposition) ? f.disposition : "default_on";
    if (!byGroup.has(key)) byGroup.set(key, []);
    byGroup.get(key)!.push([name, f]);
  }
  byGroup.forEach(list => list.sort((a, b) => a[1].label.localeCompare(b[1].label)));

  const sourceChip = (f: SystemFlag) =>
    f.source === "runtime" ? "override" : f.source === "default" ? "default" : `env: ${f.env_var}`;

  return (
    <Section title="Feature flags">
      <div className="flex items-center gap-2 pb-2">
        <input
          value={query} onChange={e => setQuery(e.target.value)}
          placeholder={`Search ${entries.length} flags — name, description, exit note…`}
          className="w-full text-xs px-2 py-1.5 rounded-[var(--r2)] outline-none"
          style={{ background: "var(--bg-1)", color: "var(--t1)", border: "1px solid var(--b1)" }}
        />
        {q && (
          <Button size="xs" variant="ghost" onClick={() => setQuery("")} className="shrink-0">Clear</Button>
        )}
      </div>
      {GROUPS.filter(g => byGroup.has(g.key)).map(g => (
        <details key={g.key} open={g.open || !!q} className="mb-2 last:mb-0">
          <summary className="cursor-pointer select-none list-none flex items-baseline gap-2 pt-1 pb-1.5">
            <span className="text-[10.5px] font-medium uppercase tracking-wide" style={{ color: "var(--t3)" }}>{g.title}</span>
            <span className="text-[9.5px]" style={{ color: "var(--t4)" }}>{byGroup.get(g.key)!.length}</span>
            <span className="aug-fs-xs leading-snug truncate" style={{ color: "var(--t4)" }}>— {g.hint}</span>
          </summary>
          {g.key === "performance_profile" && (
            <PerformanceProfile flags={flags} refresh={async () => setFlags(await getSystemFlags())} />
          )}
          {byGroup.get(g.key)!.map(([name, f]) => (
            <FlagRow key={name} name={name} f={f} chip={sourceChip(f)}
                     busy={busy === name} onToggle={v => toggle(name, v)} />
          ))}
        </details>
      ))}
    </Section>
  );
}

/** One flag row — the long registry description clamps to two lines with a more/less toggle. */
function FlagRow({ name, f, chip, busy, onToggle }: {
  name: string; f: SystemFlag; chip: string; busy: boolean; onToggle: (v: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const long = f.description.length > 180;
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-white/5 last:border-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-200">{f.label}</span>
          <span className="text-[9.5px] font-mono px-1 py-0.5 rounded" style={{ background: "var(--bg-1)", color: "var(--t4)" }}>
            {chip}
          </span>
        </div>
        <p className="aug-fs-xs text-zinc-500 mt-0.5 leading-snug"
           style={expanded || !long ? undefined
             : { display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
          {f.description}
        </p>
        {f.disposition_note && (
          <p className="aug-fs-xs mt-0.5 leading-snug italic" style={{ color: "var(--t4)" }}>{f.disposition_note}</p>
        )}
        {long && (
          <Button size="xs" variant="ghost" className="mt-0.5 h-5 px-1"
                  onClick={() => setExpanded(e => !e)}>
            {expanded ? "less" : "more"}
          </Button>
        )}
      </div>
      <Toggle checked={f.value} disabled={busy} onChange={onToggle} />
    </div>
  );
}

/** Group E as one control: the four parallelism flags set together, matched to rate limits.
 *  These are backend FLAG KEYS — wire names, frozen (renaming one strands the operator's
 *  env var and persisted override; that only happens via the backend's alias layer). */
const PERF_FLAGS = ["explore.parallel_subq", "ada.parallel_lenses", "ada.parallel_phases",
                    "ada.parallel_why_lenses"] as const;

function PerformanceProfile({ flags, refresh }: {
  flags: Record<string, SystemFlag>; refresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const vals = PERF_FLAGS.map(n => !!flags[n]?.value);
  const current = vals.every(v => v) ? "fast"
    : vals.every(v => !v) ? "conservative"
    : (flags["ada.parallel_why_lenses"]?.value && vals.filter(Boolean).length === 1) ? "balanced"
    : "custom";

  const apply = async (profile: "conservative" | "balanced" | "fast") => {
    setBusy(true);
    for (const n of PERF_FLAGS) {
      const state = profile === "fast" ? "on"
        : profile === "balanced" && n === "ada.parallel_why_lenses" ? "on"
        : "auto";                                  // auto = clear the override → code default (off)
      await setCapabilityState(n, state as CapabilityState);
    }
    await refresh();
    setBusy(false);
  };

  const OPTS: Array<{ id: "conservative" | "balanced" | "fast"; label: string; hint: string }> = [
    { id: "conservative", label: "Conservative", hint: "serial — fits a 20 RPM free tier" },
    { id: "balanced", label: "Balanced", hint: "parallel WHY lenses only (byte-identical output)" },
    { id: "fast", label: "Fast", hint: "all waves concurrent — needs provider headroom" },
  ];
  return (
    <div className="flex items-center gap-2 py-2 border-b border-white/5 flex-wrap">
      <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>Profile:</span>
      <div className="inline-flex overflow-hidden rounded-[var(--r2)]" style={{ border: "1px solid var(--b1)" }}>
        {OPTS.map(o => (
          <Button key={o.id} size="xs" variant={current === o.id ? "secondary" : "ghost"}
                  disabled={busy} onClick={() => apply(o.id)}
                  className="h-6 rounded-none px-2" title={o.hint}>
            {o.label}
          </Button>
        ))}
      </div>
      <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
        {current === "custom" ? "custom mix — pick a profile to align all four"
          : OPTS.find(o => o.id === current)?.hint}
      </span>
    </div>
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


