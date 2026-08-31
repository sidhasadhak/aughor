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
  Panel,
  Position,
  ReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { AutomationAuthor, type Draft } from "@/components/automations/AutomationAuthor";
import {
  AutomationPalette, PALETTE_DRAG_TYPE, readPaletteDrag,
  type PaletteGroup, type PalettePlacement,
} from "@/components/automations/AutomationPalette";
import {
  EFFECT_KINDS, newConditionOf, newEffectOf, useAutomationVocabulary,
} from "@/components/automations/AutomationRows";
import { OutcomeKeyPicker } from "@/components/automations/OutcomeKeyPicker";
import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import {
  getAutomationGraph, getAutomationVocabulary,
  type Automation, type AutomationGraphData, type GuardClause,
} from "@/lib/api";
import {
  aliasFor, applyConnect, clearBinding, draftToFlow, FAN_FIELD, GUARD_FIELD, guardSentences,
  producedByAlias, viewportCenter, type Vocabulary,
} from "@/lib/automationFlow";
import type { AutoCondition, AutoEffect } from "@/lib/api";

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
  // A guarded skip reads in the guard's own hue: it is the design working, and the dim
  // `skipped` grey is the colour of something having gone wrong.
  const fan = (data.fan ?? null) as { count: number; executed: number; skipped: number } | null;
  const accent = data.guarded ? "var(--chart-3)"
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
      {!!status && (
        <div className="aug-fs-xs" style={{ color: accent, marginTop: 4 }}>
          ● {data.dryRun && status === "executed" ? "would run"
              : data.guarded ? "held · condition not met" : status}
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
    data: { ...n, dryRun: !!graph.dry_run },
  }));

  // A data edge already implies "runs after", so a sequence edge on the same pair is
  // the same claim twice on an identical path — keep the one that carries meaning.
  const carriesData = new Set(
    graph.edges.filter((e) => e.type === "data").map((e) => `${e.from}->${e.to}`),
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
    return {
      id: `${e.type}:${e.from}->${e.to}:${e.label || i}`,
      source: e.from,
      target: e.to,
      label: isData ? e.label : undefined,
      animated: false,
      style: isData
        ? (e.guard
            ? { stroke: "var(--chart-3)", strokeWidth: 1.6, strokeDasharray: "5 4" }
            : { stroke: "var(--chart-1)", strokeWidth: 1.6 })
        : { stroke: "var(--t4)", strokeWidth: 1, strokeDasharray: "3 3" },
      markerEnd: { type: MarkerType.ArrowClosed,
                   color: isData ? (e.guard ? "var(--chart-3)" : "var(--chart-1)") : "var(--t4)" },
      data: { edgeType: e.type },
    };
  });

  return { nodes, edges };
}

/* ═══════════════════ DESIGN MODE (the draft, editable) ═══════════════════ */

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
  onPatch: (field: string, value: unknown) => void;
  onClear: (field: string) => void;
  /** Remove this step — absent on the last one, the same law the rail enforces. */
  onRemove?: () => void;
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

/** The kind's accent — one hue per kind so a chain reads as a sequence of ROLES the
 *  way the reference canvases do, not as identical grey boxes. */
const KIND_HUE: Record<string, string> = {
  investigate: "var(--chart-1)", slack_post: "var(--chart-2)", notify: "var(--chart-3)",
  brief: "var(--chart-5)", kinetic_action: "var(--chart-4)",
};

