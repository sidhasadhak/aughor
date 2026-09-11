"use client";

/**
 * ON-3b — the entity-type map (ROADMAP §3.15, amended 2026-09-11).
 *
 * A searchable rail of object types; a canvas centred on ONE of them, its links drawn with their verb and measured
 * cardinality, a neighbour opening its own links a hop at a time; and the entity-type panel beside it. The
 * whole-graph drawing stays on the Ontology layer as the overview — this is the type-level view ON-3's object
 * pages open into.
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
import { hasHiddenNeighbours, layoutMap, visibleRings, type MapEdge } from "@/lib/entityMapLayout";
import { formatCount } from "@/lib/format";
import { getTypeMap, type TypeMap, type TypeMapRow } from "@/lib/objectTypes";

const MONO: React.CSSProperties = { fontFamily: "var(--font-mono)" };
const RULE = "1px solid var(--b1)";

function keyWords(verified: boolean | null): string {
  return verified === true ? "key unique" : verified === false ? "key not unique" : "key unmeasured";
}

/** The type with the most links — where a first look at the map starts. */
function hubOf(map: TypeMap): string | null {
  const degree = new Map<string, number>();
  for (const link of map.links) {
    degree.set(link.from, (degree.get(link.from) ?? 0) + 1);
    degree.set(link.to, (degree.get(link.to) ?? 0) + 1);
  }
  const ranked = [...map.object_types].sort((a, b) =>
    (degree.get(b.object_type) ?? 0) - (degree.get(a.object_type) ?? 0) || a.display_name.localeCompare(b.display_name));
  return ranked[0]?.object_type ?? null;
}

export function EntityTypeMap({ connectionId, schema }: { connectionId: string; schema?: string }) {
  const [map, setMap] = useState<TypeMap | null>(null);
  const [error, setError] = useState("");
  const [focus, setFocus] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [query, setQuery] = useState("");
  // Bumped by a write in the panel (a declared display property, a measurement) so the map and the panel re-read.
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let live = true;
    setError("");
    getTypeMap(connectionId, schema)
      .then((next) => {
        if (!live) return;
        setMap(next);
        setFocus((current) => (current && next.object_types.some((t) => t.object_type === current) ? current : hubOf(next)));
      })
      .catch((e: unknown) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [connectionId, schema, version]);

  const centreOn = (objectType: string) => {
    setFocus(objectType);
    setExpanded(new Set());
  };
  const toggle = (objectType: string) => setExpanded((prev) => {
    const next = new Set(prev);
    if (next.has(objectType)) next.delete(objectType);
    else next.add(objectType);
    return next;
  });

  if (error) {
    return (
      <EmptyState icon="alert" title="The entity-type map could not be read"
        action={<Button variant="outline" size="sm" onClick={() => setVersion((v) => v + 1)}>Try again</Button>}>
        {error}
      </EmptyState>
    );
  }
  if (!map) return <div style={{ flex: 1, padding: 24 }}><SkeletonRows rows={6} /></div>;
  if (!focus || map.object_types.length === 0) {
    return <EmptyState icon="node" title="This ontology has no object types yet." />;
  }
  return (
    <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0 }} data-testid="entity-type-map">
      <TypeRail types={map.object_types} focus={focus} query={query} onQuery={setQuery} onPick={centreOn} />
      <FocusCanvas map={map} focus={focus} expanded={expanded} onFocus={centreOn} onToggle={toggle} />
      <EntityTypePanel connectionId={connectionId} schema={schema} objectType={focus} types={map.object_types}
        version={version} onFocus={centreOn} onChanged={() => setVersion((v) => v + 1)} />
    </div>
  );
}

