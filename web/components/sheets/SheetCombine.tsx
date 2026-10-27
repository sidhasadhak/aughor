"use client";

/**
 * Combining (SH-7; mockup screen 6): link a column to another sheet by a key, total another sheet's rows per key, add
 * a newer file to this sheet, keep a query's rows as a sheet.
 *
 * Every step is counted before anything is kept: a link says how many rows matched and how many missed; a total how
 * many rows have none (and show empty, never zero); a newer file every row it adds and every cell it changes, listed,
 * applied as one change that can be undone. A merge never removes a row.
 */
import { type ReactNode, useEffect, useRef, useState } from "react";

import { Chip, Label, MUTED, NUM } from "@/components/clarity/kit";
import { PANEL, PanelHead } from "@/components/sheets/SheetRecord";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { formatCount } from "@/lib/format";
import {
  applyMerge, keepLink, keepTotal, listSheets, previewLink, previewMerge, previewTotal, readSheet, showValue,
  stageFile, type LinkPreview, type MergePreview, type Sheet, type SheetSummary, type TotalPreview,
} from "@/lib/sheets";

const HOWS = ["sum", "count", "average", "min", "max", "earliest", "latest"];

function Pick({ value, onChange, items, label }: {
  value: string; onChange: (v: string) => void; items: { id: string; name: string }[]; label: string;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={label} placeholder={label} />
      <SelectContent>{items.map(i => <SelectItem key={i.id} value={i.id}>{i.name}</SelectItem>)}</SelectContent>
    </Select>
  );
}

/** What a step has kept, as the card it folds into: the thing kept, and its counts. */
function Kept({ title, lines }: { title: ReactNode; lines: ReactNode[] }) {
  return (
    <div className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 2, padding: "6px 8px",
      border: "1px solid var(--b0)", borderRadius: "var(--r2)", background: "var(--bg-1)" }}>
      <span>{title}</span>
      {lines.map((l, i) => (
        // the lines of one kept item, in their order
        <span key={i} className="aug-fs-xs" style={MUTED}>{l}</span>
      ))}
    </div>
  );
}

function Step({ n, title, done, children }: { n: number; title: string; done?: string; children: ReactNode }) {
  return (
    <section style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", background: "var(--bg-2)", padding: "10px 12px",
      display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="aug-fs-xs" style={{ width: 18, height: 18, borderRadius: "var(--r-pill)", background: "var(--bg-3)",
          display: "inline-flex", alignItems: "center", justifyContent: "center", ...NUM }}>{n}</span>
        <b className="aug-fs-sm">{title}</b>
        {done && <span style={{ marginLeft: "auto" }}><Chip tone="up">{done}</Chip></span>}
      </div>
      {children}
    </section>
  );
}

export function SheetCombine({ sheet, onClose, onChanged }: {
  sheet: Sheet; onClose: () => void; onChanged: (words: string) => void;
}) {
  const [others, setOthers] = useState<SheetSummary[]>([]);
  const [refused, setRefused] = useState<string | null>(null);
  useEffect(() => {
    listSheets().then(d => setOthers(d.sheets.filter(s => s.id !== sheet.id))).catch(() => setOthers([]));
  }, [sheet.id]);
  const stored = sheet.columns.filter(c => c.role === "stored");
  const fail = (e: unknown) => setRefused(e instanceof Error ? e.message : String(e));

  return (
    <aside aria-label="Combine" style={PANEL}>
      <PanelHead title="Combine" chip={sheet.name} onClose={onClose} />
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
        {refused && <span role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>{refused}</span>}
        <LinkStep sheet={sheet} stored={stored} others={others} onFail={fail} onKept={w => { setRefused(null); onChanged(w); }} />
        <TotalStep sheet={sheet} stored={stored} others={others} onFail={fail} onKept={w => { setRefused(null); onChanged(w); }} />
        <MergeStep sheet={sheet} stored={stored} onFail={fail} onKept={w => { setRefused(null); onChanged(w); }} />
        <Step n={4} title="Keep a query's rows as a new sheet">
          <span className="aug-fs-xs" style={MUTED}>From the SQL Editor&apos;s results, or New sheet ▸ From a query —
            frozen when kept, its query saved beside it.</span>
        </Step>
      </div>
    </aside>
  );
}

