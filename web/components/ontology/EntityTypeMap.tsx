"use client";

/**
 * ON-3b — the entity-type map (ROADMAP §3.15, amended 2026-09-11; re-laid 2026-09-12).
 *
 * A searchable rail of object types; a canvas that draws the WHOLE business at once with the most-linked type in
 * the middle — the map's first claim is which entity everything else hangs from — and the entity-type panel beside
 * it. Picking a type does not move the map: it LIGHTS it, its links and the types on the other end of them, names
 * those links with their verb and measured cardinality, and opens the type in the panel. Centring is a separate,
 * explicit act, so the middle of the map keeps meaning "the busiest entity" until a person says otherwise.
 *
 * Every fact on a card is measured, not a paragraph (`GET /object-types`): whether the key is unique, the rows,
 * the binding, the links the compiler follows, the declared actions, the verified metrics. A link the compiler
 * refuses is drawn dashed and says why on hover.
 */
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { EntityTypePanel } from "@/components/ontology/EntityTypePanel";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SkeletonRows } from "@/components/ui/motion";
import { hubOf, layoutMap, litBy, type MapEdge } from "@/lib/entityMapLayout";
import { formatCount } from "@/lib/format";
import { getTypeMap, type TypeMap, type TypeMapRow } from "@/lib/objectTypes";

const MONO: React.CSSProperties = { fontFamily: "var(--font-mono)" };
const RULE = "1px solid var(--b1)";
/** How far a card, a link or a label that the selected type does not touch falls back. */
const UNLIT = 0.42;
/** The map fits itself to the pane, but never shrinks past this — below it the cards stop being readable and a
 *  person pans instead. */
const MIN_FIT = 0.55;
const ZOOM_STEPS = [0.55, 0.7, 0.85, 1, 1.25, 1.5];

function keyWords(verified: boolean | null): string {
  return verified === true ? "key unique" : verified === false ? "key not unique" : "key unmeasured";
}

export function EntityTypeMap({ connectionId, schema }: { connectionId: string; schema?: string }) {
  const [map, setMap] = useState<TypeMap | null>(null);
  const [error, setError] = useState("");
  /** The type in the middle of the map — the busiest one until a person centres another. */
  const [focus, setFocus] = useState<string | null>(null);
  /** The type a person picked: lit on the map, open in the panel. */
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  // Bumped by a write in the panel (a declared display property, a measurement) so the map and the panel re-read.
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let live = true;
    setError("");
    getTypeMap(connectionId, schema)
      .then((next) => {
        if (!live) return;
        const has = (type: string | null) => !!type && next.object_types.some((t) => t.object_type === type);
        setMap(next);
        setFocus((current) => (has(current) ? current : hubOf(next)));
        setSelected((current) => (has(current) ? current : hubOf(next)));
      })
      .catch((e: unknown) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [connectionId, schema, version]);

  if (error) {
    return (
      <EmptyState icon="alert" title="The entity-type map could not be read"
        action={<Button variant="outline" size="sm" onClick={() => setVersion((v) => v + 1)}>Try again</Button>}>
        {error}
      </EmptyState>
    );
  }
  if (!map) return <div style={{ flex: 1, padding: 24 }}><SkeletonRows rows={6} /></div>;
  if (!focus || !selected || map.object_types.length === 0) {
    return <EmptyState icon="node" title="This ontology has no object types yet." />;
  }
  return (
    <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0 }} data-testid="entity-type-map">
      <TypeRail types={map.object_types} selected={selected} focus={focus} query={query} onQuery={setQuery}
        onPick={setSelected} />
      <FocusCanvas map={map} focus={focus} selected={selected} onSelect={setSelected} onCentre={setFocus} />
      <EntityTypePanel connectionId={connectionId} schema={schema} objectType={selected} types={map.object_types}
        version={version} onOpen={setSelected} onChanged={() => setVersion((v) => v + 1)} />
    </div>
  );
}

