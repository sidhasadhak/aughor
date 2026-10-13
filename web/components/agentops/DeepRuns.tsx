"use client";

/**
 * Agent Ops · Overview — the deep runs, each titled by its question: a row opens its phases and its trace beside it.
 *
 * It was the Phases view of the Activity tab, which folded into the Overview (2026-10-13). That list titled a run by
 * its stored question, so a scheduled run read as the grounding code writes for the model ("[Scheduled-run context —
 * written by code, not inferred] This is a scheduled daily run at …"). The run list's own fold (`runs/AgentRuns.tsx`)
 * already strips it (`lib/runTitle.ts`, the format `aughor/automations/temporal.py` writes) and folds the same
 * question asked again into one row with its count; this reads the same way, so a daily run is one row, "×N".
 *
 * **A run's trace is looked up, not assumed.** A deep run someone asked mints its trace from its own id, so the two
 * coincide; a scheduled one runs inside its automation's trace, whose id is not the run's — measured on theLook
 * 2026-10-13, `/traces/<run id>` answered 404 for every scheduled run, and the trace index filtered to the run named
 * the trace that holds it. So the trace beside a row is the one the index names for it, and the run's own id only when
 * the index names none.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { RunPhases } from "@/components/agentops/RunPhases";
import { TraceView } from "@/components/TraceExplorerPanel";
import { Card, Chip, Empty, Label, MUTED, NUM, ONE_LINE, ROW, RULE } from "@/components/clarity/kit";
import { StatusMark, ago, foldRuns, isChat, shortQuestion, type Run, type RunGroup } from "@/components/runs/AgentRuns";
import { Button } from "@/components/ui/button";
import { Loading, ReadFailed } from "@/components/ui/states";
import { getInvestigationsList, getTraces } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { useVisiblePoll } from "@/lib/useVisiblePoll";

/** How many of the newest runs the card reads — the read the Phases view made. Said on the card when it is reached. */
export const DEEP_READ = 30;
/** How many questions show before "all". */
const SHOWN = 5;

