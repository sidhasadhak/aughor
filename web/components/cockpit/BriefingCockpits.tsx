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
import { ComposedCockpit, type CockpitDoors } from "@/components/cockpit/ComposedCockpit";
import { FindingPicker } from "@/components/cockpit/FindingPicker";
import { OntologyPieceComposer } from "@/components/cockpit/OntologyPieceComposer";
import { METRICS_COCKPIT, MetricsCockpit } from "@/components/cockpit/MetricsCockpit";
import { PeriodPicker, choiceName } from "@/components/cockpit/PeriodPicker";
import { person as personName, type ImageStamp } from "@/components/cockpit/StaticTile";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { TabStrip } from "@/components/ui/tab-strip";
import { ErrorState, Loading, Refusal } from "@/components/ui/states";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import {
  CockpitRefused, acceptProposal, askCockpit, cockpitAudiences, cockpitImageUrl, copySharedCockpit, draftCockpit, findingOfCard,
  getCockpit, getProposalById, getSharedCockpit, getSystemFlags, keepCockpit, listCockpits, listSharedCockpits, moveCanvasCockpit,
  publishCockpit, rejectProposal, restoreCockpit, retireCockpit, runDashboardCard, startMyCockpit, unpublishCockpit,
  uploadCockpitImage,
  type BriefingRange, type CockpitAudience, type CockpitDrafted, type CockpitKept, type CockpitList, type CockpitVersion,
  type PersonCockpit, type SharedCockpit, type SharedCockpitListed, type StagedProposal,
} from "@/lib/api";
import { MAX_CAPTION, MAX_NOTE, type Size } from "@/lib/cockpit/catalog";
import {
  cardsPlaced, editNote, placeCard, placeImage, placeNote, placePiece, recaption, resize, sectionsOf, takeOff, takeOffCard,
  type CockpitSpec,
} from "@/lib/cockpit/edit";
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

/** A note, typed by the person — the one element of a cockpit a model never writes (the canvas,
 *  2026-10-08). Its author and date are the server's to stamp when it is kept. */
function NoteComposer({ busy, onPlace, onClose }: { busy: boolean; onPlace: (text: string) => void; onClose: () => void }) {
  const [text, setText] = useState("");
  return (
    <div data-testid="cockpit-note-composer" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16, display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
        Your words, as a reminder to yourself or your readers: bold, italics, lists and links, up to {MAX_NOTE} characters.
        Aughor never reads a note, cites it or learns from it; a model may move it, never write it.
      </div>
      <Textarea aria-label="The note's words" placeholder="Target for Q4: return rate under **10%**…" value={text} maxLength={MAX_NOTE}
        autoFocus disabled={busy} onChange={e => setText(e.target.value)} style={{ minHeight: 96 }} />
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button size="sm" disabled={busy || !text.trim()} onClick={() => onPlace(text)}>Place the note</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onClose}>Cancel</Button>
        <span className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--t3)", fontVariantNumeric: "tabular-nums" }}>{text.length} / {MAX_NOTE}</span>
      </div>
    </div>
  );
}

/** An image, chosen and uploaded by the person — the other element a model never makes. */
function ImageComposer({ connectionId, busy, onPlace, onClose }: {
  connectionId: string; busy: boolean; onPlace: (objectId: string, caption: string) => void; onClose: () => void;
}) {
  const [caption, setCaption] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [refused, setRefused] = useState("");
  const upload = async () => {
    if (!file) return;
    setUploading(true); setRefused("");
    try {
      const stamp = await uploadCockpitImage(connectionId, file);
      onPlace(stamp.object, caption.trim() || file.name);
    } catch (e) {
      setRefused((e as Error).message);
    } finally { setUploading(false); }
  };
  return (
    <div data-testid="cockpit-image-composer" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16, display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
        PNG, JPEG, GIF, WebP or SVG, up to 5 MB, into this connection's cockpit volume. It shows who uploaded it and when,
        and no period or comparison: a static thing says it is static.
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input type="file" aria-label="The image file" accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
          disabled={busy || uploading} onChange={e => { setFile(e.target.files?.[0] ?? null); setRefused(""); }} />
        <Input aria-label="Caption" placeholder="Caption" value={caption} maxLength={MAX_CAPTION} disabled={busy || uploading}
          onChange={e => setCaption(e.target.value)} style={{ maxWidth: 320, flex: 1 }} />
      </div>
      {refused && <div className="aug-fs-sm" data-testid="cockpit-image-refused" style={{ color: "var(--red4)" }}>{refused}</div>}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button size="sm" disabled={busy || uploading || !file} onClick={() => void upload()}>{uploading ? "Uploading…" : "Upload and place"}</Button>
        <Button size="sm" variant="ghost" disabled={busy || uploading} onClick={onClose}>Cancel</Button>
      </div>
    </div>
  );
}

