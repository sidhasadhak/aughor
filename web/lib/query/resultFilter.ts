/**
 * SE-4 I — plain-English filters over an in-memory result.
 *
 * Deterministic, not an LLM call. Three reasons, in order of weight:
 *
 *  1. The roadmap's own requirement is "chainable, no re-run". A filter that costs a
 *     network round-trip and a second of latency is not the same feature — the value
 *     here is that narrowing 500 rows feels like typing, not like running a query.
 *  2. This program already measured the trade in NL2SQL benchmarking and concluded
 *     deterministic guards beat LLM machinery on the parts a grammar can express.
 *     A comparison over a named column is emphatically one of those parts.
 *  3. A parse failure here must be legible. "I don't know a column called 'revenu'"
 *     is a better answer than a model quietly filtering on something else.
 *
 * The grammar covers what people actually type at a grid, and every clause reports the
 * column it bound to so the chip can show it. Anything unparseable falls back to a
 * substring match across all columns — the behaviour of a search box, which is what an
 * unrecognised phrase most likely meant.
 */

export type Cell = string | number | boolean | null;

export interface FilterClause {
  /** The phrase as typed — what the chip displays and what re-parsing round-trips. */
  text: string;
  /** Resolved column name, or null for an all-column search. */
  column: string | null;
  /** Human-readable rendering of what this clause does, for the chip's tooltip. */
  describe: string;
  predicate: (row: Cell[]) => boolean;
  /** Set when the phrase named a column we could not resolve. */
  error?: string;
}

/** Ranking filters cannot be a row predicate — they need the whole set. */
export interface RankSpec {
  kind: "top" | "bottom";
  n: number;
  columnIndex: number;
}

export interface ParsedFilter {
  clause: FilterClause | null;
  rank: RankSpec | null;
}

// ── column resolution ─────────────────────────────────────────────────────────

/** Loose match so `order date`, `order_date` and `Order Date` all find one column. */
function norm(s: string): string {
  return s.toLowerCase().replace(/[\s_-]+/g, "");
}

function resolveColumn(columns: string[], name: string): number {
  const want = norm(name);
  if (!want) return -1;
  const exact = columns.findIndex((c) => norm(c) === want);
  if (exact >= 0) return exact;
  // A unique prefix/substring match — `rev` for `revenue`. Ambiguity resolves to no
  // match rather than a guess: silently picking one of two candidates is how a filter
  // ends up describing a column the user was not looking at.
  const hits = columns
    .map((c, i) => ({ i, n: norm(c) }))
    .filter(({ n }) => n.includes(want));
  return hits.length === 1 ? hits[0].i : -1;
}

// ── value coercion ────────────────────────────────────────────────────────────

function asNumber(v: Cell): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string") {
    // Tolerate the shapes a formatted export leaves behind: 1,234.5  $1,234  (42)
    const cleaned = v.replace(/[,$\s]/g, "").replace(/^\((.*)\)$/, "-$1");
    if (cleaned === "" ) return null;
    const n = Number(cleaned);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function asText(v: Cell): string {
  return v === null ? "" : String(v);
}

/** Compare as numbers when BOTH sides are numeric, else lexically. Mixing the two is
 *  how "10" sorts before "9" — a wrong answer that looks like a working filter. */
function compare(a: Cell, b: string): number | null {
  const an = asNumber(a);
  const bn = asNumber(b);
  if (an !== null && bn !== null) return an === bn ? 0 : an < bn ? -1 : 1;
  const at = asText(a).toLowerCase();
  const bt = b.toLowerCase();
  return at === bt ? 0 : at < bt ? -1 : 1;
}

// ── grammar ───────────────────────────────────────────────────────────────────

const OPS: { re: RegExp; op: string }[] = [
  { re: /^(.+?)\s*(>=|=>|≥)\s*(.+)$/, op: ">=" },
  { re: /^(.+?)\s*(<=|=<|≤)\s*(.+)$/, op: "<=" },
  { re: /^(.+?)\s*(!=|<>|≠)\s*(.+)$/, op: "!=" },
  { re: /^(.+?)\s*>\s*(.+)$/, op: ">" },
  { re: /^(.+?)\s*<\s*(.+)$/, op: "<" },
  { re: /^(.+?)\s*=\s*(.+)$/, op: "=" },
];

