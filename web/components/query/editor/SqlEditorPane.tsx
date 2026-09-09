"use client";

/**
 * SE-1 — the CodeMirror 6 editor pane.
 *
 * A thin, imperative shell around CM6: React owns mounting and the props, CM6 owns the
 * document. The one rule that keeps that honest is that this component never re-creates
 * the EditorView on a prop change — it dispatches. A recreated view loses the cursor,
 * the undo history and the scroll position, which is the difference between an editor
 * and a textarea that forgets.
 *
 * Completion is schema-driven: `@codemirror/lang-sql` takes the table/column map
 * directly, so table names, and columns after a qualifying dot, come from the real
 * catalog rather than a keyword list. The schema arrives as a prop because fetching it
 * belongs to the workbench (which already knows the connection), not to the editor.
 *
 * ⌘/Ctrl+Enter runs. It is registered ABOVE the default keymap via Prec.highest so the
 * editor's own binding cannot be shadowed by a default, and it calls the LATEST
 * `onRun` through a ref — a stale closure here would run the query the user typed a
 * minute ago.
 */
import { useEffect, useRef } from "react";
import { Compartment, EditorState, Prec, type Extension } from "@codemirror/state";
import {
  EditorView, keymap, lineNumbers, highlightActiveLine,
  highlightActiveLineGutter, placeholder as cmPlaceholder, drawSelection,
  rectangularSelection, crosshairCursor,
} from "@codemirror/view";
import {
  defaultKeymap, history, historyKeymap, indentWithTab,
  addCursorAbove, addCursorBelow, toggleComment, toggleBlockComment,
} from "@codemirror/commands";
import {
  autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap,
  completeFromList, startCompletion, type CompletionSource,
} from "@codemirror/autocomplete";
import {
  search, searchKeymap, highlightSelectionMatches, selectNextOccurrence,
  selectSelectionMatches, openSearchPanel, gotoLine,
} from "@codemirror/search";
import { templateCompletions } from "@/components/query/editor/templates";
import { sqlIntentions } from "@/components/query/editor/intentions";
import {
  bracketMatching, indentOnInput, foldGutter, foldKeymap,
} from "@codemirror/language";
import { lintGutter } from "@codemirror/lint";
import { refreshLint } from "@/components/query/editor/diagnostics";
import { sql, type SQLDialect } from "@codemirror/lang-sql";
import { aughorEditorTheme, aughorSyntaxHighlighting } from "@/components/query/editor/theme";

export interface SqlEditorPaneProps {
  value: string;
  onChange: (sql: string) => void;
  /** Fires on ⌘/Ctrl+Enter. Receives nothing — the workbench reads cursor/selection
   *  itself via `onCursor`, so "what runs" is decided in one place. */
  onRun?: () => void;
  /** Fires on ⌘⇧F. Returns the replacement text for the range it was given, or null
   *  to leave the document alone. */
  onFormat?: (sql: string) => string | null;
  onCursor?: (pos: number, selection: { from: number; to: number } | null) => void;
  /** `{ "schema.table": ["col", …] }` — drives table and column completion. */
  schema?: Record<string, string[]>;
  defaultSchema?: string;
  dialect: SQLDialect;
  /** SE-6 — how this engine quotes an identifier that needs it. The editor does not
   *  know the connection; the workbench does, and passes `quoteIdentifier` bound to
   *  its engine hint. Wildcard expansion is the caller that cannot do without it. */
  quote?: (name: string) => string;
  /** SE-2 — the two-tier linter. Built by the caller (it needs the connection). */
  diagnostics?: Extension;
  /** SE-2 — receives an imperative `insert(text)` for the schema sidebar. Text lands
   *  at the cursor (replacing any selection), which is what makes clicking a table
   *  name feel like typing it rather than like navigating away. */
  onReady?: (api: {
    insert: (text: string) => void;
    focus: () => void;
    relint: () => void;
  }) => void;
  placeholder?: string;
  readOnly?: boolean;
}

/** The live templates as a completion source. Built once at module scope — the set is
 *  static, and rebuilding it per editor would allocate 21 snippet closures per mount. */
const TEMPLATE_OPTIONS = templateCompletions();
const templateSource: CompletionSource = completeFromList(TEMPLATE_OPTIONS);

/** SQL support with the templates added.
 *
 *  ⚠️ The templates go on the LANGUAGE's own data facet, not on a top-level
 *  `EditorState.languageData.of(…)`. Measured: the top-level registration produced a
 *  popup with the dialect's keywords and no templates at all — `autocompletion()`
 *  reads its sources through `languageDataAt` at the cursor, and inside a language the
 *  language's own data is what answers there. `LanguageSupport` takes exactly this
 *  kind of extension as its second argument, which is the documented seam. */
