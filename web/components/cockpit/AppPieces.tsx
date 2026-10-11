"use client";

/**
 * The pieces the picker adds (Arc AP-4; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.4) — each reads an entity or a
 * named set as a table does (`useSetQuery`), narrowed by the reader's own filters, through the object door:
 *
 *   - an object list: a queue as cards — each called by a property, a number beside it, a mark under it; a click
 *     chooses, a tick collects;
 *   - a map: the set placed by its coordinates on the world the app ships (`/geo/world.json`), fitted to its places,
 *     drawn with the Vega the charts already use; a click on a place chooses it;
 *   - a timeline: each object a bar between two moments on one line of days; one with no end yet runs to today, and
 *     says so; a click chooses;
 *   - choose one: one object picked by its name, found by the words typed — what the pieces that follow the choice read;
 *   - search: words a reader types, narrowing every set of an entity to the objects whose property holds them.
 *
 * Withheld is said: a piece that reads the first objects of many says how many it shows of how many there are.
 */
import { useEffect, useMemo, useState } from "react";

import { useCellBox, useMeasured, useSettled } from "@/components/cockpit/cellBox";
import { Foot, Frame, Title } from "@/components/cockpit/CockpitTile";
import { Body, Reading, Unread, WaitingWords, useNoun, usePieces, useSetQuery } from "@/components/cockpit/OntologyPieces";
import { VegaChart } from "@/components/charts/vega/VegaChart";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { MAX_TICKED_RUNS, rowsTall } from "@/lib/cockpit/catalog";
import { cellText, entityKey, plural, typeWord, WORDS } from "@/lib/cockpit/objectView";
import { formatCount } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { listObjects, type ObjectListingPage } from "@/lib/objects";

/** The most objects a map or a choose-one reads at once — the object door's page. */
const MOST = 200;
const words = (id: string) => id.replace(/[_-]+/g, " ");

/** Where a property's values sit in a page's rows — after the key, by its path, never by its place among the props: the
 *  object door leaves out a property that is the key, and lists a property named twice once. 0 when it is not listed. */
const at = (page: ObjectListingPage, path: string | null | undefined) => (path ? page.columns.findIndex(c => c.path === path) + 1 : 0);
/** What a piece over a set says it shows when the set names no label: the ontology's name for its objects — "Distribution
 *  Centers" — or the type's own words while that name is read. */
function useObjectsWord(entity: string | null | undefined, typeId: string | null | undefined): string {
  const said = useNoun(entity ?? "") || plural(typeWord(typeId)).toLowerCase() || "objects";   // the noun is plural already
  return said.charAt(0).toUpperCase() + said.slice(1);
}

/** What an object is called: by the property named, or "Order 63981" when it names none — and a key that says its type
 *  already ("case-7530088c") as it is, never "Case case-7530088c". */
const calledBy = (page: ObjectListingPage, row: unknown[], i: number) => {
  const v = i > 0 ? row[i] : null;
  if (v != null && String(v) !== "") return String(v);
  const word = typeWord(page.type_id), key = String(row[0]);
  return key.toLowerCase().startsWith(word.toLowerCase()) ? key : `${word} ${key}`;
};

/** One page of a piece's set: the objects, refused or failed said, read again when what it asks changes or an action
 *  ran. A key that changes resets the page to the first — kept beside what it was read for, never reset in an effect. */
