"use client";

/**
 * Record — "what do we hold true, and what have we learned?" (the 2027 study §V, screen 9).
 *
 * One ledger behind every view, two clocks on every entry — so "as of" is a filter, not a
 * second store: set a date and the whole page re-reads as it was recorded then. A claim's own
 * page shows its warrant, what would change it, every version it has had and who relies on it.
 * Coverage says what the connected data cannot answer yet, and what would unlock each line.
 */
import { DropdownMenu } from "@radix-ui/themes";
import { useMemo, useState } from "react";

import type { Connection } from "@/lib/api";
import { countNoun, formatCount, formatTableNumber, pct } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { connectionLabel, keyToWords } from "@/lib/names";
import {
  getClaim, getClaimCrossLinks, getClaimVersions, getOnboarding, listClaims, whoLabel,
  type Claim, type ClaimCrossLink, type Onboarding,
} from "@/lib/record";
import {
  Absent, BackHeader, Counted, Facet, Fact, Gate, ListCard, ListRow, MarkWrong, Page, Section, StatusMark, TierMark,
  countedWords, day, markedWords, tierWords, useActor, useChosen, useLoad,
  type ListColumn, type Load,
} from "@/components/record/kit";
import {
  CARD, Card, Chip, Dot, Empty, Figure, Figures, Label, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, Page as ClarityPage,
  RULE, type Tone,
} from "@/components/clarity/kit";
import {
  VERDICT_SHORT, breakdown, countBy, dateWords, figure, firstSentence, modeOf, predictionView, type PredictionVerdict,
} from "@/components/record/words";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Callout } from "@/components/ui/callout";

const WARRANT_WORDS: Record<string, string> = {
  run: "a run measured it",
  document: "a document states it",
  attestation: "a person attested it",
  claim: "it rests on another claim",
};

export function RecordPanel({ connections, selectedConn, openId, onOpen, onOpenDecision, onInspectClaim, onOpenRun, onOpenReceipt, onOpenDefinitions, onOpenMap }: {
  connections: Connection[];
  selectedConn: string;
  openId: string | null;
  onOpen: (id: string | null) => void;
  onOpenDecision: (id: string) => void;
  /** Read another claim beside this page. Absent, a cited claim opens as its own page. */
  onInspectClaim?: (id: string) => void;
  onOpenRun: (runId: string) => void;
  onOpenReceipt: (ref: string) => void;
  onOpenDefinitions: () => void;
  onOpenMap: () => void;
}) {
  if (openId) {
    return <ClaimReader id={openId} connections={connections} onBack={() => onOpen(null)} onOpen={onOpen}
      onInspectClaim={onInspectClaim ?? onOpen}
      onOpenDecision={onOpenDecision} onOpenRun={onOpenRun} onOpenReceipt={onOpenReceipt} />;
  }
  return <ClaimLedger connections={connections} selectedConn={selectedConn} onOpen={onOpen}
    onOpenDefinitions={onOpenDefinitions} onOpenMap={onOpenMap} />;
}

const KIND_WORDS: Record<string, [string, string]> = {
  finding: ["finding", "Findings"], observation: ["observation", "Observations"], reading: ["reading", "Readings"],
  definition: ["definition", "Definitions"], hypothesis: ["hypothesis", "Hypotheses"], prediction: ["prediction", "Predictions"],
  cause: ["cause", "Causes"], said: ["said", "Said"],
};
const kindNoun = (k: string, n = 1) => {
  const w = KIND_WORDS[k]?.[0] ?? k;
  return n === 1 || w === "said" ? w : w === "hypothesis" ? "hypotheses" : `${w}s`;
};

const VERDICT_DOT: Record<PredictionVerdict, "green" | "red" | "grey" | "blue"> = {
  inside: "green", above: "red", below: "red", cannot_tell: "grey", open: "blue",
};
const STATUS_DOT: Record<string, "green" | "grey" | "blue"> = { Final: "green", Provisional: "grey", "To date": "blue" };
const HYPOTHESIS_TONE: Record<string, Tone> = { supported: "up", refuted: "down" };

