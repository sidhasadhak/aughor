"use client";

/**
 * EmptyState — the ONE empty-surface primitive (PX-0, §3.14).
 *
 * The law it enforces: *an empty state is a door, not an apology*. Every empty
 * surface names what fills it and, when this deployment has the door, offers the
 * button — the standing card law extended to blank screens. Before this file the
 * app had four independent local `EmptyState`s (Evals, Automations, Monitors,
 * Semantic Layer) with four signatures and two emoji glyphs; they now render
 * through here, and the platform's worst screen — a landing pane that rendered
 * NOTHING — gets the same treatment.
 *
 * `variant="page"` is the centered full-pane form; `variant="inline"` is the quiet
 * one-liner for a list section that is merely empty inside a busy screen.
 */

import React from "react";
import { Icon } from "@/components/ui/icon";

type IconName = React.ComponentProps<typeof Icon>["name"];

export function EmptyState({ icon, title, children, action, variant = "page" }: {
  /** A glyph from the one icon set — never an emoji (the icon gate's rule). */
  icon?: IconName;
  title: string;
  /** What this surface holds once it holds something — one honest sentence. */
  children?: React.ReactNode;
  /** The door that fills it: a <Button>, a link — omitted only when this
   *  deployment genuinely has no door to offer from here. */
  action?: React.ReactNode;
  variant?: "page" | "inline";
}) {
  if (variant === "inline") {
    return (
      <div className="aug-fs-sm" style={{ padding: "24px 0", textAlign: "center", color: "var(--t4)" }}>
        <p style={{ margin: 0, lineHeight: 1.5 }}>{title}{children ? <> {children}</> : null}</p>
        {action && <div style={{ marginTop: 10 }}>{action}</div>}
      </div>
    );
  }
  return (
    <div style={{ textAlign: "center", paddingTop: 60, paddingBottom: 40, color: "var(--t3)" }}>
      {icon && (
        <div style={{ marginBottom: 14, color: "var(--t4)", display: "inline-flex" }}>
          <Icon name={icon} size={40} />
        </div>
      )}
      <div className="aug-fs-h2" style={{ fontWeight: 500, color: "var(--t2)", marginBottom: 6 }}>{title}</div>
      {children && (
        <div className="aug-fs-sm" style={{ margin: "0 auto 20px", maxWidth: 460, lineHeight: 1.5 }}>
          {children}
        </div>
      )}
      {action}
    </div>
  );
}
