"use client";

/**
 * OntologyPieces — the dashboard's pieces bound to the ontology (Arc OC-4, ROADMAP §3.56; the screen the user approved
 * on 2026-10-09: a late dispatch dashboard, board → table → detail → action).
 *
 * Each piece names what it reads by id and reads it through the doors every other surface uses: a process board reads
 * `GET /ontology/processes`, an objects table `POST /objects/list` (the object door's own compiler), an object detail
 * `GET /objects/{type}/{key}`, and an action button runs a declared action through the governed execute door — or,
 * when running it needs approval, has the door stage it in the Actions inbox for a person. Nothing here computes a figure.
 *
 * The pieces talk to each other through the dashboard, never through the spec: the spec says which table a detail
 * follows (by element key); which object is chosen is the reader's, held here while they look. After an action runs,
 * every piece reads again, so its edit shows in the table and in the detail at once — and on the object's own page,
 * which reads the same edits.
 *
 * An id that stops resolving is said where the piece stands, never drawn as an empty piece.
 *
 * Since 2026-10-10 a dashboard started from an object adds three more (design-mockups/cockpit-from-object.html): a filter
 * column over an entity's categories, a figure and a chart of objects per day. A reader's click in the filter column
 * narrows every piece over that entity — the table too — for that reader only (the user, 2026-10-10): the choice is
 * held here and in their browser, never in the spec. A piece the filters cannot narrow says "Not filtered" while one
 * is on, so a whole-business number is never read as the filtered one.
 */
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { AskAboutPiece } from "@/components/dashboards/AskAbout";
import { useCellBox, useMeasured, useSettled } from "@/components/dashboards/cellBox";
import { Foot, Frame, Title } from "@/components/dashboards/DashboardTile";
import { Masked } from "@/components/objects/Masked";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { SelectField } from "@/components/ui/select";
import { TableActions } from "@/components/TableActions";
import {
  additive, anyFilter, breakdownGaps, cellText, chosenWords, conditionsFor, dayLabel, daysBefore, entityKey, figureText,
  foldBreakdown, onDays, pathWords, plural, propertyLabel, type BreakdownMeasure,
  splitOnDays, typeWord, inLastWindow, withWords, WORDS,
  ticks, toggled, topValues, windowEnd, type Filters,
} from "@/lib/dashboards/objectView";
import { CHOOSERS, MAX_TICKED_RUNS, SWITCHED, rowsTall, type PieceName } from "@/lib/dashboards/catalog";
import { choicesOf, doorConditions, isRefused, pieceSet, readSet, readsItself, type DoorCondition, type ValueNow, type WireSpec } from "@/lib/dashboards/sets";
import { useMarkRead } from "@/components/dashboards/readSlot";
import { queryValue, typedValue, valueFits, valueWords, valuesFor, valuesRead } from "@/lib/dashboards/values";
import { runCard } from "@/lib/api";
import { formatCount, formatDateTime, isNumericType, pct } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { objectHref } from "@/lib/objectLinks";
import {
  answerSays, cachedObjectCatalog, getDeclaredActions, getObjectPage, listObjects, queryObjects, runOrPropose,
  type ActionCheck, type DeclaredAction, type ObjectListingPage, type ObjectPage, type ObjectQueryRequest,
} from "@/lib/objects";
import { getProcesses, type ProcessDetail, type ProcessesAndRules } from "@/lib/objectTypes";

/** A value read, or why it cannot be, as the provider keeps it. */
const withValue = (got: { value: unknown } | { refused: string }) => ("refused" in got ? { value: null, refused: got.refused } : { value: got.value });

/** The object a reader chose in a table. */
export interface Picked { objectType: string; typeId: string; pk: string }

interface PiecesValue {
  connectionId?: string;
  schema?: string;
  /** The key the dashboard drawn is remembered under (`<connection>:<id>`, `shared:<owner>:<id>`) — what a question about
   *  one of its sets names it by (Arc FA-2); none outside a dashboard. */
  dashboardId?: string;
  /** Each table's chosen object, by the choice it names (`chooses`) or else the table's element key. */
  picked: Record<string, Picked>;
  pick: (choice: string, p: Picked | null) => void;
  /** Arc AP-2 — the objects ticked in each table that collects them, by the choice it names (`ticks`). */
  ticked: Record<string, Picked[]>;
  tickOne: (choice: string, p: Picked, on: boolean) => void;
  tickNone: (choice: string) => void;
  /** Arc AP-2 — the set a figure shows in a table's stead, by the choice it names (`shows`). */
  shown: Record<string, string>;
  show: (choice: string, set: string | null) => void;
  /** Arc AP-2 — the dashboard's sets and values, and its elements, which the pieces read by name. */
  wire: WireSpec;
  /** The names a detail may follow — each choosing piece's element key, and each object a click chooses — with the name
   *  its picks land under: a piece that names its choice picks under that name, whichever of the two a detail follows. */
  followable: Map<string, string>;
  /** Raised after an action runs, so every piece reads again. */
  tick: number;
  bump: () => void;
  /** The tables the dashboard holds: element key → what it lists. */
  tables: { key: string; entity: string; segment: string }[];
  /** Place a table of a segment beside a board — absent on a dashboard the reader may not change. */
  onPlaceTable?: (entity: string, segment: string) => void;
  /** One read per drawn dashboard and tick, shared by its pieces — never kept past the dashboard that made it. */
  processes: () => Promise<ProcessesAndRules>;
  actions: () => Promise<Record<string, DeclaredAction>>;
  /** The reader's own filters, by entity — never in the spec. */
  filters: Filters;
  toggle: (entity: string, path: string, value: string) => void;
  clear: (entity?: string) => void;
  /** Arc AP-4 — words a reader typed in a search box, narrowing every set of an entity; none lets the search go. */
  search: (entity: string, path: string, words: string) => void;
  /** Arc AP-6 — the group the dashboard is previewed as, every read made as the person and a member of it; "" for none. */
  asGroup: string;
  /** What the object door said beside what it read — what a row policy withholds, a property masked — for the page. */
  say: (lines: string[] | undefined) => void;
  /** Arc AP-8 — what each of the dashboard's values holds now: the author's, the reader's own, a set's count, or a property
   *  of the object a reader chose — or the choice it waits on, or still being read. */
  valueOf: (name: string) => ValueNow;
  /** The values a reader set on the page, by name — kept in their browser, never in the dashboard. */
  readerValues: Record<string, unknown>;
  setValue: (name: string, value: unknown) => void;
}

const PiecesContext = createContext<PiecesValue | null>(null);

export function usePieces(): PiecesValue {
  const ctx = useContext(PiecesContext);
  if (!ctx) throw new Error("an ontology piece was drawn outside its dashboard");
  return ctx;
}

/** Where a reader's filters for one dashboard are remembered: their browser, and only theirs. */
const filtersKey = (cockpit: string) => `aughor:cockpit-filters:${cockpit}`;
/** Arc AP-8 — where the values a reader set on one dashboard are remembered: their browser, and only theirs. */
const valuesKey = (cockpit: string) => `aughor:cockpit-values:${cockpit}`;

function rememberedValues(cockpit?: string): Record<string, unknown> {
  if (!cockpit) return {};
  try {
    const raw = JSON.parse(localStorage.getItem(valuesKey(cockpit)) ?? "{}") as unknown;
    return raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : {};
  } catch { return {}; }
}

function remembered(cockpit?: string): Filters {
  if (!cockpit) return {};
  try {
    const raw = JSON.parse(localStorage.getItem(filtersKey(cockpit)) ?? "{}") as unknown;
    return raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Filters : {};
  } catch { return {}; }
}

