"use client";
/**
 * The connection knowledge graph — the Intelligence workspace's Graph tab, redone to `aughor-v2/CLARITY.md`
 * (2026-10-13).
 *
 * It is a map, so it leads with the picture. Above it, one line of what the graph holds (tables · joins · metrics ·
 * findings · terms), with how well its joins are known and whether a rebuild is owed as two chips. Beside it, a side
 * panel: at rest, what waits on a person (the review queue, folded by kind, each with its check on the row) and how
 * every link is known; with a node chosen, that node's essentials first and its question to ask. There is no row of
 * figures over the picture and no amber card above it.
 *
 * The other three views keep what they held: Explore (domains → tables → one table's page, which the `?table=` deep
 * link opens straight onto), Tour (a reading order computed from the graph) and Review (the whole queue). Each says a
 * thing once — a reason shared by 27 unprobed joins sits above them, not on every row; a column and its glossary
 * definition are one line; the findings a table holds and what depends on it are counted, the rows behind a fold.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
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
  rebuildContextGraph,
  type GovernedTag,
} from "@/lib/api";
import { CARD, Chip, Dot, Empty, Label, MUTED, NUM, ONE_LINE, Page, ROW, RULE, type Tone } from "@/components/clarity/kit";
import { FoldLine, GroupHead, rowButtonStyle } from "@/components/semantic/parts";
import { Button } from "@/components/ui/button";
import { countNoun, fmtDate, formatCount } from "@/lib/format";
import { SkeletonRows } from "@/components/ui/motion";
import { ErrorState, ReadFailed } from "@/components/ui/states";
import { GraphCanvas, questionFor } from "@/components/GraphCanvas";
import { StandingChip, WarrantChip, WarrantMix } from "@/components/graph/WarrantChip";
import { Segmented } from "@/components/ui/segmented";
import {
  KIND_HUE, KIND_WORD, groupReview, joinsMeasured, nodeName, reviewWord, subjectName, waitingItems,
} from "@/lib/graphView";

const STALE: Record<CGStaleness, { tone: Tone; word: string }> = {
  fresh: { tone: "up", word: "Fresh" },
  dirty: { tone: "amber", word: "Data moved" },
  stale: { tone: "amber", word: "Stale — rebuild" },
  unknown: { tone: "plain", word: "Freshness unknown" },
};

type View =
  | { level: "domains" }
  | { level: "tables"; domain: string }
  | { level: "detail"; tableId: string };

type Mode = "map" | "cards" | "tour" | "review";

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
  // Explore = the anti-hairball drill-down; Tour = the topology walk; Review = the whole queue.
  const [mode, setMode] = useState<Mode>("map");
  // What is chosen on the map — the side panel says its essentials.
  const [chosen, setChosen] = useState<string[]>([]);
  // S1 — the entity page is addressable: entering a detail view stamps `?table=`
  // (replace, not push — the TAB is the history unit; the entity refines it),
  // leaving removes it. page.tsx owns tab/conn/layer; this param is the panel's.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const current = params.get("table");
    const want = mode === "cards" && view.level === "detail" ? view.tableId : null;
    if (current === want || (!current && !want)) return;
    if (want) params.set("table", want); else params.delete("table");
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, [view, mode]);

  const [tour, setTour] = useState<ConnectionTour | null>(null);
  const [tourError, setTourError] = useState<string | null>(null);
  // Wave P2 — the honesty scorecard (warrant mix + the CONTENT drift axis the staleness
  // chip does not cover). A second call because it costs an in-memory re-projection; the
  // graph renders whether or not it arrives — and a failed read says so rather than vanishing.
  const [audit, setAudit] = useState<GraphAudit | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  // Wave P5 — what the graph knows it cannot vouch for, fetched with the graph so the tab
  // can carry its count without a second click to discover there is nothing to do.
  const [review, setReview] = useState<GraphReview | null>(null);
  // Wave P3 — what standing each node has earned. A read-time sidecar: it annotates the
  // graph on screen and is never written back into the committed artifact.
  const [trust, setTrust] = useState<TrustSidecar | null>(null);
  const [trustError, setTrustError] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  // Identifies the in-flight load, so a response from a superseded one is discarded.
  const loadToken = useRef(0);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    setTour(null);
    setTourError(null);
    setAudit(null);
    setAuditError(null);
    setReview(null);
    setReviewError(null);
    setTrust(null);
    setTrustError(null);
    setChosen([]);
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
      .then((a) => { if (fresh()) setAudit(a); })
      .catch((e) => { if (fresh()) setAuditError(e?.message || "Audit unavailable"); });
    getGraphReview(connectionId, schema)
      .then((r) => { if (fresh()) setReview(r); })
      .catch((e) => { if (fresh()) setReviewError(e?.message || "Review unavailable"); });
    getGraphTrust(connectionId, schema)
      .then((t) => { if (fresh()) setTrust(t); })
      .catch((e) => { if (fresh()) setTrustError(e?.message || "Standing unavailable"); });
  }, [connectionId, schema, initialTableId]);

  const [rebuilding, setRebuilding] = useState(false);
  const [rebuildError, setRebuildError] = useState<string | null>(null);
  const rebuild = useCallback(async () => {
    setRebuilding(true);
    setRebuildError(null);
    try {
      await rebuildContextGraph(connectionId, schema);
      load();
    } catch (e) {
      setRebuildError(e instanceof Error ? e.message : String(e));
    } finally {
      setRebuilding(false);
    }
  }, [connectionId, schema, load]);

  useEffect(() => { load(); }, [load]);

  const fetchTour = useCallback(() => {
    setTourError(null);
    getConnectionTour(connectionId, schema)
      .then(setTour)
      .catch((e) => setTourError(e?.message || "Tour unavailable"));
  }, [connectionId, schema]);

  const openTour = useCallback(() => {
    setMode("tour");
    if (!tour && !tourError) fetchTour();
  }, [tour, tourError, fetchTour]);

  const openTable = useCallback((tableId: string) => {
    setMode("cards");
    setView({ level: "detail", tableId });
  }, []);

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
        const other = node(otherId);
        return { id: e.id, other: other ? nodeName(other) : otherId, warrant: e.warrant };
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

  const builtOn = (id: string): CGNode[] =>
    edgesArr.filter((e) => e.kind === "derived_from" && e.from_id === id)
      .map((e) => node(e.to_id)).filter((n): n is CGNode => !!n);

  const domainJoinsFor = (domainLabel: string) =>
    (graph?.domain_edges || [])
      .filter((d) => d.from === domainLabel || d.to === domainLabel)
      .map((d) => ({ other: d.from === domainLabel ? d.to : d.from, count: d.count }));

  const isTableNode = (id: string) => !!graph?.nodes[id] && graph.nodes[id].kind === "table";
  const driftShown = !!audit?.drift?.drifted;
  const ready = !loading && !error && !!graph;

  // ── render ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-0)" }}>
      <HoldsLine graph={graph} audit={audit} auditError={auditError} review={review} mode={mode}
        onMode={(m) => (m === "tour" ? openTour() : setMode(m))} onRefresh={load}
        onRebuild={rebuild} rebuilding={rebuilding} rebuildError={rebuildError} />

      {loading && <div style={{ padding: "16px 22px" }}><SkeletonRows rows={6} /></div>}
      {error && (
        <div style={{ padding: "16px 22px" }}>
          <ErrorState kind="Graph failed" what={error} doors={[{ label: "Try again", onClick: load, primary: true }]} />
        </div>
      )}

      {ready && mode === "map" && (
        <div style={{ flex: 1, minHeight: 0, display: "flex", padding: "12px 22px 18px" }}>
          <div className="aug-graph-map">
            <div className="aug-graph-canvas">
              <GraphCanvas graph={graph} onOpenTable={openTable} onSelectionChange={setChosen} />
            </div>
            <aside className="aug-graph-rail" aria-label="Beside the map" data-testid="graph-side">
              {chosen.length === 1 && node(chosen[0]) ? (
                <NodeEssentials n={node(chosen[0])!} graph={graph} trust={trust} trustError={trustError}
                  joins={joinsFor(chosen[0])} findings={findingsFor(chosen[0]).length} builtOn={builtOn(chosen[0])}
                  onAsk={onAsk} onOpenTable={openTable} />
              ) : chosen.length > 1 ? (
                <ManyChosen nodes={chosen.map(node).filter((n): n is CGNode => !!n)} onAsk={onAsk} />
              ) : (
                <AtRest graph={graph} review={review} reviewError={reviewError} audit={audit} auditError={auditError}
                  driftShown={driftShown} onRetry={load} onAsk={onAsk} isTableNode={isTableNode}
                  onOpenTable={openTable} onOpenReview={() => setMode("review")} />
              )}
            </aside>
          </div>
        </div>
      )}

      {ready && mode !== "map" && (
        <Page testId={`graph-${mode}`}>
          {mode === "review" && (
            <ReviewList review={review} error={reviewError} graph={graph} onRetry={load} onAsk={onAsk}
              isTableNode={isTableNode} onOpenTable={openTable} />
          )}
          {mode === "tour" && <TourView tour={tour} error={tourError} graph={graph} onRetry={fetchTour} />}
          {mode === "cards" && (
            <>
              {/* Where the reader is, and the way back up. */}
              <div className="aug-fs-sm" style={{ ...ROW, gap: 6, color: "var(--t3)" }}>
                <Button variant="ghost" size="xs" onClick={() => setView({ level: "domains" })}
                  style={{ color: view.level === "domains" ? "var(--t1)" : "var(--t3)" }}>
                  Domains
                </Button>
                {view.level === "tables" && <><span>/</span><span style={{ color: "var(--t1)" }}>{view.domain}</span></>}
                {view.level === "detail" && (
                  <>
                    <span>/</span>
                    <Button variant="ghost" size="xs"
                      onClick={() => setView({ level: "tables", domain: domainOf(node(view.tableId) || ({ data: {} } as CGNode)) })}
                      style={{ color: "var(--t3)" }}>
                      {domainOf(node(view.tableId) || ({ data: {} } as CGNode))}
                    </Button>
                    <span>/</span>
                    <span style={{ color: "var(--t1)" }}>{node(view.tableId) ? nodeName(node(view.tableId)!) : ""}</span>
                  </>
                )}
              </div>

              {view.level === "domains" && (
                <section aria-label="Domains" style={CARD}>
                  <Label right={formatCount(graph.domains.length)}>Domains</Label>
                  {graph.domains.length === 0 ? <Empty>No domains yet.</Empty> : graph.domains.map((d, i) => {
                    const joined = domainJoinsFor(d.label);
                    return (
                      <Button key={d.label} variant="ghost" onClick={() => setView({ level: "tables", domain: d.label })}
                        style={{ ...rowButtonStyle(false, { display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12 }), ...(i === 0 ? { borderTop: 0 } : {}) }}>
                        <span style={{ minWidth: 0 }}>
                          <span className="aug-fs-chrome" style={{ display: "block", color: "var(--t1)", fontWeight: 500 }}>{d.label}</span>
                          {joined.length > 0 && (
                            <span className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE, display: "block" }}
                              title={joined.map((j) => `${countNoun(j.count, "cross-domain join")} to ${j.other}`).join(" · ")}>
                              joins {joined.map((j) => (j.count > 1 ? `${j.other} ×${j.count}` : j.other)).join(", ")}
                            </span>
                          )}
                        </span>
                        <span className="aug-fs-sm" style={{ ...NUM, color: "var(--t2)" }}>{countNoun(d.table_count, "table")}</span>
                      </Button>
                    );
                  })}
                </section>
              )}

              {view.level === "tables" && (
                <section aria-label={view.domain} style={CARD}>
                  <Label right={countNoun(tablesOf(view.domain).length, "table")}>{view.domain}</Label>
                  {tablesOf(view.domain).length === 0 ? <Empty>No tables in this domain.</Empty>
                    : tablesOf(view.domain).map((t, i) => (
                      <Button key={t.id} variant="ghost" onClick={() => setView({ level: "detail", tableId: t.id })}
                        style={{ ...rowButtonStyle(false, { display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12 }), ...(i === 0 ? { borderTop: 0 } : {}) }}>
                        <span style={{ minWidth: 0 }}>
                          <span className="aug-fs-chrome" style={{ display: "block", color: "var(--t1)", fontWeight: 500 }}>{nodeName(t)}</span>
                          {t.summary && <span className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE, display: "block" }} title={t.summary}>{t.summary}</span>}
                        </span>
                        <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>
                          {[countNoun(columnsFor(t.id).length, "column"),
                            joinsFor(t.id).length ? countNoun(joinsFor(t.id).length, "join") : "",
                            findingsFor(t.id).length ? countNoun(findingsFor(t.id).length, "finding") : ""]
                            .filter(Boolean).join(" · ")}
                        </span>
                      </Button>
                    ))}
                </section>
              )}

              {view.level === "detail" && (() => {
                const t = node(view.tableId);
                if (!t) return <Empty>Table not found.</Empty>;
                return (
                  <TablePage t={t} trust={trust} trustError={trustError} joins={joinsFor(t.id)} findings={findingsFor(t.id)}
                    terms={termsFor(t.id)} cols={columnsFor(t.id)} tags={tagsForEntity((t.data.source_tables as string[]) || [])}
                    domain={domainOf(t)} onAsk={onAsk}
                    dependents={<DependentsFold connectionId={connectionId} schema={schema} nodeId={t.id} />} />
                );
              })()}
            </>
          )}
        </Page>
      )}
    </div>
  );
}

