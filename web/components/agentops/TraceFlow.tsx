"use client";

/**
 * VA-5 · the node view — one run drawn as a canvas of nodes, left to right.
 *
 * **Why this is not the waterfall.** The waterfall answers "where did the time go",
 * laying every node on one axis. It cannot answer "what ran under what", because a time
 * axis flattens nesting by construction: a delegate's work and its supervisor's occupy
 * the same stretch of wall clock and end up side by side. This answers the second
 * question and gives up the first.
 *
 * **Why it can exist now.** Until delegation shipped, a trace had almost no real
 * parentage — which is why `flow_edges` originally returned `zip(nodes, nodes[1:])`.
 * Rendering that as a graph would have drawn a straight line and called it one. The
 * edges are structural now, so there is something to draw.
 *
 * **Layout is deterministic, not simulated.** A run has an inherent reading order — the
 * sequence it happened in — so positions are computed, never settled by a force. The
 * same run opened twice looks identical, which is the property a debugging surface needs
 * and a force-directed graph cannot promise. Roots form a horizontal spine in `seq`
 * order; a node's children hang one column to the right, stacked, and the next root
 * starts clear of the whole subtree.
 *
 * ── VA-4e: THE ARRANGEMENT ───────────────────────────────────────────────────
 * The canvas above was right and read flat: every node was the same rectangle, so the
 * shape of a run had to be read word by word. Two changes, both presentation:
 *
 *   - **Typed faces** (`RunNodes.tsx`). A trigger, a guardrail, a model call, a tool and
 *     the final response now each show the fields they actually have. Same rows, same
 *     endpoint — a guardrail's verdict was always in `payload.blocked`, and was being
 *     rendered as an anonymous dot named "pii".
 *   - **A docked rail.** Where the run came from, what it cost, and every node as a
 *     clickable index — so a 24-node canvas is navigable without hunting across it.
 *     Selecting a row centres its node and opens it, which is the affordance a canvas
 *     needs the moment it is bigger than the viewport.
 *
 * Nothing new is recorded and no node is invented: a run with no `user_request` row gets
 * no trigger card, and its origin is stated in the rail from the built-in agent and
 * connection it did record. A synthesised head node would be indistinguishable from a
 * real one.
 *
 * (An earlier version of this file rendered a nested list and argued that avoided a
 * dependency. It did not: `@xyflow/react` has been in this app since #178 and drives two
 * other canvases. The argument was wrong on the facts, so the canvas is the better
 * answer — same library, same design system, and pan/zoom/fit come with it.)
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  CARD_W, FACE_META, FaceHeader, FieldRow, ProseBlock, UsageBlock,
  faceOf, guardVerdict, ms, originOf, type RunFace, type RunOrigin,
} from "@/components/agentops/RunNodes";
import type { SessionEvent, TimelineNode, TraceFlowEdge, TraceTimeline } from "@/lib/api";
import { formatCount } from "@/lib/format";

/** Card geometry. Columns clear a card; rows clear a usage block. */
const COL_W = 260;
/** Above this many nodes a run stops being readable end to end — measured on the live
 *  instance, where the median trace is 10 nodes and the long ones are 71 to 239. */
const GROUP_THRESHOLD = 24;
const ROW_H = 138;

interface FlowNode extends TimelineNode {
  children: FlowNode[];
}

/**
 * Roots in `seq` order, each carrying its children.
 *
 * Built from the EDGES rather than by re-reading `parent_span_id`, so the picture and
 * the contract cannot drift: whatever the backend calls a child edge is what nests here.
 */
export function buildForest(nodes: TimelineNode[], edges: TraceFlowEdge[]): FlowNode[] {
  const byId = new Map<string, FlowNode>(nodes.map(n => [n.id, { ...n, children: [] }]));
  const claimed = new Set<string>();
  const parentOf = new Map<string, string>();

  /** Would linking parent→child close a loop? Walk up from the prospective parent. */
  const wouldCycle = (parentId: string, childId: string): boolean => {
    let p: string | undefined = parentId;
    for (let hops = 0; p && hops <= nodes.length; hops++) {
      if (p === childId) return true;
      p = parentOf.get(p);
    }
    return false;
  };

  for (const e of edges) {
    if (e.kind !== "child") continue;
    const parent = byId.get(e.from);
    const child = byId.get(e.to);
    if (!parent || !child || claimed.has(child.id) || parent.id === child.id) continue;
    // A cycle is refused EDGE BY EDGE rather than detected afterwards. Claiming both
    // ends first and cleaning up later loses them: with a→b and b→a every node is some
    // node's child, the root list comes back empty, and the whole run disappears from
    // the view. Dropping the edge that closes the loop keeps the run readable and costs
    // only the one relationship that could not be true.
    if (wouldCycle(parent.id, child.id)) continue;
    parent.children.push(child);
    parentOf.set(child.id, parent.id);
    claimed.add(child.id);
  }
  return nodes.filter(n => !claimed.has(n.id)).map(n => byId.get(n.id)!).filter(Boolean);
}

