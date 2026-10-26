"use client";

/**
 * A sheet open (mockup screens 3 to 6 and 10): its bar — where it came from, its rows and columns, its last change with
 * undo, who it is shared with — its views as tabs, the toolbar (a row, the fields, a filter, a sort, a group, combine,
 * search, undo and redo, the history, copy and CSV), the grid, and beside it the chat, the combining tools, a row's
 * record or the history.
 *
 * A view's filter, sort and hidden columns are read from the view; changing them here is the person's own until they
 * keep it as a view — shared with everyone who reads the sheet.
 */
import { type CSSProperties, type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import { Chip, MUTED, NUM } from "@/components/clarity/kit";
import { SheetChat } from "@/components/sheets/SheetChat";
import { SheetCombine } from "@/components/sheets/SheetCombine";
import { SheetGrid, type EditResult } from "@/components/sheets/SheetGrid";
import { SheetHistory, SheetRecordPanel } from "@/components/sheets/SheetRecord";
import { SharePop } from "@/components/sheets/SheetsHome";
import type { SheetsWaves } from "@/components/sheets/SpreadsheetsPage";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { Loading, ReadFailed } from "@/components/ui/states";
import { formatCount } from "@/lib/format";
import {
  KIND_LABEL, NEW_COLUMN_KINDS, addColumn, addRow, csvUrl, filterWords, opWords, opsFor, readChanges, readRows,
  readSheet, redo, removeColumn, renameSheet, saveView, setCells, showValue, undo, updateColumn, viewCount,
  type Condition, type Kind, type RowsPage, type Sheet, type SheetColumn,
} from "@/lib/sheets";

const PAGE = 500;

const BAR: CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, padding: "8px 16px", borderBottom: "1px solid var(--b1)",
  background: "var(--bg-1)", flexWrap: "wrap",
};

type Panel = "" | "chat" | "combine" | "record" | "history";
type Pop = "" | "fields" | "filter" | "sort" | "group" | "share" | "view";

interface Query {
  view: string;
  filter: Condition[];
  sort: { column: string; desc: boolean }[];
  search: string;
  group: string;
  hidden: string[];
}

function fromView(sheet: Sheet, viewId: string): Query {
  const v = sheet.views.find(x => x.id === viewId) ?? sheet.views[0];
  return {
    view: v?.id ?? "", filter: v?.filter ?? [], sort: v?.sort ?? [], search: v?.search ?? "", group: "",
    hidden: [...(v?.hidden ?? []), ...sheet.columns.filter(c => c.hidden).map(c => c.id)],
  };
}

function sameAsView(sheet: Sheet, q: Query): boolean {
  const v = sheet.views.find(x => x.id === q.view);
  if (!v) return false;
  return JSON.stringify(v.filter) === JSON.stringify(q.filter) && JSON.stringify(v.sort) === JSON.stringify(q.sort)
    && v.search === q.search && JSON.stringify([...v.hidden].sort())
      === JSON.stringify(q.hidden.filter(h => !sheet.columns.find(c => c.id === h)?.hidden).sort());
}

