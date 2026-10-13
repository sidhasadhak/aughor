"use client";

/**
 * PENDING item 9 — the company-brain map, redone to `aughor-v2/CLARITY.md` (2026-10-13). A map leads with its picture:
 * every store behind what Aughor knows is a box in its vault's column, with its live count and one line, and every
 * measured link is an arrow between two boxes carrying its count — never a drawn relationship. Below the picture, the
 * one list only this screen shows: the facts that changed since first seen, and what each replaced (CB-1).
 *
 * It used to open on a paragraph, set the boxes in a grid with no arrows, and write the links as a bulleted list of
 * sentences beside them. The arrows now sit on the picture (their sentences on hover); an arrow the picture cannot draw
 * without crossing a box is said in words under it. A box whose store could not be read shows a hatched dash and its
 * line says why — never a zero. The route that serves a box rides its hover, for a developer.
 */
import { useEffect, useState, type CSSProperties } from "react";

import { CARD, Chip, Empty, Label, MUTED, NUM, ONE_LINE, Page, RULE } from "@/components/clarity/kit";
import { EmptyState } from "@/components/ui/empty-state";
import { ReadFailed } from "@/components/ui/states";
import { Tooltip } from "@/components/ui/tooltip";
import { getBrainMap, type BrainMap } from "@/lib/api";
import { MAP, boxFigure, edgeShort, mapLayout, recentFacts, type MapLayout } from "@/lib/brainMap";
import { formatCount, formatTimestamp } from "@/lib/format";
import { dayMonth } from "@/lib/home";
import { keyToWords } from "@/lib/names";

