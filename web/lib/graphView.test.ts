import { describe, expect, it } from "vitest";

import type { CGEdge, CGNode, ConnectionGraph, GraphReviewItem } from "@/lib/api";
import {
  EDGE_HUE, KIND_HUE, groupReview, joinsMeasured, nodeName, reviewWord, subjectName, waitingItems,
} from "@/lib/graphView";

const prov = { source: "test", measured: null, note: "" };
const node = (id: string, kind: string, label: string): CGNode =>
  ({ id, kind, label, summary: "", tags: [], provenance: prov, data: {} });
const edge = (from: string, to: string, kind: string, warrant?: "measured" | "declared"): CGEdge => ({
  id: `${from}--${kind}-->${to}`, kind, from_id: from, to_id: to, provenance: prov, label: "",
  warrant: warrant ? { warrant, detail: "", label: warrant } : undefined,
});
const graphOf = (nodes: CGNode[], edges: CGEdge[]): ConnectionGraph => ({
  org_id: "o", connection_id: "c", schema_name: "s", structural_fingerprint: "", version: 1,
  nodes: Object.fromEntries(nodes.map(n => [n.id, n])), edges: Object.fromEntries(edges.map(e => [e.id, e])),
  counts: {}, domains: [], domain_edges: [], staleness: "fresh",
});
const item = (type: GraphReviewItem["type"], subject: string, why = "because", label = subject): GraphReviewItem => ({
  id: `${type}:${subject}`, type, question: `What about ${subject}?`, why, subject_id: subject, subject_label: label,
  check: "ask", depends: 0, detail: {},
});

describe("the Graph tab's words", () => {
  it("reads a snake-cased metric key as words, and leaves every other name alone", () => {
    expect(nodeName(node("m", "metric", "average_delivery_time"))).toBe("Average delivery time");
    expect(nodeName(node("m", "metric", "Order Line Revenue"))).toBe("Order Line Revenue");
    // A column-named glossary term is a column name, not a key to translate.
    expect(nodeName(node("g", "glossary_term", "created_at"))).toBe("created_at");
    expect(nodeName(node("t", "table", "Customer Order"))).toBe("Customer Order");
  });

  it("counts joins and the measured ones off the graph's own edges — no other link counts as a join", () => {
    const g = graphOf([], [
      edge("table:A", "table:B", "joins_on", "measured"),
      edge("table:B", "table:C", "joins_on", "declared"),
      edge("table:C", "table:D", "joins_on"),
      edge("finding:x", "table:A", "grounded_in"),
    ]);
    expect(joinsMeasured(g)).toEqual({ joins: 3, measured: 1 });
  });

  it("names a review subject by the graph's names: an edge by its two ends, a node by its label", () => {
    const g = graphOf(
      [node("table:CustomerService", "table", "Customer Service"), node("table:Platform", "table", "Platform"),
        node("metric:aov", "metric", "average_order_value")],
      [edge("table:CustomerService", "table:Platform", "joins_on")],
    );
    const e = Object.keys(g.edges)[0];
    expect(subjectName(item("unprobed_join", e, "w", "CustomerService → Platform"), g)).toBe("Customer Service → Platform");
    expect(subjectName(item("undocumented_hub", "metric:aov"), g)).toBe("Average order value");
    // Nothing in the graph to name it by: the server's label stands.
    expect(subjectName(item("graph_behind", "", "w", "This connection's graph"), g)).toBe("This connection's graph");
  });

  it("folds the queue by kind in rank order, and says a reason once only when every item shares it", () => {
    const groups = groupReview([
      item("graph_behind", "g", "a rebuild would add 20"),
      item("unprobed_join", "j1", "declared, not measured"),
      item("contested_finding", "f1", "two readings"),
      item("unprobed_join", "j2", "declared, not measured"),
      item("isolated_table", "t1", "no join"),
      item("isolated_table", "t2", "no join to anything else"),
    ]);
    expect(groups.map(g => [g.type, g.items.length])).toEqual([
      ["graph_behind", 1], ["unprobed_join", 2], ["contested_finding", 1], ["isolated_table", 2],
    ]);
    expect(groups[1].why).toBe("declared, not measured");
    expect(groups[3].why).toBeNull();    // two different reasons: each row keeps its own
    expect(groups[0].why).toBeNull();    // a single item says its reason on its row
  });

  it("leaves 'the graph is behind' to the chip only when the chip says it", () => {
    const items = [item("graph_behind", "g"), item("contested_finding", "f")];
    expect(waitingItems(items, true).map(i => i.type)).toEqual(["contested_finding"]);
    expect(waitingItems(items, false).map(i => i.type)).toEqual(["graph_behind", "contested_finding"]);
  });

  it("names an unknown review kind in words rather than as a key", () => {
    expect(reviewWord("unprobed_join", 3)).toBe("Unprobed joins");
    expect(reviewWord("brand_new_kind")).toBe("brand new kind");
  });

  it("colours every kind and link through tokens, never a raw hex", () => {
    for (const v of [...Object.values(KIND_HUE), ...Object.values(EDGE_HUE)]) expect(v).toMatch(/^var\(--[a-z0-9-]+\)$/);
  });
});
