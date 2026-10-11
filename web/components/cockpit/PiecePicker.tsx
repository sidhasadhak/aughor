"use client";

/**
 * Every piece a cockpit may hold, by what it is for (Arc AP-4; design-mockups/cockpit-builder.html screen 5) — the door
 * that lets a person build the dispatch desk by hand: a figure, a chart and the filter column were placed only by the
 * starter before it (the scenarios on theLook, 2026-10-11).
 *
 * A piece is placed in the section a person chose — the empty one whose "Add a piece" they pressed, or the one chosen in
 * the builder — reading the entity or the set named above the list, with what the ontology offers as its first setup:
 * a table's first properties, a chart across the entity's date, a figure's count. Every placement is a spec the rules
 * accept; a piece that cannot be placed here says why, and is not offered as if it could. The setup changes the rest.
 */
import { useEffect, useMemo, useState } from "react";

import { entityFields, isCategory, isTime, type EntityFields } from "@/components/cockpit/PieceSetup";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { CHART_DAYS, MAX_FILTERS, MAX_LABEL, MAX_TABLE_COLUMNS } from "@/lib/cockpit/catalog";
import {
  nameByPiece, placeFilterColumn, placePiece, sectionsOf, type CockpitSpec,
} from "@/lib/cockpit/edit";
import { choicesOf, isRefused, readSet } from "@/lib/cockpit/sets";
import { withUniqueKeys } from "@/lib/listKeys";
import { cachedObjectCatalog, getDeclaredActions, type DeclaredAction } from "@/lib/objects";
import { getProcesses } from "@/lib/objectTypes";

/** A piece the page places with its own composer — a card from the store, a note in the person's words, an image they
 *  upload, a recorded finding — in the section the picker was opened for. */
export type HandOff = "card" | "note" | "image" | "finding";

type Kind = "ObjectTable" | "ObjectDetail" | "ObjectFigure" | "ObjectChart" | "ProcessBoard" | "ObjectFilters" | "ActionButtons" | HandOff;
interface Entry { kind: Kind; label: string; says: string }
const GROUPS: { group: string; pieces: Entry[] }[] = [
  { group: "Show objects", pieces: [
    { kind: "ObjectTable", label: "Objects table", says: "Rows of a set; a click chooses, a tick collects." },
    { kind: "ObjectDetail", label: "Object detail", says: "The chosen object's properties and its actions." },
  ] },
  { group: "Measure", pieces: [
    { kind: "ObjectFigure", label: "Figure", says: "One number of a set, beside the whole." },
    { kind: "ObjectChart", label: "Chart", says: "Bars across the days, split by a property if you like." },
    { kind: "ProcessBoard", label: "Process board", says: "A process's stages, its promises and what is overdue." },
    { kind: "card", label: "Card", says: "A measured card from the card store." },
    { kind: "finding", label: "Finding", says: "A recorded finding, with its evidence." },
  ] },
  { group: "Filter", pieces: [
    { kind: "ObjectFilters", label: "Filter column", says: "Values with how many hold each; a reader ticks." },
  ] },
  { group: "Act", pieces: [
    { kind: "ActionButtons", label: "Action buttons", says: "Declared actions, run on what is chosen or ticked." },
  ] },
  { group: "Words & media", pieces: [
    { kind: "note", label: "Note", says: "Your own words." },
    { kind: "image", label: "Image", says: "A picture you upload." },
  ] },
];

const words = (id: string) => id.replace(/[_-]+/g, " ");
const plural = (w: string) => (/s$/i.test(w) ? w : `${w}s`);

/** The entity a cockpit already reads first — its filter column's, a piece's, a set's — for the picker to start on. */
function firstEntity(spec: CockpitSpec): string {
  for (const el of Object.values(spec.elements)) if (typeof el.props?.entity === "string" && el.props.entity) return el.props.entity;
  for (const name of Object.keys(spec.sets ?? {})) { const r = readSet(spec, name); if (!isRefused(r)) return r.entity; }
  return "";
}