/**
 * The one line above the picture: what the graph holds, how well its joins are known, whether a rebuild is owed —
 * then the view and Refresh at its right end. It replaces a strip that named the tab again and a card of the warrant
 * mix the side panel now carries.
 */
function HoldsLine({ graph, audit, auditError, review, mode, onMode, onRefresh, onRebuild, rebuilding, rebuildError }: {
  graph: ConnectionGraph | null; audit: GraphAudit | null; auditError: string | null; review: GraphReview | null;
  mode: Mode; onMode: (m: Mode) => void; onRefresh: () => void;
  /** "Rebuild owed" said a rebuild was owed with nothing that could do it; this is the doing. */
  onRebuild: () => void; rebuilding: boolean; rebuildError: string | null;
}) {
  const holds = graph ? (() => {
    const { joins, measured } = joinsMeasured(graph);
    const c = graph.counts || {};
    return { joins, measured, facts: [
      [c.table || 0, "table"], [joins, "join"], [c.metric || 0, "metric"], [c.finding || 0, "finding"],
      [c.glossary_term || 0, "term"],
    ] as [number, string][] };
  })() : null;
  // P2: a Fresh badge is about the SCHEMA only. When the content axis says the graph is missing what the platform has
  // since learned, the badge must not stand alone saying "Fresh" — that reading is the exact blindness `content_drift`
  // was written to prevent. Unread, it says it could not check rather than nothing.
  const staleness = graph ? STALE[graph.staleness] ?? STALE.unknown : null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 22px", borderBottom: "1px solid var(--b0)",
      flexWrap: "wrap", minHeight: 44 }}>
      {holds && (
        <span className="aug-fs-sm" data-testid="graph-holds" style={{ display: "inline-flex", gap: 14, flexWrap: "wrap",
          color: "var(--t2)" }}>
          {holds.facts.map(([n, noun]) => (
            <span key={noun}>
              <b style={{ color: "var(--t1)", fontWeight: 600, ...NUM }}>{formatCount(n)}</b> {n === 1 ? noun : `${noun}s`}
            </span>
          ))}
        </span>
      )}
      {holds && holds.joins > 0 && (
        holds.measured === holds.joins
          ? <Chip tone="up" title="Each join's key overlap was read off your data.">every join measured</Chip>
          : <Chip title={`${countNoun(holds.joins - holds.measured, "join")} declared by the schema or matched by name — nothing has measured their key overlap.`}>
              {formatCount(holds.measured)} of {formatCount(holds.joins)} measured
            </Chip>
      )}
      {graph && staleness && (audit?.drift?.drifted ? (
        <>
          <Chip tone="amber" testId="graph-freshness"
            title={`Schema freshness: ${staleness.word.toLowerCase()}. ${audit.drift.reason}`}>Rebuild owed</Chip>
          <Button variant="secondary" size="xs" onClick={onRebuild} disabled={rebuilding} data-testid="graph-rebuild"
            title="Rebuild the graph from the ontology, the Record, the glossary and the Briefings — no model call, no warehouse query">
            {rebuilding ? "Rebuilding…" : "Rebuild"}
          </Button>
          {rebuildError && <span role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>Not rebuilt — {rebuildError}</span>}
        </>
      ) : (
        <Chip tone={auditError ? "plain" : staleness.tone} testId="graph-freshness"
          title={auditError ? `Schema freshness only — whether a rebuild is owed could not be read (${auditError}).`
            : `Graph freshness: ${graph.staleness}`}>
          {staleness.word}
        </Chip>
      ))}
      <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 8 }}>
        <Segmented label="Graph view" value={mode}
          // "Tour" is a thing to start, not a view to be in: the view stays what it was.
          onChange={onMode}
          options={([["map", "Map"], ["cards", "Explore"], ["tour", "Tour"], ["review", "Review"]] as const).map(([m, label]) => ({
            value: m, label: `${label}${m === "review" && review && review.total > 0 ? ` ${review.total}` : ""}` }))} />
        <Button variant="ghost" size="xs" onClick={onRefresh}>Refresh</Button>
      </span>
    </div>
  );
}