/* ── stacking a run of like nodes ─────────────────────────────────────────────────
 *
 * The Flow tab drew one card per node, and a long run could not be read end to end at
 * any zoom. Measured on the live instance: the median trace is 10 nodes; the long ones
 * are 71, 104, 118 and 239.
 *
 * **A stack means N of the SAME thing.** Two model calls in a row are one stack of two;
 * two model calls with a tool call between them are two separate cards, however alike
 * they look. That is the whole rule, and it is what keeps a stack honest: expanding one
 * can only ever show more of what its face already said.
 *
 * An earlier draft folded the repeating CYCLE instead — `llm · llm · sql · pii` ×48 as a
 * single card. It compressed far harder (239 nodes to 12 cards against 144 this way) and
 * it was wrong: a card standing for four different kinds of work is not a stack, it is a
 * summary wearing a stack's clothes, and a reader cannot tell from its face what
 * expanding it will show.
 *
 * The rest of the rules follow from the same place — a stack may compress the picture,
 * never change it:
 *
 * * **Contiguous only.** A stack occupies one position in a chain that means order.
 *   Gathering like nodes from across the run would draw a sequence that never ran.
 * * **A failure is never stacked away.** Any node that did not succeed breaks the run and
 *   is drawn as itself. The alternative — a stack with a small "1 failed" on it — puts
 *   the one thing a reader is looking for one click further away than everything else.
 */

/** What makes two nodes the same THING: their face and their name. Never duration — two
 *  calls to one model are the same step at any speed. */
function stepSignature(node: TimelineNode): string {
  return `${node.event_kind || node.kind || ""}\u0000${node.name || ""}`;
}

function succeeded(node: TimelineNode): boolean {
  return node.ok !== false && !node.error_class;
}

/** Two in a row is a stack. The reference frame stacks identical nodes on sight, and a
 *  pair already halves what a reader has to scan past. */
const MIN_STACK = 2;

export interface FlowBand {
  kind: "band";
  id: string;
  /** The like nodes it stands for, in order. */
  members: FlowNode[];
  reps: number;
}

export type FlowItem = { kind: "node"; node: FlowNode } | FlowBand;

/**
 * The root sequence with each run of like nodes stacked. Pure, and exported because this
 * is where the whole feature can be wrong — jsdom draws zero edges, so nothing about a
 * canvas can catch it.
 */
export function foldRepeats(roots: FlowNode[]): FlowItem[] {
  const items: FlowItem[] = [];
  let i = 0;

  while (i < roots.length) {
    // A failure anchors the sequence: drawn as itself, and no stack may run through it.
    if (!succeeded(roots[i])) {
      items.push({ kind: "node", node: roots[i] });
      i += 1;
      continue;
    }
    const sig = stepSignature(roots[i]);
    let end = i + 1;
    while (end < roots.length
           && succeeded(roots[end])
           && stepSignature(roots[end]) === sig) end++;

    const run = end - i;
    if (run >= MIN_STACK) {
      const members = roots.slice(i, end);
      items.push({ kind: "band", id: `band:${members[0].id}`, members, reps: run });
    } else {
      items.push({ kind: "node", node: roots[i] });
    }
    i = end;
  }
  return items;
}

/** A stack, as the one node the canvas draws in its place.
 *
 *  Synthetic on purpose: `layoutForest` and the edge filter both key on node ids, so a
 *  stack that IS a node needs neither of them changed — the members simply stop being
 *  drawn, and their edges fall out of the existing `drawn` filter on their own.
 */
export function bandAsNode(band: FlowBand): FlowNode {
  const first = band.members[0];
  const total = band.members.reduce((sum, m) => sum + (m.duration_ms || 0), 0);
  return { ...first, id: band.id, duration_ms: total, children: [] };
}

/** `{id: {col, row}}` for every node. Pure, and exported so the layout is testable
 *  without mounting a canvas. */
export function layoutForest(forest: FlowNode[]): Map<string, { col: number; row: number }> {
  const pos = new Map<string, { col: number; row: number }>();
  let col = 0;

  for (const root of forest) {
    pos.set(root.id, { col, row: 0 });
    // Depth-first, so a subtree reads top-to-bottom in the order it ran. `row` is a
    // running counter rather than the child's index: two children with children of
    // their own must not be dealt the same row.
    let row = 1;
    let widest = 0;
    const walk = (node: FlowNode, depth: number) => {
      for (const child of node.children) {
        pos.set(child.id, { col: col + depth, row: row++ });
        widest = Math.max(widest, depth);
        walk(child, depth + 1);
      }
    };
    walk(root, 1);
    // Clear the whole subtree before the next root, so columns never collide.
    col += widest + 1;
  }
  return pos;
}

/** The stored row behind a node, or null when nothing matched.
 *
 *  Matched on `span_id` first and `seq` second. A node IS an event — the timeline is
 *  built from these rows — but a frame without a span has only its sequence number to be
 *  found by, and matching on seq alone would pair a node with whatever row happened to
 *  share its number in a run that recorded spans out of order. */
