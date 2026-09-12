"use client";

/**
 * ON-3b — the entity-type map (ROADMAP §3.15; rebuilt on `@xyflow/react` 2026-09-12).
 *
 * A searchable rail of object types beside a canvas that draws the WHOLE business at once, with the most-linked
 * type in the middle — the map's first claim is which entity everything else hangs from. Picking a type lights it,
 * its links and the types on the other end of them, names those links with their verb and measured cardinality,
 * and opens it in the panel.
 *
 * The canvas is the library's, not ours: pan, zoom and drag are `@xyflow/react`'s, the fifth canvas in this app to
 * use it. A card a person drags STAYS there — the arrangement is remembered per connection in this browser, and
 * `layoutMap` only decides where a card starts before anyone has moved it.
 *
 * Every fact on a card is measured, not a paragraph (`GET /object-types`): whether the key is unique, and how many
 * of its links the compiler follows. The rest is the panel's, which is open beside it. A link the compiler refuses
 * is drawn dashed and says why on hover.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Controls,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
  type NodeProps,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { EntityTypePanel } from "@/components/ontology/EntityTypePanel";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SkeletonRows } from "@/components/ui/motion";
import { getMyPreferences, putMyPreference } from "@/lib/api";
import { CARD, hubOf, layoutMap, litBy } from "@/lib/entityMapLayout";
import { getTypeMap, type TypeMap, type TypeMapRow } from "@/lib/objectTypes";

const MONO: React.CSSProperties = { fontFamily: "var(--font-mono)" };
const RULE = "1px solid var(--b1)";
/** How far a card or a link the picked type does not touch falls back. */
const UNLIT = 0.38;

function keyWords(verified: boolean | null): string {
  return verified === true ? "key unique" : verified === false ? "key not unique" : "key unmeasured";
}

/**
 * Where a person's own arrangement lives: the per-user preference store (SP-3), keyed by connection and schema,
 * so it follows them to their next browser and their next machine. `localStorage` is this device's
 * paint-before-fetch cache and nothing more — the same seam the theme toggle uses.
 */
const LAYOUT_PREFERENCE = "ontology_map_layout";
const CACHE_KEY = "ont-map-layout";
const scopeOf = (connectionId: string, schema?: string) => `${connectionId}:${schema ?? ""}`;

type Positions = Record<string, { x: number; y: number }>;
type Layouts = Record<string, Positions>;

/** Only the positions that are two finite numbers survive a read, wherever they came from. */
function positionsOf(raw: unknown): Layouts {
  if (!raw || typeof raw !== "object") return {};
  const out: Layouts = {};
  for (const [scope, cards] of Object.entries(raw as Record<string, unknown>)) {
    if (!cards || typeof cards !== "object") continue;
    out[scope] = Object.fromEntries(Object.entries(cards as Positions)
      .filter(([, p]) => p && Number.isFinite(p.x) && Number.isFinite(p.y))
      .map(([id, p]) => [id, { x: p.x, y: p.y }]));
  }
  return out;
}

function readCache(): Layouts {
  if (typeof window === "undefined") return {};
  try {
    return positionsOf(JSON.parse(window.localStorage.getItem(CACHE_KEY) ?? "null"));
  } catch {
    return {};                                  // no storage, or something else wrote there: start from the layout
  }
}

function writeCache(layouts: Layouts): void {
  try { window.localStorage.setItem(CACHE_KEY, JSON.stringify(layouts)); } catch { /* the fetch still has it */ }
}

/** Which side of a card a link leaves by — whichever way the other card actually lies, recomputed as cards move,
 *  so a dragged card's links follow it round instead of trailing from where it used to be. */
function side(dx: number, dy: number): "t" | "r" | "b" | "l" {
  return Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "r" : "l") : (dy > 0 ? "b" : "t");
}

interface CardData extends Record<string, unknown> {
  row: TypeMapRow;
  lit: boolean;
  picked: boolean;
}

