/**
 * The Spend screen's figures and folds. What must never change: a total with unpriced calls under
 * it reads as a floor, a total with no priced call under it is not a number, an unpriced model is
 * marked unknown, and a governance flag the platform raised on its own reads is named as that.
 */
import { describe, expect, it } from "vitest";

import { CALLER_FEATURES, type AuditFeedEvent, type UsageReport, type UsageRow, type UsageSummary } from "@/lib/api";
import {
  actionWords, failedLine, foldFeed, modelBars, modelName, sinceWords, spendTotals, spentFigure, tokens,
  unpricedModels, whereTokensGo,
} from "@/lib/spend";

function usageRow(over: Partial<UsageRow>): UsageRow {
  return {
    provider: "openrouter", model: "m", calls: 10, failures: 0, prompt_tokens: 0, completion_tokens: 0,
    total_tokens: 1000, calls_without_usage: 0, unpriced_calls: 0, cost_usd: 0, cost_is_complete: true,
    mean_ms: 100, failure_rate: 0, ...over,
  };
}

const report = (rows: UsageRow[]): UsageReport => ({
  axes: ["provider", "model"], total_calls: rows.reduce((n, r) => n + r.calls, 0), rows, unattributed: {},
});

describe("the spent figure", () => {
  it("is a floor while any call is unpriced, and says how much is priced", () => {
    const f = spentFigure(spendTotals(report([
      usageRow({ model: "deepseek/deepseek-v4.1-flash", calls: 514, cost_usd: 1.765142 }),
      usageRow({ provider: "gemini", model: "gemini-3.1-flash-lite", calls: 1326, unpriced_calls: 1308, cost_is_complete: false }),
    ])));
    expect(f).toMatchObject({ label: "Spent · at least", value: "$1.77", caveat: "29% of calls priced", unknown: false });
  });

  it("is not a number when no call is priced — never $0.00", () => {
    const f = spentFigure(spendTotals(report([usageRow({ calls: 5, unpriced_calls: 5, cost_is_complete: false })])));
    expect(f).toMatchObject({ value: "Unknown", caveat: "no call priced", unknown: true });
  });

  it("never rounds a small priced share down to 0%", () => {
    const f = spentFigure(spendTotals(report([usageRow({ calls: 1000, unpriced_calls: 996, cost_is_complete: false })])));
    expect(f.caveat).toBe("<1% of calls priced");
  });

  it("is a plain total when every call is priced", () => {
    const f = spentFigure(spendTotals(report([usageRow({ cost_usd: 2.5 })])));
    expect(f).toMatchObject({ label: "Spent", value: "$2.50", caveat: null, note: "every call priced" });
  });

  it("names the model most calls failed on", () => {
    const t = spendTotals(report([
      usageRow({ model: "a", calls: 100, failures: 2 }),
      usageRow({ model: "vendor/b", calls: 100, failures: 30 }),
    ]));
    expect(failedLine(t)).toBe("16.0% · most on vendor/b");
    expect(failedLine(spendTotals(report([usageRow({})])))).toBe("no call failed");
  });
});

