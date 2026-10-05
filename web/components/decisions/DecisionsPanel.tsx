"use client";

/**
 * Decisions — "what are we choosing, and what did we choose?" (the 2027 study §V, screens 5
 * and 6).
 *
 * The decision is the organisation's: the question and who is answerable, the options side by
 * side, what it relied on as recorded at that moment, the dissent kept, the expectation booked
 * when it was taken and the date it is reviewed on — and, after that date, what became of it
 * against the expectation and against the baseline.
 *
 * A scenario has no page of its own. It lives inside the decision it was projected for: its
 * assumptions with whose they are, each prediction with the method that produced it and what
 * that method must say, the limits in words, and what each will be scored against.
 */
import { useMemo, useState } from "react";

import type { Connection } from "@/lib/api";
import { countNoun, formatTableNumber, pct } from "@/lib/format";
import { connectionLabel } from "@/lib/names";
import {
  bookOutcome, bookScenario, declareDecision, getCalibration, getDecision, listDecisions, listScenarios,
  plainWho, verdictWords, whoLabel,
  type CalibrationRow, type Claim, type Decision, type DecisionDetail, type OutcomeVerdict, type Scenario,
} from "@/lib/record";
import {
  Absent, BackHeader, ClaimLine, Fact, Gate, Ledger, Page, Section, day, dayDistance, daysUntil, useLoad,
  type LedgerColumn,
} from "@/components/record/kit";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Filter = "all" | "due" | "waiting" | "reviewed";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "due", label: "Review due" },
  { id: "waiting", label: "Awaiting its date" },
  { id: "reviewed", label: "Reviewed" },
];

/** Where a decision stands against its review date. */
export function reviewState(d: Pick<Decision, "outcome" | "review_on">): "reviewed" | "due" | "waiting" {
  if (d.outcome) return "reviewed";
  const n = daysUntil(d.review_on);
  return n !== null && n <= 0 ? "due" : "waiting";
}

const REVIEW_HUE: Record<string, ChipHue> = { reviewed: "muted", due: "caution", waiting: "info" };
const REVIEW_WORDS: Record<string, string> = { reviewed: "reviewed", due: "review due", waiting: "awaiting its date" };
const VERDICT_HUE: Record<string, ChipHue> = { as_expected: "positive", better: "positive", worse: "negative", cannot_tell: "muted" };

const SOURCE_WORDS: Record<string, string> = {
  declared: "declared in a sentence",
  recommendation: "by accepting a recommendation",
  approval: "by approving an action",
  reply: "by a reply",
};

export function DecisionsPanel({ connections, selectedConn, openId, onOpen, onOpenClaim }: {
  connections: Connection[];
  selectedConn: string;
  openId: string | null;
  onOpen: (id: string | null) => void;
  onOpenClaim: (id: string) => void;
}) {
  if (openId) {
    return <DecisionReader id={openId} connections={connections} onBack={() => onOpen(null)} onOpenClaim={onOpenClaim} />;
  }
  return <DecisionLedger connections={connections} selectedConn={selectedConn} onOpen={onOpen} />;
}

