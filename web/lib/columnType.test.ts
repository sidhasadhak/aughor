/**
 * The type mark's classifier, held against the spellings this product actually serves.
 *
 * ── WHY THIS TEST EXISTS ─────────────────────────────────────────────────────
 * The rule it guards failed in production the first time it was looked at. The
 * frontend's old `isNum` read `\bINT\b`, and `INT64` has no word boundary between `T`
 * and `6` — so on the Catalog screen, which serves theLook in BigQuery's spellings,
 * `order_id INT64` classified as "not a number" and drew a blank mark, while the SQL
 * rail, fed by a different endpoint that says `INTEGER`, drew the right one for the
 * same column. Two spellings of one column, two answers.
 *
 * The backend had already been bitten by this and written the fix down in
 * `aughor/tools/profiler.py` ("every BigQuery numeric typed as unknown and no measure
 * could ever exist there"). The first assertion below therefore does not trust a list
 * copied by hand: it READS that regex out of the Python source and requires the two
 * sides of the wire to agree on every spelling. A spelling added there and not here
 * fails this test, which is the only way the drift gets caught before a screen does.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { columnTypeKind, isNumericType, type ColumnTypeKind } from "@/lib/format";

const REPO = fileURLToPath(new URL("../..", import.meta.url));

/** Split on `|` at the TOP level only — `(?:A|B)` is one alternative, not two. */
function splitAlternatives(body: string): string[] {
  const out: string[] = [];
  let depth = 0, cur = "";
  for (const ch of body) {
    if (ch === "(") depth++;
    else if (ch === ")") depth--;
    if (ch === "|" && depth === 0) { out.push(cur); cur = ""; } else cur += ch;
  }
  return [...out, cur];
}

/** Every concrete string one alternative can spell. Handles exactly what this pattern
 *  uses — a literal, an optional character (`U?`), a group (`(?:A|B)`) and an optional
 *  group (`(?:64)?`) — and would throw rather than quietly under-expand anything else. */
function expand(alt: string): string[] {
  let out = [""];
  const push = (opts: string[]) => { out = out.flatMap(p => opts.map(o => p + o)); };
  for (let i = 0; i < alt.length; ) {
    if (alt.startsWith("(?:", i)) {
      let depth = 0, j = i;
      for (; j < alt.length; j++) {
        if (alt[j] === "(") depth++;
        else if (alt[j] === ")" && --depth === 0) break;
      }
      const inner = splitAlternatives(alt.slice(i + 3, j)).flatMap(expand);
      const optional = alt[j + 1] === "?";
      push(optional ? [...inner, ""] : inner);
      i = j + (optional ? 2 : 1);
    } else if (alt[i + 1] === "?") {
      push([alt[i], ""]);
      i += 2;
    } else {
      if ("()[]{}*+".includes(alt[i])) throw new Error(`unexpanded regex syntax at ${alt.slice(i)}`);
      push([alt[i]]);
      i += 1;
    }
  }
  return out;
}

/** The alternatives inside `profiler.py::_NUMERIC_TYPES`, expanded into concrete type
 *  names. Python's `re` and JS's RegExp agree on everything this pattern uses, so the
 *  expansion is mechanical: strip the comments, join the adjacent string literals, and
 *  read the alternation. */
