/**
 * The SQL editor's chrome, redone to CLARITY (2026-10-12), held where a test can hold it: the result's figures line,
 * an error said as a failure or a refusal, the guards' chip, and the Tools ▾ menus — which must hold EVERY action that
 * left the toolbar and the results footer, or a capability was lost in the move. Fixtures are the live API's shapes:
 * a theLook run's audit rows (the run's own `SELECT * FROM (…) __q LIMIT n` wrapper included) and the gate's words.
 */
import { describe, expect, it, vi } from "vitest";

import type { AuditRecord, QueryValidation } from "@/lib/api";
import {
  cutNote, describeRunError, editorTools, recentRuns, resultFigures, resultTools, runMark, runMeta, runTime,
  sharedTools, startTables, unwrapRunSql, verdictChip, type ToolSpec,
} from "./workbench";

const shown = (items: ToolSpec[]) => items.filter(i => !i.hidden).map(i => i.label);

describe("the figures line", () => {
  const r = { row_count: 500, duration_ms: 768.86, truncated: true, cut_by: "limit" as const, cached: false };

  it("says rows · time · the cut, humanised", () => {
    expect(resultFigures(r)).toEqual({
      rows: "500 rows", time: "769 ms", cut: "cut at 500 rows — more exist beyond this limit", cached: false,
    });
    expect(resultFigures({ ...r, row_count: 12000, cut_by: "budget" }).rows).toBe("12,000 rows");
    expect(resultFigures({ ...r, row_count: 1, truncated: false }).rows).toBe("1 row");
  });

  it("says the cut for what cut it — the limit, the budget, the connector's cap", () => {
    expect(resultFigures({ ...r, cut_by: "budget", row_count: 10000 }).cut)
      .toBe("cut at 10,000 rows by this connection's row budget — more exist");
    expect(resultFigures({ ...r, cut_by: "cap" }).cut)
      .toBe("cut at 500 rows — this connector returns at most that many a call, whatever the limit");
    expect(cutNote({ row_count: 500, cut_by: null })).toBe("truncated — more rows exist beyond this limit");
    expect(resultFigures({ ...r, truncated: false, cut_by: null }).cut).toBeNull();
  });

  it("a filtered view says how many of the returned rows are on screen, not the run's count alone", () => {
    expect(resultFigures(r, { shown: 42, returned: 500 }).rows).toBe("42 of 500 rows");
    expect(resultFigures(r, { shown: 500, returned: 500 }).rows).toBe("500 rows");
    expect(resultFigures(r, { shown: 0, returned: 500 }).rows).toBe("0 of 500 rows");
  });

  it("an empty result is 'No rows'; a cached one has no run time", () => {
    expect(resultFigures({ ...r, row_count: 0, truncated: false }).rows).toBe("No rows");
    const cached = resultFigures({ ...r, cached: true, duration_ms: 0 });
    expect(cached.time).toBeNull();
    expect(cached.cached).toBe(true);
  });

  it("time reads in ms under a second and seconds after", () => {
    expect(runTime(4.2)).toBe("4 ms");
    expect(runTime(1250)).toBe("1.3 s");
    expect(runTime(Number.NaN)).toBe("—");
  });
});