function ClaimLedger({ connections, selectedConn, onOpen, onOpenDefinitions, onOpenMap }: {
  connections: Connection[]; selectedConn: string; onOpen: (id: string) => void;
  onOpenDefinitions: () => void; onOpenMap: () => void;
}) {
  const [asOf, setAsOf] = useState("");
  const load = useLoad(() => listClaims({ as_of: asOf || undefined, limit: LIMIT }), [asOf]);
  const coverage = useLoad(
    () => (selectedConn ? getOnboarding(selectedConn) : Promise.resolve(null)), [selectedConn]);
  return (
    <ClarityPage testId="claims-page">
      <Gate load={load} what="the Record">
        {all => <ClaimOverview all={all} asOf={asOf} onAsOf={setAsOf} connections={connections} selectedConn={selectedConn}
          coverage={coverage} onOpen={onOpen} onOpenDefinitions={onOpenDefinitions} onOpenMap={onOpenMap} />}
      </Gate>
    </ClarityPage>
  );
}

/** The newest this many claims are read; a page that holds exactly this many says it may hold more. */
const LIMIT = 500;

/** Figures → Needs you → filters beside the list → coverage. The marks every row would repeat (Provisional, measured,
 *  not counted, no owner) are said once, in the figures; a row carries a chip only where it differs from its kind. */
