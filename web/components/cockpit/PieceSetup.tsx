"use client";

/**
 * PieceSetup — the builder's Setup for the element chosen (Arc AP-1; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.4,
 * design-mockups/cockpit-builder.html screen 2).
 *
 * The study measured that nothing about a placed piece could be changed: a table listed the columns it was placed
 * with, a chart counted objects per day and nothing else. Here each is chosen — a table's columns, its sort and its
 * segment; a figure's calculation, its property and how it is written; a chart's days, its measure and what it is
 * split by; the filter column's properties — from what the ontology declares for the entity, never typed as a spec.
 * Each choice is handed back as the next spec (`lib/cockpit/edit.ts`), checked by the rules before it is kept, and the
 * piece reads again with what it now says. These are a person's choices, by hand; a model never sets a piece up.
 */
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { SelectField } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  CHART_DAYS, CHART_TOPS, FIGURE_AGGS, MAX_CAPTION, MAX_FILTERS, MAX_LABEL, MAX_NOTE, MAX_TABLE_COLUMNS, MAX_TITLE,
  SPLIT_AGGS, TONES,
} from "@/lib/cockpit/catalog";
import {
  editNote, moveCardTo, moveCardToNewSection, moveSectionTo, recaption, rename, sectionsOf, setProps, tabsOf,
  type CockpitSpec,
} from "@/lib/cockpit/edit";
import { lineOf, nameOf } from "@/lib/cockpit/names";
import { withUniqueKeys } from "@/lib/listKeys";
import { getDeclaredActions, type DeclaredAction } from "@/lib/objects";
import { getObjectType, getProcesses, type ObjectTypeDetail, type TypeProperty } from "@/lib/objectTypes";

/** A property a piece may read: the entity's own, or one of an object it links to one of ("Country via Customer"). */
export interface EntityField { path: string; label: string; via?: string; role: string; type: string; unit: string }
export interface EntityFields {
  fields: EntityField[];
  segments: string[];
  /** Every to-one link, and the one whose object's properties are offered for each object linked to. */
  links: { name: string; to: string }[];
  offeredFor: Record<string, string>;
}

const words = (id: string) => id.replace(/_/g, " ");
const TIME = /DATE|TIME/i;
const NUMBER = /INT|FLOAT|NUMERIC|DECIMAL|DOUBLE|REAL/i;
export const isTime = (f: EntityField) => ["timestamp", "date", "time"].includes(f.role) || TIME.test(f.type);
/** A category a reader filters or splits by — what `from_object.py` offers as a filter. */
export const isCategory = (f: EntityField) =>
  !isTime(f) && (["dimension", "flag", "ordinal"].includes(f.role) || /BOOL/i.test(f.type));
export const isNumber = (f: EntityField) => !isTime(f) && f.role !== "key" && (f.role === "measure" || NUMBER.test(f.type));
const isMoney = (f?: EntityField) => !!f && /^(USD|EUR|GBP|JPY|INR|CNY|CHF|AUD|CAD|SEK|NOK|DKK)$/i.test(f.unit);
/** Numbers in the order a measure is offered them: money first, then what the ontology calls a measure, then any
 *  other number — so "The sum of" starts at revenue, not at the first count a table happens to hold. */
const ranked = (fs: EntityField[]) => fs.map((f, i) => ({ f, i }))
  .sort((a, b) => (isMoney(a.f) ? 0 : a.f.role === "measure" ? 1 : 2) - (isMoney(b.f) ? 0 : b.f.role === "measure" ? 1 : 2) || a.i - b.i)
  .map(x => x.f);

/** The most linked objects whose properties are offered — the bound `from_object.py` keeps for its filters. */
const MAX_LINKS = 3;

const read = new Map<string, Promise<EntityFields>>();

/** What an entity offers a setup: its own properties but its key, and those of each object it links to one of — once
 *  per entity per page. A property's role is the ontology's own. */
