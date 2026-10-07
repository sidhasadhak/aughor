/**
 * The schema a person last chose for a connection, remembered per browser.
 *
 * Intelligence has its own schema picker and the Semantic Layer has another. On a connection that
 * holds several datasets they disagreed: a Briefing read on `uber_ncr` showed six Key Metrics while
 * the Semantic Layer, asked for no schema, listed none of the metrics the explorer had proposed for
 * that dataset (2026-10-07). The pickers stay separate; the choice made in one is the other's
 * default. A per-viewer convenience — storage that is refused or empty simply means no default.
 */
const KEY = (connectionId: string) => `aughor_schema_choice:${connectionId}`;

export function rememberSchema(connectionId: string, schema: string | null | undefined): void {
  if (!connectionId || !schema) return;
  try { window.localStorage.setItem(KEY(connectionId), schema); } catch { /* storage refused */ }
}

export function rememberedSchema(connectionId: string): string | null {
  if (!connectionId) return null;
  try { return window.localStorage.getItem(KEY(connectionId)); } catch { return null; }
}

/** The schema a per-connection view should read when its own picker is unset: none for a
 *  connection with one dataset (the server reads its declared schema), else the remembered
 *  choice when it is still one of the connection's schemas, else the first. */
export function defaultSchema(connectionId: string, schemas: readonly string[]): string {
  if (schemas.length < 2) return "";
  const kept = rememberedSchema(connectionId);
  return kept && schemas.includes(kept) ? kept : schemas[0];
}
