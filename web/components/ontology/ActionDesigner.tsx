"use client";

/**
 * The action designer — a business action decided in words and read against the data before it is declared, on a page
 * of its own (the rail unchanged). Approved as drawn on 2026-10-09 after the usability walk-through (job 2,
 * `docs/USABILITY_WALKTHROUGH_2026-10-09.md`) found the declare form a developer's: fourteen inputs and seven dropdowns
 * mixing the decision with a webhook, a free-text box for what the action is about, three fields pre-filled with someone
 * else's refund rule, and nothing to say which objects a person could press it on.
 *
 * The decision comes first — what it is about (a type, chosen), what a press does, what the person pressing it says,
 * when it may be pressed (values the data holds, with their counts), who decides. A call to another system is its own
 * step, only for an action that makes one. As the draft changes it is read exactly as declaring would read it, with
 * nothing written (`POST /ontology/declared-actions/preview`): how many objects allow a press now, over all of them and
 * beside each cockpit that shows them one at a time, and a press dry-run on a real object. Declaring goes through the
 * existing door (and its approval gate); then the release; then the button goes onto the cockpits a person ticks.
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
import {
  conditionMessage, dropAction, emptyAction, keepAction, keptAction, notReady, oneOf, toActionSpec,
  type ActionDraft, type AskDraft, type AskType, type CallDraft, type ConditionDraft,
} from "@/lib/actionDraft";
import { getActionTriggers, getCockpit, getDeclaredActions, keepCockpit, listCockpits, type ActionTrigger } from "@/lib/api";
import { addAction } from "@/lib/cockpit/edit";
import { formatCount } from "@/lib/format";
import { requestTab } from "@/lib/navigate";
import { listObjects } from "@/lib/objects";
import {
  declareAction, getProcessCandidates, getRelease, getTypeMap, previewAction, publishRelease,
  type ActionPreview, type ProcessCandidates, type ReleaseState, type TypeMapRow,
} from "@/lib/objectTypes";
import { idFrom } from "@/lib/processDraft";

const RULE = "1px solid var(--b1)";
const CARD: React.CSSProperties = { border: RULE, borderRadius: "var(--r3)", padding: "12px 14px", marginBottom: 12 };
const HINT: React.CSSProperties = { color: "var(--t3)" };
const LABEL: React.CSSProperties = { color: "var(--t2)", margin: "0 0 4px" };
const STEP: React.CSSProperties = { color: "var(--t3)", fontWeight: 400, marginRight: 8 };
const SETTLE_MS = 900;
const ASK_TYPES: [AskType, string][] = [["text", "Text"], ["number", "Number"], ["yes_no", "Yes or no"], ["date", "Date"]];

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

function words(id: string): string {
  return id.replace(/_/g, " ");
}

/** A cockpit that shows the type's objects one at a time — where the action's button can sit. */
export interface ActionPlace {
  cockpitId: string;
  title: string;
  detailKey: string;
  tableKey: string;
  segment: string;
}

/** The places a cockpit spec offers for an action on ``entity``: each object detail beside a table of that type. */
export function placesIn(cockpitId: string, title: string, spec: unknown, entity: string[]): ActionPlace[] {
  const els = ((spec ?? {}) as { elements?: Record<string, { type: string; props?: Record<string, unknown> }> }).elements ?? {};
  const wanted = new Set(entity.filter(Boolean).map(e => e.toLowerCase()));
  return Object.entries(els).flatMap(([key, el]) => {
    if (el.type !== "ObjectDetail") return [];
    const tableKey = String(el.props?.follows ?? "");
    const table = els[tableKey];
    if (table?.type !== "ObjectTable" || !wanted.has(String(table.props?.entity ?? "").toLowerCase())) return [];
    return [{ cockpitId, title, detailKey: key, tableKey, segment: String(table.props?.segment ?? "") }];
  });
}

/** ``spec`` with the action's button in the detail and — for a mark — the mark as a column of the table it follows.
 *  A table that shows the type's default columns names none, so ``defaults`` — the columns the listing door read for
 *  it — are written out with the mark after them; without them the mark would never show (Order shipping, 2026-10-09). */
export function withAction(spec: unknown, place: ActionPlace, actionId: string, markProperty: string,
  defaults: string[] = []): unknown {
  const s = addAction(spec, place.detailKey, actionId) as unknown as { elements: Record<string, { props: Record<string, unknown> }> };
  const table = s.elements[place.tableKey];
  if (!table || !markProperty) return s;
  const columns = Array.isArray(table.props.columns) ? (table.props.columns as string[]) : defaults;
  if (columns.length && !columns.includes(markProperty)) table.props.columns = [...columns, markProperty];
  return s;
}

/** The columns a table that names none shows — what the listing door reads for it — or [] when it cannot be read. */
async function defaultColumns(connectionId: string, schema: string | undefined, entity: string, segment: string): Promise<string[]> {
  try {
    const page = await listObjects({ entity, ...(segment ? { segment } : {}), limit: 1 }, connectionId, schema);
    return page.path === "listed" ? page.columns.map(c => c.path) : [];
  } catch {
    return [];
  }
}

type Phase = { at: "draft" } | { at: "declared"; id: string } | { at: "published"; id: string; release: number }
  | { at: "placed"; id: string; release: number; on: string[] };

