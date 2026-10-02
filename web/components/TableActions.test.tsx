// @vitest-environment jsdom
/**
 * Every table a reader is shown can leave the page AS a table (2026-10-02): "Any table in the canvas
 * must be copy-able structurally — what's the whole point otherwise? And also downloadable as CSV."
 *
 * Measured first: an answer's table copied structurally only from a selection that began and ended on
 * the table, and the result grid beside it — an Ant Design table whose header and body are separate
 * tables, a hundred rows a page — could not be copied whole at all. Neither offered a CSV.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/query/csv", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/query/csv")>()),
  downloadCsv: vi.fn(),
}));

import { downloadCsv } from "@/lib/query/csv";
import { AnswerProse } from "@/components/chat/AnswerProse";
import { renderProseBlocks } from "@/components/brief/BriefProse";
import { SqlResultTable } from "@/components/AugTable";
import { copyTable, tableHtml } from "@/components/TableActions";

// Q3's answer table, as the model wrote it.
const ANSWER = ["| Month | Monthly Revenue | Change |", "| :--- | :--- | :--- |",
                "| 2025-09-01 | $50,543.93 | -$5,421.84 |", "| 2025-10-01 | $58,007.77 | +$7,463.84 |"].join("\n");
const ANSWER_TSV = "Month\tMonthly Revenue\tChange\n2025-09-01\t$50,543.93\t-$5,421.84\n2025-10-01\t$58,007.77\t+$7,463.84";

let written: Record<string, string>[] = [];

class FakeClipboardItem {
  constructor(public parts: Record<string, Blob>) {}
}

/** jsdom's Blob has no `text()`. */
const blobText = (blob: Blob) => new Promise<string>((resolve) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result));
  reader.readAsText(blob);
});

beforeEach(() => {
  written = [];
  vi.stubGlobal("ClipboardItem", FakeClipboardItem);
  // The result grid is Ant Design's, which measures itself.
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addListener() {}, removeListener() {},
                                                addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {
      write: vi.fn(async (items: FakeClipboardItem[]) => {
        for (const item of items) {
          written.push(Object.fromEntries(await Promise.all(
            Object.entries(item.parts).map(async ([kind, blob]) => [kind, await blobText(blob)]))));
        }
      }),
      writeText: vi.fn(async (text: string) => { written.push({ "text/plain": text }); }),
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(downloadCsv).mockClear();
});

const copyButton = () => screen.getByRole("button", { name: /copy/i });
const csvButton = () => screen.getByRole("button", { name: /csv/i });

describe("an answer's table", () => {
  it("copies as rows and cells — tab-separated for a spreadsheet, a table for a document", async () => {
    render(<AnswerProse text={ANSWER} />);
    fireEvent.click(copyButton());
    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]["text/plain"]).toBe(ANSWER_TSV);
    expect(written[0]["text/html"]).toContain("<th>Monthly Revenue</th>");
    expect(written[0]["text/html"]).toContain("<td>+$7,463.84</td>");
  });

  it("downloads as a CSV a spreadsheet opens", () => {
    render(<AnswerProse text={ANSWER} />);
    fireEvent.click(csvButton());
    expect(downloadCsv).toHaveBeenCalledTimes(1);
    const [name, body] = vi.mocked(downloadCsv).mock.calls[0];
    expect(name).toMatch(/^table-\d{4}-\d{2}-\d{2}-\d{6}\.csv$/);
    expect(body).toBe('Month,Monthly Revenue,Change\r\n2025-09-01,"$50,543.93","-$5,421.84"\r\n'
                      + '2025-10-01,"$58,007.77","+$7,463.84"');
  });
});

describe("a briefing's table", () => {
  it("copies the same way", async () => {
    render(<div>{renderProseBlocks(ANSWER)}</div>);
    fireEvent.click(copyButton());
    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]["text/plain"]).toBe(ANSWER_TSV);
  });
});

describe("a result table", () => {
  it("copies every row, raw — not the page of a hundred the grid shows", async () => {
    const rows = Array.from({ length: 150 }, (_, i) => [`R${i}`, 1000.5 + i, i % 2 ? null : "x"]);
    render(<SqlResultTable columns={["region", "revenue", "flag"]} rows={rows} name="Revenue by region" />);
    fireEvent.click(copyButton());
    await waitFor(() => expect(written).toHaveLength(1));
    const lines = written[0]["text/plain"].split("\n");
    expect(lines).toHaveLength(151);
    expect([lines[0], lines[1], lines[150]]).toEqual(["region\trevenue\tflag", "R0\t1000.5\tx", "R149\t1149.5\t"]);
    fireEvent.click(csvButton());
    expect(vi.mocked(downloadCsv).mock.calls[0][0]).toMatch(/^revenue-by-region-\d{4}-/);
  });

  it("offers both with nothing to total", () => {
    render(<SqlResultTable columns={["name"]} rows={[["a"], ["b"]]} />);
    expect(csvButton()).toBeTruthy();
    expect(screen.queryByText(/Totals/)).toBeNull();
  });
});

describe("the clipboard", () => {
  it("takes the rows alone where it takes no HTML", async () => {
    vi.stubGlobal("ClipboardItem", undefined);
    expect(await copyTable({ columns: ["a", "b"], rows: [["1", null]] })).toBe(true);
    expect(written).toEqual([{ "text/plain": "a\tb\n1\t" }]);
  });

  it("refusing is said on the button, never thrown", async () => {
    navigator.clipboard.write = vi.fn(async () => { throw new Error("denied"); });
    expect(await copyTable({ columns: ["a"], rows: [["1"]] })).toBe(false);
    render(<AnswerProse text={ANSWER} />);
    fireEvent.click(copyButton());
    await waitFor(() => expect(copyButton().textContent).toContain("Copy failed"));
  });

  it("escapes a cell's HTML", () => {
    expect(tableHtml({ columns: ["<b>"], rows: [['a & "b"']] }))
      .toBe("<table><thead><tr><th>&lt;b&gt;</th></tr></thead><tbody><tr><td>a &amp; &quot;b&quot;</td></tr></tbody></table>");
  });
});
