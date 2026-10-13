"use client";

/**
 * Evidence — the claim ledger, laid out to CLARITY (`aughor-v2/CLARITY.md`) as a ledger that reads like a document:
 * one line of what it holds, the claims no one has reviewed under "Needs you", then the claims under the deep analysis
 * that made them, the chosen one open beside the list with its whole query and the feedback buttons.
 *
 * Drawn only from what the ledger records (aughor/evidence). What it does not carry is left out, not invented: guard
 * results and a verdict per claim, refused claims (the ledger keeps what a run asserted, never what it refused), a
 * receipt id, run time and bytes read, and "used in" or an outcome (`downstream_recommendations` and `outcome_status`
 * have no writer). `data_freshness` is the run's completion time, so a claim reads "recorded", never "data as of";
 * `metric_used` is a keyword guess, so it reads "mentions".
 *
 * Confidence is COUNTED or absent (the 2027 study, phase 1): a row written since carries null and reads "not counted".
 * The 0.8 / 0.5 that older rows carry were set by whether a step called itself significant, and say so on hover.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { CARD, Chip, Dot, Empty, Label, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, Page, ROW, RULE }
  from "@/components/clarity/kit";
import { TableActions } from "@/components/TableActions";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Loading, ReadFailed } from "@/components/ui/states";
import {
  getInvestigationsList as listRuns, getRecentEvidenceClaims, submitClaimFeedback, type EvidenceClaim,
} from "@/lib/api";
import { countNoun, formatCount, formatTimestamp, relTime } from "@/lib/format";
import { dayWords } from "@/lib/home";
import { runDisplayTitle } from "@/lib/runTitle";

type Feedback = "validated" | "disputed" | "needs_context";
type Filter = "all" | "unreviewed" | Feedback;

/** A review's word, its button, and the hue of its mark: checked green, adverse red, waiting on context amber. */
const FEEDBACK: Record<Feedback, { word: string; door: string; hue: "green" | "red" | "amber" }> = {
  validated:     { word: "validated",     door: "Validated",     hue: "green" },
  disputed:      { word: "disputed",      door: "Disputed",      hue: "red" },
  needs_context: { word: "needs context", door: "Needs context", hue: "amber" },
};

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all",           label: "all" },
  { id: "unreviewed",    label: "unreviewed" },
  { id: "validated",     label: "validated" },
  { id: "disputed",      label: "disputed" },
  { id: "needs_context", label: "needs context" },
];

/** How many recent claims the layer reads. */
export const LIMIT = 80;

const matches = (c: EvidenceClaim, f: Filter) =>
  f === "all" || (f === "unreviewed" ? !c.owner_feedback : c.owner_feedback === f);

/** A claim as the ledger writes it — "Headline: what was measured…" — split into the line a row shows and the rest. */
export function splitClaim(text: string): { head: string; rest: string } {
  const t = (text || "").trim();
  const colon = t.indexOf(": ");
  if (colon > 0 && colon <= 140) return { head: t.slice(0, colon), rest: t.slice(colon + 2).trim() };
  const stop = t.search(/[.!?]\s+\S/);
  if (stop > 0 && stop <= 160) return { head: t.slice(0, stop + 1), rest: t.slice(stop + 1).trim() };
  return { head: t, rest: "" };
}

/** "2d ago"; nothing when the time cannot be read. */
const ago = (iso: string) => { const t = relTime(iso); return t === "—" ? "" : `${t} ago`; };

/** A run's name: its question as a person asked it (a scheduled run's grounding stripped), cut to its first sentence. */
interface RunName { title: string; full: string; scheduled: boolean }

function runName(question: string): RunName {
  const { title, scheduled } = runDisplayTitle(question);
  const cut = title.search(/[?!.]\s+\S/);
  return { title: cut > 0 ? title.slice(0, cut + 1) : title, full: title, scheduled };
}

/** The run a claim came from — the wire spells it as the deep analysis's frozen name. */
const runOf = (c: EvidenceClaim) => c.investigation_id;

/** The claims of one run, in the order the ledger gave them. */
interface Group { run: string; at: string; claims: EvidenceClaim[] }

