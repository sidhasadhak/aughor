"use client";

/**
 * PENDING item 9 — the company-brain map. Every store behind what Aughor knows is a box with a
 * live count and the door that serves it; every arrow is a measured count, never a drawn
 * relationship. Eight Arc CB waves were built with no screen between them — this is the screen,
 * and the only place CB-1's fact dates and what each fact replaced are shown.
 */
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/states";
import { getBrainMap, type BrainMap } from "@/lib/api";
import { boxFigure, edgeLines, recentFacts, vaultColumns } from "@/lib/brainMap";

export function BrainMapPanel({ connectionId, workspaceId, contextReady = true }: {
  connectionId?: string | null; workspaceId?: string;
  /** False while the shell is still resolving the workspace and its connections: the map
   *  then says it is finding the connection, never that there is none to pick. */
  contextReady?: boolean;
}) {
  const [map, setMap] = useState<BrainMap | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!connectionId) return;
    let alive = true;
    setMap(null);
    setError(null);
    getBrainMap(connectionId, workspaceId)
      .then((m) => { if (alive) setMap(m); })
      .catch((e) => { if (alive) setError(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [connectionId, workspaceId]);

  if (!connectionId) {
    return contextReady
      ? <EmptyState variant="inline" title="The brain map is per connection. Choose one in the bar above." />
      : <div className="aug-fs-sm" style={{ color: "var(--t3)", padding: 16 }}>Finding your connection…</div>;
  }
  if (error) return <ErrorState kind="Brain map unavailable" what={error} means="No store was changed; reload to try again." />;
  if (!map) return <div className="aug-fs-sm" style={{ color: "var(--t3)", padding: 16 }}>Reading every store…</div>;

  const facts = recentFacts(map);
  return (
    <div data-testid="brain-map" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>
        Every store behind what the platform knows, read live. A dash means the store could not be read or is not
        built yet — its line says which. Nothing here is estimated.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
        {vaultColumns(map).map((vault) => (
          <section key={vault.id} aria-label={vault.title} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div className="aug-label">{vault.title}</div>
            {vault.boxes.map((box) => (
              <div key={box.id} data-testid={`brain-box-${box.id}`} title={box.door}
                style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", background: "var(--bg-2)", padding: 10 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                  <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600, flex: 1 }}>{box.title}</span>
                  <span className="aug-fs-h2" style={{ color: "var(--t1)" }}>{boxFigure(box)}</span>
                </div>
                <div className="aug-fs-xs" style={{ color: "var(--t2)", marginTop: 4, lineHeight: 1.5 }}>{box.line}</div>
                {/* The door (a route) is for a developer: it rides the box's tooltip, not its face. */}
              </div>
            ))}
          </section>
        ))}
      </div>
      {map.edges.length > 0 && (
        <section aria-label="Measured links">
          <div className="aug-label" style={{ marginBottom: 6 }}>Measured links between stores</div>
          <ul className="aug-fs-sm" style={{ margin: 0, paddingLeft: 16, color: "var(--t2)" }}>
            {edgeLines(map).map((line) => <li key={line}>{line}</li>)}
          </ul>
        </section>
      )}
      <section aria-label="Facts that changed">
        <div className="aug-label" style={{ marginBottom: 6 }}>Facts that changed, and what they replaced</div>
        {facts.length === 0 ? (
          <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>No fact has changed since it was first seen.</div>
        ) : (
          <ul className="aug-fs-sm" style={{ margin: 0, paddingLeft: 16, color: "var(--t2)" }}>
            {facts.map((f) => (
              <li key={f.id}>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--t1)" }}>{f.id}</span> changed {f.changed}
                {f.replaced ? <> — it replaced <span style={{ fontFamily: "var(--font-mono)" }}>{f.replaced}</span></> : null}
                {f.reason ? ` (${f.reason})` : ""}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
