"use client";

/**
 * AnswerProse — SP-10's reading surface for a conversational answer.
 *
 * The measured break (§3.11, the user's own ⌘K turn): the model's markdown reached
 * the screen raw — lists ran inline, backticks printed as characters, and the whole
 * multi-paragraph answer wore the display-size headline treatment. Decision 22(b),
 * taken 2026-09-15: a MAINTAINED markdown renderer for prose, plus the structured
 * cards (the user prefers library defaults over hand-rolling).
 *
 * This is the CHAT surface's renderer; the Briefing keeps `BriefProse`, whose
 * hand-rolled scope (paragraphs + tables) matches a surface the model does not
 * free-write into. Both share ONE inline-figure rule (`renderEmphasis`), so a
 * signed delta reads emerald/red identically everywhere and an id fragment never
 * does (its boundary fix lives there).
 *
 * The surface is DESIGNED, not open: `skipHtml`, an element allowlist, and every
 * element mapped — headings render as bold paragraphs (a chat answer has no place
 * for display headings), links open safely, images and raw HTML never render.
 * Inline code and bare ids become copyable mono chips; ids and dates are never
 * tinted as figures (SP-10's receipt line).
 */

import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { renderEmphasis } from "@/components/brief/BriefProse";

/** A bare id in prose — a uuid, or the repo's own prefixed ids (`ua_…`, `sb_…`). */
const ID_RE =
  /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\b(?:ua|sb)_[0-9a-f]{8,}\b)/g;

/** One copyable mono chip — inline code, and any bare id the prose carries. */
export function CopyChip({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      title="Click to copy"
      onClick={() => {
        try {
          void navigator.clipboard?.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        } catch {
          /* clipboard can be unavailable (permissions, insecure context) — the chip
             still shows its text, which is the part that must never break */
        }
      }}
      className="font-mono aug-text-sm rounded px-1 py-px align-baseline cursor-pointer"
      style={{
        background: "var(--bg-3)", border: "1px solid var(--b1)",
        color: copied ? "var(--grn4)" : "var(--t2)",
      }}
    >
      {copied ? "copied" : text}
    </button>
  );
}

/** Inline text → figure emphasis, with bare ids lifted out as chips FIRST — an id
 *  must never reach the figure pass, where its `-3f4d` once read as a loss. */
function inline(text: string): React.ReactNode[] {
  return text.split(ID_RE).map((part, i) => {
    if (!part) return null;
    if (new RegExp(`^(?:${ID_RE.source})$`).test(part)) return <CopyChip key={i} text={part} />;
    return <React.Fragment key={i}>{renderEmphasis(part)}</React.Fragment>;
  });
}

/** Apply the inline pass to an element's mixed children (strings + elements). */
function withInline(children: React.ReactNode): React.ReactNode {
  return React.Children.map(children, (child) =>
    typeof child === "string" ? <>{inline(child)}</> : child,
  );
}

type ElProps = { children?: React.ReactNode };

const P = ({ children }: ElProps) => (
  <p className="aug-text-ui leading-relaxed text-zinc-300 my-1 first:mt-0 last:mb-0">
    {withInline(children)}
  </p>
);

/** Headings as bold paragraphs — structure without a second type scale. */
const H = ({ children }: ElProps) => (
  <p className="aug-text-ui leading-relaxed font-semibold text-zinc-200 mt-2 mb-1 first:mt-0">
    {withInline(children)}
  </p>
);

const COMPONENTS = {
  p: P,
  h1: H, h2: H, h3: H, h4: H, h5: H, h6: H,
  ul: ({ children }: ElProps) => (
    <ul className="list-disc pl-5 my-1 flex flex-col gap-0.5">{children}</ul>
  ),
  ol: ({ children }: ElProps) => (
    <ol className="list-decimal pl-5 my-1 flex flex-col gap-0.5">{children}</ol>
  ),
  li: ({ children }: ElProps) => (
    <li className="aug-text-ui leading-relaxed text-zinc-300">{withInline(children)}</li>
  ),
  strong: ({ children }: ElProps) => (
    <strong className="font-semibold">{withInline(children)}</strong>
  ),
  em: ({ children }: ElProps) => <em className="italic">{withInline(children)}</em>,
  del: ({ children }: ElProps) => <del>{withInline(children)}</del>,
  blockquote: ({ children }: ElProps) => (
    <blockquote className="border-l-2 border-zinc-700 pl-3 my-1 text-zinc-400">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="border-zinc-800 my-2" />,
  a: ({ children, href }: ElProps & { href?: string }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="underline underline-offset-2 text-zinc-200 hover:text-white"
    >
      {children}
    </a>
  ),
  // Inline code is a copyable chip; a fenced block stays a block (the `pre`
  // wrapper below owns the box, so the code element inside it renders bare).
  code: ({ children, ...rest }: ElProps & { className?: string }) => {
    const text = React.Children.toArray(children).join("");
    if ("className" in rest && String(rest.className ?? "").includes("language-")) {
      return <code className="font-mono aug-text-sm">{text}</code>;
    }
    return <CopyChip text={text} />;
  },
  pre: ({ children }: ElProps) => (
    <pre
      className="font-mono aug-text-sm overflow-x-auto rounded p-2 my-1"
      style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", color: "var(--t1)" }}
    >
      {children}
    </pre>
  ),
  // The table treatment BriefProse established, kept identical here.
  table: ({ children }: ElProps) => (
    <div className="overflow-x-auto my-2">
      <table className="aug-text-ui border-collapse">{children}</table>
    </div>
  ),
  th: ({ children }: ElProps) => (
    <th className="text-left font-medium text-zinc-400 px-2 py-1 border-b border-zinc-700">
      {withInline(children)}
    </th>
  ),
  td: ({ children }: ElProps) => (
    <td className="text-zinc-300 px-2 py-1 border-b border-zinc-800 whitespace-nowrap">
      {withInline(children)}
    </td>
  ),
};

const ALLOWED = [
  "p", "ul", "ol", "li", "strong", "em", "del", "blockquote", "hr", "br", "a",
  "code", "pre", "table", "thead", "tbody", "tr", "th", "td",
  "h1", "h2", "h3", "h4", "h5", "h6",
];

export function AnswerProse({ text, className = "", caret = false }: {
  text: string;
  className?: string;
  /** Trail the streaming caret while the text is still arriving. */
  caret?: boolean;
}) {
  if (!text) return null;
  return (
    <div className={`flex flex-col ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        allowedElements={ALLOWED}
        unwrapDisallowed
        components={COMPONENTS}
      >
        {text}
      </ReactMarkdown>
      {caret && <span className="aug-caret" aria-hidden="true" />}
    </div>
  );
}

/**
 * Whether an answer should read as PROSE rather than wear the display headline.
 * A one-line conclusion keeps the `BriefHeadline` treatment it was built for; a
 * multi-paragraph or markdown-structured answer at display size is the wall the
 * user photographed ("the size of the text… absolutely terrible").
 */
export function readsAsProse(text: string): boolean {
  const t = (text || "").trim();
  if (!t) return false;
  if (t.length > 220) return true;
  if (t.includes("\n")) return true;
  if (t.includes("`")) return true;
  if (/(^|\n)\s*(?:[-*]\s|\d+\.\s|#{1,6}\s|>\s)/.test(t)) return true;
  return false;
}
