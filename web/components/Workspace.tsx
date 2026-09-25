"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

/**
 * One perspective layer of a `<Workspace>` — an id, a switcher icon, a label,
 * and a one-line blurb shown in the header and the switcher tooltip.
 */
export type WorkspaceLayer<L extends string> = { id: L; icon: string; label: string; blurb: string };

type WorkspaceProps<L extends string> = {
  /** The perspective layers, in switcher order. */
  layers: WorkspaceLayer<L>[];
  /** Active layer — controlled by the shell so external nav can deep-link. */
  layer: L;
  onLayerChange: (l: L) => void;
  /** `aria-label` for the layer switcher's `role="tablist"`. */
  ariaLabel: string;
  /** Render a layer's switcher icon at a given size/colour — kept injectable so the
   *  primitive owns no icon set (each workspace brings its own). */
  renderIcon: (icon: string, size: number, color: string) => React.ReactNode;
  /** The workspace's name, shown as the header's title ("Agent Ops", "Intelligence").
   *  Without it the active layer's label stands in, which repeats the tab under it. */
  title?: string;
  /** Optional controls that SCOPE the view — a connection, a schema. Since 2026-09-25 they
   *  render in the context bar, the 36px row under the header, never in the header itself:
   *  the header carries the title and the one action, and nothing else. */
  headerControls?: React.ReactNode;
  /** Optional controls pinned to the RIGHT of the header, after the switcher.
   *  `headerControls` sits between the title and the switcher and is for things that
   *  SCOPE the view — a range, a connection. This slot is for the one thing that is an
   *  ACTION rather than a filter, and an action does not belong in the middle of a row
   *  of view controls. */
  headerTrailing?: React.ReactNode;
  /** Optional toolbar — the 36px row UNDER the header for what SCOPES the view: a range,
   *  a filter, a search. One row of its own, so it never competes with the layer
   *  switcher for the header's width (at 1024 the Agent Ops range used to draw under
   *  the switcher). Rendered only when given. */
  toolbar?: React.ReactNode;
  /** Render the body of a layer. Called only for visited layers (keep-alive). */
  renderLayer: (id: L) => React.ReactNode;
  /** Optional live counts shown as a chip on a layer's switcher tab (e.g. the
   *  Attention layer's "needs a human" count). Zero/undefined renders nothing —
   *  a badge must mean something is actually waiting. */
  badges?: Partial<Record<L, number>>;
  /** Drop the header row entirely. For the ONE workspace whose layers each already
   *  have their own item in the left rail (Data: Catalog / SQL Editor / Semantic
   *  Layer), the header is a second copy of a control the rail already provides —
   *  a 44px band that repeats the rail's answer to "where am I". The other
   *  workspaces fold several rail items into fewer layers, or none at all, so their
   *  switcher is the only way to reach a layer and the header stays. */
  headerless?: boolean;
};

/**
 * The one Workspace shell — the region stack (header 44 · context bar 36 · layer tabs 36 ·
 * toolbar 36) over a keep-alive layered body. Extracted from
 * `IntelligenceWorkspace` so Intelligence / Canvas / Operations are all *instances* of
 * one shell rather than three hand-rolled copies of the same layer chrome (Part 2
 * Track B — "one shell").
 *
 * Keep-alive: a layer is mounted the first time it becomes active and then stays
 * mounted (display toggled), so graph zoom / scroll / fetch state survives layer
 * switches. Layers that have never been visited aren't mounted at all.
 */
export function Workspace<L extends string>({
  layers, layer, onLayerChange, ariaLabel, title, headerControls, headerTrailing, toolbar,
  renderLayer, badges, headerless,
}: WorkspaceProps<L>) {
  // Mount a layer the first time it becomes active, then keep it mounted.
  const [visited, setVisited] = useState<Set<L>>(() => new Set([layer]));
  useEffect(() => {
    setVisited(prev => (prev.has(layer) ? prev : new Set(prev).add(layer)));
  }, [layer]);

  const active = layers.find(l => l.id === layer)!;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
      {/* The region stack (docs/UI_UX_STUDY_2026-09-25.md §4.3, implemented 2026-09-25):
          header 44 — the workspace's name and its ONE action;
          context bar 36 — what scopes the view (a connection, a schema), when there is one;
          layer tabs 36 — the perspectives, underlined, in a row that scrolls rather than clips;
          toolbar 36 — what filters the view (a range, a search), when there is one.
          The header used to hold the title, the scope pickers, the segmented switcher AND the
          action in one 44px row: at 1024 the Intelligence header's tenth control sat at
          1201px, and the Agent Ops range drew under its own tabs. One job per row. */}
      {!headerless && (
      <div className="aug-content-header" style={{ flexWrap: "nowrap", minWidth: 0, overflow: "hidden" }}>
        <span className="aug-content-title" style={{ flexShrink: 0 }}>{title ?? active.label}</span>
        <span style={{ flex: 1 }} />
        {headerTrailing && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            {headerTrailing}
          </div>
        )}
      </div>
      )}

      {headerControls && <div className="aug-toolbar aug-context-bar">{headerControls}</div>}

      {!headerless && (
      <div role="tablist" aria-label={ariaLabel} className="aug-layer-tabs">
        {layers.map(l => {
          const on = l.id === layer;
          return (
            <Button
              key={l.id}
              role="tab"
              aria-selected={on}
              onClick={() => onLayerChange(l.id)}
              title={l.blurb}
              variant="ghost"
              size="sm"
              className="aug-tab"
            >
              {l.label}
              {(badges?.[l.id] ?? 0) > 0 && (
                // Amber: something in this layer is waiting on a human.
                <span className="aug-tab-badge aug-tab-badge-waiting">
                  {badges![l.id]}
                </span>
              )}
            </Button>
          );
        })}
      </div>
      )}

      {toolbar && <div className="aug-toolbar">{toolbar}</div>}

      {/* Layered body — visited layers stay mounted; only the active one shows. */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden", minHeight: 0 }}>
        {layers.map(l => visited.has(l.id) && (
          <Layer key={l.id} show={layer === l.id}>
            {renderLayer(l.id)}
          </Layer>
        ))}
      </div>
    </div>
  );
}

function Layer({ show, children }: { show: boolean; children: React.ReactNode }) {
  return (
    <div
      className={show ? "aug-anim-fade" : undefined}
      // WP-11 a11y (§1.7-7): a keep-alive layer stays MOUNTED when not shown. `inert` +
      // `aria-hidden` take the hidden layer's controls out of the tab order and the AX tree
      // (so e.g. the chat composer isn't reachable behind another workspace), belt-and-
      // suspenders with display:none.
      inert={!show}
      aria-hidden={!show || undefined}
      style={{
        position: "absolute",
        inset: 0,
        display: show ? "flex" : "none",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {children}
    </div>
  );
}