// Wave P5 — the review queue: what the graph knows it cannot vouch for, before anyone
// asks a question. Every item names what is in doubt, why it matters in consequences
// rather than mechanism, and the one check that would settle it.
const CHECK_LABEL: Record<GraphReviewItem["check"], string> = {
  probe_join: "Measure this join",
  ask: "Ask about it",
  review_finding: "Settle this",
  define: "Define it",
  rebuild: "Rebuild the graph",
};

/** A kind's colour in the queue: amber where a person must decide or check, red where a claim stands on nothing. */
const KIND_TONE: Record<GraphReviewItem["type"], string> = {
  graph_behind: "var(--amb4)",
  unprobed_join: "var(--amb4)",
  contested_finding: "var(--amb4)",
  ungrounded_finding: "var(--red4)",
  undocumented_hub: "var(--t3)",
  isolated_table: "var(--t3)",
};

/** The one check that settles an item, as buttons on its row. Every check routes to something that already exists —
 *  the Ask surface for the ones a question settles, the table's page for the ones a person reads. An item whose check
 *  has no home (settling a contested finding, a rebuild) carries no button rather than a dead one. */
function ItemDoors({ it, onAsk, isTableNode, onOpenTable, name, max = 2 }: {
  it: GraphReviewItem; onAsk?: (q: string) => void; isTableNode: (id: string) => boolean;
  onOpenTable?: (id: string) => void; name: string; max?: number;
}) {
  const doors: ReactNode[] = [];
  if (onAsk && (it.check === "ask" || it.check === "probe_join" || it.check === "define")) {
    doors.push(
      <Button key="ask" variant="outline" size="xs" title={it.question} onClick={() => onAsk(it.question)}>
        {CHECK_LABEL[it.check] || "Check this"}
      </Button>,
    );
  }
  // An unprobed_join's subject_id is an EDGE id ("table:orders--joins_on-->table:customers"), which ALSO starts with
  // "table:" — the prefix test sent the queue's top-ranked item to a "Table not found." page. Test for the node itself.
  if (onOpenTable && isTableNode(it.subject_id)) {
    doors.push(
      <Button key="open" variant="ghost" size="xs" title={`Open ${name}`} onClick={() => onOpenTable(it.subject_id)}>Open</Button>,
    );
  }
  if (!doors.length) return null;
  return <span style={{ ...ROW, flexWrap: "nowrap", gap: 4, flex: "none" }}>{doors.slice(0, max)}</span>;
}

