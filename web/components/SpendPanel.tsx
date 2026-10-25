"use client";

/**
 * Spend — what model calls cost, what is unknown, and what to fix.
 *
 * Laid out as the approved mockup lays it out (`design-mockups/spend.html`, 2026-10-10; the law is
 * `aughor-v2/CLARITY.md`): four figures, then what needs a person in amber, then two pictures side
 * by side (tokens by model · where tokens go), then the governance window said once per kind of
 * thing that happened. 5,257 words a reader faced became about two hundred; nothing left the screen
 * that a person could act on — the caps editor opens from "Set a cap" or "Edit", the full feed with
 * its filters, sort, per-event detail and CSV from "Full feed", the cost query and the route mix
 * from "Details".
 *
 * Honesty rules carried from the endpoints themselves, and drawn rather than written:
 *  - Cost is a FLOOR whenever any call is unpriced ("Spent · at least", and the share priced as an
 *    amber chip); with no priced call it is not a number at all. An unpriced model's bar is
 *    hatched grey — unknown, not zero.
 *  - A cap row shows the OBSERVED value of its own metric over its own window: a cap without its
 *    measurement is a wish. No cap is said in amber: nothing stops a runaway run.
 *  - `block` refuses new work with a sentence that names the number; `alert` records the breach.
 *    The form says so before the operator picks one.
 *  - The governance window says how far back it reaches, and a flag the platform raised on its own
 *    reads is named as that, not counted as an alarm.
 */

import React, { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import {
  deleteUsageCap, downloadAuditFeed, getAuditFeed, getConnections, getCostSql, getRouteMix, getSystemFlags,
  getUsageCaps, getUsageReport, getUsageSummary, putUsageCap,
  type AuditFeedEvent, type UsageCap, type UsageCapsResponse, type UsageReport, type UsageSummary,
} from "@/lib/api";
import { compactNumber, countNoun, formatCount, formatTimestamp, pct } from "@/lib/format";
import {
  capAmount, dayAfter, eventKey, failedLine, foldFeed, modelBars, money, sinceWords, spendTotals, spentFigure,
  tightestCap, tokens, unpricedModels, whereTokensGo,
  type FeedFold, type FoldTone,
} from "@/lib/spend";
import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import { EmptyState } from "@/components/ui/empty-state";
import { Loading, ReadFailed } from "@/components/ui/states";
import { SelectField } from "@/components/ui/select";
import { Table, TableHeader, TableBody, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { csvFilename, downloadCsv, toCsv } from "@/lib/query/csv";

const card: CSSProperties = {
  background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "12px 14px", minWidth: 0,
};
const muted: CSSProperties = { color: "var(--t3)" };
const oneLine: CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 };
const tabular: CSSProperties = { fontVariantNumeric: "tabular-nums" };
const row: CSSProperties = { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" };
/** Unknown, not zero: the de-emphasis grey, hatched (CLARITY §4). */
const HATCH = "repeating-linear-gradient(135deg, var(--chart-deemph) 0 4px, color-mix(in srgb, var(--chart-deemph) 45%, transparent) 4px 7px)";
/** The form-control look, shared by the caps form and the feed's filter bar. */
const field: CSSProperties = { background: "var(--bg-1)", border: "1px solid var(--b1)",
  borderRadius: "var(--r2)", color: "var(--t1)", padding: "5px 8px" };
/** How many events one read pulls. The server filters by CATEGORY only, so every other control
 *  narrows this window in memory — and the screen says how far back it reaches. */
const FEED_WINDOW = 500;
/** `/usage` reads the newest this-many calls by default; past it, "all time" would be a lie. */
const USAGE_SCAN = 5000;

const say = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** A section's small uppercase label, with what it says at its right end. */
function Label({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, color: "var(--t3)",
      textTransform: "uppercase", letterSpacing: ".06em" }}>
      {children}
      {right && <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }}>{right}</span>}
    </div>
  );
}

/** A caveat as an amber chip. */
function AmberChip({ children }: { children: ReactNode }) {
  return (
    <span className="aug-fs-xs" style={{ background: "var(--amb1)", color: "var(--amb4)", padding: "2px 8px",
      borderRadius: "var(--r-pill)", whiteSpace: "nowrap", ...tabular }}>{children}</span>
  );
}

function Figure({ label, value, tone, testId, right, children }: {
  label: string; value: string; tone?: string; testId: string; right?: ReactNode; children?: ReactNode;
}) {
  return (
    <section aria-label={label} data-testid={testId} style={card}>
      <div className="aug-fs-sm" style={{ ...muted, display: "flex", alignItems: "center", gap: 8 }}>
        {label}{right && <span style={{ marginLeft: "auto" }}>{right}</span>}
      </div>
      <div className="aug-fs-display" style={{ fontWeight: 600, margin: "4px 0", color: tone ?? "var(--t1)", ...tabular }}>{value}</div>
      <div className="aug-fs-sm" style={{ ...muted, ...oneLine }}>{children}</div>
    </section>
  );
}