export function entityFields(entity: string, connectionId: string, schema?: string): Promise<EntityFields> {
  const id = `${connectionId}/${schema ?? ""}/${entity}`;
  let p = read.get(id);
  if (!p) {
    p = (async () => {
      const t = await getObjectType(entity, connectionId, schema);
      if (!("properties" in t)) throw new Error("This entity is not one the ontology serves here.");
      const own = (props: TypeProperty[], prefix = "", via?: string): EntityField[] => props.filter(x => !x.is_key).map(x => ({
        path: `${prefix}${x.name}`, label: x.display_name || words(x.name), via, role: x.role, type: x.data_type, unit: x.unit }));
      const type = t as ObjectTypeDetail;
      const seen = new Set<string>();
      const toOne = [...type.links].filter(l => l.kind === "to-one" && l.traversable).sort((a, b) => a.name.length - b.name.length);
      // one link per object linked to — the shortest name — so a property is offered once, not once per link
      const links = toOne.filter(l => (seen.has(l.to) ? false : (seen.add(l.to), true))).slice(0, MAX_LINKS);
      const linked = await Promise.all(links.map(async l => {
        try {
          const lt = await getObjectType(l.to, connectionId, schema);
          return "properties" in lt ? own((lt as ObjectTypeDetail).properties, `${l.name}.`, l.to_name || words(l.to)) : [];
        } catch { return []; }
      }));
      return { fields: [...own(type.properties), ...linked.flat()], segments: type.segments ?? [],
        links: toOne.map(l => ({ name: l.name, to: l.to })), offeredFor: Object.fromEntries(links.map(l => [l.to, l.name])) };
    })();
    read.set(id, p);
    p.catch(() => read.delete(id));
  }
  return p;
}

function useEntityFields(entity: string | undefined, connectionId: string, schema?: string): EntityFields | { problem: string } | null {
  // what was read is kept with what it was read for, so another entity chosen shows nothing until its own is read
  const id = entity ? `${connectionId}/${schema ?? ""}/${entity}` : "";
  const [got, setGot] = useState<{ id: string; out: EntityFields | { problem: string } } | null>(null);
  useEffect(() => {
    if (!entity) return;
    let alive = true;
    entityFields(entity, connectionId, schema)
      .then(f => { if (alive) setGot({ id, out: f }); })
      .catch(e => { if (alive) setGot({ id, out: { problem: (e as Error).message } }); });
    return () => { alive = false; };
  }, [id, entity, connectionId, schema]);
  return got && got.id === id ? got.out : null;
}

// ── the fields a setup is made of ────────────────────────────────────────────────────────────────────────────────────

function Row({ label, right, hint, children, testid }: { label: string; right?: ReactNode; hint?: ReactNode; children: ReactNode; testid?: string }) {
  return (
    <div data-testid={testid} style={{ display: "flex", flexDirection: "column", gap: 6, padding: "10px 14px" }}>
      <div className="aug-fs-xs" style={{ display: "flex", alignItems: "baseline", gap: 6, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>
        {label}{right && <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }}>{right}</span>}
      </div>
      {children}
      {hint && <div className="aug-fs-xs" style={{ color: "var(--t3)", lineHeight: 1.45 }}>{hint}</div>}
    </div>
  );
}

/** A person's words, kept when they leave the field or press Enter — and only when there are some. */
function Words({ label, value, max, onSave, many }: { label: string; value: string; max: number; onSave: (v: string) => void; many?: boolean }) {
  const [text, setText] = useState(value);
  // a value changed from elsewhere — an undo, another cockpit — replaces what the field shows
  const [shown, setShown] = useState(value);
  if (shown !== value) { setShown(value); setText(value); }
  const save = () => {
    const t = text.trim().slice(0, max);
    if (t && t !== value) onSave(t);
    else setText(value);
  };
  return many ? (
    <Textarea aria-label={label} value={text} rows={5} onChange={e => setText(e.target.value)} onBlur={save} />
  ) : (
    <Input aria-label={label} value={text} maxLength={max} onChange={e => setText(e.target.value)} onBlur={save}
      onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
  );
}

function Pick({ label, value, options, onPick, none, disabled }: {
  label: string; value: string; options: { value: string; label: string }[]; onPick: (v: string) => void; none?: string; disabled?: boolean;
}) {
  return (
    <SelectField aria-label={label} value={value} disabled={disabled} onChange={e => onPick(e.target.value)}>
      {none !== undefined && <option value="">{none}</option>}
      {withUniqueKeys(options, o => o.value).map(([k, o]) => <option key={k} value={o.value}>{o.label}</option>)}
    </SelectField>
  );
}

const fieldLabel = (f: EntityField) => (f.via ? `${f.label} via ${f.via}` : f.label);

