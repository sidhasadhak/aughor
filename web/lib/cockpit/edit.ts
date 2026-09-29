/**
 * Hand edits to a cockpit's spec (Arc CT, CT-8; ROADMAP §3.50).
 *
 * A person arranges their cockpit by hand: moves a card, takes one off, renames a section or a
 * tab, starts a new section or a new tab. Each edit here is a pure function from a spec to a NEW
 * spec — the one it was given is never touched — and what comes out is kept by the server as the
 * next version, through the same rules as any other (`rules.ts`, run there by the validator).
 *
 * The rules refuse an empty section, tab or row of tabs. So taking the last card out of a section
 * takes the section too, and so on upward: the cockpit that is left is always one the rules can
 * accept, except the cockpit with nothing left in it — which the rules refuse, in their own words,
 * and a person retires instead.
 *
 * No model, no figure. A title a person types is theirs; the server keeps it as theirs.
 */
import { MAX_LABEL, MAX_TITLE } from "@/lib/cockpit/catalog";

export interface Element {
  type: string;
  props: Record<string, unknown>;
  children: string[];
  visible?: unknown;
}

export interface CockpitSpec {
  root: string;
  state?: Record<string, unknown>;
  elements: Record<string, Element>;
}

export interface SectionRef { key: string; title: string; tabKey: string | null; tabLabel: string | null }
export interface TabRef { key: string; name: string; label: string }

function copy(spec: unknown): CockpitSpec {
  return JSON.parse(JSON.stringify(spec)) as CockpitSpec;
}

function parentOf(s: CockpitSpec, key: string): string | null {
  for (const [k, el] of Object.entries(s.elements)) {
    if (el.children?.includes(key)) return k;
  }
  return null;
}

function tabsElement(s: CockpitSpec): string | null {
  const root = s.elements[s.root];
  return (root?.children ?? []).find(k => s.elements[k]?.type === "Tabs") ?? null;
}

/** A key no element has, made from `base`. */
function freshKey(s: CockpitSpec, base: string): string {
  const stem = base.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "el";
  let key = stem;
  for (let n = 2; key in s.elements; n++) key = `${stem}-${n}`;
  return key;
}

/** The sections a card may be moved to, in the order they are drawn. */
export function sectionsOf(spec: unknown): SectionRef[] {
  const s = spec as CockpitSpec;
  const out: SectionRef[] = [];
  const walk = (key: string, tab: TabRef | null) => {
    const el = s.elements[key];
    if (!el) return;
    if (el.type === "Section") {
      out.push({ key, title: String(el.props.title ?? ""), tabKey: tab?.key ?? null, tabLabel: tab?.label ?? null });
      return;
    }
    for (const child of el.children ?? []) {
      const c = s.elements[child];
      walk(child, c?.type === "Tab" ? { key: child, name: String(c.props.name), label: String(c.props.label) } : tab);
    }
  };
  walk(s.root, null);
  return out;
}

export function tabsOf(spec: unknown): TabRef[] {
  const s = spec as CockpitSpec;
  const tabs = tabsElement(s);
  return (tabs ? s.elements[tabs].children : []).map(k => ({
    key: k, name: String(s.elements[k].props.name), label: String(s.elements[k].props.label),
  }));
}

/** The card ids the spec places, each once, in draw order. */
export function cardsPlaced(spec: unknown): string[] {
  const s = spec as CockpitSpec;
  const seen: string[] = [];
  for (const sec of sectionsOf(s)) {
    for (const k of s.elements[sec.key].children) {
      const id = String(s.elements[k]?.props.card ?? "");
      if (s.elements[k]?.type === "Card" && id && !seen.includes(id)) seen.push(id);
    }
  }
  return seen;
}

/** The tab the spec opens on, kept to one that still exists: an edit that takes a tab away
 *  must not leave the cockpit opening on nothing. */
function settle(s: CockpitSpec): CockpitSpec {
  const names = tabsOf(s).map(t => t.name);
  if (s.state && "tab" in s.state && names.length && !names.includes(String(s.state.tab))) {
    s.state = { ...s.state, tab: names[0] };
  }
  return s;
}

/** Take `key` out of its parent; a parent left holding nothing goes too, up to the root. */
function detach(s: CockpitSpec, key: string, andDelete: boolean): void {
  const parent = parentOf(s, key);
  if (parent) s.elements[parent].children = s.elements[parent].children.filter(k => k !== key);
  if (andDelete) delete s.elements[key];
  if (parent && parent !== s.root && s.elements[parent].type !== "Card" && s.elements[parent].children.length === 0) {
    detach(s, parent, true);
  }
}

/** Take an element — a card, a section — off the cockpit. */
export function takeOff(spec: unknown, key: string): CockpitSpec {
  const s = copy(spec);
  if (key in s.elements && key !== s.root) detach(s, key, true);
  return settle(s);
}

