"use client";

/**
 * Agent runs — the person's run history, laid out to CLARITY (`aughor-v2/CLARITY.md`): four figures (runs, the
 * questions behind them, the ones that did not finish, what is running), the runs that need a person in amber with
 * their buttons on the row, then the list — one row per question, its repeats folded into ×N with the latest
 * headline, the earlier runs one click away.
 *
 * It was a wall of fifty cards: the same three questions asked ten times each, a green "Completed" on every one, a
 * dash where a run kept no headline. Only what is not completed is said now, and it is said first.
 *
 * This is the person's history (the run list). The machine view of the same runs — events, traces, spans — is
 * Agent Ops ▸ Activity, one link away; they are views over different records, so they stay two (PX-6).
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { CARD, Chip, Dot, Empty, Figure, Figures, Label, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, Page, ROW, RULE }
  from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Segmented } from "@/components/ui/segmented";
import { Loading, ReadFailed } from "@/components/ui/states";
import { getConnections, type Connection } from "@/lib/api";
import { getApiBase } from "@/lib/config";
import { subscribeKernelEvents } from "@/lib/events";
import { countNoun, formatCount, formatTimestamp, relTime } from "@/lib/format";
import { dayWords, normalizeQuestion } from "@/lib/home";
import { connectionLabel, keyToWords } from "@/lib/names";
import { localizeCurrency } from "@/lib/orgSettings";
import { runDisplayTitle } from "@/lib/runTitle";

/** How many of the newest runs the page reads — the list endpoint's own default, said on the page when it is hit. */
export const READ = 50;

/** The two kinds the run list holds, spelled as the wire spells them (the deep analysis keeps its frozen name). */
export type RunKind = "investigation" | "chat";

/** One row of the run list, as this page uses it. */
export interface Run {
  id: string;
  question: string;
  started_at: string;
  completed_at?: string | null;
  status: string;
  headline: string | null;
  kind?: string;
  connection_id?: string;
  canvas_id?: string | null;
}

/** A status that is not "complete", as a mark: its word and its hue. A completed run wears none. */
const MARK: Record<string, { word: string; hue: "red" | "amber" | "blue" | "grey" }> = {
  failed: { word: "failed", hue: "red" },
  timed_out: { word: "timed out", hue: "red" },
  interrupted: { word: "stopped", hue: "grey" },
  cancelled: { word: "stopped", hue: "grey" },
  paused: { word: "paused · waiting", hue: "amber" },
  running: { word: "running", hue: "blue" },
};
/** Ended without an answer. */
const UNFINISHED = new Set(["failed", "timed_out", "interrupted", "cancelled"]);
/** What a person is needed for: a run that ended without an answer, or one waiting at a step. */
const NEEDS = new Set([...UNFINISHED, "paused"]);

const isChat = (r: Run) => r.kind === "chat";
const kindOf = (r: Run): RunKind => (isChat(r) ? "chat" : "investigation");
const markOf = (status: string) => status === "complete" ? null
  : MARK[status] ?? { word: keyToWords(status) || "unknown", hue: "grey" as const };
/** Ended badly first, then what is in flight, then the rest. */
const rank = (status: string) => (UNFINISHED.has(status) ? 0 : status === "running" || status === "paused" ? 1 : 2);

/** Prose the platform wrote, as a line: no markdown emphasis (nothing renders it here), the org's currency. */
const plain = (text: string) => localizeCurrency(text).replace(/\*+/g, "");

/** A long question's short label — its first sentence, when more follow ("What changed in theLook in the last day?"
 *  for the daily run's four sentences of instructions). The full text stays on hover. */
export function shortQuestion(q: string): string {
  const cut = q.search(/[?!.]\s+\S/);
  return cut > 0 ? q.slice(0, cut + 1) : q;
}

/** "2d ago", or "just now". */
export function ago(iso: string): string {
  const t = relTime(iso);
  return t === "—" ? "" : /^\d+s$/.test(t) ? "just now" : `${t} ago`;
}

/** The runs of one question: the same kind, on the same connection, asked in the same words (a scheduled run's
 *  grounding stripped first, so a daily run is one question however its date line reads). */
