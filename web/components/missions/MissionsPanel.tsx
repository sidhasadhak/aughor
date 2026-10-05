"use client";

/**
 * Missions — "what are we continuously trying to achieve?" (the 2027 study §V, screen 7).
 *
 * A mission is written by a person: what to achieve, what not to damage, who owns it, what it
 * may interrupt and spend. It is judged by its objective against the baseline the metric's own
 * history predicts — read first, before anything else — and never by activity: "nine findings,
 * one decision, no measurable effect yet" is a valid report. A mission without an owner does
 * not run, and the page says so.
 */
import { useMemo, useState } from "react";

import type { Connection } from "@/lib/api";
import { countNoun, formatTableNumber } from "@/lib/format";
import { connectionLabel, keyToWords } from "@/lib/names";
import {
  getMission, getMissionReport, getMissionTemplates, listMissions, setMissionState, verdictWords, whoLabel,
  writeMission,
  type Mission, type MissionBody, type MissionDetail, type MissionReport, type MissionTemplate,
} from "@/lib/record";
import {
  Absent, BackHeader, Fact, Gate, Ledger, Page, Section, day, dayDistance, useLoad, type LedgerColumn,
} from "@/components/record/kit";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const STATE_HUE: Record<string, ChipHue> = {
  active: "positive", proposed: "info", paused: "caution", met: "accent", retired: "muted",
};

const DIRECTION_WORDS: Record<string, string> = { up: "up", down: "down", hold: "held" };

/** "revenue up to 450,000 USD by 2026-12-24" — the objective as one line. */
export function objectiveLine(o: Mission["objective"]): string {
  if (o.text) return o.text;
  const target = o.target != null ? ` to ${formatTableNumber(o.target)}${o.unit ? ` ${o.unit}` : ""}` : "";
  const when = o.by_when ? ` by ${day(o.by_when)}` : "";
  return `${keyToWords(o.metric)} ${DIRECTION_WORDS[o.direction] ?? o.direction}${target}${when}`.trim();
}

export function MissionsPanel({ connections, selectedConn, openId, onOpen, onOpenInquiry, onOpenDecision, onOpenClaim, onOpenMonitors }: {
  connections: Connection[];
  selectedConn: string;
  openId: string | null;
  onOpen: (id: string | null) => void;
  onOpenInquiry: (id: string) => void;
  onOpenDecision: (id: string) => void;
  onOpenClaim: (id: string) => void;
  onOpenMonitors: () => void;
}) {
  if (openId) {
    return <MissionReader id={openId} connections={connections} onBack={() => onOpen(null)}
      onOpenInquiry={onOpenInquiry} onOpenDecision={onOpenDecision} onOpenClaim={onOpenClaim} onOpenMonitors={onOpenMonitors} />;
  }
  return <MissionLedger connections={connections} selectedConn={selectedConn} onOpen={onOpen} />;
}

function MissionLedger({ connections, selectedConn, onOpen }: {
  connections: Connection[]; selectedConn: string; onOpen: (id: string) => void;
}) {
  const [writing, setWriting] = useState(false);
  const load = useLoad(() => listMissions(), []);
  const rows = load.data ?? [];
  const columns: LedgerColumn<Mission>[] = [
    { head: "Mission", cell: m => m.name },
    { head: "Objective", cell: m => objectiveLine(m.objective) },
    { head: "Owner", cell: m => (m.owner ? whoLabel(m.owner) : "no owner — it does not run"), width: 190 },
    { head: "State", cell: m => <StatusChip hue={STATE_HUE[m.state] ?? "muted"}>{m.state}</StatusChip>, width: 110 },
    { head: "Interruptions this week", cell: m => (m.runs ? `${m.interruptions_this_week} of ${m.budget.interruptions_per_week}` : "—"), num: true, width: 180 },
    { head: "Next report", cell: m => (m.review.next_report_on ? `${day(m.review.next_report_on)} · ${dayDistance(m.review.next_report_on)}` : "—"), width: 180 },
  ];
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <div className="aug-toolbar">
        {load.data && (
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
            {countNoun(rows.length, "mission")} · {countNoun(rows.filter(m => m.runs).length, "runs", "run")} · every connection
          </span>
        )}
        <span style={{ flex: 1 }} />
        <Button size="xs" onClick={() => setWriting(v => !v)} aria-expanded={writing}>Write a mission</Button>
      </div>
      <Page wide>
        {writing && (
          <MissionForm connectionId={selectedConn} connections={connections} onCancel={() => setWriting(false)}
            onWritten={m => { setWriting(false); load.reload(); onOpen(m.id); }} />
        )}
        <Gate load={load} what="missions">
          {() => (
            <Ledger name="missions" columns={columns} rows={rows} rowKey={m => m.id} onOpen={m => onOpen(m.id)}
              empty="No mission has been written. A mission says what to achieve and what not to damage; once one is active and owned, the week's sends are ranked by what bears on it and it reports against its baseline on its cadence." />
          )}
        </Gate>
      </Page>
    </div>
  );
}

