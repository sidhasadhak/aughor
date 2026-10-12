"use client";
/**
 * Security & Audit — redone to `aughor-v2/CLARITY.md` (2026-10-12): the figures first, then what needs a person,
 * then who ran the queries, then the checks themselves folded into a row per caller and outcome. The log's rows are
 * still all here — behind each group's Show, and behind "All rows" — with their SQL, errors and verdicts.
 *
 * On theLook the page listed 200 rows a read, and 196 of them were the Briefer's period comparisons: a "suspicious"
 * flag written before each statement ran, then the same statement logged again as it ran (`lib/auditFold.ts` says
 * why). Folded, that is two rows, and the flags are named as the platform's own reads rather than counted as alarm.
 */
import { GateMapView, PoliciesView } from "@/components/operations/GateMapPanel";
import { requestTab } from "@/lib/navigate";
import { Loading, ReadFailed } from "@/components/ui/states";
import { GuardChip, type GuardVerdict } from "@/components/ui/trust";

import { connectionLabel } from "@/lib/names";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { compactNumber, fmtDate, formatCount, MONTHS_SHORT } from "@/lib/format";
import { getApiBase } from "@/lib/config";
import { ActivityLog } from "@/components/ActivityLog";
import {
  getConnections,
  getApprovalsAudit, getAllowlist, revokeApproval,
  type ApprovalAuditEvent, type AllowlistEntry,
} from "@/lib/api";
import {
  blockedSince, byCaller, callerName, flagSplit, foldChecks, fromWhom, outcomeOf, OUTCOME_WORD,
  type AuditRecord, type CheckGroup, type Outcome,
} from "@/lib/auditFold";
import { SelectField } from "@/components/ui/select";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  CARD, Chip, Dot, Figure, Figures, HBars, Label, MUTED, NeedsRow, NeedsYou, ONE_LINE, Page, ROW,
} from "@/components/clarity/kit";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ConnectionItem {
  id: string;
  name: string;
  conn_type: string;
}

interface AuditStats {
  total: number;
  blocked: number;
  suspicious: number;
  errors: number;
  pii_redacted: number;
  avg_duration_ms: number;
  /** GM-5 — the platform's own queries (probes, profiling, samples): counted, not listed. */
  internal_statements?: number;
  internal_since?: string | null;
}

interface QueryBudget {
  connection_id: string;
  max_rows: number;
  warn_time_ms: number;
  max_time_ms: number;
  is_default: boolean;
}

// ── API helpers ───────────────────────────────────────────────────────────────

/** The window the page folds: the latest checks, enough to show who ran them and to name the noise. */
const WINDOW = 500;

async function fetchAuditLog(connId?: string, verdict?: string, limit = WINDOW): Promise<AuditRecord[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (connId) qs.set("connection_id", connId);
  if (verdict) qs.set("verdict", verdict);
  const res = await fetch(`${getApiBase()}/security/audit?${qs}`);
  if (!res.ok) throw new Error("Failed to fetch audit log");
  const data = await res.json();
  return data.records ?? [];
}

async function fetchAuditStats(connId?: string): Promise<AuditStats> {
  const qs = connId ? `?connection_id=${connId}` : "";
  const res = await fetch(`${getApiBase()}/security/audit/stats${qs}`);
  if (!res.ok) throw new Error("Failed to fetch audit stats");
  return res.json();
}

async function fetchBudget(connId: string): Promise<QueryBudget> {
  const res = await fetch(`${getApiBase()}/security/budget/${connId}`);
  if (!res.ok) throw new Error(`the server answered ${res.status}`);
  return res.json();
}