export function BrainMapPanel({ connectionId, workspaceId, contextReady = true }: {
  connectionId?: string | null; workspaceId?: string;
  /** False while the shell is still resolving the workspace and its connections: the map
   *  then says it is finding the connection, never that there is none to pick. */
  contextReady?: boolean;
}) {
  const [map, setMap] = useState<BrainMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reads, setReads] = useState(0);   // Retry bumps it

  useEffect(() => {
    if (!connectionId) return;
    let alive = true;
    setMap(null);
    setError(null);
    getBrainMap(connectionId, workspaceId)
      .then((m) => { if (alive) setMap(m); })
      .catch((e) => { if (alive) setError(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [connectionId, workspaceId, reads]);

  if (!connectionId) {
    return contextReady
      ? <EmptyState variant="inline" title="The brain map is per connection. Choose one in the bar above." />
      : <div className="aug-fs-sm" style={{ color: "var(--t3)", padding: 16 }}>Finding your connection…</div>;
  }
  if (error) {
    return (
      <Page testId="brain-map-failed">
        <ReadFailed what="the brain map — no store was changed" error={error} onRetry={() => setReads((n) => n + 1)} />
      </Page>
    );
  }
  if (!map) return <Page><Empty>Reading every store…</Empty></Page>;

  const layout = mapLayout(map);
  return (
    <Page testId="brain-map">
      {/* The picture sits on the ground and its stores are the cards — a box inside a card would be a box in a box. */}
      <section aria-label="Stores and measured links">
        <Label right={<span title="Nothing here is estimated: every box is a store read now, every arrow a count.">
          read live · an arrow is a measured count · a dash, a store not read</span>}>
          Where Aughor&apos;s knowledge lives
        </Label>
        <Picture layout={layout} />
        {layout.unplaced.length > 0 && (
          <div className="aug-fs-sm" data-testid="brain-unplaced" style={{ color: "var(--t2)", marginTop: 10 }}>
            Also measured: {layout.unplaced.join(" · ")}
          </div>
        )}
      </section>
      <ChangedFacts map={map} />
    </Page>
  );
}

// ── The picture ────────────────────────────────────────────────────────────────────────────

const HATCH = "repeating-linear-gradient(135deg, var(--chart-deemph) 0 4px, transparent 4px 7px)";

function Picture({ layout }: { layout: MapLayout }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <div data-testid="brain-picture" style={{ position: "relative", height: layout.height, minWidth: 820 }}>
        {layout.columns.map((c) => (
          <div key={c.id} className="aug-fs-xs" style={{ position: "absolute", left: `${c.x0}%`, width: `${c.x1 - c.x0}%`,
            top: 0, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em", ...ONE_LINE }}>
            {c.title}
          </div>
        ))}

        <svg aria-hidden width="100%" height={layout.height}
          style={{ position: "absolute", inset: 0, overflow: "visible", pointerEvents: "none" }}>
          <defs>
            <marker id="brain-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" style={{ fill: "var(--t3)" }} />
            </marker>
            <marker id="brain-arrow-zero" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" style={{ fill: "var(--b2)" }} />
            </marker>
          </defs>
          {layout.routes.map((r) => r.segs.map((s, i) => (
            <line key={`${r.key}:${i}`} x1={`${s.x1}%`} y1={s.y1} x2={`${s.x2}%`} y2={s.y2}
              style={{ stroke: r.edge.count ? "var(--t3)" : "var(--b2)", strokeWidth: 1.25 }}
              markerEnd={i === r.segs.length - 1 ? `url(#${r.edge.count ? "brain-arrow" : "brain-arrow-zero"})` : undefined} />
          )))}
        </svg>

        {layout.nodes.map((nd) => <StoreBox key={nd.box.id} node={nd} />)}

        {layout.routes.map((r) => (
          <Tooltip key={r.key} content={r.sentence}>
            <span role="img" aria-label={r.sentence} data-testid={`brain-edge-${r.edge.from}-${r.edge.to}`}
              className="aug-fs-xs"
              style={{ position: "absolute", left: `${r.label.x}%`, top: r.label.y,
                transform: r.label.beside ? "translate(6px, -50%)" : "translate(-50%, calc(-100% - 2px))",
                padding: "0 6px", borderRadius: "var(--r-pill)", background: "var(--bg-3)", whiteSpace: "nowrap",
                color: r.edge.count ? "var(--t2)" : "var(--t3)", lineHeight: "17px", ...NUM }}>
              {edgeShort(r.edge)}
            </span>
          </Tooltip>
        ))}
      </div>
    </div>
  );
}

/** One store: its name, its live count, and the one line that says what the count holds — or why there is none. */
function StoreBox({ node }: { node: MapLayout["nodes"][number] }) {
  const { box } = node;
  const unread = box.count === null || box.count === undefined;
  const style: CSSProperties = {
    position: "absolute", left: `${node.x0}%`, width: `${node.x1 - node.x0}%`, top: node.y0, height: MAP.nodeH,
    ...CARD, padding: "9px 12px", display: "flex", flexDirection: "column", gap: 4, overflow: "hidden",
  };
  return (
    // The door (a route) is for a developer: it rides the box's hover, not its face.
    <div data-testid={`brain-box-${box.id}`} title={box.door} style={style}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
        <span className="aug-fs-chrome" style={{ color: "var(--t1)", fontWeight: 500, flex: 1, ...ONE_LINE }}>{box.title}</span>
        <span className="aug-fs-h1" title={unread ? "Not read — the line below says why" : `${formatCount(box.count)} ${box.unit}`}
          style={{ fontWeight: 600, color: unread || box.count === 0 ? "var(--t3)" : "var(--t1)", ...NUM,
            ...(unread ? { background: HATCH, borderRadius: "var(--r1)", padding: "0 6px" } : {}) }}>
          {boxFigure(box)}
        </span>
      </div>
      <span className="aug-fs-xs" title={box.line} style={{ color: unread ? "var(--t2)" : "var(--t3)", lineHeight: 1.45,
        display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {box.line}
      </span>
    </div>
  );
}

// ── The list: facts that changed, and what each replaced ──────────────────────────────────

const KIND_WORDS: Record<string, string> = { glossary_term: "column", table: "table", metric: "metric", finding: "finding", domain: "domain" };

/** A fact as a reader names it: a column as `table.column`, a metric in words, anything else by its label. */
function factName(f: ReturnType<typeof recentFacts>[number]): { text: string; mono: boolean } {
  if (f.kind === "glossary_term") return { text: f.id.slice(f.id.indexOf(":") + 1) || f.label, mono: true };
  if (f.kind === "metric") return { text: keyToWords(f.label), mono: false };
  return { text: f.label, mono: false };
}

function ChangedFacts({ map }: { map: BrainMap }) {
  const box = map.boxes.find((b) => b.id === "facts");
  const facts = recentFacts(map);
  const changed = typeof box?.detail?.with_history === "number" ? (box.detail.with_history as number) : null;
  const unread = !box || box.count === null || box.count === undefined;
  return (
    <section aria-label="Facts that changed" data-testid="brain-facts" style={CARD}>
      <Label right={facts.length > 0 && (changed != null && changed > facts.length
        ? `newest ${formatCount(facts.length)} of ${formatCount(changed)}` : formatCount(facts.length))}>
        Facts that changed, and what each replaced
      </Label>
      {unread ? (
        <Empty>Fact history not read — {box?.line || "the facts store is not on this map"}</Empty>
      ) : facts.length === 0 ? (
        <Empty>No fact has changed since it was first seen.</Empty>
      ) : facts.map((f, i) => {
        const name = factName(f);
        return (
          <div key={f.id} data-testid={`brain-fact-${f.id}`} title={f.id}
            style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 14, alignItems: "center",
              padding: "8px 2px", ...(i ? RULE : {}) }}>
            <div style={{ minWidth: 0 }}>
              <div className="aug-fs-chrome" style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <span className={name.mono ? "aug-fs-sm" : undefined} style={{ color: "var(--t1)", fontWeight: 500, ...ONE_LINE,
                  ...(name.mono ? { fontFamily: "var(--font-mono)" } : {}) }}>{name.text}</span>
                <span className="aug-fs-xs" style={MUTED}>{KIND_WORDS[f.kind] ?? keyToWords(f.kind)}</span>
                {f.reason && f.reason !== "changed" && <Chip>{f.reason}</Chip>}
              </div>
              <div className="aug-fs-xs" title={f.replaced || undefined}
                style={{ ...MUTED, ...ONE_LINE, fontFamily: f.replaced ? "var(--font-mono)" : undefined }}>
                {f.replaced ? <>was {f.replaced}</> : "what it replaced was not kept"}
              </div>
            </div>
            <span className="aug-fs-sm" title={formatTimestamp(f.changed)} style={{ color: "var(--t2)", ...NUM }}>
              {f.changed ? dayMonth(f.changed) : "—"}
            </span>
          </div>
        );
      })}
    </section>
  );
}
