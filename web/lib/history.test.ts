/**
 * DS-4 — the undo stack, asserted where it actually goes wrong.
 *
 * Not "does undo undo". The three rules that decide whether it feels right: a typed
 * sentence is one step and not forty, loading a record from the server is a new baseline
 * rather than something to walk backwards through, and the stack is bounded.
 */
import { describe, expect, it } from "vitest";

import {
  canRedo, canUndo, COALESCE_MS, initHistory, LIMIT, pushHistory, redoHistory,
  resetHistory, undoHistory,
} from "@/lib/history";

const at = (n: number) => ({ at: n });

describe("the basics", () => {
  it("walks back and forward through what happened", () => {
    let h = initHistory("a");
    h = pushHistory(h, "b");
    h = pushHistory(h, "c");

    h = undoHistory(h);
    expect(h.present).toBe("b");
    h = undoHistory(h);
    expect(h.present).toBe("a");
    h = redoHistory(h);
    expect(h.present).toBe("b");
  });

  it("stops at the beginning rather than throwing or emptying", () => {
    const h = undoHistory(undoHistory(initHistory("a")));
    expect(h.present).toBe("a");
    expect(canUndo(h)).toBe(false);
  });

  it("drops the redo stack the moment something new is done", () => {
    // The universal rule, and the one people notice only when it is missing: a branch
    // you edited away from cannot be walked back into.
    let h = pushHistory(initHistory("a"), "b");
    h = undoHistory(h);
    expect(canRedo(h)).toBe(true);

    h = pushHistory(h, "different");
    expect(canRedo(h)).toBe(false);
  });

  it("ignores a push that changes nothing", () => {
    // An undo step that restores what is already on screen is an undo that appears to
    // do nothing — which is how a stack teaches people it is broken.
    const h = initHistory("a");
    expect(pushHistory(h, "a")).toBe(h);
  });
});

describe("coalescing — a typed sentence is ONE undo", () => {
  it("replaces the top for same-key edits in quick succession", () => {
    let h = initHistory("");
    h = pushHistory(h, "H", { key: "step1.question", ...at(0) });
    h = pushHistory(h, "He", { key: "step1.question", ...at(80) });
    h = pushHistory(h, "Hel", { key: "step1.question", ...at(160) });

    expect(h.present).toBe("Hel");
    // One step back reaches the state before the WORD, not before the last letter.
    expect(undoHistory(h).present).toBe("");
  });

  it("starts a new step once the typing pauses", () => {
    let h = initHistory("");
    h = pushHistory(h, "one", { key: "step1.question", ...at(0) });
    h = pushHistory(h, "one two", { key: "step1.question", ...at(COALESCE_MS + 1) });

    expect(undoHistory(h).present).toBe("one");
  });

  it("never coalesces across DIFFERENT fields, however fast", () => {
    // Two fields edited in the same second are two edits. Merging them would make one
    // undo revert a change the person never connected to the one they were fixing.
    let h = initHistory("");
    h = pushHistory(h, "a", { key: "step1.question", ...at(0) });
    h = pushHistory(h, "b", { key: "step2.channel", ...at(10) });

    expect(undoHistory(h).present).toBe("a");
  });

  it("keeps a keyless edit standing alone", () => {
    // Adding a step or binding a port is one deliberate act; it must never be swallowed
    // into the keystroke that happened to precede it.
    let h = initHistory("");
    h = pushHistory(h, "typed", { key: "step1.question", ...at(0) });
    h = pushHistory(h, "added a step", at(10));

    expect(undoHistory(h).present).toBe("typed");
  });

  it("does not coalesce onto an entry undo just walked off", () => {
    // Otherwise: type, undo, type again — and the second typing overwrites the entry
    // the undo was standing on, so the same undo no longer goes where it just came from.
    let h = initHistory("");
    h = pushHistory(h, "one", { key: "k", ...at(0) });
    h = undoHistory(h);
    h = pushHistory(h, "two", { key: "k", ...at(50) });

    expect(undoHistory(h).present).toBe("");
    expect(h.past.length).toBe(1);
  });
});

describe("reset — the server's reply is not something a person did", () => {
  it("starts a new baseline and empties both stacks", () => {
    let h = pushHistory(initHistory("a"), "b");
    h = undoHistory(h);
    h = resetHistory(h, "from the server");

    expect(h.present).toBe("from the server");
    expect(canUndo(h)).toBe(false);
    expect(canRedo(h)).toBe(false);
  });
});

describe("the bound", () => {
  it("forgets the oldest rather than growing forever", () => {
    let h = initHistory(0);
    for (let i = 1; i <= LIMIT + 20; i++) h = pushHistory(h, i);

    expect(h.past.length).toBe(LIMIT);
    // Still walks back the full depth it promises.
    for (let i = 0; i < LIMIT; i++) h = undoHistory(h);
    expect(canUndo(h)).toBe(false);
  });
});
