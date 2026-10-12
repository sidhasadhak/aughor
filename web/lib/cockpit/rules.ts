/**
 * The rules a cockpit spec must pass — accepted whole or refused whole, with sentences
 * (Arc CT, CT-2; AV-0's law, ROADMAP §3.11).
 *
 * ONE function, run in two places from this one file: the browser runs it before it draws a
 * spec, and the server runs it, through the validator bundle, before it keeps one. A validator
 * configured unlike its executor has cost this repo before, so there is no second copy.
 *
 * What is checked here needs no knowledge of the platform: the shape of the spec, the props
 * of each component, and what a condition may read. What only the server knows — whether a
 * card id exists in this canvas, whether a title states a figure — is checked there, on the
 * `cards`, `stateCards` and `texts` this function hands back.
 *
 * Refused outright, each for the reason its sentence gives: `watch`, `on`, `repeat`, `slots`,
 * an expression in any prop but the tabs' own binding, a state the spec seeds beyond `/tab`,
 * and a condition that reads anything the host does not publish.
 */
import { validateSpec, type Spec } from "@json-render/core";
import type { z } from "zod";

import {
  CHOOSERS, COCKPIT_VOCABULARY_VERSION, COMPONENT_NAMES, GRADE, GRID, LIMITS, MAX_DEPTH, MAX_SETS, MAX_VALUES, MAY_BE_CONDITIONAL, MAY_HOLD,
  ISO_DAY, MAX_LIST, PLACED, READER_TEXT, SET_READERS, SPLIT_AGGS, SIZES, SWITCHED, TONES, VALUE_OPS, cockpitCatalog, cockpitSet, cockpitValue,
  type ActionButtonDef,
  type ComponentName, type GridKind, type Layout, type PieceName,
} from "@/lib/cockpit/catalog";
import { choicesOf, isRefused, readSet, setNamesOf, valueRing, type WireSpec } from "@/lib/cockpit/sets";
import { valueFits } from "@/lib/cockpit/values";

/** A value's kind in words, as a sentence says what a value is. */
const KIND_WORDS: Record<string, string> = {
  days: "days", number: "a number", text: "words", date: "a day", yesno: "yes or no", list: "a list",
};
import { CARD_STATUSES, RANGE_STATUSES, TAB_PATH, publishedPath } from "@/lib/cockpit/hostState";

export const MAX_ELEMENTS = 200;
export const MAX_TABS = 8;
export const MAX_CARDS = 60;

export interface CockpitIssue {
  /** Stable, for a caller that branches; the sentence is for the reader. */
  code:
    | "not_a_spec" | "too_large" | "structure" | "unknown_component" | "refused_field"
    | "expression_in_prop" | "bad_prop" | "bad_root" | "bad_child" | "duplicate_tab"
    | "bad_state" | "condition_not_allowed" | "bad_condition";
  message: string;
  elementKey?: string;
}

export interface ReaderText { elementKey: string; prop: string; text: string }

export interface CockpitCheck {
  valid: boolean;
  issues: CockpitIssue[];
  /** Card ids the spec places, in the order it places them, each once. */
  cards: string[];
  /** Card ids whose status a condition reads, each once. */
  stateCards: string[];
  /** The text a reader will see. Empty unless the spec is valid. */
  texts: ReaderText[];
  /**
   * On a REFUSAL only: what was read from the elements whose props were sound. It is handed
   * back so the server can name, in the same refusal, what only it knows — a card the canvas
   * does not hold, a figure in a title (CT-5). It licenses nothing: `cards` and `texts` stay
   * empty, and nothing is drawn or kept from a refused spec.
   */
  seen?: { cards: string[]; stateCards: string[]; texts: ReaderText[] };
}

export interface CockpitVocabulary {
  version: number;
  components: readonly string[];
  tones: readonly string[];
  sizes: readonly string[];
  /** Arc AP-1 — the grid a resized section is laid on: its columns, and the height of one grade in px. */
  grid: { columns: number; grade: number };
  range_statuses: readonly string[];
  card_statuses: readonly string[];
  limits: { elements: number; tabs: number; cards: number };
}

