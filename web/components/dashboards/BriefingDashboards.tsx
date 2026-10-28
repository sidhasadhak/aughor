"use client";

/**
 * BriefingDashboards — a person's dashboards, the Dashboards tab beside the Briefing (Arc CT, CT-7 to
 * CT-10; ROADMAP §3.50).
 *
 * The Briefing is the connection's: what the platform found for a period. A dashboard is a
 * person's own: the standing set of cards they keep watching for an area — returns, pricing,
 * marketing — and they may keep as many as they like (§6 item 36(i)–(l)). The user: "The
 * dashboard should be a tab inside the Briefing.. as simple as that" — so it is a tab of the
 * Intelligence workspace, next to the Briefing, and the Briefing's page no longer draws one.
 *
 * Opening it loads no Briefing and asks no model, and it needs no exploration: a dashboard is made
 * of cards, not of findings.
 *
 * What it does, and what each costs:
 *   - draws the chosen dashboard for a period of its own — the latest month when ranges are on,
 *     "As written" otherwise — each figure against the period it is compared with: no model;
 *   - arranges it by hand, each save a version: no model;
 *   - starts "My dashboard" from the cards pinned before dashboards had names: no model;
 *   - moves a dashboard that lived in a Data Canvas here: no model;
 *   - drafts a new dashboard for an area the person names: ONE short model run, said so on the
 *     button. The draft is shown as its outline, can be adjusted, and is kept or discarded.
 *
 * A dashboard opens to be read (Arc AP-1) — the strip, then one bar: its period, its
 * history and Edit — and Edit opens the builder (`DashboardBuilder`): the dashboard between its layout and the setup of
 * what is chosen, the rail folded to its icons until Done. Every change there is drawn at once and kept as one version
 * a moment after a burst of them, with undo and redo. No model; a change asked in words is the one exception, as here.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { NewCardComposer } from "@/components/brief/NewCardComposer";
import type { RangeChoice } from "@/components/brief/BriefRange";
import type { CardState } from "@/components/brief/PinnedCardBody";
import { DashboardArrange, type CardLine } from "@/components/dashboards/DashboardArrange";
import { DashboardBuilder, EditBar } from "@/components/dashboards/DashboardBuilder";
import { ComposedDashboard, type DashboardDoors, type ReadState } from "@/components/dashboards/ComposedDashboard";
import { FindingPicker } from "@/components/dashboards/FindingPicker";
import { ObjectDashboardStarter } from "@/components/dashboards/ObjectDashboardStarter";
import { PackTemplatePicker } from "@/components/dashboards/PackTemplatePicker";
import { OntologyPieceComposer } from "@/components/dashboards/OntologyPieceComposer";
import { PiecePicker } from "@/components/dashboards/PiecePicker";
import { QuerySetup } from "@/components/dashboards/QuerySetup";
import { PinStrip } from "@/components/dashboards/PinStrip";
import { METRICS_DASHBOARD, MetricsDashboard } from "@/components/dashboards/MetricsDashboard";
import { QuestionComposer } from "@/components/dashboards/QuestionComposer";
import { PeriodPicker, choiceName } from "@/components/dashboards/PeriodPicker";
import { person as personName, type ImageStamp } from "@/components/dashboards/StaticTile";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Checkbox } from "@/components/ui/checkbox";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { TabStrip } from "@/components/ui/tab-strip";
import { ErrorState, Loading, Refusal } from "@/components/ui/states";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import {
  DashboardRefused, acceptProposal, askDashboard, dashboardAudiences, dashboardImageUrl, copySharedDashboard, draftDashboard, findingOfCard,
  getDeclaredActions,
  getDashboard, getGroups, getProposalById, getSharedDashboard, getSuggestedShapes, getSystemFlags, keepDashboard, listDashboards, listSharedDashboards, moveCanvasDashboard,
  publishDashboard, rejectProposal, restoreDashboard, retireDashboard, runCard, startMyDashboard, unpublishDashboard,
  uploadDashboardImage,
  type BriefingRange, type DashboardAudience, type DashboardDrafted, type DashboardKept, type DashboardList, type DashboardVersion,
  type PersonDashboard, type ShapeName, type SharedDashboard, type SharedDashboardListed, type StagedProposal,
} from "@/lib/api";
import { appWords } from "@/lib/dashboards/appVersion";
import { MAX_CAPTION, MAX_NOTE, type Layout } from "@/lib/dashboards/catalog";
import {
  cardsPlaced, editNote, layOut, placeCard, placeImage, placeNote, placePiece, placeQuestion, recaption, regrid, sectionsOf, setFilterWidth, swapCard, takeOff, takeOffCard,
  type DashboardSpec,
  type Box,
} from "@/lib/dashboards/edit";
import { hostStateOf } from "@/lib/dashboards/hostStatus";
import { SHAPES } from "@/lib/dashboards/shapes";
import { emptyDashboardSpec, overdueSegmentOf, processDashboardHolds, processDashboardSpec, startDashboard } from "@/lib/dashboards/start";
import { valuesRead } from "@/lib/dashboards/values";
import { formatDateTime } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { foldNavFor } from "@/lib/navCollapse";
import { cachedObjectCatalog } from "@/lib/objects";
import { getProcesses, type ProcessDetail } from "@/lib/objectTypes";

/** The name the Briefing gives when it keeps something for a person. The server writes the
 *  signed-in person's own name where there is one. */
const ACTOR = "briefing";

function person(name: string): string {
  return name.replace(/^user:/, "") || "someone";
}

function changed(c: DashboardVersion["changes"]): string {
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

function remember(connectionId: string, dashboardId: string) {
  try { localStorage.setItem(`aughor:cockpit:${connectionId}`, dashboardId); } catch { /* private mode: the choice just won't persist */ }
}

function Refused({ outcome }: { outcome: DashboardKept }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <Refusal
        kind={outcome.status === "not_checked" ? "Not checked · nothing was kept" : "Refused · nothing was kept"}
        claim="The dashboard was not changed."
        detail={
          <ul data-testid="dashboard-write-refusal" style={{ margin: 0, paddingLeft: 18 }}>
            {outcome.sentences.map((s, i) => <li key={`${i}-${s.slice(0, 24)}`}>{s}</li>)}
          </ul>
        }
      />
    </div>
  );
}

/** A note, typed by the person — the one element of a dashboard a model never writes (the canvas,
 *  2026-10-08). Its author and date are the server's to stamp when it is kept. */
