/**
 * SE-1 — the SQL parser, kept OFF the main thread.
 *
 * dt-sql-parser is ~20 MB unpacked. Importing it on the main thread would put that in
 * the app's primary bundle for a feature only the Query workbench uses, so it lives
 * here, behind a worker, and this module imports exactly ONE dialect entry point
 * (`dt-sql-parser/dist/parser/postgresql`) rather than the package root — the root
 * pulls every grammar it ships.
 *
 * Two jobs, both purely syntactic:
 *   split(sql)    → the statement ranges, so ⌘↵ can run the one under the cursor
 *   validate(sql) → approximate syntax errors for inline squiggles
 *
 * "Approximate" is the honest word for validate: this is a Postgres grammar used
 * against whatever engine the connection actually runs, so it catches unbalanced
 * parens and obvious malformations, not dialect-specific truth. SE-2 adds the
 * authoritative server check (`POST /query/validate`) whose verdicts override these.
 */

/// <reference lib="webworker" />

import { PostgreSQL } from "dt-sql-parser/dist/parser/postgresql";

export interface StatementRange {
  /** 0-based character offsets into the original text; `to` is exclusive. */
  from: number;
  to: number;
  text: string;
}

export interface ParseDiagnostic {
  from: number;
  to: number;
  message: string;
}

export type ParserRequest =
  | { id: number; op: "split"; sql: string }
  | { id: number; op: "validate"; sql: string };

export type ParserResponse =
  | { id: number; ok: true; result: StatementRange[] | ParseDiagnostic[] }
  | { id: number; ok: false; error: string };

const parser = new PostgreSQL();

function lineStartsOf(sql: string): number[] {
  const starts = [0];
  for (let i = 0; i < sql.length; i++) if (sql[i] === "\n") starts.push(i + 1);
  return starts;
}

/** Offset for a parser position. Both line and column are 1-BASED in dt-sql-parser
 *  (`ParseError` documents "start at 1" for each), so both lose one here — an
 *  off-by-one lands every squiggle a character to the right of its token. */
function offsetOf(lineStarts: number[], line: number, column: number): number {
  const idx = Math.max(0, Math.min(line - 1, lineStarts.length - 1));
  return lineStarts[idx] + Math.max(0, column - 1);
}

function split(sql: string): StatementRange[] {
  // The parser's own splitter knows a semicolon inside a string literal or a comment
  // does not end a statement — which is exactly why this is not `sql.split(";")`.
  let ranges: StatementRange[] = [];
  try {
    // TextSlice carries 0-based startIndex and an INCLUSIVE endIndex, so `to` is +1.
    ranges = (parser.splitSQLByStatement(sql) ?? []).map((s) => ({
      from: s.startIndex,
      to: s.endIndex + 1,
      text: sql.slice(s.startIndex, s.endIndex + 1),
    }));
  } catch {
    ranges = [];
  }
  // Fail SOFT to one statement covering everything. A parser that cannot split must
  // not make the run button dead — running the whole buffer is what any plain editor
  // would do, which is a worse experience but not a broken one.
  if (!ranges.length && sql.trim()) return [{ from: 0, to: sql.length, text: sql }];
  return ranges;
}

function validate(sql: string): ParseDiagnostic[] {
  try {
    const starts = lineStartsOf(sql);
    return (parser.validate(sql) ?? []).map((e) => {
      const from = offsetOf(starts, e.startLine, e.startColumn);
      const to = Math.max(from + 1, offsetOf(starts, e.endLine, e.endColumn));
      return { from, to, message: e.message || "Syntax error" };
    });
  } catch {
    // A parser crash must never surface as a broken editor — no squiggles is the
    // correct degradation, and the server check is the authority anyway.
    return [];
  }
}

self.onmessage = (ev: MessageEvent<ParserRequest>) => {
  const req = ev.data;
  if (!req || typeof req.id !== "number") return;
  const post = (msg: ParserResponse) => (self as unknown as Worker).postMessage(msg);
  try {
    post({ id: req.id, ok: true,
           result: req.op === "split" ? split(req.sql) : validate(req.sql) });
  } catch (err) {
    post({ id: req.id, ok: false,
           error: err instanceof Error ? err.message : String(err) });
  }
};
