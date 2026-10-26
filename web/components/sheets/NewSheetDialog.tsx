"use client";

/**
 * New sheet (mockup screen 2): from a file, blank, or from a query's rows.
 *
 * A file is read as written before anything is made. Each column offers only the kinds every one of its values reads
 * back as — a zip code written 01037 is never offered as a Number — and says how many values are empty. An Excel
 * workbook becomes one sheet per tab, each named here. Nothing is kept until "Create".
 */
import { useEffect, useRef, useState } from "react";

import { Chip, MUTED, NUM } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { getConnections, type Connection } from "@/lib/api";
import { formatCount } from "@/lib/format";
import {
  KIND_LABEL, NEW_COLUMN_KINDS, createBlank, createFromFile, createFromRows, stageFile, stageUploaded, type Kind,
  type StagedFile,
} from "@/lib/sheets";

export type NewSheetStart =
  | { source: "file"; upload?: { schema: string; file: string } }
  | { source: "blank" }
  | { source: "rows"; connectionId?: string; sql?: string; schema?: string; name?: string };

type Source = "file" | "blank" | "rows";

function prettyName(file: string, tab: string): string {
  const stem = file.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").replace(/\s+dataset$/i, "").trim();
  const base = stem.replace(/\b\w/g, c => c.toUpperCase());
  return tab ? `${base} · ${tab}` : base;
}