const dependsWords = (n: number) => (n > 0 ? `${formatCount(n)} ${n === 1 ? "thing depends" : "things depend"} on it` : "");

/** The side panel when nothing is chosen: what waits on a person, then how every link is known. */
function AtRest({ graph, review, reviewError, audit, auditError, driftShown, onRetry, onAsk, isTableNode, onOpenTable, onOpenReview }: {
  graph: ConnectionGraph; review: GraphReview | null; reviewError: string | null;
  audit: GraphAudit | null; auditError: string | null; driftShown: boolean; onRetry: () => void;
  onAsk?: (q: string) => void; isTableNode: (id: string) => boolean; onOpenTable: (id: string) => void;
  onOpenReview: () => void;
}) {
  const items = review ? waitingItems(review.items, driftShown) : [];
  const groups = groupReview(items);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, padding: "12px 14px 14px" }}>
      <section aria-label="Needs you" data-testid="graph-needs" data-waiting={items.length > 0 ? "true" : "false"}>
        <Label tone={items.length ? "amber" : undefined}
          right={review && items.length > 0 ? (review.truncated ? `${formatCount(items.length)} of ${formatCount(review.total_found)}` : formatCount(items.length)) : null}>
          Needs you
        </Label>
        {reviewError ? <ReadFailed what="what needs checking" error={reviewError} onRetry={onRetry} />
          : !review ? <SkeletonRows rows={3} />
          : items.length === 0 ? <Empty>Nothing to check — joins measured, tables connected and defined, no finding contested.</Empty>
          : groups.map((g, i) => {
            const first = g.items[0];
            if (g.items.length === 1) {
              const name = subjectName(first, graph);
              return (
                <div key={g.items[0].id} style={{ ...ROW, flexWrap: "nowrap", alignItems: "flex-start", padding: "7px 0", ...(i ? RULE : {}) }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="aug-fs-chrome" title={first.question} style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }}>{name}</div>
                    <div className="aug-fs-xs" title={first.why} style={{ ...ONE_LINE, color: "var(--t3)" }}>
                      <span style={{ color: KIND_TONE[first.type] ?? "var(--t3)" }}>{reviewWord(first.type)}</span>
                      {first.depends > 0 && ` · ${dependsWords(first.depends)}`}
                    </div>
                  </div>
                  <ItemDoors it={first} onAsk={onAsk} isTableNode={isTableNode} onOpenTable={onOpenTable} name={name} max={1} />
                </div>
              );
            }
            const names = g.items.slice(0, 2).map((it) => subjectName(it, graph));
            return (
              <div key={g.items[0].id} style={{ ...ROW, flexWrap: "nowrap", alignItems: "flex-start", padding: "7px 0", ...(i ? RULE : {}) }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="aug-fs-chrome" style={{ color: KIND_TONE[first.type] ?? "var(--t1)", fontWeight: 500 }}>
                    <span style={NUM}>{formatCount(g.items.length)}</span> {reviewWord(g.type, g.items.length).toLowerCase()}
                  </div>
                  <div className="aug-fs-xs" title={g.why ?? first.why} style={{ ...ONE_LINE, color: "var(--t3)" }}>
                    {names.join(", ")}{g.items.length > names.length ? ` +${formatCount(g.items.length - names.length)}` : ""}
                  </div>
                </div>
                <Button variant="ghost" size="xs" onClick={onOpenReview}>Review</Button>
              </div>
            );
          })}
      </section>

      <section aria-label="How it is known">
        <Label right={audit ? countNoun(audit.totals.edges, "link") : null}>How it is known</Label>
        {auditError ? <Empty>Could not read how this graph is known — {auditError}.</Empty>
          : !audit ? <SkeletonRows rows={2} />
          : audit.totals.edges === 0 ? <Empty>No links yet.</Empty>
          : <WarrantMix audit={audit} />}
      </section>

      <div className="aug-fs-xs" style={MUTED}>Click a node to read it · shift-click to choose several · drag to pin.</div>
    </div>
  );
}

