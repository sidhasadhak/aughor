"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import {
  getDomainInsights,
  getCanvasDomainInsights,
  getOrgIntelligence,
  getSchemaProfile,
  getPatterns,
  getCanvasPatterns,
  type DomainInsights,
  type ExplorationInsight,
  type OrgInsight,
  type SchemaProfile,
  type TableProfileData,
  type ColumnProfileData,
  type Pattern,
} from "@/lib/api";

// ── Helpers ────────────────────────────────────────────────────────────────────

function noveltyLabel(n: number): { label: string; color: string } {
  if (n >= 5) return { label: "High",   color: "var(--grn3)" };
  if (n >= 3) return { label: "Mid",    color: "var(--amb3)" };
  return           { label: "Low",    color: "var(--t3)"   };
}

function coveragePct(d: DomainInsights): number {
  if (!d.budget_cap) return 0;
  return Math.min(100, Math.round((d.queries_used / d.budget_cap) * 100));
}

function noveltyBreakdown(insights: ExplorationInsight[]) {
  return {
    high: insights.filter(i => i.novelty >= 5).length,
    mid:  insights.filter(i => i.novelty >= 3 && i.novelty < 5).length,
    low:  insights.filter(i => i.novelty < 3).length,
  };
}

function fmtDate(iso: string): string {
  try { return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }); }
  catch { return iso; }
}

// ── Insight row ────────────────────────────────────────────────────────────────

function InsightRow({ insight }: { insight: ExplorationInsight }) {
  const nov = noveltyLabel(insight.novelty);
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      onClick={() => setExpanded(e => !e)}
      style={{
        padding: "10px 14px", borderBottom: "1px solid var(--b0)",
        cursor: "pointer", transition: "background .1s",
      }}
      onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-hover)")}
      onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <span style={{
          flexShrink: 0, marginTop: 1, fontSize: 10, fontWeight: 700,
          padding: "1px 6px", borderRadius: 3,
          background: `color-mix(in srgb, ${nov.color} 14%, transparent)`,
          color: nov.color, letterSpacing: "0.04em",
        }}>{nov.label}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{
            margin: 0, fontSize: 12, color: "var(--t1)", lineHeight: 1.55,
            display: expanded ? undefined : "-webkit-box",
            WebkitLineClamp: expanded ? undefined : 2,
            WebkitBoxOrient: "vertical" as const,
            overflow: expanded ? undefined : "hidden",
          }}>{insight.finding}</p>
          {expanded && (
            <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
              {insight.angle && (
                <span style={{ fontSize: 10, color: "var(--t3)", background: "var(--bg-2)", borderRadius: 3, padding: "1px 6px" }}>
                  {insight.angle}
                </span>
              )}
              {insight.entities_involved?.map(e => (
                <span key={e} style={{ fontSize: 10, color: "var(--blue4)", background: "color-mix(in srgb, var(--blue4) 10%, transparent)", borderRadius: 3, padding: "1px 6px" }}>{e}</span>
              ))}
              <span style={{ fontSize: 10, color: "var(--t4)" }}>
                confidence {Math.round((insight.confidence ?? 0) * 100)}% · {fmtDate(insight.generated_at)}
              </span>
            </div>
          )}
        </div>
        <span style={{ fontSize: 10, color: "var(--t4)", flexShrink: 0 }}>
          {expanded ? "▲" : "▼"}
        </span>
      </div>
    </div>
  );
}

// ── Domain profile ─────────────────────────────────────────────────────────────

// ── Pattern Library tab ───────────────────────────────────────────────────────

const PATTERN_TYPE_META: Record<string, { label: string; color: string; icon: string }> = {
  angle:       { label: "Recurring Angle",     color: "var(--blue4)",  icon: "↻" },
  entity:      { label: "Cross-Domain Driver", color: "var(--vio3)",   icon: "⊕" },
  convergence: { label: "High-Novelty Cluster", color: "var(--grn3)", icon: "◎" },
};

