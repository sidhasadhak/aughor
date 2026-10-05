"use client";

/**
 * Agent Ops ▸ By duty — "what is the system doing?" (the 2027 study §V, screen 8).
 *
 * The row is a duty, not an agent's name: what each of the seven duties booked this week, how
 * much of it stands on something, how its runs ended by type, and what a warranted entry cost.
 * Then the failures by type, what left and what was held, and every principal — a person, a
 * built-in agent, an outside vendor's — with what became of its entries. The score is a count,
 * never a model's opinion. The live tail and the traces are one door away, folded. Between the
 * departures and the principals: what is filed and still open, and what is on probation.
 */
import { useMemo } from "react";

import { getDepartureSummary } from "@/lib/api";
import { getApiBase } from "@/lib/config";
import { compactNumber, countNoun } from "@/lib/format";
import { keyToWords } from "@/lib/names";
import {
  getPrincipalRecord, getServicePrincipals, listClaims, verdictWords, whoLabel,
} from "@/lib/record";
import { Absent, Gate, Ledger, Page, Section, day, useLoad, type LedgerColumn } from "@/components/record/kit";
import { FilingsSection, ProbationSection } from "@/components/operations/FilingsSection";
import { Button } from "@/components/ui/button";

interface DutyRow {
  duty: string;
  today: string;
  books: string[];
  runs: number | null;
  entries: number;
  warranted: number;
  failures: Record<string, number>;
  failed: number;
  cost: { tokens: number | null; llm_calls: number | null; per_warranted: number | null; note: string };
  scope_note?: string;
}

interface DutyWeek {
  since: string;
  duties: DutyRow[];
  failures_by_type: Record<string, number>;
  note: string;
}

async function readDuties(): Promise<DutyWeek> {
  const res = await fetch(`${getApiBase()}/record/duties`);
  if (!res.ok) throw new Error(`The week by duty could not be read (${res.status})`);
  return res.json();
}

const FAILURE_WORDS: Record<string, string> = {
  verification_failed: "the change was not visible afterwards",
  verification_unavailable: "the verification read could not run",
  held: "held by a law of the gate",
  held_budget: "held: its place's slots were used",
  held_probation: "held: its automation is on probation",
  held_owner: "held: an owner's answer is needed",
  contradicted: "a challenge contradicted its cause",
  no_data: "the data was not there",
  no_definition: "no approved definition",
  withheld: "withheld from the asker",
  out_of_budget: "ran out of its budget",
  tool_failed: "a tool failed",
};

const failureWords = (kind: string) => FAILURE_WORDS[kind] ?? verdictWords(kind);

interface PrincipalRow {
  principal: string;
  kind: string;
  n: number;
  by_kind: Record<string, number>;
  restated: number;
  hypotheses: Record<string, number>;
  predictions: { scored: number; inside: number };
}

/** Every author on the Record and every service principal, each with what became of its entries. */
async function readPrincipals(): Promise<PrincipalRow[]> {
  const [claims, services] = await Promise.all([listClaims({ limit: 1000 }), getServicePrincipals()]);
  const kinds = new Map<string, string>();
  for (const c of claims) {
    if (c.author) kinds.set(c.author, c.author_kind === "person" ? "a person" : c.author_kind === "agent" ? "a built-in agent" : "the platform's code");
  }
  for (const s of services.principals) kinds.set(`service:${s.name}`, "an outside agent");
  const names = [...kinds.keys()].slice(0, 40);
  const records = await Promise.all(names.map(n => getPrincipalRecord(n).catch(() => null)));
  return names.map((principal, i) => {
    const r = (records[i] ?? {}) as Partial<PrincipalRow>;
    return {
      principal, kind: kinds.get(principal)!, n: r.n ?? 0, by_kind: r.by_kind ?? {}, restated: r.restated ?? 0,
      hypotheses: r.hypotheses ?? {}, predictions: { scored: r.predictions?.scored ?? 0, inside: r.predictions?.inside ?? 0 },
    };
  }).sort((a, b) => b.n - a.n);
}

