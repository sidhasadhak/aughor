"use client";
/**
 * CI-6a — the converse body's tool trail, rendered as Chain-of-Thought steps.
 *
 * Each step is one tool the model CHOSE on this turn — a query run, a findings
 * lookup, the briefing read, a deep analysis launched. The trail is what makes the
 * conversation's texture visible: without it a converse turn reads as silence
 * followed by an answer, which is exactly the mechanical feel CI-0 measured.
 *
 * Mirrors GuardReceiptChain deliberately: same organ (the vendored ChainOfThought),
 * same "renders nothing when empty" contract, same label philosophy — the backend
 * names the mechanism, the surface names what the reader gains, and an unknown tool
 * falls back to its raw id so a new roster entry is visible before this map learns
 * its nice name.
 */
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import type { ConverseStep } from "@/lib/chatTurn";

/** What the reader gains from each tool, per roster id. */
const TOOL_LABEL: Record<string, string> = {
  answer_question: "Ran the governed answer pipeline",
  run_sql: "Ran a query through the guard battery",
  list_tables: "Read the schema manifest",
  describe_table: "Inspected a table's columns",
  deep_analysis: "Launched an Agent run",
  search_graph: "Searched the knowledge graph",
  describe_entity: "Read what's known about an entity",
  list_findings: "Read the stored findings",
  get_briefing: "Read the executive briefing",
  get_table_health: "Checked a table's data quality",
  list_trusted_queries: "Read the verified query patterns",
  list_monitors: "Checked monitors and alerts",
  list_packs: "Checked the specialist packs",
  platform_help: "Consulted the platform guide",
};

function truncate(s: string, n = 110): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export function ToolTrail({
  steps,
  streaming = false,
}: {
  steps: ConverseStep[];
  streaming?: boolean;
}) {
  if (!steps.length) return null;
  return (
    <ChainOfThought defaultOpen={false} className="my-1">
      <ChainOfThoughtHeader streaming={streaming}>
        {steps.length === 1 ? "1 step taken" : `${steps.length} steps taken`}
      </ChainOfThoughtHeader>
      <ChainOfThoughtContent>
        {steps.map((s, i) => (
          <ChainOfThoughtStep
            key={`${s.tool}-${s.index}-${i}`}
            label={TOOL_LABEL[s.tool] ?? s.tool}
            description={
              s.ok
                ? (s.detail ? truncate(s.detail) : undefined)
                : `failed${s.detail ? ` — ${truncate(s.detail)}` : ""} (the model saw this and can recover)`
            }
            status="complete"
            icon={
              s.ok ? undefined : (
                <span
                  className="block h-1.5 w-1.5 rounded-[var(--r-pill)]"
                  style={{ background: "var(--red4)" }}
                />
              )
            }
          />
        ))}
      </ChainOfThoughtContent>
    </ChainOfThought>
  );
}