function groupByRun(claims: readonly EvidenceClaim[]): Group[] {
  const out = new Map<string, Group>();
  for (const c of claims) {
    const run = runOf(c);
    const g = out.get(run);
    if (g) g.claims.push(c);
    else out.set(run, { run, at: c.created_at, claims: [c] });
  }
  return [...out.values()];
}

export function EvidencePanel({ connectionId, canvasId, onInvestigate: reexamine }: {
  connectionId:  string;
  canvasId?:     string;
  onInvestigate?: (q: string) => void;
}) {
  const [claims, setClaims]         = useState<EvidenceClaim[] | null>(null);
  const [failed, setFailed]         = useState("");
  const [filter, setFilter]         = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving]         = useState(false);
  const [notSaved, setNotSaved]     = useState("");
  // The runs' questions, so a group is headed by what was asked — never by the run's id. A failed read leaves each
  // group headed "deep analysis <id>", which says what it is without a name.
  const [names, setNames] = useState<Map<string, RunName>>(new Map());

  const load = useCallback(() => {
    setFailed("");
    setClaims(null);
    getRecentEvidenceClaims(connectionId, canvasId, LIMIT)
      .then(setClaims)
      .catch(e => setFailed(e instanceof Error ? e.message : String(e)));
    listRuns(200)
      .then(rows => setNames(new Map(rows.map(r => [r.id, runName(r.question)]))))
      .catch(() => undefined);
  }, [connectionId, canvasId]);

  useEffect(() => { load(); }, [load]);

  const all = useMemo(() => claims ?? [], [claims]);
  const counts = useMemo(() => Object.fromEntries(FILTERS.map(f => [f.id, all.filter(c => matches(c, f.id)).length])) as
    Record<Filter, number>, [all]);
  const shown = useMemo(() => all.filter(c => matches(c, filter)), [all, filter]);
  const groups = useMemo(() => groupByRun(shown), [shown]);
  const selected = shown.find(c => c.id === selectedId) ?? shown[0] ?? null;
  const nameOf = (run: string): RunName => names.get(run)
    ?? { title: `deep analysis ${run.slice(0, 8)}`, full: "", scheduled: false };

  const handleFeedback = useCallback(async (claim: EvidenceClaim, fb: Feedback) => {
    setSaving(true);
    setNotSaved("");
    // Optimistic; clicking the active one is still a set — the server is the source of truth.
    setClaims(cs => (cs ?? []).map(c => (c.id === claim.id ? { ...c, owner_feedback: fb } : c)));
    try {
      await submitClaimFeedback(runOf(claim), claim.id, fb);
    } catch (e) {
      setNotSaved(e instanceof Error ? e.message : String(e));
      setClaims(cs => (cs ?? []).map(c => (c.id === claim.id ? { ...c, owner_feedback: claim.owner_feedback } : c)));
    } finally {
      setSaving(false);
    }
  }, []);

  const scope = canvasId ? "this canvas" : "this connection";
  const capped = all.length >= LIMIT;

  const lead = (
    <div style={{ ...ROW, gap: 10 }}>
      <p className="aug-fs-ui" style={{ margin: 0, color: "var(--t2)", flex: "1 1 360px", minWidth: 0 }}>
        What the deep analyses on {scope} claimed, and the query behind each — newest first.
      </p>
      {claims && claims.length > 0 && (
        <span className="aug-fs-sm" style={{ ...MUTED, ...NUM }}
          title={capped ? `Only the latest ${LIMIT} claims are read; older ones are not shown.` : undefined}>
          {capped ? `the latest ${LIMIT} claims` : countNoun(all.length, "claim")} · {countNoun(groupByRun(all).length, "deep analysis", "deep analyses")}
        </span>
      )}
      <Button variant="ghost" size="xs" onClick={load}>Refresh</Button>
    </div>
  );

  if (failed) {
    return <Page testId="evidence-page">{lead}<ReadFailed what="the claim ledger" error={failed} onRetry={load} /></Page>;
  }
  if (!claims) {
    return <Page testId="evidence-page">{lead}<Loading what="the claim ledger" /></Page>;
  }
  if (claims.length === 0) {
    return (
      <Page testId="evidence-page">
        {lead}
        <Empty>No claims yet — each deep analysis on {scope} records the claims it made and the query behind each.</Empty>
      </Page>
    );
  }

  const unreviewed = all.filter(c => !c.owner_feedback);
  const review = () => { setFilter("unreviewed"); setSelectedId(unreviewed[0]?.id ?? null); };

  return (
    <Page testId="evidence-page">
      {lead}

      <NeedsYou testId="evidence-needs" empty="Every claim here has been reviewed.">
        {unreviewed.length > 0 && (
          <NeedsRow key="unreviewed" testId="evidence-needs-unreviewed"
            title={`${countNoun(unreviewed.length, "claim")} no one has reviewed`}
            detail="The alerts count them until each is marked validated, disputed or needs context."
            actions={<Button size="xs" variant="secondary" onClick={review}>Review</Button>} />
        )}
        {counts.disputed > 0 && (
          <NeedsRow key="disputed" title={`${countNoun(counts.disputed, "claim")} disputed`}
            detail="Open one and Re-examine sends it to a deep analysis."
            actions={<Button size="xs" variant="ghost" onClick={() => { setFilter("disputed"); setSelectedId(null); }}>Show</Button>} />
        )}
      </NeedsYou>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(300px, 36%)", gap: 14, alignItems: "start" }}>
        <section aria-label="Claims" style={CARD}>
          <Label right={<>
            <Segmented label="Filter claims by review" value={filter}
              onChange={f => { setFilter(f); setSelectedId(null); }}
              options={FILTERS.map(f => ({ value: f.id, label: <>{f.label} <span style={NUM}>{formatCount(counts[f.id])}</span></> }))} />
            <TableActions name="claims" read={() => ({
              columns: ["claim", "deep analysis", "review", "confidence", "mentions", "query", "recorded"],
              rows: shown.map(c => [c.claim_text, nameOf(runOf(c)).full || nameOf(runOf(c)).title,
                c.owner_feedback ? FEEDBACK[c.owner_feedback].word : "not reviewed", c.confidence ?? "not counted",
                c.metric_used ?? "", c.sql_source ?? "", c.created_at]),
            })} />
          </>}>Claims</Label>

          {groups.length === 0 && (
            <Empty>No claim here is {FILTERS.find(f => f.id === filter)?.label}.</Empty>
          )}
          {groups.map((g, gi) => {
            const name = nameOf(g.run);
            return (
              <div key={g.run} data-testid="evidence-run" style={{ paddingTop: gi === 0 ? 0 : 10 }}>
                <div className="aug-fs-sm" style={{ display: "flex", alignItems: "baseline", gap: 8, padding: "6px 8px 4px",
                  ...(gi === 0 ? {} : RULE) }}>
                  <span title={name.full || undefined} style={{ ...ONE_LINE, color: "var(--t2)", fontWeight: 500 }}>{name.title}</span>
                  {name.scheduled && <Chip>scheduled</Chip>}
                  <span title={formatTimestamp(g.at)} style={{ ...MUTED, ...NUM, marginLeft: "auto", whiteSpace: "nowrap" }}>
                    {dayWords(g.at)} · {countNoun(g.claims.length, "claim")}
                  </span>
                </div>
                {g.claims.map(c => {
                  const { head, rest } = splitClaim(c.claim_text);
                  const on = selected?.id === c.id;
                  const fb = c.owner_feedback ? FEEDBACK[c.owner_feedback] : null;
                  return (
                    // The chosen row's tint sits outside the button: a ghost button takes the gray accent, so the
                    // selection tint drawn on it would read grey.
                    <div key={c.id} style={{ borderRadius: "var(--r2)", background: on ? "var(--bg-sel)" : undefined }}>
                    <Button variant="ghost" data-testid="evidence-claim" aria-current={on || undefined}
                      onClick={() => { setSelectedId(c.id); setNotSaved(""); }}
                      style={{ display: "block", width: "100%", height: "auto", margin: 0, padding: "6px 8px", textAlign: "left",
                        whiteSpace: "normal", fontWeight: 400, borderRadius: "var(--r2)" }}>
                      <span style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                        <Dot hue={fb?.hue ?? "grey"} title={fb?.word ?? "not reviewed"} />
                        <span className="aug-fs-chrome" style={{ ...ONE_LINE, flex: 1, color: "var(--t1)" }}>{head}</span>
                        {!c.sql_source && <Chip title="No query was recorded for this claim.">no query</Chip>}
                      </span>
                      {rest && (
                        <span className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE, display: "block", paddingLeft: 15 }}>{rest}</span>
                      )}
                    </Button>
                    </div>
                  );
                })}
              </div>
            );
          })}

          <div className="aug-fs-xs" style={{ ...MUTED, ...RULE, marginTop: 10, paddingTop: 8 }}>
            {shown.length < all.length ? `${formatCount(shown.length)} of ${formatCount(all.length)} shown · ` : ""}
            Guard results and refusals are not recorded with a claim.
          </div>
        </section>

        {selected && (
          <ClaimReader claim={selected} run={nameOf(runOf(selected))} saving={saving} notSaved={notSaved}
            onFeedback={fb => void handleFeedback(selected, fb)}
            onReexamine={reexamine ? () => reexamine(`Re-examine this claim: ${selected.claim_text}`) : undefined} />
        )}
      </div>
    </Page>
  );
}

