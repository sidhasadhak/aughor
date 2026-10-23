"use client";

/**
 * ProfilePanel — what Aughor knows about this business, redone to `aughor-v2/CLARITY.md` (2026-10-13).
 *
 * A profile reads like a page, not a dashboard: it opens on what the business is — its name, the summary in prose and
 * a column of facts beside it (the business model, the currency, a fiscal year a person set), with why Aughor thinks
 * so one click away — then the tables as profiled, what a column's statuses and blanks mean, and the governed metrics.
 * No figure row and no "Needs you": nothing on a profile waits on a person.
 *
 * It used to open on a strip of timestamps and three numbered sections beside a rail, with a paragraph under the
 * table explaining its columns and a status note repeated on every status column. Those are said once now — in a
 * column's hover, or in a section's label — and a status column whose values ran to a megabyte (a JSON payload the
 * explorer mapped as a status) shows its first values and says how many more there are.
 *
 * Drawn only from stored data. Left out, because nothing records it: a confidence and a "decided by" per table, and
 * per fact except the industry guess; channels, distribution centres, a fiscal week; a "disputed" metric state; a
 * lifecycle ORDER (only a status column's values, and transitions where a table has a key and a timestamp — so no
 * arrows are drawn); a profiling-run count, and Re-profile / Correct doors (no endpoint re-profiles on demand, the
 * profile rebuild is a model call, and nothing corrects a profile in place). A human setting wins over the inference
 * only where org settings say so (industry, currency, a fiscal year that does not start in January), and each fact
 * says which it is.
 *
 * Reads: /business-profile, /org-settings/effective and /metrics are pure. The schema profile may open a warehouse
 * connection when its cache has expired, and /findings runs an information-schema query when given a schema — reads,
 * never writes and never a model call. Each read fails on its own and says so, with Retry — never as an empty section.
 */
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";

import { Card, CARD, Chip, Empty, Label, MUTED, NUM, ONE_LINE, ROW, RULE } from "@/components/clarity/kit";
import { FoldLine, GroupHead } from "@/components/semantic/parts";
import { TableActions } from "@/components/TableActions";
import { SkeletonRows } from "@/components/ui/motion";
import { ReadFailed } from "@/components/ui/states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { setDataCurrency, type DataCurrency } from "@/lib/orgSettings";
import {
  confirmDataCurrency, getBusinessProfile, getDataCurrency, getEffectiveSettings, getExplorationFindings, getMetrics, getSchemaProfile,
  type BusinessProfileResponse, type ExplorationFindings, type LifecycleMap, type Metric, type OrgSettings,
  type SchemaProfile,
} from "@/lib/api";
import { dateWords } from "@/lib/documents";
import { countNoun, formatCount, formatTimestamp, pct, relTime } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { keyToWords } from "@/lib/names";

type Load<T> = { state: "loading" } | { state: "ready"; data: T } | { state: "failed"; error: string };

/** One read per source, each failing on its own — a missing metric store must not blank the profile. The second value
 *  reads it again. */
function useLoad<T>(read: () => Promise<T>, deps: unknown[]): [Load<T>, () => void] {
  const [load, setLoad] = useState<Load<T>>({ state: "loading" });
  const [reads, setReads] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoad({ state: "loading" });
    read()
      .then(data => { if (alive) setLoad({ state: "ready", data }); })
      .catch(e => { if (alive) setLoad({ state: "failed", error: e instanceof Error ? e.message : String(e) }); });
    return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reads]);
  return [load, () => setReads(n => n + 1)];
}

/** A section's body once its read lands: skeleton rows while it reads, a failed read said with Retry. */
function Gate<T>({ load, what, retry, rows = 3, children }: {
  load: Load<T>; what: string; retry: () => void; rows?: number; children: (data: T) => ReactNode;
}) {
  if (load.state === "loading") return <SkeletonRows rows={rows} />;
  if (load.state === "failed") return <ReadFailed what={what} error={load.error} onRetry={retry} />;
  return <>{children(load.data)}</>;
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];

/** What the explorer found a blank to mean (its null-meaning phase). "not_applicable" (never blank)
 *  and "unknown" say nothing about a blank, so they are not listed. */
const BLANK: Record<string, string> = {
  pending:                 "an event that has not happened yet",
  not_applicable_terminal: "not applicable once terminal",
  missing:                 "a data-quality gap",
  mixed:                   "more than one thing",
};