export function eventForNode(node: TimelineNode, events: SessionEvent[]): SessionEvent | null {
  if (node.span_id) {
    const bySpan = events.find(e => e.span_id === node.span_id);
    if (bySpan) return bySpan;
  }
  return events.find(e => e.seq === node.seq) ?? null;
}

/** What a payload says, without pretending it says more than it does. */
function payloadText(event: SessionEvent | null): string | null {
  if (!event?.payload || Object.keys(event.payload).length === 0) return null;
  try {
    return JSON.stringify(event.payload, null, 2);
  } catch {
    return null;
  }
}

/** A clock time, for a card that answers "when", not "how long". */
function clockOf(at: string | null | undefined): string {
  if (!at) return "—";
  return String(at).replace("T", " ").slice(11, 19);
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
      <span style={{ color: "var(--t4)", flexShrink: 0 }}>{label}</span>
      <span style={{ color: "var(--t2)", textAlign: "right", overflowWrap: "anywhere" }}>{value}</span>
    </div>
  );
}

/* ── the card ────────────────────────────────────────────────────────────────── */

interface CardData {
  node: TimelineNode;
  event: SessionEvent | null;
  face: RunFace;
  open: boolean;
  selected: boolean;
  onToggle: () => void;
  /** The run's roll-up, carried on the response card because that is where a reader
   *  looks for what the whole run cost. */
  runUsage?: TraceTimeline["usage"] | null;
  /** The final answer's headline. The detail endpoint does not carry it — the runs list
   *  does — so it is handed down rather than re-derived here from a payload that is null
   *  on every `final_response` row measured. */
  answer?: string;
  origin?: RunOrigin;
  /** Set on the FIRST node of an expanded band — the way back. On that one card only:
   *  a hundred identical "collapse" chips is the clutter this feature exists to remove. */
  regroup?: { reps: number; onCollapse: () => void };
}

/** The body a face shows. Each branch prints only fields that face genuinely has. */
function FaceBody({ data }: { data: CardData }) {
  const { node, event, face } = data;

  if (face === "trigger") {
    const question = String((event?.payload as Record<string, unknown> | undefined)
      ?.question ?? "");
    const depth = String((event?.payload as Record<string, unknown> | undefined)
      ?.depth ?? "");
    return (
      <>
        <div style={{ borderTop: "1px solid var(--border)", padding: "2px 0" }}>
          {data.origin?.service && <FieldRow label="Service" value={data.origin.service} />}
          <FieldRow label="At" value={clockOf(node.at)} />
          {depth && <FieldRow label="Depth" value={depth} />}
        </div>
        {question && <ProseBlock text={question} tone="var(--t1)" />}
      </>
    );
  }

  if (face === "response") {
    const u = data.runUsage;
    return (
      <>
        <div style={{ borderTop: "1px solid var(--border)", padding: "2px 0" }}>
          <FieldRow
            label="Status"
            value={node.ok === false ? (node.error_class || "failed") : "ok"}
            tone={node.ok === false ? "var(--red4)" : "var(--chart-2)"}
          />
        </div>
        {data.answer && <ProseBlock text={data.answer} tone="var(--t1)" />}
        {u && (u.total_tokens != null || u.prompt_tokens != null) && (
          <UsageBlock usage={{
            prompt_tokens: u.prompt_tokens ?? null,
            completion_tokens: u.completion_tokens ?? null,
            total_tokens: u.total_tokens ?? null,
          }} />
        )}
      </>
    );
  }

  if (face === "guardrail") {
    // §6.8's guardrail span: allowed or blocked, the action it took, and how much it
    // found. All three were already in the payload and none of them was on screen.
    const v = guardVerdict(event);
    return (
      <div style={{ borderTop: "1px solid var(--border)", padding: "2px 0" }}>
        <FieldRow
          label={v.blocked ? "Blocked" : "Allowed"}
          value={[v.action, v.found ? `${formatCount(v.found)} found` : ""]
            .filter(Boolean).join(" · ") || "—"}
          tone={v.blocked ? "var(--red4)" : "var(--chart-2)"}
        />
      </div>
    );
  }

  if (face === "model") {
    return (
      <>
        <div style={{ borderTop: "1px solid var(--border)", padding: "2px 0" }}>
          {node.role && <FieldRow label="Role" value={node.role} />}
          {node.provider && <FieldRow label="Provider" value={node.provider} />}
          {node.fallback === true && (
            <FieldRow label="Fallback" value="primary refused" tone="var(--amb4)" />
          )}
        </div>
        {node.usage && (node.usage.total_tokens != null || node.usage.prompt_tokens != null)
          && <UsageBlock usage={node.usage} />}
      </>
    );
  }

  if (face === "delegation" && node.delegation) {
    return (
      <div style={{ borderTop: "1px solid var(--border)", padding: "2px 0" }}
           title={`delegation path: ${node.delegation.path}`}>
        <FieldRow label="Agent" value={node.delegation.agent_name} tone="var(--chart-4)" />
        {node.delegation.depth != null && (
          <FieldRow label="Depth" value={`d${node.delegation.depth}`} />
        )}
      </div>
    );
  }

  // tool / event: what a step of work has to report is what it returned.
  const rows: React.ReactNode[] = [];
  if (node.row_count != null) {
    rows.push(<FieldRow key="rows" label="Rows" value={formatCount(node.row_count)} />);
  }
  if (event?.retries) {
    rows.push(<FieldRow key="retries" label="Retries" value={formatCount(event.retries)}
                        tone="var(--amb4)" />);
  }
  if (!rows.length) return null;
  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "2px 0" }}>{rows}</div>
  );
}

