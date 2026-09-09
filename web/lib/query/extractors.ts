/**
 * SE-7 — data extractors, DataGrip's name for "get this result out in the shape the
 * next tool wants".
 *
 * A result grid is a dead end until the rows can leave it, and the destination decides
 * the format: a spreadsheet wants TSV, a ticket wants Markdown, a colleague's script
 * wants JSON, a fixture wants INSERT statements. One CSV button served the first of
 * those and nothing else, so everything else meant re-running the query somewhere it
 * could be exported properly.
 *
 * Every extractor here is a pure function of (columns, rows). They are pure because
 * that is what makes them testable, and they are tested because a broken quote or an
 * unescaped delimiter does not look broken — it looks like data, one column to the
 * left of where it belongs. `lib/query/csv.ts` already learned that the hard way when a
 * carriage return went out unquoted and shifted every later field.
 *
 * NULL is the value the whole set turns on. It is NOT the empty string, and each format
 * says so in its own vocabulary: nothing at all in CSV/TSV, `null` in JSON, `NULL` in
 * SQL, `∅` in Markdown and the pretty table where a blank cell would read as "".
 */
import { toCsv, toTsv } from "@/lib/query/csv";

export type Cell = string | number | boolean | null;

export interface Extractor {
  id: string;
  /** Menu label. */
  label: string;
  /** File extension for a download, without the dot. */
  ext: string;
  /** MIME type for the blob. */
  mime: string;
  render: (columns: string[], rows: readonly Cell[][], table?: string) => string;
}

const NULL_GLYPH = "∅";

/** Escape for a Markdown table cell: a pipe would end the cell, a newline the row. */
function mdCell(v: Cell): string {
  if (v === null || v === undefined) return NULL_GLYPH;
  return String(v).replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

function htmlEscape(v: Cell): string {
  if (v === null || v === undefined) return NULL_GLYPH;
  return String(v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** A SQL literal. Numbers and booleans go bare; everything else is quoted with its own
 *  quotes doubled — the one rule that decides whether the output is data or an
 *  injection. */
export function sqlLiteral(v: Cell): string {
  if (v === null || v === undefined) return "NULL";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "NULL";
  if (typeof v === "boolean") return v ? "TRUE" : "FALSE";
  return `'${String(v).replace(/'/g, "''")}'`;
}

/** An identifier in an INSERT: quoted only when it is not a plain lower-case name, for
 *  the same reason `quoteIdentifier` is careful — quoting `orders` makes it
 *  case-sensitive in Postgres and DuckDB. */
function sqlIdent(name: string): string {
  return /^[a-z_][a-z0-9_$]*$/.test(name) ? name : `"${name.replace(/"/g, '""')}"`;
}

export const EXTRACTORS: Extractor[] = [
  {
    id: "csv", label: "CSV", ext: "csv", mime: "text/csv;charset=utf-8;",
    render: (c, r) => toCsv(c, r),
  },
  {
    id: "tsv", label: "TSV", ext: "tsv", mime: "text/tab-separated-values;charset=utf-8;",
    render: (c, r) => toTsv(c, r),
  },
  {
    id: "json", label: "JSON", ext: "json", mime: "application/json;charset=utf-8;",
    // An ARRAY OF OBJECTS, not of arrays: the column names are the reason anyone asked
    // for JSON rather than CSV. A repeated column name (`SELECT a, a`) would collapse,
    // so the second one keeps its position in the name.
    render: (c, r) => {
      const names = c.map((name, i) => (c.indexOf(name) === i ? name : `${name}_${i}`));
      return JSON.stringify(r.map(row => Object.fromEntries(names.map((n, i) => [n, row[i] ?? null]))), null, 2);
    },
  },
  {
    id: "markdown", label: "Markdown", ext: "md", mime: "text/markdown;charset=utf-8;",
    render: (c, r) => [
      `| ${c.map(mdCell).join(" | ")} |`,
      `| ${c.map(() => "---").join(" | ")} |`,
      ...r.map(row => `| ${row.map(mdCell).join(" | ")} |`),
    ].join("\n"),
  },
  {
    id: "html", label: "HTML table", ext: "html", mime: "text/html;charset=utf-8;",
    render: (c, r) => [
      "<table>", "  <thead>",
      `    <tr>${c.map(h => `<th>${htmlEscape(h)}</th>`).join("")}</tr>`,
      "  </thead>", "  <tbody>",
      ...r.map(row => `    <tr>${row.map(v => `<td>${htmlEscape(v)}</td>`).join("")}</tr>`),
      "  </tbody>", "</table>",
    ].join("\n"),
  },
  {
    id: "sql-insert", label: "SQL INSERTs", ext: "sql", mime: "text/plain;charset=utf-8;",
    render: (c, r, table) => {
      const t = sqlIdent(table || "my_table");
      const cols = c.map(sqlIdent).join(", ");
      return r.map(row => `INSERT INTO ${t} (${cols}) VALUES (${row.map(sqlLiteral).join(", ")});`).join("\n");
    },
  },
  {
    id: "pretty", label: "Plain text table", ext: "txt", mime: "text/plain;charset=utf-8;",
    // Column widths from the WIDEST cell, so the output lines up in a terminal or a
    // fixed-width comment — which is the only reason to want this format.
    render: (c, r) => {
      const cell = (v: Cell) => (v === null || v === undefined ? NULL_GLYPH : String(v).replace(/\r?\n/g, " "));
      const widths = c.map((h, i) => Math.max(h.length, ...r.map(row => cell(row[i]).length), 0));
      const line = (vals: string[]) => vals.map((v, i) => v.padEnd(widths[i])).join("  ").trimEnd();
      return [
        line(c),
        widths.map(w => "-".repeat(w)).join("  ").trimEnd(),
        ...r.map(row => line(c.map((_, i) => cell(row[i])))),
      ].join("\n");
    },
  },
];

export function extractorById(id: string): Extractor {
  return EXTRACTORS.find(e => e.id === id) ?? EXTRACTORS[0];
}

/** The table an INSERT should target — the first table the SQL names, else a
 *  placeholder the user will obviously have to replace. */
export function guessTableName(sql: string): string {
  const m = /\bfrom\s+([A-Za-z_][\w.]*)/i.exec(sql);
  return m ? m[1] : "my_table";
}