/** One row of a horizontal bar picture: name and a muted line · the bar · the figure. */
function Bar({ name, sub, value, share, fill, title }: {
  name: string; sub: string; value: string; share: number; fill: string; title: string;
}) {
  return (
    <>
      <span style={oneLine} title={title}>
        <span className="aug-fs-sm" style={{ color: "var(--t1)" }}>{name}</span>
        <span className="aug-fs-xs" style={{ ...muted, ...oneLine, display: "block" }}>{sub}</span>
      </span>
      <span title={title} style={{ height: 10, borderRadius: "var(--r-pill)", background: "var(--bg-3)", overflow: "hidden" }}>
        <i data-unknown={fill === HATCH ? "true" : undefined}
          style={{ display: "block", height: "100%", borderRadius: "var(--r-pill)", background: fill,
            width: share > 0 ? `${Math.max(0.6, share * 100)}%` : 0 }} />
      </span>
      <span className="aug-fs-sm" title={title} style={{ textAlign: "right", color: "var(--t2)", ...tabular }}>{value}</span>
    </>
  );
}

const bars: CSSProperties = {
  display: "grid", gridTemplateColumns: "150px minmax(0, 1fr) 64px", gap: "7px 10px", alignItems: "center",
};

function Swatch({ fill }: { fill: string }) {
  return <i style={{ display: "inline-block", width: 12, height: 8, borderRadius: "var(--r1)", background: fill, marginRight: 5, verticalAlign: "middle" }} />;
}

// ── The page ─────────────────────────────────────────────────────────────────

