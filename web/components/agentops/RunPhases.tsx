"use client";

/**
 * CR5 → B1 → the Overview — one deep run's phases: the FIXED topology (flag-gated variants resolved server-side), the
 * phases the checkpoint recorded, and the gate a paused run waits at, resumable through its native surface.
 *
 * The list of deep runs this used to carry beside the detail is the Overview's "Deep runs" card now
 * (`DeepRuns.tsx`), titled by each run's question; a row there opens this, with the run's trace beside it.
 * It was Agent Ops ▸ Activity ▸ Phases until that tab folded into the Overview (2026-10-13), and before that the
 * phase half of the retired Runs layer — the half with no second home.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/brief/StatusChip";
import { Loading, ReadFailed } from "@/components/ui/states";
import { getInvestigationGraph, type InvestigationGraph } from "@/lib/api";
import { withUniqueKeys } from "@/lib/listKeys";

const PHASE_HUE: Record<string, "positive" | "negative" | "caution" | "muted"> = {
  complete: "positive", partial: "caution", skipped: "muted", error: "negative",
};

// Readable phase names for the graph node ids the backend returns in `topology`.
// The IDS are the backend's (`aughor/agent/graph.py` compile order) and are frozen —
// this maps them at RENDER only, so a node the map doesn't know still renders as its
// raw id rather than disappearing. Covers all three branches (deep / explore / direct)
// including the flag-gated parallel variants.
const NODE_LABEL: Record<string, string> = {
  // shared entry
  route_question: "Routing",
  // deep-analysis branch
  exploratory_scan: "Exploration scan",
  ada_intake: "Intake",
  clarify_gate: "Clarify gate",
  ada_cross_section: "Cross-section",
  ada_cross_section_multilens: "Cross-section (parallel lenses)",
  ada_phase_wave: "Baseline · Decomposition · Dimensional (parallel)",
  ada_baseline: "Baseline",
  ada_decompose: "Decomposition",
  ada_dimensional: "Dimensional",
  ada_behavioral: "Behavioral",
  ada_synthesize: "Synthesis",
  // survey (explore) branch
  exploratory_scan_explore: "Exploration scan",
  decompose_exploration: "Sub-question plan",
  plan_gate: "Plan gate",
  plan_and_execute_subq: "Sub-questions",
  plan_and_execute_wave: "Sub-questions (parallel)",
  synthesize_exploration: "Synthesis",
  // quick (direct) branch
  plan_queries: "Query plan",
  execute_planned_queries: "Query execution",
  score_evidence: "Evidence scoring",
  replan: "Replan",
  synthesize: "Synthesis",
};

/** Display name for a graph node — falls back to the raw backend id. */
function nodeLabel(node: string): string {
  return NODE_LABEL[node] ?? node;
}

/** One deep run's phases. `onResume` opens the run where a paused one is resumed. */
export function RunPhases({ runId, onResume }: {
  runId: string;
  onResume?: (runId: string) => void;
}) {
  const [graph, setGraph] = useState<InvestigationGraph | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A failed read says so with a Retry; it used to fall back to "Select a deep run", which read as nothing to show.
  const load = useCallback(() => {
    setError(null);
    getInvestigationGraph(runId)
      .then(g => { setGraph(g); setMissing(g === null); })
      .catch(e => { setGraph(null); setError(String(e?.message || e)); });
  }, [runId]);
  useEffect(() => { load(); }, [load]);

  if (error) return <ReadFailed what="this run's phases" error={error} onRetry={load} />;
  if (missing) return <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>No phase record for this run.</div>;
  if (!graph) return <Loading what="its phases" />;

  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--t2)", marginBottom: 12 }}>
        status {graph.status} · branch {graph.branch}
        {graph.checkpoint.exists
          ? ` · checkpoint step ${graph.checkpoint.step ?? "?"}${
            graph.checkpoint.last_writers.length
              ? ` · last wrote: ${graph.checkpoint.last_writers.join(", ")}` : ""}`
          : " · no checkpoint recorded"}
      </div>

      {graph.topology.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center",
          gap: 4, marginBottom: 14 }}>
          {graph.topology.map((node, i) => {
            const atGate = graph.interrupt.paused && graph.interrupt.gate === node;
            return (
              <span key={node} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                {i > 0 && <span style={{ color: "var(--t2)", fontSize: 11 }}>→</span>}
                <span style={{ fontSize: 11, padding: "3px 7px",
                  borderRadius: "var(--r2)",
                  border: `1px solid ${atGate ? "var(--amb3)" : "var(--b1)"}`,
                  background: atGate ? "var(--amb1)" : "var(--bg-1)",
                  color: atGate ? "var(--amb5)" : "var(--t2)" }}
                  title={atGate
                    ? `${node} — paused at this gate (derived from state markers)`
                    : node}>
                  {nodeLabel(node)}{atGate ? " ⏸" : ""}
                </span>
              </span>
            );
          })}
        </div>
      )}

      {graph.phases.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {/* `phase_id` names the phase's KIND — a run can hold two of one kind. */}
          {withUniqueKeys(graph.phases, p => p.phase_id).map(([key, p]) => (
            <div key={key} style={{ display: "flex", alignItems: "center",
              gap: 8, fontSize: 12 }}>
              <StatusChip hue={PHASE_HUE[p.status] ?? "muted"} strength="soft">
                {p.status}
              </StatusChip>
              <span style={{ fontWeight: 500 }}>{p.phase_name}</span>
              <span style={{ color: "var(--t3)", flex: 1, minWidth: 0,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {p.summary || p.skipped_reason || ""}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: "var(--t3)" }}>
          {graph.checkpoint.exists
            ? "No phases recorded yet."
            : "This run left no checkpoint — its phase history is not reconstructible."}
        </div>
      )}

      {graph.interrupt.paused && (
        <div style={{ marginTop: 14, padding: 10, background: "var(--amb1)",
          border: "1px solid var(--amb2)", borderRadius: "var(--r2)",
          display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 12, color: "var(--amb5)", flex: 1 }}>
            Paused at{" "}
            <code style={{ fontSize: 11 }} title={graph.interrupt.gate ?? undefined}>
              {nodeLabel(graph.interrupt.gate ?? "")}
            </code> —
            resume with feedback from the Agent view.
          </span>
          {onResume && (
            <Button variant="secondary" size="xs" onClick={() => onResume(runId)}>
              Open & resume
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
