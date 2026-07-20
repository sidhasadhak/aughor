"use client";

/**
 * PinnedCardsGrid — the cockpit's DEFAULT ("tidy") layout: a responsive grid of pinned cards the
 * reader reorders by priority via drag-and-drop. A scorecard wants scannable, uniform tiles far
 * more often than free spatial placement, so this is the default; the freeform React-Flow canvas
 * lives behind the "Arrange freely" toggle (PinnedCardsCanvas).
 *
 * Reorder is native HTML5 drag-and-drop (no extra dependency): drag a card onto another to drop it
 * before that one; a drop on empty space sends it to the end. Order persists per-connection in
 * localStorage; a drag that begins on a button / input / chart is ignored so the card stays usable.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { PinnedCardBody, type CardState } from "@/components/brief/PinnedCardBody";

const CARD_H = 210;   // uniform tile height → a clean, gap-free scorecard grid

const orderKey = (cid: string) => `aughor:cockpit-order:${cid}`;
function loadOrder(cid: string): string[] {
  try { const raw = localStorage.getItem(orderKey(cid)); const v = raw ? JSON.parse(raw) : []; return Array.isArray(v) ? v : []; }
  catch { return []; }
}
function saveOrder(cid: string, order: string[]) {
  try { localStorage.setItem(orderKey(cid), JSON.stringify(order)); } catch { /* private mode / quota — order just won't persist */ }
}
const sameOrder = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

export function PinnedCardsGrid({ connectionId, cards, onRemove, onRefresh, onOpenSource, onEvidence }: {
  connectionId: string;
  cards: CardState[];
  onRemove: (id: string) => void;
  onRefresh: (id: string) => void;
  onOpenSource?: (iid: string) => void;
  onEvidence?: (iid: string) => void;
}) {
  const [order, setOrder] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);

  // Load the saved order once the connection is known (client-only — localStorage isn't on the server).
  useEffect(() => { setOrder(loadOrder(connectionId)); setLoaded(true); }, [connectionId]);

  // Reconcile the saved order with the live card set: keep saved order for cards that still exist,
  // append newly-pinned cards at the end, drop removed ones — then persist the reconciled order.
  useEffect(() => {
    if (!loaded) return;
    setOrder(prev => {
      const live = new Set(cards.map(c => c.card.id));
      const kept = prev.filter(id => live.has(id));
      const added = cards.map(c => c.card.id).filter(id => !kept.includes(id));
      const next = [...kept, ...added];
      if (sameOrder(next, prev)) return prev;
      saveOrder(connectionId, next);
      return next;
    });
  }, [cards, loaded, connectionId]);

  const ordered = useMemo(() => {
    const byId = new Map(cards.map(c => [c.card.id, c]));
    const out = order.map(id => byId.get(id)).filter((c): c is CardState => !!c);
    // Any card not yet in `order` (first paint before the reconcile effect settles) still renders.
    if (out.length !== cards.length) {
      const seen = new Set(out.map(c => c.card.id));
      for (const c of cards) if (!seen.has(c.card.id)) out.push(c);
    }
    return out;
  }, [order, cards]);

  const move = useCallback((from: string, before: string | null) => {
    setOrder(prev => {
      const base = (prev.length ? prev : ordered.map(c => c.card.id)).filter(x => x !== from);
      const idx = before == null ? base.length : (base.indexOf(before) < 0 ? base.length : base.indexOf(before));
      base.splice(idx, 0, from);
      saveOrder(connectionId, base);
      return base;
    });
  }, [connectionId, ordered]);

  const onDragStart = useCallback((e: React.DragEvent, id: string) => {
    // A drag starting on an interactive element (button/input/select/link/chart) must not move the
    // card — otherwise you couldn't click Refresh or pan a chart.
    if ((e.target as HTMLElement).closest("button, a, input, select, textarea, canvas, svg")) {
      e.preventDefault();
      return;
    }
    setDragId(id);
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", id); } catch { /* some browsers require a payload */ }
  }, []);

  const end = useCallback(() => { setDragId(null); setOverId(null); }, []);

  if (!cards.length) return null;

  return (
    <div
      onDragOver={e => { if (dragId) { e.preventDefault(); } }}
      onDrop={e => { if (dragId) { e.preventDefault(); move(dragId, null); end(); } }}   // drop on empty space → end
      style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12, alignItems: "start" }}
    >
      {ordered.map(cs => {
        const id = cs.card.id;
        const isDragging = dragId === id;
        const isOver = overId === id && dragId !== id;
        return (
          <div
            key={id}
            draggable
            onDragStart={e => onDragStart(e, id)}
            onDragEnd={end}
            onDragOver={e => { if (dragId && dragId !== id) { e.preventDefault(); if (overId !== id) setOverId(id); } }}
            onDragLeave={() => { if (overId === id) setOverId(null); }}
            onDrop={e => { if (dragId && dragId !== id) { e.preventDefault(); e.stopPropagation(); move(dragId, id); } end(); }}
            style={{
              height: CARD_H, position: "relative",
              opacity: isDragging ? 0.4 : 1,
              outline: isOver ? "2px solid var(--vio3)" : "none",
              outlineOffset: 2, borderRadius: "var(--r3)",
              transition: "opacity var(--dur-fast, .15s)",
            }}
          >
            <PinnedCardBody cs={cs} onRemove={onRemove} onRefresh={onRefresh} onOpenSource={onOpenSource} onEvidence={onEvidence} />
          </div>
        );
      })}
    </div>
  );
}
