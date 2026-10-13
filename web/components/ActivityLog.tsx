"use client";

/**
 * Activity — what the explorer ran on a connection (or a canvas), redone to `aughor-v2/CLARITY.md` (2026-10-13) as a
 * log read like a document: one line saying what it holds and how the run stands (its buttons beside it), what needs a
 * person (failed queries to repair, a run that stopped), then the queries themselves under a heading per day, newest
 * first. A row opens on its SQL and its result; a failed one keeps the repair it always had.
 *
 * It used to open on a strip of coloured phase chips, a filter bar and an eight-column table (#, timestamp, type,
 * message, status, rows, object) of 30 rows. The rows are all still here, with every fact a column held; the column
 * sort is gone — a log reads newest first, and Copy · CSV take every row to sort elsewhere.
 *
 * A failed read is said, never shown as "no activity": the episode reads throw now, where they returned [].
 */
import React, { useEffect, useMemo, useState } from "react";

import { Chip, Dot, Empty, Label, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, Page, ROW, RULE } from "@/components/clarity/kit";
import { ListCard } from "@/components/record/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Loading, ReadFailed } from "@/components/ui/states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  fixAll,
  fixEpisode,
  getCanvasExplorationEpisodes,
  getCanvasExplorationStatus,
  getExplorationEpisodes,
  getExplorationStatus,
  restartCanvasExploration,
  restartExploration,
  resumeCanvasExploration,
  resumeExploration,
  retryQuery,
  stopCanvasExploration,
  stopExploration,
  type ExplorationEpisode,
  type ExplorationStatus,
  type FixAllResult,
  type FixSaveResult,
  type RetryQueryResult,
} from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { countNoun, formatCount, MONTHS_SHORT } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { keyToWords } from "@/lib/names";

/** How many of the newest queries one read takes; past it, the older ones are said to be unread. */
const READ_LIMIT = 1000;

// ── Words for a query ─────────────────────────────────────────────────────────────────────

/** What each phase of the explorer is doing, in the reader's words (a phase key is a wire value). */
const PHASE_WORD: Record<string, string> = {
  exploration: "schema",
  null_meaning: "nulls",
  join_verification: "joins",
  lifecycle_mapping: "lifecycles",
  distribution: "distributions",
  cross_table: "across tables",
  domain_intel: "business questions",
  synthesis: "synthesis",
  // chat-initiated query kinds
  ask: "quick answer",
  investigate: "deep analysis",
};
const phaseWord = (phase: string) => PHASE_WORD[phase] ?? keyToWords(phase);

const failedObservation = (ep: ExplorationEpisode) =>
  ep.observation.startsWith("ERROR:") || ep.observation.startsWith("EXCEPTION:");

/** The error's own words, without the driver's trailer ("…; reason: invalidQuery, location: query, message: …"). */
function errorWords(observation: string): string {
  const bare = observation.replace(/^(ERROR|EXCEPTION):\s*/i, "");
  const cut = bare.split(/;\s*reason:/i)[0].trim();
  return cut.length > 160 ? `${cut.slice(0, 160)}…` : cut;
}

/** The table a statement reads first: the last part of a dotted name, never an EXTRACT(… FROM column). */
function tableOf(sql: string): string {
  for (const m of sql.matchAll(/\b(?:FROM|INTO|UPDATE)\s+[`"']?([\w.-]+)[`"']?(\s*\))?/gi)) {
    if (m[2]) continue;
    const parts = m[1].split(".");
    return parts[parts.length - 1];
  }
  return "";
}

/** What a query asked and what kind of question it was, from its recorded intent: a business-question row carries
 *  "Domain Customer | angle=… | the question", a synthesis "[synth:share] the question". */
function readIntent(ep: ExplorationEpisode): { asked: string; kind: string } {
  const think = ep.think.trim();
  const synth = /^\[synth:[^\]]+\]\s*([\s\S]*)$/.exec(think);
  // The log keeps a synthesis's question cut short; a cut one says so.
  if (synth) return { asked: !synth[1] ? "a synthesis" : /[?.!)]$/.test(synth[1]) ? synth[1] : `${synth[1]}…`, kind: "synthesis" };
  const parts = think.split(" | ");
  if (parts.length >= 3) {
    const domain = /^Domain\s+(.+)$/.exec(parts[0]);
    return { asked: parts.slice(2).join(" | "), kind: domain ? `${domain[1]} questions` : phaseWord(ep.phase) };
  }
  return { asked: think || ep.sql.replace(/\s+/g, " ").slice(0, 120) || "a query", kind: phaseWord(ep.phase) };
}