const ASK_WORD: Record<string, string> = {
  table: "Ask about this table", finding: "Re-examine this finding", metric: "Ask about this metric",
  glossary_term: "Ask about this term", domain: "Ask about this domain",
};

/** The side panel with one node chosen: its name and how it is known first, one line of what it is, its question to
 *  ask; then, for a table, its joins — the rest is on its page (Open). */
function NodeEssentials({ n, graph, trust, trustError, joins, findings, builtOn, onAsk, onOpenTable }: {
  n: CGNode; graph: ConnectionGraph; trust: TrustSidecar | null; trustError: string | null;
  joins: { id: string; other: string; warrant?: CGNode["warrant"] }[]; findings: number; builtOn: CGNode[];
  onAsk?: (q: string) => void; onOpenTable: (id: string) => void;
}) {
  const d = n.data || {};
  const source = n.provenance ? `From ${n.provenance.source}${n.provenance.note ? ` — ${n.provenance.note}` : ""}` : undefined;
  let meta: ReactNode = null;
  let body: ReactNode = null;
  if (n.kind === "table") {
    meta = [((d.source_tables as string[]) || []).join(", "), countNoun(((d.columns as string[]) || []).length, "column"),
      findings ? countNoun(findings, "finding") : ""].filter(Boolean).join(" · ");
  } else if (n.kind === "metric") {
    meta = builtOn.length ? `on ${builtOn.map(nodeName).join(", ")}` : "";
  } else if (n.kind === "finding") {
    body = n.summary || n.label;
    meta = [d.generated_at ? fmtDate(String(d.generated_at), "day") : "", d.contested ? "contested" : "",
      d.superseded ? "superseded" : ""].filter(Boolean).join(" · ");
  } else if (n.kind === "glossary_term") {
    body = n.summary;
    meta = d.table ? `on ${String(d.table)}` : "";
  } else if (n.kind === "domain") {
    const members = ((d.members as string[]) || []).map((id) => graph.nodes[id]).filter((m): m is CGNode => !!m);
    meta = members.length ? `${countNoun(members.length, "table")}: ${members.map(nodeName).join(", ")}` : "";
  } else {
    body = n.summary;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "12px 14px 14px" }} data-testid="graph-chosen">
      <section aria-label={nodeName(n)}>
        <Label right={n.kind === "table" ? String(d.domain || "") : null}>
          <Dot color={KIND_HUE[n.kind] ?? KIND_HUE.domain} />{KIND_WORD[n.kind] ?? n.kind}
        </Label>
        <div className="aug-fs-h2" style={{ color: "var(--t1)", fontWeight: 600, overflowWrap: "anywhere" }}>{nodeName(n)}</div>
        {/* P3 standing sits beside P2's warrant deliberately: a table can be measured (how we know it) and still
            unchecked (nobody confirmed the answers built on it). One score would hide that gap. */}
        <div style={{ ...ROW, gap: 6, marginTop: 6 }}>
          <WarrantChip warrant={n.warrant} showDetail />
          <StandingChip trust={trust?.nodes?.[n.id]} />
          {trustError && n.kind === "table" && <Chip title={trustError}>standing not read</Chip>}
        </div>
        {body && <div className="aug-fs-sm" style={{ color: "var(--t2)", marginTop: 8, lineHeight: 1.55 }}>{body}</div>}
        {meta && <div className="aug-fs-xs" title={source} style={{ ...MUTED, marginTop: 6 }}>{meta}</div>}
        <div style={{ ...ROW, marginTop: 12 }}>
          {onAsk && <Button size="xs" onClick={() => onAsk(questionFor([n]))}>{ASK_WORD[n.kind] ?? "Ask about it"}</Button>}
          {n.kind === "table" && <Button size="xs" variant="outline" onClick={() => onOpenTable(n.id)}>Open</Button>}
        </div>
      </section>
      {n.kind === "table" && (
        <section aria-label="Joins">
          <Label right={formatCount(joins.length)}>Joins</Label>
          {joins.length === 0 ? <Empty>No joins.</Empty> : joins.map((j, i) => (
            <div key={j.id} style={{ ...ROW, padding: "5px 0", ...(i ? RULE : {}) }}>
              <span className="aug-fs-sm" style={{ color: "var(--t1)" }}>→ {j.other}</span>
              <WarrantChip warrant={j.warrant} showDetail />
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

/** The side panel with several nodes chosen: which, and the one question that spans them. */
function ManyChosen({ nodes, onAsk }: { nodes: CGNode[]; onAsk?: (q: string) => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "12px 14px 14px" }} data-testid="graph-chosen">
      <Label right={formatCount(nodes.length)}>Chosen</Label>
      {nodes.map((n) => (
        <div key={n.id} className="aug-fs-sm" style={{ ...ROW, flexWrap: "nowrap", color: "var(--t1)" }}>
          <Dot color={KIND_HUE[n.kind] ?? KIND_HUE.domain} title={KIND_WORD[n.kind] ?? n.kind} />
          <span style={ONE_LINE} title={n.label}>{nodeName(n)}</span>
        </div>
      ))}
      {onAsk && <span><Button size="xs" onClick={() => onAsk(questionFor(nodes))}>Ask about these together</Button></span>}
    </div>
  );
}

const SECTION: CSSProperties = { marginTop: 18 };

/**
 * One table's page — the entity page the `?table=` deep link opens. It reads as a page: the name and its standing, one
 * line of what it is, then its joins, the findings that rest on it, its columns each with its glossary definition, and
 * what depends on it behind a fold. A section with nothing in it is not drawn; what is absent is said once, together.
 */
function TablePage({ t, trust, trustError, joins, findings, terms, cols, tags, domain, onAsk, dependents }: {
  t: CGNode; trust: TrustSidecar | null; trustError: string | null;
  joins: { id: string; other: string; warrant?: CGNode["warrant"] }[]; findings: CGNode[]; terms: CGNode[];
  cols: string[]; tags: GovernedTag[]; domain: string; onAsk?: (q: string) => void; dependents: ReactNode;
}) {
  const [allFindings, setAllFindings] = useState(false);
  const [allColumns, setAllColumns] = useState(false);
  const standing = trust?.nodes?.[t.id];
  // One warrant for every finding (on theLook, all eleven are "derived") is said once, in the label.
  const findingWarrants = new Set(findings.map((f) => f.warrant?.warrant ?? ""));
  const oneFindingWarrant = findings.length > 1 && findingWarrants.size === 1 ? findings[0].warrant : undefined;
  // A column and its glossary term are one line: the term's name IS the column's.
  const termOf = new Map(terms.map((tm) => [String(tm.data.column || tm.label).toLowerCase(), tm]));
  const colSet = new Set(cols.map((c) => c.toLowerCase()));
  const strayTerms = terms.filter((tm) => !colSet.has(String(tm.data.column || tm.label).toLowerCase()));
  const lines = [
    ...cols.map((c) => ({ key: `c:${c}`, name: c, term: termOf.get(c.toLowerCase()) })),
    ...strayTerms.map((tm) => ({ key: tm.id, name: tm.label, term: tm as CGNode | undefined })),
  ];
  const defined = lines.filter((l) => l.term).length;
  const termWarrants = new Set(terms.map((tm) => tm.warrant?.label ?? ""));
  const absent = [!joins.length && "no joins", !findings.length && "no findings", !lines.length && "no columns"]
    .filter(Boolean) as string[];
  const shownFindings = allFindings ? findings : findings.slice(0, 4);
  const shownLines = allColumns ? lines : lines.slice(0, 10);
  return (
    <section aria-label={nodeName(t)} style={CARD} data-testid="graph-table-page">
      <div style={{ ...ROW, gap: 8 }}>
        <span className="aug-fs-h1" style={{ color: "var(--t1)", fontWeight: 600 }}>{nodeName(t)}</span>
        {/* P3 standing sits beside P2's warrant deliberately: a table can be measured (how we know it) and still
            unchecked (nobody confirmed the answers built on it). One score would hide that gap. */}
        <StandingChip trust={standing} />
        {trustError && <Chip title={trustError}>standing not read</Chip>}
        {onAsk && (
          <span style={{ marginLeft: "auto" }}>
            <Button size="xs" onClick={() => onAsk(questionFor([t]))}>Ask about this table</Button>
          </span>
        )}
      </div>
      <div className="aug-fs-sm" style={{ ...MUTED, marginTop: 2 }}>
        {[((t.data.source_tables as string[]) || []).join(", "), countNoun(cols.length, "column"), domain].filter(Boolean).join(" · ")}
      </div>
      {standing && <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 2 }}>{standing.detail}</div>}
      {tags.length > 0 && (
        <div style={{ ...ROW, gap: 4, marginTop: 6 }}>
          {tags.map((tag) => (
            <Chip key={`${tag.securable}:${tag.key}`} title={`${tag.securable} — set by ${tag.set_by || tag.source}`}>
              {tag.key}: {tag.value}
            </Chip>
          ))}
        </div>
      )}

      {/* P2: every join states its warrant. A measured overlap and a bare name match used to look the same here. */}
      {joins.length > 0 && (
        <div style={SECTION}>
          <Label right={formatCount(joins.length)}>Joins</Label>
          {joins.map((j, i) => (
            <div key={j.id} style={{ ...ROW, padding: "5px 0", ...(i ? RULE : {}) }}>
              <span className="aug-fs-sm" style={{ color: "var(--t1)" }}>→ {j.other}</span>
              <WarrantChip warrant={j.warrant} showDetail />
            </div>
          ))}
        </div>
      )}

      {findings.length > 0 && (
        <div style={SECTION}>
          <Label right={<>{formatCount(findings.length)}{oneFindingWarrant && <> · all <WarrantChip warrant={oneFindingWarrant} /></>}</>}>
            Findings on this table
          </Label>
          {shownFindings.map((f, i) => (
            <div key={f.id} className="aug-fs-sm" style={{ ...ROW, flexWrap: "nowrap", alignItems: "flex-start", padding: "5px 0", ...(i ? RULE : {}) }}>
              {!oneFindingWarrant && <WarrantChip warrant={f.warrant} />}
              <span style={{ color: "var(--t2)", lineHeight: 1.55 }}>{f.summary || f.label}</span>
            </div>
          ))}
          {findings.length > 4 && (
            <FoldLine open={allFindings} onToggle={() => setAllFindings((v) => !v)}>
              {allFindings ? "Fewer" : `${formatCount(findings.length - 4)} more`}
            </FoldLine>
          )}
        </div>
      )}

      {lines.length > 0 && (
        <div style={SECTION}>
          <Label right={defined ? `${formatCount(defined)} defined${termWarrants.size === 1 && terms[0]?.warrant ? ` · ${terms[0].warrant.label.toLowerCase()}` : ""}` : formatCount(lines.length)}>
            Columns
          </Label>
          <div className="aug-fs-sm" style={{ display: "grid", gridTemplateColumns: "minmax(120px, max-content) minmax(0, 1fr)", gap: "4px 16px" }}>
            {shownLines.map((l) => (
              <React.Fragment key={l.key}>
                <code className="aug-fs-xs" style={{ color: "var(--t1)", fontFamily: "var(--font-mono)" }}>{l.name}</code>
                <span style={{ color: "var(--t3)", minWidth: 0 }} title={l.term?.warrant ? `${l.term.warrant.label}: ${l.term.summary}` : undefined}>
                  {l.term?.summary || ""}
                </span>
              </React.Fragment>
            ))}
          </div>
          {lines.length > 10 && (
            <FoldLine open={allColumns} onToggle={() => setAllColumns((v) => !v)}>
              {allColumns ? "Fewer" : `${formatCount(lines.length - 10)} more`}
            </FoldLine>
          )}
        </div>
      )}

      {absent.length > 0 && <div style={SECTION}><Empty>{absent.join(" · ").replace(/^n/, "N")}.</Empty></div>}

      {/* P4: what breaks if this table changes — reported, never deleted. */}
      {dependents}
    </section>
  );
}

/**
 * Wave P4 — what depends on this node, each dependent showing the expression that would break rather than only its
 * name: counted on one line, the rows behind it.
 *
 * Loaded when the entity page opens (it walks the graph), and silent when nothing depends on the table: an empty
 * "Dependents: none" section on every leaf table is noise, while the line appearing at all is itself the signal that
 * something downstream exists. A read that FAILED is said — silence would read as "nothing depends on this".
 */
function DependentsFold({ connectionId, schema, nodeId }: {
  connectionId: string; schema?: string; nodeId: string;
}) {
  const [lineage, setLineage] = useState<GraphLineage | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let alive = true;
    setLineage(null);
    setFailed(null);
    getGraphLineage(connectionId, { nodeId, schemaName: schema })
      .then((l) => { if (alive) setLineage(l); })
      .catch((e) => { if (alive) setFailed(e?.message || "Lineage unavailable"); });
    return () => { alive = false; };
  }, [connectionId, schema, nodeId]);

  if (failed) return <div style={SECTION}><Empty>Could not read what depends on this table — {failed}.</Empty></div>;
  if (!lineage || lineage.dependents.length === 0) return null;
  const counts = Object.entries(lineage.counts_by_kind || {}).filter(([, n]) => n > 0)
    .map(([kind, n]) => countNoun(n, (KIND_WORD[kind] ?? kind).toLowerCase()));
  return (
    <div style={SECTION} data-testid="graph-dependents">
      <span title={lineage.summary}>
        <FoldLine open={open} onToggle={() => setOpen((v) => !v)}>
          What depends on this · {counts.join(" · ") || countNoun(lineage.dependents.length, "thing")}
          {lineage.truncated ? " · first shown" : ""}
        </FoldLine>
      </span>
      {open && lineage.dependents.map((d, i) => (
        <div key={d.node_id} style={{ ...ROW, flexWrap: "nowrap", padding: "5px 0", ...(i ? RULE : {}) }}>
          <Dot color={KIND_HUE[d.kind] ?? KIND_HUE.domain} title={KIND_WORD[d.kind] ?? d.kind} />
          <span className="aug-fs-sm" style={{ ...ONE_LINE, color: "var(--t1)", maxWidth: 340, flexShrink: 0 }} title={d.label}>{d.label}</span>
          {d.site && (
            // One line, ellipsised, full text on hover. Sites run to 200 characters of SQL; rendered in full they
            // wrapped to their own row and the list stopped being scannable — which defeats the point, since this
            // exists to be skimmed for the one artifact worth opening.
            <code className="aug-fs-xs" title={`${d.site_line > 0 ? `line ${d.site_line}: ` : ""}${d.site}`}
              style={{ ...ONE_LINE, color: "var(--t3)", background: "var(--bg-3)", borderRadius: "var(--r1)", padding: "1px 6px",
                maxWidth: 420, flexShrink: 1, fontFamily: "var(--font-mono)" }}>
              {d.site_line > 0 ? `line ${d.site_line}: ` : ""}{d.site}
            </code>
          )}
        </div>
      ))}
    </div>
  );
}

