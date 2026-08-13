"use client";

/**
 * SE-2 PR E — read-only SQL, highlighted by the REAL grammar.
 *
 * Replaces `ChatMessage`'s hand-rolled `FormattedSql`, which tokenised SQL with a
 * ~40-keyword regex alternation. That regex could not know that `count` inside a
 * string is not a function, or that a quoted identifier containing the word `from`
 * is not a clause — and every SQL dialect feature added since it was written was
 * invisible to it.
 *
 * **No EditorView.** A chat transcript can hold dozens of SQL blocks, and mounting a
 * CodeMirror instance per block would put dozens of editors, view plugins and DOM
 * observers on a page that only needs coloured text. Instead this parses with the same
 * Lezer grammar the editor uses and walks the tree with `highlightTree`, emitting
 * plain spans. One parse, static output, and — because it shares
 * the same design tokens — SQL in the chat is coloured identically to SQL in the
 * editor, which is the actual point of collapsing the two.
 *
 * Deliberately NOT used for QueryBuilder's inline SQL box: that one is EDITABLE, with
 * its own autocomplete and key handling, so a read-only view cannot stand in for it.
 * (The roadmap's PR E bullet reads as though it could; it conflates a viewer with an
 * editor. Migrating that box to the real CM6 editor is its own change.)
 */
import { useMemo } from "react";
import { classHighlighter, highlightTree } from "@lezer/highlight";
import { sql, StandardSQL, type SQLDialect } from "@codemirror/lang-sql";


/** Parse `code` and emit highlighted spans, using the editor's own style. */
function renderHighlighted(code: string, dialect: SQLDialect): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let pos = 0;

  const push = (text: string, cls: string | null, key: string) => {
    if (!text) return;
    out.push(cls
      ? <span key={key} className={cls}>{text}</span>
      : <span key={key}>{text}</span>);
  };

  try {
    const tree = sql({ dialect }).language.parser.parse(code);
    // `classHighlighter` (stable `tok-*` classes), NOT the editor's HighlightStyle:
    // that one generates class names whose CSS is injected by an EditorView, so with
    // no editor mounted every span would come out unstyled. The colours live in
    // styles/sql-tokens.css against the same tokens the editor theme uses.
    highlightTree(tree, classHighlighter, (from, to, classes) => {
      if (from > pos) push(code.slice(pos, from), null, `g${pos}`);
      push(code.slice(from, to), classes, `t${from}`);
      pos = to;
    });
  } catch {
    // A parse failure must never blank the SQL — the text itself is the payload,
    // and colour is the enhancement. Fall through to emitting the remainder plain.
  }
  if (pos < code.length) push(code.slice(pos), null, `tail${pos}`);
  return out;
}

export function SqlView({
  sql: code,
  dialect = StandardSQL,
  className,
  style,
}: {
  sql: string;
  dialect?: SQLDialect;
  className?: string;
  style?: React.CSSProperties;
}) {
  const parts = useMemo(() => renderHighlighted(code ?? "", dialect), [code, dialect]);

  return (
    <pre
      className={`aug-fs-ui font-code overflow-x-auto whitespace-pre p-3 leading-[1.65] ${className ?? ""}`}
      style={{ background: "transparent", color: "var(--t2)", margin: 0, ...style }}
    >
      {parts}
    </pre>
  );
}