describe("an error, said once — failed or refused", () => {
  it("an engine error is a failure, in the engine's words", () => {
    expect(describeRunError('Binder Error: column "region" must appear in the GROUP BY clause')).toEqual({
      kind: "failed", title: "Failed", why: null, statement: null,
      message: 'Binder Error: column "region" must appear in the GROUP BY clause',
    });
  });

  it("a guard's block and a table turned off are refusals, the platform's bracket tag dropped", () => {
    const blocked = describeRunError("[BLOCKED] DROP statements are not permitted in read-only mode");
    expect(blocked).toMatchObject({ kind: "refused", title: "Refused", why: "blocked by a guard",
      message: "DROP statements are not permitted in read-only mode" });
    const off = describeRunError("[EXCLUDED] thelook.users is turned off for analysis — it is excluded (sensitive). "
      + "Turn it back on in the Catalog to use it.");
    expect(off).toMatchObject({ kind: "refused", why: "turned off for analysis" });
    expect(off.message.startsWith("thelook.users is turned off")).toBe(true);
    expect(describeRunError("Only SELECT statements are permitted")).toMatchObject({
      kind: "refused", why: "only SELECT runs here", message: "Only SELECT statements are permitted" });
    expect(describeRunError("Blocked by this agent's sensitive-data guardrail: the result contains values"))
      .toMatchObject({ kind: "refused", why: "sensitive data withheld" });
  });

  it("names the statement of a Run all, and reads a refusal inside it", () => {
    expect(describeRunError("Statement 2 of 3 failed: [BLOCKED] DELETE is not permitted")).toEqual({
      kind: "refused", title: "Refused", why: "blocked by a guard", statement: "statement 2 of 3",
      message: "DELETE is not permitted",
    });
  });

  it("a cancellation is the person's own decision, never a failure", () => {
    expect(describeRunError("Cancelled after 1 of 3 statements.")).toMatchObject({ kind: "cancelled", title: "Cancelled" });
  });
});

describe("the guards' verdict as a chip", () => {
  const base: QueryValidation = { passed: true, issue_count: 0, fanout_hits: [], join_warnings: [], filter_warnings: [] };

  it("is green only when every guard ran and passed", () => {
    expect(verdictChip(base)).toMatchObject({ text: "Guards clean", tone: "up" });
    expect(verdictChip({ ...base, passed: false, issue_count: 0,
      unchecked_guards: [{ guard: "grain", reason: "could not parse" }] }))
      .toMatchObject({ text: "Not all checked", tone: "amber", title: "Not checked (grain): could not parse" });
    expect(verdictChip({ ...base, passed: false, unchecked: true, note: "" }))
      .toMatchObject({ text: "Not checked — fill parameters", tone: "amber" });
    expect(verdictChip({ ...base, passed: false, issue_count: 2 })).toMatchObject({ text: "Checked — 2 notes", tone: "amber" });
  });
});

