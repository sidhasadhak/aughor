"use client";

/**
 * Record — "what do we hold true, and what have we learned?" (the 2027 study §V, screen 9).
 *
 * One ledger behind every view, two clocks on every entry — so "as of" is a filter, not a
 * second store: set a date and the whole page re-reads as it was recorded then. A claim's own
 * page shows its warrant, what would change it, every version it has had and who relies on it.
 * Coverage says what the connected data cannot answer yet, and what would unlock each line.
 */
import { useMemo, useState } from "react";

import type { Connection } from "@/lib/api";
import { countNoun, formatTableNumber } from "@/lib/format";
import { connectionLabel, keyToWords } from "@/lib/names";
import {
  getClaim, getClaimVersions, getOnboarding, listClaims, whoLabel,
  type Claim, type Onboarding,
} from "@/lib/record";
import {
  Absent, BackHeader, Counted, Fact, Gate, Ledger, Page, Section, StatusMark, TierMark, day, useLoad,
  type LedgerColumn,
} from "@/components/record/kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const KINDS: { id: string; label: string }[] = [
  { id: "", label: "All" },
  { id: "finding", label: "Findings" },
  { id: "observation", label: "Observations" },
  { id: "reading", label: "Readings" },
  { id: "definition", label: "Definitions" },
  { id: "hypothesis", label: "Hypotheses" },
  { id: "prediction", label: "Predictions" },
  { id: "cause", label: "Causes" },
  { id: "said", label: "Said" },
];

const WARRANT_WORDS: Record<string, string> = {
  run: "a run measured it",
  document: "a document states it",
  attestation: "a person attested it",
  claim: "it rests on another claim",
};

export function RecordPanel({ connections, selectedConn, openId, onOpen, onOpenDecision, onOpenRun, onOpenReceipt, onOpenDefinitions, onOpenMap }: {
  connections: Connection[];
  selectedConn: string;
  openId: string | null;
  onOpen: (id: string | null) => void;
  onOpenDecision: (id: string) => void;
  onOpenRun: (runId: string) => void;
  onOpenReceipt: (ref: string) => void;
  onOpenDefinitions: () => void;
  onOpenMap: () => void;
}) {
  if (openId) {
    return <ClaimReader id={openId} connections={connections} onBack={() => onOpen(null)} onOpen={onOpen}
      onOpenDecision={onOpenDecision} onOpenRun={onOpenRun} onOpenReceipt={onOpenReceipt} />;
  }
  return <ClaimLedger connections={connections} selectedConn={selectedConn} onOpen={onOpen}
    onOpenDefinitions={onOpenDefinitions} onOpenMap={onOpenMap} />;
}

