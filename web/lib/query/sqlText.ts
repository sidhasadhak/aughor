/**
 * SE-6 — synchronous, dialect-agnostic reading of SQL *text*.
 *
 * The workbench already has a real parser (`dt-sql-parser`, in a worker) and this is
 * deliberately not it. The parser is asynchronous — the whole point of putting 20 MB of
 * grammar off the main thread — and every caller here runs inside a CodeMirror command,
 * where the answer is needed in the same tick that the key was pressed. An intention
 * menu that appears a frame late, on the state the document used to be in, is worse
 * than no intention menu.
 *
 * So this module reads text, carefully: it knows about single quotes, double quotes,
 * backticks, bracket quoting, `--` line comments and `/* … *\/` block comments, and it
 * refuses to be clever about anything else. Where it cannot be sure it says so by
 * returning nothing, and the caller offers the user no action rather than a wrong one.
 */

/** A half-open range in the document. */
export interface TextRange { from: number; to: number }

/** One table reference in a FROM/JOIN clause. */
export interface TableRef {
  /** As written, qualification included: `analytics.orders`, `"Order Items"`. */
  name: string;
  /** The alias, if the query declared one (`AS o`, or just `o`). */
  alias: string | null;
  /** Where `name` sits in the document. */
  range: TextRange;
  /** Where the alias sits, when there is one. */
  aliasRange: TextRange | null;
}

const IDENT_CHAR = /[A-Za-z0-9_$]/;

/** Every position that is inside a string literal, a quoted identifier or a comment.
 *  Computed once per call and shared by the scanners below — they all need the same
 *  "is this character real code?" question answered. */
function maskLiterals(sql: string): Uint8Array {
  const mask = new Uint8Array(sql.length);
  let i = 0;
  while (i < sql.length) {
    const ch = sql[i];
    if (ch === "'" || ch === '"' || ch === "`") {
      const quote = ch;
      mask[i] = 1;
      i += 1;
      while (i < sql.length) {
        mask[i] = 1;
        if (sql[i] === quote) {
          // A doubled quote is an escaped quote, not the end of the literal.
          if (sql[i + 1] === quote) { mask[i + 1] = 1; i += 2; continue; }
          i += 1;
          break;
        }
        i += 1;
      }
      continue;
    }
    if (ch === "[") {                       // T-SQL / Databricks bracket quoting
      while (i < sql.length && sql[i] !== "]") { mask[i] = 1; i += 1; }
      if (i < sql.length) { mask[i] = 1; i += 1; }
      continue;
    }
    if (ch === "-" && sql[i + 1] === "-") {
      while (i < sql.length && sql[i] !== "\n") { mask[i] = 1; i += 1; }
      continue;
    }
    if (ch === "/" && sql[i + 1] === "*") {
      const end = sql.indexOf("*/", i + 2);
      const stop = end < 0 ? sql.length : end + 2;
      while (i < stop) { mask[i] = 1; i += 1; }
      continue;
    }
    i += 1;
  }
  return mask;
}

/** The statement containing `pos`, delimited by top-level semicolons.
 *
 *  Leading whitespace is trimmed off the front so the range starts at the first real
 *  character — a range that begins on the blank line above `SELECT` makes every
 *  offset the caller computes off by however much whitespace happened to be there. */
export function statementRangeAt(sql: string, pos: number): TextRange {
  const mask = maskLiterals(sql);
  let from = 0;
  for (let i = Math.min(pos, sql.length) - 1; i >= 0; i--) {
    if (sql[i] === ";" && !mask[i]) { from = i + 1; break; }
  }
  let to = sql.length;
  for (let i = Math.max(pos, from); i < sql.length; i++) {
    if (sql[i] === ";" && !mask[i]) { to = i; break; }
  }
  while (from < to && /\s/.test(sql[from])) from += 1;
  while (to > from && /\s/.test(sql[to - 1])) to -= 1;
  return { from, to };
}

/** The identifier under (or immediately before) `pos`, or null.
 *  Qualified names count as one identifier: the caret anywhere in `o.total_amount`
 *  returns the whole thing, because that is the unit a rename or a qualify acts on. */
export function identifierAt(sql: string, pos: number): { text: string; range: TextRange } | null {
  const mask = maskLiterals(sql);
  let start = Math.min(pos, sql.length);
  // A caret sitting just after a word belongs to that word — the same rule the
  // editor's own word-motion commands use.
  if (start > 0 && !IDENT_CHAR.test(sql[start] ?? "") && IDENT_CHAR.test(sql[start - 1])) start -= 1;
  if (!IDENT_CHAR.test(sql[start] ?? "")) return null;
  if (mask[start]) return null;
  let from = start, to = start;
  while (from > 0 && IDENT_CHAR.test(sql[from - 1]) && !mask[from - 1]) from -= 1;
  while (to < sql.length && IDENT_CHAR.test(sql[to]) && !mask[to]) to += 1;
  return { text: sql.slice(from, to), range: { from, to } };
}