export function DeepRuns({ onResume }: {
  /** Opens a paused run where it is resumed. */
  onResume?: (runId: string) => void;
}) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [capped, setCapped] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ group: string; run: string } | null>(null);
  const [all, setAll] = useState(false);

  const load = useCallback(() => {
    getInvestigationsList(DEEP_READ)
      .then(rows => { setRuns(rows.filter(r => !isChat(r))); setCapped(rows.length >= DEEP_READ); setError(null); })
      .catch(e => setError(String(e?.message || e)));
  }, []);
  useEffect(() => { load(); }, [load]);
  // Only while the Overview is on screen, as the Phases view polled.
  useVisiblePoll(load, 20_000);

  const groups = useMemo(() => foldRuns(runs ?? []), [runs]);
  const shown = all ? groups : groups.slice(0, SHOWN);

  return (
    <Card label="Deep runs · by their question" testId="ao-deep-runs" ariaLabel="Deep runs"
      right={<>
        {capped && <span>in the newest {DEEP_READ} runs</span>}
        <span>a row opens its phases and its trace beside it</span>
      </>}>
      {error !== null && runs === null ? (
        <ReadFailed what="the deep runs" error={error} onRetry={load} />
      ) : runs === null ? (
        <Loading what="the deep runs" />
      ) : groups.length === 0 ? (
        <Empty>{capped ? `No deep runs in the newest ${DEEP_READ} runs.` : "No deep runs yet — ask a “why” question to start one."}</Empty>
      ) : (
        <>
          {error !== null && <ReadFailed what="the deep runs again — these are from the last read" error={error} onRetry={load} />}
          {shown.map((g, i) => (
            <DeepRunRow key={g.key} group={g} first={i === 0}
              open={open?.group === g.key ? open.run : null}
              onOpen={run => setOpen(run ? { group: g.key, run } : null)} onResume={onResume} />
          ))}
          {groups.length > SHOWN && (
            <div style={{ ...RULE, paddingTop: 6 }}>
              <Button variant="link" size="xs" aria-expanded={all} onClick={() => setAll(v => !v)}>
                {all ? `the first ${SHOWN}` : `+${groups.length - SHOWN} more questions · all ›`}
              </Button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

/** One question: what was asked, scheduled or asked, how many times, how the latest ended and when. */
function DeepRunRow({ group, first, open, onOpen, onResume }: {
  group: RunGroup; first: boolean;
  /** The run open beside the row, or null. */
  open: string | null;
  onOpen: (runId: string | null) => void;
  onResume?: (runId: string) => void;
}) {
  const latest = group.runs[0];
  const times = group.runs.length;
  return (
    <div data-testid="ao-deep-run" style={{ padding: "8px 0", ...(first ? {} : RULE) }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto auto", alignItems: "center", gap: 12 }}>
        <div style={{ minWidth: 0 }} title={group.title}>
          <div data-testid="ao-deep-run-title" className="aug-fs-chrome"
            style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }}>
            {shortQuestion(group.title)}
          </div>
          <div className="aug-fs-xs" style={{ ...ROW, gap: 6, color: "var(--t2)", marginTop: 2 }}>
            {group.scheduled
              ? <Chip testId="ao-deep-run-scheduled" title="Run by an automation on its schedule">scheduled</Chip>
              : <span>asked</span>}
            {times > 1 && <span style={NUM}>×{formatCount(times)}</span>}
          </div>
        </div>
        <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>
          {latest.status === "complete" ? <span style={MUTED}>complete</span> : <StatusMark status={latest.status} />}
        </span>
        <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }} title={latest.started_at}>{ago(latest.started_at)}</span>
        <Button variant="ghost" size="xs" aria-expanded={open !== null}
          onClick={() => onOpen(open === null ? latest.id : null)}>
          {open === null ? "Open" : "Close"}
        </Button>
      </div>
      {open !== null && (
        <RunDetail key={open} group={group} runId={open} onChoose={id => onOpen(id)} onResume={onResume} />
      )}
    </div>
  );
}

/** One run of a question: its phases, and its trace beside them. A question asked more than once offers each run. */
function RunDetail({ group, runId, onChoose, onResume }: {
  group: RunGroup; runId: string; onChoose: (runId: string) => void; onResume?: (runId: string) => void;
}) {
  const run = group.runs.find(r => r.id === runId) ?? group.runs[0];
  const [trace, setTrace] = useState<string | null>(null);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    getTraces({ investigation_id: run.id, limit: 1 })
      .then(d => { if (alive) setTrace(d.traces[0]?.trace_id ?? run.id); })
      .catch(e => { if (alive) setTraceError(String(e?.message || e)); });
    return () => { alive = false; };
  }, [run.id, attempt]);

  return (
    <div data-testid="ao-deep-run-detail" style={{ marginTop: 8 }}>
      {group.runs.length > 1 && (
        <div className="aug-fs-xs" style={{ ...ROW, gap: 4, marginBottom: 8, color: "var(--t2)" }}>
          <span>Each time it ran:</span>
          {group.runs.map(r => (
            <Button key={r.id} size="xs" variant={r.id === run.id ? "secondary" : "ghost"} aria-pressed={r.id === run.id}
              title={r.started_at} onClick={() => onChoose(r.id)}>
              {ago(r.started_at)}
            </Button>
          ))}
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "stretch" }}>
        <div style={{ flex: "1 1 260px", minWidth: 0, maxHeight: 560, overflowY: "auto" }}>
          <Label>Phases</Label>
          <RunPhases runId={run.id} onResume={onResume} />
        </div>
        <div data-testid="ao-deep-run-trace" style={{ flex: "2 1 440px", minWidth: 0, height: 560, display: "flex",
          flexDirection: "column", borderLeft: "1px solid var(--b0)" }}>
          {traceError !== null ? (
            <ReadFailed what="which trace holds this run" error={traceError} style={{ padding: 16 }}
              onRetry={() => { setTraceError(null); setAttempt(a => a + 1); }} />
          ) : trace === null ? (
            <Loading what="its trace" style={{ padding: 16 }} />
          ) : (
            <TraceView traceId={trace} answer={run.headline ?? ""} />
          )}
        </div>
      </div>
    </div>
  );
}