function PatternCard({ pattern, domainFilter }: { pattern: Pattern; domainFilter?: string }) {
  const [expanded, setExpanded] = useState(false);
  const meta = PATTERN_TYPE_META[pattern.type] ?? PATTERN_TYPE_META.angle;
  const relevantDomains = domainFilter
    ? pattern.domains.filter(d => d.toLowerCase() === domainFilter.toLowerCase())
    : pattern.domains;

  return (
    <div style={{
      background: "var(--bg-1)", border: "1px solid var(--b1)",
      borderRadius: 7, overflow: "hidden",
      borderLeft: `3px solid ${meta.color}`,
    }}>
      <button
        onClick={() => setExpanded(e => !e)}
        style={{
          width: "100%", textAlign: "left", padding: "12px 16px",
          background: "none", border: "none", cursor: "pointer", display: "flex", gap: 10, alignItems: "flex-start",
        }}
        onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-hover)")}
        onMouseLeave={e => (e.currentTarget.style.background = "none")}
      >
        {/* Type badge */}
        <span style={{
          flexShrink: 0, marginTop: 1, fontSize: 9, fontWeight: 700,
          textTransform: "uppercase", letterSpacing: "0.07em",
          padding: "2px 6px", borderRadius: 3,
          background: `color-mix(in srgb, ${meta.color} 14%, transparent)`,
          color: meta.color,
        }}>{meta.icon} {meta.label}</span>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", marginBottom: 4 }}>
            {pattern.title}
          </div>
          <div style={{ fontSize: 11, color: "var(--t3)", lineHeight: 1.5 }}>
            {pattern.description}
          </div>
        </div>

        {/* Stats */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
          <span style={{ fontSize: 11, color: "var(--t2)", fontWeight: 600 }}>
            {pattern.evidence_count} findings
          </span>
          <span style={{ fontSize: 10, color: `color-mix(in srgb, var(--grn3) ${Math.min(100, pattern.novelty * 12)}%, var(--amb3))`, fontWeight: 600 }}>
            novelty {pattern.novelty}
          </span>
        </div>
        <span style={{ fontSize: 10, color: "var(--t4)", flexShrink: 0, marginTop: 1 }}>{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div style={{ borderTop: "1px solid var(--b0)", padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
          {/* Domains */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center" }}>
            <span style={{ fontSize: 10, color: "var(--t4)" }}>Domains:</span>
            {pattern.domains.map(d => (
              <span key={d} style={{
                fontSize: 10, padding: "1px 7px", borderRadius: 3,
                background: relevantDomains.includes(d)
                  ? `color-mix(in srgb, ${meta.color} 16%, transparent)`
                  : "var(--bg-2)",
                color: relevantDomains.includes(d) ? meta.color : "var(--t3)",
                textTransform: "capitalize",
              }}>{d}</span>
            ))}
          </div>

          {/* Entities */}
          {pattern.entities.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center" }}>
              <span style={{ fontSize: 10, color: "var(--t4)" }}>Entities:</span>
              {pattern.entities.slice(0, 8).map(e => (
                <span key={e} style={{
                  fontSize: 10, padding: "1px 6px", borderRadius: 3,
                  background: "var(--bg-2)", color: "var(--t3)",
                  fontFamily: "var(--font-mono)",
                }}>{e}</span>
              ))}
            </div>
          )}

          {/* Angles (for entity patterns) */}
          {pattern.angles && pattern.angles.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center" }}>
              <span style={{ fontSize: 10, color: "var(--t4)" }}>Angles:</span>
              {pattern.angles.map(a => (
                <span key={a} style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, background: "color-mix(in srgb, var(--blue3) 10%, transparent)", color: "var(--blue4)" }}>{a}</span>
              ))}
            </div>
          )}

          {/* Example findings */}
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <span style={{ fontSize: 10, color: "var(--t4)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>Example findings</span>
            {pattern.example_findings.filter(Boolean).map((f, i) => (
              <div key={i} style={{
                fontSize: 11, color: "var(--t2)", lineHeight: 1.55,
                padding: "6px 10px", background: "var(--bg-2)", borderRadius: 5,
                borderLeft: `2px solid ${meta.color}44`,
              }}>"{f}"</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PatternsTab({
  connectionId,
  canvasId,
  domain,
}: {
  connectionId: string;
  canvasId?: string;
  domain: string;
}) {
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<"all" | "angle" | "entity" | "convergence">("all");

  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true); else setLoading(true);
    try {
      const res = canvasId ? await getCanvasPatterns(canvasId, refresh) : await getPatterns(connectionId, refresh);
      setPatterns(res.patterns ?? []);
    } catch {
      setPatterns([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [connectionId, canvasId]);

  useEffect(() => { load(); }, [load]);

  // Filter to patterns that involve this domain
  const domainPatterns = patterns.filter(p =>
    p.domains.some(d => d.toLowerCase() === domain.toLowerCase())
  );
  const displayed = (filter === "all" ? domainPatterns : domainPatterns.filter(p => p.type === filter));

  if (loading) return (
    <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 8 }}>
      {[1, 2, 3].map(i => (
        <div key={i} className="animate-pulse" style={{ height: 72, borderRadius: 7, background: "var(--bg-1)" }} />
      ))}
    </div>
  );

  return (
    <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div style={{ display: "flex", background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r2)", padding: 2, gap: 2 }}>
          {(["all", "angle", "entity", "convergence"] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)} style={{
              padding: "3px 10px", borderRadius: "calc(var(--r2) - 2px)", fontSize: 11,
              fontWeight: filter === f ? 600 : 400, cursor: "pointer",
              background: filter === f ? "var(--bg-sel)" : "transparent",
              border: `1px solid ${filter === f ? "var(--blue2)" : "transparent"}`,
              color: filter === f ? "var(--blue5)" : "var(--t3)",
            }}>
              {f === "all" ? `All (${domainPatterns.length})` : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--t3)" }}>
          {displayed.length} pattern{displayed.length !== 1 ? "s" : ""} in this domain
        </span>
        <button
          onClick={() => load(true)}
          disabled={refreshing}
          style={{
            fontSize: 11, color: refreshing ? "var(--t4)" : "var(--t3)",
            background: "none", border: "1px solid var(--b1)", borderRadius: 4,
            padding: "3px 8px", cursor: refreshing ? "default" : "pointer",
          }}
        >
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {/* Pattern cards */}
      {displayed.length === 0 ? (
        <div style={{ padding: "40px 0", textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: 8, color: "var(--t3)" }}>
          <span style={{ fontSize: 28, opacity: 0.2 }}>◎</span>
          <span style={{ fontSize: 12 }}>
            {patterns.length === 0
              ? "No patterns detected yet."
              : `No ${filter === "all" ? "" : filter + " "}patterns found for the ${domain} domain.`}
          </span>
          {patterns.length === 0 && (
            <span style={{ fontSize: 11, maxWidth: 300, textAlign: "center", lineHeight: 1.6 }}>
              Patterns emerge when domain intelligence spans multiple domains and angles. Run the explorer to build richer coverage.
            </span>
          )}
        </div>
      ) : (
        displayed.map(p => <PatternCard key={p.id} pattern={p} domainFilter={domain} />)
      )}

      {/* All-domains note */}
      {patterns.length > domainPatterns.length && (
        <div style={{ padding: "8px 12px", background: "var(--bg-1)", borderRadius: 5, fontSize: 11, color: "var(--t3)", textAlign: "center" }}>
          {patterns.length - domainPatterns.length} additional pattern{patterns.length - domainPatterns.length !== 1 ? "s" : ""} exist in other domains.
          Switch to another domain profile to explore them.
        </div>
      )}
    </div>
  );
}

// ── Schema Shape tab ──────────────────────────────────────────────────────────

function NullBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const color = pct > 20 ? "var(--r3)" : pct > 5 ? "var(--amb3)" : "var(--grn3)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 48, height: 4, background: "var(--bg-3)", borderRadius: 2 }}>
        <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 10, color: pct > 10 ? color : "var(--t4)", fontVariantNumeric: "tabular-nums" }}>
        {pct}%
      </span>
    </div>
  );
}

function TableCard({
  table,
  tableProfile,
  columns,
}: {
  table: string;
  tableProfile: TableProfileData | undefined;
  columns: ColumnProfileData[];
}) {
  const [expanded, setExpanded] = useState(true);
  const rowCount = tableProfile?.row_count;
  const grain = tableProfile?.grain_column;
  const ts = tableProfile?.primary_timestamp;
  const dr = tableProfile?.date_range;

  return (
    <div style={{ background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: 7, overflow: "hidden" }}>
      {/* Table header */}
      <button
        onClick={() => setExpanded(e => !e)}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 10,
          padding: "10px 14px", background: "none", border: "none", cursor: "pointer",
          textAlign: "left",
        }}
        onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-hover)")}
        onMouseLeave={e => (e.currentTarget.style.background = "none")}
      >
        <span style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)", fontFamily: "var(--font-mono)", flex: 1 }}>
          {table}
        </span>
        {rowCount != null && (
          <span style={{ fontSize: 10, color: "var(--t3)", background: "var(--bg-2)", padding: "1px 6px", borderRadius: 3 }}>
            {rowCount.toLocaleString()} rows
          </span>
        )}
        {grain && (
          <span style={{ fontSize: 10, color: "var(--blue4)", background: "color-mix(in srgb, var(--blue4) 10%, transparent)", padding: "1px 6px", borderRadius: 3 }}>
            grain: {grain}
          </span>
        )}
        {ts && (
          <span style={{ fontSize: 10, color: "var(--t4)" }}>
            ts: {ts}
          </span>
        )}
        {dr && (
          <span style={{ fontSize: 10, color: "var(--t4)" }}>
            {String(dr[0]).slice(0, 10)} → {String(dr[1]).slice(0, 10)}
          </span>
        )}
        <span style={{ fontSize: 10, color: "var(--t4)", marginLeft: 4 }}>{expanded ? "▲" : "▼"}</span>
      </button>

      {/* Columns */}
      {expanded && (
        <div style={{ borderTop: "1px solid var(--b0)" }}>
          <div style={{
            display: "grid",
            gridTemplateColumns: "1fr 80px 90px 100px 1fr",
            padding: "5px 14px 4px",
            fontSize: 10, fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.06em", color: "var(--t4)",
            borderBottom: "1px solid var(--b0)",
          }}>
            <span>Column</span>
            <span>Type</span>
            <span>Nulls</span>
            <span>Distinct</span>
            <span>Values / Range</span>
          </div>
          {columns.map(col => (
            <div
              key={col.column}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 80px 90px 100px 1fr",
                padding: "5px 14px",
                borderBottom: "1px solid var(--b0)",
                alignItems: "center",
              }}
              onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-hover)")}
              onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
            >
              {/* Name + tags */}
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
              {/* Type */}
              <span style={{ fontSize: 10, color: "var(--t3)", fontFamily: "var(--font-mono)" }}>
                {col.dtype?.split("(")[0].toUpperCase().slice(0, 10)}
              </span>
              {/* Null bar */}
              <NullBar rate={col.null_rate ?? 0} />
              {/* Distinct */}
              <span style={{ fontSize: 11, color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>
                {col.distinct_count?.toLocaleString() ?? "—"}
              </span>
              {/* Values */}
              <div style={{ overflow: "hidden" }}>
                {col.top_values && col.is_low_cardinality ? (
                  <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                    {col.top_values.slice(0, 5).map(v => (
                      <span key={v} style={{
                        fontSize: 10, padding: "1px 5px", borderRadius: 3,
                        background: "var(--bg-2)", color: "var(--t2)", whiteSpace: "nowrap",
                      }}>{v}</span>
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

function SchemaTab({
  connectionId,
  domainEntities,
}: {
  connectionId: string;
  domainEntities: string[];   // table names inferred from domain insights
}) {
  const [profile, setProfile] = useState<SchemaProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    setLoading(true);
    getSchemaProfile(connectionId)
      .then(setProfile)
      .catch(() => setProfile(null))
      .finally(() => setLoading(false));
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

  // Group columns by table
  const byTable: Record<string, ColumnProfileData[]> = {};
  for (const col of profile.columns) {
    if (!byTable[col.table]) byTable[col.table] = [];
    byTable[col.table].push(col);
  }

  // Relevance: domain entities first, then all
  const domainNorm = new Set(domainEntities.map(e => e.toLowerCase()));
  const allTables = Object.keys(byTable).sort();
  const relevantTables = allTables.filter(t => domainNorm.has(t.toLowerCase()));
  const otherTables = allTables.filter(t => !domainNorm.has(t.toLowerCase()));
  const tablesToShow = relevantTables.length > 0 && !showAll
    ? relevantTables
    : allTables;

  // Summary stats
  const totalCols = profile.columns.length;
  const avgNull = totalCols > 0
    ? (profile.columns.reduce((s, c) => s + (c.null_rate ?? 0), 0) / totalCols * 100).toFixed(1)
    : "0";
  const lowCard = profile.columns.filter(c => c.is_low_cardinality).length;

  const tableProfileMap: Record<string, TableProfileData> = {};
  for (const tp of profile.tables) tableProfileMap[tp.table] = tp;

  return (
    <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Summary strip */}
      <div style={{ display: "flex", gap: 16, padding: "10px 14px", background: "var(--bg-1)", borderRadius: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--t2)" }}><strong>{allTables.length}</strong> tables</span>
        <span style={{ fontSize: 11, color: "var(--t2)" }}><strong>{totalCols}</strong> columns</span>
        <span style={{ fontSize: 11, color: "var(--t2)" }}>avg null <strong>{avgNull}%</strong></span>
        <span style={{ fontSize: 11, color: "var(--t2)" }}><strong>{lowCard}</strong> categorical</span>
        {relevantTables.length > 0 && otherTables.length > 0 && (
          <button
            onClick={() => setShowAll(s => !s)}
            style={{ marginLeft: "auto", fontSize: 11, color: "var(--blue4)", background: "none", border: "none", cursor: "pointer" }}
          >
            {showAll ? `Domain tables only (${relevantTables.length})` : `Show all ${allTables.length} tables`}
          </button>
        )}
      </div>

      {/* Table cards */}
      {tablesToShow.map(table => (
        <TableCard
          key={table}
          table={table}
          tableProfile={tableProfileMap[table]}
          columns={byTable[table] ?? []}
        />
      ))}
    </div>
  );
}

// ── Domain profile ─────────────────────────────────────────────────────────────

type ProfileTab = "overview" | "insights" | "org-intel" | "schema" | "patterns";

function DomainProfile({
  domain,
  data,
  orgInsights,
  connectionId,
  canvasId,
  onBack,
}: {
  domain: string;
  data: DomainInsights;
  orgInsights: OrgInsight[];
  connectionId: string;
  canvasId?: string;
  onBack: () => void;
}) {
  const [tab, setTab] = useState<ProfileTab>("overview");
  const [search, setSearch] = useState("");

  const breakdown = noveltyBreakdown(data.insights);
  const pct = coveragePct(data);
  const domainOrg = orgInsights.filter(o => o.domain?.toLowerCase() === domain.toLowerCase());
  const sorted = useMemo(() =>
    [...data.insights].sort((a, b) => b.novelty - a.novelty),
    [data.insights]
  );
  const filtered = useMemo(() =>
    sorted.filter(i => !search || i.finding.toLowerCase().includes(search.toLowerCase()) || i.angle.toLowerCase().includes(search.toLowerCase())),
    [sorted, search]
  );
  const topInsights = sorted.slice(0, 3);

  // Collect entity names from insights to scope the schema tab
  const domainEntities = useMemo(() =>
    Array.from(new Set(data.insights.flatMap(i => i.entities_involved ?? []))),
    [data.insights]
  );

  const TABS: { id: ProfileTab; label: string }[] = [
    { id: "overview",  label: "Overview"  },
    { id: "insights",  label: `Insights (${data.insights.length})` },
    { id: "schema",    label: "Schema Shape" },
    { id: "patterns",  label: "Patterns" },
    { id: "org-intel", label: `Org Intel (${domainOrg.length})` },
  ];

  // A scannable metric pill used in the profile header.
  const Pill = ({ children }: { children: React.ReactNode }) => (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--t2)",
      background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: 6, padding: "3px 9px",
    }}>{children}</span>
  );

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Profile header */}
      <div style={{
        padding: "14px 20px", borderBottom: "1px solid var(--b1)",
        display: "flex", flexDirection: "column", gap: 12, flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            onClick={onBack}
            className="aug-btn"
            style={{ background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: 6, cursor: "pointer", color: "var(--t2)", fontSize: 11, padding: "3px 9px", display: "flex", alignItems: "center", gap: 5 }}
          >
            ← Hub
          </button>
          <span style={{ fontSize: 15, fontWeight: 700, color: "var(--t1)", textTransform: "capitalize" }}>{domain}</span>
          <span style={{
            fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em",
            padding: "2px 7px", borderRadius: 3,
            background: "color-mix(in srgb, var(--blue3) 14%, transparent)",
            color: "var(--blue4)",
          }}>Domain</span>
        </div>

        {/* Metric pills */}
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Pill><strong style={{ color: "var(--t1)" }}>{data.insights.length}</strong> insights</Pill>
          <Pill>
            <span style={{ color: "var(--grn3)", fontWeight: 600 }}>{breakdown.high}H</span>
            <span style={{ color: "var(--amb3)", fontWeight: 600 }}>{breakdown.mid}M</span>
            <span style={{ color: "var(--t3)", fontWeight: 600 }}>{breakdown.low}L</span>
          </Pill>
          <Pill><strong style={{ color: "var(--t1)" }}>{data.angles_covered.length}</strong> angles</Pill>
          <Pill>
            Coverage
            <span style={{ display: "inline-block", width: 54, height: 4, background: "var(--bg-3)", borderRadius: 2, overflow: "hidden" }}>
              <span style={{ display: "block", width: `${pct}%`, height: "100%", background: pct > 70 ? "var(--grn3)" : pct > 40 ? "var(--amb3)" : "var(--b3)" }} />
            </span>
            <strong style={{ color: "var(--t1)" }}>{pct}%</strong>
          </Pill>
          {domainOrg.length > 0 && (
            <Pill><span style={{ color: "var(--vio3)", fontWeight: 600 }}>◈ {domainOrg.length}</span> org promoted</Pill>
          )}
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--b1)", padding: "0 20px", flexShrink: 0 }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: "8px 14px", fontSize: 12, fontWeight: tab === t.id ? 600 : 400,
            color: tab === t.id ? "var(--t1)" : "var(--t3)",
            background: "none", border: "none", cursor: "pointer",
            borderBottom: tab === t.id ? "2px solid var(--blue4)" : "2px solid transparent",
            marginBottom: -1, transition: "all .12s",
          }}>{t.label}</button>
        ))}
      </div>

      {/* Tab body */}
      <div style={{ flex: 1, overflowY: "auto" }}>

        {/* ── OVERVIEW ── */}
        {tab === "overview" && (
          <div style={{ padding: "20px", display: "flex", flexDirection: "column", gap: 20 }}>

            {/* Top insights */}
            <div>
              <SectionHead
                title="Top Findings"
                action={data.insights.length > 3 ? (
                  <button onClick={() => setTab("insights")} style={{ fontSize: 11, color: "var(--blue4)", background: "none", border: "none", cursor: "pointer" }}>
                    All {data.insights.length} →
                  </button>
                ) : undefined}
              />
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {topInsights.length === 0 ? (
                  <p style={{ fontSize: 12, color: "var(--t3)" }}>No insights yet for this domain.</p>
                ) : topInsights.map(ins => {
                  const nov = noveltyLabel(ins.novelty);
                  return (
                    <button key={ins.id} onClick={() => setTab("insights")} style={{
                      textAlign: "left", background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: 6,
                      padding: "10px 14px", display: "flex", gap: 10, cursor: "pointer", transition: "all .1s",
                    }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--b2)"; e.currentTarget.style.background = "var(--bg-2)"; }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b1)"; e.currentTarget.style.background = "var(--bg-1)"; }}
                    >
                      <span style={{
                        flexShrink: 0, marginTop: 2, fontSize: 10, fontWeight: 700,
                        padding: "1px 6px", borderRadius: 3,
                        background: `color-mix(in srgb, ${nov.color} 14%, transparent)`,
                        color: nov.color,
                      }}>{nov.label}</span>
                      <p style={{ margin: 0, fontSize: 12, color: "var(--t2)", lineHeight: 1.55 }}>{ins.finding}</p>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Angles covered */}
            {data.angles_covered.length > 0 && (
              <div>
                <SectionHead title="Angles Covered" count={data.angles_covered.length} />
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {data.angles_covered.map(a => (
                    <span key={a} style={{
                      fontSize: 11, padding: "3px 9px", borderRadius: 4,
                      background: "color-mix(in srgb, var(--blue3) 10%, transparent)",
                      border: "1px solid color-mix(in srgb, var(--blue3) 25%, transparent)",
                      color: "var(--blue4)",
                    }}>{a}</span>
                  ))}
                </div>
              </div>
            )}

            {/* Budget usage */}
            <div>
              <SectionHead title="Query Budget" />
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--t2)" }}>
                  <span>{data.queries_used} queries used</span>
                  <span>{data.budget_cap} cap</span>
                </div>
                <div style={{ height: 6, background: "var(--bg-3)", borderRadius: 3 }}>
                  <div style={{
                    width: `${pct}%`, height: "100%", borderRadius: 3,
                    background: pct > 85 ? "var(--r3)" : pct > 60 ? "var(--amb3)" : "var(--grn3)",
                    transition: "width .3s",
                  }} />
                </div>
              </div>
            </div>

            {/* Org intel preview */}
            {domainOrg.length > 0 && (
              <div>
                <SectionHead
                  title="Org-Promoted Findings"
                  action={<button onClick={() => setTab("org-intel")} style={{ fontSize: 11, color: "var(--blue4)", background: "none", border: "none", cursor: "pointer" }}>View all →</button>}
                />
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {domainOrg.slice(0, 2).map(o => (
                    <div key={o.id} style={{
                      background: "color-mix(in srgb, var(--vio3) 6%, var(--bg-1))",
                      border: "1px solid color-mix(in srgb, var(--vio3) 18%, transparent)",
                      borderRadius: 6, padding: "8px 12px",
                    }}>
                      <p style={{ margin: 0, fontSize: 11, color: "var(--t2)", lineHeight: 1.55 }}>{o.text}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── INSIGHTS ── */}
        {tab === "insights" && (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {/* Search */}
            <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--b0)", flexShrink: 0 }}>
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search insights…"
                style={{
                  width: "100%", background: "var(--bg-2)", border: "1px solid var(--b1)",
                  borderRadius: 5, padding: "5px 10px", fontSize: 12,
                  color: "var(--t1)", outline: "none",
                }}
              />
            </div>
            {filtered.length === 0 ? (
              <div style={{ padding: "40px", textAlign: "center", color: "var(--t3)", fontSize: 12 }}>
                {search ? "No insights match your search." : "No insights yet."}
              </div>
            ) : filtered.map(ins => <InsightRow key={ins.id} insight={ins} />)}
          </div>
        )}

        {/* ── SCHEMA SHAPE ── */}
        {tab === "schema" && (
          <SchemaTab connectionId={connectionId} domainEntities={domainEntities} />
        )}

        {/* ── PATTERNS ── */}
        {tab === "patterns" && (
          <PatternsTab connectionId={connectionId} canvasId={canvasId} domain={domain} />
        )}

        {/* ── ORG INTEL ── */}
        {tab === "org-intel" && (
          <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 8 }}>
            {domainOrg.length === 0 ? (
              <div style={{ padding: "40px 0", textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: 8, color: "var(--t3)" }}>
                <span style={{ fontSize: 28, opacity: 0.2 }}>◈</span>
                <span style={{ fontSize: 12 }}>No org-wide findings for this domain yet.</span>
                <span style={{ fontSize: 11, maxWidth: 280, textAlign: "center", lineHeight: 1.6 }}>
                  Promote high-novelty insights via "Promote to Org →" in Domain Intel to build collective knowledge here.
                </span>
              </div>
            ) : domainOrg.map(o => {
              const nov = noveltyLabel(o.novelty);
              return (
                <div key={o.id} style={{
                  background: "var(--bg-1)", border: "1px solid var(--b1)",
                  borderRadius: 6, padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6,
                }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    {o.angle && <span style={{ fontSize: 10, color: "var(--t3)" }}>{o.angle}</span>}
                    <span style={{ marginLeft: "auto", fontSize: 10, color: nov.color, fontWeight: 600 }}>{nov.label} novelty</span>
                  </div>
                  <p style={{ margin: 0, fontSize: 12, color: "var(--t2)", lineHeight: 1.55 }}>{o.text}</p>
                  <span style={{ fontSize: 10, color: "var(--t4)" }}>Promoted {fmtDate(o.promoted_at)}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Domain card ────────────────────────────────────────────────────────────────

function DomainCard({
  domain,
  data,
  orgCount,
  onClick,
}: {
  domain: string;
  data: DomainInsights;
  orgCount: number;
  onClick: () => void;
}) {
  const breakdown = noveltyBreakdown(data.insights);
  const pct = coveragePct(data);
  const topNovelty = data.insights.length > 0 ? Math.max(...data.insights.map(i => i.novelty)) : 0;
  const nov = noveltyLabel(topNovelty);

  return (
    <button
      onClick={onClick}
      style={{
        textAlign: "left", padding: "14px", background: "var(--bg-1)",
        border: "1px solid var(--b1)", borderRadius: 6, cursor: "pointer",
        transition: "all .12s", display: "flex", flexDirection: "column", gap: 11,
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--b2)"; e.currentTarget.style.background = "var(--bg-2)"; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b1)"; e.currentTarget.style.background = "var(--bg-1)"; }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)", textTransform: "capitalize", lineHeight: 1.3 }}>{domain}</span>
        <span style={{
          fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em",
          padding: "2px 6px", borderRadius: 3, flexShrink: 0,
          background: `color-mix(in srgb, ${nov.color} 14%, transparent)`,
          color: nov.color,
        }}>{nov.label}</span>
      </div>

      {/* Stats */}
      <div style={{ display: "flex", gap: 14 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--t1)", lineHeight: 1 }}>{data.insights.length}</div>
          <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 2 }}>insights</div>
        </div>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--t1)", lineHeight: 1 }}>{data.angles_covered.length}</div>
          <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 2 }}>angles</div>
        </div>
        {orgCount > 0 && (
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--vio3)", lineHeight: 1 }}>{orgCount}</div>
            <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 2 }}>org intel</div>
          </div>
        )}
      </div>

      {/* Novelty breakdown bar */}
      <div style={{ display: "flex", gap: 1, height: 4, borderRadius: 2, overflow: "hidden", background: "var(--bg-3)" }}>
        {data.insights.length > 0 && (
          <>
            <div style={{ flex: breakdown.high, background: "var(--grn3)" }} />
            <div style={{ flex: breakdown.mid,  background: "var(--amb3)" }} />
            <div style={{ flex: breakdown.low,  background: "var(--b2)"  }} />
          </>
        )}
      </div>

      {/* Coverage */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ flex: 1, height: 3, background: "var(--bg-3)", borderRadius: 2 }}>
          <div style={{
            width: `${pct}%`, height: "100%", borderRadius: 2,
            background: pct > 70 ? "var(--grn3)" : pct > 40 ? "var(--amb3)" : "var(--b3)",
          }} />
        </div>
        <span style={{ fontSize: 10, color: "var(--t3)", whiteSpace: "nowrap" }}>{pct}% explored</span>
      </div>
    </button>
  );
}

// ── Section header ──────────────────────────────────────────────────────────────

function SectionHead({ title, count, action }: { title: string; count?: number | string; action?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 12 }}>
      <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--t3)" }}>
        {title}
      </span>
      {count != null && (
        <span style={{ fontSize: 11, color: "var(--t4)" }}>{count}</span>
      )}
      {action && <span style={{ marginLeft: "auto" }}>{action}</span>}
    </div>
  );
}

// ── Headline finding (synthesis hero card) ──────────────────────────────────────

function HeadlineFinding({ insight, onOpen }: { insight: ExplorationInsight; onOpen: () => void }) {
  const nov = noveltyLabel(insight.novelty);
  return (
    <button
      onClick={onOpen}
      style={{
        textAlign: "left", width: "100%", display: "flex", flexDirection: "column", gap: 8,
        padding: "12px 14px", background: "var(--bg-1)", border: "1px solid var(--b1)",
        borderRadius: 6, cursor: "pointer", transition: "all .12s",
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--b2)"; e.currentTarget.style.background = "var(--bg-2)"; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b1)"; e.currentTarget.style.background = "var(--bg-1)"; }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 10, fontWeight: 600, color: "var(--blue4)", textTransform: "capitalize" }}>
          {insight.domain}
        </span>
        <span style={{ fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 3, background: `color-mix(in srgb, ${nov.color} 14%, transparent)`, color: nov.color, letterSpacing: "0.04em" }}>
          {nov.label}
        </span>
        {insight.promoted_to_org && (
          <span title="Promoted to org knowledge" style={{ fontSize: 10, color: "var(--vio3)" }}>◈</span>
        )}
        <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--t4)" }}>{fmtDate(insight.generated_at)}</span>
      </div>
      <p style={{
        margin: 0, fontSize: 12, color: "var(--t1)", lineHeight: 1.55,
        display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical" as const, overflow: "hidden",
      }}>{insight.finding}</p>
      {insight.angle && (
        <span style={{ fontSize: 10, color: "var(--t3)" }}>{insight.angle}</span>
      )}
    </button>
  );
}

