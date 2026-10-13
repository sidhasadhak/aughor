/**
 * graphView.ts — what the Graph tab says about a connection's knowledge graph, as pure functions (the panel and the
 * canvas only lay these out). Redone to `aughor-v2/CLARITY.md`, 2026-10-13: the tab leads with the picture, one line of
 * what the graph holds above it, and beside it what waits on a person — said once, repeats folded into a count.
 */
import type { CGNode, ConnectionGraph, GraphReviewItem } from "@/lib/api";
import { keyToWords } from "@/lib/names";

/** Each node kind's colour: the chart palette in its fixed order, the domain in the de-emphasis grey (it is the
 *  structure the tables hang from, not a series). Edges take the colour of the kind they start from. */
export const KIND_HUE: Record<string, string> = {
  domain: "var(--chart-deemph)",
  table: "var(--chart-1)",
  metric: "var(--chart-2)",
  finding: "var(--chart-3)",
  glossary_term: "var(--chart-5)",
  brief: "var(--chart-7)",
};

export const EDGE_HUE: Record<string, string> = {
  joins_on: KIND_HUE.table,
  derived_from: KIND_HUE.metric,
  grounded_in: KIND_HUE.finding,
  defines: KIND_HUE.glossary_term,
  resolves: KIND_HUE.domain,
};

/** A node kind as a reader says it. */
export const KIND_WORD: Record<string, string> = {
  domain: "Domain", table: "Table", metric: "Metric", finding: "Finding", glossary_term: "Term", brief: "Brief",
};

/** A node's name for the eye: a metric the semantic layer keyed in snake case (`average_delivery_time`) reads as words;
 *  every other label is already the business's name for the thing, and a column name stays a column name. */
export function nodeName(n: Pick<CGNode, "kind" | "label">): string {
  if (n.kind === "metric" && /_/.test(n.label) && !/\s/.test(n.label)) {
    const w = keyToWords(n.label);
    return w.charAt(0).toUpperCase() + w.slice(1);
  }
  return n.label;
}

/** How many joins the graph holds, and how many of them were measured against the data. */
export function joinsMeasured(graph: ConnectionGraph): { joins: number; measured: number } {
  let joins = 0;
  let measured = 0;
  for (const e of Object.values(graph.edges)) {
    if (e.kind !== "joins_on") continue;
    joins += 1;
    if (e.warrant?.warrant === "measured") measured += 1;
  }
  return { joins, measured };
}

/** What a review item is about, by name. An unprobed join's subject is an EDGE id, and the server's own label spells its
 *  two ends as entity ids (`CustomerService → Platform`); the graph knows their names. */
export function subjectName(item: GraphReviewItem, graph: ConnectionGraph | null): string {
  const node = graph?.nodes[item.subject_id];
  if (node) return nodeName(node);
  const edge = graph?.edges[item.subject_id];
  if (edge) {
    const a = graph?.nodes[edge.from_id];
    const b = graph?.nodes[edge.to_id];
    if (a && b) return `${nodeName(a)} → ${nodeName(b)}`;
  }
  return item.subject_label;
}

export const REVIEW_WORD: Record<GraphReviewItem["type"], { one: string; many: string }> = {
  graph_behind: { one: "Graph is behind", many: "Graph is behind" },
  unprobed_join: { one: "Unprobed join", many: "Unprobed joins" },
  contested_finding: { one: "Contested finding", many: "Contested findings" },
  ungrounded_finding: { one: "Ungrounded finding", many: "Ungrounded findings" },
  undocumented_hub: { one: "Undocumented hub", many: "Undocumented hubs" },
  isolated_table: { one: "Isolated table", many: "Isolated tables" },
};

/** A review kind's name, for one item or for several. An unknown kind (the server's `type` is a plain string) reads as
 *  its words, never as nothing. */
export function reviewWord(type: string, n = 1): string {
  const w = REVIEW_WORD[type as GraphReviewItem["type"]];
  if (!w) return keyToWords(type);
  return n === 1 ? w.one : w.many;
}

/** The queue's items folded by kind, in the order the queue ranks them (a kind sits where its most consequential item
 *  sat), each with the reason when every item of the kind gives the same one — so it is said once, above the rows. */
export function groupReview(items: GraphReviewItem[]): { type: string; items: GraphReviewItem[]; why: string | null }[] {
  const order: string[] = [];
  const by = new Map<string, GraphReviewItem[]>();
  for (const it of items) {
    if (!by.has(it.type)) { by.set(it.type, []); order.push(it.type); }
    by.get(it.type)!.push(it);
  }
  return order.map(type => {
    const group = by.get(type)!;
    const whys = new Set(group.map(i => i.why));
    return { type, items: group, why: group.length > 1 && whys.size === 1 ? group[0].why : null };
  });
}

/** What the map's side panel lists as waiting on a person. "The graph is behind" is left to the chip above the picture
 *  when that chip already says it (`driftShown`), so it is said once; the Review list keeps every item. */
export function waitingItems(items: GraphReviewItem[], driftShown: boolean): GraphReviewItem[] {
  return driftShown ? items.filter(i => i.type !== "graph_behind") : items;
}
