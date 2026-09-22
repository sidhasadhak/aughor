"use client";

/**
 * BriefActions — under the synthesis (CB-6 / CB-7, 2026-09-23): for each cited finding that bears on a
 * declared goal or carries an action, one line. The goal is what people wrote in organisation
 * settings; the action is the cited investigation's own recommendation (executable in the inbox,
 * through the gated door) or the playbook's best play by learned success rate (a suggestion). A
 * finding with neither shows nothing — an invented action would be worse than none.
 */
import type { BriefingCitation } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function BriefActions({ citations, onOpenInvestigation }: {
  citations: BriefingCitation[];
  onOpenInvestigation?: (invId: string) => void;
}) {
  const rows = (citations ?? []).filter(c => c.priority || c.action);
  if (rows.length === 0) return null;
  return (
    <ul data-testid="brief-actions" className="mt-3 space-y-1.5 border-t border-zinc-700/40 pt-2">
      {rows.map(c => (
        <li key={c.ref} className="aug-fs-xs text-zinc-400 flex flex-wrap items-baseline gap-x-2">
          <span className="text-zinc-500">[{c.ref}]</span>
          {c.priority && <span className="text-zinc-300">bears on the goal: {c.priority}</span>}
          {c.action && (
            <span>
              next: <span className="text-zinc-300">{c.action.text}</span>
              {c.action.kind === "play" && typeof c.action.success_rate === "number" && c.action.success_rate > 0 && (
                <span className="text-zinc-500"> · worked {Math.round(c.action.success_rate * 100)}% of the time</span>
              )}
              {c.action.kind === "recommendation" && c.action.inv_id && onOpenInvestigation && (
                <Button variant="ghost" size="xs" className="ml-1 underline text-zinc-300" onClick={() => onOpenInvestigation(c.action!.inv_id!)}>
                  execute in the inbox
                </Button>
              )}
              <span className="text-zinc-500"> · {c.action.why}</span>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
