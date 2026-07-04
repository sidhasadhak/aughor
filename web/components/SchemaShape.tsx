"use client";

import { useEffect, useState } from "react";
import { formatCount } from "@/lib/format";
import {
  getSchemaProfile,
  getExplorationFindings,
  getCatalogTree,
  type SchemaProfile,
  type TableProfileData,
  type ColumnProfileData,
  type DistributionProfile,
} from "@/lib/api";

// ── Schema Shape ───────────────────────────────────────────────────────────────
// The column-profiler view (table grain, null rates, distinct counts, top values)
// MERGED with the per-column distribution shape (formerly the Domains "Distributions"
// section). Used in two places: the Catalog schema panel (scoped to one schema's
// tables) and the Domains layer (relevance-ordered by domain entities).

const bare = (n: string) => n.split(".").pop()!.toLowerCase();

// Distribution shape → pill colours + mini-bar profile (shared signature with the
// old ExplorationPanel Distributions section so the visual language is unchanged).
const DIST_SHAPE_PILL: Record<string, { label: string; text: string; bar: string }> = {
  fraction_0_1: { label: "0–1",         text: "var(--grn4)",  bar: "var(--grn3)" },
  normal:       { label: "Normal",      text: "var(--blue4)", bar: "var(--blue3)" },
  concentrated: { label: "Concentrated", text: "var(--vio4)",  bar: "var(--vio3)" },
  skewed_right: { label: "R-skew",      text: "var(--amb4)",  bar: "var(--amb3)" },
  skewed_left:  { label: "L-skew",      text: "var(--amb4)",  bar: "var(--amb3)" },
  uniform:      { label: "Uniform",     text: "var(--grn4)",  bar: "var(--grn3)" },
  bimodal:      { label: "Bimodal",     text: "var(--red4)",  bar: "var(--red3)" },
};

function miniBarHeights(shape: string): number[] {
  switch (shape) {
    case "normal":       return [4, 8, 22, 24, 16, 6];
    case "fraction_0_1": return [6, 14, 24, 16, 8, 4];
    case "concentrated": return [3, 10, 24, 18, 8, 3];
    case "skewed_right": return [24, 20, 14, 8, 4, 2];
    case "skewed_left":  return [2, 4, 8, 14, 20, 24];
    case "uniform":      return [20, 22, 22, 21, 20, 21];
    case "bimodal":      return [20, 8, 4, 8, 22, 16];
    default:             return [10, 14, 18, 16, 12, 8];
  }
}

function ShapeCell({ dist }: { dist: DistributionProfile | undefined }) {
  if (!dist || dist.shape === "unknown") {
    return <span style={{ fontSize: 10, color: "var(--t4)" }}>—</span>;
  }
  const pill = DIST_SHAPE_PILL[dist.shape] ?? { label: dist.shape, text: "var(--t3)", bar: "var(--b3)" };
  const bars = miniBarHeights(dist.shape);
  const maxH = Math.max(...bars);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }} title={`${pill.label} distribution`}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 1, height: 14 }}>
        {bars.map((h, i) => (
          <div key={i} style={{ width: 2.5, height: `${Math.max(2, (h / maxH) * 14)}px`, background: pill.bar, borderRadius: 1 }} />
        ))}
      </div>
      <span style={{ fontSize: 9, color: pill.text, whiteSpace: "nowrap" }}>{pill.label}</span>
    </div>
  );
}

function NullBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const color = pct > 20 ? "var(--r3)" : pct > 5 ? "var(--amb3)" : "var(--grn3)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 40, height: 4, background: "var(--bg-3)", borderRadius: 2 }}>
        <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 10, color: pct > 10 ? color : "var(--t4)", fontVariantNumeric: "tabular-nums" }}>
        {pct}%
      </span>
    </div>
  );
}

const GRID = "minmax(120px,1fr) 64px 78px 70px 116px minmax(96px,1fr)";

