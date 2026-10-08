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
  COCKPIT_VOCABULARY_VERSION, COMPONENT_NAMES, MAY_BE_CONDITIONAL, MAY_HOLD, PLACED, READER_TEXT, SIZES, TONES,
  cockpitCatalog, type ComponentName,
} from "@/lib/cockpit/catalog";
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
  if (parsed.success) return;
  for (const issue of parsed.error.issues) {
    const where = issue.path.length ? q(issue.path.join(".")) : "its props";
    out.push({ code: "bad_prop", elementKey: key,
      message: `The ${type.toLowerCase()} ${q(key)} has a problem with ${where}: ${issue.message}.` });
  }
}

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
  const extra = Object.keys(spec).filter(k => !["root", "elements", "state"].includes(k));
  if (extra.length) {
    issues.push({ code: "not_a_spec",
      message: `The spec carries ${list(extra.map(q))}. It holds "root", "elements" and "state".` });
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
    } else if (el.type === "Cockpit" && new Set(kinds).size > 1) {
      issues.push({ code: "bad_child", elementKey: key,
        message: `The cockpit ${q(key)} holds tabs and sections side by side. It holds one Tabs, or sections, not both.` });
    } else if (el.type === "Cockpit" && kinds.filter(k => k === "Tabs").length > 1) {
      issues.push({ code: "bad_child", elementKey: key,
        message: `The cockpit ${q(key)} holds more than one Tabs. It holds one.` });
    } else if (!PLACED.includes(el.type) && !el.children.length) {
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