const WORD_OPS: { re: RegExp; op: string }[] = [
  { re: /^(.+?)\s+is\s+not\s+(?:empty|null|blank)$/i, op: "notnull" },
  { re: /^(.+?)\s+is\s+(?:empty|null|blank)$/i, op: "isnull" },
  { re: /^(.+?)\s+does\s+not\s+contain\s+(.+)$/i, op: "!contains" },
  { re: /^(.+?)\s+contains\s+(.+)$/i, op: "contains" },
  { re: /^(.+?)\s+starts\s+with\s+(.+)$/i, op: "starts" },
  { re: /^(.+?)\s+ends\s+with\s+(.+)$/i, op: "ends" },
  { re: /^(.+?)\s+between\s+(.+?)\s+and\s+(.+)$/i, op: "between" },
  { re: /^(.+?)\s+(?:is\s+)?(?:in|one\s+of)\s+(.+)$/i, op: "in" },
  { re: /^(.+?)\s+is\s+not\s+(.+)$/i, op: "!=" },
  { re: /^(.+?)\s+(?:is|equals)\s+(.+)$/i, op: "=" },
  { re: /^(.+?)\s+(?:is\s+)?(?:above|over|greater\s+than|more\s+than)\s+(.+)$/i, op: ">" },
  { re: /^(.+?)\s+(?:is\s+)?(?:below|under|less\s+than|fewer\s+than)\s+(.+)$/i, op: "<" },
  { re: /^(.+?)\s+(?:is\s+)?(?:at\s+least)\s+(.+)$/i, op: ">=" },
  { re: /^(.+?)\s+(?:is\s+)?(?:at\s+most)\s+(.+)$/i, op: "<=" },
  { re: /^(.+?)\s+(?:is\s+)?after\s+(.+)$/i, op: ">" },
  { re: /^(.+?)\s+(?:is\s+)?before\s+(.+)$/i, op: "<" },
];

const RANK_RE = /^(top|bottom)\s+(\d+)(?:\s+(?:by|on)\s+(.+))?$/i;

const OP_WORDS: Record<string, string> = {
  ">": "greater than", ">=": "at least", "<": "less than", "<=": "at most",
  "=": "equals", "!=": "is not", contains: "contains", "!contains": "does not contain",
  starts: "starts with", ends: "ends with", isnull: "is empty", notnull: "is not empty",
  between: "between", in: "one of",
};

function stripQuotes(s: string): string {
  const t = s.trim();
  return (t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))
    ? t.slice(1, -1)
    : t;
}

function buildPredicate(op: string, idx: number, raw: string): (row: Cell[]) => boolean {
  const value = stripQuotes(raw);
  const lower = value.toLowerCase();
  switch (op) {
    case ">":  return (r) => { const c = compare(r[idx], value); return c !== null && c > 0; };
    case ">=": return (r) => { const c = compare(r[idx], value); return c !== null && c >= 0; };
    case "<":  return (r) => { const c = compare(r[idx], value); return c !== null && c < 0; };
    case "<=": return (r) => { const c = compare(r[idx], value); return c !== null && c <= 0; };
    case "=":  return (r) => compare(r[idx], value) === 0;
    case "!=": return (r) => compare(r[idx], value) !== 0;
    case "contains":  return (r) => asText(r[idx]).toLowerCase().includes(lower);
    case "!contains": return (r) => !asText(r[idx]).toLowerCase().includes(lower);
    case "starts": return (r) => asText(r[idx]).toLowerCase().startsWith(lower);
    case "ends":   return (r) => asText(r[idx]).toLowerCase().endsWith(lower);
    // NULL and "" are distinct in a typed result, and conflating them would undo the
    // one thing format:"typed" exists to preserve.
    case "isnull":  return (r) => r[idx] === null || r[idx] === "";
    case "notnull": return (r) => r[idx] !== null && r[idx] !== "";
    case "in": {
      const set = value.split(/\s*,\s*/).map((v) => stripQuotes(v).toLowerCase()).filter(Boolean);
      return (r) => set.includes(asText(r[idx]).toLowerCase());
    }
    default: return () => true;
  }
}