/** What a staged proposal places, by card id — the titles of cards the person already has, read
 *  from the draft's outline, and the cards it would create. */
function linesOf(proposal: StagedProposal | null, held: Map<string, CardLine> = new Map()): Map<string, CardLine> {
  const m = new Map<string, CardLine>(held);
  const drafted = proposal?.params?.spec as CockpitSpec | undefined;
  // The draft's outline names every element it places, in the order its spec places them: the
  // titles of cards the person already has are read from it, one section at a time.
  const outlined = ((proposal?.detail?.outline ?? []) as { sections: { cards: { title: string; static?: string }[] }[] }[])
    .flatMap(t => t.sections);
  if (drafted) {
    sectionsOf(drafted).forEach((sec, i) => {
      drafted.elements[sec.key].children.forEach((k, j) => {
        const id = String(drafted.elements[k]?.props.card ?? "");
        const line = outlined[i]?.cards[j];
        if (id && line?.title && !line.static) m.set(id, { title: line.title });
      });
    });
  }
  for (const c of ((proposal?.params?.cards ?? []) as { id: string; title: string; kind?: string; from?: string }[])) {
    m.set(c.id, { title: c.title, shows: shows(c), isNew: true });
  }
  return m;
}

/** A staged proposal, read before it is kept: a draft or an edit as its outline, which the person
 *  may adjust by hand first; a publish as who it reaches. Kept whole or discarded whole. */