function DecisionLedger({ connections, selectedConn, onOpen }: {
  connections: Connection[]; selectedConn: string; onOpen: (id: string) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [declaring, setDeclaring] = useState(false);
  const load = useLoad(() => listDecisions({ limit: 300 }), []);
  const rows = useMemo(
    () => (load.data ?? []).filter(d => filter === "all" || reviewState(d) === filter),
    [load.data, filter]);
  const many = new Set((load.data ?? []).map(d => d.connection_id)).size > 1;
  const columns: LedgerColumn<Decision>[] = [
    { head: "Question", cell: d => d.question, width: "34%" },
    { head: "Chosen", cell: d => d.chosen },
    { head: "Decided by", cell: d => whoLabel(d.decided_by), width: 130 },
    { head: "Decided", cell: d => day(d.decided_at), width: 110 },
    { head: "Review date", cell: d => (d.review_on ? `${day(d.review_on)} · ${dayDistance(d.review_on)}` : "none set"), width: 190 },
    { head: "Review", cell: d => <StatusChip hue={REVIEW_HUE[reviewState(d)]}>{REVIEW_WORDS[reviewState(d)]}</StatusChip>, width: 150 },
    ...(many ? [{ head: "Connection", cell: (d: Decision) => (d.connection_id ? connectionLabel(d.connection_id, connections) : "every connection"), width: 150 }] : []),
  ];
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <div className="aug-toolbar">
        <div role="group" aria-label="Filter decisions by review" className="aug-segmented">
          {FILTERS.map(f => (
            <Button key={f.id} variant="ghost" size="xs" aria-pressed={filter === f.id}
              className={`aug-seg-item${filter === f.id ? " active" : ""}`} onClick={() => setFilter(f.id)}>
              {f.label}
            </Button>
          ))}
        </div>
        {load.data && (
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
            {countNoun(rows.length, "decision")} · every connection
          </span>
        )}
        <span style={{ flex: 1 }} />
        <Button size="xs" onClick={() => setDeclaring(v => !v)} aria-expanded={declaring}
          title="A decision taken elsewhere, in one sentence, with what you expect of it">
          Record a decision
        </Button>
      </div>
      <Page wide>
        {declaring && (
          <DeclareForm connectionId={selectedConn} onCancel={() => setDeclaring(false)}
            onBooked={d => { setDeclaring(false); load.reload(); onOpen(d.id); }} />
        )}
        <Gate load={load} what="decisions">
          {() => (
            <Ledger name="decisions" columns={columns} rows={rows} rowKey={d => d.id} onOpen={d => onOpen(d.id)}
              empty={filter === "all"
                ? "No decision is on the record yet. One is booked when a person accepts a recommendation or approves an action, and a decision taken elsewhere can be recorded here in a sentence."
                : `No decision is in "${FILTERS.find(f => f.id === filter)?.label.toLowerCase()}" right now.`} />
          )}
        </Gate>
      </Page>
    </div>
  );
}

const num = (v: string): number | null => (v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v));