function NoteComposer({ busy, onPlace, onClose }: { busy: boolean; onPlace: (text: string) => void; onClose: () => void }) {
  const [text, setText] = useState("");
  return (
    <div data-testid="dashboard-note-composer" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16, display: "flex", flexDirection: "column", gap: 8 }}>
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
      const stamp = await uploadDashboardImage(connectionId, file);
      onPlace(stamp.object, caption.trim() || file.name);
    } catch (e) {
      setRefused((e as Error).message);
    } finally { setUploading(false); }
  };
  return (
    <div data-testid="dashboard-image-composer" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16, display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
        PNG, JPEG, GIF, WebP or SVG, up to 5 MB, into this connection's dashboard volume. It shows who uploaded it and when,
        and no period or comparison: a static thing says it is static.
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input type="file" aria-label="The image file" accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
          disabled={busy || uploading} onChange={e => { setFile(e.target.files?.[0] ?? null); setRefused(""); }} />
        <Input aria-label="Caption" placeholder="Caption" value={caption} maxLength={MAX_CAPTION} disabled={busy || uploading}
          onChange={e => setCaption(e.target.value)} style={{ maxWidth: 320, flex: 1 }} />
      </div>
      {refused && <div className="aug-fs-sm" data-testid="dashboard-image-refused" style={{ color: "var(--red4)" }}>{refused}</div>}
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
  const drafted = proposal?.params?.spec as DashboardSpec | undefined;
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
function DraftReview({ connectionId, dashboardId, result, proposal, held, onKept, onDiscarded }: {
  connectionId: string;
  /** The dashboard the proposal is for: a new one's id from the draft, or the one that stands. */
  dashboardId: string;
  result: DashboardDrafted;
  proposal: StagedProposal;
  held?: Map<string, CardLine>;
  onKept: (dashboardId: string) => void;
  onDiscarded: () => void;
}) {
  const proposed = proposal.params?.spec as DashboardSpec | undefined;
  const [spec, setSpec] = useState<DashboardSpec | null>(proposed ? structuredClone(proposed) : null);
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
      if (adjusted && spec) await keepDashboard(connectionId, dashboardId, spec, "adjusted before keeping");
      toast.success(publish ? "Published." : adjusted ? "Kept, with your changes." : "Kept.");
      onKept(dashboardId);
    } catch (e) {
      const why = e instanceof DashboardRefused ? e.outcome.sentences.join(" ") : (e as Error).message;
      toast.error("It was not kept", { description: why.slice(0, 200) });
    } finally { setBusy(false); }
  };

  const discard = async () => {
    setBusy(true);
    try { await rejectProposal(proposal.id, ACTOR); } finally { setBusy(false); }
    onDiscarded();
  };

  return (
    <div data-testid="dashboard-draft" style={{ marginTop: 14 }}>
      <div className="aug-fs-sm" style={{ color: "var(--t2)", marginBottom: 8 }}>{result.summary}</div>
      {proposal.reasoning && (
        <div className="aug-fs-sm" style={{ color: "var(--t3)", marginBottom: 8 }}>Why it is arranged this way: {proposal.reasoning}</div>
      )}
      {publish ? (
        <div className="aug-fs-sm" data-testid="dashboard-publish-proposal" style={{ color: "var(--t1)" }}>
          Publish this dashboard as an App, as it stands, to {(detail.to ?? []).join(", ")} — read-only for its readers, under your name.
          Your notes and images travel marked as yours.
        </div>
      ) : spec ? (
        <DashboardArrange spec={spec} lines={lines} onChange={setSpec} disabled={busy} />
      ) : null}
      {!!detail.taken_off?.length && (
        <div className="aug-fs-sm" data-testid="dashboard-taken-off" style={{ color: "var(--t2)", marginTop: 8 }}>
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

/** A new dashboard, three ways (2026-10-09): empty — its name and a first note in the person's words, since a dashboard
 *  holding nothing is refused; for a declared process — its board, its open-and-overdue objects and one beside them;
 *  or drafted by a model for an area, the one way here that asks one. The walk-through found only the last. */
function NewDashboard({ connectionId, schema, sym, onKept, onClose }: {
  connectionId: string; schema?: string; onKept: (dashboardId: string) => void; onClose: () => void;
  sym: string;
}) {
  const [way, setWay] = useState<"empty" | "object" | "pack" | "process" | "draft">("empty");
  const [types, setTypes] = useState<{ object_type: string; display_name: string }[] | null>(null);
  const [entity, setEntity] = useState("");
  // Arc AP-5 — what each object suggests a dashboard be
  const [suggested, setSuggested] = useState<{ entity: string; name: string; shape: ShapeName; short: string }[] | null>(null);
  useEffect(() => {
    if (way !== "object" || types) return;
    let live = true;
    cachedObjectCatalog(connectionId)
      .then(c => { if (live) setTypes(c?.object_types ?? []); })
      .catch(() => { if (live) setTypes([]); });
    return () => { live = false; };
  }, [way, types, connectionId]);
  // read on its own: the catalog answering first re-runs the read above, and must not drop these on the way
  useEffect(() => {
    if (way !== "object" || suggested) return;
    let live = true;
    getSuggestedShapes(connectionId, schema).then(s => { if (live) setSuggested(s); }).catch(() => { /* none suggested: a choice is still made by hand */ });
    return () => { live = false; };
  }, [way, suggested, connectionId, schema]);
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [processes, setProcesses] = useState<ProcessDetail[] | null>(null);
  const [processId, setProcessId] = useState("");
  const [starting, setStarting] = useState(false);
  useEffect(() => {
    if (way !== "process" || processes) return;
    let live = true;
    getProcesses(connectionId, schema).then(r => { if (live) setProcesses(r.processes); }).catch(() => { if (live) setProcesses([]); });
    return () => { live = false; };
  }, [way, processes, connectionId, schema]);
  const process = processes?.find(p => p.id === processId);
  const start = async (title: string, spec: unknown, note: string) => {
    setStarting(true);
    try {
      onKept(await startDashboard(connectionId, title, spec, note));
    } catch (e) {
      toast.error("The dashboard was not made", { description: (e as Error).message.slice(0, 200) });
    } finally { setStarting(false); }
  };
  const [area, setArea] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [result, setResult] = useState<DashboardDrafted | null>(null);
  const [proposal, setProposal] = useState<StagedProposal | null>(null);

  const draft = async () => {
    setDrafting(true); setResult(null); setProposal(null);
    try {
      const out = await draftDashboard(connectionId, area, schema);
      setResult(out);
      if (out.staged) setProposal(await getProposalById(out.proposal_id));
    } catch (e) {
      toast.error("The draft did not go through", { description: (e as Error).message.slice(0, 160) });
    } finally { setDrafting(false); }
  };

  return (
    <div data-testid="dashboard-new" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
        {([["empty", "Start empty"], ["object", "From an object"], ["pack", "From a pack template"], ["process", "For a process"],
           ["draft", "Draft it with a model"]] as const).map(([w, label]) => (
          <Button key={w} size="xs" variant={way === w ? "secondary" : "ghost"} aria-pressed={way === w}
            data-testid={`dashboard-new-${w}`} disabled={drafting || starting || !!proposal} onClick={() => setWay(w)}>{label}</Button>
        ))}
        <Button size="xs" variant="ghost" style={{ marginLeft: "auto" }} disabled={drafting || starting} onClick={onClose}>Close</Button>
      </div>

      {way === "empty" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, maxWidth: 560 }}>
          <Input aria-label="The dashboard's name" placeholder="Carrier performance" value={name} disabled={starting}
            onChange={e => setName(e.target.value)} />
          <Textarea aria-label="What this dashboard is for — its first note" rows={2} value={purpose} disabled={starting}
            placeholder="Which carriers miss pickups, and what we do about it." onChange={e => setPurpose(e.target.value)} />
          <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Button size="sm" data-testid="dashboard-start-empty" disabled={!name.trim() || !purpose.trim() || starting}
              onClick={() => void start(name, emptyDashboardSpec(name, purpose), "Started empty")}>
              {starting ? "Starting…" : "Start it"}
            </Button>
            <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
              {!name.trim() ? "Name it." : !purpose.trim() ? "Say what it is for — it becomes the dashboard's first note."
                : "Then add cards, findings and pieces from the toolbar. No model is asked."}
            </span>
          </span>
        </div>
      )}

      {way === "object" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 760 }}>
          {types === null ? <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Reading the objects…</span>
            : types.length === 0 ? (
              <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>No object is built for this connection yet.</span>
            ) : (
              <SelectField value={entity} aria-label="The object" onChange={e => setEntity(e.target.value)} style={{ maxWidth: 320 }}>
                <option value="">Choose an object…</option>
                {types.map(t => <option key={t.object_type} value={t.object_type}>{t.display_name || t.object_type}</option>)}
              </SelectField>
            )}
          {!entity && suggested && suggested.length > 0 && (
            <div data-testid="dashboard-new-suggested">
              <div className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em", margin: "2px 0 6px" }}>What each object suggests</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 6 }}>
                {withUniqueKeys(suggested, x => x.entity).map(([k, x]) => (
                  <Button key={k} variant="outline" data-testid="dashboard-new-suggestion" data-shape={x.shape} onClick={() => setEntity(x.entity)}
                    style={{ height: "auto", justifyContent: "flex-start", textAlign: "left", whiteSpace: "normal", padding: "8px 10px" }}>
                    <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                      <span style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                        <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 500 }}>{x.name}</span>
                        <span className="aug-fs-xs" style={{ color: "var(--accent-11)" }}>{SHAPES[x.shape].label}</span>
                      </span>
                      <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{x.short}</span>
                    </span>
                  </Button>
                ))}
              </div>
            </div>
          )}
          {entity && (
            <ObjectDashboardStarter connectionId={connectionId} schema={schema} entity={entity} sym={sym}
              onKept={onKept} onCancel={() => setEntity("")} />
          )}
        </div>
      )}

      {way === "pack" && (
        <PackTemplatePicker connectionId={connectionId} schema={schema} disabled={!!proposal}
          onDrafted={async out => {
            setResult(out); setProposal(null);
            if (out.staged) setProposal(await getProposalById(out.proposal_id));
          }} />
      )}

      {way === "process" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, maxWidth: 560 }}>
          {processes === null ? <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Reading the declared processes…</span>
            : processes.length === 0 ? (
              <span className="aug-fs-sm" style={{ color: "var(--t3)" }} data-testid="dashboard-new-no-process">
                No process is declared on this connection yet. Design one in the Ontology, with New process.
              </span>
            ) : (
              <>
                <SelectField value={processId} aria-label="The process" disabled={starting} onChange={e => setProcessId(e.target.value)}>
                  <option value="">Choose a process…</option>
                  {processes.map(p => <option key={p.id} value={p.id}>{p.display_name} · {p.entity}</option>)}
                </SelectField>
                <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <Button size="sm" data-testid="dashboard-start-process" disabled={!process || starting}
                    onClick={() => process && void start(process.display_name,
                      processDashboardSpec(process.display_name, process.id, process.entity_id, overdueSegmentOf(process)),
                      `Started from the process ${process.display_name}`)}>
                    {starting ? "Starting…" : "Start it"}
                  </Button>
                  <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
                    {!process ? "Choose the process it is for." : processDashboardHolds(process)}
                  </span>
                </span>
              </>
            )}
        </div>
      )}

      {way === "draft" && (<>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Input aria-label="What this dashboard is for" placeholder="What is it for? Returns, pricing, marketing…"
          value={area} onChange={e => setArea(e.target.value)} disabled={drafting || !!proposal}
          onKeyDown={e => { if (e.key === "Enter" && area.trim() && !drafting) void draft(); }}
          style={{ maxWidth: 420, flex: 1 }} />
        <Button size="sm" disabled={!area.trim() || drafting || !!proposal} onClick={() => void draft()}>
          {drafting ? "Drafting…" : "Draft it"}
        </Button>
      </div>
      <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 6 }}>
        {drafting
          ? "A model is drafting it from the connection's approved metrics, trusted queries and findings. This can take a minute."
          : "Drafting asks a model once. Nothing is kept until you keep it."}
      </div>
      </>)}

      {result && !result.staged && (
        <div style={{ marginTop: 12 }}>
          <Refusal kind="Not drafted" claim="No dashboard was drafted for this."
            detail={<ul data-testid="dashboard-not-drafted" style={{ margin: 0, paddingLeft: 18 }}>
              {result.sentences.map((s, i) => <li key={`${i}-${s.slice(0, 24)}`}>{s}</li>)}
            </ul>} />
        </div>
      )}

      {result?.staged && proposal && (
        <DraftReview connectionId={connectionId} dashboardId={result.cockpit_id} result={result} proposal={proposal}
          onKept={onKept} onDiscarded={() => { setResult(null); setProposal(null); }} />
      )}
    </div>
  );
}