async function saveBudget(
  connId: string,
  patch: { max_rows?: number; warn_time_ms?: number; max_time_ms?: number },
): Promise<void> {
  const res = await fetch(`${getApiBase()}/security/budget/${connId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`the server answered ${res.status}`);
}

// ── Words for times and durations ─────────────────────────────────────────────

const pad = (n: number) => String(n).padStart(2, "0");
function dayOf(iso: string): string {
  // A bare day ("2026-09-30") is that day wherever the reader is, not UTC midnight shifted into their zone.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T00:00:00`) : new Date(iso);
  return isNaN(d.getTime()) ? iso : `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
}
function clockOf(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
/** "22:46–23:41" within a day, "9 Oct – 11 Oct" across days. */
function span(earliest: string, latest: string): string {
  if (!earliest) return "";
  if (dayOf(earliest) === dayOf(latest)) {
    const a = clockOf(earliest), b = clockOf(latest);
    return a === b ? `${dayOf(latest)} ${a}` : `${dayOf(latest)} ${a}–${b}`;
  }
  return `${dayOf(earliest)} – ${dayOf(latest)}`;
}
function ms(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "—";
  return n < 1000 ? `${Math.round(n)} ms` : `${(n / 1000).toFixed(1).replace(/\.0$/, "")} s`;
}
const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

// ── A log row, as the detail table draws it ───────────────────────────────────

// The audit's verdicts are guard readings: safe passed, suspicious warned, blocked refused.
const VERDICT_GUARD: Record<string, GuardVerdict> = { safe: "passed", suspicious: "warned", blocked: "refused" };

function VerdictBadge({ verdict }: { verdict: string }) {
  const guard = VERDICT_GUARD[verdict];
  if (verdict === "pii_blocked") return <GuardChip verdict="refused">withheld · sensitive values</GuardChip>;
  return guard ? <GuardChip verdict={guard}>{verdict}</GuardChip> : <span className="aug-guard">{verdict}</span>;
}

function AgentCell({ hypothesisId }: { hypothesisId: string }) {
  const { agent, detail } = callerName(hypothesisId);
  return (
    <span title={hypothesisId} style={{ whiteSpace: "nowrap" }}>
      <span style={{ color: "var(--t2)", fontWeight: 500 }}>{agent}</span>
      {detail && <span className="aug-fs-xs" style={{ color: "var(--t3)", marginLeft: 5 }}>{detail}</span>}
    </span>
  );
}

const PRE: React.CSSProperties = {
  marginTop: 6, background: "var(--code-bg)", borderRadius: "var(--r2)", padding: "8px 10px",
  whiteSpace: "pre-wrap", maxHeight: 220, overflow: "auto",
};

function SqlCell({ short, full }: { short: string; full: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <Button variant="ghost" size="xs" onClick={() => setOpen(o => !o)} title={open ? "Hide the statement" : "Show the whole statement"}
        className="aug-fs-xs" style={{ fontFamily: "var(--font-code)", color: "var(--t2)", textAlign: "left", padding: 0, height: "auto" }}>
        {short.length > 60 ? short.slice(0, 60) + "…" : short}
      </Button>
      {open && <pre className="aug-fs-xs" style={{ ...PRE, color: "var(--t1)", wordBreak: "break-all" }}>{full}</pre>}
    </div>
  );
}

function ErrorCell({ error }: { error: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <Button variant="ghost" size="xs" onClick={() => setOpen(o => !o)} title={open ? "Hide the error" : "Show the whole error"}
        className="aug-fs-xs" style={{ color: "var(--red4)", textAlign: "left", padding: 0, height: "auto", lineHeight: 1.35 }}>
        {open ? error : (error.length > 48 ? error.slice(0, 48) + "…" : error)}
      </Button>
      {open && <pre className="aug-fs-xs" style={{ ...PRE, color: "var(--red4)", wordBreak: "break-word" }}>{error}</pre>}
    </div>
  );
}

type SecSortCol = "ts" | "connection" | "verdict" | "rows" | "duration" | "pii";
const VERDICT_RANK: Record<string, number> = { blocked: 0, pii_blocked: 1, suspicious: 2, safe: 3 };

function sortRecords(rows: AuditRecord[], col: SecSortCol, dir: "asc" | "desc"): AuditRecord[] {
  const m = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    switch (col) {
      case "ts":         return m * a.ts.localeCompare(b.ts);
      case "connection": return m * a.connection_id.localeCompare(b.connection_id);
      case "verdict":    return m * ((VERDICT_RANK[a.verdict] ?? 9) - (VERDICT_RANK[b.verdict] ?? 9));
      case "rows":       return m * (a.row_count - b.row_count);
      case "duration":   return m * (a.duration_ms - b.duration_ms);
      case "pii":        return m * (a.pii_redacted - b.pii_redacted);
      default:           return 0;
    }
  });
}

function SortMark({ active, dir }: { active: boolean; dir: "asc" | "desc" }) {
  if (!active) return <span style={{ marginLeft: 3, opacity: 0.25 }}>⇅</span>;
  return <span style={{ marginLeft: 3, color: "var(--blue3)" }}>{dir === "asc" ? "↑" : "↓"}</span>;
}

/** The log's rows, every column the page ever showed: time, connection, who, verdict, SQL, rows, duration, masked
 *  values and error — sortable, the statement and the error opening in place. */
function AuditTable({ records, connections, testId }: { records: AuditRecord[]; connections: ConnectionItem[]; testId?: string }) {
  const [sortCol, setSortCol] = useState<SecSortCol>("ts");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const sorted = useMemo(() => sortRecords(records, sortCol, sortDir), [records, sortCol, sortDir]);
  const sortBy = (col: SecSortCol) => {
    if (col === sortCol) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir(col === "ts" ? "desc" : "asc"); }
  };
  const HEAD: { label: string; col: SecSortCol | null; align: React.CSSProperties["textAlign"] }[] = [
    { label: "Time", col: "ts", align: "left" },
    { label: "Connection", col: "connection", align: "left" },
    { label: "Who", col: null, align: "left" },
    { label: "Verdict", col: "verdict", align: "left" },
    { label: "SQL", col: null, align: "left" },
    { label: "Rows", col: "rows", align: "right" },
    { label: "Duration", col: "duration", align: "right" },
    { label: "Masked", col: "pii", align: "right" },
    { label: "Error", col: null, align: "left" },
  ];
  return (
    <div data-testid={testId} style={{ overflow: "auto", maxHeight: 420, marginTop: 6 }}>
      <Table className="aug-fs-sm">
        <TableHeader>
          <TableRow>
            {HEAD.map(h => {
              const active = h.col != null && sortCol === h.col;
              return (
                <TableHead key={h.label} onClick={h.col ? () => sortBy(h.col!) : undefined} className="aug-fs-xs"
                  style={{ textAlign: h.align, color: active ? "var(--blue3)" : "var(--t3)", whiteSpace: "nowrap",
                    cursor: h.col ? "pointer" : "default", userSelect: "none" }}>
                  {h.label}{h.col && <SortMark active={active} dir={sortDir} />}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map(rec => (
            <TableRow key={rec.id}>
              <TableCell style={{ color: "var(--t3)", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                {rec.ts.replace("T", " ").replace("Z", "")}
              </TableCell>
              <TableCell style={{ color: "var(--t2)", whiteSpace: "nowrap" }}>
                <span title={rec.connection_id}>{connectionLabel(rec.connection_id, connections)}</span>
              </TableCell>
              <TableCell><AgentCell hypothesisId={rec.hypothesis_id} /></TableCell>
              <TableCell style={{ whiteSpace: "nowrap" }}><VerdictBadge verdict={rec.verdict} /></TableCell>
              <TableCell style={{ maxWidth: 320 }}><SqlCell short={rec.sql_digest} full={rec.sql_full} /></TableCell>
              <TableCell style={{ color: "var(--t2)", textAlign: "right", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                {formatCount(rec.row_count)}
              </TableCell>
              <TableCell style={{ color: "var(--t2)", textAlign: "right", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                {ms(rec.duration_ms)}
              </TableCell>
              <TableCell style={{ color: rec.pii_redacted > 0 ? "var(--amb4)" : "var(--t3)", textAlign: "right" }}>
                {rec.pii_redacted > 0 ? rec.pii_redacted : "—"}
              </TableCell>
              <TableCell style={{ color: "var(--red4)", maxWidth: 260 }}>
                {rec.error ? <ErrorCell error={rec.error} /> : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ── Lens toggle ───────────────────────────────────────────────────────────────

// The gate map and the policies read back as sentences (the 2027 study §V, screen 12) are two more
// views of this page. The first view is labelled for what it lists — the tab above already says "Security".
type Lens = "security" | "activity" | "approvals" | "gates" | "policies";

function LensToggle({ value, onChange }: { value: Lens; onChange: (v: Lens) => void }) {
  return (
    <Segmented label="Security view" value={value} onChange={onChange} options={[
      { value: "security", label: "Queries" },
      { value: "activity", label: "Activity" },
      { value: "approvals", label: "Approvals" },
      { value: "gates", label: "Gate map" },
      { value: "policies", label: "Policies" },
    ]} />
  );
}

// ── The query lens ────────────────────────────────────────────────────────────

const HUE: Record<Outcome, "green" | "amber" | "red" | "grey"> = {
  passed: "green", flagged: "amber", failed: "red", blocked: "red", withheld: "red",
};

/** One group's muted line: what happened, the noise named as noise, and when. */
function groupMeta(g: CheckGroup): string {
  const n = g.rows.length;
  const when = span(g.earliest, g.latest);
  const avg = g.rows.reduce((s, r) => s + r.duration_ms, 0) / Math.max(1, n);
  switch (g.outcome) {
    case "flagged":
      return g.own ? `the platform's own reads — flagged before they ran, then run · ${when}`
        : `flagged before running, then run · ${when}`;
    case "blocked":  return `refused before running${g.reason ? ` · ${g.reason}` : ""} · ${when}`;
    case "withheld": return `the result held sensitive values and was held back · ${when}`;
    case "failed":   return `${g.reason ?? "an error"} · ${when}`;
    default:         return `avg ${ms(avg)}${n > 1 ? "" : ` · ${plural(g.rows[0].row_count, "row")}`} · ${when}`;
  }
}

