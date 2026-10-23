/**
 * Hand edits to a dashboard's spec (Arc CT, CT-8; ROADMAP §3.50).
 *
 * A person arranges their dashboard by hand: moves a card, takes one off, renames a section or a
 * tab, starts a new section or a new tab. Each edit here is a pure function from a spec to a NEW
 * spec — the one it was given is never touched — and what comes out is kept by the server as the
 * next version, through the same rules as any other (`rules.ts`, run there by the validator).
 *
 * The rules refuse an empty section, tab or row of tabs. So taking the last card out of a section
 * takes the section too, and so on upward: the dashboard that is left is always one the rules can
 * accept, except the dashboard with nothing left in it — which the rules refuse, in their own words,
 * and a person retires instead.
 *
 * No model, no figure. A title a person types is theirs; the server keeps it as theirs.
 */
import {
  FILTER_WIDTH, GRID, LIMITS, MAX_CAPTION, MAX_LABEL, MAX_NOTE, MAX_TITLE, PLACED, SPAN, type DashboardSetDef, type DashboardValueDef,
  type GridKind, type Layout, type Size,
} from "@/lib/dashboards/catalog";
import { choicesOf, readersOf } from "@/lib/dashboards/sets";

export interface Element {
  type: string;
  props: Record<string, unknown>;
  children: string[];
  visible?: unknown;
}

export interface DashboardSpec {
  root: string;
  state?: Record<string, unknown>;
  elements: Record<string, Element>;
  /** Arc AP-2 — the sets and values a wired dashboard's pieces read, by name. */
  sets?: Record<string, DashboardSetDef>;
  values?: Record<string, DashboardValueDef>;
}

export interface SectionRef {
  key: string; title: string; tabKey: string | null; tabLabel: string | null;
  /** Arc AP-4 — a drawer, which holds pieces as a section does and opens beside the page on a choice. */
  drawer?: boolean;
}
export interface TabRef { key: string; name: string; label: string }

function copy(spec: unknown): DashboardSpec {
  return JSON.parse(JSON.stringify(spec)) as DashboardSpec;
}

function parentOf(s: DashboardSpec, key: string): string | null {
  for (const [k, el] of Object.entries(s.elements)) {
    if (el.children?.includes(key)) return k;
  }
  return null;
}

function tabsElement(s: DashboardSpec): string | null {
  const root = s.elements[s.root];
  return (root?.children ?? []).find(k => s.elements[k]?.type === "Tabs") ?? null;
}

/** An element's room on a section's grid: columns across, rows down (Arc AP-1). */
export interface Box { w: number; h: number }

/** The columns a section draws when it says none (`ComposedDashboard`'s most). */
const AUTO_COLUMNS = 4;
/** The size an element draws at when it says none, by kind — as `ComposedDashboard` draws it. */
const DEFAULT_SIZE: Record<GridKind, Size> = {
  Card: "small", Note: "small", Image: "small", ProcessBoard: "full", ObjectTable: "wide", ObjectDetail: "small",
  ObjectFigure: "small", ObjectChart: "full", ActionButtons: "small",
  ObjectList: "wide", ObjectMap: "wide", ObjectTimeline: "full", ChooseOne: "wide", ObjectSearch: "wide",
};
/** The rows a kind takes on the grid when nothing measured it: about the room one row of its size gave it. */
const ROWS: Record<GridKind, number> = {
  Card: 4, Note: 3, Image: 5, ProcessBoard: 7, ObjectTable: 8, ObjectDetail: 7, ObjectFigure: 3, ObjectChart: 6,
  ActionButtons: 2, ObjectList: 8, ObjectMap: 9, ObjectTimeline: 7, ChooseOne: 7, ObjectSearch: 3,
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
  return (spec as DashboardSpec).elements[sectionKey]?.props.grid === GRID.columns;
}