function TypeRail({ types, selected, focus, query, onQuery, onPick }: {
  types: TypeMapRow[];
  selected: string;
  focus: string;
  query: string;
  onQuery: (q: string) => void;
  onPick: (objectType: string) => void;
}) {
  const wanted = query.trim().toLowerCase();
  const shown = wanted
    ? types.filter((t) => [t.display_name, t.object_type, t.id, t.table].some((s) => s.toLowerCase().includes(wanted)))
    : types;
  return (
    <nav aria-label="Entity types"
      style={{ width: 212, flexShrink: 0, borderRight: RULE, display: "flex", flexDirection: "column", minHeight: 0,
               background: "var(--bg-0)" }}>
      <div style={{ padding: "10px 10px 6px" }}>
        <Input value={query} onChange={(e) => onQuery(e.target.value)} placeholder="Find an entity type"
          aria-label="Find an entity type" data-testid="entity-rail-search" />
        <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 6 }}>
          {shown.length === types.length ? `${types.length} types` : `${shown.length} of ${types.length} types`}
        </div>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0 6px 10px" }}>
        {shown.length === 0 && <EmptyState variant="inline" title={`No type matches “${query.trim()}”.`} />}
        {shown.map((t) => {
          const current = t.object_type === selected;
          return (
            <Button key={t.object_type} variant="ghost" size="sm" onClick={() => onPick(t.object_type)}
              aria-current={current ? "true" : undefined} data-testid="entity-rail-row"
              title={`Light up ${t.display_name} and what it links to`}
              className="h-auto w-full justify-start py-1.5"
              style={current ? { background: "var(--bg-hover)" } : undefined}>
              <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", minWidth: 0, gap: 1 }}>
                <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: current ? 600 : 500 }}>
                  {t.display_name}
                  {t.object_type === focus && (
                    <span className="aug-fs-xs" style={{ color: "var(--t3)", fontWeight: 400 }}> · centre</span>
                  )}
                </span>
                <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                  {keyWords(t.key_verified)} · {t.links} {t.links === 1 ? "link" : "links"}
                </span>
              </span>
            </Button>
          );
        })}
      </div>
    </nav>
  );
}