export function ActionDesigner({ connectionId, schema, types, entity, within = "Ontology", onClose, onDeclared, onPublished }: {
  connectionId: string;
  schema?: string;
  /** The types to choose from — read here when the caller has none. */
  types?: TypeMapRow[];
  /** The type a person started from, when they did. */
  entity?: string;
  /** Where the page sits, for the breadcrumb. */
  within?: string;
  onClose: () => void;
  onDeclared?: (actionId: string) => void;
  onPublished?: () => void;
}) {
  const [fetchedTypes, setFetchedTypes] = useState<TypeMapRow[]>([]);
  const rows = types ?? fetchedTypes;
  const label = (id: string) => rows.find(t => t.id === id)?.display_name ?? id;
  const [draft, setDraft] = useState<ActionDraft>(() => {
    const kept = keptAction(connectionId, schema);
    return kept && (!entity || kept.entity === entity) ? kept : emptyAction(entity ?? "", entity ?? "");
  });
  const [restored] = useState(() => !!keptAction(connectionId, schema) && draft.name !== "");
  // Read per type and kept under the type read — a reading of another type is never shown beside this one.
  const [candsRead, setCandsRead] = useState<{ entity: string; cands: ProcessCandidates | null } | null>(null);
  const [declared, setDeclared] = useState<Record<string, { name: string; takes: string[] }>>({});
  // The destinations saved in Notifications — who a press may tell.
  const [destinations, setDestinations] = useState<ActionTrigger[] | null>(null);
  const [placesRead, setPlacesRead] = useState<{ entity: string; places: ActionPlace[] } | null>(null);
  const [ticked, setTicked] = useState<Record<string, boolean>>({});
  const [said, setSaid] = useState<Record<string, string>>({});
  const [counted, setCounted] = useState<{ key: string; preview: ActionPreview } | null>(null);
  const [counting, setCounting] = useState(false);
  const [countProblem, setCountProblem] = useState("");
  const [phase, setPhase] = useState<Phase>({ at: "draft" });
  const [release, setRelease] = useState<ReleaseState | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [busy, setBusy] = useState("");
  const asked = useRef(0);
  const drafting = phase.at === "draft";

  const edit = (change: Partial<ActionDraft>) => setDraft(d => ({ ...d, ...change }));
  const editAsk = (i: number, change: Partial<AskDraft>) => setDraft(d => ({ ...d, asks: d.asks.map((a, j) => (j === i ? { ...a, ...change } : a)) }));
  const editCondition = (i: number, change: Partial<ConditionDraft>) =>
    setDraft(d => ({ ...d, conditions: d.conditions.map((c, j) => (j === i ? { ...c, ...change } : c)) }));
  const editCall = (change: Partial<CallDraft>) => setDraft(d => ({ ...d, call: { ...d.call, ...change } }));

  useEffect(() => {
    if (types) return;
    let live = true;
    getTypeMap(connectionId, schema).then(m => { if (live) setFetchedTypes(m.object_types ?? []); }).catch(() => { /* the type is chosen by its id */ });
    return () => { live = false; };
  }, [connectionId, schema, types]);

  // The ids already declared — a new action is never named like one, and an undo is chosen from them.
  useEffect(() => {
    let live = true;
    getDeclaredActions(connectionId, schema)
      .then(all => { if (live) setDeclared(Object.fromEntries(Object.values(all).map(a => [a.id, { name: a.display_name || words(a.id), takes: a.params.map(p => p.name) }]))); })
      .catch(() => { /* an id is still checked by the preview door, which answers 409 for one taken */ });
    return () => { live = false; };
  }, [connectionId, schema]);

  useEffect(() => {
    if (draft.does !== "tell" || destinations) return;
    let live = true;
    getActionTriggers().then(all => { if (live) setDestinations(all); }).catch(() => { if (live) setDestinations([]); });
    return () => { live = false; };
  }, [draft.does, destinations]);

  // What the type carries — its count and the values its state-like properties hold, read when the type is chosen.
  useEffect(() => {
    if (!draft.entity) return;
    let live = true;
    const entity = draft.entity;
    getProcessCandidates(connectionId, entity, schema)
      .then(c => { if (live) setCandsRead({ entity, cands: c }); })
      .catch(() => { if (live) setCandsRead({ entity, cands: null }); });
    return () => { live = false; };
  }, [connectionId, schema, draft.entity]);
  const cands = candsRead?.entity === draft.entity ? candsRead.cands : null;

  // The cockpits that show the type's objects one at a time — where the button can sit.
  useEffect(() => {
    if (!draft.entity) return;
    let live = true;
    const entity = draft.entity;
    const names = [draft.entity, draft.entityLabel, cands?.api_name ?? "", cands?.entity ?? ""];
    listCockpits(connectionId)
      .then(async list => {
        const found: ActionPlace[] = [];
        for (const c of (list?.cockpits ?? []).filter(c => !c.retired)) {
          const read = await getCockpit(connectionId, c.cockpit_id).catch(() => null);
          if (read) found.push(...placesIn(c.cockpit_id, c.title || c.cockpit_id, read.cockpit.spec, names));
        }
        if (live) { setPlacesRead({ entity, places: found }); setTicked(Object.fromEntries(found.map(p => [`${p.cockpitId}/${p.detailKey}`, true]))); }
      })
      .catch(() => { if (live) setPlacesRead({ entity, places: [] }); });
    return () => { live = false; };
  }, [connectionId, draft.entity, draft.entityLabel, cands?.api_name, cands?.entity]);
  const places = useMemo(() => (placesRead?.entity === draft.entity ? placesRead.places : []), [placesRead, draft.entity]);

  const problem = notReady(draft);
  const taken = useMemo(() => Object.keys(declared), [declared]);
  const undoTakes = declared[draft.call.undoAction]?.takes;
  const made = useMemo(() => (problem ? null : toActionSpec(draft, taken, undoTakes)), [draft, problem, taken, undoTakes]);
  const segments = [...new Set(places.map(p => p.segment).filter(Boolean))];
  const ask = made ? { id: made.id, action: made.spec, segments, said } : null;
  const askKey = ask ? JSON.stringify(ask) : "";

  // Read as declaring would read it, once the draft rests — nothing is written. Keyed by what is asked, so a render that
  // changes nothing the declaration says does not read it again.
  useEffect(() => {
    if (!askKey || !drafting) return;
    const asking = JSON.parse(askKey) as NonNullable<typeof ask>;
    const n = ++asked.current;
    const t = setTimeout(() => {
      setCounting(true);
      setCountProblem("");
      previewAction(connectionId, asking, schema)
        .then(p => { if (n === asked.current) setCounted({ key: JSON.stringify(asking), preview: p }); })
        .catch(e => { if (n === asked.current) { setCounted(null); setCountProblem(errorText(e)); } })
        .finally(() => { if (n === asked.current) setCounting(false); });
    }, SETTLE_MS);
    return () => clearTimeout(t);
  }, [connectionId, schema, askKey, drafting]);

  // Once declared, the reading is the declaration's own — its id is taken now, and the re-derived id must not hide it.
  const preview = counted && (!drafting || counted.key === askKey) ? counted.preview : null;
  const entityLabel = draft.entityLabel || label(draft.entity) || "object";
  const plural = `${entityLabel.toLowerCase()}s`;
  const actionId = phase.at === "draft" ? made?.id ?? "" : phase.id;
  const markProperty = draft.does === "mark" ? idFrom(draft.mark.label) : "";
  const unused = (cands?.states ?? []).filter(s => !draft.conditions.some(c => c.property === s.property));
  const segmentOf = (name: string) => preview?.segments.find(s => s.segment === name);
  const narrow = (preview?.segments ?? []).filter(s => s.allowed != null && s.allowed < s.objects);

  const declare = async () => {
    if (!made) return;
    setBusy("declare");
    try {
      await declareAction(connectionId, made.id, made.spec, schema);
      dropAction(connectionId, schema);
      setPhase({ at: "declared", id: made.id });
      setReviewing(false);
      onDeclared?.(made.id);
      setRelease(await getRelease(connectionId, schema).catch(() => null));
      toast.success("Declared. It reaches cockpits and the agent when the release is published.");
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

  const chosen = places.filter(p => ticked[`${p.cockpitId}/${p.detailKey}`]);
  const place = async () => {
    if (phase.at !== "published" || !chosen.length) return;
    setBusy("place");
    const on: string[] = [];
    try {
      for (const cockpitId of [...new Set(chosen.map(p => p.cockpitId))]) {
        const read = await getCockpit(connectionId, cockpitId);
        let spec: unknown = read.cockpit.spec;
        const els = (spec as { elements: Record<string, { props?: Record<string, unknown> }> }).elements;
        for (const p of chosen.filter(c => c.cockpitId === cockpitId)) {
          const named = Array.isArray(els[p.tableKey]?.props?.columns);
          const defaults = markProperty && !named
            ? await defaultColumns(connectionId, schema, String(els[p.tableKey]?.props?.entity ?? draft.entity), p.segment) : [];
          spec = withAction(spec, p, phase.id, markProperty, defaults);
        }
        await keepCockpit(connectionId, cockpitId, spec, `Added the action ${draft.name.trim()}`);
        on.push(chosen.find(c => c.cockpitId === cockpitId)?.title ?? cockpitId);
      }
      setPhase({ at: "placed", id: phase.id, release: phase.release, on });
    } catch (e) {
      toast.error(on.length ? `Added to ${on.join(", ")}, and not to the rest` : "The button was not added", { description: errorText(e).slice(0, 240) });
      if (on.length) setPhase({ at: "placed", id: phase.id, release: phase.release, on });
    } finally { setBusy(""); }
  };

  const openCockpit = (cockpitId: string) => {
    try { localStorage.setItem(`aughor:cockpit:${connectionId}`, cockpitId); } catch { /* the cockpit opens on its own tab */ }
    requestTab("cockpit", { conn: connectionId });
  };

  const stateLabel = phase.at === "draft" ? "Draft · not declared" : phase.at === "declared" ? "Declared · waiting for the release"
    : phase.at === "published" ? `Published in release ${phase.release}` : `On ${phase.on.join(", ")}`;
  const sample = preview?.sample;

  return (
    <div data-testid="action-designer" style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "14px 18px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <span className="aug-fs-xs" style={{ ...HINT, display: "inline-flex", alignItems: "center", gap: 4, whiteSpace: "nowrap" }}>
          {within && <>{within} <Icon name="chevr" size={11} /></>} Actions <Icon name="chevr" size={11} />
        </span>
        <span style={{ fontWeight: 500, color: "var(--t1)" }}>{draft.name.trim() || "New action"}</span>
        <span className="aug-tag aug-tag-gray" data-testid="action-designer-state">{stateLabel}</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {drafting && (
            <Button size="xs" variant="ghost" onClick={() => toast.success(keepAction(connectionId, schema, draft)
              ? "Draft kept in this browser — without its credential." : "This browser would not keep the draft.")}>Save draft</Button>
          )}
          {drafting && (
            <Button size="xs" variant="secondary" data-testid="action-review" onClick={() => setReviewing(true)}>Review and declare</Button>
          )}
          <Button size="xs" variant="ghost" onClick={onClose}>Close</Button>
        </span>
      </div>
      {drafting && (
        <p className="aug-fs-xs" style={{ margin: "-6px 0 10px", color: problem ? "var(--t2)" : "var(--t3)" }} data-testid="action-designer-status">
          {problem || (counting ? "Reading the draft against the data…" : "Ready to declare — nothing is written until you do.")}
        </p>
      )}
      {restored && drafting && (
        <p className="aug-fs-xs" style={{ ...HINT, margin: "-6px 0 10px" }}>
          Your draft, as this browser kept it.{" "}
          <Button size="xs" variant="minimal" onClick={() => { dropAction(connectionId, schema); setDraft(emptyAction(entity ?? "", entity ?? "")); }}>
            Start over
          </Button>
        </p>
      )}

      {reviewing && drafting && (
        <Callout tone={problem ? "amber" : "blue"} style={{ marginBottom: 12 }} data-testid="action-review-panel">
          <div className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {problem ? <span>Not ready to declare: {problem}</span> : (
              <>
                <span>
                  Declaring <b>{draft.name.trim()}</b>{" "}writes it to the draft of this connection&apos;s ontology; a press works once
                  the release is published. {draft.approval ? "Each press waits for a person to approve it." : "A press runs at once."}
                </span>
                <span style={{ display: "flex", gap: 6 }}>
                  <Button size="xs" disabled={!!busy} data-testid="action-declare" onClick={() => void declare()}>
                    {busy === "declare" ? "Declaring…" : "Declare the action"}
                  </Button>
                  <Button size="xs" variant="ghost" onClick={() => setReviewing(false)}>Not yet</Button>
                </span>
              </>
            )}
          </div>
        </Callout>
      )}
      {phase.at === "declared" && (
        <Callout tone="blue" style={{ marginBottom: 12 }} data-testid="action-release">
          <div className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span>
              Declared. A press works once the release is published
              {release ? ` — release ${(release.published?.number ?? 0) + 1}, which holds ${release.draft.length === 1 ? "this change" : `${release.draft.length} changes waiting, this one among them`}.` : "."}
            </span>
            <span><Button size="xs" disabled={!!busy} data-testid="action-publish" onClick={() => void publish()}>
              {busy === "publish" ? "Publishing…" : `Publish release ${(release?.published?.number ?? 0) + 1}`}
            </Button></span>
          </div>
        </Callout>
      )}
      {phase.at === "placed" && (
        <Callout tone="blue" style={{ marginBottom: 12 }} data-testid="action-placed">
          <span className="aug-fs-sm">
            The button is on {phase.on.join(", ")}.{" "}
            <Button size="xs" variant="minimal" onClick={() => openCockpit(chosen[0]?.cockpitId ?? "")}>Open {phase.on[0]}</Button>
          </span>
        </Callout>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.5fr) minmax(280px, 1fr)", gap: 14, alignItems: "start" }}>
        <div>
          <section style={CARD}>
            <p className="aug-fs-sm" style={{ ...LABEL, color: "var(--t1)", fontWeight: 500 }}><span style={STEP}>1</span>Name it</p>
            <Input value={draft.name} placeholder="Escalate to carrier" aria-label="Action name" disabled={!drafting}
              onChange={e => edit({ name: e.target.value })} />
            <Textarea value={draft.description} rows={2} style={{ marginTop: 6 }} disabled={!drafting} aria-label="What the action is for"
              placeholder="When an order has waited past the dispatch promise, hand it to the carrier team with the reason."
              onChange={e => edit({ description: e.target.value })} />
            {actionId && <p className="aug-fs-xs" style={{ ...HINT, margin: "6px 0 0" }}>Its id is made for you: {actionId}</p>}
          </section>

          <section style={CARD}>
            <p className="aug-fs-sm" style={{ ...LABEL, color: "var(--t1)", fontWeight: 500 }}><span style={STEP}>2</span>What it&apos;s about</p>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <SelectField value={draft.entity} aria-label="What the action is about" disabled={!drafting}
                onChange={e => edit({ entity: e.target.value, entityLabel: label(e.target.value), conditions: [] })}>
                <option value="">Choose a type…</option>
                {rows.filter(t => !t.absorbed_into).map(t => (
                  <option key={t.id} value={t.id}>{t.display_name || t.id}{t.rows != null ? ` · ${formatCount(t.rows)}` : ""}</option>
                ))}
              </SelectField>
              {cands && <span className="aug-fs-xs" style={{ ...HINT, whiteSpace: "nowrap" }}>{formatCount(cands.objects)} {plural}</span>}
            </div>
          </section>

          <section style={CARD} data-testid="action-does">
            <p className="aug-fs-sm" style={{ ...LABEL, color: "var(--t1)", fontWeight: 500 }}><span style={STEP}>3</span>What a press does</p>
            <Choice on={draft.does === "mark"} disabled={!drafting} icon="bookmark" title={`Mark the ${entityLabel.toLowerCase()}`}
              says="Records a mark on it. Your warehouse isn't changed, and a mark can be withdrawn." onPick={() => edit({ does: "mark" })} />
            {draft.does === "mark" && (
              <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 6, margin: "2px 0 8px 26px" }}>
                <Input value={draft.mark.label} placeholder="Escalated to carrier" aria-label="The mark's name" disabled={!drafting}
                  onChange={e => edit({ mark: { ...draft.mark, label: e.target.value } })} />
                <Input value={draft.mark.value} placeholder="yes" aria-label="What the mark reads" disabled={!drafting}
                  onChange={e => edit({ mark: { ...draft.mark, value: e.target.value } })} />
                <SelectField value={draft.mark.noteFrom} aria-label="The mark's note" disabled={!drafting} style={{ gridColumn: "1 / -1" }}
                  onChange={e => edit({ mark: { ...draft.mark, noteFrom: e.target.value } })}>
                  <option value="">No note</option>
                  {draft.asks.filter(a => idFrom(a.label)).map(a => (
                    <option key={idFrom(a.label)} value={idFrom(a.label)}>The person&apos;s {a.label.toLowerCase()} is kept as its note</option>
                  ))}
                </SelectField>
              </div>
            )}
            <Choice on={draft.does === "tell"} disabled={!drafting} icon="send" title="Tell someone"
              says="Sends a message to a destination saved in Notifications — a Slack channel, Jira, a webhook."
              onPick={() => edit({ does: "tell", approval: false })} />
            {draft.does === "tell" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, margin: "2px 0 8px 26px" }} data-testid="action-tell">
                {destinations !== null && destinations.length === 0 ? (
                  <p className="aug-fs-xs" style={{ ...HINT, margin: 0 }}>
                    No destination is saved yet. Set one up in Notifications, under Operations — then choose it here.
                  </p>
                ) : (
                  <SelectField value={draft.tell.destination} aria-label="Who is told" disabled={!drafting || destinations === null}
                    onChange={e => edit({ tell: { ...draft.tell, destination: e.target.value } })}>
                    <option value="">{destinations === null ? "Reading the destinations…" : "Choose a destination…"}</option>
                    {(destinations ?? []).map(t => (
                      <option key={t.id} value={t.id}>{t.name} · {t.type}{t.enabled ? "" : " · turned off"}</option>
                    ))}
                  </SelectField>
                )}
                <Textarea value={draft.tell.message} rows={2} aria-label="The message" disabled={!drafting}
                  placeholder={`${entityLabel} {${idFrom(entityLabel) || "object"}} needs the carrier: {reason}`}
                  onChange={e => edit({ tell: { ...draft.tell, message: e.target.value } })} />
                <span className="aug-fs-xs" style={HINT}>
                  An answer, or the {entityLabel.toLowerCase()} pressed on, goes in braces. A message cannot be unsent.
                </span>
              </div>
            )}
            <Choice on={draft.does === "analyse"} disabled={!drafting} icon="search" title="Start a deep analysis"
              says="Asks a question about this one, in a deep analysis — it spends model calls."
              onPick={() => edit({ does: "analyse", approval: true })} />
            {draft.does === "analyse" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, margin: "2px 0 8px 26px" }} data-testid="action-analysis">
                <Textarea value={draft.analysis.question} rows={2} aria-label="The question it asks" disabled={!drafting}
                  placeholder={`Why is ${entityLabel.toLowerCase()} {${idFrom(entityLabel) || "object"}} late? {reason}`}
                  onChange={e => edit({ analysis: { question: e.target.value } })} />
                <span className="aug-fs-xs" style={HINT}>An answer, or the {entityLabel.toLowerCase()} pressed on, goes in braces.</span>
              </div>
            )}
            <Choice on={draft.does === "call"} disabled={!drafting} icon="plug" title="Call another system"
              says="Sends it to a service such as your carrier's. Set up in step 7." onPick={() => edit({ does: "call", approval: true })} />
          </section>

          <section style={CARD}>
            <p className="aug-fs-sm" style={{ ...LABEL, color: "var(--t1)", fontWeight: 500 }}><span style={STEP}>4</span>What the person pressing it says</p>
            {draft.asks.map((a, i) => (
              <div key={`ask-${i}`} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
                <Input value={a.label} placeholder="Reason" aria-label={`Question ${i + 1}`} disabled={!drafting} style={{ flex: 2 }}
                  onChange={e => editAsk(i, { label: e.target.value })} />
                <SelectField value={a.type} aria-label={`Question ${i + 1} answer`} disabled={!drafting} style={{ flex: 1 }}
                  onChange={e => editAsk(i, { type: e.target.value as AskType })}>
                  {ASK_TYPES.map(([v, w]) => <option key={v} value={v}>{w}</option>)}
                </SelectField>
                <label className="aug-fs-xs" style={{ display: "flex", gap: 4, alignItems: "center", color: "var(--t2)", whiteSpace: "nowrap" }}>
                  <Checkbox checked={a.required} disabled={!drafting} aria-label={`Question ${i + 1} is required`}
                    onChange={e => editAsk(i, { required: e.target.checked })} /> Required
                </label>
                {drafting && (
                  <Button size="xs" variant="ghost" aria-label={`Take question ${i + 1} off`}
                    onClick={() => setDraft(d => ({ ...d, asks: d.asks.filter((_, j) => j !== i),
                      mark: d.mark.noteFrom === idFrom(a.label) ? { ...d.mark, noteFrom: "" } : d.mark }))}>
                    <Icon name="close" size={12} />
                  </Button>
                )}
              </div>
            ))}
            {drafting && draft.asks.length < 6 && (
              <Button size="xs" variant="ghost" onClick={() => edit({ asks: [...draft.asks, { label: "", type: "text", required: false }] })}>
                <Icon name="plus" size={12} /> Ask for something else
              </Button>
            )}
          </section>

          <section style={CARD} data-testid="action-conditions">
            <p className="aug-fs-sm" style={{ ...LABEL, color: "var(--t1)", fontWeight: 500 }}><span style={STEP}>5</span>When it may be pressed</p>
            {draft.conditions.length === 0 && (
              <p className="aug-fs-xs" style={{ ...HINT, margin: "0 0 6px" }}>On every {entityLabel.toLowerCase()}. Add a condition if only some should allow it.</p>
            )}
            {draft.conditions.map((c, i) => {
              const state = cands?.states.find(s => s.property === c.property);
              return (
                <div key={`cond-${c.property}`} style={{ borderTop: i ? RULE : undefined, paddingTop: i ? 8 : 0, marginBottom: 8 }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
                    <span className="aug-fs-sm" style={{ color: "var(--t1)" }}>{c.label}</span>
                    <SelectField value={c.negate ? "not" : "is"} aria-label={`Condition ${i + 1}`} disabled={!drafting} style={{ width: 150 }}
                      onChange={e => editCondition(i, { negate: e.target.value === "not" })}>
                      <option value="is">is one of</option>
                      <option value="not">is none of</option>
                    </SelectField>
                    {drafting && (
                      <Button size="xs" variant="ghost" style={{ marginLeft: "auto" }} aria-label={`Take condition ${i + 1} off`}
                        onClick={() => setDraft(d => ({ ...d, conditions: d.conditions.filter((_, j) => j !== i) }))}>
                        <Icon name="close" size={12} />
                      </Button>
                    )}
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
                    {(state?.values ?? []).filter(v => v.value != null).map(v => {
                      const value = String(v.value);
                      const on = c.values.includes(value);
                      return (
                        <Button key={value} size="xs" variant={on ? "secondary" : "outline"} disabled={!drafting} aria-pressed={on}
                          onClick={() => editCondition(i, { values: on ? c.values.filter(x => x !== value) : [...c.values, value] })}>
                          {value} · {formatCount(v.objects)}
                        </Button>
                      );
                    })}
                  </div>
                  <Input value={c.message} disabled={!drafting} aria-label={`What a refused press is told, condition ${i + 1}`}
                    placeholder={conditionMessage({ ...c, message: "" }, draft)} onChange={e => editCondition(i, { message: e.target.value })} />
                </div>
              );
            })}
            {drafting && unused.length > 0 && (
              <SelectField value="" aria-label="Add a condition" style={{ width: 240 }}
                onChange={e => {
                  const s = unused.find(u => u.property === e.target.value);
                  if (s) edit({ conditions: [...draft.conditions, { property: s.property, label: s.label, negate: false, values: [], message: "" }] });
                }}>
                <option value="">Add a condition on…</option>
                {unused.map(s => <option key={s.property} value={s.property}>{s.label}</option>)}
              </SelectField>
            )}
            {draft.entity && cands && !cands.states.length && (
              <p className="aug-fs-xs" style={HINT}>Nothing a {entityLabel.toLowerCase()} holds has few enough values to choose from.</p>
            )}
            <p className="aug-fs-xs" style={{ margin: "8px 0 0" }} data-testid="action-allowed">
              {!preview ? <span style={HINT}>{counting ? "Counting…" : countProblem || (problem ? `Not counted yet: ${problem}` : "")}</span>
                : preview.allowed == null ? <span style={HINT}>{preview.uncounted}</span>
                  : <>
                      <span style={{ color: preview.allowed ? "var(--grn4)" : "var(--red5)" }}>
                        {formatCount(preview.allowed)} {plural} allow it now
                      </span>
                      <span style={HINT}> · {formatCount((preview.objects ?? 0) - preview.allowed)} don&apos;t</span>
                    </>}
            </p>
          </section>

          <section style={CARD}>
            <p className="aug-fs-sm" style={{ ...LABEL, color: "var(--t1)", fontWeight: 500 }}><span style={STEP}>6</span>Who decides</p>
            <Choice on={!draft.approval} disabled={!drafting} icon="run" title="Runs when pressed"
              says={draft.does === "mark" ? "A mark anyone can withdraw." : "The call is made at once."} onPick={() => edit({ approval: false })} />
            <Choice on={draft.approval} disabled={!drafting} icon="hand" title="A person approves each press"
              says="It waits in their inbox until they do." onPick={() => edit({ approval: true })} />
          </section>

          {draft.does === "call" && <CallStep call={draft.call} disabled={!drafting} declared={declared} onChange={editCall} />}
        </div>

        <div>
          <section style={CARD} data-testid="action-press">
            <p className="aug-fs-sm" style={{ ...LABEL, color: "var(--t1)", fontWeight: 500 }}>A press, on a real {entityLabel.toLowerCase()}</p>
            {draft.asks.filter(a => idFrom(a.label)).map(a => (
              <div key={`said-${idFrom(a.label)}`} style={{ marginBottom: 6 }}>
                <Input value={said[idFrom(a.label)] ?? ""} placeholder={`${a.label} — what someone might say`} aria-label={`Try it with: ${a.label}`}
                  disabled={!drafting} onChange={e => setSaid(s => ({ ...s, [idFrom(a.label)]: e.target.value }))} />
              </div>
            ))}
            {!sample ? <p className="aug-fs-xs" style={HINT}>{preview ? preview.unread.join("; ") || `No ${entityLabel.toLowerCase()} to try it on.` : "Read once the draft is ready."}</p> : (
              <div className="aug-fs-xs" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ color: "var(--t2)" }}>
                  {entityLabel} {sample.key}
                  {/* The key is the object's name here already — its column is not said twice. */}
                  {Object.entries(sample.properties ?? {}).filter(([, v]) => String(v) !== sample.key).slice(0, 3)
                    .map(([k, v]) => ` · ${words(k)} ${v ?? "—"}`).join("")}
                </span>
                {sample.status === "allowed"
                  ? <span style={{ color: "var(--grn4)" }}><Icon name="check" size={11} /> Allowed</span>
                  : <span style={{ color: "var(--red5)" }}><Icon name="close" size={11} /> Refused: {sample.message}</span>}
                {sample.status === "allowed" && (sample.edits ?? []).map(e => (
                  <span key={e.property} style={{ color: "var(--t1)" }}>
                    After the press: {draft.mark.label.trim() || words(e.property)} reads &ldquo;{e.value}&rdquo;
                    {e.note ? `, with the note “${e.note}”` : ""}. By whoever pressed it, and it can be withdrawn.
                  </span>
                ))}
                {sample.status === "allowed" && sample.tell && (
                  <span style={{ color: "var(--t1)" }}>
                    A press would tell {sample.tell.destination}{sample.tell.type ? ` (${sample.tell.type})` : ""}: &ldquo;{sample.tell.message}&rdquo;.
                    Nothing is sent from here.
                  </span>
                )}
                {sample.status === "allowed" && sample.analysis && (
                  <span style={{ color: "var(--t1)" }}>
                    A press would start a deep analysis: &ldquo;{sample.analysis.question}&rdquo;. Nothing runs from here.
                  </span>
                )}
                {sample.status === "allowed" && sample.call && (
                  <span style={{ color: "var(--t1)", wordBreak: "break-all" }}>
                    A press would call {sample.call.method} {sample.call.url}. Nothing is sent from here.
                  </span>
                )}
              </div>
            )}
          </section>

          <section style={CARD}>
            <p className="aug-fs-sm" style={{ ...LABEL, color: "var(--t1)", fontWeight: 500 }}>What it creates</p>
            {draft.does === "mark" && markProperty && (
              <p className="aug-fs-xs" style={{ color: "var(--t2)", margin: "0 0 4px" }}>
                <Icon name="column" size={11} /> A new column on {entityLabel}, <b>{draft.mark.label.trim()}</b>, empty until a press.
              </p>
            )}
            <p className="aug-fs-xs" style={{ color: "var(--t2)", margin: 0 }}>
              <Icon name="run" size={11} /> A button for {oneOf(entityLabel)}&apos;s detail on a cockpit
              {draft.does === "tell" ? ", that sends a message and keeps its delivery as the proof it was sent"
                : draft.does === "analyse" ? ", that starts a deep analysis and keeps its job as the proof it started" : ""}.
            </p>
          </section>

          <section style={CARD} data-testid="action-places">
            <p className="aug-fs-sm" style={{ ...LABEL, color: "var(--t1)", fontWeight: 500 }}>Where it appears</p>
            {places.length === 0 ? (
              <p className="aug-fs-xs" style={HINT}>
                No cockpit of yours shows {plural} one at a time yet. Its button can be added later, with From the ontology on a cockpit.
              </p>
            ) : places.map(p => {
              const id = `${p.cockpitId}/${p.detailKey}`;
              const seg = segmentOf(p.segment);
              return (
                <label key={id} className="aug-fs-xs" style={{ display: "flex", gap: 6, alignItems: "flex-start", marginBottom: 6, color: "var(--t2)" }}>
                  <Checkbox checked={!!ticked[id]} disabled={phase.at === "placed"} aria-label={`Add it to ${p.title}`}
                    onChange={e => setTicked(t => ({ ...t, [id]: e.target.checked }))} />
                  <span>
                    <span style={{ color: "var(--t1)" }}>{p.title}</span>
                    {p.segment && ` — beside ${words(p.segment)}`}
                    {seg && seg.allowed != null && `: ${formatCount(seg.allowed)} of ${formatCount(seg.objects)} allow it`}
                  </span>
                </label>
              );
            })}
            {places.length > 0 && (
              <Button size="xs" variant="secondary" data-testid="action-place" disabled={phase.at !== "published" || !chosen.length || !!busy}
                onClick={() => void place()}>
                {busy === "place" ? "Adding…" : phase.at === "placed" ? "Added" : "Add the button to the cockpits ticked"}
              </Button>
            )}
            {places.length > 0 && phase.at !== "published" && phase.at !== "placed" && (
              <p className="aug-fs-xs" style={{ ...HINT, margin: "6px 0 0" }}>Once the action is declared and published.</p>
            )}
          </section>

          {preview && (narrow.length > 0 || preview.allowed === 0) && (
            <Callout tone="amber" style={{ marginBottom: 12 }} data-testid="action-checks">
              <div className="aug-fs-xs" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {preview.allowed === 0 && <span>No {entityLabel.toLowerCase()} allows it now — every press would be refused.</span>}
                {narrow.map(s => (
                  <span key={s.segment}>
                    {formatCount(s.objects - (s.allowed ?? 0))} of the {formatCount(s.objects)} {words(s.segment)}{" "}the button sits beside
                    can&apos;t be pressed: each would be told the condition&apos;s sentence.
                  </span>
                ))}
              </div>
            </Callout>
          )}
        </div>
      </div>
    </div>
  );
}