function usePage(props: Record<string, unknown>, columns: string[], { sort = "", descending = false, limit, extra = [] }:
  { sort?: string; descending?: boolean; limit: number; extra?: Record<string, unknown>[] }) {
  const { connectionId, schema, tick } = usePieces();
  const query = useSetQuery(props);
  const target = "entity" in query ? query : null;
  const conditions = target ? [...target.conditions, ...extra] : [];
  const asked = JSON.stringify([target?.entity, target?.segment, conditions, columns, sort, descending]);
  const [at, setAt] = useState({ asked, offset: 0 });
  const offset = at.asked === asked ? at.offset : 0;
  const [read, setRead] = useState<{ asked: string; page: ObjectListingPage | null; refused: string } | null>(null);
  useEffect(() => {
    if (!target || !connectionId) return;
    let alive = true;
    const key = `${asked}|${offset}|${limit}|${tick}`;
    listObjects({ entity: target.entity, segment: target.segment, columns, order_by: sort, descending, offset, limit, filters: conditions as typeof target.conditions },
      connectionId, schema)
      .then(out => { if (alive) setRead(out.path === "refused" ? { asked: key, page: null, refused: out.refused } : { asked: key, page: out, refused: out.error ?? "" }); })
      .catch(e => { if (alive) setRead({ asked: key, page: null, refused: (e as Error).message }); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what it asks
  }, [asked, offset, limit, connectionId, schema, tick]);
  const now = read && read.asked === `${asked}|${offset}|${limit}|${tick}` ? read : null;
  // a page read for another ask — another chosen object's links, a set switched — is never shown as this one's
  return { query, target, page: target ? now?.page ?? null : null, refused: now?.refused ?? "", offset, setOffset: (o: number) => setAt({ asked, offset: o }) };
}

function Pager({ offset, shown, total, limit, onPage }: { offset: number; shown: number; total: number | null; limit: number; onPage: (o: number) => void }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
      <Button size="icon-xs" variant="ghost" aria-label="Previous page" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}><Icon name="chevl" /></Button>
      <Button size="icon-xs" variant="ghost" aria-label="Next page" disabled={total != null ? offset + shown >= total : shown < limit}
        onClick={() => onPage(offset + limit)}><Icon name="chevr" /></Button>
    </span>
  );
}

// ── the object list ───────────────────────────────────────────────────────────────────────

/** The room a card takes in a list, and the rest of the list's box — what the cards that fit are counted from. */
const CARD_PX = 54;
const LIST_CHROME_PX = 96;

export function ObjectListPiece({ elementKey, entity, set, setFrom, chooses, ticks, title, figure, mark, sort, descending }: {
  elementKey: string | null; entity?: string | null; set?: string | null; setFrom?: string | null; chooses?: string | null; ticks?: string | null;
  title?: string | null; figure?: string | null; mark?: string | null; sort?: string | null; descending?: boolean | null;
}) {
  const { picked, pick, ticked, tickOne } = usePieces();
  const box = useCellBox();
  const limit = useSettled(box.onGrid ? Math.max(1, Math.floor((rowsTall(box.h) - LIST_CHROME_PX) / CARD_PX)) : 6, 350);
  // the object door sorts by a listed property only — a sort the cards do not show is listed beside them
  const columns = [...new Set([title, figure, mark, sort].filter((c): c is string => !!c))];
  const { query, target, page, refused, offset, setOffset } = usePage({ entity, set, set_from: setFrom }, columns,
    { sort: sort ?? "", descending: !!descending, limit });
  const objects = useObjectsWord(target?.entity ?? entity, page?.type_id);
  if ("refused" in query) return <Unread what="This list cannot be read">{query.refused}</Unread>;
  if ("waiting" in query) {
    return <Frame testid="object-list"><Title title={query.label || "Objects"} /><div className="aug-fs-sm" data-testid="object-list-waiting" style={{ color: "var(--t3)" }}><WaitingWords choice={query.waiting} what={query.label} /></div></Frame>;
  }
  if (refused && !page) return <Unread what="This list cannot be read">{refused}</Unread>;
  if (!page || !target) return <Reading what="the objects" />;
  const choice = chooses || elementKey;
  const [ti, fi, mi] = [at(page, title), at(page, figure), at(page, mark)];
  const ticks_ = ticks ? ticked[ticks] ?? [] : [];
  const full = ticks_.length >= MAX_TICKED_RUNS;
  return (
    <Frame testid="object-list">
      <Title title={query.label || objects} right={
        <span className="aug-fs-xs" data-testid="object-list-total" style={{ color: "var(--t3)", fontVariantNumeric: "tabular-nums" }}>
          {page.total == null ? "not counted" : formatCount(page.total)}
        </span>} />
      <Body testid="object-list-cards" gap={6}>
        {withUniqueKeys(page.rows, r => String(r[0])).map(([key, row]) => {
          const pk = String(row[0]);
          const object = { objectType: page.object_type, typeId: page.type_id, pk };
          const on = !!choice && picked[choice]?.pk === pk;
          const isTicked = ticks_.some(t => t.pk === pk);
          const cell = (i: number) => (i > 0 ? cellText(row[i], page.columns[i - 1]?.type, undefined, page.columns[i - 1]?.unit ?? "", page.columns[i - 1]?.role ?? "") : "—");
          return (
            <div key={key} data-testid="object-list-card" aria-pressed={on} role="button" tabIndex={0}
              onClick={() => choice && pick(choice, on ? null : object)} onKeyDown={e => { if (e.key === "Enter" && choice) pick(choice, on ? null : object); }}
              style={{ display: "grid", gridTemplateColumns: `${ticks ? "20px " : ""}minmax(0, 1fr) auto`, alignItems: "center", gap: 8,
                padding: "8px 10px", borderRadius: "var(--r2)", border: "1px solid var(--b1)", cursor: choice ? "pointer" : undefined,
                background: on ? "var(--bg-sel)" : "var(--bg-1)" }}>
              {ticks && <span onClick={e => e.stopPropagation()}><Checkbox checked={isTicked} disabled={!isTicked && full} aria-label={`Tick ${pk}`} onChange={e => tickOne(ticks, object, e.target.checked)} /></span>}
              <span style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
                <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{ti ? cell(ti) : calledBy(page, row, 0)}</span>
                {mi > 0 && <span className="aug-fs-xs" data-testid="object-list-mark" style={{ alignSelf: "flex-start", color: "var(--t2)", background: "var(--bg-3)", borderRadius: "var(--r-chip)", padding: "0 6px" }}>{cell(mi)}</span>}
              </span>
              {fi > 0 && <span className="aug-fs-sm" data-testid="object-list-figure" style={{ color: "var(--t1)", fontVariantNumeric: "tabular-nums" }}>{cell(fi)}</span>}
            </div>
          );
        })}
        {page.rows.length === 0 && <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>No objects in this set.</div>}
      </Body>
      <Foot icon="list" aside={<Pager offset={offset} shown={page.rows.length} total={page.total} limit={limit} onPage={setOffset} />}>
        {page.rows.length ? `${formatCount(offset + 1)}–${formatCount(offset + page.rows.length)} of ${page.total == null ? "…" : formatCount(page.total)}` : "none"}
        {ticks_.length > 0 && ` · ${formatCount(ticks_.length)} ticked`}
      </Foot>
    </Frame>
  );
}

