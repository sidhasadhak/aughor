"use client";

/**
 * FL-5 — the deep run's wait, composed as ONE in-place progress card.
 *
 * The stream already says everything (phase and scan progress, executed
 * queries, per-sub-question findings, guard receipts, delegations, transport
 * hops); this file is presentation only. Three lines, in the mock's shape:
 * a spinner line naming the current activity, a 3px progress bar rendered ONLY
 * when a real denominator exists (no fake motion), and a mono meta line of
 * counts. The FL-2 transport notices ride in as `children` so the wait reads
 * as one block, not a stack; the card swaps out when the result lands (the
 * turn's status leaves "loading").
 *
 * Deliberately NOT a card registry and NOT a conclusions surface (rejection of
 * record, 2026-08-28): it renders *process*. The numbers land in the report.
 */

import type { ReactNode } from "react";

import type { ChatTurn } from "@/lib/chatTurn";

function count(n: number, singular: string, plural?: string): string {
  return `${n} ${n === 1 ? singular : (plural ?? `${singular}s`)}`;
}

export function RunProgressCard({ turn, children }: { turn: ChatTurn; children?: ReactNode }) {
  // A real denominator only: a dimension scan, else the planned sub-questions.
  const bar = turn.scanProgress
    ?? (turn.subQuestions.length
      ? { done: turn.subqAnswers.length, total: turn.subQuestions.length }
      : null);
  const meta = [
    turn.phases.length > 0 && count(turn.phases.length, "phase"),
    turn.queriesExecuted.length > 0 && count(turn.queriesExecuted.length, "query", "queries"),
    turn.scanProgress && `${turn.scanProgress.done}/${turn.scanProgress.total} dimensions`,
    turn.scanProgress && turn.scanItems.length > 0
      && `${turn.scanItems[turn.scanItems.length - 1]} in progress`,
    turn.subQuestions.length > 0
      && `${turn.subqAnswers.length}/${turn.subQuestions.length} sub-questions`,
    turn.guardReceipts.length > 0 && count(turn.guardReceipts.length, "guard") + " fired",
    turn.delegations.length > 0 && count(turn.delegations.length, "delegation"),
  ].filter(Boolean).join(" · ");

  return (
    <div className="my-1 max-w-[460px] rounded-[var(--r3)] border border-zinc-800 bg-zinc-900/60 px-3.5 py-3">
      <div className="flex items-center gap-2.5 aug-fs-sm text-zinc-400">
        <span
          aria-hidden="true"
          className="h-3 w-3 flex-none rounded-[var(--r-pill)] border-[1.5px] border-zinc-700 border-t-[var(--blue3)] animate-spin motion-reduce:animate-none"
        />
        <span>{turn.statusText || "Working…"}</span>
      </div>
      {bar && bar.total > 0 && (
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={bar.total}
          aria-valuenow={Math.min(bar.done, bar.total)}
          className="mt-2.5 h-[3px] overflow-hidden rounded-[var(--r1)] bg-zinc-800"
        >
          <span
            className="block h-full rounded-[var(--r1)] bg-[var(--blue-solid)] transition-[width] duration-300"
            style={{ width: `${Math.round((Math.min(bar.done, bar.total) / bar.total) * 100)}%` }}
          />
        </div>
      )}
      {meta && <div className="mt-1.5 font-mono aug-fs-xs text-zinc-500">{meta}</div>}
      {children}
    </div>
  );
}

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
              className="ml-1 inline-block h-[13px] w-[7px] translate-y-[2px] bg-zinc-600 animate-pulse motion-reduce:animate-none"
            />
          )}
        </p>
      ))}
    </div>
  );
}