export function NewSheetDialog({ start, onClose, onMade }: {
  start: NewSheetStart; onClose: () => void; onMade: (sheetIds: string[]) => void;
}) {
  const [source, setSource] = useState<Source>(start.source);
  const [staged, setStaged] = useState<StagedFile | null>(null);
  const [reading, setReading] = useState(false);
  const [names, setNames] = useState<Record<string, string>>({});
  const [kinds, setKinds] = useState<Record<string, Record<string, Kind>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [blankName, setBlankName] = useState("");
  const [blankCols, setBlankCols] = useState<{ name: string; kind: Kind }[]>([{ name: "Name", kind: "text" }]);
  const [rowsName, setRowsName] = useState(start.source === "rows" ? start.name ?? "" : "");
  const [rowsSql, setRowsSql] = useState(start.source === "rows" ? start.sql ?? "" : "");
  const [rowsConn, setRowsConn] = useState(start.source === "rows" ? start.connectionId ?? "" : "");
  const [rowsSchema, setRowsSchema] = useState(start.source === "rows" ? start.schema ?? "" : "");
  const [connections, setConnections] = useState<Connection[]>([]);
  const upload = start.source === "file" ? start.upload : undefined;

  const took = (f: StagedFile) => {
    setStaged(f);
    setNames(Object.fromEntries(f.tabs.map(t => [t.tab, prettyName(f.upload?.file ?? f.file, t.tab)])));
    setKinds(Object.fromEntries(f.tabs.map(t => [t.tab, Object.fromEntries(t.columns.map(c => [c.name, c.suggested]))])));
  };

  useEffect(() => {
    if (!upload) return;
    setReading(true);
    stageUploaded(upload.schema, upload.file).then(took)
      .catch(e => setError(e instanceof Error ? e.message : String(e))).finally(() => setReading(false));
  }, [upload]);

  useEffect(() => {
    if (source !== "rows") return;
    getConnections().then(cs => setConnections(cs)).catch(() => setConnections([]));
  }, [source]);

  const choose = (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setReading(true);
    stageFile(file).then(took).catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setReading(false));
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      let made;
      if (source === "file" && staged) {
        made = await createFromFile(staged.token, staged.tabs.map(t => ({ tab: t.tab, name: names[t.tab] ?? "",
          kinds: kinds[t.tab] ?? {} })), staged.upload ?? upload);
      } else if (source === "blank") {
        made = await createBlank(blankName, blankCols.filter(c => c.name.trim()));
      } else {
        made = await createFromRows(rowsName, rowsConn, rowsSql, rowsSchema);
      }
      onMade(made.sheets.map(s => s.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const canCreate = source === "file" ? !!staged && staged.tabs.every(t => (names[t.tab] ?? "").trim())
    : source === "blank" ? !!blankName.trim() : !!rowsName.trim() && !!rowsConn && !!rowsSql.trim();

  return (
    <Dialog open onOpenChange={o => { if (!o) onClose(); }}>
      <DialogContent maxWidth="860px" aria-describedby={undefined}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <DialogTitle>New sheet</DialogTitle>
          <Segmented label="Make it from" value={source} onChange={v => { setSource(v); setError(null); }}
            options={[{ value: "file", label: "From a file" }, { value: "blank", label: "Blank" },
              { value: "rows", label: "From a query" }]} />
        </div>

        {source === "file" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", border: "1px solid var(--b1)",
              borderRadius: "var(--r3)", background: "var(--bg-1)" }}>
              <Icon name="table" size={18} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>{staged ? (staged.upload?.file ?? staged.file) : reading ? "Reading the file…" : "No file chosen"}</div>
                {staged && (
                  <div className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>
                    {(staged.size / (1 << 20)).toFixed(1)} MB{staged.upload ? " · already uploaded to Workspace" : ""}
                    {staged.tabs.length === 1
                      ? ` · ${formatCount(staged.tabs[0].rows)} rows · ${staged.tabs[0].columns.length} columns`
                      : ` · ${staged.tabs.length} tabs`}
                  </div>
                )}
              </div>
              <input ref={fileRef} type="file" hidden accept=".csv,.tsv,.txt,.parquet,.json,.xlsx"
                onChange={e => choose(e.target.files?.[0])} />
              <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()} disabled={reading}>
                {staged ? "Choose another" : "Choose a file"}
              </Button>
            </div>
            <div className="aug-fs-xs" style={MUTED}>An Excel workbook becomes one sheet per tab; you name each.</div>
            {staged && staged.tabs.map(t => (
              <div key={t.tab || "file"} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <label className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ width: 90, ...MUTED }}>{t.tab ? `Tab ${t.tab}` : "Name"}</span>
                  <Input value={names[t.tab] ?? ""} onChange={e => setNames({ ...names, [t.tab]: e.target.value })}
                    aria-label={`Name of the sheet${t.tab ? ` from tab ${t.tab}` : ""}`} style={{ flex: 1 }} />
                  {t.tab && <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>{formatCount(t.rows)} rows</span>}
                </label>
                <div style={{ maxHeight: 320, overflowY: "auto", border: "1px solid var(--b0)", borderRadius: "var(--r2)" }}>
                  <table className="aug-fs-sm" style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr className="aug-fs-xs" style={{ ...MUTED, textAlign: "left", position: "sticky", top: 0,
                        background: "var(--bg-2)" }}>
                        <th style={{ padding: "5px 8px", fontWeight: 500 }}>Column</th>
                        <th style={{ padding: "5px 8px", fontWeight: 500 }}>Kind</th>
                        <th style={{ padding: "5px 8px", fontWeight: 500 }}>First row</th>
                        <th style={{ padding: "5px 8px", fontWeight: 500, textAlign: "right" }}>Empty</th>
                      </tr>
                    </thead>
                    <tbody>
                      {t.columns.map((c, at) => (
                        // a file's column is its place in the file
                        <tr key={at} style={{ borderTop: "1px solid var(--b0)", verticalAlign: "top" }}>
                          <td className="aug-mono" style={{ padding: "5px 8px" }}>{c.name}</td>
                          <td style={{ padding: "5px 8px", minWidth: 200 }}>
                            <Select value={kinds[t.tab]?.[c.name] ?? c.suggested}
                              onValueChange={v => setKinds({ ...kinds, [t.tab]: { ...kinds[t.tab], [c.name]: v as Kind } })}>
                              <SelectTrigger aria-label={`Kind of ${c.name}`} />
                              <SelectContent>
                                {c.offered.map(k => <SelectItem key={k} value={k}>{KIND_LABEL[k]}</SelectItem>)}
                              </SelectContent>
                            </Select>
                            {c.note && <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 4 }}>{c.note}</div>}
                            {(kinds[t.tab]?.[c.name] ?? c.suggested) === "choice" && c.values.length > 0 && (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                                {c.values.map(([v, n]) => <Chip key={v}>{v} · {formatCount(n)}</Chip>)}
                              </div>
                            )}
                          </td>
                          <td className="aug-mono aug-fs-xs" style={{ padding: "5px 8px", ...MUTED, maxWidth: 220,
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.first ?? "—"}</td>
                          <td style={{ padding: "5px 8px", textAlign: "right", ...NUM }}>{c.empty ? formatCount(c.empty) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
            {staged && (
              <div className="aug-fs-xs" style={{ ...MUTED, display: "flex", flexDirection: "column", gap: 4 }}>
                <span><b style={{ color: "var(--t2)" }}>A kind is offered only where every value reads back as written.</b> A
                  value that does not fit leaves its column Text, and is counted.</span>
                <span><b style={{ color: "var(--t2)" }}>Every value keeps its source:</b> this file and its row. Changes made
                  later keep who and when.</span>
              </div>
            )}
          </div>
        )}

        {source === "blank" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Input value={blankName} onChange={e => setBlankName(e.target.value)} placeholder="Name the sheet"
              aria-label="Name of the sheet" />
            {blankCols.map((c, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Input value={c.name} aria-label={`Column ${i + 1}`} placeholder="Column name" style={{ flex: 1 }}
                  onChange={e => setBlankCols(blankCols.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                <div style={{ width: 180 }}>
                  <Select value={c.kind} onValueChange={v => setBlankCols(blankCols.map((x, j) => (j === i ? { ...x, kind: v as Kind } : x)))}>
                    <SelectTrigger aria-label={`Kind of column ${i + 1}`} />
                    <SelectContent>{NEW_COLUMN_KINDS.map(k => <SelectItem key={k} value={k}>{KIND_LABEL[k]}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <Button variant="ghost" size="icon-sm" aria-label="Take this column off"
                  onClick={() => setBlankCols(blankCols.filter((_, j) => j !== i))} disabled={blankCols.length === 1}>
                  <Icon name="close" />
                </Button>
              </div>
            ))}
            <Button variant="outline" size="sm" style={{ alignSelf: "flex-start" }}
              onClick={() => setBlankCols([...blankCols, { name: "", kind: "text" }])}>
              <Icon name="plus" /> Column
            </Button>
          </div>
        )}

        {source === "rows" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Input value={rowsName} onChange={e => setRowsName(e.target.value)} placeholder="Name the sheet"
              aria-label="Name of the sheet" />
            <div style={{ display: "flex", gap: 8 }}>
              <div style={{ flex: 1 }}>
                <Select value={rowsConn} onValueChange={setRowsConn}>
                  <SelectTrigger aria-label="The connection the query runs on" placeholder="Connection" />
                  <SelectContent>{connections.map(c => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <Input value={rowsSchema} onChange={e => setRowsSchema(e.target.value)} placeholder="Schema (optional)"
                aria-label="Schema" style={{ width: 200 }} />
            </div>
            <Textarea value={rowsSql} onChange={e => setRowsSql(e.target.value)} rows={6} className="aug-mono"
              placeholder="SELECT … — run once more through the connection's checks, read-only; its rows are kept frozen"
              aria-label="The query" />
            <div className="aug-fs-xs" style={MUTED}>The query is saved beside the rows. A result over 200,000 rows keeps
              the first 200,000 and says so.</div>
          </div>
        )}

        {error && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>{error}</div>}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
          <span className="aug-fs-xs" style={MUTED}>Opens on its first view. Shared with everyone in Workspace.</span>
          <Button variant="ghost" onClick={onClose} style={{ marginLeft: "auto" }}>Cancel</Button>
          <Button onClick={create} disabled={!canCreate || busy}>
            {busy ? "Making…" : staged && staged.tabs.length > 1 ? `Create ${staged.tabs.length} sheets` : "Create sheet"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
