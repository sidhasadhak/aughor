"use client";

/**
 * BriefingCockpits — a person's cockpits, the Cockpit tab beside the Briefing (Arc CT, CT-7 to
 * CT-10; ROADMAP §3.50).
 *
 * The Briefing is the connection's: what the platform found for a period. A cockpit is a
 * person's own: the standing set of cards they keep watching for an area — returns, pricing,
 * marketing — and they may keep as many as they like (§6 item 36(i)–(l)). The user: "The
 * cockpit should be a tab inside the Briefing.. as simple as that" — so it is a tab of the
 * Intelligence workspace, next to the Briefing, and the Briefing's page no longer draws one.
 *
 * Behind `cockpit.composed`; off, the tab is not there. Opening it loads no Briefing and asks
 * no model, and it needs no exploration: a cockpit is made of cards, not of findings.
 *
 * What it does, and what each costs:
 *   - draws the chosen cockpit for a period of its own — the latest month when ranges are on,
 *     "As written" otherwise — each figure against the period it is compared with: no model;
 *   - arranges it by hand, each save a version: no model;
 *   - starts "My cockpit" from the cards pinned before cockpits had names: no model;
 *   - moves a cockpit that lived in a Data Canvas here: no model;
 *   - drafts a new cockpit for an area the person names: ONE short model run, said so on the
 *     button. The draft is shown as its outline, can be adjusted, and is kept or discarded.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { NewCardComposer } from "@/components/brief/NewCardComposer";
import type { RangeChoice } from "@/components/brief/BriefRange";
import type { CardState } from "@/components/brief/PinnedCardBody";
import { CockpitArrange, type CardLine } from "@/components/cockpit/CockpitArrange";
import { ComposedCockpit } from "@/components/cockpit/ComposedCockpit";
import { METRICS_COCKPIT, MetricsCockpit } from "@/components/cockpit/MetricsCockpit";
import { PeriodPicker, choiceName } from "@/components/cockpit/PeriodPicker";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { TabStrip } from "@/components/ui/tab-strip";
import { ErrorState, Loading, Refusal } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import {
  CockpitRefused, acceptProposal, draftCockpit, getCockpit, getProposalById, getSystemFlags, keepCockpit, listCockpits,
  moveCanvasCockpit, rejectProposal, restoreCockpit, retireCockpit, runDashboardCard, startMyCockpit,
  type BriefingRange, type CockpitDrafted, type CockpitKept, type CockpitList, type CockpitVersion,
  type PersonCockpit, type StagedProposal,
} from "@/lib/api";
import { cardsPlaced, placeCard, sectionsOf, takeOffCard, type CockpitSpec } from "@/lib/cockpit/edit";
import { hostStateOf } from "@/lib/cockpit/hostStatus";
import { formatDateTime } from "@/lib/format";

/** The name the Briefing gives when it keeps something for a person. The server writes the
 *  signed-in person's own name where there is one. */
const ACTOR = "briefing";

function person(name: string): string {
  return name.replace(/^user:/, "") || "someone";
}

function changed(c: CockpitVersion["changes"]): string {
  const parts = [
    c.added.length ? `${c.added.length} added` : "",
    c.removed.length ? `${c.removed.length} removed` : "",
    c.changed.length ? `${c.changed.length} changed` : "",
  ].filter(Boolean);
  return parts.join(" · ") || "no change to its elements";
}

/** What a card a draft would create will show, in the words the chat's summary uses. */
function shows(card: { kind?: string; from?: string }): string {
  if (card.kind !== "kpi") return "a chart of its rows";
  return card.from === "metric" ? "one figure for the whole connection" : "one figure";
}

function remembered(connectionId: string): string {
  try { return localStorage.getItem(`aughor:cockpit:${connectionId}`) ?? ""; } catch { return ""; }
}

