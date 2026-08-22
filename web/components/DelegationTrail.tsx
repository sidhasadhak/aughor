"use client";
/**
 * VA-2 — the delegated hops of one turn, rendered as Chain-of-Thought steps.
 *
 * A delegate's frames already reached this surface before this component existed, and
 * that was the problem rather than the fix: they arrived carrying no attribution, so a
 * specialist's query rendered as the supervisor's own work — a question nobody in the
 * conversation appeared to have asked, against a connection the supervisor may not even
 * be bound to. `chatTurn` now routes those frames to a hop; this is where the hop
 * becomes something a reader can see.
 *
 * Mirrors ToolTrail and GuardReceiptChain deliberately: same organ, same "renders
 * nothing when empty" contract, same label philosophy — the backend names the
 * mechanism, the surface names what the reader gains.
 *
 * The description is DERIVED from the hop's projected work, never from a count of
 * frames. A hop that streamed six frames and ran no query did not do six things, and a
 * trail that says it did is the kind of confident-looking number this codebase keeps
 * finding. When the work is unreadable the step says so plainly instead of guessing.
 */
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import type { DelegatedHop } from "@/lib/chatTurn";

/** What this delegate actually did, in the reader's terms. */
function summarize(hop: DelegatedHop): string | undefined {
  const parts: string[] = [];
  if (hop.work.sql) parts.push("ran a query");
  if (hop.work.rows.length) {
    parts.push(`${hop.work.rows.length} row${hop.work.rows.length === 1 ? "" : "s"}`);
  }
  const guards = hop.work.guardReceipts.length;
  if (guards) parts.push(`${guards} guard receipt${guards === 1 ? "" : "s"}`);
  // Deliberately not "N frames": a frame count is not work, and reporting it as work
  // would make an idle hop look busy.
  return parts.length ? parts.join(" · ") : undefined;
}

export function DelegationTrail({
  hops,
  streaming = false,
}: {
  hops: DelegatedHop[];
  streaming?: boolean;
}) {
  if (!hops.length) return null;
  return (
    <ChainOfThought defaultOpen={false} className="my-1">
      <ChainOfThoughtHeader streaming={streaming}>
        {hops.length === 1
          ? `Delegated to ${hops[0].agentName}`
          : `Delegated to ${hops.length} agents`}
      </ChainOfThoughtHeader>
      <ChainOfThoughtContent>
        {hops.map(hop => (
          <ChainOfThoughtStep
            key={hop.agentPath}
            label={hop.agentName}
            // The chain of custody, shown only when there IS one: a hop delegated by
            // another agent is a different claim from one the conversation delegated,
            // and the path is the same value the runtime refuses cycles on.
            description={[
              hop.parentAgentId ? `via ${hop.agentPath}` : undefined,
              summarize(hop),
            ].filter(Boolean).join(" — ") || undefined}
            status="complete"
          />
        ))}
      </ChainOfThoughtContent>
    </ChainOfThought>
  );
}
