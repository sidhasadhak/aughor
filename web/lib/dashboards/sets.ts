/**
 * A dashboard's sets, values and choices (Arc AP-2; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.1b and §4.3).
 *
 * A set is a named group of objects pieces read: an entity, or another set it starts from, kept to one segment and the
 * author's conditions, and — for what an object links to — to the objects whose `path` is the key of the object a
 * reader chose. A choice is what a reader's click makes: the object chosen in a table (`chooses`), the objects ticked in
 * it (`ticks`), the set a figure shows in a table's stead (`shows`). A value is what the author sets once and sets read
 * ("Window · 14 days"). Wiring is by name, never by expression: each is a literal string the rules check resolves.
 *
 * ONE home for what a set reads. The browser asks the object door with it; the server runs the same function through
 * the validator bundle and compiles each set before a dashboard is kept (`aughor/dashboards/pieces.py`), so the two cannot
 * come to read a set differently.
 */
import {
  CHOOSERS, MAX_SET_DEPTH, TICKERS, type ActionButtonDef, type DashboardSetDef, type DashboardValueDef, type PieceName, type SetOp,
} from "@/lib/dashboards/catalog";
import { valuesRead } from "@/lib/dashboards/values";

type El = { type?: string; props?: Record<string, unknown>; children?: string[] };
export interface WireSpec {
  sets?: Record<string, DashboardSetDef> | null;
  values?: Record<string, DashboardValueDef> | null;
  elements: Record<string, El | undefined>;
}

/** Arc AP-8b — a condition that reads whole sets: the object is in any of them, or in none. */
export type SetRelation = "in_set" | "not_in_set";
/** One condition as the object door reads it. Arc AP-8b — one that reads whole sets holds them as reads (`reads`) until
 *  the choices they wait on are known; the door is sent them as `sets` (`doorConditions`). */
export interface DoorCondition { path: string; op: SetOp | SetRelation; value?: unknown; values?: unknown[]; [more: string]: unknown }
/** A set inside a condition, as it is read: another set's read and — for one of another entity — the link of its
 *  objects that reaches this set's own. */
interface SetInSet { read: SetRead; via?: string }

/** A set as the object door reads it: its entity and segment, and every condition down the sets it starts from — a
 *  value's condition with the value in place — and the choice it waits on, when it reads what an object links to. */
export interface SetRead {
  /** The set's name; "" for the set of every object of an entity a piece names directly. */
  name: string;
  label: string;
  entity: string;
  segment: string;
  where: DoorCondition[];
  linkedTo: { choice: string; path: string } | null;
  /** The set, then each it starts from. */
  chain: string[];
  /** Arc AP-8 — a value it reads that is not there yet: the choice a value read from a chosen object waits on, or a
   *  value still being counted. */
  pending?: { waiting: string } | { reading: true };
}

/** Arc AP-8 — what a value holds now, as the page knows it: a value; the choice a value read from a chosen object waits
 *  on; still being read (a count, a chosen object's property); or why it cannot be read. */
export type ValueNow = { value: unknown } | { waiting: string } | { reading: true } | { refused: string };
export type Refused = { refused: string };
export const isRefused = (r: unknown): r is Refused => typeof r === "object" && r !== null && "refused" in r;

const q = (s: string) => JSON.stringify(s);

/** What `name` reads, or why it cannot be read: a set it starts from that is not there, a ring of sets each starting
 *  from the next, two segments down one chain, a value no one set. Arc AP-8b — then, in order, the objects its objects
 *  reach through a link (`traverse`), and the set it is combined with (`combine`): either, both, or but not. A set that
 *  reads another one whole — one it starts from that traverses or combines, one it combines with — reads it as a set,
 *  never as conditions merged into its own, so each condition holds on one object. */