function remember(connectionId: string, cockpitId: string) {
  try { localStorage.setItem(`aughor:cockpit:${connectionId}`, cockpitId); } catch { /* private mode: the choice just won't persist */ }
}

function Refused({ outcome }: { outcome: CockpitKept }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <Refusal
        kind={outcome.status === "not_checked" ? "Not checked · nothing was kept" : "Refused · nothing was kept"}
        claim="The cockpit was not changed."
        detail={
          <ul data-testid="cockpit-write-refusal" style={{ margin: 0, paddingLeft: 18 }}>
            {outcome.sentences.map((s, i) => <li key={`${i}-${s.slice(0, 24)}`}>{s}</li>)}
          </ul>
        }
      />
    </div>
  );
}

/** A new cockpit for an area: the one door here that asks a model. */
function NewCockpit({ connectionId, schema, onKept, onClose }: {
  connectionId: string; schema?: string; onKept: (cockpitId: string) => void; onClose: () => void;
}) {
  const [area, setArea] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [result, setResult] = useState<CockpitDrafted | null>(null);
  const [proposal, setProposal] = useState<StagedProposal | null>(null);
  const [spec, setSpec] = useState<CockpitSpec | null>(null);
  const [busy, setBusy] = useState(false);

  const draft = async () => {
    setDrafting(true); setResult(null); setProposal(null); setSpec(null);
    try {
      const out = await draftCockpit(connectionId, area, schema);
      setResult(out);
      if (out.staged) {
        const p = await getProposalById(out.proposal_id);
        setProposal(p);
        const draftedSpec = p?.params?.spec as CockpitSpec | undefined;
        setSpec(draftedSpec ? structuredClone(draftedSpec) : null);
      }
    } catch (e) {
      toast.error("The draft did not go through", { description: (e as Error).message.slice(0, 160) });
    } finally { setDrafting(false); }
  };

  // The spec as the model drafted it, to tell the person's changes from the draft.
  const draftedSpec = proposal?.params?.spec as CockpitSpec | undefined;
  const adjusted = spec !== null && draftedSpec !== undefined && JSON.stringify(spec) !== JSON.stringify(draftedSpec);
  const lines = useMemo(() => {
    const m = new Map<string, CardLine>();
    const drafted = proposal?.params?.spec as CockpitSpec | undefined;
    // The draft's outline names every card it places, in the order its spec places them: the
    // titles of cards the person already has are read from it, one section at a time.
    const outlined = ((proposal?.detail?.outline ?? []) as { sections: { cards: { title: string }[] }[] }[])
      .flatMap(t => t.sections);
    if (drafted) {
      sectionsOf(drafted).forEach((sec, i) => {
        drafted.elements[sec.key].children.forEach((k, j) => {
          const id = String(drafted.elements[k]?.props.card ?? "");
          const title = outlined[i]?.cards[j]?.title;
          if (id && title) m.set(id, { title });
        });
      });
    }
    for (const c of ((proposal?.params?.cards ?? []) as { id: string; title: string; kind?: string; from?: string }[])) {
      m.set(c.id, { title: c.title, shows: shows(c), isNew: true });
    }
    return m;
  }, [proposal]);

  const keep = async () => {
    if (!proposal || !result) return;
    setBusy(true);
    try {
      await acceptProposal(proposal.id, ACTOR);
      // Adjusted before keeping: the draft is version 1, the person's changes version 2 — one act,
      // and the history says which was whose (§6 item 36, the builder's third choice).
      if (adjusted && spec) await keepCockpit(connectionId, result.cockpit_id, spec, "adjusted before keeping");
      toast.success(adjusted ? "Kept, with your changes." : "Kept.");
      onKept(result.cockpit_id);
    } catch (e) {
      const why = e instanceof CockpitRefused ? e.outcome.sentences.join(" ") : (e as Error).message;
      toast.error("It was not kept", { description: why.slice(0, 200) });
    } finally { setBusy(false); }
  };

  const discard = async () => {
    if (proposal) { setBusy(true); try { await rejectProposal(proposal.id, ACTOR); } finally { setBusy(false); } }
    setResult(null); setProposal(null); setSpec(null);
  };

  return (
    <div data-testid="cockpit-new" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Input aria-label="What this cockpit is for" placeholder="What is it for? Returns, pricing, marketing…"
          value={area} onChange={e => setArea(e.target.value)} disabled={drafting || busy || !!proposal}
          onKeyDown={e => { if (e.key === "Enter" && area.trim() && !drafting) void draft(); }}
          style={{ maxWidth: 420, flex: 1 }} />
        <Button size="sm" disabled={!area.trim() || drafting || busy || !!proposal} onClick={() => void draft()}>
          {drafting ? "Drafting…" : "Draft it"}
        </Button>
        <Button size="sm" variant="ghost" disabled={drafting || busy} onClick={onClose}>Close</Button>
      </div>
      <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 6 }}>
        {drafting
          ? "A model is drafting it from the connection's approved metrics, trusted queries and findings. This can take a minute."
          : "Drafting asks a model once. Nothing is kept until you keep it."}
      </div>

      {result && !result.staged && (
        <div style={{ marginTop: 12 }}>
          <Refusal kind="Not drafted" claim="No cockpit was drafted for this."
            detail={<ul data-testid="cockpit-not-drafted" style={{ margin: 0, paddingLeft: 18 }}>
              {result.sentences.map((s, i) => <li key={`${i}-${s.slice(0, 24)}`}>{s}</li>)}
            </ul>} />
        </div>
      )}

      {result?.staged && proposal && spec && (
        <div data-testid="cockpit-draft" style={{ marginTop: 14 }}>
          <div className="aug-fs-sm" style={{ color: "var(--t2)", marginBottom: 8 }}>{result.summary}</div>
          {proposal.reasoning && (
            <div className="aug-fs-sm" style={{ color: "var(--t3)", marginBottom: 8 }}>Why it is arranged this way: {proposal.reasoning}</div>
          )}
          <CockpitArrange spec={spec} lines={lines} onChange={setSpec} disabled={busy} />
          <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
            <Button size="sm" disabled={busy} onClick={() => void keep()}>{adjusted ? "Keep, with my changes" : "Keep it"}</Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void discard()}>Discard</Button>
            {adjusted && <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Kept as the draft, then your changes as the next version.</span>}
          </div>
        </div>
      )}
    </div>
  );
}

