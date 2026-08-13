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
} from "@codemirror/commands";
import {
  autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap,
} from "@codemirror/autocomplete";
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search";
import {
  bracketMatching, indentOnInput, foldGutter, foldKeymap,
} from "@codemirror/language";
import { lintGutter } from "@codemirror/lint";
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
  /** SE-2 — the two-tier linter. Built by the caller (it needs the connection). */
  diagnostics?: Extension;
  /** SE-2 — receives an imperative `insert(text)` for the schema sidebar. Text lands
   *  at the cursor (replacing any selection), which is what makes clicking a table
   *  name feel like typing it rather than like navigating away. */
  onReady?: (api: { insert: (text: string) => void; focus: () => void }) => void;
  placeholder?: string;
  readOnly?: boolean;
}

export function SqlEditorPane({
  value, onChange, onRun, onFormat, onCursor, onReady,
  schema, defaultSchema, dialect, diagnostics,
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
      autocompletion({ activateOnTyping: true, defaultKeymap: true }),
      // Wrapped in the compartment so the connection's dialect/schema can be swapped
      // later without touching the document (see the reconfigure effect below).
      languageCompartment.of(
        sql({ dialect, schema, defaultSchema, upperCaseKeywords: false }),
      ),
      cmPlaceholder(placeholder),
      runKeymap,
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
    const v = view.current;
    if (!v) return;
    v.dispatch({
      effects: languageCompartment.reconfigure(
        sql({ dialect, schema, defaultSchema, upperCaseKeywords: false }),
      ),
    });
  }, [dialect, schema, defaultSchema]);

  return (
    <div
      ref={host}
      data-testid="sql-editor"
      style={{ flex: 1, minHeight: 0, overflow: "hidden", background: "var(--bg-0)" }}
    />
  );
}
