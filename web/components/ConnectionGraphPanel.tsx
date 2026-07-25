"use client";
import React, { useCallback, useEffect, useState } from "react";
import {
  ConnectionGraph,
  ConnectionTour,
  CGNode,
  CGStaleness,
  getConnectionGraph,
  getConnectionTour,
} from "@/lib/api";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { Button } from "@/components/ui/button";
import { StatusChip, ChipHue } from "@/components/brief/StatusChip";
import { formatCount, pct } from "@/lib/format";

// The connection knowledge graph, rendered as a three-level ANTI-HAIRBALL surface:
// domain cluster cards (cross-domain joins collapsed to counts) → the tables inside a
// domain → a table detail page (columns, verified joins with MEASURED overlap, glossary
// terms, and the past findings that touch the table — the J6 "entity page").

const STALE_HUE: Record<CGStaleness, ChipHue> = {
  fresh: "positive", dirty: "caution", stale: "negative", unknown: "muted",
};
const STALE_LABEL: Record<CGStaleness, string> = {
  fresh: "Fresh", dirty: "Data moved", stale: "Stale — rebuild", unknown: "Freshness unknown",
};

type View =
  | { level: "domains" }
  | { level: "tables"; domain: string }
  | { level: "detail"; tableId: string };

function bare(t: string): string {
  return String(t).split(".").pop()!.trim().replace(/"/g, "").toLowerCase();
}

export function ConnectionGraphPanel({ connectionId, schema }: { connectionId: string; schema?: string }) {
  const [graph, setGraph] = useState<ConnectionGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>({ level: "domains" });
  // Wave C5 — the topology-ordered tour, lazily fetched on first open.
  const [tour, setTour] = useState<ConnectionTour | null>(null);
  const [tourError, setTourError] = useState<string | null>(null);
  const [showTour, setShowTour] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    setTour(null);
    setTourError(null);
    setShowTour(false);
    getConnectionGraph(connectionId, schema)
      .then((g) => { setGraph(g); setView({ level: "domains" }); })
      .catch((e) => setError(e?.message || "Failed to load the knowledge graph"))
      .finally(() => setLoading(false));
  }, [connectionId, schema]);

  useEffect(() => { load(); }, [load]);

  const openTour = useCallback(() => {
    setShowTour(true);
    if (!tour && !tourError) {
      getConnectionTour(connectionId, schema)
        .then(setTour)
        .catch((e) => setTourError(e?.message || "Tour unavailable"));
    }
  }, [connectionId, schema, tour, tourError]);

  // ── derived accessors ──────────────────────────────────────────────────────
  const nodesArr = graph ? Object.values(graph.nodes) : [];
  const edgesArr = graph ? Object.values(graph.edges) : [];
  const node = (id: string): CGNode | undefined => graph?.nodes[id];
  const nodeData = (id: string): Record<string, unknown> => graph?.nodes[id]?.data || {};

  const domainOf = (n: CGNode): string => (n.data.domain as string) || "Ungrouped";
  const tablesOf = (domainLabel: string): CGNode[] =>
    nodesArr.filter((n) => n.kind === "table" && domainOf(n) === domainLabel);
  const columnsFor = (id: string): string[] => (nodeData(id).columns as string[]) || [];

  const joinsFor = (tableId: string) =>
    edgesArr
      .filter((e) => e.kind === "joins_on" && (e.from_id === tableId || e.to_id === tableId))
      .map((e) => {
        const otherId = e.from_id === tableId ? e.to_id : e.from_id;
        return { other: node(otherId)?.label || otherId, overlap: e.provenance.measured, note: e.provenance.note };
      });

  const findingsFor = (tableId: string): CGNode[] =>
    edgesArr
      .filter((e) => e.kind === "grounded_in" && e.to_id === tableId)
      .map((e) => node(e.from_id))
      .filter((n): n is CGNode => !!n && n.kind === "finding");

  const termsFor = (tableId: string): CGNode[] => {
    const src = new Set(((nodeData(tableId).source_tables as string[]) || []).map(bare));
    return nodesArr.filter((n) => n.kind === "glossary_term" && src.has(bare((n.data.table as string) || "")));
  };

  const domainJoinsFor = (domainLabel: string) =>
    (graph?.domain_edges || [])
      .filter((d) => d.from === domainLabel || d.to === domainLabel)
      .map((d) => ({ other: d.from === domainLabel ? d.to : d.from, count: d.count }));

  // ── render ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px", borderBottom: "1px solid var(--bg-3)" }}>
        <span style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>Knowledge Graph</span>
        {graph && (
          <StatusChip hue={STALE_HUE[graph.staleness]} strength="soft" title={`Graph freshness: ${graph.staleness}`}>
            {STALE_LABEL[graph.staleness]}
          </StatusChip>
        )}
        <div style={{ flex: 1 }} />
        <Button variant="ghost" onClick={() => setShowTour(false)}
                style={{ fontSize: 12, color: showTour ? "var(--t3)" : "var(--t1)" }}>Explore</Button>
        <Button variant="ghost" onClick={openTour}
                style={{ fontSize: 12, color: showTour ? "var(--t1)" : "var(--t3)" }}>Tour</Button>
        <Button variant="ghost" onClick={load} style={{ color: "var(--t3)", fontSize: 12 }}>↻ Refresh</Button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        {loading && <p style={{ color: "var(--t3)", fontSize: 13 }}>Loading the connection knowledge graph…</p>}
        {error && <p style={{ color: "var(--red3)", fontSize: 13 }}>{error}</p>}

        {!loading && !error && graph && (showTour ? (
          <TourView tour={tour} error={tourError} />
        ) : (
          <>
            <MiniStatRow>
              <MiniStat value={formatCount(graph.counts.table || 0)} label="Tables" />
              <MiniStat value={formatCount(graph.counts.edges || 0)} label="Edges" />
              <MiniStat value={formatCount(graph.counts.finding || 0)} label="Findings"
                        tone={(graph.counts.finding || 0) > 0 ? "var(--vio4)" : "var(--t1)"} />
              <MiniStat value={formatCount(graph.counts.metric || 0)} label="Metrics" />
              <MiniStat value={formatCount(graph.counts.glossary_term || 0)} label="Terms" />
            </MiniStatRow>

            {/* Breadcrumb */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 14, fontSize: 12, color: "var(--t3)" }}>
              <Button variant="ghost" onClick={() => setView({ level: "domains" })}
                      style={{ padding: 0, color: view.level === "domains" ? "var(--t1)" : "var(--t3)", fontSize: 12 }}>
                Domains
              </Button>
              {view.level === "tables" && <><span>/</span><span style={{ color: "var(--t1)" }}>{view.domain}</span></>}
              {view.level === "detail" && (
                <>
                  <span>/</span>
                  <Button variant="ghost"
                          onClick={() => setView({ level: "tables", domain: domainOf(node(view.tableId) || ({ data: {} } as CGNode)) })}
                          style={{ padding: 0, color: "var(--t3)", fontSize: 12 }}>
                    {domainOf(node(view.tableId) || ({ data: {} } as CGNode))}
                  </Button>
                  <span>/</span>
                  <span style={{ color: "var(--t1)" }}>{node(view.tableId)?.label}</span>
                </>
              )}
            </div>

            {/* Level 1 — domain cluster cards */}
            {view.level === "domains" && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12 }}>
                {graph.domains.map((d) => (
                  <div key={d.label} onClick={() => setView({ level: "tables", domain: d.label })}
                       style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 16, cursor: "pointer" }}>
                    <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", marginBottom: 6 }}>{d.label}</div>
                    <div style={{ fontSize: 12, color: "var(--t3)" }}>{formatCount(d.table_count)} tables</div>
                    {domainJoinsFor(d.label).length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                        {domainJoinsFor(d.label).map((j) => (
                          <StatusChip key={j.other} hue="info" strength="soft" title={`${j.count} cross-domain join(s) to ${j.other}`}>
                            {j.other} · {j.count}
                          </StatusChip>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                {graph.domains.length === 0 && <p style={{ color: "var(--t3)", fontSize: 13 }}>No domains yet.</p>}
              </div>
            )}

            {/* Level 2 — tables inside a domain */}
            {view.level === "tables" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {tablesOf(view.domain).map((t) => (
                  <div key={t.id} onClick={() => setView({ level: "detail", tableId: t.id })}
                       style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "12px 16px", cursor: "pointer", display: "flex", alignItems: "center", gap: 12 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{t.label}</div>
                      {t.summary && <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>{t.summary}</div>}
                    </div>
                    <span style={{ fontSize: 11, color: "var(--t3)" }}>{formatCount(columnsFor(t.id).length)} cols</span>
                    {joinsFor(t.id).length > 0 && <StatusChip hue="info" strength="soft">{joinsFor(t.id).length} joins</StatusChip>}
                    {findingsFor(t.id).length > 0 && <StatusChip hue="accent" strength="soft">{findingsFor(t.id).length} findings</StatusChip>}
                  </div>
                ))}
                {tablesOf(view.domain).length === 0 && <p style={{ color: "var(--t3)", fontSize: 13 }}>No tables in this domain.</p>}
              </div>
            )}

            {/* Level 3 — table detail (the entity page) */}
            {view.level === "detail" && (() => {
              const t = node(view.tableId);
              if (!t) return <p style={{ color: "var(--t3)", fontSize: 13 }}>Table not found.</p>;
              const joins = joinsFor(t.id);
              const findings = findingsFor(t.id);
              const terms = termsFor(t.id);
              const cols = columnsFor(t.id);
              return (
                <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 600, color: "var(--t1)" }}>{t.label}</div>
                    <div style={{ fontSize: 12, color: "var(--t3)", marginTop: 2 }}>
                      {((t.data.source_tables as string[]) || []).join(", ")} · {formatCount(cols.length)} columns
                    </div>
                  </div>

                  <Section title="Verified joins — measured value-domain overlap">
                    {joins.length === 0 ? <Muted>No joins.</Muted> : joins.map((j, i) => (
                      <div key={i} style={ROW}>
                        <span style={{ color: "var(--t1)", fontSize: 12 }}>→ {j.other}</span>
                        {j.overlap != null
                          ? <StatusChip hue={j.overlap >= 0.5 ? "positive" : "caution"} strength="soft" title={j.note}>overlap {pct(j.overlap)}</StatusChip>
                          : <StatusChip hue="muted" strength="soft" title={j.note}>unprobed</StatusChip>}
                      </div>
                    ))}
                  </Section>

                  <Section title="Past findings on this table">
                    {findings.length === 0 ? <Muted>None yet.</Muted> : findings.map((f) => (
                      <div key={f.id} style={{ ...ROW, alignItems: "flex-start" }}>
                        <StatusChip hue="accent" strength="soft" title={`source: ${f.provenance.source}`}>{f.provenance.source}</StatusChip>
                        <span style={{ color: "var(--t2)", fontSize: 12 }}>{f.summary}</span>
                      </div>
                    ))}
                  </Section>

                  <Section title="Glossary terms">
                    {terms.length === 0 ? <Muted>None.</Muted> : terms.map((tm) => (
                      <div key={tm.id} style={{ ...ROW, alignItems: "flex-start" }}>
                        <span style={{ color: "var(--t1)", fontWeight: 600, fontSize: 12 }}>{tm.label}</span>
                        <span style={{ color: "var(--t3)", fontSize: 12 }}>{tm.summary}</span>
                      </div>
                    ))}
                  </Section>

                  <Section title="Columns">
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {cols.map((c) => (
                        <span key={c} style={{ fontSize: 11, color: "var(--t2)", background: "var(--bg-3)", borderRadius: "var(--r1)", padding: "2px 8px", fontFamily: "monospace" }}>{c}</span>
                      ))}
                    </div>
                  </Section>
                </div>
              );
            })()}
          </>
        ))}
      </div>
    </div>
  );
}