function TableCard({
  table,
  tableProfile,
  columns,
  distFor,
}: {
  table: string;
  tableProfile: TableProfileData | undefined;
  columns: ColumnProfileData[];
  distFor: (col: ColumnProfileData) => DistributionProfile | undefined;
}) {
  const [expanded, setExpanded] = useState(true);
  const rowCount = tableProfile?.row_count;
  const grain = tableProfile?.grain_column;
  const ts = tableProfile?.primary_timestamp;
  const dr = tableProfile?.date_range;

  return (
    <div style={{ background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: 7, overflow: "hidden", flexShrink: 0 }}>
      <button
        onClick={() => setExpanded(e => !e)}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 10,
          padding: "10px 14px", background: "none", border: "none", cursor: "pointer", textAlign: "left",
        }}
        onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-hover)")}
        onMouseLeave={e => (e.currentTarget.style.background = "none")}
      >
        <span style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)", fontFamily: "var(--font-mono)", flex: 1 }}>
          {table}
        </span>
        {rowCount != null && (
          <span style={{ fontSize: 10, color: "var(--t3)", background: "var(--bg-2)", padding: "1px 6px", borderRadius: 3 }}>
            {formatCount(rowCount)} rows
          </span>
        )}
        {grain && (
          <span style={{ fontSize: 10, color: "var(--blue4)", background: "color-mix(in srgb, var(--blue4) 10%, transparent)", padding: "1px 6px", borderRadius: 3 }}>
            grain: {grain}
          </span>
        )}
        {ts && <span style={{ fontSize: 10, color: "var(--t4)" }}>ts: {ts}</span>}
        {dr && (
          <span style={{ fontSize: 10, color: "var(--t4)" }}>
            {String(dr[0]).slice(0, 10)} → {String(dr[1]).slice(0, 10)}
          </span>
        )}
        <span style={{ fontSize: 10, color: "var(--t4)", marginLeft: 4 }}>{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div style={{ borderTop: "1px solid var(--b0)" }}>
          <div style={{
            display: "grid", gridTemplateColumns: GRID,
            padding: "5px 14px 4px", fontSize: 10, fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.06em", color: "var(--t4)", borderBottom: "1px solid var(--b0)",
          }}>
            <span>Column</span>
            <span>Type</span>
            <span>Nulls</span>
            <span>Distinct</span>
            <span>Shape</span>
            <span>Values / Range</span>
          </div>
          {columns.map(col => (
            <div
              key={col.column}
              style={{
                display: "grid", gridTemplateColumns: GRID,
                padding: "5px 14px", borderBottom: "1px solid var(--b0)", alignItems: "center",
              }}
              onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-hover)")}
              onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 5, overflow: "hidden" }}>
                <span style={{ fontSize: 11, color: "var(--t1)", fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {col.column}
                </span>
                {col.is_fk && (
                  <span style={{ fontSize: 9, color: "var(--blue4)", background: "color-mix(in srgb, var(--blue4) 12%, transparent)", padding: "0 4px", borderRadius: 2, flexShrink: 0 }}>FK</span>
                )}
                {col.semantic_type && col.semantic_type !== "unknown" && (
                  <span style={{ fontSize: 9, color: "var(--t4)", flexShrink: 0 }}>{col.semantic_type}</span>
                )}
              </div>
              <span style={{ fontSize: 10, color: "var(--t3)", fontFamily: "var(--font-mono)" }}>
                {col.dtype?.split("(")[0].toUpperCase().slice(0, 10)}
              </span>
              <NullBar rate={col.null_rate ?? 0} />
              <span style={{ fontSize: 11, color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>
                {formatCount(col.distinct_count) ?? "—"}
              </span>
              <ShapeCell dist={distFor(col)} />
              <div style={{ overflow: "hidden" }}>
                {col.top_values && col.is_low_cardinality ? (
                  <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                    {col.top_values.slice(0, 5).map(v => (
                      <span key={v} style={{ fontSize: 10, padding: "1px 5px", borderRadius: 3, background: "var(--bg-2)", color: "var(--t2)", whiteSpace: "nowrap" }}>{v}</span>
                    ))}
                    {col.top_values.length > 5 && (
                      <span style={{ fontSize: 10, color: "var(--t4)" }}>+{col.top_values.length - 5}</span>
                    )}
                  </div>
                ) : col.value_range ? (
                  <span style={{ fontSize: 10, color: "var(--t3)", fontFamily: "var(--font-mono)" }}>
                    {String(col.value_range[0]).slice(0, 12)} – {String(col.value_range[1]).slice(0, 12)}
                  </span>
                ) : (
                  <span style={{ fontSize: 10, color: "var(--t4)" }}>—</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function SchemaShape({
  connectionId,
  schemaTables,
  schemaName,
  domainEntities,
}: {
  connectionId: string;
  /** When set (Catalog schema panel), restrict to this schema's tables (bare names). */
  schemaTables?: string[];
  /** When set (Domains layer with the shared schema selector), the schema's tables are
   *  resolved from the catalog tree and used to scope — same effect as schemaTables. */
  schemaName?: string;
  /** When set (Domains layer), order domain-relevant tables first with a show-all toggle. */
  domainEntities?: string[];
}) {
  const [profile, setProfile] = useState<SchemaProfile | null>(null);
  const [dists, setDists]     = useState<Record<string, DistributionProfile>>({});
  const [loading, setLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [resolvedTables, setResolvedTables] = useState<string[] | null>(null);

  // Resolve a schema NAME → its table list (for the Domains layer, which only knows
  // the selected schema's name from the shared header). Catalog passes schemaTables
  // directly and skips this.
  useEffect(() => {
    if (!schemaName || schemaTables) { setResolvedTables(null); return; }
    let alive = true;
    getCatalogTree()
      .then(tree => {
        if (!alive) return;
        const entry = tree.sections.flatMap(s => s.entries).find(e => e.conn_id === connectionId);
        const sc = entry?.schemas.find(s => s.name === schemaName);
        setResolvedTables(sc ? sc.tables.map(t => t.name) : null);
      })
      .catch(() => { if (alive) setResolvedTables(null); });
    return () => { alive = false; };
  }, [connectionId, schemaName, schemaTables]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      getSchemaProfile(connectionId),
      getExplorationFindings(connectionId).then(f => f.distributions ?? {}).catch(() => ({} as Record<string, DistributionProfile>)),
    ])
      .then(([p, d]) => { if (alive) { setProfile(p); setDists(d); } })
      .catch(() => { if (alive) { setProfile(null); setDists({}); } })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [connectionId]);

  if (loading) return (
    <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 8 }}>
      {[1, 2, 3].map(i => (
        <div key={i} className="animate-pulse" style={{ height: 48, borderRadius: 6, background: "var(--bg-1)" }} />
      ))}
    </div>
  );

  if (!profile?.available) return (
    <div style={{ padding: "48px 20px", textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: 8, color: "var(--t3)" }}>
      <span style={{ fontSize: 28, opacity: 0.2 }}>◫</span>
      <span style={{ fontSize: 12 }}>Schema profile not yet built.</span>
      <span style={{ fontSize: 11, maxWidth: 280, textAlign: "center", lineHeight: 1.6 }}>
        The column profiler runs automatically when the background explorer analyses your schema. Trigger exploration from Connections to build it.
      </span>
    </div>
  );

  // Group columns by table.
  const byTable: Record<string, ColumnProfileData[]> = {};
  for (const col of profile.columns) {
    (byTable[col.table] ??= []).push(col);
  }

  // Distribution lookup keyed by "<bare table>:<column>" (the explorer keys
  // distributions that way; match on the bare last segment + column, lowercased).
  const distLookup = new Map<string, DistributionProfile>();
  for (const [key, d] of Object.entries(dists)) {
    const [t, ...rest] = key.split(":");
    if (!rest.length) continue;
    distLookup.set(`${bare(t)}:${rest.join(":").toLowerCase()}`, d);
  }
  const distFor = (col: ColumnProfileData) => distLookup.get(`${bare(col.table)}:${col.column.toLowerCase()}`);

  let allTables = Object.keys(byTable).sort();

  // Schema scope: restrict to this schema's tables (Catalog passes them directly;
  // Domains resolves them from the schema name). Bare-name match.
  const scopeTables = schemaTables ?? resolvedTables ?? undefined;
  if (scopeTables && scopeTables.length) {
    const allowed = new Set(scopeTables.map(bare));
    allTables = allTables.filter(t => allowed.has(bare(t)));
  }

  // Domains scope: order domain-relevant tables first, with a show-all toggle.
  const domainNorm = new Set((domainEntities ?? []).map(e => e.toLowerCase()));
  const relevant = allTables.filter(t => domainNorm.has(t.toLowerCase()));
  const tablesToShow = !scopeTables && relevant.length > 0 && !showAll ? relevant : allTables;

  // Summary stats over the scoped set.
  const scopedCols = tablesToShow.flatMap(t => byTable[t] ?? []);
  const totalCols = scopedCols.length;
  const avgNull = totalCols > 0
    ? (scopedCols.reduce((s, c) => s + (c.null_rate ?? 0), 0) / totalCols * 100).toFixed(1)
    : "0";
  const lowCard = scopedCols.filter(c => c.is_low_cardinality).length;

  const tableProfileMap: Record<string, TableProfileData> = {};
  for (const tp of profile.tables) tableProfileMap[tp.table] = tp;

  return (
    <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 12, flex: 1, minHeight: 0, overflowY: "auto" }}>
      <div style={{ display: "flex", gap: 16, padding: "10px 14px", background: "var(--bg-1)", borderRadius: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--t2)" }}><strong>{tablesToShow.length}</strong> tables</span>
        <span style={{ fontSize: 11, color: "var(--t2)" }}><strong>{totalCols}</strong> columns</span>
        <span style={{ fontSize: 11, color: "var(--t2)" }}>avg null <strong>{avgNull}%</strong></span>
        <span style={{ fontSize: 11, color: "var(--t2)" }}><strong>{lowCard}</strong> categorical</span>
        {!scopeTables && relevant.length > 0 && relevant.length < allTables.length && (
          <button
            onClick={() => setShowAll(s => !s)}
            style={{ marginLeft: "auto", fontSize: 11, color: "var(--blue4)", background: "none", border: "none", cursor: "pointer" }}
          >
            {showAll ? `Domain tables only (${relevant.length})` : `Show all ${allTables.length} tables`}
          </button>
        )}
      </div>

      {tablesToShow.length === 0 && (
        <p style={{ padding: "20px 4px", fontSize: 11, color: "var(--t4)" }}>No profiled tables in this scope.</p>
      )}

      {tablesToShow.map(table => (
        <TableCard
          key={table}
          table={table}
          tableProfile={tableProfileMap[table]}
          columns={byTable[table] ?? []}
          distFor={distFor}
        />
      ))}
    </div>
  );
}
