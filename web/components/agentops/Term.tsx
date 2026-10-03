"use client";

/**
 * Arc AO-4 — the six words Agent Ops uses without ever saying what they mean, explained
 * ONCE, where they appear. Measured 2026-10-03: "built-in", "runner", "goldens",
 * "probation", "grant" and "door" each sat on a screen with no definition anywhere a
 * reader could reach from it. One map, one component; the glossary (docs/GLOSSARY.md) is
 * the authority for the words, this is the authority for what the screen says about them.
 */
import type React from "react";

export const TERMS = {
  "built-in": "An agent that ships with Aughor and runs the platform's own jobs (profiling, "
    + "briefings, watching). You can pause or budget it; you cannot rewrite it.",
  runner: "A background process that is not an agent — automation ticks, eval experiments. "
    + "Counted apart so a heartbeat never reads as an agent's work.",
  goldens: "Questions with the SQL a person says is right. The agent's own regression "
    + "suite — a pass means its answer matched that SQL's rows, never a judge's opinion.",
  probation: "A new automation that a person must still watch: its first departures are "
    + "held for approval until it has earned its run.",
  grant: "A declared action an agent may PROPOSE on your behalf. It never executes one — "
    + "a person approves every proposal.",
  door: "A way in to an agent: the chat, a Slack bot, an automation that runs as it. "
    + "Each door has its own state, and this page says which are open.",
} as const;

export type TermId = keyof typeof TERMS;

/** The word, with its one-sentence meaning on hover and a dotted underline that says
 *  there is one. Native `title` on purpose: it works everywhere a word does, inside a
 *  chip or a table head, without a portal. */
export function Term({ id, children, style }: {
  id: TermId; children?: React.ReactNode; style?: React.CSSProperties;
}) {
  return (
    <span title={TERMS[id]} aria-label={`${id}: ${TERMS[id]}`}
      style={{ textDecoration: "underline dotted", textUnderlineOffset: 2, cursor: "help", ...style }}>
      {children ?? id}
    </span>
  );
}
