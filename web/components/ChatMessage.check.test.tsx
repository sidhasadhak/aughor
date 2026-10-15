// @vitest-environment jsdom
/**
 * A check — a question that verifies the data (route shape "check", 2026-10-15) — reads as a
 * table, not a hero. The quick body's one-row result used to become metric tiles whatever the
 * question; for a check the counts a verdict rests on are read in their columns, and a result
 * is charted only when it has a real dimension (a count by platform is a bar).
 */
import { beforeAll, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

import { ChatMessage } from "@/components/ChatMessage";
import { EMPTY_TURN, type ChatTurn } from "@/lib/chatTurn";

// The result table's grid reads the viewport; jsdom has no matchMedia.
beforeAll(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: false, media: q, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  }));
});

const route = (shape: string): NonNullable<ChatTurn["route"]> => ({
  depth: "quick", mode: "direct", tier: "simple", why: "", ambiguous: false,
  forced: null, downgradedFrom: null, shape,
});

const turn = (over: Partial<ChatTurn>): ChatTurn => ({
  ...EMPTY_TURN, id: "t1", mode: "ask", status: "done",
  question: "Do Event and Platform really join on these keys?",
  sql: "SELECT COUNT(*) AS total_rows, COUNT(p.id) AS matched, COUNT(*) - COUNT(p.id) AS orphans FROM event e LEFT JOIN platform p ON p.id = e.platform_id",
  columns: ["total_rows", "matched", "orphans"],
  rows: [[1642, 1642, 0]],
  headline: "Yes: every event row joins a platform; 0 orphans.",
  ...over,
} as ChatTurn);

const tiles = (c: HTMLElement) => c.querySelectorAll(".aug-fs-h2").length;

describe("a check's one-row result", () => {
  it("is a table of its counts, not metric tiles", () => {
    const { container } = render(<ChatMessage turn={turn({ route: route("check") })} />);
    expect(tiles(container)).toBe(0);
    expect(container.textContent).toContain("orphans");
    expect(container.textContent).toContain("1,642");
  });

  it("stays a hero for a describe, as before", () => {
    const { container } = render(<ChatMessage turn={turn({
      question: "How many events are there?", columns: ["events"], rows: [[1642]],
      headline: "1,642 events.", route: route("describe"),
    })} />);
    expect(tiles(container)).toBeGreaterThan(0);
  });
});