function ClaimLedger({ connections, selectedConn, onOpen, onOpenDefinitions, onOpenMap }: {
  connections: Connection[]; selectedConn: string; onOpen: (id: string) => void;
  onOpenDefinitions: () => void; onOpenMap: () => void;
}) {
  const [asOf, setAsOf] = useState("");
  const [kind, setKind] = useState("");
  const [query, setQuery] = useState("");
  const load = useLoad(() => listClaims({ as_of: asOf || undefined, kind: kind || undefined, limit: 500 }), [asOf, kind]);
  const coverage = useLoad(
    () => (selectedConn ? getOnboarding(selectedConn) : Promise.resolve(null)), [selectedConn]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (load.data ?? []).filter(c => !q
      || c.statement.text.toLowerCase().includes(q)
      || c.statement.metric.toLowerCase().includes(q)
      || c.about.key.toLowerCase().includes(q)
      || c.owner.toLowerCase().includes(q));
  }, [load.data, query]);

  const columns: LedgerColumn<Claim>[] = [
    { head: "Statement", cell: c => c.statement.text },
    { head: "Kind", cell: c => c.kind, width: 110 },
    { head: "Warranted", cell: c => <TierMark tier={c.tier} />, width: 170 },
    { head: "Status", cell: c => <StatusMark status={c.status} />, width: 110 },
    { head: "Held how often", cell: c => <Counted claim={c} brief />, width: 210 },
    { head: "Owner", cell: c => (c.owner ? whoLabel(c.owner) : "—"), width: 110 },
    { head: "As of", cell: c => day(c.as_of), width: 100 },
    { head: "Replaced", cell: c => (c.supersedes ? `version ${c.version}` : "—"), width: 90 },
  ];

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <div className="aug-toolbar" style={{ flexWrap: "wrap", height: "auto", minHeight: 36, rowGap: 6, paddingTop: 4, paddingBottom: 4 }}>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <span className="aug-label">As of</span>
          <Input type="date" value={asOf} max={new Date().toISOString().slice(0, 10)} aria-label="As of date"
            onChange={e => setAsOf(e.target.value)} style={{ width: 160 }} />
        </label>
        {asOf
          ? <Button size="xs" variant="ghost" onClick={() => setAsOf("")}>Back to today</Button>
          : <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>today — set a date to read the Record as it stood then</span>}
        <span style={{ flex: 1 }} />
        <Input value={query} onChange={e => setQuery(e.target.value)} placeholder="Find a claim, a metric, an owner"
          aria-label="Find a claim" style={{ width: 260 }} />
      </div>
      <div className="aug-toolbar" style={{ flexWrap: "wrap", height: "auto", minHeight: 36, rowGap: 6, paddingTop: 4, paddingBottom: 4 }}>
        <div role="group" aria-label="Kind of claim" className="aug-segmented">
          {KINDS.map(k => (
            <Button key={k.id || "all"} variant="ghost" size="xs" aria-pressed={kind === k.id}
              className={`aug-seg-item${kind === k.id ? " active" : ""}`} onClick={() => setKind(k.id)}>{k.label}</Button>
          ))}
        </div>
        {load.data && (
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
            {countNoun(rows.length, "claim")}{asOf ? ` as recorded on ${asOf}` : ""} · every connection
          </span>
        )}
        <span style={{ flex: 1 }} />
        <Button size="xs" variant="ghost" onClick={onOpenDefinitions}>Definitions</Button>
        <Button size="xs" variant="ghost" onClick={onOpenMap}>Map</Button>
      </div>
      <Page wide>
        <Gate load={load} what="the Record">
          {() => (
            <Ledger name={asOf ? `claims-as-of-${asOf}` : "claims"} columns={columns} rows={rows} rowKey={c => c.id}
              onOpen={c => onOpen(c.id)}
              empty={asOf
                ? `Nothing of this kind was on the record on ${asOf}.`
                : query ? "No claim matches that." : "Nothing of this kind is on the record yet. An answer, a finding, a hypothesis a run tested and a prediction booked with a decision each land here with their warrant."} />
          )}
        </Gate>
        <div style={{ height: 24 }} />
        <Section label="Coverage" meta={selectedConn ? connectionLabel(selectedConn, connections) : undefined}>
          {!selectedConn ? (
            <Absent>Coverage is measured per connection. Choose one and this says what its data cannot answer yet.</Absent>
          ) : (
            <Gate load={coverage} what="coverage">
              {c => (c ? <Coverage view={c} /> : null)}
            </Gate>
          )}
        </Section>
      </Page>
    </div>
  );
}

