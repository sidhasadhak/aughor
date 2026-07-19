"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  deleteDashboardCard, listDashboardCards, runDashboardCard,
  type DashboardCard,
} from "@/lib/api";
import { PinnedCardsCanvas, type CardState } from "@/components/brief/PinnedCardsCanvas";
import { toast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { useRegisterCommands, type Command } from "@/lib/commandRegistry";

/** The standing cockpit layer: the user's OWN persistent pinned cards on one canvas the reader
 *  arranges. Each card's number is re-run through the guard battery on read. The brief's findings
 *  read separately in the narrative layer (the exhibit strip) — the cockpit is the surface the
 *  user curates, not a dump of the cycle's signals. Renders nothing until a card exists. */
export function PinnedCards({ connectionId, refreshKey, onOpenSource, onEvidence }: {
  connectionId: string;
  refreshKey?: number;
  onOpenSource?: (insightId: string) => void;
  onEvidence?: (insightId: string) => void;
}) {
  const [cards, setCards] = useState<CardState[]>([]);   // the user's persistent pins
  const [ready, setReady] = useState(false);

  // User pins — fetched from the store, each re-run through the guard battery.
  useEffect(() => {
    if (!connectionId) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await listDashboardCards({ scope: "connection", scopeRef: connectionId });
        const withRuns = await Promise.all(
          list.map(async (card: DashboardCard): Promise<CardState> => {
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

  // ── ⌘K "Tidy cockpit" command — offered only while the cockpit has cards ──
  const tidyCommands = useMemo<Command[]>(() =>
    cards.length > 0
      ? [{ id: "cockpit-tidy", label: "Tidy cockpit", sublabel: "Re-pack the cockpit into a clean, gap-free grid", icon: "canvas", accent: "var(--grn3)", keywords: "tidy cockpit arrange pack grid layout reset", run: () => tidyRef.current?.() }]
      : [],
  [cards.length]);
  useRegisterCommands("cockpit", tidyCommands);

  if (!ready || cards.length === 0) return null;

  return (
    <div style={{ marginBottom: 20 }}>
      <div className="aug-label" style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        Your cockpit
        <span className="aug-tag aug-tag-green">Guarded</span>
        <span className="aug-fs-xs" style={{ fontWeight: 400, color: "var(--t4)", textTransform: "none" as const, letterSpacing: 0 }}>your pinned cards · drag the title to arrange · select to resize · snaps to grid, never overlaps</span>
        <Button
          variant="ghost" size="xs"
          onClick={() => tidyRef.current?.()}
          title="Re-arrange every card into a clean, gap-free grid"
          style={{ marginLeft: "auto", fontSize: 11, color: "var(--t3)", padding: "2px 8px", textTransform: "none" as const, letterSpacing: 0 }}
        >▦ Tidy up</Button>
      </div>
      <PinnedCardsCanvas
        connectionId={connectionId}
        cards={cards}
        onRemove={remove}
        onRefresh={refreshOne}
        onOpenSource={onOpenSource}
        onEvidence={onEvidence}
        registerTidy={registerTidy}
      />
    </div>
  );
}