export function SpendPanel() {
  const [report, setReport] = useState<UsageReport | null>(null);
  const [reportErr, setReportErr] = useState<string | null>(null);
  const [day, setDay] = useState<UsageSummary | null>(null);
  const [dayErr, setDayErr] = useState<string | null>(null);
  const [week, setWeek] = useState<UsageSummary | null>(null);
  const [caps, setCaps] = useState<UsageCapsResponse | null>(null);
  const [capsErr, setCapsErr] = useState<string | null>(null);
  const [capsOpen, setCapsOpen] = useState(false);
  const [details, setDetails] = useState(false);

  const readUsage = useCallback(() => {
    setReportErr(null);
    getUsageReport("provider,model").then(setReport).catch(e => setReportErr(say(e)));
  }, []);
  const readDay = useCallback(() => {
    setDayErr(null);
    getUsageSummary({ range: "24h" }).then(setDay).catch(e => setDayErr(say(e)));
  }, []);
  const readCaps = useCallback(async () => {
    try { setCaps(await getUsageCaps()); setCapsErr(null); } catch (e) { setCapsErr(say(e)); }
  }, []);
  useEffect(() => {
    readUsage();
    readDay();
    readCaps();
    // The week only feeds one muted line under the call count; a failed read leaves the line out.
    getUsageSummary({ range: "7d" }).then(setWeek).catch(() => setWeek(null));
  }, [readUsage, readDay, readCaps]);

  const totals = useMemo(() => (report ? spendTotals(report) : null), [report]);
  const spent = totals ? spentFigure(totals) : null;
  const unpriced = report ? unpricedModels(report) : [];
  const noCap = caps !== null && caps.caps.length === 0;
  const cap = caps ? tightestCap(caps.caps) : null;
  const capOver = cap?.observed != null && cap.limit > 0 && cap.observed >= cap.limit;

  return (
    <div style={{ flex: 1, minWidth: 0, overflowY: "auto" }}>
      <div style={{ padding: "14px 22px 28px", display: "flex", flexDirection: "column", gap: 14, width: "100%" }}>
        <div data-testid="spend-figures" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 14 }}>
          <Figure testId="spend-spent" label={spent?.label ?? "Spent"} value={spent?.value ?? "—"}
            tone={spent?.unknown ? "var(--t3)" : undefined}>
            {reportErr ? "could not be read"
              : spent?.caveat ? <AmberChip>{spent.caveat}</AmberChip> : spent?.note}
          </Figure>
          <Figure testId="spend-calls" label="Model calls" value={totals ? formatCount(totals.calls) : "—"}>
            {week ? `${formatCount(week.calls)} in the last 7 days` : null}
          </Figure>
          <Figure testId="spend-failed" label="Failed" value={totals ? formatCount(totals.failures) : "—"}>
            {totals ? failedLine(totals) : null}
          </Figure>
          <Figure testId="spend-cap" label="Spend cap"
            value={capsErr ? "—" : caps === null ? "—" : cap ? capAmount(cap.metric, cap.limit) : "None"}
            tone={noCap ? "var(--amb4)" : capOver ? "var(--red4)" : undefined}
            right={cap && !capsOpen ? <Button size="xs" variant="ghost" onClick={() => setCapsOpen(true)}>Edit</Button> : null}>
            {capsErr ? "could not be read"
              : noCap ? "nothing stops a runaway run"
              : cap ? [
                cap.observed != null ? `${capAmount(cap.metric, cap.observed)} so far` : "",
                `per ${cap.window_hours}h`,
                cap.action === "block" ? "blocks new work" : "alerts",
                caps && caps.caps.length > 1 ? `+${caps.caps.length - 1} more` : "",
              ].filter(Boolean).join(" · ") : null}
          </Figure>
        </div>

        {capsErr && <ReadFailed what="the spend caps" error={capsErr} onRetry={readCaps} />}

        {(unpriced.length > 0 || noCap) && (
          <section aria-label="Needs you" data-testid="spend-needs"
            style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", padding: "10px 14px",
              borderRadius: "var(--r3)", background: "var(--amb1)" }}>
            <span style={{ flex: "1 1 320px", minWidth: 0 }}>
              {totals && unpriced.length > 0 ? (
                <>
                  <span className="aug-fs-chrome" style={{ fontWeight: 500, color: "var(--t1)", display: "block" }}
                    title="A price is declared by the operator (AUGHOR_MODEL_PRICES) or published in the provider's catalogue; a model with neither stays unpriced.">
                    {totals.unpriced === 1 ? "1 call has no price" : `${formatCount(totals.unpriced)} calls have no price`}, so the real spend is unknown
                  </span>
                  <span className="aug-fs-sm" style={{ color: "var(--t2)", display: "block", ...oneLine }}>
                    {unpriced.slice(0, 3).map(m => `${m.name} · ${countNoun(m.calls, "call")}`).join("  ·  ")}
                    {unpriced.length > 3 ? `  ·  +${unpriced.length - 3} more` : ""}
                  </span>
                </>
              ) : (
                <span className="aug-fs-chrome" style={{ fontWeight: 500, color: "var(--t1)" }}>
                  No spend cap is set — nothing stops a runaway run
                </span>
              )}
            </span>
            {noCap && !capsOpen && <Button size="sm" variant="secondary" onClick={() => setCapsOpen(true)}>Set a cap</Button>}
          </section>
        )}

        {capsOpen && caps && <CapsEditor data={caps} onChanged={readCaps} onClose={() => setCapsOpen(false)} />}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 14 }}>
          <ModelsCard report={report} error={reportErr} onRetry={readUsage} />
          <WhereCard day={day} error={dayErr} onRetry={readDay} />
        </div>

        <GovernanceCard />

        <div>
          <Button size="xs" variant="ghost" aria-expanded={details} onClick={() => setDetails(o => !o)}>
            Details <Icon name={details ? "chevu" : "chevd"} size={12} />
          </Button>
          {details && <Details />}
        </div>
      </div>
    </div>
  );
}

// ── Tokens by model · where tokens go ────────────────────────────────────────

function ModelsCard({ report, error, onRetry }: { report: UsageReport | null; error: string | null; onRetry: () => void }) {
  const rows = report ? modelBars(report) : [];
  const top = Math.max(1, ...rows.map(r => r.tokens));
  const anyUnknown = rows.some(r => r.unpriced);
  const anyPriced = rows.some(r => !r.unpriced && !r.folded);
  const scope = report && report.total_calls >= USAGE_SCAN ? `newest ${formatCount(USAGE_SCAN)} calls` : "all time";
  return (
    <section aria-label="Tokens by model" data-testid="spend-models" style={card}>
      <Label right={<span className="aug-fs-xs" style={muted}>{scope}</span>}>Tokens by model</Label>
      {error ? <ReadFailed what="the usage rollup" error={error} onRetry={onRetry} />
        : !report ? <Loading what="the usage rollup" />
        : rows.length === 0 ? <div className="aug-fs-sm" style={muted}>No model calls recorded yet.</div>
        : (
          <>
            <div style={bars}>
              {rows.map(r => (
                <Bar key={r.key} name={r.name} sub={r.sub} value={tokens(r.tokens)} share={r.tokens / top} title={r.title}
                  fill={r.unpriced ? HATCH : r.folded ? "var(--chart-deemph)" : "var(--chart-1)"} />
              ))}
            </div>
            {anyUnknown && (
              <div className="aug-fs-xs" style={{ ...muted, display: "flex", gap: 12, marginTop: 10 }}>
                {anyPriced && <span><Swatch fill="var(--chart-1)" />priced</span>}
                <span><Swatch fill={HATCH} />no price</span>
              </div>
            )}
          </>
        )}
    </section>
  );
}

