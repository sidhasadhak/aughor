/**
 * SSE splitter tests — CI-1d.
 *
 * The straddling-chunk case is the one that matters. A parser that assumes each
 * network read contains whole records loses the frame that spans a boundary,
 * and loses it SILENTLY: the next read starts mid-JSON and simply fails to
 * parse. Fixtures never reproduce it because a fixture arrives in one piece.
 */

import { describe, expect, it } from "vitest";

import { FrameBuffer, parseRecord, readFrames } from "./sseFrames";

/** A body that hands back exactly the chunks given, as the network would. */
function bodyOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(c) {
      if (i < chunks.length) c.enqueue(enc.encode(chunks[i++]));
      else c.close();
    },
  });
}

async function collect(chunks: string[]) {
  const out = [];
  for await (const f of readFrames(bodyOf(chunks))) out.push(f);
  return out;
}

describe("parseRecord", () => {
  it("reads event name and JSON payload", () => {
    expect(parseRecord('event: route\ndata: {"mode":"ask"}')).toEqual({
      event: "route", data: { mode: "ask" },
    });
  });

  it("defaults the event name when the record omits one", () => {
    expect(parseRecord('data: {"a":1}')?.event).toBe("message");
  });

  it("ignores a record with no data line", () => {
    expect(parseRecord("event: ping")).toBeNull();
  });

  it("surfaces unparseable JSON as an error frame rather than dropping it", () => {
    const f = parseRecord("event: rows\ndata: {not json");
    expect(f?.event).toBe("error");
    expect(String(f?.data.message)).toContain("unparseable rows frame");
  });

  it("rejoins a multi-line data payload", () => {
    // The SDK/spec allows a payload split across several `data:` lines.
    expect(parseRecord('data: {"a":\ndata: 1}')).toEqual({ event: "message", data: { a: 1 } });
  });
});

describe("FrameBuffer — the straddling chunk", () => {
  it("keeps a record that spans two pushes", () => {
    const b = new FrameBuffer();
    expect(b.push('event: sql\ndata: {"sq')).toEqual([]); // nothing complete yet
    const got = b.push('l":"SELECT 1"}\n\n');
    expect(got).toEqual([{ event: "sql", data: { sql: "SELECT 1" } }]);
  });

  it("splits several records arriving in one push", () => {
    const b = new FrameBuffer();
    const got = b.push('data: {"n":1}\n\ndata: {"n":2}\n\ndata: {"n":3}\n\n');
    expect(got.map((f) => f.data.n)).toEqual([1, 2, 3]);
  });

  it("reports a truncated tail as pending", () => {
    const b = new FrameBuffer();
    b.push('data: {"n":1}\n\ndata: {"trunc');
    expect(b.pending).toBe('data: {"trunc');
  });

  it("does NOT split on a newline inside a JSON payload", () => {
    // A narrative with a line break is ordinary; splitting per line tears the
    // frame into unparseable pieces.
    const b = new FrameBuffer();
    const got = b.push('data: {"narrative":"line one\\nline two"}\n\n');
    expect(got).toHaveLength(1);
    expect(got[0].data.narrative).toBe("line one\nline two");
  });
});

describe("readFrames over a chunked body", () => {
  it("recovers every frame regardless of where the boundaries fall", async () => {
    const whole = 'event: start\ndata: {"investigation_id":"i1"}\n\n'
      + 'event: narrative_delta\ndata: {"narrative":"Rev"}\n\n'
      + 'event: done\ndata: {}\n\n';
    // Byte-by-byte is the worst case a real network can produce.
    const perChar = await collect([...whole]);
    expect(perChar.map((f) => f.event)).toEqual(["start", "narrative_delta", "done"]);

    // And the same content in two arbitrary pieces.
    const split = await collect([whole.slice(0, 37), whole.slice(37)]);
    expect(split.map((f) => f.event)).toEqual(["start", "narrative_delta", "done"]);
  });

  it("yields nothing for an empty body rather than hanging", async () => {
    expect(await collect([])).toEqual([]);
  });

  it("drops a truncated final record instead of emitting a half frame", async () => {
    const got = await collect(['data: {"n":1}\n\ndata: {"trunc']);
    expect(got).toHaveLength(1);
    expect(got[0].data.n).toBe(1);
  });
});
