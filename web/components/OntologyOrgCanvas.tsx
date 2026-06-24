"use client";

/**
 * OntologyOrgCanvas — the org-level board.
 *
 * Every (connection, schema) pair the org owns is rendered as its *own* entity
 * cluster — the same nodes-and-edges graph the single-connection canvas draws,
 * in its light "compact" form — floating directly on the open dotted background
 * (no heavy card chrome).  A small label above each cluster reads
 * "connection · schema" so you always know what you're looking at.
 *
 * Proximity encodes grouping: clusters belonging to the same connection sit
 * close together in one band; different connections are pushed far apart.  So a
 * 6-schema database reads as one tight neighbourhood, distinct from the next
 * connection's neighbourhood.
 *
 * Schemas are enumerated from the catalog tree (all of them, not just the one in
 * the connection's stored metadata), and each schema's ontology is fetched
 * per-schema via getOntology(conn, schema) — that's how all six beautycommerce
 * schemas show up rather than only "analytics".
 *
 * Nodes are draggable; positions persist per cluster (localStorage).  Trackpad
 * pinch / ⌘-wheel zooms the whole board.
 */

import { useEffect, useMemo, useRef, useState, useLayoutEffect } from "react";
import { useWheelZoom } from "@/lib/useWheelZoom";
import { EntityCluster, measureCluster } from "./OntologyCanvas";
import {
  getCatalogTree,
  getOntology,
  type OntologyGraph,
} from "@/lib/api";

// ── Layout constants ──────────────────────────────────────────────────────────

const SCHEMA_GAP = 56;    // gap between schema clusters of the SAME connection (close)
const CONN_GAP   = 128;   // gap between connection bands (far)
const PAN_PAD    = 1200;  // pannable breathing room on every side (incl. up/left)
const LABEL_H    = 30;    // floating label strip above each cluster
const SHELL_W    = 320;   // placeholder size while a graph loads
const SHELL_H    = 180;

const DOTS = {
  backgroundImage: "radial-gradient(circle, var(--b2) 1.2px, transparent 1.2px)",
  backgroundSize: "26px 26px",
} as const;

// ── Model ───────────────────────────────────────────────────────────────────────

interface ClusterModel {
  connId: string;
  connName: string;
  connType: string;
  schema: string;
  tableCount: number;
  graph: OntologyGraph | null;
  loading: boolean;
  error: boolean;
}

/** Bands = clusters grouped by connection, preserving discovery order. */
function bandsOf(models: ClusterModel[]): { connId: string; connName: string; connType: string; clusters: ClusterModel[] }[] {
  const order: string[] = [];
  const map: Record<string, ClusterModel[]> = {};
  for (const m of models) {
    if (!(m.connId in map)) { map[m.connId] = []; order.push(m.connId); }
    map[m.connId].push(m);
  }
  return order.map(connId => ({
    connId,
    connName: map[connId][0].connName,
    connType: map[connId][0].connType,
    clusters: map[connId],
  }));
}

// ── A single floating cluster (label + open entity graph) ────────────────────────