export function EntityTypeMap({ connectionId, schema }: { connectionId: string; schema?: string }) {
  const [map, setMap] = useState<TypeMap | null>(null);
  const [error, setError] = useState("");
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
        setMap(next);
        setSelected((current) =>
          (current && next.object_types.some((t) => t.object_type === current) ? current : hubOf(next)));
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
  if (!selected || map.object_types.length === 0) {
    return <EmptyState icon="node" title="This ontology has no object types yet." />;
  }
  return (
    <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0 }} data-testid="entity-type-map">
      <TypeRail types={map.object_types} selected={selected} query={query} onQuery={setQuery} onPick={setSelected} />
      <MapCanvas map={map} selected={selected} onSelect={setSelected} scope={scopeOf(connectionId, schema)} />
      <EntityTypePanel connectionId={connectionId} schema={schema} objectType={selected} types={map.object_types}
        version={version} onOpen={setSelected} onChanged={() => setVersion((v) => v + 1)} />
    </div>
  );
}

function TypeRail({ types, selected, query, onQuery, onPick }: {
  types: TypeMapRow[];
  selected: string;
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
              title={`Light ${t.display_name} up on the map and open it here`}
              className="h-auto w-full justify-start py-1.5"
              style={current ? { background: "var(--bg-hover)" } : undefined}>
              <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", minWidth: 0, gap: 1 }}>
                <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: current ? 600 : 500 }}>
                  {t.display_name}
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

/** One entity type on the canvas. Handles on all four sides, invisible: a link leaves by whichever side the type
 *  it reaches actually lies on, and that is recomputed as cards move. */