function ClaimOverview({ all, asOf, onAsOf, connections, selectedConn, coverage, onOpen, onOpenDefinitions, onOpenMap }: {
  all: Claim[]; asOf: string; onAsOf: (d: string) => void; connections: Connection[]; selectedConn: string;
  coverage: Load<Onboarding | null>; onOpen: (id: string) => void; onOpenDefinitions: () => void; onOpenMap: () => void;
}) {
  const [query, setQuery] = useState("");
  const [kinds, toggleKind, clearKinds] = useChosen();
  const [abouts, toggleAbout, clearAbouts] = useChosen();
  const [tiers, toggleTier, clearTiers] = useChosen();
  const [verdicts, toggleVerdict, clearVerdicts] = useChosen();

  const aboutKey = (c: Claim) => `${c.about.kind}:${c.about.key}`;
  const aboutName = (c: Claim) => (c.about.kind === "connection" ? connectionLabel(c.about.key, connections) : keyToWords(c.about.key));
  const views = useMemo(() => new Map(all.map(c => [c.id, predictionView(c)])), [all]);
  const verdictOf = (c: Claim) => views.get(c.id)?.verdict ?? "";

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all.filter(c => (!kinds.size || kinds.has(c.kind))
      && (!abouts.size || abouts.has(aboutKey(c)))
      && (!tiers.size || tiers.has(c.tier))
      && (!verdicts.size || verdicts.has(verdictOf(c)))
      && (!q || c.statement.text.toLowerCase().includes(q) || c.statement.metric.toLowerCase().includes(q)
        || c.about.key.toLowerCase().includes(q) || c.owner.toLowerCase().includes(q)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, query, kinds, abouts, tiers, verdicts]);
  const filtered = !!(query.trim() || kinds.size || abouts.size || tiers.size || verdicts.size);
  const clear = () => { setQuery(""); clearKinds(); clearAbouts(); clearTiers(); clearVerdicts(); };

  // What a row need not repeat: the status and the tier most claims of its kind share.
  const usual = useMemo(() => {
    const m = new Map<string, { status: string; tier: string }>();
    for (const [k] of countBy(all, c => c.kind)) {
      const of = all.filter(c => c.kind === k);
      m.set(k, { status: modeOf(of, c => c.status), tier: modeOf(of, c => c.tier) });
    }
    return m;
  }, [all]);

  // Rows under the day they were recorded; each day's heading says once what most of its rows share.
  const recordedDay = (c: Claim) => day(c.recorded_at);
  const authorOf = (c: Claim) => whoLabel(c.author_kind === "agent" ? `agent:${c.author.replace(/^agent:/, "")}` : c.author);
  const groups = useMemo(() => {
    const m = new Map<string, Claim[]>();
    for (const c of rows) m.set(day(c.recorded_at), [...(m.get(day(c.recorded_at)) ?? []), c]);
    return m;
  }, [rows]);
  const groupNorm = (rs: Claim[]) => {
    const share = (key: (c: Claim) => string, words: (v: string, n: number) => string) => {
      const [top] = countBy(rs, key);
      if (!top) return { value: "", phrase: "" };
      return { value: top[0], phrase: top[1] === rs.length ? words(top[0], top[1]) : `mostly ${words(top[0], top[1])}` };
    };
    const k = share(c => c.kind, (v, n) => kindNoun(v, n));
    const a = share(aboutKey, v => aboutName(rs.find(c => aboutKey(c) === v)!));
    const w = share(authorOf, v => `by ${v}`);
    return { kind: k.value, kindPhrase: k.phrase, about: a.value, aboutPhrase: a.phrase, author: w.value, authorPhrase: w.phrase };
  };
  const norms = new Map([...groups].map(([k, rs]) => [k, groupNorm(rs)]));

  const byStatus = new Map(countBy(all, c => c.status));
  const predictions = all.filter(c => c.kind === "prediction");
  const scored = predictions.filter(c => verdictOf(c) !== "open");
  const held = scored.filter(c => verdictOf(c) === "inside");
  const counted = all.filter(c => c.confidence?.hit_rate != null);
  const notes = [...new Set(all.filter(c => c.confidence?.hit_rate == null)
    .map(c => (c.confidence ? c.confidence.note : c.confidence_note) || "").filter(Boolean))];
  const blocker = coverage.data?.coverage.top_blocker as { definition?: string; holds?: number } | null | undefined;

  const columns: ListColumn<Claim>[] = [
    { head: "Statement", value: c => c.statement.text },
    { head: "Kind", value: c => c.kind },
    { head: "About", value: c => aboutName(c) },
    { head: "Warranted", value: c => tierWords(c.tier) },
    { head: "Status", value: c => c.status },
    { head: "State", value: c => c.state },
    { head: "Held how often", value: c => countedWords(c) },
    { head: "Owner", value: c => (c.owner ? whoLabel(c.owner) : "") },
    { head: "As of", value: c => day(c.as_of) },
    { head: "Version", value: c => c.version },
  ];

  return (
    <>
      <Figures testId="claim-figures">
        <Figure label={asOf ? `Claims on ${dateWords(asOf)}` : "Claims"} value={formatCount(all.length)} testId="fig-claims"
          title={all.length >= LIMIT ? `The newest ${LIMIT} are read` : undefined}
          sub={all.length === 0 ? "none on the record" : <>
            <span>{breakdown(countBy(all, c => c.kind), kindNoun)}</span>
            {all.length >= LIMIT && <Chip title="The page reads the newest claims; older ones are not counted here">{`the newest ${LIMIT}`}</Chip>}
          </>} />
        <Figure label="Provisional" value={formatCount(byStatus.get("Provisional") ?? 0)} testId="fig-claims-provisional"
          title="Final · Provisional · To date — the same three words everywhere a figure is shown"
          sub={[
            byStatus.get("To date") ? `${formatCount(byStatus.get("To date")!)} to date` : "",
            byStatus.get("Final") ? `${formatCount(byStatus.get("Final")!)} final` : "none final",
          ].filter(Boolean).join(" · ")} />
        <Figure label="Predictions held" testId="fig-claims-held"
          value={scored.length ? pct(held.length / scored.length, 1) : "—"}
          sub={predictions.length === 0 ? "no prediction is booked"
            : `${formatCount(held.length)} of ${formatCount(scored.length)} scored · ${formatCount(predictions.length - scored.length)} open`} />
        <Figure label="Counted" value={`${formatCount(counted.length)} of ${formatCount(all.length)}`} testId="fig-claims-counted"
          title="How often claims of a kind have been right — counted, never a model's own estimate"
          sub={counted.length === all.length ? "every one has a hit rate"
            : <Chip title={notes.join("\n") || undefined} testId="claims-not-counted">{`${formatCount(all.length - counted.length)} not counted yet`}</Chip>} />
      </Figures>

      <NeedsYou testId="claim-needs" empty="Nothing needs you · predictions are scored by code on their day">
        {blocker?.definition && (blocker.holds ?? 0) > 0 ? [
          <NeedsRow key="blocker" testId="needs-claims-definition"
            title={`${countNoun(blocker.holds ?? 0, "message")} ${blocker.holds === 1 ? "waits" : "wait"} for you to approve “${blocker.definition}”`}
            detail={`held at the gate on ${connectionLabel(selectedConn, connections)} until the definition is approved`}
            actions={<Button size="xs" variant="secondary" onClick={onOpenDefinitions}>Open definitions</Button>} />,
        ] : []}
      </NeedsYou>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(200px, 250px) minmax(0, 1fr)", gap: 14, alignItems: "start" }}>
        <section aria-label="Filter claims" data-testid="claim-facets" style={CARD}>
          <Label>Find</Label>
          <Input value={query} onChange={e => setQuery(e.target.value)} placeholder="a claim, a metric, an owner"
            aria-label="Find a claim" style={{ width: "100%", marginBottom: 12 }} />
          <Label right={asOf ? <Button size="xs" variant="ghost" onClick={() => onAsOf("")}>Back to today</Button> : "today"}>As of</Label>
          <Input type="date" value={asOf} max={new Date().toISOString().slice(0, 10)} aria-label="As of date"
            title="Set a date to read the Record as it stood then" onChange={e => onAsOf(e.target.value)}
            style={{ width: "100%", marginBottom: 12 }} />
          <Facet label="Kind" chosen={kinds} onToggle={toggleKind} testId="facet-kind"
            values={countBy(all, c => c.kind).map(([k, n]) => ({ value: k, label: KIND_WORDS[k]?.[1] ?? k, count: n }))} />
          <Facet label="About" chosen={abouts} onToggle={toggleAbout} testId="facet-about"
            values={countBy(all, aboutKey).map(([k, n]) => {
              const c = all.find(x => aboutKey(x) === k)!;
              return { value: k, label: aboutName(c), count: n, title: c.about.kind === "connection" ? "a connection" : `a ${c.about.kind}` };
            })} />
          <Facet label="Warranted" chosen={tiers} onToggle={toggleTier} testId="facet-tier"
            values={countBy(all, c => c.tier).map(([k, n]) => ({ value: k, label: tierWords(k), count: n }))} />
          {predictions.length > 0 && (
            <Facet label="Predictions" chosen={verdicts} onToggle={toggleVerdict} testId="facet-verdict"
              values={countBy(predictions, verdictOf).map(([k, n]) => ({ value: k, label: VERDICT_SHORT[k as PredictionVerdict] ?? k, count: n }))} />
          )}
          {filtered && <Button size="xs" variant="ghost" onClick={clear}>Clear filters</Button>}
        </section>

        <ListCard<Claim> label="Claims" name={asOf ? `claims-as-of-${asOf}` : "claims"} testId="claim-list"
          rows={rows} rowKey={c => c.id} columns={columns}
          tools={<>
            <span className="aug-fs-xs" style={NUM}>
              {[filtered ? `${formatCount(rows.length)} of ${formatCount(all.length)}` : "",
                asOf ? `as recorded on ${dateWords(asOf)}` : ""].filter(Boolean).join(" · ")}
            </span>
            <DropdownMenu.Root>
              <DropdownMenu.Trigger>
                <Button size="xs" variant="ghost">Tools <Icon name="chevd" size={12} /></Button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Content size="1" align="end">
                <DropdownMenu.Item onSelect={onOpenDefinitions}>Definitions</DropdownMenu.Item>
                <DropdownMenu.Item onSelect={onOpenMap}>Map</DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          </>}
          empty={asOf && !filtered
            ? `Nothing was on the record on ${dateWords(asOf)}.`
            : filtered ? "No claim matches that." : "Nothing is on the record yet. An answer, a finding, a tested hypothesis and a booked prediction each land here."}
          group={{
            key: recordedDay,
            head: k => (k ? `Recorded ${dateWords(k)}` : "Not dated"),
            meta: (k, rs) => {
              const g = norms.get(k);
              return [countNoun(rs.length, "claim"), g?.kindPhrase, g?.aboutPhrase, g?.authorPhrase].filter(Boolean).join(" · ");
            },
          }}
          renderRow={(c, first) => {
            const p = views.get(c.id);
            const norm = usual.get(c.kind);
            // What the group's heading already says (the kind, the connection, the author most of its rows share) is
            // not repeated on the row; a row names only where it differs.
            const g = norms.get(recordedDay(c)) ?? groupNorm([c]);
            const kindPart = c.kind !== g.kind ? kindNoun(c.kind) : "";
            const aboutPart = aboutKey(c) !== g.about ? aboutName(c) : "";
            if (p) {
              return (
                <ListRow first={first} testId="claim-row" onOpen={() => onOpen(c.id)}
                  title={[p.metric, p.period].filter(Boolean).join(" · ")} full={c.statement.text}
                  mark={<Dot hue={VERDICT_DOT[p.verdict]} title={VERDICT_SHORT[p.verdict]} />}
                  chips={p.verdict !== "open" && (
                    <Chip tone={p.verdict === "inside" ? "up" : p.verdict === "cannot_tell" ? "plain" : "down"}>{VERDICT_SHORT[p.verdict]}</Chip>
                  )}
                  figure={p.band} figureTitle={p.bandFull ? `expected ${p.bandFull}` : undefined}
                  meta={[
                    kindPart, aboutPart,
                    p.verdict === "open" ? (p.settles ? `settles ${dateWords(p.settles)}` : "") : (p.scored ? `scored ${dateWords(p.scored)}` : "scored"),
                    p.actual ? `actual ${p.actual}` : "",
                  ].filter(Boolean).join(" · ")} />
              );
            }
            return (
              <ListRow first={first} testId="claim-row" onOpen={() => onOpen(c.id)}
                title={firstSentence(c.statement.text)} full={c.statement.text}
                mark={<Dot hue={STATUS_DOT[c.status] ?? "grey"} title={c.status} />}
                chips={<>
                  {c.kind === "hypothesis" && <Chip tone={HYPOTHESIS_TONE[c.state] ?? "plain"}>{c.state || "open"}</Chip>}
                  {norm && c.status !== norm.status && <Chip>{c.status}</Chip>}
                  {norm && c.tier !== norm.tier && <Chip title="How this statement is warranted">{tierWords(c.tier)}</Chip>}
                  {c.supersedes && <Chip title={`Version ${c.version}: it replaced an earlier one`}>restated</Chip>}
                </>}
                figure={c.statement.value != null ? figure(c.statement.value) : undefined}
                meta={[
                  kindPart, aboutPart,
                  !c.as_of ? "not dated" : day(c.as_of) !== recordedDay(c) ? `as of ${dateWords(c.as_of)}` : "",
                  c.owner ? `owned by ${whoLabel(c.owner)}` : "",
                  authorOf(c) !== g.author ? `by ${authorOf(c)}` : "",
                ].filter(Boolean).join(" · ")} />
            );
          }} />
      </div>

      <Card label="Coverage" right={selectedConn ? connectionLabel(selectedConn, connections) : undefined} testId="claim-coverage">
        {!selectedConn ? (
          <Empty>Coverage is measured per connection · choose one and this says what its data cannot answer yet</Empty>
        ) : (
          <Gate load={coverage} what="coverage">
            {v => (v ? <Coverage view={v} /> : null)}
          </Gate>
        )}
      </Card>
    </>
  );
}

