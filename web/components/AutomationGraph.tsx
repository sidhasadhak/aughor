"use client";

/**
 * VA-4b · the client half — an automation drawn as the graph it is.
 *
 * Until now this surface rendered `effects.map(describeEffect).join(", ")`: a
 * comma-joined sentence. The user's framing was exact — "what we have is a flow after the
 * run is done… what you see from VoltAgent is the whole workflow that gets designed by
 * the user."
 *
 * **The server owns the graph.** Nodes and edges come from `GET /automations/{id}/graph`,
 * derived from the same `collect_refs` the engine resolves against. This file lays out
 * and paints; it never infers an edge. Two readers deriving the graph differently is how
 * a picture and its run come to disagree, and a workflow view with decorative arrows is
 * worse than a list — a list at least does not claim.
 *
 * **Two edge kinds, drawn differently, because they mean different things.** A `data`
 * edge is a real `{"$from": …}` binding — output→input, labelled with the key it carries,
 * and the only reason a canvas beats a list. A `sequence` edge is just "runs after":
 * true, much weaker, and drawn faint and dashed so it never reads as a dependency the
 * engine does not have.
 *
 * **Structure and Execution are one graph, two readings** — the same toggle the user's
 * VoltAgent screenshot shows. Execution asks the server for the same graph decorated with
 * a run; it is never a second surface that could drift from the first.
 *
 * Layout is DETERMINISTIC, never simulated — the same automation opened twice looks
 * identical, which is what a design surface needs and a force cannot promise. Steps form
 * a left-to-right spine in the order they run, because that is the order they run in.
 * (Same reasoning, and the same library, as `agentops/TraceFlow.tsx`: `@xyflow/react` has
 * been in this app since #178 and drives three canvases.)
 */
import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { getAutomationGraph, type AutomationGraphData } from "@/lib/api";

export type { AutomationGraphData };

/** Status → colour. Mirrors the engine's vocabulary exactly; no status is invented here. */
const STATUS_COLOR: Record<string, string> = {
  executed: "var(--chart-2)",
  failed: "var(--red4)",
  dispatch_error: "var(--red4)",
  uncertain: "var(--chart-threshold-warn, #f59e0b)",
  approval_required: "var(--chart-threshold-warn, #f59e0b)",
  criterion_failed: "var(--chart-threshold-warn, #f59e0b)",
  invalid_params: "var(--red4)",
  skipped: "var(--t4)",
};

const COL_W = 250;

