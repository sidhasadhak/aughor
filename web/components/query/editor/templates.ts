/**
 * SE-6 — live templates: DataGrip's `sel`+Tab, in CodeMirror.
 *
 * A template is an abbreviation that expands into a skeleton with the caret parked on
 * the first hole and Tab moving between holes (`${}` fields — CodeMirror's own snippet
 * mechanism, so the fields, the tabbing and the escape behaviour are the editor's,
 * not a re-implementation).
 *
 * Two rules the abbreviations follow, both taken from DataGrip's set rather than
 * invented here, because the muscle memory is the point:
 *   - the abbreviation is the first syllable of what it writes (`sel`, `ins`, `upd`),
 *   - and the expansion is the SHAPE, not an opinion: no invented column names, no
 *     `LIMIT 100` someone has to remember to delete.
 *
 * They are ordinary completions, so they appear in the same popup as tables and
 * columns and are filtered the same way. `section` groups them under one heading so a
 * template never looks like a column that happens to be called `sel`.
 */
import { snippetCompletion, type Completion } from "@codemirror/autocomplete";

export interface SqlTemplate {
  /** What you type. */
  abbrev: string;
  /** What it writes, with `${name}` holes. */
  template: string;
  /** One line, shown beside the abbreviation in the popup. */
  detail: string;
}

/** The set. Ordered as a person learns them, not alphabetically — the popup sorts. */
export const SQL_TEMPLATES: SqlTemplate[] = [
  { abbrev: "sel",    detail: "SELECT … FROM …",
    template: "SELECT ${*}\nFROM ${table}" },
  { abbrev: "selw",   detail: "SELECT … WHERE …",
    template: "SELECT ${*}\nFROM ${table}\nWHERE ${condition}" },
  { abbrev: "selc",   detail: "SELECT COUNT(*)",
    template: "SELECT COUNT(*)\nFROM ${table}" },
  { abbrev: "gb",     detail: "GROUP BY with a count",
    template: "SELECT ${column}, COUNT(*) AS n\nFROM ${table}\nGROUP BY ${column}\nORDER BY n DESC" },
  { abbrev: "ob",     detail: "ORDER BY",
    template: "ORDER BY ${column} ${DESC}" },
  { abbrev: "jn",     detail: "JOIN … ON …",
    template: "JOIN ${table} ${alias} ON ${alias}.${key} = ${other}.${key}" },
  { abbrev: "ljn",    detail: "LEFT JOIN … ON …",
    template: "LEFT JOIN ${table} ${alias} ON ${alias}.${key} = ${other}.${key}" },
  { abbrev: "cte",    detail: "WITH … AS ( … )",
    template: "WITH ${name} AS (\n  ${query}\n)\nSELECT *\nFROM ${name}" },
  { abbrev: "win",    detail: "Window function",
    template: "${SUM}(${column}) OVER (PARTITION BY ${key} ORDER BY ${ts})" },
  { abbrev: "case",   detail: "CASE WHEN … THEN … END",
    template: "CASE WHEN ${condition} THEN ${value} ELSE ${other} END" },
  { abbrev: "ins",    detail: "INSERT INTO … VALUES",
    template: "INSERT INTO ${table} (${columns})\nVALUES (${values})" },
  { abbrev: "upd",    detail: "UPDATE … SET … WHERE",
    template: "UPDATE ${table}\nSET ${column} = ${value}\nWHERE ${condition}" },
  { abbrev: "del",    detail: "DELETE FROM … WHERE",
    template: "DELETE FROM ${table}\nWHERE ${condition}" },
  { abbrev: "ct",     detail: "CREATE TABLE",
    template: "CREATE TABLE ${name} (\n  ${column} ${type}\n)" },
  { abbrev: "ctas",   detail: "CREATE TABLE AS SELECT",
    template: "CREATE TABLE ${name} AS\nSELECT ${*}\nFROM ${table}" },
  { abbrev: "cv",     detail: "CREATE VIEW",
    template: "CREATE VIEW ${name} AS\nSELECT ${*}\nFROM ${table}" },
  { abbrev: "exp",    detail: "EXPLAIN the statement",
    template: "EXPLAIN ${statement}" },
  { abbrev: "lim",    detail: "LIMIT n",
    template: "LIMIT ${100}" },
  { abbrev: "dt",     detail: "DESCRIBE a table",
    template: "DESCRIBE ${table}" },
  { abbrev: "nn",     detail: "Rows where a column IS NULL",
    template: "SELECT COUNT(*) AS nulls\nFROM ${table}\nWHERE ${column} IS NULL" },
  { abbrev: "dup",    detail: "Find duplicate keys",
    template: "SELECT ${key}, COUNT(*) AS n\nFROM ${table}\nGROUP BY ${key}\nHAVING COUNT(*) > 1\nORDER BY n DESC" },
];

/** The templates as completions. `boost` lifts them just above ordinary identifiers
 *  when the typed prefix matches an abbreviation exactly — typing `sel` should offer
 *  the template first, not a column called `selected`. */
export function templateCompletions(): Completion[] {
  return SQL_TEMPLATES.map(t => snippetCompletion(t.template, {
    label: t.abbrev,
    detail: t.detail,
    type: "text",
    section: { name: "Templates", rank: 0 },
    boost: 40,
  }));
}