function useOther(id: string) {
  const [other, setOther] = useState<Sheet | null>(null);
  useEffect(() => {
    if (!id) { setOther(null); return; }
    readSheet(id).then(setOther).catch(() => setOther(null));
  }, [id]);
  return other;
}

function LinkStep({ sheet, stored, others, onFail, onKept }: {
  sheet: Sheet; stored: Sheet["columns"]; others: SheetSummary[]; onFail: (e: unknown) => void; onKept: (w: string) => void;
}) {
  const [column, setColumn] = useState("");
  const [otherId, setOtherId] = useState("");
  const [otherCol, setOtherCol] = useState("");
  const [seen, setSeen] = useState<LinkPreview | null>(null);
  const [bring, setBring] = useState<Set<string>>(new Set());
  const other = useOther(otherId);
  useEffect(() => { setSeen(null); }, [column, otherId, otherCol]);
  const links = sheet.columns.filter(c => c.kind === "link" && c.link);
  const [adding, setAdding] = useState(false);
  const form = links.length === 0 || adding;
  return (
    <Step n={1} title="Link a column to another sheet" done={links.length ? `${links.length} kept` : undefined}>
      {links.map(l => {
        const brought = sheet.columns.filter(c => c.role === "lookup" && c.via === l.id).map(c => c.name);
        return (
          <Kept key={l.id} title={<><b>{l.name}</b> → {others.find(o => o.id === l.link!.sheet)?.name ?? "a removed sheet"}</>}
            lines={[`${formatCount(l.link!.matched)} of ${formatCount(l.link!.matched + l.link!.missed)} rows matched · `
              + `${formatCount(l.link!.missed)} ${l.link!.missed === 1 ? "miss" : "misses"}`,
            ...(brought.length ? [`Brings in ${brought.join(", ")}`] : [])]} />
        );
      })}
      {!form && (
        <Button variant="ghost" size="xs" onClick={() => setAdding(true)} style={{ alignSelf: "flex-start" }}>
          <Icon name="plus" size={12} /> Link another column
        </Button>
      )}
      {form && <>
      <Pick value={column} onChange={setColumn} items={stored} label="This sheet's column" />
      <div style={{ display: "flex", gap: 6 }}>
        <div style={{ flex: 1 }}><Pick value={otherId} onChange={v => { setOtherId(v); setOtherCol(""); }} items={others} label="The other sheet" /></div>
        <div style={{ flex: 1 }}><Pick value={otherCol} onChange={setOtherCol}
          items={(other?.columns ?? []).filter(c => c.role === "stored")} label="Its key" /></div>
      </div>
      <Button variant="outline" size="xs" disabled={!column || !otherId || !otherCol} style={{ alignSelf: "flex-start" }}
        onClick={() => previewLink(sheet.id, column, otherId, otherCol).then(setSeen).catch(onFail)}>Count the matches</Button>
      {seen && (
        <div className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={NUM}><b>{formatCount(seen.matched)}</b> of {formatCount(seen.rows)} rows matched ·{" "}
            <b>{formatCount(seen.missed)}</b> {seen.missed === 1 ? "miss" : "misses"}{seen.empty ? ` · ${formatCount(seen.empty)} have no key` : ""}</span>
          {seen.some_misses.length > 0 && <span className="aug-fs-xs" style={MUTED}>Missed, e.g.: {seen.some_misses.join(", ")}</span>}
          {seen.other_repeats > 0 && (
            <span className="aug-fs-xs" style={{ color: "var(--amb4)" }}>{formatCount(seen.other_repeats)} keys repeat in {seen.other_name};
              a column read through the link needs one row per key — total its rows instead.</span>
          )}
          {seen.other_repeats === 0 && seen.can_bring.length > 0 && (
            <>
              <span className="aug-fs-xs" style={MUTED}>Bring in from {seen.other_name}:</span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px" }}>
                {seen.can_bring.map(c => (
                  <label key={c.id} className="aug-fs-xs" style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <Checkbox checked={bring.has(c.id)} aria-label={c.name}
                      onChange={() => { const b = new Set(bring); if (b.has(c.id)) b.delete(c.id); else b.add(c.id); setBring(b); }} />
                    {c.name}
                  </label>
                ))}
              </div>
            </>
          )}
          <Button size="xs" style={{ alignSelf: "flex-start" }}
            onClick={() => keepLink(sheet.id, column, otherId, otherCol, seen.other_repeats ? [] : [...bring])
              .then(() => { setSeen(null); setBring(new Set()); setAdding(false); onKept("Link kept"); }).catch(onFail)}>
            Keep the link{bring.size && !seen.other_repeats ? ` and ${bring.size} column${bring.size === 1 ? "" : "s"}` : ""}
          </Button>
        </div>
      )}
      </>}
    </Step>
  );
}

