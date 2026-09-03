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
import { createContext, memo, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  type Connection as RFConnection,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  type NodeChange,
  type OnConnectEnd,
  Panel,
  Position,
  ReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import {
  blankDraft, DesignControls, StepInspector, updatePayload, type Draft,
} from "@/components/automations/AutomationAuthor";
import { DeployMenu } from "@/components/automations/DeployMenu";
import {
  AutomationPalette, PALETTE_DRAG_TYPE, readPaletteDrag,
  type PaletteGroup, type PalettePlacement,
} from "@/components/automations/AutomationPalette";
import {
  EFFECT_KINDS, newConditionOf, newEffectOf, useAutomationVocabulary,
} from "@/components/automations/AutomationRows";
import { OutcomeKeyPicker } from "@/components/automations/OutcomeKeyPicker";
import { canvasClipboard, copyToCanvasClipboard } from "@/lib/canvasClipboard";
import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import {
  dryRunAutomationDraft, getActivityEvents, getAutomationGraph, getAutomationLayout,
  getAutomationVocabulary, saveAutomationLayout,
  type Automation, type AutomationGraphData, type GuardClause,
} from "@/lib/api";
import {
  aliasFor, applyConnect, clearBinding, draftToFlow, ELSE_FIELD, FAN_FIELD, GUARD_FIELD,
  guardSentences, landPrebound, layoutToPersist, liveStatuses, pasteEffect,
  producedByAlias, rootAliases, viewportCenter, visibleFields,
  type EdgeDrop, type LiveStatus, type Vocabulary,
} from "@/lib/automationFlow";
import type { AutoCondition, AutoEffect } from "@/lib/api";
import {
  canRedo, canUndo, initHistory, pushHistory, redoHistory, resetHistory, undoHistory,
  type History, type PushOptions,
} from "@/lib/history";

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
  // DS-3 — in flight. Its own hue: a step still working is not a step that worked.
  running: "var(--chart-1)",
};

/** DS-3 — what a live span can honestly claim.
 *
 *  Measured on a real run: a step's `tool_call_result` comes back `ok: true` even when the
 *  step's OUTCOME was `dispatch_error`, because the span records that the work returned
 *  without raising — the verdict is decided after it closes. So a closed span means the
 *  step STARTED and FINISHED, not that it worked, and mapping it to `executed` would
 *  flash a green card over a message nobody received.
 *
 *  `ran` is therefore deliberately not one of the engine's outcome words: it has no colour
 *  in `STATUS_COLOR`, renders in the neutral fallback, and is replaced a moment later by
 *  the stored outcome when `build_graph` answers. The stream is the anticipation; the
 *  stored run is the truth. */
const LIVE_STATUS: Record<string, string> = {
  running: "running", done: "ran", failed: "failed",
};

const KIND_ICON: Record<string, IconName> = {
  investigate: "search", slack_post: "send", notify: "bell",
  brief: "brief", kinetic_action: "bolt", monitor: "activity", agent_alert: "alert",
  subchain: "layers",
  // DS-11 — the same glyph the palette row carries. A kind absent from this table falls
  // back to the generic "process" gear, which is how a new kind ends up looking like
  // scaffolding on the one surface built to make a chain read as roles.
  integration_call: "key",
  metric_value: "metric", trusted_query: "table",
};

const COL_W = 300;

/* ── DS-4 · the minimap ─────────────────────────────────────────────────────────
 *
 * `Controls` has been stock, un-tokenised xyflow chrome in all four canvases since the
 * first one shipped — there is not a single `.react-flow__*` override in this codebase.
 * A default-styled MiniMap would have been the second such thing on screen, and a bigger
 * one, so this one is tokened at every surface it exposes. It can be: `nodeColor` reaches
 * the rect through `style.fill` and `bgColor`/`maskColor` become CSS custom properties,
 * so `var(…)` resolves in all three (checked in the library, not assumed — a colour
 * passed as an SVG *attribute* would have silently rendered black).
 */

/** Below this, a minimap is chrome rather than help — and on a narrow pane it is chrome
 *  that costs canvas. A chain you can see all of does not need a map of itself. */
const MINIMAP_FROM = 5;

/**
 * A dot reads as the card it stands for: the kind's hue while designing, the run's status
 * while reading a run. Both come from the maps the cards themselves use, so a dot and its
 * node cannot come to disagree — which is the only way a minimap can actively mislead.
 */
function miniNodeColor(mode: "design" | "execution") {
  return (node: RFNode): string => {
    const data = (node.data ?? {}) as Record<string, unknown>;
    if (mode === "execution") {
      if (data.guarded) return "var(--chart-3)";
      const status = String(data.status || "");
      return status ? (STATUS_COLOR[status] || "var(--t4)") : "var(--t4)";
    }
    if (node.type === "designTrigger") return "var(--t3)";
    return KIND_HUE[String(data.kind ?? "")] ?? "var(--chart-6)";
  };
}

const MINIMAP_STYLE: React.CSSProperties = {
  width: 128, height: 88,
  border: "1px solid var(--b1)", borderRadius: "var(--r2)",
  // The default sits hard in the corner, overlapping the zoom controls on a short pane.
  marginRight: 8, marginBottom: 8,
};

/** Durations read as durations, not as raw milliseconds. */
function ms(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 2)}s`;
  return `${Math.round(n)}ms`;
}

/* ═══════════════════ EXECUTION MODE (server graph, read-only) ═══════════════════ */

function StepNode({ data }: { data: Record<string, unknown> }) {
  const status = String(data.status || "");
  const produced = (data.produced as string[]) || [];
  // A guarded skip reads in the guard's own hue: it is the design working, and the dim
  // `skipped` grey is the colour of something having gone wrong. DS-6 — a route's
  // untaken arm is the same idea one branch over, in the route's own hue.
  const fan = (data.fan ?? null) as { count: number; executed: number; skipped: number } | null;
  const accent = data.guarded ? "var(--chart-3)"
    : data.not_taken ? "var(--chart-4)"
    : status ? (STATUS_COLOR[status] || "var(--t3)") : "var(--border)";
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
      {/* W1 — the guard this step carried, and (below) whether it is what held the step.
          A run canvas that shows only "skipped" cannot tell a design working from an
          upstream breaking. */}
      {Array.isArray(data.when) && (data.when as string[]).length > 0 && (
        <div className="aug-fs-xs" style={{ color: "var(--chart-3)", marginTop: 3,
          fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap" }}>
          only if {(data.when as string[]).join(
            data.when_logic === "any" ? " or " : " and ")}
        </div>
      )}
      {/* DS-6 — the route, a design fact like the guard above it: an arm drawn
          without its "otherwise" reads as a step that always fires. */}
      {!!data.else_of && (
        <div className="aug-fs-xs" style={{ color: "var(--chart-4)", marginTop: 3,
          fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap" }}>
          otherwise of {String(data.else_of)}
        </div>
      )}
      {!!status && (
        <div className="aug-fs-xs" style={{ color: accent, marginTop: 4 }}>
          ● {data.dryRun && status === "executed" ? "would run"
              : data.guarded ? "held · condition not met"
              // "not taken" alone: the message distinguishes "met its condition"
              // from "was not decided", and a summary that guessed which would be
              // wrong half the time.
              : data.not_taken ? "not taken" : status}
          {!!fan && (
            <span style={{ color: "var(--t4)" }}>
              {" "}· {fan.executed} of {fan.count}{fan.skipped ? ` · ${fan.skipped} held` : ""}
            </span>
          )}
          {/* A preview's duration is how long the INERT dispatcher took — "0ms" next to
              "would run" is noise dressed as a measurement. */}
          {!data.dryRun && typeof data.duration_ms === "number"
            && (data.duration_ms as number) > 0 && (
            <span style={{ color: "var(--t4)" }}> · {ms(data.duration_ms as number)}</span>
          )}
          {typeof data.attempts === "number" && (data.attempts as number) > 1 && (
            <span style={{ color: "var(--t4)" }}> · {String(data.attempts)} attempts</span>
          )}
        </div>
      )}
      {/* W2 — a step that ran once per item. The status line above already carries how
          many of them ran (the server writes "2 of 3 ran" as the message); this says
          what the list WAS, which is the half a run cannot infer. */}
      {!!data.for_each && (
        <div className="aug-fs-xs" style={{ color: "var(--chart-2)", marginTop: 3,
          fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap" }}>
          for each {String(data.for_each)}
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
      {/* DS-7 — the spine on this picture only touches the roots; the card says why. */}
      {data.scheduling === "parallel" && (
        <div className="aug-fs-xs" style={{ color: "var(--chart-2)", marginTop: 2 }}>
          steps run in parallel — as the arrows allow
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
    // B2 — the preview flag rides on every node. The status a dry run produces is
    // `executed`, which is the engine's honest word for "this step ran to completion"
    // and exactly the wrong one to put on screen when nothing ran: found by driving it,
    // with "● executed" sitting under a banner reading "nothing was sent".
    // DS-7 — the trigger card carries the scheduling, so a run whose spine only
    // touches the roots can say why.
    data: { ...n, dryRun: !!graph.dry_run,
            ...(n.type === "trigger" ? { scheduling: graph.scheduling } : {}) },
  }));

  // A data edge already implies "runs after", so a sequence edge on the same pair is
  // the same claim twice on an identical path — keep the one that carries meaning.
  // DS-6 — a route edge implies it too, and claims more: it decides.
  const carriesData = new Set(
    graph.edges.filter((e) => e.type === "data" || e.type === "route")
      .map((e) => `${e.from}->${e.to}`),
  );
  // W1 + B2 — a step can bind the SAME upstream key twice: once into a field and once
  // in its guard (`message: {$from: numbers.answer}` beside `only if numbers.answer is
  // set`). `build_graph` reports both, correctly — they are different claims — but in
  // Execution mode there are no per-field handles to land on, so the two arrows are one
  // arrow drawn twice, with one id. React logged a duplicate-key error and the second
  // edge was liable to be dropped. Deduped by what an execution edge actually says:
  // "this key flows from here to there". The guard is stated on the node either way.
  const seenData = new Set<string>();
  const drawn = graph.edges.filter((e) => {
    if (e.type === "sequence") return !carriesData.has(`${e.from}->${e.to}`);
    if (e.type !== "data") return true;
    const key = `${e.from}->${e.to}:${e.label ?? ""}`;
    if (seenData.has(key)) return false;
    seenData.add(key);
    return true;
  });

  const edges: RFEdge[] = drawn.map((e, i) => {
    const isData = e.type === "data";
    // DS-6 — the route, in its own hue and dashes: it carries no value (that is a
    // data edge) and claims more than order (that is the sequence spine) — it decides
    // whether the arm runs at all. Labelled with the server's own word.
    const isRoute = e.type === "route";
    return {
      id: `${e.type}:${e.from}->${e.to}:${e.label || i}`,
      source: e.from,
      target: e.to,
      label: isData || isRoute ? e.label : undefined,
      animated: false,
      style: isRoute
        ? { stroke: "var(--chart-4)", strokeWidth: 1.6, strokeDasharray: "7 4" }
        : isData
          ? (e.guard
              ? { stroke: "var(--chart-3)", strokeWidth: 1.6, strokeDasharray: "5 4" }
              : { stroke: "var(--chart-1)", strokeWidth: 1.6 })
          : { stroke: "var(--t4)", strokeWidth: 1, strokeDasharray: "3 3" },
      markerEnd: { type: MarkerType.ArrowClosed,
                   color: isRoute ? "var(--chart-4)"
                     : isData ? (e.guard ? "var(--chart-3)" : "var(--chart-1)") : "var(--t4)" },
      data: { edgeType: e.type },
    };
  });

  return { nodes, edges };
}