function Choice({ on, disabled, icon, title, says, onPick }: {
  on: boolean; disabled: boolean; icon: "bookmark" | "plug" | "run" | "hand" | "send" | "search"; title: string; says: string; onPick: () => void;
}) {
  return (
    <Button variant="ghost" size="sm" disabled={disabled} aria-pressed={on} onClick={onPick} className="h-auto w-full justify-start py-1.5"
      style={{ border: on ? "1px solid var(--accent)" : RULE, marginBottom: 6, textAlign: "left" }}>
      <span style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <Icon name={icon} size={14} />
        <span style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: on ? 500 : 400 }}>{title}</span>
          <span className="aug-fs-xs" style={{ color: "var(--t3)", whiteSpace: "normal" }}>{says}</span>
        </span>
      </span>
    </Button>
  );
}

/** Step 7 — the call to another system: an integration, kept apart from the decision and asked only of an action that
 *  makes one. Nothing is pre-filled; the credential is stored encrypted by the declare door and never kept here. */
function CallStep({ call, disabled, declared, onChange }: {
  call: CallDraft; disabled: boolean; declared: Record<string, { name: string; takes: string[] }>; onChange: (change: Partial<CallDraft>) => void;
}) {
  return (
    <section style={{ ...CARD, background: "var(--bg-2)" }} data-testid="action-call">
      <p className="aug-fs-sm" style={{ ...LABEL, color: "var(--t1)", fontWeight: 500 }}><span style={STEP}>7</span>Connect it to another system</p>
      <p className="aug-fs-xs" style={{ ...HINT, margin: "0 0 8px" }}>
        A question&apos;s answer and the object pressed on are filled in where you write them in braces, like {"{reason}"}.
      </p>
      <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
        <SelectField value={call.method} aria-label="Method" disabled={disabled} style={{ width: 110 }}
          onChange={e => onChange({ method: e.target.value as CallDraft["method"] })}>
          {(["POST", "PUT", "PATCH", "GET", "DELETE"] as const).map(m => <option key={m} value={m}>{m}</option>)}
        </SelectField>
        <Input value={call.url} placeholder="https://api.carrier.example/claims" aria-label="Address" disabled={disabled} style={{ flex: 1 }}
          onChange={e => onChange({ url: e.target.value })} />
      </div>
      <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
        <Input value={call.authHeader} placeholder="Authorization" aria-label="Credential header" disabled={disabled} style={{ flex: 1 }}
          onChange={e => onChange({ authHeader: e.target.value })} />
        <Input value={call.secret} type="password" placeholder="Credential — stored encrypted" aria-label="Credential" disabled={disabled}
          style={{ flex: 1 }} onChange={e => onChange({ secret: e.target.value })} />
      </div>
      <Textarea value={call.body} rows={3} placeholder='{"order": "{order}", "reason": "{reason}"}' aria-label="The message sent (JSON)"
        disabled={disabled} onChange={e => onChange({ body: e.target.value })} />
      <p className="aug-fs-xs" style={{ ...LABEL, marginTop: 8 }}>How to check it worked</p>
      <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
        <Textarea value={call.check} rows={2} placeholder="SELECT 1 FROM claims WHERE order_id = '{order}'" aria-label="The read that checks it"
          disabled={disabled} style={{ flex: 1 }} onChange={e => onChange({ check: e.target.value })} />
        <SelectField value={call.expects} aria-label="It worked when the read" disabled={disabled} style={{ width: 150 }}
          onChange={e => onChange({ expects: e.target.value as CallDraft["expects"] })}>
          <option value="rows">finds a row</option>
          <option value="no_rows">finds none</option>
        </SelectField>
      </div>
      <p className="aug-fs-xs" style={{ ...LABEL, marginTop: 8 }}>Taking it back</p>
      {call.undo === "action" && (
        <p className="aug-fs-xs" style={{ ...HINT, margin: "0 0 4px" }}>What that action asks for is answered from this one&apos;s answers, by name.</p>
      )}
      <div style={{ display: "flex", gap: 6 }}>
        <SelectField value={call.undo} aria-label="Taking it back" disabled={disabled} style={{ flex: 1 }}
          onChange={e => onChange({ undo: e.target.value as CallDraft["undo"] })}>
          <option value="irreversible">It cannot be taken back</option>
          <option value="action">Another action takes it back</option>
        </SelectField>
        {call.undo === "action" && (
          <>
            <SelectField value={call.undoAction} aria-label="The action that takes it back" disabled={disabled} style={{ flex: 1 }}
              onChange={e => onChange({ undoAction: e.target.value })}>
              <option value="">Choose the action…</option>
              {Object.entries(declared).map(([id, a]) => <option key={id} value={id}>{a.name}</option>)}
            </SelectField>
            <Input value={call.undoHours} type="number" min={0} placeholder="Hours open (0: always)" aria-label="Hours it stays open"
              disabled={disabled} style={{ width: 150 }} onChange={e => onChange({ undoHours: e.target.value })} />
          </>
        )}
      </div>
    </section>
  );
}