function FocusCanvas({ map, focus, selected, onSelect, onCentre }: {
  map: TypeMap;
  focus: string;
  selected: string;
  onSelect: (objectType: string) => void;
  onCentre: (objectType: string) => void;
}) {
  const layout = useMemo(() => layoutMap(map, focus), [map, focus]);
  const lit = useMemo(() => litBy(map, selected), [map, selected]);
  const types = useMemo(() => new Map(map.object_types.map((t) => [t.object_type, t])), [map]);
  const scroller = useRef<HTMLDivElement>(null);
  const [pane, setPane] = useState({ w: 0, h: 0 });
  /** null while the map sizes itself to the pane; a number once a person has zoomed. */
  const [zoom, setZoom] = useState<number | null>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);

  const fit = useMemo(() => {
    if (pane.w === 0 || pane.h === 0) return 1;
    const room = Math.min((pane.w - 24) / layout.width, (pane.h - 24) / layout.height);
    return Math.max(MIN_FIT, Math.min(1, room));
  }, [pane, layout.width, layout.height]);
  const scale = zoom ?? fit;
  const [width, height] = [layout.width * scale, layout.height * scale];

  const measure = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    setPane((last) => (last.w === el.clientWidth && last.h === el.clientHeight
      ? last : { w: el.clientWidth, h: el.clientHeight }));
  }, []);

  const centre = useCallback(() => {
    const el = scroller.current;
    if (!el || el.clientWidth === 0) return;
    el.scrollLeft = Math.max(0, (el.scrollWidth - el.clientWidth) / 2);
    el.scrollTop = Math.max(0, (el.scrollHeight - el.clientHeight) / 2);
  }, []);

  // Size the map to the pane before the first paint, and bring its centre into view when it re-centres or is zoomed.
  useLayoutEffect(() => { measure(); centre(); }, [focus, width, height, measure, centre]);
  // Then keep the pane's size as it changes: this layer can mount hidden (zero wide), and a map sized then would be
  // wrong the moment it shows.
  useEffect(() => {
    const el = scroller.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [measure]);

  const step = (by: number) => setZoom(() => {
    const up = ZOOM_STEPS.find((z) => z > scale + 1e-6);
    const down = [...ZOOM_STEPS].reverse().find((z) => z < scale - 1e-6);
    return by > 0 ? (up ?? ZOOM_STEPS[ZOOM_STEPS.length - 1]) : (down ?? ZOOM_STEPS[0]);
  });

  // Dragging the background pans; a card keeps its own click.
  const startPan = (e: React.PointerEvent) => {
    const el = scroller.current;
    if (!el || e.button !== 0 || (e.target as HTMLElement).closest("[data-map-card]")) return;
    drag.current = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop };
    el.setPointerCapture(e.pointerId);
  };
  const movePan = (e: React.PointerEvent) => {
    const el = scroller.current;
    if (!el || !drag.current) return;
    el.scrollLeft = drag.current.left - (e.clientX - drag.current.x);
    el.scrollTop = drag.current.top - (e.clientY - drag.current.y);
  };
  const endPan = (e: React.PointerEvent) => {
    if (drag.current) scroller.current?.releasePointerCapture(e.pointerId);
    drag.current = null;
  };

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", position: "relative" }}>
      <div ref={scroller} data-testid="entity-map-canvas" onPointerDown={startPan} onPointerMove={movePan}
        onPointerUp={endPan} onPointerCancel={endPan}
        style={{ flex: 1, minWidth: 0, overflow: "auto", background: "var(--bg-1)", touchAction: "none",
                 backgroundImage: "radial-gradient(circle, var(--b2) 1px, transparent 1px)", backgroundSize: "24px 24px" }}>
        {/* The map sits in the middle of the pane however small it is, and is scrolled once it outgrows it. */}
        <div style={{ width: "max-content", minWidth: "100%", minHeight: "100%",
                      display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ position: "relative", width, height, flexShrink: 0 }}>
            <div style={{ position: "absolute", top: 0, left: 0, width: layout.width, height: layout.height,
                          transform: `scale(${scale})`, transformOrigin: "0 0" }}>
              <svg width={layout.width} height={layout.height} aria-hidden="true" style={{ position: "absolute", inset: 0 }}>
                {layout.edges.map((edge) => {
                  const on = lit.links.has(edge.link.relationship);
                  return (
                    <path key={edge.link.relationship} d={edge.path} fill="none"
                      stroke={edge.link.traversable ? "var(--blue3)" : "var(--amb4)"}
                      strokeWidth={on ? 2 : 1.25}
                      strokeDasharray={edge.link.traversable ? undefined : "5 4"} opacity={on ? 0.95 : UNLIT} />
                  );
                })}
              </svg>
              {layout.nodes.map((node) => {
                const type = types.get(node.objectType);
                if (!type) return null;
                const props = {
                  type, x: node.x, y: node.y, lit: lit.nodes.has(node.objectType),
                  selected: node.objectType === selected, onSelect, onCentre,
                };
                return node.objectType === focus
                  ? <FocusCard key={node.objectType} {...props} />
                  : <NeighbourCard key={node.objectType} {...props} />;
              })}
              {/* Only the picked type's links are named: every label at once is what made this map unreadable. */}
              {layout.edges.filter((edge) => lit.links.has(edge.link.relationship))
                .map((edge) => <LinkLabel key={`label:${edge.link.relationship}`} edge={edge} types={types} />)}
            </div>
          </div>
        </div>
      </div>
      <Zoom scale={scale} fitted={zoom === null} onStep={step} onFit={() => setZoom(null)} />
      <UnlinkedTray unlinked={layout.unlinked} types={types} selected={selected} onSelect={onSelect} />
    </div>
  );
}