/** A change to the dashboard that stands, asked for in words (the canvas, §2.5): one short model
 *  run, bound to this dashboard; what comes back is a proposal to keep or not. Writing a note or
 *  choosing an image is never asked of it — those doors are by hand. */
function AskChange({ connectionId, dashboardId, schema, held, onKept }: {
  connectionId: string; dashboardId: string; schema?: string; held: Map<string, CardLine>; onKept: () => void;
}) {
  const [words, setWords] = useState("");
  const [asking, setAsking] = useState(false);
  const [result, setResult] = useState<DashboardDrafted | null>(null);
  const [proposal, setProposal] = useState<StagedProposal | null>(null);

  const ask = async () => {
    if (!words.trim()) return;
    setAsking(true); setResult(null); setProposal(null);
    try {
      const out = await askDashboard(connectionId, dashboardId, words, schema);
      setResult(out);
      if (out.staged) setProposal(await getProposalById(out.proposal_id));
    } catch (e) {
      toast.error("The change could not be drafted", { description: (e as Error).message.slice(0, 160) });
    } finally { setAsking(false); }
  };

  return (
    <div data-testid="dashboard-ask" style={{ marginBottom: 12 }}>
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
        {asking ? "A model is reading the dashboard and drafting the change. This can take a minute."
          : "Asks a model once; it may arrange, add a finding or share — never write a note or pick an image. Nothing changes until you keep it."}
      </div>
      {result && !result.staged && (
        <div style={{ marginTop: 10 }}>
          <Refusal kind="Not proposed" claim="No change was drafted for this."
            detail={<ul data-testid="dashboard-not-proposed" style={{ margin: 0, paddingLeft: 18 }}>
              {result.sentences.map((s, i) => <li key={`${i}-${s.slice(0, 24)}`}>{s}</li>)}
            </ul>} />
        </div>
      )}
      {result?.staged && proposal && (
        <DraftReview connectionId={connectionId} dashboardId={dashboardId} result={result} proposal={proposal} held={held}
          onKept={() => { setResult(null); setProposal(null); setWords(""); onKept(); }}
          onDiscarded={() => { setResult(null); setProposal(null); }} />
      )}
    </div>
  );
}

/** Who a dashboard is published to (the canvas, B5): the groups the person belongs to and the roles
 *  they may publish to, picked by hand; publishing and unpublishing are each a version. With App versions
 *  on (ED-4) a change kept since the version its readers read is a draft, published to the same audience. */
