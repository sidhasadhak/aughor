/**
 * What the host says about each card, read off the card's own run (Arc CT, CT-4).
 *
 * A card is run in the browser, as the Briefing's cockpit runs its cards, so this is where
 * its status is said. The range's status is the server's (`aughor/cockpit/host.py`).
 *
 *   within      the card has a limit and its value is inside it
 *   over        the card has a limit and its value is past it
 *   unmeasured  the card has no limit, or no value to hold against one
 *   withheld    not said here yet — see below
 *
 * **Nothing says `withheld` today.** It needs a rule for which cards a reader may not see,
 * and the platform has no such rule per card: whoever may open a canvas may see its cards.
 * The word is in the vocabulary and the renderer honours it; the day a rule exists, this is
 * the function that says it.
 */
import type { CardState } from "@/components/brief/PinnedCardBody";
import type { CardStatus, CockpitHostState, RangeStatus } from "@/lib/cockpit/hostState";

interface Limits { warning?: number | null; critical?: number | null; direction?: string }

/** The value a card's limit is held against: the run's own figure when the run was cut to a
 *  range (a range's figure never rolls into the card's standing value), else the standing one.
 *
 *  The range's figure is read from `run.value`, which the server states as a number. The
 *  first cut of this function read it out of `rows` and asked for a number there; the server
 *  sends `rows` as text, so every ranged card read as unmeasured and no condition on one ever
 *  held. Twenty tests passed on it. The live run did not. */
export function cardValue(cs: CardState): number | null {
  const { run, failed } = cs;
  if (failed || !run || run.error) return null;
  const v = run.scoped && !run.scoped.standing ? run.value : run.refresh?.last_value;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** The limits a card carries, nearest first: crossing the warning is already over. */
function limitsOf(cs: CardState): { values: number[]; below: boolean } {
  const t = (cs.card.thresholds ?? {}) as Limits;
  const values = [t.warning, t.critical].filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  return { values, below: t.direction === "below" };
}

export function cardStatus(cs: CardState): CardStatus {
  const { values, below } = limitsOf(cs);
  const value = cardValue(cs);
  if (!values.length || value === null) return "unmeasured";
  const crossed = values.some(limit => (below ? value <= limit : value >= limit));
  return crossed ? "over" : "within";
}

/** The tree a cockpit's conditions read: the range's status from the server, each card's
 *  from its run. A card the canvas holds always has a status, so a condition on it is never
 *  silently false for want of one. */
export function hostStateOf(rangeStatus: RangeStatus, cards: CardState[]): CockpitHostState {
  return {
    range: { status: rangeStatus },
    cards: Object.fromEntries(cards.map(cs => [cs.card.id, { status: cardStatus(cs) }])),
  };
}
