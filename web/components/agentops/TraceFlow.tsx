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
/** Up to this many cards a run reads fine as one line, so it stays one. */
const ONE_ROW_UP_TO = 6;
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

/** Roughly how tall each face's card draws, MEASURED in the browser at scale 1.
 *
 *  Only spacing depends on these, so a wrong number costs whitespace, never correctness —
 *  but a number that is too SMALL costs collisions, which is what the first block layout
 *  shipped: rows were spaced 138px while a model call draws 154, so every model card
 *  overlapped the row beneath it. Rounded up, and the row takes the tallest card in it. */
const FACE_HEIGHT: Record<RunFace, number> = {
  // Keyed by RunFace — `model`, not `llm`. Spelled wrong the first time, and the cost was
  // silent: every model card fell through to the tool height and the rows sized to it.
  model: 160, response: 160, trigger: 120, delegation: 120, guardrail: 80,
  tool: 56, event: 80,
};
const ROW_GAP = 26;
/** The longest repeating turn worth looking for — measured, the real one is 3. */
const MAX_TURN = 8;
const COL_GAP = 34;

function cardHeight(node: TimelineNode): number {
  return FACE_HEIGHT[faceOf(node)] ?? 120;
}

/**
 * The length of the run's repeating turn, or null when it has none.
 *
 * Measured on the live instance: after like-with-like stacking, both long traces are the
 * same three cards over and over — `pii · model · sql.execute` — matching at every offset
 * of three. A run with that rhythm has a structure, and a layout that cuts across it is
 * what made the first block read as a spreadsheet: rows of arbitrary width chop each turn
 * in a different place, so nothing lines up with anything and the eye finds no pattern to
 * hold on to.
 *
 * Used ONLY to choose the row width. It groups nothing and claims nothing about the cards
 * — every one stays its own card, which is the rule stacking already answers to.
 */
export function dominantPeriod(items: FlowItem[]): number | null {
  const sig = items.map(it => (it.kind === "node"
    ? stepSignature(it.node)
    : stepSignature(it.members[0])));
  if (sig.length < 8) return null;

  for (let period = 2; period <= MAX_TURN; period++) {
    if (sig.length < period * 3) break;
    // A turn has to have VARIETY in it. A run of one repeated thing matches at every
    // offset, so it "has" a period of two — which is not a rhythm, it is a run of the
    // same card, and stacking already answers that. Caught by a test built from twenty
    // identical nodes, which the first version happily laid out in turns of two.
    if (new Set(sig.slice(0, period)).size < 2) continue;
    let hits = 0;
    for (let i = 0; i + period < sig.length; i++) {
      if (sig[i] === sig[i + period]) hits++;
    }
    // The SMALLEST period that repeats almost everywhere, so the first match wins. A
    // longer one scores just as well on a perfect cycle — six is two turns of three —
    // and a reader counting turns means the short one.
    if (hits / (sig.length - period) >= 0.8) return period;
  }
  return null;
}

/**
 * A FLAT run, laid out as a block rather than a line.
 *
 * A single sequence has no tree to draw, so the tree layout gave it one long row — 68
 * cards on a measured run, which no zoom makes readable. Wrapped in reading order into a
 * landscape block, the same run is something a reader can take in.
 *
 * **The rows SNAKE.** Row 0 runs left to right, row 1 right to left, and so on, so the
 * last card of one row sits directly above the first card of the next and the step
 * between them is a short hop. Wrapping every row back to the left margin instead — the
 * obvious way, and the way this shipped first — draws one long diagonal across the whole
 * block per row. On a 68-card run that was eight of them crossing every card on the
 * canvas, which is worse than the long line it replaced.
 *
 * **Rows are as tall as the tallest card in them**, not a constant. The cards are not one
 * height — a model call draws roughly twice a tool call — and spacing them uniformly is
 * what made the first version collide.
 *
 * **An opened stack grows DOWNWARD from its own cell.** That is what keeps the run still:
 * the stack's card and everything before it do not move, where flowing its members back
 * into the sequence would shove everything after it along.
 */
