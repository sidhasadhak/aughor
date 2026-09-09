"use client";

/**
 * SpendPanel — PX-2 (§3.14): the governed-spend cockpit.
 *
 * Everything here existed and nothing was visible: the G4 caps store shipped with a
 * write door and no form ("caps could be read by the enforcement path and set by
 * nobody"), the usage rollup, per-model health and the cross-cutting audit feed were
 * folds with no route to an eye. This layer is those endpoints given one screen.
 *
 * Honesty rules carried from the endpoints themselves:
 *  - Cost is a FLOOR whenever any call is unpriced — never presented as a total.
 *  - A cap row shows the OBSERVED value of its own metric over its own window,
 *    because a cap without its measurement is just a wish.
 *  - `block` refuses new work with a sentence that names the number; `alert` records
 *    the breach. The form says so before the operator picks one.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  deleteUsageCap, getAuditFeed, getCostSql, getModelUsage, getRouteMix,
  getUsageCaps, getUsageReport, putUsageCap,
  type AuditFeedEvent, type ModelUsageRow, type UsageCap, type UsageReport,
} from "@/lib/api";
import { compactNumber, countNoun, formatTimestamp, pct } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { EmptyState } from "@/components/ui/empty-state";
import { csvFilename, downloadCsv, toCsv } from "@/lib/query/csv";

const cell: React.CSSProperties = { padding: "6px 10px", whiteSpace: "nowrap" };
const num: React.CSSProperties = { ...cell, textAlign: "right", fontFamily: "var(--font-mono)" };
/** The form-control look, shared by the caps form and the feed's filter bar. */
const feedSel: React.CSSProperties = { background: "var(--bg-1)", border: "1px solid var(--b1)",
  borderRadius: "var(--r2)", color: "var(--t1)", padding: "5px 8px" };

function SectionTitle({ children, sub }: { children: React.ReactNode; sub?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 10, margin: "22px 0 8px" }}>
      <span className="aug-fs-sm" style={{ fontWeight: 600, color: "var(--t1)" }}>{children}</span>
      {sub && <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>{sub}</span>}
    </div>
  );
}

function money(v: number): string {
  return `$${v.toFixed(v >= 100 ? 0 : 2)}`;
}

// ── Caps ─────────────────────────────────────────────────────────────────────

function CapMeter({ cap }: { cap: UsageCap }) {
  if (cap.observed == null || !cap.limit) return null;
  const ratio = Math.min(1, cap.observed / cap.limit);
  const over = cap.observed >= cap.limit;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 140 }}>
      <div style={{ flex: 1, height: 4, borderRadius: "var(--r-pill)", background: "var(--bg-3)", overflow: "hidden" }}>
        <div style={{ width: `${Math.round(ratio * 100)}%`, height: "100%",
          background: over ? "var(--red4)" : ratio > 0.8 ? "var(--amb4)" : "var(--grn4)" }} />
      </div>
      <span className="aug-fs-xs" style={{ color: over ? "var(--red4)" : "var(--t3)", fontFamily: "var(--font-mono)" }}>
        {cap.metric === "cost_usd" ? money(cap.observed) : compactNumber(cap.observed)}
      </span>
    </div>
  );
}

