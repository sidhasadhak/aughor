"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  deleteDashboardCard, listDashboardCards, runDashboardCard, pinInsightToDashboard,
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
export function PinnedCards({ connectionId, schema, refreshKey, suggestions, onPinned, onOpenSource, onEvidence }: {
  connectionId: string;
  schema?: string;
  refreshKey?: number;
  /** Real movers from this cycle offered as one-click pins in the empty state. */
  suggestions?: { insightId: string; value: string; label: string }[];
  onPinned?: () => void;
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

  // One-click pin from the empty-state suggestions — the same guarded path as a finding's Pin.
  const pinSuggestion = useCallback(async (insightId: string) => {
    try {
      await pinInsightToDashboard(connectionId, insightId, { scope: "connection", scopeRef: connectionId, schema });
      toast.success("Pinned to your cockpit");
      onPinned?.();
    } catch {
      toast.error("Couldn't pin finding", { description: "The finding's query didn't pass the trust guards." });
    }
  }, [connectionId, schema, onPinned]);

  // ── ⌘K "Tidy cockpit" command — offered only while the cockpit has cards ──
  const tidyCommands = useMemo<Command[]>(() =>
    cards.length > 0
      ? [{ id: "cockpit-tidy", label: "Tidy cockpit", sublabel: "Re-pack the cockpit into a clean, gap-free grid", icon: "canvas", accent: "var(--grn3)", keywords: "tidy cockpit arrange pack grid layout reset", run: () => tidyRef.current?.() }]
      : [],
  [cards.length]);
  useRegisterCommands("cockpit", tidyCommands);

  if (!ready) return null;   // avoid an empty-state flash before the first fetch settles

  // Empty state (Direction B) — teach the cockpit instead of vanishing. The suggested pins are
  // REAL movers from this cycle, so the first pin is one grounded click. The "Your cockpit"
  // eyebrow + violet rule are owned by the standing-layer wrapper above.
  if (cards.length === 0) {
    return (
      <div style={{ marginBottom: 20 }}>
        <div style={{ border: "1px dashed var(--vio2)", background: "var(--vio1)", borderRadius: "var(--r3)", padding: "20px 22px" }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 14, fontWeight: 600, color: "var(--t1)" }}>Nothing pinned yet</h3>
          <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.5, color: "var(--t2)", maxWidth: "56ch" }}>
            Pin any number or chart from a finding and it lives here permanently — refreshed every cycle,
            guarded like everything else, arranged your way. Start with this cycle&apos;s movers, or compose one above.
          </p>
          {suggestions && suggestions.length > 0 && (
            <>
              <div className="aug-label" style={{ color: "var(--vio4)", margin: "16px 0 8px" }}>From this cycle&apos;s findings</div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {suggestions.map(s => (
                  <div key={s.insightId} style={{ display: "flex", alignItems: "center", gap: 9, background: "var(--bg-2)", border: "1px solid var(--b2)", borderRadius: "var(--r2)", padding: "8px 12px", fontSize: 12, color: "var(--t2)" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--t1)" }}>{s.value}</span>
                    <span style={{ color: "var(--t3)", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.label}</span>
                    <Button variant="ghost" size="xs" onClick={() => pinSuggestion(s.insightId)} title="Pin this figure to your cockpit"
                      style={{ color: "var(--vio4)", fontWeight: 600, fontSize: 12, padding: "2px 8px" }}>Pin</Button>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
        <span className="aug-tag aug-tag-green">Guarded</span>
        <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>your pinned cards · drag the title to arrange · select to resize · snaps to grid, never overlaps</span>
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
