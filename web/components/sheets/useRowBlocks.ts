"use client";

/**
 * A view's rows, read a block at a time as they scroll into sight — so the grid's scroll bar is the whole view
 * (99,441 rows scroll as one list), never a page of it with Previous and Next.
 *
 * A block is read once per reading of the view. A change to the sheet reads again the blocks in sight and drops the
 * rest; a new filter, sort or search starts over from the first block — the rows on screen stay until it lands, and
 * are then replaced whole, so a sort never empties the grid for the length of a read (the grid flashed on every
 * sort). A block that lands after the view moved on is dropped, never shown under the wrong view.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { readRows, type Changed, type ColumnTotals, type RowsQuery, type Versions } from "@/lib/sheets";

export const BLOCK = 200;
/** The most blocks kept read at once; the farthest from sight go first. */
const KEEP = 12;

interface Block { rows: unknown[][]; changed: Changed; versions: Versions; marks: Record<string, string[]> }

export interface RowBlocks {
  /** null until the first block of the first reading lands. */
  total: number | null;
  /** The rows shown are the last reading's, while a new filter, sort or search is read. */
  stale: boolean;
  totals: Record<string, ColumnTotals>;
  columns: string[];
  failed: string | null;
  rowAt: (index: number) => unknown[] | undefined;
  rowByNumber: (row: number) => unknown[] | undefined;
  changedOf: (row: number, column: string) => { by: string; at: string; version: number } | undefined;
  /** The version a change to a cell must name — 0 for one never set. */
  versionOf: (row: number, column: string) => number;
  marksOf: (row: number) => string[];
  /** The rows in sight — the blocks holding them are read if they are not. */
  onVisible: (first: number, last: number) => void;
  retry: () => void;
}

export function useRowBlocks(sheetId: string, query: RowsQuery | null, tick: number): RowBlocks {
  const key = query ? JSON.stringify(query) : "";
  const [blocks, setBlocks] = useState<Record<number, Block>>({});
  const [head, setHead] = useState<{ total: number; totals: Record<string, ColumnTotals>; columns: string[] } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const reading = useRef(0);
  // the reading whose first block replaces what is on screen, rather than joining it
  const replacing = useRef(-1);
  const pending = useRef(new Set<number>());
  const sight = useRef<[number, number]>([0, 0]);
  const queryRef = useRef(query);
  // the reading a block is read for; kept in step before the effects below read it
  useEffect(() => { queryRef.current = query; }, [query]);

  const read = useCallback((b: number, at: number) => {
    const q = queryRef.current;
    if (!q || pending.current.has(b)) return;
    pending.current.add(b);
    readRows(sheetId, { ...q, offset: b * BLOCK, limit: BLOCK })
      .then(p => {
        if (at !== reading.current) return;
        pending.current.delete(b);
        setHead({ total: p.total, totals: p.totals, columns: p.columns });
        setFailed(null);
        const block = { rows: p.rows, changed: p.changed, versions: p.versions ?? {}, marks: p.marks ?? {} };
        if (replacing.current === at) {
          replacing.current = -1;
          setStale(false);
          setBlocks({ [b]: block });
          return;
        }
        setBlocks(old => {
          const next = { ...old, [b]: block };
          const kept = Object.keys(next).map(Number);
          if (kept.length <= KEEP) return next;
          const mid = Math.floor((sight.current[0] + sight.current[1]) / 2 / BLOCK);
          kept.sort((x, y) => Math.abs(y - mid) - Math.abs(x - mid));
          for (const far of kept.slice(0, kept.length - KEEP)) delete next[far];
          return next;
        });
      })
      .catch(e => {
        if (at !== reading.current) return;
        pending.current.delete(b);
        if (replacing.current === at) { replacing.current = -1; setStale(false); }
        setFailed(e instanceof Error ? e.message : String(e));
      });
  }, [sheetId]);

  const visibleBlocks = () => {
    const [first, last] = sight.current;
    const out: number[] = [];
    for (let b = Math.floor(first / BLOCK); b <= Math.floor(Math.max(first, last) / BLOCK); b++) out.push(b);
    return out;
  };

  // a new reading of the view: from the first block, which replaces the rows on screen when it lands — another
  // sheet's rows never stay on screen under this one's columns
  const shownFor = useRef(sheetId);
  useEffect(() => {
    reading.current += 1;
    pending.current.clear();
    sight.current = [0, 0];
    if (shownFor.current !== sheetId) {
      shownFor.current = sheetId;
      replacing.current = -1;
      setStale(false);
      setBlocks({});
      setHead(null);
    } else {
      replacing.current = reading.current;
      setStale(true);
    }
    setFailed(null);
    read(0, reading.current);
  }, [key, read, sheetId]);

  // the sheet changed: the blocks in sight again, the rest dropped (kept on screen until their new reading lands)
  const firstTick = useRef(tick);
  useEffect(() => {
    if (tick === firstTick.current) return;
    firstTick.current = tick;
    reading.current += 1;
    pending.current.clear();
    const wanted = new Set(visibleBlocks());
    setBlocks(old => Object.fromEntries(Object.entries(old).filter(([b]) => wanted.has(Number(b)))));
    for (const b of wanted) read(b, reading.current);
  }, [tick, read]);

  const onVisible = useCallback((first: number, last: number) => {
    sight.current = [first, last];
    for (const b of visibleBlocks()) {
      if (!(b in blocks)) read(b, reading.current);
    }
  }, [blocks, read]);

  return useMemo<RowBlocks>(() => {
    const rowAt = (i: number) => blocks[Math.floor(i / BLOCK)]?.rows[i % BLOCK];
    const each = Object.values(blocks);
    return {
      total: head?.total ?? null,
      stale,
      totals: head?.totals ?? {},
      columns: head?.columns ?? [],
      failed,
      rowAt,
      rowByNumber: row => {
        for (const b of each) {
          const r = b.rows.find(x => Number(x[0]) === row);
          if (r) return r;
        }
        return undefined;
      },
      changedOf: (row, column) => {
        for (const b of each) {
          const c = b.changed[String(row)]?.[column];
          if (c) return c;
        }
        return undefined;
      },
      versionOf: (row, column) => {
        for (const b of each) {
          const v = b.versions[String(row)]?.[column] ?? b.changed[String(row)]?.[column]?.version;
          if (v !== undefined) return v;
        }
        return 0;
      },
      marksOf: row => {
        for (const b of each) {
          const m = b.marks[String(row)];
          if (m) return m;
        }
        return [];
      },
      onVisible,
      retry: () => {
        setFailed(null);
        pending.current.clear();
        for (const b of visibleBlocks()) read(b, reading.current);
      },
    };
  }, [blocks, head, failed, stale, onVisible, read]);
}