// Wave C5 — the topology-ordered tour: a numbered curriculum where every step names the
// prior step it builds on (the `connects_to_label`), with the deterministic significance
// and the LLM narration when present.
function TourView({ tour, error }: { tour: ConnectionTour | null; error: string | null }) {
  if (error) return <p style={{ color: "var(--t3)", fontSize: 13 }}>{error}</p>;
  if (!tour) return <p style={{ color: "var(--t3)", fontSize: 13 }}>Building the tour…</p>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 720 }}>
      <p style={{ color: "var(--t3)", fontSize: 12, marginBottom: 4 }}>
        A reading order computed from the graph — the hub first, then a breadth-first walk, then the
        metrics as the capstone. Each step builds on the one before it.
      </p>
      {tour.steps.map((s) => (
        <div key={s.node_id} style={{ display: "flex", gap: 12, background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "12px 16px" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--t3)", minWidth: 22, fontVariantNumeric: "tabular-nums" }}>{s.order + 1}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{s.label}</span>
              <StatusChip hue={s.kind === "metric" ? "accent" : "info"} strength="soft">{s.kind}</StatusChip>
              {s.connects_to_label && (
                <span style={{ fontSize: 11, color: "var(--t3)" }}>↳ builds on {s.connects_to_label} · {s.connection}</span>
              )}
            </div>
            <div style={{ fontSize: 12, color: "var(--t2)", marginTop: 4 }}>{s.narration || s.why}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

const ROW: React.CSSProperties = { display: "flex", alignItems: "center", gap: 10, padding: "5px 0" };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}
function Muted({ children }: { children: React.ReactNode }) {
  return <p style={{ color: "var(--t3)", fontSize: 12 }}>{children}</p>;
}
