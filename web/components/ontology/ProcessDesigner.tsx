"use client";

/**
 * The process designer — a business process designed FROM the data, on a page of its own inside the Ontology (the rail
 * unchanged). Approved as drawn on 2026-10-09 after the usability walk-through (`docs/USABILITY_WALKTHROUGH_2026-10-09.md`)
 * found the old form in a quarter-width column four screens down, silent about why it would not submit, picking blind
 * from column names, and unable to show — before publishing — that a delivery process typed the obvious way would call
 * ≈35,750 records left behind "late".
 *
 * A person names things in words; ids are made for them (`lib/processDraft`). The data is read for them: the moments
 * the type and its linked records carry, with counts, and the statuses objects end in (`GET /ontology/processes/
 * candidates`). As the draft changes it is counted exactly as declaring it would count it, with nothing written
 * (`POST /ontology/processes/preview`): how many reach each stage, the typical time between stages, each promise's
 * breach rate, and the checks to read before publishing — a stage objects wait at for over a year asked about as a
 * question, with the statuses that explain them. Publishing declares the process and publishes the release; then a
 * cockpit for it is one press away.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import { processCockpitSpec, startCockpit as keepNewCockpit } from "@/lib/cockpit/start";
import { formatCount, pct } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { requestTab } from "@/lib/navigate";
import { listObjects, type ObjectListingPage } from "@/lib/objects";
import {
  changeProcess,
  declareProcess,
  getProcessCandidates,
  getRelease,
  previewProcess,
  publishRelease,
  type DesignCheck,
  type ProcessCandidates,
  type ProcessDetail,
  type ProcessMoment,
  type ProcessPreview,
  type ReleaseState,
  type TypeMapRow,
} from "@/lib/objectTypes";
import {
  EMPTY_STAGE,
  LEFT,
  draftFromProcess,
  dropDraft,
  emptyDraft,
  freshId,
  idFrom,
  keepDraft,
  keptDraft,
  notReady,
  toSpec,
  toggledMoves,
  type Anchor,
  type ProcessDraft,
  type PromiseDraft,
  type StageDraft,
} from "@/lib/processDraft";

const RULE = "1px solid var(--b1)";
const CARD: React.CSSProperties = { border: RULE, borderRadius: "var(--r3)", padding: "12px 14px", marginBottom: 12 };
const TILE: React.CSSProperties = { background: "var(--bg-2)", borderRadius: "var(--r2)", padding: "8px 10px", minWidth: 0 };
const HINT: React.CSSProperties = { color: "var(--t3)" };
const LABEL: React.CSSProperties = { color: "var(--t2)", margin: "0 0 4px" };
const BIG: React.CSSProperties = { fontSize: 18, fontWeight: 500, color: "var(--t1)", lineHeight: 1.3 };
/** How long the draft rests before it is counted again. */
const SETTLE_MS = 900;

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** A refusal in words — an edit the platform's approval gate held (HTTP 428) says what happened, never the status code.
 *  An approval given in the dialog sends the held edit on its own (`lib/approval`); a 428 reaches here only when the
 *  dialog was closed without approving. */
function refusal(title: string, e: unknown): [string, { description: string }] {
  const said = errorText(e);
  return /\b428\b|approval/i.test(said)
    ? ["Not approved", { description: `Nothing was changed: changing the ontology on this connection needs approval. Press again and approve it in the dialog.` }]
    : [title, { description: said.slice(0, 240) }];
}

function upper(words: string): string {
  return words ? words[0].toUpperCase() + words.slice(1) : words;
}

function momentLabel(m: ProcessMoment): string {
  return m.via ? `${m.on_label} · ${m.label}` : m.label;
}

