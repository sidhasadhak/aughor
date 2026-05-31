"use client";

import { useEffect, useState, useCallback } from "react";
import { getOrgIntelligence, deleteOrgInsight, type OrgInsight } from "@/lib/api";

// ── Novelty label ──────────────────────────────────────────────────────────────

function noveltyLabel(n: number): { label: string; color: string } {
  if (n >= 5) return { label: "High", color: "var(--grn3)" };
  if (n >= 3) return { label: "Mid",  color: "var(--amb3)" };
  return           { label: "Low",  color: "var(--t3)" };
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

// ── Insight card ──────────────────────────────────────────────────────────────

function InsightCard({ insight, onDelete }: { insight: OrgInsight; onDelete: () => void }) {
  const [deleting, setDeleting] = useState(false);
  const nov = noveltyLabel(insight.novelty ?? 3);

  const handleDelete = async () => {
    if (deleting) return;
    setDeleting(true);
    try {
      await deleteOrgInsight(insight.id);
      onDelete();
    } catch {
      setDeleting(false);
    }
  };

  return (
    <div
      style={{
        background: "var(--bg-1)",
        border: "1px solid var(--b1)",
        borderRadius: 6,
        padding: "10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      {/* Meta row */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        {insight.domain && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              color: "var(--b3)",
              background: "color-mix(in srgb, var(--b3) 12%, transparent)",
              borderRadius: 3,
              padding: "1px 5px",
            }}
          >
            {insight.domain}
          </span>
        )}
        {insight.angle && (
          <span style={{ fontSize: 10, color: "var(--t3)" }}>{insight.angle}</span>
        )}
        <span style={{ marginLeft: "auto", fontSize: 10, color: nov.color, fontWeight: 600 }}>
          {nov.label} novelty
        </span>
      </div>

      {/* Finding text */}
      <p style={{ margin: 0, fontSize: 12, color: "var(--t2)", lineHeight: 1.55 }}>
        {insight.text}
      </p>

      {/* Footer row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 2 }}>
        <span style={{ fontSize: 10, color: "var(--t3)" }}>
          Promoted {fmtDate(insight.promoted_at)}
        </span>
        {insight.canvas_id && (
          <span
            style={{
              fontSize: 10,
              color: "var(--t3)",
              background: "var(--bg-2)",
              borderRadius: 3,
              padding: "1px 5px",
              fontFamily: "var(--font-mono)",
            }}
          >
            canvas:{insight.canvas_id.slice(0, 8)}
          </span>
        )}
        <button
          onClick={handleDelete}
          disabled={deleting}
          style={{
            marginLeft: "auto",
            fontSize: 10,
            color: deleting ? "var(--t3)" : "var(--r3)",
            background: "none",
            border: "none",
            cursor: deleting ? "default" : "pointer",
            padding: "2px 6px",
            borderRadius: 3,
          }}
        >
          {deleting ? "…" : "Remove"}
        </button>
      </div>
    </div>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────────

export function OrgIntelPanel() {
  const [insights, setInsights] = useState<OrgInsight[]>([]);
  const [loading, setLoading]   = useState(true);
  const [search, setSearch]     = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setInsights(await getOrgIntelligence());
    } catch {
      setInsights([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleDelete = (id: string) => {
    setInsights(prev => prev.filter(i => i.id !== id));
  };

  // Filter + group by domain
  const filtered = insights.filter(i =>
    !search || i.text.toLowerCase().includes(search.toLowerCase()) || i.domain.toLowerCase().includes(search.toLowerCase())
  );

  const domains = Array.from(new Set(filtered.map(i => i.domain || "General"))).sort();

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden", gap: 0 }}>
      {/* Toolbar */}
      <div
        style={{
          padding: "10px 16px",
          borderBottom: "1px solid var(--b1)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexShrink: 0,
        }}
      >
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Filter insights…"
          style={{
            flex: 1,
            background: "var(--bg-2)",
            border: "1px solid var(--b1)",
            borderRadius: 5,
            padding: "5px 10px",
            fontSize: 12,
            color: "var(--t1)",
            outline: "none",
          }}
        />
        <span style={{ fontSize: 11, color: "var(--t3)", whiteSpace: "nowrap" }}>
          {filtered.length} insight{filtered.length !== 1 ? "s" : ""}
        </span>
        <button
          onClick={load}
          style={{
            fontSize: 11,
            color: "var(--t3)",
            background: "none",
            border: "1px solid var(--b1)",
            borderRadius: 4,
            padding: "4px 8px",
            cursor: "pointer",
          }}
        >
          Refresh
        </button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: "16px" }}>
        {loading ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[1, 2, 3].map(i => (
              <div
                key={i}
                className="animate-pulse"
                style={{ height: 80, borderRadius: 6, background: "var(--bg-1)" }}
              />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 10,
              height: 240,
              color: "var(--t3)",
            }}
          >
            <span style={{ fontSize: 32, opacity: 0.25 }}>◈</span>
            <span style={{ fontSize: 12 }}>
              {search ? "No insights match your filter" : "No org-wide intelligence yet"}
            </span>
            {!search && (
              <span style={{ fontSize: 11, color: "var(--t3)", maxWidth: 280, textAlign: "center" }}>
                Promote canvas domain insights via the "Promote to Org →" button in Domain Intel to build collective knowledge.
              </span>
            )}
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            {domains.map(domain => {
              const domainInsights = filtered.filter(i => (i.domain || "General") === domain);
              return (
                <section key={domain}>
                  <div
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.08em",
                      color: "var(--t3)",
                      marginBottom: 8,
                      paddingBottom: 4,
                      borderBottom: "1px solid var(--b1)",
                    }}
                  >
                    {domain}
                    <span style={{ fontWeight: 400, marginLeft: 6 }}>
                      · {domainInsights.length}
                    </span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {domainInsights.map(insight => (
                      <InsightCard
                        key={insight.id}
                        insight={insight}
                        onDelete={() => handleDelete(insight.id)}
                      />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