// ── Synthesis home — the core "Hub of Intelligence" command center ──────────────

function SynthesisHome({
  domainData,
  orgInsights,
  patterns,
  onSelectDomain,
}: {
  domainData: Record<string, DomainInsights>;
  orgInsights: OrgInsight[];
  patterns: Pattern[];
  onSelectDomain: (d: string) => void;
}) {
  const domains = Object.keys(domainData).sort();
  const allInsights = useMemo(
    () => domains.flatMap(d => domainData[d].insights),
    [domainData], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const totalInsights = allInsights.length;
  const totalAngles   = domains.reduce((s, d) => s + domainData[d].angles_covered.length, 0);
  const allNovelties  = allInsights.map(i => i.novelty);
  const avgNovelty    = allNovelties.length ? (allNovelties.reduce((s, n) => s + n, 0) / allNovelties.length).toFixed(1) : "—";
  const highNovelty   = allInsights.filter(i => i.novelty >= 5).length;
  const crossDomain   = patterns.filter(p => p.domains.length > 1);

  const headline = useMemo(
    () => [...allInsights].sort((a, b) => (b.novelty - a.novelty) || ((b.confidence ?? 0) - (a.confidence ?? 0))).slice(0, 8),
    [allInsights],
  );
  const topPatterns = useMemo(
    () => [...patterns].sort((a, b) => (b.novelty - a.novelty) || (b.evidence_count - a.evidence_count)).slice(0, 4),
    [patterns],
  );
  const recentOrg = useMemo(
    () => [...orgInsights].sort((a, b) => (b.promoted_at || "").localeCompare(a.promoted_at || "")).slice(0, 4),
    [orgInsights],
  );
  const gaps = useMemo(
    () => domains.map(d => ({ d, pct: coveragePct(domainData[d]) })).filter(x => x.pct < 40).sort((a, b) => a.pct - b.pct).slice(0, 3),
    [domainData], // eslint-disable-line react-hooks/exhaustive-deps
  );

  if (domains.length === 0) {
    return (
      <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "var(--t3)", gap: 8 }}>
        <div style={{ fontSize: 32, opacity: 0.2 }}>◈</div>
        <div style={{ fontSize: 13, color: "var(--t2)", fontWeight: 500 }}>No intelligence built yet</div>
        <div style={{ fontSize: 11, maxWidth: 320, textAlign: "center", lineHeight: 1.6 }}>
          Run the background explorer on a connection to begin building domain knowledge, patterns, and org intelligence.
        </div>
      </div>
    );
  }

  const KPIS = [
    { value: domains.length,    label: "Domains",       accent: "var(--blue3)" },
    { value: totalInsights,     label: "Insights",      accent: "var(--grn3)"  },
    { value: highNovelty,       label: "High-novelty",  accent: "var(--grn3)"  },
    { value: crossDomain.length,label: "Cross-domain",  accent: "var(--vio3)"  },
    { value: orgInsights.length,label: "Org knowledge", accent: "var(--vio3)"  },
    { value: avgNovelty,        label: "Avg novelty",   accent: "var(--cyn3)"  },
  ];

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "22px 24px 32px", display: "flex", flexDirection: "column", gap: 26 }}>
      {/* KPI strip */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 10 }}>
        {KPIS.map(s => (
          <div key={s.label} style={{ padding: "12px 14px", background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: 6 }}>
            <div style={{ fontSize: 22, fontWeight: 700, color: "var(--t1)", lineHeight: 1 }}>{s.value}</div>
            <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 4 }}>{s.label}</div>
            <div style={{ height: 2, background: s.accent, borderRadius: 1, marginTop: 9, width: 22 }} />
          </div>
        ))}
      </div>

      {/* Headline findings — the cream, surfaced across all domains */}
      <div>
        <SectionHead title="Headline Findings" count={`top ${headline.length} across all domains`} />
        {headline.length === 0 ? (
          <p style={{ fontSize: 12, color: "var(--t3)" }}>No findings yet.</p>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 10 }}>
            {headline.map(ins => (
              <HeadlineFinding key={ins.id} insight={ins} onOpen={() => onSelectDomain(ins.domain)} />
            ))}
          </div>
        )}
      </div>

      {/* Cross-domain patterns */}
      <div>
        <SectionHead title="Cross-Domain Patterns" count={`${crossDomain.length} spanning multiple domains`} />
        {topPatterns.length === 0 ? (
          <div style={{ padding: "20px 0", textAlign: "center", color: "var(--t3)", fontSize: 12, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 24, opacity: 0.2 }}>◎</span>
            <span>No patterns detected yet — they emerge as coverage deepens across domains.</span>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {topPatterns.map(p => <PatternCard key={p.id} pattern={p} />)}
          </div>
        )}
      </div>

      {/* Org-promoted knowledge */}
      {recentOrg.length > 0 && (
        <div>
          <SectionHead title="Org-Promoted Knowledge" count={`${orgInsights.length} collective findings`} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 10 }}>
            {recentOrg.map(o => {
              const nov = noveltyLabel(o.novelty);
              return (
                <div key={o.id} style={{
                  background: "color-mix(in srgb, var(--vio3) 5%, var(--bg-1))",
                  border: "1px solid color-mix(in srgb, var(--vio3) 18%, transparent)",
                  borderRadius: 6, padding: "11px 14px", display: "flex", flexDirection: "column", gap: 7,
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    {o.domain && <span style={{ fontSize: 10, fontWeight: 600, color: "var(--vio3)", textTransform: "capitalize" }}>{o.domain}</span>}
                    {o.angle && <span style={{ fontSize: 10, color: "var(--t4)" }}>· {o.angle}</span>}
                    <span style={{ marginLeft: "auto", fontSize: 10, color: nov.color, fontWeight: 600 }}>{nov.label}</span>
                  </div>
                  <p style={{ margin: 0, fontSize: 12, color: "var(--t2)", lineHeight: 1.55 }}>{o.text}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Domains — demoted to a browsable section */}
      <div>
        <SectionHead
          title="Domains"
          count={`${domains.length} mapped`}
          action={gaps.length > 0 ? (
            <span style={{ fontSize: 10, color: "var(--amb3)" }}>
              {gaps.length} need{gaps.length === 1 ? "s" : ""} exploration: {gaps.map(g => g.d).join(", ")}
            </span>
          ) : undefined}
        />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
          {domains.map(domain => (
            <DomainCard
              key={domain}
              domain={domain}
              data={domainData[domain]}
              orgCount={orgInsights.filter(o => o.domain?.toLowerCase() === domain.toLowerCase()).length}
              onClick={() => onSelectDomain(domain)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────────

export function IntelligenceHub({ connectionId, canvasId }: { connectionId: string; canvasId?: string }) {
  const [domainData, setDomainData] = useState<Record<string, DomainInsights>>({});
  const [orgInsights, setOrgInsights] = useState<OrgInsight[]>([]);
  const [hubPatterns, setHubPatterns] = useState<Pattern[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Canvas scope: brief/synthesise only the canvas's curated-table intelligence,
      // keeping the Hub consistent with the canvas-scoped Briefing + Domains.
      const [domains, org, pat] = await Promise.all([
        canvasId ? getCanvasDomainInsights(canvasId) : getDomainInsights(connectionId),
        getOrgIntelligence(),
        (canvasId ? getCanvasPatterns(canvasId) : getPatterns(connectionId))
          .then(r => r.patterns ?? []).catch(() => [] as Pattern[]),
      ]);
      setDomainData(domains);
      setOrgInsights(org);
      setHubPatterns(pat);
    } catch {
      setDomainData({});
      setOrgInsights([]);
      setHubPatterns([]);
    } finally {
      setLoading(false);
    }
  }, [connectionId, canvasId]);

  useEffect(() => { load(); }, [load]);

  const domainList = useMemo(() =>
    Object.keys(domainData).sort().filter(d =>
      !search || d.toLowerCase().includes(search.toLowerCase())
    ),
    [domainData, search]
  );

  return (
    <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
      {/* Left sidebar — domain list */}
      <div style={{
        width: 200, borderRight: "1px solid var(--b1)", display: "flex",
        flexDirection: "column", flexShrink: 0, background: "var(--bg-0)",
      }}>
        {/* Sidebar header */}
        <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--b1)", flexShrink: 0 }}>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter domains…"
            style={{
              width: "100%", background: "var(--bg-2)", border: "1px solid var(--b1)",
              borderRadius: 5, padding: "4px 8px", fontSize: 11,
              color: "var(--t1)", outline: "none",
            }}
          />
        </div>

        {/* Domain list */}
        <div style={{ flex: 1, overflowY: "auto", padding: "6px" }}>
          {/* All domains entry */}
          <button
            onClick={() => setSelectedDomain(null)}
            style={{
              width: "100%", textAlign: "left", padding: "7px 10px",
              borderRadius: 5, fontSize: 12, fontWeight: 500, cursor: "pointer",
              background: !selectedDomain ? "var(--bg-sel)" : "transparent",
              border: `1px solid ${!selectedDomain ? "var(--blue2)" : "transparent"}`,
              color: !selectedDomain ? "var(--blue5)" : "var(--t2)",
              display: "flex", alignItems: "center", gap: 8, marginBottom: 2,
              transition: "all .1s",
            }}
            onMouseEnter={e => { if (selectedDomain) e.currentTarget.style.background = "var(--bg-hover)"; }}
            onMouseLeave={e => { if (selectedDomain) e.currentTarget.style.background = "transparent"; }}
          >
            <span style={{ fontSize: 11 }}>◈</span>
            <span>Hub Home</span>
            <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--t4)" }}>{Object.keys(domainData).length}</span>
          </button>

          {loading ? (
            [1, 2, 3, 4].map(i => (
              <div key={i} className="animate-pulse" style={{ height: 32, borderRadius: 5, background: "var(--bg-1)", marginBottom: 2 }} />
            ))
          ) : domainList.map(domain => {
            const d = domainData[domain];
            const orgCount = orgInsights.filter(o => o.domain?.toLowerCase() === domain.toLowerCase()).length;
            const isSelected = selectedDomain === domain;
            return (
              <button
                key={domain}
                onClick={() => setSelectedDomain(domain)}
                style={{
                  width: "100%", textAlign: "left", padding: "7px 10px",
                  borderRadius: 5, fontSize: 12, cursor: "pointer",
                  background: isSelected ? "var(--bg-sel)" : "transparent",
                  border: `1px solid ${isSelected ? "var(--blue2)" : "transparent"}`,
                  color: isSelected ? "var(--blue5)" : "var(--t2)",
                  display: "flex", alignItems: "center", gap: 6, marginBottom: 2,
                  transition: "all .1s", fontWeight: isSelected ? 600 : 400,
                }}
                onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = "var(--bg-hover)"; }}
                onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = "transparent"; }}
              >
                <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textTransform: "capitalize" }}>{domain}</span>
                <span style={{ fontSize: 10, color: "var(--t4)", flexShrink: 0 }}>{d.insights.length}</span>
                {orgCount > 0 && (
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--vio3)", flexShrink: 0 }} />
                )}
              </button>
            );
          })}
        </div>

        {/* Sidebar footer */}
        <div style={{ padding: "8px 12px", borderTop: "1px solid var(--b0)" }}>
          <button
            onClick={load}
            style={{
              width: "100%", fontSize: 11, color: "var(--t3)", background: "none",
              border: "1px solid var(--b1)", borderRadius: 4, padding: "4px 0", cursor: "pointer",
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Main content */}
      {loading ? (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12, padding: 24 }}>
          {[1, 2, 3].map(i => (
            <div key={i} className="animate-pulse" style={{ height: 140, borderRadius: 8, background: "var(--bg-1)" }} />
          ))}
        </div>
      ) : selectedDomain && domainData[selectedDomain] ? (
        <DomainProfile
          domain={selectedDomain}
          data={domainData[selectedDomain]}
          orgInsights={orgInsights}
          connectionId={connectionId}
          canvasId={canvasId}
          onBack={() => setSelectedDomain(null)}
        />
      ) : (
        <SynthesisHome
          domainData={domainData}
          orgInsights={orgInsights}
          patterns={hubPatterns}
          onSelectDomain={setSelectedDomain}
        />
      )}
    </div>
  );
}
