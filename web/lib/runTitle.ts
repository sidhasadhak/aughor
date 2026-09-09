/**
 * runTitle — a human title for a run whose stored question carries machine grounding.
 *
 * PX-1 (§3.14): scheduled investigations are dispatched with a code-written grounding
 * block prepended to the question (`aughor/automations/temporal.py` — the observation
 * window, and sometimes the previous run's report). That text is FOR THE MODEL, and it
 * is correct there; five cards on one screen of Agent runs were titled
 * "[Scheduled-run context — written by code, not inferred] This is a scheduled daily
 * run at 2026-…" because the UI reused the stored question as a display title.
 *
 * The law: the fix is display-side only — what the model receives never changes to
 * make a screen prettier. This module derives; it never rewrites storage.
 *
 * The two header lines and the previous-block's closing sentence are byte-for-byte
 * constants in temporal.py (`observation_note`, `previous_report_note`). If either
 * changes shape there, the tests here are the tripwire — update both together.
 */

const SCHEDULED_HEADER = "[Scheduled-run context — written by code, not inferred]";
const PREVIOUS_HEADER = "[Previous scheduled report — for consistency checking]";
// The previous-report block can QUOTE a summary containing blank lines, so it cannot
// be stripped paragraph-wise; its code-written closing sentence is the anchor.
const PREVIOUS_TAIL = "instead of narrating the difference as a business change.";

export interface RunTitle {
  /** What a person should read as the run's title — the question, never the plumbing. */
  title: string;
  /** True when grounding was stripped: this run was schedule-shaped. */
  scheduled: boolean;
}

export function runDisplayTitle(question: string | null | undefined): RunTitle {
  const raw = (question ?? "").trim();
  let text = raw;
  let scheduled = false;
  if (text.startsWith(SCHEDULED_HEADER)) {
    scheduled = true;
    // The observation note has no internal blank lines — it ends at the first one.
    const cut = text.indexOf("\n\n");
    text = cut === -1 ? "" : text.slice(cut + 2).trimStart();
  }
  if (text.startsWith(PREVIOUS_HEADER)) {
    scheduled = true;
    const tail = text.indexOf(PREVIOUS_TAIL);
    text = tail === -1 ? "" : text.slice(tail + PREVIOUS_TAIL.length).trimStart();
  }
  text = text.trim();
  if (text) return { title: text, scheduled };
  // A scheduled run whose config carried an empty question: name what it is rather
  // than showing the plumbing or an empty string.
  return { title: scheduled ? "Scheduled run" : raw, scheduled };
}