export function PiecesProvider({ connectionId, schema, elements, sets, values, onPlaceTable, dashboardId, asGroup = "", onSaid, cardSql, children }: {
  connectionId?: string;
  schema?: string;
  /** Arc AP-6 — preview every read as the person and a member of this group. */
  asGroup?: string;
  /** Arc AP-6 — each line the object door said beside a read, once, for the page. */
  onSaid?: (line: string) => void;
  elements: Record<string, { type?: string; props?: Record<string, unknown> } | undefined>;
  /** Arc AP-2 — the sets and values the dashboard names, read by its pieces. */
  sets?: WireSpec["sets"];
  values?: WireSpec["values"];
  onPlaceTable?: (entity: string, segment: string) => void;
  /** The dashboard drawn — the key a reader's filters are remembered under; none, and they last while it is open. */
  dashboardId?: string;
  /** Arc AP-8c — the statement of a card the dashboard places, for a value read from a query of its own. */
  cardSql?: (card: string) => string | undefined;
  children: ReactNode;
}) {
  const [picked, setPicked] = useState<Record<string, Picked>>({});
  const [ticked, setTicked] = useState<Record<string, Picked[]>>({});
  const [shown, setShown] = useState<Record<string, string>>({});
  const [filters, setFilters] = useState<Filters>(() => remembered(dashboardId));
  useEffect(() => { setFilters(remembered(dashboardId)); }, [dashboardId]);
  const keep = useCallback((next: Filters) => {
    setFilters(next);
    // a reader's choice changes a row they chose from: the detail is chosen again from what the table now lists, and
    // nothing stays ticked that the table may no longer list
    setPicked({});
    setTicked({});
    if (!dashboardId) return;
    try { localStorage.setItem(filtersKey(dashboardId), JSON.stringify(next)); } catch { /* it lasts while the dashboard is open */ }
  }, [dashboardId]);
  const toggle = useCallback((entity: string, path: string, value: string) => keep(toggled(filters, entity, path, value)),
    [filters, keep]);
  const search = useCallback((entity: string, path: string, words: string) => keep(withWords(filters, entity, path, words)),
    [filters, keep]);
  const clear = useCallback((entity?: string) => {
    if (!entity) { keep({}); return; }
    const next = { ...filters };
    delete next[entityKey(entity)];
    keep(next);
  }, [filters, keep]);
  const [tick, setTick] = useState(0);
  const pick = useCallback((choice: string, p: Picked | null) => setPicked(prev => {
    const next = { ...prev };
    if (p) next[choice] = p; else delete next[choice];
    return next;
  }), []);
  const tickOne = useCallback((choice: string, p: Picked, on: boolean) => setTicked(prev => {
    const had = prev[choice] ?? [];
    const rest = had.filter(x => x.pk !== p.pk);
    return { ...prev, [choice]: on ? [...rest, p] : rest };
  }), []);
  const tickNone = useCallback((choice: string) => setTicked(prev => ({ ...prev, [choice]: [] })), []);
  // a figure switching the list: what was chosen and ticked in the tables it switches is of another set now, and is let
  // go — a detail never goes on showing an object the list no longer holds
  const shownNow = useRef(shown);
  useEffect(() => { shownNow.current = shown; }, [shown]);
  const show = useCallback((choice: string, set: string | null) => {
    const switched = Object.entries(elements).filter(([, el]) => SWITCHED.includes(el?.type as PieceName) && el?.props?.set_from === choice);
    // what the list shows now: the set a figure showed in it, else the table's own
    const before = shownNow.current[choice] ?? (switched.length ? String(switched[0][1]?.props?.set ?? "") : null);
    if (before === set) return;
    const chooses = switched.flatMap(([key, el]) => [key, ...(typeof el?.props?.chooses === "string" ? [el.props.chooses] : [])]);
    const ticks = switched.flatMap(([, el]) => (typeof el?.props?.ticks === "string" ? [el.props.ticks] : []));
    if (chooses.length) setPicked(p => Object.fromEntries(Object.entries(p).filter(([k]) => !chooses.includes(k))));
    if (ticks.length) setTicked(t => Object.fromEntries(Object.entries(t).filter(([k]) => !ticks.includes(k))));
    setShown(prev => {
      const next = { ...prev };
      if (set) next[choice] = set; else delete next[choice];
      return next;
    });
  }, [elements]);
  const wire = useMemo<WireSpec>(() => ({ sets: sets ?? {}, values: values ?? {}, elements }), [sets, values, elements]);
  const followable = useMemo(() => new Map(Object.entries(elements).flatMap(([key, el]): [string, string][] => {
    if (!CHOOSERS.includes(el?.type as PieceName)) return [];
    const named = typeof el?.props?.chooses === "string" && el.props.chooses ? el.props.chooses : "";
    return named ? [[key, named], [named, named]] : [[key, key]];
  })), [elements]);
  const bump = useCallback(() => setTick(t => t + 1), []);
  const tables = useMemo(() => Object.entries(elements)
    .filter(([, el]) => el?.type === "ObjectTable")
    .map(([key, el]) => ({ key, entity: String(el?.props?.entity ?? ""), segment: String(el?.props?.segment ?? "") })),
  [elements]);
  const reads = useRef(new Map<string, Promise<unknown>>());
  const once = useCallback(<T,>(key: string, read: () => Promise<T>): Promise<T> => {
    let hit = reads.current.get(key) as Promise<T> | undefined;
    if (!hit) {
      hit = read();
      hit.catch(() => reads.current.delete(key));
      reads.current.set(key, hit);
    }
    return hit;
  }, []);
  const processes = useCallback(() => (connectionId
    ? once(`processes|${schema ?? ""}|${tick}`, () => getProcesses(connectionId, schema))
    : Promise.reject(new Error("This dashboard names no connection."))), [connectionId, schema, tick, once]);
  const actions = useCallback(() => (connectionId
    ? once(`actions|${schema ?? ""}`, () => getDeclaredActions(connectionId, schema))
    : Promise.reject(new Error("This dashboard names no connection."))), [connectionId, schema, once]);
  // each line said once to the page: a table, a figure and a chart of the same objects hear the same policy
  const heard = useRef(new Set<string>());
  const onSaidRef = useRef(onSaid);
  useEffect(() => { onSaidRef.current = onSaid; }, [onSaid]);
  const say = useCallback((lines: string[] | undefined) => {
    for (const line of lines ?? []) {
      if (line && !heard.current.has(line)) { heard.current.add(line); onSaidRef.current?.(line); }
    }
  }, []);
  // Arc AP-8 — the values: the reader's own, kept in their browser; a set's count and a chosen object's property, read here
  const [readerValues, setReaderValues] = useState<Record<string, unknown>>(() => rememberedValues(dashboardId));
  useEffect(() => { setReaderValues(rememberedValues(dashboardId)); }, [dashboardId]);
  const setValue = useCallback((name: string, v: unknown) => {
    setReaderValues(prev => {
      // undefined lets the reader's own go: the value is the author's again
      const { [name]: _gone, ...rest } = prev;
      void _gone;
      const next = v === undefined ? rest : { ...prev, [name]: v };
      if (dashboardId) {
        try { localStorage.setItem(valuesKey(dashboardId), JSON.stringify(next)); } catch { /* it lasts while the dashboard is open */ }
      }
      return next;
    });
    // like a filter: what the sets hold changes, so what was chosen and ticked from them is let go
    setPicked({});
    setTicked({});
  }, [dashboardId]);
  const [counted, setCounted] = useState<Record<string, { asked: string; n: number; refused?: string }>>({});
  const [readOff, setReadOff] = useState<Record<string, { pk: string; value: unknown; refused?: string }>>({});
  const [queried, setQueried] = useState<Record<string, { asked: string; value: unknown; refused?: string }>>({});
  // the choice each query value's own values wait on, as this render reads them (Arc AP-8c)
  const waitsRef = useRef<Record<string, string>>({});
  const valueOf = useCallback((name: string): ValueNow => {
    const def = values?.[name];
    if (!def) return { value: null };
    const from = def.from;
    if (!from || from.by === "author") return { value: def.value ?? null };
    if (from.by === "reader") {
      // the reader's own while it is still one the author offers, of the value's kind — else the author's
      const mine = readerValues[name];
      const offered = from.options ?? [];
      const among = (x: unknown) => offered.some(o => o === x);
      const ok = name in readerValues && valueFits(def.kind, mine)
        && (!offered.length || (Array.isArray(mine) ? mine.every(among) : among(mine)));
      return { value: ok ? mine : def.value ?? null };
    }
    if (from.by === "chosen") {
      const p = picked[from.choice];
      if (!p) return { waiting: from.choice };
      const got = readOff[name];
      if (!got || got.pk !== p.pk) return { reading: true };
      return got.refused ? { refused: got.refused } : { value: got.value };
    }
    if (from.by === "query") {
      // Arc AP-8c — the query's first value, as last read; one that reads itself back waits on nothing, and says so
      const ring = readsItself(wire, name, cardSql);
      if (ring) return { refused: `${ring.map(n => values?.[n]?.label ?? n).join(" → ")} read each other in a ring.` };
      // a query that reads a value read off a chosen object waits on that choice, and says which
      const waits = waitsRef.current[name];
      if (waits) return { waiting: waits };
      const got = queried[name];
      if (!got) return { reading: true };
      return got.refused ? { refused: got.refused } : { value: got.value };
    }
    const got = counted[name];
    if (!got) return { reading: true };
    return got.refused ? { refused: got.refused } : { value: got.n };
  }, [values, readerValues, picked, readOff, counted, queried, wire, cardSql]);
  // what each counted (or, AP-8c, summed) value asks the object door — its set, read with the values as they stand now
  const countAsks = useMemo(() => Object.fromEntries(Object.entries(values ?? {}).flatMap(([name, def]): [string, ObjectQueryRequest][] => {
    const from = def.from;
    if (from?.by !== "count" && from?.by !== "sum") return [];
    const r = readSet(wire, from.set, valueOf);
    if (isRefused(r)) return [];
    const read = doorConditions(r, c => picked[c]?.pk ?? null);
    if (!("filters" in read)) return [];
    const measure = from.by === "sum" ? { name: "n", agg: "sum", path: from.path } : { name: "n", agg: "count" };
    return [[name, { object_type: r.entity, measures: [measure], ...(r.segment ? { segment: r.segment } : {}),
      ...(read.filters.length ? { filters: read.filters } : {}) } as ObjectQueryRequest]];
  })), [values, wire, valueOf, picked]);
  const countKey = JSON.stringify(countAsks);
  useEffect(() => {
    if (!connectionId) return;
    let alive = true;
    for (const [name, body] of Object.entries(countAsks)) {
      const asked = JSON.stringify(body);
      if (counted[name]?.asked === `${asked}|${tick}`) continue;
      const at = `${asked}|${tick}`;
      queryObjects(body, connectionId, schema, ...(asGroup ? [asGroup] : []))
        .then(out => {
          if (!alive) return;
          // a count that cannot be read says why to what reads it — never a zero, never reading for ever
          const refused = out.path === "refused" ? out.refused : out.error ?? "";
          // a sum over no objects is none, never a zero it did not add up
          const raw = out.path === "refused" ? 0 : out.rows?.[0]?.[0];
          const n = Number(raw ?? (body.measures[0]?.agg === "sum" ? Number.NaN : 0));
          const why = refused || (Number.isNaN(n) ? "The set holds no objects to add up." : "");
          setCounted(prev => ({ ...prev, [name]: why ? { asked: at, n: 0, refused: why } : { asked: at, n } }));
        })
        .catch(e => { if (alive) setCounted(prev => ({ ...prev, [name]: { asked: at, n: 0, refused: (e as Error).message || "The count could not be read." } })); });
    }
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what each count asks
  }, [countKey, connectionId, schema, tick, asGroup]);
  // a property of the object a reader chose, read off its page
  const chosenKey = JSON.stringify(Object.entries(values ?? {}).flatMap(([name, def]) =>
    def.from?.by === "chosen" && picked[def.from.choice] ? [[name, picked[def.from.choice]?.pk]] : []));
  useEffect(() => {
    if (!connectionId) return;
    let alive = true;
    for (const [name, def] of Object.entries(values ?? {})) {
      if (def.from?.by !== "chosen") continue;
      const p = picked[def.from.choice];
      if (!p || readOff[name]?.pk === p.pk) continue;
      const path = def.from.path;
      const pk = p.pk;
      getObjectPage(p.objectType, pk, connectionId, schema, ...(asGroup ? [asGroup] : []))
        .then(out => {
          if (!alive) return;
          // what the chosen object holds — or why it cannot be read: refused, gone, withheld, masked, or not one of its own
          const prop = out.path === "object" ? out.properties.find(x => x.name === path) : undefined;
          const refused = out.path === "refused" ? out.refused : out.path !== "object" ? out.detail
            : !prop ? `The chosen object has no property ${path}.` : prop.withheld ? `${prop.display_name || path} is withheld from you: ${prop.withheld}` : "";
          setReadOff(prev => ({ ...prev, [name]: refused ? { pk, value: null, refused } : { pk, value: prop?.value ?? null } }));
        })
        .catch(e => { if (alive) setReadOff(prev => ({ ...prev, [name]: { pk, value: null, refused: (e as Error).message || "The chosen object could not be read." } })); });
    }
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the objects chosen
  }, [chosenKey, connectionId, schema, asGroup]);
  // Arc AP-8c — a value read from a query of the dashboard's own: the card run as written, never cut to the page's range,
  // with the values it reads as the page holds them now; again whenever one of them changes
  const queryAsks = useMemo(() => Object.fromEntries(Object.entries(values ?? {}).flatMap(([name, def]): [string, string][] => {
    if (def.from?.by !== "query") return [];
    const sql = cardSql?.(def.from.card);
    const names = valuesRead(sql);
    const now = names.length ? valuesFor(names, values, valueOf) : { values: {} };
    return [[name, JSON.stringify({ card: def.from.card, column: def.from.column ?? null, kind: def.kind, placed: sql !== undefined,
      ...("values" in now ? { sent: now.values } : "refused" in now ? { refused: now.refused }
        : "waiting" in now ? { pending: true, waiting: now.waiting } : { pending: true }) })]];
  })), [values, cardSql, valueOf]);
  waitsRef.current = Object.fromEntries(Object.entries(queryAsks).flatMap(([name, asked]) => {
    const w = (JSON.parse(asked) as { waiting?: string }).waiting;
    return w ? [[name, w]] : [];
  }));
  const queryKey = JSON.stringify(queryAsks);
  useEffect(() => {
    let alive = true;
    for (const [name, asked] of Object.entries(queryAsks)) {
      const at = `${asked}|${tick}`;
      if (queried[name]?.asked === at) continue;
      const ask = JSON.parse(asked) as { card: string; column: string | null; kind: string; placed: boolean;
        sent?: Record<string, { kind: string; value: unknown }>; refused?: string; pending?: boolean };
      if (ask.pending) continue;
      if (!ask.placed || ask.refused) {
        const refused = ask.refused ?? "The query it reads is not a card this dashboard places.";
        setQueried(prev => ({ ...prev, [name]: { asked: at, value: null, refused } }));
        continue;
      }
      runCard(ask.card, null, Object.keys(ask.sent ?? {}).length ? { values: ask.sent } : {})
        .then(run => { if (alive) setQueried(prev => ({ ...prev, [name]: { asked: at, ...withValue(queryValue(ask.kind, ask.column, run)) } })); })
        .catch(e => { if (alive) setQueried(prev => ({ ...prev, [name]: { asked: at, value: null, refused: (e as Error).message || "The query could not be run." } })); });
    }
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what each query is asked
  }, [queryKey, tick]);
  const value = useMemo<PiecesValue>(() => ({
    connectionId, schema, dashboardId, picked, pick, ticked, tickOne, tickNone, shown, show, wire, followable, tick, bump, tables, onPlaceTable,
    processes, actions, filters, toggle, clear, search, asGroup, say, valueOf, readerValues, setValue,
  }), [connectionId, schema, dashboardId, picked, pick, ticked, tickOne, tickNone, shown, show, wire, followable, tick, bump, tables, onPlaceTable,
    processes, actions, filters, toggle, clear, search, asGroup, say, valueOf, readerValues, setValue]);
  return <PiecesContext.Provider value={value}>{children}</PiecesContext.Provider>;
}

/** What a piece reads, as the object door reads it (Arc AP-2): the entity and segment of its set — its named set, the
 *  one a figure shows in its stead, or every object of the entity it names — and the conditions down that set, the
 *  object it links to and the reader's own filters over its entity. A set of what a chosen object links to waits on
 *  the choice while nothing is chosen. */
export type SetQuery =
  | { entity: string; segment: string; conditions: DoorCondition[]; label: string; set: string; narrowed: boolean }
  | { waiting: string; label: string }
  | { reading: true; label: string }
  | { refused: string };

export function useSetQuery(props: Record<string, unknown>, { reader: withReader = true }: { reader?: boolean } = {}): SetQuery {
  const { wire, picked, shown, filters, valueOf } = usePieces();
  const r = pieceSet(wire, props, c => shown[c] ?? null, valueOf);
  if (isRefused(r)) return r;
  const read = doorConditions(r, c => picked[c]?.pk ?? null);
  // a value it reads is still being counted, or read off the object chosen (Arc AP-8)
  if ("reading" in read) return { reading: true, label: r.label };
  if ("waiting" in read) return { waiting: read.waiting, label: r.label };
  // the whole of a set, beside what a reader's filters leave of it, is read without them
  const reader = withReader ? conditionsFor(filters, r.entity) as unknown as DoorCondition[] : [];
  return { entity: r.entity, segment: r.segment, conditions: [...read.filters, ...reader], label: r.label, set: r.name,
    narrowed: reader.length > 0 };
}

