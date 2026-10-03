import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { createTurnMap } from "./turnmap.js";

describe("the persisted turn map (AO-7b)", () => {
  it("survives a restart", () => {
    const file = join(mkdtempSync(join(tmpdir(), "turnmap-")), "turns.json");
    const a = createTurnMap<{ investigationId: string }>({ file });
    a.set("msg-1", { investigationId: "inv-1" });
    a.set("thread-1", { investigationId: "inv-1" });
    expect(JSON.parse(readFileSync(file, "utf8"))).toHaveLength(2);
    const b = createTurnMap<{ investigationId: string }>({ file });
    expect(b.get("msg-1")?.investigationId).toBe("inv-1");
    expect(b.size()).toBe(2);
  });

  it("is bounded, oldest out", () => {
    const m = createTurnMap<number>({ file: "", limit: 3 });
    for (let i = 0; i < 5; i++) m.set(`k${i}`, i);
    expect(m.size()).toBe(3);
    expect(m.get("k0")).toBeUndefined();
    expect(m.get("k4")).toBe(4);
  });

  it("goes on in memory when the file cannot be written, and says so once", () => {
    const lines: string[] = [];
    const m = createTurnMap<number>({ file: "/nonexistent-root-dir/x/turns.json", log: l => lines.push(l) });
    m.set("a", 1); m.set("b", 2);
    expect(m.get("b")).toBe(2);
    expect(lines.filter(l => l.includes("could not write"))).toHaveLength(1);
  });
});