export function WorkPanel({ onOpenRuns, onOpenDepartures, onOpenActivity, onOpenAgents, onOpenActionCentre, onOpenDeveloper, onOpenHub }: {
  onOpenRuns: () => void;
  onOpenDepartures: () => void;
  onOpenActivity: () => void;
  onOpenAgents: () => void;
  onOpenActionCentre: () => void;
  onOpenDeveloper: () => void;
  onOpenHub: () => void;
}) {
  const week = useLoad(() => readDuties(), []);
  const departures = useLoad(() => getDepartureSummary(), []);
  const principals = useLoad(readPrincipals, []);

  const dutyColumns: LedgerColumn<DutyRow>[] = [
    { head: "Duty", cell: d => d.duty, width: 110 },
    { head: "Carried today by", cell: d => d.today },
    { head: "Runs", cell: d => (d.runs === null ? "—" : d.runs), num: true, width: 70 },
    { head: "Booked", cell: d => d.entries, num: true, width: 80 },
    { head: "Warranted", cell: d => d.warranted, num: true, width: 100 },
    { head: "Failed", cell: d => d.failed, num: true, width: 70 },
    {
      head: "Tokens per warranted entry", width: 260,
      cell: d => (
        <span title={d.cost.note}>
          {d.cost.per_warranted != null ? compactNumber(d.cost.per_warranted) : d.runs === null ? "not metered for this duty" : d.cost.note}
        </span>
      ),
    },
  ];

  const principalColumns: LedgerColumn<PrincipalRow>[] = [
    { head: "Principal", cell: p => whoLabel(p.principal) },
    { head: "Is", cell: p => p.kind, width: 160 },
    { head: "Entries", cell: p => p.n, num: true, width: 80 },
    { head: "By kind", cell: p => Object.entries(p.by_kind).map(([k, n]) => `${n} ${k}`).join(" · ") || "—" },
    { head: "Restated", cell: p => p.restated, num: true, width: 90 },
    { head: "Hypotheses", cell: p => Object.entries(p.hypotheses).map(([k, n]) => `${n} ${k}`).join(" · ") || "—", width: 260 },
    { head: "Predictions inside their band", cell: p => (p.predictions.scored ? `${p.predictions.inside} of ${p.predictions.scored}` : "none scored"), num: true, width: 220 },
  ];

  const failures = useMemo(
    () => Object.entries(week.data?.failures_by_type ?? {}).sort((a, b) => b[1] - a[1]),
    [week.data]);

  return (
    <Page wide>
      <Section label="The week by duty" meta={week.data ? `since ${day(week.data.since)} · every connection` : undefined}>
        <Gate load={week} what="the week by duty">
          {w => (
            <>
              <Ledger name="week-by-duty" columns={dutyColumns} rows={w.duties} rowKey={d => d.duty}
                empty="No duty is declared in the agent contract." />
              <Absent>{w.note}</Absent>
            </>
          )}
        </Gate>
      </Section>

      <Section label="Failures by type" meta={week.data ? countNoun(failures.reduce((n, [, c]) => n + c, 0), "failure") : undefined}
        action={<Button size="xs" variant="ghost" onClick={onOpenRuns}>Every run</Button>}>
        <Gate load={week} what="the failures">
          {() => failures.length === 0 ? (
            <Absent>Nothing failed this week: every run answered, every verification that ran passed, and nothing was held.</Absent>
          ) : (
            <>
              {failures.map(([kind, n]) => (
                <div className="aug-item" key={kind}>
                  <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
                    <span className="aug-num" style={{ marginRight: 10 }}>{n}</span>{failureWords(kind)}
                  </div>
                  <div className="aug-item-foot aug-fs-sm">
                    <span>{week.data!.duties.filter(d => d.failures[kind]).map(d => d.duty).join(", ")}</span>
                  </div>
                </div>
              ))}
            </>
          )}
        </Gate>
      </Section>

      <Section label="Departures" action={<Button size="xs" variant="ghost" onClick={onOpenDepartures}>Every departure</Button>}>
        <Gate load={departures} what="departures">
          {d => {
            const by = d?.by_state ?? {};
            const states = Object.entries(by);
            if (states.length === 0) return <Absent>Nothing has reached the departure gate yet.</Absent>;
            return (
              <div className="aug-item">
                <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
                  {states.map(([s, n]) => `${n} ${keyToWords(s)}`).join(" · ")}
                </div>
                <div className="aug-item-foot aug-fs-sm">
                  <span>{d?.awaiting ? `${countNoun(d.awaiting, "send")} waiting on a person` : "none waits on a person"}</span>
                  <span>all time, every connection</span>
                </div>
              </div>
            );
          }}
        </Gate>
      </Section>

      <FilingsSection />

      <ProbationSection onOpenHub={onOpenHub} />

      <Section label="Principals" meta={principals.data ? countNoun(principals.data.length, "principal") : undefined}
        action={
          <span style={{ display: "inline-flex", gap: 4 }}>
            <Button size="xs" variant="ghost" onClick={onOpenAgents} title="Each built-in and custom agent's runs, quality and setup">Roster</Button>
            <Button size="xs" variant="ghost" onClick={onOpenActionCentre} title="What each action may do, and its grants">Authority</Button>
            <Button size="xs" variant="ghost" onClick={onOpenDeveloper} title="Service principals and their keys">Keys</Button>
          </span>
        }>
        <Gate load={principals} what="principals">
          {rows => (
            <Ledger name="principals" columns={principalColumns} rows={rows} rowKey={p => p.principal}
              empty="Nobody has booked an entry yet. A person, a built-in agent and an outside vendor's agent appear here in the same rows, each with what became of what it booked." />
          )}
        </Gate>
      </Section>

      <Section label="The live tail and traces" action={<Button size="xs" variant="outline" onClick={onOpenActivity}>Open activity</Button>}>
        <Absent>What is running now, each run&apos;s trace and a deep run&apos;s phases are on the Activity tab.</Absent>
      </Section>
    </Page>
  );
}
