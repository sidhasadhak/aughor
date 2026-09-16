"use client";

/**
 * AnswerParts — the answer's structured half, rendered (AV-1, §3.11 third movement).
 *
 * One organ for the closed part vocabulary the `present` tool validated. Everything
 * here is promotion, not invention: fact rows carry the ProposalCard's labeled-row
 * treatment, the badge is the established StatusChip, the bar is `ui/progress` with
 * the real denominator the schema already enforced, a section's body reads through
 * AnswerProse, and an action is a DOOR — `follow_up` rides the exact path the
 * follow-up chips ride, and `proposal_ref` renders the live approval card whose
 * Accept goes through the one inbox.
 *
 * A kind this client does not know renders as its own name in a quiet line — the
 * vocabulary is versioned, and a newer server must degrade legibly, never as raw
 * JSON and never as silence.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { AnswerProse } from "@/components/chat/AnswerProse";
import { ProposalCardById } from "@/components/ProposalCard";
import { approverName } from "@/lib/auth";
import { Icon } from "@/components/ui/icon";
import type { AnswerPart } from "@/lib/chatTurn";

/** The schema's one semantic scale, mapped onto the established chip hues. */
const TONE_HUE: Record<string, ChipHue> = {
  good: "positive", warn: "caution", bad: "negative", info: "info", neutral: "muted",
};

function FactRows({ part }: { part: Extract<AnswerPart, { kind: "fact_set" }> }) {
  return (
    <div className="flex flex-col gap-1">
      {part.title && (
        <span className="aug-text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--t3)" }}>
          {part.title}
        </span>
      )}
      {part.facts.map((f, i) => (
        <div key={i} className="flex gap-2 items-baseline min-w-0">
          <span className="aug-text-xs shrink-0" style={{ color: "var(--t3)", width: 148 }}>
            {f.label}
          </span>
          <span className="aug-text-sm min-w-0" style={{ color: "var(--t2)", overflowWrap: "anywhere" }}>
            {f.value}
          </span>
          {f.status && TONE_HUE[f.status] && (
            <StatusChip hue={TONE_HUE[f.status]} strength="soft">{f.status}</StatusChip>
          )}
        </div>
      ))}
    </div>
  );
}

function Section({ part }: { part: Extract<AnswerPart, { kind: "section" }> }) {
  const [open, setOpen] = useState(!part.collapsed);
  return (
    <div className="rounded-md" style={{ border: "1px solid var(--b1)" }}>
      <Button variant="ghost" size="xs" onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        className="w-full h-auto justify-start gap-1.5 px-2 py-1.5 font-normal">
        <span style={{ transform: open ? "rotate(90deg)" : undefined, transition: "transform 120ms" }}>
          <Icon name="next" size={14} />
        </span>
        <span className="aug-text-sm" style={{ color: "var(--t1)" }}>{part.title}</span>
      </Button>
      {open && (
        <div className="px-2 pb-2">
          <AnswerProse text={part.body} />
        </div>
      )}
    </div>
  );
}

export function AnswerParts({ parts, onFollowUp }: {
  parts: AnswerPart[];
  /** The same door the follow-up chips ride — a click asks, nothing else. */
  onFollowUp?: (question: string) => void;
}) {
  if (!parts.length) return null;
  return (
    <div className="flex flex-col gap-2 my-1" data-testid="answer-parts">
      {parts.map((part, i) => {
        switch (part.kind) {
          case "fact_set":
            return <FactRows key={i} part={part} />;
          case "status":
            return (
              <span key={i}>
                <StatusChip hue={TONE_HUE[part.tone] ?? "muted"} strength="soft">
                  {part.label}
                </StatusChip>
              </span>
            );
          case "progress":
            return (
              <div key={i} className="flex items-center gap-2">
                <span className="aug-text-xs shrink-0" style={{ color: "var(--t3)" }}>
                  {part.label}
                </span>
                <Progress value={(part.done / part.total) * 100} className="flex-1" />
                <span className="aug-text-xs tabular-nums" style={{ color: "var(--t2)" }}>
                  {part.done}/{part.total}
                </span>
              </div>
            );
          case "section":
            return <Section key={i} part={part} />;
          case "action_set":
            return (
              <div key={i} className="flex flex-wrap gap-1.5">
                {part.actions.map((a, j) =>
                  a.action === "follow_up" ? (
                    <Button key={j} variant="secondary" size="xs"
                      onClick={() => onFollowUp?.(a.question)}>
                      {a.label}
                    </Button>
                  ) : null)}
              </div>
            );
          case "proposal_ref":
            return <ProposalCardById key={i} proposalId={part.proposal_id} actor={approverName("chat")} />;
          default:
            // A newer server's kind: name it quietly rather than dump or drop it.
            return (
              <span key={i} className="aug-text-xs" style={{ color: "var(--t3)" }}>
                (a {(part as { kind: string }).kind} part this client does not render yet)
              </span>
            );
        }
      })}
    </div>
  );
}
