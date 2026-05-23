"use client";

import { useRef, useLayoutEffect, useState } from "react";
import TableIcon from "@atlaskit/icon/core/table";
import { RichSchema, SchemaTable, SchemaJoin } from "@/lib/api";

// ── Layout constants ──────────────────────────────────────────────────────────
const CARD_W     = 264;   // card body width
const LABEL_H    = 18;    // "Table" label above the card
const HEADER_H   = 54;    // card header (icon + name + row count)
const ROW_H      = 26;    // height of each column row
const FOOTER_H   = 32;    // "Show N more" button
const LAYER_GAP  = 130;   // horizontal gap between layers
const CARD_GAP_Y = 40;    // vertical gap between cards in the same layer
const PAD        = 56;    // canvas edge padding

// ── Layout engine ─────────────────────────────────────────────────────────────

interface CardLayout {
  table: SchemaTable;
  layer: number;
  x: number;
  y: number;           // top of the wrapper (includes label)
  wrapperH: number;    // total wrapper height (label + card body)
}

function computeLayout(
  tables: SchemaTable[],
  joins: SchemaJoin[],
  expanded: Set<string>,
  pkSet: Set<string>,
): { cards: CardLayout[]; canvasW: number; canvasH: number } {

  // Degree counting: t1 = FK side (references), t2 = PK side (referenced)
  const outDeg: Record<string, number> = {};
  const inDeg:  Record<string, number> = {};
  for (const t of tables) { outDeg[t.name] = 0; inDeg[t.name] = 0; }
  for (const j of joins) {
    outDeg[j.t1] = (outDeg[j.t1] ?? 0) + 1;
    inDeg[j.t2]  = (inDeg[j.t2]  ?? 0) + 1;
  }

  // Layer assignment
  //   0 — pure dimensions (only referenced, never reference others)
  //   1 — bridge tables   (both reference and are referenced)
  //   2 — pure facts      (reference others, never referenced themselves)
  //   3 — isolated        (no joins at all)
  const layerOf: Record<string, number> = {};
  for (const t of tables) {
    const o = outDeg[t.name], i = inDeg[t.name];
    if (o === 0 && i === 0) layerOf[t.name] = 3;
    else if (o === 0)       layerOf[t.name] = 0;  // pure dimension
    else if (i === 0)       layerOf[t.name] = 2;  // pure fact
    else                    layerOf[t.name] = 1;  // bridge
  }

  // Group & sort alphabetically within each layer
  const byLayer: Record<number, SchemaTable[]> = {};
  for (const t of tables) {
    const l = layerOf[t.name];
    (byLayer[l] ??= []).push(t);
  }
  for (const arr of Object.values(byLayer))
    arr.sort((a, b) => a.name.localeCompare(b.name));

  // Compute wrapper height for a given table.
  // Default: only PK/FK columns visible. Expanded: all columns.
  function wrapperH(t: SchemaTable): number {
    const isExp = expanded.has(t.name);
    const keyCols = t.columns.filter(
      c => pkSet.has(`${t.name}.${c.name}`) || c.is_fk,
    );
    const visCols = isExp ? t.columns.length : keyCols.length;
    const hasMore = !isExp && t.columns.length > keyCols.length;
    return LABEL_H + HEADER_H + visCols * ROW_H + (hasMore ? FOOTER_H : 0);
  }

  // Only use layers that contain tables; map to sequential X positions
  const usedLayers = ([0, 1, 2, 3] as number[]).filter(l => byLayer[l]?.length);
  const layerX: Record<number, number> = {};
  usedLayers.forEach((l, i) => {
    layerX[l] = PAD + i * (CARD_W + LAYER_GAP);
  });

  // Stack cards top-to-bottom within each layer
  const cards: CardLayout[] = [];
  for (const layer of usedLayers) {
    let y = PAD;
    for (const t of byLayer[layer]) {
      const h = wrapperH(t);
      cards.push({ table: t, layer, x: layerX[layer], y, wrapperH: h });
      y += h + CARD_GAP_Y;
    }
  }

  const canvasW = (usedLayers.length > 0
    ? layerX[usedLayers[usedLayers.length - 1]] + CARD_W + PAD
    : PAD * 2 + CARD_W);

  const canvasH = Math.max(
    400,
    ...usedLayers.map(l => {
      let h = PAD;
      for (const t of byLayer[l]) h += wrapperH(t) + CARD_GAP_Y;
      return h + PAD - CARD_GAP_Y;
    }),
  );

  return { cards, canvasW, canvasH };
}

// ── PK inference ──────────────────────────────────────────────────────────────