/* ═══════════════════ DESIGN MODE (the draft, editable) ═══════════════════ */

/** DS-4 — what one undo step restores: the chain, and where it was arranged. */
interface CanvasState {
  draft: Draft;
  positions: Record<string, { x: number; y: number }>;
}

const NODE_W = 280;

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "6px 9px", borderRadius: "var(--r2)",
  border: "1px solid var(--b1)", background: "var(--bg-1)", color: "var(--t1)",
};

/** A port dot, half over the card edge the way the reference frames draw them.
 *  Output = green ("gives"), input = blue; a bound input fills solid. */
const PORT = 10;
const portStyle = (kind: "in" | "out", bound: boolean): React.CSSProperties => ({
  width: PORT, height: PORT, borderRadius: "var(--r-pill)",
  background: bound ? "var(--chart-1)" : "var(--bg-2)",
  border: `2px solid ${kind === "out" ? "var(--chart-2)" : "var(--chart-1)"}`,
  boxShadow: "0 0 0 3px var(--bg-0)",
});

interface DesignNodeData {
  alias: string;
  kind: string;
  config: Record<string, unknown>;
  publishes: string[];
  openSet: boolean;
  inputs: { field: string; boundTo: string | null }[];
  /** W1 — the guard, raw. Rendered into sentences with the server's operator words
   *  rather than stored as prose, so a node and the editor cannot word it differently. */
  when: GuardClause[];
  whenLogic: "all" | "any";
  /** W2 — the fan-out, as one line ("EMEA, NA" or "rows.items"). "" = runs once. */
  forEach: string;
  /** DS-6 — the step whose "Only if" this one runs OTHERWISE of. "" = unrouted. */
  elseOf: string;
  /* ── §3.8b · why there are no callbacks in here ──
   *
   * A node's `data` used to carry `onPatch`, `onClear`, `onRemove`, `onDuplicate` and
   * `onRunToHere` as closures built inside the `design` memo. That made `data` a NEW
   * object with NEW function identities on every memo run, so `React.memo` on the node
   * could never hit — every node re-rendered whenever anything changed, including on
   * every frame of a drag. The handlers now live in `NodeHandlersContext` as stable
   * dispatchers that take the alias, and `data` is plain serialisable state that
   * compares cheaply. Wiring the change channel without this would have fixed the
   * position resets and left the re-render storm.
   *
   * Capability stays as BOOLEANS rather than optional callbacks: the node still has to
   * know that the last step shows no remove control, and "is this allowed" is data —
   * only "do it" was ever behaviour. */
  canRemove: boolean;
  canDuplicate: boolean;
  canRunToHere: boolean;
  /** True while that walk is in flight, so the control cannot be pressed twice. */
  running?: boolean;
  [key: string]: unknown;
}

/** The step handlers, hoisted out of `data` so a node's props can be compared.
 *
 * Every one takes the alias it acts on, so ONE stable object serves N nodes — the
 * property that makes memoisation possible at all. Null outside the canvas (the node
 * components are exported for tests and for the run view, where nothing is editable). */
interface NodeHandlers {
  patch: (alias: string, field: string, value: unknown) => void;
  clear: (alias: string, field: string) => void;
  remove: (alias: string) => void;
  duplicate: (alias: string) => void;
  runToHere: (alias: string) => void;
}

const NodeHandlersContext = createContext<NodeHandlers | null>(null);

/** §3.8b — the position changes in one ReactFlow batch, or null when there are none.
 *
 * Exported and pure because it is the whole of the new logic and the rest is a
 * `setState` — this file's own harness note says to assert at the handoff, since jsdom
 * reports every element as 0×0 and a rendered-drag assertion could not fail.
 *
 * **Positions only, deliberately.** ReactFlow also emits `add`, `remove`, `dimensions`,
 * `select` and `replace` changes. Applying those here would make the library a second
 * author of what the chain CONTAINS, and the draft is the first — two sources of truth
 * for structure is how a canvas starts disagreeing with what it will save. Structure
 * flows draft → canvas; only position flows back.
 */
export function positionChanges(
  changes: NodeChange<RFNode>[],
): Record<string, { x: number; y: number }> | null {
  let moved: Record<string, { x: number; y: number }> | null = null;
  for (const c of changes) {
    // `position` is absent on the final `dragging: false` tick, and on a change that
    // only reports selection. Writing `undefined` would blank a card's coordinates.
    if (c.type === "position" && c.position) (moved ??= {})[c.id] = c.position;
  }
  return moved;
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
  subchain:       [{ field: "automation_id", placeholder: "automation id" }],
  // DS-11 — the OPERATION, and deliberately not the grant. Found by drawing a real
  // chain: with no entry here a step that reads Gmail and one that posts to Slack
  // rendered as two identical empty boxes, both headed "Use an integration". The
  // account is chosen in the rail, from a picker over the reader's OWN grants — putting
  // its id in a free-text box on the node would invite pasting one that is not theirs,
  // and putting the email on the canvas is the spill `effect_detail` refuses.
  integration_call: [{ field: "operation", placeholder: "pick one in the rail" }],
  metric_value:   [{ field: "metric", placeholder: "metric name" }],
  trusted_query:  [{ field: "query_id", placeholder: "trusted query id" }],
};

/** The kind's accent — one hue per kind so a chain reads as a sequence of ROLES the
 *  way the reference canvases do, not as identical grey boxes. */
const KIND_HUE: Record<string, string> = {
  investigate: "var(--chart-1)", slack_post: "var(--chart-2)", notify: "var(--chart-3)",
  brief: "var(--chart-5)", kinetic_action: "var(--chart-4)",
  subchain: "var(--chart-6)",
  // DS-11 asked for a seventh hue and declined to invent one: "a palette decision with a
  // validator to satisfy, not a side effect of adding an effect kind." That work is now
  // done, so this kind takes the seventh rather than sharing the declared action's. The
  // accent was chosen by the palette SEARCH in the one hue gap left, and `lint:palette`
  // holds it to a stricter bar than the six meet among themselves: >= 6 CVD and >= 15
  // normal-vision separation from ALL six, not merely from an adjacent neighbour.
  //
  // It is NOT a seventh chart series — charts still fold to "Other" at six and
  // CHART_SERIES is untouched. On a canvas every kind is on screen at once, where the
  // chart's fold-to-grey would render one step type as though it were disabled.
  integration_call: "var(--chart-7)",
};