function PublishPanel({ connectionId, dashboardId, publishedTo, draft = false, readersSee = null, busy, onDone, onClose }: {
  connectionId: string; dashboardId: string; publishedTo: DashboardAudience[]; busy: boolean;
  draft?: boolean; readersSee?: number | null;
  onDone: (act: () => Promise<DashboardKept>, said: (k: DashboardKept) => string) => Promise<boolean>; onClose: () => void;
}) {
  const [audiences, setAudiences] = useState<{ groups: DashboardAudience[]; roles: DashboardAudience[] } | null>(null);
  const [problem, setProblem] = useState("");
  const [chosen, setChosen] = useState<DashboardAudience[]>(publishedTo);
  useEffect(() => {
    let alive = true;
    dashboardAudiences(connectionId).then(a => { if (alive) setAudiences(a); }).catch(e => { if (alive) setProblem((e as Error).message); });
    return () => { alive = false; };
  }, [connectionId]);
  const same = JSON.stringify(chosen.map(c => `${c.kind}:${c.id}`).sort()) === JSON.stringify(publishedTo.map(c => `${c.kind}:${c.id}`).sort());
  const toggle = (a: DashboardAudience, on: boolean) =>
    setChosen(cs => (on ? [...cs.filter(c => !(c.kind === a.kind && c.id === a.id)), a] : cs.filter(c => !(c.kind === a.kind && c.id === a.id))));
  const all = [...(audiences?.groups ?? []), ...(audiences?.roles ?? [])];
  return (
    <div data-testid="dashboard-publish" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16, display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="aug-label">Publish as an App to</div>
      {problem ? <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>Who you may publish to could not be read: {problem}</div>
        : !audiences ? <Loading what="who you may publish to" style={{ padding: "4px 0" }} />
        : !all.length ? <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>You belong to no group and hold no role a dashboard can be published to.</div>
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
        Readers find it under “Apps shared with you”, read-only, under your name, for the period they choose. A card they may not read stands and says so.
        Your notes and images travel marked as yours. It reads the ontology release it was pinned to and says when one since changes what it reads.
        Publishing is a version; so is unpublishing.
      </div>
      {draft && readersSee !== null && (
        <div className="aug-fs-sm" data-testid="dashboard-publish-draft" style={{ color: "var(--t1)" }}>
          Its readers read version {readersSee}. What you kept since is a draft until you publish it.
        </div>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button size="sm" disabled={busy || (same && !draft) || !chosen.length} data-testid="dashboard-publish-go"
          onClick={() => void onDone(() => publishDashboard(connectionId, dashboardId, chosen), k => `Published as an App, as version ${k.version}.`).then(ok => { if (ok) onClose(); })}>
          {same && draft ? "Publish your changes" : "Publish the App"}
        </Button>
        {publishedTo.length > 0 && (
          <Button size="sm" variant="secondary" disabled={busy}
            onClick={() => void onDone(() => unpublishDashboard(connectionId, dashboardId), k => `Unpublished, as version ${k.version}.`).then(ok => { if (ok) onClose(); })}>
            Unpublish the App
          </Button>
        )}
        <Button size="sm" variant="ghost" disabled={busy} onClick={onClose}>Close</Button>
      </div>
    </div>
  );
}

/** A dashboard someone else published to a group the person is in or a role they hold: read as it
 *  stands, for the reader's own period, with no door that changes it — and a door to start a
 *  dashboard of their own from it. */
function SharedDashboardView({ connectionId, schema, owner, dashboardId, range, chosenRange, onRange, rangesOn, onStarted }: {
  connectionId: string; schema?: string; owner: string; dashboardId: string;
  range: BriefingRange | null; chosenRange: RangeChoice; onRange: (c: RangeChoice) => void; rangesOn: boolean | null;
  onStarted: (dashboardId: string) => void;
}) {
  const [data, setData] = useState<SharedDashboard | null>(null);
  const [cards, setCards] = useState<CardState[]>([]);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const rangeKey = JSON.stringify(range ?? null);
  useEffect(() => {
    let cancelled = false;
    setProblem("");
    (async () => {
      try {
        const read = await getSharedDashboard(connectionId, owner, dashboardId, range);
        const placed = new Set(read.cockpit.spec ? cardsPlaced(read.cockpit.spec) : []);
        const runs = await Promise.all(read.cards.filter(c => placed.has(c.id)).map(async (card): Promise<CardState> => {
          // Arc AP-8 — a query reading the dashboard's values is run by its own cell, with them
          if (valuesRead(card.sql).length) return { card };
          try { return { card, run: await runCard(card.id, range, { compare: true }) }; }
          catch { return { card, failed: true }; }
        }));
        if (cancelled) return;
        setData(read); setCards(runs);
      } catch (e) {
        if (!cancelled) setProblem((e as Error).message || "The dashboard could not be read.");
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }, [connectionId, owner, dashboardId, rangeKey]);
  const doors = useMemo<DashboardDoors>(() => ({
    onRefresh: async (id: string) => {
      try { const run = await runCard(id, range, { compare: true }); setCards(cs => cs.map(c => (c.card.id === id ? { ...c, run, failed: false } : c))); }
      catch { setCards(cs => cs.map(c => (c.card.id === id ? { ...c, failed: true } : c))); }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }), [rangeKey]);
  const host = useMemo(() => hostStateOf(data?.range.status ?? "standing", cards), [data?.range.status, cards]);
  const images = useMemo<Record<string, ImageStamp>>(() => Object.fromEntries(
    Object.entries(data?.images ?? {}).map(([id, s]) => [id, { ...s, url: dashboardImageUrl(connectionId, id) }])), [data?.images, connectionId]);
  const start = async () => {
    setBusy(true);
    try {
      const out = await copySharedDashboard(connectionId, owner, dashboardId);
      toast.success(`“${out.title ?? "The dashboard"}” is yours now, as version ${out.version}. The published one is unchanged.`);
      if (out.cockpit_id) onStarted(out.cockpit_id);
    } catch (e) {
      const why = e instanceof DashboardRefused ? e.outcome.sentences.join(" ") : (e as Error).message;
      toast.error("No dashboard was started", { description: why.slice(0, 200) });
    } finally { setBusy(false); }
  };
  if (problem) return <ErrorState kind="Not read" what="This shared dashboard could not be read." means={problem} />;
  if (!data) return <div className="aug-fs-sm" data-testid="dashboard-loading" style={{ color: "var(--t3)" }}>Reading the shared dashboard…</div>;
  return (
    <div data-testid="dashboard-shared" data-owner={owner} data-dashboard={dashboardId}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
        {data.ranges_on && rangesOn && (
          <PeriodPicker value={chosenRange} onChange={onRange} showing={data.range.status === "standing" ? null : data.range} />
        )}
        <span className="aug-fs-sm" data-testid="dashboard-shared-by" style={{ color: "var(--t2)" }}>
          An App by {personName(data.published_by)}, for {data.published_to.map(t => t.name).join(", ")} · version {data.cockpit.version} · read-only
        </span>
        <Button size="xs" variant="secondary" disabled={busy} style={{ marginLeft: "auto" }} onClick={() => void start()}>
          Start my dashboard from this
        </Button>
      </div>
      {data.ontology && <PinStrip pin={data.ontology} spec={data.cockpit.spec} />}
      <ComposedDashboard spec={data.cockpit.spec} cards={cards} host={host} doors={doors} sym={data.currency_symbol || "$"}
        images={images} range={range} schema={schema} connectionId={connectionId} dashboardId={`shared:${owner}:${dashboardId}`} />
    </div>
  );
}

/** How long after the last step of a resize it is kept: a burst of steps is ONE version (Arc AP-1). */
const KEEP_AFTER_MS = 900;

/** What the object door says when a row policy or a mask holds something back from a reader (aughor/ontology/security.py):
 *  a listing's "only the … objects … may see are shown", a count's "counted over only the … objects", a masked property,
 *  and a group or a person in none of the policy's groups. A preview says these in its banner. */
const WITHHELD = /may see are shown|counted over only the|masked for|sees no |none of its groups/;

/** Arc AP-8c — the cards of the person's own query a dashboard places, by id and title: what a value may read. */
export function placedQueries(spec: { elements?: Record<string, { type?: string; props?: Record<string, unknown> } | undefined> } | null | undefined,
  cards: { id: string; title?: string; sql?: string; render?: Record<string, unknown> }[]): { id: string; title: string }[] {
  const placed = new Set(Object.values(spec?.elements ?? {}).filter(el => el?.type === "Card").map(el => String(el?.props?.card ?? "")));
  // a query of the person's own carries how it is shown (Arc AP-7, `render.shown`)
  return cards.filter(c => placed.has(c.id) && (c.sql ?? "").trim() && c.render?.shown != null)
    .map(c => ({ id: c.id, title: c.title || "A query of yours" }));
}

export function BriefingDashboards({ connectionId, schema, onOpenSource, onEvidence }: {
  connectionId: string;
  schema?: string;
  onOpenSource?: (iid: string) => void;
  onEvidence?: (iid: string) => void;
}) {
  // The period the cards are read for: the person's pick, else the latest complete month where
  // ranges are on — a dashboard is watched month by month, as the mock showed it — else as written.
  // Nothing is read until the flag is known: a first read "as written" would roll every card's
  // standing value for a view nobody asked for.
  const [rangesOn, setRangesOn] = useState<boolean | null>(null);
  const [picked, setChosenRange] = useState<RangeChoice | null>(null);
  const chosenRange: RangeChoice = picked ?? (rangesOn ? { preset: "previous_month" } : { preset: "standing" });
  const range: BriefingRange | null = chosenRange.preset === "standing" ? null : chosenRange;
  const [list, setList] = useState<DashboardList | null>(null);
  const [chosen, setChosen] = useState("");
  const [data, setData] = useState<PersonDashboard | null>(null);
  const [cards, setCards] = useState<CardState[]>([]);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<DashboardKept | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  // Arc AP-6 — building safely: what each element read (the checks chip), the group the builder previews the dashboard
  // as, the groups it may preview as, and what the object door said a preview withholds
  const [checks, setChecks] = useState<Record<string, ReadState>>({});
  const onReadState = useCallback((key: string, state: ReadState | null) => setChecks(c => {
    if (!state) { if (!(key in c)) return c; const rest = { ...c }; delete rest[key]; return rest; }
    return c[key]?.status === state.status && c[key]?.reason === state.reason ? c : { ...c, [key]: state };
  }), []);
  // a preview lasts while this dashboard is built: leaving the builder, or opening another, reads as the person again
  const [previewing, setPreviewing] = useState("");
  const [groups, setGroups] = useState<{ id: string; name: string }[]>([]);
  const [heldBack, setHeldBack] = useState<string[]>([]);
  /** Preview as a group, or as the person again with "" — what an earlier preview was told withheld goes with it. */
  const previewAsGroup = (group: string) => { setHeldBack([]); setPreviewing(group); };
  const onSaid = useCallback((line: string) => {
    // what a row policy or a mask holds back is said; a compiler's other notes are the pieces' own
    if (WITHHELD.test(line)) setHeldBack(w => (w.includes(line) ? w : [...w, line]));
  }, []);
  // Retire is on the toolbar (2026-10-09): inside History it read as absent — the usability walk-through's finding.
  const [retiring, setRetiring] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [composing, setComposing] = useState(false);
  // The two doors by hand only: a note's words and an image are the person's, never a model's.
  const [noting, setNoting] = useState(false);
  const [imaging, setImaging] = useState(false);
  // Any recorded finding of the connection, as a card (B3); who the dashboard is published to (B5).
  const [picking, setPicking] = useState(false);
  // Arc AP-6 — whether row policies and masks hold here (`ontology.security`): off, a previewed group reads all the person reads
  const [limitsOn, setLimitsOn] = useState(false);
  // PENDING 54 — a question the agent answers on a rhythm
  const [questioning, setQuestioning] = useState(false);
  // Arc AP-7 — a query of the person's own, written for a section
  const [writing, setWriting] = useState<{ section: string | null } | null>(null);
  // the picker open, for a section (none: the first that holds pieces); and where a card, a note, an image or a finding
  // handed off from it lands
  const [adding, setAdding] = useState<{ section: string | null } | null>(null);
  const target = useRef<string | null>(null);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    if (!editing) return;
    let alive = true;
    getGroups().then(g => { if (alive) setGroups(g.groups.map(x => ({ id: x.id, name: x.name }))); }).catch(() => { /* no group to preview as */ });
    return () => { alive = false; };
  }, [editing]);
  const [placing, setPlacing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [shared, setShared] = useState<SharedDashboardListed[]>([]);
  const [tick, setTick] = useState(0);
  // The dashboard is being read for a period while the cards on screen are still the period before.
  const [reading, setReading] = useState(false);
  const known = useRef<Set<string>>(new Set());
  const adopt = useRef(false);
  // what the version that places the adopted card says it did — a pinned card, or a query of the person's own (Arc AP-7)
  const adoptNote = useRef("");
  // Arc AP-1 — a change in the builder, or a resize, drawn at once (`draft`) and kept as one version per burst (`burst`)
  const [draft, setDraft] = useState<DashboardSpec | null>(null);
  // when this browser last saw a burst kept, and whether one is waiting or on its way — the builder's "saved" says them
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [pending, setPending] = useState(false);
  // the builder's undo and redo: the specs before and after, in this sitting — each step back is kept as a version too
  const NO_STEPS = { past: [] as DashboardSpec[], future: [] as DashboardSpec[] };
  const [stacks, setStacks] = useState(NO_STEPS);
  const burst = useRef<{ spec: DashboardSpec | null; cockpit: string; note: string; timer: ReturnType<typeof setTimeout> | null;
    chain: Promise<void>; since: boolean }>({ spec: null, cockpit: "", note: "", timer: null, chain: Promise.resolve(), since: false });

  const rangeKey = JSON.stringify(range ?? null);
  const reload = useCallback(() => setTick(t => t + 1), []);

  useEffect(() => {
    let alive = true;
    getSystemFlags().then(f => {
      if (alive) { setRangesOn(!!f["briefing.ranges"]?.value); setLimitsOn(!!f["ontology.security"]?.value); }
    }).catch(() => { if (alive) setRangesOn(false); });
    return () => { alive = false; };
  }, []);

  // The person's dashboards.
  useEffect(() => {
    let cancelled = false;
    listDashboards(connectionId).then(l => {
      if (cancelled) return;
      setList(l);
      const live = l.cockpits.filter(c => !c.retired);
      // The metrics are the dashboard a person opens on (asked 2026-10-05); one of their own is
      // opened when it is where they left off.
      setChosen(prev => {
        const want = prev || remembered(connectionId);
        return live.some(c => c.cockpit_id === want) || want.startsWith("shared:") ? want : METRICS_DASHBOARD;
      });
    }).catch(e => { if (!cancelled) setProblem((e as Error).message); });
    // What others published to a group the person is in or a role they hold (B5). Nothing to
    // show is nothing to say: the strip simply has no such heading.
    listSharedDashboards(connectionId).then(s => { if (!cancelled) setShared(s); }).catch(() => { if (!cancelled) setShared([]); });
    return () => { cancelled = true; };
  }, [connectionId, tick]);

  // The chosen dashboard, read for the page's range, each card it places run through the guards.
  useEffect(() => {
    if (!chosen || chosen === METRICS_DASHBOARD || chosen.startsWith("shared:")) { setData(null); return; }
    if (rangesOn === null) return;
    let cancelled = false;
    setReading(true);
    (async () => {
      try {
        const read = await getDashboard(connectionId, chosen, range);
        const placed = new Set(read.cockpit.spec ? cardsPlaced(read.cockpit.spec) : []);
        const runs = await Promise.all(read.cards.filter(c => placed.has(c.id)).map(async (card): Promise<CardState> => {
          // Arc AP-8 — a query reading the dashboard's values is run by its own cell, with them
          if (valuesRead(card.sql).length) return { card };
          try { return { card, run: await runCard(card.id, range, { compare: true }) }; }
          catch { return { card, failed: true }; }
        }));
        if (cancelled) return;
        // A card pinned from here lands on the dashboard in view (§6 item 36(k)).
        if (adopt.current && read.cockpit.spec && !read.cockpit.retired) {
          adopt.current = false;
          const fresh = read.cards.filter(c => !known.current.has(c.id) && !placed.has(c.id));
          if (fresh.length) {
            let spec = read.cockpit.spec as DashboardSpec;
            for (const c of fresh) spec = placeCard(spec, c.id, target.current ?? undefined);
            target.current = null;
            const note = adoptNote.current || "a card pinned from the Briefing";
            adoptNote.current = "";
            try { await keepDashboard(connectionId, chosen, spec, note); reload(); return; }
            catch (e) { if (e instanceof DashboardRefused) setRefusal(e.outcome); }
          }
        }
        known.current = new Set(read.cards.map(c => c.id));
        setData(read); setCards(runs); setProblem("");
      } catch (e) {
        if (!cancelled) setProblem((e as Error).message || "The dashboard could not be read.");
      } finally {
        if (!cancelled) setReading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }, [connectionId, chosen, rangeKey, tick, rangesOn]);

  const write = useCallback(async (act: () => Promise<DashboardKept>, done: (k: DashboardKept) => string) => {
    setBusy(true); setRefusal(null);
    try {
      const kept = await act();
      toast.success(done(kept));
      reload();
      return true;
    } catch (e) {
      if (e instanceof DashboardRefused) setRefusal(e.outcome);
      else toast.error("That did not go through", { description: (e as Error).message.slice(0, 160) });
      return false;
    } finally { setBusy(false); }
  }, [reload]);

  /** Open another dashboard. From the builder's own picker it opens in the builder; anywhere else, to be read. */
  const choose = (id: string, keepEditing = false) => {
    if (burst.current.timer) sendBurst();
    setDraft(null);
    setChosen(id); remember(connectionId, id); setShowHistory(false); setRefusal(null); setProblem("");
    setPicking(false); setPublishing(false); setNoting(false); setImaging(false); setComposing(false); setQuestioning(false);
    setEditing(keepEditing); setStacks(NO_STEPS); previewAsGroup("");
  };

  const refreshOne = useCallback(async (id: string) => {
    try {
      const run = await runCard(id, range, { compare: true });
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, run, failed: false } : c)));
    } catch {
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, failed: true } : c)));
      toast.error("Couldn't refresh card", { description: "The query failed the trust guards or the source is unavailable." });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }, [rangeKey]);

  // One edit of the spec by hand, kept as the next version: what every door on a tile comes to. It is made on the newest
  // spec — a burst still waiting is folded into it, not kept after it — and kept after any keep already on its way, so
  // a resize landing late never takes back a note just placed (Arc AP-1).
  const edit = useCallback((change: (s: DashboardSpec) => DashboardSpec, note: string, said: string) => {
    if (!data?.cockpit.spec) return;
    const b = burst.current;
    const base = (b.spec && b.cockpit === data.cockpit_id ? b.spec : data.cockpit.spec) as DashboardSpec;
    if (b.timer) { clearTimeout(b.timer); b.timer = null; }
    if (b.spec) { b.spec = null; setDraft(null); setPending(false); }
    b.chain = b.chain.then(() => write(() => keepDashboard(connectionId, data.cockpit_id, change(base), note), () => said).then(() => undefined));
  }, [connectionId, data, write]);

  // Arc AP-1 — a resize is drawn at once and kept as ONE version per burst of steps, a moment after the last. The cards
  // are not read again: the room changed, and nothing measured did. Keeps go one after another, never two at once, and
  // a newer burst is never undone by an older one landing.
  const sendBurst = useCallback(() => {
    const b = burst.current;
    if (b.timer) { clearTimeout(b.timer); b.timer = null; }
    const sent = b.spec, cockpit = b.cockpit, note = b.note;
    if (!sent || !cockpit) return;
    b.chain = b.chain.then(async () => {
      try {
        const k = await keepDashboard(connectionId, cockpit, sent, note);
        setData(d => (d && d.cockpit_id === cockpit ? { ...d, cockpit: { ...d.cockpit, spec: sent, version: k.version ?? d.cockpit.version } } : d));
        burst.current.since = true;
        setSavedAt(Date.now());
        // what a refused keep said is no longer so once a later one is kept
        setRefusal(null);
      } catch (e) {
        if (e instanceof DashboardRefused) setRefusal(e.outcome);
        else toast.error("The new size was not kept", { description: (e as Error).message.slice(0, 160) });
      } finally {
        if (burst.current.spec === sent) { burst.current.spec = null; setDraft(null); setPending(false); }
      }
    });
  }, [connectionId]);
  const keepSoon = useCallback((change: (s: DashboardSpec) => DashboardSpec, note: string) => {
    if (!data?.cockpit.spec) return;
    const b = burst.current;
    const same = b.spec && b.cockpit === data.cockpit_id;
    const next = change((same ? b.spec : data.cockpit.spec) as DashboardSpec);
    b.spec = next; b.cockpit = data.cockpit_id; b.note = note;
    setDraft(next); setPending(true);
    if (b.timer) clearTimeout(b.timer);
    b.timer = setTimeout(sendBurst, KEEP_AFTER_MS);
  }, [data, sendBurst]);
  // a burst still waiting is kept before the page leaves it
  useEffect(() => () => { if (burst.current.timer) sendBurst(); }, [sendBurst]);

  // Arc AP-1 — in the builder every change goes through here: drawn at once, kept with the burst, and undoable.
  const current = (draft ?? data?.cockpit.spec ?? null) as DashboardSpec | null;
  const change = useCallback((next: DashboardSpec, note: string) => {
    if (!current) return;
    setStacks(st => ({ past: [...st.past.slice(-49), current], future: [] }));
    keepSoon(() => next, note);
  }, [current, keepSoon]);
  const undo = () => {
    const prev = stacks.past.at(-1);
    if (!prev || !current) return;
    setStacks({ past: stacks.past.slice(0, -1), future: [...stacks.future, current] });
    keepSoon(() => prev, "undone by hand");
  };
  const redo = () => {
    const next = stacks.future.at(-1);
    if (!next || !current) return;
    setStacks({ past: [...stacks.past, current], future: stacks.future.slice(0, -1) });
    keepSoon(() => next, "redone by hand");
  };
  const done = () => {
    if (burst.current.timer) sendBurst();
    setEditing(false); setShowHistory(false); setRetiring(false); setPublishing(false);
    setStacks(NO_STEPS); previewAsGroup("");
  };
  // the rail folds to its icons while the builder is open, and comes back as the person keeps it
  useEffect(() => (editing ? foldNavFor() : undefined), [editing]);

  // Arc AP-1 — read first: a dashboard being read offers its reader's own doors only, and the builder all of them, each
  // change kept through `change` so that it can be undone
  const readDoors = useMemo<DashboardDoors>(() => ({ onRefresh: refreshOne, onOpenSource, onEvidence }), [refreshOne, onOpenSource, onEvidence]);
  const editDoors = useMemo<DashboardDoors>(() => {
    const on = (fn: (s: DashboardSpec) => DashboardSpec, note: string) => { if (current) change(fn(current), note); };
    return {
      onRefresh: refreshOne, onOpenSource, onEvidence,
      onRemove: (id: string) => on(s => takeOffCard(s, id), "a card taken off"),
      onTakeOff: (key: string) => on(s => takeOff(s, key), "taken off by hand"),
      onEditNote: (key: string, text: string) => on(s => editNote(s, key, text), "a note's words changed by hand"),
      onRecaption: (key: string, caption: string) => on(s => recaption(s, key, caption), "an image's caption changed by hand"),
      onPlaceTable: (entity: string, segment: string) => on(s => placePiece(s, "ObjectTable", { entity, segment, size: "wide" }).spec,
        "an objects table placed from a process board"),
      onRegrid: (key: string, box: Box, measured: Record<string, Box>) => on(s => regrid(s, key, box, measured), "resized by hand"),
      onFilterWidth: (grades: number) => on(s => setFilterWidth(s, grades), "the filter column resized by hand"),
      // Arc AP-4 — an empty section's offer: the piece picker for it, or sections of its own
      onAddPiece: (section: string) => setAdding({ section }),
      onLayOut: (section: string, layout: Layout) => on(s => layOut(s, section, layout), `laid out in ${layout} by hand`),
    };
  }, [current, change, refreshOne, onOpenSource, onEvidence]);
  const host = useMemo(() => hostStateOf(data?.range.status ?? "standing", cards), [data?.range.status, cards]);
  // Where each image's bytes are read from: the API, with this reader's own access.
  const images = useMemo<Record<string, ImageStamp>>(() => Object.fromEntries(
    Object.entries(data?.images ?? {}).map(([id, s]) => [id, { ...s, url: dashboardImageUrl(connectionId, id) }])),
  [data?.images, connectionId]);

  if (list === null) {
    return <div className="aug-fs-sm" data-testid="dashboards-loading" style={{ color: "var(--t3)", padding: "24px 32px" }}>Reading your dashboards…</div>;
  }

  const live = list.cockpits.filter(c => !c.retired);
  const kept = data?.cockpit;
  const drawn = kept && !kept.retired && kept.spec != null;
  // Arc ED-4 — which version an App's readers read, and whether a change since is a draft
  const app = appWords(kept ?? { version: 0, published_to: [] });
  const pinned = list.shared_cards + list.own_cards;
  const lines = new Map<string, CardLine>((data?.cards ?? []).map(c => [c.id, { title: c.title }]));

  const startOwn = pinned > 0 ? (
    <Button variant="secondary" size="xs" disabled={busy}
      onClick={() => void write(() => startMyDashboard(connectionId), () => "“My dashboard” started from your pinned cards.")}>
      Start “My dashboard” from {pinned} pinned {pinned === 1 ? "card" : "cards"}
    </Button>
  ) : (
    <Button variant="secondary" size="xs" onClick={() => setNewOpen(true)}>New dashboard</Button>
  );
  // Under the Metrics dashboard, a person's own dashboards are one muted line and their door — the explanation on hover.
  const noneYetLine = (
    <div className="aug-fs-sm" data-testid="dashboard-none-yet" style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--t3)" }}
      title="A dashboard is the set of cards you keep watching for one area — returns, pricing, marketing. It is yours: nobody else sees it or changes it.">
      {list.cockpits.length ? "No dashboard of your own in use" : "No dashboard of your own yet"} — the cards you keep watching for one area
      {startOwn}
    </div>
  );
  const noneYet = (
        <EmptyState icon="gauge" variant="inline"
          title={list.cockpits.length ? "You have no dashboards in use" : "You have no dashboards yet"}
          action={pinned > 0 ? (
            <Button variant="secondary" size="sm" disabled={busy}
              onClick={() => void write(() => startMyDashboard(connectionId), () => "“My dashboard” started from your pinned cards.")}>
              Start “My dashboard” from {pinned} pinned {pinned === 1 ? "card" : "cards"}
            </Button>
          ) : (
            <Button variant="secondary" size="sm" onClick={() => setNewOpen(true)}>New dashboard</Button>
          )}>
          A dashboard is the set of cards you keep watching for one area — returns, pricing, marketing. It is yours:
          nobody else sees it or changes it. Name an area and one is drafted for you to keep, or start from the cards already pinned here.
        </EmptyState>
  );

  // a dashboard's versions, newest first, each one a person may go back to
  const historyPanel = kept && data ? (
    <div style={{ margin: "8px 0 12px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <span className="aug-fs-sm" data-testid="dashboard-version" style={{ color: "var(--t3)" }}>
          Version {kept.version} · {kept.written_by_model ? "drafted, kept" : "kept"} by {person(kept.approved_by)} · {formatDateTime(kept.kept_at)}
        </span>
      </div>
      <ol data-testid="dashboard-history" style={{ listStyle: "none", margin: 0, padding: 0, borderTop: "1px solid var(--b1)" }}>
        {data.history.map(v => (
          <li key={v.artifact_id} className="aug-fs-sm" style={{ display: "flex", alignItems: "baseline", gap: 12, padding: "7px 0", borderBottom: "1px solid var(--b1)", color: "var(--t2)", flexWrap: "wrap" }}>
            <span style={{ color: "var(--t1)", fontWeight: 500, minWidth: 74 }}>Version {v.version}</span>
            <span style={{ flex: 1, minWidth: 0 }}>
              {/* Arc AP-6 — what it changed, in words; a server before the words says its counts, as before */}
              {v.said ? (v.said.length > 0 && (
                <span data-testid="dashboard-history-said" style={{ display: "block", color: "var(--t1)" }}>{v.said.join(" · ")}</span>
              )) : <>{v.retired ? "Retired" : changed(v.changes)} · </>}
              {person(v.approved_by)} · {formatDateTime(v.kept_at)}
              {v.source ? ` · ${v.source}` : ""}{v.note ? ` · ${v.note}` : ""}
              {kept.published_version === v.version && (
                <span data-testid="dashboard-history-read" style={{ color: "var(--t1)" }}> · what its readers read</span>
              )}
            </span>
            {v.current ? <span style={{ color: "var(--t3)" }}>current</span> : v.retired ? null : (
              <Button variant="ghost" size="xs" disabled={busy}
                onClick={() => void write(() => restoreDashboard(connectionId, data.cockpit_id, v.version),
                  k => (k.status === "unchanged" ? "That is the version you are on." : `Back to version ${v.version}, kept as version ${k.version}.`))}>
                Go back to this
              </Button>
            )}
          </li>
        ))}
      </ol>
    </div>
  ) : null;

  // what may be added by hand, each in its own composer — placed by `edit`, kept at once
  const composers = kept && data ? (
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
          onPlace={text => { const at = target.current ?? undefined; target.current = null;
            edit(s => placeNote(s, text, at), "a note written by hand", "Placed. Its author and date are stamped as it is kept."); setNoting(false); }} />
      )}
      {questioning && (
        <QuestionComposer connectionId={connectionId} schema={schema} busy={busy} onClose={() => setQuestioning(false)}
          onKept={(automation, first, rhythm) => { const at = target.current ?? undefined; target.current = null;
            edit(s => placeQuestion(s, automation, first || undefined, at), "a question kept by hand",
              rhythm === "ask" ? "Placed. It is asked only when you ask." : "Placed. Its first answer comes on its rhythm.");
            setQuestioning(false); }} />
      )}
      {imaging && (
        <ImageComposer connectionId={connectionId} busy={busy} onClose={() => setImaging(false)}
          onPlace={(objectId, caption) => { const at = target.current ?? undefined; target.current = null;
            edit(s => placeImage(s, objectId, caption, at), "an image uploaded by hand", "Placed. The upload is stamped with your name and the date."); setImaging(false); }} />
      )}
      {placing && (
        <OntologyPieceComposer connectionId={connectionId} schema={schema} spec={(current ?? kept.spec) as DashboardSpec} busy={busy}
          onClose={() => setPlacing(false)}
          onPlace={(change, note, said) => { edit(change, note, said); setPlacing(false); }} />
      )}
      {picking && (
        <FindingPicker connectionId={connectionId} schema={schema} busy={busy}
          placed={new Set(cards.map(c => findingOfCard(c.card)).filter(Boolean))}
          onPlaced={() => { adopt.current = true; reload(); }} onClose={() => setPicking(false)} />
      )}
      {publishing && (
        <PublishPanel connectionId={connectionId} dashboardId={data.cockpit_id} busy={busy}
          publishedTo={(kept.published_to ?? []) as DashboardAudience[]} draft={app.draft} readersSee={app.readersSee}
          onDone={write} onClose={() => setPublishing(false)} />
      )}
    </>
  ) : null;

  // Arc AP-1 — the builder: the dashboard between its layout and the setup of what is chosen, in place of the strip
  if (editing && drawn && data && current && chosen !== METRICS_DASHBOARD && !chosen.startsWith("shared:")) {
    const at = savedAt ?? (kept.kept_at ? Date.parse(kept.kept_at) : NaN);
    const saved = pending ? "Saving…"
      : `saved ${Number.isNaN(at) ? "" : new Date(at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} · version ${kept.version}`;
    const shut = () => { setComposing(false); setNoting(false); setImaging(false); setPicking(false); setPlacing(false); setQuestioning(false); };
    return (
      <div data-testid="briefing-dashboards" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <DashboardBuilder spec={current} onChange={change} cardTitle={id => lines.get(id)?.title} connectionId={connectionId} schema={schema}
          onAddPiece={section => setAdding({ section })} checks={checks}
          cardReads={id => valuesRead(data.cards.find(c => c.id === id)?.sql)}
          queryCards={placedQueries(current, data.cards)}
          bar={(
            <EditBar saved={saved} canUndo={stacks.past.length > 0} canRedo={stacks.future.length > 0} onUndo={undo} onRedo={redo} onDone={done}
              picker={(
                <SelectField aria-label="The dashboard being edited" value={chosen} onChange={e => choose(e.target.value, true)} style={{ maxWidth: 240 }}>
                  {live.map(c => <option key={c.cockpit_id} value={c.cockpit_id}>{c.title || c.cockpit_id}</option>)}
                </SelectField>
              )}
              actions={(
                <>
                  {groups.length > 0 && (
                    <SelectField aria-label="Preview as" data-testid="builder-preview-as" value={previewing}
                      onChange={e => previewAsGroup(e.target.value)} style={{ maxWidth: 260 }}>
                      <option value="">Preview as · you</option>
                      {withUniqueKeys(groups, g => g.id).map(([k, g]) => <option key={k} value={g.id}>Preview as {g.name}</option>)}
                    </SelectField>
                  )}
                  <Button size="xs" variant="ghost" aria-expanded={showHistory} data-testid="builder-history" onClick={() => {
                    if (!showHistory && burst.current.since) { burst.current.since = false; reload(); }
                    setShowHistory(h => !h);
                  }}><Icon name="history" /> History</Button>
                  <Button size="xs" variant={kept.published_to?.length ? "secondary" : "ghost"} disabled={busy} data-testid="dashboard-publish-open"
                    aria-expanded={publishing} title={app.title || "Share this dashboard, as it stands, with a group you belong to or a role you hold."}
                    onClick={() => setPublishing(p => !p)}>
                    <Icon name="send" /> {app.label}
                  </Button>
                  <Button size="xs" variant="ghost" disabled={busy} data-testid="dashboard-retire-open" aria-expanded={retiring}
                    title="Take this dashboard off your strip for good. Its history stays in the record."
                    onClick={() => setRetiring(r => !r)}><Icon name="close" /> Retire</Button>
                </>
              )} />
          )}
          add={(
            <>
              <Button size="xs" variant="ghost" disabled={busy || composing} data-testid="dashboard-card-new" onClick={() => { shut(); setComposing(true); }}>
                <Icon name="plus" /> Card
              </Button>
              <Button size="xs" variant="ghost" disabled={busy || noting} data-testid="dashboard-note-new"
                title="Your own words on this dashboard. By hand only: a model never writes a note." onClick={() => { shut(); setNoting(true); }}>
                <Icon name="plus" /> Note
              </Button>
              <Button size="xs" variant="ghost" disabled={busy || questioning} data-testid="dashboard-question-new"
                title="A question the agent answers on a rhythm, as the Data Canvas does. By hand only." onClick={() => { shut(); setQuestioning(true); }}>
                <Icon name="plus" /> Question
              </Button>
              <Button size="xs" variant="ghost" disabled={busy || imaging} data-testid="dashboard-image-new"
                title="An image of your own on this dashboard. By hand only: a model never chooses one." onClick={() => { shut(); setImaging(true); }}>
                <Icon name="plus" /> Image
              </Button>
              <Button size="xs" variant="ghost" disabled={busy || picking} data-testid="dashboard-finding-new"
                title="Any finding the explorer has recorded on this connection, as a card: its query re-run through the guards."
                onClick={() => { shut(); setPicking(true); }}>
                <Icon name="plus" /> Finding
              </Button>
              <Button size="xs" variant="ghost" disabled={busy || placing} data-testid="dashboard-piece-new"
                title="A process board, an objects table, an object detail or an action button — each reads what the ontology declares, by id."
                onClick={() => { shut(); setPlacing(true); }}>
                <Icon name="plus" /> From the ontology
              </Button>
              <Button size="xs" variant="ghost" disabled={busy} data-testid="dashboard-buttons-new"
                title="Buttons that run declared actions on what a reader chose or ticked — wired in their setup."
                onClick={async () => {
                  shut();
                  try {
                    const declared = Object.values(await getDeclaredActions(connectionId, schema));
                    if (!declared.length) { toast.error("No action is declared here", { description: "Declare one in Ontology ▸ Actions, then place its button." }); return; }
                    const placed = placePiece(current, "ActionButtons", { buttons: [{ action: declared[0].id }] });
                    if (placed.key) change(placed.spec, "action buttons placed by hand");
                  } catch (e) {
                    toast.error("The declared actions could not be read", { description: (e as Error).message.slice(0, 160) });
                  }
                }}>
                <Icon name="plus" /> Action buttons
              </Button>
            </>
          )}
          cardSetup={cardId => {
            // Arc AP-7 — a card of the person's own query is set up here: its SQL, how it is shown, and Keep
            const held = data.cards.find(c => c.id === cardId);
            if (!held || !held.own || !(held.render as { shown?: unknown })?.shown) return null;
            return (
              <QuerySetup key={held.id} connectionId={connectionId} card={held} values={current.values ?? {}}
                onKept={(kept, replaced) => replaced
                  && edit(s => swapCard(s, replaced, kept.id), "a query of your own changed by hand", `Kept the change to “${kept.title}”.`)} />
            );
          }}
          aside={showHistory ? (
            <div data-testid="builder-history-panel" style={{ padding: "4px 14px" }}>
              <div style={{ display: "flex", alignItems: "center", padding: "8px 0" }}>
                <span className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>History</span>
                <Button size="xs" variant="ghost" style={{ marginLeft: "auto" }} onClick={() => setShowHistory(false)}>Back to the setup</Button>
              </div>
              {historyPanel}
            </div>
          ) : writing ? (
            <QuerySetup connectionId={connectionId} onClose={() => setWriting(null)} values={current.values ?? {}}
              onKept={() => {
                target.current = writing.section; adopt.current = true; adoptNote.current = "a query of your own placed by hand";
                setWriting(null); reload();
              }} />
          ) : undefined}
          above={(
            <>
              {previewing && (
                <Callout tone="blue" style={{ margin: "0 0 10px" }} data-testid="dashboard-preview-banner">
                  <span className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <b style={{ fontWeight: 600 }}>Previewing as {groups.find(g => g.id === previewing)?.name ?? previewing}.</b>
                      Each piece reads what you and a member of it may both see; nothing is run or changed.
                      <Button size="xs" variant="ghost" onClick={() => previewAsGroup("")}>Stop previewing</Button>
                    </span>
                    {heldBack.length ? withUniqueKeys(heldBack, w => w).map(([k, w]) => (
                      <span key={k} className="aug-fs-xs" data-testid="dashboard-preview-withheld" style={{ color: "var(--t2)" }}>Withheld — {w}.</span>
                    )) : (
                      <span className="aug-fs-xs" data-testid="dashboard-preview-nothing" style={{ color: "var(--t3)" }}>
                        {limitsOn ? "No row policy or mask holds back what these pieces read from this group."
                          : `Limiting who sees which objects is off here, so a member of ${groups.find(g => g.id === previewing)?.name ?? previewing} reads what you read.`}
                      </span>
                    )}
                  </span>
                </Callout>
              )}
              {refusal && <Refused outcome={refusal} />}
              {retiring && (
                <Callout tone="amber" style={{ margin: "0 0 10px" }} data-testid="dashboard-retire-confirm">
                  <span className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    Retire this dashboard? It leaves your strip for good and cannot be brought back; its history stays in the record.
                    <Button size="xs" disabled={busy} onClick={() => {
                      setRetiring(false); setEditing(false); previewAsGroup("");
                      void write(() => retireDashboard(connectionId, data.cockpit_id), () => "Dashboard retired. Its history stays.");
                    }}>Retire it</Button>
                    <Button size="xs" variant="ghost" onClick={() => setRetiring(false)}>Keep it</Button>
                  </span>
                </Callout>
              )}
              {composers}
              {adding && (
                <PiecePicker spec={current} section={adding.section} connectionId={connectionId} schema={schema}
                  onPlace={change} onClose={() => setAdding(null)}
                  onHandOff={(kind, section) => {
                    setAdding(null); shut(); target.current = section;
                    if (kind === "query") { setShowHistory(false); setWriting({ section }); return; }
                    if (kind === "card") setComposing(true); else if (kind === "note") setNoting(true);
                    else if (kind === "image") setImaging(true); else setPicking(true);
                  }} />
              )}
              <AskChange connectionId={connectionId} dashboardId={data.cockpit_id} schema={schema} held={lines}
                onKept={() => { setPublishing(false); reload(); }} />
              {data.ontology && (
                <PinStrip pin={data.ontology} spec={current} busy={busy}
                  onRepin={() => void write(() => keepDashboard(connectionId, data.cockpit_id, kept.spec, `re-pinned to ${data.ontology?.current}`, true),
                    k => (k.status === "unchanged" ? "Already pinned there." : `Re-pinned, as version ${k.version}.`))} />
              )}
            </>
          )}>
          {({ selected, onSelect, handle, reads }) => (previewing ? (
            // Arc AP-6 — read as the person and a member of the group, with no door that changes the dashboard
            <ComposedDashboard key={`preview:${previewing}`} spec={current} cards={cards} host={host}
              doors={{ onRefresh: editDoors.onRefresh, onReadState }} sym={data.currency_symbol || "$"} images={images} range={range}
              schema={schema} connectionId={connectionId} dashboardId={`${connectionId}:${chosen}:preview`} asGroup={previewing} onSaid={onSaid} />
          ) : (
            <ComposedDashboard spec={current} cards={cards} host={host} doors={{ ...editDoors, onSelect, onReadState }} sym={data.currency_symbol || "$"}
              images={images} range={range} schema={schema} connectionId={connectionId} dashboardId={`${connectionId}:${chosen}`}
              selected={selected} handle={handle} reads={reads} />
          ))}
        </DashboardBuilder>
      </div>
    );
  }

  return (
    <div data-testid="briefing-dashboards" style={{ flex: 1, overflow: "auto", padding: "14px 32px 32px" }}>
      {/* The strip: the connection's metrics first (nobody's to arrange), then the person's own
          cockpits under the layer's label — violet is the user's, as the Briefing has always marked
          it — and, at the end, the door to a new one. */}
      <TabStrip label="Your dashboards" size="1" value={chosen} onChange={choose} style={{ marginBottom: 12 }}
        tabs={[
          { id: METRICS_DASHBOARD, label: "Metrics" },
          { heading: <span className="aug-label" style={{ color: "var(--vio4)" }}>Your dashboards</span> },
          ...live.map(c => ({ id: c.cockpit_id, label: c.title || c.cockpit_id })),
          // Published to a group the person is in or a role they hold: read-only, under the publisher's name.
          ...(shared.length ? [{ heading: <span className="aug-label" style={{ color: "var(--t3)" }}>Apps shared with you</span> }] : []),
          ...shared.map(s => ({ id: `shared:${s.owner}/${s.cockpit_id}`, label: `${s.title || s.cockpit_id} · ${person(s.published_by || s.owner)}` })),
        ]}
        trailing={<Button size="xs" variant="ghost" data-testid="dashboard-new-open" onClick={() => setNewOpen(o => !o)}>+ New dashboard</Button>} />

      {newOpen && (
        <NewDashboard connectionId={connectionId} schema={schema} onClose={() => setNewOpen(false)}
          sym={data?.currency_symbol || "$"}
          onKept={id => { setNewOpen(false); choose(id); reload(); }} />
      )}

      {/* Dashboards that lived in a Data Canvas, offered here once (CT-10). */}
      {list.from_canvases.map(c => (
        <div key={c.canvas_id} data-testid="dashboard-move-offer" className="aug-fs-sm"
          style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, color: "var(--t2)" }}>
          <span>“{c.title}” was kept in a Data Canvas, which is for questions and deep analysis now. Move it here, with its cards?</span>
          <Button size="xs" variant="secondary" disabled={busy} onClick={async () => {
            setBusy(true);
            try {
              const out = await moveCanvasDashboard(connectionId, c.canvas_id);
              if (out.moved) { toast.success(`Moved “${out.title}” here.`); if (out.cockpit_id) choose(out.cockpit_id); reload(); }
              else toast.error("It was not moved", { description: out.sentences.join(" ").slice(0, 200) });
            } finally { setBusy(false); }
          }}>Move it here</Button>
        </div>
      ))}

      {refusal && <Refused outcome={refusal} />}
      {problem && (
        <ErrorState kind="Failed" what="Your dashboard could not be read." means={problem}
          doors={[{ label: "Try again", onClick: reload, primary: true }]} />
      )}

      {chosen === METRICS_DASHBOARD ? (
        <>
          <MetricsDashboard connectionId={connectionId} schema={schema} rangesOn={rangesOn}
            value={chosenRange} onChange={setChosenRange} />
          {live.length === 0 && <div style={{ marginTop: 14 }}>{noneYetLine}</div>}
        </>
      ) : chosen.startsWith("shared:") ? (
        <SharedDashboardView connectionId={connectionId} schema={schema}
          owner={chosen.slice("shared:".length, chosen.lastIndexOf("/"))} dashboardId={chosen.slice(chosen.lastIndexOf("/") + 1)}
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
              <Button size="xs" variant="ghost" aria-expanded={showHistory} onClick={() => {
                // a resize kept since the page was read is not in its history yet: read it again once
                if (!showHistory && burst.current.since) { burst.current.since = false; reload(); }
                setShowHistory(s => !s);
              }}>
                <Icon name="history" /> {showHistory ? "Hide history" : "History"}
              </Button>
              <Button size="xs" variant="secondary" data-testid="dashboard-edit" disabled={busy || reading}
                title="Build this dashboard in place: its layout, each piece's setup, and sizes one grade at a time."
                onClick={() => { setShowHistory(false); setRefusal(null); setEditing(true); }}>
                <Icon name="edit" /> Edit
              </Button>
            </span>
          </div>

          {showHistory && historyPanel}

          {composers}
          {data.ontology && (
            <PinStrip pin={data.ontology} spec={kept.spec} busy={busy}
              onRepin={() => void write(() => keepDashboard(connectionId, data.cockpit_id, kept.spec,
                `re-pinned to ${data.ontology?.current}`, true),
              k => (k.status === "unchanged" ? "Already pinned there." : `Re-pinned, as version ${k.version}.`))} />
          )}
          {reading && <Loading what={`the cards for ${choiceName(chosenRange)}`} style={{ padding: "12px 0" }} />}
          {!reading && data.range.edge_note && (
            <div className="aug-fs-sm" data-testid="dashboard-edge-note" style={{ color: "var(--t2)", margin: "4px 0 8px" }}>{data.range.edge_note}</div>
          )}
          <div aria-busy={reading || undefined}
            style={{ opacity: reading ? 0.45 : 1, transition: "opacity 120ms ease-out", pointerEvents: reading ? "none" : undefined }}>
            <ComposedDashboard spec={draft ?? kept.spec} cards={cards} host={host} doors={readDoors} sym={data.currency_symbol || "$"}
              images={images} range={range} schema={schema} connectionId={connectionId} dashboardId={`${connectionId}:${chosen}`} />
          </div>
        </>
      ) : !problem ? (
        <div className="aug-fs-sm" data-testid="dashboard-loading" style={{ color: "var(--t3)" }}>Reading the dashboard…</div>
      ) : null}
    </div>
  );
}
