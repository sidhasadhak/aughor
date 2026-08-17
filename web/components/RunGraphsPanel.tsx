"use client";

/**
 * CR5 — two honest run graphs, and deliberately no DAG editor (the Effect law
 * is a feature):
 *
 * (a) the automation run strip — conditions evaluated → per-effect outcomes,
 *     straight from `automation_runs`. A run that did nothing renders as
 *     "evaluated, did not fire" WITH ITS REASON; effect messages (authored
 *     refusals included) render verbatim, never paraphrased.
 * (b) the deep-run phase view — the FIXED topology (flag-gated variants
 *     resolved server-side), the phases the checkpoint recorded, and the gate
 *     a paused run waits at, resumable through its native surface.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/brief/StatusChip";
import {
  getAllAutomationRuns, getInvestigationGraph, getInvestigationsList,
  type AutomationRun, type InvestigationGraph, type InvestigationListRow,
} from "@/lib/api";
import { fmtMs } from "@/lib/cost";
import { relTime } from "@/lib/format";

const OUTCOME_HUE: Record<string, "positive" | "negative" | "caution" | "info" | "muted"> = {
  fired: "positive", not_fired: "muted", gated: "caution", error: "negative",
};
const EFFECT_HUE: Record<string, "positive" | "negative" | "caution" | "muted"> = {
  executed: "positive", failed: "negative", approval_required: "caution",
  criterion_failed: "caution", skipped: "muted", invalid_params: "negative",
  dispatch_error: "negative",
};
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

export function RunGraphsPanel({ onOpenInvestigation }: {
  onOpenInvestigation?: (invId: string) => void;
}) {
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [invs, setInvs] = useState<InvestigationListRow[]>([]);
  const [selectedInv, setSelectedInv] = useState<string | null>(null);
  const [showTicks, setShowTicks] = useState(false);
  const [graph, setGraph] = useState<InvestigationGraph | null>(null);

  const load = useCallback(() => {
    getAllAutomationRuns({ limit: 50 }).then(setRuns).catch(() => {});
    getInvestigationsList(30)
      .then(rows => {
        const deep = rows.filter(r => r.kind === "investigation");
        setInvs(deep);
        setSelectedInv(prev => prev ?? deep[0]?.id ?? null);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 20_000);
    return () => clearInterval(iv);
  }, [load]);

  useEffect(() => {
    if (!selectedInv) { setGraph(null); return; }
    getInvestigationGraph(selectedInv).then(setGraph).catch(() => setGraph(null));
  }, [selectedInv]);

  // A run that FIRED gets its own card; the rest fold into one row per automation. The
  // split is on the outcome the engine recorded, never on a string in the reason.
  const firedRuns = useMemo(() => runs.filter(r => r.outcome !== "not_fired"), [runs]);
  const shownRuns = showTicks ? runs : firedRuns;
  const folded = useMemo(() => {
    if (showTicks) return [];
    const by = new Map<string, { id: string; name: string; ticks: number; lastAt: string | null }>();
    for (const r of runs) {
      if (r.outcome !== "not_fired") continue;
      const id = r.automation_id;
      const seen = by.get(id);
      if (seen) {
        seen.ticks += 1;
        if (!seen.lastAt || String(r.started_at) > seen.lastAt) seen.lastAt = r.started_at;
      } else {
        by.set(id, { id, name: r.automation_name || id, ticks: 1, lastAt: r.started_at });
      }
    }
    return [...by.values()].sort((a, b) => b.ticks - a.ticks);
  }, [runs, showTicks]);

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
      {/* ── (a) automation run strip ── */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 8 }}>
        <span className="aug-label" style={{ color: "var(--t2)" }}>
          Automation runs — conditions → effects
        </span>
        <span className="aug-fs-sm" style={{ color: "var(--t2)", marginRight: "auto" }}>
          {folded.length > 0
            ? `${folded.length} automation${folded.length === 1 ? "" : "s"} · `
              + `${runs.length - firedRuns.length} evaluated without firing, folded`
            : "the engine records one run per tick, including ticks that do nothing"}
        </span>
        <Button variant="ghost" size="xs" onClick={() => setShowTicks(v => !v)}
          style={{ color: "var(--blue4)" }}>
          {showTicks ? "fold quiet ticks" : "show every tick"}
        </Button>
      </div>

      {/* A tick that evaluated and fired nothing is not a run worth a card — the engine
          writes one per minute per automation, so the un-folded strip is a wall of
          "evaluated — did not fire" with the real firings buried in it. One row per
          automation carries the same facts; expanding it gives back every tick. */}
      {!showTicks && folded.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
          {folded.map(f => (
            <div key={f.id} style={{ display: "flex", alignItems: "center", gap: 10,
              background: "var(--bg-1)", border: "1px solid var(--b1)",
              borderRadius: "var(--r3)", padding: "8px 14px" }}>
              <StatusChip hue="muted" strength="soft">quiet</StatusChip>
              <span className="aug-fs-ui" style={{ fontWeight: 500 }}>{f.name}</span>
              <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>
                {f.ticks} tick{f.ticks === 1 ? "" : "s"} evaluated · none fired
                {f.lastAt ? ` · last ${relTime(f.lastAt)}` : ""}
              </span>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 28 }}>
        {runs.length === 0 ? (
          <div className="aug-fs-sm" style={{ padding: 20, color: "var(--t2)",
            background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)" }}>
            No automation runs yet. The engine records one run per tick — including
            ticks that evaluate and do nothing — for every automation you create.
          </div>
        ) : shownRuns.length === 0 ? (
          <div className="aug-fs-sm" style={{ padding: 20, color: "var(--t2)",
            background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)" }}>
            Every run in this window evaluated without firing — folded above. Nothing acted.
          </div>
        ) : shownRuns.map(run => (
          <div key={run.id} style={{ background: "var(--bg-2)", border: "1px solid var(--b1)",
            borderRadius: "var(--r3)", padding: "10px 14px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <StatusChip hue={OUTCOME_HUE[run.outcome] ?? "muted"} strength="soft">
                {run.outcome === "not_fired" ? "evaluated — did not fire" : run.outcome}
              </StatusChip>
              <span style={{ fontSize: 12, fontWeight: 500 }}>{run.automation_name || run.automation_id}</span>
              <span style={{ fontSize: 12, color: "var(--t2)" }}>
                {relTime(run.started_at)} · {fmtMs(run.duration_ms)}
              </span>
              {run.reason && (
                <span style={{ fontSize: 12, color: "var(--t3)", flex: 1, minWidth: 0,
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  title={run.reason}>
                  {run.reason}
                </span>
              )}
            </div>
            {run.conditions_fired.length > 0 && (
              <div style={{ fontSize: 12, color: "var(--t3)", marginTop: 6 }}>
                conditions fired: {run.conditions_fired.join(", ")}
              </div>
            )}
            {run.effects.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 6 }}>
                {run.effects.map((ef, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 8,
                    fontSize: 12, paddingLeft: 10, borderLeft: "2px solid var(--b1)" }}>
                    <StatusChip hue={EFFECT_HUE[ef.status] ?? "muted"} strength="soft">
                      {ef.status}
                    </StatusChip>
                    <span style={{ color: "var(--t2)" }}>{ef.kind}{ef.target ? ` → ${ef.target}` : ""}</span>
                    {ef.attempts > 1 && <span style={{ color: "var(--amb4)" }}>×{ef.attempts}</span>}
                    {/* the authored message, verbatim — never paraphrased */}
                    {ef.message && <span style={{ color: "var(--t3)" }}>{ef.message}</span>}
                  </div>
                ))}
              </div>
            )}
            {run.error && (
              <div style={{ fontSize: 12, color: "var(--red4)", marginTop: 6 }}>{run.error}</div>
            )}
          </div>
        ))}
      </div>

      {/* ── (b) deep-run phase view ── */}
      <div className="aug-label" style={{ color: "var(--t3)", marginBottom: 8 }}>
        Deep-run phases — the fixed deep analysis topology
      </div>
      <div style={{ display: "flex", gap: 12 }}>
        <div style={{ width: 260, flexShrink: 0 }}>
          {invs.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--t3)", padding: 12 }}>
              No deep runs yet — ask a &quot;why&quot; question to start one.
            </div>
          ) : invs.map(inv => (
            <Button key={inv.id} variant="ghost" size="sm"
              onClick={() => setSelectedInv(inv.id)}
              style={{ display: "block", width: "100%", height: "auto", textAlign: "left",
                padding: "7px 10px", marginBottom: 2, whiteSpace: "normal",
                background: selectedInv === inv.id ? "var(--bg-sel)" : undefined }}>
              <span style={{ display: "block", fontSize: 12, overflow: "hidden",
                textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{inv.question}</span>
              <span style={{ display: "block", fontSize: 12, color: "var(--t2)", marginTop: 2 }}>
                {inv.status}{inv.status === "paused" ? " — waiting on you" : ""} · {relTime(inv.started_at)}
              </span>
            </Button>
          ))}
        </div>
        <div style={{ flex: 1, background: "var(--bg-2)", border: "1px solid var(--b1)",
          borderRadius: "var(--r3)", padding: 16, minHeight: 180 }}>
          {!graph ? (
            <div style={{ fontSize: 12, color: "var(--t3)" }}>Select a deep run.</div>
          ) : (
            <>
              <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>{graph.question}</div>
              <div style={{ fontSize: 12, color: "var(--t2)", marginBottom: 12 }}>
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
                        {i > 0 && <span style={{ color: "var(--t2)", fontSize: 12 }}>→</span>}
                        <span style={{ fontSize: 12, padding: "3px 7px",
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
                  {graph.phases.map(p => (
                    <div key={p.phase_id} style={{ display: "flex", alignItems: "center",
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
                    <code style={{ fontSize: 12 }} title={graph.interrupt.gate ?? undefined}>
                      {nodeLabel(graph.interrupt.gate ?? "")}
                    </code> —
                    resume with feedback from the deep analysis view.
                  </span>
                  {onOpenInvestigation && (
                    <Button variant="secondary" size="xs"
                      onClick={() => onOpenInvestigation(graph.investigation_id)}>
                      Open & resume
                    </Button>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