function DesignStepNode({ data, selected }: { data: DesignNodeData; selected?: boolean }) {
  // Operator WORDS come from the server's vocabulary (cached module-side, so N nodes
  // make one request) — a local map would be a second spelling of a closed set.
  const { guardOps } = useAutomationVocabulary();
  const boundOf = (field: string) =>
    data.inputs.find(i => i.field === field)?.boundTo ?? null;
  const bindableSet = new Set(data.inputs.map(i => i.field));
  const fields = PRIMARY_FIELDS[data.kind] ?? [];
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
        {data.onRemove && (
          <Button variant="ghost" size="icon-sm" aria-label={`remove ${data.alias}`}
            className="nodrag" style={{ width: 20, height: 20, color: "var(--t4)" }}
            onClick={data.onRemove}>
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
                    onClick={() => data.onClear(field)}>
                    <Icon name="close" size={10} />
                  </Button>
                </div>
              ) : (
                <input
                  className="nodrag aug-fs-sm"
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
  return c.kind;
}

function DesignTriggerNode({ data }: {
  data: { conditions: { kind: string; config: Record<string, unknown> }[]; logic: string };
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
      </div>
      <Handle type="source" position={Position.Right}
        style={{ ...portStyle("out", false), right: -(12 + PORT / 2),
                 top: "50%", transform: "translateY(-50%)" }} />
    </div>
  );
}

const NODE_TYPES = {
  step: StepNode, trigger: TriggerNode,
  designStep: DesignStepNode, designTrigger: DesignTriggerNode,
};

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
  /** B2 — a dry run's graph. Held rather than refetched, because a preview is never
   *  stored: there is no run id for the graph route to look up. It takes precedence over
   *  the server's graph while it is on screen, and any move that asks for a REAL run
   *  clears it — a preview must never be mistaken for something that happened. */
  const [preview, setPreview] = useState<AutomationGraphData | null>(null);
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
    // W1 — the fetch now carries the guard operators too; this canvas wants only the
    // per-kind ports, and `AutomationRows` fetches (and caches) the same document for
    // the "Only if" pickers.
    getAutomationVocabulary().then(v => setVocab(v.kinds)).catch(() => setVocab({}));
  }, []);

  const authoring = !!automation && mode === "design";

  // The EXECUTION graph stays the server's; fetched only when that mode is on screen.
  useEffect(() => {
    // A preview owns the canvas while it is up; refetching here would replace it with
    // the last REAL run the moment it was shown.
    if (mode !== "execution" || preview) return;
    let live = true;
    getAutomationGraph(automationId, runId || "latest")
      .then((g) => { if (live) { setGraph(g); setError(""); } })
      .catch((e) => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [automationId, mode, runId, reloadKey, preview]);

  /* ── design-mode graph, drawn from the draft ── */
  // Positions survive dragging but reset per automation — session-local by design:
  // a stored layout is a second copy of the chain's order that could drift from it.
  const positions = useRef(new Map<string, { x: number; y: number }>());
  useEffect(() => { positions.current.clear(); }, [automationId]);

  /* ── DS-4 · the open-set key picker (what replaced the window.prompt) ── */
  const [pendingBind, setPendingBind] =
    useState<{ from: string; to: string; field: string } | null>(null);
  /** Keys each step has been SEEN to publish, from the latest run. `null` = not asked
   *  yet; fetched only when a bind is actually pending, because a canvas nobody is
   *  binding on should not spend a request to populate a picker nobody opened. */
  const [observed, setObserved] = useState<Record<string, string[]> | null>(null);

  useEffect(() => {
    if (!pendingBind || observed !== null) return;
    let live = true;
    getAutomationGraph(automationId, "latest")
      .then(g => { if (live) setObserved(producedByAlias(g)); })
      // A step that never ran, or a graph we could not read, leaves the typed field as
      // the only offer — which is the honest state, not an error worth a banner.
      .catch(() => { if (live) setObserved({}); });
    return () => { live = false; };
  }, [pendingBind, observed, automationId]);

  /* ── DS-1 · the palette, and the one gate everything it offers goes through ── */
  const [palette, setPalette] = useState<PaletteGroup | "all" | null>(null);
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
      const at = position
        ?? (rf.current && pane
          ? viewportCenter(rf.current.getViewport(),
                           { width: pane.width, height: pane.height }, NODE_W)
          : null);
      if (at) positions.current.set(alias, at);
      setDraft(d => ({
        ...d, effects: [...d.effects, newEffectOf(placement.kind as AutoEffect["kind"])],
      }));
    },
    [draft.effects.length],
  );

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
      position: positions.current.get("__trigger") ?? { x: 0, y: 60 },
      data: { conditions: draft.conditions,
              logic: automation?.condition_logic ?? "all" },
    }, ...steps.map((s, i) => ({
      id: s.alias,
      type: "designStep" as const,
      position: positions.current.get(s.alias) ?? { x: 260 + i * (NODE_W + 90), y: 0 },
      data: {
        ...s,
        onPatch: (field: string, value: unknown) => patchField(s.alias, field, value),
        onClear: (field: string) => clearField(s.alias, field),
        // The last step keeps no remove control at all — the model requires one effect,
        // and an affordance that fails at save teaches the wrong law. Same rule as the
        // rail, enforced by ABSENCE both places.
        onRemove: draft.effects.length > 1
          ? () => setDraft(d => ({ ...d, effects: d.effects.filter((_, j) => j !== i) }))
          : undefined,
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
        // Animated, because the edge carries DATA — the reference frames use motion to
        // say exactly this, and only this. The sequence spine stays still.
        // W1 — a GUARD edge carries data too, but to a decision rather than a field, so
        // it reads in its own hue and dashes: same motion, different claim.
        animated: true,
        // W2 — a FAN edge carries the list a step repeats over: its own hue again, and
        // dashed for the same reason the guard's is — neither fills a field.
        style: e.guard
          ? { stroke: "var(--chart-3)", strokeWidth: 2, strokeDasharray: "5 4" }
          : e.fan
            ? { stroke: "var(--chart-2)", strokeWidth: 2, strokeDasharray: "2 3" }
            : { stroke: "var(--chart-1)", strokeWidth: 2 },
        labelStyle: { fill: "var(--t1)", fontFamily: "var(--font-mono)" },
        labelBgStyle: { fill: "var(--bg-2)", stroke: "var(--b2)" },
        labelBgPadding: [7, 3] as [number, number],
        labelBgBorderRadius: 6,
        markerEnd: { type: MarkerType.ArrowClosed,
                     color: e.guard ? "var(--chart-3)"
                          : e.fan ? "var(--chart-2)" : "var(--chart-1)" },
      })),
    ];
    return { nodes, edges: rfEdges };
  }, [draft, vocab, patchField, clearField, automation]);

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
      setConnectError(r.error);
      window.setTimeout(() => setConnectError(""), 3200);
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
  const execution = mode === "execution" && shown ? toFlow(shown) : null;

  return (
    <div style={{ height: "100%", minHeight: 260, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, paddingBottom: 6 }}>
        <div style={{ display: "inline-flex", gap: 2, padding: 2,
          border: "1px solid var(--b1)", borderRadius: "var(--r-chip)",
          background: "var(--bg-1)" }}>
          {(["design", "execution"] as const).map((m) => (
            <Button key={m} variant={mode === m ? "secondary" : "ghost"} size="xs"
              onClick={() => {
                setMode(m); setPreview(null);
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
      </div>
      <div style={{ flex: 1, minHeight: 220, display: "flex", gap: 8 }}>
        {mode === "execution" && !preview && (graph?.runs?.length ?? 0) > 0 && (
          <div style={{ width: 132, flexShrink: 0, overflowY: "auto",
                        border: "1px solid var(--border)", borderRadius: 8, padding: 4 }}>
            <div className="aug-fs-xs" style={{ color: "var(--t4)", padding: "2px 4px 4px" }}>
              runs
            </div>
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
            onAdd={addFromPalette}
            onClose={() => setPalette(null)}
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
             style={{ flex: 1, minWidth: 0, minHeight: 220,
                      border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          {mode === "design" ? (
            <ReactFlow
              onInit={(instance) => { rf.current = instance; }}
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
              <Background gap={18} size={1.2} color="var(--b1)" />
              <Controls showInteractive={false} />
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
              {connectError && (
                <Panel position="top-center">
                  <span className="aug-fs-xs" style={{ color: "var(--amb5)",
                    background: "var(--amb1)", border: "1px solid var(--amb2)",
                    borderRadius: "var(--r-chip)", padding: "3px 10px" }}>
                    {connectError}
                  </span>
                </Panel>
              )}
              <Panel position="bottom-center">
                <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
                  drag a <span style={{ color: "var(--chart-2)" }}>gives</span> dot onto an
                  input dot to bind · double-click an edge to unbind
                </span>
              </Panel>
            </ReactFlow>
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
            </ReactFlow>
          )}
        </div>

        {authoring && (
          <AutomationAuthor
            onPreview={(g) => { setPreview(g); setMode("execution"); }}
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
