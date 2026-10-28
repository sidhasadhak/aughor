"use client";

/**
 * The Spreadsheets home (mockup screen 1): how to start a sheet, the workspace's sheets — rows, columns, where each came
 * from, its last change and who it is shared with — and the files already uploaded to the Workspace, each one click
 * from becoming a sheet.
 */
import { type CSSProperties, useCallback, useEffect, useMemo, useState } from "react";

import { Chip, Empty, Label, MUTED, NUM, ONE_LINE } from "@/components/clarity/kit";
import { NewSheetDialog, type NewSheetStart } from "@/components/sheets/NewSheetDialog";
import { NewSheetChat } from "@/components/sheets/SheetChat";
import { SharePop } from "@/components/sheets/SheetSharing";
import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Loading, ReadFailed } from "@/components/ui/states";
import { formatCount, formatTimestamp } from "@/lib/format";
import {
  isWithheld, lastChangeWords, listSheets, sharedWords, type SheetSummary, type UploadedFile, type WithheldSheet,
} from "@/lib/sheets";

const BAR: CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, padding: "10px 22px", borderBottom: "1px solid var(--b1)",
  background: "var(--bg-1)", flex: "0 0 auto", flexWrap: "wrap",
};

function size(bytes: number): string {
  if (bytes >= 1 << 20) return `${(bytes / (1 << 20)).toFixed(1)} MB`;
  if (bytes >= 1 << 10) return `${Math.round(bytes / (1 << 10))} KB`;
  return `${bytes} B`;
}