function TypeRail({ types, focus, query, onQuery, onPick }: {
  types: TypeMapRow[];
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
          const current = t.object_type === focus;
          return (
            <Button key={t.object_type} variant="ghost" size="sm" onClick={() => onPick(t.object_type)}
              aria-current={current ? "true" : undefined} data-testid="entity-rail-row"
              className="h-auto w-full justify-start py-1.5"
              style={current ? { background: "var(--bg-hover)" } : undefined}>
              <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", minWidth: 0, gap: 1 }}>
                <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: current ? 600 : 500 }}>{t.display_name}</span>
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

function FocusCanvas({ map, focus, expanded, onFocus, onToggle }: {
  map: TypeMap;
  focus: string;
  expanded: ReadonlySet<string>;
  onFocus: (objectType: string) => void;
  onToggle: (objectType: string) => void;
}) {
  const layout = useMemo(() => layoutMap(map, focus, expanded), [map, focus, expanded]);
  const rings = useMemo(() => visibleRings(map, focus, expanded), [map, focus, expanded]);
  const types = useMemo(() => new Map(map.object_types.map((t) => [t.object_type, t])), [map]);
  const scroller = useRef<HTMLDivElement>(null);

  const centre = useCallback(() => {
    const el = scroller.current;
    if (!el || el.clientWidth === 0) return;
    el.scrollLeft = Math.max(0, (layout.width - el.clientWidth) / 2);
    el.scrollTop = Math.max(0, (layout.height - el.clientHeight) / 2);
  }, [layout.width, layout.height]);

  // Bring the centre into view when the map re-centres or grows a ring…
  useLayoutEffect(() => { centre(); }, [focus, centre]);
  // …and when the pane itself gets its size: the layer can mount hidden (zero wide), and a centre computed then
  // pushes the centred card off the left edge once it shows.
  useEffect(() => {
    const el = scroller.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let last = "";
    const observer = new ResizeObserver(() => {
      const size = `${el.clientWidth}x${el.clientHeight}`;
      if (size !== last) {
        last = size;
        centre();
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [centre]);

  return (
    <div ref={scroller} data-testid="entity-map-canvas"
      style={{ flex: 1, minWidth: 0, overflow: "auto", background: "var(--bg-1)",
               backgroundImage: "radial-gradient(circle, var(--b2) 1px, transparent 1px)", backgroundSize: "24px 24px" }}>
      <div style={{ position: "relative", width: layout.width, height: layout.height, margin: "0 auto" }}>
        <svg width={layout.width} height={layout.height} aria-hidden="true" style={{ position: "absolute", inset: 0 }}>
          {layout.edges.map((edge) => (
            <line key={edge.link.relationship} x1={edge.x1} y1={edge.y1} x2={edge.x2} y2={edge.y2}
              stroke={edge.link.traversable ? "var(--blue3)" : "var(--amb4)"}
              strokeWidth={edge.link.traversable ? 1.5 : 1.25}
              strokeDasharray={edge.link.traversable ? undefined : "5 4"} opacity={0.7} />
          ))}
        </svg>
        {layout.nodes.map((node) => {
          const type = types.get(node.objectType);
          if (!type) return null;
          if (node.objectType === focus) return <FocusCard key={node.objectType} type={type} x={node.x} y={node.y} />;
          const open = expanded.has(node.objectType);
          return (
            <NeighbourCard key={node.objectType} type={type} x={node.x} y={node.y} open={open}
              canOpen={open || hasHiddenNeighbours(map, node.objectType, rings)} onFocus={onFocus} onToggle={onToggle} />
          );
        })}
        {layout.edges.map((edge) => <LinkLabel key={`label:${edge.link.relationship}`} edge={edge} types={types} />)}
      </div>
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

function FocusCard({ type, x, y }: { type: TypeMapRow; x: number; y: number }) {
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
    <div className="aug-panel" data-testid="entity-map-focus"
      style={{ position: "absolute", left: x, top: y, transform: "translate(-50%, -50%)", width: 236, zIndex: 2,
               padding: "12px 14px", borderColor: "var(--blue3)" }}>
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

function NeighbourCard({ type, x, y, open, canOpen, onFocus, onToggle }: {
  type: TypeMapRow;
  x: number;
  y: number;
  open: boolean;
  canOpen: boolean;
  onFocus: (objectType: string) => void;
  onToggle: (objectType: string) => void;
}) {
  return (
    <div className="aug-panel" data-testid="entity-map-neighbour"
      style={{ position: "absolute", left: x, top: y, transform: "translate(-50%, -50%)", width: 180, zIndex: 2,
               padding: "4px 6px 6px" }}>
      <Button variant="ghost" size="xs" className="w-full justify-start" onClick={() => onFocus(type.object_type)}
        title={`Centre the map on ${type.display_name}`}>
        <span className="aug-fs-sm"
          style={{ color: "var(--t1)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis" }}>
          {type.display_name}
        </span>
      </Button>
      <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "0 8px" }}>
        <span className="aug-fs-xs"
          style={{ flex: 1, minWidth: 0, color: "var(--t3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {keyWords(type.key_verified)} · {type.links} {type.links === 1 ? "link" : "links"}
        </span>
        {canOpen && (
          <Button variant="ghost" size="icon-xs" onClick={() => onToggle(type.object_type)} aria-expanded={open}
            title={open ? `Hide what ${type.display_name} links to` : `Show what ${type.display_name} links to`}>
            <Icon name={open ? "minus" : "plus"} size={12} label={open ? "Collapse" : "Expand"} />
          </Button>
        )}
      </div>
    </div>
  );
}