export function readSet(spec: WireSpec, name: string, valueOf?: (value: string) => ValueNow, visiting: string[] = []): SetRead | Refused {
  if (visiting.includes(name)) return { refused: `The sets ${[...visiting, name].map(q).join(" → ")} read each other in a ring.` };
  if (visiting.length >= MAX_SET_DEPTH) return { refused: `The set ${q(visiting[0])} reads sets more than ${MAX_SET_DEPTH} deep.` };
  const own = spec.sets?.[name];
  const base = walkSet(spec, name, valueOf, [...visiting, name]);
  if (isRefused(base) || !own) return base;
  let r: SetRead = base;
  if (own.traverse) {
    r = { name, label: own.label ?? name, entity: own.traverse.entity, segment: "", linkedTo: null, chain: base.chain,
      where: [{ path: "", op: "in_set", reads: [{ read: base, via: own.traverse.link }] }], ...(base.pending ? { pending: base.pending } : {}) };
  }
  if (own.combine) {
    const other = readSet(spec, own.combine.set, valueOf, [...visiting, name]);
    if (isRefused(other)) {
      return { refused: other.refused.includes(" in a ring") || other.refused.includes(" deep.") ? other.refused
        : `The set ${q(name)} is combined with ${q(own.combine.set)}, which cannot be read: ${other.refused}` };
    }
    if (other.entity !== r.entity) {
      return { refused: `The set ${q(name)} holds ${r.entity} objects and is combined with ${q(own.combine.set)}, which holds ${other.entity}. Sets combined hold the same entity.` };
    }
    const pending = r.pending ?? other.pending;
    const op = own.combine.op;
    r = op === "either"
      ? { name, label: r.label, entity: r.entity, segment: "", linkedTo: null, chain: r.chain,
        where: [{ path: "", op: "in_set", reads: [{ read: { ...r, pending: undefined } }, { read: { ...other, pending: undefined } }] }] }
      : { ...r, where: [...r.where, { path: "", op: op === "both" ? "in_set" : "not_in_set", reads: [{ read: { ...other, pending: undefined } }] }] };
    if (pending) r.pending = pending; else delete r.pending;
  }
  return r;
}

/** A set's own start, segment, conditions and chosen-object link, down the sets it starts from — and a set it starts
 *  from that traverses or combines, read whole (Arc AP-8b). */
function walkSet(spec: WireSpec, name: string, valueOf: ((value: string) => ValueNow) | undefined, visiting: string[]): SetRead | Refused {
  const sets = spec.sets ?? {};
  const values = spec.values ?? {};
  const chain: string[] = [];
  const where: DoorCondition[] = [];
  let segment = "";
  let linkedTo: SetRead["linkedTo"] = null;
  let pending: SetRead["pending"];
  let at: string | null | undefined = name;
  while (at) {
    if (chain.includes(at)) return { refused: `The sets ${[...chain, at].map(q).join(" → ")} start from each other in a ring.` };
    const set: DashboardSetDef | undefined = sets[at];
    if (!set) {
      return { refused: chain.length ? `The set ${q(chain[chain.length - 1])} starts from ${q(at)}, which this dashboard does not hold.`
        : `This dashboard holds no set named ${q(at)}.` };
    }
    if (chain.length && (set.traverse || set.combine)) {
      // a set it starts from that reaches other objects, or is combined: its objects, read whole
      const inner = readSet(spec, at, valueOf, [...visiting, ...chain.slice(1)]);
      if (isRefused(inner)) return inner;
      where.push({ path: "", op: "in_set", reads: [{ read: { ...inner, pending: undefined } }] });
      pending = pending ?? inner.pending;
      return { name, label: sets[name]?.label ?? name, entity: inner.entity, segment, where, linkedTo, chain: [...chain, ...inner.chain],
        ...(pending ? { pending } : {}) };
    }
    chain.push(at);
    if (set.segment) {
      if (segment && segment !== set.segment) {
        return { refused: `The set ${q(name)} keeps two segments down the sets it starts from (${q(segment)} and ${q(set.segment)}). A set keeps one.` };
      }
      segment = set.segment;
    }
    if (set.linked_to) {
      if (linkedTo) return { refused: `The set ${q(name)} is linked to two chosen objects down the sets it starts from. It is linked to one.` };
      linkedTo = { choice: set.linked_to.choice, path: set.linked_to.path };
    }
    for (const c of set.where ?? []) {
      const cond: DoorCondition = { path: c.path, op: c.op };
      if (c.value_from) {
        const v = values[c.value_from];
        if (!v) return { refused: `The set ${q(at)} reads the value ${q(c.value_from)}, which this dashboard does not hold.` };
        if (c.op === "in_last" && v.kind !== "days") {
          return { refused: `The set ${q(at)} counts the last days by the value ${q(c.value_from)}, which is a ${v.kind}, not a number of days.` };
        }
        // Arc AP-8c — a list keeps objects among it, and only a list does
        const among = c.op === "in" || c.op === "not_in";
        if (among !== (v.kind === "list")) {
          return { refused: among ? `The set ${q(at)} keeps ${c.path} among the value ${q(c.value_from)}, which is not a list.`
            : `The set ${q(at)} compares ${c.path} with the list ${q(c.value_from)}. A list keeps objects among it: in or not_in.` };
        }
        // the value as the page holds it now — the reader's, a count, the chosen object's — else the one the author set
        const now: ValueNow = valueOf ? valueOf(c.value_from) : { value: v.value ?? null };
        if ("refused" in now) return { refused: `The set ${q(at)} reads the value ${q(c.value_from)}, which cannot be read: ${now.refused}` };
        if ("value" in now) {
          if (among) cond.values = Array.isArray(now.value) ? now.value : now.value === null || now.value === undefined ? [] : [now.value];
          else cond.value = now.value;
        } else pending = pending ?? now;
      } else if (c.op === "in" || c.op === "not_in") {
        cond.values = c.values ?? [];
      } else if (c.op !== "is_null" && c.op !== "not_null") {
        cond.value = c.value;
      }
      where.push(cond);
    }
    if (set.entity) {
      if (set.from) return { refused: `The set ${q(at)} names an entity and a set it starts from. It names one.` };
      return { name, label: sets[name]?.label ?? name, entity: set.entity, segment, where, linkedTo, chain, ...(pending ? { pending } : {}) };
    }
    if (!set.from) return { refused: `The set ${q(at)} names neither an entity nor a set it starts from.` };
    at = set.from;
  }
  return { refused: `The set ${q(name)} reads nothing.` };
}

