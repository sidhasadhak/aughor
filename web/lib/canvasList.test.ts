/**
 * What an open Data Canvas says (`lib/canvasList.ts`): its connection gone or not, and its history with a repeated
 * question said once. The fixtures are the live install's four
 * canvases and its history's shape on 2026-10-12 — 30 runs that were three questions.
 */
import { describe, expect, it } from "vitest";

import type { Canvas, CanvasHistoryItem, Connection } from "@/lib/api";
import { agoWords, connectionGone, foldHistory, runStateWord, scopeWords, tablesTitle } from "@/lib/canvasList";

const NOW = Date.parse("2026-10-12T12:00:00Z");

const canvas = (id: string, over: Partial<Canvas> = {}): Canvas => ({
  id, name: id, description: "", is_legacy: false, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
  scopes: [{ connection_id: "thelook", schema_name: null, tables: [] }], last_activity: null, ...over,
});

const LIVE: Canvas[] = [
  canvas("analytics", { name: "The Look Analytics", updated_at: "2026-09-18T00:15:55Z", last_activity: null }),
  canvas("ops", { name: "E-Commerce Operations Overview", last_activity: "2026-10-03T14:25:33Z" }),
  canvas("superstore", { name: "Superstore Sales Analytics", last_activity: "2026-08-15T18:15:04Z",
    scopes: [{ connection_id: "duck", schema_name: "main", tables: ["main.superstore"] }] }),
  canvas("airline", { name: "Airline And Sales Operations", last_activity: "2026-08-21T21:56:57Z",
    scopes: [{ connection_id: "workspace", schema_name: "main", tables: Array.from({ length: 24 }, (_, i) => `main.t${i}`) }] }),
];
const CONNS = [
  { id: "thelook", name: "theLook", conn_type: "bigquery" },
  { id: "duck", name: "DuckDB", conn_type: "duckdb" },
  { id: "workspace", name: "Workspace", conn_type: "local_upload" },
] as unknown as Connection[];

describe("a canvas's connection", () => {
  it("is there for every live canvas when every connection the install has is read", () => {
    expect(LIVE.filter(c => connectionGone(c, CONNS))).toEqual([]);
  });

  it("is gone only when the install has no such connection — another workspace's is not gone", () => {
    const orphan = canvas("lux", { scopes: [{ connection_id: "removed", schema_name: null, tables: [] }] });
    expect([...LIVE, orphan].filter(c => connectionGone(c, CONNS)).map(c => c.id)).toEqual(["lux"]);
    expect(LIVE.filter(c => connectionGone(c, [CONNS[0]])).map(c => c.id)).toEqual(["superstore", "airline"]);
  });

  it("is never called gone before the connections are read", () => {
    // An empty list is one not read yet: saying every canvas lost its connection would be false.
    expect(connectionGone(LIVE[0], [])).toBe(false);
  });
});

describe("an open canvas's history", () => {
  const run = (id: string, question: string, at: string, over: Partial<CanvasHistoryItem> = {}): CanvasHistoryItem => ({
    id, question, status: "complete", started_at: at, ...over,     // no kind: anything not a chat is a deep analysis
  });

  it("says a question asked many times once, with its count, the newest run first", () => {
    const items = [
      run("a1", "What was total revenue in July 2026?", "2026-10-03T13:53:57Z"),
      run("b1", "How has monthly revenue trended?", "2026-10-03T14:25:33Z"),
      run("a2", "What was total revenue in July 2026?", "2026-10-03T14:23:57Z"),
      run("a3", "What was total revenue in July 2026? ", "2026-10-01T10:00:00Z"),
    ];
    const asked = foldHistory(items);
    expect(asked.map(q => [q.question, q.runs.length])).toEqual([
      ["How has monthly revenue trended?", 1],
      ["What was total revenue in July 2026?", 3],
    ]);
    expect(asked[1].latest.id).toBe("a2");
    expect(asked[1].key).toBe("a2");           // keyed by a run's id, never by the question's words
  });

  it("keeps a chat and a deep analysis of the same question apart", () => {
    const asked = foldHistory([
      run("c1", "Give me route wise number of flights", "2026-08-21T21:56:57Z", { kind: "chat" }),
      run("d1", "Give me route wise number of flights", "2026-08-21T06:46:40Z"),
    ]);
    expect(asked.map(q => q.kind)).toEqual(["chat", "deep"]);
  });

  it("says a run that did not simply finish, and nothing for one that did", () => {
    expect(runStateWord("complete")).toBeNull();
    expect(runStateWord("failed")).toEqual({ word: "failed", tone: "down" });
    expect(runStateWord("timed_out")?.word).toBe("timed out");
    expect(runStateWord("running")?.tone).toBe("amber");
  });

  it("says when, as a person says it", () => {
    expect(agoWords("2026-10-12T08:00:00Z", NOW)).toBe("today");
    expect(agoWords("2026-10-11T08:00:00Z", NOW)).toBe("yesterday");
    expect(agoWords("2026-07-01T00:00:00Z", NOW)).toBe("3 months ago");
    expect(agoWords(null, NOW)).toBe("—");
  });
});