/** How much of the map is shown, and the two ways out of it: a step in or out, and back to the whole map. */
function Zoom({ scale, fitted, onStep, onFit }: {
  scale: number;
  fitted: boolean;
  onStep: (by: number) => void;
  onFit: () => void;
}) {
  return (
    <div data-testid="entity-map-zoom"
      style={{ position: "absolute", top: 10, right: 10, zIndex: 4, display: "flex", alignItems: "center", gap: 2,
               padding: 2, borderRadius: "var(--r-chip)", border: RULE, background: "var(--bg-0)" }}>
      <Button variant="ghost" size="icon-xs" onClick={() => onStep(-1)} title="Show more of the map">
        <Icon name="minus" size={12} label="Zoom out" />
      </Button>
      <span className="aug-fs-xs" style={{ ...MONO, color: "var(--t3)", minWidth: 34, textAlign: "center" }}>
        {Math.round(scale * 100)}%
      </span>
      <Button variant="ghost" size="icon-xs" onClick={() => onStep(1)} title="Zoom in">
        <Icon name="plus" size={12} label="Zoom in" />
      </Button>
      <Button variant="ghost" size="icon-xs" onClick={onFit} disabled={fitted} title="Fit the whole map in the pane">
        <Icon name="expand" size={12} label="Fit the map" />
      </Button>
    </div>
  );
}

/** The types no link touches. They are part of the ontology and stay pickable — they are simply not somewhere on
 *  the rings, because no link puts them anywhere. */
function UnlinkedTray({ unlinked, types, selected, onSelect }: {
  unlinked: string[];
  types: ReadonlyMap<string, TypeMapRow>;
  selected: string;
  onSelect: (objectType: string) => void;
}) {
  if (unlinked.length === 0) return null;
  return (
    <div data-testid="entity-map-unlinked"
      style={{ borderTop: RULE, background: "var(--bg-0)", padding: "5px 10px", display: "flex", alignItems: "center",
               gap: 6, flexWrap: "wrap" }}>
      <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
        No measured link reaches {unlinked.length === 1 ? "this type" : `these ${unlinked.length} types`}
      </span>
      {unlinked.map((objectType) => (
        <Button key={objectType} variant="ghost" size="xs" onClick={() => onSelect(objectType)}
          aria-current={objectType === selected ? "true" : undefined}
          title={`Open ${types.get(objectType)?.display_name ?? objectType} in the panel`}
          style={objectType === selected ? { background: "var(--bg-hover)" } : undefined}>
          <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>{types.get(objectType)?.display_name ?? objectType}</span>
        </Button>
      ))}
    </div>
  );
}

/** A link's verb and measured cardinality where its line is clear of both cards; the arrow points from → to, the
 *  direction both the verb and the cardinality read in. */
function LinkLabel({ edge, types }: { edge: MapEdge; types: ReadonlyMap<string, TypeMapRow> }) {
  const { link } = edge;
  const from = types.get(link.from)?.display_name ?? link.from;
  const to = types.get(link.to)?.display_name ?? link.to;
  const verb = link.verb || "relates to";
  const degrees = (Math.atan2(edge.y2 - edge.y1, edge.x2 - edge.x1) * 180) / Math.PI;
  const title = [
    `${from} ${verb} ${to} · ${link.cardinality} (${link.measured ? "measured" : "not measured"})`,
    link.business_name ? `name: ${link.business_name}` : "",
    `link names: ${link.name} · ${link.reverse_name}`,
    link.traversable ? "the compiler follows this link" : `refused: ${link.why_not ?? ""}`,
  ].filter(Boolean).join("\n");
  return (
    <div className="aug-fs-xs" title={title} data-testid="entity-map-link"
      style={{ position: "absolute", left: edge.labelX, top: edge.labelY, zIndex: 3,
               transform: "translate(-50%, -50%)", display: "flex", alignItems: "center", gap: 4, whiteSpace: "nowrap",
               padding: "1px 7px", borderRadius: "var(--r-chip)", background: "var(--bg-0)", color: "var(--t2)",
               border: `1px solid ${link.traversable ? "var(--b2)" : "var(--amb2)"}` }}>
      <span>{verb}</span>
      <span aria-hidden="true" style={{ display: "inline-block", transform: `rotate(${degrees}deg)` }}>→</span>
      <span style={{ ...MONO, color: link.traversable ? "var(--t3)" : "var(--amb5)" }}>{link.cardinality}</span>
    </div>
  );
}