/** What a connection's data answers, in its one line, and what is listed as missing with what each would unlock. The
 *  held messages the line ends on are said once, under Needs you, so the line here stops before them. */
function Coverage({ view }: { view: Onboarding }) {
  const cov = view.coverage as {
    line?: string; note?: string; top_blocker?: unknown; tables?: { mapped?: number; total?: number; share?: number };
  };
  const t = cov.tables;
  const said = (cov.line ?? "").split(" · ").filter(part => !(cov.top_blocker && /wait[s]? for you to approve/.test(part))).join(" · ");
  const line = said
    || (typeof t?.share === "number" ? `${Math.round(t.share * 100)}% of its tables are mapped${t.total != null ? ` (${t.mapped ?? 0} of ${t.total})` : ""}` : "")
    || cov.note || "Coverage is not measured for this connection yet";
  const list = view.shopping_list ?? [];
  const why = (view.shopping_note ?? "").split(";")[0].trim();
  return (
    <div>
      <div className="aug-fs-sm" style={{ color: "var(--t1)" }}>{line}</div>
      {list.length === 0 ? (
        <Empty title={view.shopping_note || undefined}>Nothing is listed as missing{why ? ` · ${why}` : ""}</Empty>
      ) : withUniqueKeys(list.slice(0, 12), item => String(item.what ?? item.missing ?? "gap")).map(([k, item], i) => (
        <div key={k} style={{ padding: "6px 0", ...(i ? RULE : {}) }}>
          <div className="aug-fs-sm" style={{ color: "var(--t1)" }}>{String(item.what ?? item.missing ?? "A gap")}</div>
          <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }}>
            {[Array.isArray(item.unlocks) && item.unlocks.length ? `would unlock: ${item.unlocks.join(", ")}` : "",
              typeof item.why === "string" ? item.why : ""].filter(Boolean).join(" · ")}
          </div>
        </div>
      ))}
    </div>
  );
}

