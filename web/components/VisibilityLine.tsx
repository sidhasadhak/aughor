"use client";

/**
 * VisibilityLine — one sentence in the ontology header (CB-5, 2026-09-23): how much of the business
 * the platform can see on this connection, and the one missing definition holding sends back.
 * Deterministic numbers from GET /visibility: the profiler's tables against the ontology's mapped
 * ones (declared exclusions out of the denominator), the joins that were measured, and the held
 * sends grouped by the definition that would clear them. Renders nothing while loading or on
 * failure — a header line that guesses would be worse than none.
 */
import { useEffect, useState } from "react";
import { getVisibility, type Visibility } from "@/lib/api";

export function VisibilityLine({ connectionId, schema }: { connectionId: string; schema?: string }) {
  const [v, setV] = useState<Visibility | null>(null);

  useEffect(() => {
    let alive = true;
    setV(null);
    getVisibility(connectionId, schema).then(d => { if (alive) setV(d); }).catch(() => { /* say nothing rather than guess */ });
    return () => { alive = false; };
  }, [connectionId, schema]);

  if (!v || !v.line) return null;
  const band = v.tables.band;
  const title = [
    v.tables.basis === "profiler"
      ? `${v.tables.mapped} of ${v.tables.in_scope} tables mapped to business objects${v.tables.unmapped.length ? ` · not yet: ${v.tables.unmapped.slice(0, 6).join(", ")}${v.tables.unmapped.length > 6 ? "…" : ""}` : ""}`
      : v.tables.note,
    v.definitions.length ? `held sends by missing definition: ${v.definitions.map(d => `${d.definition} (${d.holds})`).join(", ")}` : "no send is held for a missing definition",
  ].join("\n");
  return (
    <span
      data-testid="visibility-line"
      title={title}
      className={`aug-fs-xs border rounded-[var(--r-chip)] px-2 py-0.5 ${band === "red" ? "border-zinc-500 text-zinc-200" : "border-zinc-700 text-zinc-400"}`}
    >
      {v.line}
    </span>
  );
}