describe("tokens by model", () => {
  it("marks an unpriced model unknown and says a free one is free", () => {
    const bars = modelBars(report([
      usageRow({ provider: "gemini", model: "gemini-3.1-flash-lite", total_tokens: 4_476_728, calls: 1326, unpriced_calls: 1308 }),
      usageRow({ model: "nvidia/nemotron-3-super:free", total_tokens: 84_936, calls: 8 }),
      usageRow({ model: "deepseek/deepseek-v4.1-flash", total_tokens: 4_399_585, calls: 514, cost_usd: 1.77 }),
    ]));
    expect(bars.map(b => [b.name, b.unpriced, b.sub])).toEqual([
      ["gemini-3.1-flash-lite", true, "gemini · 1,326 calls"],
      ["deepseek-v4.1-flash", false, "openrouter · 514 calls · $1.77"],
      ["nvidia/nemotron-3-super:free", false, "openrouter · 8 calls · free"],
    ]);
    expect(tokens(4_476_728)).toBe("4.48M");
    expect(tokens(166_761)).toBe("167K");
  });

  it("folds the models past the top few into one row, unknown if any of them is", () => {
    const rows = Array.from({ length: 8 }, (_, i) => usageRow({ model: `m${i}`, total_tokens: 1000 - i, unpriced_calls: i === 7 ? 1 : 0 }));
    const bars = modelBars(report(rows), 6);
    expect(bars).toHaveLength(6);
    expect(bars[5]).toMatchObject({ name: "3 more models", folded: true, unpriced: true, tokens: 995 + 994 + 993 });
  });

  it("lists the unpriced models, most calls first", () => {
    expect(unpricedModels(report([
      usageRow({ model: "a", unpriced_calls: 2 }), usageRow({ model: "b" }), usageRow({ model: "c/d", unpriced_calls: 9 }),
    ]))).toEqual([{ name: "c/d", calls: 9 }, { name: "a", calls: 2 }]);
  });

  it("drops a vendor prefix only when the model's own name repeats it", () => {
    expect(modelName("deepseek/deepseek-v4.1-flash")).toBe("deepseek-v4.1-flash");
    expect(modelName("typesafe/jev-router")).toBe("typesafe/jev-router");
    expect(modelName("gemini-3.1-flash-lite")).toBe("gemini-3.1-flash-lite");
  });
});

describe("where tokens go", () => {
  const summary = (sites: UsageSummary["sites"], calls: number, tokens: number) =>
    ({ calls, tokens, sites } as unknown as UsageSummary);
  const site = (caller: string, calls: number, total_tokens: number) =>
    ({ caller, calls, total_tokens, prompt_tokens: 0, calls_without_usage: 0 });

  it("names what the tokens were spent on, and counts the rest as Other", () => {
    // The mockup's own window: the deep-analysis sites fold into one row, and "Other" is the
    // window's total less the named rows — which counts sites past the summary's top twelve.
    // The deep-analysis module is read from the table, not restated here.
    const deep = CALLER_FEATURES.find(([, f]) => f === "deep_analysis")?.[0] ?? "";
    const rows = whereTokensGo(summary([
      site("aughor.agent.tool_loop:run_tool_loop", 9, 49_460),
      site("aughor.agent.explore:build_analysis_ledger", 6, 29_840),
      site("aughor.sql.writer:fix", 6, 24_014),
      site("aughor.judgment.seam:judge", 1, 2_578),
      ...["run_analysis_phase", "_run_synth", "deep_breakdown"].map((fn, i) =>
        site(`${deep}${fn}`, [21, 6, 16][i], [123_718, 45_914, 165_822][i])),
    ], 83, 451_593));
    expect(rows.map(r => [r.label, r.calls, r.tokens])).toEqual([
      ["Deep analysis", 43, 335_454],
      ["Conversation agent", 9, 49_460],
      ["Survey", 6, 29_840],
      ["SQL repair", 6, 24_014],
      ["Other", 19, 12_825],
    ]);
    expect(rows[4].other).toBe(true);
    expect(rows[4].sites).toEqual(["aughor.judgment.seam:judge"]);
  });

  it("folds named rows past the top few into Other rather than dropping them", () => {
    const rows = whereTokensGo(summary([
      site("aughor.explorer.agent:<lambda>", 1, 500), site("aughor.sql.writer:write", 1, 400),
      site("aughor.semantic.autoseed:_seed", 1, 300), site("aughor.ontology.enricher:x", 1, 200),
      site("aughor.business_profile.infer:_ask", 1, 100),
    ], 5, 1_500), 3);
    expect(rows.map(r => [r.label, r.tokens])).toEqual([["Exploration", 500], ["Writing SQL", 400], ["Other", 600]]);
    expect([...rows[2].sites].sort()).toEqual(
      ["aughor.business_profile.infer:_ask", "aughor.ontology.enricher:x", "aughor.semantic.autoseed:_seed"]);
  });
});

