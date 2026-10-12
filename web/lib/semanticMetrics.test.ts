/**
 * Where each metric stands on the Semantic Layer's Metrics tab: the figures, "Needs you" and the list's groups.
 *
 * The fixtures are LuxExperience (`dcc63d83`) as the live API answered on 2026-10-12 — eight approved definitions,
 * four of them with no date column (Gross Margin %, Item Return Rate, Session Conversion Rate, Marketing ROAS), and two
 * retail-package metrics not bound — and theLook's shapes beside it: an approved metric with no SQL, a proposal
 * waiting for review, a draft, two retired.
 */
import { describe, expect, it } from "vitest";

import type { CatalogueMetric, Metric, RemovedProposal } from "@/lib/api";

import {
  dayWords, figures, grouped, lastDecision, missingRoles, needs, packsOf, place, shortColumn, shortUnit, standingChip,
  standingOf,
} from "./semanticMetrics";

function row(over: Partial<CatalogueMetric> = {}): CatalogueMetric {
  return {
    name: "m", label: "M", source: "defined", state: "defined", sql: "SELECT 1", unit: "", definition: "", grain: "",
    dimensions: [], tables: [], anti_patterns: [], pack_id: "", required_roles: [], missing_roles: [], sane_range: null,
    why_it_matters: "", reason: "", status: "approved", version: 1, owner: "", editable: true, schema: "luxexperience",
    ...over,
  };
}

function metric(over: Partial<Metric> = {}): Metric {
  return {
    name: "m", label: "M", sql: "SELECT 1", tables: [], dimensions: [], filters: [], unit: null, caveats: null,
    target_value: null, warning_threshold: null, critical_threshold: null, target_period: null, benchmark_source: null,
    owner: null, freshness_sla: null, freshness_check_sql: null, quality_tests: [], lineage: [], wrong_usage_examples: [],
    approved_by: "amitkamlapure", approved_at: "2026-10-12T15:22:23+00:00", status: "approved", version: 1,
    connection: "dcc63d83", schema_name: null, home_schema: "luxexperience", ...over,
  };
}

const dated = { time_kind: "flow" as const, time_column: "orders.order_date" };

// LuxExperience, as it stood.
const LUX_STORED: Metric[] = [
  metric({ name: "average_order_value_aov", label: "Average Order Value (AOV)", ...dated, approved_at: "2026-10-12T15:18:46+00:00" }),
  metric({ name: "gross_margin", label: "Gross Margin %" }),
  metric({ name: "item_return_rate", label: "Item Return Rate" }),
  metric({ name: "session_conversion_rate", label: "Session Conversion Rate" }),
  metric({ name: "markdown_penetration", label: "Markdown Penetration", time_kind: "flow", time_column: "price_history.effective_date" }),
  metric({ name: "marketing_roas", label: "Marketing ROAS" }),
  metric({ name: "clienteling_influenced_gmv_per_interaction", label: "Clienteling GMV", time_kind: "flow", time_column: "clienteling_interactions.interaction_date" }),
  metric({ name: "average_inventory_weeks_of_cover", label: "Weeks of Cover", time_kind: "flow", time_column: "inventory_snapshots.snapshot_date" }),
];
const LUX_ROWS: CatalogueMetric[] = [
  ...LUX_STORED.map(m => row({ name: m.name, label: m.label })),
  row({ name: "cart_to_order_conversion_rate", label: "Cart-to-order conversion rate", source: "industry", state: "needs_binding",
        status: "", editable: false, pack_id: "retail", missing_roles: ["cart"], required_roles: ["cart"] }),
  row({ name: "return_rate", label: "Return rate", source: "industry", state: "needs_binding", status: "", editable: false,
        pack_id: "retail", missing_roles: ["order_item"], required_roles: ["order_item"] }),
];

describe("LuxExperience — why its metrics did not read as measured", () => {
  const placed = place(LUX_ROWS, LUX_STORED);

  it("counts four approved and measured of eight, four that can't be measured, two not bound", () => {
    const f = figures(placed);
    expect(f).toMatchObject({ approved: 8, measured: 4, noDate: 4, noSql: 0, unchecked: 0, review: 0, notBound: 2 });
  });

  it("names the four with no date column, together, as one thing that needs a person", () => {
    const n = needs(placed);
    expect(n.map(x => x.kind)).toEqual(["no_date", "not_bound"]);
    expect(n[0].items.map(p => p.row.label)).toEqual(["Gross Margin %", "Item Return Rate", "Session Conversion Rate", "Marketing ROAS"]);
  });

  it("says which package and which data an unbound metric is waiting on, each once", () => {
    const unbound = needs(placed).find(x => x.kind === "not_bound")!;
    expect(packsOf(unbound.items)).toEqual(["retail"]);
    expect(missingRoles(unbound.items)).toEqual(["cart", "order_item"]);
  });

  it("groups the list: approved first, the unbound industry metrics apart", () => {
    expect(grouped(placed).map(g => [g.id, g.items.length])).toEqual([["approved", 8], ["not_bound", 2]]);
  });

  it("folds the day's batch of approvals into one count", () => {
    expect(lastDecision(LUX_STORED, [])).toMatchObject({ action: "approved", count: 8, by: "amitkamlapure" });
  });
});