/** The fields a piece is offered: an object it already reads through another link than the one offered keeps being
 *  read through its own — "Country via Customer", ticked, rather than a second Country or a path in its raw words. */
export function fieldsFor(ef: EntityFields, chosen: (string | null | undefined)[]): EntityField[] {
  const swap = new Map<string, string>();
  for (const path of chosen) {
    const name = path && path.includes(".") ? path.slice(0, path.indexOf(".")) : "";
    const link = name ? ef.links.find(l => l.name === name) : undefined;
    const offered = link ? ef.offeredFor[link.to] : undefined;
    if (offered && offered !== name) swap.set(offered, name);
  }
  if (!swap.size) return ef.fields;
  return ef.fields.map(f => {
    const pre = f.path.includes(".") ? f.path.slice(0, f.path.indexOf(".")) : "";
    return swap.has(pre) ? { ...f, path: `${swap.get(pre)}${f.path.slice(pre.length)}` } : f;
  });
}
const asOptions = (fs: EntityField[]) => fs.map(f => ({ value: f.path, label: fieldLabel(f) }));
/** A path the setup names that the entity no longer offers is still shown, as itself, so nothing reads as lost. */
const keeping = (opts: { value: string; label: string }[], ...paths: (string | null | undefined)[]) =>
  [...opts, ...paths.filter((p): p is string => !!p && !opts.some(o => o.value === p)).map(p => ({ value: p, label: words(p) }))];

const TONE_WORDS: Record<string, string> = { good: "Good", warn: "Watch", bad: "Bad", info: "Note", neutral: "Plain" };

const AGG_WORDS: Record<string, string> = {
  count: "How many", count_distinct: "How many different", sum: "The sum of", avg: "The average of", min: "The least", max: "The most",
};

type Props = Record<string, unknown>;
type Change = (next: CockpitSpec, note: string) => void;

/** Where a placed element sits, and a door to move it to another section — or a new one. */
function SectionPick({ spec, k, onChange }: { spec: CockpitSpec; k: string; onChange: Change }) {
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const sections = sectionsOf(spec);
  const here = sections.find(s => spec.elements[s.key]?.children.includes(k))?.key ?? "";
  if (naming) {
    return (
      <Row label="In the section">
        <div style={{ display: "flex", gap: 6 }}>
          <Input autoFocus aria-label="Name of the new section" placeholder="Name of the new section" value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && name.trim()) { onChange(moveCardToNewSection(spec, k, name), "moved to a new section by hand"); setNaming(false); setName(""); }
              if (e.key === "Escape") setNaming(false);
            }} />
          <Button size="xs" variant="ghost" onClick={() => setNaming(false)}>Cancel</Button>
        </div>
      </Row>
    );
  }
  return (
    <Row label="In the section">
      <Pick label="In the section" value={here} onPick={v => (v === "__new__" ? setNaming(true) : onChange(moveCardTo(spec, k, v), "moved by hand"))}
        options={[...sections.map(s => ({ value: s.key, label: s.tabLabel ? `${s.tabLabel} · ${s.title}` : s.title })), { value: "__new__", label: "A new section…" }]} />
    </Row>
  );
}

// ── one setup per kind ───────────────────────────────────────────────────────────────────────────────────────────────