export interface RunGroup {
  key: string;
  /** The question as a person reads it — never the scheduled run's grounding. */
  title: string;
  scheduled: boolean;
  /** Newest first; `runs[0]` is the latest. */
  runs: Run[];
}

export function foldRuns(runs: readonly Run[]): RunGroup[] {
  const groups = new Map<string, RunGroup>();
  const newestFirst = [...runs].sort((a, b) => b.started_at.localeCompare(a.started_at));
  for (const r of newestFirst) {
    const { title, scheduled } = runDisplayTitle(r.question);
    const key = `${kindOf(r)}|${r.connection_id ?? ""}|${normalizeQuestion(title)}`;
    const g = groups.get(key);
    if (g) g.runs.push(r);
    else groups.set(key, { key, title: plain(title) || "A run with no question recorded", scheduled, runs: [r] });
  }
  return [...groups.values()].sort((a, b) => rank(a.runs[0].status) - rank(b.runs[0].status)
    || b.runs[0].started_at.localeCompare(a.runs[0].started_at));
}

type Filter = "all" | "deep" | "chat";

export function AgentRuns({ onGoToChat, onOpenRun, onOpenMachineView, workspaceId }: {
  /** Opens a chat — with a question it asks it straight away. */
  onGoToChat: (q?: string) => void;
  onOpenRun: (id: string, kind: RunKind, connectionId?: string, canvasId?: string | null) => void;
  onOpenMachineView?: () => void;
  workspaceId?: string;
}) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  // A row names its connection, never its id.
  const [conns, setConns] = useState<Connection[]>([]);
  useEffect(() => { getConnections().then(setConns).catch(() => {}); }, []);

  const [tick, setTick] = useState(0);
  const retry = useCallback(() => setTick(t => t + 1), []);
  useEffect(() => {
    let alive = true;
    const load = () => {
      const ctrl = new AbortController();
      const to = setTimeout(() => ctrl.abort(), 8_000);
      const scope = workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : "";
      fetch(`${getApiBase()}/investigations?limit=${READ}${scope}`, { signal: ctrl.signal })
        .then(r => (r.ok ? r.json() : Promise.reject(new Error(`the list was refused (${r.status})`))))
        .then(d => { if (alive) { setRuns(Array.isArray(d) ? d : []); setFailed(null); } })
        .catch(e => { if (alive) setFailed(e instanceof Error ? e.message : String(e)); })
        .finally(() => clearTimeout(to));
    };
    load();
    // Refresh on a run's lifecycle events, so a run started elsewhere (another tab, the API) appears without a reload.
    const unsub = subscribeKernelEvents(() => load(), { kinds: ["investigation."] });
    return () => { alive = false; unsub(); };
  }, [workspaceId, tick]);

  const all = useMemo(() => runs ?? [], [runs]);
  const groups = useMemo(() => foldRuns(all), [all]);

  if (runs === null) {
    return <Page testId="runs">{failed !== null
      ? <ReadFailed what="the runs" error={failed} onRetry={retry} style={CARD} />
      : <Loading what="the runs" style={CARD} />}</Page>;
  }

  if (all.length === 0) {
    return (
      <Page testId="runs">
        <section aria-label="Runs" style={CARD}>
          <Empty>No runs yet.</Empty>
          <Button size="xs" variant="secondary" style={{ marginTop: 8 }} onClick={() => onGoToChat()}>Ask a question</Button>
        </section>
      </Page>
    );
  }

  const deep = all.filter(r => !isChat(r)).length;
  const unfinished = all.filter(r => UNFINISHED.has(r.status)).length;
  const running = all.filter(r => r.status === "running").length;
  const paused = all.filter(r => r.status === "paused").length;
  const since = all.reduce((min, r) => (r.started_at < min ? r.started_at : min), all[0].started_at);
  // Said once: one connection is named in the figures, not on every row; several are named on each row.
  const connIds = [...new Set(all.map(r => r.connection_id).filter((id): id is string => !!id))];
  const where = connIds.length === 1 ? ` · ${connectionLabel(connIds[0], conns)}`
    : connIds.length > 1 ? ` · ${countNoun(connIds.length, "connection")}` : "";
  const capped = all.length >= READ;
  const waiting = groups.filter(g => NEEDS.has(g.runs[0].status));
  const shown = filter === "all" ? groups : groups.filter(g => (filter === "chat") === isChat(g.runs[0]));
  const open = (r: Run) => onOpenRun(r.id, kindOf(r), r.connection_id, r.canvas_id);

  return (
    <Page testId="runs">
      <Figures testId="runs-figures">
        <Figure testId="runs-fig-runs" label="Runs" value={formatCount(all.length)}
          sub={<>
            <span>since {dayWords(since)}{where}</span>
            {capped && <Chip title={`This page reads the newest ${READ} runs; older ones are not listed`}>newest {READ}</Chip>}
          </>} />
        <Figure testId="runs-fig-questions" label="Questions" value={formatCount(groups.length)}
          sub={all.length > groups.length ? `${formatCount(all.length - groups.length)} repeat runs folded` : "none repeated"} />
        <Figure testId="runs-fig-unfinished" label="Didn't finish" value={formatCount(unfinished)}
          tone={unfinished ? "red" : undefined} sub="failed, timed out or stopped" />
        <Figure testId="runs-fig-running" label="Running" value={formatCount(running)}
          sub={paused ? `${formatCount(paused)} paused, waiting` : running ? "in flight now" : "nothing in flight"} />
      </Figures>

      {failed !== null && (
        <div className="aug-fs-xs" style={ROW}>
          <Chip tone="amber" title={failed}>not refreshed — showing the last list read</Chip>
          <Button variant="link" size="xs" onClick={retry}>Retry</Button>
        </div>
      )}

      {waiting.length > 0 && (
        <NeedsYou testId="runs-needs" right={countNoun(waiting.length, "question")}>
          {waiting.map(g => {
            const latest = g.runs[0];
            const repeats = g.runs.filter(r => r.status === latest.status).length;
            return (
              <NeedsRow key={g.key} testId="runs-needs-row" title={<span style={ONE_LINE} title={g.title}>{shortQuestion(g.title)}</span>}
                detail={<span style={{ ...ROW, flexWrap: "nowrap", gap: 6 }}>
                  <StatusMark status={latest.status} />
                  <span>· {ago(latest.started_at)}{repeats > 1 ? ` · ${repeats} times` : ""}</span>
                </span>}
                actions={<>
                  <Button size="xs" variant="secondary" onClick={() => open(latest)}>Open</Button>
                  {!g.scheduled && latest.status !== "paused" && (
                    <Button size="xs" variant="ghost" title="Asks it again in a chat"
                      onClick={() => onGoToChat(runDisplayTitle(latest.question).title)}>
                      Ask again
                    </Button>
                  )}
                </>} />
            );
          })}
        </NeedsYou>
      )}

      <section aria-label="Runs by question" data-testid="runs-list" style={CARD}>
        <Label right={<>
          <Segmented label="Which runs" value={filter} onChange={setFilter} options={[
            { value: "all", label: <>All <span style={{ ...MUTED, ...NUM }}>{formatCount(all.length)}</span></> },
            { value: "deep", label: <>Deep analyses <span style={{ ...MUTED, ...NUM }}>{formatCount(deep)}</span></> },
            { value: "chat", label: <>Conversations <span style={{ ...MUTED, ...NUM }}>{formatCount(all.length - deep)}</span></> },
          ]} />
          {onOpenMachineView && (
            <Button variant="ghost" size="xs" onClick={onOpenMachineView}
              title="The machine view of every run — its events, traces and spans — in Agent Ops">
              Traces &amp; spans <Icon name="chevr" size={12} />
            </Button>
          )}
        </>}>
          By question
        </Label>
        {shown.length === 0 ? (
          <Empty>{filter === "chat" ? "No conversations" : "No deep analyses"} in the {capped ? `newest ${READ} runs` : "runs"}.</Empty>
        ) : shown.map((g, i) => (
          <GroupRow key={g.key} g={g} first={i === 0} showConn={connIds.length > 1} conns={conns} onOpen={open} />
        ))}
      </section>
    </Page>
  );
}

