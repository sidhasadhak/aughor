"use client";

/**
 * The ONE read of `GET /connections/{id}/schema/rich`.
 *
 * This file used to hold a bespoke fetch-into-useState provider for a single
 * connection, while seven other components fetched the same endpoint themselves —
 * `CatalogScreen` (×3 sites), `QueryBuilder`, `CommandPalette`, `CanvasCreator`,
 * `SemanticLayerPanel` and `NewCardComposer`. Measured on one page load, that was
 * twenty-plus identical requests, because none of them could see the others.
 *
 * A single-connection provider could never have fixed it: those callers ask about
 * DIFFERENT connections (the catalog's tree selection, the builder's own picker, a
 * canvas being created). So the cache is keyed BY CONNECTION and any component may
 * ask for any connection — `useRichSchema(connId)` — while identical asks collapse
 * into one request.
 *
 * `SchemaProvider` / `useSchema` survive with their exact previous shape so their
 * three consumers (SchemaPanel, ConfigurePanel, CatalogScreen's refresh) needed no
 * change. They are now a thin view over the shared cache rather than a second one.
 *
 * The invalidation contract is unchanged too: `refresh()` still calls
 * `refreshSchemaCache` on the server, and now also drops the client entry so the next
 * read re-fetches instead of serving the pre-refresh answer for another five minutes.
 */
import { createContext, useCallback, useContext, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSchemaRich, refreshSchemaCache, type RichSchema } from "@/lib/api";

/** The cache key for one connection's rich schema. Exported so a caller that needs to
 *  invalidate directly uses the same key rather than re-deriving a matching string. */
export function richSchemaKey(connId: string | null | undefined) {
  return ["schema-rich", connId ?? ""] as const;
}

export interface RichSchemaResult {
  schema: RichSchema | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/**
 * The rich schema for `connId`, shared across every caller asking for the same one.
 * Passing null/empty disables the query rather than fetching nothing — a component
 * rendering before its connection resolves should not issue a request.
 */
export function useRichSchema(connId: string | null | undefined): RichSchemaResult {
  const qc = useQueryClient();
  const enabled = !!connId;

  const { data, isLoading, isError } = useQuery({
    queryKey: richSchemaKey(connId),
    queryFn: () => getSchemaRich(connId as string),
    enabled,
  });

  const refresh = useCallback(() => {
    if (!connId) return;
    // Server-side cache first, then the client entry — in that order, so the refetch
    // this triggers cannot race ahead and repopulate from the stale server cache.
    refreshSchemaCache(connId)
      .catch(() => { /* a failed server refresh still warrants a client refetch */ })
      .finally(() => { qc.invalidateQueries({ queryKey: richSchemaKey(connId) }); });
  }, [connId, qc]);

  return {
    schema: data ?? null,
    loading: enabled && isLoading,
    error: isError ? "Failed to load schema" : null,
    refresh,
  };
}

// ── The original context API, preserved ───────────────────────────────────────
// Kept because three components consume it and their call sites are correct as
// written; changing them would have been churn, not improvement.

interface SchemaContextValue extends RichSchemaResult {
  connId: string | null;
}

const SchemaContext = createContext<SchemaContextValue>({
  connId: null,
  schema: null,
  loading: false,
  error: null,
  refresh: () => {},
});

export function SchemaProvider({
  connId,
  children,
}: {
  connId: string | null;
  children: React.ReactNode;
}) {
  const { schema, loading, error, refresh } = useRichSchema(connId);
  const value = useMemo(
    () => ({ connId, schema, loading, error, refresh }),
    [connId, schema, loading, error, refresh],
  );
  return <SchemaContext.Provider value={value}>{children}</SchemaContext.Provider>;
}

export function useSchema() {
  return useContext(SchemaContext);
}