function TableSetup({ p, ef, set, noun }: { p: Props; ef: EntityFields; set: (patch: Props, note: string) => void; noun: string }) {
  const chosen = (p.columns as string[] | null | undefined) ?? [];
  const fields = fieldsFor(ef, [...chosen, p.sort as string]);
  const offered = keeping(asOptions(fields), ...chosen);
  const full = chosen.length >= MAX_TABLE_COLUMNS;
  const toggle = (path: string) => {
    const next = chosen.includes(path) ? chosen.filter(c => c !== path) : [...chosen, path];
    set({ columns: next.length ? next : null }, "a table's columns chosen by hand");
  };
  return (
    <>
      <Row label="Lists" hint={p.segment ? "The segment's objects only, a page at a time." : "Every object, a page at a time."}>
        <Pick label="Segment" value={String(p.segment ?? "")} none={`Every ${noun}`}
          options={keeping(ef.segments.map(s => ({ value: s, label: words(s) })), p.segment as string)}
          onPick={v => set({ segment: v || null }, "a table's segment chosen by hand")} />
      </Row>
      <Row label="Columns" right={`${chosen.length} of ${MAX_TABLE_COLUMNS}`} testid="setup-columns"
        hint="Beside each object's key, in the order chosen.">
        <div style={{ display: "flex", flexDirection: "column", gap: 2, maxHeight: 260, overflow: "auto" }}>
          {withUniqueKeys(offered, o => o.value).map(([key, o]) => {
            const on = chosen.includes(o.value);
            return (
              <label key={key} className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 0", color: on ? "var(--t1)" : "var(--t2)" }}>
                <Checkbox checked={on} disabled={!on && full} onChange={() => toggle(o.value)} aria-label={o.label} />
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{o.label}</span>
                {on && <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{chosen.indexOf(o.value) + 1}</span>}
              </label>
            );
          })}
        </div>
      </Row>
      <Row label="Sorted by">
        <Pick label="Sorted by" value={String(p.sort ?? "")} none="The key" options={keeping(asOptions(fields), p.sort as string)}
          onPick={v => set({ sort: v || null, descending: v ? (p.descending ?? true) : null }, "a table's order chosen by hand")} />
        {!!p.sort && (
          <Segmented label="Order" value={p.descending ? "desc" : "asc"}
            options={[{ value: "desc", label: "Descending" }, { value: "asc", label: "Ascending" }]}
            onChange={v => set({ descending: v === "desc" }, "a table's order chosen by hand")} />
        )}
      </Row>
    </>
  );
}

/** The measure of a figure or a chart: what it counts or adds up, of which property, and how it is written. */
function MeasureRows({ p, ef, aggs, set, note }: {
  p: Props; ef: EntityFields; aggs: readonly string[]; set: (patch: Props, note: string) => void; note: string;
}) {
  const agg = String(p.agg ?? "count");
  const fields = fieldsFor(ef, [p.path as string]);
  const numbers = ranked(fields.filter(isNumber));
  const any = fields.filter(f => !isTime(f));
  const of = agg === "count_distinct" ? any : numbers;
  const pickAgg = (v: string) => {
    if (v === "count") { set({ agg: "count", path: null, format: null }, note); return; }
    const pool = v === "count_distinct" ? any : numbers;
    const path = pool.some(f => f.path === p.path) ? String(p.path) : pool[0]?.path;
    if (!path) return;
    // how it is written follows what it reads: money for a currency, a number otherwise — the person may say money after
    set({ agg: v, path, format: v !== "count_distinct" && isMoney(fields.find(f => f.path === path)) ? "money" : null }, note);
  };
  return (
    <>
      <Row label="Measures">
        <Pick label="Measure" value={agg} onPick={pickAgg}
          options={aggs.filter(a => a === "count" || (a === "count_distinct" ? any.length : numbers.length)).map(a => ({ value: a, label: AGG_WORDS[a] ?? a }))} />
        {agg !== "count" && (
          <Pick label="Of" value={String(p.path ?? "")} options={keeping(asOptions(of), p.path as string)}
            onPick={v => set({ path: v, format: isMoney(fields.find(f => f.path === v)) && agg !== "count_distinct" ? "money" : null }, note)} />
        )}
      </Row>
      {agg !== "count" && agg !== "count_distinct" && (
        <Row label="Written as">
          <Segmented label="Written as" value={String(p.format ?? "number")}
            options={[{ value: "number", label: "A number" }, { value: "money", label: "Money" }]}
            onChange={v => set({ format: v }, note)} />
        </Row>
      )}
    </>
  );
}

function FigureSetup({ p, ef, set }: { p: Props; ef: EntityFields; set: (patch: Props, note: string) => void }) {
  return (
    <>
      <Row label="Label"><Words label="Label" value={String(p.label ?? "")} max={MAX_LABEL} onSave={v => set({ label: v }, "a figure's label written by hand")} /></Row>
      <MeasureRows p={p} ef={ef} aggs={FIGURE_AGGS} note="a figure's measure chosen by hand" set={set} />
    </>
  );
}

