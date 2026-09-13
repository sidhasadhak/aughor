"use client";

/**
 * EmptyState — the ONE empty-surface primitive (PX-0, §3.14; Instrument §6 "empty").
 *
 * The law it enforces: *an empty state is a door, not an apology*. Every empty surface
 * states the precondition and, when this deployment has the door, offers the one action
 * that resolves it. Before this file the app had four independent local `EmptyState`s;
 * they render through here.
 *
 * Drawn the way the design system draws it: left-aligned on the page's own plane (centred
 * type is on the anti-brief), a 28px glyph in --b3 — the ONE place the seventh size lives —
 * a 13/600 title, 12px body, then the door.
 *
 * `variant="page"` is the form for a whole pane; `variant="inline"` is the quiet one-liner
 * for a list section that is merely empty inside a busy screen.
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
      <div className="aug-empty aug-empty-inline aug-fs-sm">
        <p style={{ margin: 0, lineHeight: 1.55 }}>{title}{children ? <> {children}</> : null}</p>
        {action && <div className="aug-empty-actions">{action}</div>}
      </div>
    );
  }
  return (
    <div className="aug-empty">
      {icon && (
        <span className="aug-empty-glyph" aria-hidden>
          <Icon name={icon} size={28} />
        </span>
      )}
      <div className="aug-empty-title">{title}</div>
      {children && <div className="aug-empty-body">{children}</div>}
      {action && <div className="aug-empty-actions">{action}</div>}
    </div>
  );
}
