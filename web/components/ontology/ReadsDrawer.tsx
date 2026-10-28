"use client";

/**
 * Arc FA, FA-3 — every entity of the scope by its reads over the last thirty days, the least read first: the list a
 * person cleaning up the ontology reads before marking something retiring or withdrawing it (ROADMAP §3.60).
 *
 * One door (`GET /object-types/uses?window=30`): each entity with how many audited
 * statements named its tables, the day it was last read and how many people read it where the session log says who.
 * What is not counted says why — no table bound, or a log that could not be read — and is listed last, never as zero;
 * a table two entities are read from is said beside each, because a statement naming it counts for both.
 */
import React, { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { SkeletonRows } from "@/components/ui/motion";
import { countNoun, formatCount, utcDayWords } from "@/lib/format";
import { getEntitiesByReads, type EntitiesByReads, type EntityReadsRow } from "@/lib/objectTypes";

const RULE = "1px solid var(--b1)";

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** The muted line under an entity's name: its tables, when it was last read, who read it, and what it shares. */
function metaOf(row: EntityReadsRow, days: number): string {
  if (row.reads == null) return row.said || "not counted";
  const parts = [row.tables.join(" · ")];
  parts.push(row.last_read ? `last read ${utcDayWords(row.last_read)}` : `not read in ${days} days`);
  if (row.readers != null && row.reads > 0) parts.push(countNoun(row.readers, "reader"));
  if (row.unattributed) parts.push(`${formatCount(row.unattributed)} with no reader recorded`);
  return parts.filter(Boolean).join(" · ");
}

export function ReadsDrawer({ connectionId, schema, onClose }: {
  connectionId: string;
  schema?: string;
  onClose: () => void;
}) {
  const [state, setState] = useState<EntitiesByReads | null>(null);
  const [said, setSaid] = useState("");
  useEffect(() => {
    let live = true;
    setState(null);
    setSaid("");
    getEntitiesByReads(connectionId, schema, 30)
      .then((next) => { if (live) setState(next); })
      .catch((e: unknown) => { if (live) setSaid(errorText(e)); });
    return () => { live = false; };
  }, [connectionId, schema]);

  return (
    <aside aria-label="Reads by entity" data-testid="ontology-reads-drawer"
      style={{ width: 400, flexShrink: 0, borderLeft: RULE, display: "flex", flexDirection: "column", minHeight: 0,
               background: "var(--bg-0)" }}>
      <header style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 16px", borderBottom: RULE }}>
        <h3 className="aug-fs-xs"
          style={{ margin: 0, color: "var(--t2)", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".06em" }}>
          Reads · {state?.days ?? 30} days
        </h3>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>least read first</span>
        <Button variant="ghost" size="icon-xs" onClick={onClose} aria-label="Close" style={{ marginLeft: "auto" }}>
          <Icon name="close" size={13} />
        </Button>
      </header>
      <div style={{ flex: 1, overflowY: "auto", padding: "4px 16px 16px" }}>
        {said && <p className="aug-fs-sm" style={{ color: "var(--t3)" }}>{said}</p>}
        {!state && !said && <div style={{ paddingTop: 12 }}><SkeletonRows rows={6} /></div>}
        {state?.said && <p className="aug-fs-xs" style={{ color: "var(--amb4)" }}>{state.said}</p>}
        {state && state.entities.length === 0 && (
          <p className="aug-fs-sm" style={{ color: "var(--t3)" }}>This ontology has no entities yet.</p>
        )}
        {state && state.entities.length > 0 && (
          <ol style={{ margin: 0, padding: 0 }}>
            {state.entities.map((row) => (
              <li key={`reads:${row.entity}`} data-testid="ontology-reads-row"
                style={{ listStyle: "none", padding: "8px 0", borderTop: RULE }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                  <span className="aug-fs-sm" style={{ color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis",
                                                       whiteSpace: "nowrap" }} title={row.object_type}>
                    {row.display_name}
                  </span>
                  {row.part_of && <span className="aug-tag aug-tag-gray">part</span>}
                  <span className="aug-fs-sm" style={{ marginLeft: "auto", fontVariantNumeric: "tabular-nums",
                                                       color: row.reads == null ? "var(--t3)" : "var(--t1)" }}
                    data-testid="ontology-reads-count">
                    {row.reads == null ? "not counted" : countNoun(row.reads, "read")}
                  </span>
                </div>
                <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>{metaOf(row, state.days)}</div>
                {row.shared_said && (
                  <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>Shared table: {row.shared_said}</div>
                )}
              </li>
            ))}
          </ol>
        )}
        {state && (
          <p className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 12 }}>
            Counted from {state.source}; a reader is the person the session log names for the run.
          </p>
        )}
      </div>
    </aside>
  );
}