function days(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${Number.isInteger(n) ? n : n.toFixed(1)} d`;
}

/** A fresh cockpit holding the process's board, its open-and-overdue objects and one object beside them — the same
 *  cockpit a process's own panel and *+ New cockpit* start (`lib/cockpit/start`). */
export const cockpitSpecFor = processCockpitSpec;

type Phase = { at: "draft" } | { at: "declared"; id: string } | { at: "published"; id: string; release: number };

export function ProcessDesigner({ connectionId, schema, types, entity, takenIds, editing, onClose, onDeclared, onPublished }: {
  connectionId: string;
  schema?: string;
  types: TypeMapRow[];
  /** Arc OC-5 — a declared process being CHANGED (a promise added, the moves expected): its id and its stages' names
   *  stay; saving counts it again and writes a new version of it. */
  editing?: ProcessDetail;
  /** The type a person started from, when they did. */
  entity?: string;
  /** Ids of the processes already declared — a new one is never named like them. */
  takenIds: string[];
  onClose: () => void;
  onDeclared: (processId: string) => void;
  /** The release holding the process was published — what reads the release re-reads it. */
  onPublished?: () => void;
}) {
  const [draft, setDraft] = useState<ProcessDraft>(() => {
    if (editing) return draftFromProcess(editing);
    const kept = keptDraft(connectionId, schema);
    return kept && (!entity || kept.entity === entity) ? kept : emptyDraft(entity ?? "");
  });
  const [restored] = useState(() => !editing && !!keptDraft(connectionId, schema) && draft.name !== "");
  const [cands, setCands] = useState<ProcessCandidates | null>(null);
  const [candsProblem, setCandsProblem] = useState("");
  // A count is shown only beside the draft it counted — a stage changed since reads "—" until it is counted again.
  const [counted, setCounted] = useState<{ key: string; preview: ProcessPreview } | null>(null);
  const [counting, setCounting] = useState(false);
  const [countProblem, setCountProblem] = useState("");
  const [phase, setPhase] = useState<Phase>({ at: "draft" });
  const [release, setRelease] = useState<ReleaseState | null>(null);
  const [busy, setBusy] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [exitOpen, setExitOpen] = useState(false);
  const [samples, setSamples] = useState<Record<string, ObjectListingPage | string>>({});
  const asked = useRef(0);

  const edit = (change: Partial<ProcessDraft>) => setDraft(d => ({ ...d, ...change }));
  const editStage = (i: number, change: Partial<StageDraft>) =>
    setDraft(d => ({ ...d, stages: d.stages.map((s, j) => (j === i ? { ...s, ...change } : s)) }));

  // What the type carries — read when the type is chosen.
  useEffect(() => {
    if (!draft.entity) { setCands(null); return; }
    let live = true;
    setCands(null);
    setCandsProblem("");
    getProcessCandidates(connectionId, draft.entity, schema)
      .then(c => { if (live) setCands(c); })
      .catch(e => { if (live) setCandsProblem(errorText(e)); });
    return () => { live = false; };
  }, [connectionId, schema, draft.entity]);

  const problem = notReady(draft);
  const spec = useMemo(() => (problem ? null : toSpec(draft, takenIds)), [draft, problem, takenIds]);
  const specKey = spec ? JSON.stringify(spec) : "";
  const specNow = useRef(spec);
  specNow.current = spec;

  // Counted as declaring would count it, once the draft rests — nothing is written. Keyed by the spec's content, so a
  // render that changes nothing the declaration says does not count it again.
  useEffect(() => {
    const asking = specNow.current;
    if (!asking || phase.at !== "draft") return;
    const n = ++asked.current;
    const t = setTimeout(() => {
      setCounting(true);
      setCountProblem("");
      previewProcess(connectionId, asking, schema, !!editing)
        .then(p => { if (n === asked.current) setCounted({ key: JSON.stringify(asking), preview: p }); })
        .catch(e => { if (n === asked.current) { setCounted(null); setCountProblem(errorText(e)); } })
        .finally(() => { if (n === asked.current) setCounting(false); });
    }, SETTLE_MS);
    return () => clearTimeout(t);
  }, [connectionId, schema, specKey, phase.at]);

  // Once declared, the count is the declaration's own — the process's id is taken now, and the draft's re-derived id
  // must not hide what was counted and declared.
  const preview = counted && (phase.at !== "draft" || counted.key === specKey) ? counted.preview : null;
  const measured = preview?.process;
  const objects = measured?.objects ?? cands?.objects ?? null;
  const usedMoments = new Set(draft.stages.map(s => (s.anchor?.kind === "moment" ? s.anchor.path : "")));
  const usedStates = new Set(draft.stages.flatMap(s => (s.anchor?.kind === "state" ? s.anchor.values : [])));
  const status = cands?.states[0];
  const suggestions = [
    ...(cands?.moments ?? []).filter(m => !usedMoments.has(m.path) && m.set > 0)
      .sort((a, b) => b.set - a.set).slice(0, 4)
      .map(m => ({ key: `m:${m.path}`, label: `${momentLabel(m)} · ${formatCount(m.set)}`,
                   stage: { label: m.label.replace(/[\s_]+(at|on)$/i, "").replace(/_/g, " "), anchor: { kind: "moment", path: m.path } as Anchor } })),
    ...(status ? status.values.filter(v => v.value && !usedStates.has(v.value)).slice(0, 2)
      .map(v => ({ key: `s:${v.value}`, label: `${status.label} reaches ${v.value} · ${formatCount(v.objects)}`,
                   stage: { label: String(v.value), anchor: { kind: "state", property: status.property, values: [String(v.value)] } as Anchor } })) : []),
  ];
  const addStage = (stage: Partial<StageDraft> = {}) => setDraft(d => {
    const empty = d.stages.findIndex(s => !s.label.trim() && !s.anchor);
    if (empty >= 0) return { ...d, stages: d.stages.map((s, j) => (j === empty ? { ...EMPTY_STAGE, ...stage } : s)) };
    return { ...d, stages: [...d.stages, { ...EMPTY_STAGE, ...stage }] };
  });

  const checks = preview?.checks ?? [];
  const openAsks = checks.filter(c => c.level === "ask" && !draft.late.includes(c.id));
  const declaredId = phase.at === "draft" ? (spec?.id ?? freshId(idFrom(draft.name), takenIds)) : phase.id;

  const show = async (c: DesignCheck) => {
    if (!c.show) return;
    setSamples(s => ({ ...s, [c.id]: "loading" }));
    try {
      const page = await listObjects({ entity: c.show.entity, filters: c.show.filters, columns: c.show.columns, limit: 20 },
        connectionId, schema);
      setSamples(s => ({ ...s, [c.id]: page.path === "listed" ? (page.error ? page.error : page) : page.refused }));
    } catch (e) {
      setSamples(s => ({ ...s, [c.id]: errorText(e) }));
    }
  };

  const declare = async () => {
    if (!spec) return;
    setBusy("declare");
    try {
      const made = editing ? await changeProcess(connectionId, spec, schema) : await declareProcess(connectionId, spec, schema);
      if (!editing) dropDraft(connectionId, schema);
      setPhase({ at: "declared", id: made.id });
      setReviewing(false);
      onDeclared(made.id);
      setRelease(await getRelease(connectionId, schema).catch(() => null));
      toast.success(`${editing ? "Changed" : "Declared"}. It reaches readers when the release is published.`);
    } catch (e) {
      toast.error(...refusal("Not declared", e));
    } finally { setBusy(""); }
  };

  const publish = async () => {
    if (phase.at !== "declared") return;
    setBusy("publish");
    try {
      const out = await publishRelease(connectionId, schema);
      setPhase({ at: "published", id: phase.id, release: out.number });
      onPublished?.();
      toast.success(`Published as release ${out.number}.`);
    } catch (e) {
      toast.error(...refusal("Not published", e));
    } finally { setBusy(""); }
  };

  const segment = preview?.creates.find(c => c.kind === "segment");
  const startCockpit = async () => {
    if (phase.at !== "published" || !segment) return;
    setBusy("cockpit");
    try {
      await keepNewCockpit(connectionId, draft.name, processCockpitSpec(draft.name, phase.id, cands?.entity ?? draft.entity, segment.name),
        `Started from the process ${draft.name.trim()}`);
      requestTab("cockpit", { conn: connectionId });
    } catch (e) {
      toast.error("The cockpit was not made", { description: errorText(e).slice(0, 240) });
    } finally { setBusy(""); }
  };

  const stateLabel = phase.at === "draft" ? "Draft · not published"
    : phase.at === "declared" ? "Declared · waiting for the release" : `Published in release ${phase.release}`;

  return (
    <div data-testid="process-designer" style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "14px 18px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <span className="aug-fs-xs" style={{ ...HINT, display: "inline-flex", alignItems: "center", gap: 4, whiteSpace: "nowrap" }}>
          Ontology <Icon name="chevr" size={11} /> Processes <Icon name="chevr" size={11} />
        </span>
        <span style={{ fontWeight: 500, color: "var(--t1)" }}>
          {editing ? `Change ${editing.display_name}` : draft.name.trim() || "New process"}
        </span>
        <span className="aug-tag aug-tag-gray" data-testid="designer-state">{stateLabel}</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {phase.at === "draft" && !editing && (
            <Button size="xs" variant="ghost" onClick={() => toast.success(keepDraft(connectionId, schema, draft)
              ? "Draft kept in this browser." : "This browser would not keep the draft.")}>Save draft</Button>
          )}
          {phase.at === "draft" && (
            <Button size="xs" variant="secondary" data-testid="designer-review" onClick={() => setReviewing(true)}>
              {editing ? "Review the change" : "Review and publish"}
            </Button>
          )}
          <Button size="xs" variant="ghost" onClick={onClose}>Close</Button>
        </span>
      </div>
      {restored && phase.at === "draft" && (
        <p className="aug-fs-xs" style={{ ...HINT, margin: "-6px 0 10px" }}>
          Your draft, as this browser kept it.{" "}
          <Button size="xs" variant="minimal" onClick={() => { dropDraft(connectionId, schema); setDraft(emptyDraft(entity ?? "")); }}>
            Start over
          </Button>
        </p>
      )}

      {reviewing && phase.at === "draft" && (
        <Callout tone={problem || openAsks.length ? "amber" : "blue"} style={{ marginBottom: 12 }} data-testid="designer-review-panel">
          <div className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {problem ? <span>Not ready to publish: {problem}</span> : (
              <>
                <span>
                  {editing ? "Saving the change to " : "Declaring "}<b>{draft.name.trim()}</b>{" "}counts it once more and writes it to the draft of this connection&apos;s
                  ontology; it reaches the agent, the Briefing and cockpits when the release is published.
                  {openAsks.length > 0 && ` ${openAsks.length === 1 ? "One question below is" : `${openAsks.length} questions below are`} not answered — the numbers would be published as they stand.`}
                </span>
                <span style={{ display: "flex", gap: 6 }}>
                  <Button size="xs" disabled={!!busy || counting} data-testid="designer-declare" onClick={() => void declare()}>
                    {busy === "declare" ? (editing ? "Saving…" : "Declaring…")
                      : editing ? (openAsks.length ? "Save it anyway" : "Save the change")
                      : openAsks.length ? "Declare it anyway" : "Declare the process"}
                  </Button>
                  <Button size="xs" variant="ghost" onClick={() => setReviewing(false)}>Not yet</Button>
                </span>
              </>
            )}
          </div>
        </Callout>
      )}
      {phase.at === "declared" && (
        <Callout tone="blue" style={{ marginBottom: 12 }} data-testid="designer-release">
          <div className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span>
              Declared. Readers get it with the next release
              {release ? ` — release ${(release.published?.number ?? 0) + 1}, which holds ${release.draft.length === 1 ? "this change" : `${release.draft.length} changes waiting, this one among them`}.` : "."}
              {" "}The release strip above lists everything waiting.
            </span>
            <span><Button size="xs" disabled={!!busy} data-testid="designer-publish" onClick={() => void publish()}>
              {busy === "publish" ? "Publishing…" : `Publish release ${(release?.published?.number ?? 0) + 1}`}
            </Button></span>
          </div>
        </Callout>
      )}

      <section style={{ ...CARD, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
        <div>
          <p className="aug-fs-xs" style={LABEL}>Process name</p>
          <Input value={draft.name} placeholder="Order delivery" aria-label="Process name" disabled={phase.at !== "draft"}
            onChange={e => edit({ name: e.target.value })} />
          <p className="aug-fs-xs" style={{ ...HINT, margin: "4px 0 0" }}>
            {declaredId ? <>id <span style={{ fontFamily: "var(--font-mono)" }}>{declaredId}</span>, made for you</> : "an id is made from the name"}
          </p>
        </div>
        <div>
          <p className="aug-fs-xs" style={LABEL}>What moves through it</p>
          <SelectField value={draft.entity} aria-label="What moves through the process" disabled={phase.at !== "draft" || !!editing}
            onChange={e => edit({ entity: e.target.value, stages: [{ ...EMPTY_STAGE }, { ...EMPTY_STAGE }], leaves: null, late: [] })}>
            <option value="">Choose a type…</option>
            {types.filter(t => !t.absorbed_into).map(t => (
              <option key={t.id} value={t.id}>{t.display_name || t.id}{t.rows != null ? ` · ${formatCount(t.rows)}` : ""}</option>
            ))}
          </SelectField>
          <p className="aug-fs-xs" style={{ ...HINT, margin: "4px 0 0" }}>
            {cands ? `${formatCount(cands.objects)} objects${cands.table ? ` · ${cands.table}` : ""}`
              : candsProblem ? candsProblem : draft.entity ? "Reading the data…" : "the objects each stage counts"}
          </p>
        </div>
        <div>
          <p className="aug-fs-xs" style={LABEL}>Owner</p>
          <Input value={draft.owner} placeholder="Logistics operations" aria-label="Process owner" disabled={phase.at !== "draft"}
            onChange={e => edit({ owner: e.target.value })} />
          <p className="aug-fs-xs" style={{ ...HINT, margin: "4px 0 0" }}>answers for its promises</p>
        </div>
        <div style={{ gridColumn: "1 / -1" }}>
          <Textarea value={draft.description} rows={2} placeholder="What the process is, in a sentence a new colleague would understand"
            aria-label="Process description" disabled={phase.at !== "draft"} onChange={e => edit({ description: e.target.value })} />
        </div>
      </section>

      <section style={CARD} data-testid="designer-stages">
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 500, color: "var(--t1)" }}>Stages</span>
          <span className="aug-fs-xs" style={HINT}>counted on the data as you build</span>
          <span className="aug-fs-xs" style={{ marginLeft: "auto", color: problem ? "var(--t2)" : "var(--t3)" }} data-testid="designer-status">
            {problem ? problem : counting ? "Counting on the data…" : countProblem ? `Could not be counted: ${countProblem}` : preview ? "Counted" : ""}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "stretch", gap: 6, flexWrap: "wrap" }}>
          {draft.stages.map((s, i) => (
            <React.Fragment key={i}>
              {i > 0 && (
                <PromiseEditor stage={s} i={i} measured={measured?.stages[i]} moments={cands?.moments ?? []}
                  disabled={phase.at !== "draft"} onChange={promise => editStage(i, { promise })} />
              )}
              <StageCard stage={s} i={i} cands={cands} measured={measured?.stages[i]} objects={objects}
                removable={draft.stages.length > 2 && phase.at === "draft"} disabled={phase.at !== "draft"}
                onChange={change => editStage(i, change)}
                onRemove={() => setDraft(d => ({ ...d, stages: d.stages.filter((_, j) => j !== i) }))} />
            </React.Fragment>
          ))}
          {phase.at === "draft" && draft.stages.length < 12 && (
            <div style={{ display: "flex", alignItems: "center" }}>
              <Button size="xs" variant="ghost" onClick={() => addStage()}><Icon name="plus" size={12} /> Add a stage</Button>
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 12 }} data-testid="designer-exits">
          <span className="aug-fs-xs" style={LABEL}>Exits</span>
          {draft.leaves && draft.leaves.values.length > 0 ? (
            <span className="aug-tag aug-tag-gray">
              <Icon name="minus" size={11} /> {draft.leaves.property} is {draft.leaves.values.join(" or ")}
              {measured?.leaves?.left != null ? ` · ${formatCount(measured.leaves.left)} leave` : ""}
            </span>
          ) : <span className="aug-fs-xs" style={HINT}>none — every object stays in the process until it reaches the last stage</span>}
          {phase.at === "draft" && (
            <Button size="xs" variant="ghost" onClick={() => setExitOpen(o => !o)}>
              <Icon name={draft.leaves ? "edit" : "plus"} size={12} /> {draft.leaves ? "Change the exit" : "Add an exit"}
            </Button>
          )}
        </div>
        {exitOpen && phase.at === "draft" && (
          <ExitEditor cands={cands} leaves={draft.leaves} onChange={leaves => edit({ leaves })} onDone={() => setExitOpen(false)} />
        )}

        {phase.at === "draft" && suggestions.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 10 }} data-testid="designer-suggestions">
            <span className="aug-fs-xs" style={LABEL}>Suggested from your data</span>
            {suggestions.map(s => (
              <Button key={s.key} size="xs" variant="outline" onClick={() => addStage(s.stage)}>
                <Icon name="plus" size={11} /> {s.label}
              </Button>
            ))}
          </div>
        )}
        {cands?.unread.length ? (
          <p className="aug-fs-xs" style={{ ...HINT, margin: "8px 0 0" }}>Not read: {cands.unread.join("; ")}</p>
        ) : null}
      </section>

      {/* the last count's moves stay listed while a mark is counted again — the marks are the draft's own */}
      <MovesSection draft={draft} preview={counted?.preview ?? null} disabled={phase.at !== "draft"}
        onMark={(move, expected) => edit({ moves: toggledMoves(draft, counted?.preview.process.observed ?? [], move, expected) })} />

      <section style={CARD} data-testid="designer-checks">
        <div style={{ fontWeight: 500, color: "var(--t1)", marginBottom: 8 }}>Before you publish</div>
        {!preview ? (
          <p className="aug-fs-sm" style={{ ...HINT, margin: 0 }}>
            {problem ? "The checks run once the draft can be counted." : counting ? "Counting…" : "The checks appear here once the draft is counted."}
          </p>
        ) : checks.length === 0 ? (
          <p className="aug-fs-sm" style={{ ...HINT, margin: 0 }}>Nothing to ask about.</p>
        ) : withUniqueKeys(checks, c => c.id).map(([k, c]) => (
          <CheckRow key={k} check={c} late={draft.late.includes(c.id)} disabled={phase.at !== "draft"}
            sample={samples[c.id]} onShow={() => void show(c)}
            onLeft={() => { if (c.exit) { edit({ leaves: { property: c.exit.property, values: c.exit.values } }); setExitOpen(true); } }}
            onLate={() => edit({ late: [...draft.late, c.id] })}
            onUndo={() => edit({ late: draft.late.filter(x => x !== c.id) })} />
        ))}
      </section>

      <section style={CARD} data-testid="designer-creates">
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
          <span style={{ fontWeight: 500, color: "var(--t1)" }}>What it creates</span>
          <span className="aug-fs-xs" style={HINT}>ready to place on a cockpit once published</span>
        </div>
        {preview?.creates.length ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10 }}>
            {withUniqueKeys(preview.creates, c => c.name).map(([k, c]) => (
              <div key={k} style={TILE} data-testid="designer-create">
                <div className="aug-fs-xs" style={{ color: "var(--t2)" }}>
                  {c.kind === "segment" ? `Late ${c.noun}` : c.kind === "metric" ? `${upper(c.noun)} promise broken` : `${upper(c.noun)} duration`}
                </div>
                <div style={BIG}>
                  {c.kind === "segment" ? formatCount(c.value) : c.kind === "metric" ? pct(c.value, 1) : days(c.value)}
                </div>
                <div className="aug-fs-xs" style={HINT}>{c.says}</div>
                <div className="aug-fs-xs" style={{ ...HINT, fontFamily: "var(--font-mono)" }}>{c.name}</div>
              </div>
            ))}
          </div>
        ) : <p className="aug-fs-sm" style={{ ...HINT, margin: 0 }}>A promise on a stage makes a list of what is late, its rate and its typical duration.</p>}
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
          <Button size="xs" variant="outline" data-testid="designer-cockpit" disabled={phase.at !== "published" || !segment || !!busy}
            onClick={() => void startCockpit()}>
            <Icon name="gauge" size={12} /> {busy === "cockpit" ? "Making it…" : "Start a cockpit for this process"}
          </Button>
          {phase.at !== "published" && (
            <span className="aug-fs-xs" style={HINT}>
              {!segment ? "A cockpit needs a promise to list what is late." : "Publish the process first — a cockpit reads what is published."}
            </span>
          )}
        </div>
      </section>
    </div>
  );
}

function StageCard({ stage, i, cands, measured, objects, removable, disabled, onChange, onRemove }: {
  stage: StageDraft;
  i: number;
  cands: ProcessCandidates | null;
  measured?: ProcessPreview["process"]["stages"][number];
  objects: number | null;
  removable: boolean;
  disabled: boolean;
  onChange: (change: Partial<StageDraft>) => void;
  onRemove: () => void;
}) {
  const anchor = stage.anchor;
  const value = !anchor ? "" : anchor.kind === "moment" ? `m:${anchor.path}` : `s:${anchor.property}`;
  const state = anchor?.kind === "state" ? cands?.states.find(s => s.property === anchor.property) : undefined;
  const pick = (v: string) => {
    if (!v) return onChange({ anchor: null });
    if (v.startsWith("m:")) {
      const promise = stage.promise;
      return onChange({ anchor: { kind: "moment", path: v.slice(2) }, promise });
    }
    return onChange({ anchor: { kind: "state", property: v.slice(2), values: [] }, promise: null });
  };
  return (
    <div style={{ ...TILE, width: 210, display: "flex", flexDirection: "column", gap: 6 }} data-testid="designer-stage">
      <Input value={stage.label} placeholder={i === 0 ? "Placed" : i === 1 ? "Shipped" : "Delivered"} disabled={disabled}
        aria-label={`Stage ${i + 1} name`} onChange={e => onChange({ label: e.target.value })} />
      <SelectField value={value} aria-label={`When an object reaches stage ${i + 1}`} disabled={disabled || !cands}
        onChange={e => pick(e.target.value)}>
        <option value="">{cands ? "When is it reached?" : "Choose a type first"}</option>
        <optgroup label="When a moment is set">
          {(cands?.moments ?? []).map(m => (
            <option key={m.path} value={`m:${m.path}`}>{momentLabel(m)} · {formatCount(m.set)}</option>
          ))}
        </optgroup>
        <optgroup label="When a status is">
          {(cands?.states ?? []).map(s => <option key={s.property} value={`s:${s.property}`}>{s.label} is…</option>)}
        </optgroup>
      </SelectField>
      {state && anchor?.kind === "state" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {withUniqueKeys(state.values.filter(v => v.value), v => String(v.value)).map(([k, v]) => (
            <label key={k} className="aug-fs-xs" style={{ display: "flex", gap: 6, alignItems: "center", color: "var(--t2)" }}>
              <Checkbox checked={anchor.values.includes(String(v.value))} disabled={disabled}
                aria-label={`${state.label} is ${v.value}`}
                onChange={e => onChange({ anchor: { ...anchor, values: e.target.checked
                  ? [...anchor.values, String(v.value)] : anchor.values.filter(x => x !== v.value) } })} />
              {v.value} · {formatCount(v.objects)}
            </label>
          ))}
        </div>
      )}
      <div>
        <div style={BIG} data-testid="designer-reached">{measured?.reached != null ? formatCount(measured.reached) : "—"}</div>
        <div className="aug-fs-xs" style={HINT}>
          {measured?.reached != null && objects ? `${pct(measured.reached / objects, 0)} reach it` : "reach it"}
        </div>
      </div>
      {removable && (
        <span><Button size="xs" variant="ghost" onClick={onRemove}>Remove</Button></span>
      )}
    </div>
  );
}

function PromiseEditor({ stage, i, measured, moments, disabled, onChange }: {
  stage: StageDraft;
  i: number;
  measured?: ProcessPreview["process"]["stages"][number];
  moments: ProcessMoment[];
  disabled: boolean;
  onChange: (promise: PromiseDraft | null) => void;
}) {
  const p = stage.promise;
  const kind = p?.kind ?? "";
  const set = (k: string) => {
    if (!k) return onChange(null);
    if (k === "deadline") return onChange({ kind: "deadline", deadline: "", name: p?.name ?? "", target: p?.target ?? "" });
    return onChange({ kind: k as "days" | "hours", amount: p && p.kind !== "deadline" ? p.amount : "", name: p?.name ?? "", target: p?.target ?? "" });
  };
  const rate = measured?.promise?.breach_rate;
  return (
    <div style={{ width: 150, display: "flex", flexDirection: "column", justifyContent: "center", gap: 4 }} data-testid="designer-promise">
      <div className="aug-fs-xs" style={{ ...HINT, textAlign: "center" }}>
        {measured?.p50_days != null ? `${days(measured.p50_days)} median` : ""} <Icon name="next" size={11} />
      </div>
      <SelectField value={kind} aria-label={`Promise on stage ${i + 1}`} disabled={disabled} onChange={e => set(e.target.value)}>
        <option value="">no promise</option>
        <option value="days">within days</option>
        <option value="hours">within hours</option>
        <option value="deadline">by a deadline</option>
      </SelectField>
      {p && p.kind !== "deadline" && (
        <Input value={p.amount} inputMode="numeric" placeholder={p.kind === "hours" ? "24" : "5"} disabled={disabled}
          aria-label={`Promise on stage ${i + 1}, ${p.kind}`} onChange={e => onChange({ ...p, amount: e.target.value })} />
      )}
      {p && p.kind === "deadline" && (
        <SelectField value={p.deadline} aria-label={`Promise on stage ${i + 1}, deadline`} disabled={disabled}
          onChange={e => onChange({ ...p, deadline: e.target.value })}>
          <option value="">the deadline…</option>
          {moments.map(m => <option key={m.path} value={m.path}>{momentLabel(m)}</option>)}
        </SelectField>
      )}
      {p && (
        <Input value={p.name} placeholder={`called ${idFrom(stage.label) || "delivery"}`} disabled={disabled}
          aria-label={`Promise on stage ${i + 1}, name`} onChange={e => onChange({ ...p, name: e.target.value })} />
      )}
      {p && (
        <Input value={p.target} inputMode="decimal" placeholder="target % kept (optional)" disabled={disabled}
          aria-label={`Promise on stage ${i + 1}, target`} onChange={e => onChange({ ...p, target: e.target.value })} />
      )}
      {p && rate != null && (
        <div className="aug-fs-xs" style={{ textAlign: "center", color: "var(--t2)" }} data-testid="designer-breach">
          {pct(rate, 1)} of those that reached it late
        </div>
      )}
    </div>
  );
}

function ExitEditor({ cands, leaves, onChange, onDone }: {
  cands: ProcessCandidates | null;
  leaves: ProcessDraft["leaves"];
  onChange: (leaves: ProcessDraft["leaves"]) => void;
  onDone: () => void;
}) {
  const states = cands?.states ?? [];
  const property = leaves?.property ?? states[0]?.property ?? "";
  const state = states.find(s => s.property === property);
  const values = leaves?.property === property ? leaves.values : [];
  return (
    <div style={{ ...TILE, marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }} data-testid="designer-exit-editor">
      <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>
        An object leaves the process when this property holds one of these values — it is then never open, and never late.
      </span>
      <SelectField value={property} aria-label="The property an object leaves by"
        onChange={e => onChange({ property: e.target.value, values: [] })}>
        {states.map(s => <option key={s.property} value={s.property}>{s.label}</option>)}
      </SelectField>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {withUniqueKeys((state?.values ?? []).filter(v => v.value), v => String(v.value)).map(([k, v]) => (
          <label key={k} className="aug-fs-xs" style={{ display: "flex", gap: 6, alignItems: "center", color: "var(--t2)" }}>
            <Checkbox checked={values.includes(String(v.value))} aria-label={`Leaves when ${property} is ${v.value}`}
              onChange={e => onChange({ property, values: e.target.checked ? [...values, String(v.value)]
                : values.filter(x => x !== v.value) })} />
            {v.value} · {formatCount(v.objects)}
          </label>
        ))}
      </div>
      <span style={{ display: "flex", gap: 6 }}>
        <Button size="xs" variant="ghost" onClick={onDone}>Done</Button>
        {leaves && <Button size="xs" variant="ghost" onClick={() => { onChange(null); onDone(); }}>Remove the exit</Button>}
      </span>
    </div>
  );
}

function CheckRow({ check, late, disabled, sample, onShow, onLeft, onLate, onUndo }: {
  check: DesignCheck;
  late: boolean;
  disabled: boolean;
  sample?: ObjectListingPage | string;
  onShow: () => void;
  onLeft: () => void;
  onLate: () => void;
  onUndo: () => void;
}) {
  if (check.level === "ok") {
    return (
      <div className="aug-fs-sm" style={{ display: "flex", gap: 6, alignItems: "baseline", color: "var(--t2)", margin: "4px 0" }}
        data-testid="designer-check" data-level="ok">
        <Icon name="check" size={13} /> {check.says}
      </div>
    );
  }
  if (late) {
    return (
      <div className="aug-fs-sm" style={{ color: "var(--t3)", margin: "4px 0" }} data-testid="designer-check" data-level="answered">
        You said these are really late. {check.says}{" "}
        {!disabled && <Button size="xs" variant="minimal" onClick={onUndo}>Undo</Button>}
      </div>
    );
  }
  const exit = check.exit;
  return (
    <Callout tone={check.level === "error" ? "red" : "amber"} style={{ marginBottom: 8 }} data-testid="designer-check" data-level={check.level}>
      <div className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span><Icon name={check.level === "error" ? "alert" : "warning"} size={13} /> {check.says}</span>
        {check.level === "ask" && exit && (
          <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>
            {exit.label} is {exit.values.join(" or ")} for {formatCount(exit.explains)} of the {formatCount(exit.of)}. Declared as
            the way they left, it would also take out {formatCount(exit.recent)} waiting less than a year.
          </span>
        )}
        <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {check.level === "ask" && !disabled && (
            <>
              <Button size="xs" variant="outline" disabled={!exit} title={exit ? undefined : "No status explains them — add an exit by hand"}
                onClick={onLeft}>They left the process</Button>
              <Button size="xs" variant="outline" onClick={onLate}>They really are late</Button>
            </>
          )}
          {check.show && (
            <Button size="xs" variant="outline" onClick={onShow}>{check.level === "ask" ? "Show me 20 of them" : "Show them"}</Button>
          )}
        </span>
        {sample === "loading" && <span className="aug-fs-xs" style={HINT}>Listing them…</span>}
        {typeof sample === "string" && sample !== "loading" && <span className="aug-fs-xs" style={HINT}>{sample}</span>}
        {sample && typeof sample !== "string" && <Sample page={sample} />}
      </div>
    </Callout>
  );
}

function Sample({ page }: { page: ObjectListingPage }) {
  return (
    <div style={{ overflowX: "auto" }} data-testid="designer-sample">
      <table className="aug-fs-xs" style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>{withUniqueKeys(page.names, n => n).map(([k, n]) => (
            <th key={k} style={{ textAlign: "left", padding: "2px 8px", color: "var(--t2)", borderBottom: RULE }}>{n}</th>
          ))}</tr>
        </thead>
        <tbody>
          {withUniqueKeys(page.rows, r => String(r[0])).map(([k, r]) => (
            <tr key={k}>{r.map((cell, j) => (
              <td key={j} style={{ padding: "2px 8px", color: "var(--t1)", fontFamily: "var(--font-mono)" }}>{cell == null ? "—" : String(cell)}</td>
            ))}</tr>
          ))}
        </tbody>
      </table>
      {page.total != null && <span style={HINT}>{formatCount(page.total)} in all</span>}
    </div>
  );
}


/** Arc OC-5 — how objects move between the stages, as the data counts it, with the moves a person expects marked: none
 *  marked, each stage to the next is expected. A move the data makes that nobody expects, and one expected that never
 *  happens, are both said. */
function MovesSection({ draft, preview, disabled, onMark }: {
  draft: ProcessDraft;
  preview: ProcessPreview | null;
  disabled: boolean;
  onMark: (move: { from: string; to: string }, expected: boolean) => void;
}) {
  const observed = preview?.process.observed ?? [];
  const conformance = preview?.process.conformance ?? {};
  const label = (id: string) => (id === LEFT ? "leaves the process"
    : draft.stages.find(s => (s.id || idFrom(s.label)) === id)?.label.trim() || id);
  return (
    <section style={CARD} data-testid="designer-moves">
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 500, color: "var(--t1)" }}>How objects move</span>
        <span className="aug-fs-xs" style={HINT}>
          {draft.moves ? "the moves you expect are ticked" : "none marked — each stage to the next is expected"}
        </span>
      </div>
      {!observed.length ? (
        <p className="aug-fs-sm" style={{ ...HINT, margin: 0 }}>
          {preview ? "No moves between stages with a moment were counted." : "The moves appear once the draft is counted."}
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {withUniqueKeys(observed, m => `${m.from_stage}>${m.to_stage}`).map(([k, m]) => {
            const expected = draft.moves ? draft.moves.some(x => x.from === m.from_stage && x.to === m.to_stage) : m.declared;
            return (
            <label key={k} className="aug-fs-sm" data-testid="designer-move"
              style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--t1)" }}>
              <Checkbox checked={expected} disabled={disabled}
                aria-label={`Expect ${label(m.from_stage)} to ${label(m.to_stage)}`}
                onChange={e => onMark({ from: m.from_stage, to: m.to_stage }, e.target.checked)} />
              <span>{label(m.from_stage)} → {label(m.to_stage)}</span>
              <span className="aug-fs-xs" style={HINT}>{formatCount(m.objects)}</span>
              {!expected && !!m.objects && <span className="aug-tag aug-tag-amber">nobody expects it</span>}
              {expected && !m.objects && <span className="aug-tag aug-tag-gray">never happens</span>}
            </label>
            );
          })}
        </div>
      )}
      {!!conformance.untimed?.length && (
        <p className="aug-fs-xs" style={{ ...HINT, margin: "6px 0 0" }}>
          Not counted as moves: {conformance.untimed.join(", ")} — reached by a status, which has no moment.
        </p>
      )}
    </section>
  );
}
