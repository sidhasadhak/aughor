/**
 * AO-7b — which Slack message carried which turn, PERSISTED.
 *
 * The map used to live in memory: a restart forgot every answer the bot had posted, and a
 * ✅ on one of them the next morning recorded nothing. A verdict is the one thing a person
 * gives back, so the map that makes it land is written through to a small JSON file
 * (bounded, oldest out) and read back at start. A file that cannot be written is said
 * once and the map goes on in memory — a bot must answer even on a read-only disk.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export interface PersistedTurnMap<T> {
  get(id: string): T | undefined;
  set(id: string, value: T): void;
  size(): number;
}

export function createTurnMap<T>(opts: {
  /** Where the map lives; "" keeps it in memory only. */
  file: string;
  /** Oldest entries fall out past this. */
  limit?: number;
  log?: (line: string) => void;
}): PersistedTurnMap<T> {
  const limit = opts.limit ?? 500;
  const log = opts.log ?? (() => {});
  const m = new Map<string, T>();
  let writeFailed = false;

  if (opts.file && existsSync(opts.file)) {
    try {
      const raw = JSON.parse(readFileSync(opts.file, "utf8")) as [string, T][];
      for (const [k, v] of raw.slice(-limit)) m.set(k, v);
      log(`turn map: ${m.size} answer(s) remembered from ${opts.file}`);
    } catch (err) {
      log(`turn map: could not read ${opts.file} (${String(err)}); starting empty`);
    }
  }

  const flush = () => {
    if (!opts.file || writeFailed) return;
    try {
      mkdirSync(dirname(opts.file), { recursive: true });
      writeFileSync(opts.file, JSON.stringify([...m.entries()]), "utf8");
    } catch (err) {
      writeFailed = true;
      log(`turn map: could not write ${opts.file} (${String(err)}); a restart will forget `
        + "— verdicts on answers posted after it will not land");
    }
  };

  return {
    get: (id) => m.get(id),
    set: (id, value) => {
      if (m.has(id)) m.delete(id);          // re-set moves it to the newest end
      m.set(id, value);
      while (m.size > limit) {
        const first = m.keys().next().value;
        if (first === undefined) break;
        m.delete(first);
      }
      flush();
    },
    size: () => m.size,
  };
}