function backendNumericSpellings(): string[] {
  const src = readFileSync(`${REPO}/aughor/tools/profiler.py`, "utf8");
  const block = src.slice(src.indexOf("_NUMERIC_TYPES = re.compile("));
  const pattern = block
    .slice(0, block.indexOf("re.IGNORECASE"))
    // The comment above the pattern QUOTES the word "unknown" while explaining the bug
    // this file exists for, and a literal-scan that keeps it reads the explanation as
    // part of the regex. Comments go first.
    .replace(/#[^\n]*/g, "")
    .split("\n").map(l => l.trim()).filter(l => /^r?"/.test(l))
    .map(l => l.replace(/^r?"/, "").replace(/",?\s*$/, ""))
    .join("");
  expect(pattern, "profiler.py no longer spells _NUMERIC_TYPES as a literal").toContain("BIGINT");

  const body = pattern.replace(/^\\b\(/, "").replace(/\)\\b$/, "");
  return [...new Set(splitAlternatives(body).flatMap(expand))].filter(Boolean);
}

describe("columnTypeKind", () => {
  it("calls a number every spelling the backend's profiler calls a number", () => {
    const spellings = backendNumericSpellings();
    expect(spellings.length).toBeGreaterThan(12);
    expect(spellings).toContain("INT64");
    const disagreed = spellings.filter(t => columnTypeKind(t) !== "num");
    expect(disagreed, "frontend disagrees with profiler.py::_NUMERIC_TYPES").toEqual([]);
  });

  /** Measured 2026-09-20 off the running API: every distinct `type` string the rich
   *  schema served across all seven live connections, plus the BigQuery spellings the
   *  Catalog screen serves for the same tables. A real catalog, not an invented one. */
  it.each([
    ["VARCHAR", "text"], ["STRING", "text"], ["INTEGER", "num"], ["BIGINT", "num"],
    ["DOUBLE", "num"], ["BOOLEAN", "bool"], ["TIMESTAMP", "time"], ["FLOAT", "num"],
    ["DATE", "date"], ["GEOGRAPHY", "geo"], ["INT64", "num"], ["FLOAT64", "num"],
  ] as [string, ColumnTypeKind][])("serves %s as %s", (type, kind) => {
    expect(columnTypeKind(type)).toBe(kind);
  });

  /** The dialects this app connects to spell the same nine ideas differently; a mark
   *  that only knew DuckDB would be blank on half of them. */
  it.each([
    // DuckDB · Postgres · MySQL · Snowflake · BigQuery · Spark
    ["UBIGINT", "num"], ["HUGEINT", "num"], ["DECIMAL(18,3)", "num"], ["int4", "num"],
    ["float8", "num"], ["double precision", "num"], ["NUMBER(38,0)", "num"],
    ["BIGNUMERIC", "num"], ["serial", "num"], ["money", "num"],
    ["character varying(255)", "text"], ["bpchar", "text"], ["TEXT", "text"],
    ["UUID", "text"], ["ENUM", "text"],
    ["TIMESTAMP_NTZ", "time"], ["timestamp without time zone", "time"],
    ["TIMESTAMPTZ", "time"], ["DATETIME", "time"], ["TIME", "time"], ["INTERVAL", "time"],
    ["BOOL", "bool"], ["BIT", "bool"],
    ["JSONB", "json"], ["STRUCT<a INT>", "json"], ["ARRAY<STRING>", "json"],
    ["VARIANT", "json"], ["MAP", "json"],
    ["BYTEA", "binary"], ["BLOB", "binary"], ["BYTES", "binary"], ["VARBINARY", "binary"],
    ["GEOMETRY", "geo"],
  ] as [string, ColumnTypeKind][])("reads %s as %s", (type, kind) => {
    expect(columnTypeKind(type)).toBe(kind);
  });

  /** A day is not an instant. This is the distinction the coloured dot threw away —
   *  both were blue — and half the questions this product answers are "per day". */
  it("tells DATE and DATETIME apart", () => {
    expect(columnTypeKind("DATE")).toBe("date");
    expect(columnTypeKind("DATETIME")).toBe("time");
    expect(columnTypeKind("TIMESTAMP")).not.toBe(columnTypeKind("DATE"));
  });

  /** An unrecognised type must not borrow another kind's glyph: a mark that says text
   *  on a column nobody typed is a confident lie, and grouping by it is a real action a
   *  reader would take on the strength of it. */
  it.each(["", null, undefined, "SOMETHING_ELSE", "vector(1536)"])(
    "leaves %o unknown rather than guessing", type => {
      expect(columnTypeKind(type)).toBe("unknown");
    });

  /** The numeric gate that decides which columns get a distribution is now the SAME
   *  rule as the mark, so a column can no longer read as a number and profile as text. */
  it("is the one definition of numeric", () => {
    for (const t of ["INT64", "UBIGINT", "DECIMAL(9,2)", "float8"]) {
      expect(isNumericType(t)).toBe(true);
      expect(columnTypeKind(t)).toBe("num");
    }
    for (const t of ["VARCHAR", "TIMESTAMP", "BOOLEAN", "GEOGRAPHY", null]) {
      expect(isNumericType(t)).toBe(false);
    }
  });
});

/**
 * Every type the app itself offers a person — the Catalog screen's type editor and the
 * upload cast picker — must have a mark. These are read out of the components' source
 * rather than copied here: a type added to either picker and not to the classifier
 * would otherwise ship a blank glyph on a type WE put in the dropdown.
 */
describe("the types this app lets a person choose", () => {
  const listFrom = (file: string, name: string): string[] => {
    const src = readFileSync(`${REPO}/web/components/${file}`, "utf8");
    const m = src.match(new RegExp(`${name}\\s*(?::[^=]*)?=\\s*\\[([^\\]]*)\\]`));
    expect(m, `${name} not found in ${file}`).toBeTruthy();
    return [...m![1].matchAll(/"([^"]+)"/g)].map(x => x[1]);
  };

  it.each([
    ["CatalogScreen.tsx", "TYPE_OPTIONS"],
    ["AddDataPanel.tsx", "CAST_TYPES"],
  ])("%s · %s all classify", (file, name) => {
    const types = listFrom(file, name);
    expect(types.length).toBeGreaterThan(5);
    expect(types.filter(t => columnTypeKind(t) === "unknown")).toEqual([]);
  });
});
