"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { type RichSchema } from "@/lib/api";
import { API_BASE } from "@/lib/config";

interface SchemaContextValue {
  connId: string | null;
  schema: RichSchema | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
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
  const [schema, setSchema] = useState<RichSchema | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!connId) {
      setSchema(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15_000);
    fetch(`${API_BASE}/connections/${connId}/schema/rich`, {
      signal: controller.signal,
    })
      .then((r) => {
        if (!r.ok) throw new Error("Failed to load schema");
        return r.json();
      })
      .then((d) => setSchema(d))
      .catch(() => setError("Failed to load schema"))
      .finally(() => {
        setLoading(false);
        clearTimeout(timeout);
      });
    return () => {
      controller.abort();
      clearTimeout(timeout);
    };
  }, [connId, tick]);

  return (
    <SchemaContext.Provider value={{ connId, schema, loading, error, refresh }}>
      {children}
    </SchemaContext.Provider>
  );
}

export function useSchema() {
  return useContext(SchemaContext);
}