function DraftReview({ connectionId, cockpitId, result, proposal, held, onKept, onDiscarded }: {
  connectionId: string;
  /** The cockpit the proposal is for: a new one's id from the draft, or the one that stands. */
  cockpitId: string;
  result: CockpitDrafted;
  proposal: StagedProposal;
  held?: Map<string, CardLine>;
  onKept: (cockpitId: string) => void;
  onDiscarded: () => void;
}) {
  const proposed = proposal.params?.spec as CockpitSpec | undefined;
  const [spec, setSpec] = useState<CockpitSpec | null>(proposed ? structuredClone(proposed) : null);
  const [busy, setBusy] = useState(false);
  const detail = (proposal.detail ?? {}) as { mode?: string; to?: string[]; taken_off?: { what: string; title: string; from: string }[] };
  const publish = detail.mode === "publish";
  const adjusted = spec !== null && proposed !== undefined && JSON.stringify(spec) !== JSON.stringify(proposed);
  const lines = useMemo(() => linesOf(proposal, held), [proposal, held]);

  const keep = async () => {
    setBusy(true);
    try {
      await acceptProposal(proposal.id, ACTOR);
      // Adjusted before keeping: the draft is one version, the person's changes the next — one act,
      // and the history says which was whose (§6 item 36, the builder's third choice).
      if (adjusted && spec) await keepCockpit(connectionId, cockpitId, spec, "adjusted before keeping");
      toast.success(publish ? "Published." : adjusted ? "Kept, with your changes." : "Kept.");
      onKept(cockpitId);
    } catch (e) {
      const why = e instanceof CockpitRefused ? e.outcome.sentences.join(" ") : (e as Error).message;
      toast.error("It was not kept", { description: why.slice(0, 200) });
    } finally { setBusy(false); }
  };

  const discard = async () => {
    setBusy(true);
    try { await rejectProposal(proposal.id, ACTOR); } finally { setBusy(false); }
    onDiscarded();
  };

  return (
    <div data-testid="cockpit-draft" style={{ marginTop: 14 }}>
      <div className="aug-fs-sm" style={{ color: "var(--t2)", marginBottom: 8 }}>{result.summary}</div>
      {proposal.reasoning && (
        <div className="aug-fs-sm" style={{ color: "var(--t3)", marginBottom: 8 }}>Why it is arranged this way: {proposal.reasoning}</div>
      )}
      {publish ? (
        <div className="aug-fs-sm" data-testid="cockpit-publish-proposal" style={{ color: "var(--t1)" }}>
          Publish this cockpit, as it stands, to {(detail.to ?? []).join(", ")} — read-only for its readers, under your name.
          Your notes and images travel marked as yours.
        </div>
      ) : spec ? (
        <CockpitArrange spec={spec} lines={lines} onChange={setSpec} disabled={busy} />
      ) : null}
      {!!detail.taken_off?.length && (
        <div className="aug-fs-sm" data-testid="cockpit-taken-off" style={{ color: "var(--t2)", marginTop: 8 }}>
          Taken off: {detail.taken_off.map(t => `${t.title}${t.from ? ` (from ${t.from})` : ""}`).join("; ")}.
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center", flexWrap: "wrap" }}>
        <Button size="sm" disabled={busy} onClick={() => void keep()}>{adjusted ? "Keep, with my changes" : "Keep it"}</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void discard()}>Discard</Button>
        {adjusted && <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Kept as proposed, then your changes as the next version.</span>}
        <span className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--t3)" }}>Words never write: kept whole or discarded whole, against the version on screen.</span>
      </div>
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

  const draft = async () => {
    setDrafting(true); setResult(null); setProposal(null);
    try {
      const out = await draftCockpit(connectionId, area, schema);
      setResult(out);
      if (out.staged) setProposal(await getProposalById(out.proposal_id));
    } catch (e) {
      toast.error("The draft did not go through", { description: (e as Error).message.slice(0, 160) });
    } finally { setDrafting(false); }
  };

  return (
    <div data-testid="cockpit-new" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Input aria-label="What this cockpit is for" placeholder="What is it for? Returns, pricing, marketing…"
          value={area} onChange={e => setArea(e.target.value)} disabled={drafting || !!proposal}
          onKeyDown={e => { if (e.key === "Enter" && area.trim() && !drafting) void draft(); }}
          style={{ maxWidth: 420, flex: 1 }} />
        <Button size="sm" disabled={!area.trim() || drafting || !!proposal} onClick={() => void draft()}>
          {drafting ? "Drafting…" : "Draft it"}
        </Button>
        <Button size="sm" variant="ghost" disabled={drafting} onClick={onClose}>Close</Button>
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

      {result?.staged && proposal && (
        <DraftReview connectionId={connectionId} cockpitId={result.cockpit_id} result={result} proposal={proposal}
          onKept={onKept} onDiscarded={() => { setResult(null); setProposal(null); }} />
      )}
    </div>
  );
}

/** A change to the cockpit that stands, asked for in words (the canvas, §2.5): one short model
 *  run, bound to this cockpit; what comes back is a proposal to keep or not. Writing a note or
 *  choosing an image is never asked of it — those doors are by hand. */
function AskChange({ connectionId, cockpitId, schema, held, onKept }: {
  connectionId: string; cockpitId: string; schema?: string; held: Map<string, CardLine>; onKept: () => void;
}) {
  const [words, setWords] = useState("");
  const [asking, setAsking] = useState(false);
  const [result, setResult] = useState<CockpitDrafted | null>(null);
  const [proposal, setProposal] = useState<StagedProposal | null>(null);

  const ask = async () => {
    if (!words.trim()) return;
    setAsking(true); setResult(null); setProposal(null);
    try {
      const out = await askCockpit(connectionId, cockpitId, words, schema);
      setResult(out);
      if (out.staged) setProposal(await getProposalById(out.proposal_id));
    } catch (e) {
      toast.error("The change could not be drafted", { description: (e as Error).message.slice(0, 160) });
    } finally { setAsking(false); }
  };

  return (
    <div data-testid="cockpit-ask" style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Input aria-label="Ask for a change in words" placeholder="In words: “add the finding about returns by category”, “make the net sales card bigger”, “share this with the sales team”"
          value={words} onChange={e => setWords(e.target.value)} disabled={asking || !!proposal}
          onKeyDown={e => { if (e.key === "Enter" && words.trim() && !asking) void ask(); }}
          style={{ flex: 1, minWidth: 280 }} />
        <Button size="sm" variant="secondary" disabled={!words.trim() || asking || !!proposal} onClick={() => void ask()}>
          {asking ? "Drafting…" : "Propose"}
        </Button>
      </div>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 4 }}>
        {asking ? "A model is reading the cockpit and drafting the change. This can take a minute."
          : "Asks a model once; it may arrange, add a finding or share — never write a note or pick an image. Nothing changes until you keep it."}
      </div>
      {result && !result.staged && (
        <div style={{ marginTop: 10 }}>
          <Refusal kind="Not proposed" claim="No change was drafted for this."
            detail={<ul data-testid="cockpit-not-proposed" style={{ margin: 0, paddingLeft: 18 }}>
              {result.sentences.map((s, i) => <li key={`${i}-${s.slice(0, 24)}`}>{s}</li>)}
            </ul>} />
        </div>
      )}
      {result?.staged && proposal && (
        <DraftReview connectionId={connectionId} cockpitId={cockpitId} result={result} proposal={proposal} held={held}
          onKept={() => { setResult(null); setProposal(null); setWords(""); onKept(); }}
          onDiscarded={() => { setResult(null); setProposal(null); }} />
      )}
    </div>
  );
}