describe("where one row stands", () => {
  it("an approved definition with SQL and a date is measured; without a date it is not", () => {
    expect(standingOf(row(), metric(dated))).toBe("measured");
    expect(standingOf(row(), metric())).toBe("no_date");
  });

  it("no SQL comes before no date — nothing can be dated without a statement", () => {
    expect(standingOf(row({ sql: "" }), metric({ sql: "" }))).toBe("no_sql");
  });

  it("an approved row whose definition could not be read is 'not checked' — never guessed either way", () => {
    expect(standingOf(row(), undefined)).toBe("unchecked");
    expect(figures(place([row()], []))).toMatchObject({ approved: 1, measured: 0, noDate: 0, unchecked: 1 });
    expect(needs(place([row()], []))).toEqual([]);
  });

  it("reads the governance status: proposed waits for review, deprecated is retired, anything else a draft", () => {
    expect(standingOf(row({ status: "proposed" }), metric({ status: "proposed" }))).toBe("proposed");
    expect(standingOf(row({ status: "deprecated" }), metric({ status: "deprecated" }))).toBe("retired");
    expect(standingOf(row({ status: "draft" }), metric({ status: "draft" }))).toBe("draft");
    expect(standingOf(row({ status: "" }), metric({ status: undefined }))).toBe("draft");
  });

  it("a suggestion keeps a rejected statement apart from a missing one", () => {
    expect(standingOf(row({ source: "explorer", state: "proposed" }), null)).toBe("suggested");
    expect(standingOf(row({ source: "explorer", state: "needs_formula" }), null)).toBe("needs_sql");
    expect(standingOf(row({ source: "explorer", state: "formula_rejected" }), null)).toBe("sql_rejected");
  });
});

describe("theLook's shapes", () => {
  const stored = [
    metric({ name: "revenue", label: "Revenue", ...dated }),
    metric({ name: "cart_to_order_conversion_rate", label: "Cart-to-order conversion rate", sql: "", ...dated }),
    metric({ name: "average_delivery_time", label: "Average Delivery Time", status: "proposed", approved_at: null,
             approved_by: null, proposed_by: "amitkamlapure", proposed_at: "2026-10-08T07:33:36+00:00", ...dated }),
    metric({ name: "sales_volume_by_category", label: "Sales Volume by Category", status: "draft", approved_at: null }),
    metric({ name: "gross_margin_rate", label: "Gross Margin Rate", status: "deprecated", ...dated }),
  ];
  const rows = stored.map(m => row({ name: m.name, label: m.label, sql: m.sql, status: m.status ?? "" }));
  const placed = place(rows, stored);

  it("puts the decision first, then the approved metric with no SQL", () => {
    expect(needs(placed).map(n => [n.kind, n.items.map(p => p.row.name)])).toEqual([
      ["review", ["average_delivery_time"]],
      ["no_sql", ["cart_to_order_conversion_rate"]],
    ]);
  });

  it("folds the retired group and keeps drafts out of Needs you", () => {
    const g = grouped(placed);
    expect(g.map(x => x.id)).toEqual(["approved", "review", "draft", "retired"]);
    expect(g.find(x => x.id === "retired")?.folded).toBe(true);
    expect(figures(placed)).toMatchObject({ approved: 2, measured: 1, noSql: 1, review: 1, drafts: 1, retired: 1 });
  });

  it("flags a name defined twice in one dataset as needing a person", () => {
    const twice = place([row({ name: "revenue" })], [metric({ name: "revenue", ...dated }), metric({ name: "revenue", ...dated })]);
    expect(twice[0].duplicate).toBe(true);
    expect(needs(twice).map(n => n.kind)).toEqual(["duplicate"]);
  });
});

describe("the last decision", () => {
  it("is a removal when that came last, and names the one metric when there was one", () => {
    const removed: RemovedProposal[] = [{ connection: "c", schema_name: "*", name: "nmr", label: "Net Merchandise Revenue",
      source: "defined", by: "amitkamlapure", at: "2026-10-13T10:39:51+00:00" }];
    expect(lastDecision(LUX_STORED, removed)).toMatchObject({ action: "removed", count: 1, label: "Net Merchandise Revenue" });
  });

  it("is nothing when nothing is dated — never a made-up day", () => {
    expect(lastDecision([metric({ approved_at: null })], [])).toBeNull();
  });
});

describe("short words", () => {
  it("a unit keeps its first words; the rest stays on the definition", () => {
    expect(shortUnit("EUR, typically 300-2000 for luxury multi-brand orders")).toBe("EUR");
    expect(shortUnit("ratio 0-1 (e-commerce typically 0.005-0.05)")).toBe("ratio 0-1");
    expect(shortUnit(null)).toBe("");
  });

  it("a date column drops the project and dataset in front", () => {
    expect(shortColumn("bigquery-public-data.thelook_ecommerce.events.created_at")).toBe("events.created_at");
    expect(shortColumn("orders.order_date")).toBe("orders.order_date");
  });

  it("a day reads as today, yesterday, or its date", () => {
    const now = new Date(2026, 9, 12, 21, 0);
    expect(dayWords(new Date(2026, 9, 12, 9, 0).toISOString(), now)).toBe("today");
    expect(dayWords(new Date(2026, 9, 11, 9, 0).toISOString(), now)).toBe("yesterday");
    expect(dayWords(new Date(2026, 9, 8, 9, 0).toISOString(), now)).toBe("8 Oct");
    expect(dayWords(new Date(2025, 9, 8, 9, 0).toISOString(), now)).toBe("8 Oct 2025");
  });

  it("each state wears its meaning: amber needs a person, violet is a suggestion, green is measured", () => {
    const [measured, noDate] = place([row({ name: "a" }), row({ name: "b" })], [metric({ name: "a", ...dated }), metric({ name: "b" })]);
    expect(standingChip(measured)).toMatchObject({ tone: "up", text: "✓ measured" });
    expect(standingChip(noDate)).toMatchObject({ tone: "amber", text: "no date column" });
    const [s] = place([row({ source: "industry", state: "proposed", pack_id: "retail", status: "" })], []);
    expect(standingChip(s)).toMatchObject({ tone: "violet", text: "suggested · retail package" });
  });
});
