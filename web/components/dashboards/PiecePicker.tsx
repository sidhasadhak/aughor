"use client";

/**
 * Every piece a dashboard may hold, by what it is for (Arc AP-4; design-mockups/cockpit-builder.html screen 5) — the door
 * that lets a person build the dispatch desk by hand: a figure, a chart and the filter column were placed only by the
 * starter before it (the scenarios on theLook, 2026-10-11).
 *
 * A piece is placed in the section a person chose — the empty one whose "Add a piece" they pressed, or the one chosen in
 * the builder — reading the entity or the set named above the list, with what the ontology offers as its first setup:
 * a table's first properties, a chart across the entity's date, a figure's count. Every placement is a spec the rules
 * accept; a piece that cannot be placed here says why, and is not offered as if it could. The setup changes the rest.
 */
import { useEffect, useMemo, useState } from "react";

import {
  entityFields, isCategory, isNumber, isText, isTime, nameField, placesOf, ranked, timesOf, type EntityFields,
} from "@/components/dashboards/PieceSetup";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { CHART_DAYS, MAX_FILTERS, MAX_LABEL, MAX_TABLE_COLUMNS } from "@/lib/dashboards/catalog";
import {
  addDrawer, freshWireName, nameByPiece, placeFilterColumn, placePiece, putSet, sectionsOf, type DashboardSpec,
} from "@/lib/dashboards/edit";
import { choicesOf, isRefused, readSet } from "@/lib/dashboards/sets";
import { withUniqueKeys } from "@/lib/listKeys";
import { cachedObjectCatalog, getDeclaredActions, type DeclaredAction } from "@/lib/objects";
import { getProcesses } from "@/lib/objectTypes";

/** A piece the page places with its own composer — a card from the store, a note in the person's words, an image they
 *  upload, a recorded finding — in the section the picker was opened for. */
export type HandOff = "card" | "note" | "image" | "finding" | "query";
const HANDED: readonly string[] = ["card", "note", "image", "finding", "query"];

type Placed = "ObjectTable" | "ObjectDetail" | "ObjectFigure" | "ObjectChart" | "ObjectBreakdown" | "ProcessBoard"
  | "ActionButtons" | "ObjectList" | "ObjectMap" | "ObjectTimeline" | "ChooseOne" | "ObjectSearch";
/** "Linked" places two things: a set of what the chosen object links to, and a table of it; a drawer is the dashboard's own,
 *  holding a detail of the object it opens on. */