function ChartSetup({ p, ef, set }: { p: Props; ef: EntityFields; set: (patch: Props, note: string) => void }) {
  const fields = fieldsFor(ef, [p.time as string, p.split as string]);
  const times = fields.filter(isTime);
  const categories = fields.filter(isCategory);
  const agg = String(p.agg ?? "count");
  const splits = (SPLIT_AGGS as readonly string[]).includes(agg);
  return (
    <>
      <Row label="Label"><Words label="Label" value={String(p.label ?? "")} max={MAX_LABEL} onSave={v => set({ label: v }, "a chart's label written by hand")} /></Row>
      <Row label="Across" hint="A date the objects hold: one bar a day, over the last days they hold.">
        <Pick label="Across" value={String(p.time ?? "")} options={keeping(asOptions(times), p.time as string)}
          onPick={v => set({ time: v }, "a chart's date chosen by hand")} />
      </Row>
      <Row label="Days">
        <Segmented label="Days" value={String(p.days ?? 30)} options={CHART_DAYS.map(d => ({ value: String(d), label: String(d) }))}
          onChange={v => set({ days: Number(v) }, "a chart's days chosen by hand")} />
      </Row>
      {/* a chart that counts says no measure at all, as it did before it could say one */}
      <MeasureRows p={p} ef={ef} aggs={p.split ? SPLIT_AGGS : FIGURE_AGGS} note="a chart's measure chosen by hand"
        set={(patch, note) => set({ ...patch, ...(patch.agg === "count" ? { agg: null } : {}) }, note)} />
      <Row label="Split by" testid="setup-split"
        hint={!splits ? "A split stacks its bars, so it measures how many or a sum."
          : p.split ? "Its most common values, each in its own colour; the rest are folded into Other." : undefined}>
        <Pick label="Split by" value={String(p.split ?? "")} none="Nothing" options={keeping(asOptions(categories), p.split as string)}
          disabled={!splits && !p.split} onPick={v => set({ split: v || null, top: v ? (p.top ?? null) : null }, "a chart's split chosen by hand")} />
        {!!p.split && (
          <Segmented label="Values drawn" value={String(p.top ?? 5)} options={CHART_TOPS.map(t => ({ value: String(t), label: `Top ${t}` }))}
            onChange={v => set({ top: Number(v) === 5 ? null : Number(v) }, "a chart's split chosen by hand")} />
        )}
      </Row>
    </>
  );
}

function FiltersSetup({ p, ef, set }: { p: Props; ef: EntityFields; set: (patch: Props, note: string) => void }) {
  type F = { path: string; label: string; via?: string | null };
  const list = (p.properties as F[] | undefined) ?? [];
  const free = fieldsFor(ef, list.map(x => x.path)).filter(f => isCategory(f) && !list.some(x => x.path === f.path));
  const put = (next: F[], note: string) => set({ properties: next }, note);
  const move = (i: number, d: number) => {
    const next = [...list];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    put(next, "the filter column arranged by hand");
  };
  return (
    <>
      <Row label="Filters by" right={`${list.length} of ${MAX_FILTERS}`} testid="setup-filters"
        hint="Each reader's clicks are their own, and narrow every piece over the same objects.">
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 2 }}>
          {withUniqueKeys(list, f => f.path).map(([key, f], i) => (
            <li key={key} className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 4, color: "var(--t1)" }}>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {f.label}{f.via && <span style={{ color: "var(--vio4)" }}> via {f.via}</span>}
              </span>
              <Button size="xs" variant="ghost" aria-label={`Move ${f.label} up`} disabled={i === 0} onClick={() => move(i, -1)}><Icon name="chevu" size={12} /></Button>
              <Button size="xs" variant="ghost" aria-label={`Move ${f.label} down`} disabled={i === list.length - 1} onClick={() => move(i, 1)}><Icon name="chevd" size={12} /></Button>
              <Button size="xs" variant="ghost" aria-label={`Take ${f.label} off`} disabled={list.length === 1}
                onClick={() => put(list.filter(x => x.path !== f.path), "a filter taken off by hand")}><Icon name="close" size={12} /></Button>
            </li>
          ))}
        </ul>
        {list.length < MAX_FILTERS && free.length > 0 && (
          <Pick label="Add a filter" value="" none="+ Add a filter" options={asOptions(free)}
            onPick={v => {
              const f = free.find(x => x.path === v);
              if (f) put([...list, { path: f.path, label: f.label.slice(0, MAX_LABEL), ...(f.via ? { via: f.via.slice(0, MAX_LABEL) } : {}) }], "a filter added by hand");
            }} />
        )}
      </Row>
    </>
  );
}

