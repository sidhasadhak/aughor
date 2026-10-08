"use client";

/**
 * NoteProse — a cockpit note's words, drawn from the Markdown subset a note may hold (the
 * canvas, docs/COCKPIT_CANVAS_2026-10-08.md; the user's call, 2026-10-08: "Markdown subset, up
 * to 2,000": bold, italics, lists, links).
 *
 * Narrower than the chat's `AnswerProse` on purpose. A note is a person's reminder, not a
 * document: no headings, no tables, no code, no images, no raw HTML. A link opens in a new tab
 * and is kept to http and https — a note is the one place on a cockpit a person can write a
 * link, and a cockpit is a surface the platform vouches for, so the link is a door and nothing
 * more: nothing on the page runs from it.
 */
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";

const ALLOWED = ["p", "ul", "ol", "li", "strong", "em", "a", "br"];

type ElProps = { children?: ReactNode };

/** A link a note may carry: http or https, nothing else. */
export function noteHref(href: string | undefined): string | undefined {
  if (!href) return undefined;
  try {
    const u = new URL(href);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : undefined;
  } catch {
    return undefined;
  }
}

const COMPONENTS = {
  p: ({ children }: ElProps) => <p style={{ margin: 0 }}>{children}</p>,
  ul: ({ children }: ElProps) => <ul style={{ margin: 0, paddingLeft: 18, listStyle: "disc" }}>{children}</ul>,
  ol: ({ children }: ElProps) => <ol style={{ margin: 0, paddingLeft: 18, listStyle: "decimal" }}>{children}</ol>,
  li: ({ children }: ElProps) => <li>{children}</li>,
  strong: ({ children }: ElProps) => <strong style={{ fontWeight: 600 }}>{children}</strong>,
  em: ({ children }: ElProps) => <em>{children}</em>,
  a: ({ children, href }: ElProps & { href?: string }) => {
    const safe = noteHref(href);
    return safe
      ? <a href={safe} target="_blank" rel="noopener noreferrer" style={{ textDecoration: "underline", textUnderlineOffset: 2 }}>{children}</a>
      : <span>{children}</span>;
  },
};

export function NoteProse({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="aug-fs-ui" data-testid="note-prose" style={{ display: "flex", flexDirection: "column", gap: 6, color: "var(--t1)", lineHeight: 1.5, whiteSpace: "pre-wrap", minWidth: 0, overflowWrap: "anywhere" }}>
      <ReactMarkdown skipHtml allowedElements={ALLOWED} unwrapDisallowed components={COMPONENTS}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