/** Who a cockpit is published to (the canvas, B5): the groups the person belongs to and the roles
 *  they may publish to, picked by hand; publishing and unpublishing are each a version. */
function PublishPanel({ connectionId, cockpitId, publishedTo, busy, onDone, onClose }: {
  connectionId: string; cockpitId: string; publishedTo: CockpitAudience[]; busy: boolean;
  onDone: (act: () => Promise<CockpitKept>, said: (k: CockpitKept) => string) => Promise<boolean>; onClose: () => void;
}) {
  const [audiences, setAudiences] = useState<{ groups: CockpitAudience[]; roles: CockpitAudience[] } | null>(null);
  const [problem, setProblem] = useState("");
  const [chosen, setChosen] = useState<CockpitAudience[]>(publishedTo);
  useEffect(() => {
    let alive = true;
    cockpitAudiences(connectionId).then(a => { if (alive) setAudiences(a); }).catch(e => { if (alive) setProblem((e as Error).message); });
    return () => { alive = false; };
  }, [connectionId]);
  const same = JSON.stringify(chosen.map(c => `${c.kind}:${c.id}`).sort()) === JSON.stringify(publishedTo.map(c => `${c.kind}:${c.id}`).sort());
  const toggle = (a: CockpitAudience, on: boolean) =>
    setChosen(cs => (on ? [...cs.filter(c => !(c.kind === a.kind && c.id === a.id)), a] : cs.filter(c => !(c.kind === a.kind && c.id === a.id))));
  const all = [...(audiences?.groups ?? []), ...(audiences?.roles ?? [])];
  return (
    <div data-testid="cockpit-publish" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16, display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="aug-label">Publish to</div>
      {problem ? <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>Who you may publish to could not be read: {problem}</div>
        : !audiences ? <Loading what="who you may publish to" style={{ padding: "4px 0" }} />
        : !all.length ? <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>You belong to no group and hold no role a cockpit can be published to.</div>
        : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 4 }}>
            {all.map(a => (
              <li key={`${a.kind}:${a.id}`} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Checkbox checked={chosen.some(c => c.kind === a.kind && c.id === a.id)} disabled={busy}
                  aria-label={`Publish to ${a.name}`} onChange={e => toggle(a, e.target.checked)} />
                <span>{a.name}</span>
                <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{a.kind === "group" ? "a group you belong to" : "a role you hold"}</span>
              </li>
            ))}
          </ul>
        )}
      <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
        Readers see it under “Shared with you”, read-only, under your name, for the period they choose. A card they may not read stands and says so.
        Your notes and images travel marked as yours. Publishing is a version; so is unpublishing.
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button size="sm" disabled={busy || same || !chosen.length} data-testid="cockpit-publish-go"
          onClick={() => void onDone(() => publishCockpit(connectionId, cockpitId, chosen), k => `Published, as version ${k.version}.`).then(ok => { if (ok) onClose(); })}>
          Publish
        </Button>
        {publishedTo.length > 0 && (
          <Button size="sm" variant="secondary" disabled={busy}
            onClick={() => void onDone(() => unpublishCockpit(connectionId, cockpitId), k => `Unpublished, as version ${k.version}.`).then(ok => { if (ok) onClose(); })}>
            Unpublish
          </Button>
        )}
        <Button size="sm" variant="ghost" disabled={busy} onClick={onClose}>Close</Button>
      </div>
    </div>
  );
}

