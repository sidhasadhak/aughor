"use client";

/**
 * FL-5 — what a deep run says while it works. The progress card that lived here (an
 * activity line, a bar, a line of counts) is gone at the user's word (2026-09-30): the
 * thinking row above the answer carries the latest update, and a box under it said the
 * same thing twice. What stays is the findings, landing as prose.
 */

import type { ChatTurn } from "@/lib/chatTurn";

/**
 * FL-5 — narrative interleaving: the wait's actual engagement payload. Each
 * answered sub-question's sentence lands as prose the moment it exists ("So
 * far East and South look flat…") instead of accumulating silently for the
 * terminal report. Prose only — evidence, charts and SQL stay in the report,
 * where the receipts are.
 */
export function InFlightFindings({ turn }: { turn: ChatTurn }) {
  const spoken = turn.subqAnswers.filter((a) => a.answer);
  if (spoken.length === 0 || turn.exploreReport) return null;
  return (
    <div className="my-1.5 flex flex-col gap-1" data-testid="in-flight-findings">
      {spoken.map((a, i) => (
        <p key={a.subq_id} className="aug-fs-sm text-zinc-400 leading-relaxed max-w-[66ch]">
          {a.answer}
          {i === spoken.length - 1 && (
            <span
              aria-hidden="true"
              className="aug-caret"
            />
          )}
        </p>
      ))}
    </div>
  );
}