const num = (v: string): number | null => (v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v));

/** Five lines: the objective, what not to damage, the owner, what it may interrupt, how often it reports. */
function MissionForm({ connectionId, connections, onWritten, onCancel }: {
  connectionId: string; connections: Connection[]; onWritten: (m: Mission) => void; onCancel: () => void;
}) {
  const templates = useLoad(() => getMissionTemplates(connectionId || undefined), [connectionId]);
  const [name, setName] = useState("");
  const [metric, setMetric] = useState("");
  const [direction, setDirection] = useState("up");
  const [target, setTarget] = useState("");
  const [unit, setUnit] = useState("");
  const [byWhen, setByWhen] = useState("");
  const [guardMetric, setGuardMetric] = useState("");
  const [guardBound, setGuardBound] = useState("at_least");
  const [guardLimit, setGuardLimit] = useState("");
  const [owner, setOwner] = useState("");
  const [interruptions, setInterruptions] = useState("3");
  const [cadence, setCadence] = useState("monthly");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const fill = (t: MissionTemplate) => {
    const body = (t.body ?? {}) as Partial<MissionBody>;
    setName(body.name ?? t.name ?? "");
    setMetric(body.objective?.metric ?? "");
    setDirection(body.objective?.direction || "up");
    setUnit(body.objective?.unit ?? "");
    const c = body.constraints?.[0];
    setGuardMetric(c?.metric ?? "");
    setGuardBound(c?.bound || "at_least");
    setCadence(body.cadence || "monthly");
  };

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const body: MissionBody = {
        name: name.trim(),
        objective: { metric: metric.trim(), direction, target: num(target), unit: unit.trim(), by_when: byWhen },
        constraints: guardMetric.trim()
          ? [{ metric: guardMetric.trim(), bound: guardBound, limit: num(guardLimit) }] : [],
        connections: connectionId ? [connectionId] : [],
        owner: owner.trim(),
        budget: { interruptions_per_week: num(interruptions) ?? 3 },
        cadence,
        state: "proposed",
      };
      onWritten(await writeMission(body));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const seg = (value: string, set: (v: string) => void, options: [string, string][], label: string) => (
    <div role="group" aria-label={label} className="aug-segmented" style={{ justifySelf: "start" }}>
      {options.map(([id, text]) => (
        <Button key={id} variant="ghost" size="xs" aria-pressed={value === id}
          className={`aug-seg-item${value === id ? " active" : ""}`} onClick={() => set(id)}>{text}</Button>
      ))}
    </div>
  );

  return (
    <Section label="Write a mission"
      meta={connectionId ? `on ${connectionLabel(connectionId, connections)}` : "no connection selected — it will span every connection"}>
      {(templates.data?.templates.length ?? 0) > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Start from a template the installed packs ship:</span>
          {templates.data!.templates.map(t => (
            <Button key={`${t.pack}:${String(t.id ?? t.name)}`} size="xs" variant="outline" onClick={() => fill(t)}
              title={String(t.description ?? "")}>{t.name}</Button>
          ))}
        </div>
      )}
      <div className="aug-form-grid">
        <label className="aug-fs-sm" htmlFor="mi-name">Name</label>
        <Input id="mi-name" value={name} onChange={e => setName(e.target.value)} placeholder="Keep APAC renewals whole" />
        <label className="aug-fs-sm" htmlFor="mi-metric">Achieve</label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <Input id="mi-metric" value={metric} onChange={e => setMetric(e.target.value)} placeholder="a metric: revenue" style={{ flex: "2 1 150px" }} />
          {seg(direction, setDirection, [["up", "up"], ["down", "down"], ["hold", "hold"]], "Direction")}
          <Input aria-label="Target" value={target} onChange={e => setTarget(e.target.value)} placeholder="target" inputMode="decimal" style={{ flex: "1 1 90px" }} />
          <Input aria-label="Unit" value={unit} onChange={e => setUnit(e.target.value)} placeholder="unit" style={{ flex: "1 1 70px" }} />
          <Input aria-label="By when" type="date" value={byWhen} onChange={e => setByWhen(e.target.value)} style={{ flex: "1 1 150px" }} />
        </div>
        <label className="aug-fs-sm" htmlFor="mi-guard">Without damaging</label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <Input id="mi-guard" value={guardMetric} onChange={e => setGuardMetric(e.target.value)} placeholder="a metric: refund rate" style={{ flex: "2 1 150px" }} />
          {seg(guardBound, setGuardBound, [["at_least", "at least"], ["at_most", "at most"]], "Bound")}
          <Input aria-label="Limit" value={guardLimit} onChange={e => setGuardLimit(e.target.value)} placeholder="limit" inputMode="decimal" style={{ flex: "1 1 90px" }} />
        </div>
        <label className="aug-fs-sm" htmlFor="mi-owner">Owner</label>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Input id="mi-owner" value={owner} onChange={e => setOwner(e.target.value)} placeholder="user:ana" style={{ width: 220 }} />
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>a person; without one the mission is kept and does not run</span>
        </div>
        <label className="aug-fs-sm" htmlFor="mi-int">May interrupt</label>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Input id="mi-int" value={interruptions} onChange={e => setInterruptions(e.target.value)} inputMode="numeric" style={{ width: 70 }} />
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>times a week, and reports</span>
          {seg(cadence, setCadence, [["weekly", "weekly"], ["monthly", "monthly"], ["quarterly", "quarterly"]], "Report cadence")}
        </div>
        <span />
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Button size="xs" disabled={busy || !name.trim() || !metric.trim()} onClick={() => void submit()}>Write it</Button>
          <Button size="xs" variant="ghost" onClick={onCancel}>Cancel</Button>
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>It is written as proposed; activating it is a separate step.</span>
          {error && <span className="aug-fs-sm" role="alert" style={{ color: "var(--red4)" }}>{error}</span>}
        </div>
      </div>
    </Section>
  );
}