function WhereCard({ day, error, onRetry }: { day: UsageSummary | null; error: string | null; onRetry: () => void }) {
  const rows = day ? whereTokensGo(day) : [];
  const top = Math.max(1, ...rows.map(r => r.tokens));
  return (
    <section aria-label="Where tokens go" data-testid="spend-where" style={card}>
      <Label right={<span className="aug-fs-xs" style={muted}>last 24 hours{day ? ` · ${tokens(day.tokens)}` : ""}</span>}>
        Where tokens go
      </Label>
      {error ? <ReadFailed what="the last 24 hours" error={error} onRetry={onRetry} />
        : !day ? <Loading what="the last 24 hours" />
        : rows.length === 0 ? <div className="aug-fs-sm" style={muted}>No model calls in the last 24 hours.</div>
        : (
          <>
            <div style={bars}>
              {rows.map(r => (
                <Bar key={r.key} name={r.label} sub={countNoun(r.calls, "call")} value={tokens(r.tokens)} share={r.tokens / top}
                  title={`${r.label} · ${countNoun(r.calls, "call")} · ${tokens(r.tokens)} tokens${r.sites.length ? `\n${r.sites.join("\n")}` : ""}`}
                  fill={r.other ? "var(--chart-deemph)" : "var(--chart-1)"} />
              ))}
            </div>
            {day.calls_without_usage > 0 && (
              <div className="aug-fs-xs" style={{ ...muted, marginTop: 10 }}>
                {countNoun(day.calls_without_usage, "call")} reported no token count
              </div>
            )}
          </>
        )}
    </section>
  );
}

// ── Caps ─────────────────────────────────────────────────────────────────────

function CapMeter({ cap }: { cap: UsageCap }) {
  if (cap.observed == null || !cap.limit) return null;
  const ratio = Math.min(1, cap.observed / cap.limit);
  const over = cap.observed >= cap.limit;
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 140 }}
      title={`${capAmount(cap.metric, cap.observed)} of ${capAmount(cap.metric, cap.limit)} in the last ${cap.window_hours}h`}>
      <span style={{ flex: 1, height: 4, borderRadius: "var(--r-pill)", background: "var(--bg-3)", overflow: "hidden" }}>
        <span style={{ display: "block", width: `${Math.round(ratio * 100)}%`, height: "100%",
          background: over ? "var(--red4)" : ratio > 0.8 ? "var(--amb4)" : "var(--grn4)" }} />
      </span>
      <span className="aug-fs-xs" style={{ color: over ? "var(--red4)" : "var(--t3)", ...tabular }}>
        {cap.metric === "cost_usd" ? money(cap.observed) : compactNumber(cap.observed)}
      </span>
    </span>
  );
}

