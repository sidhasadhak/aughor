/**
 * CP-5 — the turn's table, as the platform formats it, shaped for Slack.
 *
 * This file used to BUILD the table (`gfmTable`, `renderGrid`, `toCsv`): one of the three
 * unshared answers to "show a table" that Arc CP's census counted, and the one that posted
 * `54496.64009666443` into a thread, because it formatted no cell. The table is now built
 * once, in Python (`aughor/answer/exhibit.py`, by the web table's own rule), and this file
 * asks for it through `POST /exhibits/table` with Slack's ENCODINGS — the only part of a
 * table this door owns:
 *
 * Slack has no table widget. A GFM table renders, but only while it is narrow enough not
 * to wrap into mush — past roughly six columns a table stops being readable in a thread and
 * starts being a wall. So narrow-and-short renders inline, everything else rides as a CSV
 * the reader can open in the tool they were going to open it in anyway, with a preview above
 * it so the thread still shows the answer. Whatever is trimmed says so: the caption comes
 * back with the table.
 */

/** Past this many columns a Slack table wraps into an unreadable block. */
export const MAX_INLINE_COLS = 6;
/** Past this many rows a thread turns into a spreadsheet nobody scrolls. */
export const MAX_INLINE_ROWS = 10;
/** How much of an oversized grid to preview above its CSV. */
export const PREVIEW_ROWS = 5;

export interface Grid {
  columns: string[];
  rows: unknown[][];
}

export interface TableRendering {
  /** Markdown to post — the whole table, a captioned preview of it, or a caption alone. */
  markdown: string;
  /** Every row as CSV when the markdown does not carry them all. */
  csv: string | null;
}

/** `null` when there is nothing worth a second message — a one-number result the prose
 *  already said — or when the platform could not be asked; the answer is already posted. */
export type TableRenderer = (grid: Grid) => Promise<TableRendering | null>;

interface Env {
  AUGHOR_API_URL?: string;
  AUGHOR_API_KEY?: string;
  AUGHOR_CONNECTION_ID?: string;
}

export function createTableRenderer(
  env: Env = process.env,
  fetchImpl: typeof fetch = fetch,
): TableRenderer {
  const base = (env.AUGHOR_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
  // The connection names the org whose currency a money column reads in — never on the
  // `/ask` wire, so it rides here the way it rides on the chart request.
  const connection = env.AUGHOR_CONNECTION_ID ?? "workspace";

  return async function renderTable({ columns, rows }) {
    if (!columns.length || !rows.length) return null;
    try {
      const res = await fetchImpl(`${base}/exhibits/table`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          ...(env.AUGHOR_API_KEY ? { "x-api-key": env.AUGHOR_API_KEY } : {}),
        },
        body: JSON.stringify({
          columns, rows,
          max_cols: MAX_INLINE_COLS, max_rows: MAX_INLINE_ROWS, preview_rows: PREVIEW_ROWS,
          rest: "the full result is attached as CSV",
          connection_id: connection,
        }),
      });
      if (!res.ok) return null;
      const body = (await res.json()) as { show?: boolean; markdown?: unknown; csv?: unknown };
      if (!body.show) return null;
      return {
        markdown: typeof body.markdown === "string" ? body.markdown : "",
        csv: typeof body.csv === "string" ? body.csv : null,
      };
    } catch {
      return null; // the API went away after answering; the answer itself already landed
    }
  };
}

/** A filename that sorts and survives Slack — no colons, no spaces. */
export function csvFilename(question: string): string {
  const stem = question.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
  return `${stem || "result"}.csv`;
}