/** The names of the sets a dashboard holds. */
export const setNamesOf = (spec: WireSpec): string[] => Object.keys(spec.sets ?? {});

/** Arc AP-8 — a value counted (or, AP-8c, summed) from a set that, down the sets it starts from and the values they
 *  read, reads that value again: the names round the ring, or null. */
export function valueRing(spec: WireSpec): string[] | null {
  const values = spec.values ?? {};
  const sets = spec.sets ?? {};
  const next = (node: string): string[] => {
    if (node.startsWith("v:")) {
      const v = values[node.slice(2)];
      return v?.from?.by === "count" || v?.from?.by === "sum" ? [`s:${v.from.set}`] : [];
    }
    const set = sets[node.slice(2)];
    return set ? [...(set.from ? [`s:${set.from}`] : []), ...(set.combine ? [`s:${set.combine.set}`] : []),
      ...(set.where ?? []).filter(c => c.value_from).map(c => `v:${c.value_from}`)] : [];
  };
  for (const name of Object.keys(values)) {
    if (values[name]?.from?.by !== "count" && values[name]?.from?.by !== "sum") continue;
    const start = `v:${name}`;
    const path: string[] = [];
    const seen = new Set<string>();
    const walk = (node: string): string[] | null => {
      if (node === start && path.length) return [...path, node];
      if (seen.has(node)) return null;
      seen.add(node);
      path.push(node);
      for (const n of next(node)) {
        const found = walk(n);
        if (found) return found;
      }
      path.pop();
      return null;
    };
    const ring = walk(start);
    if (ring) return ring.map(n => n.slice(2));
  }
  return null;
}

/** Arc AP-8c — the values a set reads, down the sets it starts from, reads whole and is combined with — each once. */
function valuesOfSet(spec: WireSpec, name: string, seen: Set<string> = new Set()): string[] {
  if (seen.has(name)) return [];
  seen.add(name);
  const set = spec.sets?.[name];
  if (!set) return [];
  const own = (set.where ?? []).flatMap(c => (c.value_from ? [c.value_from] : []));
  const more = [set.from, set.combine?.set].filter((x): x is string => !!x).flatMap(n => valuesOfSet(spec, n, seen));
  return [...new Set([...own, ...more])];
}

/** Arc AP-8c — the values a value reads to be read: a count's or a sum's set's, and a query's (`cardSql` says the
 *  statement of a card the dashboard places). */
export function valueReads(spec: WireSpec, name: string, cardSql?: (card: string) => string | undefined): string[] {
  const from = spec.values?.[name]?.from;
  if (from?.by === "count" || from?.by === "sum") return valuesOfSet(spec, from.set);
  if (from?.by === "query") return valuesRead(cardSql?.(from.card));
  return [];
}

/** Arc AP-8c — the values round a ring that `name` starts — it reads a value that, down what each reads, reads it back —
 *  or null. A value read from a query that reads it would wait on itself for ever. */