/** Durations read as durations, not as raw milliseconds. */
function ms(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 2)}s`;
  return `${Math.round(n)}ms`;
}

function StepNode({ data }: { data: Record<string, unknown> }) {
  const status = String(data.status || "");
  const produced = (data.produced as string[]) || [];
  const accent = status ? (STATUS_COLOR[status] || "var(--t3)") : "var(--border)";
  return (
    <div style={{
      minWidth: 190, maxWidth: 210, borderRadius: 8, padding: "8px 10px",
      border: "1px solid var(--border)", borderLeft: `3px solid ${accent}`,
      background: "var(--bg-2)",
    }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>{String(data.kind || "")}</div>
      <div className="aug-fs-sm" style={{ fontWeight: 600, marginTop: 1 }}>
        {String(data.label || "")}
      </div>
      {!!data.detail && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {String(data.detail)}
        </div>
      )}
      {!!status && (
        <div className="aug-fs-xs" style={{ color: accent, marginTop: 4 }}>
          ● {status}
          {typeof data.duration_ms === "number" && (data.duration_ms as number) > 0 && (
            <span style={{ color: "var(--t4)" }}> · {ms(data.duration_ms as number)}</span>
          )}
          {typeof data.attempts === "number" && (data.attempts as number) > 1 && (
            <span style={{ color: "var(--t4)" }}> · {String(data.attempts)} attempts</span>
          )}
        </div>
      )}
      {/* Whose work this step is. `delegated` distinguishes a step that named its own
          agent from one that simply inherited the automation's — the difference between
          "this agent acts throughout" and "this one part was handed off". */}
      {!!data.agent_id && (
        <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 3 }}>
          {data.delegated ? "delegated to " : "as "}{String(data.agent_id)}
        </div>
      )}
      {/* What this step PRODUCED. It is what makes a data edge checkable by eye: the key
          an edge claims to carry is either listed here or the edge is lying. */}
      {produced.length > 0 && (
        <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 3 }}>
          gives {produced.join(" · ")}
        </div>
      )}
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

function TriggerNode({ data }: { data: Record<string, unknown> }) {
  return (
    <div style={{
      minWidth: 170, maxWidth: 210, borderRadius: 8, padding: "8px 10px",
      border: "1px dashed var(--border)", background: "var(--bg-2)",
    }}>
      <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>when</div>
      <div className="aug-fs-sm" style={{ fontWeight: 600, marginTop: 1 }}>
        {String(data.detail || "manual")}
      </div>
      {/* On a run, a trigger that shows only what it WATCHES is a design element in a
          view meant to show what happened. */}
      {Array.isArray(data.fired) && (data.fired as string[]).length > 0 && (
        <div className="aug-fs-xs" style={{ color: "var(--chart-2)", marginTop: 3 }}>
          fired · {(data.fired as string[]).join(", ")}
        </div>
      )}
      {!!data.at && (
        <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 2 }}>
          {String(data.at).replace("T", " ").slice(0, 19)}
          {typeof data.duration_ms === "number" && (data.duration_ms as number) > 0
            ? ` · ${ms(data.duration_ms as number)}` : ""}
        </div>
      )}
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const NODE_TYPES = { step: StepNode, trigger: TriggerNode };

/**
 * Nodes and edges in ReactFlow's shape.
 *
 * Exported and pure so it can be asserted directly: ReactFlow measures its container
 * before drawing an edge and jsdom reports every element as 0×0, so a test that asserts
 * on RENDERED edges cannot fail — `TraceFlow.test.tsx` proved that by suppressing every
 * edge and watching 260 tests stay green. The assertion belongs on this handoff.
 */
export function toFlow(graph: AutomationGraphData): { nodes: RFNode[]; edges: RFEdge[] } {
  const nodes: RFNode[] = graph.nodes.map((n, i) => ({
    id: n.id,
    type: n.type === "trigger" ? "trigger" : "step",
    position: { x: i * COL_W, y: 0 },
    data: { ...n },
  }));

  // A data edge already implies "runs after" — you cannot consume what has not run — so a
  // sequence edge between the same pair is the same claim twice, drawn on an IDENTICAL
  // path. Measured in the browser: both `open->reply` edges rendered `M443,36 C470,36
  // 470,36 497,36`, the dashed one hidden under the solid one. Keep the edge that carries
  // meaning; drop the one that repeats it.
  const carriesData = new Set(
    graph.edges.filter((e) => e.type === "data").map((e) => `${e.from}->${e.to}`),
  );
  const drawn = graph.edges.filter(
    (e) => e.type !== "sequence" || !carriesData.has(`${e.from}->${e.to}`),
  );

  const edges: RFEdge[] = drawn.map((e, i) => {
    const isData = e.type === "data";
    return {
      id: `${e.type}:${e.from}->${e.to}:${e.label || i}`,
      source: e.from,
      target: e.to,
      label: isData ? e.label : undefined,
      animated: false,
      // A data edge carries a value and is drawn as the primary relation. A sequence
      // edge is faint and dashed: it means only "runs after", and a picture that draws
      // both alike teaches a dependency the engine does not have.
      // `--t4`, not `--border`: measured in the browser, `--border` is #232f39 against a
      // dark pane and the trigger's edge read as absent — a first step that looks
      // unconnected to its own trigger. Muted, but visible.
      style: isData
        ? { stroke: "var(--chart-1)", strokeWidth: 1.6 }
        : { stroke: "var(--t4)", strokeWidth: 1, strokeDasharray: "3 3" },
      markerEnd: { type: MarkerType.ArrowClosed,
                   color: isData ? "var(--chart-1)" : "var(--t4)" },
      // No `labelStyle`: it takes a style object, so any size here is a raw font-size
      // literal, and the design-token gate ratchets those. ReactFlow's own stylesheet
      // (imported above) already sizes `.react-flow__edge-text`, so the label is styled
      // by the design system's rules rather than by a number smuggled past them.
      data: { edgeType: e.type },
    };
  });

  return { nodes, edges };
}

