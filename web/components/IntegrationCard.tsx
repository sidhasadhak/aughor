import type * as React from "react";

/**
 * One integration, drawn the same way everywhere on the Integrations page (the user,
 * 2026-10-07: the Slack card was "too big with additional details which others do not have",
 * while the MCP cards lacked any detail of the connection).
 *
 * Name and status, the actions on the right; what it is in one line; then at most a few facts
 * about the connection on ONE line, cut with an ellipsis and whole on hover. Everything else a
 * card can do — a set-up form, Slack's bots and supervisor, an MCP server's tools — is the
 * caller's `children`, shown only when the caller has opened it.
 */
export type CardTone = "ok" | "warn" | "muted";

const TONE: Record<CardTone, string> = { ok: "var(--grn4)", warn: "var(--amb4)", muted: "var(--t3)" };

export function IntegrationCard({ name, status, actions, blurb, details, detailsTitle, testId, children }: {
  name: string;
  status?: { tone: CardTone; text: string } | null;
  actions?: React.ReactNode;
  blurb: React.ReactNode;
  /** Short facts about the connection; empty ones are dropped, the rest joined on one line. */
  details?: (string | null | undefined | false)[];
  /** What hovering the facts shows — the facts themselves unless the caller has more to say. */
  detailsTitle?: string;
  testId?: string;
  children?: React.ReactNode;
}) {
  const facts = (details ?? []).filter((d): d is string => !!d);
  return (
    <div data-testid={testId} style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)",
      padding: 14, background: "var(--bg-1)", minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, minHeight: 24 }}>
        <span className="aug-fs-ui" style={{ fontWeight: 600 }}>{name}</span>
        {status && (
          <span className="aug-fs-xs" style={{ color: TONE[status.tone], whiteSpace: "nowrap" }}>
            ● {status.text}
          </span>
        )}
        <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
          {actions}
        </span>
      </div>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 4, lineHeight: 1.5 }}>
        {blurb}
      </div>
      {facts.length > 0 && (
        <div className="aug-fs-xs" title={detailsTitle || facts.join(" · ")} style={{ color: "var(--t2)", marginTop: 4,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {facts.join(" · ")}
        </div>
      )}
      {children}
    </div>
  );
}
