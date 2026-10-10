/**
 * A cockpit's sets, values and choices (Arc AP-2; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.1b and §4.3).
 *
 * A set is a named group of objects pieces read: an entity, or another set it starts from, kept to one segment and the
 * author's conditions, and — for what an object links to — to the objects whose `path` is the key of the object a
 * reader chose. A choice is what a reader's click makes: the object chosen in a table (`chooses`), the objects ticked in
 * it (`ticks`), the set a figure shows in a table's stead (`shows`). A value is what the author sets once and sets read
 * ("Window · 14 days"). Wiring is by name, never by expression: each is a literal string the rules check resolves.
 *
 * ONE home for what a set reads. The browser asks the object door with it; the server runs the same function through
 * the validator bundle and compiles each set before a cockpit is kept (`aughor/cockpit/pieces.py`), so the two cannot
 * come to read a set differently.
 */
import type { ActionButtonDef, CockpitSetDef, CockpitValueDef, SetOp } from "@/lib/cockpit/catalog";

type El = { type?: string; props?: Record<string, unknown>; children?: string[] };
export interface WireSpec {
  sets?: Record<string, CockpitSetDef> | null;
  values?: Record<string, CockpitValueDef> | null;
  elements: Record<string, El | undefined>;
}

/** One condition as the object door reads it. */
export interface DoorCondition { path: string; op: SetOp; value?: unknown; values?: unknown[]; [more: string]: unknown }

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
}
export type Refused = { refused: string };
export const isRefused = (r: unknown): r is Refused => typeof r === "object" && r !== null && "refused" in r;

const q = (s: string) => JSON.stringify(s);

/** What `name` reads, or why it cannot be read: a set it starts from that is not there, a ring of sets each starting
 *  from the next, two segments down one chain, a value no one set. */
export function readSet(spec: WireSpec, name: string): SetRead | Refused {
  const sets = spec.sets ?? {};
  const values = spec.values ?? {};
  const chain: string[] = [];
  const where: DoorCondition[] = [];
  let segment = "";
  let linkedTo: SetRead["linkedTo"] = null;
  let at: string | null | undefined = name;
  while (at) {
    if (chain.includes(at)) return { refused: `The sets ${[...chain, at].map(q).join(" → ")} start from each other in a ring.` };
    const set: CockpitSetDef | undefined = sets[at];
    if (!set) {
      return { refused: chain.length ? `The set ${q(chain[chain.length - 1])} starts from ${q(at)}, which this cockpit does not hold.`
        : `This cockpit holds no set named ${q(at)}.` };
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
        if (!v) return { refused: `The set ${q(at)} reads the value ${q(c.value_from)}, which this cockpit does not hold.` };
        if (c.op === "in_last" && v.kind !== "days") {
          return { refused: `The set ${q(at)} counts the last days by the value ${q(c.value_from)}, which is a ${v.kind}, not a number of days.` };
        }
        cond.value = v.value;
      } else if (c.op === "in" || c.op === "not_in") {
        cond.values = c.values ?? [];
      } else if (c.op !== "is_null" && c.op !== "not_null") {
        cond.value = c.value;
      }
      where.push(cond);
    }
    if (set.entity) {
      if (set.from) return { refused: `The set ${q(at)} names an entity and a set it starts from. It names one.` };
      return { name, label: sets[name]?.label ?? name, entity: set.entity, segment, where, linkedTo, chain };
    }
    if (!set.from) return { refused: `The set ${q(at)} names neither an entity nor a set it starts from.` };
    at = set.from;
  }
  return { refused: `The set ${q(name)} reads nothing.` };
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
export function pieceSet(spec: WireSpec, props: Record<string, unknown>, shown?: (choice: string) => string | null): SetRead | Refused {
  const from = typeof props.set_from === "string" ? props.set_from : "";
  const instead = from && shown ? shown(from) : null;
  if (instead) return readSet(spec, instead);
  if (typeof props.set === "string" && props.set) return readSet(spec, props.set);
  if (typeof props.entity === "string" && props.entity) return everyObject(props.entity, typeof props.segment === "string" ? props.segment : "");
  return { refused: "This piece names neither an entity nor a set." };
}

/** Every choice the cockpit's pieces make, by name. */
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
    if (el?.type === "ObjectTable") {
      const r = pieceSet(spec, { ...p, set_from: undefined });
      const entity = isRefused(r) ? "" : r.entity;
      add(p.chooses, "chosen", key, entity);
      add(p.ticks, "ticked", key, entity);
    } else if (el?.type === "ObjectFigure") {
      add(p.shows, "shown", key, "");
    }
  }
  return out;
}

/** The element keys that read `name` — a set, a value or a choice — and the sets that do, each once. A set nothing reads
 *  may be taken away; one something reads says what. */
export function readersOf(spec: WireSpec, name: string): { elements: string[]; sets: string[] } {
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
    s.from === name || s.linked_to?.choice === name || (s.where ?? []).some(c => c.value_from === name)).map(([k]) => k);
  return { elements, sets };
}

/** What a set reads as the object door's conditions — or the choice it waits on, when it reads what a chosen object
 *  links to and nothing is chosen yet. `chosen` names the key of the object a choice holds. */
export function doorConditions(r: SetRead, chosen: (choice: string) => string | null): { filters: DoorCondition[] } | { waiting: string } {
  const filters = [...r.where];
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
} {
  const sets: ReturnType<typeof wiring>["sets"] = {};
  for (const name of Object.keys(spec.sets ?? {})) {
    const r = readSet(spec, name);
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
  return { sets, buttons };
}
