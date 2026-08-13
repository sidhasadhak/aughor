/**
 * CSV export for a result set — ONE implementation, for every surface that offers it.
 *
 * There were two. SE-1's results panel escaped to RFC 4180; the visual builder's
 * `exportCsv` tested `/[",\n]/` and joined rows with `\n`. That second one is not a
 * style difference, it is a correctness gap: a cell containing a CARRIAGE RETURN went
 * out unquoted, and a bare CR inside an unquoted field ends the record for a strict
 * reader. The row splits in two and every column after it shifts. Warehouse text
 * columns carry `\r\n` more often than anyone expects — anything that has been through
 * a Windows editor, a pasted address, a copied description.
 *
 * A result set is arbitrary user data, so the escape has to hold for all of it. This is
 * the one place that judgement lives now.
 */

/** Cells the grid can hold. Typed results carry real nulls; the legacy path strings. */
export type CsvCell = string | number | boolean | null | undefined;

/**
 * RFC 4180. A field is quoted when it contains a quote, a comma, CR or LF; embedded
 * quotes double. Records are CRLF-terminated, which is what the spec says and what
 * Excel produces.
 *
 * NULL becomes an EMPTY field, never the `∅` display glyph: the glyph exists so a
 * reader can tell a null from an empty string on screen, and a spreadsheet importing
 * it would get a literal character where it should get a blank cell.
 */
export function toCsv(columns: string[], rows: readonly CsvCell[][]): string {
  const cell = (v: CsvCell) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map(cell).join(","), ...rows.map(r => r.map(cell).join(","))].join("\r\n");
}

/**
 * Tab-separated, for the CLIPBOARD. Spreadsheets paste TSV straight into cells while
 * CSV lands in a single column, so the two exports genuinely want different formats.
 * Tabs and newlines inside a cell are collapsed to spaces rather than quoted: TSV has
 * no escape mechanism, so the only honest options are to flatten or to corrupt.
 */
export function toTsv(columns: string[], rows: readonly CsvCell[][]): string {
  const cell = (v: CsvCell) =>
    v === null || v === undefined ? "" : String(v).replace(/[\t\r\n]+/g, " ");
  return [columns.map(cell).join("\t"), ...rows.map(r => r.map(cell).join("\t"))].join("\n");
}

/** A filename stamped with the run's local time, so repeated exports do not collide. */
export function csvFilename(prefix = "query"): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${prefix}-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
    + `-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.csv`;
}

/** Hand the browser a file. A blocked download must never take the panel down. */
export function downloadCsv(name: string, body: string): void {
  try {
    const url = URL.createObjectURL(new Blob([body], { type: "text/csv;charset=utf-8;" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    // Revoked on a later tick, not immediately: some browsers have not finished reading
    // the blob when click() returns, and revoking early yields an empty file.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch { /* a blocked download is not worth failing the panel over */ }
}