/**
 * Parse one phrase against the result's columns.
 *
 * Never throws and never returns "no filter": an unrecognised phrase becomes a
 * substring search over every column, because at a grid that is what typing text means.
 */
export function parseFilter(phrase: string, columns: string[]): ParsedFilter {
  const text = phrase.trim();
  if (!text) return { clause: null, rank: null };

  const rank = RANK_RE.exec(text);
  if (rank) {
    const [, kind, n, colName] = rank;
    // No column named → rank by the last numeric-looking column, which in a
    // GROUP BY result is almost always the measure.
    const idx = colName ? resolveColumn(columns, colName) : columns.length - 1;
    if (idx < 0) {
      return {
        clause: { text, column: null, describe: text, predicate: () => true,
                  error: `No column matching "${colName?.trim()}"` },
        rank: null,
      };
    }
    return {
      clause: null,
      rank: { kind: kind.toLowerCase() as "top" | "bottom", n: Number(n), columnIndex: idx },
    };
  }

  for (const { re, op } of [...WORD_OPS, ...OPS]) {
    const m = re.exec(text);
    if (!m) continue;
    const colName = m[1];
    const idx = resolveColumn(columns, colName);
    if (idx < 0) continue;   // not a column — keep trying, then fall through to search

    if (op === "between") {
      const [lo, hi] = [stripQuotes(m[2]), stripQuotes(m[3])];
      const ge = buildPredicate(">=", idx, lo);
      const le = buildPredicate("<=", idx, hi);
      return {
        clause: {
          text, column: columns[idx],
          describe: `${columns[idx]} between ${lo} and ${hi}`,
          predicate: (r) => ge(r) && le(r),
        },
        rank: null,
      };
    }

    const rawValue = op === "isnull" || op === "notnull" ? "" : stripQuotes(m[m.length - 1]);
    return {
      clause: {
        text, column: columns[idx],
        describe: `${columns[idx]} ${OP_WORDS[op] ?? op}${rawValue ? ` ${rawValue}` : ""}`,
        predicate: buildPredicate(op, idx, rawValue),
      },
      rank: null,
    };
  }

  // A phrase that LOOKS like a comparison but named no column we have: say so, rather
  // than silently degrading to a text search that would return nothing and look broken.
  for (const { re } of [...WORD_OPS, ...OPS]) {
    const m = re.exec(text);
    if (m && resolveColumn(columns, m[1]) < 0) {
      return {
        clause: {
          text, column: null, describe: text, predicate: () => true,
          error: `No column matching "${m[1].trim()}"`,
        },
        rank: null,
      };
    }
  }

  const needle = text.toLowerCase();
  return {
    clause: {
      text, column: null,
      describe: `any column contains ${text}`,
      predicate: (r) => r.some((c) => asText(c).toLowerCase().includes(needle)),
    },
    rank: null,
  };
}

/** Apply clauses (AND) then ranking. Ranking runs LAST so `top 5` means the top of the
 *  filtered set, which is what chaining a chip after a filter is asking for. */
export function applyFilters(
  rows: Cell[][],
  clauses: FilterClause[],
  ranks: RankSpec[],
): Cell[][] {
  let out = rows;
  const live = clauses.filter((c) => !c.error);
  if (live.length) out = out.filter((r) => live.every((c) => c.predicate(r)));
  for (const rank of ranks) {
    const sorted = [...out].sort((a, b) => {
      const c = compare(a[rank.columnIndex], asText(b[rank.columnIndex]));
      return c ?? 0;
    });
    out = rank.kind === "top" ? sorted.reverse().slice(0, rank.n) : sorted.slice(0, rank.n);
  }
  return out;
}