export function vocabulary(): CockpitVocabulary {
  return {
    version: COCKPIT_VOCABULARY_VERSION,
    components: COMPONENT_NAMES,
    tones: TONES,
    sizes: SIZES,
    grid: { columns: GRID.columns, grade: GRADE },
    range_statuses: RANGE_STATUSES,
    card_statuses: CARD_STATUSES,
    limits: { elements: MAX_ELEMENTS, tabs: MAX_TABS, cards: MAX_CARDS },
  };
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const q = (s: unknown) => JSON.stringify(String(s));
const list = (xs: readonly string[]) => xs.join(", ");

const ELEMENT_FIELDS = new Set(["type", "props", "children", "visible"]);

/** Why each field a spec may not carry is refused, said to whoever wrote it. */
const REFUSED_FIELDS: Record<string, string> = {
  watch: "A cockpit runs nothing without a click, so \"watch\" is refused.",
  on: "A cockpit defines no action of its own; a card keeps the doors it already has.",
  repeat: "A cockpit places each card by its id; \"repeat\" is refused.",
  slots: "A cockpit holds its elements in \"children\"; \"slots\" is refused.",
};

/** The first expression key found anywhere inside a prop's value, or null. */
function expressionIn(value: unknown): string | null {
  if (Array.isArray(value)) {
    for (const v of value) { const k = expressionIn(v); if (k) return k; }
    return null;
  }
  if (!isObj(value)) return null;
  for (const [k, v] of Object.entries(value)) {
    if (k.startsWith("$")) return k;
    const inner = expressionIn(v);
    if (inner) return inner;
  }
  return null;
}

function isComponent(t: unknown): t is ComponentName {
  return typeof t === "string" && (COMPONENT_NAMES as readonly string[]).includes(t);
}

function checkProps(key: string, type: ComponentName, props: Obj, out: CockpitIssue[]): void {
  let literal = props;
  if (type === "Tabs") {
    const v = props.value;
    const bound = isObj(v) && Object.keys(v).length === 1 && v.$bindState === TAB_PATH;
    if (!bound) {
      out.push({ code: "bad_prop", elementKey: key,
        message: `The tabs ${q(key)} must carry "value": {"$bindState": "${TAB_PATH}"} and nothing else in its place.` });
      return;
    }
    literal = Object.fromEntries(Object.entries(props).filter(([k]) => k !== "value"));
    if (Object.keys(literal).length) {
      out.push({ code: "bad_prop", elementKey: key,
        message: `The tabs ${q(key)} carries ${list(Object.keys(literal).map(q))}. Tabs take "value" and nothing else.` });
    }
    return;
  }
  for (const [name, value] of Object.entries(props)) {
    const expr = expressionIn(value);
    if (expr) {
      out.push({ code: "expression_in_prop", elementKey: key,
        message: `The ${type.toLowerCase()} ${q(key)} sets ${q(name)} from an expression (${expr}). `
          + "In a cockpit a prop is written, never computed." });
    }
  }
  if (out.some(i => i.elementKey === key && i.code === "expression_in_prop")) return;
  const declared = (cockpitCatalog.data.components[type].props as z.ZodObject).strict();
  const parsed = declared.safeParse(literal);
  if (parsed.success) {
    if (type === "ObjectChart") checkChart(key, literal, out);
    return;
  }
  for (const issue of parsed.error.issues) {
    const where = issue.path.length ? q(issue.path.join(".")) : "its props";
    out.push({ code: "bad_prop", elementKey: key,
      message: `The ${type.toLowerCase()} ${q(key)} has a problem with ${where}: ${issue.message}.` });
  }
}

/** Arc AP-1 — what a chart measures and what it splits by say one thing together: an aggregate names the property it
 *  reads, a split stacks the bars — so what they measure must add up — and how many values it draws needs a split. */
function checkChart(key: string, props: Obj, out: CockpitIssue[]): void {
  const agg = typeof props.agg === "string" ? props.agg : "count";
  const refuse = (message: string) => out.push({ code: "bad_prop", elementKey: key, message });
  if (agg !== "count" && !props.path) {
    refuse(`The chart ${q(key)} measures the ${agg} of nothing. Name the property it reads in "path".`);
  }
  if (props.split && !(SPLIT_AGGS as readonly string[]).includes(agg)) {
    refuse(`The chart ${q(key)} is split by ${q(String(props.split))} and measures the ${agg}. A split stacks its bars, `
      + "so a chart split by a property measures a count or a sum.");
  }
  if (props.top != null && !props.split) {
    refuse(`The chart ${q(key)} says how many values to draw and splits by nothing. Name the property in "split".`);
  }
}

/** Arc AP-2 and AP-3 — the wiring, by name: every set, value and choice a piece names is one the cockpit holds, sets
 *  form no ring and keep one segment, a condition says what its operator needs, a set of what a chosen object links to
 *  waits on a chosen object, one name is one thing, and every source a button's parameter names is there. Whether a
 *  set compiles, and whether a source holds what a parameter takes, are the server's to say (it knows the ontology). */
function checkWiring(spec: WireSpec, sound: Map<string, { type: ComponentName; props: Obj; children: string[] }>, clean: Set<string>,
  choices: ReturnType<typeof choicesOf>, issues: CockpitIssue[]): void {
  const sets = isObj(spec.sets) ? spec.sets as Record<string, unknown> : spec.sets == null ? {} : null;
  const values = isObj(spec.values) ? spec.values as Record<string, unknown> : spec.values == null ? {} : null;
  if (sets === null) issues.push({ code: "bad_prop", message: "The spec's \"sets\" is not a map of named sets." });
  if (values === null) issues.push({ code: "bad_prop", message: "The spec's \"values\" is not a map of named values." });
  const setNames = Object.keys(sets ?? {});
  const valueNames = Object.keys(values ?? {});
  if (setNames.length > MAX_SETS) issues.push({ code: "too_large", message: `The cockpit holds ${setNames.length} sets. It holds at most ${MAX_SETS}.` });
  if (valueNames.length > MAX_VALUES) issues.push({ code: "too_large", message: `The cockpit holds ${valueNames.length} values. It holds at most ${MAX_VALUES}.` });
  const sound_ = new Set<string>();
  for (const [name, raw] of Object.entries(values ?? {})) {
    const parsed = cockpitValue.safeParse(raw);
    if (!parsed.success) {
      issues.push({ code: "bad_prop", message: `The value ${q(name)} has a problem: ${parsed.error.issues.map(i => `${i.path.join(".") || "it"} ${i.message}`).join("; ")}.` });
      continue;
    }
    const v = parsed.data;
    const by = v.from?.by ?? "author";
    // a value the author or the reader sets holds one of its own — the reader's first; a value counted or read holds none
    const set_ = by === "author" || by === "reader";
    // a list's own is one value (the list), and the choices a reader offers are its items
    const held = set_ ? (v.kind === "list" ? [...(v.from?.by === "reader" ? v.from.options ?? [] : [])]
      : [v.value, ...(v.from?.by === "reader" ? v.from.options ?? [] : [])]) : [];
    if (set_ && (v.value === undefined || v.value === null)) {
      issues.push({ code: "bad_prop", message: `The value ${q(name)} holds nothing. A value ${by === "author" ? "you set" : "the reader sets"} holds one to start from.` });
    } else if (!set_ && v.value !== undefined && v.value !== null) {
      const how = by === "count" ? "counted" : by === "sum" ? "summed from a set" : by === "query" ? "read from a query" : "read from the object chosen";
      issues.push({ code: "bad_prop", message: `The value ${q(name)} is ${how} and holds one of its own. It holds none.` });
    } else if (set_ && v.kind === "yesno" && typeof v.value !== "boolean") {
      issues.push({ code: "bad_prop", message: `The value ${q(name)} is yes or no and holds ${JSON.stringify(v.value)}.` });
    } else if (set_ && v.kind === "list" && !valueFits("list", v.value)) {
      issues.push({ code: "bad_prop", message: `The value ${q(name)} is a list and holds ${JSON.stringify(v.value)}. A list holds 1 to ${MAX_LIST} numbers or words, each once.` });
    } else if (set_ && v.kind !== "list" && Array.isArray(v.value)) {
      issues.push({ code: "bad_prop", message: `The value ${q(name)} is ${KIND_WORDS[v.kind]} and holds a list.` });
    } else if (set_ && v.kind !== "yesno" && typeof v.value === "boolean") {
      issues.push({ code: "bad_prop", message: `The value ${q(name)} is ${KIND_WORDS[v.kind]} and holds ${v.value ? "yes" : "no"}.` });
    }
    if (v.from?.by === "reader" && v.kind === "yesno" && v.from.options?.length) {
      issues.push({ code: "bad_prop", message: `The value ${q(name)} is yes or no: the reader chooses Yes or No, and it offers no other choices.` });
    }
    for (const h of held) {
      if (h === undefined || h === null) continue;
      if ((v.kind === "days" || v.kind === "number") && typeof h !== "number") {
        issues.push({ code: "bad_prop", message: `The value ${q(name)} is a ${v.kind} and holds ${JSON.stringify(h)}. A ${v.kind} holds a number.` });
      } else if (v.kind === "days" && (!Number.isInteger(h) || (h as number) < 1)) {
        issues.push({ code: "bad_prop", message: `The value ${q(name)} counts ${JSON.stringify(h)} days. Days are a whole number, one or more.` });
      } else if (v.kind === "text" && typeof h !== "string") {
        issues.push({ code: "bad_prop", message: `The value ${q(name)} is a word and holds a number.` });
      } else if (v.kind === "date" && !(typeof h === "string" && ISO_DAY.test(h))) {
        issues.push({ code: "bad_prop", message: `The value ${q(name)} is a day and holds ${JSON.stringify(h)}. A day is written 2026-10-11.` });
      }
    }
    if (v.from?.by === "reader" && v.from.options?.length) {
      const opts = v.from.options;
      // a list starts from some of the choices; any other value from one of them
      const starts = v.kind === "list" ? (Array.isArray(v.value) ? v.value : []) : v.value === undefined || v.value === null ? [] : [v.value];
      const strays = starts.filter(x => !opts.some(o => o === x));
      if (new Set(opts.map(o => JSON.stringify(o))).size !== opts.length) {
        issues.push({ code: "bad_prop", message: `The value ${q(name)} offers the same choice twice.` });
      } else if (strays.length) {
        issues.push({ code: "bad_prop", message: `The value ${q(name)} starts from ${JSON.stringify(v.kind === "list" ? strays : strays[0])}, which is not one of the choices it offers.` });
      }
    }
    if (v.from?.by === "count" || v.from?.by === "sum") {
      const verb = v.from.by === "count" ? "counts" : "sums";
      if (v.kind !== "number") issues.push({ code: "bad_prop", message: `The value ${q(name)} ${verb} a set, so it holds a number — not ${KIND_WORDS[v.kind]}.` });
      if (!setNamesOf(spec).includes(v.from.set)) issues.push({ code: "bad_prop", message: `The value ${q(name)} ${verb} the set ${q(v.from.set)}, which this cockpit does not hold.` });
    } else if (v.from?.by === "query") {
      // Arc AP-8c — a query of the cockpit's own: a card it places
      const card = v.from.card;
      if (!Object.values(spec.elements).some(el => el?.type === "Card" && el.props?.card === card)) {
        issues.push({ code: "bad_prop", message: `The value ${q(name)} reads the query ${q(card)}, which this cockpit does not place.` });
      }
      if (v.kind === "days") issues.push({ code: "bad_prop", message: `The value ${q(name)} reads a query, and a query's value is a number, not days. Make it a number.` });
    } else if (v.from?.by === "chosen") {
      if (choices.get(v.from.choice)?.kind !== "chosen") {
        issues.push({ code: "bad_prop", message: `The value ${q(name)} reads ${v.from.path} of ${q(v.from.choice)}, and no click chooses ${q(v.from.choice)}.` });
      }
      if (v.kind === "list" || v.kind === "days") {
        issues.push({ code: "bad_prop", message: `The value ${q(name)} reads one property of one object, so it is not ${KIND_WORDS[v.kind]}.` });
      }
    }
  }
  const ring = valueRing(spec);
  if (ring) issues.push({ code: "bad_prop", message: `${ring.map(q).join(" → ")} read each other in a ring: a value counted or summed from a set that reads it.` });
  for (const [name, raw] of Object.entries(sets ?? {})) {
    const parsed = cockpitSet.safeParse(raw);
    if (!parsed.success) {
      issues.push({ code: "bad_prop", message: `The set ${q(name)} has a problem: ${parsed.error.issues.map(i => `${i.path.join(".") || "it"} ${i.message}`).join("; ")}.` });
      continue;
    }
    sound_.add(name);
    const set = parsed.data;
    for (const c of set.where ?? []) {
      const said = `The set ${q(name)} keeps ${c.path} ${c.op}`;
      const lit = c.value !== undefined && c.value !== null;
      // Arc AP-8 — a value compares as its kind allows: a word for equality, a number or a day for any comparison
      const v = c.value_from && isObj(values?.[c.value_from]) ? values?.[c.value_from] as { kind?: string } : null;
      if (c.value_from && v && !(VALUE_OPS as readonly string[]).includes(c.op)) {
        issues.push({ code: "bad_prop", message: `${said} the value ${q(c.value_from)}. A value is compared with =, !=, >, >=, <, <=, counted back by in_last, or kept among by in or not_in.` });
      } else if (c.value_from && (v?.kind === "list") !== (c.op === "in" || c.op === "not_in")) {
        // a list with any other comparison, or "in" with a value that is not a list: the set's reading says it, once
      } else if (c.value_from && (v?.kind === "text" || v?.kind === "yesno") && !["=", "!="].includes(c.op)) {
        issues.push({ code: "bad_prop", message: `${said} the ${v.kind === "text" ? "word" : "yes or no"} ${q(c.value_from)}. ${v.kind === "text" ? "A word" : "Yes or no"} is compared with = or !=.` });
      } else if (c.value_from && v && c.op !== "in_last" && v.kind === "days") {
        issues.push({ code: "bad_prop", message: `${said} the days ${q(c.value_from)}. Days are counted back by in_last.` });
      }
      if ((c.op === "is_null" || c.op === "not_null") && (lit || c.values?.length || c.value_from)) {
        issues.push({ code: "bad_prop", message: `${said} with something to compare. ${c.op} compares with nothing.` });
      } else if ((c.op === "in" || c.op === "not_in") && !(c.values?.length) && !c.value_from) {
        issues.push({ code: "bad_prop", message: `${said} and lists no values.` });
      } else if (c.op === "in_last" && !c.value_from && !(typeof c.value === "number" && Number.isInteger(c.value) && c.value >= 1)) {
        issues.push({ code: "bad_prop", message: `${said} without a whole number of days, or a value of days to count by.` });
      } else if (!["is_null", "not_null", "in", "not_in", "in_last"].includes(c.op) && !lit && !c.value_from) {
        issues.push({ code: "bad_prop", message: `${said} and compares with nothing.` });
      }
    }
    if (set.linked_to && choices.get(set.linked_to.choice)?.kind !== "chosen") {
      issues.push({ code: "bad_prop", message: `The set ${q(name)} reads what ${q(set.linked_to.choice)} links to, and no click chooses ${q(set.linked_to.choice)}.` });
    }
  }
  for (const name of sound_) {
    const r = readSet(spec, name);
    // a set others start from is read once more for each: what it says is said once
    if (isRefused(r) && !issues.some(i => i.message === r.refused)) issues.push({ code: "bad_prop", message: r.refused });
  }
  // one name, one thing: a set, a value and a choice never share a name, and an object is chosen by one table
  for (const [name, c] of choices) {
    if (setNames.includes(name) || valueNames.includes(name)) {
      issues.push({ code: "bad_prop", elementKey: c.madeBy[0], message: `${q(name)} names a set or a value and a choice. One name is one thing.` });
    }
    if (c.kind !== "shown" && c.madeBy.length > 1) {
      issues.push({ code: "bad_prop", elementKey: c.madeBy[1], message: `${q(name)} is made by ${c.madeBy.map(q).join(" and ")}. An object is chosen or ticked in one piece.` });
    }
  }
  for (const name of setNames) {
    if (valueNames.includes(name)) issues.push({ code: "bad_prop", message: `${q(name)} names a set and a value. One name is one thing.` });
  }
  const kindsOf = new Map<string, Set<string>>();
  for (const [key, el] of sound) {
    for (const [prop, kind] of [["chooses", "chosen"], ["ticks", "ticked"], ["shows", "shown"]] as const) {
      const n = el.props[prop];
      if (typeof n === "string") kindsOf.set(n, (kindsOf.get(n) ?? new Set()).add(kind));
    }
    void key;
  }
  for (const [n, kinds] of kindsOf) {
    if (kinds.size > 1) issues.push({ code: "bad_prop", message: `${q(n)} is made as ${[...kinds].join(" and ")}. A choice is one kind of thing.` });
  }
  const isSet = (n: unknown) => typeof n === "string" && setNames.includes(n);
  for (const [key, el] of sound) {
    if (!clean.has(key)) continue;
    const p = el.props;
    const what = `The ${KIND[el.type] ?? el.type.toLowerCase()} ${q(key)}`;
    if (SET_READERS.includes(el.type as PieceName)) {
      const named = [p.entity ? "an entity" : "", p.set ? "a set" : ""].filter(Boolean);
      if (named.length !== 1) {
        issues.push({ code: "bad_prop", elementKey: key, message: `${what} names ${named.length ? named.join(" and ") : "neither an entity nor a set"}. It reads one: an entity, or a set.` });
      } else if (p.set && !isSet(p.set)) {
        issues.push({ code: "bad_prop", elementKey: key, message: `${what} reads the set ${q(String(p.set))}, which this cockpit does not hold.` });
      } else if (p.set && p.segment) {
        issues.push({ code: "bad_prop", elementKey: key, message: `${what} reads a set and also names a segment. A set keeps its own segment.` });
      }
    }
    // Arc AP-2 — a filter column counting within a set: one the cockpit holds, of the entity it filters
    if (el.type === "ObjectFilters" && p.set != null) {
      const within = isSet(p.set) ? readSet(spec, String(p.set)) : null;
      if (!within) {
        issues.push({ code: "bad_prop", elementKey: key, message: `The filter column ${q(key)} counts within the set ${q(String(p.set))}, which this cockpit does not hold.` });
      } else if (!isRefused(within) && within.entity.toLowerCase() !== String(p.entity ?? "").toLowerCase()) {
        issues.push({ code: "bad_prop", elementKey: key, message: `The filter column ${q(key)} filters ${String(p.entity)} and counts within ${q(String(p.set))}, a set of ${within.entity}. It counts within a set of what it filters.` });
      }
    }
    if (el.type === "ObjectFigure" && p.of != null && !isSet(p.of)) {
      issues.push({ code: "bad_prop", elementKey: key, message: `${what} is said beside the set ${q(String(p.of))}, which this cockpit does not hold.` });
    }
    if (el.type === "ObjectFigure" && p.shows != null && !p.set) {
      issues.push({ code: "bad_prop", elementKey: key, message: `${what} shows its set in a table and reads no set. A figure that switches a list reads a set.` });
    }
    if (SWITCHED.includes(el.type as PieceName) && p.set_from != null) {
      if (choices.get(String(p.set_from))?.kind !== "shown") {
        issues.push({ code: "bad_prop", elementKey: key, message: `${what} lists the set a figure shows in ${q(String(p.set_from))}, and no figure shows a set there.` });
      } else if (!p.set) {
        issues.push({ code: "bad_prop", elementKey: key, message: `${what} lists the set a figure shows, and names no set to list before one is shown.` });
      }
    }
    if (el.type === "ActionButtons") {
      ((p.buttons as ActionButtonDef[] | undefined) ?? []).forEach((b, i) => {
        const which = `The button ${i + 1} of ${q(key)} (${b.label || b.action})`;
        for (const [param, src] of Object.entries(b.params ?? {})) {
          if ("from" in src) {
            const c = choices.get(src.from);
            if (!c || c.kind === "shown") {
              issues.push({ code: "bad_prop", elementKey: key, message: `${which} takes ${q(param)} from ${q(src.from)}, which is not an object a click chooses or ticks collect.` });
            }
          } else if ("set" in src && !isSet(src.set)) {
            issues.push({ code: "bad_prop", elementKey: key, message: `${which} takes ${q(param)} from the set ${q(src.set)}, which this cockpit does not hold.` });
          }
        }
        for (const n of b.after?.read ?? []) {
          if (!isSet(n)) issues.push({ code: "bad_prop", elementKey: key, message: `${which} reads the set ${q(n)} again after it runs, and this cockpit does not hold it.` });
        }
      });
    }
  }
}

/** Arc AP-4 — a structure of pieces: a section holds pieces on its own, or is laid out in columns, rows or tabs of
 *  sections of its own — never both; a section side by side says its width; a tab is called by its section's title;
 *  only a section split into sections goes untitled; and sections sit at most `MAX_DEPTH` deep. */
function checkStructure(sound: Map<string, { type: ComponentName; props: Obj; children: string[] }>, clean: Set<string>,
  issues: CockpitIssue[]): void {
  const parentOf = new Map<string, string>();
  for (const [key, el] of sound) for (const c of el.children) parentOf.set(c, key);
  const depth = (key: string): number => {
    let n = 0;
    for (let at = parentOf.get(key), guard = 0; at && guard < 50; at = parentOf.get(at), guard++) if (sound.get(at)?.type === "Section") n++;
    return n;
  };
  for (const [key, el] of sound) {
    if (el.type !== "Section" || !clean.has(key)) continue;
    const p = el.props;
    const layout = p.layout as Layout | null | undefined;
    const kids = el.children.filter(c => sound.has(c));
    const sections = kids.filter(c => sound.get(c)!.type === "Section");
    const pieces = kids.filter(c => sound.get(c)!.type !== "Section");
    const what = `The section ${q(key)}`;
    if (layout) {
      if (p.grid != null || p.columns != null) {
        issues.push({ code: "bad_prop", elementKey: key, message: `${what} is laid out in ${layout} and also says ${p.grid != null ? "a grid" : "columns of its own"}. A section split into sections says neither: each section it holds places its own pieces.` });
      }
      if (!kids.length) {
        issues.push({ code: "bad_child", elementKey: key, message: `${what} is laid out in ${layout} and holds nothing. Split it into sections, or take its layout off.` });
      } else if (pieces.length) {
        issues.push({ code: "bad_child", elementKey: key, message: `${what} is laid out in ${layout} and holds ${list(pieces.map(q))}. A section split into sections holds sections only.` });
      }
      for (const c of sections) {
        const child = sound.get(c)!;
        if (layout === "columns" && typeof child.props.w !== "number") {
          issues.push({ code: "bad_prop", elementKey: c, message: `The section ${q(c)} sits in columns in ${q(key)} and says no width. Each section side by side says its width, 1 to ${GRID.columns} columns.` });
        }
        if (layout === "tabs" && !child.props.title) {
          issues.push({ code: "bad_prop", elementKey: c, message: `The section ${q(c)} is a tab of ${q(key)} and has no title. A tab is called by its section's title.` });
        }
      }
    } else {
      if (sections.length) {
        issues.push({ code: "bad_child", elementKey: key, message: `${what} holds ${list(sections.map(q))} and is not laid out. A section holds pieces, or is laid out in columns, rows or tabs of sections.` });
      }
      if (!p.title) {
        issues.push({ code: "bad_prop", elementKey: key, message: `${what} has no title. A section that holds pieces says what it holds; only one split into sections goes without.` });
      }
    }
    const parent = parentOf.get(key);
    const inColumns = !!parent && sound.get(parent)?.type === "Section" && sound.get(parent)!.props.layout === "columns";
    if (p.w != null && !inColumns) {
      issues.push({ code: "bad_prop", elementKey: key, message: `${what} says a width of ${String(p.w)} columns and does not sit in columns. Only a section side by side with others says its width.` });
    }
    const d = depth(key);
    if (d >= MAX_DEPTH) {
      issues.push({ code: "too_large", elementKey: key, message: `${what} sits ${d + 1} sections deep. Sections sit at most ${MAX_DEPTH} deep, so a reader keeps the page's shape.` });
    }
  }
}

/** A piece as a sentence names it. */
/** "A figure", "An objects table" — a kind's word with its article, capitalised. */
const an = (word: string) => `${/^[aeiou]/i.test(word) ? "An" : "A"} ${word}`;
const KIND: Partial<Record<string, string>> = {
  ObjectTable: "objects table", ObjectFigure: "figure", ObjectChart: "chart", ObjectList: "object list", ObjectMap: "map",
  ObjectTimeline: "timeline", ChooseOne: "choose-one", ObjectSearch: "search", Drawer: "drawer",
};

function checkCondition(key: string, cond: unknown, out: CockpitIssue[], stateCards: Set<string>): void {
  const refuse = (message: string) => out.push({ code: "bad_condition", elementKey: key, message });
  if (Array.isArray(cond)) {
    if (!cond.length) refuse(`The condition on ${q(key)} is an empty list.`);
    cond.forEach(c => checkCondition(key, c, out, stateCards));
    return;
  }
  if (!isObj(cond)) {
    refuse(`The condition on ${q(key)} is ${JSON.stringify(cond)}. A condition compares a status the host publishes.`);
    return;
  }
  for (const joiner of ["$and", "$or"] as const) {
    if (joiner in cond) {
      const parts = cond[joiner];
      if (Object.keys(cond).length !== 1 || !Array.isArray(parts) || !parts.length) {
        refuse(`The condition on ${q(key)} uses "${joiner}", which takes a list of conditions and nothing beside it.`);
        return;
      }
      parts.forEach(c => checkCondition(key, c, out, stateCards));
      return;
    }
  }
  if (!("$state" in cond)) {
    refuse(`The condition on ${q(key)} reads ${list(Object.keys(cond).map(q)) || "nothing"}. `
      + "A condition reads \"$state\" and nothing else.");
    return;
  }
  const path = cond.$state;
  const published = typeof path === "string" ? publishedPath(path) : null;
  if (!published) {
    refuse(`The condition on ${q(key)} reads ${q(path)}. A condition may read "/range/status" or `
      + "\"/cards/<card id>/status\" and nothing else.");
    return;
  }
  const ops = Object.keys(cond).filter(k => k !== "$state" && k !== "not");
  if (ops.length !== 1 || (ops[0] !== "eq" && ops[0] !== "neq")) {
    refuse(`The condition on ${q(key)} compares ${q(path)} with ${list(ops.map(q)) || "nothing"}. `
      + "A status is compared with \"eq\" or \"neq\", once.");
    return;
  }
  if ("not" in cond && cond.not !== true) {
    refuse(`The condition on ${q(key)} carries "not": ${JSON.stringify(cond.not)}. It is true or it is absent.`);
    return;
  }
  const value = cond[ops[0]];
  if (typeof value !== "string" || !published.values.includes(value)) {
    refuse(`The condition on ${q(key)} compares ${q(path)} with ${JSON.stringify(value)}. `
      + `It may be compared with: ${list(published.values)}.`);
    return;
  }
  if (published.kind === "card") stateCards.add(published.card);
}

const REFUSED: CockpitCheck = { valid: false, issues: [], cards: [], stateCards: [], texts: [] };

export function checkCockpitSpec(spec: unknown): CockpitCheck {
  const issues: CockpitIssue[] = [];
  const cards: string[] = [];
  const stateCards = new Set<string>();
  const texts: ReaderText[] = [];
  const done = (): CockpitCheck => (
    { ...REFUSED, issues, seen: { cards, stateCards: [...stateCards], texts } });

  if (!isObj(spec) || typeof spec.root !== "string" || !isObj(spec.elements)) {
    issues.push({ code: "not_a_spec",
      message: "A cockpit spec is an object with a \"root\" and a map of \"elements\"." });
    return done();
  }
  const extra = Object.keys(spec).filter(k => !["root", "elements", "state", "sets", "values"].includes(k));
  if (extra.length) {
    issues.push({ code: "not_a_spec",
      message: `The spec carries ${list(extra.map(q))}. It holds "root", "elements", "state", and the "sets" and "values" its pieces read.` });
  }
  const elements = spec.elements as Record<string, unknown>;
  const keys = Object.keys(elements);
  if (keys.length > MAX_ELEMENTS) {
    issues.push({ code: "too_large",
      message: `The spec holds ${keys.length} elements. A cockpit holds at most ${MAX_ELEMENTS}.` });
    return done();
  }

  // A refusal names EVERY kind of fault it can, not the first kind it meets (CT-5): the writer
  // is a model, and a round spent learning of one fault at a time is a model call. So a phase
  // does not stop the next. What lets that be safe is `sound`: the elements whose type, props
  // and children can be read. A later phase reads those and no others, and an element that is
  // not sound has already been refused by name.
  type El = { type: ComponentName; props: Obj; children: string[]; visible?: unknown };
  const sound = new Map<string, El>();
  /** The sound elements whose props passed. Only their names, ids and titles are read: a prop
   *  that was refused is not told again as a namesake, or as a card the canvas does not hold. */
  const clean = new Set<string>();

  // The shape of each element, before anything reads it.
  for (const key of keys) {
    const el = elements[key];
    if (!isObj(el)) {
      issues.push({ code: "structure", elementKey: key, message: `The element ${q(key)} is not an object.` });
      continue;
    }
    for (const field of Object.keys(el)) {
      if (ELEMENT_FIELDS.has(field)) continue;
      issues.push({ code: "refused_field", elementKey: key,
        message: `The element ${q(key)} carries ${q(field)}. `
          + (REFUSED_FIELDS[field] ?? "An element holds \"type\", \"props\", \"children\" and \"visible\".") });
    }
    if (!isComponent(el.type)) {
      issues.push({ code: "unknown_component", elementKey: key,
        message: `The element ${q(key)} is a ${q(el.type)}. A cockpit is made of: ${list(COMPONENT_NAMES)}.` });
      continue;
    }
    const hasProps = isObj(el.props);
    const before = issues.length;
    if (!hasProps) {
      issues.push({ code: "bad_prop", elementKey: key, message: `The element ${q(key)} has no "props".` });
    } else {
      checkProps(key, el.type, el.props as Obj, issues);
    }
    if (issues.length === before) clean.add(key);
    const hasChildren = Array.isArray(el.children) && el.children.every(c => typeof c === "string");
    if (!hasChildren) {
      issues.push({ code: "structure", elementKey: key,
        message: `The element ${q(key)} needs "children": a list of element keys, empty when it holds none.` });
    }
    if (hasProps && hasChildren) sound.set(key, el as unknown as El);
  }

  // Every key an element names must be one the spec defines.
  if (!(spec.root in elements)) {
    issues.push({ code: "bad_root",
      message: `The root is ${q(spec.root)}, which the spec does not define.` });
  }
  for (const [key, el] of sound) {
    const missing = el.children.filter(c => !(c in elements));
    if (missing.length) {
      issues.push({ code: "bad_child", elementKey: key,
        message: `The ${el.type.toLowerCase()} ${q(key)} holds ${list(missing.map(q))}, which the spec does not define.` });
    }
  }

  const root = sound.get(spec.root);
  if (root && root.type !== "Cockpit") {
    issues.push({ code: "bad_root", elementKey: spec.root,
      message: `The root ${q(spec.root)} is a ${root.type}. The root of a cockpit is a Cockpit.` });
  }

  const tabNames = new Map<string, string>();
  let tabCount = 0;
  let cardCount = 0;

  for (const [key, el] of sound) {
    // Only the children that can be read are judged for their kind. One the spec does not
    // define, or one that is not sound, has been refused above in its own words.
    const held = el.children.filter(c => sound.has(c));
    const kinds = held.map(c => (sound.get(c) as El).type);
    const stray = held.filter((_, i) => !MAY_HOLD[el.type].includes(kinds[i]));
    if (stray.length) {
      const may = MAY_HOLD[el.type];
      issues.push({ code: "bad_child", elementKey: key,
        message: `The ${el.type.toLowerCase()} ${q(key)} holds ${list(stray.map(q))}. `
          + (may.length ? `A ${el.type} holds: ${list(may)}.` : `A ${el.type} holds nothing.`) });
    } else if (el.type === "Cockpit" && new Set(kinds.filter(k => k !== "ObjectFilters" && k !== "Drawer")).size > 1) {
      issues.push({ code: "bad_child", elementKey: key,
        message: `The cockpit ${q(key)} holds tabs and sections side by side. It holds one Tabs, or sections, not both.` });
    } else if (el.type === "Cockpit" && kinds.filter(k => k === "Tabs").length > 1) {
      issues.push({ code: "bad_child", elementKey: key,
        message: `The cockpit ${q(key)} holds more than one Tabs. It holds one.` });
    } else if (el.type === "Cockpit" && kinds.filter(k => k === "ObjectFilters").length > 1) {
      issues.push({ code: "bad_child", elementKey: key,
        message: `The cockpit ${q(key)} holds more than one filter column. It holds one, as its first child.` });
    } else if (el.type === "Cockpit" && kinds.includes("ObjectFilters") && kinds[0] !== "ObjectFilters") {
      issues.push({ code: "bad_child", elementKey: key,
        message: `The cockpit ${q(key)} holds its filter column after its tabs or sections. A filter column is the cockpit's first child, drawn beside the rest.` });
    } else if (el.type === "Cockpit" && kinds.length > 0 && kinds.every(k => k === "ObjectFilters" || k === "Drawer")) {
      issues.push({ code: "bad_child", elementKey: key,
        message: kinds.includes("ObjectFilters")
          ? `The cockpit ${q(key)} holds a filter column and nothing it narrows. It holds one Tabs, or sections, beside it.`
          : `The cockpit ${q(key)} holds only drawers. It holds one Tabs, or sections, for a drawer to open beside.` });
    } else if (MAY_HOLD[el.type].length && !PLACED.includes(el.type) && el.type !== "Section" && el.type !== "Drawer" && !el.children.length) {
      // Arc AP-4 — a section may hold nothing yet: the builder offers it a piece, and a reader is drawn none
      issues.push({ code: "bad_child", elementKey: key,
        message: `The ${el.type.toLowerCase()} ${q(key)} holds nothing. An empty ${el.type} is refused.` });
    }

    if (key !== spec.root && el.type === "Cockpit") {
      issues.push({ code: "bad_root", elementKey: key,
        message: `The element ${q(key)} is a second Cockpit. A spec holds one, at its root.` });
    }
    // A name, an id or a title is read only from props that passed. One that was refused is
    // not read again here, where two tabs with no name would be called namesakes.
    if (el.type === "Tab") {
      tabCount += 1;
      if (clean.has(key)) {
        const name = el.props.name as string;
        const first = tabNames.get(name);
        if (first) {
          issues.push({ code: "duplicate_tab", elementKey: key,
            message: `The tabs ${q(first)} and ${q(key)} are both named ${q(name)}. A tab's name is its own.` });
        } else {
          tabNames.set(name, key);
        }
      }
    }
    if (el.type === "Card") {
      cardCount += 1;
      const id = el.props.card as string;
      if (clean.has(key) && !cards.includes(id)) cards.push(id);
    }
    if (el.visible !== undefined) {
      if (!MAY_BE_CONDITIONAL.includes(el.type)) {
        issues.push({ code: "condition_not_allowed", elementKey: key,
          message: `The ${el.type.toLowerCase()} ${q(key)} is shown by a condition. `
            + `Only these may be: ${list(MAY_BE_CONDITIONAL)}.` });
      } else {
        checkCondition(key, el.visible, issues, stateCards);
      }
    }
    for (const prop of clean.has(key) ? READER_TEXT[el.type] ?? [] : []) {
      texts.push({ elementKey: key, prop, text: el.props[prop] as string });
    }
  }

  // Arc OC-4 — an object detail follows an objects table in the same cockpit, by its key — or, since Arc AP-2, the
  // object a click chooses, by the choice's name: in a table, or since Arc AP-4 a list, a map, a timeline or a choose-one.
  const wire = spec as unknown as WireSpec;
  const choices = choicesOf(wire);
  for (const [key, el] of sound) {
    if (el.type !== "ObjectDetail" || !clean.has(key)) continue;
    const follows = el.props.follows as string;
    if (!CHOOSERS.includes(sound.get(follows)?.type as PieceName) && choices.get(follows)?.kind !== "chosen") {
      issues.push({ code: "bad_prop", elementKey: key,
        message: `The object detail ${q(key)} follows ${q(follows)}, which is neither a piece a click chooses in nor an object a click chooses.` });
    }
  }

  // Arc AP-4 — a drawer opens on an object a click chooses, by the choice's name
  for (const [key, el] of sound) {
    if (el.type !== "Drawer" || !clean.has(key)) continue;
    const on = String(el.props.opens_on);
    if (choices.get(on)?.kind !== "chosen") {
      issues.push({ code: "bad_prop", elementKey: key,
        message: `The drawer ${q(key)} opens on ${q(on)}, and no click chooses ${q(on)}. A drawer opens on an object a table, a list, a map, a timeline or a choose-one names.` });
    }
  }

  checkWiring(wire, sound, clean, choices, issues);
  checkStructure(sound, clean, issues);

  // Arc AP-1 — a section on the grid places each element by w columns and h rows, within what its kind may take; a
  // section that is not says sizes by name, and a w or an h there would be read by nothing.
  for (const [key, el] of sound) {
    // a section split into sections places none of its own: its sections' widths are the structure's rules' to judge
    if (el.type !== "Section" || !clean.has(key) || el.props.layout != null) continue;
    const gridded = el.props.grid === GRID.columns;
    if (gridded && el.props.columns != null) {
      issues.push({ code: "bad_prop", elementKey: key,
        message: `The section ${q(key)} is on the grid and also says ${el.props.columns} columns. `
          + `On the grid a section has ${GRID.columns} columns; it says none of its own.` });
    }
    for (const child of el.children) {
      const c = sound.get(child);
      if (!c || !clean.has(child)) continue;
      const w = c.props.w, h = c.props.h;
      const said = [w != null ? `w ${String(w)}` : "", h != null ? `h ${String(h)}` : ""].filter(Boolean).join(" and ");
      if (!gridded) {
        if (said) {
          issues.push({ code: "bad_prop", elementKey: child,
            message: `The ${KIND[c.type] ?? c.type.toLowerCase()} ${q(child)} says ${said}, and its section ${q(key)} is not on the grid. `
              + `Columns and rows are said only in a section with "grid": ${GRID.columns}; elsewhere a size is said by name.` });
        }
        continue;
      }
      const lim = LIMITS[c.type as GridKind];
      if (!lim) continue;
      if (typeof w !== "number" || typeof h !== "number") {
        issues.push({ code: "bad_prop", elementKey: child,
          message: `The ${KIND[c.type] ?? c.type.toLowerCase()} ${q(child)} is on the grid of section ${q(key)} and does not say its `
            + `${typeof w !== "number" && typeof h !== "number" ? "w and h" : typeof w !== "number" ? "w" : "h"}. `
            + "On the grid each element says how many columns (w) and rows (h) it takes." });
        continue;
      }
      if (w < lim.w[0] || w > lim.w[1] || h < lim.h[0] || h > lim.h[1]) {
        issues.push({ code: "bad_prop", elementKey: child,
          message: `The ${KIND[c.type] ?? c.type.toLowerCase()} ${q(child)} takes ${w} × ${h}. ${an(KIND[c.type] ?? c.type)} takes ${lim.w[0]} to ${lim.w[1]} `
            + `columns and ${lim.h[0]} to ${lim.h[1]} rows, so it is never too small to read or too large for what it holds.` });
      }
    }
  }

  if (tabCount > MAX_TABS) {
    issues.push({ code: "too_large", message: `The spec holds ${tabCount} tabs. A cockpit holds at most ${MAX_TABS}.` });
  }
  if (cardCount > MAX_CARDS) {
    issues.push({ code: "too_large", message: `The spec places ${cardCount} cards. A cockpit places at most ${MAX_CARDS}.` });
  }

  if (spec.state !== undefined) {
    const state = spec.state;
    const seeded = isObj(state) ? Object.keys(state) : null;
    if (!seeded || seeded.some(k => k !== "tab")) {
      issues.push({ code: "bad_state",
        message: `The spec seeds ${seeded ? list(seeded.map(q)) : "a state that is not an object"}. `
          + "A spec may seed \"tab\" and nothing else; the range and every card's status are the host's to say." });
    } else if (seeded.length && (typeof (state as Obj).tab !== "string" || !tabNames.has((state as Obj).tab as string))) {
      issues.push({ code: "bad_state",
        message: `The spec opens on the tab ${JSON.stringify((state as Obj).tab)}, which it does not hold. `
          + (tabNames.size ? `Its tabs are: ${list([...tabNames.keys()])}.` : "It holds no tabs.") });
    }
  }

  if (issues.length) return done();

  // The library's own checks, last, as a backstop. Everything above speaks in this file's
  // sentences; what is left for the library is what it alone looks for — an element nothing
  // holds, which would draw harmlessly and is refused all the same, because a kept spec holds
  // only what it shows — and any rule of its own that these rules have not caught up with.
  const structure = validateSpec(spec as unknown as Spec, { checkOrphans: true });
  for (const i of structure.issues) {
    issues.push({ code: "structure", elementKey: i.elementKey, message: `${i.message} (${i.code})` });
  }
  const parsed = cockpitCatalog.validate(spec);
  if (!parsed.success) {
    for (const i of parsed.error?.issues ?? []) {
      issues.push({ code: "structure", message: `The catalog refused ${q(i.path.join("."))}: ${i.message}.` });
    }
  }
  if (issues.length) return done();
  return { valid: true, issues: [], cards, stateCards: [...stateCards], texts };
}

/** The tab a spec opens on: the one it seeds, else the first its Tabs holds, else none. */
export function openingTab(spec: unknown): string | null {
  if (!isObj(spec) || !isObj(spec.elements)) return null;
  const seeded = isObj(spec.state) ? spec.state.tab : undefined;
  if (typeof seeded === "string") return seeded;
  const elements = spec.elements;
  const tabs = Object.values(elements).find(el => isObj(el) && el.type === "Tabs");
  const first = isObj(tabs) && Array.isArray(tabs.children) ? elements[String(tabs.children[0])] : null;
  return isObj(first) && isObj(first.props) && typeof first.props.name === "string" ? first.props.name : null;
}