// ── the map ───────────────────────────────────────────────────────────────────────────────

const WORLD = { url: "/geo/world.json", format: { property: "features" } };

/** The places a map is fitted to: the box around its points, given room, so ten distribution centres fill it. */
export function fitOf(points: { lat: number; lng: number }[]): Record<string, unknown> | null {
  if (!points.length) return null;
  const lats = points.map(p => p.lat), lngs = points.map(p => p.lng);
  const [s, n, w, e] = [Math.min(...lats), Math.max(...lats), Math.min(...lngs), Math.max(...lngs)];
  const dy = Math.max(2, (n - s) * 0.2), dx = Math.max(2, (e - w) * 0.2);
  const corners = [[w - dx, s - dy], [e + dx, n + dy], [w - dx, n + dy], [e + dx, s - dy]]
    .map(([x, y]) => [Math.max(-180, Math.min(180, x)), Math.max(-85, Math.min(85, y))]);
  return { type: "Feature", properties: {}, geometry: { type: "MultiPoint", coordinates: corners } };
}

export function ObjectMapPiece({ elementKey, entity, set, setFrom, chooses, lat, lng, label }: {
  elementKey: string | null; entity?: string | null; set?: string | null; setFrom?: string | null; chooses?: string | null;
  lat: string; lng: string; label?: string | null;
}) {
  const { picked, pick } = usePieces();
  const box = useCellBox();
  const [plot, room] = useMeasured<HTMLDivElement>();
  const columns = [lat, lng, ...(label ? [label] : [])];
  const { query, target, page, refused } = usePage({ entity, set, set_from: setFrom }, columns, { limit: MOST });
  const objects = useObjectsWord(target?.entity ?? entity, page?.type_id);
  const choice = chooses || elementKey;
  const chosen = choice ? picked[choice]?.pk ?? null : null;
  const points = useMemo(() => {
    if (!page) return [];
    const [y, x, n] = [at(page, lat), at(page, lng), at(page, label)];
    // a coordinate left empty is no place: Number(null) is 0, and 0, 0 is in the sea off Africa
    const num = (v: unknown) => (v == null || v === "" ? NaN : Number(v));
    return page.rows.map(r => ({ pk: String(r[0]), lat: y ? num(r[y]) : NaN, lng: x ? num(r[x]) : NaN, name: calledBy(page, r, n) }))
      .filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lng) && Math.abs(p.lat) <= 90 && Math.abs(p.lng) <= 180);
  }, [page, lat, lng, label]);
  const spec = useMemo(() => {
    const fit = fitOf(points);
    return {
      // drawn at the size it is handed: the charts' own autosize "fit" fitted against a fitted projection collapses
      // every place to one point (measured 2026-10-11, the world drawn as a dot and ten centres on it)
      autosize: { type: "none" },
      projection: { type: "equalEarth", ...(fit ? { fit } : {}) },
      layer: [
        { data: WORLD, mark: { type: "geoshape" } },
        {
          data: { values: points.map(p => ({ ...p, chosen: p.pk === chosen })) },
          mark: { type: "circle", tooltip: true, opacity: 0.9, stroke: "white", strokeWidth: 1 },
          encoding: {
            longitude: { field: "lng", type: "quantitative" }, latitude: { field: "lat", type: "quantitative" },
            size: { condition: { test: "datum.chosen", value: 260 }, value: 110 },
            tooltip: [{ field: "name", type: "nominal", title: "Place" }],
          },
        },
      ],
    };
  }, [points, chosen]);
  if ("refused" in query) return <Unread what="This map cannot be read">{query.refused}</Unread>;
  if ("waiting" in query) return <Frame testid="object-map"><Title title={query.label || "Places"} /><div className="aug-fs-sm" style={{ color: "var(--t3)" }}><WaitingWords choice={query.waiting} what={query.label} /></div></Frame>;
  if (refused && !page) return <Unread what="This map cannot be read">{refused}</Unread>;
  if (!page) return <Reading what="the places" />;
  const unplaced = page.rows.length - points.length;
  const height = box.onGrid ? Math.max(180, room.height || 260) : 300;
  return (
    <Frame testid="object-map">
      <Title title={query.label || objects} right={
        <span className="aug-fs-xs" data-testid="object-map-total" style={{ color: "var(--t3)", fontVariantNumeric: "tabular-nums" }}>
          {formatCount(points.length)} placed{page.total != null && page.total > page.rows.length ? ` of ${formatCount(page.total)}` : ""}
        </span>} />
      <div ref={plot} data-testid="object-map-plot" data-points={points.length} style={{ position: "relative", minHeight: 0, ...(box.onGrid ? { flex: 1 } : {}) }}>
        {points.length > 0
          ? <VegaChart spec={spec} height={height} onSelect={d => { const pk = String(d.pk ?? ""); if (choice && pk) pick(choice, chosen === pk ? null : { objectType: page.object_type, typeId: page.type_id, pk }); }} />
          : <div className="aug-fs-sm" style={{ color: "var(--t3)", padding: "12px 0" }}>None of these has a place to put on a map.</div>}
      </div>
      {(unplaced > 0 || (page.total != null && page.total > page.rows.length)) && (
        <Foot icon="info">
          {unplaced > 0 ? `${formatCount(unplaced)} with no coordinates are not drawn. ` : ""}
          {page.total != null && page.total > page.rows.length ? `The first ${formatCount(page.rows.length)} of ${formatCount(page.total)} are drawn.` : ""}
        </Foot>
      )}
    </Frame>
  );
}

