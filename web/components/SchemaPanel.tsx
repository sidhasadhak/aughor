"use client";

import { useEffect, useState } from "react";
import { getSchemaRich, RichSchema } from "@/lib/api";
// SchemaCards kept for potential future use
// import { SchemaCards } from "./SchemaCards";
import { ERDiagram } from "./ERDiagram";

interface Props {
  connId: string | null;
  connName?: string;
}

export function SchemaPanel({ connId, connName }: Props) {
  const [richSchema, setRichSchema] = useState<RichSchema | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!connId) { setRichSchema(null); return; }
    setLoading(true);
    setError(null);
    getSchemaRich(connId)
      .then(setRichSchema)
      .catch(() => setError("Failed to load schema."))
      .finally(() => setLoading(false));
  }, [connId]);

  if (!connId) {
    return (
      <div className="flex-1 flex items-center justify-center border-l border-zinc-600">
        <p className="text-xs text-zinc-500">Select a connection to view its schema</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0 border-l border-zinc-600">
      {/* Header */}
      <div className="px-4 h-10 flex items-center border-b border-zinc-600 shrink-0">
        <span className="text-xs font-medium text-zinc-400">Schema</span>
        {loading && <span className="text-xs text-zinc-500 ml-auto">Loading…</span>}
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {error ? (
          <div className="p-4">
            <p className="text-xs text-red-400">{error}</p>
          </div>
        ) : loading ? (
          <div className="p-4 space-y-3 animate-pulse">
            {[70, 50, 85, 60, 75].map((w, i) => (
              <div key={i} className="h-3 bg-zinc-800 rounded" style={{ width: `${w}%` }} />
            ))}
          </div>
        ) : richSchema ? (
          <ERDiagram schema={richSchema} />
        ) : null}
      </div>
    </div>
  );
}