/** The explained blanks grouped by what a blank means, a data-quality gap first. */
function blankGroups<T extends { meaning: string }>(blanks: [string, T][]): { meaning: string; rows: [string, T][] }[] {
  const order = ["missing", ...Object.keys(BLANK).filter(k => k !== "missing")];
  const by = new Map<string, [string, T][]>();
  for (const b of blanks) by.set(b[1].meaning, [...(by.get(b[1].meaning) ?? []), b]);
  const rank = (m: string) => (order.indexOf(m) < 0 ? order.length : order.indexOf(m));
  return [...by.entries()].sort((a, b) => rank(a[0]) - rank(b[0])).map(([meaning, rows]) => ({ meaning, rows }));
}

/** At or above this the industry guess is held; below it the chip says it is an inference. */
const HELD = 0.86;

/** A status column shows this many of its values; the rest are counted. */
export const STATES_SHOWN = 8;
/** A value longer than this is cut, its start kept on hover — one explorer run mapped a JSON payload as a status. */
const STATE_CHARS = 40;

/** A status column's values as a reader sees them: the first few, each cut to a readable length, and how many more. */
export function statusValues(lc: LifecycleMap): { shown: { text: string; full: string; terminal: boolean; active: boolean }[]; more: number } {
  const all = lc.states ?? [];
  const terminal = new Set(lc.terminal_states ?? []);
  const active = new Set(lc.active_states ?? []);
  return {
    shown: all.slice(0, STATES_SHOWN).map(st => ({
      text: st.length > STATE_CHARS ? `${st.slice(0, STATE_CHARS - 1)}…` : st,
      full: st.length > 200 ? `${st.slice(0, 200)}…` : st,
      terminal: terminal.has(st), active: active.has(st),
    })),
    more: Math.max(0, all.length - STATES_SHOWN),
  };
}

const TERM: CSSProperties = { ...MUTED, paddingTop: 2 };

