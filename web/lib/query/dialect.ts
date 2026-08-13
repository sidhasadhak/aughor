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

/** Engines whose grammar is Postgres-compatible for editing purposes. DuckDB is the
 *  load-bearing entry: it is this product's default engine and has no CM6 dialect. */
const POSTGRES_FAMILY = new Set([
  "duckdb", "postgres", "postgresql", "local_upload", "aughor_ops", "motherduck",
  "federated", "exasol",
]);

export function engineFamily(hint: EngineHint | null | undefined): EngineFamily {
  // `dialect` wins when present: it is the backend's own declaration of what will
  // execute the SQL, while conn_type only says how we connected.
  const raw = (hint?.dialect || hint?.conn_type || "").trim().toLowerCase();
  if (!raw) return "standard";
  if (POSTGRES_FAMILY.has(raw)) return "postgres";
  if (raw === "mysql" || raw === "mariadb") return "mysql";
  if (raw === "sqlite") return "sqlite";
  if (raw === "bigquery") return "bigquery";
  if (raw === "snowflake") return "snowflake";
  return "standard";
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
