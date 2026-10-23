"use client";

/**
 * What each placed element read, as its cell hears it (Arc AP-6 — the builder's checks chip: "12 read cleanly · 1 to
 * fix"). A piece that cannot be read draws `Unread`, one still reading draws `Reading`, a card withheld or not one of
 * the person's draws its own tile: each marks its cell while it is drawn, and the cell says what it holds — refused,
 * reading, or read cleanly — to the page that keeps the dashboard. Nothing else is asked of a piece.
 */
import { createContext, useContext, useEffect } from "react";

export type ReadStatus = "refused" | "reading";
export interface ReadSlot { mark: (status: ReadStatus, reason: string) => () => void }

export const ReadSlotContext = createContext<ReadSlot | null>(null);

/** Mark the cell this is drawn in as refused, with why, or still reading — for as long as it is drawn. */
export function useMarkRead(status: ReadStatus, reason = ""): void {
  const slot = useContext(ReadSlotContext);
  useEffect(() => (slot ? slot.mark(status, reason) : undefined), [slot, status, reason]);
}