interface CardProps {
  type: TypeMapRow;
  x: number;
  y: number;
  lit: boolean;
  selected: boolean;
  onSelect: (objectType: string) => void;
  onCentre: (objectType: string) => void;
}

function FocusCard({ type, x, y, lit, selected, onSelect }: CardProps) {
  const rows: [string, React.ReactNode][] = [
    ["Key", <><span style={MONO}>{type.key}</span>{" "}
      <span className={`aug-tag ${type.key_verified === true ? "aug-tag-green" : type.key_verified === false ? "aug-tag-red" : "aug-tag-gray"}`}>
        {type.key_verified === true ? "unique" : type.key_verified === false ? "not unique" : "unmeasured"}
      </span></>],
    ["Rows", type.rows == null ? "not yet measured" : formatCount(type.rows)],
    ["Binding", <span key="b" style={MONO}>{type.table || "a keyed SELECT"}</span>],
    ["Links", `${type.traversable_links} of ${type.links} followed`],
    ["Actions", formatCount(type.actions)],
    ["Metrics", `${formatCount(type.metrics)} verified`],
    ["Named by", <span key="n" style={MONO}>{type.display_is_key ? "its key" : type.display_property}</span>],
  ];
  return (
    <div className="aug-panel" data-testid="entity-map-focus" data-map-card onClick={() => onSelect(type.object_type)}
      title={`The busiest entity type — ${type.links} ${type.links === 1 ? "link" : "links"}`}
      style={{ position: "absolute", left: x, top: y, transform: "translate(-50%, -50%)", width: 236, zIndex: 2,
               padding: "12px 14px", cursor: "pointer", opacity: lit ? 1 : UNLIT,
               borderColor: selected ? "var(--blue4)" : "var(--blue3)",
               boxShadow: selected ? "0 0 0 2px var(--blue1)" : undefined }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <span style={{ color: "var(--blue3)", display: "inline-flex" }}><Icon name="node" size={16} /></span>
        <span className="aug-fs-ui"
          style={{ color: "var(--t1)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {type.display_name}
        </span>
      </div>
      <dl className="aug-fs-xs"
        style={{ display: "grid", gridTemplateColumns: "max-content minmax(0, 1fr)", columnGap: 10, rowGap: 3, margin: "10px 0 0" }}>
        {rows.map(([label, value]) => (
          <React.Fragment key={label}>
            <dt style={{ color: "var(--t3)" }}>{label}</dt>
            <dd style={{ margin: 0, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{value}</dd>
          </React.Fragment>
        ))}
      </dl>
    </div>
  );
}

function NeighbourCard({ type, x, y, lit, selected, onSelect, onCentre }: CardProps) {
  return (
    <div className="aug-panel" data-testid="entity-map-neighbour" data-map-card
      style={{ position: "absolute", left: x, top: y, transform: "translate(-50%, -50%)", width: 180, zIndex: 2,
               padding: "4px 6px 6px", opacity: lit ? 1 : UNLIT,
               borderColor: selected ? "var(--blue4)" : undefined,
               boxShadow: selected ? "0 0 0 2px var(--blue1)" : undefined }}>
      <Button variant="ghost" size="xs" className="w-full justify-start" onClick={() => onSelect(type.object_type)}
        title={`Light up ${type.display_name} and what it links to`}>
        <span className="aug-fs-sm"
          style={{ color: "var(--t1)", fontWeight: selected ? 600 : 500, overflow: "hidden", textOverflow: "ellipsis" }}>
          {type.display_name}
        </span>
      </Button>
      <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "0 8px" }}>
        <span className="aug-fs-xs"
          style={{ flex: 1, minWidth: 0, color: "var(--t3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {keyWords(type.key_verified)} · {type.links} {type.links === 1 ? "link" : "links"}
        </span>
        <Button variant="ghost" size="icon-xs" onClick={() => onCentre(type.object_type)}
          title={`Put ${type.display_name} in the middle of the map`}>
          <Icon name="target" size={12} label="Centre the map here" />
        </Button>
      </div>
    </div>
  );
}
