"use client";

import { useCallback, useEffect, useState } from "react";

import {
  deleteDashboardCard,
  listDashboardCards,
  runDashboardCard,
} from "@/lib/api";
import { PinnedCardsCanvas, type CardState } from "@/components/brief/PinnedCardsCanvas";

/** The standing "cockpit" layer of the Briefing: the user's own pinned KPI/chart/table cards.
 *  Each is re-run through the guard battery so its number stays honest, then laid out on a CANVAS
 *  (PinnedCardsCanvas) the reader arranges by priority and resizes at will — the layout persists
 *  per connection, the same scope every briefing element uses. Renders nothing until a card exists. */
export function PinnedCards({ connectionId, refreshKey, onOpenSource }: {
  connectionId: string;
  refreshKey?: number;
  onOpenSource?: (insightId: string) => void;
}) {
  const [cards, setCards] = useState<CardState[]>([]);
  const [ready, setReady] = useState(false);

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

  const remove = useCallback(async (id: string) => {
    await deleteDashboardCard(id).catch(() => {});
    setCards(cs => cs.filter(c => c.card.id !== id));
  }, []);

  const refreshOne = useCallback(async (id: string) => {
    try {
      const run = await runDashboardCard(id);
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, run, failed: false } : c)));
    } catch {
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, failed: true } : c)));
    }
  }, []);

  if (!ready || cards.length === 0) return null;

  return (
    <div style={{ marginBottom: 20 }}>
      <div className="aug-label" style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        Your pinned cards
        <span style={{
          fontSize: 9, fontWeight: 600, letterSpacing: ".05em", textTransform: "uppercase" as const,
          padding: "2px 6px", borderRadius: "var(--r1)", color: "var(--grn4)",
          background: "var(--grn1)", border: "1px solid var(--grn2)",
        }}>Guarded</span>
        <span style={{ fontSize: 9.5, fontWeight: 400, color: "var(--t4)" }}>drag the title to arrange · select to resize</span>
      </div>
      <PinnedCardsCanvas
        connectionId={connectionId}
        cards={cards}
        onRemove={remove}
        onRefresh={refreshOne}
        onOpenSource={onOpenSource}
      />
    </div>
  );
}
