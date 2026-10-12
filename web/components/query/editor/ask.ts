/**
 * `/ask` — the SQL editor writes a statement for you, in the editor (the user, 2026-10-12: "a user typing '/ask' and
 * after that writing what is expected from the SQL … we only deliver SQL"). It replaces the assistant pane that sat
 * on the right.
 *
 * A line that begins `/ask` is a request, not SQL: it wears an accent and a hint at its end. ↵ (or ⌘↵) on it sends the
 * words to the platform's own question-to-SQL path; the line reads "writing SQL…" while it works, Esc cancels, and the
 * answer replaces the line in ONE edit — so ⌘Z puts the request back. Nothing runs: running stays the person's ⌘↵.
 * A refusal or a failure is said on the line, and the request stays for another try.
 *
 * The extension owns the line, its decoration and the edit. Who writes the SQL is the caller's (`onAsk`, read through
 * a getter so the extension built once at mount always reaches the current connection).
 */
import { type Extension, Prec, RangeSetBuilder, StateEffect, StateField, type EditorState } from "@codemirror/state";
import { Decoration, type DecorationSet, EditorView, keymap, WidgetType } from "@codemirror/view";

export const ASK = "/ask";

/** What the caller hands back: the statement, and a few short notes said above it as SQL comments. */
export interface AskAnswer {
  sql: string;
  /** e.g. "revenue is the approved metric's definition" — each one line, said as `-- …`. */
  notes?: string[];
}

export type AskHandler = (request: string, context: string, signal: AbortSignal) => Promise<AskAnswer>;

/** The request on the line holding `pos`, or null when that line is not an `/ask` line. `request` is "" for a bare
 *  `/ask`. Pure — the logic tests read it without an editor. */
export function askAt(doc: string, pos: number): { from: number; to: number; request: string } | null {
  const from = doc.lastIndexOf("\n", Math.max(0, pos - 1)) + 1;
  const nl = doc.indexOf("\n", pos);
  const to = nl === -1 ? doc.length : nl;
  const line = doc.slice(from, to);
  const m = /^\s*\/ask(?:\s+(.*))?$/i.exec(line);
  if (!m) return null;
  return { from, to, request: (m[1] ?? "").trim() };
}

/** The document with every `/ask` line blanked to spaces of the same length — what the linter checks and a run
 *  splits, so a request is never read as SQL and every offset still points at the same character. */
export function blankAskLines(doc: string): string {
  return doc.replace(/^[ \t]*\/ask(?:[ \t][^\n]*)?$/gim, line => " ".repeat(line.length));
}

/** The text that replaces an `/ask` line: the request kept as a comment (what was asked stays readable), the notes,
 *  then the statement. */
export function answerText(request: string, answer: AskAnswer): string {
  const notes = (answer.notes ?? []).map(n => n.replace(/\s+/g, " ").trim()).filter(Boolean).slice(0, 3);
  return [`-- /ask ${request}`, ...notes.map(n => `-- ${n}`), answer.sql.trim()].join("\n");
}

/** The editor text a request is asked against: everything but the `/ask` line itself. */
export function contextAround(doc: string, from: number, to: number): string {
  return (doc.slice(0, from) + doc.slice(Math.min(doc.length, to + 1))).trim();
}

type Status = { kind: "writing"; from: number } | { kind: "said"; from: number; text: string };

const setStatus = StateEffect.define<Status | null>({
  map: (s, m) => (s ? { ...s, from: m.mapPos(s.from) } : s),
});

const status = StateField.define<Status | null>({
  create: () => null,
  update(value, tr) {
    let v = value ? { ...value, from: tr.changes.mapPos(value.from) } : value;
    for (const e of tr.effects) if (e.is(setStatus)) v = e.value;
    // A said line clears once the person edits it — they are writing the next try.
    if (v?.kind === "said" && tr.docChanged && !tr.effects.some(e => e.is(setStatus))) {
      const line = tr.state.doc.lineAt(Math.min(v.from, tr.state.doc.length));
      if (tr.changes.touchesRange(line.from, line.to)) v = null;
    }
    return v;
  },
});

class Hint extends WidgetType {
  constructor(readonly text: string, readonly tone: "hint" | "busy" | "said") { super(); }
  eq(o: Hint) { return o.text === this.text && o.tone === this.tone; }
  toDOM() {
    const el = document.createElement("span");
    el.className = `cm-ask-hint cm-ask-${this.tone}`;
    el.textContent = this.text;
    el.setAttribute("data-testid", `ask-${this.tone}`);
    return el;
  }
  ignoreEvent() { return true; }
}

const LINE = Decoration.line({ class: "cm-ask-line" });
const CMD = Decoration.mark({ class: "cm-ask-cmd" });
const WORDS = Decoration.mark({ class: "cm-ask-words" });