export function readsItself(spec: WireSpec, name: string, cardSql?: (card: string) => string | undefined): string[] | null {
  const path: string[] = [];
  const seen = new Set<string>();
  const walk = (n: string): string[] | null => {
    if (n === name && path.length) return [...path, n];
    if (seen.has(n)) return null;
    seen.add(n);
    path.push(n);
    for (const next of valueReads(spec, n, cardSql)) {
      const found = walk(next);
      if (found) return found;
    }
    path.pop();
    return null;
  };
  return walk(name);
}

/** A value of `kind` that stands for one the page has not read yet, for the server's compile of every set (Arc AP-8). */
export function probeValue(kind: string): unknown {
  return kind === "text" ? "probe" : kind === "date" ? "2026-01-01" : kind === "yesno" ? true : kind === "list" ? ["probe"] : 1;
}

/** Every object of `entity` — the set a piece that names an entity reads, as every piece did before sets. */
export function everyObject(entity: string, segment = ""): SetRead {
  return { name: "", label: "", entity, segment, where: [], linkedTo: null, chain: [] };
}

export type ChoiceKind = "chosen" | "ticked" | "shown";
/** A choice a reader makes, by name: what kind of thing it holds, the pieces that make it, and — for an object chosen
 *  or ticked — the entity those objects are. */
export interface Choice { name: string; kind: ChoiceKind; madeBy: string[]; entity: string }

/** The set a piece reads: the set a figure shows in its stead when one does, else its named set, else every object of
 *  the entity it names. */
export function pieceSet(spec: WireSpec, props: Record<string, unknown>, shown?: (choice: string) => string | null,
  valueOf?: (value: string) => ValueNow): SetRead | Refused {
  const from = typeof props.set_from === "string" ? props.set_from : "";
  const instead = from && shown ? shown(from) : null;
  if (instead) return readSet(spec, instead, valueOf);
  if (typeof props.set === "string" && props.set) return readSet(spec, props.set, valueOf);
  if (typeof props.entity === "string" && props.entity) return everyObject(props.entity, typeof props.segment === "string" ? props.segment : "");
  return { refused: "This piece names neither an entity nor a set." };
}

/** Every choice the dashboard's pieces make, by name. */
export function choicesOf(spec: WireSpec): Map<string, Choice> {
  const out = new Map<string, Choice>();
  const add = (name: unknown, kind: ChoiceKind, key: string, entity: string) => {
    if (typeof name !== "string" || !name) return;
    const had = out.get(name);
    if (had) { had.madeBy.push(key); return; }
    out.set(name, { name, kind, madeBy: [key], entity });
  };
  for (const [key, el] of Object.entries(spec.elements)) {
    const p = el?.props ?? {};
    // a click in a table, a list, a map, a timeline or a choose-one chooses (Arc AP-4); ticks collect in a table or a list
    if (CHOOSERS.includes(el?.type as PieceName)) {
      const r = pieceSet(spec, { ...p, set_from: undefined });
      const entity = isRefused(r) ? "" : r.entity;
      add(p.chooses, "chosen", key, entity);
      if (TICKERS.includes(el?.type as PieceName)) add(p.ticks, "ticked", key, entity);
    } else if (el?.type === "ObjectFigure") {
      add(p.shows, "shown", key, "");
    }
  }
  return out;
}

/** The element keys that read `name` — a set, a value or a choice — and the sets that do, each once. A set nothing reads
 *  may be taken away; one something reads says what. */
export function readersOf(spec: WireSpec, name: string): { elements: string[]; sets: string[]; values: string[] } {
  const elements: string[] = [];
  for (const [key, el] of Object.entries(spec.elements)) {
    const p = el?.props ?? {};
    const named = [p.set, p.of, p.set_from, p.follows].includes(name)
      || (el?.type === "ActionButtons" && ((p.buttons as ActionButtonDef[] | undefined) ?? []).some(b =>
        Object.values(b.params ?? {}).some(s => ("from" in s && s.from === name) || ("set" in s && s.set === name))
        || (b.after?.read ?? []).includes(name)));
    if (named) elements.push(key);
  }
  const sets = Object.entries(spec.sets ?? {}).filter(([, s]) =>
    s.from === name || s.linked_to?.choice === name || s.combine?.set === name || (s.where ?? []).some(c => c.value_from === name)).map(([k]) => k);
  // Arc AP-8 — a value counted or summed from a set reads it; one read from a chosen object reads the choice
  const values = Object.entries(spec.values ?? {}).filter(([, v]) =>
    ((v.from?.by === "count" || v.from?.by === "sum") && v.from.set === name) || (v.from?.by === "chosen" && v.from.choice === name)).map(([k]) => k);
  return { elements, sets, values };
}

