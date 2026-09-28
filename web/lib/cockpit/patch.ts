/**
 * An edit to a cockpit, applied strictly (Arc CT, CT-5).
 *
 * An edit arrives as RFC 6902 operations against the spec as it stands, is shown to a person,
 * and on their approval becomes the next version. So an operation does exactly what it says
 * or the whole edit is refused: what a person approves must be what was asked.
 *
 * The library has `applySpecPatch`, and it is not used here. Measured on 0.21.0 (CT-5's
 * survey): a `replace` of a path that does not exist CREATES it, a `remove` of something
 * absent and an operation it has never heard of are both passed over in silence, and the
 * whole-document path writes a key named "". It is built for a spec arriving in pieces, where
 * leniency is the point. Here leniency would let an edit do less than it said.
 *
 * All or nothing: the spec handed in is never changed, and a refused edit hands back no spec.
 * The result still has to pass `checkCockpitSpec`; this file only moves values.
 */

export const MAX_PATCHES = 100;

export interface PatchIssue {
  /** Which operation, counted from 1 as a reader would. 0 when the edit itself is at fault. */
  index: number;
  message: string;
}

export interface PatchResult {
  ok: boolean;
  /** The edited spec. Null unless `ok`. */
  spec: unknown;
  issues: PatchIssue[];
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const q = (s: unknown) => JSON.stringify(typeof s === "string" ? s : String(s));
const clone = <T,>(v: T): T => (v === undefined ? v : JSON.parse(JSON.stringify(v)));

const OPS = ["add", "remove", "replace", "move", "copy", "test"] as const;
const INDEX = /^(0|[1-9][0-9]*)$/;
/** Keys that reach an object's prototype rather than its own members. */
const UNSAFE = new Set(["__proto__", "constructor", "prototype"]);

class Refusal extends Error {}

function tokens(pointer: unknown, what: string): string[] {
  if (typeof pointer !== "string") throw new Refusal(`its ${what} is ${JSON.stringify(pointer)}; a ${what} is a string such as "/elements/sec-a/props/title"`);
  if (pointer === "") throw new Refusal(`its ${what} is the whole spec; an edit changes a part of a cockpit, and a new cockpit is drafted whole`);
  if (!pointer.startsWith("/")) throw new Refusal(`its ${what} ${q(pointer)} does not begin with "/"`);
  const out = pointer.slice(1).split("/").map(t => t.replace(/~1/g, "/").replace(/~0/g, "~"));
  const unsafe = out.find(t => UNSAFE.has(t));
  if (unsafe) throw new Refusal(`its ${what} ${q(pointer)} names ${q(unsafe)}, which no spec holds`);
  return out;
}

const has = (o: Obj, k: string) => Object.prototype.hasOwnProperty.call(o, k);

/** The value at `path`, which must exist. */
function read(doc: unknown, path: string[], pointer: string): unknown {
  let at = doc;
  for (const t of path) {
    if (Array.isArray(at)) {
      if (!INDEX.test(t) || Number(t) >= at.length) throw new Refusal(`${q(pointer)} is not in the spec`);
      at = at[Number(t)];
    } else if (isObj(at) && has(at, t)) {
      at = at[t];
    } else {
      throw new Refusal(`${q(pointer)} is not in the spec`);
    }
  }
  return at;
}

/** The container `path` ends in, and the last token. The container must exist. */
function parent(doc: unknown, path: string[], pointer: string): [unknown, string] {
  const last = path[path.length - 1];
  const upTo = "/" + path.slice(0, -1).map(t => t.replace(/~/g, "~0").replace(/\//g, "~1")).join("/");
  const holder = path.length === 1 ? doc : read(doc, path.slice(0, -1), upTo);
  if (!Array.isArray(holder) && !isObj(holder)) {
    throw new Refusal(`${q(pointer)} is inside ${q(upTo)}, which holds nothing of its own`);
  }
  return [holder, last];
}

function add(doc: unknown, pointer: string, value: unknown): void {
  const [holder, last] = parent(doc, tokens(pointer, "path"), pointer);
  if (Array.isArray(holder)) {
    if (last === "-") { holder.push(value); return; }
    if (!INDEX.test(last) || Number(last) > holder.length) {
      throw new Refusal(`${q(pointer)} is position ${q(last)} of a list of ${holder.length}; a position is 0 to ${holder.length}, or "-" for the end`);
    }
    holder.splice(Number(last), 0, value);
    return;
  }
  (holder as Obj)[last] = value;
}

function remove(doc: unknown, pointer: string): unknown {
  const path = tokens(pointer, "path");
  const was = read(doc, path, pointer);
  const [holder, last] = parent(doc, path, pointer);
  if (Array.isArray(holder)) holder.splice(Number(last), 1);
  else delete (holder as Obj)[last];
  return was;
}

function same(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => same(v, b[i]));
  }
  if (isObj(a) || isObj(b)) {
    if (!isObj(a) || !isObj(b)) return false;
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every(k => has(b, k) && same(a[k], b[k]));
  }
  return a === b;
}

function applyOne(doc: unknown, patch: unknown): void {
  if (!isObj(patch)) throw new Refusal(`it is ${JSON.stringify(patch)}; an operation is an object with "op" and "path"`);
  const op = patch.op;
  if (typeof op !== "string" || !(OPS as readonly string[]).includes(op)) {
    throw new Refusal(`its "op" is ${JSON.stringify(op)}; an operation is one of: ${OPS.join(", ")}`);
  }
  const path = patch.path as string;
  const needsValue = op === "add" || op === "replace" || op === "test";
  if (needsValue && !has(patch, "value")) throw new Refusal(`"${op}" carries no "value"`);
  const value = clone(patch.value);

  if (op === "add") { add(doc, path, value); return; }
  if (op === "remove") { remove(doc, path); return; }
  if (op === "replace") {
    const p = tokens(path, "path");
    read(doc, p, path);                       // it must be there to be replaced
    const [holder, last] = parent(doc, p, path);
    if (Array.isArray(holder)) holder[Number(last)] = value;
    else (holder as Obj)[last] = value;
    return;
  }
  if (op === "test") {
    const found = read(doc, tokens(path, "path"), path);
    if (!same(found, value)) {
      throw new Refusal(`${q(path)} holds ${JSON.stringify(found)}, not ${JSON.stringify(value)}; the cockpit is not as the edit took it to be`);
    }
    return;
  }
  // move, copy
  const from = patch.from;
  const fromPath = tokens(from, "from");
  tokens(path, "path");
  if (op === "move") {
    if (path === from) return;
    if (path.startsWith(`${from as string}/`)) throw new Refusal(`it moves ${q(from)} into itself`);
    add(doc, path, remove(doc, from as string));
    return;
  }
  add(doc, path, clone(read(doc, fromPath, from as string)));
}

export function applyCockpitPatches(spec: unknown, patches: unknown): PatchResult {
  const refuse = (index: number, message: string): PatchResult => ({ ok: false, spec: null, issues: [{ index, message }] });
  if (!isObj(spec)) return refuse(0, "There is no cockpit to edit.");
  if (!Array.isArray(patches) || !patches.length) {
    return refuse(0, "An edit is a list of operations, and this one holds none.");
  }
  if (patches.length > MAX_PATCHES) {
    return refuse(0, `The edit holds ${patches.length} operations. An edit holds at most ${MAX_PATCHES}; a larger change is a new cockpit.`);
  }
  const doc = clone(spec);
  for (let i = 0; i < patches.length; i++) {
    try {
      applyOne(doc, patches[i]);
    } catch (e) {
      if (!(e instanceof Refusal)) throw e;
      // The operations after a refused one were written against a spec that never came to
      // be, so they are not judged. Nothing of the edit is kept.
      return refuse(i + 1, `Operation ${i + 1} of ${patches.length} is refused: ${e.message}. Nothing was changed.`);
    }
  }
  return { ok: true, spec: doc, issues: [] };
}
