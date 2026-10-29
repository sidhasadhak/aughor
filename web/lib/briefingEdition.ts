/**
 * Arc BG (ROADMAP §3.66) — the words an edition's page puts around what the server measured and wrote.
 *
 * Pure: no fetch, no DOM. The page reads these so a story's kicker, a figure's tone and the readers on
 * offer are decided once, in one place a test can hold.
 */
import type { AccessGroup, EditionFigure, EditionStory } from "@/lib/api";

/** The Segmented control needs a non-empty value; the organisation is "" to the server. */
export const ORGANISATION = "_organisation";

export const toServerReader = (v: string): string => (v === ORGANISATION ? "" : v);
export const fromServerReader = (v: string | undefined | null): string => (v ? v : ORGANISATION);

/** The readers on offer: the organisation, then every function group, by name. */
export function readerOptions(groups: Pick<AccessGroup, "id" | "name" | "kind">[]): { value: string; label: string }[] {
  const fns = groups.filter(g => g.kind === "function").sort((a, b) => a.name.localeCompare(b.name));
  return [{ value: ORGANISATION, label: "The organisation" }, ...fns.map(g => ({ value: g.id, label: g.name }))];
}

const UNIT_WORDS: Record<string, [string, string]> = {
  day: ["day", "days"], week: ["week", "weeks"], month: ["month", "months"], year: ["year", "years"],
};

export function rangeWord(period: string, n = 1): string {
  const [one, many] = UNIT_WORDS[period] ?? ["range", "ranges"];
  return n === 1 ? one : many;
}

/** Why a story is on the page, in a reader's words. */
export function kickerOf(story: Pick<EditionStory, "reason">, fig: EditionFigure | undefined, period: string): string {
  if (fig && story.reason === "streak" && fig.streak) {
    const n = Math.abs(fig.streak);
    return `${n} ${rangeWord(period, n)} in a row ${fig.streak > 0 ? "up" : "down"}`;
  }
  if (story.reason === "new_level") return "Holding a new level";
  if (story.reason === "watch") return "Your watch";
  if (fig && fig.z !== null && fig.outside) {
    if (fig.floor) return "Far outside its usual range";
    return fig.z > 0 ? "Above its usual range" : "Below its usual range";
  }
  return "This " + rangeWord(period);
}

/** Good, bad or neither: a figure's distance from its usual range, read in the direction the guide
 *  calls good. A figure whose good direction is not declared is neither — colour would be a judgement
 *  the data does not carry. */
export function toneOf(fig: Pick<EditionFigure, "better" | "current" | "usual">): "good" | "bad" | "neutral" {
  if (fig.better === "none" || fig.current === null || !fig.usual) return "neutral";
  const up = fig.current > fig.usual.mean;
  return (up === (fig.better === "up")) ? "good" : "bad";
}

export function writeLabel(period: string, custom: boolean): string {
  if (custom) return "Write this range's edition";
  return `Write this ${rangeWord(period)}'s edition`;
}

/** A function group's id from a name a person types: a lowercase slug of at most 64 characters. */
export function groupIdOf(name: string): string {
  return name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
}