function ProcessSetup({ p, connectionId, schema, set }: { p: Props; connectionId: string; schema?: string; set: (patch: Props, note: string) => void }) {
  const [processes, setProcesses] = useState<{ value: string; label: string }[]>([]);
  useEffect(() => {
    let alive = true;
    getProcesses(connectionId, schema).then(r => { if (alive) setProcesses(r.processes.map(x => ({ value: x.id, label: x.display_name || words(x.id) }))); })
      .catch(() => { /* the process it names stays offered */ });
    return () => { alive = false; };
  }, [connectionId, schema]);
  return (
    <Row label="Process" hint="Each stage, how often each promise is broken, and the objects open past it.">
      <Pick label="Process" value={String(p.process ?? "")} options={keeping(processes, p.process as string)}
        onPick={v => v && set({ process: v }, "a board's process chosen by hand")} />
    </Row>
  );
}

function ActionSetup({ spec, k, p, connectionId, schema, set }: {
  spec: CockpitSpec; k: string; p: Props; connectionId: string; schema?: string; set: (patch: Props, note: string) => void;
}) {
  const [actions, setActions] = useState<Record<string, DeclaredAction>>({});
  useEffect(() => {
    let alive = true;
    getDeclaredActions(connectionId, schema).then(a => { if (alive) setActions(a); }).catch(() => { /* the action it names stays offered */ });
    return () => { alive = false; };
  }, [connectionId, schema]);
  // the detail holding the button follows a table: the actions offered are the ones that take one of its objects
  const detail = Object.entries(spec.elements).find(([, el]) => el.type === "ObjectDetail" && el.children.includes(k))?.[1];
  const entity = String(spec.elements[String(detail?.props.follows ?? "")]?.props.entity ?? "").toLowerCase();
  const fits = Object.values(actions).filter(a => !entity || a.params.some(x => x.kind === "object" && x.object_type.toLowerCase() === entity));
  return (
    <Row label="Action" hint="Run on the object the detail shows — or proposed for approval when it needs one.">
      <Pick label="Action" value={String(p.action ?? "")} options={keeping(fits.map(a => ({ value: a.id, label: a.display_name || words(a.id) })), p.action as string)}
        onPick={v => v && set({ action: v }, "a button's action chosen by hand")} />
    </Row>
  );
}

// ── the panel ────────────────────────────────────────────────────────────────────────────────────────────────────────

