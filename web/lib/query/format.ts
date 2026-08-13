/**
 * SE-2 PR C — SQL formatting, dialect-aware.
 *
 * Uses the same engine mapping as the editor's tokenizer (`dialect.ts`), so the
 * formatter and the highlighter never disagree about what dialect this connection
 * speaks — sql-formatter ships both `duckdb` and `postgresql`, and picking the wrong
 * one silently mangles dialect-specific syntax.
 *
 * Formatting NEVER throws. A buffer mid-edit is frequently unparseable, and ⌘⇧F on a
 * half-typed statement must be a no-op, not an error dialog — the user's text is
 * returned unchanged and they keep typing.
 */
import { format as sqlFormat, supportedDialects, type SqlLanguage } from "sql-formatter";
import { formatterLanguage, type EngineHint } from "@/lib/query/dialect";

/** The library's OWN list, not a hand-copied one — a hardcoded set would drift the
 *  moment sql-formatter adds or renames a dialect, and drift here means silently
 *  formatting DuckDB as generic SQL. */
const SUPPORTED = new Set<string>(supportedDialects);

export function formatSql(sql: string, engine: EngineHint | null | undefined): string {
  if (!sql.trim()) return sql;
  const mapped = formatterLanguage(engine);
  const language = (SUPPORTED.has(mapped) ? mapped : "sql") as SqlLanguage;
  try {
    return sqlFormat(sql, {
      language,
      keywordCase: "upper",
      // Two spaces matches the editor's own indent unit and this codebase's SQL.
      tabWidth: 2,
      linesBetweenQueries: 1,
    });
  } catch {
    // Unparseable mid-edit text is the common case, not an exceptional one.
    return sql;
  }
}
