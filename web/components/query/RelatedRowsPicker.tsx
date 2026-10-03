"use client";

/**
 * DE-5f (ROADMAP §3.51) — the joins a value can be followed through, each with its evidence.
 *
 * The list comes from the server (`GET /connections/{id}/related-joins`): the ontology's relationships
 * with their measured overlap and cardinality, then the verified join map. A join the data bears out is a
 * button; one the values disprove, or a name match nobody probed, is listed with its sentence and not
 * offered — the rows are never opened on a guess. No joins at all is said too, with whether an ontology is
 * built for the connection.
 */
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import type { RelatedJoin, RelatedJoinsAnswer } from "@/lib/api";
import { NULL_GLYPH } from "@/lib/query/cellMenu";
import type { Cell } from "@/lib/query/resultFilter";

function brief(v: Cell): string {
  if (v === null) return NULL_GLYPH;
  const s = String(v);
  return s.length > 24 ? `"${s.slice(0, 23)}…"` : `"${s}"`;
}

export function RelatedRowsPicker({ table, column, value, fetchJoins, onOpen, onClose, x, y }: {
  table: string;
  column: string;
  value: Cell;
  fetchJoins: () => Promise<RelatedJoinsAnswer>;
  onOpen: (join: RelatedJoin) => void;
  onClose: () => void;
  x: number;
  y: number;
}) {
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  const [answer, setAnswer] = useState<RelatedJoinsAnswer | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stale = false;
    setState("loading");
    fetchJoins()
      .then(a => { if (!stale) { setAnswer(a); setState("ready"); } })
      .catch(e => { if (!stale) { setError(e instanceof Error ? e.message : "could not read the joins"); setState("failed"); } });
    return () => { stale = true; };
  }, [fetchJoins]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const left = Math.min(x, (typeof window !== "undefined" ? window.innerWidth : 1e9) - 340);
  const top = Math.min(y, (typeof window !== "undefined" ? window.innerHeight : 1e9) - 320);
  const joins = answer?.joins ?? [];

  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 30 }} onClick={onClose} />
      <div data-testid="related-rows-picker" className="aug-fs-ui" style={{
        position: "fixed", left, top, zIndex: 31, width: 320, maxHeight: 300, display: "flex", flexDirection: "column",
        background: "var(--bg-2)", border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "var(--shadow-md)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 8px 2px" }}>
          <span style={{ color: "var(--t2)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
            Related rows · {column} = {brief(value)}
          </span>
          <Button variant="ghost" size="xs" aria-label="Close" onClick={onClose}><Icon name="close" size={12} /></Button>
        </div>
        <div style={{ overflowY: "auto", flex: 1, minHeight: 0, padding: "0 8px 8px" }}>
          {state === "loading" && (
            <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "4px 0" }}>Reading the joins the data bears out…</div>
          )}
          {state === "failed" && (
            <div className="aug-fs-xs" data-testid="related-note" style={{ color: "var(--red4)", padding: "4px 0" }}>
              The joins could not be read — {error}
            </div>
          )}
          {state === "ready" && joins.length === 0 && (
            <div className="aug-fs-xs" data-testid="related-note" style={{ color: "var(--t3)", padding: "4px 0", lineHeight: 1.5 }}>
              No verified join touches {table}.{column} — nothing to open.
              {answer?.ontology === "not built" ? " No ontology is built for this connection; only the schema's keys and names were read." : ""}
              {answer?.join_map ? ` The join map was ${answer.join_map}.` : ""}
            </div>
          )}
          {state === "ready" && joins.map(j => (
            <div key={`${j.other_table}.${j.other_column}`} data-testid="related-join" style={{ padding: "3px 0" }}>
              <Button variant="ghost" size="xs" className="aug-fs-ui" data-testid="related-open"
                disabled={!j.openable}
                title={j.openable ? "Open these rows through the same door as the query, with the value bound" : j.sentence}
                style={{ width: "100%", justifyContent: "flex-start" }}
                onClick={() => { if (j.openable) { onOpen(j); onClose(); } }}>
                <Icon name="link" size={12} /> {j.other_table} · {j.other_column} = {brief(value)}
              </Button>
              <div className="aug-fs-xs" data-testid="related-sentence" style={{ color: j.openable ? "var(--t3)" : "var(--amb4)", padding: "0 8px" }}>
                {j.sentence} · {j.source === "ontology" ? "the ontology" : "the schema"}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
