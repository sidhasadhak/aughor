"use client";

/**
 * OntologyOrgCanvas — the org-level board.
 *
 * One bounding box per connection (database).  Inside each box, the
 * connection's schema(s) are sub-boxed, and each schema holds the *actual*
 * entity cluster — the same nodes-and-edges graph the single-connection canvas
 * draws (customer_order ──placed by──▶ Customer …), rendered via the shared
 * `EntityCluster`.  So the org view is literally "a big box (connection) full
 * of the relationship clusters derived from its tables", grouped connection →
 * schema, exactly as you'd read the business across the org.
 *
 * Trackpad pinch / ⌘-wheel (useWheelZoom) zooms the whole board: out to see
 * every connection at once, in to read individual entities.  Cross-connection
 * edges are intentionally not drawn (that's a separate architecture).
 *
 * Prototype scope: composes the existing per-connection `getOntology` endpoint
 * client-side (no backend changes).  One graph = one (connection, schema) pair,
 * so today each connection box holds a single schema cluster; the layout is
 * already structured to hold several once multi-schema graphs arrive.
 */

import { useEffect, useMemo, useRef, useState, useLayoutEffect } from "react";
import { useWheelZoom } from "@/lib/useWheelZoom";
import { EntityCluster, measureCluster } from "./OntologyCanvas";
import {
  getConnections,
  getOntology,
  type Connection,
  type OntologyGraph,
} from "@/lib/api";

// ── Layout constants ──────────────────────────────────────────────────────────

const GAP            = 72;    // gap between connection boxes
const BOX_PAD        = 18;    // inner padding of a connection box
const SCHEMA_PAD     = 14;    // padding inside a schema sub-box (around the cluster)
const SHELL_W        = 420;   // placeholder cluster width while a graph loads
const SHELL_H        = 240;
const MAX_COLS       = 3;

const DOTS = {
  backgroundImage: "radial-gradient(circle, #2a3140 1.2px, transparent 1.2px)",
  backgroundSize: "24px 24px",
} as const;

// ── Per-connection model ──────────────────────────────────────────────────────

interface BoxModel {
  conn: Connection;
  graph: OntologyGraph | null;
  loading: boolean;
  error: boolean;
}

/** A connection's schemas — today always one graph per connection. */
type SchemaGroup = { schema: string; graph: OntologyGraph };

function schemaGroups(graph: OntologyGraph | null): SchemaGroup[] {
  if (!graph) return [];
  return [{ schema: graph.schema_name || "public", graph }];
}

// ── A single schema sub-box (label + real entity cluster) ───────────────────────

function SchemaBox({
  group,
  selectedEntityId,
  onSelectEntity,
}: {
  group: SchemaGroup;
  selectedEntityId: string | null;
  onSelectEntity: (id: string | null) => void;
}) {
  const { graph } = group;
  const size = useMemo(() => measureCluster(graph), [graph]);
  const entityCount = Object.keys(graph.entities).length;
  const relCount    = Object.keys(graph.relationships).length;

  return (
    <div className="rounded-lg border border-zinc-700/50 bg-zinc-950/30 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-zinc-700/40 bg-zinc-900/40">
        <span className="w-1.5 h-1.5 rounded-full bg-sky-400 shrink-0" />
        <span className="text-[12px] font-medium text-zinc-200 truncate">{group.schema}</span>
        <span className="text-[11px] text-zinc-500 ml-auto shrink-0">
          {entityCount} entities · {relCount} rels
        </span>
      </div>
      <div style={{ ...DOTS, padding: SCHEMA_PAD }}>
        <div style={{ width: size.w, height: size.h, position: "relative" }}>
          <EntityCluster
            graph={graph}
            selectedEntityId={selectedEntityId}
            onSelectEntity={onSelectEntity}
            showColLabels={false}
            showCausal={false}
          />
        </div>
      </div>
    </div>
  );
}

// ── A single connection box ──────────────────────────────────────────────────────

