/**
 * What the host publishes to a cockpit, and therefore all a condition may read (Arc CT, CT-2).
 *
 * The tree carries STATUSES, never figures: a figure appears only inside a card, where it is
 * measured. The model writes "show this card when the watch is over its limit"; whether the
 * watch is over its limit is the host's to say.
 *
 *   /tab                     which tab is open — the only path a spec may seed or write
 *   /range/status            final · provisional · to_date
 *   /cards/<card id>/status  within · over · unmeasured · withheld
 */

export const RANGE_STATUSES = ["final", "provisional", "to_date"] as const;
export type RangeStatus = (typeof RANGE_STATUSES)[number];

export const CARD_STATUSES = ["within", "over", "unmeasured", "withheld"] as const;
export type CardStatus = (typeof CARD_STATUSES)[number];

export interface CockpitHostState {
  range: { status: RangeStatus };
  cards: Record<string, { status: CardStatus }>;
}

export const TAB_PATH = "/tab";
export const RANGE_STATUS_PATH = "/range/status";

const CARD_STATUS_PATH = /^\/cards\/([A-Za-z0-9_-]{1,64})\/status$/;

export type PublishedPath =
  | { kind: "range"; values: readonly string[] }
  | { kind: "card"; card: string; values: readonly string[] };

/** The path as the host publishes it, or null when a condition may not read it. */
export function publishedPath(path: string): PublishedPath | null {
  if (path === RANGE_STATUS_PATH) return { kind: "range", values: RANGE_STATUSES };
  const m = CARD_STATUS_PATH.exec(path);
  if (m) return { kind: "card", card: m[1], values: CARD_STATUSES };
  return null;
}

/** The state a cockpit renders against: the open tab, and the host's tree laid over it. */
export function stateModel(tab: string | null, host: CockpitHostState): Record<string, unknown> {
  return { tab, range: { status: host.range.status }, cards: host.cards };
}