/** One declared link from a type this claim is about into another connection, with the newest
 *  claims on the far side. A far connection the reader may not see is said, and nothing of it named. */
function CrossLink({ link: l, connections, onInspectClaim }: {
  link: ClaimCrossLink; connections: Connection[]; onInspectClaim: (id: string) => void;
}) {
  if (l.withheld) {
    return (
      <div className="aug-item" data-testid="cross-link">
        <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{l.near_type} is linked to a type in a connection you may not see.</div>
        <div className="aug-item-foot aug-fs-sm"><span>Withheld: nothing of that connection is listed here.</span></div>
      </div>
    );
  }
  const shown = l.far_claims.length;
  return (
    <div className="aug-item" data-testid="cross-link">
      <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
        {l.near_type} is linked to {l.far_type}, in {connectionLabel(l.far_connection, connections)}
      </div>
      <div className="aug-item-foot aug-fs-sm">
        {l.name && <span>{l.name}</span>}
        <span>declared in the organisation&apos;s ontology{l.domain && l.domain !== "default" ? `, ${l.domain}` : ""}</span>
        <span>{l.far_claims_total === 0
          ? `no claim about ${l.far_type} is on record there`
          : l.far_claims_total > shown
            ? `the newest ${shown} of ${countNoun(l.far_claims_total, "claim")} about ${l.far_type} there`
            : `${countNoun(l.far_claims_total, "claim")} about ${l.far_type} there`}</span>
      </div>
      {l.far_claims.map(c => (
        <div className="aug-claim-line" key={c.id}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)", minWidth: 0 }}>
            <Button variant="link" size="xs" className="aug-ledger-open" onClick={() => onInspectClaim(c.id)}>{c.text}</Button>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <StatusMark status={c.status} />
            <TierMark tier={c.tier} />
          </div>
        </div>
      ))}
    </div>
  );
}

