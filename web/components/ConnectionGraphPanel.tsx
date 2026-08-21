"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ConnectionGraph,
  ConnectionTour,
  CGNode,
  CGStaleness,
  GraphAudit,
  GraphLineage,
  TrustSidecar,
  GraphReview,
  GraphReviewItem,
  getConnectionGraph,
  getConnectionTour,
  getGraphAudit,
  getGraphLineage,
  getGraphReview,
  getGraphTrust,
  listGovernedTags,
  type GovernedTag,
} from "@/lib/api";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { Button } from "@/components/ui/button";
import { StatusChip, ChipHue } from "@/components/brief/StatusChip";
import { formatCount } from "@/lib/format";
import { GraphCanvas } from "@/components/GraphCanvas";
import { GraphAuditBar, StandingChip, WarrantChip } from "@/components/graph/WarrantChip";

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

// The Ask seam is renamed at the door: the panel's own vocabulary is 'ask', and the
// prop name is the workspace's older spelling of the same callback.
export function ConnectionGraphPanel({ connectionId, schema, onInvestigate: onAsk, initialTableId }: {
  connectionId: string; schema?: string;
  /** The workspace Ask seam — a graph selection becomes a question on the full Ask surface. */
  onInvestigate?: (q: string) => void;
  /** S1 deep link — open straight onto one entity's detail page (`?table=` in the URL). */
  initialTableId?: string;
}) {
  const [graph, setGraph] = useState<ConnectionGraph | null>(null);
  // S1/J13 — the governance axis on the entity page: G2 tags were write-only
  // (store, no route, no UI). One fetch of table-kind tags serves every detail
  // view; a tag matches an entity when its securable's table segment equals one
  // of the entity's source tables. Best-effort: no tags plane ⇒ no chip row.
  const [governedTags, setGovernedTags] = useState<GovernedTag[]>([]);
  useEffect(() => {
    listGovernedTags({ securablePrefix: "table:" })
      .then(setGovernedTags)
      .catch(() => setGovernedTags([]));
  }, [connectionId]);
  const tagsForEntity = (sourceTables: string[]): GovernedTag[] => {
    const wants = new Set(sourceTables.map((s) => (s.split(".").pop() || s).toLowerCase()));
    return governedTags.filter((t) => {
      const seg = t.securable.slice("table:".length).split(".").pop() || "";
      return wants.has(seg.toLowerCase());
    });
  };
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>({ level: "domains" });
  // Map = the node-link canvas (default — a knowledge graph should look like one);
  // Explore = the C4 anti-hairball card drill-down; Tour = the C5 topology walk.
  const [mode, setMode] = useState<"map" | "cards" | "tour" | "review">("map");
  // Wave C5 — the topology-ordered tour, lazily fetched on first open.
  // S1 — the entity page is addressable: entering a detail view stamps `?table=`
  // (replace, not push — the TAB is the history unit; the entity refines it),
  // leaving removes it. page.tsx owns tab/conn/layer; this param is the panel's.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const current = params.get("table");
    const want = view.level === "detail" ? view.tableId : null;
    if (current === want || (!current && !want)) return;
    if (want) params.set("table", want); else params.delete("table");
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, [view]);

  const [tour, setTour] = useState<ConnectionTour | null>(null);
  const [tourError, setTourError] = useState<string | null>(null);
  // Wave P2 — the honesty scorecard (warrant mix + the CONTENT drift axis the staleness
  // chip does not cover). A second call because it costs an in-memory re-projection; the
  // graph renders whether or not it arrives.
  const [audit, setAudit] = useState<GraphAudit | null>(null);
  // Wave P5 — what the graph knows it cannot vouch for, fetched with the graph so the tab
  // can carry its count without a second click to discover there is nothing to do.
  const [review, setReview] = useState<GraphReview | null>(null);
  // Wave P3 — what standing each node has earned. A read-time sidecar: it annotates the
  // graph on screen and is never written back into the committed artifact.
  const [trust, setTrust] = useState<TrustSidecar | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  // Identifies the in-flight load, so a response from a superseded one is discarded.
  const loadToken = useRef(0);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    setTour(null);
    setTourError(null);
    setAudit(null);
    setReview(null);
    setReviewError(null);
    setTrust(null);
    setMode("map");
    // Every response is checked against the token that requested it. Without this,
    // switching connections mid-flight renders B's graph beside A's audit, drift reason
    // and standing chips — four independent fetches, four chances to mismatch.
    const token = ++loadToken.current;
    const fresh = () => token === loadToken.current;
    getConnectionGraph(connectionId, schema)
      .then((g) => {
        if (!fresh()) return;
        setGraph(g);
        // S1 — a `?table=` deep link opens the entity page directly; an unknown
        // id degrades to the domains view rather than erroring.
        if (initialTableId && g.nodes[initialTableId]) {
          setMode("cards");
          setView({ level: "detail", tableId: initialTableId });
        } else {
          setView({ level: "domains" });
        }
      })
      .catch((e) => { if (fresh()) setError(e?.message || "Failed to load the knowledge graph"); })
      .finally(() => { if (fresh()) setLoading(false); });
    getGraphAudit(connectionId, schema)
      .then((a) => { if (fresh()) setAudit(a); }).catch(() => { if (fresh()) setAudit(null); });
    getGraphReview(connectionId, schema)
      .then((r) => { if (fresh()) setReview(r); })
      .catch((e) => { if (fresh()) setReviewError(e?.message || "Review unavailable"); });
    getGraphTrust(connectionId, schema)
      .then((t) => { if (fresh()) setTrust(t); }).catch(() => { if (fresh()) setTrust(null); });
  }, [connectionId, schema]);

  useEffect(() => { load(); }, [load]);

  const openTour = useCallback(() => {
    setMode("tour");
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
        return { other: node(otherId)?.label || otherId, warrant: e.warrant, note: e.provenance.note };
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
          // P2: a Fresh badge is about the SCHEMA only. When the content axis says the
          // graph is missing what the platform has since learned, the badge must not
          // stand alone saying "Fresh" — that reading is the exact blindness
          // `content_drift` was written to prevent.
          <StatusChip
            hue={audit?.drift?.drifted ? "caution" : STALE_HUE[graph.staleness]}
            strength="soft"
            title={audit?.drift?.drifted
              ? `Schema freshness: ${graph.staleness}. ${audit.drift.reason}`
              : `Graph freshness: ${graph.staleness}`}
          >
            {audit?.drift?.drifted ? "Rebuild owed" : STALE_LABEL[graph.staleness]}
          </StatusChip>
        )}
        <div style={{ flex: 1 }} />
        <Button variant="ghost" onClick={() => setMode("map")}
                style={{ fontSize: 12, color: mode === "map" ? "var(--t1)" : "var(--t3)" }}>Map</Button>
        <Button variant="ghost" onClick={() => setMode("cards")}
                style={{ fontSize: 12, color: mode === "cards" ? "var(--t1)" : "var(--t3)" }}>Explore</Button>
        <Button variant="ghost" onClick={openTour}
                style={{ fontSize: 12, color: mode === "tour" ? "var(--t1)" : "var(--t3)" }}>Tour</Button>
        <Button variant="ghost" onClick={() => setMode("review")}
                style={{ fontSize: 12, color: mode === "review" ? "var(--t1)" : "var(--t3)" }}>
          Review{review && review.total > 0 ? ` · ${review.total}` : ""}
        </Button>
        <Button variant="ghost" onClick={load} style={{ color: "var(--t3)", fontSize: 12 }}>↻ Refresh</Button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 20, display: "flex", flexDirection: "column" }}>
        {loading && <p style={{ color: "var(--t3)", fontSize: 13 }}>Loading the connection knowledge graph…</p>}
        {error && <p style={{ color: "var(--red3)", fontSize: 13 }}>{error}</p>}

        {!loading && !error && graph && mode === "map" && (
          <>
            <MiniStatRow>
              <MiniStat value={formatCount(graph.counts.table || 0)} label="Tables" />
              <MiniStat value={formatCount(graph.counts.edges || 0)} label="Edges" />
              <MiniStat value={formatCount(graph.counts.finding || 0)} label="Findings"
                        tone={(graph.counts.finding || 0) > 0 ? "var(--vio4)" : "var(--t1)"} />
              <MiniStat value={formatCount(graph.counts.metric || 0)} label="Metrics" />
              <MiniStat value={formatCount(graph.counts.glossary_term || 0)} label="Terms" />
            </MiniStatRow>
            <GraphAuditBar audit={audit} />
            <GraphCanvas
              graph={graph}
              onOpenTable={(tableId) => { setMode("cards"); setView({ level: "detail", tableId }); }}
              onAsk={onAsk}
            />
          </>
        )}

        {!loading && !error && graph && mode === "review" && (
          <ReviewView review={review} error={reviewError} onAsk={onAsk}
                      isTableNode={(id) => !!graph?.nodes[id] && graph.nodes[id].kind === "table"}
                      onOpenTable={(id) => { setMode("cards"); setView({ level: "detail", tableId: id }); }} />
        )}

        {!loading && !error && graph && mode !== "map" && mode !== "review" && (mode === "tour" ? (
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
            <GraphAuditBar audit={audit} />

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
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 16, fontWeight: 600, color: "var(--t1)" }}>{t.label}</span>
                      {/* P3 standing sits beside P2's warrant deliberately: a table can be
                          measured (how we know it) and still unchecked (nobody confirmed
                          the answers built on it). One score would hide that gap. */}
                      <StandingChip trust={trust?.nodes?.[t.id]} />
                    </div>
                    <div style={{ fontSize: 12, color: "var(--t3)", marginTop: 2 }}>
                      {((t.data.source_tables as string[]) || []).join(", ")} · {formatCount(cols.length)} columns
                    </div>
                    {(() => {
                      const tags = tagsForEntity((t.data.source_tables as string[]) || []);
                      if (!tags.length) return null;
                      return (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                          {tags.map((tag) => (
                            <span key={`${tag.securable}:${tag.key}`}
                                  title={`${tag.securable} — set by ${tag.set_by || tag.source}`}
                                  style={{ fontSize: 11, padding: "1px 7px", borderRadius: "var(--r-chip)",
                                           background: "var(--bg-2)", border: "1px solid var(--b2)",
                                           color: "var(--t2)" }}>
                              {tag.key}: {tag.value}
                            </span>
                          ))}
                        </div>
                      );
                    })()}
                    {trust?.nodes?.[t.id] && (
                      <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 4 }}>
                        {trust.nodes[t.id].detail}
                      </div>
                    )}
                  </div>

                  {/* P2: every join states its warrant. A measured overlap and a bare
                      name match used to look the same here. */}
                  <Section title="Joins — and how each one is known">
                    {joins.length === 0 ? <Muted>No joins.</Muted> : joins.map((j, i) => (
                      <div key={i} style={ROW}>
                        <span style={{ color: "var(--t1)", fontSize: 12 }}>→ {j.other}</span>
                        <WarrantChip warrant={j.warrant} showDetail />
                      </div>
                    ))}
                  </Section>

                  <Section title="Past findings on this table">
                    {findings.length === 0 ? <Muted>None yet.</Muted> : findings.map((f) => (
                      <div key={f.id} style={{ ...ROW, alignItems: "flex-start" }}>
                        <WarrantChip warrant={f.warrant} />
                        <span style={{ color: "var(--t2)", fontSize: 12 }}>{f.summary}</span>
                      </div>
                    ))}
                  </Section>

                  <Section title="Glossary terms">
                    {terms.length === 0 ? <Muted>None.</Muted> : terms.map((tm) => (
                      <div key={tm.id} style={{ ...ROW, alignItems: "flex-start" }}>
                        <span style={{ color: "var(--t1)", fontWeight: 600, fontSize: 12 }}>{tm.label}</span>
                        <WarrantChip warrant={tm.warrant} />
                        <span style={{ color: "var(--t3)", fontSize: 12 }}>{tm.summary}</span>
                      </div>
                    ))}
                  </Section>

                  {/* P4: what breaks if this table changes — reported, never deleted. */}
                  <DependentsSection connectionId={connectionId} schema={schema} nodeId={t.id} />

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