export function SheetsHome({ onOpen }: { onOpen: (id: string) => void }) {
  // the sheets the reader may open, and apart from them the ones not shared with them — named, never read (SH-8)
  const [data, setData] = useState<{ sheets: SheetSummary[]; withheld: WithheldSheet[]; uploads: UploadedFile[];
    me: string } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [start, setStart] = useState<NewSheetStart | null>(null);
  const [chatting, setChatting] = useState(false);
  const [find, setFind] = useState("");
  const [sharing, setSharing] = useState<string>("");
  const [moreFiles, setMoreFiles] = useState(false);

  const read = useCallback(() => {
    listSheets().then(d => {
      setData({ ...d, sheets: d.sheets.filter((s): s is SheetSummary => !isWithheld(s)), withheld: d.sheets.filter(isWithheld) });
      setFailed(null);
    })
      .catch(e => setFailed(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(() => { read(); }, [read]);

  const shown = useMemo(() => {
    const q = find.trim().toLowerCase();
    return (data?.sheets ?? []).filter(s => !q || s.name.toLowerCase().includes(q) || s.came_from.toLowerCase().includes(q));
  }, [data, find]);
  const notShared = useMemo(() => {
    const q = find.trim().toLowerCase();
    return (data?.withheld ?? []).filter(s => !q || s.name.toLowerCase().includes(q));
  }, [data, find]);

  if (failed) return <ReadFailed what="the sheets" error={failed} onRetry={read} />;
  if (!data) return <Loading what="the sheets" />;

  const rows = data.sheets.reduce((n, s) => n + (s.rows || 0), 0);
  const tiles: { icon: IconName; title: string; detail: string; start: NewSheetStart | "chat" }[] = [
    { icon: "table", title: "From a file", detail: "CSV, TSV, Parquet, JSON · an Excel workbook becomes one sheet per tab",
      start: { source: "file" } },
    { icon: "plus", title: "Blank", detail: "Name it, then add columns and rows", start: { source: "blank" } },
    { icon: "sql", title: "From a query or an answer", detail: "Keep the rows of a SQL result or a chat answer",
      start: { source: "rows" } },
    { icon: "spark", title: "In the chat", detail: "Drop a file and say what it is for", start: "chat" },
  ];
  // the largest first — a workspace's own data before its odds and ends — each marked when a sheet was made from it
  const byFile = new Map<string, SheetSummary[]>();
  for (const s of data.sheets) {
    const from = s.source.upload?.file || s.source.file;
    if (from) byFile.set(from, [...(byFile.get(from) ?? []), s]);
  }
  const ordered = [...data.uploads].sort((a, b) => b.size - a.size || a.file.localeCompare(b.file));
  const files = moreFiles ? ordered : ordered.slice(0, 6);
  const schemas = new Set(data.uploads.map(f => f.schema));

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", background: "var(--bg-0)" }}>
        <div style={BAR}>
          <span className="aug-fs-ui" style={{ fontWeight: 600, color: "var(--t1)" }}>Spreadsheets</span>
          <Chip title="A sheet belongs to its workspace — everyone in it reads and edits it — until its maker shares it with chosen people.">
            Workspace
          </Chip>
          <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>
            {formatCount(data.sheets.length)} sheet{data.sheets.length === 1 ? "" : "s"} · {formatCount(rows)} rows
            {data.withheld.length ? ` · ${formatCount(data.withheld.length)} not shared with you` : ""}
          </span>
          <div style={{ marginLeft: "auto", width: 220 }}>
            <Input value={find} onChange={e => setFind(e.target.value)} placeholder="Find a sheet" aria-label="Find a sheet" />
          </div>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "16px 22px 28px", display: "flex",
          flexDirection: "column", gap: 18 }}>
          <section>
            <Label>Start a sheet</Label>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
              {tiles.map(t => (
                <Button key={t.start === "chat" ? "chat" : t.start.source} variant="ghost"
                  onClick={() => (t.start === "chat" ? setChatting(true) : setStart(t.start))}
                  style={{ display: "flex", alignItems: "flex-start", gap: 10, height: "auto", padding: "12px 14px",
                    textAlign: "left", whiteSpace: "normal", border: "1px solid var(--card-edge)",
                    background: "var(--bg-2)", borderRadius: "var(--r3)", fontWeight: 400 }}>
                  <span style={{ color: "var(--blue4)", paddingTop: 2 }}><Icon name={t.icon} size={16} /></span>
                  <span>
                    <span className="aug-fs-ui" style={{ display: "block", color: "var(--t1)", fontWeight: 600 }}>{t.title}</span>
                    <span className="aug-fs-xs" style={{ ...MUTED, display: "block", marginTop: 2 }}>{t.detail}</span>
                  </span>
                </Button>
              ))}
            </div>
          </section>

          <section>
            <Label right={find ? `${formatCount(shown.length)} of ${formatCount(data.sheets.length)}` : undefined}>
              Sheets in this workspace
            </Label>
            {data.sheets.length === 0 && data.withheld.length === 0 ? (
              <Empty>No sheet yet. Start one from a file, from nothing, or from a query&apos;s rows.</Empty>
            ) : (
              <table className="aug-fs-sm" style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr className="aug-fs-xs" style={{ ...MUTED, textAlign: "left" }}>
                    <th style={{ padding: "6px 8px", fontWeight: 500 }}>Sheet</th>
                    <th style={{ padding: "6px 8px", fontWeight: 500, textAlign: "right" }}>Rows</th>
                    <th style={{ padding: "6px 8px", fontWeight: 500, textAlign: "right" }}>Columns</th>
                    <th style={{ padding: "6px 8px", fontWeight: 500 }}>From</th>
                    <th style={{ padding: "6px 8px", fontWeight: 500 }}>Last change</th>
                    <th style={{ padding: "6px 8px", fontWeight: 500 }}>Shared with</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map(s => (
                    <tr key={s.id} style={{ borderTop: "1px solid var(--b0)", height: 34 }}>
                      <td style={{ padding: "4px 8px" }}>
                        <Button variant="ghost" size="sm" onClick={() => onOpen(s.id)}
                          style={{ fontWeight: 600, color: "var(--t1)", padding: "0 4px" }}>
                          <Icon name="table" size={13} /> {s.name}
                        </Button>
                        {s.access === "view" && <span className="aug-fs-xs" style={MUTED} title="Shared with you to read">can read</span>}
                      </td>
                      <td style={{ padding: "4px 8px", textAlign: "right", ...NUM }}>{formatCount(s.rows)}</td>
                      <td style={{ padding: "4px 8px", textAlign: "right", ...NUM }}>
                        {typeof s.columns === "number" ? s.columns : s.columns.length}
                      </td>
                      <td style={{ padding: "4px 8px", ...MUTED, ...ONE_LINE, maxWidth: 320 }} title={s.came_from}>{s.came_from}</td>
                      <td style={{ padding: "4px 8px", ...MUTED, ...ONE_LINE, maxWidth: 320 }}
                        title={`${s.last_change.what} · ${formatTimestamp(s.last_change.at, "short")}`}>
                        {lastChangeWords(s.last_change, data.me)}
                      </td>
                      <td style={{ padding: "4px 8px", position: "relative" }}>
                        <Button variant="ghost" size="xs" onClick={() => setSharing(sharing === s.id ? "" : s.id)}
                          aria-expanded={sharing === s.id}>
                          <Chip>{sharedWords(s)}</Chip>
                        </Button>
                        {sharing === s.id && <SharePop name={s.name} sheetId={s.id} me={data.me}
                          onDone={() => setSharing("")} onChanged={read} />}
                      </td>
                    </tr>
                  ))}
                  {notShared.map(s => (
                    <tr key={s.id} style={{ borderTop: "1px solid var(--b0)", height: 34 }}>
                      <td style={{ padding: "4px 8px" }}>
                        <span style={{ ...MUTED, display: "inline-flex", alignItems: "center", gap: 6, padding: "0 4px" }}>
                          <Icon name="lock" size={13} /> {s.name}
                        </span>
                      </td>
                      <td colSpan={4} style={{ padding: "4px 8px", ...MUTED, ...ONE_LINE, maxWidth: 640 }} title={s.withheld}>
                        {s.withheld}
                      </td>
                      <td style={{ padding: "4px 8px" }}><Chip>Not shared with you</Chip></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <Label right={data.uploads.length ? `${formatCount(data.uploads.length)} files` : undefined}>
              Files already uploaded here
            </Label>
            {data.uploads.length === 0 ? (
              <Empty>No file is uploaded to the Workspace yet.</Empty>
            ) : (
              <div style={{ display: "flex", flexDirection: "column" }}>
                {files.map(f => (
                  <div key={`${f.schema}/${f.file}`} style={{ display: "flex", alignItems: "center", gap: 10,
                    padding: "5px 0", borderTop: "1px solid var(--b0)" }}>
                    <span className="aug-mono aug-fs-sm" style={{ color: "var(--t1)", ...ONE_LINE }}>{f.file}</span>
                    <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, whiteSpace: "nowrap" }}>
                      {schemas.size > 1 ? `${f.schema} · ` : ""}{size(f.size)}
                    </span>
                    {(byFile.get(f.file) ?? []).slice(0, 2).map(made => (
                      <Button key={made.id} variant="ghost" size="xs" onClick={() => onOpen(made.id)}
                        title={`The sheet ${made.name} was made from this file`} style={MUTED}>
                        <Icon name="table" size={11} /> {made.name}
                      </Button>
                    ))}
                    <Button variant="outline" size="xs" style={{ marginLeft: "auto" }}
                      onClick={() => setStart({ source: "file", upload: { schema: f.schema, file: f.file } })}>
                      Make a sheet
                    </Button>
                  </div>
                ))}
                {data.uploads.length > 6 && (
                  <Button variant="ghost" size="xs" onClick={() => setMoreFiles(!moreFiles)} style={{ alignSelf: "flex-start" }}>
                    {moreFiles ? "Show fewer" : `+ ${formatCount(data.uploads.length - 6)} more files`}
                  </Button>
                )}
              </div>
            )}
          </section>
        </div>
      </div>
      {start && (
        <NewSheetDialog start={start} onClose={() => setStart(null)}
          onMade={ids => { setStart(null); read(); if (ids[0]) onOpen(ids[0]); }} />
      )}
      {chatting && (
        <NewSheetChat onClose={() => setChatting(false)} onMade={id => { setChatting(false); onOpen(id); }} />
      )}
    </div>
  );
}