interface Item {
  key: string;
  /** The newest run of this statement; `members` holds every run folded into the row, newest first. */
  ep: ExplorationEpisode;
  members: ExplorationEpisode[];
  at: Date;
  /** When the earliest folded run ran. */
  first: Date;
  asked: string;
  kind: string;
  table: string;
  rows: number | null;
  failed: boolean;
  error: string;
}

/** The log newest first, one row per statement — a run repeated back to back with the same intent, statement and
 *  result on the same day folds into one row that counts it (theLook: 26 of 177 were such repeats). */
function toItems(episodes: ExplorationEpisode[]): Item[] {
  const newestFirst = [...episodes].sort((a, b) => b.ts - a.ts);
  const runs: ExplorationEpisode[][] = [];
  for (const ep of newestFirst) {
    const last = runs[runs.length - 1]?.[0];
    if (last && last.think === ep.think && last.sql === ep.sql && last.observation === ep.observation
      && dayKey(new Date(last.ts * 1000)) === dayKey(new Date(ep.ts * 1000))) runs[runs.length - 1].push(ep);
    else runs.push([ep]);
  }
  return withUniqueKeys(runs, members => `${members[0].episode_id}|${members[0].ts}`).map(([key, members]) => {
    const ep = members[0];
    const failed = failedObservation(ep);
    const rowMatch = failed ? null : /\b(\d+)\s+rows?\b/i.exec(ep.observation);
    return {
      key, ep, members, at: new Date(ep.ts * 1000), first: new Date(members[members.length - 1].ts * 1000),
      ...readIntent(ep), table: tableOf(ep.sql),
      rows: rowMatch ? parseInt(rowMatch[1], 10) : null, failed, error: failed ? errorWords(ep.observation) : "",
    };
  });
}

// ── Days and times ────────────────────────────────────────────────────────────────────────

