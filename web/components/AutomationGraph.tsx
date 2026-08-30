"use client";

/**
 * VA-4b/VA-12/B1 · the automation canvas — Design you can touch, Execution you can trust.
 *
 * Two modes, two authorities, on one canvas:
 *
 * **Design** draws the DRAFT — the one deliberate departure from "the server owns the
 * graph": an editor that cannot show your unsaved edit is not an editor. Nodes drag
 * freely, primary fields edit in place, and the ports are the server's own vocabulary
 * drawn as dots (`/automations/vocabulary`, the same `PUBLISHED_KEYS` that
 * `validate_chain` refuses against). Dragging an output dot onto an input dot WRITES a
 * `{"$from": "alias.key"}` binding into the draft; the edge is the binding, not a
 * picture of one. What the canvas refuses at drag time and what the server refuses at
 * save are the same law (`applyConnect` mirrors `validate_chain`), so the canvas never
 * teaches a rule the engine does not have. This is B1: the unknown KEY that used to
 * surface at 09:00 as a skipped step now cannot be drawn, typed, or saved.
 *
 * **Execution** stays exactly what VA-4b built: the SERVER's graph, decorated with a
 * run, read-only. A run is evidence; nothing on it is editable and nothing about it is
 * derived client-side.
 *
 * The look leans on the frames the user pointed at (Langflow's component anatomy,
 * VoltAgent's Execution/Structure toggle) — visible left/right port dots, labeled
 * output rows, free drag — built on `@xyflow/react`, the library already driving four
 * canvases here. Design investment, not adoption.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  type Connection as RFConnection,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { AutomationAuthor, type Draft } from "@/components/automations/AutomationAuthor";
import { EFFECT_KINDS } from "@/components/automations/AutomationRows";
import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import {
  getAutomationGraph, getAutomationVocabulary,
  type Automation, type AutomationGraphData,
} from "@/lib/api";
import {
  aliasFor, applyConnect, clearBinding, draftToFlow, type Vocabulary,
} from "@/lib/automationFlow";

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

const KIND_ICON: Record<string, IconName> = {
  investigate: "search", slack_post: "send", notify: "bell",
  brief: "brief", kinetic_action: "bolt", monitor: "activity", agent_alert: "alert",
};

const COL_W = 300;

/** Durations read as durations, not as raw milliseconds. */
function ms(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 2)}s`;
  return `${Math.round(n)}ms`;
}

/* ═══════════════════ EXECUTION MODE (server graph, read-only) ═══════════════════ */

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
      {!!data.agent_id && (
        <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 3 }}>
          {data.delegated ? "delegated to " : "as "}{String(data.agent_id)}
        </div>
      )}
      {/* What this step PRODUCED — the run's own answer to the design's `gives`. */}
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

/**
 * Server graph → ReactFlow, for EXECUTION. Exported and pure so it stays asserted on
 * the handoff (jsdom draws zero edges no matter what it is given).
 */
export function toFlow(graph: AutomationGraphData): { nodes: RFNode[]; edges: RFEdge[] } {
  const nodes: RFNode[] = graph.nodes.map((n, i) => ({
    id: n.id,
    type: n.type === "trigger" ? "trigger" : "step",
    position: { x: i * 250, y: 0 },
    data: { ...n },
  }));

  // A data edge already implies "runs after", so a sequence edge on the same pair is
  // the same claim twice on an identical path — keep the one that carries meaning.
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
      style: isData
        ? { stroke: "var(--chart-1)", strokeWidth: 1.6 }
        : { stroke: "var(--t4)", strokeWidth: 1, strokeDasharray: "3 3" },
      markerEnd: { type: MarkerType.ArrowClosed,
                   color: isData ? "var(--chart-1)" : "var(--t4)" },
      data: { edgeType: e.type },
    };
  });

  return { nodes, edges };
}

/* ═══════════════════ DESIGN MODE (the draft, editable) ═══════════════════ */

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "4px 8px", borderRadius: "var(--r2)",
  border: "1px solid var(--b1)", background: "var(--bg-1)", color: "var(--t1)",
};

/** One port dot. Output dots are green ("gives"), input dots blue; a bound input fills. */
const PORT = 9;
const portStyle = (kind: "in" | "out", bound: boolean): React.CSSProperties => ({
  width: PORT, height: PORT, borderRadius: "var(--r-pill)",
  background: bound ? "var(--chart-1)" : "var(--bg-1)",
  border: `2px solid ${kind === "out" ? "var(--chart-2)" : "var(--chart-1)"}`,
});

interface DesignNodeData {
  alias: string;
  kind: string;
  config: Record<string, unknown>;
  publishes: string[];
  openSet: boolean;
  inputs: { field: string; boundTo: string | null }[];
  onPatch: (field: string, value: unknown) => void;
  onClear: (field: string) => void;
  [key: string]: unknown;
}

/** The primary editable fields per kind — the ones a person actually authors on the
 *  node. Everything else stays on the rail; a node holding every field is a form
 *  wearing a node costume. */
const PRIMARY_FIELDS: Record<string, { field: string; placeholder: string }[]> = {
  investigate:    [{ field: "question", placeholder: "what should the agent ask?" }],
  slack_post:     [{ field: "channel", placeholder: "#channel" },
                   { field: "message", placeholder: "message — or drag a port here" }],
  notify:         [{ field: "trigger_id", placeholder: "notification trigger id" },
                   { field: "message", placeholder: "message — or drag a port here" }],
  brief:          [{ field: "subscription_id", placeholder: "briefing subscription id" }],
  kinetic_action: [{ field: "action_id", placeholder: "declared action id" }],
};

function DesignStepNode({ data }: { data: DesignNodeData }) {
  const boundOf = (field: string) =>
    data.inputs.find(i => i.field === field)?.boundTo ?? null;
  const bindableSet = new Set(data.inputs.map(i => i.field));
  const fields = PRIMARY_FIELDS[data.kind] ?? [];
  const kindLabel = EFFECT_KINDS.find(k => k.value === data.kind)?.label ?? data.kind;

  return (
    <div style={{
      width: COL_W - 40, borderRadius: 8, background: "var(--bg-2)",
      border: "1px solid var(--b2)", boxShadow: "var(--shadow-sm)",
    }}>
      {/* The unnamed target handle SEQUENCE edges land on. Named `in:` handles carry
          bindings; an edge with no targetHandle attaches to the default handle, and a
          node without one silently drops the edge — measured: the trigger's spine edge
          vanished while every port rendered. Hidden: it is geometry, not a port. */}
      <Handle type="target" position={Position.Left} style={{ opacity: 0, top: 16 }} />
      {/* header — Langflow anatomy: icon · kind · the alias other steps bind BY */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 10px",
        borderBottom: "1px solid var(--b1)" }}>
        <span style={{ color: "var(--chart-1)", display: "flex" }}>
          <Icon name={KIND_ICON[data.kind] ?? "process"} size={13} />
        </span>
        <span className="aug-fs-sm" style={{ fontWeight: 600 }}>{kindLabel}</span>
        <span className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--t3)",
          border: "1px solid var(--b1)", borderRadius: "var(--r-pill)", padding: "0 7px" }}>
          {data.alias}
        </span>
      </div>

      {/* editable fields; a bound field renders its BINDING, with its input port dot */}
      <div style={{ padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
        {fields.map(({ field, placeholder }) => {
          const bound = boundOf(field);
          const bindable = bindableSet.has(field);
          return (
            <div key={field} style={{ position: "relative" }}>
              <div className="aug-fs-xs" style={{ color: "var(--t4)", marginBottom: 2 }}>
                {field}
              </div>
              {bindable && (
                <Handle
                  id={`in:${field}`} type="target" position={Position.Left}
                  style={{ ...portStyle("in", !!bound), left: -15,
                           top: "50%", transform: "translateY(-30%)" }}
                  title={`bind '${field}' — drag from an output port`}
                />
              )}
              {bound ? (
                <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center",
                  gap: 6, padding: "4px 8px", borderRadius: "var(--r2)",
                  border: "1px solid var(--chart-1)", background: "var(--bg-1)",
                  color: "var(--chart-1)" }}>
                  <Icon name="link" size={11} />
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap" }}>{bound}</span>
                  <Button variant="ghost" size="icon-sm" aria-label={`unbind ${field}`}
                    className="nodrag" style={{ marginLeft: "auto", width: 18, height: 18 }}
                    onClick={() => data.onClear(field)}>
                    <Icon name="close" size={10} />
                  </Button>
                </div>
              ) : (
                <input
                  className="nodrag aug-fs-xs"
                  style={inputStyle}
                  placeholder={placeholder}
                  value={String(data.config[field] ?? "")}
                  onChange={e => data.onPatch(field, e.target.value)}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* output ports — "gives X", each a real source dot. The design's promise; the
          Execution node's `produced` is the run's answer to it. */}
      {data.publishes.length > 0 && (
        <div style={{ borderTop: "1px solid var(--b1)", padding: "5px 10px 7px" }}>
          {data.publishes.map(key => (
            <div key={key} style={{ position: "relative", display: "flex",
              justifyContent: "flex-end", padding: "2px 0" }}>
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                gives <span style={{ color: "var(--chart-2)" }}>
                  {data.openSet ? "the action's outcome" : key}</span>
              </span>
              <Handle
                id={`out:${key}`} type="source" position={Position.Right}
                style={{ ...portStyle("out", false), right: -15,
                         top: "50%", transform: "translateY(-50%)" }}
                title={data.openSet ? "drag to bind (key asked on drop)" : `drag '${key}' onto an input port`}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DesignTriggerNode({ data }: { data: { detail: string } }) {
  return (
    <div style={{
      minWidth: 170, maxWidth: 230, borderRadius: 8, padding: "8px 10px",
      border: "1px dashed var(--b2)", background: "var(--bg-2)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ color: "var(--chart-3)", display: "flex" }}>
          <Icon name="bolt" size={13} />
        </span>
        <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>when</span>
      </div>
      <div className="aug-fs-sm" style={{ fontWeight: 600, marginTop: 2 }}>
        {data.detail || "manual"}
      </div>
      <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 2 }}>
        edit triggers in the rail →
      </div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const NODE_TYPES = {
  step: StepNode, trigger: TriggerNode,
  designStep: DesignStepNode, designTrigger: DesignTriggerNode,
};

function describeConditions(draft: Draft): string {
  return draft.conditions.map(c => {
    if (c.kind === "schedule") return `schedule · ${c.config.cron ?? ""}`;
    if (c.kind === "metric") return `monitor ${c.config.monitor_id ?? ""}`;
    return `${c.kind} · ${c.config.table ?? ""}`;
  }).join("  +  ");
}

/* ═══════════════════ the component ═══════════════════ */

export function AutomationGraph({ automationId, automation, onSaved }: {
  automationId: string;
  /** The record itself. Present ⇒ Design mode is AUTHORABLE. Absent ⇒ read-only. */
  automation?: Automation;
  onSaved?: () => void;
}) {
  const [mode, setMode] = useState<"design" | "execution">("design");
  const [runId, setRunId] = useState("");
  const [graph, setGraph] = useState<AutomationGraphData | null>(null);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  /** Drag-time refusals — `applyConnect`'s sentence, shown then cleared. */
  const [connectError, setConnectError] = useState("");
  const [vocab, setVocab] = useState<Vocabulary | null>(null);

  const [draft, setDraft] = useState<Draft>(() => ({
    conditions: automation?.conditions ?? [], effects: automation?.effects ?? [],
  }));
  useEffect(() => {
    if (automation) setDraft({ conditions: automation.conditions, effects: automation.effects });
  }, [automation]);

  useEffect(() => {
    getAutomationVocabulary().then(setVocab).catch(() => setVocab({}));
  }, []);

  const authoring = !!automation && mode === "design";

  // The EXECUTION graph stays the server's; fetched only when that mode is on screen.
  useEffect(() => {
    if (mode !== "execution") return;
    let live = true;
    getAutomationGraph(automationId, runId || "latest")
      .then((g) => { if (live) { setGraph(g); setError(""); } })
      .catch((e) => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [automationId, mode, runId, reloadKey]);

  /* ── design-mode graph, drawn from the draft ── */
  // Positions survive dragging but reset per automation — session-local by design:
  // a stored layout is a second copy of the chain's order that could drift from it.
  const positions = useRef(new Map<string, { x: number; y: number }>());
  useEffect(() => { positions.current.clear(); }, [automationId]);

  const patchField = useCallback((alias: string, field: string, value: unknown) => {
    setDraft(d => ({
      ...d,
      effects: d.effects.map((e, i) =>
        aliasFor(e, i) === alias ? { ...e, config: { ...e.config, [field]: value } } : e),
    }));
  }, []);

  const clearField = useCallback((alias: string, field: string) => {
    setDraft(d => clearBinding(d, alias, field));
  }, []);

  const design = useMemo(() => {
    if (!vocab) return { nodes: [] as RFNode[], edges: [] as RFEdge[] };
    const { steps, edges } = draftToFlow(draft, vocab);
    const nodes: RFNode[] = [{
      id: "__trigger",
      type: "designTrigger",
      position: positions.current.get("__trigger") ?? { x: 0, y: 40 },
      data: { detail: describeConditions(draft) },
    }, ...steps.map((s, i) => ({
      id: s.alias,
      type: "designStep" as const,
      position: positions.current.get(s.alias) ?? { x: (i + 1) * COL_W, y: 0 },
      data: {
        ...s,
        onPatch: (field: string, value: unknown) => patchField(s.alias, field, value),
        onClear: (field: string) => clearField(s.alias, field),
      } as DesignNodeData,
    }))];
    const rfEdges: RFEdge[] = [
      // the faint "runs after" spine, trigger → first step (order itself is the rail's)
      ...(steps.length ? [{
        id: "__seq:trigger", source: "__trigger", target: steps[0].alias,
        style: { stroke: "var(--t4)", strokeWidth: 1, strokeDasharray: "3 3" },
        markerEnd: { type: MarkerType.ArrowClosed, color: "var(--t4)" },
      }] : []),
      ...edges.map(e => ({
        id: `bind:${e.from}.${e.key}->${e.to}.${e.field}`,
        source: e.from,
        sourceHandle: `out:${e.key}`,
        target: e.to,
        targetHandle: `in:${e.field}`,
        label: e.key,
        style: { stroke: "var(--chart-1)", strokeWidth: 1.6 },
        labelStyle: { fill: "var(--t2)" },
        labelBgStyle: { fill: "var(--bg-1)" },
        markerEnd: { type: MarkerType.ArrowClosed, color: "var(--chart-1)" },
      })),
    ];
    return { nodes, edges: rfEdges };
  }, [draft, vocab, patchField, clearField]);

  /** Edges are handed over ONE FRAME after the nodes that carry their handles.
   *  ReactFlow drops an edge whose named handle is not yet registered, and on the
   *  first paint after the vocabulary arrives, nodes and edges land in the same
   *  render — measured: every edge missing until a mode toggle remounted the canvas.
   *  A frame later the handles exist and the same edges draw. */
  const [edgesLive, setEdgesLive] = useState(false);
  useEffect(() => {
    setEdgesLive(false);
    const frame = requestAnimationFrame(() => setEdgesLive(true));
    return () => cancelAnimationFrame(frame);
  }, [design.nodes.length, mode]);

  const onConnect = useCallback((c: RFConnection) => {
    if (!vocab || !c.source || !c.target) return;
    const key = (c.sourceHandle ?? "").replace(/^out:/, "");
    const field = (c.targetHandle ?? "").replace(/^in:/, "");
    if (!key || !field) return;
    // The open-set port ("*") cannot know its key at drag time; ask for it. A prompt
    // is homely, but inventing a key silently would draw an edge the run then skips.
    const realKey = key === "*"
      ? (window.prompt("Which key of the action's outcome?") ?? "").trim()
      : key;
    if (!realKey) return;
    const r = applyConnect(draft, vocab, {
      fromAlias: c.source, key: realKey, toAlias: c.target, field,
    });
    if (r.error) {
      setConnectError(r.error);
      window.setTimeout(() => setConnectError(""), 3200);
      return;
    }
    setDraft(r.draft);
  }, [draft, vocab]);

  if (error && mode === "execution") {
    return <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Could not load the graph: {error}</div>;
  }

  const execution = mode === "execution" && graph ? toFlow(graph) : null;

  return (
    <div style={{ height: "100%", minHeight: 260, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, paddingBottom: 6 }}>
        <div style={{ display: "inline-flex", gap: 2, padding: 2,
          border: "1px solid var(--b1)", borderRadius: "var(--r-chip)",
          background: "var(--bg-1)" }}>
          {(["design", "execution"] as const).map((m) => (
            <Button key={m} variant={mode === m ? "secondary" : "ghost"} size="xs"
              onClick={() => { setMode(m); if (m === "design") setRunId(""); }}>
              {m === "design" ? "Design" : "Execution"}
            </Button>
          ))}
        </div>
        {mode === "design" && !connectError && (
          <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
            drag a <span style={{ color: "var(--chart-2)" }}>gives</span> dot onto an
            input dot to bind it · double-click an edge to unbind · nodes drag freely
          </span>
        )}
        {connectError && (
          <span className="aug-fs-xs" style={{ color: "var(--amb4)" }}>{connectError}</span>
        )}
        {mode === "execution" && graph?.run_missing && (
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            never run — showing the design
          </span>
        )}
        {mode === "execution" && graph && !graph.run_missing && graph.run_outcome
          && graph.run_outcome !== "fired" && (
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            last run {graph.run_outcome}
            {graph.run_reason ? ` — ${graph.run_reason}` : ""}
          </span>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 220, display: "flex", gap: 8 }}>
        {mode === "execution" && (graph?.runs?.length ?? 0) > 0 && (
          <div style={{ width: 132, flexShrink: 0, overflowY: "auto",
                        border: "1px solid var(--border)", borderRadius: 8, padding: 4 }}>
            <div className="aug-fs-xs" style={{ color: "var(--t4)", padding: "2px 4px 4px" }}>
              runs
            </div>
            {(graph?.runs ?? []).map((r) => {
              const active = (runId || graph?.run_id) === r.id;
              return (
                <Button key={r.id} variant="ghost" size="sm" className="aug-fs-xs"
                  onClick={() => setRunId(r.id)}
                  style={{
                    display: "block", width: "100%", height: "auto", textAlign: "left",
                    padding: "3px 5px", marginBottom: 2,
                    background: active ? "var(--bg-3)" : "transparent",
                    color: active ? "var(--t1)" : "var(--t3)",
                  }}>
                  <div>{r.at ? r.at.replace("T", " ").slice(5, 16) : r.id.slice(0, 8)}</div>
                  <div style={{ color: r.failed > 0 ? "var(--red4)" : "var(--t4)" }}>
                    {r.outcome}{r.failed > 0 ? ` · ${r.failed} failed` : ""}
                  </div>
                </Button>
              );
            })}
          </div>
        )}

        <div style={{ flex: 1, minWidth: 0, minHeight: 220,
                      border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          {mode === "design" ? (
            <ReactFlow
              nodes={design.nodes}
              edges={edgesLive ? design.edges : []}
              nodeTypes={NODE_TYPES}
              onConnect={onConnect}
              onNodeDragStop={(_e, n) => positions.current.set(n.id, n.position)}
              onEdgeDoubleClick={(_e, edge) => {
                // the edge IS the binding — double-click removes both
                const m = /^bind:.*->(.+)\.([^.]+)$/.exec(edge.id);
                if (m) clearField(m[1], m[2]);
              }}
              fitView
              fitViewOptions={{ minZoom: 0.5, maxZoom: 1, padding: 0.16 }}
              nodesDraggable
              nodesConnectable
              proOptions={{ hideAttribution: true }}
              minZoom={0.3}
              maxZoom={1.6}
            >
              <Background gap={16} color="var(--border)" />
              <Controls showInteractive={false} />
            </ReactFlow>
          ) : !graph ? (
            <div className="aug-fs-sm" style={{ color: "var(--t3)", padding: 16 }}>Loading…</div>
          ) : (
            <ReactFlow
              nodes={execution!.nodes}
              edges={execution!.edges}
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
          )}
        </div>

        {authoring && (
          <AutomationAuthor
            automation={automation!}
            draft={draft}
            onDraft={setDraft}
            onSaved={() => { setReloadKey(k => k + 1); onSaved?.(); }}
          />
        )}
      </div>
    </div>
  );
}

export default AutomationGraph;
