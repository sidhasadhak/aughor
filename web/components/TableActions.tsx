"use client";
/**
 * Copy and CSV for a table — every table a reader is shown can leave the page AS a table.
 *
 * "Any table in the canvas must be copy-able structurally — what's the whole point otherwise?
 * And also downloadable as CSV" (2026-10-02). An answer's table had neither: copying it took a
 * selection that started and ended exactly on the table, and the result table beside it is an
 * Ant Design grid whose header and body are separate tables, showing 100 rows a page — no
 * selection copies that whole. So each table carries both actions, and they read the table's
 * own rows, not what a selection happened to cover:
 *
 *   · Copy writes tab-separated rows — a spreadsheet pastes them into cells — with an HTML
 *     table beside them, which a document pastes as a table;
 *   · CSV downloads RFC 4180 through the one CSV module (`lib/query/csv`).
 */
import React, { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { csvFilename, downloadCsv, toCsv, toTsv, type CsvCell } from "@/lib/query/csv";

export type TableData = { columns: string[]; rows: CsvCell[][] };

const ESCAPE: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
const esc = (v: CsvCell) => (v === null || v === undefined ? "" : String(v)).replace(/[&<>"]/g, (c) => ESCAPE[c]);

/** The table as HTML, for the clipboard's `text/html` — what a document pastes as a table. */
export function tableHtml({ columns, rows }: TableData): string {
  return `<table><thead><tr>${columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>`
    + rows.map((r) => `<tr>${r.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")
    + "</tbody></table>";
}

/** A rendered table's cells as text: the first row is the header, the rest are rows. */
export function tableFromElement(el: HTMLTableElement): TableData {
  const lines = Array.from(el.rows).map((tr) => Array.from(tr.cells).map((c) => (c.textContent ?? "").trim()));
  return { columns: lines[0] ?? [], rows: lines.slice(1) };
}

/** A result's raw values, for a spreadsheet: a number stays a number, an object its JSON. */
export function rawCells(rows: unknown[][]): CsvCell[][] {
  return rows.map((r) => (r as unknown[]).map((v) =>
    v === null || v === undefined ? null
      : typeof v === "object" ? JSON.stringify(v) : (v as CsvCell)));
}

/** Copy as tab-separated rows and an HTML table; only the rows where the clipboard takes no HTML. */
export async function copyTable(t: TableData): Promise<boolean> {
  const tsv = toTsv(t.columns, t.rows);
  try {
    if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
      await navigator.clipboard.write([new ClipboardItem({
        "text/plain": new Blob([tsv], { type: "text/plain" }),
        "text/html": new Blob([tableHtml(t)], { type: "text/html" }),
      })]);
    } else {
      await navigator.clipboard.writeText(tsv);
    }
    return true;
  } catch {
    // Refused (permissions, an insecure origin, no focus): said on the button, never thrown.
    return false;
  }
}

function slug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "table";
}

/** The two actions, reading the table when clicked — so a table still streaming in copies whole. */
export function TableActions({ read, name = "table" }: { read: () => TableData | null; name?: string }) {
  const [copied, setCopied] = useState<"" | "ok" | "failed">("");
  const copy = async () => {
    const t = read();
    if (!t) return;
    setCopied((await copyTable(t)) ? "ok" : "failed");
    setTimeout(() => setCopied(""), 1500);
  };
  const download = () => {
    const t = read();
    if (t) downloadCsv(csvFilename(slug(name)), toCsv(t.columns, t.rows));
  };
  return (
    <div className="flex items-center gap-0.5">
      <Button variant="ghost" size="xs" onClick={() => void copy()}
              title="Copy the table — pastes into a spreadsheet as cells"
              className="text-[var(--t3)] hover:text-[var(--t1)]">
        <Icon name={copied === "ok" ? "check" : "copy"} size={12} label="Copy table" />
        {copied === "ok" ? "Copied" : copied === "failed" ? "Copy failed" : "Copy"}
      </Button>
      <Button variant="ghost" size="xs" onClick={download} title="Download the table as CSV"
              className="text-[var(--t3)] hover:text-[var(--t1)]">
        <Icon name="download" size={12} label="Download CSV" />
        CSV
      </Button>
    </div>
  );
}

/** A table written in prose (an answer's, a briefing's), with its actions under its right edge. */
export function ProseTable({ children, name }: { children: React.ReactNode; name?: string }) {
  const ref = useRef<HTMLTableElement>(null);
  return (
    <div className="my-2 inline-block max-w-full align-top">
      <div className="overflow-x-auto">
        <table ref={ref} className="aug-text-ui border-collapse">{children}</table>
      </div>
      <div className="flex justify-end">
        <TableActions name={name} read={() => (ref.current ? tableFromElement(ref.current) : null)} />
      </div>
    </div>
  );
}