export function PiecePicker({ spec, section, connectionId, schema, wiringOn, onPlace, onHandOff, onClose }: {
  spec: CockpitSpec;
  /** The section a piece goes in; the first that holds pieces when none is named. */
  section: string | null;
  connectionId: string;
  schema?: string;
  /** Whether a piece may read one of the cockpit's sets (Arc AP-2). */
  wiringOn: boolean;
  onPlace: (next: CockpitSpec, note: string) => void;
  onHandOff: (kind: HandOff, section: string | null) => void;
  onClose: () => void;
}) {
  const target = section ?? sectionsOf(spec)[0]?.key ?? null;
  const sectionTitle = target ? String(spec.elements[target]?.props.title ?? "the section") : "";
  const [entities, setEntities] = useState<{ value: string; label: string }[]>([]);
  const [entity, setEntity] = useState(() => firstEntity(spec));
  const [reads, setReads] = useState("");                       // "" — every object of the entity; else a set's name
  const [find, setFind] = useState("");
  const [fields, setFields] = useState<{ entity: string; f: EntityFields } | null>(null);
  const [actions, setActions] = useState<DeclaredAction[] | null>(null);
  const [processes, setProcesses] = useState<{ id: string; entity: string }[] | null>(null);
  useEffect(() => {
    let alive = true;
    cachedObjectCatalog(connectionId).then(c => {
      if (!alive || !c) return;
      const list = c.object_types.map(t => ({ value: t.object_type, label: t.display_name || words(t.object_type) }));
      setEntities(list);
      setEntity(e => e || list[0]?.value || "");
    }).catch(() => { /* the entity the cockpit reads stays offered */ });
    getDeclaredActions(connectionId, schema).then(a => { if (alive) setActions(Object.values(a)); }).catch(() => { if (alive) setActions([]); });
    getProcesses(connectionId, schema).then(p => { if (alive) setProcesses((p?.processes ?? []).map(x => ({ id: x.id, entity: x.entity }))); })
      .catch(() => { if (alive) setProcesses([]); });
    return () => { alive = false; };
  }, [connectionId, schema]);
  // what the piece reads: a set's entity when one is chosen, else the entity chosen
  const set = reads ? readSet(spec, reads) : null;
  const of = set && !isRefused(set) ? set.entity : entity;
  useEffect(() => {
    if (!of) return;
    let alive = true;
    entityFields(of, connectionId, schema).then(f => { if (alive) setFields({ entity: of, f }); }).catch(() => { /* none offered */ });
    return () => { alive = false; };
  }, [of, connectionId, schema]);
  const ef = fields && fields.entity === of ? fields.f : null;
  const noun = entities.find(e => e.value === of)?.label ?? words(of);
  const sets = wiringOn ? Object.keys(spec.sets ?? {}).map(n => ({ n, r: readSet(spec, n) })).filter(x => !isRefused(x.r)) : [];
  const tables = Object.entries(spec.elements).filter(([, el]) => el.type === "ObjectTable");
  const chosen = [...choicesOf(spec).values()].filter(c => c.kind === "chosen");
  const hasFilters = Object.values(spec.elements).some(el => el.type === "ObjectFilters");
  const label = (reads ? spec.sets?.[reads]?.label : undefined) ?? plural(noun);

  /** Why a piece cannot be placed here, or "" — and the props it is placed with when it can. */
  const plan = (kind: Kind): { why: string; props?: Record<string, unknown> } => {
    if (!target && kind !== "ObjectFilters") return { why: "There is no section to place it in. Add a section first." };
    const scope = reads ? { set: reads } : { entity: of };
    switch (kind) {
      case "ObjectTable": {
        if (!of) return { why: "Choose what it lists above." };
        if (!ef) return { why: "Reading what the ontology offers…" };
        const fs = ef.fields.filter(f => !f.via);
        const columns = [...fs.filter(isTime).slice(0, 1), ...fs.filter(isCategory).slice(0, 2)].map(f => f.path).slice(0, MAX_TABLE_COLUMNS);
        return { why: "", props: { ...scope, ...(columns.length ? { columns } : {}) } };
      }
      case "ObjectDetail":
        if (!tables.length && !chosen.length) return { why: "A detail follows an objects table. Place one first." };
        return { why: "", props: { follows: chosen[0]?.name ?? tables[0][0] } };
      case "ObjectFigure":
        if (!of) return { why: "Choose what it counts above." };
        return { why: "", props: { ...scope, label: label.slice(0, MAX_LABEL), agg: "count" } };
      case "ObjectChart": {
        if (!of) return { why: "Choose what it draws above." };
        if (!ef) return { why: "Reading what the ontology offers…" };
        const time = ef.fields.find(f => !f.via && isTime(f));
        if (!time) return { why: `${noun} holds no date to draw across.` };
        return { why: "", props: { ...scope, label: `${label}, by ${time.label.toLowerCase()}`.slice(0, MAX_LABEL), time: time.path, days: CHART_DAYS[1] ?? 14 } };
      }
      case "ProcessBoard": {
        if (processes === null) return { why: "Reading the declared processes…" };
        const p = processes.find(x => !of || words(x.entity).toLowerCase() === words(of).toLowerCase()) ?? processes[0];
        if (!p) return { why: "This connection declares no process. Declare one in Ontology ▸ Processes." };
        return { why: "", props: { process: p.id } };
      }
      case "ObjectFilters": {
        if (hasFilters) return { why: "The cockpit has its filter column. It holds one." };
        if (!entity) return { why: "Choose what it filters above." };
        if (!ef || fields?.entity !== entity) return { why: "Reading what the ontology offers…" };
        const props = ef.fields.filter(isCategory).slice(0, Math.min(3, MAX_FILTERS))
          .map(f => ({ path: f.path, label: f.label.slice(0, MAX_LABEL), ...(f.via ? { via: f.via.slice(0, MAX_LABEL) } : {}) }));
        if (!props.length) return { why: `${noun} has no property to filter by.` };
        return { why: "", props: { entity, properties: props, ...(reads ? { set: reads } : {}) } };
      }
      case "ActionButtons": {
        if (actions === null) return { why: "Reading the declared actions…" };
        if (!actions.length) return { why: "No action is declared here. Declare one in Ontology ▸ Actions." };
        const on = actions.find(a => words(a.entity || a.object_type).toLowerCase() === words(of).toLowerCase()) ?? actions[0];
        return { why: "", props: { buttons: [{ action: on.id }] } };
      }
      default:
        return { why: "" };
    }
  };

  const place = (e: Entry) => {
    if (e.kind === "card" || e.kind === "note" || e.kind === "image" || e.kind === "finding") { onHandOff(e.kind, target); return; }
    const p = plan(e.kind);
    if (p.why || !p.props) return;
    let next: CockpitSpec | null = null;
    if (e.kind === "ObjectFilters") next = placeFilterColumn(spec, p.props).spec;
    else {
      const placed = placePiece(spec, e.kind, p.props, target ?? undefined);
      if (!placed.key) return;
      // a new section is called by what its first piece reads — "Shipped late", never a chart's whole label — a detail by
      // what it shows ("The chosen order"), a row of buttons by what they do
      const name = e.kind === "ObjectDetail" ? (chosen.length ? `The ${words(String(p.props.follows))}` : "The chosen one")
        : e.kind === "ActionButtons" ? "Actions" : e.kind === "ProcessBoard" ? words(String(p.props.process)).replace(/^./, c => c.toUpperCase()) : label;
      next = target ? nameByPiece(placed.spec, target, name) : placed.spec;
    }
    onPlace(next, `${e.label.toLowerCase()} placed by hand`);
    onClose();
  };

  const shown = useMemo(() => {
    const q = find.trim().toLowerCase();
    return GROUPS.map(g => ({ ...g, pieces: g.pieces.filter(p => !q || `${p.label} ${p.says}`.toLowerCase().includes(q)) })).filter(g => g.pieces.length);
  }, [find]);

  return (
    <Dialog open onOpenChange={o => { if (!o) onClose(); }}>
      <DialogContent data-testid="piece-picker" style={{ maxWidth: 640 }}>
        <DialogHeader>
          <DialogTitle>Add a piece</DialogTitle>
          <DialogDescription>{target ? `To ${sectionTitle}.` : "To the cockpit."} Its setup changes the rest after.</DialogDescription>
        </DialogHeader>
        <div style={{ display: "grid", gridTemplateColumns: sets.length ? "1fr 1fr" : "1fr", gap: 8 }}>
          <SelectField aria-label="What it reads" value={entity} onChange={e => { setEntity(e.target.value); setReads(""); }}>
            {!entity && <option value="">Choose an entity</option>}
            {withUniqueKeys([...entities, ...(entity && !entities.some(x => x.value === entity) ? [{ value: entity, label: words(entity) }] : [])], x => x.value)
              .map(([k, x]) => <option key={k} value={x.value}>{x.label}</option>)}
          </SelectField>
          {sets.length > 0 && (
            <SelectField aria-label="Which of them" value={reads} onChange={e => setReads(e.target.value)}>
              <option value="">Every one</option>
              {withUniqueKeys(sets, x => x.n).map(([k, x]) => <option key={k} value={x.n}>{spec.sets?.[x.n]?.label ?? x.n}</option>)}
            </SelectField>
          )}
        </div>
        <Input aria-label="Find a piece" placeholder="Find a piece" value={find} onChange={e => setFind(e.target.value)} />
        <div style={{ display: "flex", flexDirection: "column", gap: 10, maxHeight: 420, overflow: "auto" }}>
          {withUniqueKeys(shown, g => g.group).map(([gk, g]) => (
            <div key={gk}>
              <div className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em", margin: "2px 0 4px" }}>{g.group}</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                {withUniqueKeys(g.pieces, e => e.kind).map(([ek, e]) => {
                  const p = e.kind === "card" || e.kind === "note" || e.kind === "image" || e.kind === "finding" ? { why: target ? "" : "There is no section to place it in." } : plan(e.kind);
                  return (
                    <Button key={ek} variant="outline" data-testid="piece-picker-entry" data-kind={e.kind} disabled={!!p.why}
                      title={p.why || e.says} onClick={() => place(e)}
                      style={{ height: "auto", justifyContent: "flex-start", textAlign: "left", padding: "8px 10px", whiteSpace: "normal" }}>
                      <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                        <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 500 }}>{e.label}</span>
                        <span className="aug-fs-xs" data-testid="piece-picker-says" style={{ color: "var(--t3)" }}>{p.why || e.says}</span>
                      </span>
                    </Button>
                  );
                })}
              </div>
            </div>
          ))}
          {!shown.length && <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>No piece is called that. <Icon name="search" size={12} /></div>}
        </div>
      </DialogContent>
    </Dialog>
  );
}