function EntityCard({ data }: NodeProps<RFNode<CardData>>) {
  const { row, lit, picked } = data;
  return (
    <div className="aug-panel" data-testid="entity-map-card"
      style={{ width: CARD.w, height: CARD.h, padding: "8px 12px", display: "flex", flexDirection: "column",
               justifyContent: "center", gap: 2, opacity: lit ? 1 : UNLIT, cursor: "pointer",
               borderColor: picked ? "var(--blue4)" : undefined,
               boxShadow: picked ? "0 0 0 2px var(--blue1)" : undefined }}>
      {(["t", "r", "b", "l"] as const).map((id) => (
        <React.Fragment key={id}>
          <Handle type="source" id={id} position={SIDES[id]} style={HANDLE} isConnectable={false} />
          <Handle type="target" id={`${id}-in`} position={SIDES[id]} style={HANDLE} isConnectable={false} />
        </React.Fragment>
      ))}
      <span className="aug-fs-sm"
        style={{ color: "var(--t1)", fontWeight: picked ? 600 : 500, overflow: "hidden",
                 textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {row.display_name}
      </span>
      <span className="aug-fs-xs" style={{ color: "var(--t3)", whiteSpace: "nowrap" }}>
        {keyWords(row.key_verified)} · {row.traversable_links} of {row.links} {row.links === 1 ? "link" : "links"}
      </span>
    </div>
  );
}

const SIDES = { t: Position.Top, r: Position.Right, b: Position.Bottom, l: Position.Left } as const;
const HANDLE: React.CSSProperties = { opacity: 0, width: 1, height: 1, minWidth: 1, minHeight: 1, border: "none" };
const NODE_TYPES = { entity: EntityCard };

function MapCanvas({ map, selected, onSelect, scope }: {
  map: TypeMap;
  selected: string;
  onSelect: (objectType: string) => void;
  scope: string;
}) {
  const hub = useMemo(() => hubOf(map) ?? selected, [map, selected]);
  const start = useMemo(() => layoutMap(map, hub), [map, hub]);
  const rows = useMemo(() => new Map(map.object_types.map((t) => [t.object_type, t])), [map]);
  const lit = useMemo(() => litBy(map, selected), [map, selected]);
  /** Every map this person has arranged. The cache is read BEFORE the first paint — reading only from the store
   *  would draw the map at the layout's positions and then jump — and the store's answer wins when it lands. */
  const [layouts, setLayouts] = useState<Layouts>(readCache);
  useEffect(() => {
    let live = true;
    getMyPreferences()
      .then(({ preferences }) => {
        if (!live) return;
        const stored = positionsOf(preferences[LAYOUT_PREFERENCE]);
        setLayouts(stored);
        writeCache(stored);
      })
      // An unreachable store leaves the cached arrangement standing — cosmetic, never blocking.
      .catch(() => {});
    return () => { live = false; };
  }, []);
  const moved = useMemo(() => layouts[scope] ?? {}, [layouts, scope]);

  const [nodes, setNodes, onNodesChange] = useNodesState<RFNode<CardData>>([]);
  const [edges, setEdges] = useEdgesState<RFEdge>([]);

  // The cards: where the layout starts them, or where this person left them.
  useEffect(() => {
    setNodes(start.nodes.flatMap((node) => {
      const row = rows.get(node.objectType);
      if (!row) return [];
      const at = moved[node.objectType] ?? { x: node.x - CARD.w / 2, y: node.y - CARD.h / 2 };
      return [{
        id: node.objectType, type: "entity", position: at, draggable: true,
        data: { row, lit: true, picked: false },
      } satisfies RFNode<CardData>];
    }));
  }, [start, rows, moved, setNodes]);

  // Lighting is a re-read of the cards already on the canvas, never a re-layout: picking a type must not move it.
  useEffect(() => {
    setNodes((current) => current.map((node) => {
      const on = lit.nodes.size === 0 || lit.nodes.has(node.id);
      const picked = node.id === selected;
      return node.data.lit === on && node.data.picked === picked
        ? node
        : { ...node, data: { ...node.data, lit: on, picked } };
    }));
  }, [lit, selected, setNodes]);

  // The links, drawn between whichever sides the two cards now face — recomputed from live positions, so an edge
  // follows a card that was dragged rather than pointing at where it used to be.
  useEffect(() => {
    const at = new Map(nodes.map((n) => [n.id, { x: n.position.x + CARD.w / 2, y: n.position.y + CARD.h / 2 }]));
    setEdges(map.links.flatMap((link) => {
      const [a, b] = [at.get(link.from), at.get(link.to)];
      if (!a || !b || link.from === link.to) return [];
      const on = lit.links.has(link.relationship);
      const verb = link.verb || "relates to";
      return [{
        id: link.relationship, source: link.from, target: link.to,
        sourceHandle: side(b.x - a.x, b.y - a.y), targetHandle: `${side(a.x - b.x, a.y - b.y)}-in`,
        // Only the picked type's links are named: every label at once is what made this map unreadable.
        label: on ? `${verb} · ${link.cardinality}` : undefined,
        labelShowBg: true,
        labelBgPadding: [6, 3] as [number, number],
        labelBgBorderRadius: 4,
        labelBgStyle: { fill: "var(--bg-0)", stroke: link.traversable ? "var(--b2)" : "var(--amb2)" },
        labelStyle: { fill: "var(--t2)", fontSize: "var(--aug-fs-xs)" },
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14,
                     color: link.traversable ? "var(--blue3)" : "var(--amb4)" },
        style: { stroke: link.traversable ? "var(--blue3)" : "var(--amb4)",
                 strokeWidth: on ? 2 : 1.25, strokeDasharray: link.traversable ? undefined : "5 4",
                 opacity: on || lit.links.size === 0 ? 0.95 : UNLIT },
        data: { why: link.traversable ? "" : link.why_not ?? "" },
      } satisfies RFEdge];
    }));
  }, [map.links, nodes, lit, setEdges]);

  /** One drop is one write: the cache for this device's next paint, the store for every other one. */
  const keep = useCallback((positions: Positions) => {
    setLayouts((current) => {
      const next = { ...current, [scope]: positions };
      writeCache(next);
      putMyPreference(LAYOUT_PREFERENCE, next).catch(() => { /* the cache holds it for this device */ });
      return next;
    });
  }, [scope]);

  const drop = useCallback((_e: unknown, node: RFNode) => {
    keep({ ...(layouts[scope] ?? {}), [node.id]: { x: node.position.x, y: node.position.y } });
  }, [keep, layouts, scope]);

  const reset = useCallback(() => keep({}), [keep]);

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, background: "var(--bg-canvas)" }} data-testid="entity-map-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onNodeClick={(_e, node) => onSelect(node.id)}
        onNodeDragStop={drop}
        fitView
        fitViewOptions={{ padding: 0.14, maxZoom: 1 }}
        minZoom={0.2}
        maxZoom={2}
        nodesDraggable
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
        style={{ background: "var(--bg-canvas)" }}
      >
        <Controls showInteractive={false} />
        {Object.keys(moved).length > 0 && (
          <Panel position="top-right">
            <Button variant="outline" size="xs" onClick={reset}
              title="Put every card back where the map started it">
              <Icon name="refresh" size={12} /> Reset arrangement
            </Button>
          </Panel>
        )}
      </ReactFlow>
    </div>
  );
}

export { MONO };
