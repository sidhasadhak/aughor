// @vitest-environment jsdom
/**
 * The grid flashed on every sort (the user, 2026-10-27: "why does the sheet flashes (flickering) when I sort it"): a
 * new sort emptied the rows and the count before the sorted rows were read, so for the length of a read the grid went
 * away and "Loading the rows" stood in its place. A new filter, sort or search now keeps the rows on screen until the
 * first sorted block lands, then replaces them whole — never mixing the two orders. Another sheet's rows never stay.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

type Page = { total: number; totals: Record<string, never>; columns: string[]; rows: unknown[][]; changed: object };
const asked: { id: string; sort: unknown; offset: number; resolve: (p: Page) => void }[] = [];

vi.mock("@/lib/sheets", () => ({
  readRows: (id: string, q: { sort?: unknown; offset?: number }) => new Promise<Page>(resolve => {
    asked.push({ id, sort: q.sort, offset: q.offset ?? 0, resolve });
  }),
}));

import { useRowBlocks } from "./useRowBlocks";

const page = (first: string, n = 3): Page => ({
  total: 500, totals: {}, columns: ["c1"], changed: {},
  rows: Array.from({ length: n }, (_, i) => [i + 1, `${first}${i}`]),
});
const query = (sort: { column: string; desc: boolean }[]) => ({ filter: [], sort, search: "" });

describe("a new reading of the view", () => {
  it("keeps the rows on screen until the sorted ones land, then replaces them whole", async () => {
    asked.length = 0;
    const { result, rerender } = renderHook(({ id, q }) => useRowBlocks(id, q, 0),
      { initialProps: { id: "s1", q: query([]) } });
    expect(result.current.total).toBeNull();                        // the first reading: nothing yet to keep
    act(() => asked[0].resolve(page("a")));
    await waitFor(() => expect(result.current.rowAt(0)?.[1]).toBe("a0"));
    act(() => result.current.onVisible(195, 205));                  // a second block read into sight
    await waitFor(() => expect(asked.some(a => a.offset === 200)).toBe(true));
    act(() => asked.find(a => a.offset === 200)!.resolve(page("b")));
    await waitFor(() => expect(result.current.rowAt(200)?.[1]).toBe("b0"));

    rerender({ id: "s1", q: query([{ column: "c1", desc: true }]) });   // sorted
    expect(result.current.stale).toBe(true);
    expect(result.current.total).toBe(500);                          // the count stays — no Loading in its place
    expect(result.current.rowAt(0)?.[1]).toBe("a0");                 // and the rows stay
    const sorted = asked[asked.length - 1];
    expect(sorted.sort).toEqual([{ column: "c1", desc: true }]);
    act(() => sorted.resolve(page("z")));
    await waitFor(() => expect(result.current.stale).toBe(false));
    expect(result.current.rowAt(0)?.[1]).toBe("z0");
    expect(result.current.rowAt(200)).toBeUndefined();               // the last order's block went with it
  });

  it("shows nothing of another sheet's rows", async () => {
    asked.length = 0;
    const { result, rerender } = renderHook(({ id, q }) => useRowBlocks(id, q, 0),
      { initialProps: { id: "s1", q: query([]) } });
    act(() => asked[0].resolve(page("a")));
    await waitFor(() => expect(result.current.rowAt(0)?.[1]).toBe("a0"));
    rerender({ id: "s2", q: query([]) });
    expect(result.current.rowAt(0)).toBeUndefined();
    expect(result.current.total).toBeNull();
    expect(result.current.stale).toBe(false);
  });
});