export function PieceSetup({ spec, selected, onChange, connectionId, schema, cardTitle, entityTitle }: {
  spec: CockpitSpec;
  selected: string | null;
  onChange: Change;
  connectionId: string;
  schema?: string;
  cardTitle?: (id: string) => string | undefined;
  /** The name the ontology gives an entity, where the caller knows it. */
  entityTitle?: (id: string) => string | undefined;
}) {
  const el = selected ? spec.elements[selected] : undefined;
  const entity = el && ["ObjectTable", "ObjectFigure", "ObjectChart", "ObjectFilters"].includes(el.type) ? String(el.props.entity ?? "") : undefined;
  const ef = useEntityFields(entity, connectionId, schema);
  if (!selected || !el) {
    return (
      <div className="aug-fs-sm" data-testid="setup-empty" style={{ padding: "16px 14px", color: "var(--t3)", lineHeight: 1.5 }}>
        Choose a piece on the cockpit, or a line in its layout, to set it up. Its size moves one grade at a time — drag an
        edge, use − and + above the cockpit, or Alt and the arrow keys.
      </div>
    );
  }
  const k = selected;
  const p = el.props as Props;
  const set = (patch: Props, note: string) => onChange(setProps(spec, k, patch), note);
  const named = nameOf(spec.elements, k, cardTitle, entityTitle);
  const noun = entity ? entityTitle?.(entity) ?? words(entity) : "";
  const kind = named.kind.charAt(0).toUpperCase() + named.kind.slice(1);
  const title = named.title;
  const needsFields = entity !== undefined;
  const fieldsBody = (body: (ef: EntityFields) => ReactNode) => (
    !ef ? <div className="aug-fs-sm" style={{ padding: "10px 14px", color: "var(--t3)" }}>Reading what {noun} holds…</div>
      : "problem" in ef ? <div className="aug-fs-sm" style={{ padding: "10px 14px", color: "var(--t2)" }}>What {noun} holds could not be read: {ef.problem}</div>
        : body(ef)
  );
  const placed = !["Cockpit", "Tabs", "Tab", "Section", "ObjectFilters", "ActionButton"].includes(el.type);
  return (
    <div data-testid="piece-setup" data-kind={el.type}>
      <div style={{ padding: "12px 14px 8px", borderBottom: "1px solid var(--b1)" }}>
        <div className="aug-fs-xs" style={{ color: "var(--accent-11)", textTransform: "uppercase", letterSpacing: ".06em" }}>{kind}</div>
        <div className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis" }}>{title || kind}</div>
      </div>
      {el.type === "Cockpit" && (
        <Row label="Name"><Words label="Name" value={String(p.title ?? "")} max={MAX_TITLE} onSave={v => onChange(rename(spec, k, v), "renamed by hand")} /></Row>
      )}
      {el.type === "Tab" && (
        <Row label="Label"><Words label="Label" value={String(p.label ?? "")} max={MAX_LABEL} onSave={v => onChange(rename(spec, k, v), "a tab renamed by hand")} /></Row>
      )}
      {el.type === "Section" && (
        <>
          <Row label="Title"><Words label="Title" value={String(p.title ?? "")} max={MAX_TITLE} onSave={v => onChange(rename(spec, k, v), "a section renamed by hand")} /></Row>
          {tabsOf(spec).length > 0 && (
            <Row label="In the tab">
              <Pick label="In the tab" value={tabsOf(spec).find(t => spec.elements[t.key]?.children.includes(k))?.key ?? ""}
                options={tabsOf(spec).map(t => ({ value: t.key, label: t.label }))} onPick={v => onChange(moveSectionTo(spec, k, v), "a section moved by hand")} />
            </Row>
          )}
          <Row label="Laid out" hint={p.grid ? "Twelve columns, and rows of 40 px: each piece moves one grade at a time."
            : "By size. Resize anything in it and it moves onto the twelve-column grid, each piece keeping its room."}>
            <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>{p.grid ? "On the grid" : `${p.columns ?? "Up to 4"} columns`}</span>
          </Row>
        </>
      )}
      {el.type === "Card" && (
        <>
          <Row label="Edge" hint="A coloured edge is emphasis. What the card measures is the card's own.">
            <Pick label="Edge" value={String(p.tone ?? "")} none="None" options={TONES.map(t => ({ value: t, label: TONE_WORDS[t] }))}
              onPick={v => set({ tone: v || null }, "a card's edge chosen by hand")} />
          </Row>
        </>
      )}
      {el.type === "Note" && (
        <Row label="Words" hint="Yours, stamped with your name and today when kept. A model never writes one.">
          <Words many label="Words" value={String(p.text ?? "")} max={MAX_NOTE} onSave={v => onChange(editNote(spec, k, v), "a note's words changed by hand")} />
        </Row>
      )}
      {el.type === "Image" && (
        <Row label="Caption"><Words label="Caption" value={String(p.caption ?? "")} max={MAX_CAPTION} onSave={v => onChange(recaption(spec, k, v), "an image's caption changed by hand")} /></Row>
      )}
      {el.type === "ProcessBoard" && <ProcessSetup p={p} connectionId={connectionId} schema={schema} set={set} />}
      {el.type === "ObjectDetail" && (
        <Row label="Shows the object chosen in">
          <Pick label="Follows" value={String(p.follows ?? "")} onPick={v => v && set({ follows: v }, "a detail's table chosen by hand")}
            options={Object.keys(spec.elements).filter(x => spec.elements[x].type === "ObjectTable").map(x => ({ value: x, label: lineOf(spec.elements, x) }))} />
        </Row>
      )}
      {el.type === "ActionButton" && <ActionSetup spec={spec} k={k} p={p} connectionId={connectionId} schema={schema} set={set} />}
      {needsFields && el.type === "ObjectTable" && fieldsBody(f => <TableSetup p={p} ef={f} set={set} noun={noun} />)}
      {needsFields && el.type === "ObjectFigure" && fieldsBody(f => <FigureSetup p={p} ef={f} set={set} />)}
      {needsFields && el.type === "ObjectChart" && fieldsBody(f => <ChartSetup p={p} ef={f} set={set} />)}
      {needsFields && el.type === "ObjectFilters" && fieldsBody(f => <FiltersSetup p={p} ef={f} set={set} />)}
      {placed && <SectionPick spec={spec} k={k} onChange={onChange} />}
    </div>
  );
}