function DesignStepNodeInner({ data, selected }: { data: DesignNodeData; selected?: boolean }) {
  const handlers = useContext(NodeHandlersContext);
  // Operator WORDS come from the server's vocabulary (cached module-side, so N nodes
  // make one request) — a local map would be a second spelling of a closed set.
  const { guardOps } = useAutomationVocabulary();
  const boundOf = (field: string) =>
    data.inputs.find(i => i.field === field)?.boundTo ?? null;
  const bindableSet = new Set(data.inputs.map(i => i.field));
  // A BOUND field renders even when it is not primary (`visibleFields` carries the
  // full why — the short version: a hidden binding dropped the join's edges).
  const fields = visibleFields(PRIMARY_FIELDS[data.kind] ?? [], data.inputs);
  const kindLabel = EFFECT_KINDS.find(k => k.value === data.kind)?.label ?? data.kind;
  const hue = KIND_HUE[data.kind] ?? "var(--chart-6)";

  return (
    <div style={{
      width: NODE_W, borderRadius: "var(--r3)", background: "var(--bg-2)",
      border: `1px solid ${selected ? hue : "var(--b2)"}`,
      boxShadow: selected ? `0 0 0 1px ${hue}, var(--shadow-md)` : "var(--shadow-sm)",
      transition: "box-shadow var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out)",
    }}>
      {/* The unnamed target handle SEQUENCE edges land on — an edge with no
          targetHandle attaches to the default handle, and a node without one silently
          drops the edge (measured: the trigger's spine vanished while every port
          rendered). Hidden: geometry, not a port. */}
      <Handle type="target" position={Position.Left} style={{ opacity: 0, top: 20 }} />
      {/* DS-6 — the unnamed SOURCE handle the route edge leaves from: a verdict has no
          "gives" port, and a node without a default source handle silently drops the
          edge (the same measured lesson, one direction over). */}
      <Handle type="source" position={Position.Right} style={{ opacity: 0, top: 20 }} />

      {/* header — icon tile · kind · alias · remove. The tile carries the kind's hue,
          so a chain reads as roles at a glance (the reference frames' trick). */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px",
        borderBottom: "1px solid var(--b1)" }}>
        <span style={{
          width: 24, height: 24, borderRadius: "var(--r2)", display: "grid",
          placeItems: "center", color: hue,
          background: "color-mix(in srgb, currentColor 14%, transparent)",
        }}>
          <Icon name={KIND_ICON[data.kind] ?? "process"} size={13} />
        </span>
        <span className="aug-fs-ui" style={{ fontWeight: 600 }}>{kindLabel}</span>
        <span className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--t3)",
          border: "1px solid var(--b1)", borderRadius: "var(--r-pill)",
          padding: "1px 8px", background: "var(--bg-1)" }}>
          {data.alias}
        </span>
        {data.canRunToHere && handlers && (
          <Button variant="ghost" size="icon-sm" aria-label={`run to ${data.alias}`}
            title="Run the chain to here — inert, nothing is sent"
            disabled={data.running}
            className="nodrag" style={{ width: 20, height: 20, color: "var(--t4)" }}
            onClick={() => handlers.runToHere(data.alias)}>
            <Icon name={data.running ? "spinner" : "run"} size={11} />
          </Button>
        )}
        {data.canDuplicate && handlers && (
          <Button variant="ghost" size="icon-sm" aria-label={`duplicate ${data.alias}`}
            title="Duplicate this step (⌘D)"
            className="nodrag" style={{ width: 20, height: 20, color: "var(--t4)" }}
            onClick={() => handlers.duplicate(data.alias)}>
            <Icon name="copy" size={11} />
          </Button>
        )}
        {data.canRemove && handlers && (
          <Button variant="ghost" size="icon-sm" aria-label={`remove ${data.alias}`}
            className="nodrag" style={{ width: 20, height: 20, color: "var(--t4)" }}
            onClick={() => handlers.remove(data.alias)}>
            <Icon name="close" size={11} />
          </Button>
        )}
      </div>

      {/* fields — each row owns its input port, dot centred ON the row it binds */}
      <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 9 }}>
        {fields.map(({ field, placeholder }) => {
          const bound = boundOf(field);
          const bindable = bindableSet.has(field);
          return (
            <div key={field} style={{ position: "relative" }}>
              {bindable && (
                <Handle
                  id={`in:${field}`} type="target" position={Position.Left}
                  style={{ ...portStyle("in", !!bound), left: -(12 + PORT / 2),
                           top: "calc(50% + 7px)", transform: "translateY(-50%)" }}
                  title={`bind '${field}' — drag from a gives port`}
                />
              )}
              <div className="aug-fs-xs" style={{ color: "var(--t4)", marginBottom: 3,
                letterSpacing: "0.04em" }}>
                {field}
              </div>
              {bound ? (
                <div className="aug-fs-sm" style={{ display: "flex", alignItems: "center",
                  gap: 7, padding: "6px 9px", borderRadius: "var(--r2)",
                  border: "1px solid color-mix(in srgb, var(--chart-1) 55%, transparent)",
                  background: "color-mix(in srgb, var(--chart-1) 10%, var(--bg-1))",
                  color: "var(--chart-1)" }}>
                  <Icon name="link" size={12} />
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap", fontFamily: "var(--font-mono)" }}>{bound}</span>
                  <Button variant="ghost" size="icon-sm" aria-label={`unbind ${field}`}
                    className="nodrag" style={{ marginLeft: "auto", width: 18, height: 18 }}
                    onClick={() => handlers?.clear(data.alias, field)}>
                    <Icon name="close" size={10} />
                  </Button>
                </div>
              ) : (
                <input
                  className="nodrag aug-fs-sm"
                  style={inputStyle}
                  placeholder={placeholder}
                  value={String(data.config[field] ?? "")}
                  onChange={e => handlers?.patch(data.alias, field, e.target.value)}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* W1 — "only if", with a port of its own. An input port that DECIDES rather than
          fills, so it is drawn apart from the field rows and never inside them. The
          strip is absent when there is no guard: an empty one would say a step is
          conditional when it always runs. */}
      {data.when.length > 0 && (
        <div style={{ position: "relative", borderTop: "1px solid var(--b1)",
          padding: "7px 12px 8px", background: "var(--bg-1)" }}>
          <Handle
            id={`in:${GUARD_FIELD}`} type="target" position={Position.Left}
            style={{ ...portStyle("in", true), left: -(12 + PORT / 2),
                     top: "50%", transform: "translateY(-50%)",
                     borderColor: "var(--chart-3)", background: "var(--chart-3)" }}
            title="this step runs only if the guard holds"
          />
          <div className="aug-fs-xs" style={{ color: "var(--t4)", letterSpacing: "0.04em" }}>
            only if{data.when.length > 1 ? ` · ${data.whenLogic}` : ""}
          </div>
          {guardSentences(data.when, guardOps).map((line, i) => (
            <div key={i} className="aug-fs-xs" style={{ color: "var(--chart-3)",
              fontFamily: "var(--font-mono)", marginTop: 2, overflow: "hidden",
              textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{line}</div>
          ))}
        </div>
      )}

      {/* DS-6 — "otherwise", with a port of its own like the guard above: the route
          DECIDES whether this arm runs, so it is drawn apart from the field rows.
          Absent on an unrouted step — an empty strip would say a step is an arm when
          it always runs. */}
      {!!data.elseOf && (
        <div style={{ position: "relative", borderTop: "1px solid var(--b1)",
          padding: "7px 12px 8px", background: "var(--bg-1)" }}>
          <Handle
            id={`in:${ELSE_FIELD}`} type="target" position={Position.Left}
            style={{ ...portStyle("in", true), left: -(12 + PORT / 2),
                     top: "50%", transform: "translateY(-50%)",
                     borderColor: "var(--chart-4)", background: "var(--chart-4)" }}
            title="this step runs when that step's Only if does not hold"
          />
          <div className="aug-fs-xs" style={{ color: "var(--t4)", letterSpacing: "0.04em" }}>
            otherwise
          </div>
          <div className="aug-fs-xs" style={{ color: "var(--chart-4)",
            fontFamily: "var(--font-mono)", marginTop: 2, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            when {data.elseOf}&apos;s only-if does not hold
          </div>
        </div>
      )}

      {/* W2 — "for each", with a port of its own for the same reason the guard has one:
          a list decides how many times the step runs, not what one run says, so it is
          drawn apart from the field rows. Absent when the step runs once — an empty
          strip would say a step repeats when it does not. */}
      {!!data.forEach && (
        <div style={{ position: "relative", borderTop: "1px solid var(--b1)",
          padding: "7px 12px 8px", background: "var(--bg-1)" }}>
          <Handle
            id={`in:${FAN_FIELD}`} type="target" position={Position.Left}
            style={{ ...portStyle("in", true), left: -(12 + PORT / 2),
                     top: "50%", transform: "translateY(-50%)",
                     borderColor: "var(--chart-2)", background: "var(--chart-2)" }}
            title="this step runs once per item of this list"
          />
          <div className="aug-fs-xs" style={{ color: "var(--t4)", letterSpacing: "0.04em" }}>
            for each
          </div>
          <div className="aug-fs-xs" style={{ color: "var(--chart-2)",
            fontFamily: "var(--font-mono)", marginTop: 2, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{data.forEach}</div>
        </div>
      )}

      {/* outputs — "gives X", one row per key, its dot half over the right edge */}
      {data.publishes.length > 0 && (
        <div style={{ borderTop: "1px solid var(--b1)", padding: "7px 12px 9px",
          display: "flex", flexDirection: "column", gap: 4 }}>
          {data.publishes.map(key => (
            <div key={key} style={{ position: "relative", display: "flex",
              justifyContent: "flex-end", alignItems: "center", minHeight: 18 }}>
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                gives{" "}
                <span style={{ color: "var(--chart-2)", fontFamily: "var(--font-mono)" }}>
                  {data.openSet ? "the action's outcome" : key}
                </span>
              </span>
              <Handle
                id={`out:${key}`} type="source" position={Position.Right}
                style={{ ...portStyle("out", false), right: -(12 + PORT / 2),
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

/** One condition, humanised. The cron stays visible because it is the truth; the words
 *  in front of it are for scanning, not a translation layer that could drift. */
function conditionLine(c: { kind: string; config: Record<string, unknown> }): string {
  if (c.kind === "schedule") return `on schedule · ${c.config.cron ?? ""}`;
  if (c.kind === "metric") return `monitor ${c.config.monitor_id ?? ""} fires`;
  if (c.kind === "source_change") return `${c.config.table ?? "a table"} changes`;
  if (c.kind === "entity_appears") return `new key in ${c.config.table ?? "a table"}`;
  if (c.kind === "webhook") return "when its URL is called";
  return c.kind;
}

function DesignTriggerNode({ data }: {
  data: { conditions: { kind: string; config: Record<string, unknown> }[]; logic: string;
          scheduling?: string };
}) {
  return (
    <div style={{
      width: 210, borderRadius: "var(--r3)", background: "var(--bg-2)",
      border: "1px dashed var(--b3)", boxShadow: "var(--shadow-sm)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px",
        borderBottom: "1px solid var(--b1)" }}>
        <span style={{
          width: 24, height: 24, borderRadius: "var(--r2)", display: "grid",
          placeItems: "center", color: "var(--chart-3)",
          background: "color-mix(in srgb, currentColor 14%, transparent)",
        }}>
          <Icon name="bolt" size={13} />
        </span>
        <span className="aug-fs-ui" style={{ fontWeight: 600 }}>Trigger</span>
        {data.conditions.length > 1 && (
          <span className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--t4)" }}>
            {data.logic === "all" ? "all match" : "any match"}
          </span>
        )}
      </div>
      <div style={{ padding: "9px 12px", display: "flex", flexDirection: "column", gap: 4 }}>
        {data.conditions.length === 0 && (
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>manual only</span>
        )}
        {data.conditions.map((c, i) => (
          <span key={i} className="aug-fs-sm" style={{ color: "var(--t2)" }}>
            {conditionLine(c)}
          </span>
        ))}
        {/* DS-7 — a spine-less picture must say why: the frontier starts every root
            at once, and only the arrows order what follows. */}
        {data.scheduling === "parallel" && (
          <span className="aug-fs-xs" style={{ color: "var(--chart-2)" }}>
            steps run in parallel — as the arrows allow
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Right}
        style={{ ...portStyle("out", false), right: -(12 + PORT / 2),
                 top: "50%", transform: "translateY(-50%)" }} />
    </div>
  );
}

/* ── §3.8b · memoised, and the order this had to be done in ──
 *
 * ReactFlow re-renders its node layer on every frame of a drag. Without `memo` here
 * every card re-ran its whole body each frame — Langflow memoises six sub-components
 * inside `GenericNode` alone, which is what the comparison actually showed.
 *
 * This is the LAST of the three changes, not the first: memo compares props, `data` is
 * a node's props, and until the handler closures came out of `data` (see
 * `NodeHandlersContext`) every comparison was guaranteed to differ. Adding `memo`
 * first would have looked like a fix and changed nothing measurable. */
const StepNodeMemo = memo(StepNode);
const TriggerNodeMemo = memo(TriggerNode);
const DesignStepNode = memo(DesignStepNodeInner);
const DesignTriggerNodeMemo = memo(DesignTriggerNode);

const NODE_TYPES = {
  step: StepNodeMemo, trigger: TriggerNodeMemo,
  designStep: DesignStepNode, designTrigger: DesignTriggerNodeMemo,
};

/* ═══════════════════ the component ═══════════════════ */

export function AutomationGraph({ automationId, automation, create, onCreated, header,
                                  onSaved, liveRunId }: {
  /** Absent ⇒ the canvas is authoring something that does not exist yet (create mode). */
  automationId?: string;
  /** The record itself. Present ⇒ Design mode is AUTHORABLE. Absent with `create` ⇒
   *  canvas-first creation; absent without it ⇒ read-only. */
  automation?: Automation;
  /** DS-1R — canvas-first creation: the connection the new automation will belong to,
   *  and (for a DS-15 proposal) the draft to start from instead of a blank canvas. */
  create?: { connId: string; seed?: Draft };
  /** Create mode's exit: the record the server now holds. */
  onCreated?: (a: Automation) => void;
  /** DS-1R — the ONE header row. The canvas owns it so the identity, the mode and the
   *  design's verbs share a single strip instead of stacking ("layer after layer…
   *  the main workflow is getting out of focus" — the user, 2026-09-02). */
  header?: {
    name: string; enabled?: boolean; onBack: () => void;
    onRunNow?: () => void; running?: boolean;
    /** Present ⇒ the name is editable in place (create mode). */
    onName?: (name: string) => void;
  };
  onSaved?: () => void;
  /** DS-3 — a run happening NOW, named by whoever started it. While this is set the
   *  canvas watches that run's own spans as they are written; when it clears, the
   *  authoritative graph is fetched, and the two agree. */
  liveRunId?: string | null;
}) {
  const [mode, setMode] = useState<"design" | "execution">("design");
  const [runId, setRunId] = useState("");
  const [graph, setGraph] = useState<AutomationGraphData | null>(null);
  /** B2 — a dry run's graph. Held rather than refetched, because a preview is never
   *  stored: there is no run id for the graph route to look up. It takes precedence over
   *  the server's graph while it is on screen, and any move that asks for a REAL run
   *  clears it — a preview must never be mistaken for something that happened. */
  const [preview, setPreview] = useState<AutomationGraphData | null>(null);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  /** Drag-time refusals — `applyConnect`'s sentence, shown then cleared. */
  /** A transient sentence over the canvas: a refused drag, or what a paste could not
 *  carry over. One channel, because two would overlap in the same corner. */
  const [notice, setNotice] = useState("");
  const [vocab, setVocab] = useState<Vocabulary | null>(null);
  // W2's reserved word, from the same fetched document the pickers read — a paste
  // has to know which refs are per-iteration, and must not spell that word itself.
  const { forEach: fanVocab } = useAutomationVocabulary();
  const itemAlias = fanVocab.itemAlias;

  /* ── DS-4 · one undoable state ──
   *
   * The draft and the arrangement travel together. They could have been two stacks, and
   * that is the version that feels broken: a person drags a node, edits a field, presses
   * undo twice and watches the two changes come back in an order neither of them chose.
   * One state, one stack, one meaning for "the last thing I did".
   */
  const [history, setHistory] = useState<History<CanvasState>>(() => initHistory({
    draft: automation
      ? { conditions: automation.conditions, effects: automation.effects }
      // Create mode starts from the seed (a DS-15 proposal) or the blank canvas —
      // the trigger node alone, which is the user's own picture of "new automation".
      : create?.seed ?? blankDraft(),
    positions: {},
  }));
  const draft = history.present.draft;
  const positions = history.present.positions;

  /** Record an edit. Keeps `useState`'s signature — value or updater — so the sixteen
   *  places that write the draft did not have to learn about history, and an `opts.key`
   *  is what turns a burst of keystrokes into one undo. */
  const setDraft = useCallback((
    next: Draft | ((d: Draft) => Draft), opts?: PushOptions,
  ) => {
    setHistory(h => {
      const draftNext = typeof next === "function"
        ? (next as (d: Draft) => Draft)(h.present.draft) : next;
      if (draftNext === h.present.draft) return h;
      return pushHistory(h, { ...h.present, draft: draftNext }, opts);
    });
  }, []);

  // A record arriving from the server is a new BASELINE, never an edit: recording it
  // would let undo walk backwards through the server's own reply, and the first thing
  // it would restore is the draft as it was before the save that produced this reply.
  // The arrangement rides through — it is not part of the record.
  useEffect(() => {
    if (!automation) return;
    setHistory(h => resetHistory(h, {
      draft: { conditions: automation.conditions, effects: automation.effects },
      positions: h.present.positions,
    }));
  }, [automation]);

  useEffect(() => {
    // W1 — the fetch now carries the guard operators too; this canvas wants only the
    // per-kind ports, and `AutomationRows` fetches (and caches) the same document for
    // the "Only if" pickers.
    getAutomationVocabulary().then(v => setVocab(v.kinds)).catch(() => setVocab({}));
  }, []);

  const authoring = (!!automation || !!create) && mode === "design";
  // Kept in a ref so the key listener can read it without being rebuilt on every edit.
  useEffect(() => { authoringRef.current = authoring; }, [authoring]);

  // The EXECUTION graph stays the server's; fetched only when that mode is on screen.
  useEffect(() => {
    // A preview owns the canvas while it is up; refetching here would replace it with
    // the last REAL run the moment it was shown. No id ⇒ nothing stored to fetch.
    if (mode !== "execution" || preview || !automationId) return;
    let live = true;
    getAutomationGraph(automationId, runId || "latest")
      .then((g) => { if (live) { setGraph(g); setError(""); } })
      .catch((e) => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [automationId, mode, runId, reloadKey, preview]);

  /* ── design-mode graph, drawn from the draft ── */
  // Positions survive dragging but reset per automation — session-local by design:
  // a stored layout is a second copy of the chain's order that could drift from it.
  /* ── DS-4 · the arrangement, kept ──
   *
   * `positions` holds ONLY placements a person made — a drag, or a step dropped from the
   * palette. The computed fallback below is never written into it, which is what makes
   * saving the whole map safe: the cockpit's rule, that automatic (re)placement must
   * never persist, holds here by construction rather than by a flag.
   */
  useEffect(() => {
    if (!automationId) return;          // an unsaved chain has no stored arrangement
    let live = true;
    getAutomationLayout(automationId)
      .then(saved => {
        if (!live) return;
        // Neither an edit nor a baseline — it COMPLETES the baseline that was already
        // there, so it patches the present and leaves both stacks exactly as they are.
        // A reset here would throw away edits made in the moment before it arrived.
        setHistory(h => ({ ...h, present: { ...h.present, positions: saved } }));
      })
      // An arrangement is a convenience; failing to read one opens the canvas at its
      // computed default rather than putting an error over a working editor.
      .catch(() => {});
    return () => { live = false; };
  }, [automationId]);

  const saveTimer = useRef<number | null>(null);
  useEffect(() => () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); }, []);

  /** Persist the arrangement, debounced — a drag emits a position per frame at rest and
   *  one request per drag is the honest number. `alive` prunes: a step that was removed
   *  (or a palette add that was discarded) must not keep a coordinate forever.
   *
   *  Takes the arrangement rather than reading it: after an undo the state React is
   *  about to render and the one this closure captured are different, and the arrangement
   *  that gets saved has to be the one on screen. */
  const persistLayout = useCallback((
    layout: Record<string, { x: number; y: number }>, alive: Set<string>,
  ) => {
    if (!automationId) return;          // arrangements persist per stored id only
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      void saveAutomationLayout(automationId, layoutToPersist(layout, alive)).catch(() => {});
    }, 500);
  }, [automationId]);

  /* ── DS-4 · walking the stack ──
   *
   * An undo has to put back the ARRANGEMENT it restores, not just the chain, or the two
   * halves of one state drift apart the first time somebody undoes a drag. So both walks
   * persist the layout they land on, pruned to the steps that state actually has.
   */
  const walk = useCallback((direction: "undo" | "redo") => {
    setHistory(h => {
      const next = direction === "undo" ? undoHistory(h) : redoHistory(h);
      if (next === h) return h;
      const alive = new Set<string>([
        "__trigger",
        ...next.present.draft.effects.map((e, i) => aliasFor(e, i)),
      ]);
      persistLayout(next.present.positions, alive);
      return next;
    });
  }, [persistLayout]);

  /* ── DS-4 · duplicate, copy, paste ──
   *
   * Every one of these lands a step through `pasteEffect`, which is where the dangerous
   * part lives: a step's name is positional and its bindings are strings, so a copy
   * carries references that mean "whatever is in that position". A reference whose
   * producer is not present and upstream is DROPPED and reported — never repointed,
   * because a repointed binding saves cleanly, draws a confident edge, and posts another
   * step's answer at 09:00.
   */
  const landStep = useCallback((step: AutoEffect, at?: { x: number; y: number }) => {
    setHistory(h => {
      const { draft: nextDraft, dropped } = pasteEffect(h.present.draft, step, itemAlias);
      const alias = aliasFor(nextDraft.effects[nextDraft.effects.length - 1],
                             nextDraft.effects.length - 1);
      const nextPositions = at ? { ...h.present.positions, [alias]: at } : h.present.positions;
      if (at) persistLayout(nextPositions, new Set([...Object.keys(nextPositions), alias]));
      if (dropped.length) {
        // Said out loud, because a paste that silently arrives half-wired is the same
        // class of quiet wrongness this function refuses to commit.
        setNotice(`${alias}: ${[...new Set(dropped)].join(", ")} `
          + `${dropped.length > 1 ? "were" : "was"} not carried over — `
          + "the step they read is not in this chain.");
        window.setTimeout(() => setNotice(""), 5200);
      }
      return pushHistory(h, { draft: nextDraft, positions: nextPositions });
    });
  }, [persistLayout, itemAlias]);

  /* ── DS-2 · run to here ──
   *
   * B2 already walks a whole chain inert, and returns an ordinary `AutomationRun` so the
   * Execution canvas draws it with no second way of showing one. This is that same walk
   * with a frontier: it previews the DRAFT (what Save would send, never a second
   * assembly of it), and the steps past the cut come back drawn but undecorated — "not
   * asked" rather than "did nothing".
   */
  const [runningTo, setRunningTo] = useState<string | null>(null);

  const runToHere = useCallback(async (alias: string) => {
    if (!automation) return;
    setRunningTo(alias);
    setNotice("");
    try {
      const { graph } = await dryRunAutomationDraft(
        updatePayload(automation, draft), alias);
      setPreview(graph);
      setMode("execution");
    } catch (e) {
      setNotice((e as Error)?.message || "Could not walk the chain");
      window.setTimeout(() => setNotice(""), 4000);
    } finally {
      setRunningTo(null);
    }
  }, [automation, draft]);

  /** Duplicate lands beside its original, so the copy is visibly a second card rather
   *  than one hiding exactly underneath the one it came from. */
  const duplicateStep = useCallback((alias: string) => {
    const source = draft.effects.find((e, i) => aliasFor(e, i) === alias);
    if (!source) return;
    const from = positions[alias];
    landStep(source, from ? { x: from.x + 42, y: from.y + 42 } : undefined);
  }, [draft.effects, positions, landStep]);

  /** Which step the canvas has selected — ReactFlow's own selection, so ⌘C acts on the
   *  card with the ring around it rather than on some notion of "current" of our own. */
  const [selectedAlias, setSelectedAlias] = useState<string | null>(null);

  /** The three gestures, behind a ref so the key listener reads today's draft without
   *  being torn down and rebuilt on every keystroke. Each returns whether it DID
   *  something, so the handler only swallows the browser's own shortcut when we used it
   *  — ⌘C with nothing selected must still mean "copy the text I highlighted". */
  const commandsRef = useRef<Record<"copy" | "paste" | "duplicate", () => boolean>>({
    copy: () => false, paste: () => false, duplicate: () => false,
  });
  useEffect(() => {
    const selected = () => (selectedAlias && selectedAlias !== "__trigger"
      ? draft.effects.find((e, i) => aliasFor(e, i) === selectedAlias) ?? null
      : null);
    const centre = () => {
      const pane = paneRef.current?.getBoundingClientRect();
      return rf.current && pane
        ? viewportCenter(rf.current.getViewport(),
                         { width: pane.width, height: pane.height }, NODE_W)
        : undefined;
    };
    commandsRef.current = {
      copy: () => {
        const step = selected();
        if (!step) return false;
        copyToCanvasClipboard(step);
        setNotice(`${selectedAlias} copied — ⌘V to paste it into any chain.`);
        window.setTimeout(() => setNotice(""), 2600);
        return true;
      },
      paste: () => {
        const step = canvasClipboard();
        if (!step) return false;
        landStep(step, centre());
        return true;
      },
      duplicate: () => {
        const step = selected();
        if (!step || !selectedAlias) return false;
        duplicateStep(selectedAlias);
        return true;
      },
    };
  }, [draft.effects, selectedAlias, landStep, duplicateStep]);

  const authoringRef = useRef(false);
  useEffect(() => {
    // ⌘Z / ⌘⇧Z, the repo's own shortcut shape (a window listener that reads
    // `metaKey || ctrlKey`), armed only while this canvas is the thing being edited.
    // A ref rather than a dependency so the listener is not torn down and rebuilt every
    // time the draft changes — it would miss a keystroke landing in that gap.
    /** Is the person typing? ⌘C/⌘V mean TEXT inside a field and a STEP outside one —
     *  taking the gesture away from a half-typed channel name would be a worse trade
     *  than the convenience is worth. ⌘Z is the deliberate exception: those fields are
     *  the draft, so this stack is the authority for them too. */
    const inTextField = (target: EventTarget | null): boolean => {
      const el = target as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable === true;
    };

    const handler = (e: KeyboardEvent) => {
      if (!authoringRef.current) return;
      const meta = e.metaKey || e.ctrlKey;
      if (!meta) return;
      const key = e.key.toLowerCase();

      if (key === "z") {
        e.preventDefault();
        walk(e.shiftKey ? "redo" : "undo");
        return;
      }
      if (inTextField(e.target)) return;

      const cmd = commandsRef.current;
      if (key === "c" && cmd.copy()) e.preventDefault();
      else if (key === "v" && cmd.paste()) e.preventDefault();
      else if (key === "d" && cmd.duplicate()) e.preventDefault();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [walk]);

  /* ── DS-4 · the open-set key picker (what replaced the window.prompt) ── */
  const [pendingBind, setPendingBind] =
    useState<{ from: string; to: string; field: string } | null>(null);
  /** Keys each step has been SEEN to publish, from the latest run. `null` = not asked
   *  yet; fetched only when a bind is actually pending, because a canvas nobody is
   *  binding on should not spend a request to populate a picker nobody opened. */
  const [observed, setObserved] = useState<Record<string, string[]> | null>(null);

  useEffect(() => {
    if (!pendingBind || observed !== null) return;
    if (!automationId) { setObserved({}); return; }   // never run ⇒ nothing observed
    let live = true;
    getAutomationGraph(automationId, "latest")
      .then(g => { if (live) setObserved(producedByAlias(g)); })
      // A step that never ran, or a graph we could not read, leaves the typed field as
      // the only offer — which is the honest state, not an error worth a banner.
      .catch(() => { if (live) setObserved({}); });
    return () => { live = false; };
  }, [pendingBind, observed, automationId]);

  /* ── DS-3 · a run, while it is running ──
   *
   * The substrate was already there: the engine writes a span per step under
   * `trace_id == run_id` as it goes, and `/activity?trace_id=` reads them back. Nothing
   * was watching. This polls at 1Hz rather than opening a stream, because `/activity`
   * already takes the filter and `/activity/stream` does not — one existing endpoint
   * beats one new one, and the swap to SSE is a later, smaller change.
   *
   * The stream is the ANTICIPATION; `build_graph` is the truth. When the run ends, the
   * ordinary fetch below runs and replaces every guess with the stored outcome — which is
   * what keeps a lively canvas from becoming a confident wrong one.
   */
  const [live, setLive] = useState<Record<string, LiveStatus>>({});

  useEffect(() => {
    if (!liveRunId) { setLive({}); return; }
    let alive = true;
    const tick = () => {
      getActivityEvents({ trace_id: liveRunId, limit: 200 })
        .then(r => { if (alive) setLive(liveStatuses(r.events ?? [])); })
        // A poll that fails is a poll: never surfaced as an error, because blanking a
        // working canvas over one dropped request is worse than a stale second.
        .catch(() => {});
    };
    tick();
    const iv = window.setInterval(tick, 1000);
    return () => { alive = false; window.clearInterval(iv); };
  }, [liveRunId]);

  // A run that just ended is the one thing the stored graph must be re-read for.
  const wasLive = useRef<string | null>(null);
  useEffect(() => {
    if (liveRunId) {
      wasLive.current = liveRunId;
      // A preview would otherwise swallow the run entirely — it blocks the fetch and
      // wins the render, so a live run started with one up would be invisible.
      setPreview(null);
      setMode("execution");
      setRunId(liveRunId);
      return;
    }
    if (!wasLive.current) return;
    const finished = wasLive.current;
    wasLive.current = null;
    setPreview(null);
    setMode("execution");
    setRunId(finished);
    setReloadKey(k => k + 1);
  }, [liveRunId]);

  /* ── DS-4 · what the canvas measured ──
   *
   * The minimap draws nothing for a node it cannot size, and it sizes from the node
   * OBJECT we hand ReactFlow — `nodeHasDimensions(userNode)` — not from the internals it
   * measures. Our nodes are derived fresh from the draft, and the library reports its
   * measurements only through `onNodesChange`, which this canvas never receives (probed:
   * it does not fire here at all). So the map came up an EMPTY BOX while the canvas
   * itself was perfect, because edges and dragging read the internals instead.
   *
   * So we measure the rendered cards ourselves — the same thing the library does, from
   * the same DOM, because the channel it would tell us through is silent. Exact rather
   * than a declared guess: a card grows when it gains a guard or a fan-out strip, and a
   * minimap drawn from an assumed height would quietly stop matching the canvas.
   */
  const [sizes, setSizes] = useState<Record<string, { width: number; height: number }>>({});

  const measureNodes = useCallback(() => {
    const pane = paneRef.current;
    if (!pane) return;
    setSizes(prev => {
      let next = prev;
      for (const el of pane.querySelectorAll<HTMLElement>(".react-flow__node")) {
        const id = el.dataset.id;
        if (!id) continue;
        const width = el.offsetWidth, height = el.offsetHeight;
        if (!width || !height) continue;
        const seen = prev[id];
        if (seen && seen.width === width && seen.height === height) continue;
        // Clone only once something actually moved, so a re-measure that changed nothing
        // cannot loop the memo that feeds it.
        if (next === prev) next = { ...prev };
        next[id] = { width, height };
      }
      return next;
    });
  }, []);

  // After every render, and once more a frame later: the first pass catches the common
  // case, the second a card whose fonts or strips settled late. No dependency list on
  // purpose — the things that change a card's size are its content, its mode and its
  // count, and enumerating those is a list that goes stale the next time a strip is
  // added. It cannot loop: `measureNodes` returns the SAME state object unless a size
  // actually moved, so a render that measures the same thing schedules nothing.
  useEffect(() => {
    measureNodes();
    const frame = requestAnimationFrame(measureNodes);
    return () => cancelAnimationFrame(frame);
  });

  /* ── DS-1 · the palette, and the one gate everything it offers goes through ── */
  const [palette, setPalette] = useState<PaletteGroup | "all" | null>(null);
  /** DS-1 P2 — the rail's second section. The runs list used to appear on its own the
   *  moment execution mode opened; it is now a section a reader opens and collapses
   *  like the palette (entering execution still opens it — the old behaviour, now
   *  dismissable). Sections are exclusive: runs lives in execution, palette in design,
   *  and switching sections closes the other — which is also what makes "every section
   *  switch clears search" true for free, because the palette remounts fresh. */
  const [runsOpen, setRunsOpen] = useState(false);
  /** DS-1 P1 — the edge someone dropped on empty canvas: producer, key, and where it
   *  landed. While set, the palette shows only consumers and the next add lands
   *  pre-bound to it. Cleared by the banner's ×, the palette closing, or the add. */
  const [edgeDrop, setEdgeDrop] = useState<EdgeDrop | null>(null);

  /** The gesture half of P1 — everything it decides lives in `landPrebound`, because
   *  jsdom cannot drive a ReactFlow drag (measured four times) and the law has to be
   *  testable without one. Fires on EVERY connection end; the guards keep it to the
   *  one case that means "offer me a consumer": a gives port released over nothing. */
  const onConnectEnd = useCallback<OnConnectEnd>((_event, cs) => {
    if (!authoringRef.current) return;
    if (!cs.fromHandle || cs.toNode) return;          // landed on a node — onConnect owns it
    const h = cs.fromHandle;
    if (h.type !== "source" || !h.id?.startsWith("out:")) return;
    if (!h.nodeId || h.nodeId === "__trigger") return; // the trigger's spine is not a value
    setEdgeDrop({ from: h.nodeId, key: h.id.slice(4), at: cs.to ?? null });
    setPalette("action");
  }, []);
  // Captured from `onInit` rather than `useReactFlow`, which would need this canvas
  // wrapped in a provider it does not otherwise want.
  const rf = useRef<ReactFlowInstance | null>(null);
  const paneRef = useRef<HTMLDivElement>(null);

  /**
   * Place what the palette handed over. The ONE add path: a clicked row and a dropped
   * row both arrive here, and only the position differs — a drop knows where the reader
   * put it, a click means "wherever I am looking".
   *
   * A TRIGGER ignores position on purpose: every condition renders inside the single
   * `__trigger` node, so there is no new node for a drop point to be about, and moving
   * the trigger card to wherever a reader released the mouse would be a surprise dressed
   * as precision.
   */
  const addFromPalette = useCallback(
    (placement: PalettePlacement, position?: { x: number; y: number }) => {
      if (placement.group === "trigger") {
        setDraft(d => ({
          ...d,
          conditions: [...d.conditions,
                       newConditionOf(placement.kind as AutoCondition["kind"])],
        }));
        return;
      }
      // The alias the new step WILL have — `aliasFor`'s rule, one step ahead of it, so
      // the position is filed under the same name the node is about to be drawn with.
      const alias = `step${draft.effects.length + 1}`;
      const pane = paneRef.current?.getBoundingClientRect();
      // DS-1 P1 — a pre-bound add prefers WHERE THE EDGE WAS RELEASED: the reader
      // already pointed at the place; the viewport centre is for adds with no gesture.
      const at = position ?? edgeDrop?.at
        ?? (rf.current && pane
          ? viewportCenter(rf.current.getViewport(),
                           { width: pane.width, height: pane.height }, NODE_W)
          : null);
      // DS-1 P1 — landing from an edge drop appends AND wires in one act (and so one
      // undo). Computed against the same draft the alias was, outside the updater —
      // React may run updaters twice, and `landPrebound` is not free to run twice
      // against two different presents.
      const landed = edgeDrop && vocab
        ? landPrebound(draft, vocab, newEffectOf(placement.kind as AutoEffect["kind"]),
                       { from: edgeDrop.from, key: edgeDrop.key })
        : null;
      if (landed?.error) {
        setNotice(landed.error);
        window.setTimeout(() => setNotice(""), 3200);
      }
      // The step and where it landed are ONE act, so they are one entry: an undo that
      // removed the step but kept its coordinate would leave a ghost for the next add
      // to inherit.
      setHistory(h => {
        const nextPositions = at ? { ...h.present.positions, [alias]: at } : h.present.positions;
        const next = {
          draft: landed ? landed.draft : {
            ...h.present.draft,
            effects: [...h.present.draft.effects,
                      newEffectOf(placement.kind as AutoEffect["kind"])],
          },
          positions: nextPositions,
        };
        if (at) persistLayout(nextPositions, new Set([...Object.keys(nextPositions), alias]));
        return pushHistory(h, next);
      });
      // An open-set drop cannot know its key at drag time — park the connection for
      // the picker, exactly as a node-to-node `out:*` drag does (DS-4's machinery).
      if (landed && !landed.error && edgeDrop?.key === "*" && landed.field) {
        setPendingBind({ from: edgeDrop.from, to: landed.alias, field: landed.field });
      }
      setEdgeDrop(null);
    },
    [draft, edgeDrop, vocab, persistLayout],
  );

  const patchField = useCallback((alias: string, field: string, value: unknown) => {
    // Coalesced per field: typing a question is ONE undo, not one per character. The
    // clock is read out here rather than inside the updater, which React may call twice.
    const now = Date.now();
    setDraft(d => ({
      ...d,
      effects: d.effects.map((e, i) =>
        aliasFor(e, i) === alias ? { ...e, config: { ...e.config, [field]: value } } : e),
    }), { key: `${alias}.${field}`, at: now });
  }, [setDraft]);

  const clearField = useCallback((alias: string, field: string) => {
    setDraft(d => clearBinding(d, alias, field));
  }, []);

  /* ── §3.8b · the change channel, and why the overlay is separate from history ──
   *
   * ReactFlow was handed `nodes` and NO `onNodesChange`, which breaks controlled mode:
   * the library moved the card in its own store, our array never heard, and the next
   * parent render put the card back where `positions` still said it was. The DS-4 note
   * above read the silence as a library quirk ("it does not fire here at all") — it did
   * not fire because it was never passed.
   *
   * Positions during a drag land HERE and not in history. `positions` lives in the undo
   * stack, and writing there per pointer-move would put a hundred steps between a person
   * and the thing they wanted to undo. So the overlay holds the live position, the design
   * memo prefers it, and `onNodeDragStop` commits ONE entry and drops the overlay — the
   * same coalescing the stack already documents. */
  const [livePos, setLivePos] = useState<Record<string, { x: number; y: number }>>({});

  const onNodesChange = useCallback((changes: NodeChange<RFNode>[]) => {
    const moved = positionChanges(changes);
    if (moved) setLivePos(prev => ({ ...prev, ...moved }));
  }, []);

  /** §3.8b — one stable object for N nodes. Rebuilt only when a dispatcher itself
   *  changes, which is what lets `memo(DesignStepNodeInner)` actually hit. */
  const nodeHandlers = useMemo<NodeHandlers>(() => ({
    patch: (alias, field, value) => patchField(alias, field, value),
    clear: (alias, field) => clearField(alias, field),
    duplicate: (alias) => duplicateStep(alias),
    runToHere: (alias) => runToHere(alias),
    // `aliasFor(e, j)`, not `e.alias`: a draft effect's alias is often EMPTY and the
    // displayed name is positional (`step2`). Filtering on the raw field would match
    // nothing and silently remove no step.
    remove: (alias) => setDraft(d => ({
      ...d, effects: d.effects.filter((e, j) => aliasFor(e, j) !== alias),
    })),
  }), [patchField, clearField, duplicateStep, runToHere, setDraft]);

  const design = useMemo(() => {
    if (!vocab) return { nodes: [] as RFNode[], edges: [] as RFEdge[] };
    const { steps, edges } = draftToFlow(draft, vocab);
    const nodes: RFNode[] = [{
      id: "__trigger",
      type: "designTrigger",
      measured: sizes["__trigger"],
      position: livePos["__trigger"] ?? positions["__trigger"] ?? { x: 0, y: 60 },
      data: { conditions: draft.conditions,
              logic: automation?.condition_logic ?? "all",
              scheduling: automation?.scheduling ?? "ordered" },
    }, ...steps.map((s, i) => ({
      id: s.alias,
      type: "designStep" as const,
      measured: sizes[s.alias],
      position: livePos[s.alias] ?? positions[s.alias] ?? { x: 260 + i * (NODE_W + 90), y: 0 },
      data: {
        ...s,
        // §3.8b — capabilities, not closures. The behaviour is one stable object in
        // `NodeHandlersContext`; what stays here is what the node has to KNOW.
        canDuplicate: true,
        canRunToHere: Boolean(automation),
        running: runningTo === s.alias,
        // The last step keeps no remove control at all — the model requires one effect,
        // and an affordance that fails at save teaches the wrong law. Same rule as the
        // rail, enforced by ABSENCE both places.
        canRemove: draft.effects.length > 1,
      } as DesignNodeData,
    }))];
    const spineStyle = {
      style: { stroke: "var(--t4)", strokeWidth: 1, strokeDasharray: "3 3" },
      markerEnd: { type: MarkerType.ArrowClosed, color: "var(--t4)" },
    };
    // DS-7 — where the spine attaches depends on the scheduling. Ordered: trigger →
    // first step (order itself is the rail's). Parallel: trigger → every ROOT, because
    // the frontier starts them all at once and everything downstream is ordered by the
    // arrows already drawn — a single spine would claim a first step that isn't one.
    const parallel = automation?.scheduling === "parallel";
    const rfEdges: RFEdge[] = [
      ...(steps.length
        ? (parallel
            ? rootAliases(draft).map(alias => ({
                id: `__seq:trigger:${alias}`, source: "__trigger", target: alias,
                ...spineStyle,
              }))
            : [{
                id: "__seq:trigger", source: "__trigger", target: steps[0].alias,
                ...spineStyle,
              }])
        : []),
      ...edges.map(e => ({
        id: `bind:${e.from}.${e.key}->${e.to}.${e.field}`,
        source: e.from,
        // DS-6 — a ROUTE edge leaves from the node's hidden default handle: a verdict
        // has no "gives" port. Everything else leaves from the key it carries.
        sourceHandle: e.route ? undefined : `out:${e.key}`,
        target: e.to,
        targetHandle: `in:${e.field}`,
        label: e.route ? "otherwise" : e.key,
        // Animated, because the edge carries DATA — the reference frames use motion to
        // say exactly this, and only this. The sequence spine stays still.
        // W1 — a GUARD edge carries data too, but to a decision rather than a field, so
        // it reads in its own hue and dashes: same motion, different claim.
        // DS-6 — a ROUTE edge carries nothing at all — it decides — so it alone among
        // the labelled edges does not move.
        animated: !e.route,
        // W2 — a FAN edge carries the list a step repeats over: its own hue again, and
        // dashed for the same reason the guard's is — neither fills a field.
        style: e.route
          ? { stroke: "var(--chart-4)", strokeWidth: 2, strokeDasharray: "7 4" }
          : e.guard
            ? { stroke: "var(--chart-3)", strokeWidth: 2, strokeDasharray: "5 4" }
            : e.fan
              ? { stroke: "var(--chart-2)", strokeWidth: 2, strokeDasharray: "2 3" }
              : { stroke: "var(--chart-1)", strokeWidth: 2 },
        labelStyle: { fill: "var(--t1)", fontFamily: "var(--font-mono)" },
        labelBgStyle: { fill: "var(--bg-2)", stroke: "var(--b2)" },
        labelBgPadding: [7, 3] as [number, number],
        labelBgBorderRadius: 6,
        markerEnd: { type: MarkerType.ArrowClosed,
                     color: e.route ? "var(--chart-4)"
                          : e.guard ? "var(--chart-3)"
                          : e.fan ? "var(--chart-2)" : "var(--chart-1)" },
      })),
    ];
    return { nodes, edges: rfEdges };
  }, [draft, positions, livePos, vocab, automation, sizes, runningTo]);

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

  /** Bind with a key, wherever the key came from — the drag, a picker row, or typed. */
  const bindWith = useCallback((
    from: string, toAlias: string, field: string, key: string,
  ) => {
    if (!vocab || !key) return;
    const r = applyConnect(draft, vocab, { fromAlias: from, key, toAlias, field });
    if (r.error) {
      setNotice(r.error);
      window.setTimeout(() => setNotice(""), 3200);
      return;
    }
    setDraft(r.draft);
    setPendingBind(null);
  }, [draft, vocab]);

  const onConnect = useCallback((c: RFConnection) => {
    if (!vocab || !c.source || !c.target) return;
    const key = (c.sourceHandle ?? "").replace(/^out:/, "");
    const field = (c.targetHandle ?? "").replace(/^in:/, "");
    if (!key || !field) return;
    // DS-4 — the open-set port ("*") cannot know its key at drag time. It used to be a
    // `window.prompt`: homely, and blind, since a typo draws an edge the run then skips.
    // Now the drop parks the connection and the picker below offers the keys this step
    // has actually been seen to publish, with a typed tail for the ones it hasn't.
    if (key === "*") {
      setPendingBind({ from: c.source, to: c.target, field });
      return;
    }
    bindWith(c.source, c.target, field, key);
  }, [vocab, bindWith]);

  if (error && mode === "execution") {
    return <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Could not load the graph: {error}</div>;
  }

  const shown = preview ?? graph;
  const executionFlow = mode === "execution" && shown ? toFlow(shown) : null;
  const execution = executionFlow && {
    ...executionFlow,
    nodes: executionFlow.nodes.map(n => ({
      ...n,
      measured: sizes[n.id],
      // While the run is in flight the server has no stored outcome for it yet — the
      // graph it returns is the STRUCTURE, every node undecorated. The spans decorate it
      // as they arrive, and a step that has not started stays undecorated, which is the
      // honest picture of a chain part-way through.
      ...(liveRunId ? { data: { ...n.data, status: LIVE_STATUS[live[n.id]] ?? "",
                                duration_ms: null, message: "" } } : {}),
    })),
  };

  return (
    <div style={{ height: "100%", minHeight: 260, display: "flex", flexDirection: "column" }}>
      {/* DS-1R — ONE strip: identity · mode · truth chips · the design's verbs. The
          rail and the second header row died into it, so the workflow below gets the
          room ("the actual workflow should be the primary driver" — user, 2026-09-02). */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, paddingBottom: 6,
        minWidth: 0 }}>
        {header && (
          <>
            <Button variant="ghost" size="sm" className="aug-fs-sm"
              onClick={header.onBack} style={{ color: "var(--t3)", flexShrink: 0 }}>
              ← Automations
            </Button>
            {header.onName ? (
              <input
                className="aug-fs-ui"
                aria-label="Name this automation"
                value={header.name}
                onChange={e => header.onName?.(e.target.value)}
                placeholder="Name this automation"
                style={{ fontWeight: 600, background: "var(--bg-1)",
                  border: "1px solid var(--b1)", borderRadius: "var(--r2)",
                  padding: "3px 8px", color: "var(--t1)", width: 200 }}
              />
            ) : (
              <span className="aug-fs-ui" style={{ fontWeight: 600, overflow: "hidden",
                textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{header.name}</span>
            )}
            {header.enabled !== undefined && (
              <span className="aug-fs-xs" style={{ flexShrink: 0,
                color: header.enabled ? "var(--grn4)" : "var(--t4)" }}>
                ● {header.enabled ? "enabled" : "disabled"}
              </span>
            )}
          </>
        )}
        <div style={{ display: "inline-flex", gap: 2, padding: 2,
          border: "1px solid var(--b1)", borderRadius: "var(--r-chip)",
          background: "var(--bg-1)" }}>
          {(["design", "execution"] as const).map((m) => (
            <Button key={m} variant={mode === m ? "secondary" : "ghost"} size="xs"
              // An unsaved chain has no runs; Execution opens there only for a preview.
              disabled={m === "execution" && !automationId && !preview}
              onClick={() => {
                setMode(m); setPreview(null); setRunsOpen(m === "execution");
                if (m === "design") setRunId("");
              }}>
              {m === "design" ? "Design" : "Execution"}
            </Button>
          ))}
        </div>
        {mode === "execution" && preview && (
          <span className="aug-fs-xs" style={{ color: "var(--chart-3)" }}>
            preview — nothing was sent{preview.run_reason?.includes(";")
              ? ` · ${preview.run_reason.split(";").slice(1).join(";").trim()}` : ""}
          </span>
        )}
        {mode === "execution" && !preview && graph?.run_missing && (
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            never run — showing the design
          </span>
        )}
        {mode === "execution" && !preview && graph && !graph.run_missing && graph.run_outcome
          && graph.run_outcome !== "fired" && (
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            last run {graph.run_outcome}
            {graph.run_reason ? ` — ${graph.run_reason}` : ""}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {(automation || create) && mode === "design" && (
          <DesignControls
            automation={automation ?? null}
            connId={create?.connId ?? automation?.conn_id ?? ""}
            name={header?.name ?? automation?.name ?? ""}
            draft={draft}
            onDraft={d => setDraft(d)}
            onSaved={(created) => {
              if (created) { onCreated?.(created); return; }
              setReloadKey(k => k + 1); onSaved?.();
            }}
            onPreview={(g) => { setPreview(g); setMode("execution"); }}
          />
        )}
        {/* DS-17 — one Deploy control, on the surface where the behaviour lives. Only for
            a SAVED chain: every door binds something to a stored record, so a draft has
            nothing to deploy and offering the menu would be offering an empty answer. */}
        {automationId && mode === "design" && (
          <DeployMenu automationId={automationId}
            onChanged={() => { setReloadKey(k => k + 1); onSaved?.(); }} />
        )}
        {header?.onRunNow && (
          <Button variant="ghost" size="sm" className="aug-fs-xs" style={{ flexShrink: 0 }}
            disabled={header.running} onClick={header.onRunNow}>
            {header.running ? "Running…" : "Run now"}
          </Button>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 220, display: "flex", gap: 8 }}>
        {/* DS-1 P2 — the rail: one slim strip of sections beside the canvas. Palette
            in design, Runs in execution (opening Runs takes you there); the active
            section re-clicked collapses. Versions joins when a store for it exists —
            the ledger's rule is "once there is more than one section", and there are
            exactly two. */}
        {(authoring || !!automationId) && (
          <div data-testid="canvas-rail" style={{ width: 34, flexShrink: 0,
            display: "flex", flexDirection: "column", gap: 4, alignItems: "center",
            paddingTop: 2 }}>
            {(!!automation || !!create) && (
              <Button variant={palette ? "secondary" : "ghost"} size="icon-sm"
                aria-label={palette ? "Collapse the palette" : "Open the palette"}
                title="Palette"
                onClick={() => {
                  if (palette) { setPalette(null); setEdgeDrop(null); return; }
                  setRunsOpen(false);
                  if (mode !== "design") { setMode("design"); setPreview(null); setRunId(""); }
                  setPalette("all");
                }}>
                <Icon name="layers" size={14} />
              </Button>
            )}
            {!!automationId && (
              <Button variant={runsOpen && mode === "execution" ? "secondary" : "ghost"}
                size="icon-sm"
                aria-label={runsOpen && mode === "execution"
                  ? "Collapse the runs list" : "Open the runs list"}
                title="Runs"
                onClick={() => {
                  if (runsOpen && mode === "execution") { setRunsOpen(false); return; }
                  setPalette(null); setEdgeDrop(null);
                  setMode("execution"); setPreview(null); setRunsOpen(true);
                }}>
                <Icon name="history" size={14} />
              </Button>
            )}
          </div>
        )}
        {mode === "execution" && runsOpen && !preview && graph && (
          <div style={{ width: 132, flexShrink: 0, overflowY: "auto",
                        border: "1px solid var(--border)", borderRadius: 8, padding: 4 }}>
            <div className="aug-fs-xs" style={{ color: "var(--t4)", padding: "2px 4px 4px" }}>
              runs
            </div>
            {(graph.runs?.length ?? 0) === 0 && (
              <div className="aug-fs-xs" style={{ color: "var(--t4)", padding: "2px 4px" }}>
                no runs yet
              </div>
            )}
            {(graph?.runs ?? []).map((r) => {
              const active = (runId || graph?.run_id) === r.id;
              return (
                <Button key={r.id} variant="ghost" size="sm" className="aug-fs-xs"
                  onClick={() => { setPreview(null); setRunId(r.id); }}
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

        {authoring && palette && (
          <AutomationPalette
            connId={automation?.conn_id}
            only={palette === "all" ? undefined : palette}
            bindFilter={edgeDrop
              ? { ref: `${edgeDrop.from}.${edgeDrop.key === "*" ? "…" : edgeDrop.key}` }
              : undefined}
            onClearBindFilter={() => setEdgeDrop(null)}
            onAdd={addFromPalette}
            onClose={() => { setPalette(null); setEdgeDrop(null); }}
          />
        )}

        <div ref={paneRef}
             onDragOver={(e) => {
               // Without this the browser refuses the drop outright — and a palette row
               // that can be picked up and not put down reads as a broken canvas.
               if (e.dataTransfer.types.includes(PALETTE_DRAG_TYPE)) {
                 e.preventDefault();
                 e.dataTransfer.dropEffect = "copy";
               }
             }}
             onDrop={(e) => {
               const placement = readPaletteDrag(e.dataTransfer.getData(PALETTE_DRAG_TYPE));
               if (!placement) return;
               e.preventDefault();
               addFromPalette(placement, rf.current?.screenToFlowPosition(
                 { x: e.clientX, y: e.clientY }));
             }}
             style={{ flex: 1, minWidth: 0, minHeight: 220, position: "relative",
                      border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          {/* §3.8b — the handlers the nodes call, provided ONCE for the whole canvas.
              In `data` they were N closures rebuilt on every memo run, so `memo` on the
              node could never hit; here they are one stable object. */}
          {mode === "design" ? (
            <NodeHandlersContext.Provider value={nodeHandlers}>
            <ReactFlow
              onInit={(instance) => { rf.current = instance; }}
              onSelectionChange={({ nodes }) => setSelectedAlias(nodes[0]?.id ?? null)}
              nodes={design.nodes}
              edges={edgesLive ? design.edges : []}
              nodeTypes={NODE_TYPES}
              onConnect={onConnect}
              onConnectEnd={onConnectEnd}
              onNodesChange={onNodesChange}
              onNodeDragStop={(_e, n) => {
                // A move is an edit: same stack, so one undo means "the last thing I
                // did" whether that was typing or dragging. Coalesced per node, so
                // nudging one card twice is one step.
                const now = Date.now();
                setHistory(h => {
                  const nextPositions = { ...h.present.positions, [n.id]: n.position };
                  persistLayout(nextPositions, new Set(design.nodes.map(node => node.id)));
                  return pushHistory(h, { ...h.present, positions: nextPositions },
                                     { key: `move:${n.id}`, at: now });
                });
                // The overlay has served its purpose for this node: history now holds the
                // position, and leaving the entry behind would let a stale live value win
                // over a later undo.
                setLivePos(prev => {
                  if (!(n.id in prev)) return prev;
                  const next = { ...prev }; delete next[n.id]; return next;
                });
              }}
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
              <Background gap={18} size={1.2} color="var(--b1)" />
              <Controls showInteractive={false} />
              {design.nodes.length >= MINIMAP_FROM && (
                <MiniMap pannable zoomable position="bottom-right"
                  ariaLabel="Chain overview"
                  nodeColor={miniNodeColor("design")} nodeStrokeWidth={0}
                  nodeBorderRadius={3}
                  bgColor="var(--bg-1)"
                  maskColor="color-mix(in srgb, var(--bg-0) 68%, transparent)"
                  style={MINIMAP_STYLE} />
              )}
              {/* The Volt frame's toolbar, ON the canvas: adding is part of designing,
                  not a trip to a side panel. Both write the same draft the rail and
                  Save share; the rail stays for the fields a node does not carry.
                  DS-1 — these now OPEN the palette, narrowed to the half they name,
                  instead of appending a kind nobody chose. Same two words, and the
                  reader picks what lands. */}
              {authoring && (
                <Panel position="top-left" style={{ display: "flex", gap: 6 }}>
                  <Button variant={palette === "trigger" ? "default" : "secondary"} size="xs"
                    aria-expanded={palette === "trigger"}
                    onClick={() => setPalette(p => (p === "trigger" ? null : "trigger"))}>
                    <Icon name="bolt" size={11} /> Add Trigger
                  </Button>
                  <Button variant={palette === "action" ? "default" : "secondary"} size="xs"
                    aria-expanded={palette === "action"}
                    onClick={() => setPalette(p => (p === "action" ? null : "action"))}>
                    <Icon name="plus" size={11} /> Add Action
                  </Button>
                  {/* The keyboard is the way this gets used; the buttons are how it gets
                      FOUND, and how their disabled state says whether there is anything
                      to walk back to. */}
                  <Button variant="secondary" size="xs" disabled={!canUndo(history)}
                    aria-label="Undo" title="Undo (⌘Z)"
                    onClick={() => walk("undo")}>
                    <Icon name="back" size={11} />
                  </Button>
                  <Button variant="secondary" size="xs" disabled={!canRedo(history)}
                    aria-label="Redo" title="Redo (⌘⇧Z)"
                    onClick={() => walk("redo")}>
                    <Icon name="next" size={11} />
                  </Button>
                </Panel>
              )}
              {pendingBind && (
                <Panel position="top-center">
                  <OutcomeKeyPicker
                    from={pendingBind.from}
                    field={pendingBind.field}
                    candidates={observed === null ? null : (observed[pendingBind.from] ?? [])}
                    onPick={(key) => bindWith(
                      pendingBind.from, pendingBind.to, pendingBind.field, key)}
                    onCancel={() => setPendingBind(null)}
                  />
                </Panel>
              )}
              {notice && (
                <Panel position="top-center">
                  <span className="aug-fs-xs" style={{ color: "var(--amb5)",
                    background: "var(--amb1)", border: "1px solid var(--amb2)",
                    borderRadius: "var(--r-chip)", padding: "3px 10px" }}>
                    {notice}
                  </span>
                </Panel>
              )}
              <Panel position="bottom-center">
                <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
                  drag a <span style={{ color: "var(--chart-2)" }}>gives</span> dot onto an
                  input dot to bind · double-click an edge to unbind · ⌘D duplicates a
                  selected step, ⌘C / ⌘V move one between chains
                </span>
              </Panel>
            </ReactFlow>
            </NodeHandlersContext.Provider>
          // B2 — `shown`, not `graph`: a PREVIEW is a graph this canvas was handed rather
          // than one it fetched, and gating the body on the fetched one left a dry run
          // reading "Loading…" underneath its own "nothing was sent" banner. Found by
          // driving it — the banner and the body were reading two different states.
          ) : !shown ? (
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
              {execution!.nodes.length >= MINIMAP_FROM && (
                <MiniMap pannable zoomable position="bottom-right"
                  ariaLabel="Run overview"
                  nodeColor={miniNodeColor("execution")} nodeStrokeWidth={0}
                  nodeBorderRadius={3}
                  bgColor="var(--bg-1)"
                  maskColor="color-mix(in srgb, var(--bg-0) 68%, transparent)"
                  style={MINIMAP_STYLE} />
              )}
            </ReactFlow>
          )}

          {/* DS-1R — the design panel as a LENS: the selected node's richer widgets
              (kind selects, "Post as…", agent pickers, guard editors), floating at the
              canvas edge. It reads the selection and writes the same draft; nothing
              edits "everything" any more — the workflow is the one primary editor. */}
          {authoring && selectedAlias && (
            <StepInspector
              draft={draft}
              onDraft={d => setDraft(d)}
              selection={selectedAlias}
              logicLabel={(automation?.condition_logic ?? "all") === "all"
                ? "all match" : "any match"}
              onClose={() => setSelectedAlias(null)}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default AutomationGraph;