/**
 * Wave P4 — what depends on this node, each dependent showing the expression that would
 * break rather than only its name.
 *
 * Loaded when the entity page opens (it walks the graph), and silent when nothing depends
 * on the table: an empty "Dependents: none" section on every leaf table is noise, while
 * the section appearing at all is itself the signal that something downstream exists.
 */
function DependentsSection({ connectionId, schema, nodeId }: {
  connectionId: string; schema?: string; nodeId: string;
}) {
  const [lineage, setLineage] = useState<GraphLineage | null>(null);
  useEffect(() => {
    let alive = true;
    setLineage(null);
    getGraphLineage(connectionId, { nodeId, schemaName: schema })
      .then((l) => { if (alive) setLineage(l); })
      .catch(() => {});
    return () => { alive = false; };
  }, [connectionId, schema, nodeId]);

  if (!lineage || lineage.dependents.length === 0) return null;
  return (
    <Section title={`What depends on this — ${lineage.dependents.length}`}>
      <div style={{ fontSize: 11, color: "var(--t3)", marginBottom: 4 }}>{lineage.summary}</div>
      {lineage.dependents.map((d) => (
        <div key={d.node_id} style={{ ...ROW, alignItems: "center", flexWrap: "nowrap" }}>
          <StatusChip hue={d.kind === "metric" ? "info" : "accent"} strength="soft">{d.kind}</StatusChip>
          <span style={{ color: "var(--t1)", fontSize: 12, whiteSpace: "nowrap",
                         overflow: "hidden", textOverflow: "ellipsis", maxWidth: 340,
                         flexShrink: 0 }}
                title={d.label}>{d.label}</span>
          {d.site && (
            // One line, ellipsised, full text on hover. Sites run to 200 characters of
            // SQL; rendered in full they wrapped to their own row and the list stopped
            // being scannable — which defeats the point, since this section exists to be
            // skimmed for the one artifact worth opening.
            <code
              title={`${d.site_line > 0 ? `line ${d.site_line}: ` : ""}${d.site}`}
              style={{
                fontSize: 11, color: "var(--t3)", background: "var(--bg-3)",
                borderRadius: "var(--r1)", padding: "1px 6px",
                maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap", flexShrink: 1, minWidth: 0,
              }}
            >
              {d.site_line > 0 ? `line ${d.site_line}: ` : ""}{d.site}
            </code>
          )}
        </div>
      ))}
    </Section>
  );
}