export function AutomationGraph({ automationId }: { automationId: string }) {
  const [mode, setMode] = useState<"structure" | "execution">("structure");
  // "" = the latest run. A specific id pins the canvas to THAT run, which is what makes
  // the rail a rail rather than a list of links to somewhere else.
  const [runId, setRunId] = useState("");
  const [graph, setGraph] = useState<AutomationGraphData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    const which = mode === "execution" ? (runId || "latest") : "";
    getAutomationGraph(automationId, which)
      .then((g) => { if (live) { setGraph(g); setError(""); } })
      .catch((e) => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [automationId, mode, runId]);

  const flow = useMemo(() => (graph ? toFlow(graph) : { nodes: [], edges: [] }), [graph]);

  if (error) {
    return <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Could not load the graph: {error}</div>;
  }
  if (!graph) {
    return <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Loading…</div>;
  }

  return (
    <div style={{ height: "100%", minHeight: 260, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, paddingBottom: 6 }}>
        {(["structure", "execution"] as const).map((m) => (
          <button
            key={m}
            onClick={() => { setMode(m); if (m === "structure") setRunId(""); }}
            className="aug-fs-xs"
            style={{
              padding: "2px 8px", borderRadius: 6, cursor: "pointer",
              border: "1px solid var(--border)",
              background: mode === m ? "var(--bg-3)" : "transparent",
              color: mode === m ? "var(--t1)" : "var(--t3)",
            }}
          >
            {m === "structure" ? "Structure" : "Execution"}
          </button>
        ))}
        {/* Said plainly rather than shown as an empty Execution view: the automation has
            simply never run, and its structure is what is on screen. */}
        {graph.run_missing && (
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            never run — showing the design
          </span>
        )}
        {/* A `not_fired` or `gated` tick decorates nothing, so without this the Execution
            view is indistinguishable from Structure and the viewer cannot tell whether
            the run did nothing or the view is broken. The engine's own reason, verbatim. */}
        {mode === "execution" && !graph.run_missing && graph.run_outcome
          && graph.run_outcome !== "fired" && (
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            last run {graph.run_outcome}
            {graph.run_reason ? ` — ${graph.run_reason}` : ""}
          </span>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 220, display: "flex", gap: 8 }}>
      {mode === "execution" && (graph.runs?.length ?? 0) > 0 && (
        <div style={{ width: 132, flexShrink: 0, overflowY: "auto",
                      border: "1px solid var(--border)", borderRadius: 8, padding: 4 }}>
          <div className="aug-fs-xs" style={{ color: "var(--t4)", padding: "2px 4px 4px" }}>
            runs
          </div>
          {(graph.runs ?? []).map((r) => {
            const active = (runId || graph.run_id) === r.id;
            return (
              <button
                key={r.id}
                onClick={() => setRunId(r.id)}
                className="aug-fs-xs"
                style={{
                  display: "block", width: "100%", textAlign: "left", cursor: "pointer",
                  padding: "3px 5px", borderRadius: 5, marginBottom: 2,
                  border: "1px solid " + (active ? "var(--border)" : "transparent"),
                  background: active ? "var(--bg-3)" : "transparent",
                  color: active ? "var(--t1)" : "var(--t3)",
                }}
              >
                <div>{r.at ? r.at.replace("T", " ").slice(5, 16) : r.id.slice(0, 8)}</div>
                <div style={{ color: r.failed > 0 ? "var(--red4)" : "var(--t4)" }}>
                  {r.outcome}{r.failed > 0 ? ` · ${r.failed} failed` : ""}
                </div>
              </button>
            );
          })}
        </div>
      )}
      <div style={{ flex: 1, minHeight: 220, border: "1px solid var(--border)",
                    borderRadius: 8, overflow: "hidden" }}>
        <ReactFlow
          nodes={flow.nodes}
          edges={flow.edges}
          nodeTypes={NODE_TYPES}
          fitView
          fitViewOptions={{ minZoom: 0.5, maxZoom: 1, padding: 0.16 }}
          nodesDraggable={false}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} color="var(--border)" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      </div>
    </div>
  );
}

export default AutomationGraph;