/** A cockpit someone else published to a group the person is in or a role they hold: read as it
 *  stands, for the reader's own period, with no door that changes it — and a door to start a
 *  cockpit of their own from it. */
function SharedCockpitView({ connectionId, schema, owner, cockpitId, range, chosenRange, onRange, rangesOn, onStarted }: {
  connectionId: string; schema?: string; owner: string; cockpitId: string;
  range: BriefingRange | null; chosenRange: RangeChoice; onRange: (c: RangeChoice) => void; rangesOn: boolean | null;
  onStarted: (cockpitId: string) => void;
}) {
  const [data, setData] = useState<SharedCockpit | null>(null);
  const [cards, setCards] = useState<CardState[]>([]);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const rangeKey = JSON.stringify(range ?? null);
  useEffect(() => {
    let cancelled = false;
    setProblem("");
    (async () => {
      try {
        const read = await getSharedCockpit(connectionId, owner, cockpitId, range);
        const placed = new Set(read.cockpit.spec ? cardsPlaced(read.cockpit.spec) : []);
        const runs = await Promise.all(read.cards.filter(c => placed.has(c.id)).map(async (card): Promise<CardState> => {
          try { return { card, run: await runDashboardCard(card.id, range, { compare: true }) }; }
          catch { return { card, failed: true }; }
        }));
        if (cancelled) return;
        setData(read); setCards(runs);
      } catch (e) {
        if (!cancelled) setProblem((e as Error).message || "The cockpit could not be read.");
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }, [connectionId, owner, cockpitId, rangeKey]);
  const doors = useMemo<CockpitDoors>(() => ({
    onRefresh: async (id: string) => {
      try { const run = await runDashboardCard(id, range, { compare: true }); setCards(cs => cs.map(c => (c.card.id === id ? { ...c, run, failed: false } : c))); }
      catch { setCards(cs => cs.map(c => (c.card.id === id ? { ...c, failed: true } : c))); }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }), [rangeKey]);
  const host = useMemo(() => hostStateOf(data?.range.status ?? "standing", cards), [data?.range.status, cards]);
  const images = useMemo<Record<string, ImageStamp>>(() => Object.fromEntries(
    Object.entries(data?.images ?? {}).map(([id, s]) => [id, { ...s, url: cockpitImageUrl(connectionId, id) }])), [data?.images, connectionId]);
  const start = async () => {
    setBusy(true);
    try {
      const out = await copySharedCockpit(connectionId, owner, cockpitId);
      toast.success(`“${out.title ?? "The cockpit"}” is yours now, as version ${out.version}. The published one is unchanged.`);
      if (out.cockpit_id) onStarted(out.cockpit_id);
    } catch (e) {
      const why = e instanceof CockpitRefused ? e.outcome.sentences.join(" ") : (e as Error).message;
      toast.error("No cockpit was started", { description: why.slice(0, 200) });
    } finally { setBusy(false); }
  };
  if (problem) return <ErrorState kind="Not read" what="This shared cockpit could not be read." means={problem} />;
  if (!data) return <div className="aug-fs-sm" data-testid="cockpit-loading" style={{ color: "var(--t3)" }}>Reading the shared cockpit…</div>;
  return (
    <div data-testid="cockpit-shared" data-owner={owner} data-cockpit={cockpitId}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
        {data.ranges_on && rangesOn && (
          <PeriodPicker value={chosenRange} onChange={onRange} showing={data.range.status === "standing" ? null : data.range} />
        )}
        <span className="aug-fs-sm" data-testid="cockpit-shared-by" style={{ color: "var(--t2)" }}>
          Published by {personName(data.published_by)} to {data.published_to.map(t => t.name).join(", ")} · version {data.cockpit.version} · read-only
        </span>
        <Button size="xs" variant="secondary" disabled={busy} style={{ marginLeft: "auto" }} onClick={() => void start()}>
          Start my cockpit from this
        </Button>
      </div>
      <ComposedCockpit spec={data.cockpit.spec} cards={cards} host={host} doors={doors} sym={data.currency_symbol || "$"}
        images={images} range={range} schema={schema} connectionId={connectionId} />
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
  // The two doors by hand only: a note's words and an image are the person's, never a model's.
  const [noting, setNoting] = useState(false);
  const [imaging, setImaging] = useState(false);
  // Any recorded finding of the connection, as a card (B3); who the cockpit is published to (B5).
  const [picking, setPicking] = useState(false);
  // Arc OC-4 — a piece bound to the ontology, placed by hand, while `ontology.cockpit_pieces` is on.
  const [piecesOn, setPiecesOn] = useState(false);
  const [placing, setPlacing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [shared, setShared] = useState<SharedCockpitListed[]>([]);
  const [tick, setTick] = useState(0);
  // The cockpit is being read for a period while the cards on screen are still the period before.
  const [reading, setReading] = useState(false);
  const known = useRef<Set<string>>(new Set());
  const adopt = useRef(false);

  const rangeKey = JSON.stringify(range ?? null);
  const reload = useCallback(() => setTick(t => t + 1), []);

  useEffect(() => {
    let alive = true;
    getSystemFlags().then(f => {
      if (alive) { setRangesOn(!!f["briefing.ranges"]?.value); setPiecesOn(!!f["ontology.cockpit_pieces"]?.value); }
    }).catch(() => { if (alive) { setRangesOn(false); setPiecesOn(false); } });
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
        return live.some(c => c.cockpit_id === want) || want.startsWith("shared:") ? want : METRICS_COCKPIT;
      });
    }).catch(e => { if (!cancelled) setProblem((e as Error).message); });
    // What others published to a group the person is in or a role they hold (B5). Nothing to
    // show is nothing to say: the strip simply has no such heading.
    listSharedCockpits(connectionId).then(s => { if (!cancelled) setShared(s); }).catch(() => { if (!cancelled) setShared([]); });
    return () => { cancelled = true; };
  }, [connectionId, tick]);

  // The chosen cockpit, read for the page's range, each card it places run through the guards.
  useEffect(() => {
    if (!chosen || chosen === METRICS_COCKPIT || chosen.startsWith("shared:") || list === "off") { setData(null); return; }
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

  const choose = (id: string) => {
    setChosen(id); remember(connectionId, id); setArranging(null); setShowHistory(false); setRefusal(null); setProblem("");
    setPicking(false); setPublishing(false); setNoting(false); setImaging(false); setComposing(false);
  };

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

  // One edit of the spec by hand, kept as the next version: what every door on a tile comes to.
  const edit = useCallback((change: (s: CockpitSpec) => CockpitSpec, note: string, said: string) => {
    if (!data?.cockpit.spec) return;
    void write(() => keepCockpit(connectionId, data.cockpit_id, change(data.cockpit.spec as CockpitSpec), note), () => said);
  }, [connectionId, data, write]);

  const doors = useMemo<CockpitDoors>(() => ({
    onRemove: takeOffOne, onRefresh: refreshOne, onOpenSource, onEvidence,
    onTakeOff: (key: string) => edit(s => takeOff(s, key), "taken off by hand", "Taken off. The version before keeps it."),
    onResize: (key: string, size: Size) => edit(s => resize(s, key, size), `resized to ${size} by hand`,
      "Resized. The same thing, with more or less room; nothing was re-measured."),
    onEditNote: (key: string, text: string) => edit(s => editNote(s, key, text), "a note's words changed by hand", "Kept, and stamped with your name and today."),
    onRecaption: (key: string, caption: string) => edit(s => recaption(s, key, caption), "an image's caption changed by hand", "Kept."),
    onPlaceTable: piecesOn ? (entity: string, segment: string) => edit(s => placePiece(s, "ObjectTable", { entity, segment, size: "wide" }).spec,
      "an objects table placed from a process board", "Placed: the objects still waiting and already past the promise.") : undefined,
  }), [takeOffOne, refreshOne, onOpenSource, onEvidence, edit, piecesOn]);
  const host = useMemo(() => hostStateOf(data?.range.status ?? "standing", cards), [data?.range.status, cards]);
  // Where each image's bytes are read from: the API, with this reader's own access.
  const images = useMemo<Record<string, ImageStamp>>(() => Object.fromEntries(
    Object.entries(data?.images ?? {}).map(([id, s]) => [id, { ...s, url: cockpitImageUrl(connectionId, id) }])),
  [data?.images, connectionId]);

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
  const notPlaced = arranging ? (data?.cards ?? []).filter(c => !cardsPlaced(arranging).includes(c.id)) : [];
  // A duplicate is not offered back — superseded, from a deprecated metric, or a copy — and the
  // tray says how many it left out and why, so nothing reads as lost.
  const unplaced = notPlaced.filter(c => !c.not_offered);
  const withheld = notPlaced.filter(c => c.not_offered);

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
          // Published to a group the person is in or a role they hold: read-only, under the publisher's name.
          ...(shared.length ? [{ heading: <span className="aug-label" style={{ color: "var(--t3)" }}>Shared with you</span> }] : []),
          ...shared.map(s => ({ id: `shared:${s.owner}/${s.cockpit_id}`, label: `${s.title || s.cockpit_id} · ${person(s.published_by || s.owner)}` })),
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
      ) : chosen.startsWith("shared:") ? (
        <SharedCockpitView connectionId={connectionId} schema={schema}
          owner={chosen.slice("shared:".length, chosen.lastIndexOf("/"))} cockpitId={chosen.slice(chosen.lastIndexOf("/") + 1)}
          range={range} chosenRange={chosenRange} onRange={setChosenRange} rangesOn={rangesOn}
          onStarted={id => { choose(id); reload(); }} />
      ) : live.length === 0 ? noneYet : drawn && data ? (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 4 }}>
            {data.ranges_on && (
              <PeriodPicker value={chosenRange} onChange={setChosenRange} disabled={busy} reading={reading}
                showing={data.range.status === "standing" || reading ? null : data.range} />
            )}
            <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
              {!arranging && (
                <Button size="xs" variant="ghost" disabled={busy || composing} data-testid="cockpit-card-new"
                  onClick={() => { setComposing(true); setNoting(false); setImaging(false); }}>
                  <Icon name="plus" /> Card
                </Button>
              )}
              {!arranging && (
                <Button size="xs" variant="ghost" disabled={busy || noting} data-testid="cockpit-note-new"
                  title="Your own words on this cockpit. By hand only: a model never writes a note."
                  onClick={() => { setNoting(true); setComposing(false); setImaging(false); }}>
                  <Icon name="plus" /> Note
                </Button>
              )}
              {!arranging && (
                <Button size="xs" variant="ghost" disabled={busy || imaging} data-testid="cockpit-image-new"
                  title="An image of your own on this cockpit. By hand only: a model never chooses one."
                  onClick={() => { setImaging(true); setComposing(false); setNoting(false); setPicking(false); }}>
                  <Icon name="plus" /> Image
                </Button>
              )}
              {!arranging && (
                <Button size="xs" variant="ghost" disabled={busy || picking} data-testid="cockpit-finding-new"
                  title="Any finding the explorer has recorded on this connection, as a card: its query re-run through the guards."
                  onClick={() => { setPicking(true); setComposing(false); setNoting(false); setImaging(false); }}>
                  <Icon name="plus" /> Finding
                </Button>
              )}
              {!arranging && piecesOn && (
                <Button size="xs" variant="ghost" disabled={busy || placing} data-testid="cockpit-piece-new"
                  title="A process board, an objects table, an object detail or an action button — each reads what the ontology declares, by id."
                  onClick={() => { setPlacing(true); setComposing(false); setNoting(false); setImaging(false); setPicking(false); }}>
                  <Icon name="plus" /> From the ontology
                </Button>
              )}
              {!arranging && (
                <Button size="xs" variant={kept.published_to?.length ? "secondary" : "ghost"} disabled={busy} data-testid="cockpit-publish-open"
                  aria-expanded={publishing} title="Share this cockpit, as it stands, with a group you belong to or a role you hold."
                  onClick={() => setPublishing(p => !p)}>
                  <Icon name="send" /> {kept.published_to?.length ? `Published to ${kept.published_to.map(t => t.name).join(", ")}` : "Publish"}
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
              {withheld.length > 0 && (
                <div className="aug-fs-sm" data-testid="cockpit-tray-withheld" style={{ marginTop: 8, color: "var(--t3)" }}>
                  Not offered: {withheld.map(c => `${c.title} — ${c.not_offered}`).join("; ")}.
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
              {noting && (
                <NoteComposer busy={busy} onClose={() => setNoting(false)}
                  onPlace={text => { edit(s => placeNote(s, text), "a note written by hand", "Placed. Its author and date are stamped as it is kept."); setNoting(false); }} />
              )}
              {imaging && (
                <ImageComposer connectionId={connectionId} busy={busy} onClose={() => setImaging(false)}
                  onPlace={(objectId, caption) => { edit(s => placeImage(s, objectId, caption), "an image uploaded by hand", "Placed. The upload is stamped with your name and the date."); setImaging(false); }} />
              )}
              {placing && piecesOn && (
                <OntologyPieceComposer connectionId={connectionId} schema={schema} spec={kept.spec as CockpitSpec} busy={busy}
                  onClose={() => setPlacing(false)}
                  onPlace={(change, note, said) => { edit(change, note, said); setPlacing(false); }} />
              )}
              {picking && (
                <FindingPicker connectionId={connectionId} schema={schema} busy={busy}
                  placed={new Set(cards.map(c => findingOfCard(c.card)).filter(Boolean))}
                  onPlaced={() => { adopt.current = true; reload(); }} onClose={() => setPicking(false)} />
              )}
              {publishing && (
                <PublishPanel connectionId={connectionId} cockpitId={data.cockpit_id} busy={busy}
                  publishedTo={(kept.published_to ?? []) as CockpitAudience[]}
                  onDone={write} onClose={() => setPublishing(false)} />
              )}
              <AskChange connectionId={connectionId} cockpitId={data.cockpit_id} schema={schema} held={lines}
                onKept={() => { setPublishing(false); reload(); }} />
              {reading && <Loading what={`the cards for ${choiceName(chosenRange)}`} style={{ padding: "12px 0" }} />}
              {!reading && data.range.edge_note && (
                <div className="aug-fs-sm" data-testid="cockpit-edge-note" style={{ color: "var(--t2)", margin: "4px 0 8px" }}>{data.range.edge_note}</div>
              )}
              <div aria-busy={reading || undefined}
                style={{ opacity: reading ? 0.45 : 1, transition: "opacity 120ms ease-out", pointerEvents: reading ? "none" : undefined }}>
                <ComposedCockpit spec={kept.spec} cards={cards} host={host} doors={doors} sym={data.currency_symbol || "$"}
                  images={images} range={range} schema={schema} connectionId={connectionId} />
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
