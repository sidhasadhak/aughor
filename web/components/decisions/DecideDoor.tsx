"use client";

/**
 * The Decide door on what a person reads — a dashboard Question's answer, a Briefing's figure (the decision-framework
 * study §3.2 and §8 step 3, `docs/DECISION_FRAMEWORK_STUDY_2026-10-26.md`). Home's Decide was the only door on a figure
 * the platform showed; a decision taken on anything else booked nothing, or booked it citing nothing.
 *
 * The server cites what the decision was taken on, never the page: a run's answer by the claims its receipt booked, a
 * Briefing figure by measuring it for the edition's days and booking that reading with its own receipt. What it could
 * not cite is said on the decision. With nowhere to book it — no connection — the door is not shown.
 */
import { useEffect, useState, type CSSProperties } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { getMetrics, type Metric } from "@/lib/api";
import { utcDayWords } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { requestTab } from "@/lib/navigate";
import { declareDecision, type ExpectationIn } from "@/lib/record";

const row: CSSProperties = { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" };
const muted: CSSProperties = { color: "var(--t3)" };

/** The option every door puts beside what was chosen: deciding not to act is a decision too. */
export const NOT_ACT = "not act";
const DIRECTIONS = [{ value: "up", label: "go up" }, { value: "down", label: "go down" }, { value: "hold", label: "hold" }];

export interface Expect { metric: string; direction: string; dimension: string; part: string }
export const NO_EXPECT: Expect = { metric: "", direction: "up", dimension: "", part: "" };

/** An expectation as the declare door takes it; null when no metric was named (then nothing can be scored). */
export function expectationOf(v: Expect): ExpectationIn | null {
  if (!v.metric) return null;
  return {
    metric: v.metric, direction: v.direction,
    ...(v.dimension && v.part.trim() ? { segment_dimension: v.dimension, segment_value: v.part.trim() } : {}),
  };
}

/** The metrics a review can measure for the weeks after a decision: approved, and knowing their dates. */
export function useReviewableMetrics(connectionId: string, open: boolean): Metric[] {
  const [metrics, setMetrics] = useState<Metric[]>([]);
  useEffect(() => {
    if (!open || !connectionId) return;
    let alive = true;
    getMetrics(connectionId).then(ms => { if (alive) setMetrics(ms.filter(x => x.status === "approved" && x.time_kind && x.time_column)); })
      .catch(() => { if (alive) setMetrics([]); });
    return () => { alive = false; };
  }, [open, connectionId]);
  return metrics;
}

/** What a decision expects: an approved metric that knows its dates, the way it should move, and — for a metric with
 *  dimensions — one part of it, read against the rest of its group at review (PENDING 57, D-1/D-3). */
export function ExpectRow({ metrics, value, onChange, testId = "home-expect" }: {
  metrics: Metric[]; value: Expect; onChange: (v: Expect) => void; testId?: string;
}) {
  const m = metrics.find(x => x.name === value.metric);
  return (
    <div style={{ ...row, marginTop: 6 }} data-testid={testId}>
      <span className="aug-fs-xs" style={muted}>Expect</span>
      <SelectField aria-label="The metric it should move" value={value.metric} style={{ maxWidth: 220 }}
        onChange={e => onChange({ ...value, metric: e.target.value, dimension: "", part: "" })}>
        <option value="">nothing named — it cannot be scored</option>
        {withUniqueKeys(metrics, x => x.name).map(([k, x]) => <option key={k} value={x.name}>{x.label || x.name}</option>)}
      </SelectField>
      {value.metric && (
        <SelectField aria-label="The way it should move" value={value.direction} style={{ maxWidth: 120 }}
          onChange={e => onChange({ ...value, direction: e.target.value })}>
          {DIRECTIONS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
        </SelectField>
      )}
      {m && (m.dimensions ?? []).length > 0 && (
        <>
          <SelectField aria-label="One part of it" value={value.dimension} style={{ maxWidth: 160 }}
            onChange={e => onChange({ ...value, dimension: e.target.value, part: "" })}>
            <option value="">all of it</option>
            {(m.dimensions ?? []).map(d => <option key={d} value={d}>{`for one ${d.replace(/_/g, " ")}`}</option>)}
          </SelectField>
          {value.dimension && (
            <Input aria-label="Which one" value={value.part} placeholder="e.g. Jeans" style={{ maxWidth: 140 }}
              onChange={e => onChange({ ...value, part: e.target.value })} />
          )}
        </>
      )}
    </div>
  );
}

/** What the decision is taken on: a run's answer, or one of an edition's figures over its days. */
export type DecideOn =
  | { kind: "run"; runId: string }
  | { kind: "figure"; figures: { metric: string; label: string }[]; start: string; end: string };

/** The door: one button, then — only when asked — what was decided, what it should move, and Book it. */
export function DecideDoor({ connectionId, question, on, testId }: {
  connectionId: string;
  /** What was being decided, as the reader saw it: the question asked, or the edition's heading. */
  question: string;
  on: DecideOn;
  testId: string;
}) {
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState("");
  const [figure, setFigure] = useState(on.kind === "figure" ? on.figures[0]?.metric ?? "" : "");
  const [expect, setExpect] = useState<Expect>(NO_EXPECT);
  const [said, setSaid] = useState<{ line: string; id?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const metrics = useReviewableMetrics(connectionId, open);
  if (!connectionId) return null;
  if (on.kind === "figure" && on.figures.length === 0) return null;
  const figureLabel = on.kind === "figure" ? on.figures.find(f => f.metric === figure)?.label ?? figure : "";

  const book = async () => {
    setBusy(true);
    try {
      const expectation = expectationOf(expect);
      const d = await declareDecision({
        question: on.kind === "figure" ? `${question} — ${figureLabel}` : question,
        chosen: chosen.trim(), options: [chosen.trim(), NOT_ACT], connection_id: connectionId,
        note: on.kind === "run" ? `Decided on the answer of run ${on.runId}` : `Decided on ${figureLabel}, ${on.start} to ${on.end}`,
        ...(on.kind === "run" ? { run_id: on.runId } : { figure: { metric: figure, start: on.start, end: on.end } }),
        ...(expectation ? { expectation } : {}),
      });
      const cited = d.relied_on.length;
      const why = typeof d.extra.relied_on_note === "string" ? d.extra.relied_on_note : "";
      setSaid({
        id: d.id,
        line: `Booked as a decision · review ${utcDayWords(d.review_on)} · `
          + (cited ? `it cites ${cited === 1 ? "what it was decided on" : `${cited} claims it was decided on`}` : why || "it cites nothing")
          + (expectation ? "" : " · nothing expected, so it cannot be scored"),
      });
      setOpen(false); setChosen(""); setExpect(NO_EXPECT);
    } catch (e) {
      setSaid({ line: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid={testId} style={{ marginTop: 8 }}>
      {!open ? (
        <div style={row}>
          <Button size="xs" variant="secondary" onClick={() => { setOpen(true); setSaid(null); }}>Decide</Button>
          {said && <span className="aug-fs-xs" style={muted}>{said.line}</span>}
          {said?.id && (
            <Button size="xs" variant="ghost" onClick={() => requestTab("decisions", { id: said.id! })}>Open it →</Button>
          )}
        </div>
      ) : (
        <>
          <div style={row}>
            {on.kind === "figure" && on.figures.length > 1 && (
              <SelectField aria-label="The figure it was decided on" value={figure} style={{ maxWidth: 200 }}
                onChange={e => setFigure(e.target.value)}>
                {withUniqueKeys(on.figures, f => f.metric).map(([k, f]) => <option key={k} value={f.metric}>{f.label}</option>)}
              </SelectField>
            )}
            <Input aria-label="What was decided" value={chosen} onChange={e => setChosen(e.target.value)} style={{ flex: 1, minWidth: 180 }}
              placeholder="What was decided?" />
            <Button size="sm" disabled={!chosen.trim() || busy} onClick={book}>Book it</Button>
            <Button size="sm" variant="ghost" onClick={() => { setOpen(false); setChosen(""); }}>Cancel</Button>
          </div>
          <ExpectRow metrics={metrics} value={expect} onChange={setExpect} testId={`${testId}-expect`} />
        </>
      )}
    </div>
  );
}
