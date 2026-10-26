"use client";

/**
 * A row opened as a record (mockup screen 10), and the sheet's history.
 *
 * The record holds every field with where its value came from — the file's row, who set it, the expression it is
 * computed from, the sheet it is read from — the rows of other sheets it links to and that link to it, its history,
 * and its comments. A comment is kept in the Record as a said claim in its author's name, readable by whoever can
 * read the row; it is never a value of the sheet.
 */
import { type CSSProperties, useCallback, useEffect, useState } from "react";

import { Label, MUTED, NUM } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Loading, ReadFailed } from "@/components/ui/states";
import { formatCount, formatTimestamp } from "@/lib/format";
import {
  comment, readChanges, readRecord, showValue, who, type ChangeRow, type Sheet, type SheetRecord,
} from "@/lib/sheets";

export const PANEL_WIDTH = 420;

export const PANEL: CSSProperties = {
  width: PANEL_WIDTH, flex: "0 0 auto", display: "flex", flexDirection: "column", minHeight: 0,
  borderLeft: "1px solid var(--b1)", background: "var(--bg-1)",
};

export function PanelHead({ title, chip, onClose }: { title: string; chip?: string; onClose: () => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderBottom: "1px solid var(--b1)",
      flex: "0 0 auto" }}>
      <span className="aug-label">{title}</span>
      {chip && <span className="aug-fs-xs" style={{ ...MUTED, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{chip}</span>}
      <Button variant="ghost" size="icon-xs" aria-label="Close" onClick={onClose} style={{ marginLeft: "auto" }}>
        <Icon name="close" size={12} />
      </Button>
    </div>
  );
}

type Tab = "fields" | "linked" | "history" | "comments";