export function ProfilePanel({ connectionId, canvasId, schema, workspaceId }: {
  connectionId: string;
  canvasId?:    string;
  schema?:      string;
  workspaceId?: string;
}) {
  const [profile, reProfile]   = useLoad<BusinessProfileResponse>(() => getBusinessProfile(connectionId, schema), [connectionId, schema]);
  const [settings, reSettings] = useLoad<OrgSettings>(() => getEffectiveSettings(workspaceId), [workspaceId]);
  const [tables, reTables]     = useLoad<SchemaProfile>(() => getSchemaProfile(connectionId), [connectionId]);
  const [metrics, reMetrics]   = useLoad<Metric[]>(() => getMetrics(), []);
  const [findings, reFindings] = useLoad<ExplorationFindings>(() => getExplorationFindings(connectionId, schema), [connectionId, schema]);
  const [why, setWhy] = useState(false);
  const [showDeprecated, setShowDeprecated] = useState(false);

  const p = profile.state === "ready" && profile.data.available ? profile.data.profile ?? null : null;
  const generatedAt = profile.state === "ready" ? profile.data.generated_at ?? null : null;
  const org = settings.state === "ready" ? settings.data : null;

  const tableRows = useMemo(() => {
    if (tables.state !== "ready" || !tables.data.available) return [];
    const prefix = schema ? `${schema}.` : null;
    const nulls = new Map<string, { sum: number; n: number }>();
    for (const c of tables.data.columns) {
      if (typeof c.null_rate !== "number") continue;   // an unmeasured column is not a zero
      const acc = nulls.get(c.table) ?? { sum: 0, n: 0 };
      acc.sum += c.null_rate;
      acc.n += 1;
      nulls.set(c.table, acc);
    }
    return tables.data.tables
      .filter(t => !prefix || t.table.startsWith(prefix))
      .map(t => {
        const acc = nulls.get(t.table);
        return { ...t, name: prefix ? t.table.slice(prefix.length) : t.table, avgNull: acc?.n ? acc.sum / acc.n : null };
      });
  }, [tables, schema]);
  const lastProfiled = tableRows.reduce<string | null>((a, t) => (!a || t.computed_at > a ? t.computed_at : a), null);
  // Said once in the label when every table was profiled the same day; a column only when they differ.
  const profiledApart = new Set(tableRows.map(t => (t.computed_at || "").slice(0, 10))).size > 1;
  const [now] = useState(() => Date.now());

  // A connection's own entry for a metric beats the global one of the same name.
  const governed = useMemo(() => {
    if (metrics.state !== "ready") return [];
    const byName = new Map<string, Metric>();
    for (const m of metrics.data) {
      const scope = m.connection ?? "*";
      if (scope !== "*" && scope !== connectionId) continue;
      // A schema's profile shows the metrics of THAT dataset: the Olist profile listed the Uber and airline
      // schemas' metrics under "Governed metrics" because the three share one connection (2026-10-22).
      const dataset = m.home_schema ?? m.schema_name ?? null;
      if (schema && dataset && dataset !== "*" && dataset !== schema) continue;
      const prev = byName.get(m.name);
      if (!prev || ((prev.connection ?? "*") === "*" && scope !== "*")) byName.set(m.name, m);
    }
    return [...byName.values()];
  }, [metrics, connectionId, schema]);
  const allGlobal = governed.length > 0 && governed.every(m => (m.connection ?? "*") === "*");
  const live = governed.filter(m => m.status !== "deprecated");
  const deprecated = governed.filter(m => m.status === "deprecated");

  const statusCols = findings.state === "ready" ? Object.entries(findings.data.lifecycle_maps ?? {}) : [];
  const noOrder = statusCols.every(([, lc]) => !(lc.transitions ?? []).length);
  const blanks = findings.state === "ready"
    ? Object.entries(findings.data.null_meanings ?? {}).filter(([, v]) => v.meaning !== "not_applicable" && v.meaning !== "unknown")
    : [];

  return (
    <div data-testid="profile-overview" style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
      <section aria-label="The business" style={{ ...CARD, padding: "14px 20px 16px" }}>
        <Label right={<>
          {generatedAt && <span title={formatTimestamp(generatedAt)}>inferred {relTime(generatedAt)} ago</span>}
          {canvasId && <Chip title="A canvas does not narrow the profile">connection-wide</Chip>}
        </>}>
          The business
        </Label>
        <Gate load={profile} what="the business profile" retry={reProfile}>
          {() => !p ? (
            <Empty>No business profile inferred for this {schema ? "schema" : "connection"} yet — the explorer infers one when it runs.</Empty>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "14px 36px", alignItems: "flex-start" }}>
              <div style={{ flex: "1 1 480px", minWidth: 0, maxWidth: 820 }}>
                <IndustryLine inferred={p.industry} confidence={p.confidence} human={org?.industry || ""} />
                <p className="aug-fs-ui" style={{ margin: "8px 0 0", lineHeight: 1.7, color: "var(--t1)" }}>{p.summary}</p>
                {p.evidence && (
                  <>
                    <FoldLine open={why} onToggle={() => setWhy(o => !o)} testId="profile-why">Why Aughor thinks so</FoldLine>
                    {why && (
                      <p className="aug-fs-sm" style={{ margin: "6px 0 0", lineHeight: 1.6, color: "var(--t2)" }}>
                        {Array.isArray(p.evidence) ? p.evidence.join(" ") : p.evidence}
                      </p>
                    )}
                  </>
                )}
              </div>
              <dl className="aug-fs-sm" data-testid="profile-facts" style={{ flex: "0 1 340px", minWidth: 240, margin: 0,
                display: "grid", gridTemplateColumns: "88px minmax(0, 1fr)", gap: "8px 12px" }}>
                {p.business_model && (
                  <>
                    <dt style={TERM}>Model</dt>
                    <dd style={{ margin: 0, minWidth: 0 }} title={`${p.business_model}\n\nInferred; no confidence is recorded for it.`}>
                      <div style={{ color: "var(--t1)", display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical",
                        overflow: "hidden" }}>{p.business_model}</div>
                    </dd>
                  </>
                )}
                {/* The data's currency is the profile's PROPOSAL until a person confirms it, per dataset
                    (2026-10-23, the Olist study's Gap 14: "USD · org setting · inferred BRL" printed reais in dollars). */}
                <CurrencyFact connectionId={connectionId} schema={schema} />
                {/* A January start is also what an unset setting reads as, so only another month is a human decision. */}
                {org && org.fiscal_year_start_month > 1 && (
                  <>
                    <dt style={TERM}>Fiscal year</dt>
                    <dd style={{ margin: 0, ...ROW }}>
                      <span style={{ color: "var(--t1)" }}>starts {MONTHS[org.fiscal_year_start_month - 1]}</span>
                      <Chip title="Set in org settings">org setting</Chip>
                    </dd>
                  </>
                )}
                {settings.state === "failed" && (
                  <>
                    <dt style={TERM}>Org settings</dt>
                    <dd style={{ margin: 0 }}>
                      <ReadFailed what="them — a setting a person made may be missing here" onRetry={reSettings} />
                    </dd>
                  </>
                )}
              </dl>
            </div>
          )}
        </Gate>
      </section>

      <Card label="Tables" testId="profile-tables" right={tableRows.length > 0 && <>
        <span title="Each figure is the profiler's; none records a human decision.">
          {countNoun(tableRows.length, "table")}{lastProfiled && !profiledApart && ` · profiled ${relTime(lastProfiled)} ago`}
        </span>
        <TableActions name="table profile" read={() => ({
          columns: ["table", "key", "key verified", "rows", "latest record", "average null rate", "profiled"],
          rows: tableRows.map(t => [t.name, t.grain_column, t.grain_verified, t.row_count, t.date_range?.[1] ?? null,
            t.avgNull, t.computed_at]),
        })} />
      </>}>
        <Gate load={tables} what="the table profile" retry={reTables} rows={6}>
          {() => tableRows.length === 0 ? (
            <Empty>No table profile yet — tables are profiled when the connection is first read, and after its schema changes.</Empty>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>table</TableHead>
                  <TableHead title="The key column the profiler checked — ✓ where it verified it">key</TableHead>
                  <TableHead className="num">rows</TableHead>
                  <TableHead className="num" title="The latest value of the table's main timestamp">latest record</TableHead>
                  <TableHead className="num" title="The average null rate across the table's columns">blank</TableHead>
                  {profiledApart && <TableHead className="num">profiled</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {tableRows.map(t => (
                  <TableRow key={t.table}>
                    <TableCell style={{ fontFamily: "var(--font-mono)" }}>{t.name}</TableCell>
                    <TableCell>
                      {t.grain_column ? (
                        <span style={ROW}>
                          <span style={{ fontFamily: "var(--font-mono)" }}>{t.grain_column}</span>
                          {t.grain_verified
                            ? <span title="The profiler verified this key" style={{ color: "var(--grn4)" }}>✓</span>
                            : <span style={MUTED}>unverified</span>}
                        </span>
                      ) : <span style={MUTED}>—</span>}
                    </TableCell>
                    <TableCell className="num">{formatCount(t.row_count)}</TableCell>
                    <TableCell className="num" title={t.primary_timestamp ? `the latest ${t.primary_timestamp}` : undefined}>
                      {t.date_range?.[1] ? dateWords(t.date_range[1], now) : <span style={MUTED}>no timestamp</span>}
                    </TableCell>
                    <TableCell className="num">{t.avgNull == null ? "—" : pct(t.avgNull, 1)}</TableCell>
                    {profiledApart && (
                      <TableCell className="num" title={formatTimestamp(t.computed_at)} style={MUTED}>{relTime(t.computed_at)} ago</TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Gate>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 14, alignItems: "start" }}>
        <Card label="Status columns" testId="profile-status" right={findings.state === "ready" && statusCols.length > 0 && (
          <span title={noOrder ? "No transitions were recorded between the values, so no order is claimed" : undefined}>
            {countNoun(statusCols.length, "column")}{noOrder && " · no order claimed"}
          </span>
        )}>
          <Gate load={findings} what="the explorer's findings" retry={reFindings}>
            {() => statusCols.length === 0 ? <Empty>No status column mapped yet.</Empty> : statusCols.map(([table, lc], i) => {
              const { shown, more } = statusValues(lc);
              const transitions = (lc.transitions ?? []).length;
              return (
                <div key={table} style={{ padding: "7px 0", ...(i ? RULE : {}) }}>
                  <div className="aug-fs-sm" style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                    <span style={{ fontFamily: "var(--font-mono)", color: "var(--t1)", ...ONE_LINE }}>{table}.{lc.status_column}</span>
                    {!noOrder && (
                      <span className="aug-fs-xs" style={{ ...MUTED, marginLeft: "auto" }}>
                        {transitions ? countNoun(transitions, "transition") : "no order claimed"}
                      </span>
                    )}
                  </div>
                  <div style={{ ...ROW, gap: 4, marginTop: 4 }}>
                    {shown.map((st, k) => (
                      <span key={`${k}:${st.text}`} className="aug-fs-xs"
                        title={[st.full, st.terminal ? "terminal" : st.active ? "active" : ""].filter(Boolean).join(" · ")}
                        style={{ padding: "0 7px", borderRadius: "var(--r1)", border: `1px ${st.terminal ? "dashed" : "solid"} var(--b2)`,
                          color: st.terminal ? "var(--t3)" : "var(--t2)", maxWidth: 260, ...ONE_LINE }}>
                        {st.text}
                      </span>
                    ))}
                    {more > 0 && <span className="aug-fs-xs" style={MUTED}>+{formatCount(more)} more</span>}
                  </div>
                </div>
              );
            })}
          </Gate>
        </Card>

        <Card label="What a blank means" testId="profile-blanks"
          right={findings.state === "ready" && blanks.length > 0 && countNoun(blanks.length, "column")}>
          <Gate load={findings} what="the explorer's findings" retry={reFindings}>
            {() => blanks.length === 0 ? <Empty>No column&apos;s blanks are explained yet.</Empty> : blankGroups(blanks).map((g, gi) => (
              // What a blank means is said once per group, not on every column that shares it.
              <div key={g.meaning} data-testid={`blanks-${g.meaning}`}>
                <GroupHead first={gi === 0} count={g.rows.length}
                  name={g.meaning === "missing" ? <Chip tone="amber">{BLANK.missing}</Chip> : <span>{BLANK[g.meaning] ?? keyToWords(g.meaning)}</span>} />
                {g.rows.map(([key, nm], i) => {
                  const [table, column] = key.split(":");
                  return (
                    <div key={key} style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12, alignItems: "center",
                      padding: "5px 0", ...(i ? RULE : {}) }}>
                      <div style={{ minWidth: 0 }}>
                        <div className="aug-fs-sm" style={{ fontFamily: "var(--font-mono)", color: "var(--t1)", ...ONE_LINE }}>{table}.{column}</div>
                        {nm.business_rule && (
                          <div className="aug-fs-xs" title={nm.business_rule} style={{ ...MUTED, ...ONE_LINE }}>{nm.business_rule}</div>
                        )}
                      </div>
                      <span className="aug-fs-sm" title="null rate" style={{ color: "var(--t2)", ...NUM }}>
                        {nm.null_rate == null ? "—" : pct(nm.null_rate, 1)}
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
          </Gate>
        </Card>
      </div>

      <Card label="Governed metrics" testId="profile-metrics" right={metrics.state === "ready" && governed.length > 0 && <>
        {formatCount(live.length)}
        {allGlobal && <Chip title="Each applies to every connection">every connection</Chip>}
      </>}>
        <Gate load={metrics} what="the metrics" retry={reMetrics} rows={2}>
          {() => governed.length === 0 ? <Empty>No governed metric applies to this connection.</Empty> : (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", columnGap: 28 }}>
                {withUniqueKeys(live, m => m.name).map(([key, m]) => <MetricRow key={key} m={m} />)}
              </div>
              {deprecated.length > 0 && (
                <>
                  <FoldLine open={showDeprecated} onToggle={() => setShowDeprecated(o => !o)} testId="profile-deprecated">
                    Deprecated · {formatCount(deprecated.length)}
                  </FoldLine>
                  {showDeprecated && (
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", columnGap: 28 }}>
                      {withUniqueKeys(deprecated, m => m.name).map(([key, m]) => <MetricRow key={key} m={m} />)}
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </Gate>
      </Card>
    </div>
  );
}

/** The business's industry as the page's heading, and whose word it is: held, inferred, or an org setting that wins. */
function IndustryLine({ inferred, confidence, human }: { inferred: string; confidence: number; human: string }) {
  const name = human || inferred;
  if (!name) return null;
  let chip: ReactNode;
  if (human) {
    const corrected = !!inferred && inferred !== human;
    chip = (
      <Chip title={corrected ? `Aughor inferred ${inferred}; the org setting wins` : inferred ? "Set in org settings, and the inference agrees" : "Set in org settings"}>
        {corrected ? "org setting · corrected" : "org setting"}
      </Chip>
    );
  } else {
    const held = confidence >= HELD;
    chip = (
      <Chip tone={held ? "up" : "plain"} title={`Industry inferred at confidence ${confidence.toFixed(2)}; held at ${HELD} and above`}>
        {held ? "✓ held" : "inferred"} · {pct(confidence)}
      </Chip>
    );
  }
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
      <h2 className="aug-fs-h1" style={{ margin: 0, fontWeight: 600, color: "var(--t1)" }}>{name}</h2>
      {chip}
    </div>
  );
}

/** The data's currency (2026-10-23): the profile PROPOSES it, a person confirms it — per dataset — and only a
 *  confirmed one labels a figure; until then amounts print plain. The org's reporting currency describes the
 *  organisation and labels nothing here. */
export function CurrencyFact({ connectionId, schema }: { connectionId: string; schema?: string }) {
  const [c, setC] = useState<DataCurrency | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    getDataCurrency(connectionId, schema)
      .then(d => { if (alive) { setC(d); setDataCurrency(d); } })
      .catch(() => { /* unread: the line is left out rather than guessed */ });
    return () => { alive = false; };
  }, [connectionId, schema]);
  async function save(code: string) {
    setBusy(true);
    setError("");
    try {
      const d = await confirmDataCurrency(connectionId, schema, code);
      setC(d);
      setDataCurrency(d);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  if (!c) return null;
  const who = `Confirmed by ${c.confirmed_by || "a person"}${c.confirmed_at ? ` on ${dateWords(c.confirmed_at, Date.now())}` : ""}`;
  return (
    <>
      <dt style={TERM}>Currency</dt>
      <dd data-testid="profile-currency" style={{ margin: 0, ...ROW, flexWrap: "wrap" }}>
        {c.code ? (
          <>
            <span style={{ color: "var(--t1)" }}>{c.code}</span>
            <Chip tone="up" title={`${who}; every figure from this data carries it`}>✓ confirmed</Chip>
          </>
        ) : c.inferred ? (
          <>
            <span style={{ color: "var(--t1)" }}>{c.inferred}</span>
            <span className="aug-fs-xs" style={MUTED} title="The profile's inference. Figures print as plain amounts until a person confirms it.">
              suggested by the profile · unconfirmed
            </span>
            {!editing && (
              <Button size="xs" variant="secondary" disabled={busy} onClick={() => void save(c.inferred)}>Confirm {c.inferred}</Button>
            )}
          </>
        ) : (
          <span className="aug-fs-xs" style={MUTED}>not known · amounts print plain</span>
        )}
        {!editing ? (
          <Button size="xs" variant="ghost" disabled={busy}
            onClick={() => { setDraft(c.code || c.inferred || ""); setEditing(true); }}>
            {c.code ? "Change" : "Another currency"}
          </Button>
        ) : (
          <>
            <Input aria-label="Currency code" value={draft} maxLength={3} style={{ width: 70 }}
              onChange={e => setDraft(e.target.value.toUpperCase())} />
            <Button size="xs" variant="secondary" disabled={busy || !/^[A-Z]{3}$/.test(draft)} onClick={() => void save(draft)}>Save</Button>
            {c.code && <Button size="xs" variant="ghost" disabled={busy} onClick={() => void save("")}>Clear</Button>}
            <Button size="xs" variant="ghost" disabled={busy} onClick={() => setEditing(false)}>Cancel</Button>
          </>
        )}
        {error && <span className="aug-fs-xs" style={{ color: "var(--red4)" }}>{error}</span>}
      </dd>
    </>
  );
}

const METRIC_STATE: Record<string, { tone: "plain" | "violet"; title: string }> = {
  proposed: { tone: "violet", title: "Proposed, not yet approved" },
  draft: { tone: "plain", title: "A draft — not yet proposed" },
  deprecated: { tone: "plain", title: "Deprecated — kept for its history" },
};

/** A governed metric: its name, version and — only when it is not approved — its state; the formula on one line. */
function MetricRow({ m }: { m: Metric }) {
  const state = m.status && m.status !== "approved" ? METRIC_STATE[m.status] ?? { tone: "plain" as const, title: m.status } : null;
  return (
    <div style={{ padding: "7px 0", ...RULE, minWidth: 0 }}
      title={(m.connection ?? "*") === "*" ? `${m.name} · applies to every connection` : m.name}>
      <div className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <span style={{ color: "var(--t1)", fontWeight: 500, ...ONE_LINE }}>{m.label || keyToWords(m.name)}</span>
        <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>v{m.version ?? 0}</span>
        {state && <Chip tone={state.tone} title={state.title}>{m.status}</Chip>}
      </div>
      <div className="aug-fs-xs" title={m.sql || undefined}
        style={{ ...MUTED, ...ONE_LINE, fontFamily: m.sql ? "var(--font-mono)" : undefined }}>
        {m.sql || "no formula recorded"}
      </div>
    </div>
  );
}