const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
function pad(n: number): string { return String(n).padStart(2, "0"); }
function dayKey(d: Date): string { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function clock(d: Date): string { return `${pad(d.getHours())}:${pad(d.getMinutes())}`; }
function dayWords(d: Date): string {
  const words = `${WEEKDAY[d.getDay()]} ${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
  return d.getFullYear() === new Date().getFullYear() ? words : `${words} ${d.getFullYear()}`;
}

type Range = "all" | "today" | "yesterday" | "week";
type Outcome = "all" | "success" | "error";

function inRange(d: Date, range: Range): boolean {
  if (range === "all") return true;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  if (range === "today") return day === today;
  if (range === "yesterday") return day === today - 86_400_000;
  return d.getTime() >= today - 7 * 86_400_000;
}

// ── How the run stands ────────────────────────────────────────────────────────────────────

interface RunStateProps {
  status: ExplorationStatus | null;
  statusFailed: boolean;
  stopped: boolean;
  onStop: () => void; onResume: () => void; onRestart: () => void;
  stopping: boolean; resuming: boolean; restarting: boolean;
}

/** The run's state as chips (one per dataset when the connection has several), what the last run counted, and its
 *  buttons — Stop while it runs, Resume and Restart when it is stopped. An interrupted run's buttons are in Needs you. */
function RunState({ status, statusFailed, stopped, onStop, onResume, onRestart, stopping, resuming, restarting }: RunStateProps) {
  if (!status) {
    return statusFailed
      ? <Chip tone="down" testId="run-state" title="The explorer's status could not be read">run state not read</Chip>
      : null;
  }
  // A run a restart killed reads as stopped, with its reason, never as running (2026-10-07).
  const interrupted = !!status.interrupted;
  const running = !stopped && !interrupted && !["complete", "failed", "pending"].includes(status.phase);
  const halted = stopped || interrupted || status.paused || status.phase === "pending";
  // Per-dataset runs: one chip per run, so a dead OLD run's "failed" can never pass for the run just started on another.
  const perSchema = Object.entries(status.per_schema ?? {});
  const counted = [
    status.queries_executed > 0 && countNoun(status.queries_executed, "query", "queries"),
    status.facts_discovered > 0 && countNoun(status.facts_discovered, "fact"),
    status.insights_found > 0 && countNoun(status.insights_found, "finding"),
    status.tables_total > 0 && countNoun(status.tables_total, "table"),
    status.tables_total > 0 && countNoun(status.joins_total, "join"),
  ].filter(Boolean).join(" · ");
  return (
    <div data-testid="run-state" style={{ ...ROW, gap: 6 }}>
      {perSchema.length > 0 ? perSchema.map(([schema, phase]) => {
        const cut = (status.interrupted_schemas ?? []).includes(schema);
        const live = !stopped && !cut && !["complete", "failed", "pending"].includes(phase);
        const word = phase === "complete" ? "complete" : phase === "pending" ? "idle" : phase === "failed" ? "failed"
          : cut ? `interrupted at ${phaseWord(phase)}` : phaseWord(phase);
        return (
          <Chip key={schema} tone={phase === "failed" ? "down" : live ? "accent" : "plain"}
            title={phase === "failed" && status.error ? status.error : `The run on ${schema}: ${word}`}>
            {live && <span className="aug-dot aug-dot-live" aria-hidden />}{schema} · {word}
          </Chip>
        );
      }) : (
        <Chip tone={status.phase === "failed" ? "down" : running ? "accent" : "plain"}
          title={status.error ?? status.interrupted_note ?? undefined}>
          {running && <span className="aug-dot aug-dot-live" aria-hidden />}
          {interrupted ? `interrupted at ${phaseWord(status.phase)}` : halted && !running ? "stopped"
            : status.phase === "complete" ? "complete" : status.phase === "failed" ? "failed"
            : `running · ${phaseWord(status.phase)}`}
        </Chip>
      )}
      {counted && <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>last run {counted}</span>}
      {status.phase === "complete" && status.domain_intel_skipped && status.domain_intel_note && (
        <Chip title={status.domain_intel_note}>business questions skipped</Chip>
      )}
      {running && (
        <Button size="xs" variant="destructive" onClick={onStop} disabled={stopping}>{stopping ? "Stopping…" : "Stop"}</Button>
      )}
      {halted && !running && !interrupted && (
        <>
          <Button size="xs" variant="secondary" onClick={onResume} disabled={resuming || restarting}>
            {resuming ? "Resuming…" : "Resume"}
          </Button>
          <Button size="xs" variant="ghost" onClick={onRestart} disabled={resuming || restarting}>
            {restarting ? "Restarting…" : "Restart"}
          </Button>
        </>
      )}
    </div>
  );
}

// ── A row and what it opens on ────────────────────────────────────────────────────────────

const CODE: React.CSSProperties = {
  margin: 0, padding: "8px 10px", borderRadius: "var(--r2)", background: "var(--code-bg)", color: "var(--t2)",
  fontFamily: "var(--font-code)", whiteSpace: "pre-wrap", wordBreak: "break-all", lineHeight: 1.6, maxHeight: 240,
  overflow: "auto",
};

function QueryRow({ item, first, open, onToggle, connectionId, canvasId }: {
  item: Item; first: boolean; open: boolean; onToggle: () => void; connectionId: string; canvasId?: string;
}) {
  const { ep } = item;
  const obs = ep.observation.slice(0, 600) + (ep.observation.length > 600 ? "…" : "");
  return (
    <div data-testid="activity-row" style={{ padding: "6px 0", ...(first ? {} : RULE) }}>
      <Button variant="ghost" aria-expanded={open} onClick={onToggle} title={ep.think || undefined}
        style={{ display: "grid", gridTemplateColumns: "12px minmax(0, 1fr) auto 14px", gap: 10, alignItems: "center",
          width: "100%", height: "auto", margin: 0, padding: "2px", textAlign: "left", whiteSpace: "normal", fontWeight: 400 }}>
        <Dot hue={item.failed ? "red" : "green"} title={item.failed ? "failed" : "ran"} />
        <span style={{ minWidth: 0 }}>
          <span style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)" }}>{item.asked}</span>
            {item.members.length > 1 && (
              <Chip title={`The same statement ran ${item.members.length} times, with the same result`}>{`×${item.members.length}`}</Chip>
            )}
          </span>
          <span className="aug-fs-xs" style={{ ...ONE_LINE, display: "block", ...MUTED }}>
            {[item.kind, item.table, clock(item.first) === clock(item.at) ? clock(item.at) : `${clock(item.first)}–${clock(item.at)}`]
              .filter(Boolean).join(" · ")}
            {item.failed && <span style={{ color: "var(--red4)" }}> · {item.error}</span>}
          </span>
        </span>
        <span className="aug-fs-chrome" style={{ ...NUM, color: item.failed ? "var(--red4)" : "var(--t2)", textAlign: "right" }}
          title={item.rows == null && !item.failed ? "The result did not say how many rows it held" : undefined}>
          {item.failed ? "failed" : item.rows == null ? "—" : countNoun(item.rows, "row")}
        </span>
        <Icon name={open ? "chevu" : "chevd"} size={12} />
      </Button>
      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "8px 2px 6px 24px" }}>
          <div>
            <Label>SQL</Label>
            <pre className="aug-fs-xs" style={CODE}>{ep.sql || "No statement was recorded."}</pre>
          </div>
          <div>
            <Label>{item.failed ? "Error" : "Result"}</Label>
            <pre className="aug-fs-xs" style={item.failed ? { ...CODE, background: "var(--red1)", color: "var(--red4)" } : CODE}>{obs}</pre>
          </div>
          {item.failed && ep.sql && <RetryPanel ep={ep} connectionId={connectionId} errorMsg={ep.observation} canvasId={canvasId} />}
        </div>
      )}
    </div>
  );
}

/** Repair one failed query: run a corrected statement (with the person's guidance, if any), then save it as a finding. */
function RetryPanel({ ep, connectionId, errorMsg, canvasId }: { ep: ExplorationEpisode; connectionId: string; errorMsg: string; canvasId?: string }) {
  const [hint, setHint] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RetryQueryResult | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<FixSaveResult | null>(null);

  async function handleRetry() {
    setLoading(true); setResult(null); setSaved(null);
    try { setResult(await retryQuery(connectionId, ep.sql, errorMsg, hint)); }
    catch (e: unknown) { setResult({ ok: false, corrected_sql: "", explanation: "", rows: [], columns: [], error: String(e) }); }
    finally { setLoading(false); }
  }

  async function handleSave() {
    setSaving(true);
    try {
      setSaved(await fixEpisode(connectionId, { sql: ep.sql, error: errorMsg, think: ep.think, phase: ep.phase }, hint, canvasId ?? ""));
    } catch (e: unknown) {
      setSaved({ ok: false, stored: false, corrected_sql: "", error: String(e) });
    } finally { setSaving(false); }
  }

  if (!open) {
    return <div><Button size="xs" variant="secondary" onClick={() => setOpen(true)}>Retry with a fix</Button></div>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ ...ROW, flexWrap: "nowrap" }}>
        <Input type="text" value={hint} onChange={e => setHint(e.target.value)} aria-label="Guidance for the fix"
          onKeyDown={e => e.key === "Enter" && !loading && handleRetry()}
          placeholder="Guidance, optional — e.g. use click_ts instead of click_id" style={{ flex: 1, minWidth: 0 }} />
        <Button size="xs" variant="secondary" onClick={handleRetry} disabled={loading}>{loading ? "Fixing…" : "Run fix"}</Button>
        <Button size="xs" variant="ghost" onClick={() => { setOpen(false); setResult(null); }}>Cancel</Button>
      </div>
      {result && (
        <>
          {result.explanation && <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>{result.explanation}</div>}
          {result.corrected_sql && <pre className="aug-fs-xs" style={CODE}>{result.corrected_sql}</pre>}
          {result.ok ? (
            <>
              <div style={{ overflowX: "auto" }}>
                <Table className="aug-fs-xs">
                  <TableHeader><TableRow>{result.columns.map(c => <TableHead key={c}>{c}</TableHead>)}</TableRow></TableHeader>
                  <TableBody>{result.rows.slice(0, 15).map((row, i) => (
                    <TableRow key={i}>{row.map((cell, j) => <TableCell key={j}>{cell as string}</TableCell>)}</TableRow>
                  ))}</TableBody>
                </Table>
              </div>
              {/* Save the successful fix as a finding (through the Phase-8 guards) */}
              {!saved
                ? <div><Button size="xs" variant="secondary" onClick={handleSave} disabled={saving}>{saving ? "Saving…" : "Save as finding"}</Button></div>
                : <SaveFeedback saved={saved} />}
            </>
          ) : (
            <pre className="aug-fs-xs" style={{ ...CODE, background: "var(--red1)", color: "var(--red4)" }}>{result.error}</pre>
          )}
        </>
      )}
    </div>
  );
}

function SaveFeedback({ saved }: { saved: FixSaveResult }) {
  const note = saved.insight?.verification_note;
  if (!saved.ok) return <div><Chip tone="down" title={saved.error}>{`Not saved — ${saved.error ?? "the save failed"}`}</Chip></div>;
  if (saved.stored && saved.insight?.unverified) return <div><Chip tone="amber" title={note}>{`Saved, not verified — ${note}`}</Chip></div>;
  if (!saved.stored) return <div><Chip tone="accent" title={saved.reason}>{`Query fixed — ${saved.reason ?? "no finding stored"}`}</Chip></div>;
  return <div><Chip tone="up">Saved as a finding</Chip></div>;
}

// ── The page ──────────────────────────────────────────────────────────────────────────────

interface Props {
  connectionId: string;
  isActive: boolean;
  canvasId?: string;
}

export function ActivityLog({ connectionId, isActive, canvasId }: Props) {
  // Each read is kept with the connection (or canvas) it was of, so another connection's log never shows under this one
  // while its own is read — nor after its own read fails.
  const scope = canvasId ? `canvas:${canvasId}` : connectionId;
  const [read, setRead] = useState<{ scope: string; episodes: ExplorationEpisode[] } | null>(null);
  const [readFailure, setReadFailure] = useState<{ scope: string; message: string } | null>(null);
  const [statusRead, setStatusRead] = useState<{ scope: string; status: ExplorationStatus | null; failed: boolean } | null>(null);
  const episodes = read?.scope === scope ? read.episodes : null;
  const readError = readFailure?.scope === scope ? readFailure.message : null;
  const status = statusRead?.scope === scope ? statusRead.status : null;
  const statusFailed = statusRead?.scope === scope && statusRead.failed;
  const [reads, setReads] = useState(0);
  const [stopped, setStopped] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [restarting, setRestarting] = useState(false);
  // why a Continue or Restart did not run — a spent monthly budget the person chose not to run past
  const [runError, setRunError] = useState("");
  const [range, setRange] = useState<Range>("all");
  const [outcome, setOutcome] = useState<Outcome>("all");
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [fixingAll, setFixingAll] = useState(false);
  const [fixAllSummary, setFixAllSummary] = useState<FixAllResult["summary"] | null>(null);
  const [fixAllError, setFixAllError] = useState("");
  const scoped = !!scope;

  useEffect(() => {
    if (!isActive || !scoped) return;
    let cancelled = false;
    const load = async () => {
      const statusAsked = (canvasId ? getCanvasExplorationStatus(canvasId) : getExplorationStatus(connectionId))
        .then(s => ({ status: s, failed: false }), () => ({ status: null, failed: true }));
      try {
        const eps = canvasId
          ? await getCanvasExplorationEpisodes(canvasId, "", READ_LIMIT)
          : await getExplorationEpisodes(connectionId, "", READ_LIMIT);
        if (!cancelled) { setRead({ scope, episodes: eps }); setReadFailure(null); }
      } catch (e) {
        if (!cancelled) setReadFailure({ scope, message: e instanceof Error ? e.message : String(e) });
      }
      const st = await statusAsked;
      if (!cancelled) { setStatusRead({ scope, ...st }); if (st.status?.paused) setStopped(true); }
    };
    load();
    // K2: kernel events drive refresh; the interval is only a slow fallback.
    const t = setInterval(load, 60_000);
    const unsub = subscribeKernelEvents(() => load(), {
      kinds: ["exploration."], connId: connectionId, canvasId: canvasId || undefined,
    });
    return () => { cancelled = true; clearInterval(t); unsub(); };
  }, [connectionId, canvasId, scope, isActive, scoped, reads]);

  async function handleStop() {
    setStopping(true);
    try {
      if (canvasId) await stopCanvasExploration(canvasId);
      else await stopExploration(connectionId);
      setStopped(true);
    } finally { setStopping(false); }
  }
  async function handleResume() {
    setResuming(true); setRunError("");
    try {
      if (canvasId) await resumeCanvasExploration(canvasId);
      else await resumeExploration(connectionId);
      setStopped(false);
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "The run did not continue");
    } finally { setResuming(false); }
  }
  async function handleRestart() {
    setRestarting(true); setRunError("");
    try {
      if (canvasId) await restartCanvasExploration(canvasId);
      else await restartExploration(connectionId);
      setStopped(false); setRead({ scope, episodes: [] });
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "The run did not restart");
    } finally { setRestarting(false); }
  }

  const items = useMemo(() => toItems(episodes ?? []), [episodes]);
  const ranged = useMemo(() => items.filter(it => inRange(it.at, range)), [items, range]);
  const shown = useMemo(() => ranged.filter(it => outcome === "all" || (outcome === "error") === it.failed), [ranged, outcome]);
  const failures = useMemo(() => ranged.filter(it => it.failed), [ranged]);
  const failedRuns = useMemo(() => failures.flatMap(it => it.members), [failures]);

  // Fix all repairs ONLY the failed queries this range shows. The client passes exactly that set, so the server never
  // re-derives "all errors" or generates fresh queries — a range ("Yesterday") scopes the batch.
  async function handleFixAll() {
    if (failedRuns.length === 0 || fixingAll) return;
    setFixingAll(true); setFixAllSummary(null); setFixAllError("");
    try {
      const r = await fixAll(
        connectionId,
        failedRuns.map(ep => ({ sql: ep.sql, error: ep.observation, think: ep.think, phase: ep.phase })),
        "", canvasId ?? "",
      );
      setFixAllSummary(r.summary);
    } catch (e) {
      setFixAllError(e instanceof Error ? e.message : String(e));
    } finally { setFixingAll(false); }
  }

  if (!scoped) {
    return <Page testId="activity"><Empty>No connection is open — the explorer keeps its log per connection.</Empty></Page>;
  }
  if (episodes === null) {
    return (
      <Page testId="activity">
        {readError
          ? <ReadFailed what="the explorer's log" error={readError} onRetry={() => setReads(r => r + 1)} />
          : <Loading what="the explorer's log" />}
      </Page>
    );
  }

  const interrupted = !!status?.interrupted;
  const oldest = items.length ? items[items.length - 1].at : null;
  const errorsSaid = new Set(failures.map(f => f.error));
  const failDays = [...new Set(failures.map(f => dayWords(f.at)))];
  const toggle = (key: string) => setOpen(prev => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  return (
    <Page testId="activity">
      <div style={{ ...ROW, gap: 10 }}>
        <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>
          What the explorer ran {canvasId ? "on this canvas" : "here"}, newest first
        </span>
        {oldest && (
          <span className="aug-fs-sm" style={{ ...MUTED, ...NUM }}>
            {countNoun(episodes.length, "query", "queries")} since {dayWords(oldest)}
          </span>
        )}
        {episodes.length >= READ_LIMIT && (
          <Chip title={`One read takes the newest ${formatCount(READ_LIMIT)} queries; older ones are kept but not read here.`}>
            {`the latest ${formatCount(READ_LIMIT)} · older not read`}
          </Chip>
        )}
        {readError && <Chip tone="down" title={readError} testId="activity-reread-failed">the last re-read failed</Chip>}
        <span style={{ flex: 1 }} />
        <RunState status={status} statusFailed={statusFailed} stopped={stopped}
          onStop={handleStop} onResume={handleResume} onRestart={handleRestart}
          stopping={stopping} resuming={resuming} restarting={restarting} />
      </div>
      {runError && <div role="alert" className="aug-fs-sm" data-testid="run-error" style={{ color: "var(--amb4)" }}>{runError}</div>}

      <NeedsYou testId="activity-needs"
        empty={`Nothing needs you · no failed query${range === "all" ? "" : " in this range"}, no run waiting`}>
        {[
          failures.length > 0 && (
            <NeedsRow key="failed" testId="needs-failed"
              title={`${countNoun(failedRuns.length, "query", "queries")} failed${failDays.length === 1 ? ` · ${failDays[0]}` : ""}`}
              detail={fixAllError ? `Fix all did not run — ${fixAllError}`
                : fixAllSummary ? `fixed ${fixAllSummary.fixed} of ${fixAllSummary.total} · saved ${fixAllSummary.saved}`
                  + `${fixAllSummary.flagged > 0 ? ` (${fixAllSummary.flagged} flagged)` : ""}`
                  + `${fixAllSummary.failed > 0 ? ` · ${fixAllSummary.failed} still failing` : ""}`
                : `${failures[0].error}${errorsSaid.size > 1 ? ` · and ${countNoun(errorsSaid.size - 1, "other error")}` : ""}`}
              actions={<>
                <Button size="xs" variant="ghost" onClick={() => setOutcome("error")}>Show</Button>
                <Button size="xs" variant="secondary" onClick={handleFixAll} disabled={fixingAll}
                  title={`Repair the ${countNoun(failedRuns.length, "failed query", "failed queries")} in this range and save each that works as a finding`}>
                  {fixingAll ? "Fixing…" : `Fix all ${failedRuns.length}`}
                </Button>
              </>} />
          ),
          interrupted && status && (
            <NeedsRow key="interrupted" testId="needs-interrupted"
              title={(status.interrupted_schemas ?? []).length
                ? `The run stopped on ${(status.interrupted_schemas ?? []).join(", ")}`
                : `The run stopped at ${phaseWord(status.phase)}`}
              detail={status.interrupted_note}
              actions={<>
                <Button size="xs" variant="secondary" onClick={handleResume} disabled={resuming || restarting}>
                  {resuming ? "Resuming…" : "Continue"}
                </Button>
                <Button size="xs" variant="ghost" onClick={handleRestart} disabled={resuming || restarting}>
                  {restarting ? "Restarting…" : "Restart"}
                </Button>
              </>} />
          ),
          status?.held_note && (
            <NeedsRow key="held" testId="needs-held" title="A run is held" detail={status.held_note} />
          ),
        ]}
      </NeedsYou>

      <ListCard<Item>
        testId="activity-log"
        label="Queries"
        name="explorer-queries"
        tools={<>
          <Segmented label="Outcome" value={outcome} onChange={setOutcome} options={[
            { value: "all", label: "All" }, { value: "success", label: "Succeeded" }, { value: "error", label: "Failed" },
          ]} />
          <Segmented label="Range" value={range} onChange={setRange} options={[
            { value: "all", label: "All dates" }, { value: "today", label: "Today" },
            { value: "yesterday", label: "Yesterday" }, { value: "week", label: "This week" },
          ]} />
        </>}
        rows={shown}
        page={30}
        rowKey={it => it.key}
        columns={[
          { head: "When", value: it => `${dayKey(it.at)} ${clock(it.at)}` },
          { head: "Times", value: it => it.members.length },
          { head: "Kind", value: it => it.kind },
          { head: "Asked", value: it => it.asked },
          { head: "Table", value: it => it.table },
          { head: "Rows", value: it => it.rows },
          { head: "Outcome", value: it => (it.failed ? "failed" : "ran") },
          { head: "Error", value: it => (it.failed ? it.ep.observation : "") },
          { head: "SQL", value: it => it.ep.sql },
        ]}
        group={{
          key: it => dayKey(it.at),
          head: (_k, rows) => dayWords(rows[0].at),
          meta: (_k, rows) => {
            const runs = rows.reduce((n, r) => n + r.members.length, 0);
            const failed = rows.reduce((n, r) => n + (r.failed ? r.members.length : 0), 0);
            return `${countNoun(runs, "query", "queries")}${failed ? ` · ${failed} failed` : ""}`;
          },
        }}
        empty={items.length === 0
          ? "Nothing has run here yet — the explorer's queries appear as it runs."
          : "No query matches these filters."}
        renderRow={(it, first) => (
          <QueryRow key={it.key} item={it} first={first} open={open.has(it.key)} onToggle={() => toggle(it.key)}
            connectionId={connectionId} canvasId={canvasId} />
        )}
      />
    </Page>
  );
}