export function layoutGrid(
  items: FlowItem[],
  expanded: ReadonlySet<string>,
  cell: { w: number; h: number },
): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  if (items.length === 0) return pos;

  // A run short enough to read across stays a line. Reshaping four cards into a block
  // answers a question nobody had.
  // Otherwise cols·w ≈ TARGET · rows·h ⇒ cols ≈ √(n·h·TARGET/w). TARGET is the aspect
  // being aimed AT, and it is not 1: a canvas pane is landscape, and solving for a
  // literal square put ten cards in two columns — a ribbon in a pane twice as wide as
  // it is tall.
  /** How tall one item draws: a card, or an opened stack's whole column. */
  const heightOf = (item: FlowItem): number => {
    if (item.kind === "node") return cardHeight(item.node);
    const one = cardHeight(item.members[0]);
    return expanded.has(item.id)
      ? item.members.length * (one + ROW_GAP) - ROW_GAP
      : one;
  };

  const TARGET = 1.8;
  // Measured against what a cell actually OCCUPIES — the card plus its gap, and the mean
  // card height rather than a constant. Using the bare cell missed both and came out at
  // an aspect of 2.9 where 1.8 was asked for.
  const unitW = cell.w + COL_GAP;
  // The TALLEST card, not the mean: a row is as tall as its tallest card, and with rows
  // laid out in whole turns every row contains the tall one. Using the mean under-counted
  // the height by a third and chose six columns where nine was the landscape answer.
  //
  // And COLLAPSED heights only. If the column count moved with what is open, expanding a
  // stack would re-flow the entire block — the opposite of the one thing an opened stack
  // is supposed to guarantee.
  const baseHeight = (it: FlowItem) =>
    cardHeight(it.kind === "node" ? it.node : it.members[0]);
  const unitH = Math.max(...items.map(baseHeight)) + ROW_GAP;
  const aspectOf = (c: number) =>
    (c * unitW) / (Math.ceil(items.length / c) * unitH);

  const turn = dominantPeriod(items);
  let cols: number;
  if (items.length <= ONE_ROW_UP_TO) {
    cols = items.length;
  } else if (turn) {
    // WHOLE TURNS PER ROW. Every row then starts at the same point in the cycle, so the
    // kinds line up down the columns and the run reads as the rhythm it is — instead of
    // each row chopping the turn somewhere else and the block reading as noise.
    // Which multiple is chosen by aspect rather than by rounding: rounding 7.2 to the
    // nearest multiple of 3 gives 6, and 6 columns of 68 cards is a portrait ribbon in a
    // landscape pane.
    let bestK = 1;
    for (let k = 1; k <= 6; k++) {
      if (turn * k > items.length) break;
      if (Math.abs(aspectOf(turn * k) - TARGET) < Math.abs(aspectOf(turn * bestK) - TARGET)) {
        bestK = k;
      }
    }
    cols = turn * bestK;
  } else {
    cols = Math.max(1, Math.round(Math.sqrt((items.length * unitH * TARGET) / unitW)));
  }
  // A run laid out in whole turns must NOT snake: reversing every other row would flip
  // half the turns back to front and throw away the alignment that makes it readable.
  const snake = !turn;

  const rowHeights: number[] = [];
  items.forEach((item, i) => {
    const row = Math.floor(i / cols);
    rowHeights[row] = Math.max(rowHeights[row] ?? 0, heightOf(item));
  });
  const tops: number[] = [];
  let y = 0;
  for (let r = 0; r < rowHeights.length; r++) {
    tops[r] = y;
    y += rowHeights[r] + ROW_GAP;
  }

  items.forEach((item, i) => {
    const row = Math.floor(i / cols);
    const within = i % cols;
    // Serpentine: odd rows run the other way, so the step from the end of one row to the
    // start of the next is a hop straight down rather than a diagonal across everything.
    const col = snake && row % 2 === 1 ? cols - 1 - within : within;
    const x = col * unitW;
    const top = tops[row];
    if (item.kind === "node") {
      pos.set(item.node.id, { x, y: top });
    } else if (expanded.has(item.id)) {
      const step = cardHeight(item.members[0]) + ROW_GAP;
      item.members.forEach((m, k) => pos.set(m.id, { x, y: top + k * step }));
    } else {
      pos.set(item.id, { x, y: top });
    }
  });
  return pos;
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
  /** The front card, built exactly as any other node's is — see `BandCard`. */
  card: CardData;
  onExpand: () => void;
  [key: string]: unknown;
}