function NodeCard({ data }: { data: CardData }) {
  const { node, event, face, open, selected } = data;
  const payload = open ? payloadText(event) : null;
  const failed = node.ok === false;
  const accent = failed ? "var(--red4)" : FACE_META[face].color;
  // A guardrail that allowed everything is the run working. It gets the same face as one
  // that blocked, and a quieter frame — a canvas where every node shouts says nothing.
  const quiet = face === "guardrail" && !failed && !guardVerdict(event).blocked;

  const frame = `1px solid ${selected ? accent : "var(--border)"}`;

  return (
    <div
      style={{
        width: CARD_W,
        background: "var(--bg-2)",
        // Long-hand on all four sides, not `border` + a `borderLeft` override. React
        // warns on exactly that combination the moment the shorthand CHANGES between
        // renders — which it now does, because selecting a card recolours its frame —
        // and the warning is right: which of the two wins is render-order dependent.
        borderTop: frame,
        borderRight: frame,
        borderBottom: frame,
        borderLeft: `3px solid ${accent}`,
        borderRadius: "var(--r-chip)",
        overflow: "hidden",
        opacity: quiet ? 0.82 : 1,
        boxShadow: selected ? "var(--shadow-md)" : undefined,
      }}
    >
      {/* A custom node needs handles or its edges have nothing to anchor to and simply
          do not render — 14 nodes drew 0 edges before these existed. Hidden, because the
          anchor points are geometry, not something a reader of a finished run acts on. */}
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />

      {data.regroup && (
        <Button
          variant="ghost" size="xs" className="nodrag aug-fs-xs"
          aria-label={`Collapse these ${data.regroup.reps} repeats`}
          onClick={e => { e.stopPropagation(); data.regroup!.onCollapse(); }}
          style={{ width: "100%", justifyContent: "flex-start", gap: 5, height: "auto",
                   padding: "3px 9px", color: "var(--chart-3)",
                   borderBottom: "1px solid var(--b1)", borderRadius: 0 }}>
          <Icon name="layers" size={11} />
          collapse ×{data.regroup.reps}
        </Button>
      )}

      <FaceHeader face={face} title={node.name} duration={node.duration_ms} failed={failed} />

      <FaceBody data={data} />

      {failed && (
        <div className="aug-fs-xs" style={{ padding: "3px 9px", color: "var(--red4)",
                      borderTop: "1px solid var(--border)" }}>
          {node.error_class || "failed"}
        </div>
      )}

      {/* The card summarises; this is the row it summarises FROM. Without it the canvas
          could say a call took 9.63s and cost 806 tokens and still not say what was
          asked or answered — which is the question a person opens a trace to settle. */}
      <Button
        variant="ghost"
        size="xs"
        onClick={data.onToggle}
        className="nodrag aug-fs-xs"
        style={{
          width: "100%", display: "flex", justifyContent: "space-between",
          alignItems: "center", padding: "0 9px", borderRadius: 0,
          borderTop: "1px solid var(--border)", color: "var(--t3)",
        }}
      >
        <span>{open ? "Hide details" : "Details"}</span>
        <Icon name={open ? "chevd" : "chevr"} size={11} />
      </Button>

      {open && (
        <div
          className="nodrag nowheel aug-fs-xs"
          style={{
            borderTop: "1px solid var(--border)", padding: "6px 9px",
            maxHeight: 260, overflowY: "auto", background: "var(--bg-1)",
          }}
        >
          {event ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <DetailRow label="Kind" value={event.kind} />
              <DetailRow label="At" value={event.at} />
              {node.offset_ms != null && <DetailRow label="Offset" value={ms(node.offset_ms)} />}
              {node.gap_ms != null && <DetailRow label="Waited before" value={ms(node.gap_ms)} />}
              {event.provider && <DetailRow label="Provider" value={event.provider} />}
              {event.role && <DetailRow label="Role" value={event.role} />}
              {event.fallback === true && <DetailRow label="Fallback" value="the primary backend refused" />}
              {event.retries != null && event.retries > 0 && (
                <DetailRow label="Retries" value={formatCount(event.retries)} />
              )}
              {event.row_count != null && <DetailRow label="Rows" value={formatCount(event.row_count)} />}
              {event.error_class && <DetailRow label="Error" value={event.error_class} />}

              {payload ? (
                <>
                  <span style={{ color: "var(--t4)", marginTop: 4 }}>Payload</span>
                  <pre style={{
                    margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere",
                    color: "var(--t2)", fontFamily: "var(--font-mono)",
                  }}>{payload}</pre>
                </>
              ) : (
                <span style={{ color: "var(--t4)", marginTop: 4 }}>
                  This row carries no payload.
                </span>
              )}

              {event.content_captured === false && (
                // Absence with a reason. "No prompt here" and "prompt capture was off"
                // call for different responses, and only one of them is a bug.
                <span style={{ color: "var(--t4)" }}>
                  Prompt content was not captured for this run (obs.prompt_capture was off).
                </span>
              )}
            </div>
          ) : (
            <span style={{ color: "var(--t4)" }}>
              No stored row matched this node, so there is nothing further to show.
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** The data a stack card is drawn from. */
interface BandData {
  band: FlowBand;
  face: RunFace;
  onExpand: () => void;
  [key: string]: unknown;
}

/**
 * A run of like nodes, drawn as one card.
 *
 * It wears the FACE of the thing it stacks, because that is what makes a stack readable
 * without opening it: every node inside is this node, and the only new information is
 * how many and how long they took together. A card standing for several kinds of work
 * could not say that, which is why this stacks like with like and nothing else.
 *
 * The offset plates behind it are the affordance the request asked for; they also say,
 * without a word, that this is several nodes and not one.
 */
function BandCard({ data }: { data: BandData }) {
  const { band, face, onExpand } = data;
  const first = band.members[0];
  const total = band.members.reduce((sum, m) => sum + (m.duration_ms || 0), 0);
  const accent = FACE_META[face].color;

  return (
    <div style={{ position: "relative", width: CARD_W }}>
      {/* Inert: `pointerEvents: none`, so the whole target stays the card itself. */}
      {[2, 1].map(depth => (
        <div key={depth} aria-hidden style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          transform: `translate(${depth * 5}px, ${depth * 5}px)`,
          background: "var(--bg-2)", border: "1px solid var(--border)",
          borderRadius: "var(--r-chip)", opacity: depth === 1 ? 0.7 : 0.4,
        }} />
      ))}
      <div
        role="button"
        tabIndex={0}
        aria-label={`Expand ${band.reps} stacked ${first.name || face} nodes`}
        onClick={onExpand}
        onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onExpand(); } }}
        style={{
          position: "relative", width: CARD_W, cursor: "pointer",
          background: "var(--bg-2)",
          borderTop: "1px solid var(--border)", borderRight: "1px solid var(--border)",
          borderBottom: "1px solid var(--border)",
          borderLeft: `3px solid ${accent}`,
          borderRadius: "var(--r-chip)", overflow: "hidden",
        }}>
        <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
        <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 9px",
          borderBottom: "1px solid var(--b1)" }}>
          <span style={{ width: 7, height: 7, borderRadius: "var(--r-pill)",
            flexShrink: 0, background: accent }} />
          <span className="aug-fs-ui" style={{ fontWeight: 600, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {first.name || face}
          </span>
          <span className="aug-fs-ui" style={{ marginLeft: "auto", fontWeight: 600,
            color: accent }}>
            ×{band.reps}
          </span>
        </div>
        <div className="aug-fs-xs" style={{ padding: "6px 9px", color: "var(--t4)" }}>
          {ms(total)} total · click to expand
        </div>
        <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      </div>
    </div>
  );
}