function GroupRow({ g, open, onToggle, connections, first }: {
  g: CheckGroup; open: boolean; onToggle: () => void; connections: ConnectionItem[]; first: boolean;
}) {
  const word = OUTCOME_WORD[g.outcome];
  return (
    <div data-testid="check-group" style={{ borderTop: first ? undefined : "1px solid var(--b0)", padding: "8px 2px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "12px minmax(0, 1fr) auto auto", gap: 10, alignItems: "center" }}>
        <Dot hue={g.outcome === "flagged" && g.own ? "grey" : HUE[g.outcome]} title={word} />
        <div style={{ minWidth: 0 }}>
          <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)" }}>
            {word} <span style={{ color: "var(--t2)" }}>· {g.name}</span>
          </div>
          <div className="aug-fs-xs" title={g.reason ?? undefined} style={{ ...MUTED, ...ONE_LINE }}>{groupMeta(g)}</div>
        </div>
        <span className="aug-fs-chrome" data-testid="check-group-count"
          style={{ color: "var(--t2)", fontVariantNumeric: "tabular-nums", textAlign: "right", minWidth: 36 }}>
          {formatCount(g.rows.length)}
        </span>
        <Button size="xs" variant="ghost" aria-expanded={open} onClick={onToggle}>
          {open ? "Hide" : "Show"} <Icon name={open ? "chevu" : "chevd"} size={12} />
        </Button>
      </div>
      {open && <AuditTable records={g.rows} connections={connections} />}
    </div>
  );
}

/** The limits a statement runs under on this connection — read first, edited behind Edit. */
function LimitsCard({ connId, connName }: { connId: string; connName: string }) {
  const [budget, setBudget] = useState<QueryBudget | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const read = useCallback(() => {
    setReadError(null);
    fetchBudget(connId).then(setBudget).catch(e => setReadError(e instanceof Error ? e.message : String(e)));
  }, [connId]);
  useEffect(() => { read(); }, [read]);

  return (
    <section aria-label="Query limits" data-testid="audit-limits" style={{ ...CARD, flex: "1 1 260px" }}>
      <Label right={budget && !editing ? <Button size="xs" variant="ghost" onClick={() => setEditing(true)}>Edit</Button> : null}>
        Limits · {connName}
      </Label>
      {readError ? <ReadFailed what="the limits" error={readError} onRetry={read} />
        : !budget ? <Loading what="the limits" />
        : editing ? <BudgetEditor connId={connId} budget={budget} onDone={b => { if (b) setBudget(b); setEditing(false); }} />
        : (
          <div style={ROW}>
            <Chip>{`${formatCount(budget.max_rows)} rows at most`}</Chip>
            <Chip>{`warns at ${ms(budget.warn_time_ms)}`}</Chip>
            <Chip>{`stops at ${ms(budget.max_time_ms)}`}</Chip>
            {budget.is_default && <Chip title="No limits were set for this connection; saving an edit sets its own">the default</Chip>}
          </div>
        )}
    </section>
  );
}

function BudgetEditor({ connId, budget, onDone }: { connId: string; budget: QueryBudget; onDone: (b: QueryBudget | null) => void }) {
  const [draft, setDraft] = useState({ max_rows: budget.max_rows, warn_time_ms: budget.warn_time_ms, max_time_ms: budget.max_time_ms });
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  async function save() {
    setSaving(true);
    setFailed(null);
    try {
      await saveBudget(connId, draft);
      onDone({ ...budget, ...draft, is_default: false });
    } catch (e) {
      setFailed(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }
  const FIELDS: { key: keyof typeof draft; label: string }[] = [
    { key: "max_rows", label: "Max rows" }, { key: "warn_time_ms", label: "Warn after (ms)" }, { key: "max_time_ms", label: "Stop after (ms)" },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {budget.is_default && <div className="aug-fs-xs" style={{ color: "var(--amb4)" }}>These are the defaults — saving sets this connection&apos;s own.</div>}
      {FIELDS.map(f => (
        <label key={f.key} className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: "var(--t2)", width: 110, flexShrink: 0 }}>{f.label}</span>
          <Input type="number" value={draft[f.key]} style={{ width: 110 }}
            onChange={e => setDraft(d => ({ ...d, [f.key]: Number(e.target.value) }))} />
        </label>
      ))}
      <div style={ROW}>
        <Button size="xs" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save limits"}</Button>
        <Button size="xs" variant="ghost" onClick={() => onDone(null)} disabled={saving}>Cancel</Button>
      </div>
      {failed && <div role="alert" className="aug-fs-xs" style={{ color: "var(--red4)" }}>Not saved — {failed}</div>}
    </div>
  );
}

const VERDICT_FILTERS = [
  { value: "all", label: "All" },
  { value: "safe", label: "Passed" },
  { value: "suspicious", label: "Flagged" },
  { value: "blocked", label: "Blocked" },
] as const;
type VerdictFilter = typeof VERDICT_FILTERS[number]["value"];

function QueriesLens({ connId, connections, reloadKey, onLoading }: {
  connId?: string;
  connections: ConnectionItem[];
  reloadKey: number;
  onLoading: (b: boolean) => void;
}) {
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [blockedRows, setBlockedRows] = useState<AuditRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<VerdictFilter>("all");
  const [filterConnId, setFilterConnId] = useState<string | undefined>(connId);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [allRows, setAllRows] = useState(false);
  /** When the log was last read: "this week" is counted back from the read, not from each render. */
  const [readAt, setReadAt] = useState(0);
  const listRef = useRef<HTMLElement | null>(null);

  useEffect(() => { setFilterConnId(connId); }, [connId]);

  const load = useCallback(async () => {
    setLoading(true);
    onLoading(true);
    setError(null);
    try {
      const v = verdict === "all" ? undefined : verdict;
      const [s, r, b] = await Promise.all([
        fetchAuditStats(filterConnId),
        fetchAuditLog(filterConnId, v),
        // The blocked statements on their own read: a refusal a week old is far outside the latest checks.
        v === "blocked" ? Promise.resolve(null) : fetchAuditLog(filterConnId, "blocked", 50),
      ]);
      setStats(s);
      setRecords(r);
      setBlockedRows(b ?? r);
      setReadAt(Date.now());
      setOpen(new Set());
      setAllRows(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load audit data");
    } finally {
      setLoading(false);
      onLoading(false);
    }
  }, [filterConnId, verdict, onLoading]);
  useEffect(() => { load(); }, [load, reloadKey]);

  const groups = useMemo(() => foldChecks(records), [records]);
  const callers = useMemo(() => byCaller(records), [records]);
  const split = useMemo(() => flagSplit(records), [records]);
  const recentBlocked = useMemo(() => blockedSince(blockedRows, readAt, 7), [blockedRows, readAt]);
  const lastBlocked = blockedRows.find(r => outcomeOf(r) === "blocked");
  const windowSpan = records.length ? span(records[records.length - 1].ts, records[0].ts) : "";
  const filterWord = verdict === "all" ? "checks" : verdict === "safe" ? "passed" : verdict === "suspicious" ? "flagged" : "blocked";

  const review = (keys: string[]) => {
    setOpen(new Set(keys));
    listRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  };

  if (error) return <Page><ReadFailed what="the audit log" error={error} onRetry={load} /></Page>;
  if (!stats) return <Page><Loading what="the audit log" /></Page>;

  const flagSub = verdict !== "all" && verdict !== "suspicious" ? "flagged before they ran, then run"
    : split.flagged === 0 ? `none in the latest ${formatCount(records.length)}`
    : split.asked.length === 0 ? `${formatCount(split.flagged)} recent, all the platform's own`
    : `${formatCount(split.asked.length)} recent from people or agents`;
  const notListed = stats.internal_statements ?? 0;
  /** How many the log holds of what this view lists — not counted apart for "passed". */
  const ofAll = verdict === "all" ? stats.total : verdict === "suspicious" ? stats.suspicious : verdict === "blocked" ? stats.blocked : null;
  /** Whether the rows read can say anything about flags: the Passed and Blocked views hold none. */
  const flagsRead = verdict === "all" || verdict === "suspicious";

  return (
    <Page testId="audit-queries">
      <Figures testId="audit-figures">
        <Figure label="Queries checked" value={compactNumber(stats.total)} title={`${formatCount(stats.total)} statements checked and logged`}
          sub={`${compactNumber(stats.errors)} errors · avg ${ms(stats.avg_duration_ms)}`} testId="fig-checked" />
        <Figure label="Blocked" value={compactNumber(stats.blocked)} tone={recentBlocked.length ? "red" : undefined}
          sub={lastBlocked ? `refused before running · last ${dayOf(lastBlocked.ts)}` : "refused before running"} testId="fig-blocked" />
        <Figure label="Flagged" value={compactNumber(stats.suspicious)} sub={flagSub} testId="fig-flagged"
          title={verdict === "all" && split.flagged ? `Of the latest ${formatCount(records.length)} checks, ${formatCount(split.flagged)} were flagged`
            + ` and ${formatCount(split.own)} of those were the platform's own reads. A flag is written before a statement runs; the`
            + " statement is logged again when it runs." : undefined} />
        <Figure label="Values masked" value={compactNumber(stats.pii_redacted)} sub="sensitive values hidden in results" testId="fig-masked" />
      </Figures>

      <NeedsYou testId="audit-needs" empty={flagsRead
        ? "Nothing needs you · no recent flag from a person or an agent, nothing blocked this week"
        : "Nothing needs you · nothing blocked this week"}>
        {[
          flagsRead && split.asked.length > 0 && (
            <NeedsRow key="asked" testId="needs-asked"
              title={`${plural(split.asked.length, "flagged query", "flagged queries")} from people or agents`}
              detail={fromWhom(split.asked)}
              actions={<Button size="xs" variant="secondary"
                onClick={() => review(groups.filter(g => g.outcome === "flagged" && !g.own).map(g => g.key))}>Review</Button>} />
          ),
          recentBlocked.length > 0 && (
            <NeedsRow key="blocked" testId="needs-blocked"
              title={`${plural(recentBlocked.length, "query", "queries")} blocked this week`}
              detail={`${fromWhom(recentBlocked)}${recentBlocked[0].error ? ` · ${recentBlocked[0].error}` : ""}`}
              actions={<Button size="xs" variant="secondary" onClick={() => setVerdict("blocked")}>Review</Button>} />
          ),
        ]}
      </NeedsYou>

      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-start" }}>
        <section aria-label="Who ran them" data-testid="audit-callers" style={{ ...CARD, flex: "1.6 1 420px" }}>
          <Label right={records.length ? <span>{windowSpan}</span> : null}>
            Who ran them
          </Label>
          {callers.length === 0 ? <div className="aug-fs-sm" style={MUTED}>Nothing in the log yet.</div> : (
            <HBars bars={callers.map(c => {
              const parts = [
                c.flagged ? (c.flaggedOwn === c.flagged ? `${formatCount(c.flagged)} flagged, its own reads` : `${formatCount(c.flagged)} flagged`) : "",
                c.blocked ? `${formatCount(c.blocked)} blocked` : "",
                c.withheld ? `${formatCount(c.withheld)} withheld` : "",
                c.failed ? plural(c.failed, "error") : "",
              ].filter(Boolean);
              return {
                key: c.name, name: c.name, meta: parts.join(" · ") || undefined, value: c.total, shown: compactNumber(c.total),
                tip: `${c.name}: ${plural(c.total, "check")}${parts.length ? ` — ${parts.join(", ")}` : ", all passed"}`,
              };
            })} />
          )}
        </section>
        {connId && <LimitsCard key={connId} connId={connId} connName={connectionLabel(connId, connections)} />}
      </div>

      <section ref={listRef} aria-label="Query checks" data-testid="audit-checks" style={CARD}>
        <Label right={<>
          {records.length > 0 && <span>{`latest ${formatCount(records.length)} ${filterWord}${ofAll != null ? ` of ${compactNumber(ofAll)}` : ""}`}</span>}
          {notListed > 0 && (
            <Chip testId="audit-not-listed"
              title={`Not listed here: ${formatCount(notListed)} queries the platform ran for its own checks — probes, profiling`
                + ` and samples${stats.internal_since ? ` — since ${fmtDate(stats.internal_since, "day")}` : ""}.`}>
              {`${compactNumber(notListed)} probes not listed${stats.internal_since ? ` · since ${dayOf(stats.internal_since)}` : ""}`}
            </Chip>
          )}
        </>}>
          Query checks
        </Label>
        <div style={{ ...ROW, marginBottom: 6 }}>
          <Segmented label="Verdict" value={verdict} onChange={v => setVerdict(v)}
            options={VERDICT_FILTERS.map(f => ({ value: f.value, label: f.label }))} />
          <SelectField aria-label="Connection" value={filterConnId || ""} onChange={e => setFilterConnId(e.target.value || undefined)}>
            <option value="">All connections</option>
            {connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </SelectField>
          {loading && <Loading inline />}
        </div>
        {groups.length === 0 ? (
          <div className="aug-fs-sm" style={MUTED}>
            {verdict === "all" ? "No query has been checked here yet." : `No ${filterWord} query in the log.`}
          </div>
        ) : groups.map((g, i) => (
          <GroupRow key={g.key} g={g} first={i === 0} connections={connections} open={open.has(g.key)}
            onToggle={() => setOpen(prev => { const n = new Set(prev); if (n.has(g.key)) n.delete(g.key); else n.add(g.key); return n; })} />
        ))}
        {records.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <Button size="xs" variant="ghost" aria-expanded={allRows} onClick={() => setAllRows(a => !a)}>
              {allRows ? "Hide the rows" : `All ${formatCount(records.length)} rows`} <Icon name={allRows ? "chevu" : "chevd"} size={12} />
            </Button>
            {allRows && <AuditTable records={records} connections={connections} testId="audit-all-rows" />}
          </div>
        )}
      </section>
    </Page>
  );
}

// ── Action approvals (P4) — the graduated-approval allowlist and its decisions ──

/** Decisions that refused something: an action's row carries a red dot when any of them is among its decisions. */
const REFUSALS = new Set(["blocked", "proposal_rejected", "criterion_failed"]);
/** The order an action's decisions are said in: refusals first, then what a person granted, then the rest. */
const DECISION_ORDER = ["blocked", "criterion_failed", "proposal_rejected", "approved", "allowlisted", "revoked", "executed", "auto"];
const DECISION_WORD: Record<string, string> = {
  allowlisted: "pre-approved", auto: "automatic", criterion_failed: "check failed", proposal_rejected: "proposal rejected",
};
/** An action's id in words: `connection.schema.delete` → "connection schema delete". A declared action's namespace goes —
 *  `<namespace>.open_case` → "open case" — because its own name already says what it does. */
const actionWords = (a: string) => a.replace(/^[a-z]+\.(?=[a-z]+_[a-z_]+$)/, "").replace(/[._]+/g, " ").trim();
const decisionWords = (d: string) => DECISION_WORD[d] ?? d.replace(/_/g, " ");

function ActionApprovalsSection() {
  const [audit, setAudit] = useState<ApprovalAuditEvent[] | null>(null);
  const [allow, setAllow] = useState<AllowlistEntry[] | null>(null);
  const [auditFailed, setAuditFailed] = useState<string | null>(null);
  const [allowFailed, setAllowFailed] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openAction, setOpenAction] = useState<ReadonlySet<string>>(new Set());
  const [trail, setTrail] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));
    Promise.all([
      getApprovalsAudit(100).then(a => { setAudit(a); setAuditFailed(null); }).catch(e => setAuditFailed(msg(e))),
      getAllowlist().then(l => { setAllow(l); setAllowFailed(null); }).catch(e => setAllowFailed(msg(e))),
    ]).finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const [revokeError, setRevokeError] = useState<string | null>(null);
  async function handleRevoke(e: AllowlistEntry) {
    setRevokeError(null);
    try {
      await revokeApproval(e.action, e.scope);
    } catch (err) {
      // No auto-poll on this panel — a swallowed failure left the entry
      // looking allowlisted with zero feedback.
      setRevokeError(err instanceof Error ? err.message : "Revoke failed");
    } finally {
      load();
    }
  }

  // Repeats folded: one row per action on the allowlist, one per decision and action in the trail.
  const allowByAction = useMemo(() => {
    const m = new Map<string, AllowlistEntry[]>();
    for (const e of allow ?? []) m.set(e.action, [...(m.get(e.action) ?? []), e]);
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  }, [allow]);
  const decisions = useMemo(() => {
    const m = new Map<string, { action: string; n: number; by: Map<string, number>; last: string; actor: string }>();
    for (const e of audit ?? []) {
      const g = m.get(e.action) ?? { action: e.action, n: 0, by: new Map<string, number>(), last: "", actor: e.actor };
      g.n++;
      g.by.set(e.decision, (g.by.get(e.decision) ?? 0) + 1);
      if ((e.at ?? "") > g.last) { g.last = e.at ?? ""; g.actor = e.actor; }
      m.set(e.action, g);
    }
    const rank = (d: string) => { const i = DECISION_ORDER.indexOf(d); return i < 0 ? DECISION_ORDER.length : i; };
    return [...m.values()].sort((a, b) => b.n - a.n || b.last.localeCompare(a.last)).map(g => ({
      ...g,
      refused: [...g.by.keys()].some(d => REFUSALS.has(d)),
      said: [...g.by.entries()].sort((a, b) => rank(a[0]) - rank(b[0])).map(([d, k]) => `${k} ${decisionWords(d)}`).join(" · "),
    }));
  }, [audit]);

  return (
    <Page testId="audit-approvals">
      {revokeError && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>Revoke failed: {revokeError}</div>}
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-start" }}>
        <section aria-label="Pre-approved actions" style={{ ...CARD, flex: "1 1 360px" }}>
          <Label right={<>
            {allow && <span>{`${formatCount(allow.length)} pre-approved`}</span>}
            <Button size="xs" variant="ghost" onClick={load} disabled={loading}>{loading ? "Reading…" : "Refresh"}</Button>
          </>}>Pre-approved</Label>
          {allowFailed ? <ReadFailed what="the pre-approved actions" error={allowFailed} onRetry={load} />
            : !allow ? <Loading what="the pre-approved actions" />
            : allowByAction.length === 0 ? <div className="aug-fs-sm" style={MUTED}>No action is pre-approved.</div>
            : allowByAction.map(([action, entries], i) => {
              const isOpen = openAction.has(action);
              return (
                <div key={action} style={{ borderTop: i ? "1px solid var(--b0)" : undefined, padding: "7px 2px" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", gap: 10, alignItems: "center" }}>
                    <div style={{ minWidth: 0 }}>
                      <div className="aug-fs-chrome" title={action} style={{ ...ONE_LINE, color: "var(--t1)" }}>{actionWords(action)}</div>
                      <div className="aug-fs-xs" title={entries.map(e => e.scope || "everywhere").join(", ")} style={{ ...MUTED, ...ONE_LINE }}>
                        {entries.slice(0, 2).map(e => e.scope || "everywhere").join(" · ")}{entries.length > 2 ? ` · +${entries.length - 2} more` : ""}
                      </div>
                    </div>
                    <span className="aug-fs-chrome" style={{ color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>{entries.length}</span>
                    <Button size="xs" variant="ghost" aria-expanded={isOpen}
                      onClick={() => setOpenAction(p => { const n = new Set(p); if (n.has(action)) n.delete(action); else n.add(action); return n; })}>
                      {isOpen ? "Hide" : "Show"} <Icon name={isOpen ? "chevu" : "chevd"} size={12} />
                    </Button>
                  </div>
                  {isOpen && entries.map(e => (
                    <div key={`${e.action}@${e.scope}`} className="aug-fs-sm"
                      style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0 0 12px" }}>
                      <code className="aug-fs-xs" style={{ color: "var(--t2)", ...ONE_LINE }}>{e.scope || "*"}</code>
                      <span className="aug-fs-xs" style={MUTED}>{[e.by, e.at ? dayOf(e.at) : ""].filter(Boolean).join(" · ")}</span>
                      <span style={{ flex: 1 }} />
                      <Button size="xs" variant="outline" onClick={() => handleRevoke(e)}>Revoke</Button>
                    </div>
                  ))}
                </div>
              );
            })}
        </section>

        <section aria-label="Decisions" style={{ ...CARD, flex: "1 1 360px" }}>
          <Label right={audit ? <span>{`latest ${formatCount(audit.length)}`}</span> : null}>Decisions</Label>
          {auditFailed ? <ReadFailed what="the approval decisions" error={auditFailed} onRetry={load} />
            : !audit ? <Loading what="the approval decisions" />
            : decisions.length === 0 ? (
              <div className="aug-fs-sm" style={{ ...ROW, ...MUTED }}>
                No high-risk action attempted yet.
                <Chip title="AUGHOR_ACTION_APPROVAL=0 on the server switches the approval gate off">the gate is on unless the server switched it off</Chip>
              </div>
            ) : (
              <>
                {decisions.map((d, i) => (
                  <div key={d.action} data-testid="decision-row" style={{ display: "grid", gridTemplateColumns: "12px minmax(0, 1fr) auto",
                    gap: 10, alignItems: "center", borderTop: i ? "1px solid var(--b0)" : undefined, padding: "7px 2px" }}>
                    <Dot hue={d.refused ? "red" : "green"} title={d.refused ? "something was refused" : "nothing refused"} />
                    <div style={{ minWidth: 0 }}>
                      <div className="aug-fs-chrome" title={d.action} style={{ ...ONE_LINE, color: "var(--t1)" }}>{actionWords(d.action)}</div>
                      <div className="aug-fs-xs" title={d.said} style={{ ...MUTED, ...ONE_LINE }}>
                        {d.said}{d.last ? ` · last ${dayOf(d.last)}, ${d.actor}` : ""}
                      </div>
                    </div>
                    <span className="aug-fs-chrome" style={{ color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>{d.n}</span>
                  </div>
                ))}
                <div style={{ marginTop: 6 }}>
                  <Button size="xs" variant="ghost" aria-expanded={trail} onClick={() => setTrail(t => !t)}>
                    {trail ? "Hide the trail" : "Full trail"} <Icon name={trail ? "chevu" : "chevd"} size={12} />
                  </Button>
                  {trail && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 2, maxHeight: 260, overflow: "auto", marginTop: 4 }}>
                      {audit.map((e, i) => (
                        <div key={e.seq ?? i} className="aug-fs-sm" title={e.detail || undefined}
                          style={{ display: "flex", alignItems: "center", gap: 8, lineHeight: 1.6 }}>
                          <span style={{ color: "var(--t2)", fontWeight: 600, minWidth: 78 }}>{decisionWords(e.decision)}</span>
                          <code style={{ color: "var(--t2)" }}>{e.action}</code>
                          {e.scope && <span style={MUTED}>@ {e.scope}</span>}
                          <span style={{ flex: 1 }} />
                          <span className="aug-fs-xs" style={MUTED}>{e.actor}</span>
                          {e.at && <span className="aug-fs-xs" style={{ ...MUTED, fontVariantNumeric: "tabular-nums" }}>{e.at.slice(0, 19).replace("T", " ")}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
        </section>
      </div>
    </Page>
  );
}

export function SecurityAuditPanel({
  connId,
  lens = "security",
  onLensChange,
}: {
  connId?: string;
  lens?: Lens;
  onLensChange?: (v: Lens) => void;
}) {
  const [connections, setConnections] = useState<ConnectionItem[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getConnections()
      .then(cs => setConnections(cs.map(c => ({ id: c.id, name: c.name, conn_type: c.conn_type }))))
      .catch(() => setConnections([]));
  }, []);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
      <div style={{ padding: "12px 20px 0", display: "flex", alignItems: "center", gap: 12, flexShrink: 0, flexWrap: "wrap" }}>
        <LensToggle value={lens} onChange={v => onLensChange?.(v)} />
        {connId && <Chip title={connId}>{connectionLabel(connId, connections)}</Chip>}
        <div style={{ flex: 1 }} />
        {lens === "security" && (
          <Button variant="ghost" size="xs" onClick={() => setReloadKey(k => k + 1)} disabled={loading}>
            <Icon name="refresh" size={12} />{loading ? "Reading…" : "Refresh"}
          </Button>
        )}
      </div>

      {/* Activity lens — exploration episode log (merged Audit Log) */}
      {lens === "activity" && <ActivityLog connectionId={connId ?? ""} isActive />}

      {/* Approvals lens — the pre-approved actions and every high-risk decision, on its own tab */}
      {lens === "approvals" && <ActionApprovalsSection />}

      {lens === "gates" && <GateMapView />}
      {lens === "policies" && (
        <PoliciesView onOpenSettings={() => requestTab("settings")} onOpenSpend={() => requestTab("spend")} />
      )}

      {lens === "security" && (
        <QueriesLens connId={connId} connections={connections} reloadKey={reloadKey} onLoading={setLoading} />
      )}
    </div>
  );
}