export function SheetView({ sheetId, waves, onBack, onOpen, onAsk }: {
  sheetId: string; waves: SheetsWaves; onBack: () => void; onOpen: (id: string) => void;
  onAsk?: (question: string) => void;
}) {
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [query, setQuery] = useState<Query | null>(null);
  const [page, setPage] = useState<RowsPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [rowsFailed, setRowsFailed] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>(waves.chat ? "chat" : "");
  const [pop, setPop] = useState<Pop>("");
  const [recordRow, setRecordRow] = useState<number | null>(null);
  const [said, setSaid] = useState<{ text: string; tone: "ok" | "bad" } | null>(null);
  const [history, setHistory] = useState<{ can_undo: string; can_redo: string } | null>(null);
  const [tick, setTick] = useState(0);
  const [renaming, setRenaming] = useState<string | null>(null);

  const readDefinition = useCallback(() => readSheet(sheetId).then(s => {
    setSheet(s);
    setFailed(null);
    setQuery(q => q ?? fromView(s, s.views[0]?.id ?? ""));
    return s;
  }).catch(e => { setFailed(e instanceof Error ? e.message : String(e)); return null; }), [sheetId]);

  useEffect(() => { void readDefinition(); }, [readDefinition]);

  const readUndo = useCallback(() => {
    if (!waves.grid) return;
    readChanges(sheetId).then(h => setHistory({ can_undo: h.can_undo, can_redo: h.can_redo })).catch(() => setHistory(null));
  }, [sheetId, waves.grid]);
  useEffect(() => { readUndo(); }, [readUndo, tick]);

  useEffect(() => {
    if (!sheet || !query) return;
    let live = true;
    readRows(sheet.id, { filter: query.filter, sort: query.sort, search: query.search, group: query.group, offset,
      limit: PAGE })
      .then(p => { if (live) { setPage(p); setRowsFailed(null); } })
      .catch(e => { if (live) setRowsFailed(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [sheet, query, offset, tick]);

  /** After any change: the definition and the rows again, and what undo would take back. */
  const changed = useCallback(async (words?: string) => {
    await readDefinition();
    setTick(t => t + 1);
    if (words) setSaid({ text: words, tone: "ok" });
  }, [readDefinition]);

  const run = useCallback(async (what: () => Promise<unknown>, words?: string) => {
    try {
      await what();
      await changed(words);
      return true;
    } catch (e) {
      setSaid({ text: e instanceof Error ? e.message : String(e), tone: "bad" });
      return false;
    }
  }, [changed]);

  const onEdit = useCallback(async (row: number, c: SheetColumn, value: unknown, version: number): Promise<EditResult> => {
    if (!sheet) return { ok: false };
    try {
      await setCells(sheet.id, [{ row, column: c.id, value, version }]);
      setTick(t => t + 1);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  }, [sheet]);

  const hidden = useMemo(() => new Set(query?.hidden ?? []), [query]);

  if (failed) return <ReadFailed what="the sheet" error={failed} onRetry={() => void readDefinition()} />;
  if (!sheet || !query) return <Loading what="the sheet" />;

  const setQ = (q: Partial<Query>) => { setOffset(0); setQuery({ ...query, ...q }); };
  const dirty = !sameAsView(sheet, query);
  const view = sheet.views.find(v => v.id === query.view);
  const all = page ? Number(sheet.rows ?? 0) : 0;

  const copyPage = () => {
    if (!page) return;
    const shown = sheet.columns.filter(c => !hidden.has(c.id));
    const idx = Object.fromEntries(page.columns.map((id, i) => [id, i + 1]));
    const lines = [shown.map(c => c.name).join("\t"),
      ...page.rows.map(r => shown.map(c => showValue(r[idx[c.id]], c)).join("\t"))];
    void navigator.clipboard?.writeText(lines.join("\n"));
    setSaid({ text: `Copied ${formatCount(page.rows.length)} rows`, tone: "ok" });
  };

  const keepAsView = async (name: string) => {
    if (!name.trim()) return;
    const ok = await run(() => saveView(sheet.id, { name, filter: query.filter, sort: query.sort, search: query.search,
      hidden: query.hidden.filter(h => !sheet.columns.find(c => c.id === h)?.hidden) }), `View ${name} kept`);
    if (ok) {
      const s = await readSheet(sheet.id);
      const made = s.views[s.views.length - 1];
      if (made) setQuery({ ...fromView(s, made.id), group: query.group });
    }
  };

  const updateThisView = () => view && run(() => saveView(sheet.id, { ...view, filter: query.filter, sort: query.sort,
    search: query.search, hidden: query.hidden.filter(h => !sheet.columns.find(c => c.id === h)?.hidden) }),
  `View ${view.name} changed`);

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", background: "var(--bg-0)" }}>
        {/* the sheet's bar */}
        <div style={BAR}>
          <Button variant="ghost" size="sm" onClick={onBack} style={{ ...MUTED, padding: "0 4px" }}>Spreadsheets /</Button>
          {renaming !== null ? (
            <Input value={renaming} autoFocus aria-label="The sheet's name" style={{ width: 240 }}
              onChange={e => setRenaming(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter") { const n = renaming; setRenaming(null); void run(() => renameSheet(sheet.id, n), "Renamed"); }
                if (e.key === "Escape") setRenaming(null);
              }} onBlur={() => setRenaming(null)} />
          ) : (
            <Button variant="ghost" size="sm" disabled={!waves.grid} title={waves.grid ? "Rename" : undefined}
              onClick={() => setRenaming(sheet.name)} style={{ fontWeight: 600, color: "var(--t1)", padding: "0 4px" }}>
              {sheet.name}
            </Button>
          )}
          <Chip title={sheet.source.sql || undefined}>{sheet.came_from}</Chip>
          {history?.can_undo && (
            <Chip tone="accent" title={`Undo: ${history.can_undo}`}>
              last: {history.can_undo.slice(0, 48)}
            </Chip>
          )}
          <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>
            {formatCount(page?.total ?? 0)}{page && page.total !== all ? ` of ${formatCount(all)}` : ""} rows · {sheet.columns.length} columns
          </span>
          <span style={{ marginLeft: "auto", display: "flex", gap: 6, position: "relative" }}>
            <Button variant="outline" size="sm" onClick={() => setPop(pop === "share" ? "" : "share")}>Share · Workspace</Button>
            {pop === "share" && <SharePop name={sheet.name} sheetId={sheet.id} onDone={() => setPop("")} />}
            {waves.combine && (
              <Button variant={panel === "combine" ? "secondary" : "outline"} size="sm"
                onClick={() => setPanel(panel === "combine" ? "" : "combine")}><Icon name="link" /> Combine</Button>
            )}
            {waves.chat && (
              <Button variant={panel === "chat" ? "secondary" : "outline"} size="sm"
                onClick={() => setPanel(panel === "chat" ? "" : "chat")}><Icon name="chat" /> Chat</Button>
            )}
          </span>
        </div>

        {/* the views */}
        <div role="tablist" aria-label="Views" style={{ ...BAR, gap: 2, padding: "0 12px", background: "var(--bg-0)" }}>
          {sheet.views.map(v => (
            <Button key={v.id} role="tab" aria-selected={v.id === query.view} variant="ghost" size="sm"
              onClick={() => { setOffset(0); setQuery(fromView(sheet, v.id)); }}
              style={{ borderBottom: v.id === query.view ? "2px solid var(--blue3)" : "2px solid transparent",
                borderRadius: 0, color: v.id === query.view ? "var(--t1)" : "var(--t2)", height: 34 }}>
              <Icon name="table" size={12} /> {v.name}
              {v.made_by && <Chip tone="violet" title="Proposed by the assistant, applied by a person">proposed</Chip>}
            </Button>
          ))}
          {waves.grid && (
            <span style={{ position: "relative" }}>
              <Button variant="ghost" size="sm" onClick={() => setPop(pop === "view" ? "" : "view")} style={{ ...MUTED, height: 34 }}>
                <Icon name="plus" size={12} /> View
              </Button>
              {pop === "view" && (
                <NamePop label="Keep what is shown — its filter, sort and hidden columns — as a view everyone who reads the sheet sees"
                  initial={view && !dirty ? `${view.name} 2` : "New view"} onClose={() => setPop("")}
                  onKeep={name => { setPop(""); void keepAsView(name); }} />
              )}
            </span>
          )}
          {dirty && waves.grid && (
            <span className="aug-fs-xs" style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center", ...MUTED }}>
              changed here, not kept
              {view && <Button variant="outline" size="xs" onClick={() => void updateThisView()}>Keep in {view.name}</Button>}
              <Button variant="ghost" size="xs" onClick={() => setQuery({ ...fromView(sheet, query.view), group: query.group })}>
                Back to the view
              </Button>
            </span>
          )}
        </div>

        {/* the toolbar */}
        <div style={{ ...BAR, gap: 4, background: "var(--bg-0)", position: "relative" }}>
          {waves.grid && (
            <Button variant="ghost" size="sm" onClick={() => void run(async () => {
              const r = await addRow(sheet.id);
              setSaid({ text: `Row ${r.row} added`, tone: "ok" });
            })}><Icon name="plus" /> Row</Button>
          )}
          <ToolButton on={hidden.size > 0} onClick={() => setPop(pop === "fields" ? "" : "fields")} icon="column"
            label={hidden.size ? `Fields · ${hidden.size} hidden` : "Fields"} />
          <ToolButton on={query.filter.length > 0} onClick={() => setPop(pop === "filter" ? "" : "filter")} icon="filter"
            label={query.filter.length ? `Filter · ${query.filter.length}` : "Filter"} />
          <ToolButton on={query.sort.length > 0} onClick={() => setPop(pop === "sort" ? "" : "sort")} icon="sliders"
            label={query.sort.length ? `Sort · ${query.sort.length}` : "Sort"} />
          <ToolButton on={!!query.group} onClick={() => setPop(pop === "group" ? "" : "group")} icon="list"
            label={query.group ? `Group · ${sheet.columns.find(c => c.id === query.group)?.name ?? ""}` : "Group"} />
          <div style={{ width: 220, marginLeft: 8 }}>
            <Input value={query.search} placeholder="Search this sheet" aria-label="Search this sheet"
              onChange={e => setQ({ search: e.target.value })} />
          </div>
          <span style={{ marginLeft: "auto", display: "flex", gap: 2 }}>
            {waves.grid && (
              <>
                <Button variant="ghost" size="icon-sm" aria-label="Undo" title={history?.can_undo ? `Undo: ${history.can_undo}` : "Nothing to undo"}
                  disabled={!history?.can_undo} onClick={() => void run(() => undo(sheet.id), "Undone")}>
                  <Icon name="back" />
                </Button>
                <Button variant="ghost" size="icon-sm" aria-label="Redo" title={history?.can_redo ? `Redo: ${history.can_redo}` : "Nothing to redo"}
                  disabled={!history?.can_redo} onClick={() => void run(() => redo(sheet.id), "Redone")}>
                  <Icon name="next" />
                </Button>
                <Button variant={panel === "history" ? "secondary" : "ghost"} size="sm"
                  onClick={() => setPanel(panel === "history" ? "" : "history")}><Icon name="history" /> History</Button>
              </>
            )}
            <Button variant="ghost" size="sm" onClick={copyPage}><Icon name="copy" /> Copy</Button>
            <Button variant="ghost" size="sm" onClick={() => window.open(csvUrl(sheet.id, {
              filter: query.filter, sort: query.sort, search: query.search, view: query.view }), "_blank")}>
              <Icon name="download" /> CSV
            </Button>
          </span>
          {pop === "fields" && (
            <FieldsPop sheet={sheet} hidden={hidden} editable={waves.grid}
              onHidden={h => setQ({ hidden: h })} onClose={() => setPop("")}
              run={run} />
          )}
          {pop === "filter" && (
            <FilterPop sheet={sheet} conditions={query.filter} onApply={f => { setQ({ filter: f }); setPop(""); }}
              onClose={() => setPop("")} />
          )}
          {pop === "sort" && (
            <SortPop sheet={sheet} sort={query.sort} onApply={s => { setQ({ sort: s }); setPop(""); }} onClose={() => setPop("")} />
          )}
          {pop === "group" && (
            <Popover onClose={() => setPop("")} left={340}>
              <span className="aug-fs-xs" style={MUTED}>Group the rows by</span>
              <Select value={query.group} onValueChange={g => { setQ({ group: g }); setPop(""); }}
                items={{ "": "No grouping", ...Object.fromEntries(sheet.columns.map(c => [c.id, c.name])) }}>
                <SelectTrigger aria-label="Group by" />
                <SelectContent>
                  <SelectItem value="">No grouping</SelectItem>
                  {sheet.columns.map(c => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </Popover>
          )}
        </div>
        {(query.filter.length > 0 || said) && (
          <div className="aug-fs-xs" style={{ padding: "4px 16px", display: "flex", gap: 10, borderBottom: "1px solid var(--b0)",
            ...MUTED }}>
            {query.filter.length > 0 && <span>Filter: {filterWords(query.filter, sheet.columns)}</span>}
            {said && (
              <span role={said.tone === "bad" ? "alert" : "status"} style={{ marginLeft: "auto",
                color: said.tone === "bad" ? "var(--red4)" : "var(--grn4)" }}>
                {said.text}
                <Button variant="ghost" size="icon-xs" aria-label="Dismiss" onClick={() => setSaid(null)}><Icon name="close" size={11} /></Button>
              </span>
            )}
          </div>
        )}

        {rowsFailed ? <ReadFailed what="the rows" error={rowsFailed} onRetry={() => setTick(t => t + 1)} />
          : !page ? <Loading what="the rows" /> : (
            <SheetGrid sheet={sheet} page={page} hidden={hidden} editable={waves.grid} groupBy={query.group}
              onEdit={onEdit} rowStart={offset}
              onOpenRow={row => { setRecordRow(row); setPanel("record"); }} />
          )}
        {page && page.total > PAGE && (
          <div className="aug-fs-xs" style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 12px",
            background: "var(--bg-1)", ...MUTED }}>
            <Button variant="outline" size="xs" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Previous {formatCount(PAGE)}
            </Button>
            <Button variant="outline" size="xs" disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>
              Next {formatCount(PAGE)}
            </Button>
            <span>{viewCount(page.total, all)}{view ? ` · ${view.name}` : ""}{query.sort.length ? "" : " · in the sheet's order"}</span>
          </div>
        )}
      </div>

      {panel === "chat" && waves.chat && (
        <SheetChat sheet={sheet} viewId={query.view} viewRows={page?.total ?? null} onClose={() => setPanel("")}
          onApplied={() => void changed("Applied")} onOpenSheet={onOpen} onAsk={onAsk}
          onOpenView={name => { setOffset(0); readSheet(sheet.id).then(s => {
            setSheet(s);
            const v = [...s.views].reverse().find(x => x.name === name);
            if (v) setQuery(fromView(s, v.id));
          }); }} />
      )}
      {panel === "combine" && waves.combine && (
        <SheetCombine sheet={sheet} onClose={() => setPanel("")} onChanged={words => void changed(words)} />
      )}
      {panel === "record" && recordRow !== null && (
        <SheetRecordPanel sheet={sheet} row={recordRow} editable={waves.grid} onClose={() => setPanel("")}
          onOpenSheet={onOpen} />
      )}
      {panel === "history" && waves.grid && (
        <SheetHistory sheet={sheet} tick={tick} onClose={() => setPanel("")}
          onUndo={() => void run(() => undo(sheet.id), "Undone")} />
      )}
    </div>
  );
}

function ToolButton({ on, onClick, icon, label }: { on: boolean; onClick: () => void; icon: "column" | "filter" | "sliders" | "list"; label: string }) {
  return (
    <Button variant={on ? "secondary" : "ghost"} size="sm" onClick={onClick}>
      <Icon name={icon} /> {label}
    </Button>
  );
}

export function Popover({ children, onClose, left = 0, width = 360 }: {
  children: ReactNode; onClose: () => void; left?: number; width?: number;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div role="dialog" className="aug-fs-sm" style={{ position: "absolute", top: "100%", left, zIndex: 30, width,
      background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "10px 12px",
      display: "flex", flexDirection: "column", gap: 8 }}>
      {children}
      <Button variant="ghost" size="xs" onClick={onClose} style={{ alignSelf: "flex-end" }}>Close</Button>
    </div>
  );
}

function FieldsPop({ sheet, hidden, editable, onHidden, onClose, run }: {
  sheet: Sheet; hidden: Set<string>; editable: boolean; onHidden: (h: string[]) => void; onClose: () => void;
  run: (what: () => Promise<unknown>, words?: string) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState<string>("");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [kind, setKind] = useState<Kind>("text");
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState<Kind>("text");
  const toggle = (id: string) => onHidden(hidden.has(id) ? [...hidden].filter(h => h !== id) : [...hidden, id]);
  return (
    <Popover onClose={onClose} left={60} width={420}>
      <span className="aug-fs-xs" style={MUTED}>Columns — shown or hidden in this view{editable ? "; described, renamed or added" : ""}</span>
      <div style={{ maxHeight: 340, overflowY: "auto", display: "flex", flexDirection: "column", gap: 2 }}>
        {sheet.columns.map(c => (
          <div key={c.id} style={{ display: "flex", flexDirection: "column", gap: 4, padding: "3px 0", borderTop: "1px solid var(--b0)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Checkbox checked={!hidden.has(c.id)} onChange={() => toggle(c.id)} aria-label={`Show ${c.name}`} />
              <span style={{ flex: 1 }}>{c.name}</span>
              <span className="aug-fs-xs" style={MUTED}>{KIND_LABEL[c.kind]}{c.role !== "stored" ? ` · ${c.role}` : ""}</span>
              {editable && (
                <Button variant="ghost" size="icon-xs" aria-label={`Change ${c.name}`}
                  onClick={() => { setEditing(editing === c.id ? "" : c.id); setName(c.name); setDesc(c.description); setKind(c.kind); }}>
                  <Icon name="edit" size={12} />
                </Button>
              )}
            </div>
            {editing === c.id && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "4px 0 6px 24px" }}>
                <Input value={name} onChange={e => setName(e.target.value)} aria-label="Name" />
                <Input value={desc} onChange={e => setDesc(e.target.value)} placeholder="What this column holds"
                  aria-label="Description" />
                {c.role === "stored" && c.kind !== "link" && (
                  <Select value={kind} onValueChange={v => setKind(v as Kind)}>
                    <SelectTrigger aria-label="Kind" />
                    <SelectContent>{NEW_COLUMN_KINDS.map(k => <SelectItem key={k} value={k}>{KIND_LABEL[k]}</SelectItem>)}</SelectContent>
                  </Select>
                )}
                <div style={{ display: "flex", gap: 6 }}>
                  <Button size="xs" onClick={() => void run(() => updateColumn(sheet.id, c.id, {
                    name: name !== c.name ? name : undefined, description: desc !== c.description ? desc : undefined,
                    kind: kind !== c.kind ? kind : undefined,
                  }), `${name} changed`).then(ok => { if (ok) setEditing(""); })}>Keep</Button>
                  <Button variant="destructive" size="xs" onClick={() => void run(() => removeColumn(sheet.id, c.id),
                    `${c.name} taken off — undo brings it back`)}>Take off</Button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      {editable && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", borderTop: "1px solid var(--b1)", paddingTop: 8 }}>
          <Input value={newName} onChange={e => setNewName(e.target.value)} placeholder="A new column" aria-label="New column" style={{ flex: 1 }} />
          <div style={{ width: 130 }}>
            <Select value={newKind} onValueChange={v => setNewKind(v as Kind)}>
              <SelectTrigger aria-label="New column's kind" />
              <SelectContent>{NEW_COLUMN_KINDS.map(k => <SelectItem key={k} value={k}>{KIND_LABEL[k]}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <Button size="xs" disabled={!newName.trim()} onClick={() => void run(() => addColumn(sheet.id, newName, newKind),
            `${newName} added`).then(ok => { if (ok) setNewName(""); })}>Add</Button>
        </div>
      )}
    </Popover>
  );
}

function FilterPop({ sheet, conditions, onApply, onClose }: {
  sheet: Sheet; conditions: Condition[]; onApply: (f: Condition[]) => void; onClose: () => void;
}) {
  const [rows, setRows] = useState<Condition[]>(conditions.length ? conditions : [{ column: sheet.columns[0]?.id ?? "", op: "is", value: "" }]);
  const colOf = (id: string) => sheet.columns.find(c => c.id === id);
  const set = (i: number, c: Partial<Condition>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...c } : r)));
  return (
    <Popover onClose={onClose} left={150} width={560}>
      <span className="aug-fs-xs" style={MUTED}>Show the rows where every condition holds</span>
      {rows.map((r, i) => {
        const col = colOf(r.column);
        const ops = opsFor(col?.kind ?? "text");
        const valueless = r.op === "empty" || r.op === "not_empty";
        return (
          <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <div style={{ width: 180 }}>
              <Select value={r.column} onValueChange={v => set(i, { column: v, op: opsFor(colOf(v)?.kind ?? "text")[0] })}>
                <SelectTrigger aria-label="Column" />
                <SelectContent>{sheet.columns.map(c => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div style={{ width: 130 }}>
              <Select value={r.op} onValueChange={v => set(i, { op: v })}>
                <SelectTrigger aria-label="How" />
                <SelectContent>{ops.map(o => <SelectItem key={o} value={o}>{opWords(o)}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            {!valueless && (
              <Input aria-label="Value" style={{ flex: 1 }}
                placeholder={r.op === "in" || r.op === "not_in" ? "values, separated by commas"
                  : col?.kind === "date" ? "2018-10-17" : ""}
                value={Array.isArray(r.value) ? r.value.join(", ") : String(r.value ?? "")}
                onChange={e => set(i, { value: r.op === "in" || r.op === "not_in"
                  ? e.target.value.split(",").map(x => x.trim()).filter(Boolean) : e.target.value })} />
            )}
            <Button variant="ghost" size="icon-xs" aria-label="Take off this condition" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
              <Icon name="close" size={12} />
            </Button>
          </div>
        );
      })}
      <div style={{ display: "flex", gap: 6 }}>
        <Button variant="outline" size="xs" onClick={() => setRows([...rows, { column: sheet.columns[0]?.id ?? "", op: "is", value: "" }])}>
          <Icon name="plus" size={12} /> Condition
        </Button>
        <Button size="xs" onClick={() => onApply(rows.filter(r => r.column && (r.op === "empty" || r.op === "not_empty"
          || (Array.isArray(r.value) ? r.value.length : String(r.value ?? "").trim()))))}>Apply</Button>
        <Button variant="ghost" size="xs" onClick={() => onApply([])}>Clear</Button>
      </div>
    </Popover>
  );
}

function SortPop({ sheet, sort, onApply, onClose }: {
  sheet: Sheet; sort: { column: string; desc: boolean }[]; onApply: (s: { column: string; desc: boolean }[]) => void;
  onClose: () => void;
}) {
  const [rows, setRows] = useState(sort.length ? sort : [{ column: sheet.columns[0]?.id ?? "", desc: false }]);
  return (
    <Popover onClose={onClose} left={240} width={420}>
      <span className="aug-fs-xs" style={MUTED}>Sort the rows by — then by the sheet&apos;s order</span>
      {rows.map((r, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <div style={{ flex: 1 }}>
            <Select value={r.column} onValueChange={v => setRows(rows.map((x, j) => (j === i ? { ...x, column: v } : x)))}>
              <SelectTrigger aria-label="Column" />
              <SelectContent>{sheet.columns.map(c => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <Button variant="outline" size="xs" onClick={() => setRows(rows.map((x, j) => (j === i ? { ...x, desc: !x.desc } : x)))}>
            {r.desc ? "highest first" : "lowest first"}
          </Button>
          <Button variant="ghost" size="icon-xs" aria-label="Take off" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
            <Icon name="close" size={12} />
          </Button>
        </div>
      ))}
      <div style={{ display: "flex", gap: 6 }}>
        <Button variant="outline" size="xs" onClick={() => setRows([...rows, { column: sheet.columns[0]?.id ?? "", desc: false }])}>
          <Icon name="plus" size={12} /> Then by
        </Button>
        <Button size="xs" onClick={() => onApply(rows.filter(r => r.column))}>Apply</Button>
        <Button variant="ghost" size="xs" onClick={() => onApply([])}>Clear</Button>
      </div>
    </Popover>
  );
}

function NamePop({ label, initial, onKeep, onClose }: {
  label: string; initial: string; onKeep: (name: string) => void; onClose: () => void;
}) {
  const [name, setName] = useState(initial);
  return (
    <Popover onClose={onClose} width={340}>
      <span className="aug-fs-xs" style={MUTED}>{label}</span>
      <Input value={name} autoFocus aria-label="The view's name" onChange={e => setName(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") onKeep(name); }} />
      <Button size="xs" disabled={!name.trim()} onClick={() => onKeep(name)} style={{ alignSelf: "flex-start" }}>Keep the view</Button>
    </Popover>
  );
}