const NODE_TYPES = { traceNode: NodeCard, bandNode: BandCard };

/* ── the rail ────────────────────────────────────────────────────────────────── */

function RailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ borderTop: "1px solid var(--b1)", padding: "7px 10px" }}>
      <div className="aug-fs-xs" style={{ color: "var(--t4)", letterSpacing: "0.06em",
        textTransform: "uppercase", marginBottom: 3 }}>{title}</div>
      {children}
    </div>
  );
}

/**
 * Where the run came from, what it cost, and every node as an index.
 *
 * The origin block is the honest replacement for a synthesised trigger node: a run
 * started inside the platform has no request row, and saying "agent: explorer ·
 * connection workspace" is a true answer where an invented head card would be a false
 * one.
 */
function TimelineRail({ timeline, nodes, origin, selectedId, onSelect }: {
  timeline: TraceTimeline;
  nodes: TimelineNode[];
  origin: RunOrigin;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const u = timeline.usage ?? {};
  return (
    <div data-testid="timeline-rail" style={{
      width: 208, flexShrink: 0, display: "flex", flexDirection: "column",
      border: "1px solid var(--border)", borderRadius: "var(--r-chip)",
      background: "var(--bg-1)", overflow: "hidden",
    }}>
      <div style={{ padding: "8px 10px" }}>
        <div className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 500 }}>Timeline</div>
        <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 1 }}>
          {formatCount(timeline.span_count ?? nodes.length)} spans
          {timeline.model_calls ? ` · ${formatCount(timeline.model_calls)} model calls` : ""}
        </div>
      </div>

      <RailSection title="Origin">
        {origin.service && <FieldRow label="Service" value={origin.service} />}
        {!origin.requested && (
          // Named, rather than left as an empty trigger slot on the canvas: this run was
          // started inside the platform, and that is a different fact from "unknown".
          <FieldRow label="Started" value="inside the platform" />
        )}
        {/* The built-in that ran it and the user's own agent are DIFFERENT facts — a
            run can have both — so they get two rows rather than one that guesses. */}
        {origin.builtinAgent && <FieldRow label="Agent" value={origin.builtinAgent} />}
        {origin.customAgent && <FieldRow label="Custom agent" value={origin.customAgent} />}
        {origin.connId && <FieldRow label="Connection" value={origin.connId} />}
        {origin.jobId && <FieldRow label="Job" value={origin.jobId} />}
      </RailSection>

      <RailSection title="Timing">
        <FieldRow label="Wall" value={ms(timeline.wall_ms)} />
        <FieldRow label="Busy" value={ms(timeline.busy_ms)} />
        <FieldRow label="Idle" value={ms(timeline.idle_ms)} />
        {!!timeline.concurrent_nodes && (
          // Wall ≠ busy + idle the moment anything overlaps, so the number that makes
          // the other three readable ships beside them rather than in a tooltip.
          <FieldRow label="Overlapped" tone="var(--amb4)"
            value={`${formatCount(timeline.concurrent_nodes)} nodes`} />
        )}
        {u.total_tokens != null && (
          <FieldRow label="Tokens" value={formatCount(u.total_tokens)} />
        )}
      </RailSection>

      <div style={{ borderTop: "1px solid var(--b1)", flex: 1, overflowY: "auto",
        padding: "4px 0" }}>
        {nodes.map(n => {
          const face = faceOf(n);
          const active = selectedId === n.id;
          return (
            <Button
              key={n.id}
              variant="ghost"
              size="sm"
              onClick={() => onSelect(n.id)}
              className="aug-fs-xs"
              style={{
                display: "flex", width: "100%", height: "auto", gap: 6, textAlign: "left",
                padding: "3px 10px", borderRadius: 0, justifyContent: "flex-start",
                background: active ? "var(--bg-sel)" : undefined,
              }}
            >
              <span style={{ color: n.ok === false ? "var(--red4)" : FACE_META[face].color,
                flexShrink: 0, display: "flex" }}>
                <Icon name={FACE_META[face].icon} size={11} />
              </span>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                textOverflow: "ellipsis", whiteSpace: "nowrap",
                color: active ? "var(--t1)" : "var(--t2)" }}>{n.name}</span>
              <span style={{ color: "var(--t4)", flexShrink: 0,
                fontVariantNumeric: "tabular-nums" }}>
                {n.duration_ms == null ? "" : ms(n.duration_ms)}
              </span>
            </Button>
          );
        })}
      </div>
    </div>
  );
}