export function BriefingCockpits({ connectionId, schema, onOpenSource, onEvidence }: {
  connectionId: string;
  schema?: string;
  onOpenSource?: (iid: string) => void;
  onEvidence?: (iid: string) => void;
}) {
  // The period the cards are read for: the person's pick, else the latest complete month where
  // ranges are on — a cockpit is watched month by month, as the mock showed it — else as written.
  // Nothing is read until the flag is known: a first read "as written" would roll every card's
  // standing value for a view nobody asked for.
  const [rangesOn, setRangesOn] = useState<boolean | null>(null);
  const [picked, setChosenRange] = useState<RangeChoice | null>(null);
  const chosenRange: RangeChoice = picked ?? (rangesOn ? { preset: "previous_month" } : { preset: "standing" });
  const range: BriefingRange | null = chosenRange.preset === "standing" ? null : chosenRange;
  const [list, setList] = useState<CockpitList | null | "off">(null);
  const [chosen, setChosen] = useState("");
  const [data, setData] = useState<PersonCockpit | null>(null);
  const [cards, setCards] = useState<CardState[]>([]);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<CockpitKept | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [arranging, setArranging] = useState<CockpitSpec | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [composing, setComposing] = useState(false);
  const [tick, setTick] = useState(0);
  // The cockpit is being read for a period while the cards on screen are still the period before.
  const [reading, setReading] = useState(false);
  const known = useRef<Set<string>>(new Set());
  const adopt = useRef(false);

  const rangeKey = JSON.stringify(range ?? null);
  const reload = useCallback(() => setTick(t => t + 1), []);

  useEffect(() => {
    let alive = true;
    getSystemFlags().then(f => { if (alive) setRangesOn(!!f["briefing.ranges"]?.value); })
      .catch(() => { if (alive) setRangesOn(false); });
    return () => { alive = false; };
  }, []);

  // The person's cockpits. Null from the route means the flag is off: draw what was drawn before.
  useEffect(() => {
    let cancelled = false;
    listCockpits(connectionId).then(l => {
      if (cancelled) return;
      if (l === null) { setList("off"); return; }
      setList(l);
      const live = l.cockpits.filter(c => !c.retired);
      // The metrics are the cockpit a person opens on (asked 2026-10-05); one of their own is
      // opened when it is where they left off.
      setChosen(prev => {
        const want = prev || remembered(connectionId);
        return live.some(c => c.cockpit_id === want) ? want : METRICS_COCKPIT;
      });
    }).catch(e => { if (!cancelled) setProblem((e as Error).message); });
    return () => { cancelled = true; };
  }, [connectionId, tick]);

  // The chosen cockpit, read for the page's range, each card it places run through the guards.
  useEffect(() => {
    if (!chosen || chosen === METRICS_COCKPIT || list === "off") { setData(null); return; }
    if (rangesOn === null) return;
    let cancelled = false;
    setReading(true);
    (async () => {
      try {
        const read = await getCockpit(connectionId, chosen, range);
        const placed = new Set(read.cockpit.spec ? cardsPlaced(read.cockpit.spec) : []);
        const runs = await Promise.all(read.cards.filter(c => placed.has(c.id)).map(async (card): Promise<CardState> => {
          try { return { card, run: await runDashboardCard(card.id, range, { compare: true }) }; }
          catch { return { card, failed: true }; }
        }));
        if (cancelled) return;
        // A card pinned from here lands on the cockpit in view (§6 item 36(k)).
        if (adopt.current && read.cockpit.spec && !read.cockpit.retired) {
          adopt.current = false;
          const fresh = read.cards.filter(c => !known.current.has(c.id) && !placed.has(c.id));
          if (fresh.length) {
            let spec = read.cockpit.spec as CockpitSpec;
            for (const c of fresh) spec = placeCard(spec, c.id);
            try { await keepCockpit(connectionId, chosen, spec, "a card pinned from the Briefing"); reload(); return; }
            catch (e) { if (e instanceof CockpitRefused) setRefusal(e.outcome); }
          }
        }
        known.current = new Set(read.cards.map(c => c.id));
        setData(read); setCards(runs); setProblem("");
      } catch (e) {
        if (!cancelled) setProblem((e as Error).message || "The cockpit could not be read.");
      } finally {
        if (!cancelled) setReading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }, [connectionId, chosen, rangeKey, tick, list === "off", rangesOn]);

  const write = useCallback(async (act: () => Promise<CockpitKept>, done: (k: CockpitKept) => string) => {
    setBusy(true); setRefusal(null);
    try {
      const kept = await act();
      toast.success(done(kept));
      reload();
      return true;
    } catch (e) {
      if (e instanceof CockpitRefused) setRefusal(e.outcome);
      else toast.error("That did not go through", { description: (e as Error).message.slice(0, 160) });
      return false;
    } finally { setBusy(false); }
  }, [reload]);

  const choose = (id: string) => { setChosen(id); remember(connectionId, id); setArranging(null); setShowHistory(false); setRefusal(null); setProblem(""); };

  const refreshOne = useCallback(async (id: string) => {
    try {
      const run = await runDashboardCard(id, range, { compare: true });
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, run, failed: false } : c)));
    } catch {
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, failed: true } : c)));
      toast.error("Couldn't refresh card", { description: "The query failed the trust guards or the source is unavailable." });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }, [rangeKey]);

  // "Remove" on a card takes it off THIS cockpit. The card stays — another cockpit may place it.
  const takeOffOne = useCallback((id: string) => {
    if (!data?.cockpit.spec) return;
    void write(() => keepCockpit(connectionId, data.cockpit_id, takeOffCard(data.cockpit.spec, id), "a card taken off"),
      () => "Taken off this cockpit. The card is kept.");
  }, [connectionId, data, write]);

  const doors = useMemo(() => ({ onRemove: takeOffOne, onRefresh: refreshOne, onOpenSource, onEvidence }),
    [takeOffOne, refreshOne, onOpenSource, onEvidence]);
  const host = useMemo(() => hostStateOf(data?.range.status ?? "standing", cards), [data?.range.status, cards]);

  if (list === "off") {
    return (
      <div style={{ padding: "24px 32px" }}>
        <EmptyState icon="gauge" title="Cockpits are off on this install">
          Cockpits need the cockpit flag, which is off here. The Briefing keeps its own cockpit meanwhile.
        </EmptyState>
      </div>
    );
  }
  if (list === null) {
    return <div className="aug-fs-sm" data-testid="cockpits-loading" style={{ color: "var(--t3)", padding: "24px 32px" }}>Reading your cockpits…</div>;
  }

  const live = list.cockpits.filter(c => !c.retired);
  const kept = data?.cockpit;
  const drawn = kept && !kept.retired && kept.spec != null;
  const pinned = list.shared_cards + list.own_cards;
  const lines = new Map<string, CardLine>((data?.cards ?? []).map(c => [c.id, { title: c.title }]));
  const unplaced = arranging ? (data?.cards ?? []).filter(c => !cardsPlaced(arranging).includes(c.id)) : [];

  const noneYet = (
        <EmptyState icon="gauge" variant="inline"
          title={list.cockpits.length ? "You have no cockpits in use" : "You have no cockpits yet"}
          action={pinned > 0 ? (
            <Button variant="secondary" size="sm" disabled={busy}
              onClick={() => void write(() => startMyCockpit(connectionId), () => "“My cockpit” started from your pinned cards.")}>
              Start “My cockpit” from {pinned} pinned {pinned === 1 ? "card" : "cards"}
            </Button>
          ) : (
            <Button variant="secondary" size="sm" onClick={() => setNewOpen(true)}>New cockpit</Button>
          )}>
          A cockpit is the set of cards you keep watching for one area — returns, pricing, marketing. It is yours:
          nobody else sees it or changes it. Name an area and one is drafted for you to keep, or start from the cards already pinned here.
        </EmptyState>
  );

  return (
    <div data-testid="briefing-cockpits" style={{ flex: 1, overflow: "auto", padding: "14px 32px 32px" }}>
      {/* The strip: the connection's metrics first (nobody's to arrange), then the person's own
          cockpits under the layer's label — violet is the user's, as the Briefing has always marked
          it — and, at the end, the door to a new one. */}
      <TabStrip label="Your cockpits" size="1" value={chosen} onChange={choose} style={{ marginBottom: 12 }}
        tabs={[
          { id: METRICS_COCKPIT, label: "Metrics" },
          { heading: <span className="aug-label" style={{ color: "var(--vio4)" }}>Your cockpits</span> },
          ...live.map(c => ({ id: c.cockpit_id, label: c.title || c.cockpit_id })),
        ]}
        trailing={<Button size="xs" variant="ghost" data-testid="cockpit-new-open" onClick={() => setNewOpen(o => !o)}>+ New cockpit</Button>} />

      {/* A retired cockpit leaves the strip, not the record: it is said here, and brought back
          as the version it was before it was retired. */}
      {list.cockpits.some(c => c.retired) && (
        <div data-testid="cockpit-retired" className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 10, color: "var(--t3)" }}>
          <span>Retired:</span>
          {list.cockpits.filter(c => c.retired).map(c => (
            <span key={c.cockpit_id} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <span>{c.title || c.cockpit_id}</span>
              <Button size="xs" variant="ghost" disabled={busy || c.version < 2}
                onClick={() => void write(() => restoreCockpit(connectionId, c.cockpit_id, c.version - 1),
                  () => `“${c.title}” is back, as it was before it was retired.`).then(ok => { if (ok) choose(c.cockpit_id); })}>
                Bring back
              </Button>
            </span>
          ))}
        </div>
      )}

      {newOpen && (
        <NewCockpit connectionId={connectionId} schema={schema} onClose={() => setNewOpen(false)}
          onKept={id => { setNewOpen(false); choose(id); reload(); }} />
      )}

      {/* Cockpits that lived in a Data Canvas, offered here once (CT-10). */}
      {list.from_canvases.map(c => (
        <div key={c.canvas_id} data-testid="cockpit-move-offer" className="aug-fs-sm"
          style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, color: "var(--t2)" }}>
          <span>“{c.title}” was kept in a Data Canvas, which is for questions and deep analysis now. Move it here, with its cards?</span>
          <Button size="xs" variant="secondary" disabled={busy} onClick={async () => {
            setBusy(true);
            try {
              const out = await moveCanvasCockpit(connectionId, c.canvas_id);
              if (out.moved) { toast.success(`Moved “${out.title}” here.`); if (out.cockpit_id) choose(out.cockpit_id); reload(); }
              else toast.error("It was not moved", { description: out.sentences.join(" ").slice(0, 200) });
            } finally { setBusy(false); }
          }}>Move it here</Button>
        </div>
      ))}

      {refusal && <Refused outcome={refusal} />}
      {problem && (
        <ErrorState kind="Failed" what="Your cockpit could not be read." means={problem}
          doors={[{ label: "Try again", onClick: reload, primary: true }]} />
      )}

      {chosen === METRICS_COCKPIT ? (
        <>
          <MetricsCockpit connectionId={connectionId} schema={schema} rangesOn={rangesOn}
            value={chosenRange} onChange={setChosenRange} />
          {live.length === 0 && <div style={{ marginTop: 20 }}>{noneYet}</div>}
        </>
      ) : live.length === 0 ? noneYet : drawn && data ? (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 4 }}>
            {data.ranges_on && (
              <PeriodPicker value={chosenRange} onChange={setChosenRange} disabled={busy} reading={reading}
                showing={data.range.status === "standing" || reading ? null : data.range} />
            )}
            {reading && <Loading inline what={`the cards for ${choiceName(chosenRange)}`} />}
            <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
              {!arranging && (
                <Button size="xs" variant="ghost" disabled={busy || composing} data-testid="cockpit-card-new"
                  onClick={() => setComposing(true)}>
                  <Icon name="plus" /> Card
                </Button>
              )}
              {!arranging && (
                <Button size="xs" variant="ghost" disabled={busy} data-testid="cockpit-arrange-open"
                  onClick={() => setArranging(JSON.parse(JSON.stringify(kept.spec)) as CockpitSpec)}>
                  <Icon name="sliders" /> Arrange
                </Button>
              )}
              <Button size="xs" variant="ghost" aria-expanded={showHistory} onClick={() => setShowHistory(s => !s)}>
                <Icon name="history" /> {showHistory ? "Hide history" : "History"}
              </Button>
            </span>
          </div>

          {showHistory && (
            <div style={{ margin: "8px 0 12px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
              <span className="aug-fs-sm" data-testid="cockpit-version" style={{ color: "var(--t3)" }}>
                Version {kept.version} · {kept.written_by_model ? "drafted, kept" : "kept"} by {person(kept.approved_by)} · {formatDateTime(kept.kept_at)}
              </span>
              <Button size="xs" variant="ghost" disabled={busy} style={{ marginLeft: "auto" }}
                onClick={() => void write(() => retireCockpit(connectionId, data.cockpit_id), () => "Cockpit retired. Its history stays.")}>
                Retire this cockpit
              </Button>
            </div>
            <ol data-testid="cockpit-history" style={{ listStyle: "none", margin: 0, padding: 0, borderTop: "1px solid var(--b1)" }}>
              {data.history.map(v => (
                <li key={v.artifact_id} className="aug-fs-sm" style={{ display: "flex", alignItems: "baseline", gap: 12, padding: "7px 0", borderBottom: "1px solid var(--b1)", color: "var(--t2)" }}>
                  <span style={{ color: "var(--t1)", fontWeight: 500, minWidth: 74 }}>Version {v.version}</span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    {v.retired ? "Retired" : changed(v.changes)} · {person(v.approved_by)} · {formatDateTime(v.kept_at)}
                    {v.source ? ` · ${v.source}` : ""}{v.note ? ` · ${v.note}` : ""}
                  </span>
                  {v.current ? <span style={{ color: "var(--t3)" }}>current</span> : v.retired ? null : (
                    <Button variant="ghost" size="xs" disabled={busy}
                      onClick={() => void write(() => restoreCockpit(connectionId, data.cockpit_id, v.version),
                        k => (k.status === "unchanged" ? "That is the version you are on." : `Back to version ${v.version}, kept as version ${k.version}.`))}>
                      Go back to this
                    </Button>
                  )}
                </li>
              ))}
            </ol>
            </div>
          )}

          {arranging ? (
            <div style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16 }}>
              <CockpitArrange spec={arranging} lines={lines} onChange={setArranging} disabled={busy} />
              {unplaced.length > 0 && (
                <div data-testid="cockpit-tray" style={{ marginTop: 12 }}>
                  <div className="aug-label" style={{ marginBottom: 6 }}>Cards you have that are not on this cockpit</div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {unplaced.map(c => (
                      <Button key={c.id} size="xs" variant="outline" onClick={() => setArranging(s => (s ? placeCard(s, c.id) : s))}>
                        + {c.title}
                      </Button>
                    ))}
                  </div>
                </div>
              )}
              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <Button size="sm" disabled={busy || JSON.stringify(arranging) === JSON.stringify(kept.spec)}
                  onClick={async () => {
                    const ok = await write(() => keepCockpit(connectionId, data.cockpit_id, arranging, "arranged by hand"),
                      k => (k.status === "unchanged" ? "Nothing changed." : `Kept as version ${k.version}.`));
                    if (ok) setArranging(null);
                  }}>Save</Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setArranging(null); setRefusal(null); }}>Cancel</Button>
              </div>
            </div>
          ) : (
            <>
              {composing && (
                <div style={{ marginTop: 8 }}>
                  <NewCardComposer connectionId={connectionId} schema={schema} startOpen
                    onClose={() => setComposing(false)}
                    onCreated={() => { adopt.current = true; reload(); }} />
                </div>
              )}
              {!reading && data.range.edge_note && (
                <div className="aug-fs-sm" data-testid="cockpit-edge-note" style={{ color: "var(--t2)", margin: "4px 0 8px" }}>{data.range.edge_note}</div>
              )}
              <div aria-busy={reading || undefined}
                style={{ opacity: reading ? 0.45 : 1, transition: "opacity 120ms ease-out", pointerEvents: reading ? "none" : undefined }}>
                <ComposedCockpit spec={kept.spec} cards={cards} host={host} doors={doors} sym={data.currency_symbol || "$"} />
              </div>
            </>
          )}
        </>
      ) : !problem ? (
        <div className="aug-fs-sm" data-testid="cockpit-loading" style={{ color: "var(--t3)" }}>Reading the cockpit…</div>
      ) : null}
    </div>
  );
}