/** What a set reads as the object door's conditions — or the choice it waits on, when it reads what a chosen object
 *  links to and nothing is chosen yet. `chosen` names the key of the object a choice holds. */
export function doorConditions(r: SetRead, chosen: (choice: string) => string | null):
  { filters: DoorCondition[] } | { waiting: string } | { reading: true } {
  if (r.pending) return r.pending;
  const filters: DoorCondition[] = [];
  for (const c of r.where) {
    const reads = c.reads as SetInSet[] | undefined;
    if (!reads) { filters.push(c); continue; }
    // Arc AP-8b — each set read whole, its own choices resolved: what the door is sent
    const inSets: Record<string, unknown>[] = [];
    for (const { read, via } of reads) {
      const inner = doorConditions(read, chosen);
      if (!("filters" in inner)) return inner;
      inSets.push({ entity: read.entity, ...(read.segment ? { segment: read.segment } : {}), filters: inner.filters, ...(via ? { via } : {}) });
    }
    filters.push({ path: "", op: c.op, sets: inSets });
  }
  if (r.linkedTo) {
    const pk = chosen(r.linkedTo.choice);
    if (pk === null) return { waiting: r.linkedTo.choice };
    filters.push({ path: r.linkedTo.path, op: "=", value: pk });
  }
  return { filters };
}

/** For the server: each set as the object door would read it — a chosen object stood in for by a probe value, since a
 *  keep compiles every set and runs none — and each button's parameters with the kind and entity of their source. */
export function wiring(spec: WireSpec): {
  sets: Record<string, { entity: string; segment: string; filters: DoorCondition[] } | Refused>;
  buttons: { element: string; index: number; action: string; params: Record<string, { source: string; entity: string }> }[];
  /** Arc AP-8 — each value that is not the author's: where it comes from, and for one read off a chosen object, the
   *  entity that object is and the property read. */
  values: Record<string, { by: string; set?: string; choice?: string; entity?: string; path?: string; card?: string; kind?: string }>;
} {
  const sets: ReturnType<typeof wiring>["sets"] = {};
  for (const name of Object.keys(spec.sets ?? {})) {
    const r = readSet(spec, name, v => {
      const def = spec.values?.[v];
      const by = def?.from?.by ?? "author";
      return { value: by === "author" || by === "reader" ? def?.value ?? null : probeValue(def?.kind ?? "number") };
    });
    if (isRefused(r)) { sets[name] = r; continue; }
    const read = doorConditions(r, () => "probe");
    sets[name] = { entity: r.entity, segment: r.segment, filters: "filters" in read ? read.filters : [] };
  }
  const choices = choicesOf(spec);
  const buttons: ReturnType<typeof wiring>["buttons"] = [];
  for (const [key, el] of Object.entries(spec.elements)) {
    if (el?.type !== "ActionButtons") continue;
    ((el.props?.buttons as ActionButtonDef[] | undefined) ?? []).forEach((b, index) => {
      const params: Record<string, { source: string; entity: string }> = {};
      for (const [param, s] of Object.entries(b.params ?? {})) {
        if ("from" in s) {
          const c = choices.get(s.from);
          params[param] = { source: c?.kind ?? "missing", entity: c?.entity ?? "" };
        } else if ("set" in s) {
          const r = readSet(spec, s.set);
          params[param] = { source: "set", entity: isRefused(r) ? "" : r.entity };
        } else {
          params[param] = { source: "ask" in s ? "ask" : "value", entity: "" };
        }
      }
      buttons.push({ element: key, index, action: b.action, params });
    });
  }
  const values: ReturnType<typeof wiring>["values"] = {};
  for (const [name, v] of Object.entries(spec.values ?? {})) {
    const from = v.from;
    if (!from || from.by === "author") continue;
    if (from.by === "sum") {
      // Arc AP-8c — the property summed, on the entity the set's objects are
      const r = readSet(spec, from.set);
      values[name] = { by: "sum", set: from.set, path: from.path, entity: isRefused(r) ? "" : r.entity };
      continue;
    }
    values[name] = from.by === "chosen" ? { by: "chosen", choice: from.choice, path: from.path, entity: choices.get(from.choice)?.entity ?? "" }
      : from.by === "count" ? { by: "count", set: from.set }
        : from.by === "query" ? { by: "query", card: from.card, kind: v.kind } : { by: from.by };
  }
  return { sets, buttons, values };
}