/* ── the canvas ──────────────────────────────────────────────────────────────── */

export function TraceFlow({
  timeline,
  edges,
  events = [],
  answer,
}: {
  timeline: TraceTimeline;
  edges: TraceFlowEdge[];
  /** The trace's stored rows, so a node can show what it was built FROM. */
  events?: SessionEvent[];
  /** The run's answer headline, from the runs list. `final_response` payloads are null
   *  on every row measured, so the detail endpoint has nothing to give here. */
  answer?: string;
}) {
  // One at a time. An expanded card overlays the row beneath it — the layout is a fixed
  // grid, so it cannot make room — and several open at once turns a readable canvas into
  // stacked panels. Opening one closes the last, which is also how a person reads a run.
  const [openId, setOpenId] = useState<string | null>(null);
  const [rf, setRf] = useState<ReactFlowInstance | null>(null);
  /** The rail gives up its 208px on demand. On a narrow pane that is the difference
   *  between a canvas and a column of clipped cards. */
  const [railOpen, setRailOpen] = useState(true);
  /** Repeated stretches folded into one card each.
   *
   *  ON by default only for a run long enough to need it — the median trace measured is
   *  ten nodes, and folding what already fits on screen would be a control that changes
   *  a picture nobody was struggling with. */
  const [grouped, setGrouped] = useState(
    () => (timeline.nodes ?? []).length > GROUP_THRESHOLD);
  /** Bands the reader has opened. Ids, not indices: folding is recomputed whenever the
   *  run changes, and an index would reopen whatever landed in that slot. */
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const origin = useMemo(() => originOf(events), [events]);

  const { rfNodes, rfEdges, nested, drawnNodes, bandCount, foldedAway } = useMemo(() => {
    const forest = buildForest(timeline.nodes ?? [], edges ?? []);

    // A collapsed band stands in the layout as ONE synthetic node, so neither
    // `layoutForest` nor the edge filter below needs to know bands exist: its members
    // are simply not in `drawn`, and their edges fall out on their own.
    const items: FlowItem[] = grouped
      ? foldRepeats(forest)
      : forest.map(node => ({ kind: "node" as const, node }));
    const bands: FlowBand[] = [];
    const laidOut: FlowNode[] = [];
    for (const item of items) {
      if (item.kind === "node") laidOut.push(item.node);
      else if (expanded.has(item.id)) laidOut.push(...item.members);
      else { bands.push(item); laidOut.push(bandAsNode(item)); }
    }

    const pos = layoutForest(laidOut);
    const drawn = new Set(pos.keys());

    // The way back, on the first card of each opened band and nowhere else.
    const regroupAt = new Map<string, { reps: number; onCollapse: () => void }>();
    for (const item of items) {
      if (item.kind !== "band" || !expanded.has(item.id)) continue;
      regroupAt.set(item.members[0].id, {
        reps: item.reps,
        onCollapse: () => setExpanded(cur => {
          const next = new Set(cur);
          next.delete(item.id);
          return next;
        }),
      });
    }

    const rfNodes: RFNode[] = (timeline.nodes ?? [])
      .filter(n => drawn.has(n.id))
      .map(n => {
        const p = pos.get(n.id)!;
        const open = openId === n.id;
        return {
          id: n.id,
          type: "traceNode",
          position: { x: p.col * COL_W, y: p.row * ROW_H },
          data: {
            node: n,
            event: eventForNode(n, events),
            face: faceOf(n),
            open,
            selected: open,
            runUsage: timeline.usage ?? null,
            answer,
            origin,
            regroup: regroupAt.get(n.id),
            onToggle: () => setOpenId(cur => (cur === n.id ? null : n.id)),
          } satisfies CardData,
          draggable: true,
          // An open card has to sit above its neighbours, or the detail it exists to
          // show is drawn underneath the next node.
          zIndex: open ? 10 : 0,
        };
      });

    for (const band of bands) {
      const p = pos.get(band.id);
      if (!p) continue;
      rfNodes.push({
        id: band.id,
        type: "bandNode",
        position: { x: p.col * COL_W, y: p.row * ROW_H },
        data: {
          band,
          face: faceOf(band.members[0]),
          onExpand: () => setExpanded(cur => new Set(cur).add(band.id)),
        } satisfies BandData,
        draggable: true,
      });
    }

    // The chain across a band. The run's own `next` edges connect real nodes, so the two
    // that reached into a folded stretch vanish with its members — leaving the band
    // floating. These replace exactly those, and carry no latency label: the wait either
    // side of twenty iterations is not one number.
    const anchors = items.map(item =>
      item.kind === "node"
        ? { in: item.node.id, out: item.node.id }
        : expanded.has(item.id)
          ? { in: item.members[0].id, out: item.members[item.members.length - 1].id }
          : { in: item.id, out: item.id });
    const bridged: RFEdge[] = [];
    for (let i = 0; i + 1 < items.length; i++) {
      const spansBand = items[i].kind === "band" || items[i + 1].kind === "band";
      if (!spansBand) continue;
      const from = anchors[i].out;
      const to = anchors[i + 1].in;
      if (!drawn.has(from) || !drawn.has(to)) continue;
      bridged.push({
        id: `band-next-${from}-${to}`,
        source: from, target: to, animated: false,
        style: { stroke: "var(--b2)" },
        markerEnd: { type: MarkerType.ArrowClosed, color: "var(--b2)" },
      });
    }

    const rfEdges: RFEdge[] = (edges ?? [])
      .filter(e => drawn.has(e.from) && drawn.has(e.to))
      .map((e, i) => ({
        id: `${e.kind}-${i}-${e.from}-${e.to}`,
        source: e.from,
        target: e.to,
        // The latency is rendered ON the edge — the detail that turns boxes-and-arrows
        // into a reading of where a run waited. Only `next` edges carry one: a child
        // runs INSIDE its parent, so a number there would be a duration posing as a wait.
        label: e.kind === "next" && e.latency_ms != null ? ms(e.latency_ms) : undefined,
        animated: false,
        style: {
          stroke: e.kind === "child" ? "var(--chart-4)" : "var(--b2)",
          strokeDasharray: e.kind === "child" ? "4 3" : undefined,
        },
        // No font-size here: an edge label is a style OBJECT, so it cannot take an
        // `aug-fs-*` class, and a raw literal is what the type scale exists to prevent.
        // The renderer's default is on-scale, so the honest move is to not set one.
        labelStyle: { fill: "var(--t3)" },
        labelBgStyle: { fill: "var(--bg-1)" },
        markerEnd: { type: MarkerType.ArrowClosed, color:
          e.kind === "child" ? "var(--chart-4)" : "var(--b2)" },
      }));

    return {
      rfNodes, rfEdges: [...rfEdges, ...bridged],
      nested: forest.some(n => n.children.length > 0),
      drawnNodes: (timeline.nodes ?? []).filter(n => drawn.has(n.id)),
      bandCount: bands.length,
      foldedAway: bands.reduce((n, b) => n + b.members.length - 1, 0),
    };
  }, [timeline.nodes, timeline.usage, edges, events, openId, answer, origin,
      grouped, expanded]);

  /**
   * Re-fit when the RUN changes.
   *
   * `fitView` as a prop applies on first mount only, and this component does not remount
   * between runs — it takes new props. Measured in the browser: opening a 24-node run,
   * clicking its last rail row, then switching to a 45-node run left the viewport at
   * `scale 0.8, x 245.8` — the previous run's pan — so the new run opened wherever the
   * old one had been left rather than fitted. Nothing errored; it just showed the wrong
   * part of the right run.
   *
   * Keyed on the node IDS, not on `rfNodes`: that array is rebuilt every time a card
   * opens, and keying on it would yank the viewport back on every click.
   */
  const fitKey = rfNodes.map(n => n.id).join("|");
  useEffect(() => {
    if (!rf || !fitKey) return;
    // Deferred a frame: the nodes for the new run have to be measured before there are
    // bounds to fit to, and ReactFlow measures after commit.
    const frame = requestAnimationFrame(() => {
      // The same bounds as the prop it stands in for — an unbounded fit resolves a wide
      // run to scale 0.2, which is a picture of a run rather than a reading of one.
      rf.fitView({ minZoom: 0.55, maxZoom: 1, padding: 0.15 });
    });
    return () => cancelAnimationFrame(frame);
  }, [rf, fitKey]);

  /** Pick a node from the rail: open it AND bring it into view. A canvas wider than the
   *  viewport makes selection without centring a no-op the reader cannot see. */
  const selectNode = useCallback((id: string) => {
    setOpenId(cur => (cur === id ? null : id));
    const n = rfNodes.find(x => x.id === id);
    if (n && rf) {
      rf.setCenter(n.position.x + CARD_W / 2, n.position.y + ROW_H / 3,
                   { zoom: Math.max(0.8, rf.getZoom()), duration: 240 });
    }
  }, [rfNodes, rf]);

  if (!rfNodes.length) {
    return (
      <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
        This run recorded no nodes to draw.
      </div>
    );
  }

  return (
    <div style={{ height: "100%", minHeight: 360, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8, paddingBottom: 6 }}>
        {!nested && (
          // Say it plainly rather than presenting a chain as a graph. A run that never
          // delegated genuinely has no structure to show, and the waterfall reads better.
          <div className="aug-fs-xs" style={{ color: "var(--t3)", flex: 1 }}>
            This run is a single sequence — nothing nested inside anything else. The
            Waterfall shows the same nodes against time.
          </div>
        )}
        {/* Grouping is offered only when there is something to group — a control that
            reports "0 stacks" on a six-node run is a question the reader did not have. */}
        {(bandCount > 0 || expanded.size > 0 || (drawnNodes.length > GROUP_THRESHOLD)) && (
          <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: "auto" }}>
            {grouped && foldedAway > 0 && (
              <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
                {formatCount(foldedAway)} repeats folded
              </span>
            )}
            {grouped && expanded.size > 0 && (
              <Button variant="ghost" size="xs" className="aug-fs-xs"
                style={{ color: "var(--chart-3)" }}
                onClick={() => setExpanded(new Set())}>
                Collapse all
              </Button>
            )}
            <Button variant="ghost" size="xs" className="aug-fs-xs"
              style={{ color: grouped ? "var(--chart-3)" : "var(--t3)" }}
              aria-pressed={grouped}
              onClick={() => { setGrouped(g => !g); setExpanded(new Set()); }}>
              <Icon name="layers" size={11} />
              {grouped ? "Grouped" : "Group repeats"}
            </Button>
          </div>
        )}
        <Button variant="ghost" size="xs" className="aug-fs-xs"
          style={{ marginLeft: bandCount > 0 || expanded.size > 0 ? undefined : "auto",
                   color: "var(--t3)" }}
          onClick={() => setRailOpen(o => !o)}>
          {railOpen ? "Hide timeline" : "Timeline"}
        </Button>
      </div>
      <div style={{ flex: 1, minHeight: 320, display: "flex", gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0, border: "1px solid var(--border)",
                      borderRadius: "var(--r-chip)" }}>
          <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            nodeTypes={NODE_TYPES}
            onInit={setRf}
            fitView
            // Bounded, because an unbounded fit is not a view. A wide run fitted to the
            // container resolved to scale 0.2 — every card 7px tall and unreadable, which
            // is a picture of a run rather than a reading of one. Fit when the run is
            // small enough to fit legibly; otherwise stay legible and let the reader pan,
            // with fit-to-screen still one click away in the controls.
            fitViewOptions={{ minZoom: 0.55, maxZoom: 1, padding: 0.15 }}
            proOptions={{ hideAttribution: true }}
            minZoom={0.2}
            maxZoom={1.6}
          >
            <Background gap={16} color="var(--border)" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        {railOpen && (
          <TimelineRail
            timeline={timeline}
            nodes={drawnNodes}
            origin={origin}
            selectedId={openId}
            onSelect={selectNode}
          />
        )}
      </div>
    </div>
  );
}