function CapsSection() {
  const [caps, setCaps] = useState<UsageCap[]>([]);
  const [vocab, setVocab] = useState<{ scopes: string[]; metrics: string[]; actions: string[] }>({ scopes: [], metrics: [], actions: [] });
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ scope: "org", subject: "*", metric: "cost_usd",
    limit: "", window_hours: "24", action: "alert" });

  const load = useCallback(async () => {
    try {
      const r = await getUsageCaps();
      setCaps(r.caps);
      setVocab({ scopes: r.scopes, metrics: r.metrics, actions: r.actions });
      setErr("");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setLoaded(true); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function declare() {
    const limit = parseFloat(form.limit);
    if (isNaN(limit) || limit < 0) { setErr("The limit must be a number ≥ 0."); return; }
    setBusy(true); setErr("");
    try {
      await putUsageCap({ scope: form.scope, subject: form.subject.trim() || "*",
        metric: form.metric, limit, window_hours: Math.max(1, parseInt(form.window_hours) || 24),
        action: form.action });
      setForm(f => ({ ...f, limit: "" }));
      await load();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function remove(cap: UsageCap) {
    setBusy(true); setErr("");
    try {
      await deleteUsageCap({ scope: cap.scope, metric: cap.metric,
        subject: cap.subject, window_hours: cap.window_hours });
      await load();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  const sel = feedSel;

  return (
    <>
      <SectionTitle sub="a cap without its measurement is just a wish — each row shows its metric, observed over its own window">
        Usage caps
      </SectionTitle>
      {loaded && caps.length === 0 && (
        <EmptyState variant="inline"
          title="No caps declared — every model call is currently uncapped.">
          Declare one below: “alert” records a breach in the governance feed; “block”
          refuses new work with a sentence that names the number.
        </EmptyState>
      )}
      {caps.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {caps.map((c, i) => (
            <div key={i} className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 12,
              padding: "8px 12px", border: "1px solid var(--b0)", borderRadius: "var(--r2)", background: "var(--bg-2)" }}>
              <span style={{ color: "var(--t1)", fontWeight: 500 }}>
                {c.metric === "cost_usd" ? money(c.limit) : compactNumber(c.limit)}{" "}
                <span style={{ color: "var(--t3)", fontWeight: 400 }}>{c.metric.replace(/_/g, " ")}</span>
              </span>
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                per {c.window_hours}h · {c.scope === "user" ? `user ${c.subject}` : "whole org"}
              </span>
              <span className="aug-fs-xs" style={{
                color: c.action === "block" ? "var(--red4)" : "var(--amb4)",
                border: `1px solid color-mix(in srgb, ${c.action === "block" ? "var(--red4)" : "var(--amb4)"} 45%, transparent)`,
                borderRadius: "var(--r-chip)", padding: "1px 8px" }}>
                {c.action === "block" ? "blocks new work" : "alerts"}
              </span>
              <span style={{ flex: 1 }} />
              <CapMeter cap={c} />
              {c.set_by && <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>set by {c.set_by}</span>}
              <Button size="xs" variant="ghost" disabled={busy} onClick={() => remove(c)}
                data-testid={`cap-remove-${c.scope}-${c.metric}`}>
                <Icon name="trash" size={12} /> Remove
              </Button>
            </div>
          ))}
        </div>
      )}
      <div className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
        marginTop: 10, padding: "10px 12px", border: "1px solid var(--b0)", borderRadius: "var(--r3)", background: "var(--bg-2)" }}>
        <select style={sel} value={form.scope} onChange={e => setForm(f => ({ ...f, scope: e.target.value }))}>
          {(vocab.scopes.length ? vocab.scopes : ["org", "user"]).map(s =>
            <option key={s} value={s}>{s === "org" ? "whole org" : "one user"}</option>)}
        </select>
        {form.scope === "user" && (
          <input style={{ ...sel, width: 150 }} placeholder="user id" value={form.subject}
            onChange={e => setForm(f => ({ ...f, subject: e.target.value }))} />
        )}
        <select style={sel} value={form.metric} onChange={e => setForm(f => ({ ...f, metric: e.target.value }))}>
          {(vocab.metrics.length ? vocab.metrics : ["calls", "total_tokens", "cost_usd"]).map(m =>
            <option key={m} value={m}>{m.replace(/_/g, " ")}</option>)}
        </select>
        <input style={{ ...sel, width: 110 }} placeholder="limit" inputMode="decimal"
          value={form.limit} onChange={e => setForm(f => ({ ...f, limit: e.target.value }))}
          data-testid="cap-limit" />
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>per</span>
        <input style={{ ...sel, width: 60 }} inputMode="numeric" value={form.window_hours}
          onChange={e => setForm(f => ({ ...f, window_hours: e.target.value }))} />
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>hours ·</span>
        <select style={sel} value={form.action} onChange={e => setForm(f => ({ ...f, action: e.target.value }))}>
          {(vocab.actions.length ? vocab.actions : ["alert", "block"]).map(a =>
            <option key={a} value={a}>{a === "block" ? "block new work" : "alert only"}</option>)}
        </select>
        <Button size="sm" disabled={busy || !form.limit.trim()} onClick={declare} data-testid="cap-declare">
          Declare the cap
        </Button>
      </div>
      {err && <p className="aug-fs-xs" style={{ color: "var(--red4)", margin: "6px 0 0" }}>{err}</p>}
    </>
  );
}

// ── Usage & model health ─────────────────────────────────────────────────────

function UsageSection() {
  const [report, setReport] = useState<UsageReport | null>(null);
  const [models, setModels] = useState<ModelUsageRow[]>([]);
  const [share, setShare] = useState<number | null | undefined>(undefined);
  const [err, setErr] = useState("");

  useEffect(() => {
    getUsageReport("provider,model").then(setReport)
      .catch(e => setErr(e instanceof Error ? e.message : String(e)));
    getModelUsage().then(r => setModels(r.models)).catch(() => setModels([]));
    getRouteMix().then(r => setShare((r as { converse_share?: number | null }).converse_share))
      .catch(() => setShare(undefined));
  }, []);

  const totals = useMemo(() => {
    if (!report) return null;
    let cost = 0, unpriced = 0, tokens = 0;
    for (const r of report.rows) { cost += r.cost_usd; unpriced += r.unpriced_calls; tokens += r.total_tokens; }
    return { cost, unpriced, tokens };
  }, [report]);

  if (err) return <p className="aug-fs-sm" style={{ color: "var(--red4)" }}>{err}</p>;
  if (!report) return <p className="aug-fs-sm" style={{ color: "var(--t4)" }}>Reading the usage rollup…</p>;

  const rows = [...report.rows].sort((a, b) => b.total_tokens - a.total_tokens).slice(0, 20);
  return (
    <>
      <SectionTitle sub={totals && totals.unpriced > 0
        ? `${money(totals.cost)} across ${countNoun(report.total_calls, "call")} — a floor, not a total: ${countNoun(totals.unpriced, "call")} carry no declared price`
        : totals ? `${money(totals.cost)} across ${countNoun(report.total_calls, "call")}` : undefined}>
        Usage by provider &amp; model
      </SectionTitle>
      {typeof share === "number" && (
        <p className="aug-fs-xs" style={{ color: "var(--t4)", margin: "0 0 8px" }}>
          Route mix: {pct(share)} of finished ask turns were served conversationally.
        </p>
      )}
      {rows.length === 0 ? (
        <EmptyState variant="inline" title="No model calls recorded yet." />
      ) : (
        <div style={{ overflowX: "auto", border: "1px solid var(--b0)", borderRadius: "var(--r3)" }}>
          <table className="aug-fs-sm" style={{ width: "100%", borderCollapse: "collapse", color: "var(--t2)" }}>
            <thead>
              <tr className="aug-fs-xs" style={{ color: "var(--t3)", textAlign: "left", borderBottom: "1px solid var(--b0)" }}>
                <th style={cell}>Provider</th><th style={cell}>Model</th>
                <th style={{ ...num }}>Calls</th><th style={{ ...num }}>Tokens</th>
                <th style={{ ...num }}>Cost</th><th style={{ ...num }}>Failure rate</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} style={{ borderBottom: "1px solid var(--b0)" }}>
                  <td style={cell}>{String(r.provider ?? "")}</td>
                  <td style={{ ...cell, fontFamily: "var(--font-mono)" }}>{String(r.model ?? "")}</td>
                  <td style={num}>{compactNumber(r.calls)}</td>
                  <td style={num}>{compactNumber(r.total_tokens)}</td>
                  <td style={num}>{r.cost_is_complete ? money(r.cost_usd) : `≥ ${money(r.cost_usd)}`}</td>
                  <td style={{ ...num, color: r.failure_rate > 0.05 ? "var(--red4)" : undefined }}>
                    {pct(r.failure_rate)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {models.some(m => m.failures > 0) && (
        <p className="aug-fs-xs" style={{ color: "var(--amb4)", margin: "6px 0 0" }}>
          {countNoun(models.reduce((n, m) => n + m.failures, 0), "model call")} failed in the
          scanned window — the worst offender is{" "}
          <span style={{ fontFamily: "var(--font-mono)" }}>
            {[...models].sort((a, b) => b.failures - a.failures)[0]?.model}
          </span>.
        </p>
      )}
    </>
  );
}

// ── The governance feed ──────────────────────────────────────────────────────

/** How many events one fetch pulls. The server filters by CATEGORY only, so every
 *  other control here narrows this window in memory. The header says so: a filter
 *  that silently searches a slice is a filter that lies. */
const FEED_WINDOW = 500;

type FeedSort = { key: "at" | "category" | "kind" | "actor"; desc: boolean };

const FEED_COLUMNS: { key: FeedSort["key"] | "summary"; label: string; width?: number }[] = [
  { key: "at",       label: "When",    width: 150 },
  { key: "category", label: "Category", width: 150 },
  { key: "kind",     label: "Event",   width: 190 },
  { key: "actor",    label: "Actor",   width: 150 },
  { key: "summary",  label: "What happened" },
];

function SortHeader({ label, active, desc, onClick, width }: {
  label: string; active: boolean; desc: boolean; onClick?: () => void; width?: number;
}) {
  return (
    <th style={{ ...cell, width, position: "sticky", top: 0, zIndex: 1,
      background: "var(--bg-2)", borderBottom: "1px solid var(--b1)" }}>
      {onClick ? (
        <Button variant="ghost" size="xs" onClick={onClick}
          className="aug-fs-xs h-auto p-0 font-normal"
          style={{ color: active ? "var(--t1)" : "var(--t3)" }}>
          {label}
          {active && <Icon name={desc ? "chevd" : "chevu"} size={10} />}
        </Button>
      ) : <span style={{ color: "var(--t3)" }}>{label}</span>}
    </th>
  );
}

function FeedRow({ ev }: { ev: AuditFeedEvent }) {
  const [open, setOpen] = useState(false);
  // Only offer the disclosure when there is something under it. A chevron that
  // expands to an empty box is worse than no chevron.
  const hasDetail = ev.detail && Object.keys(ev.detail).length > 0;
  return (
    <>
      <tr style={{ borderBottom: "1px solid var(--b0)", cursor: hasDetail ? "pointer" : "default" }}
        onClick={() => hasDetail && setOpen(o => !o)}
        data-testid="governance-feed-row">
        <td style={{ ...cell, color: "var(--t4)", fontFamily: "var(--font-mono)" }}>
          {formatTimestamp(ev.at, "short")}
        </td>
        <td style={cell}>
          <span className="aug-fs-xs" style={{ color: "var(--t3)", border: "1px solid var(--b1)",
            borderRadius: "var(--r-chip)", padding: "1px 7px", whiteSpace: "nowrap" }}>
            {ev.category.replace(/_/g, " ")}
          </span>
        </td>
        <td style={{ ...cell, color: "var(--t3)", fontFamily: "var(--font-mono)" }}>{ev.kind}</td>
        <td style={{ ...cell, color: "var(--t3)" }}>{ev.actor || "—"}</td>
        <td style={{ ...cell, color: "var(--t2)", whiteSpace: "normal" }}>
          <span style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
            <span style={{ color: "var(--t4)", width: 11, flexShrink: 0 }}>
              {hasDetail && <Icon name={open ? "chevd" : "chevr"} size={11} />}
            </span>
            {ev.summary || ev.kind}
          </span>
        </td>
      </tr>
      {open && hasDetail && (
        <tr style={{ borderBottom: "1px solid var(--b0)", background: "var(--bg-1)" }}>
          <td colSpan={FEED_COLUMNS.length} style={{ padding: "8px 12px 10px" }}>
            <pre className="aug-fs-xs" style={{ margin: 0, maxHeight: 200, overflow: "auto",
              fontFamily: "var(--font-mono)", color: "var(--t3)", whiteSpace: "pre-wrap" }}>
              {JSON.stringify(ev.detail, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

function FeedSection() {
  const [events, setEvents] = useState<AuditFeedEvent[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [category, setCategory] = useState("");
  const [actor, setActor] = useState("");
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<FeedSort>({ key: "at", desc: true });
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getAuditFeed(category, FEED_WINDOW)
      .then(r => { setEvents(r.events); setCategories(r.categories); setErr(""); })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [category]);

  // The vocabularies come from the rows themselves, never a hand-written list: a
  // hard-coded kind list goes stale the moment a sink emits a new one, and the
  // filter would then hide events it has no name for.
  const actors = useMemo(
    () => [...new Set(events.map(e => e.actor).filter(Boolean))].sort(),
    [events]);
  const kinds = useMemo(
    () => [...new Set(events.map(e => e.kind).filter(Boolean))].sort(),
    [events]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const out = events.filter(e =>
      (!actor || e.actor === actor)
      && (!kind || e.kind === kind)
      && (!needle
        || e.summary?.toLowerCase().includes(needle)
        || e.kind?.toLowerCase().includes(needle)
        || e.actor?.toLowerCase().includes(needle)
        || e.conn_id?.toLowerCase().includes(needle)));
    const dir = sort.desc ? -1 : 1;
    return out.sort((a, b) => {
      const av = String(a[sort.key] ?? ""), bv = String(b[sort.key] ?? "");
      return av === bv ? 0 : (av < bv ? -1 : 1) * dir;
    });
  }, [events, actor, kind, q, sort]);

  const filtered = rows.length !== events.length;

  function toggleSort(key: FeedSort["key"]) {
    setSort(s => s.key === key ? { key, desc: !s.desc } : { key, desc: true });
  }

  function exportCsv() {
    downloadCsv(
      csvFilename("governance-feed"),
      toCsv(["at", "category", "kind", "actor", "org_id", "conn_id", "summary"],
        rows.map(e => [e.at, e.category, e.kind, e.actor, e.org_id, e.conn_id, e.summary])),
    );
  }

  return (
    <>
      <SectionTitle sub={`every governance-relevant event, across all five audit sinks, newest first — the ${FEED_WINDOW} most recent`}>
        Governance feed
      </SectionTitle>

      {/* ── Filters ──────────────────────────────────────────────────────────
          Category is a SERVER filter (the endpoint takes it, and rejects an unknown
          one rather than answering empty). Actor, event and search narrow the
          fetched window in memory — which is why the count line below says how many
          of how many, rather than presenting a slice as the whole. */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <select style={feedSel} value={category} onChange={e => setCategory(e.target.value)}
          aria-label="Category" data-testid="feed-category">
          <option value="">All categories</option>
          {categories.map(c => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
        </select>
        <select style={feedSel} value={kind} onChange={e => setKind(e.target.value)}
          aria-label="Event" data-testid="feed-kind">
          <option value="">All events</option>
          {kinds.map(k => <option key={k} value={k}>{k}</option>)}
        </select>
        <select style={feedSel} value={actor} onChange={e => setActor(e.target.value)}
          aria-label="Actor" data-testid="feed-actor">
          <option value="">All actors</option>
          {actors.map(a => <option key={a} value={a}>{a}</option>)}
        </select>
        <input style={{ ...feedSel, width: 220 }} value={q} onChange={e => setQ(e.target.value)}
          placeholder="Search summary, event, actor…" aria-label="Search the feed"
          data-testid="feed-search" />
        {(category || kind || actor || q) && (
          <Button size="xs" variant="ghost"
            onClick={() => { setCategory(""); setKind(""); setActor(""); setQ(""); }}>
            Clear filters
          </Button>
        )}
        <span style={{ flex: 1 }} />
        <span className="aug-fs-xs" style={{ color: "var(--t4)" }} data-testid="feed-count">
          {filtered
            ? `${compactNumber(rows.length)} of ${compactNumber(events.length)} events`
            : countNoun(rows.length, "event")}
        </span>
        <Button size="xs" variant="ghost" onClick={exportCsv} disabled={rows.length === 0}>
          <Icon name="download" size={12} /> CSV
        </Button>
      </div>

      {err && <p className="aug-fs-sm" style={{ color: "var(--red4)" }}>{err}</p>}
      {!err && loading && <p className="aug-fs-sm" style={{ color: "var(--t4)" }}>Reading the audit sinks…</p>}
      {!err && !loading && rows.length === 0 && (
        <EmptyState variant="inline"
          title={events.length === 0
            ? "Nothing recorded in this category yet."
            : "No event in the window matches these filters."} />
      )}
      {!err && rows.length > 0 && (
        <div style={{ overflow: "auto", maxHeight: "58vh",
          border: "1px solid var(--b0)", borderRadius: "var(--r3)" }}>
          <table className="aug-fs-sm" style={{ width: "100%", borderCollapse: "collapse", color: "var(--t2)" }}>
            <thead>
              <tr className="aug-fs-xs" style={{ textAlign: "left" }}>
                {FEED_COLUMNS.map(c => (
                  <SortHeader key={c.key} label={c.label} width={c.width}
                    active={sort.key === c.key} desc={sort.desc}
                    onClick={c.key === "summary" ? undefined : () => toggleSort(c.key as FeedSort["key"])} />
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((e, i) => <FeedRow key={`${e.at}-${e.kind}-${i}`} ev={e} />)}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ── Cost SQL disclosure ──────────────────────────────────────────────────────

function CostSqlSection() {
  const [open, setOpen] = useState(false);
  const [sql, setSql] = useState("");
  useEffect(() => {
    if (open && !sql) getCostSql().then(r => setSql(r.sql)).catch(() => setSql("-- unavailable"));
  }, [open, sql]);
  return (
    <div style={{ marginTop: 18 }}>
      <Button size="xs" variant="ghost" onClick={() => setOpen(o => !o)}>
        <Icon name={open ? "chevd" : "chevr"} size={12} />
        The cost query — the same SQL this page's numbers come from
      </Button>
      {open && (
        <div style={{ marginTop: 6 }}>
          <pre className="aug-fs-xs" style={{ margin: 0, maxHeight: 220, overflow: "auto",
            fontFamily: "var(--font-mono)", color: "var(--t2)", background: "var(--bg-1)",
            border: "1px solid var(--b0)", borderRadius: "var(--r2)", padding: 10 }}>{sql || "…"}</pre>
          <Button size="xs" variant="ghost" onClick={() => { navigator.clipboard?.writeText(sql).catch(() => {}); }}>
            <Icon name="copy" size={12} /> Copy
          </Button>
        </div>
      )}
    </div>
  );
}

export function SpendPanel() {
  return (
    <div style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "18px 24px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span className="aug-fs-h2" style={{ fontWeight: 600, color: "var(--t1)" }}>Spend</span>
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
          what the models cost, who set the limits, and the ledger behind both
        </span>
      </div>
      <CapsSection />
      <UsageSection />
      <FeedSection />
      <CostSqlSection />
    </div>
  );
}