function CapsEditor({ data, onChanged, onClose }: {
  data: UsageCapsResponse; onChanged: () => Promise<void>; onClose: () => void;
}) {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ scope: "org", subject: "*", metric: "cost_usd",
    limit: "", window_hours: "24", action: "alert" });

  async function declare() {
    const limit = parseFloat(form.limit);
    if (isNaN(limit) || limit < 0) { setErr("The limit must be a number ≥ 0."); return; }
    setBusy(true); setErr("");
    try {
      await putUsageCap({ scope: form.scope, subject: form.subject.trim() || "*",
        metric: form.metric, limit, window_hours: Math.max(1, parseInt(form.window_hours) || 24),
        action: form.action });
      setForm(f => ({ ...f, limit: "" }));
      await onChanged();
    } catch (e) { setErr(say(e)); }
    finally { setBusy(false); }
  }

  async function remove(cap: UsageCap) {
    setBusy(true); setErr("");
    try {
      await deleteUsageCap({ scope: cap.scope, metric: cap.metric, subject: cap.subject, window_hours: cap.window_hours });
      await onChanged();
    } catch (e) { setErr(say(e)); }
    finally { setBusy(false); }
  }

  return (
    <section aria-label="Spend caps" data-testid="spend-caps" style={card}>
      <Label right={<Button size="xs" variant="ghost" onClick={onClose}>Close</Button>}>Spend caps</Label>
      {data.caps.map((c, i) => (
        <div key={`${c.scope}:${c.subject}:${c.metric}:${c.window_hours}`} className="aug-fs-sm"
          style={{ ...row, flexWrap: "nowrap", gap: 12, padding: "8px 2px", borderTop: i ? "1px solid var(--b1)" : undefined }}>
          <span style={{ color: "var(--t1)", fontWeight: 500, ...tabular }}>{capAmount(c.metric, c.limit)}</span>
          <span className="aug-fs-xs" style={muted}>per {c.window_hours}h · {c.scope === "user" ? `user ${c.subject}` : "whole org"}</span>
          <span className="aug-fs-xs" style={{ color: c.action === "block" ? "var(--red4)" : "var(--amb4)" }}>
            {c.action === "block" ? "blocks new work" : "alerts"}
          </span>
          <span style={{ flex: 1 }} />
          <CapMeter cap={c} />
          {c.set_by && <span className="aug-fs-xs" style={muted}>set by {c.set_by}</span>}
          <Button size="xs" variant="ghost" disabled={busy} onClick={() => remove(c)} data-testid={`cap-remove-${c.scope}-${c.metric}`}>
            <Icon name="trash" size={12} /> Remove
          </Button>
        </div>
      ))}
      <div className="aug-fs-sm" style={{ ...row, marginTop: data.caps.length ? 10 : 0 }}>
        <SelectField style={field} value={form.scope} onChange={e => setForm(f => ({ ...f, scope: e.target.value }))}>
          {(data.scopes.length ? data.scopes : ["org", "user"]).map(s =>
            <option key={s} value={s}>{s === "org" ? "whole org" : "one user"}</option>)}
        </SelectField>
        {form.scope === "user" && (
          <Input style={{ ...field, width: 150 }} placeholder="user id" value={form.subject}
            onChange={e => setForm(f => ({ ...f, subject: e.target.value }))} />
        )}
        <SelectField style={field} value={form.metric} onChange={e => setForm(f => ({ ...f, metric: e.target.value }))}>
          {(data.metrics.length ? data.metrics : ["calls", "total_tokens", "cost_usd"]).map(m =>
            <option key={m} value={m}>{m.replace(/_/g, " ")}</option>)}
        </SelectField>
        <Input style={{ ...field, width: 110 }} placeholder="limit" inputMode="decimal"
          value={form.limit} onChange={e => setForm(f => ({ ...f, limit: e.target.value }))} data-testid="cap-limit" />
        <span className="aug-fs-xs" style={muted}>per</span>
        <Input style={{ ...field, width: 60 }} inputMode="numeric" value={form.window_hours}
          onChange={e => setForm(f => ({ ...f, window_hours: e.target.value }))} />
        <span className="aug-fs-xs" style={muted}>hours ·</span>
        <SelectField style={field} value={form.action} onChange={e => setForm(f => ({ ...f, action: e.target.value }))}>
          {(data.actions.length ? data.actions : ["alert", "block"]).map(a =>
            <option key={a} value={a}>{a === "block" ? "block new work" : "alert only"}</option>)}
        </SelectField>
        <Button size="sm" disabled={busy || !form.limit.trim()} onClick={declare} data-testid="cap-declare">Declare the cap</Button>
      </div>
      <div className="aug-fs-xs" style={{ ...muted, marginTop: 8 }}>
        Alert records a breach in the governance feed · block refuses new work and names the number
      </div>
      {err && <div className="aug-fs-xs" style={{ color: "var(--red4)", marginTop: 6 }}>{err}</div>}
    </section>
  );
}

// ── Governance ───────────────────────────────────────────────────────────────

const FOLD_ICON: Record<FoldTone, { name: IconName; color: string }> = {
  amber: { name: "warning", color: "var(--amb4)" },
  accent: { name: "bolt", color: "var(--accent-text)" },
  green: { name: "check", color: "var(--grn4)" },
  plain: { name: "dot", color: "var(--t3)" },
};

type Focus = { label: string; keys: ReadonlySet<string> };