/** Take a card off the cockpit wherever it is placed. The card itself is not touched. */
export function takeOffCard(spec: unknown, cardId: string): CockpitSpec {
  let s = copy(spec);
  for (const [k, el] of Object.entries(s.elements)) {
    if (el.type === "Card" && el.props.card === cardId) s = takeOff(s, k);
  }
  return s;
}

/** Move an element one place earlier (-1) or later (+1) among its siblings. */
export function moveWithin(spec: unknown, key: string, delta: -1 | 1): CockpitSpec {
  const s = copy(spec);
  const parent = parentOf(s, key);
  if (!parent) return s;
  const kids = s.elements[parent].children;
  const i = kids.indexOf(key);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= kids.length) return s;
  [kids[i], kids[j]] = [kids[j], kids[i]];
  return s;
}

/** Move a card to the end of another section. */
export function moveCardTo(spec: unknown, key: string, sectionKey: string): CockpitSpec {
  const s = copy(spec);
  if (!(key in s.elements) || s.elements[sectionKey]?.type !== "Section" || parentOf(s, key) === sectionKey) return s;
  detach(s, key, false);
  if (!(sectionKey in s.elements)) return copy(spec);         // the section went with the card: nothing moved
  s.elements[sectionKey].children.push(key);
  return settle(s);
}

/** Start a new section, after the one the card is in, and move the card to it. */
export function moveCardToNewSection(spec: unknown, key: string, title: string): CockpitSpec {
  const s = copy(spec);
  const from = parentOf(s, key);
  const holder = from ? parentOf(s, from) : null;
  const name = title.trim().slice(0, MAX_TITLE);
  if (!from || !holder || !name) return s;
  const section = freshKey(s, `sec-${name}`);
  s.elements[section] = { type: "Section", props: { title: name }, children: [] };
  const siblings = s.elements[holder].children;
  siblings.splice(siblings.indexOf(from) + 1, 0, section);
  detach(s, key, false);
  s.elements[section].children.push(key);
  return settle(s);
}

/** Place a card the person has in a section — the first, when none is named. */
export function placeCard(spec: unknown, cardId: string, sectionKey?: string): CockpitSpec {
  const s = copy(spec);
  const target = sectionKey ?? sectionsOf(s)[0]?.key;
  if (!target || s.elements[target]?.type !== "Section") return s;
  const key = freshKey(s, `card-${cardId}`);
  s.elements[key] = { type: "Card", props: { card: cardId }, children: [] };
  s.elements[target].children.push(key);
  return s;
}

/** Rename the cockpit, a section or a tab. An empty name is no name: nothing changes. */
export function rename(spec: unknown, key: string, text: string): CockpitSpec {
  const s = copy(spec);
  const el = s.elements[key];
  const name = text.trim();
  if (!el || !name) return s;
  if (el.type === "Tab") el.props.label = name.slice(0, MAX_LABEL);
  else if (el.type === "Section" || el.type === "Cockpit") el.props.title = name.slice(0, MAX_TITLE);
  return s;
}

/** Move a section to another tab. */
export function moveSectionTo(spec: unknown, sectionKey: string, tabKey: string): CockpitSpec {
  const s = copy(spec);
  if (s.elements[sectionKey]?.type !== "Section" || s.elements[tabKey]?.type !== "Tab" || parentOf(s, sectionKey) === tabKey) return s;
  detach(s, sectionKey, false);
  if (!(tabKey in s.elements)) return copy(spec);
  s.elements[tabKey].children.push(sectionKey);
  return settle(s);
}

/** Start a new tab and move a section to it. A cockpit with no tabs gets them: what it held
 *  becomes the first tab, "Overview", and the new tab follows it. */
export function moveSectionToNewTab(spec: unknown, sectionKey: string, label: string): CockpitSpec {
  const s = copy(spec);
  const name = label.trim().slice(0, MAX_LABEL);
  if (s.elements[sectionKey]?.type !== "Section" || !name) return s;
  let tabs = tabsElement(s);
  if (!tabs) {
    const root = s.elements[s.root];
    const first = freshKey(s, "tab-overview");
    s.elements[first] = { type: "Tab", props: { name: "overview", label: "Overview" }, children: [...root.children] };
    tabs = freshKey(s, "tabs");
    s.elements[tabs] = { type: "Tabs", props: { value: { $bindState: "/tab" } }, children: [first] };
    root.children = [tabs];
    s.state = { ...(s.state ?? {}), tab: "overview" };
  }
  const names = new Set(tabsOf(s).map(t => t.name));
  let tabName = name.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "tab";
  for (let n = 2; names.has(tabName); n++) tabName = `${tabName.replace(/-\d+$/, "")}-${n}`;
  const tab = freshKey(s, `tab-${tabName}`);
  s.elements[tab] = { type: "Tab", props: { name: tabName, label: name }, children: [] };
  s.elements[tabs].children.push(tab);
  detach(s, sectionKey, false);
  s.elements[tab].children.push(sectionKey);
  return settle(s);
}