/** The whole review queue, folded by kind, most consequential first: a reason every item of a kind shares is said once
 *  above its rows; each row is what is in doubt, what depends on it, and its check. */
function ReviewList({ review, error, graph, onRetry, onAsk, isTableNode, onOpenTable }: {
  review: GraphReview | null; error: string | null; graph: ConnectionGraph; onRetry: () => void;
  onAsk?: (q: string) => void; isTableNode: (id: string) => boolean; onOpenTable?: (tableId: string) => void;
}) {
  const groups = useMemo(() => groupReview(review?.items ?? []), [review]);
  // A failed fetch used to render as "Checking the graph…" forever — the same indistinguishable-states bug the Fresh
  // badge had.
  const waiting = !!review && review.total > 0;
  return (
    <section aria-label="Needs you" style={CARD} data-testid="graph-review" data-waiting={waiting ? "true" : "false"}>
      <Label tone={waiting ? "amber" : undefined}
        right={review && review.total > 0 ? (
          <span title="Ranked by how much depends on each, never by a guessed severity.">
            {review.truncated ? `${formatCount(review.total)} of ${formatCount(review.total_found)}` : formatCount(review.total)}
            {" · most consequential first"}
          </span>
        ) : null}>
        Needs you
      </Label>
      {error ? <ReadFailed what="what this graph cannot vouch for" error={error} onRetry={onRetry} />
        : !review ? <SkeletonRows rows={4} />
        : review.total === 0 ? <Empty>Nothing to review — every join measured, every table connected and defined, no finding contested.</Empty>
        : groups.map((g, gi) => (
          <div key={g.items[0].id}>
            <GroupHead name={reviewWord(g.type, g.items.length)} count={g.items.length} first={gi === 0} />
            {g.why && <div className="aug-fs-sm" style={{ ...MUTED, marginBottom: 4 }}>{g.why}</div>}
            {g.items.map((it, i) => {
              const name = subjectName(it, graph);
              return (
                <div key={it.id} style={{ ...ROW, flexWrap: "nowrap", alignItems: "flex-start", padding: "7px 0", ...(i ? RULE : {}) }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="aug-fs-chrome" title={it.question} style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }}>{name}</div>
                    {(!g.why || it.depends > 0) && (
                      <div className="aug-fs-xs" title={it.why} style={{ ...ONE_LINE, color: "var(--t3)" }}>
                        {[g.why ? "" : it.why, dependsWords(it.depends)].filter(Boolean).join(" · ")}
                      </div>
                    )}
                  </div>
                  <ItemDoors it={it} onAsk={onAsk} isTableNode={isTableNode} onOpenTable={onOpenTable} name={name} />
                </div>
              );
            })}
          </div>
        ))}
    </section>
  );
}