/** "We decided this elsewhere" — the question, what was chosen, and the expectation booked with it. */
function DeclareForm({ connectionId, onBooked, onCancel }: {
  connectionId: string; onBooked: (d: DecisionDetail) => void; onCancel: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [chosen, setChosen] = useState("");
  const [others, setOthers] = useState("");
  const [metric, setMetric] = useState("");
  const [low, setLow] = useState("");
  const [high, setHigh] = useState("");
  const [unit, setUnit] = useState("");
  const [reviewOn, setReviewOn] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const lo = num(low), hi = num(high);
      const options = [chosen, ...others.split("\n")].map(o => o.trim()).filter(Boolean);
      const d = await declareDecision({
        question: question.trim(), chosen: chosen.trim(), options, connection_id: connectionId, review_on: reviewOn,
        expectation: metric.trim()
          ? { metric: metric.trim(), low: lo, high: hi, mid: lo !== null && hi !== null ? (lo + hi) / 2 : null, unit: unit.trim(), settles_on: reviewOn }
          : null,
      });
      onBooked(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Section label="Record a decision">
      <div className="aug-form-grid">
        <label className="aug-fs-sm" htmlFor="dec-q">What was being decided</label>
        <Input id="dec-q" value={question} onChange={e => setQuestion(e.target.value)} placeholder="Do we extend the promotion by two weeks?" />
        <label className="aug-fs-sm" htmlFor="dec-c">What was chosen</label>
        <Input id="dec-c" value={chosen} onChange={e => setChosen(e.target.value)} placeholder="Extend it to 15 September" />
        <label className="aug-fs-sm" htmlFor="dec-o">The options not taken</label>
        <Input id="dec-o" value={others} onChange={e => setOthers(e.target.value)} placeholder="End it on schedule" />
        <label className="aug-fs-sm" htmlFor="dec-m">Expected to move</label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Input id="dec-m" value={metric} onChange={e => setMetric(e.target.value)} placeholder="new customers" style={{ flex: "2 1 160px" }} />
          <Input aria-label="Expected low" value={low} onChange={e => setLow(e.target.value)} placeholder="from" inputMode="decimal" style={{ flex: "1 1 80px" }} />
          <Input aria-label="Expected high" value={high} onChange={e => setHigh(e.target.value)} placeholder="to" inputMode="decimal" style={{ flex: "1 1 80px" }} />
          <Input aria-label="Unit" value={unit} onChange={e => setUnit(e.target.value)} placeholder="unit" style={{ flex: "1 1 70px" }} />
        </div>
        <label className="aug-fs-sm" htmlFor="dec-r">Review on</label>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Input id="dec-r" type="date" value={reviewOn} onChange={e => setReviewOn(e.target.value)} style={{ width: 170 }} />
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>left empty, the date is proposed from how long this connection&apos;s days take to settle</span>
        </div>
        <span />
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Button size="xs" disabled={busy || !question.trim() || !chosen.trim()} onClick={() => void submit()}>Book it</Button>
          <Button size="xs" variant="ghost" onClick={onCancel}>Cancel</Button>
          {error && <span className="aug-fs-sm" role="alert" style={{ color: "var(--red4)" }}>{error}</span>}
        </div>
      </div>
    </Section>
  );
}

// ── the Reader ───────────────────────────────────────────────────────────────────────────

function DecisionReader({ id, connections, onBack, onOpenClaim }: {
  id: string; connections: Connection[]; onBack: () => void; onOpenClaim: (id: string) => void;
}) {
  const load = useLoad(() => getDecision(id), [id]);
  const d = load.data;
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <BackHeader from="Decisions" onBack={onBack} title={d?.question ?? "Decision"}
        chips={d && <StatusChip hue={REVIEW_HUE[reviewState(d)]}>{REVIEW_WORDS[reviewState(d)]}</StatusChip>} />
      <Gate load={load} what="the decision">
        {detail => <DecisionBody d={detail} connections={connections} reload={load.reload} onOpenClaim={onOpenClaim} />}
      </Gate>
    </div>
  );
}

function band(c: Claim): string {
  const lo = c.extra.low as number | null | undefined, hi = c.extra.high as number | null | undefined;
  const unit = c.statement.unit ? ` ${c.statement.unit}` : "";
  if (lo == null || hi == null) return c.statement.value != null ? `${formatTableNumber(c.statement.value)}${unit}` : "no interval stated";
  if (lo === hi) return `${formatTableNumber(lo)}${unit} exactly`;
  const cov = typeof c.extra.coverage === "number" ? ` at ${pct(c.extra.coverage as number)} coverage` : "";
  return `${formatTableNumber(lo)} to ${formatTableNumber(hi)}${unit}${cov}`;
}