function decorations(state: EditorState): DecorationSet {
  const b = new RangeSetBuilder<Decoration>();
  const s = state.field(status, false) ?? null;
  const at = s ? state.doc.lineAt(Math.min(s.from, state.doc.length)).number : -1;
  for (let n = 1; n <= state.doc.lines; n++) {
    const line = state.doc.line(n);
    if (!/^\s*\/ask(\s|$)/i.test(line.text)) continue;
    b.add(line.from, line.from, LINE);
    const cmd = line.from + line.text.search(/\/ask/i);
    b.add(cmd, cmd + ASK.length, CMD);
    if (cmd + ASK.length < line.to) b.add(cmd + ASK.length, line.to, WORDS);
    const mine = n === at ? s : null;
    const hint = mine?.kind === "writing" ? new Hint("writing SQL…  Esc cancels", "busy")
      : mine?.kind === "said" ? new Hint(mine.text, "said")
      : new Hint(/^\s*\/ask\s+\S/i.test(line.text) ? "↵ writes the SQL — nothing runs" : "say what the SQL should give you", "hint");
    b.add(line.to, line.to, Decoration.widget({ widget: hint, side: 1 }));
  }
  return b.finish();
}

const decorate = StateField.define<DecorationSet>({
  create: decorations,
  update: (deco, tr) => (tr.docChanged || tr.effects.some(e => e.is(setStatus)) ? decorations(tr.state) : deco),
  provide: f => EditorView.decorations.from(f),
});

/**
 * The `/ask` extension. `getHandler` returns the current handler (or null when there is no connection to ask).
 * Exported pieces (`runAsk`, `cancelAsk`) are the commands the keymap binds, so a test can call them on a view.
 */
export function askExtension(getHandler: () => AskHandler | null): Extension {
  let inflight: AbortController | null = null;

  const say = (view: EditorView, from: number, text: string) =>
    view.dispatch({ effects: setStatus.of({ kind: "said", from, text }) });

  const runAsk = (view: EditorView): boolean => {
    const doc = view.state.doc.toString();
    const at = askAt(doc, view.state.selection.main.head);
    if (!at) return false;                                   // not an /ask line: ↵ and ⌘↵ do what they always did
    if (inflight) return true;                               // one request at a time; the line says it is writing
    if (!at.request) { say(view, at.from, "say what the SQL should give you, after /ask"); return true; }
    const handler = getHandler();
    if (!handler) { say(view, at.from, "choose a connection first"); return true; }
    const ctl = new AbortController();
    inflight = ctl;
    view.dispatch({ effects: setStatus.of({ kind: "writing", from: at.from }) });
    handler(at.request, contextAround(doc, at.from, at.to), ctl.signal)
      .then(answer => {
        if (ctl.signal.aborted) return;
        const s = view.state.field(status, false);
        const line = view.state.doc.lineAt(Math.min(s?.from ?? at.from, view.state.doc.length));
        const still = askAt(view.state.doc.toString(), line.from);
        if (!still) { view.dispatch({ effects: setStatus.of(null) }); return; }   // the person removed the request
        if (!answer.sql.trim()) { say(view, line.from, "no SQL came back — try saying it another way"); return; }
        const insert = answerText(still.request || at.request, answer);
        view.dispatch({
          changes: { from: line.from, to: line.to, insert },
          selection: { anchor: line.from + insert.length },
          effects: setStatus.of(null),
          scrollIntoView: true,
          userEvent: "input.ask",
        });
      })
      .catch(e => {
        if (ctl.signal.aborted) return;
        const s = view.state.field(status, false);
        say(view, s?.from ?? at.from, e instanceof Error ? e.message : "the SQL could not be written");
      })
      .finally(() => { if (inflight === ctl) inflight = null; });
    return true;
  };

  const cancelAsk = (view: EditorView): boolean => {
    if (!inflight) return false;
    inflight.abort();
    inflight = null;
    view.dispatch({ effects: setStatus.of(null) });
    return true;
  };

  return [
    status,
    decorate,
    // Above the run keys (also Prec.highest, registered later), so ↵ / ⌘↵ on an /ask line asks instead of running.
    Prec.highest(keymap.of([
      { key: "Enter", run: runAsk },
      { key: "Mod-Enter", run: runAsk },
      { key: "Escape", run: cancelAsk },
    ])),
    EditorView.baseTheme({
      ".cm-ask-line": { backgroundColor: "color-mix(in srgb, var(--blue4) 10%, transparent)" },
      // A request is words, not SQL: the SQL highlighter's colours are taken off it, and the command wears the accent.
      ".cm-ask-words, .cm-ask-words span": { color: "var(--t1) !important", fontStyle: "normal !important" },
      ".cm-ask-cmd, .cm-ask-cmd span": { color: "var(--blue4) !important", fontWeight: "600" },
      ".cm-ask-hint": { marginLeft: "12px", fontFamily: "var(--font-sans)", fontSize: "var(--aug-fs-sm)", color: "var(--t3)" },
      ".cm-ask-busy": { color: "var(--blue4)" },
      ".cm-ask-said": { color: "var(--amb4)" },
    }),
  ];
}