/** The chosen claim, beside the list: the whole sentence, its marks, the query behind it, and the review buttons. */
function ClaimReader({ claim, run, saving, notSaved, onFeedback, onReexamine }: {
  claim: EvidenceClaim; run: RunName; saving: boolean; notSaved: string;
  onFeedback: (fb: Feedback) => void; onReexamine?: () => void;
}) {
  const { head, rest } = splitClaim(claim.claim_text);
  return (
    <section aria-label="The chosen claim" data-testid="evidence-reader"
      style={{ ...CARD, position: "sticky", top: 0, display: "flex", flexDirection: "column", gap: 10 }}>
      <Label right={<span title={formatTimestamp(claim.created_at)} style={NUM}>recorded {ago(claim.created_at)}</span>}>Claim</Label>
      <div>
        <p className="aug-fs-ui" style={{ margin: 0, color: "var(--t1)", fontWeight: 500 }}>{head}</p>
        {rest && <p className="aug-fs-chrome" style={{ margin: "4px 0 0", color: "var(--t2)", lineHeight: 1.55 }}>{rest}</p>}
      </div>
      <div style={{ ...ROW, gap: 6 }}>
        {claim.confidence == null
          ? <Chip title="No counted confidence for this claim yet.">confidence not counted</Chip>
          : <Chip title="Written by an older version from whether the step called itself significant — not counted.">
              confidence {claim.confidence.toFixed(2)}
            </Chip>}
        {claim.metric_used && <Chip title="A keyword found in the claim, not a link to the metric.">mentions {claim.metric_used}</Chip>}
        <span className="aug-fs-xs" title={run.full || undefined} style={{ ...MUTED, ...ONE_LINE }}>from {run.title}</span>
      </div>

      <div>
        <Label>The query behind it</Label>
        {claim.sql_source
          ? <pre className="aug-fs-xs" style={{ margin: 0, padding: "8px 10px", background: "var(--bg-1)", borderRadius: "var(--r2)",
              color: "var(--t2)", fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap", overflowWrap: "anywhere",
              maxHeight: 280, overflowY: "auto" }}>{claim.sql_source}</pre>
          : <Empty>No query was recorded for this claim.</Empty>}
      </div>

      <div>
        <Label>Review</Label>
        <div style={ROW}>
          {(Object.keys(FEEDBACK) as Feedback[]).map(k => (
            <Button key={k} variant="outline" size="xs" disabled={saving} aria-pressed={claim.owner_feedback === k}
              className={`aug-fb-door aug-fb-door-${k}`} onClick={() => onFeedback(k)}>
              {FEEDBACK[k].door}
            </Button>
          ))}
          {onReexamine && (
            <Button variant="secondary" size="xs" style={{ marginLeft: "auto" }} onClick={onReexamine}
              title="Ask a deep analysis to check this claim again">Re-examine</Button>
          )}
        </div>
        <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 6 }}
          title="Recorded on this claim. The alert summary counts the claims no one has reviewed; nothing else reads a review yet, so it does not change future claims.">
          Counted by the alerts until marked; it does not change future claims.
        </div>
        {notSaved && (
          <div role="alert" className="aug-fs-xs" style={{ color: "var(--red4)", marginTop: 4 }}>Not saved — {notSaved}</div>
        )}
      </div>
    </section>
  );
}