describe("Tools ▾ holds every action that left the toolbar", () => {
  const act = {
    explain: vi.fn(), runAll: vi.fn(), format: vi.fn(), formatPrefs: vi.fn(), openExisting: vi.fn(),
    toggleHistory: vi.fn(), shortcuts: vi.fn(),
  };
  const editor = (over: Partial<Parameters<typeof editorTools>[0]> = {}) => editorTools({
    connected: true, explainWith: "EXPLAIN", statementCount: 3, runAllPref: false, hasSql: true, historyOpen: false,
    act, ...over,
  });
  const shared = (over: Partial<Parameters<typeof sharedTools>[0]> = {}) => sharedTools({
    saved: true, versionsOpen: false, catalogOpen: true,
    act: { versions: vi.fn(), share: vi.fn(), catalog: vi.fn() }, ...over,
  });

  it("the editor's: Explain, Run all, Format and its preferences, Open, Recent runs, the keys", () => {
    expect(shown(editor())).toEqual([
      "Explain plan", "Run all 3 statements", "Format SQL", "Formatting preferences…",
      "Open a saved or recent query…", "Recent runs", "Keyboard shortcuts",
    ]);
    // Each calls the action it names.
    const byTest = Object.fromEntries(editor().map(i => [i.testId, i]));
    byTest["sql-explain"].onSelect(); byTest["sql-run-all"].onSelect(); byTest["sql-format"].onSelect();
    byTest["sql-format-prefs"].onSelect(); byTest["sql-open-existing"].onSelect();
    byTest["sql-history-toggle"].onSelect(); byTest["sql-shortcuts"].onSelect();
    for (const fn of Object.values(act)) expect(fn).toHaveBeenCalledTimes(1);
  });

  it("offers each only when it can act: no plan statement, one statement, an empty buffer, no connection", () => {
    expect(shown(editor({ explainWith: null }))).not.toContain("Explain plan");
    expect(shown(editor({ statementCount: 1 }))).not.toContain("Run all 1 statements");
    // The tab already runs every statement on Run: a second "Run all" would be the same verb twice.
    expect(shown(editor({ runAllPref: true })).some(l => l.startsWith("Run all"))).toBe(false);
    expect(shown(editor({ hasSql: false }))).not.toContain("Format SQL");
    expect(shown(editor({ connected: false }))).toEqual([
      "Format SQL", "Formatting preferences…", "Open a saved or recent query…", "Recent runs", "Keyboard shortcuts",
    ]);
    expect(shown(editor({ historyOpen: true }))).toContain("Hide recent runs");
  });

  it("the workbench's: version history (once saved), the share link, the catalog", () => {
    expect(shown(shared())).toEqual(["Version history", "Copy share link", "Hide catalog"]);
    expect(shown(shared({ saved: false, catalogOpen: false }))).toEqual(["Copy share link", "Show catalog"]);
    expect(shown(shared({ versionsOpen: true }))[0]).toBe("Hide version history");
    // A share link without a saved query still says why it cannot be made — the item is never silently gone.
    expect(shared({ saved: false }).find(i => i.testId === "workbench-share")?.title).toMatch(/Save this query first/);
  });

  it("the result's: a chart, the other formats, Pin, Schedule — what was the footer's row of buttons", () => {
    const r = (over: Partial<Parameters<typeof resultTools>[0]> = {}) => resultTools({
      hasRows: true, connected: true, filtered: false, scheduleCount: 0,
      act: { addChart: vi.fn(), export: vi.fn(), pin: vi.fn(), schedule: vi.fn() }, ...over,
    });
    expect(shown(r())).toEqual(["Add a chart", "Other formats…", "Pin to the dashboard", "Schedule…"]);
    expect(shown(r({ scheduleCount: 2 }))).toContain("Schedule (2)…");
    expect(shown(r({ filtered: true }))).toContain("Other formats, filtered rows…");
    // An empty result still schedules; nothing to chart, export or pin.
    expect(shown(r({ hasRows: false }))).toEqual(["Schedule…"]);
  });

  it("every item names what it does by a test id the screen can be driven by", () => {
    const all = [
      ...editor(), ...shared(),
      ...resultTools({ hasRows: true, connected: true, filtered: false, scheduleCount: 0,
        act: { addChart: vi.fn(), export: vi.fn(), pin: vi.fn(), schedule: vi.fn() } }),
    ];
    const ids = all.map(i => i.testId);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.every(Boolean)).toBe(true);
  });
});