// ── a claim's own page ───────────────────────────────────────────────────────────────────

function ClaimReader({ id, connections, onBack, onOpen, onInspectClaim, onOpenDecision, onOpenRun, onOpenReceipt }: {
  id: string; connections: Connection[]; onBack: () => void; onOpen: (id: string) => void;
  onInspectClaim: (id: string) => void;
  onOpenDecision: (id: string) => void; onOpenRun: (runId: string) => void; onOpenReceipt: (ref: string) => void;
}) {
  const load = useLoad(() => getClaim(id), [id]);
  const versions = useLoad(() => getClaimVersions(id), [id]);
  // Asked of the ontology's own door, which alone opens an organisation's ontology.
  const links = useLoad(() => getClaimCrossLinks(id), [id]);
  const actor = useActor();
  const [said, setSaid] = useState("");
  const c = load.data;
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <BackHeader from="Claims" onBack={onBack} title={c?.statement.text ?? "Claim"}
        chips={c && <><StatusMark status={c.status} /><TierMark tier={c.tier} /></>} />
      <Gate load={load} what="the claim">
        {claim => (
          <Page rail={<ClaimRail c={claim} connections={connections} />}>
            {said && <p className="aug-fs-sm" role="status" style={{ color: "var(--t2)", margin: "0 0 12px" }}>{said}</p>}
            {claim.superseded_by && (
              <Callout tone="amber" style={{ marginBottom: 16 }}>
                <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>This version was replaced. </span>
                <Button size="xs" variant="link" onClick={() => onOpen(claim.superseded_by)}>Open the current one</Button>
              </Callout>
            )}
            <Section label="What is held">
              <p className="aug-fs-h1 aug-lede">{claim.statement.text}</p>
              <div className="aug-item-foot aug-fs-sm" style={{ marginTop: 6 }}>
                {claim.statement.metric && <span>{keyToWords(claim.statement.metric)}{claim.statement.value != null ? `: ${formatTableNumber(claim.statement.value)} ${claim.statement.unit}` : ""}</span>}
                {(claim.statement.range_start || claim.statement.range_end) && <span>{claim.statement.range_start || "…"} to {claim.statement.range_end || "…"}</span>}
                <Counted claim={claim} />
              </div>
              {!claim.superseded_by && (
                <div style={{ display: "flex", flexWrap: "wrap", marginTop: 8 }}>
                  {/* The page follows the claim to the version the correction booked. */}
                  <MarkWrong claim={claim} actor={actor} onMarked={out => { setSaid(markedWords(out)); onOpen(out.id); }} />
                </div>
              )}
            </Section>

            <Section label="Why it is held" meta={countNoun(claim.warrants.length, "warrant")}>
              {claim.warrants.length === 0 ? (
                <Absent>{claim.tier === "said" ? "It was said, and nothing measured it: no run, document or attestation stands behind it." : "No warrant is recorded on this version."}</Absent>
              ) : claim.warrants.map(w => (
                <div className="aug-item" key={`${w.kind}:${w.ref}`}>
                  <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{w.detail || WARRANT_WORDS[w.kind] || w.kind}</div>
                  <div className="aug-item-foot aug-fs-sm">
                    {w.detail && <span>{WARRANT_WORDS[w.kind] ?? w.kind}</span>}
                    {w.kind === "attestation" && w.ref && <span>by {whoLabel(w.ref)}</span>}
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

            <Section label="Who else was told" meta={claim.told?.length ? countNoun(claim.told.length, "message") : undefined}>
              {(claim.told?.length ?? 0) === 0 ? (
                <Absent>{sentence(claim.told_note || "no message citing this claim is on record")}</Absent>
              ) : claim.told!.map(t => (
                <div className="aug-item" key={t.departure_id}>
                  <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
                    {t.state === "departed" || t.state === "sent" ? "Sent" : t.state === "held" ? "Held at the gate" : sentence(t.state.replace(/_/g, " "))}
                    {t.addressed_to ? ` to ${whoLabel(t.addressed_to)}` : t.target ? ` to ${t.target}` : ""}
                  </div>
                  <div className="aug-item-foot aug-fs-sm">
                    <span>{day(t.at)}</span>
                    {t.kind && <span>{t.kind.replace(/_/g, " ")}</span>}
                    {t.by && <span>by {t.by}</span>}
                    {t.verdict && <span>their verdict: {t.verdict.replace(/_/g, " ")}</span>}
                  </div>
                </div>
              ))}
            </Section>

            {((links.data?.length ?? 0) > 0 || links.error) && (
              <Section label="Linked in other connections" meta={links.data?.length ? countNoun(links.data.length, "link") : undefined}>
                {links.error && <Absent>The organisation&apos;s ontology could not be read just now, so no link is listed.</Absent>}
                {(links.data ?? []).map(l => <CrossLink key={`${l.domain}:${l.relationship}`} link={l} connections={connections} onInspectClaim={onInspectClaim} />)}
              </Section>
            )}

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

const sentence = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) + (/[.!?]$/.test(s) ? "" : ".") : "");

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