type Kind = Placed | "ObjectFilters" | "Linked" | "Drawer" | HandOff;
interface Entry { kind: Kind; label: string; says: string }
const GROUPS: { group: string; pieces: Entry[] }[] = [
  { group: "Show objects", pieces: [
    { kind: "ObjectTable", label: "Objects table", says: "Rows of a set; a click chooses, a tick collects." },
    { kind: "ObjectList", label: "Object list", says: "A queue as cards: a name, a number, a mark." },
    { kind: "ObjectMap", label: "Map", says: "Each placed by its coordinates; a click chooses one." },
    { kind: "ObjectTimeline", label: "Timeline", says: "Each a bar from one moment to the next." },
    { kind: "ObjectDetail", label: "Object detail", says: "The chosen object's properties and its actions." },
    { kind: "Linked", label: "Linked objects", says: "What the chosen one links to — an order's lines." },
    { kind: "Drawer", label: "Drawer", says: "The chosen one, opened beside the page." },
  ] },
  { group: "Measure", pieces: [
    { kind: "ObjectFigure", label: "Figure", says: "One number of a set, beside the whole." },
    { kind: "ObjectChart", label: "Chart", says: "Bars across the days, split by a property if you like." },
    { kind: "ObjectBreakdown", label: "Breakdown", says: "Groups by a property, each with its count; they add up to the whole." },
    { kind: "ProcessBoard", label: "Process board", says: "A process's stages, its promises and what is overdue." },
    { kind: "card", label: "Card", says: "A measured card from the card store." },
    { kind: "query", label: "Your own query", says: "SQL over any table, shown as a table, a figure or a chart." },
    { kind: "finding", label: "Finding", says: "A recorded finding, with its evidence." },
  ] },
  { group: "Filter", pieces: [
    { kind: "ObjectFilters", label: "Filter column", says: "Values with how many hold each; a reader ticks." },
    { kind: "ObjectSearch", label: "Search", says: "Words that narrow every piece over the same objects." },
    { kind: "ChooseOne", label: "Choose one", says: "One object found by name, for the pieces that follow it." },
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
/** Words kept to `max` characters, cut between words — "Products of the chosen distribution center" never ends "…cent";
 *  past the limit "the chosen" gives way first, it being what every linked set is of. */
function upTo(text: string, max: number): string {
  const t = text.length > max ? text.replace(" of the chosen ", " of the ") : text;
  if (t.length <= max) return t;
  const cut = t.slice(0, max + 1);
  return cut.slice(0, Math.max(cut.lastIndexOf(" "), 1)).trim();
}

/** The entity a dashboard already reads first — its filter column's, a piece's, a set's — for the picker to start on. */
function firstEntity(spec: DashboardSpec): string {
  for (const el of Object.values(spec.elements)) if (typeof el.props?.entity === "string" && el.props.entity) return el.props.entity;
  for (const name of Object.keys(spec.sets ?? {})) { const r = readSet(spec, name); if (!isRefused(r)) return r.entity; }
  return "";
}

export function PiecePicker({ spec, section, connectionId, schema, onPlace, onHandOff, onClose }: {
  spec: DashboardSpec;
  /** The section a piece goes in; the first that holds pieces when none is named. */
  section: string | null;
  connectionId: string;
  schema?: string;
  onPlace: (next: DashboardSpec, note: string) => void;
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
    }).catch(() => { /* the entity the dashboard reads stays offered */ });
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
  // the sets of the entity chosen — a set of the customers a set of orders reaches is offered under Customer (Arc AP-8b)
  const sets = Object.keys(spec.sets ?? {}).map(n => ({ n, r: readSet(spec, n) }))
    .filter(x => !isRefused(x.r) && (!entity || (x.r as { entity: string }).entity === entity));
  // the pieces a click chooses in, by their keys — a choose-one always names its choice, so it is followed by that
  const tables = Object.entries(spec.elements).filter(([, el]) => ["ObjectTable", "ObjectList", "ObjectMap", "ObjectTimeline"].includes(el.type));
  const chosen = [...choicesOf(spec).values()].filter(c => c.kind === "chosen");
  const hasFilters = Object.values(spec.elements).some(el => el.type === "ObjectFilters");
  const label = (reads ? spec.sets?.[reads]?.label : undefined) ?? plural(noun);

  /** Why a piece cannot be placed here, or "" — and the props it is placed with when it can. */
  const plan = (kind: Kind): { why: string; props?: Record<string, unknown> } => {
    if (!target && kind !== "ObjectFilters" && kind !== "Drawer") return { why: "There is no section to place it in. Add a section first." };
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
        if (!tables.length && !chosen.length) return { why: "A detail follows a table, a list, a map or a timeline. Place one first." };
        return { why: "", props: { follows: chosen[0]?.name ?? tables[0][0] } };
      case "ObjectList": {
        if (!of) return { why: "Choose what it lists above." };
        if (!ef) return { why: "Reading what the ontology offers…" };
        const own = ef.fields.filter(f => !f.via);
        const title = nameField(ef);
        const figure = ranked(own.filter(isNumber))[0];
        const mark = own.find(f => isCategory(f) && f.path !== title?.path);
        const time = own.find(isTime);
        // the newest first; a queue read oldest first is one choice away in its setup
        return { why: "", props: { ...scope, title: title?.path, figure: figure?.path, mark: mark?.path, sort: time?.path, descending: time ? true : undefined } };
      }
      case "ObjectMap": {
        if (!of) return { why: "Choose what it places above." };
        if (!ef) return { why: "Reading what the ontology offers…" };
        const at = placesOf(ef);
        if (!at) return { why: `${noun} holds no latitude and longitude to place it by.` };
        return { why: "", props: { ...scope, lat: at.lat.path, lng: at.lng.path, label: nameField(ef)?.path } };
      }
      case "ObjectTimeline": {
        if (!of) return { why: "Choose what it draws above." };
        if (!ef) return { why: "Reading what the ontology offers…" };
        const t = timesOf(ef);
        if (!t) return { why: `${noun} holds fewer than two moments to draw a bar between.` };
        return { why: "", props: { ...scope, start: t.start.path, end: t.end.path, label: nameField(ef)?.path } };
      }
      case "ChooseOne": {
        if (!of) return { why: "Choose what it chooses from above." };
        if (!ef) return { why: "Reading what the ontology offers…" };
        const name = nameField(ef);
        if (!name) return { why: `${noun} holds no name to find one by. A click in a table or a list chooses one.` };
        return { why: "", props: { ...scope, chooses: freshWireName(spec, `chosen ${noun}`), label: name.path } };
      }
      case "ObjectSearch": {
        if (!of) return { why: "Choose what it searches above." };
        if (!ef) return { why: "Reading what the ontology offers…" };
        const text = nameField(ef) ?? ef.fields.find(f => !f.via && isText(f));
        if (!text) return { why: `${noun} holds no words to look for.` };
        return { why: "", props: { entity: of, path: text.path, label: upTo(`Find ${plural(noun).toLowerCase()}`, MAX_LABEL) } };
      }
      case "Drawer": {
        if (target && spec.elements[target]?.type === "Drawer") return { why: "A drawer opens beside the page. It holds pieces, not a drawer." };
        if (!chosen.length) return { why: "Nothing names the object a click chooses yet. Name it in the setup of a table, a list, a map or a timeline." };
        const free = chosen.find(c => !Object.values(spec.elements).some(el => el.type === "Drawer" && el.props.opens_on === c.name));
        if (!free) return { why: "Each chosen object opens its drawer already." };
        return { why: "", props: { opens_on: free.name } };
      }
      case "Linked": {
        if (!chosen.length) return { why: "Nothing names the object a click chooses yet. Name it in the setup of a table, a list, a map or a timeline." };
        if (!of) return { why: "Choose what it lists above — an order's lines, say." };
        if (!ef) return { why: "Reading what the ontology offers…" };
        // what names the chosen object's key: an order line's `order_id` names its order
        for (const c of chosen) {
          const one = words(c.entity).toLowerCase().replace(/s$/, "").replace(/ /g, "_");
          const path = ef.fields.find(f => !f.via && f.path.toLowerCase() === `${one}_id`)?.path;
          if (path && c.entity.toLowerCase() !== of.toLowerCase()) return { why: "", props: { choice: c.name, path, entity: of } };
        }
        return { why: `${noun} names none of the objects a click chooses here.` };
      }
      case "ObjectFigure":
        if (!of) return { why: "Choose what it counts above." };
        return { why: "", props: { ...scope, label: upTo(label, MAX_LABEL), agg: "count" } };
      case "ObjectChart": {
        if (!of) return { why: "Choose what it draws above." };
        if (!ef) return { why: "Reading what the ontology offers…" };
        const time = ef.fields.find(f => !f.via && isTime(f));
        if (!time) return { why: `${noun} holds no date to draw across.` };
        return { why: "", props: { ...scope, label: upTo(`${label}, by ${time.label.toLowerCase()}`, MAX_LABEL), time: time.path, days: CHART_DAYS[1] ?? 14 } };
      }
      case "ObjectBreakdown": {
        if (!of) return { why: "Choose what it groups above." };
        if (!ef) return { why: "Reading what the ontology offers…" };
        const group = ef.fields.find(isCategory);
        if (!group) return { why: `${noun} has no property to group by.` };
        return { why: "", props: { ...scope, label: upTo(`${label} by ${group.label.toLowerCase()}`, MAX_LABEL), by: group.path,
          measures: [{ agg: "count" }] } };
      }
      case "ProcessBoard": {
        if (processes === null) return { why: "Reading the declared processes…" };
        const p = processes.find(x => !of || words(x.entity).toLowerCase() === words(of).toLowerCase()) ?? processes[0];
        if (!p) return { why: "This connection declares no process. Declare one in Ontology ▸ Processes." };
        return { why: "", props: { process: p.id } };
      }
      case "ObjectFilters": {
        if (hasFilters) return { why: "The dashboard has its filter column. It holds one." };
        if (!entity) return { why: "Choose what it filters above." };
        if (!ef || fields?.entity !== entity) return { why: "Reading what the ontology offers…" };
        const props = ef.fields.filter(isCategory).slice(0, Math.min(3, MAX_FILTERS))
          .map(f => ({ path: f.path, label: upTo(f.label, MAX_LABEL), ...(f.via ? { via: upTo(f.via, MAX_LABEL) } : {}) }));
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
    if (HANDED.includes(e.kind)) { onHandOff(e.kind as HandOff, target); return; }
    const p = plan(e.kind);
    if (p.why || !p.props) return;
    let next: DashboardSpec | null = null;
    if (e.kind === "ObjectFilters") next = placeFilterColumn(spec, p.props).spec;
    else if (e.kind === "Drawer") {
      const on = String(p.props.opens_on);
      next = addDrawer(spec, upTo(`The ${words(on).replace(/^chosen /, "")}`, MAX_LABEL), on).spec;
    } else if (e.kind === "Linked") {
      // a set of what the chosen object links to, named for it, and a table of the set — "Order items of the chosen order"
      const choice = String(p.props.choice);
      const said = upTo(`${plural(noun)} of the ${words(choice)}`, MAX_LABEL);
      const name = freshWireName(spec, said);
      const withSet = putSet(spec, name, { label: said, entity: String(p.props.entity), linked_to: { choice, path: String(p.props.path) } });
      const placed = placePiece(withSet, "ObjectTable", { set: name }, target ?? undefined);
      if (!placed.key) return;
      next = target ? nameByPiece(placed.spec, target, said) : placed.spec;
    } else {
      const placed = placePiece(spec, e.kind as Placed, p.props, target ?? undefined);
      if (!placed.key) return;
      // a new section is called by what its first piece reads — "Shipped late", never a chart's whole label — a detail by
      // what it shows ("The chosen order"), a row of buttons by what they do
      const name = e.kind === "ObjectDetail" ? (chosen.length ? `The ${words(String(p.props.follows))}` : "The chosen one")
        : e.kind === "ActionButtons" ? "Actions" : e.kind === "ProcessBoard" ? words(String(p.props.process)).replace(/^./, c => c.toUpperCase())
          : e.kind === "ObjectSearch" ? "Search" : e.kind === "ChooseOne" ? `Choose ${/^[aeiou]/i.test(noun) ? "an" : "a"} ${noun.toLowerCase()}` : label;
      next = target ? nameByPiece(placed.spec, target, name) : placed.spec;
    }
    onPlace(next, `${e.label.toLowerCase()} placed by hand`);
    onClose();
  };

  const shown = useMemo(() => {
    const q = find.trim().toLowerCase();
    return GROUPS.map(g => ({ ...g, pieces: g.pieces.filter(p => !q || `${p.label} ${p.says}`.toLowerCase().includes(q)) }))
      .filter(g => g.pieces.length);
  }, [find]);

  return (
    <Dialog open onOpenChange={o => { if (!o) onClose(); }}>
      <DialogContent data-testid="piece-picker" style={{ maxWidth: 640 }}>
        <DialogHeader>
          <DialogTitle>Add a piece</DialogTitle>
          <DialogDescription>{target ? `To ${sectionTitle}.` : "To the dashboard."} Its setup changes the rest after.</DialogDescription>
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
                  const p = HANDED.includes(e.kind) ? { why: target ? "" : "There is no section to place it in." } : plan(e.kind as Placed | "ObjectFilters" | "Linked" | "Drawer");
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
