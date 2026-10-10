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
import {
  FILTER_WIDTH, GRID, LIMITS, MAX_CAPTION, MAX_LABEL, MAX_NOTE, MAX_TITLE, PLACED, SPAN, type GridKind, type Size,
} from "@/lib/cockpit/catalog";

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

/** An element's room on a section's grid: columns across, rows down (Arc AP-1). */
export interface Box { w: number; h: number }

/** The columns a section draws when it says none (`ComposedCockpit`'s most). */
const AUTO_COLUMNS = 4;
/** The size an element draws at when it says none, by kind — as `ComposedCockpit` draws it. */
const DEFAULT_SIZE: Record<GridKind, Size> = {
  Card: "small", Note: "small", Image: "small", ProcessBoard: "full", ObjectTable: "wide", ObjectDetail: "small",
  ObjectFigure: "small", ObjectChart: "full",
};
/** The rows a kind takes on the grid when nothing measured it: about the room one row of its size gave it. */
const ROWS: Record<GridKind, number> = {
  Card: 4, Note: 3, Image: 5, ProcessBoard: 7, ObjectTable: 8, ObjectDetail: 7, ObjectFigure: 3, ObjectChart: 6,
};

const clamp = (lo: number, hi: number, v: number) => Math.max(lo, Math.min(hi, v));

/** A box held to what its kind may take (`LIMITS`), in whole grades. */
export function clampBox(type: string, box: Box): Box {
  const lim = LIMITS[type as GridKind];
  const w = Math.round(box.w), h = Math.round(box.h);
  return lim ? { w: clamp(lim.w[0], lim.w[1], w), h: clamp(lim.h[0], lim.h[1], h) } : { w, h };
}

/** The room an element has: its own w and h on the grid, else the room its size gives it on a section of `columns`. */
export function boxOf(el: Element, columns = AUTO_COLUMNS): Box {
  if (typeof el.props.w === "number" && typeof el.props.h === "number") return { w: el.props.w, h: el.props.h };
  const kind = el.type as GridKind;
  const span = SPAN[(el.props.size as Size | undefined) ?? DEFAULT_SIZE[kind] ?? "small"] ?? SPAN.small;
  const c = Math.max(1, columns);
  const rows = ROWS[kind] ?? 4;
  return clampBox(el.type, { w: (GRID.columns * Math.min(span.w, c)) / c, h: span.h === 2 ? rows * 2 + 1 : rows });
}

/** The named size nearest a box, for an element leaving the grid for a section that sizes by name. */
export function sizeNear(box: Box): Size {
  const wide = box.w >= 9 ? 3 : box.w >= 5 ? 2 : 1;
  const tall = box.h >= 8 ? 2 : 1;
  return (Object.keys(SPAN) as Size[]).find(s => SPAN[s].w === wide && SPAN[s].h === tall) ?? "small";
}

export function onGrid(spec: unknown, sectionKey: string): boolean {
  return (spec as CockpitSpec).elements[sectionKey]?.props.grid === GRID.columns;
}