export function SheetRecordPanel({ sheet, row, editable, onClose, onOpenSheet }: {
  sheet: Sheet; row: number; editable: boolean; onClose: () => void; onOpenSheet: (id: string) => void;
}) {
  const [rec, setRec] = useState<SheetRecord | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("fields");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);

  const read = useCallback(() => {
    readRecord(sheet.id, row).then(r => { setRec(r); setFailed(null); })
      .catch(e => setFailed(e instanceof Error ? e.message : String(e)));
  }, [sheet.id, row]);
  useEffect(() => { read(); }, [read]);

  const send = async () => {
    if (!draft.trim()) return;
    setSending(true);
    setRefused(null);
    try {
      await comment(sheet.id, row, draft);
      setDraft("");
      read();
    } catch (e) {
      setRefused(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  };

  const linked = rec?.linked.reduce((n, l) => n + l.count, 0) ?? 0;
  return (
    <aside aria-label={`Row ${row} of ${sheet.name}`} style={PANEL}>
      <PanelHead title={`Row ${formatCount(row)}`} chip={rec?.came_from} onClose={onClose} />
      <div role="tablist" style={{ display: "flex", gap: 2, padding: "0 10px", borderBottom: "1px solid var(--b0)" }}>
        {([["fields", "Fields"], ["linked", `Linked · ${linked}`], ["history", "History"],
          ["comments", `Comments${rec?.comments.length ? ` · ${rec.comments.length}` : ""}`]] as [Tab, string][]).map(([t, label]) => (
          <Button key={t} role="tab" aria-selected={tab === t} variant="ghost" size="sm" onClick={() => setTab(t)}
            style={{ borderRadius: 0, borderBottom: tab === t ? "2px solid var(--blue3)" : "2px solid transparent" }}>{label}</Button>
        ))}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "10px 14px" }}>
        {failed ? <ReadFailed what="the row" error={failed} onRetry={read} /> : !rec ? <Loading what="the row" /> : (
          <>
            {tab === "fields" && rec.fields.map(f => {
              const col = sheet.columns.find(c => c.id === f.column);
              return (
                <div key={f.column} title={f.description || undefined} style={{ display: "grid",
                  gridTemplateColumns: "140px 1fr", gap: 8, padding: "6px 0", borderBottom: "1px solid var(--b0)" }}>
                  <span className="aug-mono aug-fs-xs" style={{ ...MUTED, overflow: "hidden", textOverflow: "ellipsis" }}>{f.name}</span>
                  <span className="aug-fs-sm" style={{ minWidth: 0 }}>
                    <span style={{ display: "block", overflowWrap: "anywhere" }}>
                      {f.value === null || f.value === undefined || f.value === "" ? <span style={MUTED}>empty</span>
                        : col ? showValue(f.value, col) : String(f.value)}
                    </span>
                    <span className="aug-fs-xs" style={MUTED}>{f.source}</span>
                  </span>
                </div>
              );
            })}
            {tab === "linked" && (rec.linked.length === 0 ? (
              <div className="aug-fs-xs" style={MUTED}>This sheet links to no other sheet, and none links to it.
                Links are made in Combine.</div>
            ) : rec.linked.map(l => (
              <section key={`${l.sheet}-${l.through}-${l.direction}`} style={{ marginBottom: 14 }}>
                <Label right={<Button variant="ghost" size="xs" onClick={() => onOpenSheet(l.sheet)}>Open {l.name}</Button>}>
                  {l.direction === "to" ? `${l.through} → ${l.name}` : `${l.name} · by ${l.through}`} · {formatCount(l.count)}
                </Label>
                {l.rows.length === 0 ? <div className="aug-fs-xs" style={MUTED}>No row matches.</div> : l.rows.map(r => (
                  <div key={r.row} className="aug-fs-xs" style={{ padding: "4px 0", borderBottom: "1px solid var(--b0)",
                    display: "flex", flexWrap: "wrap", gap: "2px 10px" }}>
                    <span style={{ ...MUTED, ...NUM }}>row {formatCount(r.row)}</span>
                    {r.values.map((v, i) => v === null || v === "" ? null : (
                      <span key={l.columns[i] ?? i}><span style={MUTED}>{l.columns[i]}:</span> {String(v)}</span>
                    ))}
                  </div>
                ))}
                {l.count > l.rows.length && <div className="aug-fs-xs" style={MUTED}>+ {formatCount(l.count - l.rows.length)} more</div>}
              </section>
            )))}
            {tab === "history" && (
              <div className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span style={MUTED}>{rec.came_from.replace(/^imported/, "Imported")}{rec.history.length ? "" : " · not changed since."}</span>
                {rec.history.map(h => (
                  <span key={`${h.at}-${h.column}-${h.event}`} className="aug-fs-xs">
                    {h.column ? <b>{h.column}</b> : "the row"}{" "}
                    {h.event === "set" ? (h.column ? `set to ${String(h.value ?? "empty")}` : String(h.value ?? "")) : "back to its source's value"}
                    {" "}· {who(h.by)} · {formatTimestamp(h.at, "short")}
                    {h.origin.startsWith("proposal:") && " · proposed by the assistant"}
                  </span>
                ))}
              </div>
            )}
            {tab === "comments" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {rec.comments.length === 0 && (
                  <div className="aug-fs-xs" style={MUTED}>No comments yet. A comment is kept in the Record, in your name,
                    readable by whoever can read this row.</div>
                )}
                {rec.comments.map(c => (
                  <div key={c.id || c.at} className="aug-fs-sm" style={{ padding: "6px 0", borderBottom: "1px solid var(--b0)" }}>
                    <div>{c.text}</div>
                    <div className="aug-fs-xs" style={MUTED}>{who(c.by)} · {formatTimestamp(c.at, "short")} · a said claim in the Record</div>
                  </div>
                ))}
                {editable && (
                  <div style={{ display: "flex", gap: 6 }}>
                    <Input value={draft} onChange={e => setDraft(e.target.value)} placeholder="Write a comment…"
                      aria-label="Comment" style={{ flex: 1 }}
                      onKeyDown={e => { if (e.key === "Enter") void send(); }} />
                    <Button size="sm" onClick={() => void send()} disabled={sending || !draft.trim()}>Keep</Button>
                  </div>
                )}
                {refused && <span role="alert" className="aug-fs-xs" style={{ color: "var(--red4)" }}>{refused}</span>}
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

/** Every change to the sheet, newest first: what it was, who made it, what made it — and undo for the latest. */
export function SheetHistory({ sheet, tick, onClose, onUndo }: {
  sheet: Sheet; tick: number; onClose: () => void; onUndo: () => void;
}) {
  const [rows, setRows] = useState<{ changes: ChangeRow[]; can_undo: string } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const read = useCallback(() => {
    readChanges(sheet.id).then(r => { setRows(r); setFailed(null); })
      .catch(e => setFailed(e instanceof Error ? e.message : String(e)));
  }, [sheet.id]);
  useEffect(() => { read(); }, [read, tick]);
  return (
    <aside aria-label={`History of ${sheet.name}`} style={PANEL}>
      <PanelHead title="History" chip={rows ? `${formatCount(rows.changes.length)} changes` : undefined} onClose={onClose} />
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "10px 14px" }}>
        {failed ? <ReadFailed what="the history" error={failed} onRetry={read} /> : !rows ? <Loading what="the history" /> : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {rows.can_undo && (
              <Button variant="outline" size="xs" onClick={onUndo} style={{ alignSelf: "flex-start", marginBottom: 8 }}>
                Undo your last: {rows.can_undo.slice(0, 50)}
              </Button>
            )}
            {rows.changes.map(c => (
              <div key={c.id} className="aug-fs-sm" style={{ padding: "6px 0", borderBottom: "1px solid var(--b0)" }}>
                <div>{c.what}</div>
                <div className="aug-fs-xs" style={MUTED}>
                  {who(c.by)} · {formatTimestamp(c.at, "short")}
                  {c.origin.startsWith("proposal:") && " · proposed by the assistant, applied by them"}
                  {c.origin.startsWith("undo:") && " · an undo"}
                  {c.origin.startsWith("redo:") && " · a redo"}
                  {c.origin === "merge" && " · a newer file"}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