function TotalStep({ sheet, stored, others, onFail, onKept }: {
  sheet: Sheet; stored: Sheet["columns"]; others: SheetSummary[]; onFail: (e: unknown) => void; onKept: (w: string) => void;
}) {
  const [by, setBy] = useState("");
  const [otherId, setOtherId] = useState("");
  const [key, setKey] = useState("");
  const [how, setHow] = useState("sum");
  const [of, setOf] = useState("");
  const [name, setName] = useState("");
  const [seen, setSeen] = useState<TotalPreview | null>(null);
  const other = useOther(otherId);
  useEffect(() => { setSeen(null); }, [by, otherId, key, how, of]);
  const totals = sheet.columns.filter(c => c.role === "total");
  const ofCol = other?.columns.find(c => c.id === of);
  const [adding, setAdding] = useState(false);
  const form = totals.length === 0 || adding;
  return (
    <Step n={2} title="Total another sheet's rows per key" done={totals.length ? `${totals.length} kept` : undefined}>
      {totals.map(t => (
        <Kept key={t.id} title={<><b>{t.name}</b> · {t.how} of {others.find(o => o.id === t.sheet)?.name ?? "a removed sheet"}{" "}
          per {sheet.columns.find(c => c.id === t.by)?.name ?? t.by}</>}
          lines={t.description ? [t.description.charAt(0).toUpperCase() + t.description.slice(1)] : []} />
      ))}
      {!form && (
        <Button variant="ghost" size="xs" onClick={() => setAdding(true)} style={{ alignSelf: "flex-start" }}>
          <Icon name="plus" size={12} /> Another total
        </Button>
      )}
      {form && <>
      <div style={{ display: "flex", gap: 6 }}>
        <div style={{ flex: 1 }}><Pick value={otherId} onChange={v => { setOtherId(v); setKey(""); setOf(""); }} items={others} label="The other sheet" /></div>
        <div style={{ flex: 1 }}><Pick value={key} onChange={setKey} items={(other?.columns ?? []).filter(c => c.role === "stored")} label="Its key" /></div>
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <div style={{ width: 120 }}><Pick value={how} onChange={setHow} items={HOWS.map(h => ({ id: h, name: h }))} label="How" /></div>
        {how !== "count" && (
          <div style={{ flex: 1 }}><Pick value={of} onChange={setOf} items={(other?.columns ?? []).filter(c => c.role === "stored")} label="Of" /></div>
        )}
      </div>
      <Pick value={by} onChange={setBy} items={stored} label="Per this sheet's column" />
      <Button variant="outline" size="xs" disabled={!by || !otherId || !key || (how !== "count" && !of)} style={{ alignSelf: "flex-start" }}
        onClick={() => previewTotal(sheet.id, { by_column: by, other: otherId, other_key: key, how, of: how === "count" ? "" : of })
          .then(setSeen).catch(onFail)}>Count it</Button>
      {seen && (
        <div className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={NUM}><b>{formatCount(seen.rows_with)}</b> rows have rows in {seen.other_name} ·{" "}
            <b>{formatCount(seen.rows_without)}</b> have none, and show {how === "count" ? "0" : "empty, never zero"}</span>
          <span className="aug-fs-xs" style={MUTED}>{formatCount(seen.other_rows_counted)} rows of {seen.other_name} counted ·{" "}
            {formatCount(seen.other_rows_unmatched)} match no row here · the {how}:{" "}
            {ofCol ? showValue(seen.total, ofCol.kind === "money" ? ofCol : { ...ofCol, kind: "number" }) : String(seen.total ?? "—")}</span>
          <Input value={name} onChange={e => setName(e.target.value)} placeholder={`Name it — e.g. ${how === "count" ? "Payments" : "Paid"}`}
            aria-label="The total's name" />
          <Button size="xs" style={{ alignSelf: "flex-start" }}
            onClick={() => keepTotal(sheet.id, { by_column: by, other: otherId, other_key: key, how, of: how === "count" ? "" : of, name })
              .then(() => { setSeen(null); setName(""); setAdding(false); onKept("Total kept"); }).catch(onFail)}>Keep the total</Button>
        </div>
      )}
      </>}
    </Step>
  );
}