// ── the Reader ───────────────────────────────────────────────────────────────────────────

const NEXT_STATES: Record<string, { to: string; label: string }[]> = {
  proposed: [{ to: "active", label: "Activate" }, { to: "retired", label: "Retire" }],
  active: [{ to: "paused", label: "Pause" }, { to: "met", label: "Mark met" }, { to: "retired", label: "Retire" }],
  paused: [{ to: "active", label: "Resume" }, { to: "retired", label: "Retire" }],
  met: [{ to: "retired", label: "Retire" }],
  retired: [],
};

function MissionReader({ id, connections, onBack, onOpenInquiry, onOpenDecision, onOpenClaim, onOpenMonitors }: {
  id: string; connections: Connection[]; onBack: () => void;
  onOpenInquiry: (id: string) => void; onOpenDecision: (id: string) => void; onOpenClaim: (id: string) => void;
  onOpenMonitors: () => void;
}) {
  const load = useLoad(() => getMission(id), [id]);
  const [error, setError] = useState("");
  const m = load.data;
  const move = async (to: string) => {
    setError("");
    try { await setMissionState(id, to); load.reload(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <BackHeader from="Missions" onBack={onBack} title={m?.name ?? "Mission"}
        chips={m && <StatusChip hue={STATE_HUE[m.state] ?? "muted"}>{m.state}</StatusChip>}
        actions={m && (
          <span style={{ display: "inline-flex", gap: 6 }}>
            {(NEXT_STATES[m.state] ?? []).map(s => (
              <Button key={s.to} size="xs" variant={s.to === "active" ? "default" : "outline"} onClick={() => void move(s.to)}>{s.label}</Button>
            ))}
          </span>
        )} />
      {error && <p className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", margin: 0, padding: "8px 20px" }}>{error}</p>}
      <Gate load={load} what="the mission">
        {detail => <MissionBodyView m={detail} connections={connections}
          onOpenInquiry={onOpenInquiry} onOpenDecision={onOpenDecision} onOpenClaim={onOpenClaim} onOpenMonitors={onOpenMonitors} />}
      </Gate>
    </div>
  );
}

const OBJECTIVE_HUE: Record<string, ChipHue> = {
  ahead: "positive", on_track: "positive", met: "positive", moved: "positive",
  behind: "negative", worse: "negative", no_effect: "caution", cannot_tell: "muted",
};

function MissionBodyView({ m, connections, onOpenInquiry, onOpenDecision, onOpenClaim, onOpenMonitors }: {
  m: MissionDetail; connections: Connection[];
  onOpenInquiry: (id: string) => void; onOpenDecision: (id: string) => void; onOpenClaim: (id: string) => void;
  onOpenMonitors: () => void;
}) {
  // The report as it would read now, composed from fields and not booked; the booked ones are
  // the cadence's, listed beneath with the day each was written.
  const report = useLoad(() => getMissionReport(m.id, true), [m.id, m.version]);
  const ceiling = Object.entries(m.budget.authority_ceiling);
  const rail = (
    <>
      <div className="aug-rail-head"><span className="aug-label">This mission</span></div>
      <Fact label="Owner">{m.owner ? whoLabel(m.owner) : "none — it does not run"}</Fact>
      <Fact label="Runs">{m.runs ? "yes: active and owned" : (m.runs_note ?? "no")}</Fact>
      <Fact label="Scope">
        {[m.scope.domain, m.scope.segment].filter(Boolean).join(" · ") || "no domain or segment stated"}
        {m.scope.connections.length > 0 && <> · {m.scope.connections.map(c => connectionLabel(c, connections)).join(", ")}</>}
      </Fact>
      <Fact label="May interrupt">{m.budget.interruptions_per_week} times a week</Fact>
      <Fact label="May spend">
        {m.budget.spend_per_month != null ? `${formatTableNumber(m.budget.spend_per_month)} ${m.budget.spend_unit} a month` : "no spend budget set"}
      </Fact>
      <Fact label="Ceiling">
        {ceiling.length ? ceiling.map(([a, l]) => `${a === "*" ? "any other action" : keyToWords(a)} up to L${l}`).join(" · ") : "no ceiling set — actions stay at the level their record earned"}
      </Fact>
      <Fact label="Reports">{m.review.cadence}{m.review.next_report_on ? ` · next ${day(m.review.next_report_on)}` : ""}</Fact>
      <Fact label="Written by">{whoLabel(m.written_by)} · version {m.version}</Fact>
    </>
  );
  return (
    <Page rail={rail}>
      <Gate load={report} what="the mission's report">
        {r => r.report
          ? <ReportView report={r.report} m={m} onOpenInquiry={onOpenInquiry} onOpenDecision={onOpenDecision}
              onOpenClaim={onOpenClaim} onOpenMonitors={onOpenMonitors} />
          : <Absent>{r.note || "No report can be composed for this mission yet."}</Absent>}
      </Gate>
      <Section label="Past reports" meta={countNoun(m.reports.length, "report")}>
        {m.reports.length === 0 ? (
          <Absent>None booked yet. The first is written on {m.review.next_report_on ? day(m.review.next_report_on) : "its cadence once the mission is active"} and each is kept as of its date.</Absent>
        ) : m.reports.map(r => (
          <div className="aug-item" key={r.id}>
            <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{r.headline}</div>
            <div className="aug-item-foot aug-fs-sm">
              {r.period && <span>{day(r.period.from)} to {day(r.period.to)}</span>}
              {r.verdict && <span>{verdictWords(r.verdict)}</span>}
            </div>
          </div>
        ))}
      </Section>
    </Page>
  );
}

function ReportView({ report, m, onOpenInquiry, onOpenDecision, onOpenClaim, onOpenMonitors }: {
  report: MissionReport; m: MissionDetail;
  onOpenInquiry: (id: string) => void; onOpenDecision: (id: string) => void; onOpenClaim: (id: string) => void;
  onOpenMonitors: () => void;
}) {
  const o = report.objective;
  const lessons = useMemo(() => report.lessons.map(l => (typeof l === "string" ? l : `${l.turned_out ?? ""}${l.believed ? ` (believed: ${l.believed})` : ""}`)), [report.lessons]);
  const spend = report.cost.spend;
  const levels = Object.entries(report.cost.actions_by_level);
  return (
    <>
      <Section label="The objective against its baseline" meta={`${day(report.period.from)} to ${day(report.period.to)}`}>
        <p className="aug-fs-h1 aug-lede">{objectiveLine(m.objective)}</p>
        <div className="aug-item">
          <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
            <StatusChip hue={OBJECTIVE_HUE[o.verdict] ?? "muted"}>{verdictWords(o.verdict)}</StatusChip>
            <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>{o.why || report.headline}</span>
          </div>
          <div className="aug-item-foot aug-fs-sm">
            {o.actual != null && <span>actual {formatTableNumber(o.actual)}</span>}
            {o.baseline != null && <span>baseline {formatTableNumber(o.baseline)}</span>}
            {o.low != null && o.high != null && <span>the baseline&apos;s range {formatTableNumber(o.low)} to {formatTableNumber(o.high)}</span>}
            {!o.measurable && <span>not measurable yet — the objective&apos;s metric needs an approved definition</span>}
          </div>
        </div>
      </Section>

      <Section label="Constraints" meta={countNoun(report.constraints.length, "constraint")}>
        {report.constraints.length === 0 ? <Absent>No constraint was written: nothing says what this mission must not damage.</Absent>
          : report.constraints.map(c => (
            <div className="aug-item" key={c.metric}>
              <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
                <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>
                  {keyToWords(c.metric)} {c.bound === "at_most" ? "at most" : "at least"} {c.limit != null ? formatTableNumber(c.limit) : "its limit"}
                </span>
                <StatusChip hue={c.held === true ? "positive" : c.held === false ? "negative" : "muted"}>
                  {c.held === true ? "held" : c.held === false ? "broken" : "cannot tell"}
                </StatusChip>
              </div>
              <div className="aug-item-foot aug-fs-sm">
                {c.actual != null && <span>actual {formatTableNumber(c.actual)}</span>}
                {c.held === null && <span>{c.note.replace(/^cannot tell:\s*/, "") || "its metric has no approved definition to measure"}</span>}
              </div>
            </div>
          ))}
      </Section>

      <Section label="What it watched" meta={countNoun(report.watches.length, "watch", "watches")}
        action={<Button size="xs" variant="ghost" onClick={onOpenMonitors}>Monitors</Button>}>
        {report.watches.length === 0 ? <Absent>It watches nothing: no monitor, promise or claim is attached.</Absent>
          : report.watches.map(w => (
            <div className="aug-item" key={`${w.kind}:${w.ref}`}>
              <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{w.label || w.ref}</div>
              <div className="aug-item-foot aug-fs-sm">
                <span>{w.kind}</span><span>{w.state}</span>
                <span style={{ flex: 1 }} />
                {w.kind === "claim" && w.ref && <Button size="xs" variant="ghost" onClick={() => onOpenClaim(w.ref)}>Open the claim</Button>}
              </div>
            </div>
          ))}
      </Section>

      <Section label="What it opened" meta={countNoun(report.opened.inquiries, "inquiry", "inquiries")}>
        {report.opened.inquiries === 0 ? <Absent>No inquiry was opened under this mission in the period.</Absent> : (
          <div className="aug-item">
            <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
              {Object.entries(report.opened.by_state).map(([s, n]) => `${n} ${s}`).join(" · ")}
            </div>
            <div className="aug-item-foot">
              {report.opened.ids.map(i => <Button key={i} size="xs" variant="outline" onClick={() => onOpenInquiry(i)}>Open the inquiry</Button>)}
            </div>
          </div>
        )}
      </Section>

      <Section label="What it decided" meta={countNoun(report.decided.length, "decision")}>
        {report.decided.length === 0 ? <Absent>No decision was booked toward this mission in the period.</Absent>
          : report.decided.map((d, i) => (
            <div className="aug-item" key={d.id ?? i}>
              <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{d.chosen || d.question}</div>
              <div className="aug-item-foot aug-fs-sm">
                <span>{d.verdict ? verdictWords(d.verdict) : d.outcome || (d.review_on ? `reviewed on ${day(d.review_on)}` : "no outcome yet")}</span>
                <span style={{ flex: 1 }} />
                {d.id && <Button size="xs" variant="ghost" onClick={() => onOpenDecision(d.id!)}>Open the decision</Button>}
              </div>
            </div>
          ))}
      </Section>

      <Section label="What it cost">
        <div className="aug-item">
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
            {report.cost.interruptions} of {report.cost.interruptions_budgeted} interruptions used this period
            {report.cost.held > 0 && <> · {countNoun(report.cost.held, "send")} held</>}
          </div>
          <div className="aug-item-foot aug-fs-sm">
            <span>{spend.amount != null ? `spent ${formatTableNumber(spend.amount)} ${spend.unit}` : spend.note}</span>
            {spend.runs > 0 && <span>{countNoun(spend.runs, "run")}</span>}
            {spend.unpriced_calls > 0 && <span>{countNoun(spend.unpriced_calls, "model call")} not priced</span>}
            <span>{levels.length ? `actions: ${levels.map(([l, n]) => `${n} at ${l}`).join(", ")}` : "no action ran"}</span>
          </div>
        </div>
      </Section>

      <Section label="Lessons">
        {lessons.length === 0 ? <Absent>No lesson was written in the period — none of its inquiries closed with one.</Absent>
          : lessons.map(l => <div className="aug-item aug-fs-ui" key={l} style={{ color: "var(--t1)" }}>{l}</div>)}
      </Section>
    </>
  );
}
