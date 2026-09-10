/**
 * SE-1 — the CodeMirror theme, written in the app's own tokens.
 *
 * CM6 takes `var(--…)` directly in its style objects, so the theme references the
 * design tokens rather than reading computed styles and plumbing hex values in. That
 * is what makes light/dark work with no JS at all: the tokens are redefined under
 * `data-theme`, and the editor follows because it never resolved them in the first
 * place.
 *
 * Font family and size are set EXPLICITLY. `globals.css` has unlayered input rules
 * that would otherwise reach into the editor's contenteditable and give it the form
 * font — a 13px sans SQL editor. Stating both here wins by specificity and keeps the
 * editor monospace regardless of what the cascade does later.
 */
import { EditorView } from "@codemirror/view";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";

export const aughorEditorTheme = EditorView.theme({
  "&": {
    fontFamily: "var(--font-code, var(--font-jetbrains-mono), monospace)",
    // Literal rather than a token: the app defines font sizes as `aug-fs-*` CLASSES,
    // and CM6's theme takes CSS values, not classes. 13px is `aug-fs-ui`, the single
    // size the whole SQL Editor now uses — the document and its chrome read as one
    // surface instead of the document being the odd one out.
    fontSize: "var(--aug-fs-ui)",
    color: "var(--t1)",
    backgroundColor: "var(--bg-0)",
    height: "100%",
  },
  ".cm-content": {
    fontFamily: "var(--font-code, var(--font-jetbrains-mono), monospace)",
    caretColor: "var(--t1)",
    padding: "10px 0",
  },
  ".cm-scroller": {
    fontFamily: "var(--font-code, var(--font-jetbrains-mono), monospace)",
    lineHeight: "1.6",
    overflow: "auto",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-gutters": {
    backgroundColor: "var(--bg-0)",
    color: "var(--t4)",
    border: "none",
    borderRight: "1px solid var(--b0)",
  },
  ".cm-activeLine": { backgroundColor: "var(--bg-1)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--bg-1)", color: "var(--t2)" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection": {
    backgroundColor: "var(--bg-3)",
  },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--t1)" },
  ".cm-placeholder": { color: "var(--t4)" },
  // The statement the cursor sits in — the one ⌘↵ will run. Making "what will run"
  // visible is the whole reason statement-under-cursor execution is safe to offer.
  ".cm-activeStatement": {
    backgroundColor: "var(--bg-1)",
    boxShadow: "inset 2px 0 0 0 var(--blue4)",
  },
  ".cm-tooltip": {
    backgroundColor: "var(--bg-2)",
    border: "1px solid var(--b1)",
    borderRadius: "var(--r2)",
    color: "var(--t1)",
  },
  ".cm-tooltip.cm-tooltip-autocomplete > ul > li": {
    fontFamily: "var(--font-code, var(--font-jetbrains-mono), monospace)",
    padding: "3px 8px",
  },
  ".cm-tooltip.cm-tooltip-autocomplete > ul > li[aria-selected]": {
    backgroundColor: "var(--bg-3)",
    color: "var(--t1)",
  },
  ".cm-completionIcon": { paddingRight: "12px", opacity: 0.6 },
  ".cm-completionDetail": { color: "var(--t4)", fontStyle: "normal", marginLeft: "8px" },
  // ── The find / replace panel ───────────────────────────────────────────────
  // SE-6 opened this panel for the first time (`searchKeymap` had been registered
  // for two waves without the `search()` extension that provides the panel, so ⌘F
  // was a dead key). It arrives with CM6's stock styles: white inputs and white
  // buttons on the app's dark chrome. Everything below is that panel written in the
  // app's tokens, so it reads as part of the editor in either theme.
  ".cm-panels": {
    backgroundColor: "var(--bg-2)",
    color: "var(--t1)",
    fontFamily: "var(--font-ui)",
    fontSize: "var(--aug-fs-sm)",
  },
  ".cm-panels.cm-panels-top": { borderBottom: "1px solid var(--b1)" },
  ".cm-panels.cm-panels-bottom": { borderTop: "1px solid var(--b1)" },
  ".cm-panel.cm-search": { padding: "6px 8px", display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px" },
  ".cm-panel.cm-search label": { display: "inline-flex", alignItems: "center", gap: "3px", color: "var(--t3)", fontSize: "var(--aug-fs-xs)" },
  ".cm-panel.cm-search input, .cm-panel.cm-search button, .cm-panel.cm-search select": {
    fontFamily: "var(--font-ui)",
    fontSize: "var(--aug-fs-sm)",
    margin: 0,
  },
  ".cm-panel.cm-search input[type=text]": {
    backgroundColor: "var(--bg-1)",
    color: "var(--t1)",
    border: "1px solid var(--b1)",
    borderRadius: "var(--r1)",
    padding: "3px 7px",
    minWidth: "180px",
    outline: "none",
  },
  ".cm-panel.cm-search input[type=text]:focus": { borderColor: "var(--blue3)" },
  ".cm-panel.cm-search button:not([name=close])": {
    backgroundColor: "var(--bg-3)",
    backgroundImage: "none",
    color: "var(--t2)",
    border: "1px solid var(--b1)",
    borderRadius: "var(--r1)",
    padding: "3px 8px",
    cursor: "pointer",
  },
  ".cm-panel.cm-search button:not([name=close]):hover": { color: "var(--t1)", borderColor: "var(--b2)" },
  ".cm-panel.cm-search button[name=close]": {
    color: "var(--t3)", background: "none", border: "none", cursor: "pointer",
    fontSize: "var(--aug-fs-h2)", padding: "0 4px",
  },
  // Go-to-line renders as CM6's generic dialog panel in this version — `cm-dialog`
  // with `cm-textfield` / `cm-button` inside, NOT the `cm-gotoLine` class an older
  // reference documents. Found by opening it and reading the DOM, after a first draft
  // styled a selector that matches nothing and left a white box on the dark chrome.
  ".cm-panel.cm-dialog": { padding: "6px 8px", display: "flex", alignItems: "center", gap: "6px" },
  ".cm-textfield": {
    backgroundColor: "var(--bg-1)", color: "var(--t1)", fontFamily: "var(--font-ui)",
    fontSize: "var(--aug-fs-sm)",
    border: "1px solid var(--b1)", borderRadius: "var(--r1)", padding: "3px 7px", outline: "none",
  },
  ".cm-textfield:focus": { borderColor: "var(--blue3)" },
  ".cm-button": {
    backgroundColor: "var(--bg-3)", backgroundImage: "none", color: "var(--t2)",
    fontFamily: "var(--font-ui)", fontSize: "var(--aug-fs-sm)",
    border: "1px solid var(--b1)", borderRadius: "var(--r1)", padding: "3px 8px", cursor: "pointer",
  },
  ".cm-button:hover": { color: "var(--t1)", borderColor: "var(--b2)" },
  ".cm-dialog-close": {
    color: "var(--t3)", background: "none", border: "none", cursor: "pointer", padding: "0 4px",
  },
  ".cm-searchMatch": { backgroundColor: "var(--bg-3)", outline: "1px solid var(--b2)" },
  ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "var(--amb1)" },
  // Every caret after the first. Without this a multiple-caret edit is invisible:
  // CM6 draws the extra cursors, but at the default 1px they vanish against the
  // active-line background.
  ".cm-cursor-secondary": { borderLeftColor: "var(--blue4)", borderLeftWidth: "2px" },
});

/** Syntax colours, also token-native. Kept deliberately quiet — a SQL editor that
 *  colours nine token classes reads as noise; keywords, literals and comments carry
 *  nearly all the signal. */
export const aughorHighlightStyle = HighlightStyle.define([
  { tag: [t.keyword, t.operatorKeyword, t.modifier], color: "var(--vio4)", fontWeight: "500" },
  { tag: [t.string, t.special(t.string)],            color: "var(--grn4)" },
  { tag: [t.number, t.bool, t.null],                 color: "var(--amb4)" },
  { tag: [t.comment, t.lineComment, t.blockComment], color: "var(--t4)", fontStyle: "italic" },
  { tag: [t.function(t.variableName), t.standard(t.name)], color: "var(--blue4)" },
  { tag: [t.typeName, t.className],                  color: "var(--cyn4)" },
  { tag: t.invalid,                                  color: "var(--red4)" },
]);

export const aughorSyntaxHighlighting = syntaxHighlighting(aughorHighlightStyle);
