// @vitest-environment jsdom
/**
 * `/ask` in the SQL editor (2026-10-12): a line that begins `/ask` is a request. ↵ sends it, the answer replaces the
 * line in one edit (⌘Z brings the request back), nothing runs, and a failure is said on the line with the request
 * kept. Driven through a real CodeMirror view and its own key handling — the handler is the only stub.
 */
import { EditorState } from "@codemirror/state";
import { EditorView, runScopeHandlers } from "@codemirror/view";
import { history, historyKeymap } from "@codemirror/commands";
import { keymap } from "@codemirror/view";
import { afterEach, describe, expect, it, vi } from "vitest";

import { askAt, answerText, askExtension, blankAskLines, contextAround, type AskHandler } from "@/components/query/editor/ask";

let views: EditorView[] = [];
afterEach(() => { views.forEach(v => v.destroy()); views = []; });

function editor(doc: string, handler: AskHandler | null, onRun = vi.fn()) {
  const view = new EditorView({
    state: EditorState.create({
      doc,
      selection: { anchor: doc.length },
      extensions: [history(), askExtension(() => handler), keymap.of([{ key: "Mod-Enter", run: () => { onRun(); return true; } }, ...historyKeymap])],
    }),
    parent: document.body,
  });
  views.push(view);
  return { view, onRun };
}

// CodeMirror's "Mod" is ⌘ on a Mac and Ctrl elsewhere — send the one this platform reads.
const MAC = /Mac|iPhone|iPad/.test(navigator.platform);
const press = (view: EditorView, key: string, mod = false) =>
  runScopeHandlers(view, new KeyboardEvent("keydown", { key, metaKey: mod && MAC, ctrlKey: mod && !MAC }), "editor");
const text = (view: EditorView) => view.state.doc.toString();
const settle = () => new Promise(r => setTimeout(r, 0));

describe("the line", () => {
  it("is a request only when it begins /ask", () => {
    expect(askAt("/ask country-wise sales", 5)).toEqual({ from: 0, to: 23, request: "country-wise sales" });
    expect(askAt("SELECT 1;\n  /ASK  orders by month", 14)).toEqual({ from: 10, to: 33, request: "orders by month" });
    expect(askAt("/ask", 4)).toEqual({ from: 0, to: 4, request: "" });
    expect(askAt("/asking for trouble", 3)).toBeNull();
    expect(askAt("SELECT '/ask'", 9)).toBeNull();
  });

  it("is replaced by the request as a comment, the notes, then the statement", () => {
    expect(answerText("country-wise sales", { sql: "SELECT country, SUM(x) FROM t GROUP BY 1\n", notes: ["sales is the approved metric"] }))
      .toBe("-- /ask country-wise sales\n-- sales is the approved metric\nSELECT country, SUM(x) FROM t GROUP BY 1");
    expect(contextAround("SELECT 1;\n/ask more\nSELECT 2;", 10, 19)).toBe("SELECT 1;\nSELECT 2;");
  });
});

describe("what the linter checks and a run splits", () => {
  it("never reads a request as SQL, and keeps every offset", () => {
    const doc = "SELECT 1;\n/ask country-wise sales\n  /ASK\n-- /ask kept as a comment\nSELECT '/ask' AS x";
    const out = blankAskLines(doc);
    expect(out.length).toBe(doc.length);
    expect(out).toBe("SELECT 1;\n" + " ".repeat(23) + "\n" + " ".repeat(6) + "\n-- /ask kept as a comment\nSELECT '/ask' AS x");
    expect(blankAskLines("/asking")).toBe("/asking");
  });
});

describe("↵ on an /ask line", () => {
  it("writes the SQL in place — one edit, nothing run — and ⌘Z brings the request back", async () => {
    let finish!: (a: { sql: string; notes?: string[] }) => void;
    const handler = vi.fn<AskHandler>(() => new Promise(r => { finish = r; }));
    const { view, onRun } = editor("SELECT 1;\n/ask country-wise sales", handler);
    expect(press(view, "Enter")).toBe(true);
    expect(handler).toHaveBeenCalledWith("country-wise sales", "SELECT 1;", expect.any(AbortSignal));
    expect(view.dom.querySelector("[data-testid=ask-busy]")?.textContent).toMatch(/writing SQL/);
    finish({ sql: "SELECT country, SUM(sale_price) FROM order_items GROUP BY 1", notes: ["sales: the approved metric"] });
    await settle();
    expect(text(view)).toBe("SELECT 1;\n-- /ask country-wise sales\n-- sales: the approved metric\nSELECT country, SUM(sale_price) FROM order_items GROUP BY 1");
    expect(onRun).not.toHaveBeenCalled();
    press(view, "z", true);
    expect(text(view)).toBe("SELECT 1;\n/ask country-wise sales");
  });

  it("⌘↵ on an /ask line asks rather than runs; elsewhere it runs as it always did", async () => {
    const handler = vi.fn<AskHandler>(async () => ({ sql: "SELECT 2" }));
    const asked = editor("/ask two", handler);
    press(asked.view, "Enter", true);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(asked.onRun).not.toHaveBeenCalled();
    const plain = editor("SELECT 1", handler);
    press(plain.view, "Enter", true);
    expect(plain.onRun).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(press(plain.view, "Enter")).toBe(false);                       // a plain ↵ is the editor's own newline
  });

  it("says a failure on the line and keeps the request for another try", async () => {
    const { view } = editor("/ask revenue by planet", async () => { throw new Error("no table holds a planet"); });
    press(view, "Enter");
    await settle();
    expect(text(view)).toBe("/ask revenue by planet");
    expect(view.dom.querySelector("[data-testid=ask-said]")?.textContent).toBe("no table holds a planet");
  });

  it("a bare /ask, or no connection, says what is missing and asks nobody", () => {
    const handler = vi.fn<AskHandler>();
    const bare = editor("/ask", handler);
    press(bare.view, "Enter");
    expect(bare.view.dom.querySelector("[data-testid=ask-said]")?.textContent).toMatch(/say what the SQL should give you/);
    const none = editor("/ask orders by day", null);
    press(none.view, "Enter");
    expect(none.view.dom.querySelector("[data-testid=ask-said]")?.textContent).toBe("choose a connection first");
    expect(handler).not.toHaveBeenCalled();
  });

  it("Esc cancels a request being written: the signal aborts and the line stays", async () => {
    let signal!: AbortSignal;
    const { view } = editor("/ask orders by day", (_r, _c, s) => { signal = s; return new Promise(() => {}); });
    press(view, "Enter");
    expect(press(view, "Escape")).toBe(true);
    expect(signal.aborted).toBe(true);
    expect(view.dom.querySelector("[data-testid=ask-busy]")).toBeNull();
    expect(text(view)).toBe("/ask orders by day");
  });
});
