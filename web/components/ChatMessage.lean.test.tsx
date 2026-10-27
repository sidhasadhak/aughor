// @vitest-environment jsdom
/**
 * The chat beside a sheet answers lean (Arc SH, the user, 2026-10-27): "Do we need the N, Late N, Late Pct and
 * everything below that? I know its from our standard template for Canvas, but it need not be everywhere." Beside a
 * sheet the grid is the table, so the answer is its prose and the steps it took — no result figure (it repeated the
 * answer's own numbers under raw column names), no actions, no details, no export. Every other surface is unchanged,
 * and an answer the numbers check withheld still shows the result it points at.
 */
import { beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ChatMessage } from "@/components/ChatMessage";
import { EMPTY_TURN, type ChatTurn } from "@/lib/chatTurn";

beforeAll(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: false, media: q, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  }));
});

const TURN = {
  ...EMPTY_TURN, id: "t1", mode: "ask", status: "done",
  question: "Is any specific city more likely to receive delayed shipments in SP state?",
  sql: "SELECT COUNT(*) n, SUM(late::INT) late_n, ROUND(100.0*AVG(late::INT),2) late_pct FROM olist_orders",
  columns: ["n", "late_n", "late_pct"],
  rows: [[40495, 1820, 4.49]],
  headline: "Yes — across SP, 4.49% of delivered orders were late (1,820 of 40,495).",
  receiptId: "r1",
} as ChatTurn;

describe("a lean answer", () => {
  it("is the answer alone: no figure, actions, details or export", () => {
    const { container } = render(<ChatMessage turn={TURN} connectionId="sheets" lean />);
    expect(screen.getByText(/4.49% of delivered orders were late/)).toBeInTheDocument();
    expect(container.querySelectorAll(".aug-fs-h2")).toHaveLength(0);           // the N / Late N / Late Pct tiles
    for (const gone of ["Pin to dashboard", "Run a deep analysis", "Methodology & details", "Export"]) {
      expect(screen.queryByText(gone)).not.toBeInTheDocument();
    }
  });

  it("is the template as it was everywhere else", () => {
    const { container } = render(<ChatMessage turn={TURN} connectionId="sheets" />);
    expect(container.querySelectorAll(".aug-fs-h2").length).toBeGreaterThan(0);
    expect(screen.getByText("Methodology & details")).toBeInTheDocument();
  });

  it("still shows the result a withheld answer points at", () => {
    const withheld = { ...TURN, headline: "I could not ground this answer in the query result — …",
      guardReceipts: [{ guard: "numeric grounding", action: "withheld the answer", detail: "" }] } as ChatTurn;
    const { container } = render(<ChatMessage turn={withheld} connectionId="sheets" lean />);
    expect(container.querySelectorAll(".aug-fs-h2").length).toBeGreaterThan(0);
    expect(screen.queryByText("Methodology & details")).not.toBeInTheDocument();
  });
});