// ── the timeline ──────────────────────────────────────────────────────────────────────────

const LANE_PX = 26;
const day = (s: unknown): number | null => {
  const t = Date.parse(String(s ?? "").replace(" ", "T").replace(/\+00(:00)?$/, "Z"));
  return Number.isFinite(t) ? t : null;
};

export function ObjectTimelinePiece({ elementKey, entity, set, setFrom, chooses, start, end, label }: {
  elementKey: string | null; entity?: string | null; set?: string | null; setFrom?: string | null; chooses?: string | null;
  start: string; end: string; label?: string | null;
}) {
  const { picked, pick } = usePieces();
  const box = useCellBox();
  const [plot, room] = useMeasured<HTMLDivElement>();
  // today, as the timeline was first drawn: an open bar runs to it
  const [now] = useState(() => Date.now());
  const limit = useSettled(box.onGrid ? Math.max(2, Math.floor((rowsTall(box.h) - 100) / LANE_PX)) : 8, 350);
  const columns = [...new Set([label, start, end].filter((c): c is string => !!c))];
  const { query, target, page, refused, offset, setOffset } = usePage({ entity, set, set_from: setFrom }, columns, { sort: start, descending: true, limit });
  const objects = useObjectsWord(target?.entity ?? entity, page?.type_id);
  if ("refused" in query) return <Unread what="This timeline cannot be read">{query.refused}</Unread>;
  if ("waiting" in query) return <Frame testid="object-timeline"><Title title={query.label || "Objects"} /><div className="aug-fs-sm" style={{ color: "var(--t3)" }}><WaitingWords choice={query.waiting} what={query.label} /></div></Frame>;
  if (refused && !page) return <Unread what="This timeline cannot be read">{refused}</Unread>;
  if (!page) return <Reading what="the objects" />;
  const choice = chooses || elementKey;
  const [ni, si, ei] = [at(page, label), at(page, start), at(page, end)];
  const lanes = page.rows.map(r => ({ pk: String(r[0]), name: calledBy(page, r, ni), from: si ? day(r[si]) : null, to: ei ? day(r[ei]) : null }));
  const known = lanes.filter(l => l.from !== null);
  const lo = known.length ? Math.min(...known.map(l => l.from!)) : now;
  const hi = known.length ? Math.max(...known.map(l => l.to ?? now)) : now;
  const width = Math.max(240, room.width || 480);
  const NAME = Math.min(160, Math.round(width * 0.3));
  const x = (t: number) => NAME + ((t - lo) / Math.max(1, hi - lo)) * (width - NAME - 8);
  const dayText = (t: number) => new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  return (
    <Frame testid="object-timeline">
      <Title title={query.label || objects} right={
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{known.length ? `${dayText(lo)} – ${dayText(hi)}` : ""}</span>} />
      <div ref={plot} style={{ minHeight: 0, overflow: "auto", ...(box.onGrid ? { flex: 1 } : {}) }}>
        <svg width={width} height={lanes.length * LANE_PX + 4} role="img" aria-label={`${query.label || "Objects"}, each from ${words(start)} to ${words(end)}`} style={{ display: "block" }}>
          {withUniqueKeys(lanes, l => l.pk).map(([key, l], i) => {
            const on = !!choice && picked[choice]?.pk === l.pk;
            const y = i * LANE_PX + 4;
            const open = l.from !== null && l.to === null;
            return (
              <g key={key} data-testid="object-timeline-lane" data-open={open || undefined} style={{ cursor: choice ? "pointer" : undefined }}
                onClick={() => choice && pick(choice, on ? null : { objectType: page.object_type, typeId: page.type_id, pk: l.pk })}>
                <rect x={0} y={y - 2} width={width} height={LANE_PX - 2} fill={on ? "var(--bg-sel)" : "transparent"} />
                <text x={4} y={y + 13} fill="var(--t1)" style={{ font: "12px Inter, system-ui, sans-serif" }}>{l.name.length > 22 ? `${l.name.slice(0, 21)}…` : l.name}</text>
                {l.from !== null && (
                  <rect x={x(l.from)} y={y + 3} width={Math.max(3, x(l.to ?? now) - x(l.from))} height={LANE_PX - 12} rx={3}
                    fill={open ? "var(--chart-deemph)" : "var(--chart-1)"} strokeDasharray={open ? "3 2" : undefined} stroke={open ? "var(--chart-1)" : undefined}>
                    <title>{`${l.name}: ${dayText(l.from)} – ${l.to !== null ? dayText(l.to) : "still open, drawn to today"}`}</title>
                  </rect>
                )}
              </g>
            );
          })}
        </svg>
        {lanes.length === 0 && <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>No objects in this set.</div>}
      </div>
      <Foot icon="clock" aside={<Pager offset={offset} shown={page.rows.length} total={page.total} limit={limit} onPage={setOffset} />}>
        {lanes.some(l => l.from !== null && l.to === null) ? "A bar still open runs to today. " : ""}{page.total == null ? "" : `${formatCount(page.total)} in all`}
      </Foot>
    </Frame>
  );
}