// Wave C5 — the topology-ordered tour: a numbered curriculum where every step names the prior step it builds on, with
// the deterministic significance on hover and the narration when there is one.
function TourView({ tour, error, graph, onRetry }: {
  tour: ConnectionTour | null; error: string | null; graph: ConnectionGraph; onRetry: () => void;
}) {
  return (
    <section aria-label="Reading order" style={CARD} data-testid="graph-tour">
      <Label right={tour ? (
        <span title="Computed from the graph: the hub first, then a breadth-first walk outward, then the metrics as the capstone. Each step builds on the one before it.">
          {countNoun(tour.steps.length, "step")}
        </span>
      ) : null}>
        Reading order
      </Label>
      {error ? <ReadFailed what="the reading order" error={error} onRetry={onRetry} />
        : !tour ? <SkeletonRows rows={5} />
        : tour.steps.length === 0 ? <Empty>No reading order — the graph has no tables or metrics to walk.</Empty>
        : tour.steps.map((s, i) => {
          const n = graph.nodes[s.node_id];
          const name = n ? nodeName(n) : s.label;
          return (
            <div key={s.node_id} title={s.why}
              style={{ display: "grid", gridTemplateColumns: "28px minmax(0, 1fr)", gap: 8, padding: "7px 0", ...(i ? RULE : {}) }}>
              <span className="aug-fs-sm" style={{ ...MUTED, ...NUM }}>{s.order + 1}</span>
              <div style={{ minWidth: 0 }}>
                <div className="aug-fs-chrome" style={{ ...ROW, gap: 6 }}>
                  <Dot color={KIND_HUE[s.kind] ?? KIND_HUE.domain} title={KIND_WORD[s.kind] ?? s.kind} />
                  <span style={{ color: "var(--t1)", fontWeight: 500 }}>{name}</span>
                  {(s.connection || s.connects_to_label) && (
                    <span className="aug-fs-xs" style={MUTED}>{s.connection || `builds on ${s.connects_to_label}`}</span>
                  )}
                </div>
                {s.narration && <div className="aug-fs-sm" style={{ color: "var(--t2)", marginTop: 2 }}>{s.narration}</div>}
              </div>
            </div>
          );
        })}
    </section>
  );
}
