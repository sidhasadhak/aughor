/**
 * DS-4 · undo/redo, as a value.
 *
 * Pure and React-free on purpose. The interesting parts of an undo stack are not the two
 * arrays — they are the three decisions that make it feel right, and each one is wrong in
 * a way a rendered test cannot see:
 *
 * 1. **Coalescing.** A field edit fires per keystroke. A stack that pushed each one makes
 *    undo eat a character at a time, which reads as broken rather than granular. Edits
 *    carrying the same `key` within `COALESCE_MS` REPLACE the top instead of pushing, so
 *    a typed sentence is one undo.
 * 2. **Reset vs record.** Loading a fresh record from the server is not something a
 *    person did, so it cannot be undone: it starts a new baseline and empties both
 *    stacks. Recording it would let undo walk backwards through the server's own reply.
 * 3. **A bound.** An editing session is unbounded; memory is not. The oldest entries fall
 *    off the back once `LIMIT` is reached — undo far enough and you stop, rather than
 *    growing a stack nobody will ever walk to the end of.
 *
 * A redo stack is dropped by any new edit, which is the universal rule and the one people
 * are surprised by only when it is missing.
 */

/** How long two edits carrying the same key stay one undo step. Long enough to cover
 *  typing at speed, short enough that a pause reads as a new thought. */
export const COALESCE_MS = 600;

/** How many steps back a person can walk. Beyond this the oldest are forgotten. */
export const LIMIT = 60;

export interface History<T> {
  past: T[];
  present: T;
  future: T[];
  /** What the top entry was about, for coalescing. `null` = never coalesce onto it. */
  lastKey: string | null;
  lastAt: number;
}

export function initHistory<T>(present: T): History<T> {
  return { past: [], present, future: [], lastKey: null, lastAt: 0 };
}

export interface PushOptions {
  /** Edits sharing a key, close together in time, become ONE undo step. Omit for an
   *  edit that should always stand alone (adding a step, binding a port, discarding). */
  key?: string;
  /** The clock, injected so a test can be about the rule rather than about waiting. */
  at?: number;
}

/**
 * Record a new present.
 *
 * A push identical to the current present is a no-op: nothing happened, and an undo step
 * that restores what is already on screen is an undo that appears to do nothing.
 */
export function pushHistory<T>(
  history: History<T>, next: T, options: PushOptions = {},
): History<T> {
  if (Object.is(next, history.present)) return history;

  const key = options.key ?? null;
  const at = options.at ?? 0;
  const coalesce = key !== null
    && key === history.lastKey
    && at - history.lastAt < COALESCE_MS;

  if (coalesce) {
    // Same thought, still being typed: the top entry moves, the stack does not grow.
    return { ...history, present: next, future: [], lastAt: at };
  }

  const past = [...history.past, history.present];
  return {
    past: past.length > LIMIT ? past.slice(past.length - LIMIT) : past,
    present: next,
    future: [],
    lastKey: key,
    lastAt: at,
  };
}

export function canUndo<T>(history: History<T>): boolean {
  return history.past.length > 0;
}

export function canRedo<T>(history: History<T>): boolean {
  return history.future.length > 0;
}

export function undoHistory<T>(history: History<T>): History<T> {
  if (!history.past.length) return history;
  const present = history.past[history.past.length - 1];
  return {
    past: history.past.slice(0, -1),
    present,
    future: [history.present, ...history.future],
    // The next edit after an undo must never coalesce onto the entry it just walked off.
    lastKey: null,
    lastAt: 0,
  };
}

export function redoHistory<T>(history: History<T>): History<T> {
  if (!history.future.length) return history;
  const [present, ...future] = history.future;
  return {
    past: [...history.past, history.present],
    present,
    future,
    lastKey: null,
    lastAt: 0,
  };
}

/**
 * Start again from `present` — a new record arrived, and nothing before it was this
 * automation. Both stacks empty: an undo across that boundary would restore a draft of a
 * different thing.
 */
export function resetHistory<T>(history: History<T>, present: T): History<T> {
  return initHistory(present);
}