describe("the governance window, folded", () => {
  const ev = (over: Partial<AuditFeedEvent>): AuditFeedEvent => ({
    category: "data_access", kind: "query.execution", at: "2026-10-10T12:00:00Z", actor: "a", org_id: "default",
    conn_id: "914df862", summary: "", detail: {}, ...over,
  });
  const query = (verdict: string, hypothesis_id: string) => ev({ detail: { verdict, hypothesis_id } });
  const action = (decision: string, act = "x.resolve_case", conn = "914df862") =>
    ev({ category: "action_decision", kind: "action.approval", conn_id: conn, summary: `${decision} ${act}`, detail: { decision, action: act } });
  const names = (id: string) => ({ "914df862": "LuxExperience" } as Record<string, string>)[id];

  it("says query checks once, and names the platform's own flagged reads as noise", () => {
    const folds = foldFeed([
      query("safe", "__monitor__"), query("safe", "objects.list"),
      query("suspicious", "__brief_period__"), query("suspicious", "__trust_coltypes__"),
    ], names);
    expect(folds).toEqual([expect.objectContaining({
      key: "query", tone: "plain", title: "Query checks", count: 4, sub: "2 safe · 2 flagged were the platform's own reads",
    })]);
  });

  it("puts a flagged or blocked query that is not the platform's own in amber, first", () => {
    const folds = foldFeed([query("safe", "objects"), query("suspicious", "h1"), query("blocked", "h2"), query("blocked", "h3")], names);
    expect(folds.map(f => [f.title, f.tone, f.count])).toEqual([
      ["Queries were blocked", "amber", 2], ["A query was flagged", "amber", 1], ["Query checks", "plain", 4],
    ]);
    expect(folds[2].sub).toBe("1 safe · 1 flagged · 2 blocked");
    expect(folds[0].sub).toBe("LuxExperience");
  });

  it("puts what needs a person first, and groups the gate's decisions as a reader asks", () => {
    const folds = foldFeed([
      ...Array.from({ length: 3 }, () => action("approved", "ontology.override")),
      action("allowlisted", "ontology.override"),
      action("executed", "x.open_case"), action("executed", "x.start_work_on_case"),
      action("criterion_failed"),
      action("revoked", "ontology.override"),
      action("dispatch_error", "x.open_case", "gone"),
      ev({ category: "data_access", kind: "mcp.tool_call", detail: { route: "/org-settings/agent-policy", allowed: true } }),
      ev({ category: "enforcement", kind: "usage.cap_hit", summary: "cap hit: $25 per 24h" }),
    ], names);
    expect(folds.map(f => [f.title, f.tone, f.count, f.sub])).toEqual([
      ["An action's check failed", "amber", 1, "resolve case · LuxExperience"],
      ["An approval was revoked", "amber", 1, "ontology override · LuxExperience"],
      ["Action dispatch error", "amber", 1, "open case"],
      ["Usage cap hit", "amber", 1, "cap hit: $25 per 24h"],
      ["Actions ran", "accent", 2, "open case, start work on case · LuxExperience"],
      ["Approvals granted", "green", 4, "ontology override · LuxExperience"],
      ["Tool call from an MCP agent", "plain", 1, "agent policy · allowed"],
    ]);
  });

  it("puts a refused MCP call in amber", () => {
    const folds = foldFeed([ev({ kind: "mcp.tool_call", detail: { route: "/sql/run", allowed: false } })], names);
    expect(folds[0]).toMatchObject({ title: "An MCP agent was refused", tone: "amber", sub: "run · refused" });
  });

  it("names an action in a reader's words", () => {
    expect(actionWords("x.resolve_case")).toBe("resolve case");
    expect(actionWords("ontology.override")).toBe("ontology override");
  });

  it("says how far back the window reaches", () => {
    const now = Date.parse("2026-10-10T12:19:46Z");
    expect(sinceWords([ev({ at: "2026-10-10T12:19:35Z" }), ev({ at: "2026-10-10T10:45:45Z" })], now)).toBe("last 90 minutes");
    expect(sinceWords([ev({ at: "2026-10-10T12:10:00Z" })], now)).toBe("last 10 minutes");
    expect(sinceWords([ev({ at: "2026-10-09T12:00:00Z" })], now)).toBe("last 24 hours");
    expect(sinceWords([ev({ at: "2026-10-01T12:00:00Z" })], now)).toBe("last 9 days");
    expect(sinceWords([], now)).toBe("");
  });
});