function ConnectionBox({
  model,
  width,
  selectedEntityId,
  onSelectEntity,
  onOpen,
}: {
  model: BoxModel;
  width: number;
  selectedEntityId: string | null;
  onSelectEntity: (id: string | null) => void;
  onOpen: () => void;
}) {
  const { conn, graph, loading, error } = model;
  const groups = useMemo(() => schemaGroups(graph), [graph]);
  const totalEntities = groups.reduce((n, g) => n + Object.keys(g.graph.entities).length, 0);
  const totalRels     = groups.reduce((n, g) => n + Object.keys(g.graph.relationships).length, 0);

  return (
    <div
      style={{ width }}
      className="rounded-2xl border border-zinc-700/60 bg-zinc-900/50 backdrop-blur-sm shadow-xl shadow-black/30 overflow-hidden flex flex-col"
    >
      {/* Connection header — click to drill into the single-connection canvas */}
      <button
        onClick={onOpen}
        className="text-left px-4 pt-3.5 pb-3 border-b border-zinc-700/50 hover:bg-zinc-800/40 transition group"
      >
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-violet-400 shrink-0" />
          <p className="text-[15px] font-semibold text-zinc-100 truncate flex-1 group-hover:text-violet-200 transition">
            {conn.name}
          </p>
          <span className="text-[10px] uppercase tracking-wider text-zinc-500 border border-zinc-700 rounded px-1.5 py-0.5 shrink-0">
            {conn.conn_type}
          </span>
        </div>
        {graph && (
          <div className="flex items-center gap-3 mt-1.5 text-[12px] text-zinc-400">
            <span><strong className="text-zinc-200 font-semibold">{totalEntities}</strong> entities</span>
            <span><strong className="text-zinc-200 font-semibold">{totalRels}</strong> relationships</span>
            <span><strong className="text-zinc-200 font-semibold">{groups.length}</strong> schema{groups.length === 1 ? "" : "s"}</span>
          </div>
        )}
      </button>

      {/* Body — one cluster per schema */}
      <div className="flex-1" style={{ padding: BOX_PAD, display: "flex", flexDirection: "column", gap: BOX_PAD }}>
        {loading && (
          <div className="flex items-center justify-center" style={{ minHeight: SHELL_H }}>
            <div className="w-6 h-6 border-2 border-violet-500/70 border-t-transparent rounded-full animate-spin" />
          </div>
        )}
        {error && (
          <p className="text-[12px] text-zinc-500 text-center" style={{ minHeight: SHELL_H, display: "flex", alignItems: "center", justifyContent: "center" }}>
            No ontology yet — builds on next query.
          </p>
        )}
        {groups.map(g => (
          <SchemaBox
            key={g.schema}
            group={g}
            selectedEntityId={selectedEntityId}
            onSelectEntity={onSelectEntity}
          />
        ))}
      </div>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

export function OntologyOrgCanvas({
  onOpenConnection,
}: {
  onOpenConnection: (connId: string) => void;
}) {
  const [boxes, setBoxes] = useState<BoxModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [zoom, setZoom] = useState(0.45);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);

  const scrollRef  = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [natural, setNatural] = useState({ w: 1400, h: 900 });

  useWheelZoom(scrollRef, zoom, setZoom, { min: 0.15, max: 1.5 });

  // Render box shells immediately from the connection list, then fill each in
  // as its graph resolves (progressive — don't block on the slowest connection).
  useEffect(() => {
    let alive = true;
    getConnections()
      .then(conns => {
        if (!alive) return;
        setBoxes(conns.map(conn => ({ conn, graph: null, loading: true, error: false })));
        setLoading(false);
        conns.forEach(conn => {
          getOntology(conn.id)
            .then(graph => alive && setBoxes(prev => prev.map(b => b.conn.id === conn.id ? { ...b, graph, loading: false } : b)))
            .catch(() => alive && setBoxes(prev => prev.map(b => b.conn.id === conn.id ? { ...b, loading: false, error: true } : b)));
        });
      })
      .catch(() => alive && setLoading(false));
    return () => { alive = false; };
  }, []);

  // Box widths track their widest schema cluster; the row budget fits the widest
  // box so flex-wrap packs a near-square grid.
  const boxWidths = useMemo(
    () => boxes.map(b => {
      const groups = schemaGroups(b.graph);
      const clusterW = groups.length
        ? Math.max(...groups.map(g => measureCluster(g.graph).w))
        : SHELL_W;
      return clusterW + SCHEMA_PAD * 2 + BOX_PAD * 2;
    }),
    [boxes],
  );
  const maxBoxW = Math.max(SHELL_W + SCHEMA_PAD * 2 + BOX_PAD * 2, ...boxWidths);
  const cols    = Math.max(1, Math.min(MAX_COLS, Math.ceil(Math.sqrt(boxes.length || 1))));
  const innerW  = cols * maxBoxW + (cols + 1) * GAP;

  useLayoutEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    setNatural({ w: el.offsetWidth, h: el.offsetHeight });
  }, [boxes, innerW]);

  return (
    <div className="w-full h-full relative" style={{ background: "#11171D" }}>
      {/* Title */}
      <div className="absolute top-3 left-3 z-20 bg-zinc-900/80 backdrop-blur-sm border border-zinc-700/50 rounded-lg px-3.5 py-2 pointer-events-none">
        <p className="text-[12px] font-semibold text-zinc-200">Organization Ontology</p>
        <p className="text-[11px] text-zinc-500">{boxes.length} connections · pinch / ⌘-scroll to zoom</p>
      </div>

      {/* Zoom controls */}
      <div className="absolute top-3 right-3 z-20 flex items-center gap-1 bg-zinc-900/80 backdrop-blur-sm border border-zinc-700/50 rounded-lg px-2.5 py-1.5 select-none">
        <button
          onClick={() => setZoom(z => Math.max(0.15, +(z - 0.05).toFixed(2)))}
          className="w-5 h-5 flex items-center justify-center text-zinc-400 hover:text-zinc-200 text-base font-mono transition"
        >−</button>
        <span className="text-[11px] font-mono text-zinc-400 w-8 text-center">{Math.round(zoom * 100)}%</span>
        <button
          onClick={() => setZoom(z => Math.min(1.5, +(z + 0.05).toFixed(2)))}
          className="w-5 h-5 flex items-center justify-center text-zinc-400 hover:text-zinc-200 text-base font-mono transition"
        >+</button>
      </div>

      {loading ? (
        <div className="w-full h-full flex items-center justify-center">
          <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div ref={scrollRef} className="w-full h-full overflow-auto">
          <div style={{ width: natural.w * zoom, height: natural.h * zoom, position: "relative", minWidth: "100%", minHeight: "100%" }}>
            <div
              ref={contentRef}
              className="flex flex-wrap items-start"
              style={{
                width: innerW,
                gap: GAP,
                paddingTop: GAP + 28,   // clear the floating title card
                paddingLeft: GAP,
                paddingRight: GAP,
                paddingBottom: GAP,
                transform: `scale(${zoom})`,
                transformOrigin: "top left",
                position: "absolute",
                top: 0,
                left: 0,
              }}
            >
              {boxes.map((b, i) => (
                <ConnectionBox
                  key={b.conn.id}
                  model={b}
                  width={boxWidths[i] ?? SHELL_W}
                  selectedEntityId={selectedEntityId}
                  onSelectEntity={setSelectedEntityId}
                  onOpen={() => onOpenConnection(b.conn.id)}
                />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
