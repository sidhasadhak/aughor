"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  deleteDashboardCard, listDashboardCards, runDashboardCard, runDirectQuery,
  type DashboardCard, type DashboardCardRefresh, type ExplorationInsight,
} from "@/lib/api";
import { PinnedCardsCanvas, type CardState } from "@/components/brief/PinnedCardsCanvas";
import { toast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { useRegisterCommands, type Command } from "@/lib/commandRegistry";

/** A brief finding, rendered as a (virtual) chart/table card beside the user's pins. */
export interface DashboardFinding { insight: ExplorationInsight; domain: string; }

const REFRESH_STUB: DashboardCardRefresh = { cadence: "brief_cycle", last_run: "", last_value: null, prev_value: null, history: [] };

/** Synthesize a card-shaped object for a finding so the canvas can render it like any card. */
function findingToCard(f: DashboardFinding, connectionId: string): DashboardCard {
  return {
    id: `finding:${f.insight.id}`, connection_id: connectionId, scope: "connection", scope_ref: connectionId,
    source: "insight", kind: "chart", title: f.insight.finding, sql: f.insight.sql, query_ref: null,
    render: {}, refresh: REFRESH_STUB, thresholds: {},
    provenance: { insight_id: f.insight.id, origin_finding_id: f.insight.id, receipt_ref: "" },
    links: [], body: "", author: "", created_at: "", updated_at: "",
  };
}

/** The standing cockpit layer: the brief's own findings rendered as chart/table cards (virtual,
 *  from the brief each cycle) beside the user's OWN persistent pinned cards, all on one canvas the
 *  reader arranges. Each card's number is re-run through the guard battery (pins) or straight from
 *  the finding's grounded SQL (findings). Renders nothing until at least one card exists. */
export function PinnedCards({ connectionId, refreshKey, findings, onOpenSource, onEvidence }: {
  connectionId: string;
  refreshKey?: number;
  findings?: DashboardFinding[];
  onOpenSource?: (insightId: string) => void;
  onEvidence?: (insightId: string) => void;
}) {
  const [cards, setCards] = useState<CardState[]>([]);            // the user's persistent pins
  const [findingCards, setFindingCards] = useState<CardState[]>([]); // the brief's findings (virtual)
  const [ready, setReady] = useState(false);
  const [findingsReady, setFindingsReady] = useState(false);

  // User pins — fetched from the store, each re-run through the guard battery.
  useEffect(() => {
    if (!connectionId) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await listDashboardCards({ scope: "connection", scopeRef: connectionId });
        const withRuns = await Promise.all(
          list.map(async (card): Promise<CardState> => {
            try { return { card, run: await runDashboardCard(card.id) }; }
            catch { return { card, failed: true }; }
          }),
        );
        if (!cancelled) setCards(withRuns);
      } catch {
        if (!cancelled) setCards([]);
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => { cancelled = true; };
  }, [connectionId, refreshKey]);

  // Brief findings → virtual cards: run each finding's own grounded SQL for a chart/table.
  useEffect(() => {
    const seen = new Set<string>();
    const list = (findings || []).filter(f =>
      f.insight?.id && (f.insight.sql || "").trim() && !seen.has(f.insight.id) && seen.add(f.insight.id));
    if (!connectionId || !list.length) { setFindingCards([]); setFindingsReady(true); return; }
    let cancelled = false;
    setFindingsReady(false);
    Promise.all(list.map(async (f): Promise<CardState> => {
      const card = findingToCard(f, connectionId);
      try {
        const r = await runDirectQuery(connectionId, f.insight.sql, 200, { useCache: true });
        return { card, isFinding: true, failed: !!r.error, run: { columns: r.columns, rows: r.rows, row_count: r.rows.length, caveats: [], error: r.error ?? null, refresh: REFRESH_STUB } };
      } catch {
        return { card, isFinding: true, failed: true };
      }
    })).then(cs => { if (!cancelled) { setFindingCards(cs); setFindingsReady(true); } });
    return () => { cancelled = true; };
  }, [findings, connectionId, refreshKey]);

  const remove = useCallback(async (id: string) => {
    try {
      await deleteDashboardCard(id);
      setCards(cs => cs.filter(c => c.card.id !== id));
      toast.success("Card removed from your cockpit");
    } catch {
      toast.error("Couldn't remove card", { description: "The card store didn't accept the delete — try again." });
    }
  }, []);

  // The canvas owns the RF node state, so it hands its "re-pack everything" action up here via a
  // stable registrar; the header button below invokes it.
  const tidyRef = useRef<(() => void) | null>(null);
  const registerTidy = useCallback((fn: (() => void) | null) => { tidyRef.current = fn; }, []);

  const refreshOne = useCallback(async (id: string) => {
    try {
      const run = await runDashboardCard(id);
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, run, failed: false } : c)));
      toast.success("Card refreshed");
    } catch {
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, failed: true } : c)));
      toast.error("Couldn't refresh card", { description: "The query failed the trust guards or the source is unavailable." });
    }
  }, []);

  // The brief's findings first (the fresh signals), then the user's standing pins.
  const all = useMemo(() => [...findingCards, ...cards], [findingCards, cards]);

  // ── ⌘K "Tidy cockpit" command — offered only while the cockpit has cards ──
  const tidyCommands = useMemo<Command[]>(() =>
    all.length > 0
      ? [{ id: "cockpit-tidy", label: "Tidy cockpit", sublabel: "Re-pack the cockpit into a clean, gap-free grid", icon: "canvas", accent: "var(--grn3)", keywords: "tidy cockpit arrange pack grid layout reset", run: () => tidyRef.current?.() }]
      : [],
  [all.length]);
  useRegisterCommands("cockpit", tidyCommands);

  // Wait for BOTH pins and findings before first paint, so findings pack at the top (not below the
  // pins that happened to load first).
  if (!ready || !findingsReady || all.length === 0) return null;

  return (
    <div style={{ marginBottom: 20 }}>
      <div className="aug-label" style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        Your cockpit
        <span className="aug-tag aug-tag-green">Guarded</span>
        <span className="aug-fs-xs" style={{ fontWeight: 400, color: "var(--t4)", textTransform: "none" as const, letterSpacing: 0 }}>findings + your pinned cards · drag the title to arrange · select to resize · snaps to grid, never overlaps</span>
        <Button
          variant="ghost" size="xs"
          onClick={() => tidyRef.current?.()}
          title="Re-arrange every card into a clean, gap-free grid"
          style={{ marginLeft: "auto", fontSize: 11, color: "var(--t3)", padding: "2px 8px", textTransform: "none" as const, letterSpacing: 0 }}
        >▦ Tidy up</Button>
      </div>
      <PinnedCardsCanvas
        connectionId={connectionId}
        cards={all}
        onRemove={remove}
        onRefresh={refreshOne}
        onOpenSource={onOpenSource}
        onEvidence={onEvidence}
        registerTidy={registerTidy}
      />
    </div>
  );
}