/** Fit an element to the section it now stands in: on the grid it says its room in columns and rows; off it, by name. */
function fitTo(s: DashboardSpec, sectionKey: string, key: string): void {
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

/** Whether pieces may be placed in `key`: a section not laid out in sections, or a drawer (Arc AP-4). */
function holdsPieces(s: DashboardSpec, key: string): boolean {
  const el = s.elements[key];
  return !!el && ((el.type === "Section" && !el.props.layout) || el.type === "Drawer");
}

/** A key no element has, made from `base`. */
function freshKey(s: DashboardSpec, base: string): string {
  const stem = base.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "el";
  let key = stem;
  for (let n = 2; key in s.elements; n++) key = `${stem}-${n}`;
  return key;
}

/** The sections a card may be moved to, in the order they are drawn. */
export function sectionsOf(spec: unknown): SectionRef[] {
  const s = spec as DashboardSpec;
  const out: SectionRef[] = [];
  const walk = (key: string, tab: TabRef | null) => {
    const el = s.elements[key];
    if (!el) return;
    if (el.type === "Section" && !el.props.layout) {
      out.push({ key, title: String(el.props.title ?? ""), tabKey: tab?.key ?? null, tabLabel: tab?.label ?? null });
      return;
    }
    if (el.type === "Drawer") {
      out.push({ key, title: String(el.props.title ?? ""), tabKey: null, tabLabel: null, drawer: true });
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
  const s = spec as DashboardSpec;
  const tabs = tabsElement(s);
  return (tabs ? s.elements[tabs].children : []).map(k => ({
    key: k, name: String(s.elements[k].props.name), label: String(s.elements[k].props.label),
  }));
}

/** The card ids the spec places, each once, in draw order. */
export function cardsPlaced(spec: unknown): string[] {
  const s = spec as DashboardSpec;
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
 *  must not leave the dashboard opening on nothing. */
function settle(s: DashboardSpec): DashboardSpec {
  const names = tabsOf(s).map(t => t.name);
  if (s.state && "tab" in s.state && names.length && !names.includes(String(s.state.tab))) {
    s.state = { ...s.state, tab: names[0] };
  }
  return s;
}

/** Take `key` out of its parent; a container left holding nothing goes too, up to the root. A placed element holds
 *  only what goes with it — an object detail its action buttons — so deleting one deletes those (Arc OC-4), and one
 *  left empty stays. */
function detach(s: DashboardSpec, key: string, andDelete: boolean): void {
  const parent = parentOf(s, key);
  if (parent) s.elements[parent].children = s.elements[parent].children.filter(k => k !== key);
  if (andDelete) {
    if (PLACED.includes(s.elements[key]?.type as never)) for (const child of s.elements[key].children) delete s.elements[child];
    delete s.elements[key];
  }
  // a drawer left with nothing stays, for a person to place a piece in or take off
  if (parent && parent !== s.root && !PLACED.includes(s.elements[parent].type as never) && s.elements[parent].children.length === 0
    && !inLayout(s, parent) && s.elements[parent].type !== "Drawer") {
    detach(s, parent, true);
  }
}

/** Arc AP-4 — whether a section sits in one laid out in sections: there, a section left with nothing stays, an empty box
 *  its layout keeps; a section of the dashboard's own goes when it is emptied, as it always did. */
function inLayout(s: DashboardSpec, key: string): boolean {
  const parent = parentOf(s, key);
  return s.elements[key]?.type === "Section" && !!parent && s.elements[parent]?.type === "Section" && !!s.elements[parent].props.layout;
}

/** Take an element — a card, a section — off the dashboard. A table goes with every detail that follows it. */
export function takeOff(spec: unknown, key: string): DashboardSpec {
  const s = copy(spec);
  if (!(key in s.elements) || key === s.root) return settle(s);
  const followers = s.elements[key].type === "ObjectTable"
    ? Object.keys(s.elements).filter(k => s.elements[k].type === "ObjectDetail" && s.elements[k].props.follows === key) : [];
  for (const k of followers) if (k in s.elements) detach(s, k, true);
  if (key in s.elements) detach(s, key, true);
  return settle(s);
}

/** Take a card off the dashboard wherever it is placed. The card itself is not touched. */
export function takeOffCard(spec: unknown, cardId: string): DashboardSpec {
  let s = copy(spec);
  for (const [k, el] of Object.entries(s.elements)) {
    if (el.type === "Card" && el.props.card === cardId) s = takeOff(s, k);
  }
  return s;
}

/** Move an element one place earlier (-1) or later (+1) among its siblings. */
export function moveWithin(spec: unknown, key: string, delta: -1 | 1): DashboardSpec {
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
export function moveCardTo(spec: unknown, key: string, sectionKey: string): DashboardSpec {
  const s = copy(spec);
  if (!(key in s.elements) || !holdsPieces(s, sectionKey) || parentOf(s, key) === sectionKey) return s;
  detach(s, key, false);
  if (!(sectionKey in s.elements)) return copy(spec);         // the section went with the card: nothing moved
  s.elements[sectionKey].children.push(key);
  fitTo(s, sectionKey, key);
  return settle(s);
}

/** Start a new section, after the one the card is in, and move the card to it. */
export function moveCardToNewSection(spec: unknown, key: string, title: string): DashboardSpec {
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
export function placeCard(spec: unknown, cardId: string, sectionKey?: string): DashboardSpec {
  const s = copy(spec);
  const target = sectionKey ?? sectionsOf(s)[0]?.key;
  if (!target || s.elements[target]?.type !== "Section") return s;
  const key = freshKey(s, `card-${cardId}`);
  s.elements[key] = { type: "Card", props: { card: cardId }, children: [] };
  s.elements[target].children.push(key);
  fitTo(s, target, key);
  return s;
}

/** Arc AP-7 — a changed card in place of the one it replaces, wherever the dashboard places it: a change to a query of the
 *  person's own is a new card, and the one before stays in the store for the versions that read it. */
export function swapCard(spec: unknown, from: string, to: string): DashboardSpec {
  const s = copy(spec);
  for (const el of Object.values(s.elements)) {
    if (el.type === "Card" && el.props?.card === from) el.props = { ...el.props, card: to };
  }
  return s;
}

/** Place a note — the person's own words — in a section; the first, when none is named. The
 *  author and the date are the server's to stamp when it is kept. An empty note is no note. */
export function placeNote(spec: unknown, text: string, sectionKey?: string): DashboardSpec {
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
export function placeImage(spec: unknown, objectId: string, caption: string, sectionKey?: string): DashboardSpec {
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
  spec: unknown, type: "ProcessBoard" | "ObjectTable" | "ObjectDetail" | "ActionButtons" | "ObjectFigure" | "ObjectChart"
    | "ObjectList" | "ObjectMap" | "ObjectTimeline" | "ChooseOne" | "ObjectSearch",
  props: Record<string, unknown>, sectionKey?: string,
): { spec: DashboardSpec; key: string | null } {
  const s = copy(spec);
  const target = sectionKey ?? sectionsOf(s)[0]?.key;
  if (!target || !holdsPieces(s, target)) return { spec: s, key: null };
  const base = type === "ProcessBoard" ? `board-${props.process}` : type === "ObjectTable"
    ? `table-${props.segment || props.entity || props.set}` : type === "ActionButtons" ? "buttons"
      : type === "ObjectFigure" ? `figure-${props.set || props.entity}` : type === "ObjectChart" ? `chart-${props.set || props.entity}`
        : type === "ObjectDetail" ? `detail-${props.follows}`
          : `${type.replace(/^Object/, "").replace(/^ChooseOne$/, "choose").toLowerCase()}-${props.set || props.entity}`;
  const key = freshKey(s, String(base));
  const kept = Object.fromEntries(Object.entries(props).filter(([, v]) => v !== undefined && v !== null && v !== ""
    && !(Array.isArray(v) && !v.length)));
  s.elements[key] = { type, props: kept, children: [] };
  const empty = s.elements[target].children.length === 0;
  s.elements[target].children.push(key);
  fitTo(s, target, key);
  // Arc AP-4 — the first piece in a section fills it, as a piece fills the box a person made for it
  const lim = LIMITS[type as GridKind];
  if (empty && lim && onGrid(s, target)) s.elements[key].props.w = Math.min(lim.w[1], GRID.columns);
  return { spec: s, key };
}

/** Arc AP-4 — a drawer that opens beside the page when `opensOn` is chosen, holding a detail of the chosen object: the
 *  dashboard's own, after its sections. */
export function addDrawer(spec: unknown, title: string, opensOn: string): { spec: DashboardSpec; key: string | null } {
  const s = copy(spec);
  const name = title.trim().slice(0, MAX_TITLE);
  if (!name || !opensOn || !s.elements[s.root]) return { spec: s, key: null };
  const key = freshKey(s, `drawer-${opensOn}`);
  s.elements[key] = { type: "Drawer", props: { title: name, opens_on: opensOn }, children: [] };
  const detail = freshKey(s, `detail-${opensOn}`);
  s.elements[detail] = { type: "ObjectDetail", props: { follows: opensOn }, children: [] };
  s.elements[key].children.push(detail);
  s.elements[s.root].children.push(key);
  return { spec: s, key };
}

/** Arc OC-4 — add a declared action's button to an object detail, once. */
export function addAction(spec: unknown, detailKey: string, actionId: string): DashboardSpec {
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
export function editNote(spec: unknown, key: string, text: string): DashboardSpec {
  const s = copy(spec);
  const words = text.trim().slice(0, MAX_NOTE);
  const el = s.elements[key];
  if (!el || el.type !== "Note" || !words) return s;
  el.props = { ...el.props, text: words };
  return s;
}

/** Change an image's caption. */
export function recaption(spec: unknown, key: string, caption: string): DashboardSpec {
  const s = copy(spec);
  const said = caption.trim().slice(0, MAX_CAPTION);
  const el = s.elements[key];
  if (!el || el.type !== "Image" || !said) return s;
  el.props = { ...el.props, caption: said };
  return s;
}

/** Give a placed element — a card, a note, an image — a size. "small" is the size an element
 *  has when it says none, so it is written as none: a spec says only what it must. */
export function resize(spec: unknown, key: string, size: Size): DashboardSpec {
  const s = copy(spec);
  const el = s.elements[key];
  if (!el || !PLACED.includes(el.type as never)) return s;
  const { size: _was, ...rest } = el.props;
  el.props = size === "small" ? rest : { ...rest, size };
  return s;
}

/** Arc AP-1 — put a section on the grid: each element it places takes the room `measured` says it had on screen (a
 *  person's eye judged the dashboard as drawn), else the room its size gave it; its `columns` goes, and each `size`, which
 *  the grid would read by nothing. A section already on the grid is left as it is. */
export function toGrid(spec: unknown, sectionKey: string, measured: Record<string, Box> = {}): DashboardSpec {
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
export function regrid(spec: unknown, key: string, box: Box, measured: Record<string, Box> = {}): DashboardSpec {
  const section = parentOf(spec as DashboardSpec, key);
  if (!section || (spec as DashboardSpec).elements[section]?.type !== "Section") return copy(spec);
  const s = toGrid(spec, section, measured);
  const el = s.elements[key];
  if (!el || !(el.type in LIMITS)) return s;
  const fitted = clampBox(el.type, box);
  el.props = { ...el.props, w: fitted.w, h: fitted.h };
  return s;
}

/** Arc AP-1 — the filter column's width in grades of 40 px, held to its least and most. */
export function setFilterWidth(spec: unknown, w: number): DashboardSpec {
  const s = copy(spec);
  const key = (s.elements[s.root]?.children ?? []).find(k => s.elements[k]?.type === "ObjectFilters");
  if (!key) return s;
  s.elements[key].props = { ...s.elements[key].props, w: clamp(FILTER_WIDTH.least, FILTER_WIDTH.most, Math.round(w)) };
  return s;
}

/** The keys of the notes and images a spec holds, in the order its sections place them. */
export function staticsPlaced(spec: unknown): string[] {
  const s = spec as DashboardSpec;
  return sectionsOf(s).flatMap(sec => s.elements[sec.key].children.filter(k => {
    const t = s.elements[k]?.type;
    return t === "Note" || t === "Image";
  }));
}

/** Rename the dashboard, a section or a tab. An empty name is no name: nothing changes. */
export function rename(spec: unknown, key: string, text: string): DashboardSpec {
  const s = copy(spec);
  const el = s.elements[key];
  const name = text.trim();
  if (!el || !name) return s;
  if (el.type === "Tab") el.props.label = name.slice(0, MAX_LABEL);
  else if (el.type === "Section" || el.type === "Cockpit") el.props.title = name.slice(0, MAX_TITLE);
  return s;
}

/** Move a section to another tab. */
export function moveSectionTo(spec: unknown, sectionKey: string, tabKey: string): DashboardSpec {
  const s = copy(spec);
  if (s.elements[sectionKey]?.type !== "Section" || s.elements[tabKey]?.type !== "Tab" || parentOf(s, sectionKey) === tabKey) return s;
  detach(s, sectionKey, false);
  if (!(tabKey in s.elements)) return copy(spec);
  s.elements[tabKey].children.push(sectionKey);
  return settle(s);
}

/** Start a new tab and move a section to it. A dashboard with no tabs gets them: what it held
 *  becomes the first tab, "Overview", and the new tab follows it. */
export function moveSectionToNewTab(spec: unknown, sectionKey: string, label: string): DashboardSpec {
  const s = copy(spec);
  const name = label.trim().slice(0, MAX_LABEL);
  if (s.elements[sectionKey]?.type !== "Section" || !name) return s;
  let tabs = tabsElement(s);
  if (!tabs) {
    const root = s.elements[s.root];
    // the filter column stays the dashboard's own first child, beside the tabs: a tab holds sections only
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

// ── Arc AP-1 — the builder (docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.4) ─────────────────────────────────────

/** The builder's Setup: some of an element's props set, the rest kept. A prop set to null or undefined is taken off,
 *  so choosing "none" leaves nothing behind. Its room — `size`, `w`, `h` — is the handles' and the steps' to change. */
export function setProps(spec: unknown, key: string, patch: Record<string, unknown>): DashboardSpec {
  const s = copy(spec);
  const el = s.elements[key];
  if (!el) return s;
  const props = { ...el.props };
  for (const [name, value] of Object.entries(patch)) {
    if (value === undefined || value === null) delete props[name];
    else props[name] = value;
  }
  el.props = props;
  return s;
}

/** Whether `key` can move one place earlier or later among its parent's children. The filter column stays the
 *  dashboard's first child, so nothing moves before it and it moves nowhere. */
export function canMove(spec: unknown, key: string, delta: -1 | 1): boolean {
  const s = spec as DashboardSpec;
  const parent = parentOf(s, key);
  if (!parent || s.elements[key]?.type === "ObjectFilters") return false;
  const kids = s.elements[parent].children;
  const j = kids.indexOf(key) + delta;
  return j >= 0 && j < kids.length && s.elements[kids[j]]?.type !== "ObjectFilters";
}

/** Take an element off, and everything it holds: a section with its pieces, a tab with its sections. A section left
 *  with nothing goes, as `takeOff` takes it, so the dashboard left is one the rules accept. */
export function takeOffAll(spec: unknown, key: string): DashboardSpec {
  const s = spec as DashboardSpec;
  const el = s.elements[key];
  if (!el || key === s.root) return copy(spec);
  if (PLACED.includes(el.type as never) || el.type === "ObjectFilters" || el.type === "ActionButton") return takeOff(spec, key);
  let out = copy(spec);
  for (const child of [...el.children]) out = takeOffAll(out, child);
  return key in out.elements ? takeOff(out, key) : out;
}

/** One line of a dashboard's outline: an element and how deep it sits under the root. The row of tabs is not a line —
 *  its tabs are. */
export interface OutlineLine { key: string; depth: number; type: string }

/** The dashboard as a tree of lines, in the order it is drawn: the root, the filter column, each tab, each section, the
 *  pieces each holds and the buttons a detail holds. */
export function outline(spec: unknown): OutlineLine[] {
  const s = spec as DashboardSpec;
  const out: OutlineLine[] = [];
  const walk = (key: string, depth: number, seen: Set<string>) => {
    const el = s.elements[key];
    if (!el || seen.has(key)) return;
    seen.add(key);
    if (el.type === "Tabs") { for (const c of el.children) walk(c, depth, seen); return; }
    out.push({ key, depth, type: el.type });
    for (const c of el.children) walk(c, depth + 1, seen);
  };
  walk(s.root, 0, new Set());
  return out;
}

// ── Arc AP-2 — a dashboard's sets and values, by hand ─────────────────────────────────────────────────────────────────

/** A name for a new set, value or choice, made from what a person calls it — "Shipped late" → `shipped-late` — and
 *  never one the dashboard already uses for anything. */
export function freshWireName(spec: unknown, label: string): string {
  const s = spec as DashboardSpec;
  const used = new Set([...Object.keys(s.sets ?? {}), ...Object.keys(s.values ?? {}), ...choicesOf(s).keys()]);
  const base = (label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").replace(/^[^a-z]+/, "") || "set").slice(0, 32);
  if (!used.has(base)) return base;
  for (let i = 2; ; i++) if (!used.has(`${base}-${i}`)) return `${base}-${i}`;
}

/** The set `name` added, or changed to `def`. */
export function putSet(spec: unknown, name: string, def: DashboardSetDef): DashboardSpec {
  const s = copy(spec);
  s.sets = { ...(s.sets ?? {}), [name]: def };
  return s;
}

/** The value `name` added, or changed to `def`. */
export function putValue(spec: unknown, name: string, def: DashboardValueDef): DashboardSpec {
  const s = copy(spec);
  s.values = { ...(s.values ?? {}), [name]: def };
  return s;
}

/** Arc AP-8 — the value `from` renamed `label`: while nothing reads it, its name follows — `{{country}}`, never the
 *  `{{window-2}}` it was made as — kept in its place among the values; once something reads it, the name stays and
 *  only the label changes, so nothing that reads it is left reading nothing. The name it has after. */
export function renameValue(spec: unknown, from: string, label: string, read: boolean): { spec: DashboardSpec; name: string } {
  const s = copy(spec);
  const def = s.values?.[from];
  if (!def) return { spec: s, name: from };
  const others = { ...s, values: Object.fromEntries(Object.entries(s.values ?? {}).filter(([k]) => k !== from)) };
  const name = read ? from : freshWireName(others, label);
  s.values = Object.fromEntries(Object.entries(s.values ?? {}).map(([k, v]) => (k === from ? [name, { ...v, label }] : [k, v])));
  return { spec: s, name };
}

/** Take a set or a value away — only one nothing reads; one something reads is left as it is, and `readersOf` says
 *  what reads it. A dashboard left with none carries no empty map. */
export function dropWire(spec: unknown, name: string): DashboardSpec {
  const s = copy(spec);
  const readers = readersOf(s, name);
  if (readers.elements.length || readers.sets.length) return s;
  for (const k of ["sets", "values"] as const) {
    const map = s[k];
    if (map && name in map) {
      delete map[name];
      if (!Object.keys(map).length) delete s[k];
    }
  }
  return s;
}

// ── Arc AP-4 — a structure of pieces ────────────────────────────────────────────────────────────────────────────────

/** What a new, empty section is called until a person names it — or until its first piece names it (`nameByPiece`). */
export const NEW_SECTION = "New section";
export type Side = "above" | "below" | "left" | "right";

function emptySection(s: DashboardSpec, title = NEW_SECTION): string {
  const key = freshKey(s, "section");
  s.elements[key] = { type: "Section", props: { title, grid: GRID.columns }, children: [] };
  return key;
}

/** Split a section with a new, empty one on a side of it — the user's ask of 2026-10-11, on Workshop's blank app. In a
 *  layout running the same way, the new section joins it beside or under this one (side by side, the two share its
 *  width); otherwise a section laid out that way takes this one's place and holds the two. Returns the new section. */
export function splitSection(spec: unknown, key: string, side: Side): { spec: DashboardSpec; key: string | null } {
  const s = copy(spec);
  const el = s.elements[key];
  if (el?.type !== "Section") return { spec: s, key: null };
  const way: Layout = side === "left" || side === "right" ? "columns" : "rows";
  const first = side === "left" || side === "above";
  const parent = parentOf(s, key);
  const fresh = emptySection(s);
  const p = parent ? s.elements[parent] : null;
  if (p?.type === "Section" && p.props.layout === way) {
    const at = p.children.indexOf(key);
    p.children.splice(first ? at : at + 1, 0, fresh);
    if (way === "columns") {
      const w = typeof el.props.w === "number" ? el.props.w : GRID.columns;
      const half = Math.max(1, Math.floor(w / 2));
      el.props.w = Math.max(1, w - half);
      s.elements[fresh].props.w = half;
    }
    return { spec: s, key: fresh };
  }
  const wrap = freshKey(s, `${key}-${way}`);
  const props: Record<string, unknown> = { layout: way };
  // the place this section held — its width among columns, a condition it is shown by — is the wrapper's now
  if (el.props.w != null) { props.w = el.props.w; delete el.props.w; }
  s.elements[wrap] = { type: "Section", props, children: first ? [fresh, key] : [key, fresh],
    ...(el.visible !== undefined ? { visible: el.visible } : {}) };
  if (el.visible !== undefined) delete el.visible;
  if (way === "columns") { el.props.w = GRID.columns / 2; s.elements[fresh].props.w = GRID.columns / 2; }
  if (parent) s.elements[parent].children = s.elements[parent].children.map(k => (k === key ? wrap : k));
  return { spec: s, key: fresh };
}

/** Split an empty section into sections of its own: two side by side, two one under the other, or two tabs. */
export function layOut(spec: unknown, key: string, layout: Layout): DashboardSpec {
  const s = copy(spec);
  const el = s.elements[key];
  if (el?.type !== "Section" || el.children.length || el.props.layout) return s;
  const titles = layout === "tabs" ? ["First tab", "Second tab"] : [NEW_SECTION, NEW_SECTION];
  const kids = titles.map(t => emptySection(s, t));
  if (layout === "columns") for (const k of kids) s.elements[k].props.w = GRID.columns / 2;
  const { grid: _g, columns: _c, ...rest } = el.props;
  void _g; void _c;
  el.props = { ...rest, layout };
  el.children = kids;
  return s;
}

/** One more section inside a section laid out in sections — side by side, a third of the width. */
export function addSectionInside(spec: unknown, key: string): { spec: DashboardSpec; key: string | null } {
  const s = copy(spec);
  const el = s.elements[key];
  if (el?.type !== "Section" || !el.props.layout) return { spec: s, key: null };
  const fresh = emptySection(s, el.props.layout === "tabs" ? "New tab" : NEW_SECTION);
  if (el.props.layout === "columns") s.elements[fresh].props.w = GRID.columns / 3;
  el.children.push(fresh);
  return { spec: s, key: fresh };
}

/** A section's width among columns, one twelfth at a time, between one column and all twelve. */
export function setSectionWidth(spec: unknown, key: string, w: number): DashboardSpec {
  const s = copy(spec);
  const el = s.elements[key];
  if (el?.type === "Section" && typeof el.props.w === "number") el.props.w = Math.min(GRID.columns, Math.max(1, Math.round(w)));
  return s;
}

/** Whether a section sits among columns, and so says its width. */
export function inColumns(spec: unknown, key: string): boolean {
  const s = spec as DashboardSpec;
  const parent = parentOf(s, key);
  return s.elements[key]?.type === "Section" && !!parent && s.elements[parent]?.props.layout === "columns";
}

/** A copy of an element and all it holds, beside it, under keys of its own. A choice is made by one element: a copy
 *  names none (what it chooses, ticks or shows), and a person names its own. */
export function duplicate(spec: unknown, key: string): { spec: DashboardSpec; key: string | null } {
  const s = copy(spec);
  const parent = parentOf(s, key);
  if (!parent || key === s.root || !s.elements[key] || s.elements[key].type === "ObjectFilters") return { spec: s, key: null };
  const clone = (k: string): string => {
    const el = s.elements[k];
    const fresh = freshKey(s, k);
    const { chooses: _c, ticks: _t, shows: _s, ...props } = el.props;
    void _c; void _t; void _s;
    s.elements[fresh] = { ...JSON.parse(JSON.stringify(el)), props: JSON.parse(JSON.stringify(props)), children: [] };
    s.elements[fresh].children = el.children.map(clone);
    return fresh;
  };
  const made = clone(key);
  const at = s.elements[parent].children.indexOf(key);
  s.elements[parent].children.splice(at + 1, 0, made);
  return { spec: s, key: made };
}

/** A section still called what a new one is called takes the name of the first piece placed in it. */
export function nameByPiece(spec: unknown, sectionKey: string, name: string): DashboardSpec {
  const s = copy(spec);
  const el = s.elements[sectionKey];
  if (el?.type === "Section" && el.props.title === NEW_SECTION && name.trim()) el.props.title = name.trim().slice(0, MAX_TITLE);
  return s;
}

/** Arc AP-4 — the dashboard's filter column, placed by hand: its first child, beside what it narrows. A dashboard holds one. */
export function placeFilterColumn(spec: unknown, props: Record<string, unknown>): { spec: DashboardSpec; key: string | null } {
  const s = copy(spec);
  const root = s.elements[s.root];
  if (!root || root.children.some(k => s.elements[k]?.type === "ObjectFilters")) return { spec: s, key: null };
  const key = freshKey(s, "filters");
  s.elements[key] = { type: "ObjectFilters", props, children: [] };
  root.children.unshift(key);
  return { spec: s, key };
}