/** What a piece reading a chosen object's links says while nothing is chosen: "Choose an order in its table to see its
 *  lines here." — the choice's entity in words, never its name. */
export function WaitingWords({ choice, what }: { choice: string; what: string }) {
  const { wire } = usePieces();
  // "Products of the chosen distribution center" is the centre's products: what the set holds, said once
  const held = what.replace(/^its\s+/i, "").replace(/\s+of the\s.*$/i, "").toLowerCase();
  return <>{chooseWords(wire, choice)} to see {held ? `its ${held}` : "what it links to"} here.</>;
}

/** Where a reader makes a choice, in words: "Choose an order in its table" — a table, a list, a map, a timeline, or by
 *  its name in a choose-one (Arc AP-4). */
export function chooseWords(wire: WireSpec, choice: string): string {
  const made = choicesOf(wire).get(choice);
  const entity = words(made?.entity || "one").toLowerCase();
  const an = /^[aeiou]/.test(entity) ? "an" : "a";
  const where = WHERE[String(wire.elements[made?.madeBy[0] ?? ""]?.type ?? "ObjectTable")] ?? "";
  return `Choose ${an} ${entity}${where}`;
}
const WHERE: Record<string, string> = {
  ObjectTable: " in its table", ObjectList: " in its list", ObjectMap: " on its map", ObjectTimeline: " on its timeline", ChooseOne: "",
};

/** Whether a reader's filter is on anywhere in the dashboard — and so whether `entity`'s pieces are narrowed by one.
 *  Outside a dashboard's pieces (a strip of cards with none), nothing is filtered. */
export function useFiltering(entity?: string): { on: boolean; narrows: boolean } {
  const ctx = useContext(PiecesContext);
  if (!ctx) return { on: false, narrows: false };
  return { on: anyFilter(ctx.filters), narrows: !!entity && conditionsFor(ctx.filters, entity).length > 0 };
}

/** `useFiltering` for a piece that may read a set (Arc AP-2): its entity is its set's — so a piece reading a set of the
 *  filtered entity is narrowed, and says nothing; one over another entity says it is not filtered. */
export function usePieceFiltering(props: Record<string, unknown>): { on: boolean; narrows: boolean } {
  const ctx = useContext(PiecesContext);
  if (!ctx) return { on: false, narrows: false };
  const r = pieceSet(ctx.wire, props, c => ctx.shown[c] ?? null);
  const entity = isRefused(r) ? "" : r.entity;
  return { on: anyFilter(ctx.filters), narrows: !!entity && conditionsFor(ctx.filters, entity).length > 0 };
}

/** The chip a piece the filters cannot narrow wears while one is on. */
export function NotFiltered() {
  return (
    <span className="aug-fs-xs" data-testid="not-filtered" title="The filters narrow the objects' own pieces; this one reads everything"
      style={{ position: "absolute", top: 10, right: 12, zIndex: 1, color: "var(--t3)", background: "var(--bg-3)",
        border: "1px solid var(--b1)", borderRadius: "var(--r-chip)", padding: "1px 7px", pointerEvents: "auto" }}>
      Not filtered
    </span>
  );
}

/** A piece that cannot be read says so, in its place. */
export function Unread({ what, children }: { what: string; children: ReactNode }) {
  useMarkRead("refused", typeof children === "string" ? `${what}: ${children}` : what);
  return (
    <Frame testid="ontology-piece-unread" dashed>
      <div className="aug-fs-ui" style={{ color: "var(--t1)", fontWeight: 500 }}>{what}</div>
      <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>{children}</div>
    </Frame>
  );
}

/** What a piece holds between its title and its foot. On a section's grid it fills the box and scrolls when it holds
 *  more; off the grid it is as tall as what it holds, as before (Arc AP-1). */
export function Body({ children, gap = 6, testid }: { children: ReactNode; gap?: number; testid?: string }) {
  const box = useCellBox();
  return (
    <div data-testid={testid} style={{ display: "flex", flexDirection: "column", gap, minHeight: 0, ...(box.onGrid ? { flex: 1, overflow: "auto" } : {}) }}>
      {children}
    </div>
  );
}

export function Reading({ what }: { what: string }) {
  useMarkRead("reading");
  return (
    <Frame testid="ontology-piece-reading">
      <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Reading {what}…</div>
    </Frame>
  );
}

const words = (id: string) => id.replace(/[_-]+/g, " ");

// ── the process board ───────────────────────────────────────────────────────────────────────

export function ProcessBoardPiece({ process }: { process: string }) {
  const { processes, tables, onPlaceTable } = usePieces();
  const [found, setFound] = useState<ProcessDetail | null | undefined>(undefined);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    let alive = true;
    processes()
      .then(all => { if (alive) { setFound(all.processes.find(p => p.id === process) ?? null); setProblem(""); } })
      .catch(e => { if (alive) setProblem((e as Error).message); });
    return () => { alive = false; };
  }, [processes, process]);

  if (problem) return <Unread what="This process could not be read">{problem}</Unread>;
  if (found === undefined) return <Reading what="the process" />;
  if (found === null) {
    return <Unread what="Not a process here">The board names the process “{process}”, which this connection does not declare.</Unread>;
  }
  return (
    <Frame testid="process-board">
      <Title title={found.display_name || words(found.id)}
        right={<span className="aug-fs-xs" style={{ color: "var(--t3)", whiteSpace: "nowrap" }}>Process board</span>} />
      <Body>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.max(1, found.stages.length)}, minmax(0, 1fr))`, gap: 8 }}>
        {withUniqueKeys(found.stages, st => st.name).map(([k, stage]) => (
          <div key={k} data-testid="process-stage" style={{ background: "var(--bg-1)", borderRadius: "var(--r2)", padding: "8px 10px", minWidth: 0 }}>
            <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>{stage.display_name}</div>
            <div className="aug-fs-h2" style={{ color: "var(--t1)", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{formatCount(stage.reached)}</div>
            <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
              {stage.share != null ? pct(stage.share) : "—"}
              {stage.transition?.p50_days != null ? ` · p50 ${stage.transition.p50_days.toFixed(1)} d` : ""}
            </div>
          </div>
        ))}
      </div>
      {withUniqueKeys(found.stages.filter(s => s.promise), st => st.name).map(([k, stage]) => {
        const promise = stage.promise!;
        const segment = promise.overdue_segment ?? "";
        const table = tables.find(t => t.segment === segment);
        const terms = promise.kind === "deadline" ? `by ${words(promise.deadline)}`
          : promise.kind === "within_hours" ? `within ${promise.within_hours} hours` : `within ${promise.within_days} days`;
        return (
          <div key={k} data-testid="process-promise" className="aug-fs-sm"
            style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", borderTop: "1px solid var(--b1)", paddingTop: 8 }}>
            <span style={{ color: "var(--t2)", display: "inline-flex", alignItems: "center", gap: 6 }}>
              <Icon name="clock" size={13} /> {words(promise.name)}: {stage.display_name} {terms}
            </span>
            <span style={{ color: promise.breach_rate ? "var(--red3)" : "var(--t3)" }}>
              {promise.breach_rate != null ? `broken on ${pct(promise.breach_rate, 1)}` : "not measured"}
            </span>
            <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 6 }}>
              {promise.open_overdue == null ? null : table ? (
                <Button size="xs" variant="outline" data-testid="process-overdue"
                  title={`Show the table of these, as of ${promise.as_of}`}
                  onClick={() => document.querySelector(`[data-element="${table.key}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" })}>
                  {formatCount(promise.open_overdue)} open and overdue <Icon name="chevd" />
                </Button>
              ) : onPlaceTable && segment ? (
                <Button size="xs" variant="outline" data-testid="process-overdue-place"
                  title="Place a table of the objects still waiting and already past the promise"
                  onClick={() => onPlaceTable(promise.grain_id, segment)}>
                  {formatCount(promise.open_overdue)} open and overdue · add a table
                </Button>
              ) : (
                <span data-testid="process-overdue-count" style={{ color: "var(--t2)" }}>{formatCount(promise.open_overdue)} open and overdue</span>
              )}
            </span>
          </div>
        );
      })}
      {found.leaves && (
        <div className="aug-fs-xs" data-testid="process-leaves" style={{ color: "var(--t3)" }}>
          {found.leaves.left != null ? `${formatCount(found.leaves.left)} left the process` : "Objects leave the process"} when{" "}
          {found.leaves.property} is {found.leaves.values.join(" or ")} — they are not open, and never overdue
          {found.leaves.unknown ? `; ${formatCount(found.leaves.unknown)} hold no ${found.leaves.property} and are left out` : ""}
        </div>
      )}
      {found.counted_over && (
        <div className="aug-fs-xs" data-testid="process-counted-over" style={{ color: "var(--t3)", display: "flex", gap: 4 }}>
          <Icon name="lock" size={11} /> {found.counted_over}
        </div>
      )}
      </Body>
      <Foot icon="process">{found.measured_at ? `Measured ${formatDateTime(found.measured_at)}` : "Not measured yet"} · {found.entity_id}</Foot>
    </Frame>
  );
}

// ── the objects table ──────────────────────────────────────────────────────────────────────

/** A table row as drawn, and everything else a table's box holds — its padding, title, header row and foot: what the
 *  rows that fit are counted from (6 rows in 8 grades, 10 in 11, as measured on theLook 2026-10-10). */
const TABLE_ROW_PX = 29;
const TABLE_CHROME_PX = 110;