function DecisionBody({ d, connections, reload, onOpenClaim }: {
  d: DecisionDetail; connections: Connection[]; reload: () => void; onOpenClaim: (id: string) => void;
}) {
  const scenarios = useLoad(() => listScenarios(d.id), [d.id, d.version]);
  const calibration = useLoad(() => getCalibration(d.connection_id || undefined), [d.connection_id]);
  const state = reviewState(d);
  const rail = (
    <>
      <div className="aug-rail-head"><span className="aug-label">This decision</span></div>
      <Fact label="Answerable">{whoLabel(d.owner || d.decided_by)}</Fact>
      {d.approvers.length > 0 && <Fact label="Approvers">{d.approvers.map(whoLabel).join(", ")}</Fact>}
      <Fact label="Decided">{day(d.decided_at)} by {whoLabel(d.decided_by)}</Fact>
      <Fact label="Booked">{SOURCE_WORDS[d.source.kind] ?? d.source.kind}</Fact>
      <Fact label="Review date">{d.review_on ? `${day(d.review_on)} · ${dayDistance(d.review_on)}` : "none set"}</Fact>
      {d.objective && <Fact label="Toward">{d.objective}</Fact>}
      <Fact label="Connection">{d.connection_id ? connectionLabel(d.connection_id, connections) : "every connection"}</Fact>
    </>
  );
  return (
    <Page rail={rail}>
      <Section label="The options" meta={countNoun(d.options.length, "option")}>
        {d.options.length === 0 ? (
          <Absent>Only the choice was recorded: {d.chosen}. The options it was chosen over were not written down.</Absent>
        ) : (
          <div className="aug-options">
            {d.options.map(o => {
              const chosen = o.id === d.chosen || o.description === d.chosen;
              return (
                <div className="aug-option" data-chosen={chosen} key={o.id}>
                  <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                    <span className="aug-fs-ui" style={{ color: "var(--t1)", fontWeight: chosen ? 600 : 400 }}>{o.description}</span>
                    {chosen && <StatusChip hue="info">chosen</StatusChip>}
                  </div>
                  <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
                    {[o.cost && `cost: ${o.cost}`, o.reversibility && `reversibility: ${o.reversibility}`, o.actor && `acts: ${whoLabel(o.actor)}`]
                      .filter(Boolean).join(" · ") || "no cost, reversibility or actor recorded"}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Section>

      <Section label="The scenario"
        meta={scenarios.data ? countNoun(scenarios.data.predictions.filter(p => p.booked_as !== d.expectation_claim).length, "prediction") : undefined}>
        <Gate load={scenarios} what="the scenario">
          {s => <ScenarioBlock decision={d} scenarios={s.scenarios} predictions={s.predictions}
            calibration={calibration.data ?? []} onBooked={() => { scenarios.reload(); reload(); }} onOpenClaim={onOpenClaim} />}
        </Gate>
      </Section>

      <Section label="What it relied on" meta={countNoun(d.relied_on_claims.length, "claim")}>
        {d.relied_on_claims.length === 0 ? (
          <Absent>No claim was cited when this decision was booked.</Absent>
        ) : d.relied_on_claims.map(c => <ClaimLine key={c.id} claim={c} onOpen={onOpenClaim} />)}
      </Section>

      <Section label="Dissent" meta={d.dissent.length ? countNoun(d.dissent.length, "voice") : undefined}>
        {d.dissent.length === 0 ? <Absent>No dissent was recorded.</Absent> : d.dissent.map(x => (
          <div className="aug-item" key={`${x.who}:${x.why}`}>
            <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{x.why}</div>
            <div className="aug-item-foot aug-fs-sm"><span>{whoLabel(x.who)}</span></div>
          </div>
        ))}
      </Section>

      <Section label="The expectation booked">
        {d.expectation ? (
          <div className="aug-item">
            <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{d.expectation.statement.text}</div>
            <div className="aug-item-foot aug-fs-sm">
              <span>{d.expectation.statement.metric}: {band(d.expectation)}</span>
              <span>settles {day(String(d.expectation.extra.settles_on ?? d.review_on))}</span>
              <span>booked by {whoLabel(d.expectation.author)}</span>
            </div>
          </div>
        ) : <Absent>No expectation was booked with this decision, so its outcome can only be read against the baseline.</Absent>}
      </Section>

      <Section label="What became of it">
        {d.outcome_record ? (
          <div className="aug-item">
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <StatusChip hue={VERDICT_HUE[d.outcome_record.verdict] ?? "muted"}>{verdictWords(d.outcome_record.verdict)}</StatusChip>
              <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>{d.outcome_record.why}</span>
            </div>
            <div className="aug-item-foot aug-fs-sm">
              {d.outcome_record.actual != null && <span>actual {formatTableNumber(d.outcome_record.actual)}</span>}
              {d.outcome_record.baseline != null && <span>baseline {formatTableNumber(d.outcome_record.baseline)}</span>}
              {d.outcome_record.against_expectation && <span>against the expectation: {d.outcome_record.against_expectation}</span>}
              <span>measured {day(d.outcome_record.measured_on)} by {whoLabel(d.outcome_record.measured_by)}</span>
            </div>
          </div>
        ) : state === "due" ? (
          <OutcomeForm decisionId={d.id} onBooked={reload} />
        ) : (
          <Absent>
            Its review date is {d.review_on ? `${day(d.review_on)} (${dayDistance(d.review_on)})` : "not set"}. On that date the outcome
            is measured on settled days, against the expectation and against the metric&apos;s own baseline.
          </Absent>
        )}
      </Section>
    </Page>
  );
}

// ── the scenario, inside its decision ────────────────────────────────────────────────────

const METHOD_WORDS: Record<string, string> = {
  identity: "arithmetic on stated inputs — exact",
  declared: "an assumption a named person declared",
  history: "the metric's own history",
  intervention: "past cases of the same change",
};

function licence(method: string, metric: string, rows: CalibrationRow[]): string {
  const mine = rows.filter(r => r.method === method);
  const n = mine.reduce((a, r) => a + r.n - r.cannot_tell, 0);
  if (n === 0) return "no prediction by this method has been scored here yet";
  const inside = mine.reduce((a, r) => a + r.inside, 0);
  const onMetric = mine.filter(r => r.metric === metric).reduce((a, r) => a + r.n - r.cannot_tell, 0);
  return `${inside} of ${n} scored predictions by this method fell inside their interval${onMetric ? ` (${onMetric} on this metric)` : ""}`;
}

function ScenarioBlock({ decision, scenarios, predictions, calibration, onBooked, onOpenClaim }: {
  decision: DecisionDetail; scenarios: Scenario[]; predictions: (Claim & { booked_as?: string })[];
  calibration: CalibrationRow[]; onBooked: () => void; onOpenClaim: (id: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const made = predictions.filter(p => p.id !== decision.expectation?.id && p.booked_as !== decision.expectation_claim);
  const assumptions = scenarios.flatMap(s => s.assumptions);
  const limits = [...new Set(scenarios.flatMap(s => s.limits))];
  return (
    <div>
      {made.length === 0 && !adding && (
        <Absent>No scenario has been projected for this decision. A projection states its method — arithmetic on stated inputs, a named person&apos;s assumption, or the metric&apos;s own history — and is scored when its days settle.</Absent>
      )}
      {assumptions.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          <div className="aug-fs-sm" style={{ color: "var(--t3)", marginBottom: 2 }}>Assumptions</div>
          {assumptions.map(a => (
            <div className="aug-item" key={`${a.variable}:${a.claim}`}>
              <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
                {a.variable}{a.value != null ? ` = ${formatTableNumber(a.value)}` : ""}{a.text ? ` — ${a.text}` : ""}
              </div>
              <div className="aug-item-foot aug-fs-sm"><span>{a.source} by {whoLabel(a.by)}</span></div>
            </div>
          ))}
        </div>
      )}
      {made.map(p => {
        const method = String(p.extra.method ?? "");
        // What the method must say, in a reader's words: the claim it was booked as is the button
        // beside it, and a person is named, not shown as an id.
        const mustSay = (Array.isArray(p.extra.must_say) ? (p.extra.must_say as string[]) : [])
          .filter(m => !m.startsWith("booked as claim")).map(plainWho);
        const scored = p.state === "scored";
        return (
          <div className="aug-item" key={p.id}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>{p.statement.metric}: {band(p)}</span>
              <StatusChip hue="muted" title={METHOD_WORDS[method]}>{method || "no method"}</StatusChip>
              {scored && (
                <StatusChip hue={p.extra.scored_against === "inside" ? "positive" : "negative"}>
                  scored {String(p.extra.scored_against ?? "")}: {formatTableNumber(p.extra.actual as number)}
                </StatusChip>
              )}
            </div>
            <div className="aug-item-foot aug-fs-sm">
              <span>{METHOD_WORDS[method] ?? method}</span>
              {mustSay.map(m => <span key={m}>{m}</span>)}
              <span title="How far this method can be trusted here">{licence(method, p.statement.metric, calibration)}</span>
              {!scored && <span>scored on {day(String(p.extra.settles_on ?? ""))} against the settled figure</span>}
              <span>by {whoLabel(p.author)}</span>
              <span style={{ flex: 1 }} />
              <Button size="xs" variant="ghost" onClick={() => onOpenClaim(p.id)}>Open the claim</Button>
            </div>
          </div>
        );
      })}
      {limits.length > 0 && (
        <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "10px 0 0" }}>
          <span style={{ color: "var(--t3)" }}>Limits: </span>{limits.join(" · ")}
        </p>
      )}
      <div style={{ marginTop: 10 }}>
        {adding
          ? <ProjectForm decision={decision} onCancel={() => setAdding(false)} onBooked={() => { setAdding(false); onBooked(); }} />
          : <Button size="xs" variant="outline" onClick={() => setAdding(true)}>Add a projection</Button>}
      </div>
    </div>
  );
}

/** One projection under one method: arithmetic on stated inputs, or an assumption with a name on it. */
function ProjectForm({ decision, onBooked, onCancel }: {
  decision: DecisionDetail; onBooked: () => void; onCancel: () => void;
}) {
  const [method, setMethod] = useState<"identity" | "declared">("identity");
  const [metric, setMetric] = useState("");
  const [formula, setFormula] = useState("");
  const [inputs, setInputs] = useState("");
  const [variable, setVariable] = useState("");
  const [value, setValue] = useState("");
  const [low, setLow] = useState("");
  const [high, setHigh] = useState("");
  const [unit, setUnit] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      if (method === "identity") {
        const parsed: Record<string, number> = {};
        for (const part of inputs.split(",")) {
          const [k, v] = part.split("=").map(x => x.trim());
          if (!k) continue;
          if (num(v ?? "") === null) throw new Error(`"${part.trim()}" is not a name = number`);
          parsed[k] = Number(v);
        }
        await bookScenario(decision.id, { method, metric: metric.trim(), formula: formula.trim(), inputs: parsed, unit: unit.trim() });
      } else {
        await bookScenario(decision.id, {
          method, metric: metric.trim(), unit: unit.trim(),
          assumption: { variable: variable.trim(), value: num(value), low: num(low), high: num(high), unit: unit.trim() },
        });
      }
      onBooked();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="aug-form-grid">
      <label className="aug-fs-sm">Method</label>
      <div role="group" aria-label="Method" className="aug-segmented" style={{ justifySelf: "start" }}>
        {(["identity", "declared"] as const).map(m => (
          <Button key={m} variant="ghost" size="xs" aria-pressed={method === m} title={METHOD_WORDS[m]}
            className={`aug-seg-item${method === m ? " active" : ""}`} onClick={() => setMethod(m)}>
            {m === "identity" ? "Arithmetic" : "My assumption"}
          </Button>
        ))}
      </div>
      <label className="aug-fs-sm" htmlFor="sc-metric">What it predicts</label>
      <div style={{ display: "flex", gap: 8 }}>
        <Input id="sc-metric" value={metric} onChange={e => setMetric(e.target.value)} placeholder="credit cost" style={{ flex: 1 }} />
        <Input aria-label="Unit" value={unit} onChange={e => setUnit(e.target.value)} placeholder="unit" style={{ width: 90 }} />
      </div>
      {method === "identity" ? (
        <>
          <label className="aug-fs-sm" htmlFor="sc-formula">Formula</label>
          <Input id="sc-formula" value={formula} onChange={e => setFormula(e.target.value)} placeholder="accounts * credit" />
          <label className="aug-fs-sm" htmlFor="sc-inputs">Inputs</label>
          <Input id="sc-inputs" value={inputs} onChange={e => setInputs(e.target.value)} placeholder="accounts = 31, credit = 1290" />
        </>
      ) : (
        <>
          <label className="aug-fs-sm" htmlFor="sc-var">Assumption</label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Input id="sc-var" value={variable} onChange={e => setVariable(e.target.value)} placeholder="win-back rate" style={{ flex: "2 1 160px" }} />
            <Input aria-label="Value" value={value} onChange={e => setValue(e.target.value)} placeholder="value" inputMode="decimal" style={{ flex: "1 1 80px" }} />
            <Input aria-label="Low" value={low} onChange={e => setLow(e.target.value)} placeholder="low" inputMode="decimal" style={{ flex: "1 1 70px" }} />
            <Input aria-label="High" value={high} onChange={e => setHigh(e.target.value)} placeholder="high" inputMode="decimal" style={{ flex: "1 1 70px" }} />
          </div>
        </>
      )}
      <span />
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Button size="xs" disabled={busy || !metric.trim()} onClick={() => void submit()}>Book the projection</Button>
        <Button size="xs" variant="ghost" onClick={onCancel}>Cancel</Button>
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
          {method === "declared" ? "It is booked as your declared claim, under your name." : "It says which inputs it held fixed."}
        </span>
        {error && <span className="aug-fs-sm" role="alert" style={{ color: "var(--red4)" }}>{error}</span>}
      </div>
    </div>
  );
}

const VERDICTS: OutcomeVerdict[] = ["as_expected", "better", "worse", "cannot_tell"];

/** The review date has come: what was measured, against the expectation and the baseline. */
function OutcomeForm({ decisionId, onBooked }: { decisionId: string; onBooked: () => void }) {
  const [actual, setActual] = useState("");
  const [baseline, setBaseline] = useState("");
  const [verdict, setVerdict] = useState<OutcomeVerdict>("cannot_tell");
  const [why, setWhy] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await bookOutcome(decisionId, {
        measured_on: new Date().toISOString().slice(0, 10), actual: num(actual), baseline: num(baseline), verdict, why: why.trim(),
      });
      onBooked();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <Absent>Its review date has come and no outcome is booked. The platform books one itself when the metric is measurable on settled days; a person can book it here.</Absent>
      <div className="aug-form-grid" style={{ marginTop: 8 }}>
        <label className="aug-fs-sm" htmlFor="out-actual">Measured</label>
        <div style={{ display: "flex", gap: 8 }}>
          <Input id="out-actual" value={actual} onChange={e => setActual(e.target.value)} placeholder="actual" inputMode="decimal" style={{ width: 140 }} />
          <Input aria-label="Baseline" value={baseline} onChange={e => setBaseline(e.target.value)} placeholder="baseline" inputMode="decimal" style={{ width: 140 }} />
        </div>
        <label className="aug-fs-sm">Verdict</label>
        <div role="group" aria-label="Verdict" className="aug-segmented" style={{ justifySelf: "start" }}>
          {VERDICTS.map(v => (
            <Button key={v} variant="ghost" size="xs" aria-pressed={verdict === v}
              className={`aug-seg-item${verdict === v ? " active" : ""}`} onClick={() => setVerdict(v)}>{verdictWords(v)}</Button>
          ))}
        </div>
        <label className="aug-fs-sm" htmlFor="out-why">Why</label>
        <Input id="out-why" value={why} onChange={e => setWhy(e.target.value)} placeholder="What the measurement showed" />
        <span />
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Button size="xs" disabled={busy} onClick={() => void submit()}>Book the outcome</Button>
          {error && <span className="aug-fs-sm" role="alert" style={{ color: "var(--red4)" }}>{error}</span>}
        </div>
      </div>
    </div>
  );
}
