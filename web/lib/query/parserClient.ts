/**
 * SE-1 — the main-thread half of the SQL parser worker.
 *
 * One lazily-created worker for the whole app, request/response correlated by id. The
 * worker is created on FIRST USE rather than at import: the Query workbench is one
 * layer of one tab, and paying 20 MB of parser download for someone who never opens
 * it is exactly the cost the worker split exists to avoid.
 *
 * Every call degrades to a usable answer rather than throwing. A parser that fails to
 * load must not make the run button dead — `splitStatements` falls back to treating
 * the buffer as one statement, and `validateSql` falls back to no squiggles.
 */
import type {
  ParseDiagnostic,
  ParserResponse,
  StatementRange,
} from "@/lib/query/parserWorker";

export type { ParseDiagnostic, StatementRange };

let worker: Worker | null = null;
let nextId = 1;
let unavailable = false;
const pending = new Map<number, (r: ParserResponse) => void>();

function ensureWorker(): Worker | null {
  if (unavailable) return null;
  if (worker) return worker;
  try {
    // The standard Turbopack/webpack-recognised worker form — the `new URL(…,
    // import.meta.url)` literal is what lets the bundler emit a separate chunk.
    worker = new Worker(new URL("./parserWorker.ts", import.meta.url));
    worker.onmessage = (ev: MessageEvent<ParserResponse>) => {
      const resolve = pending.get(ev.data?.id);
      if (resolve) { pending.delete(ev.data.id); resolve(ev.data); }
    };
    worker.onerror = () => {
      // Fail the whole facility once rather than hanging every later call: the
      // fallbacks below are honest, a pending promise that never settles is not.
      unavailable = true;
      for (const [id, resolve] of pending) {
        resolve({ id, ok: false, error: "parser worker failed to load" });
      }
      pending.clear();
      worker = null;
    };
  } catch {
    unavailable = true;
    return null;
  }
  return worker;
}

function ask(op: "split" | "validate", sql: string): Promise<ParserResponse> {
  const w = ensureWorker();
  const id = nextId++;
  if (!w) return Promise.resolve({ id, ok: false, error: "parser unavailable" });
  return new Promise((resolve) => {
    pending.set(id, resolve);
    w.postMessage({ id, op, sql });
    // A worker that never answers must not strand the caller — the caller's own
    // fallback is better than a promise that hangs for the tab's lifetime.
    setTimeout(() => {
      if (pending.delete(id)) resolve({ id, ok: false, error: "parser timed out" });
    }, 4000);
  });
}

/** Statement ranges for `sql`. Falls back to the whole buffer as one statement. */
export async function splitStatements(sql: string): Promise<StatementRange[]> {
  const res = await ask("split", sql);
  if (res.ok) return res.result as StatementRange[];
  return sql.trim() ? [{ from: 0, to: sql.length, text: sql }] : [];
}

/** Approximate syntax diagnostics. Falls back to none. */
export async function validateSql(sql: string): Promise<ParseDiagnostic[]> {
  const res = await ask("validate", sql);
  return res.ok ? (res.result as ParseDiagnostic[]) : [];
}

/** The statement containing `cursor`, or null. The range whose span covers the
 *  cursor wins; on a boundary the LATER statement wins, which matches the intuition
 *  that a cursor sitting just after a `;` belongs to what you are about to type. */
export function statementAt(
  ranges: StatementRange[], cursor: number,
): StatementRange | null {
  let found: StatementRange | null = null;
  for (const r of ranges) {
    if (cursor >= r.from && cursor <= r.to) found = r;
    else if (r.from > cursor && !found) { found = r; break; }
  }
  return found ?? (ranges.length ? ranges[ranges.length - 1] : null);
}