function ClusterTile({
  model,
  selectedEntityId,
  onSelectEntity,
  scale,
  onOpen,
}: {
  model: ClusterModel;
  selectedEntityId: string | null;
  onSelectEntity: (id: string | null) => void;
  scale: number;
  onOpen: () => void;
}) {
  const { graph, loading, error, schema, connName, connType } = model;

  const size = useMemo(
    () => (graph ? measureCluster(graph, { compact: true }) : { w: SHELL_W, h: SHELL_H }),
    [graph],
  );
  const entityCount = graph ? Object.keys(graph.entities).length : 0;

  // Label — connection · schema, with a type dot.  Click opens the connection.
  const label = (
    <button
      onClick={onOpen}
      className="group flex items-center gap-2 mb-1.5 max-w-full text-left"
      title={`Open ${connName} → ${schema}`}
    >
      <span className="w-2 h-2 rounded-full bg-zinc-500 shrink-0" />
      <span className="text-[12px] font-semibold text-zinc-200 group-hover:text-amber-200 transition truncate">
        {connName}
      </span>
      <span className="text-zinc-500 text-[12px]">·</span>
      <span className="text-[12px] text-zinc-400 truncate">{schema}</span>
      <span className="text-[10px] uppercase tracking-wider text-zinc-500 border border-zinc-700/60 rounded px-1 py-0.5 shrink-0">
        {connType}
      </span>
      {graph && (
        <span className="text-[11px] text-zinc-500 shrink-0">
          {entityCount} {entityCount === 1 ? "entity" : "entities"}
        </span>
      )}
    </button>
  );

  if (loading) {
    return (
      <div style={{ width: SHELL_W }}>
        {label}
        <div className="flex items-center justify-center" style={{ height: SHELL_H }}>
          <div className="w-5 h-5 border-2 border-amber-500/60 border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }
  if (error || !graph || entityCount === 0) {
    return (
      <div style={{ width: SHELL_W }}>
        {label}
        <div className="flex items-center justify-center text-[11px] text-zinc-500" style={{ height: 90 }}>
          no ontology yet
        </div>
      </div>
    );
  }

  return (
    <div style={{ width: size.w }}>
      {label}
      <div style={{ width: size.w, height: size.h, position: "relative" }}>
        <EntityCluster
          graph={graph}
          compact
          storageKey={`${model.connId}:${schema}`}
          scale={scale}
          selectedEntityId={selectedEntityId}
          onSelectEntity={onSelectEntity}
          showColLabels={false}
          showCausal={false}
        />
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
  const [models, setModels] = useState<ClusterModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [zoom, setZoom] = useState(0.65);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);

  const scrollRef  = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [natural, setNatural] = useState({ w: 1400, h: 900 });

  useWheelZoom(scrollRef, zoom, setZoom, { min: 0.15, max: 1.5 });

  // Enumerate every (connection, schema) from the catalog tree, render a shell
  // per pair immediately, then fill each as its per-schema ontology resolves.
  useEffect(() => {
    let alive = true;
    getCatalogTree()
      .then(tree => {
        if (!alive) return;
        const entries = tree.sections.flatMap(s => s.entries);
        const shells: ClusterModel[] = entries.flatMap(e =>
          e.schemas.map(sc => ({
            connId: e.conn_id,
            connName: e.name,
            connType: e.conn_type,
            schema: sc.name,
            tableCount: sc.tables?.length ?? 0,
            graph: null,
            loading: true,
            error: false,
          })),
        );
        setModels(shells);
        setLoading(false);
        for (const sh of shells) {
          getOntology(sh.connId, sh.schema)
            .then(graph => alive && setModels(prev => prev.map(m =>
              m.connId === sh.connId && m.schema === sh.schema ? { ...m, graph, loading: false } : m)))
            .catch(() => alive && setModels(prev => prev.map(m =>
              m.connId === sh.connId && m.schema === sh.schema ? { ...m, loading: false, error: true } : m)));
        }
      })
      .catch(() => alive && setLoading(false));
    return () => { alive = false; };
  }, []);

  const bands = useMemo(() => bandsOf(models), [models]);

  useLayoutEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    setNatural({ w: el.offsetWidth, h: el.offsetHeight });
  }, [models, zoom]);

  // Center the board on the content on first paint, leaving equal room to pan in
  // every direction (the board used to be pinned to 0,0 — unreachable up/left).
  const centered = useRef(false);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || loading || centered.current || natural.w <= 1) return;
    centered.current = true;
    el.scrollLeft = PAN_PAD * zoom - 40;
    el.scrollTop  = PAN_PAD * zoom - 40;
  }, [loading, natural.w, natural.h, zoom]);

  const connCount = bands.length;
  const schemaCount = models.length;

  return (
    <div className="w-full h-full relative" style={{ background: "var(--bg-1)" }}>
      {/* Title */}
      <div className="absolute top-3 left-3 z-20 bg-zinc-900/80 backdrop-blur-sm border border-zinc-700/50 rounded-lg px-3.5 py-2 pointer-events-none">
        <p className="text-[12px] font-semibold text-zinc-200">Organization Ontology</p>
        <p className="text-[11px] text-zinc-500">{connCount} connections · {schemaCount} schemas · drag nodes · pinch to zoom</p>
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
          <div className="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div ref={scrollRef} className="w-full h-full overflow-auto" style={DOTS}>
          <div style={{ width: (natural.w + PAN_PAD * 2) * zoom, height: (natural.h + PAN_PAD * 2) * zoom, position: "relative", minWidth: "100%", minHeight: "100%" }}>
            <div
              ref={contentRef}
              className="inline-flex flex-col"
              style={{
                gap: CONN_GAP,
                paddingTop: CONN_GAP,
                paddingLeft: CONN_GAP,
                paddingRight: CONN_GAP,
                paddingBottom: CONN_GAP,
                transform: `translate(${PAN_PAD * zoom}px, ${PAN_PAD * zoom}px) scale(${zoom})`,
                transformOrigin: "top left",
                position: "absolute",
                top: 0,
                left: 0,
              }}
            >
              {/* One band per connection — schemas packed close inside the band. */}
              {bands.map(band => (
                <div key={band.connId} className="flex flex-wrap items-start" style={{ gap: SCHEMA_GAP }}>
                  {band.clusters.map(c => (
                    <ClusterTile
                      key={`${c.connId}:${c.schema}`}
                      model={c}
                      selectedEntityId={selectedEntityId}
                      onSelectEntity={setSelectedEntityId}
                      scale={zoom}
                      onOpen={() => onOpenConnection(c.connId)}
                    />
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