const RESERVED_AFTER_TABLE = new Set([
  "on", "using", "where", "group", "order", "having", "limit", "offset", "join",
  "inner", "left", "right", "full", "cross", "outer", "union", "except", "intersect",
  "window", "qualify", "fetch", "for", "into", "set", "values", "returning", "lateral",
  "natural", "tablesample", "with", "as", "select", "from", "and", "or", "not", "asof",
]);

/** Every table named in a FROM or JOIN clause of `sql`, with its alias.
 *
 *  Subqueries and table functions are skipped rather than guessed at: `FROM (SELECT …)`
 *  has no table name to offer and `FROM read_csv('…')` names a function, so neither
 *  produces a ref. The alias rule is SQL's own — an optional `AS`, then a bare
 *  identifier that is not a reserved word that can legally follow a table. */
export function tableRefs(sql: string, offset = 0): TableRef[] {
  const mask = maskLiterals(sql);
  const out: TableRef[] = [];
  const kw = /\b(from|join)\b/gi;
  let m: RegExpExecArray | null;
  while ((m = kw.exec(sql))) {
    if (mask[m.index]) continue;
    let i = kw.lastIndex;
    while (i < sql.length && /\s/.test(sql[i])) i += 1;
    if (sql[i] === "(") continue;                       // a subquery, not a table
    const nameStart = i;
    while (i < sql.length && (IDENT_CHAR.test(sql[i]) || sql[i] === "." || sql[i] === '"' || sql[i] === "`")) i += 1;
    if (i === nameStart) continue;
    if (sql[i] === "(") continue;                       // a table function
    const name = sql.slice(nameStart, i);
    const range = { from: nameStart + offset, to: i + offset };

    // Optional alias.
    let j = i;
    while (j < sql.length && /[ \t]/.test(sql[j])) j += 1;
    let alias: string | null = null;
    let aliasRange: TextRange | null = null;
    if (/^as\b/i.test(sql.slice(j, j + 3))) {
      j += 2;
      while (j < sql.length && /\s/.test(sql[j])) j += 1;
    }
    const aliasStart = j;
    while (j < sql.length && IDENT_CHAR.test(sql[j])) j += 1;
    const candidate = sql.slice(aliasStart, j);
    if (candidate && !RESERVED_AFTER_TABLE.has(candidate.toLowerCase())) {
      alias = candidate;
      aliasRange = { from: aliasStart + offset, to: j + offset };
    }
    out.push({ name, alias, range, aliasRange });
  }
  return out;
}

/** Where a `*` sits in the SELECT list of `sql`, if there is exactly one to expand.
 *  A qualified star (`o.*`) reports its qualifier so the caller can expand only that
 *  table's columns; more than one star returns null, because expanding one of several
 *  changes what the query returns in a way the user did not ask for. */
export function selectStar(sql: string): { range: TextRange; qualifier: string | null } | null {
  const mask = maskLiterals(sql);
  const sel = /\bselect\b/i.exec(sql);
  if (!sel || mask[sel.index]) return null;
  const fromMatch = /\bfrom\b/i.exec(sql.slice(sel.index));
  const listEnd = fromMatch ? sel.index + fromMatch.index : sql.length;
  const list = sql.slice(sel.index + 6, listEnd);
  const stars: { range: TextRange; qualifier: string | null }[] = [];
  const star = /(?:([A-Za-z_][A-Za-z0-9_$]*)\s*\.\s*)?\*/g;
  let m: RegExpExecArray | null;
  while ((m = star.exec(list))) {
    const at = sel.index + 6 + m.index;
    if (mask[at]) continue;
    stars.push({ range: { from: at, to: at + m[0].length }, qualifier: m[1] ?? null });
  }
  return stars.length === 1 ? stars[0] : null;
}

/** Every standalone occurrence of `name` in `sql`, outside strings and comments.
 *  Used by rename, which must not touch `orders` inside `'orders'` or a comment. */
export function identifierOccurrences(sql: string, name: string, offset = 0): TextRange[] {
  const mask = maskLiterals(sql);
  const out: TextRange[] = [];
  const re = new RegExp(`(?<![A-Za-z0-9_$.])${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![A-Za-z0-9_$])`, "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(sql))) {
    if (mask[m.index]) continue;
    out.push({ from: m.index + offset, to: m.index + m[0].length + offset });
  }
  return out;
}

/** A short, readable alias for a table name — DataGrip's "introduce alias" rule:
 *  initials of the underscore-separated parts, falling back to the first letters.
 *  `order_items` → `oi`, `orders` → `o`, `customers` → `c`. Collisions get a digit. */
export function suggestAlias(tableName: string, taken: Set<string>): string {
  const bare = tableName.split(".").pop()!.replace(/["`[\]]/g, "");
  const parts = bare.split(/[_\s]+/).filter(Boolean);
  let base = parts.length > 1
    ? parts.map(p => p[0]).join("").toLowerCase()
    : bare.slice(0, 1).toLowerCase();
  if (!/^[a-z]/.test(base)) base = "t";
  let candidate = base;
  let n = 2;
  while (taken.has(candidate)) candidate = `${base}${n++}`;
  return candidate;
}