function GovernanceCard() {
  const [feed, setFeed] = useState<{ events: AuditFeedEvent[]; categories: string[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [names, setNames] = useState<ReadonlyMap<string, string>>(new Map());
  const [full, setFull] = useState(false);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [shown, setShown] = useState<AuditFeedEvent[] | null>(null);
  // Arc TC, TC-5 — with `govern.justifications` on, the full feed takes dates and exports its
  // whole window from the server. A flag that cannot be read leaves both out.
  const [windowed, setWindowed] = useState(false);

  const read = useCallback(() => {
    setErr(null);
    getAuditFeed("", FEED_WINDOW).then(r => setFeed({ events: r.events, categories: r.categories })).catch(e => setErr(say(e)));
  }, []);
  useEffect(() => {
    read();
    // Names a connection on a folded row; a read that fails leaves the name out, never the row.
    getConnections().then(cs => setNames(new Map(cs.map(c => [c.id, c.name])))).catch(() => setNames(new Map()));
    getSystemFlags().then(f => setWindowed(!!f["govern.justifications"]?.value)).catch(() => setWindowed(false));
  }, [read]);

  const events = useMemo(() => feed?.events ?? [], [feed]);
  const folds = useMemo(() => foldFeed(events, id => names.get(id)), [events, names]);
  const span = sinceWords(events);

  const view = (f: FeedFold) => { setFocus({ label: f.title, keys: new Set(f.events.map(eventKey)) }); setFull(true); };
  const exportCsv = () => {
    const rows = full && shown ? shown : events;
    downloadCsv(csvFilename("governance-feed"),
      toCsv(["at", "category", "kind", "actor", "org_id", "conn_id", "summary"],
        rows.map(e => [e.at, e.category, e.kind, e.actor, e.org_id, e.conn_id, e.summary])));
  };

  return (
    <section aria-label="Governance" data-testid="spend-governance" style={card}>
      <Label right={
        <span style={row}>
          {feed && <span className="aug-fs-xs" style={muted}>{countNoun(events.length, "event")}</span>}
          <Button size="xs" variant="ghost" aria-expanded={full} disabled={!feed}
            onClick={() => { setFull(o => !o); setFocus(null); }}>{full ? "Hide feed" : "Full feed"}</Button>
          <Button size="xs" variant="ghost" disabled={!events.length} onClick={exportCsv}>
            <Icon name="download" size={12} /> CSV
          </Button>
        </span>
      }>
        {span ? `Governance · ${span}` : "Governance"}
      </Label>
      {err ? <ReadFailed what="the governance feed" error={err} onRetry={read} />
        : !feed ? <Loading what="the governance feed" />
        : folds.length === 0 ? <div className="aug-fs-sm" style={muted}>Nothing recorded yet.</div>
        : folds.map((f, i) => (
          <div key={f.key} data-testid="governance-fold" className="aug-fs-sm"
            style={{ display: "grid", gridTemplateColumns: "18px minmax(0, 1fr) auto auto", gap: 10, alignItems: "center",
              padding: "8px 2px", borderTop: i ? "1px solid var(--b1)" : undefined }}>
            <span style={{ display: "inline-flex", color: FOLD_ICON[f.tone].color }}><Icon name={FOLD_ICON[f.tone].name} size={14} /></span>
            <span style={oneLine} title={f.sub ? `${f.title} · ${f.sub}` : f.title}>
              <span style={{ color: "var(--t1)" }}>{f.title}</span>
              {f.sub && <span style={{ ...muted, marginLeft: 6 }}>{f.sub}</span>}
            </span>
            <span style={{ color: "var(--t2)", textAlign: "right", minWidth: 36, ...tabular }}>{formatCount(f.count)}</span>
            {f.tone === "amber" ? <Button size="xs" variant="secondary" onClick={() => view(f)}>View</Button> : <span />}
          </div>
        ))}
      {full && feed && (
        <FullFeed base={events} categories={feed.categories} focus={focus} windowed={windowed}
          onClearFocus={() => setFocus(null)} onRows={setShown} />
      )}
    </section>
  );
}

type FeedSort = { key: "at" | "category" | "kind" | "actor"; desc: boolean };

const FEED_COLUMNS: { key: FeedSort["key"] | "summary"; label: string; width?: number }[] = [
  { key: "at",       label: "When",    width: 150 },
  { key: "category", label: "Category", width: 150 },
  { key: "kind",     label: "Event",   width: 190 },
  { key: "actor",    label: "Actor",   width: 150 },
  { key: "summary",  label: "What happened" },
];

const cell: CSSProperties = { padding: "6px 10px", whiteSpace: "nowrap" };

function SortHeader({ label, active, desc, onClick, width }: {
  label: string; active: boolean; desc: boolean; onClick?: () => void; width?: number;
}) {
  return (
    <th style={{ ...cell, width, position: "sticky", top: 0, zIndex: 1, background: "var(--bg-2)", borderBottom: "1px solid var(--b1)" }}>
      {onClick ? (
        <Button variant="ghost" size="xs" onClick={onClick} className="aug-fs-xs h-auto p-0 font-normal"
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
  // Only offer the disclosure when there is something under it.
  const hasDetail = ev.detail && Object.keys(ev.detail).length > 0;
  return (
    <>
      <tr style={{ borderBottom: "1px solid var(--b0)", cursor: hasDetail ? "pointer" : "default" }}
        onClick={() => hasDetail && setOpen(o => !o)} data-testid="governance-feed-row">
        <td style={{ ...cell, color: "var(--t3)", ...tabular }}>{formatTimestamp(ev.at, "short")}</td>
        <td style={{ ...cell, color: "var(--t3)" }}>{ev.category.replace(/_/g, " ")}</td>
        <td style={{ ...cell, color: "var(--t3)", fontFamily: "var(--font-mono)" }}>{ev.kind}</td>
        <td style={{ ...cell, color: "var(--t3)" }}>{ev.actor || "—"}</td>
        <td style={{ ...cell, color: "var(--t2)", whiteSpace: "normal" }}>
          <span style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
            <span style={{ color: "var(--t3)", width: 11, flexShrink: 0 }}>
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

/** Every event in the window, filterable and sortable, each opening its detail. Category is a
 *  SERVER filter (the endpoint rejects an unknown one rather than answering empty); event, actor
 *  and search narrow the fetched window in memory — which is why the count says how many of how
 *  many, rather than presenting a slice as the whole. */
function FullFeed({ base, categories, focus, windowed = false, onClearFocus, onRows }: {
  base: AuditFeedEvent[]; categories: string[]; focus: Focus | null; windowed?: boolean;
  onClearFocus: () => void; onRows: (rows: AuditFeedEvent[]) => void;
}) {
  const [category, setCategory] = useState("");
  const [byCategory, setByCategory] = useState<AuditFeedEvent[] | null>(null);
  const [actor, setActor] = useState("");
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<FeedSort>({ key: "at", desc: true });
  const [err, setErr] = useState("");
  const [attempt, setAttempt] = useState(0);
  // TC-5: a first and last day, read by the server; "more" when the window holds more than one read.
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [more, setMore] = useState(false);
  const [exportErr, setExportErr] = useState("");
  const dated = windowed && Boolean(from || to);
  const serverRead = Boolean(category) || dated;

  useEffect(() => {
    setByCategory(null);
    setErr("");
    setMore(false);
    if (!serverRead) return;
    const dates = dated ? { since: from || undefined, until: to ? dayAfter(to) : undefined } : undefined;
    getAuditFeed(category, FEED_WINDOW, dates)
      .then(r => { setByCategory(r.events); setMore(Boolean(r.next_cursor)); })
      .catch(e => setErr(say(e)));
  }, [category, from, to, dated, serverRead, attempt]);

  const exportFile = () => {
    setExportErr("");
    downloadAuditFeed("csv", { category, since: from, until: to ? dayAfter(to) : "" })
      .catch(e => setExportErr(say(e)));
  };

  const events = useMemo(() => (serverRead ? byCategory ?? [] : base), [serverRead, byCategory, base]);
  // The vocabularies come from the rows themselves, never a hand-written list: a hard-coded kind
  // list goes stale the moment a sink emits a new one, and the filter would then hide events.
  const actors = useMemo(() => [...new Set(events.map(e => e.actor).filter(Boolean))].sort(), [events]);
  const kinds = useMemo(() => [...new Set(events.map(e => e.kind).filter(Boolean))].sort(), [events]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const out = events.filter(e =>
      (!focus || focus.keys.has(eventKey(e)))
      && (!actor || e.actor === actor)
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
  }, [events, focus, actor, kind, q, sort]);
  useEffect(() => { onRows(rows); }, [rows, onRows]);

  const loading = serverRead && byCategory === null && !err;
  const toggleSort = (key: FeedSort["key"]) => setSort(s => (s.key === key ? { key, desc: !s.desc } : { key, desc: true }));

  return (
    <div style={{ marginTop: 10, borderTop: "1px solid var(--b1)", paddingTop: 10 }}>
      <div style={{ ...row, marginBottom: 8 }}>
        <SelectField style={field} value={category} onChange={e => setCategory(e.target.value)}
          aria-label="Category" data-testid="feed-category">
          <option value="">All categories</option>
          {categories.map(c => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
        </SelectField>
        <SelectField style={field} value={kind} onChange={e => setKind(e.target.value)} aria-label="Event" data-testid="feed-kind">
          <option value="">All events</option>
          {kinds.map(k => <option key={k} value={k}>{k}</option>)}
        </SelectField>
        <SelectField style={field} value={actor} onChange={e => setActor(e.target.value)} aria-label="Actor" data-testid="feed-actor">
          <option value="">All actors</option>
          {actors.map(a => <option key={a} value={a}>{a}</option>)}
        </SelectField>
        <Input style={{ ...field, width: 220 }} value={q} onChange={e => setQ(e.target.value)}
          placeholder="Search summary, event, actor…" aria-label="Search the feed" data-testid="feed-search" />
        {windowed && (
          <>
            <Input type="date" style={{ ...field, width: 150 }} value={from} max={to || undefined}
              onChange={e => setFrom(e.target.value)} aria-label="From" title="From this day" data-testid="feed-since" />
            <Input type="date" style={{ ...field, width: 150 }} value={to} min={from || undefined}
              onChange={e => setTo(e.target.value)} aria-label="To" title="To this day, inclusive" data-testid="feed-until" />
          </>
        )}
        {(category || kind || actor || q || from || to) && (
          <Button size="xs" variant="ghost"
            onClick={() => { setCategory(""); setKind(""); setActor(""); setQ(""); setFrom(""); setTo(""); }}>
            Clear filters
          </Button>
        )}
        <span style={{ flex: 1 }} />
        <span className="aug-fs-xs" style={muted} data-testid="feed-count">
          {rows.length !== events.length
            ? `${formatCount(rows.length)} of ${formatCount(events.length)} events`
            : countNoun(rows.length, "event")}
          {more ? ` — the newest ${formatCount(events.length)}; the export has every one` : ""}
        </span>
        {windowed && (
          <Button size="xs" variant="ghost" onClick={exportFile} data-testid="feed-export"
            title="Every event in the chosen dates and category, as a CSV file">
            <Icon name="download" size={12} /> Export
          </Button>
        )}
      </div>
      {exportErr && <div className="aug-fs-xs" style={{ color: "var(--red4)", marginBottom: 8 }}>{exportErr}</div>}
      {focus && (
        <div className="aug-fs-xs" style={{ ...row, ...muted, marginBottom: 8 }} data-testid="feed-focus">
          {`Showing the ${focus.keys.size === 1 ? "event" : `${formatCount(focus.keys.size)} events`} behind “${focus.label}”`}
          <Button size="xs" variant="ghost" onClick={onClearFocus}>Show all</Button>
        </div>
      )}
      {err && <ReadFailed what="this category" error={err} onRetry={() => setAttempt(n => n + 1)} />}
      {!err && loading && <Loading what="this category" />}
      {!err && !loading && rows.length === 0 && (
        <EmptyState variant="inline"
          title={events.length === 0 ? "Nothing recorded in this category yet." : "No event in the window matches these filters."} />
      )}
      {!err && rows.length > 0 && (
        <div style={{ overflow: "auto", maxHeight: "58vh", border: "1px solid var(--b0)", borderRadius: "var(--r3)" }}>
          <Table className="aug-fs-sm" style={{ color: "var(--t2)" }}>
            <TableHeader>
              <TableRow className="aug-fs-xs" style={{ textAlign: "left" }}>
                {FEED_COLUMNS.map(c => (
                  <SortHeader key={c.key} label={c.label} width={c.width} active={sort.key === c.key} desc={sort.desc}
                    onClick={c.key === "summary" ? undefined : () => toggleSort(c.key as FeedSort["key"])} />
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((e, i) => <FeedRow key={`${e.at}-${e.kind}-${i}`} ev={e} />)}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

// ── Details ──────────────────────────────────────────────────────────────────

/** What the page does not lead with: how ask turns were served, and the SQL behind the cost
 *  figures — read only when a person opens it. */
function Details() {
  const [share, setShare] = useState<number | null | undefined>(undefined);
  const [sql, setSql] = useState("");
  useEffect(() => {
    getRouteMix().then(r => setShare((r as { converse_share?: number | null }).converse_share ?? null)).catch(() => setShare(null));
    getCostSql().then(r => setSql(r.sql)).catch(() => setSql("-- the cost query could not be read"));
  }, []);
  return (
    <div style={{ ...card, marginTop: 8, display: "flex", flexDirection: "column", gap: 10 }} data-testid="spend-details">
      <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>
        {share === undefined ? <Loading what="the route mix" inline />
          : share === null ? "Route mix: not measured yet."
          : `Route mix: ${pct(share)} of finished ask turns were answered by the conversation agent.`}
      </div>
      <div>
        <Label right={<Button size="xs" variant="ghost" disabled={!sql}
          onClick={() => { navigator.clipboard?.writeText(sql).catch(() => {}); }}><Icon name="copy" size={12} /> Copy</Button>}>
          The cost query
        </Label>
        <pre className="aug-fs-xs" style={{ margin: 0, maxHeight: 220, overflow: "auto", fontFamily: "var(--font-mono)",
          color: "var(--t2)", background: "var(--bg-1)", border: "1px solid var(--b0)", borderRadius: "var(--r2)", padding: 10 }}>
          {sql || "…"}
        </pre>
      </div>
    </div>
  );
}