function sqlWithTemplates(
  dialect: SQLDialect, schema?: Record<string, string[]>, defaultSchema?: string,
): Extension {
  const support = sql({ dialect, schema, defaultSchema, upperCaseKeywords: false });
  return [support, support.language.data.of({ autocomplete: templateSource })];
}

export function SqlEditorPane({
  value, onChange, onRun, onFormat, onCursor, onReady,
  schema, defaultSchema, dialect, diagnostics, quote,
  placeholder = "SELECT … — ⌘↵ runs the statement under the cursor",
  readOnly = false,
}: SqlEditorPaneProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const view = useRef<EditorView | null>(null);
  // Per-INSTANCE, not module-level: a compartment is a handle into one view's
  // configuration, so two editors sharing one would reconfigure each other.
  const languageCompartment = useRef(new Compartment()).current;
  // Callbacks through refs so the extensions built once at mount always reach the
  // CURRENT handler. Rebuilding extensions per render would recreate the view.
  const onChangeRef = useRef(onChange);
  const onRunRef = useRef(onRun);
  const onFormatRef = useRef(onFormat);
  const onCursorRef = useRef(onCursor);
  // SE-6 — the intentions read the CURRENT schema through this ref. Rebuilding the
  // extension when the catalog refreshes would mean rebuilding the view, and a
  // rebuilt view has no undo history and no cursor.
  const schemaRef = useRef<Record<string, string[]>>(schema ?? {});
  const quoteRef = useRef<(n: string) => string>(n => n);
  onChangeRef.current = onChange;
  onRunRef.current = onRun;
  onFormatRef.current = onFormat;
  onCursorRef.current = onCursor;

  // Mount once. `value` is the INITIAL doc here — later changes come through the
  // reconcile effect below, never by rebuilding the view.
  useEffect(() => {
    if (!host.current || view.current) return;

    const runKeymap = Prec.highest(keymap.of([
      {
        key: "Mod-Enter",
        preventDefault: true,
        run: () => { onRunRef.current?.(); return true; },
      },
      {
        // ⌘⇧F — formats the selection if there is one, else the whole document. The
        // caller decides the text; this only owns the edit, so the cursor lands
        // sensibly and the change is a single undo step.
        key: "Mod-Shift-f",
        preventDefault: true,
        run: (v) => {
          const fmt = onFormatRef.current;
          if (!fmt) return false;
          const sel = v.state.selection.main;
          const whole = sel.empty;
          const from = whole ? 0 : sel.from;
          const to = whole ? v.state.doc.length : sel.to;
          const next = fmt(v.state.sliceDoc(from, to));
          if (next == null || next === v.state.sliceDoc(from, to)) return true;
          v.dispatch({
            changes: { from, to, insert: next },
            selection: { anchor: Math.min(from + next.length, from + next.length) },
          });
          return true;
        },
      },
    ]));

    // SE-6 — the DataGrip keys, at `Prec.highest` so a default binding cannot shadow
    // one of them. Each is a verb the editor did not have:
    //   ⌘D      select the next occurrence of the selection → a real multiple-caret
    //           edit, the feature DataGrip lists as "multiple carets"
    //   ⌘⇧L     select ALL occurrences at once
    //   ⌥⌘↑/↓   add a caret on the line above/below
    //   ⌥⏎      the intentions menu (see intentions.ts)
    //   ⌘J      the live-template list (see templates.ts) — explicit completion with
    //           the templates already in it
    //   ⌘/ ⌥⌘/  toggle a line / block comment, DataGrip's own pair
    //   ⌘L      go to line (DataGrip's key; ⌘G is the browser's Find Next)
    //   ⌘F ⌥⌘F  find / find-and-replace: `searchKeymap` was ALREADY registered here
    //           and did nothing, because the panel it opens is provided by the
    //           `search()` extension, which was not. ⌘F was a dead key.
    const editKeymap = Prec.highest(keymap.of([
      { key: "Mod-d", preventDefault: true, run: selectNextOccurrence },
      { key: "Mod-Shift-l", preventDefault: true, run: selectSelectionMatches },
      { key: "Mod-Alt-ArrowUp", preventDefault: true, run: addCursorAbove },
      { key: "Mod-Alt-ArrowDown", preventDefault: true, run: addCursorBelow },
      { key: "Mod-j", preventDefault: true, run: startCompletion },
      { key: "Mod-/", preventDefault: true, run: toggleComment },
      { key: "Mod-Alt-/", preventDefault: true, run: toggleBlockComment },
      // ⌘L, DataGrip's own go-to-line. NOT ⌘G: measured in the browser, ⌘G never
      // reaches the editor — it is Find Next at the browser level and is not
      // preventable from the page. A key we advertise and the OS eats is worse than
      // no key. `searchKeymap`'s own ⌥⌘G stays bound as well.
      { key: "Mod-l", preventDefault: true, run: gotoLine },
      { key: "Mod-f", preventDefault: true, run: openSearchPanel },
      { key: "Mod-Alt-f", preventDefault: true, run: openSearchPanel },
    ]));

    const extensions: Extension[] = [
      lineNumbers(),
      foldGutter(),
      history(),
      drawSelection(),
      indentOnInput(),
      bracketMatching(),
      closeBrackets(),
      highlightActiveLine(),
      highlightActiveLineGutter(),
      highlightSelectionMatches(),
      rectangularSelection(),
      crosshairCursor(),
      // Without this a second caret cannot exist, so ⌘D and ⌥-click would extend the
      // one selection instead of adding to it. It is the switch that makes every
      // multiple-caret command above real rather than decorative.
      EditorState.allowMultipleSelections.of(true),
      EditorView.clickAddsSelectionRange.of(e => e.altKey),
      search({ top: true }),
      autocompletion({ activateOnTyping: true, defaultKeymap: true }),
      // Wrapped in the compartment so the connection's dialect/schema can be swapped
      // later without touching the document (see the reconfigure effect below).
      // Live templates ride alongside the language's own completions rather than
      // replacing them: `override` would drop schema completion, which is the one
      // thing here nobody would trade a template set for.
      languageCompartment.of(sqlWithTemplates(dialect, schema, defaultSchema)),
      sqlIntentions(() => schemaRef.current, () => quoteRef.current),
      cmPlaceholder(placeholder),
      runKeymap,
      editKeymap,
      keymap.of([
        ...closeBracketsKeymap, ...defaultKeymap, ...historyKeymap,
        ...completionKeymap, ...searchKeymap, ...foldKeymap, indentWithTab,
      ]),
      // The gutter marker is what makes a guard finding discoverable: a squiggle on a
      // table name three lines down is easy to miss, a marker in the gutter is not.
      ...(diagnostics ? [diagnostics, lintGutter()] : []),
      aughorEditorTheme,
      aughorSyntaxHighlighting,
      EditorView.lineWrapping,
      EditorState.readOnly.of(readOnly),
      EditorView.updateListener.of((u) => {
        if (u.docChanged) onChangeRef.current?.(u.state.doc.toString());
        if (u.selectionSet || u.docChanged) {
          const sel = u.state.selection.main;
          onCursorRef.current?.(
            sel.head, sel.empty ? null : { from: sel.from, to: sel.to },
          );
        }
      }),
    ];

    view.current = new EditorView({
      state: EditorState.create({ doc: value, extensions }),
      parent: host.current,
    });

    // Hand the caller an imperative handle. Insertion belongs here, not in the
    // sidebar, because only the view knows where the cursor is — and it dispatches
    // rather than rewriting the doc, so the insert is one undo step.
    const v = view.current;
    onReady?.({
      insert: (text: string) => {
        const sel = v.state.selection.main;
        v.dispatch({
          changes: { from: sel.from, to: sel.to, insert: text },
          selection: { anchor: sel.from + text.length },
          scrollIntoView: true,
        });
        v.focus();
      },
      focus: () => v.focus(),
      // SE-4 H — re-run the linter when something OUTSIDE the document changed the
      // verdict's inputs (parameter values). The editor owns the view, so it owns the
      // only handle that can ask CodeMirror to lint again.
      relint: () => v.dispatch({ effects: refreshLint.of(null) }),
    });

    return () => { view.current?.destroy(); view.current = null; };
    // Mount-only by design — see the reconcile/compartment effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reconcile an externally-changed value (a tab switch, a restored draft, SQL handed
  // in from elsewhere). Guarded on inequality so the user's own typing — which already
  // reached the parent through onChange — never round-trips into a doc replacement
  // that would jump the cursor to the end mid-keystroke.
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const current = v.state.doc.toString();
    if (current === value) return;
    v.dispatch({
      changes: { from: 0, to: current.length, insert: value },
      selection: { anchor: Math.min(v.state.selection.main.head, value.length) },
    });
  }, [value]);

  // The dialect and the schema change when the connection does. CM6 wants these
  // reconfigured rather than re-mounted, so the language extension is swapped through
  // the view's own effect channel and the document survives the switch.
  useEffect(() => {
    schemaRef.current = schema ?? {};
    quoteRef.current = quote ?? (n => n);
    const v = view.current;
    if (!v) return;
    v.dispatch({
      effects: languageCompartment.reconfigure(
        sqlWithTemplates(dialect, schema, defaultSchema),
      ),
    });
  }, [dialect, schema, defaultSchema, quote]);

  return (
    <div
      ref={host}
      data-testid="sql-editor"
      style={{ flex: 1, minHeight: 0, overflow: "hidden", background: "var(--bg-0)" }}
    />
  );
}