// Wave P5 — the review queue: what the graph knows it cannot vouch for, before anyone
// asks a question. Every item names what is in doubt, why it matters in consequences
// rather than mechanism, and the one check that would settle it.
const REVIEW_HUE: Record<GraphReviewItem["type"], ChipHue> = {
  graph_behind: "caution",
  unprobed_join: "caution",
  contested_finding: "accent",
  ungrounded_finding: "muted",
  undocumented_hub: "info",
  isolated_table: "muted",
};
const REVIEW_LABEL: Record<GraphReviewItem["type"], string> = {
  graph_behind: "Graph is behind",
  unprobed_join: "Unprobed join",
  contested_finding: "Contested",
  ungrounded_finding: "Ungrounded",
  undocumented_hub: "Undocumented hub",
  isolated_table: "Isolated",
};
const CHECK_LABEL: Record<GraphReviewItem["check"], string> = {
  probe_join: "Measure this join",
  ask: "Ask about it",
  review_finding: "Settle this",
  define: "Define it",
  rebuild: "Rebuild the graph",
};

function ReviewView({ review, error, onAsk, isTableNode, onOpenTable }: {
  review: GraphReview | null;
  error: string | null;
  onAsk?: (q: string) => void;
  /** True when the id names a table NODE — not an edge id that merely starts "table:". */
  isTableNode: (id: string) => boolean;
  onOpenTable?: (tableId: string) => void;
}) {
  // A failed fetch used to render as "Checking the graph…" forever — the same
  // indistinguishable-states bug the Fresh badge had.
  if (error) return <p style={{ color: "var(--t3)", fontSize: 13 }}>{error}</p>;
  if (!review) return <p style={{ color: "var(--t3)", fontSize: 13 }}>Checking the graph…</p>;
  if (review.total === 0) {
    return (
      <p style={{ color: "var(--t3)", fontSize: 13, maxWidth: 620 }}>
        Nothing to review. Every join in this graph has been measured, every table is
        connected and defined, and no finding is contested.
      </p>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 760 }}>
      <p style={{ color: "var(--t3)", fontSize: 12 }}>
        {review.truncated
          ? `${review.total} of ${review.total_found} things this graph cannot vouch for`
          : `${review.total} thing${review.total !== 1 ? "s" : ""} this graph cannot vouch for`}
        , most consequential first — ranked by how much depends on each, never by a guessed
        severity.
      </p>
      {review.items.map((it) => (
        <div key={it.id} style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "12px 16px", display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            {/* Guarded: `type` is a plain string server-side, and an unknown value would
                index StatusChip's hue map with undefined and unmount the panel. */}
            <StatusChip hue={REVIEW_HUE[it.type] || "muted"} strength="soft">
              {REVIEW_LABEL[it.type] || it.type.replace(/_/g, " ")}
            </StatusChip>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{it.question}</span>
          </div>
          <div style={{ fontSize: 12, color: "var(--t3)" }}>{it.why}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {/* Every check routes to something that already exists — the Ask surface for
                the ones a question settles, the entity page for the ones a human reads.
                An item whose check has no home would be a to-do list, not a queue. */}
            {onAsk && (it.check === "ask" || it.check === "probe_join" || it.check === "define") && (
              <Button variant="ghost" onClick={() => onAsk(it.question)}
                      style={{ fontSize: 12, padding: 0, color: "var(--t2)" }}>
                {CHECK_LABEL[it.check] || "Check this"} →
              </Button>
            )}
            {/* An unprobed_join's subject_id is an EDGE id
                ("table:orders--joins_on-->table:customers"), which ALSO starts with
                "table:" — the prefix test sent the queue's top-ranked item to a
                "Table not found." page. Test for the node itself. */}
            {onOpenTable && isTableNode(it.subject_id) && (
              <Button variant="ghost" onClick={() => onOpenTable(it.subject_id)}
                      style={{ fontSize: 12, padding: 0, color: "var(--t3)" }}>
                Open {it.subject_label}
              </Button>
            )}
            {it.depends > 0 && (
              <span style={{ fontSize: 11, color: "var(--t4)" }}>
                {formatCount(it.depends)} thing{it.depends !== 1 ? "s" : ""} depend on this
              </span>
            )}
          </div>
        </div>
      ))}
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