/**
 * A run of like nodes, drawn as that node with copies behind it.
 *
 * **The front card is a REAL node card, in its ordinary state.** An earlier pass replaced
 * it with a condensed two-line summary, and that was the wrong trade: the default card is
 * what a reader already knows how to read, and every node in the stack is that node — so
 * shrinking it removed the familiar thing and put a new thing in its place, to save
 * vertical room the layout was not short of. The reference frame stacks whole nodes for
 * the same reason.
 *
 * The only additions are the offset plates behind it and the count on top. The plates are
 * the affordance the request asked for; they also say, without a word, that this is
 * several nodes and not one. The duration on the face is the stack's TOTAL
 * (`bandAsNode`), which is the one number that would otherwise be wrong.
 */
function BandCard({ data }: { data: BandData }) {
  const { band, card, onExpand } = data;
  const accent = FACE_META[card.face].color;
  const label = `Expand ${band.reps} stacked ${card.node.name || card.face} nodes`;

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
        aria-label={label}
        onClick={onExpand}
        onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onExpand(); } }}
        style={{ position: "relative", cursor: "pointer" }}>
        <NodeCard data={card} />
        <span
          aria-hidden
          style={{
            position: "absolute", top: -7, right: -7,
            padding: "1px 7px", borderRadius: "var(--r-pill)",
            background: "var(--bg-1)", border: `1px solid ${accent}`, color: accent,
          }}
          className="aug-fs-xs">
          ×{band.reps}
        </span>
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
  // Hidden by default. It is a companion to the canvas, not a frame around it, and it
  // was taking 208px from the thing the surface is for before anyone asked it to.
  const [railOpen, setRailOpen] = useState(false);
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

    // A flat run is a sequence, so it wraps into a block; a nested one has a shape of its
    // own and keeps the tree layout, which is the only thing that can show it. The notice
    // above the canvas already tells the reader which of the two they are looking at.
    const nestedRun = forest.some(n => n.children.length > 0);
    const pos: Map<string, { x: number; y: number }> = nestedRun
      ? new Map([...layoutForest(laidOut)].map(([id, p]) =>
          [id, { x: p.col * COL_W, y: p.row * ROW_H }]))
      : layoutGrid(items, expanded, { w: COL_W, h: ROW_H });
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
          position: { x: p.x, y: p.y },
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
        position: { x: p.x, y: p.y },
        data: {
          band,
          // Built through the same path as any other card, off the synthetic node — so
          // the stack's face is the node's face, not a second rendering of it that could
          // drift. `bandAsNode` carries the stack's TOTAL duration.
          card: {
            node: bandAsNode(band),
            event: eventForNode(band.members[0], events),
            face: faceOf(band.members[0]),
            open: false,
            selected: false,
            runUsage: timeline.usage ?? null,
            answer,
            origin,
            onToggle: () => setExpanded(cur => new Set(cur).add(band.id)),
          },
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
      nested: nestedRun,
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
  // Keyed on the RUN's nodes, never on the drawn ones.
  //
  // Those differ the moment a stack opens, and keying on what is drawn made expanding one
  // re-fit the whole canvas: the reader clicked a card to see inside it and the viewport
  // jumped somewhere else, losing the very node they were looking at. Reported from the
  // browser, and invisible to every test that does not drive it.
  //
  // With this key nothing moves on expand — the stack's first member takes the stack's
  // own column, so the card under the cursor stays exactly where it was and only what
  // lies to its right shifts along. A re-fit is still one click away in the controls.
  const fitKey = (timeline.nodes ?? []).map(n => n.id).join("|");
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
      {/* Wraps rather than squeezes. The stacking controls made this row three items
          longer, and on a narrow pane a plain `flex: 1` note gave up its width first —
          measured at a ~310px canvas, where it collapsed into a column one word wide
          while the buttons stayed put. The note takes a whole line before it does that. */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8, paddingBottom: 6,
                    flexWrap: "wrap" }}>
        {!nested && (
          // Say it plainly rather than presenting a chain as a graph. A run that never
          // delegated genuinely has no structure to show, and the waterfall reads better.
          <div className="aug-fs-xs" style={{ color: "var(--t3)", flex: "1 1 260px",
                                              minWidth: 0 }}>
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
