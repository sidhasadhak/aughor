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

function StepNode({ data }: { data: Record<string, unknown> }) {
  const status = String(data.status || "");
  const produced = (data.produced as string[]) || [];
  const accent = status ? (STATUS_COLOR[status] || "var(--t3)") : "var(--border)";
  return (
    <div style={{
      minWidth: 190, maxWidth: 210, borderRadius: 8, padding: "8px 10px",
      border: "1px solid var(--border)", borderLeft: `3px solid ${accent}`,
      background: "var(--bg2)",
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
        <div className="aug-fs-xs" style={{ color: accent, marginTop: 4 }}>● {status}</div>
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
      border: "1px dashed var(--border)", background: "var(--bg2)",
    }}>
      <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>when</div>
      <div className="aug-fs-sm" style={{ fontWeight: 600, marginTop: 1 }}>
        {String(data.detail || "manual")}
      </div>
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

  const edges: RFEdge[] = graph.edges.map((e, i) => {
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
      style: isData
        ? { stroke: "var(--chart-1)", strokeWidth: 1.6 }
        : { stroke: "var(--border)", strokeWidth: 1, strokeDasharray: "3 3" },
      markerEnd: { type: MarkerType.ArrowClosed,
                   color: isData ? "var(--chart-1)" : "var(--border)" },
      labelStyle: { fontSize: 10, fill: "var(--t3)" },
      data: { edgeType: e.type },
    };
  });

  return { nodes, edges };
}

export function AutomationGraph({ automationId }: { automationId: string }) {
  const [mode, setMode] = useState<"structure" | "execution">("structure");
  const [graph, setGraph] = useState<AutomationGraphData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    getAutomationGraph(automationId, mode === "execution" ? "latest" : "")
      .then((g) => { if (live) { setGraph(g); setError(""); } })
      .catch((e) => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [automationId, mode]);

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
            onClick={() => setMode(m)}
            className="aug-fs-xs"
            style={{
              padding: "2px 8px", borderRadius: 6, cursor: "pointer",
              border: "1px solid var(--border)",
              background: mode === m ? "var(--bg3)" : "transparent",
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
      </div>
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
  );
}

export default AutomationGraph;