/** Fit an element to the section it now stands in: on the grid it says its room in columns and rows; off it, by name. */
function fitTo(s: CockpitSpec, sectionKey: string, key: string): void {
  const el = s.elements[key];
  if (!el || !(el.type in LIMITS)) return;
  if (onGrid(s, sectionKey)) {
    const box = boxOf(el);
    const { size: _size, ...rest } = el.props;
    el.props = { ...rest, w: box.w, h: box.h };
  } else if (typeof el.props.w === "number" || typeof el.props.h === "number") {
    const { w: _w, h: _h, ...rest } = el.props;
    const near = sizeNear(boxOf(el));
    el.props = near === "small" ? rest : { ...rest, size: near };
  }
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

/** Take `key` out of its parent; a container left holding nothing goes too, up to the root. A placed element holds
 *  only what goes with it — an object detail its action buttons — so deleting one deletes those (Arc OC-4), and one
 *  left empty stays. */
function detach(s: CockpitSpec, key: string, andDelete: boolean): void {
  const parent = parentOf(s, key);
  if (parent) s.elements[parent].children = s.elements[parent].children.filter(k => k !== key);
  if (andDelete) {
    if (PLACED.includes(s.elements[key]?.type as never)) for (const child of s.elements[key].children) delete s.elements[child];
    delete s.elements[key];
  }
  if (parent && parent !== s.root && !PLACED.includes(s.elements[parent].type as never) && s.elements[parent].children.length === 0) {
    detach(s, parent, true);
  }
}

/** Take an element — a card, a section — off the cockpit. A table goes with every detail that follows it. */
export function takeOff(spec: unknown, key: string): CockpitSpec {
  const s = copy(spec);
  if (!(key in s.elements) || key === s.root) return settle(s);
  const followers = s.elements[key].type === "ObjectTable"
    ? Object.keys(s.elements).filter(k => s.elements[k].type === "ObjectDetail" && s.elements[k].props.follows === key) : [];
  for (const k of followers) if (k in s.elements) detach(s, k, true);
  if (key in s.elements) detach(s, key, true);
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
  fitTo(s, sectionKey, key);
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
  // a section started from one on the grid is on the grid too: what moves keeps its room
  s.elements[section] = { type: "Section", props: onGrid(s, from) ? { title: name, grid: GRID.columns } : { title: name }, children: [] };
  const siblings = s.elements[holder].children;
  siblings.splice(siblings.indexOf(from) + 1, 0, section);
  detach(s, key, false);
  s.elements[section].children.push(key);
  fitTo(s, section, key);
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
  fitTo(s, target, key);
  return s;
}

/** Place a note — the person's own words — in a section; the first, when none is named. The
 *  author and the date are the server's to stamp when it is kept. An empty note is no note. */
export function placeNote(spec: unknown, text: string, sectionKey?: string): CockpitSpec {
  const s = copy(spec);
  const words = text.trim().slice(0, MAX_NOTE);
  const target = sectionKey ?? sectionsOf(s)[0]?.key;
  if (!words || !target || s.elements[target]?.type !== "Section") return s;
  const key = freshKey(s, "note");
  s.elements[key] = { type: "Note", props: { text: words }, children: [] };
  s.elements[target].children.push(key);
  fitTo(s, target, key);
  return s;
}

/** Place an image the person uploaded, by its object id, with a caption. */
export function placeImage(spec: unknown, objectId: string, caption: string, sectionKey?: string): CockpitSpec {
  const s = copy(spec);
  const said = caption.trim().slice(0, MAX_CAPTION);
  const target = sectionKey ?? sectionsOf(s)[0]?.key;
  if (!objectId || !said || !target || s.elements[target]?.type !== "Section") return s;
  const key = freshKey(s, "image");
  s.elements[key] = { type: "Image", props: { object: objectId, caption: said }, children: [] };
  s.elements[target].children.push(key);
  fitTo(s, target, key);
  return s;
}

/** Arc OC-4 — place a piece bound to the ontology in a section (the first, unless one is named). Returns the spec and
 *  the new element's key — a detail names the table it follows by that key. An action button goes in a detail
 *  (`addAction`), never in a section. */
export function placePiece(
  spec: unknown, type: "ProcessBoard" | "ObjectTable" | "ObjectDetail", props: Record<string, unknown>, sectionKey?: string,
): { spec: CockpitSpec; key: string | null } {
  const s = copy(spec);
  const target = sectionKey ?? sectionsOf(s)[0]?.key;
  if (!target || s.elements[target]?.type !== "Section") return { spec: s, key: null };
  const base = type === "ProcessBoard" ? `board-${props.process}` : type === "ObjectTable"
    ? `table-${props.segment || props.entity}` : `detail-${props.follows}`;
  const key = freshKey(s, String(base));
  const kept = Object.fromEntries(Object.entries(props).filter(([, v]) => v !== undefined && v !== null && v !== ""
    && !(Array.isArray(v) && !v.length)));
  s.elements[key] = { type, props: kept, children: [] };
  s.elements[target].children.push(key);
  fitTo(s, target, key);
  return { spec: s, key };
}

/** Arc OC-4 — add a declared action's button to an object detail, once. */
export function addAction(spec: unknown, detailKey: string, actionId: string): CockpitSpec {
  const s = copy(spec);
  const detail = s.elements[detailKey];
  if (!detail || detail.type !== "ObjectDetail" || !actionId) return s;
  if (detail.children.some(k => s.elements[k]?.type === "ActionButton" && s.elements[k]?.props.action === actionId)) return s;
  const key = freshKey(s, `action-${actionId}`);
  s.elements[key] = { type: "ActionButton", props: { action: actionId }, children: [] };
  detail.children.push(key);
  return s;
}

/** Change a note's words. Its stamps are the server's: a changed note is re-stamped when kept. */
export function editNote(spec: unknown, key: string, text: string): CockpitSpec {
  const s = copy(spec);
  const words = text.trim().slice(0, MAX_NOTE);
  const el = s.elements[key];
  if (!el || el.type !== "Note" || !words) return s;
  el.props = { ...el.props, text: words };
  return s;
}

/** Change an image's caption. */
export function recaption(spec: unknown, key: string, caption: string): CockpitSpec {
  const s = copy(spec);
  const said = caption.trim().slice(0, MAX_CAPTION);
  const el = s.elements[key];
  if (!el || el.type !== "Image" || !said) return s;
  el.props = { ...el.props, caption: said };
  return s;
}

/** Give a placed element — a card, a note, an image — a size. "small" is the size an element
 *  has when it says none, so it is written as none: a spec says only what it must. */
export function resize(spec: unknown, key: string, size: Size): CockpitSpec {
  const s = copy(spec);
  const el = s.elements[key];
  if (!el || !PLACED.includes(el.type as never)) return s;
  const { size: _was, ...rest } = el.props;
  el.props = size === "small" ? rest : { ...rest, size };
  return s;
}

/** Arc AP-1 — put a section on the grid: each element it places takes the room `measured` says it had on screen (a
 *  person's eye judged the cockpit as drawn), else the room its size gave it; its `columns` goes, and each `size`, which
 *  the grid would read by nothing. A section already on the grid is left as it is. */
export function toGrid(spec: unknown, sectionKey: string, measured: Record<string, Box> = {}): CockpitSpec {
  const s = copy(spec);
  const sec = s.elements[sectionKey];
  if (!sec || sec.type !== "Section" || onGrid(s, sectionKey)) return s;
  const columns = typeof sec.props.columns === "number" ? sec.props.columns : AUTO_COLUMNS;
  for (const k of sec.children) {
    const el = s.elements[k];
    if (!el || !(el.type in LIMITS)) continue;
    const box = clampBox(el.type, measured[k] ?? boxOf(el, columns));
    const { size: _size, ...rest } = el.props;
    el.props = { ...rest, w: box.w, h: box.h };
  }
  const { columns: _columns, ...props } = sec.props;
  sec.props = { ...props, grid: GRID.columns };
  return s;
}

/** Arc AP-1 — give an element its room on its section's grid, held to what its kind may take. A section not yet on the
 *  grid moves onto it first, every other element keeping the room `measured` says it had. Nothing else changes. */
export function regrid(spec: unknown, key: string, box: Box, measured: Record<string, Box> = {}): CockpitSpec {
  const section = parentOf(spec as CockpitSpec, key);
  if (!section || (spec as CockpitSpec).elements[section]?.type !== "Section") return copy(spec);
  const s = toGrid(spec, section, measured);
  const el = s.elements[key];
  if (!el || !(el.type in LIMITS)) return s;
  const fitted = clampBox(el.type, box);
  el.props = { ...el.props, w: fitted.w, h: fitted.h };
  return s;
}

/** Arc AP-1 — the filter column's width in grades of 40 px, held to its least and most. */
export function setFilterWidth(spec: unknown, w: number): CockpitSpec {
  const s = copy(spec);
  const key = (s.elements[s.root]?.children ?? []).find(k => s.elements[k]?.type === "ObjectFilters");
  if (!key) return s;
  s.elements[key].props = { ...s.elements[key].props, w: clamp(FILTER_WIDTH.least, FILTER_WIDTH.most, Math.round(w)) };
  return s;
}

/** The keys of the notes and images a spec holds, in the order its sections place them. */
export function staticsPlaced(spec: unknown): string[] {
  const s = spec as CockpitSpec;
  return sectionsOf(s).flatMap(sec => s.elements[sec.key].children.filter(k => {
    const t = s.elements[k]?.type;
    return t === "Note" || t === "Image";
  }));
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
    // the filter column stays the cockpit's own first child, beside the tabs: a tab holds sections only
    const column = root.children.filter(k => s.elements[k]?.type === "ObjectFilters");
    const first = freshKey(s, "tab-overview");
    s.elements[first] = { type: "Tab", props: { name: "overview", label: "Overview" },
      children: root.children.filter(k => !column.includes(k)) };
    tabs = freshKey(s, "tabs");
    s.elements[tabs] = { type: "Tabs", props: { value: { $bindState: "/tab" } }, children: [first] };
    root.children = [...column, tabs];
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
