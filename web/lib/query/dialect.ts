/**
 * SE-1 — one mapping from a connection's engine to the SQL dialects the editor needs.
 *
 * Two consumers with different vocabularies: CodeMirror's `@codemirror/lang-sql` ships
 * a small set of dialect objects (they drive tokenizing, quoting and keyword
 * completion), and sql-formatter names its languages differently again. Both derive
 * from the same fact — what engine will actually run this SQL — so the derivation
 * lives here once rather than as two `switch` statements that drift.
 *
 * The engine vocabulary is the backend's, not an invented one: `conn_type` values come
 * from `aughor/connectors/registry.py`, and `dialect` (the SE-0 field, when present)
 * from `aughor/db/dialects.py`, whose rule table knows bigquery · snowflake · mysql ·
 * postgres. Anything unrecognised resolves to StandardSQL rather than guessing — a
 * wrong dialect mis-tokenizes the user's SQL, which is worse than a neutral one.
 *
 * DuckDB maps to PostgreSQL deliberately: DuckDB's grammar is explicitly
 * Postgres-compatible, and CM6 ships no DuckDB dialect. That is a closer fit than
 * StandardSQL for the engine most of this product's connections actually use.
 */
import {
  MySQL,
  PostgreSQL,
  SQLDialect,
  SQLite,
  StandardSQL,
} from "@codemirror/lang-sql";
import { CONNECTORS } from "@/lib/connectors.gen";

/** The engine facts we get from a connection row. Both fields are optional because
 *  `dialect` only exists on connections that went through the SE-0 contract. */
export interface EngineHint {
  conn_type?: string | null;
  dialect?: string | null;
}

/** Normalised engine family — the single thing both mappings below switch on. */
export type EngineFamily =
  | "postgres"
  | "mysql"
  | "sqlite"
  | "bigquery"
  | "snowflake"
  | "standard";

/** DE-3b: the family is one fact on each engine's declaration (`engineFamily` in
 *  `lib/connectors.gen.ts`, generated from `aughor/connectors/declarations.py`), looked up by
 *  connector type or by dialect. The dialect names below are the ones a connection row can
 *  carry that are not themselves a connector type. DuckDB is the load-bearing entry: it is
 *  this product's default engine and has no CM6 dialect, and its grammar is Postgres-shaped. */
const DIALECT_FAMILY: Record<string, EngineFamily> = {
  duckdb: "postgres", postgres: "postgres", postgresql: "postgres", aughor_ops: "postgres",
  mysql: "mysql", mariadb: "mysql", sqlite: "sqlite", bigquery: "bigquery", snowflake: "snowflake",
};

function familyOf(raw: string): EngineFamily | null {
  const byType = CONNECTORS[raw];
  if (byType) return byType.engineFamily as EngineFamily;
  const byDialect = Object.values(CONNECTORS).find(c => c.dialect === raw);
  if (byDialect) return byDialect.engineFamily as EngineFamily;
  return DIALECT_FAMILY[raw] ?? null;
}

export function engineFamily(hint: EngineHint | null | undefined): EngineFamily {
  // `dialect` wins when present: it is the backend's own declaration of what will
  // execute the SQL, while conn_type only says how we connected.
  const raw = (hint?.dialect || hint?.conn_type || "").trim().toLowerCase();
  if (!raw) return "standard";
  return familyOf(raw) ?? "standard";
}

/** The CodeMirror dialect for this connection — drives tokenizing and keyword
 *  completion. BigQuery and Snowflake have no CM6 dialect of their own; StandardSQL
 *  is the honest fallback (their DDL/DML core is ANSI-shaped). */
export function cmDialect(hint: EngineHint | null | undefined): SQLDialect {
  switch (engineFamily(hint)) {
    case "postgres":  return PostgreSQL;
    case "mysql":     return MySQL;
    case "sqlite":    return SQLite;
    default:          return StandardSQL;
  }
}

/** Quote an identifier for this engine, but ONLY when it needs it.
 *
 *  Written for SE-6's wildcard expansion, which found the real hazard immediately: the
 *  Superstore table's columns are `Row ID`, `Sub-Category`, `Postal Code`. Pasting
 *  those bare into a SELECT list produces SQL that does not parse, so an intention that
 *  did not quote would hand the user a broken query and call it help. Quoting
 *  everything is the other failure — `"orders"` is case-sensitive in Postgres and
 *  DuckDB, so blanket quoting can turn a working reference into a missing one.
 *
 *  The rule is therefore: quote only a name that is not a plain lower-case identifier.
 *  MySQL uses backticks; BigQuery's backtick quoting applies to whole paths, so a bare
 *  column there takes the same double quotes ANSI gives it. */
export function quoteIdentifier(name: string, hint: EngineHint | null | undefined): string {
  if (/^[a-z_][a-z0-9_$]*$/.test(name)) return name;
  // Already quoted by whoever wrote it — leave it exactly as it is.
  if (/^(".*"|`.*`|\[[^]*])$/.test(name)) return name;
  if (engineFamily(hint) === "mysql") return `\`${name.replace(/`/g, "``")}\``;
  return `"${name.replace(/"/g, '""')}"`;
}

/** How this engine spells "explain the plan" — or null when it has no such statement.
 *
 *  Measured live before this existed: an unconditional `EXPLAIN` button on a BigQuery
 *  connection returned `400 Statement not supported: ExplainStatement`. BigQuery has no
 *  EXPLAIN — its plan lives in the job statistics of a dry run — so the honest thing is
 *  to not offer the button there. A control that always fails is worse than a missing
 *  one: it teaches the user that the feature is broken rather than absent.
 *
 *  SQLite is the other special case: plain `EXPLAIN` there dumps VDBE bytecode, which
 *  is not what anyone means; `EXPLAIN QUERY PLAN` is. */
export function explainPrefix(hint: EngineHint | null | undefined): string | null {
  switch (engineFamily(hint)) {
    case "postgres":  return "EXPLAIN";
    case "mysql":     return "EXPLAIN";
    case "snowflake": return "EXPLAIN";
    case "sqlite":    return "EXPLAIN QUERY PLAN";
    case "bigquery":  return null;
    default:          return null;
  }
}

/** The sql-formatter language id for this connection (SE-2 uses it for Format;
 *  defined here so the two mappings cannot drift apart later). */
export function formatterLanguage(hint: EngineHint | null | undefined): string {
  switch (engineFamily(hint)) {
    case "postgres":  return "postgresql";
    case "mysql":     return "mysql";
    case "sqlite":    return "sqlite";
    case "bigquery":  return "bigquery";
    case "snowflake": return "snowflake";
    default:          return "sql";
  }
}