function MergeStep({ sheet, stored, onFail, onKept }: {
  sheet: Sheet; stored: Sheet["columns"]; onFail: (e: unknown) => void; onKept: (w: string) => void;
}) {
  const [token, setToken] = useState("");
  const [file, setFile] = useState("");
  const [key, setKey] = useState(sheet.key || "");
  const [seen, setSeen] = useState<MergePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  const nameOf = (id: string) => sheet.columns.find(c => c.id === id)?.name ?? id;
  return (
    <Step n={3} title="Add a newer file to this sheet">
      <span className="aug-fs-xs" style={MUTED}>Rows are matched on a key; every row added and every cell changed is shown
        before it is applied, as one change you can undo. A merge never removes a row.</span>
      <input ref={ref} type="file" hidden accept=".csv,.tsv,.parquet,.json,.xlsx" onChange={e => {
        const f = e.target.files?.[0];
        if (!f) return;
        setBusy(true);
        stageFile(f).then(st => { setToken(st.token); setFile(f.name); setSeen(null); }).catch(onFail).finally(() => setBusy(false));
      }} />
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <Button variant="outline" size="xs" onClick={() => ref.current?.click()} disabled={busy}>
          <Icon name="upload" /> {file || "Choose a file…"}
        </Button>
        <div style={{ flex: 1 }}><Pick value={key} onChange={setKey} items={stored} label="Match rows on" /></div>
      </div>
      <Button variant="outline" size="xs" disabled={!token || !key || busy} style={{ alignSelf: "flex-start" }}
        onClick={() => { setBusy(true); previewMerge(sheet.id, token, key).then(setSeen).catch(onFail).finally(() => setBusy(false)); }}>
        Compare with the sheet
      </Button>
      {seen && (
        <div className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={NUM}><b>{formatCount(seen.rows_added)}</b> rows added · <b>{formatCount(seen.cells_changed)}</b> cells changed in{" "}
            {formatCount(seen.rows_changed)} rows · {formatCount(seen.kept_as_is)} rows not in the file, kept as they are</span>
          {seen.misfit > 0 && <span className="aug-fs-xs" style={{ color: "var(--amb4)" }}>{formatCount(seen.misfit)} values in the file do not
            read as their column&apos;s kind and are left as they were.</span>}
          {seen.file_columns_not_in_sheet.length > 0 && <span className="aug-fs-xs" style={MUTED}>Not in the sheet, not added:{" "}
            {seen.file_columns_not_in_sheet.join(", ")}</span>}
          {seen.changes.length > 0 && (
            <div className="aug-fs-xs" style={{ maxHeight: 180, overflowY: "auto", border: "1px solid var(--b0)", borderRadius: "var(--r2)" }}>
              {seen.changes.map(c => (
                <div key={`${c.row}-${c.column}`} style={{ padding: "3px 6px", borderBottom: "1px solid var(--b0)" }}>
                  <span style={MUTED}>{seen.key ? nameOf(seen.key) : "key"} {c.key} · {c.name}:</span>{" "}
                  <s style={MUTED}>{String(c.old ?? "empty")}</s> → <b>{String(c.new ?? "empty")}</b>
                </div>
              ))}
              {seen.cells_changed > seen.changes.length && (
                <div style={{ padding: "3px 6px", ...MUTED }}>+ {formatCount(seen.cells_changed - seen.changes.length)} more cells</div>
              )}
            </div>
          )}
          <Label>Applied as one change</Label>
          <Button size="xs" disabled={busy || (seen.rows_added + seen.cells_changed === 0)} style={{ alignSelf: "flex-start" }}
            onClick={() => { setBusy(true); applyMerge(sheet.id, token, key, seen.basis)
              .then(r => { setSeen(null); setToken(""); setFile(""); onKept(`${formatCount(r.cells_changed)} cells changed, ${formatCount(r.rows_added)} rows added`); })
              .catch(onFail).finally(() => setBusy(false)); }}>
            {seen.rows_added + seen.cells_changed === 0 ? "Nothing to change" : "Apply the file"}
          </Button>
        </div>
      )}
    </Step>
  );
}