// ── choose one ────────────────────────────────────────────────────────────────────────────

export function ChooseOnePiece({ entity, set, chooses, label }: { entity?: string | null; set?: string | null; chooses: string; label: string }) {
  const { picked, pick } = usePieces();
  const [text, setText] = useState("");
  // the name of the one chosen, kept from the click — the words typed after may find others, and not it
  const [kept, setKept] = useState<{ pk: string; name: string } | null>(null);
  const typed = useSettled(text.trim(), 350);
  const query = useSetQuery({ entity, set });
  const target = "entity" in query ? query : null;
  const noun = useNoun(target?.entity ?? entity ?? "");
  // the words typed look for the objects whose name holds them — at the object door, never among a first page only
  const { page, refused } = usePage({ entity, set }, [label], { sort: label, limit: 12,
    extra: typed ? [{ path: label, op: "contains", value: typed }] : [] });
  const chosen = picked[chooses];
  const filtered = useMemo(() => {
    if (!page) return [];
    const named = page.rows.map(r => ({ pk: String(r[0]), name: calledBy(page, r, at(page, label)) }));
    // four customers called Zoe are four choices: a name held by more than one says its key beside it
    const seen = new Map<string, number>();
    for (const o of named) seen.set(o.name, (seen.get(o.name) ?? 0) + 1);
    return named.map(o => ((seen.get(o.name) ?? 0) > 1 ? { ...o, name: `${o.name} · ${o.pk}` } : o));
  }, [page, label]);
  if ("refused" in query) return <Unread what="This choice cannot be read">{query.refused}</Unread>;
  if ("waiting" in query) return <Frame testid="choose-one"><Title title={query.label || "Choose one"} /><div className="aug-fs-sm" style={{ color: "var(--t3)" }}><WaitingWords choice={query.waiting} what={query.label} /></div></Frame>;
  const named = !chosen ? null : kept?.pk === chosen.pk ? kept.name : filtered.find(o => o.pk === chosen.pk)?.name ?? null;
  return (
    <Frame testid="choose-one">
      <Title title={`Choose ${/^[aeiou]/i.test(noun) ? "an" : "a"} ${noun.toLowerCase().replace(/s$/, "")}`} />
      {/* the one chosen, and the door to let it go, on a line of their own: a narrow piece keeps its title */}
      {chosen && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
          <span className="aug-fs-sm" data-testid="choose-one-chosen" style={{ flex: 1, minWidth: 0, color: "var(--t1)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {named ?? `${typeWord(chosen.typeId)} ${chosen.pk}`}
          </span>
          <Button size="xs" variant="ghost" data-testid="choose-one-clear" onClick={() => pick(chooses, null)}>Let go</Button>
        </div>
      )}
      <Input aria-label={`Find ${noun.toLowerCase()} by ${words(label)}`} placeholder={`Find by ${words(label)}`} value={text} onChange={e => setText(e.target.value)} />
      {refused && !page ? <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>{refused}</div> : !page ? <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Reading…</div> : (
        <Body testid="choose-one-options" gap={2}>
          {withUniqueKeys(filtered, o => o.pk).map(([key, o]) => (
            <Button key={key} size="xs" variant={chosen?.pk === o.pk ? "secondary" : "ghost"} data-testid="choose-one-option" aria-pressed={chosen?.pk === o.pk}
              onClick={() => { setKept(o); pick(chooses, chosen?.pk === o.pk ? null : { objectType: page.object_type, typeId: page.type_id, pk: o.pk }); }}
              style={{ justifyContent: "flex-start" }}>{o.name}</Button>
          ))}
          {filtered.length === 0 && <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>{typed ? `None whose ${words(label)} holds “${typed}”.` : "None in this set."}</div>}
          {page.total != null && page.total > filtered.length && filtered.length > 0 && (
            <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>The first {formatCount(filtered.length)} of {formatCount(page.total)} — type to find one.</div>
          )}
        </Body>
      )}
    </Frame>
  );
}

// ── search ────────────────────────────────────────────────────────────────────────────────

export function ObjectSearchPiece({ entity, path, label }: { entity: string; path: string; label: string }) {
  const { filters, search } = usePieces();
  const held = filters[entityKey(entity)]?.[WORDS + path]?.[0] ?? "";
  const noun = useNoun(entity);
  const [text, setText] = useState(held);
  const [shownHeld, setShownHeld] = useState(held);
  // words let go elsewhere — the filter bar's Clear — are let go here too
  if (held !== shownHeld) { setShownHeld(held); setText(held); }
  const settled = useSettled(text, 400);
  useEffect(() => { if (settled.trim() !== held) search(entity, path, settled); }, [settled]); // eslint-disable-line react-hooks/exhaustive-deps -- typed words, once settled
  return (
    <Frame testid="object-search">
      <Title title={label} />
      <Input aria-label={label} placeholder={`Words in the ${words(path)}`} value={text} onChange={e => setText(e.target.value)} />
      <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
        {held ? `Every ${noun.toLowerCase().replace(/s$/, "")} piece shows those whose ${words(path)} holds “${held}” — for you only.`
          : `Narrows every piece over ${noun.toLowerCase()}, for you only.`}
      </div>
    </Frame>
  );
}