describe("the starting point", () => {
  const run = (id: string, sql: string, over: Partial<AuditRecord> = {}): AuditRecord => ({
    id, ts: "2026-10-12T00:11:00Z", connection_id: "8233e4fd", hypothesis_id: "query_workbench",
    sql_digest: sql.slice(0, 40), sql_full: sql, verdict: "safe", row_count: 5, duration_ms: 768.86, error: null, ...over,
  });

  it("opens the person's statement, not the run's row-cap wrapper", () => {
    expect(unwrapRunSql("SELECT * FROM (SELECT country, COUNT(*) FROM users GROUP BY 1) __q LIMIT 501"))
      .toBe("SELECT country, COUNT(*) FROM users GROUP BY 1");
    // Anything else is left exactly as written.
    expect(unwrapRunSql("SELECT * FROM (SELECT 1) q LIMIT 5")).toBe("SELECT * FROM (SELECT 1) q LIMIT 5");
    expect(unwrapRunSql("DROP SCHEMA rearm_single CASCADE")).toBe("DROP SCHEMA rearm_single CASCADE");
  });

  it("opens a dashboard piece's statement without the piece's sort or sum around it — theLook's live runs", () => {
    // As the live audit holds them (2026-10-13): the row cap around a piece's wrapper around the person's statement.
    const stmt = "SELECT u.country, ROUND(SUM(oi.sale_price), 2) AS sales FROM thelook.orders o JOIN thelook.users u "
      + "ON u.id = o.user_id GROUP BY 1 ORDER BY sales DESC LIMIT 5";
    expect(unwrapRunSql(`SELECT * FROM (SELECT * FROM (\n${stmt}\n) AS q ORDER BY \`q\`.\`sales\` DESC LIMIT 201) __q LIMIT 202`))
      .toBe(stmt);
    const daily = "SELECT DATE(o.created_at) AS day, u.country, SUM(oi.sale_price) AS sales\nFROM thelook.orders o\nGROUP BY 1, 2";
    expect(unwrapRunSql("SELECT * FROM (SELECT DATE_TRUNC(`q`.`day`, DAY) AS x, `q`.`country` AS s, SUM(`q`.`sales`) AS v0 "
      + `FROM (\n${daily}\n) AS q GROUP BY 1, 2 ORDER BY 1 LIMIT 41) __q LIMIT 42`)).toBe(daily);
    expect(unwrapRunSql(`SELECT * FROM (SELECT SUM(\`q\`.\`sales\`) AS v0 FROM (\n${stmt}\n) AS q) __q LIMIT 3`)).toBe(stmt);
    // a person's own subquery aliased q, on one line, is theirs — left as written
    expect(unwrapRunSql("SELECT * FROM (SELECT 1 AS a) AS q")).toBe("SELECT * FROM (SELECT 1 AS a) AS q");
  });

  it("folds a repeated statement into a count, newest first", () => {
    const runs = recentRuns([
      run("a", "SELECT * FROM (SELECT SUM(x) FROM t) __q LIMIT 501"),
      run("b", "SELECT * FROM (SELECT  SUM(x)\nFROM t) __q LIMIT 501"),
      run("c", "SELECT * FROM (SELECT region FROM t) __q LIMIT 501", { error: "Binder Error" }),
      run("d", "SELECT * FROM (SELECT SUM(x) FROM t) __q LIMIT 101"),
    ]);
    expect(runs.map(r => [r.preview, r.times, r.last.id])).toEqual([
      ["SELECT SUM(x) FROM t", 3, "a"],
      ["SELECT region FROM t", 1, "c"],
    ]);
  });

  it("marks only what did not simply pass, in the audit screen's words", () => {
    expect(runMark(run("a", "x"))).toBeNull();
    expect(runMark(run("a", "x", { verdict: "blocked" }))).toEqual({ word: "blocked", tone: "red" });
    expect(runMark(run("a", "x", { error: "Binder Error" }))).toEqual({ word: "failed", tone: "red" });
    expect(runMark(run("a", "x", { verdict: "suspicious" }))).toEqual({ word: "flagged", tone: "amber" });
    expect(runMeta(run("a", "x"))).toBe("5 rows · 769 ms");
  });

  it("lists the largest tables first; an uncounted table is unknown, not zero, and sorts last", () => {
    expect(startTables([
      { name: "thelook.users", rowCount: 100000 }, { name: "thelook.events", rowCount: 2426096 },
      { name: "thelook.notes", rowCount: null }, { name: "thelook.orders", rowCount: "125,303" },
    ], 3)).toEqual([
      { name: "thelook.events", rows: 2426096, shown: "2.4M" },
      { name: "thelook.orders", rows: 125303, shown: "125.3K" },
      { name: "thelook.users", rows: 100000, shown: "100.0K" },
    ]);
    expect(startTables([{ name: "a", rowCount: null }])[0]).toEqual({ name: "a", rows: null, shown: "not counted" });
  });
});