function StatusMark({ status }: { status: string }) {
  const m = markOf(status);
  if (!m) return null;
  return (
    <span data-testid="run-status" style={{ display: "inline-flex", alignItems: "center", gap: 5, flex: "0 0 auto",
      color: m.hue === "red" ? "var(--red4)" : m.hue === "amber" ? "var(--amb4)" : m.hue === "blue" ? "var(--blue4)" : "var(--t2)" }}>
      <Dot hue={m.hue} />{m.word}
    </span>
  );
}

/** What a run found, as its muted line — or, for a finished run that kept no headline, that it kept none. */
function Headline({ run }: { run: Run }) {
  if (run.headline?.trim()) return <span style={{ ...ONE_LINE, flex: "0 1 auto" }}>{plain(run.headline)}</span>;
  return run.status === "complete" ? <span style={{ ...MUTED, flex: "0 0 auto" }}>no headline</span> : null;
}

const ROW_BUTTON = {
  display: "block", width: "100%", height: "auto", margin: 0, padding: "3px 4px", textAlign: "left", whiteSpace: "normal",
  fontWeight: 400, minWidth: 0,
} as const;

function GroupRow({ g, first, showConn, conns, onOpen }: {
  g: RunGroup; first: boolean; showConn: boolean; conns: Connection[]; onOpen: (r: Run) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const latest = g.runs[0];
  const earlier = g.runs.slice(1);
  const earlierUnfinished = earlier.filter(r => UNFINISHED.has(r.status)).length;
  const chat = isChat(latest);
  return (
    <div data-testid="run-group" style={{ padding: "5px 0", ...(first ? {} : RULE) }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 64px 64px", gap: 10, alignItems: "center" }}>
        <Button variant="ghost" onClick={() => onOpen(latest)} title={g.title} style={ROW_BUTTON}>
          <span style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
            <span title={chat ? "a conversation" : "a deep analysis"} style={{ display: "inline-flex", color: "var(--t3)", flex: "0 0 auto" }}>
              <Icon name={chat ? "chat" : "spark"} size={13} />
            </span>
            <span className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }}>{shortQuestion(g.title)}</span>
          </span>
          <span className="aug-fs-xs" style={{ ...ROW, flexWrap: "nowrap", gap: 6, color: "var(--t2)", marginTop: 2,
            paddingLeft: 20, minWidth: 0 }}>
            <StatusMark status={latest.status} />
            <Headline run={latest} />
            {g.scheduled && <Chip title="Asked by a schedule, not a person">scheduled</Chip>}
            {showConn && latest.connection_id && <span style={{ ...MUTED, flex: "0 0 auto" }}>· {connectionLabel(latest.connection_id, conns)}</span>}
            {earlierUnfinished > 0 && (
              <Chip tone="down" title="Earlier runs of this question that ended without an answer">
                {formatCount(earlierUnfinished)} earlier didn&apos;t finish
              </Chip>
            )}
          </span>
        </Button>
        <span style={{ textAlign: "right" }}>
          {earlier.length > 0 && (
            <Button variant="ghost" size="xs" aria-expanded={expanded} onClick={() => setExpanded(e => !e)}
              title={expanded ? "Hide the earlier runs" : `Show the ${countNoun(earlier.length, "earlier run")}`}
              style={{ ...NUM, fontWeight: 600, color: "var(--t1)" }}>
              ×{formatCount(g.runs.length)} <Icon name={expanded ? "chevu" : "chevd"} size={12} />
            </Button>
          )}
        </span>
        <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, textAlign: "right", whiteSpace: "nowrap" }}
          title={formatTimestamp(latest.started_at)}>
          {ago(latest.started_at)}
        </span>
      </div>
      {expanded && (
        <div data-testid="run-earlier" style={{ margin: "2px 0 4px 24px", paddingLeft: 10, borderLeft: "1px solid var(--b1)" }}>
          {earlier.map(r => (
            <Button key={r.id} variant="ghost" onClick={() => onOpen(r)} title={formatTimestamp(r.started_at)}
              style={{ ...ROW_BUTTON, display: "grid", gridTemplateColumns: "130px minmax(0, 1fr)", gap: 10, alignItems: "center" }}>
              <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, whiteSpace: "nowrap" }}>{formatTimestamp(r.started_at, "short")}</span>
              <span className="aug-fs-xs" style={{ ...ROW, flexWrap: "nowrap", gap: 6, color: "var(--t2)", minWidth: 0 }}>
                <StatusMark status={r.status} />
                <Headline run={r} />
              </span>
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
