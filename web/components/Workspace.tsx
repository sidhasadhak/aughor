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
  /** Optional header controls (connection / schema pickers …) inserted between the
   *  title and the switcher. When present the switcher drops its `margin-left:auto`,
   *  so the trailing group is right-aligned by the first control instead. */
  headerControls?: React.ReactNode;
  /** Render the body of a layer. Called only for visited layers (keep-alive). */
  renderLayer: (id: L) => React.ReactNode;
};

/**
 * The one Workspace shell — a header (active title + optional controls + a segmented
 * perspective switcher) over a keep-alive layered body. Extracted from
 * `IntelligenceWorkspace` so Intelligence / Canvas / Operations are all *instances* of
 * one shell rather than three hand-rolled copies of the same layer chrome (Part 2
 * Track B — "one shell").
 *
 * Keep-alive: a layer is mounted the first time it becomes active and then stays
 * mounted (display toggled), so graph zoom / scroll / fetch state survives layer
 * switches. Layers that have never been visited aren't mounted at all.
 */
export function Workspace<L extends string>({
  layers, layer, onLayerChange, ariaLabel, renderIcon, headerControls, renderLayer,
}: WorkspaceProps<L>) {
  // Mount a layer the first time it becomes active, then keep it mounted.
  const [visited, setVisited] = useState<Set<L>>(() => new Set([layer]));
  useEffect(() => {
    setVisited(prev => (prev.has(layer) ? prev : new Set(prev).add(layer)));
  }, [layer]);

  const active = layers.find(l => l.id === layer)!;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
      {/* Workspace header — title + optional controls + perspective switcher */}
      <div className="aug-content-header" style={{ gap: 14 }}>
        {renderIcon(active.icon, 14, "var(--t3)")}
        <span style={{ fontSize: 13, fontWeight: 500 }}>{active.label}</span>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>· {active.blurb}</span>

        {headerControls}

        {/* Layer switcher — segmented control */}
        <div
          role="tablist"
          aria-label={ariaLabel}
          style={{
            marginLeft: headerControls ? 0 : "auto",
            display: "flex",
            gap: 2,
            padding: 2,
            background: "var(--bg-2)",
            border: "1px solid var(--b1)",
            borderRadius: "var(--r3)",
          }}
        >
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
                style={{
                  padding: "4px 11px",
                  borderRadius: "var(--r2)",
                  border: "1px solid transparent",
                  background: on ? "var(--bg-sel)" : "transparent",
                  color: on ? "var(--blue5)" : "var(--t2)",
                  fontWeight: on ? 500 : 400,
                }}
              >
                {renderIcon(l.icon, 13, on ? "var(--blue4)" : "currentColor")}
                {l.label}
              </Button>
            );
          })}
        </div>
      </div>

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