function Coverage({ view }: { view: Onboarding }) {
  const cov = view.coverage as { note?: string; mapped?: number; total?: number; share?: number; [k: string]: unknown };
  const list = view.shopping_list ?? [];
  return (
    <div>
      <p className="aug-fs-ui" style={{ color: "var(--t1)", margin: "0 0 6px" }}>
        {typeof cov.share === "number"
          ? `${Math.round(cov.share * 100)}% of this connection's tables are mapped to a declared type${typeof cov.mapped === "number" && typeof cov.total === "number" ? ` (${cov.mapped} of ${cov.total})` : ""}.`
          : cov.note || "Coverage is not measured for this connection yet."}
      </p>
      {list.length === 0 ? (
        <Absent>{view.shopping_note || "Nothing is listed as missing."}</Absent>
      ) : list.slice(0, 12).map((item, i) => (
        <div className="aug-item" key={String(item.what ?? i)}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{String(item.what ?? item.missing ?? "A gap")}</div>
          <div className="aug-item-foot aug-fs-sm">
            {Array.isArray(item.unlocks) && item.unlocks.length > 0 && <span>would unlock: {item.unlocks.join(", ")}</span>}
            {typeof item.why === "string" && <span>{item.why}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── a claim's own page ───────────────────────────────────────────────────────────────────

function ClaimReader({ id, connections, onBack, onOpen, onOpenDecision, onOpenRun, onOpenReceipt }: {
  id: string; connections: Connection[]; onBack: () => void; onOpen: (id: string) => void;
  onOpenDecision: (id: string) => void; onOpenRun: (runId: string) => void; onOpenReceipt: (ref: string) => void;
}) {
  const load = useLoad(() => getClaim(id), [id]);
  const versions = useLoad(() => getClaimVersions(id), [id]);
  const c = load.data;
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <BackHeader from="Claims" onBack={onBack} title={c?.statement.text ?? "Claim"}
        chips={c && <><StatusMark status={c.status} /><TierMark tier={c.tier} /></>} />
      <Gate load={load} what="the claim">
        {claim => (
          <Page rail={<ClaimRail c={claim} connections={connections} />}>
            {claim.superseded_by && (
              <div className="aug-callout aug-callout-amber" style={{ marginBottom: 16 }}>
                <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>This version was replaced. </span>
                <Button size="xs" variant="link" onClick={() => onOpen(claim.superseded_by)}>Open the current one</Button>
              </div>
            )}
            <Section label="What is held">
              <p className="aug-fs-h1 aug-lede">{claim.statement.text}</p>
              <div className="aug-item-foot aug-fs-sm" style={{ marginTop: 6 }}>
                {claim.statement.metric && <span>{keyToWords(claim.statement.metric)}{claim.statement.value != null ? `: ${formatTableNumber(claim.statement.value)} ${claim.statement.unit}` : ""}</span>}
                {(claim.statement.range_start || claim.statement.range_end) && <span>{claim.statement.range_start || "…"} to {claim.statement.range_end || "…"}</span>}
                <Counted claim={claim} />
              </div>
            </Section>

            <Section label="Why it is held" meta={countNoun(claim.warrants.length, "warrant")}>
              {claim.warrants.length === 0 ? (
                <Absent>{claim.tier === "said" ? "It was said, and nothing measured it: no run, document or attestation stands behind it." : "No warrant is recorded on this version."}</Absent>
              ) : claim.warrants.map(w => (
                <div className="aug-item" key={`${w.kind}:${w.ref}`}>
                  <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{w.detail || WARRANT_WORDS[w.kind] || w.kind}</div>
                  <div className="aug-item-foot aug-fs-sm">
                    <span>{WARRANT_WORDS[w.kind] ?? w.kind}</span>
                    {w.reproducible === false && <span>cannot be re-run: {w.why_not || "no reason recorded"}</span>}
                    <span style={{ flex: 1 }} />
                    {w.kind === "run" && <Button size="xs" variant="ghost" onClick={() => onOpenRun(w.ref)}>Open the run</Button>}
                    {w.kind === "run" && <Button size="xs" variant="ghost" onClick={() => onOpenReceipt(w.ref)}>Its receipt</Button>}
                    {w.kind === "claim" && <Button size="xs" variant="ghost" onClick={() => onOpen(w.ref)}>Open that claim</Button>}
                  </div>
                </div>
              ))}
            </Section>

            <Section label="What would change it">
              {claim.falsifier
                ? <p className="aug-fs-ui" style={{ color: "var(--t1)", margin: 0 }}>{claim.falsifier}{claim.next_check ? ` It is next checked on ${day(claim.next_check)}.` : ""}</p>
                : <Absent>Nothing is recorded that would change this claim{claim.next_check ? `; it is next checked on ${day(claim.next_check)}` : ", and no re-check is scheduled"}.</Absent>}
            </Section>

            <Section label="Who relies on it" meta={countNoun(claim.relied_on_by?.length ?? 0, "decision")}>
              {(claim.relied_on_by?.length ?? 0) === 0 ? <Absent>No decision cites this claim.</Absent> : (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {claim.relied_on_by!.map(d => <Button key={d} size="xs" variant="outline" onClick={() => onOpenDecision(d)}>Open the decision</Button>)}
                </div>
              )}
            </Section>

            <Section label="Every version" meta={versions.data ? countNoun(versions.data.length, "version") : undefined}>
              <Gate load={versions} what="the versions">
                {vs => (
                  <>
                    {vs.map(v => (
                      <div className="aug-item" key={v.id}>
                        <div className="aug-fs-ui" style={{ color: v.id === claim.id ? "var(--t1)" : "var(--t2)" }}>{v.statement.text}</div>
                        <div className="aug-item-foot aug-fs-sm">
                          <span>version {v.version}{v.id === claim.id ? " — this one" : ""}</span>
                          <span>as of {day(v.as_of)}</span>
                          <span>recorded {day(v.recorded_at)}</span>
                          <StatusMark status={v.status} />
                          {v.state && <span>{v.state}</span>}
                          <span style={{ flex: 1 }} />
                          {v.id !== claim.id && <Button size="xs" variant="ghost" onClick={() => onOpen(v.id)}>Open</Button>}
                        </div>
                      </div>
                    ))}
                  </>
                )}
              </Gate>
            </Section>
          </Page>
        )}
      </Gate>
    </div>
  );
}

function ClaimRail({ c, connections }: { c: Claim; connections: Connection[] }) {
  return (
    <>
      <div className="aug-rail-head"><span className="aug-label">This claim</span></div>
      <Fact label="Kind">{c.kind}{c.state ? ` · ${c.state}` : ""}</Fact>
      <Fact label="About">{c.about.kind === "connection" ? connectionLabel(c.about.key, connections) : `${c.about.kind} ${c.about.key}`}</Fact>
      <Fact label="Owner">{c.owner ? whoLabel(c.owner) : "nobody named"}</Fact>
      <Fact label="Author">{whoLabel(c.author_kind === "agent" ? `agent:${c.author}` : c.author)}</Fact>
      <Fact label="As of">{day(c.as_of) || "not dated"}</Fact>
      <Fact label="Recorded">{day(c.recorded_at)}</Fact>
      {c.definition_version && <Fact label="Definition">version {c.definition_version}</Fact>}
      {c.valid_until && <Fact label="Valid until">{day(c.valid_until)}</Fact>}
      <Fact label="Version">{c.version}{c.supersedes ? " — it replaced an earlier one" : ""}</Fact>
    </>
  );
}
