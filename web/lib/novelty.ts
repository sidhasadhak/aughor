/**
 * A finding's novelty, as the reader sees it. The explorer scores novelty 1–5 and clamps it there
 * (`aughor/explorer/verify.py` `clamp_novelty`); the Briefing read it out of 10 — "High" at 7, a meter full at 10 —
 * so on theLook's 44 findings (scored 1–5) "High" never showed, the top score read "Notable", and the meter stopped
 * half way (2026-10-13). One scale, here.
 */
export const NOVELTY_MAX = 5;

/** The word for a score: 5 High · 4 Notable · 3 Mid · below that Low. */
export function noveltyLabel(n: number): string {
  if (n >= 5) return "High";
  if (n >= 4) return "Notable";
  if (n >= 3) return "Mid";
  return "Low";
}

/** How far along the scale a score sits, 0–1 — for a meter or a shade. */
export function noveltyShare(n: number): number {
  return Math.max(0, Math.min(1, n / NOVELTY_MAX));
}

/** "4 of 5" — the score as the reader reads it. */
export function noveltyOutOf(n: number): string {
  return `${Math.round(n)} of ${NOVELTY_MAX}`;
}