export function ObjectTablePiece({ elementKey, entity, segment, set, setFrom, chooses, ticks, columns, sort, descending, tall, marked }: {
  elementKey: string | null;
  entity?: string | null;
  segment?: string | null;
  /** Arc AP-2 — the set it lists, the set a figure shows in its stead, and the choices a click and a tick make. */
  set?: string | null;
  setFrom?: string | null;
  chooses?: string | null;
  ticks?: string | null;
  columns?: string[] | null;
  sort?: string | null;
  descending?: boolean | null;
  tall: boolean;
  /** the Grist study §10 — the rows a declared rule or segment admits, marked in its tone */
  marked?: Marked | null;
}) {
  const { connectionId, schema, tick, picked, pick, ticked, tickOne, tickNone, asGroup, say } = usePieces();
  const query = useSetQuery({ entity, segment, set, set_from: setFrom });
  const target = "entity" in query ? query : null;
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ObjectListingPage | null>(null);
  const [refused, setRefused] = useState("");
  // Arc AP-1 — on the grid, as many rows as the box holds, read from its height once a resize settles (a drag reads
  // once, not once a grade). Off the grid, six (twelve tall), as before.
  const box = useCellBox();
  const fits = box.onGrid ? Math.max(1, Math.floor((rowsTall(box.h) - TABLE_CHROME_PX) / TABLE_ROW_PX)) : null;
  const limit = useSettled(fits ?? (tall ? 12 : 6), 350);
  const asked = JSON.stringify([target?.entity, target?.segment, columns, sort, descending, target?.conditions]);
  useEffect(() => { setOffset(0); }, [asked]);
  // a list that waits on a choice, or cannot be read, holds nothing: what it listed before is let go of at once
  if (!target && page) setPage(null);
  useEffect(() => {
    if (!target) return;
    let alive = true;
    listObjects({ entity: target.entity, segment: target.segment, columns: columns ?? [], order_by: sort ?? "",
                  descending: !!descending, offset, limit, filters: target.conditions }, connectionId, schema, ...(asGroup ? [asGroup] : []))
      .then(out => {
        if (!alive) return;
        if (out.path === "refused") { setRefused(out.refused); setPage(null); return; }
        say(out.caveats);
        setRefused(out.error ?? ""); setPage(out);
      })
      .catch(e => { if (alive) setRefused((e as Error).message); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what the table asks
  }, [asked, offset, limit, connectionId, schema, tick, asGroup]);
  const marks = useMarked(target, marked, page?.key ?? "", page ? page.rows.map(r => String(r[0])) : []);

  if ("refused" in query) return <Unread what="This table cannot be read">{query.refused}</Unread>;
  if ("waiting" in query) {
    return (
      <Frame testid="object-table">
        <Title title={query.label || "Objects"} />
        <div className="aug-fs-sm" data-testid="object-table-waiting" style={{ color: "var(--t3)" }}>
          <WaitingWords choice={query.waiting} what={query.label} />
        </div>
      </Frame>
    );
  }
  if (refused && !page) return <Unread what="This table cannot be read">{refused}</Unread>;
  if (!page) return <Reading what="the objects" />;
  // the choice a click makes — named (Arc AP-2), or the table's own key as before — and the ticks it collects
  const choice = chooses || elementKey;
  const chosen = choice ? picked[choice] : undefined;
  const ticks_ = ticks ? ticked[ticks] ?? [] : [];
  const full = ticks_.length >= MAX_TICKED_RUNS;
  // the type as a person reads it — "Distribution center", never "DistributionCenter"
  const heading = query.label || `${typeWord(page.type_id)}${target?.segment ? ` · ${words(target.segment)}` : ""}`;
  const shown = page.rows.length;
  return (
    <Frame testid="object-table">
      <Title title={heading} right={<>
        {marked && <MarkLegend marked={marked} read={marks} total={page.total} />}
        <span className="aug-fs-xs" title={page.segment_said || undefined} data-testid="object-table-total"
          style={{ color: "var(--t3)", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
          {page.total == null ? "not counted" : formatCount(page.total)}
        </span></>} />
      <div style={{ overflowX: "auto", minHeight: 0, ...(box.onGrid ? { flex: 1, overflowY: "auto" } : {}) }}>
        <table className="aug-fs-sm" style={{ width: "100%", borderCollapse: "collapse", tableLayout: "auto" }}>
          <thead>
            <tr>
              {ticks && <th aria-label="Ticked" style={{ width: 22, borderBottom: "1px solid var(--b1)" }} />}
              {/* the key column headed by what each row is — "Order" — and the rest by their properties' names */}
              {withUniqueKeys([{ name: page.key, label: typeWord(page.type_id) || page.key, edited: false }, ...page.columns], c => c.name).map(([k, c]) => (
                <th key={k} style={{ textAlign: "type" in c && isNumericType(c.type) ? "right" : "left", fontWeight: 500, color: "var(--t3)", padding: "4px 8px 6px 0", borderBottom: "1px solid var(--b1)", whiteSpace: "nowrap" }}>
                  {c.edited && <Icon name="edit" size={11} label="Set by a declared action" />}
                  {"masked" in c && c.masked && <Icon name="lock" size={11} label="Masked for you — the note under the table says why" />}
                  {" "}{propertyLabel(c.label)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {/* keyed by each row's object key, made unique: an entity whose key is not unique lists one key twice */}
            {withUniqueKeys(page.rows, r => String(r[0])).map(([rowKey, row]) => {
              const pk = String(row[0]);
              const on = chosen?.pk === pk;
              const object = { objectType: page.object_type, typeId: page.type_id, pk };
              const isTicked = ticks_.some(t => t.pk === pk);
              const isMarked = !!marked && marks.on.has(pk);
              return (
                <tr key={rowKey} data-testid="object-table-row" aria-selected={on} data-marked={isMarked || undefined}
                  onClick={() => choice && pick(choice, on ? null : object)}
                  style={{ cursor: choice ? "pointer" : undefined, background: on ? "var(--bg-sel)" : undefined }}>
                  {ticks && (
                    <td onClick={e => e.stopPropagation()} style={{ padding: "5px 6px 5px 0", borderBottom: "1px solid var(--b1)" }}>
                      <Checkbox checked={isTicked} disabled={!isTicked && full} aria-label={`Tick ${pk}`}
                        onChange={e => tickOne(ticks, object, e.target.checked)} />
                    </td>
                  )}
                  {row.map((v, i) => {
                    // the key in mono; every other cell written as its column's type reads (a moment, a number)
                    const type = i > 0 ? page.columns[i - 1]?.type : "";
                    const col = i > 0 ? page.columns[i - 1] : undefined;
                    const text = cellText(v, type, undefined, col?.unit ?? "", col?.role ?? "");
                    const num = i > 0 && isNumericType(type);
                    return (
                      <td key={page.names[i] ?? i} className={i === 0 ? "aug-mono" : undefined} style={{
                        padding: i === 0 && marked ? "5px 8px 5px 8px" : "5px 8px 5px 0", borderBottom: "1px solid var(--b1)", whiteSpace: "nowrap",
                        boxShadow: i === 0 && isMarked && marked ? `inset 3px 0 0 ${MARK_TONE[marked.tone]}` : undefined,
                        textAlign: num ? "right" : undefined, color: text === "—" ? "var(--t3)" : "var(--t1)", fontVariantNumeric: "tabular-nums" }}>
                        {i > 0 && page.columns[i - 1]?.edited && text !== "—" && <Icon name="edit" size={11} label="Edited" />} {text}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        {shown === 0 && <div className="aug-fs-sm" style={{ color: "var(--t3)", padding: "8px 0" }}>No objects in this set.</div>}
        {/* what this reader does not see, and why — a row policy, a masked column — said, never implied (Arc OC-7) */}
        {page.caveats.length > 0 && (
          <div className="aug-fs-xs" data-testid="object-table-caveats" style={{ color: "var(--t3)", padding: "6px 0 0" }}>
            {page.caveats.map(c => <div key={c}>{c}</div>)}
          </div>
        )}
      </div>
      <Foot icon="table" aside={
        <span style={{ display: "inline-flex", gap: 4 }}>
          <AskAboutPiece query={query} ticked={ticks_} total={page.total} typeId={page.type_id} />
          <Button size="icon-xs" variant="ghost" aria-label="Previous page" disabled={offset === 0}
            onClick={() => setOffset(o => Math.max(0, o - limit))}><Icon name="chevl" /></Button>
          <Button size="icon-xs" variant="ghost" aria-label="Next page"
            disabled={page.total != null ? offset + shown >= page.total : shown < limit}
            onClick={() => setOffset(o => o + limit)}><Icon name="chevr" /></Button>
        </span>}>
        {shown ? `${formatCount(offset + 1)}–${formatCount(offset + shown)}` : "0"}{page.total != null ? ` of ${formatCount(page.total)}` : ""}
        {sort ? ` · by ${words(sort)}${descending ? ", highest first" : ""}` : ""}
        {ticks && ticks_.length > 0 && (
          <span data-testid="object-table-ticked">
            {" · "}{formatCount(ticks_.length)} ticked{full ? ` (the most one press runs on)` : ""}{" "}
            <Button size="xs" variant="ghost" onClick={() => tickNone(ticks)}>Clear</Button>
          </span>
        )}
      </Foot>
    </Frame>
  );
}

// ── the object detail and its actions ───────────────────────────────────────────────────────

/** The object a detail shows, to the action buttons it holds. */
const DetailObject = createContext<{ page: ObjectPage | null; table: string }>({ page: null, table: "" });

export function ObjectDetailPiece({ follows, children }: { follows: string; children?: ReactNode }) {
  const { connectionId, schema, picked, tick, followable, asGroup } = usePieces();
  const chosen = picked[followable.get(follows) ?? follows];
  const [page, setPage] = useState<ObjectPage | null>(null);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    if (!chosen) { setPage(null); setProblem(""); return; }
    let alive = true;
    getObjectPage(chosen.objectType, chosen.pk, connectionId, schema, ...(asGroup ? [asGroup] : []))
      .then(out => {
        if (!alive) return;
        if (out.path === "object") { setPage(out); setProblem(""); }
        else setProblem(out.path === "refused" ? out.refused : out.detail);
      })
      .catch(e => { if (alive) setProblem((e as Error).message); });
    return () => { alive = false; };
  }, [chosen?.objectType, chosen?.pk, connectionId, schema, tick, asGroup]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!followable.has(follows)) {
    return <Unread what="Follows nothing here">This detail follows “{follows}”, which no piece on this dashboard chooses in.</Unread>;
  }
  if (!chosen) {
    return (
      <Frame testid="object-detail">
        <Title title="Object detail" />
        <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Choose one to see it here.</div>
      </Frame>
    );
  }
  if (problem) return <Unread what="This object could not be read">{problem}</Unread>;
  if (!page || page.pk !== chosen.pk) return <Reading what={`${typeWord(chosen.typeId).toLowerCase()} ${chosen.pk}`} />;
  const key = page.key.toLowerCase();
  const props = [...page.properties.filter(p => p.name.toLowerCase() === key),
    ...page.properties.filter(p => p.name.toLowerCase() !== key && !p.overlay).slice(0, 7),
    ...page.properties.filter(p => p.overlay)];
  return (
    <Frame testid="object-detail">
      <Title title={page.title || `${page.type_name} ${page.pk}`} right={
        <Link className="aug-fs-xs" href={objectHref(page.object_type, page.pk, connectionId, schema)}
          style={{ color: "var(--blue3)", display: "inline-flex", alignItems: "center", gap: 4 }}>
          Open page <Icon name="external" size={11} />
        </Link>} />
      <Body>
      <dl style={{ display: "grid", gridTemplateColumns: "minmax(90px, max-content) minmax(0, 1fr)", columnGap: 12, rowGap: 4, margin: 0 }}>
        {withUniqueKeys(props, x => x.name).map(([k, p]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt className="aug-fs-xs" style={{ color: "var(--t3)", display: "flex", alignItems: "center", gap: 4 }}>
              {p.overlay && <Icon name="edit" size={11} label="Set by an accepted action" />}{propertyLabel(p.display_name, p.name)}
            </dt>
            <dd className="aug-fs-sm" data-testid={p.overlay ? "object-detail-edit" : undefined}
              style={{ margin: 0, overflowWrap: "anywhere", color: p.value == null ? "var(--t3)" : "var(--t1)" }}>
              {/* a value written as the table writes it: a moment as "Sep 28, 00:24", money as $25.00 */}
              {p.withheld ? <Masked why={p.withheld} /> : cellText(p.value, p.data_type || p.semantic_type, undefined, p.unit ?? "", p.semantic_type)}
              {p.overlay && (
                <span className="aug-fs-xs" style={{ display: "block", color: "var(--t3)" }}>
                  {p.overlay.provenance}{p.overlay.note ? ` — ${p.overlay.note}` : ""}
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {children && (
        <DetailObject.Provider value={{ page, table: follows }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>{children}</div>
        </DetailObject.Provider>
      )}
      </Body>
      <Foot icon="eye">Follows the choice · read live</Foot>
    </Frame>
  );
}

const word = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

/** What a press that ran says: "Done." alone when the action declares no check, else what its check found — a run
 *  whose check failed is never read as done. */
export function ranSaid(check?: ActionCheck): string {
  if (!check || check.status === "not_declared") return "Done.";
  if (check.status === "passed") return `Done — its check passed: ${check.why}.`;
  if (check.status === "failed") return `It ran, but its check failed: ${check.why}.`;
  // Arc OC-6 — its calls still in the outbox: the check waits for them to land
  if (check.status === "pending") return `Done — ${check.why}.`;
  // a call the outbox gave up on is not on its way — it is never "done"
  if (check.status === "waits_for_a_person") return `It ran, but ${check.why}.`;
  return `Done — its check could not be read: ${check.why}.`;
}

export function ActionButtonPiece({ action }: { action: string }) {
  const { connectionId, schema, bump, actions } = usePieces();
  const { page } = useContext(DetailObject);
  const [declared, setDeclared] = useState<DeclaredAction | null | undefined>(undefined);
  const [asking, setAsking] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  useEffect(() => {
    let alive = true;
    actions().then(all => { if (alive) setDeclared(all[action] ?? null); })
      .catch(() => { if (alive) setDeclared(null); });
    return () => { alive = false; };
  }, [actions, action]);
  useEffect(() => { setSaid(""); setAsking(false); }, [page?.pk]);

  if (declared === undefined || !page || !connectionId) return null;
  if (declared === null) {
    return <span className="aug-fs-xs" data-testid="action-button-missing" style={{ color: "var(--t3)" }}>The action “{action}” is not declared here.</span>;
  }
  const target = declared.params.find(p => p.kind === "object");
  const fits = !!target && [word(page.type_id), word(page.object_type)].includes(word(target.object_type));
  const asked = declared.params.filter(p => p.kind === "value" && p.required && p.default_value == null);
  const optional = declared.params.filter(p => p.kind === "value" && !(p.required && p.default_value == null));
  const label = declared.display_name || words(declared.id);

  const run = async () => {
    if (!target) return;
    setBusy(true);
    try {
      const params: Record<string, unknown> = { [target.name]: page.pk };
      for (const p of [...asked, ...optional]) if (values[p.name]?.trim()) params[p.name] = values[p.name].trim();
      // Arc OC-6 — the version of each property the action sets, as this detail read it (0: none set yet)
      const expected = Object.fromEntries((declared.edits ?? []).map(e => [e.property,
        page.properties.find(p => p.name.toLowerCase() === e.property.toLowerCase() && p.overlay)?.overlay?.version ?? 0]));
      const out = await runOrPropose(declared.id, params, connectionId, schema, `from a dashboard, on ${page.type_name} ${page.pk}`,
        Object.keys(expected).length ? expected : undefined);
      if (out.status === "ran") { setSaid(ranSaid(out.verification)); setAsking(false); setValues({}); bump(); }
      else if (out.status === "proposed") { setSaid("It needs approval — proposed in Actions."); setAsking(false); }
      else setSaid(out.message);
    } catch (e) {
      setSaid((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <span data-testid="action-button" style={{ display: "inline-flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      {asking ? (
        <>
          {withUniqueKeys([...asked, ...optional], x => x.name).map(([k, p]) => (
            <Input key={k} aria-label={p.display_name || p.name} placeholder={p.display_name || words(p.name)}
              value={values[p.name] ?? ""} onChange={e => setValues(v => ({ ...v, [p.name]: e.target.value }))}
              style={{ width: 160 }} />
          ))}
          <Button size="xs" disabled={busy || asked.some(p => !values[p.name]?.trim())} onClick={() => void run()}>
            <Icon name="bolt" /> {busy ? "Running…" : label}
          </Button>
          <Button size="xs" variant="ghost" disabled={busy} onClick={() => setAsking(false)}>Cancel</Button>
        </>
      ) : (
        <Button size="xs" variant="secondary" disabled={busy || !fits} aria-label={label}
          title={fits ? declared.description || `Run ${label} on this ${page.type_name}` : `${label} takes a ${target?.object_type || "different"} object`}
          onClick={() => ([...asked, ...optional].length ? setAsking(true) : void run())}>
          <Icon name="bolt" /> {busy ? "Running…" : label}
        </Button>
      )}
      {said && <span className="aug-fs-xs" data-testid="action-button-said" style={{ color: "var(--t2)" }}>{said}</span>}
    </span>
  );
}


// ── a dashboard started from an object: the filter column, a figure, a chart (2026-10-10) ─────────────────────

const num = (v: unknown): number | null => {
  const n = Number(v);
  return v === null || v === undefined || v === "" || Number.isNaN(n) ? null : n;
};

/** What its objects are called, lower case and plural ("orders"): the entity's name in the object catalog. */
export function useNoun(entity: string): string {
  const { connectionId } = usePieces();
  const [name, setName] = useState("");
  useEffect(() => {
    if (!connectionId) return;
    let alive = true;
    cachedObjectCatalog(connectionId)
      .then(c => {
        const t = c?.object_types.find(o => [o.object_type, o.id].some(n => n.toLowerCase() === entity.toLowerCase()));
        if (alive) setName(t?.display_name ?? "");
      })
      .catch(() => { /* the entity's own spelling stands */ });
    return () => { alive = false; };
  }, [connectionId, entity]);
  return plural(name || words(entity)).toLowerCase();
}

type Read = { rows: unknown[][]; caveats: string[] } | { refused: string } | null;

/** One object query, asked again when what it asks, the connection or the tick changes. Null asks nothing. */
function useObjectQuery(body: ObjectQueryRequest | null): Read {
  const { connectionId, schema, tick, asGroup, say } = usePieces();
  const [read, setRead] = useState<Read>(null);
  const asked = JSON.stringify(body);
  useEffect(() => {
    if (!body) { setRead(null); return; }
    let alive = true;
    queryObjects(body, connectionId, schema, ...(asGroup ? [asGroup] : []))
      .then(out => {
        if (!alive) return;
        if (out.path !== "refused") say(answerSays(out));   // Arc ED-6 — a read cut at the cap says so
        if (out.path === "refused") setRead({ refused: out.refused });
        else if (out.error) setRead({ refused: out.error });
        else setRead({ rows: out.rows, caveats: out.caveats ?? [] });
      })
      .catch(e => { if (alive) setRead({ refused: (e as Error).message }); });
    return () => { alive = false; };
  }, [asked, connectionId, schema, tick, asGroup]); // eslint-disable-line react-hooks/exhaustive-deps -- keyed on what it asks
  return read;
}

const COUNT = { name: "n", agg: "count" };

/** The small uppercase label a column or a card is headed by. */
export function Label({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="aug-fs-xs" style={{ display: "flex", alignItems: "baseline", gap: 6, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>
      {children}{right}
    </div>
  );
}

const Via = ({ what }: { what: string }) => (
  <span style={{ color: "var(--vio4)", textTransform: "none", letterSpacing: 0 }}>via {what}</span>
);

export interface FilterProperty { path: string; label: string; via?: string | null }

/** The filter column: each property's values, how many objects hold each, and a bar for it. A reader's click narrows
 *  every piece over the entity; each list is counted under the OTHER filters, never its own. */
export function ObjectFiltersPiece({ entity, properties, set }: { entity: string; properties: FilterProperty[]; set?: string | null }) {
  return (
    <aside data-testid="object-filters" aria-label="Filters" style={{
      background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "10px 12px",
      display: "flex", flexDirection: "column", gap: 14, alignSelf: "start", position: "sticky", top: 12,
    }}>
      {withUniqueKeys(properties, p => p.path).map(([k, p]) => <Facet key={k} entity={entity} prop={p} set={set} />)}
    </aside>
  );
}

/** What a filter column counts within (Arc AP-2): the set it names, read as every piece reads one — or none, and it
 *  counts every object of its entity as it did before sets. */
function useCountsWithin(set: string | null | undefined): { entity: string; segment: string; conditions: DoorCondition[]; label: string }
  | { refused: string } | null {
  const { wire, picked, valueOf } = usePieces();
  if (!set) return null;
  const r = readSet(wire, set, valueOf);
  if (isRefused(r)) return r;
  const read = doorConditions(r, c => picked[c]?.pk ?? null);
  if ("reading" in read) return { refused: "Reading the value its counts wait on…" };
  if ("waiting" in read) return { refused: `Its counts wait on the ${words(read.waiting)}.` };
  return { entity: r.entity, segment: r.segment, conditions: read.filters, label: r.label };
}

/** The values a list shows before "Show all", and the most it reads. */
const SHOWN = 6;
const MOST = 50;

function Facet({ entity, prop, set }: { entity: string; prop: FilterProperty; set?: string | null }) {
  const { filters, toggle } = usePieces();
  const [all, setAll] = useState(false);
  // within a set, its counts are of the set's objects ("China 480" of the waiting orders); else of every object — the
  // body asked before sets, key for key
  const within = useCountsWithin(set);
  const scoped = within && "entity" in within ? within : null;
  const read = useObjectQuery(within && "refused" in within ? null : scoped
    ? { object_type: scoped.entity, ...(scoped.segment ? { segment: scoped.segment } : {}), measures: [COUNT], by: [prop.path],
        filters: [...scoped.conditions, ...conditionsFor(filters, entity, prop.path)], order_by: "n", descending: true, limit: MOST + 1 }
    : { object_type: entity, measures: [COUNT], by: [prop.path],
        filters: conditionsFor(filters, entity, prop.path), order_by: "n", descending: true, limit: MOST + 1 });
  if (within && "refused" in within) {
    return (
      <div data-testid="object-facet">
        <Label right={prop.via ? <Via what={prop.via} /> : null}>{prop.label}</Label>
        <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 5 }}>{within.refused}</div>
      </div>
    );
  }
  const chosen = filters[entityKey(entity)]?.[prop.path] ?? [];
  const head = <Label right={prop.via ? <Via what={prop.via} /> : null}>{prop.label}</Label>;
  if (!read || "refused" in read) {
    return (
      <div data-testid="object-facet">
        {head}
        <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 5 }}>{read ? read.refused : "Reading…"}</div>
      </div>
    );
  }
  const rows = read.rows.slice(0, MOST).map(r => ({ value: r[0], n: num(r[1]) ?? 0 }));
  // a value chosen and now held by none under the other filters stays, so it can be unchosen
  for (const v of chosen) if (!rows.some(r => String(r.value) === v)) rows.push({ value: v, n: 0 });
  const shown = all ? rows : rows.filter((r, i) => i < SHOWN || chosen.includes(String(r.value)));
  const top = Math.max(1, ...rows.map(r => r.n));
  return (
    <div data-testid="object-facet" role="group" aria-label={prop.label}>
      {head}
      <div style={{ marginTop: 5 }}>
        {shown.map((r, i) => {
          const empty = r.value === null || r.value === undefined || r.value === "" || r.value === "NULL";
          const v = String(r.value);
          const on = chosen.includes(v);
          return (
            <label key={empty ? `empty-${i}` : `v-${v}`} data-testid="object-facet-row" data-on={on || undefined}
              title={empty ? "Objects with no value cannot be chosen" : undefined} className="aug-fs-sm"
              style={{ display: "grid", gridTemplateColumns: "16px minmax(0, 1fr) 52px 48px", alignItems: "center", gap: 7,
                padding: "3px 4px", borderRadius: "var(--r2)", cursor: empty ? "default" : "pointer",
                background: on ? "var(--bg-sel)" : undefined }}>
              <Checkbox checked={on} disabled={empty} aria-label={`${prop.label}: ${empty ? "no value" : v}`}
                onChange={() => toggle(entity, prop.path, v)} />
              <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: empty ? "var(--t3)" : "var(--t1)" }}>
                {empty ? "No value" : v}
              </span>
              <span style={{ textAlign: "right", color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>{formatCount(r.n)}</span>
              <span aria-hidden="true" style={{ height: 6, background: "var(--bg-4)", borderRadius: 3, overflow: "hidden" }}>
                <span style={{ display: "block", height: "100%", width: `${(r.n / top) * 100}%`, background: "var(--chart-1)" }} />
              </span>
            </label>
          );
        })}
      </div>
      {rows.length > SHOWN && (
        <Button size="xs" variant="ghost" style={{ marginTop: 2 }} onClick={() => setAll(a => !a)}>
          {all ? "Show fewer" : `Show all ${formatCount(rows.length)}`}
        </Button>
      )}
      {read.rows.length > MOST && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>The first {MOST} values, by how many objects hold each.</div>
      )}
    </div>
  );
}

/** Above the pieces a filter column narrows: what is chosen, a way out, and how many objects that leaves. */
// ── Arc AP-8 — the values a reader sets ─────────────────────────────────────────────────────

/** The most choices drawn side by side; more are a list to pick from. */
const SIDE_BY_SIDE = 6;
const valueText = (kind: string, v: unknown) => (v === null || v === undefined ? "" : kind === "number" && typeof v === "number" ? formatCount(v)
  : valueWords(kind, v));
/** A value as a box to type in holds it: never grouped, so it reads back as typed; a list with a comma between. */
const boxText = (v: unknown) => (v === null || v === undefined ? "" : Array.isArray(v) ? v.join(", ") : String(v));

/** The values a reader sets on the page, above its pieces: each a control of its own — the choices its author offers,
 *  or a box to type in — remembered in the reader's browser, never in the dashboard. Nothing when it offers none. */
export function ValuesBar({ spaced = true }: { spaced?: boolean }) {
  const { wire, valueOf, readerValues, setValue } = usePieces();
  const offered = Object.entries(wire.values ?? {}).filter(([, v]) => v.from?.by === "reader");
  if (!offered.length) return null;
  return (
    <div role="group" aria-label="Values you set" data-testid="dashboard-values" className="aug-fs-sm"
      style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap", marginBottom: spaced ? 14 : 0 }}>
      {offered.map(([name, def]) => {
        const now = valueOf(name);
        const value = "value" in now ? now.value : def.value ?? null;
        return (
          <ReaderValue key={name} name={name} label={def.label} kind={def.kind} value={value}
            options={def.from?.by === "reader" ? def.from.options ?? [] : []}
            changed={name in readerValues && JSON.stringify(value) !== JSON.stringify(def.value ?? null)} start={def.value ?? null}
            onSet={v => setValue(name, v)} onReset={() => setValue(name, undefined)} />
        );
      })}
    </div>
  );
}

function ReaderValue({ name, label, kind, value, options, changed, start, onSet, onReset }: {
  name: string; label: string; kind: string; value: unknown; options: (string | number)[]; changed: boolean; start: unknown;
  onSet: (v: unknown) => void; onReset: () => void;
}) {
  const [text, setText] = useState(boxText(value));
  const [shown, setShown] = useState(value);
  if (shown !== value) { setShown(value); setText(boxText(value)); }
  const [wrong, setWrong] = useState(false);
  const commit = () => {
    const v = typedValue(kind, text);
    if (v === null) { setWrong(true); return; }
    setWrong(false);
    if (JSON.stringify(v) !== JSON.stringify(value)) onSet(v);
  };
  const unit = kind === "days" ? "days" : "";
  // Arc AP-8c — yes or no is a switch of two; a list, the choices offered, any number of them ticked (one at least)
  const held = Array.isArray(value) ? value : [];
  const flip = (o: string | number) => {
    const next = held.some(x => x === o) ? held.filter(x => x !== o) : [...held, o];
    if (next.length) onSet(options.filter(x => next.some(n => n === x)));
  };
  const control = kind === "yesno" ? (
    <Segmented label={label} value={value === true ? "yes" : value === false ? "no" : ""}
      options={[{ value: "yes", label: "Yes" }, { value: "no", label: "No" }]} onChange={v => onSet(v === "yes")} />
  ) : kind === "list" && options.length ? (
    <span role="group" aria-label={label} style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
      {options.map(o => (
        <Button key={String(o)} size="xs" variant={held.some(x => x === o) ? "secondary" : "ghost"} aria-pressed={held.some(x => x === o)}
          disabled={held.length === 1 && held[0] === o} title={held.length === 1 && held[0] === o ? "A list holds one at least" : undefined}
          onClick={() => flip(o)}>{valueText("text", o)}</Button>
      ))}
    </span>
  ) : options.length && options.length <= SIDE_BY_SIDE ? (
    <Segmented label={label} value={options.some(o => o === value) ? String(value) : ""}
      options={options.map(o => ({ value: String(o), label: valueText(kind, o) }))}
      onChange={v => onSet(options.find(o => String(o) === v))} />
  ) : options.length ? (
    <SelectField aria-label={label} value={String(value ?? "")} onChange={e => onSet(options.find(o => String(o) === e.target.value))}>
      {options.map(o => <option key={String(o)} value={String(o)}>{valueText(kind, o)}</option>)}
    </SelectField>
  ) : (
    <Input aria-label={label} aria-invalid={wrong || undefined} value={text} onChange={e => { setText(e.target.value); setWrong(false); }}
      type={kind === "date" ? "date" : kind === "text" || kind === "list" ? "text" : "number"} inputMode={kind === "days" || kind === "number" ? "decimal" : undefined}
      onBlur={commit} onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") { setText(boxText(value)); setWrong(false); } }}
      style={{ width: kind === "text" || kind === "list" ? 160 : kind === "date" ? 150 : 90 }} />
  );
  return (
    <span data-testid="dashboard-value" data-name={name} style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span style={{ color: "var(--t3)" }}>{label}</span>
      {control}
      {unit && <span style={{ color: "var(--t3)" }}>{unit}</span>}
      {wrong && (
        <span className="aug-fs-xs" data-testid="dashboard-value-wrong" style={{ color: "var(--t2)" }}>
          {kind === "days" ? "A whole number of days, one or more." : kind === "number" ? "A number." : kind === "date" ? "A day."
            : kind === "list" ? "Items with a comma between, at most 30." : "Some words, at most 120."}
        </span>
      )}
      {changed && (
        <Button size="xs" variant="ghost" data-testid="dashboard-value-reset" title={`Back to ${valueText(kind, start)}${unit ? ` ${unit}` : ""}, as the dashboard was made`}
          onClick={onReset}>Reset</Button>
      )}
    </span>
  );
}

export function FilterBar({ entity, properties, set }: { entity: string; properties: FilterProperty[]; set?: string | null }) {
  const { filters, toggle, clear } = usePieces();
  const noun = useNoun(entity);
  const narrowed = conditionsFor(filters, entity);
  // within a set (Arc AP-2), how many of the set's objects the reader's filters leave — never every object ever
  const within = useCountsWithin(set);
  const scoped = within && "entity" in within ? within : null;
  const base = scoped ? { object_type: scoped.entity, ...(scoped.segment ? { segment: scoped.segment } : {}) } : { object_type: entity };
  const setConditions = scoped ? scoped.conditions : [];
  const some = useObjectQuery(narrowed.length && !(within && "refused" in within)
    ? { ...base, measures: [COUNT], filters: [...setConditions, ...narrowed] } : null);
  const every = useObjectQuery(within && "refused" in within ? null
    : scoped ? { ...base, measures: [COUNT], ...(setConditions.length ? { filters: setConditions } : {}) } : { object_type: entity, measures: [COUNT] });
  const total = every && "rows" in every ? num(every.rows[0]?.[0]) : null;
  const left = some && "rows" in some ? num(some.rows[0]?.[0]) : null;
  const chosen = Object.entries(filters[entityKey(entity)] ?? {}).filter(([, v]) => v.length);
  // a search box's words are held under the property marked (Arc AP-4): named by the property, said in quotes
  const label = (path: string) => { const bare = path.startsWith(WORDS) ? path.slice(WORDS.length) : path;
    return properties.find(p => p.path === bare)?.label ?? words(bare); };
  return (
    <div data-testid="object-filter-bar" className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", minHeight: 26 }}>
      {chosen.map(([path, values]) => (
        <span key={path} data-testid="object-filter-chip" style={{ display: "inline-flex", alignItems: "center", gap: 4,
          background: "var(--bg-sel)", color: "var(--accent-text)", padding: "2px 4px 2px 9px", borderRadius: "var(--r-pill)" }}>
          {label(path)}: {path.startsWith(WORDS) ? `“${values[0]}”` : values.join(", ")}
          <Button size="icon-xs" variant="ghost" aria-label={`Clear ${label(path)}`}
            onClick={() => values.forEach(v => toggle(entity, path, v))}><Icon name="close" size={11} /></Button>
        </span>
      ))}
      {chosen.length > 0 && <Button size="xs" variant="ghost" onClick={() => clear(entity)}>Clear</Button>}
      <span data-testid="object-filter-count" style={{ marginLeft: "auto", color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>
        {within && "refused" in within ? within.refused
          : scoped ? (narrowed.length
            ? `${left == null ? "…" : formatCount(left)} of ${total == null ? "…" : formatCount(total)} in “${scoped.label}”`
            : `${total == null ? "…" : formatCount(total)} in “${scoped.label}”`)
          : narrowed.length
            ? `${left == null ? "…" : formatCount(left)} of ${total == null ? "…" : formatCount(total)} ${noun}`
            : `${total == null ? "…" : formatCount(total)} ${noun}`}
      </span>
    </div>
  );
}

/** One figure over an entity's objects, narrowed by the reader's filters, and said beside the whole. */
export function ObjectFigurePiece({ entity, set, of, shows, label, agg, path, format, sym }: {
  entity?: string | null; label: string; agg: string; path?: string | null; format?: string | null; sym: string;
  /** Arc AP-2 — the set it measures, the set it is said beside, and the choice a click shows its set in. */
  set?: string | null; of?: string | null; shows?: string | null;
}) {
  const { shown, show, wire } = usePieces();
  const { onGrid } = useCellBox();
  const measure = { name: "v", agg, path: path ?? "" };
  const query = useSetQuery({ entity, set });
  const whole = useSetQuery({ entity, set }, { reader: false });
  const besideSet = useSetQuery(of ? { set: of } : { entity: "" });
  const target = "entity" in query ? query : null;
  const noun = useNoun(target?.entity ?? entity ?? "");
  const body = (q: SetQuery): ObjectQueryRequest | null => ("entity" in q && q.entity
    ? { object_type: q.entity, measures: [measure], ...(q.segment ? { segment: q.segment } : {}), ...(q.conditions.length ? { filters: q.conditions } : {}) }
    : null);
  const value = useObjectQuery(body(query));
  // said beside it: the same measure over the set the author named — "of 6,788 placed" — or, with none named, over the
  // whole of its own set while a reader's filters narrow it, as a figure did before sets
  const beside = useObjectQuery(of ? body(besideSet) : target?.narrowed ? body(whole) : null);
  // a figure that switches a list is lit while its set is the one the table shows — the table's own set before a click
  const shownSet = shows ? shown[shows] ?? String(Object.values(wire.elements).find(el => el?.type === "ObjectTable"
    && el.props?.set_from === shows)?.props?.set ?? "") : "";
  const lit = !!shows && !!set && shownSet === set;
  if ("refused" in query) return <Unread what={`${label} cannot be read`}>{query.refused}</Unread>;
  if (value && "refused" in value) return <Unread what={`${label} cannot be read`}>{value.refused}</Unread>;
  const v = value && "rows" in value ? num(value.rows[0]?.[0]) : null;
  const w = beside && "rows" in beside ? num(beside.rows[0]?.[0]) : null;
  const text = (x: number | null) => figureText(x, agg, format, sym);
  const besideWords = "waiting" in query ? `once ${words(query.waiting)} is chosen`
    : of ? (beside ? `of ${text(w)} ${("label" in besideSet && besideSet.label ? besideSet.label : words(of)).toLowerCase()}` : "")
      : !target?.narrowed ? "" : agg === "count" || agg === "count_distinct" || agg === "sum" ? `of ${text(w)}` : `all ${noun} ${text(w)}`;
  return (
    <Frame testid="object-figure">
      <div role={shows ? "button" : undefined} aria-pressed={shows ? lit : undefined} tabIndex={shows ? 0 : undefined}
        data-testid={shows ? "object-figure-shows" : undefined}
        title={shows ? `Show ${label} in the list` : undefined}
        onClick={shows && set ? () => show(shows, set) : undefined}
        onKeyDown={shows && set ? e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); show(shows, set); } } : undefined}
        style={{ display: "flex", flexDirection: "column", gap: 6, cursor: shows ? "pointer" : undefined, borderRadius: "var(--r2)",
          boxShadow: lit ? "inset 0 -2px 0 var(--accent)" : undefined, ...(onGrid ? { flex: 1, justifyContent: "center", minHeight: 0 } : {}) }}>
        <div className="aug-fs-xs" style={{ color: lit ? "var(--t1)" : "var(--t3)" }}>{label}</div>
        <div className="aug-fs-display" data-testid="object-figure-value"
          style={{ color: "var(--t1)", fontWeight: 600, fontVariantNumeric: "tabular-nums", lineHeight: 1.2 }}>
          {"waiting" in query ? "—" : value ? text(v) : "…"}
        </div>
        <div className="aug-fs-xs" data-testid="object-figure-whole" style={{ color: "var(--t3)", minHeight: 16 }}>{besideWords}</div>
      </div>
    </Frame>
  );
}

/** The most groups a breakdown reads; past them, Other is asked of the door rather than folded from what was read. */
const BREAKDOWN_READ = 1000;
/** A breakdown's groups when it says none. */
export const BREAKDOWN_TOP = 8;

/** An entity's objects grouped by one property (the Grist study §10): the largest groups first, the rest as one Other
 *  row, those with no value as their own row — so the rows hold every object, and the line beneath says whether they
 *  add up to the whole. A click on a group is the filter column's click: it narrows every piece over the entity, while
 *  this one, counted under the OTHER filters, keeps every group and ticks the chosen. Other and No value are not
 *  chosen — a filter of one value cannot hold them yet. */
export function ObjectBreakdownPiece({ entity, set, label, by, measures, top, show, sym = "$" }: {
  entity?: string | null; set?: string | null; label: string; by: string; measures: BreakdownMeasure[];
  top?: number | null; show?: string | null; sym?: string;
}) {
  const { filters, toggle } = usePieces();
  // its set without the reader's filters, then those filters but its own — choosing a group never hides the rest
  const base = useSetQuery({ entity, set }, { reader: false });
  const scoped = "entity" in base ? base : null;
  const noun = useNoun(scoped?.entity ?? entity ?? "");
  const conditions = scoped ? [...scoped.conditions, ...(conditionsFor(filters, scoped.entity, by) as unknown as DoorCondition[])] : [];
  const ms = measures.map((m, i) => ({ name: `m${i}`, agg: m.agg, path: m.path ?? "" }));
  const scope = scoped ? { object_type: scoped.entity, ...(scoped.segment ? { segment: scoped.segment } : {}) } : null;
  const n = top ?? BREAKDOWN_TOP;
  const read = useObjectQuery(scope ? { ...scope, ...(conditions.length ? { filters: conditions } : {}), measures: ms,
    by: [by], order_by: "m0", descending: true, limit: BREAKDOWN_READ } : null);
  const whole = useObjectQuery(scope ? { ...scope, ...(conditions.length ? { filters: conditions } : {}), measures: ms } : null);
  const rows = read && "rows" in read ? read.rows : [];
  const complete = rows.length < BREAKDOWN_READ;
  const shownValues = rows.filter(r => !(r[0] === null || r[0] === undefined || r[0] === "" || r[0] === "NULL"))
    .slice(0, n).map(r => String(r[0]));
  const valued = rows.filter(r => !(r[0] === null || r[0] === undefined || r[0] === "" || r[0] === "NULL")).length;
  // Other's measures that do not add up — or all of Other, when the groups read are not all there are — from the door
  const askOther = !!scope && !!read && "rows" in read && (valued > n || !complete)
    && (!complete || measures.some(m => !additive(m.agg)));
  const otherRead = useObjectQuery(askOther && scope ? { ...scope, measures: ms,
    filters: [...conditions, { path: by, op: "not_in", values: shownValues } as unknown as DoorCondition] } : null);
  const { label: byLabel, via } = pathWords(by);
  const groupNoun = plural(byLabel.toLowerCase());
  const chosen = scoped ? filters[entityKey(scoped.entity)]?.[by] ?? [] : [];
  if ("refused" in base) return <Unread what={`${label} cannot be read`}>{base.refused}</Unread>;
  if ("waiting" in base) return <Unread what={label}><WaitingWords choice={base.waiting} what={label} /></Unread>;
  for (const r of [read, whole, otherRead]) if (r && "refused" in r) return <Unread what={`${label} cannot be read`}>{r.refused}</Unread>;
  if (!read || !whole || (askOther && !otherRead)) return <Reading what={label.toLowerCase()} />;
  const other = otherRead && "rows" in otherRead ? measures.map((_, i) => num(otherRead.rows[0]?.[i])) : null;
  const folded = foldBreakdown(rows, n, measures, other, complete);
  const all = measures.map((_, i) => ("rows" in whole ? num(whole.rows[0]?.[i]) : null));
  const gaps = breakdownGaps(folded, all, measures);
  const word = (m: BreakdownMeasure, i: number) => m.label || (m.agg === "count" ? propertyLabel(noun)
    : `${AGG_WORDS[m.agg] ?? m.agg} ${pathWords(m.path ?? "").label.toLowerCase()}`) || `Measure ${i + 1}`;
  const text = (v: number | null, i: number) => figureText(v, measures[i].agg, measures[i].format, sym);
  // the share a row is of the whole: of the first sum, else of the count — none when nothing adds up
  const shareAt = Math.max(measures.findIndex(m => m.agg === "sum"), measures.findIndex(m => m.agg === "count"));
  const share = (r: (typeof folded)[number]) => (shareAt >= 0 && all[shareAt] ? (r.values[shareAt] ?? 0) / (all[shareAt] as number) : null);
  const most = Math.max(1e-9, ...folded.map(r => Math.abs(r.values[0] ?? 0)));
  const name = (r: (typeof folded)[number]) => (r.kind === "group" ? r.value : r.kind === "other"
    ? `Other · ${formatCount(r.groups)} ${r.groups === 1 ? byLabel.toLowerCase() : groupNoun}` : "No value");
  const groups = rows.filter(r => !(r[0] === null || r[0] === undefined || r[0] === "" || r[0] === "NULL")).length;
  const counted = measures.map((m, i) => (additive(m.agg) ? text(all[i], i) : "")).filter(Boolean);
  const foot = gaps.length
    ? `The groups hold ${text(folded.reduce((s, r) => s + (r.values[gaps[0]] ?? 0), 0), gaps[0])} of ${text(all[gaps[0]], gaps[0])} — `
      + "some objects are in no row."
    : `${complete ? formatCount(groups) : `More than ${formatCount(groups)}`} ${groups === 1 ? byLabel.toLowerCase() : groupNoun}`
      + `${counted.length ? ` · ${counted.join(" · ")}` : ""}${measures.some(m => additive(m.agg)) ? ` — every ${noun.replace(/s$/, "")} is in one row.` : "."}`;
  const pick = (r: (typeof folded)[number]) => (r.kind === "group" && scoped ? () => toggle(scoped.entity, by, r.value) : undefined);
  const why = (r: (typeof folded)[number]) => (r.kind === "other" ? "Other cannot be chosen — choose its groups in a filter column"
    : r.kind === "none" ? "Objects with no value cannot be chosen" : chosen.includes(r.value) ? `Let go of ${r.value}` : `Narrow the dashboard to ${r.value}`);
  return (
    <Frame testid="object-breakdown">
      <Title title={label} right={<>
        {via && <Via what={via} />}
        <TableActions name={label} read={() => ({
          columns: [byLabel, ...measures.map(word), ...(shareAt >= 0 ? ["Share"] : [])],
          rows: folded.map(r => [name(r), ...r.values.map(v => v ?? ""), ...(shareAt >= 0 ? [share(r) ?? ""] : [])]),
        })} />
      </>} />
      <Body testid="object-breakdown-rows">
        {show === "bars" ? folded.map(r => {
          const on = r.kind === "group" && chosen.includes(r.value);
          return (
            <div key={`${r.kind}:${r.value}`} data-testid="object-breakdown-row" data-on={on || undefined} title={why(r)}
              role={r.kind === "group" ? "button" : undefined} tabIndex={r.kind === "group" ? 0 : undefined} aria-pressed={r.kind === "group" ? on : undefined}
              onClick={pick(r)} onKeyDown={e => { if ((e.key === "Enter" || e.key === " ") && pick(r)) { e.preventDefault(); pick(r)?.(); } }}
              className="aug-fs-sm" style={{ display: "grid", gridTemplateColumns: "minmax(0, 120px) minmax(0, 1fr) auto", alignItems: "center",
                gap: 8, padding: "3px 4px", borderRadius: "var(--r2)", cursor: r.kind === "group" ? "pointer" : "default",
                background: on ? "var(--bg-sel)" : undefined }}>
              <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: r.kind === "group" ? "var(--t1)" : "var(--t3)" }}>
                {on ? "✓ " : ""}{name(r)}
              </span>
              <span aria-hidden="true" style={{ height: 10, background: "var(--bg-4)", borderRadius: 3, overflow: "hidden" }}>
                <span style={{ display: "block", height: "100%", width: `${(Math.abs(r.values[0] ?? 0) / most) * 100}%`,
                  background: r.kind === "group" ? "var(--chart-1)" : "var(--chart-deemph)" }} />
              </span>
              <span style={{ textAlign: "right", color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>{text(r.values[0], 0)}</span>
            </div>
          );
        }) : (
          <table className="aug-fs-sm" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr className="aug-fs-xs" style={{ color: "var(--t3)", textAlign: "left" }}>
                <th style={{ padding: "4px 6px", fontWeight: 500 }}>{byLabel}</th>
                {measures.map((m, i) => <th key={`m${i}`} style={{ padding: "4px 6px", fontWeight: 500, textAlign: "right" }}>{word(m, i)}</th>)}
                {shareAt >= 0 && <th style={{ padding: "4px 6px", fontWeight: 500 }}>Share of {word(measures[shareAt], shareAt).toLowerCase()}</th>}
              </tr>
            </thead>
            <tbody>
              {folded.map(r => {
                const on = r.kind === "group" && chosen.includes(r.value);
                const s = share(r);
                return (
                  <tr key={`${r.kind}:${r.value}`} data-testid="object-breakdown-row" data-on={on || undefined} title={why(r)}
                    tabIndex={r.kind === "group" ? 0 : undefined} aria-selected={r.kind === "group" ? on : undefined}
                    onClick={pick(r)} onKeyDown={e => { if ((e.key === "Enter" || e.key === " ") && pick(r)) { e.preventDefault(); pick(r)?.(); } }}
                    style={{ borderTop: "1px solid var(--b0)", cursor: r.kind === "group" ? "pointer" : "default",
                      background: on ? "var(--bg-sel)" : undefined, color: r.kind === "group" ? "var(--t1)" : "var(--t3)" }}>
                    <td style={{ padding: "4px 6px", whiteSpace: "nowrap", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {on ? "✓ " : ""}{name(r)}
                    </td>
                    {r.values.map((v, i) => (
                      <td key={`m${i}`} style={{ padding: "4px 6px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{text(v, i)}</td>
                    ))}
                    {shareAt >= 0 && (
                      <td style={{ padding: "4px 6px", minWidth: 120 }}>
                        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span aria-hidden="true" style={{ flex: 1, height: 6, background: "var(--bg-4)", borderRadius: 3, overflow: "hidden" }}>
                            <span style={{ display: "block", height: "100%", width: `${Math.max(0, Math.min(1, s ?? 0)) * 100}%`,
                              background: r.kind === "group" ? "var(--chart-1)" : "var(--chart-deemph)" }} />
                          </span>
                          <span style={{ color: "var(--t2)", fontVariantNumeric: "tabular-nums", minWidth: 42, textAlign: "right" }}>
                            {s === null ? "—" : pct(s, 1)}
                          </span>
                        </span>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Body>
      <div className="aug-fs-xs" data-testid="object-breakdown-foot" style={{ color: gaps.length ? "var(--amb4)" : "var(--t3)", paddingTop: 4 }}>
        {foot}
      </div>
      {chosen.length > 0 && (
        <div className="aug-fs-xs" data-testid="object-breakdown-chosen" style={{ color: "var(--t2)" }}>
          Chosen: {chosen.join(", ")} — click {chosen.length === 1 ? "it" : "one"} again to let go.
        </div>
      )}
    </Frame>
  );
}

const AGG_WORDS: Record<string, string> = {
  sum: "Sum of", avg: "Average", min: "Least", max: "Most", count_distinct: "Distinct",
};

/** A table's or a list's rows marked by a declared rule or segment (the Grist study §10). */
export interface Marked { segment: string; tone: "good" | "warn" | "bad" | "info" | "neutral"; label?: string | null }

/** A mark's colour, as a card's rule is drawn. */
export const MARK_TONE: Record<Marked["tone"], string> = {
  good: "var(--grn3)", warn: "var(--amb3)", bad: "var(--red3)", info: "var(--blue3)", neutral: "var(--b2)",
};

/** Which of the keys on screen a mark admits, and how many of the listing's objects it marks — both read through the
 *  door as `in_set`, a set of the listing's own entity kept to the declared segment. Nothing a dashboard marks by is a
 *  formula of its own: a mark names what the ontology declares, or it is refused at the keep. */
export function useMarked(target: { entity: string; segment: string; conditions: DoorCondition[] } | null,
  marked: Marked | null | undefined, keyPath: string, keys: string[]): { on: Set<string>; count: number | null; refused: string } {
  const { connectionId, schema, asGroup } = usePieces();
  const inSet = target && marked
    ? ({ path: "", op: "in_set", sets: [{ entity: target.entity, segment: marked.segment }] } as unknown as DoorCondition) : null;
  const counted = useObjectQuery(inSet && target ? { object_type: target.entity, ...(target.segment ? { segment: target.segment } : {}),
    measures: [COUNT], filters: [...target.conditions, inSet] } : null);
  const [on, setOn] = useState<Set<string>>(() => new Set());
  const [refused, setRefused] = useState("");
  const asked = JSON.stringify([target?.entity, target?.segment, target?.conditions, marked?.segment, keyPath, keys]);
  useEffect(() => {
    if (!target || !inSet || !keyPath || !keys.length) { setOn(new Set()); return; }
    let alive = true;
    listObjects({ entity: target.entity, segment: target.segment, columns: [], offset: 0, limit: keys.length,
                  filters: [...target.conditions, inSet, { path: keyPath, op: "in", values: keys } as unknown as DoorCondition] },
                connectionId, schema, ...(asGroup ? [asGroup] : []))
      .then(out => {
        if (!alive) return;
        if (out.path === "refused") { setRefused(out.refused); setOn(new Set()); return; }
        setRefused(out.error ?? "");
        setOn(new Set(out.rows.map(r => String(r[0]))));
      })
      .catch(e => { if (alive) setRefused((e as Error).message); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what it asks
  }, [asked, connectionId, schema, asGroup]);
  return { on, count: counted && "rows" in counted ? num(counted.rows[0]?.[0]) : null,
    refused: counted && "refused" in counted ? counted.refused : refused };
}

/** What a mark means and how many it marks, beside the piece's title: "● Late dispatch — 1,275 of 6,366". A mark that
 *  cannot be read says so in its place. */
export function MarkLegend({ marked, read, total }: { marked: Marked; read: ReturnType<typeof useMarked>; total: number | null }) {
  const name = marked.label || words(marked.segment).replace(/^./, c => c.toUpperCase());
  return (
    <span className="aug-fs-xs" data-testid="object-mark-legend" title={read.refused || `Rows ${name} admits are marked`}
      style={{ display: "inline-flex", alignItems: "center", gap: 5, color: read.refused ? "var(--amb4)" : "var(--t2)", whiteSpace: "nowrap" }}>
      <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2, background: MARK_TONE[marked.tone] }} />
      {read.refused ? `${name} cannot be marked` : `${name} — ${read.count == null ? "…" : formatCount(read.count)}`
        + `${total != null && read.count != null ? ` of ${formatCount(total)}` : ""}`}
    </span>
  );
}

// the chart's frame in px, drawn at the size its card gives it (Arc AP-1): off the grid at the mockup's shape, 640 × 210
// scaled to the card's width; on the grid at the box's own width and height — its text always at its own size
const W = 640, H = 210, LEFT = 40, TOP = 26, PAD_RIGHT = 8, PAD_BOTTOM = 26;
/** A split's colours in the order its values are drawn — the six series, then Other in the fold's grey (Arc AP-1). */
const SERIES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--chart-6)"];
const OTHER = "var(--chart-deemph)";
/** The values a split draws when its chart says none. */
export const SPLIT_TOP = 5;
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

/** An entity's objects per day over its last whole days: the reader's filtered objects as bars, all of them as a
 *  line behind — or, with no filter on, all of them as bars. A bar may measure an aggregate of a property instead of a
 *  count, and be split by a property: its most common values stacked in fixed colours, the rest as Other (Arc AP-1).
 *  Each bar says its day and what it holds when pointed at. */
export function ObjectChartPiece({ entity, set, label, time, days, agg, path, format, split, top, sym = "$" }: {
  entity?: string | null; label: string; time: string; days: number;
  agg?: string | null; path?: string | null; format?: string | null; split?: string | null; top?: number | null; sym?: string;
  /** Arc AP-2 — the set it draws, in place of every object of an entity. */
  set?: string | null;
}) {
  const { filters } = usePieces();
  const box = useCellBox();
  const [plot, room] = useMeasured<HTMLDivElement>();
  const width = room.width || W;
  const height = box.onGrid ? Math.max(120, room.height || H) : Math.round((width * H) / W);
  const RIGHT = width - PAD_RIGHT, BASE = height - PAD_BOTTOM;
  // its set, as a reader's filters leave it, and the whole of it behind — every object of its entity, before sets
  const query = useSetQuery({ entity, set });
  const whole = useSetQuery({ entity, set }, { reader: false });
  const base = "entity" in whole ? whole : null;
  const narrowedBy = "entity" in query && query.narrowed ? query : null;
  const ent = base?.entity ?? entity ?? "";
  const noun = useNoun(ent);
  const how = agg || "count";
  const by = split ? [split] : [];
  const scope = (q: { entity: string; segment: string }) => ({ object_type: q.entity, ...(q.segment ? { segment: q.segment } : {}) });
  // a set that counts its own last days on the chart's date is drawn over exactly those days, today included; else the
  // window ends where the objects stop (Arc AP-2)
  const fixed = base ? inLastWindow(base.conditions, time) : null;
  const last = useObjectQuery(base && !fixed ? { ...scope(base), measures: [{ name: "t", agg: "max", path: time }],
    ...(base.conditions.length ? { filters: base.conditions } : {}) } : null);
  const end = fixed ? fixed.end : last && "rows" in last ? windowEnd(String(last.rows[0]?.[0] ?? "")) : "";
  const span = fixed?.days ?? days;
  const window = end ? daysBefore(end, span) : [];
  const per = (q: { entity: string; segment: string; conditions: DoorCondition[] }): ObjectQueryRequest | null => end ? {
    ...scope(q), measures: [{ name: "n", agg: how, path: path ?? "" }], time, grain: "day", start: window[0], end,
    filters: q.conditions, ...(by.length ? { by } : {}) } : null;
  const every = useObjectQuery(base ? per(base) : null);
  const some = useObjectQuery(narrowedBy ? per(narrowedBy) : null);
  const narrowed = narrowedBy ? narrowedBy.conditions : [];
  const [hover, setHover] = useState<number | null>(null);
  const failed = [last, every, some].find(r => r && "refused" in r) as { refused: string } | undefined;
  if ("refused" in query) return <Unread what={`${label} cannot be read`}>{query.refused}</Unread>;
  if ("waiting" in query) {
    return (
      <Frame testid="object-chart">
        <div className="aug-fs-chrome" style={{ color: "var(--t1)", fontWeight: 500 }}>{label}</div>
        <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Choose one in {words(query.waiting)} to see it here.</div>
      </Frame>
    );
  }
  if (failed) return <Unread what={`${label} cannot be read`}>{failed.refused}</Unread>;
  const everyRows = every && "rows" in every ? every.rows : null;
  const someRows = narrowed.length ? (some && "rows" in some ? some.rows : null) : everyRows;
  // the values a split draws come from every object, so each keeps its colour while the reader narrows
  const values = split && everyRows ? topValues(everyRows, top ?? SPLIT_TOP) : [];
  const stacksOf = (rows: unknown[][]) => (split ? splitOnDays(window, rows, values) : onDays(window, rows).map(v => [v]));
  const allStacks = everyRows ? stacksOf(everyRows) : null;
  const stacks = someRows ? stacksOf(someRows) : null;
  const text = (v: number) => (how === "count" ? `${formatCount(v)} ${noun}` : figureText(v, how, format, sym));
  const tick = (v: number) => (how === "count" || how === "count_distinct" ? formatCount(v) : figureText(v, how, format, sym));
  const others = !!stacks && stacks.some(st => (st[values.length] ?? 0) > 0) && !!split;
  const swatch = (color: string) => <i style={{ width: 10, height: 10, borderRadius: 2, background: color, display: "inline-block" }} />;
  const head = (
    <div style={{ display: "flex", alignItems: "center", gap: 10, fontWeight: 500, flexWrap: "wrap" }} className="aug-fs-chrome">
      <span style={{ color: "var(--t1)" }}>{label} · last {span} days</span>
      {(narrowed.length > 0 || values.length > 0) && (
        <span className="aug-fs-xs" data-testid="object-chart-legend" style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 6, color: "var(--t2)", fontWeight: 400, flexWrap: "wrap" }}>
          {split
            ? <>{values.map((v, j) => <span key={v} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>{swatch(SERIES[j])}{v}</span>)}
              {others && <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>{swatch(OTHER)}Other</span>}</>
            : <>{swatch("var(--chart-1)")}{chosenWords(filters, ent)}</>}
          {narrowed.length > 0 && <><i style={{ width: 14, height: 2, background: "var(--chart-deemph)", display: "inline-block", marginLeft: 8 }} />All {noun}</>}
        </span>
      )}
    </div>
  );
  if (!stacks || !allStacks) {
    return (
      <Frame testid="object-chart">{head}
        <div ref={plot} className="aug-fs-sm" style={{ color: "var(--t3)", ...(box.onGrid ? { flex: 1, minHeight: 0 } : {}) }}>Reading…</div>
      </Frame>
    );
  }
  const all = allStacks.map(sum);
  const bars = stacks.map(sum);
  const axis = ticks(Math.max(1, ...all, ...bars));
  const topOfAxis = axis[axis.length - 1] || 1;
  const y = (v: number) => BASE - (v / topOfAxis) * (BASE - TOP);
  const slot = (RIGHT - LEFT) / window.length;
  const bw = Math.max(2, slot - 2);
  const x = (i: number) => LEFT + i * slot + 1;
  const mid = (i: number) => x(i) + bw / 2;
  const r = Math.min(2.5, bw / 2);
  // one segment of a bar, from `from` up to `to`: the top of a bar is rounded, a segment under another leaves a 1 px gap
  const segment = (i: number, from: number, to: number, topmost: boolean) => {
    const t = y(to), b = y(from) - (from > 0 ? 1 : 0), l = x(i), w = bw;
    if (b - t < 1) return "";
    if (!topmost || b - t < r) return `M${l},${b} V${t} H${l + w} V${b} Z`;
    return `M${l},${b} V${t + r} Q${l},${t} ${l + r},${t} H${l + w - r} Q${l + w},${t} ${l + w},${t + r} V${b} Z`;
  };
  const colours = split ? [...SERIES.slice(0, values.length), OTHER] : ["var(--chart-1)"];
  const lastI = window.length - 1;
  // the label marks the latest day that holds any — a set of what waits past a 2-day promise holds none from the last
  // two days, and "0" at the end would say nothing (scenario on theLook, 2026-10-11) — and says its day when not the last
  const series = narrowed.length ? all : bars;
  let endI = lastI;
  while (endI > 0 && !series[endI]) endI--;
  const lineEnd = series[endI] ?? 0;
  const endSaid = endI === lastI ? text(lineEnd) : `${text(lineEnd)} on ${dayLabel(window[endI])}`;
  const said = (i: number) => {
    const day = dayLabel(window[i]);
    const parts = split ? stacks[i].map((v, j) => (v > 0 ? `${j < values.length ? values[j] : "Other"} ${tick(v)}` : "")).filter(Boolean) : [];
    const what = narrowed.length ? `${text(bars[i])} ${chosenWords(filters, ent)} of ${text(all[i])}` : text(bars[i]);
    return `${day}: ${what}${parts.length ? ` — ${parts.join(" · ")}` : ""}`;
  };
  return (
    <Frame testid="object-chart">
      {head}
      <div ref={plot} style={{ position: "relative", overflow: "hidden", ...(box.onGrid ? { flex: 1, minHeight: 0 } : {}) }}
        onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" data-testid="object-chart-svg"
          style={box.onGrid ? { position: "absolute", left: 0, top: 0 } : { display: "block" }}
          aria-label={`${label}, last ${span} days${split ? `, split by its ${values.length} most common values` : ""}${narrowed.length ? `: ${chosenWords(filters, ent)} as bars, all ${noun} as a line` : ""}`}>
          {axis.map(t => (
            <g key={t}>
              <line x1={LEFT} x2={RIGHT} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" />
              <text x={LEFT - 6} y={y(t) + 3} textAnchor="end" fill="var(--chart-tick)" style={{ font: "10px Inter, system-ui, sans-serif" }}>{tick(t)}</text>
            </g>
          ))}
          {stacks.map((st, i) => {
            const topJ = st.reduce((k, v, j) => (v > 0 ? j : k), -1);
            let at = 0;
            return (
              <g key={window[i]} data-testid="object-chart-bar">
                <g opacity={hover === null || hover === i ? 1 : 0.55}>
                  {st.map((v, j) => {
                    const from = at;
                    at += v;
                    const d = v > 0 ? segment(i, from, at, j === topJ) : "";
                    return d ? <path key={j} d={d} fill={colours[j]} data-testid="object-chart-segment" /> : null;
                  })}
                </g>
                {i % 7 === 0 && <text x={mid(i)} y={height - 8} textAnchor="middle" fill="var(--chart-tick)" style={{ font: "10px Inter, system-ui, sans-serif" }}>{dayLabel(window[i])}</text>}
                <rect data-testid="object-chart-hit" x={LEFT + i * slot} y={TOP - 10} width={slot} height={BASE - TOP + 10} fill="transparent"
                  onMouseEnter={() => setHover(i)}><title>{said(i)}</title></rect>
              </g>
            );
          })}
          {narrowed.length > 0 && (
            <polyline points={all.map((v, i) => `${mid(i)},${y(v)}`).join(" ")} fill="none" stroke="var(--chart-deemph)"
              strokeWidth={2} strokeLinejoin="round" pointerEvents="none" />
          )}
          <circle cx={mid(endI)} cy={y(lineEnd)} r={4} fill={narrowed.length || split ? "var(--chart-deemph)" : "var(--chart-1)"} stroke="var(--bg-2)" strokeWidth={2} pointerEvents="none" />
          <text x={mid(endI) - 6} y={y(lineEnd) - 8} textAnchor="end" fill="var(--t2)" data-testid="object-chart-end" style={{ font: "10.5px Inter, system-ui, sans-serif" }}>
            {endSaid}
          </text>
        </svg>
        {hover !== null && (
          <div data-testid="object-chart-tip" className="aug-fs-xs" role="status" style={{
            position: "absolute", top: 0, left: `${(mid(hover) / width) * 100}%`, transform: `translateX(${hover > lastI / 2 ? "-100%" : "0"})`,
            background: "var(--bg-3)", border: "1px solid var(--b1)", borderRadius: "var(--r2)", padding: "4px 8px", color: "var(--t1)",
            whiteSpace: "nowrap", pointerEvents: "none", boxShadow: "var(--shadow-sm)" }}>
            {said(hover)}
          </div>
        )}
      </div>
    </Frame>
  );
}