function buildPkSet(tables: SchemaTable[], joins: SchemaJoin[]): Set<string> {
  const pks = new Set<string>();
  for (const t of tables)
    for (const c of t.columns)
      if (c.name.toLowerCase() === "id") pks.add(`${t.name}.${c.name}`);
  for (const j of joins)
    pks.add(`${j.t2}.${j.c2}`);
  return pks;
}

// Sort columns: PKs → FKs → rest (alpha) so key columns are always in the visible slice
function sortCols(table: SchemaTable, pkSet: Set<string>) {
  return [...table.columns].sort((a, b) => {
    const rank = (c: typeof a) =>
      pkSet.has(`${table.name}.${c.name}`) ? 0 : c.is_fk ? 1 : 2;
    return rank(a) !== rank(b) ? rank(a) - rank(b) : a.name.localeCompare(b.name);
  });
}

// ── Table card ────────────────────────────────────────────────────────────────

interface TableCardProps {
  layout: CardLayout;
  pkSet: Set<string>;
  expanded: boolean;
  onExpand: () => void;
  registerRow: (key: string, el: HTMLDivElement | null) => void;
}

function TableCard({ layout, pkSet, expanded, onExpand, registerRow }: TableCardProps) {
  const { table } = layout;
  const sorted = sortCols(table, pkSet);
  const keyCols = sorted.filter(c => pkSet.has(`${table.name}.${c.name}`) || c.is_fk);
  const otherCols = sorted.filter(c => !pkSet.has(`${table.name}.${c.name}`) && !c.is_fk);
  const visible = expanded ? sorted : keyCols;
  const hiddenCount = otherCols.length;

  return (
    <div
      className="absolute flex flex-col gap-1"
      style={{ left: layout.x, top: layout.y, width: CARD_W }}
    >
      {/* "Table" label */}
      <span className="text-[10px] text-zinc-500 px-0.5" style={{ height: LABEL_H, lineHeight: `${LABEL_H}px` }}>
        Table
      </span>

      <div className="rounded-lg border border-zinc-600 overflow-hidden shadow-lg shadow-black/40">
        {/* Header */}
        <div
          className="flex items-center gap-2.5 px-3 bg-zinc-900 border-b border-zinc-700/80"
          style={{ height: HEADER_H }}
        >
          <div className="w-7 h-7 rounded bg-indigo-950/80 border border-indigo-800/50 flex items-center justify-center text-indigo-300 shrink-0">
            <TableIcon label="Table" size="small" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[12px] font-semibold font-mono text-zinc-100 truncate leading-snug">
              {table.name}
            </div>
            {table.row_count && (
              <div className="text-[10px] font-mono text-zinc-500 leading-none mt-px">
                {Number(table.row_count).toLocaleString()} rows
              </div>
            )}
          </div>
        </div>

        {/* Column rows */}
        <div className="bg-zinc-800 divide-y divide-zinc-700/40">
          {visible.map((col) => {
            const isPk = pkSet.has(`${table.name}.${col.name}`);
            const type = col.type.replace(/\(.*\)/, "").trim();
            return (
              <div
                key={col.name}
                ref={el => registerRow(`${table.name}:${col.name}`, el as HTMLDivElement | null)}
                className="flex items-center gap-2 px-3 hover:bg-zinc-700/30 transition-colors"
                style={{ height: ROW_H }}
              >
                {/* Badge — fixed 28px slot */}
                <div className="w-7 flex items-center justify-center shrink-0">
                  {isPk ? (
                    <span className="text-[9px] font-bold text-amber-400 border border-amber-400/50 rounded px-[3px] py-px leading-tight">
                      PK
                    </span>
                  ) : col.is_fk ? (
                    <span className="text-[9px] font-bold text-violet-400 border border-violet-400/50 rounded px-[3px] py-px leading-tight">
                      FK
                    </span>
                  ) : null}
                </div>
                <span className="flex-1 text-[11px] font-mono text-zinc-300 truncate min-w-0">
                  {col.name}
                </span>
                <span className="text-[10px] font-mono text-zinc-500 shrink-0 pl-2">
                  {type}
                </span>
              </div>
            );
          })}
        </div>

        {/* Show more footer */}
        {hiddenCount > 0 && (
          <button
            onClick={onExpand}
            className="w-full bg-zinc-800 text-[11px] text-zinc-500 hover:text-zinc-300 hover:bg-zinc-700/50 transition-colors border-t border-zinc-700/50 text-center"
            style={{ height: FOOTER_H, lineHeight: `${FOOTER_H}px` }}
          >
            {expanded ? "Show less" : `Show ${hiddenCount} more column${hiddenCount !== 1 ? "s" : ""}`}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Connection lines ──────────────────────────────────────────────────────────

interface Conn {
  x1: number; y1: number;
  x2: number; y2: number;
  match: "exact" | "inferred";
}

function Connections({ lines, w, h }: { lines: Conn[]; w: number; h: number }) {
  if (!lines.length) return null;
  return (
    <svg
      className="absolute inset-0 pointer-events-none"
      width={w} height={h}
      style={{ zIndex: 0 }}
    >
      <defs>
        <marker id="mk-inf"   markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
          <path d="M0,1 L6,3.5 L0,6 Z" fill="#575755" />
        </marker>
        <marker id="mk-exact" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
          <path d="M0,1 L6,3.5 L0,6 Z" fill="#7c6fd4" />
        </marker>
      </defs>
      {lines.map((c, i) => {
        const goRight = c.x2 > c.x1;
        const dx = Math.max(50, Math.abs(c.x2 - c.x1) * 0.45);
        const cpx1 = c.x1 + (goRight ? dx : -dx);
        const cpx2 = c.x2 - (goRight ? dx : -dx);
        const d = `M${c.x1},${c.y1} C${cpx1},${c.y1} ${cpx2},${c.y2} ${c.x2},${c.y2}`;
        const exact = c.match === "exact";
        return (
          <path
            key={i}
            d={d}
            fill="none"
            stroke={exact ? "#7c6fd4" : "#575755"}
            strokeWidth={exact ? 1.5 : 1}
            strokeDasharray={exact ? undefined : "5 3"}
            markerEnd={exact ? "url(#mk-exact)" : "url(#mk-inf)"}
            opacity={0.85}
          />
        );
      })}
    </svg>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

export function ERDiagram({ schema }: { schema: RichSchema }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rowRefs      = useRef<Record<string, HTMLDivElement | null>>({});
  const [lines, setLines]       = useState<Conn[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const pkSet = buildPkSet(schema.tables, schema.joins);
  const { cards, canvasW, canvasH } = computeLayout(schema.tables, schema.joins, expanded, pkSet);
  const cardMap = Object.fromEntries(cards.map(c => [c.table.name, c]));

  const registerRow = (key: string, el: HTMLDivElement | null) => {
    rowRefs.current[key] = el;
  };

  const toggleExpand = (name: string) =>
    setExpanded(prev => { const s = new Set(prev); s.has(name) ? s.delete(name) : s.add(name); return s; });

  // Measure column row positions → draw connection lines
  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const measure = () => {
      const cr = container.getBoundingClientRect();
      const sl = container.scrollLeft;
      const st = container.scrollTop;

      const newLines: Conn[] = [];
      for (const j of schema.joins) {
        const srcCard = cardMap[j.t1];
        const tgtCard = cardMap[j.t2];
        if (!srcCard || !tgtCard) continue;

        // Y anchored to the column row if visible, else card body center
        const getY = (tableName: string, colName: string, card: CardLayout) => {
          const el = rowRefs.current[`${tableName}:${colName}`];
          if (el) {
            const r = el.getBoundingClientRect();
            return r.top + r.height / 2 - cr.top + st;
          }
          // Fallback: center of card body
          return card.y + LABEL_H + HEADER_H + (card.wrapperH - LABEL_H - HEADER_H) / 2;
        };

        const y1 = getY(j.t1, j.c1, srcCard);
        const y2 = getY(j.t2, j.c2, tgtCard);

        // Exit/enter from the horizontal edge closest to the other table
        let x1: number, x2: number;
        if (srcCard.x + CARD_W <= tgtCard.x) {
          x1 = srcCard.x + CARD_W; x2 = tgtCard.x;       // src left of tgt
        } else {
          x1 = srcCard.x;          x2 = tgtCard.x + CARD_W; // src right of tgt
        }

        newLines.push({ x1, y1, x2, y2, match: j.match });
      }
      setLines(newLines);
    };

    const raf = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(raf);
  }, [schema, expanded]);  // re-measure when schema or expansion changes

  if (!schema.tables.length) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="text-xs text-zinc-500">No tables found.</span>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="w-full h-full overflow-auto"
      style={{
        backgroundImage: "radial-gradient(circle, #3f3f3d 1px, transparent 1px)",
        backgroundSize: "20px 20px",
      }}
    >
      <div className="relative" style={{ width: canvasW, height: canvasH }}>
        <Connections lines={lines} w={canvasW} h={canvasH} />
        {cards.map(card => (
          <TableCard
            key={card.table.name}
            layout={card}
            pkSet={pkSet}
            expanded={expanded.has(card.table.name)}
            onExpand={() => toggleExpand(card.table.name)}
            registerRow={registerRow}
          />
        ))}
      </div>
    </div>
  );
}
