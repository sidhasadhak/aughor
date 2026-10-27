"use client";

/**
 * A sheet open (mockup screens 3 to 10): its bar — where it came from, its rows and columns, who it is shared with —
 * its views as tabs, the toolbar, the rows laid out as the view says (a grid, grouped or not; a board; a calendar),
 * and beside them the chat, the combining tools, a row's record or the history.
 *
 * A view's filter, sort, grouping and hidden columns are read from the view; changing them here is the person's own
 * until they keep them in the view. A change made here is said under the toolbar with Undo beside it. With
 * `sheets.views` (SH-3) a view can be a board or a calendar, grouped with its totals, or kept to its maker — and rules mark
 * rows.
 */
import { type CSSProperties, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Chip, Dot, MUTED, NUM } from "@/components/clarity/kit";
import { SheetBoard } from "@/components/sheets/SheetBoard";
import { SheetCalendar } from "@/components/sheets/SheetCalendar";
import { SheetChat } from "@/components/sheets/SheetChat";
import { SheetCombine } from "@/components/sheets/SheetCombine";
import { SheetDashboard } from "@/components/sheets/SheetDashboard";
import { RULE_COLOR, SheetGrid, type EditResult } from "@/components/sheets/SheetGrid";
import { SheetGroups } from "@/components/sheets/SheetGroups";
import { SheetHistory, SheetRecordPanel } from "@/components/sheets/SheetRecord";
import { SharePop } from "@/components/sheets/SheetsHome";
import type { SheetsWaves } from "@/components/sheets/SpreadsheetsPage";
import { useCloseOutside } from "@/components/sheets/useCloseOutside";
import { useRowBlocks } from "@/components/sheets/useRowBlocks";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon, type IconName } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { Loading, ReadFailed } from "@/components/ui/states";
import { formatCount } from "@/lib/format";
import {
  KIND_LABEL, NEW_COLUMN_KINDS, RULE_TONES, addColumn, addRow, csvUrl, filterWords, opWords, opsFor, readChanges,
  readRows, readSheet, redo, removeColumn, removeRule, removeView, renameSheet, saveRule, saveView, setCells, showValue,
  undo,
  updateColumn, type Condition, type Kind, type RowsQuery, type RuleTone, type Sheet, type SheetColumn, type SheetView as View,
  type ViewKind,
} from "@/lib/sheets";

/** The most rows Copy takes; the CSV holds every row. */
const COPY_MOST = 2000;
/** Below this width the toolbar's buttons say their names on hover only. */
const NARROW = 860;

const BAR: CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, padding: "8px 16px", borderBottom: "1px solid var(--b1)",
  background: "var(--bg-1)", flexWrap: "nowrap", minWidth: 0,
};

const KIND_OF_VIEW: Record<ViewKind | "grouped", IconName> = { grid: "table", grouped: "list", board: "column", calendar: "date" };

type Panel = "" | "chat" | "combine" | "record" | "history";
type Pop = "" | "fields" | "filter" | "sort" | "group" | "share" | "view" | "rules" | "lanes" | "card" | "by";

interface Query {
  view: string;
  filter: Condition[];
  sort: { column: string; desc: boolean }[];
  search: string;
  group: string;
  hidden: string[];
  kind: ViewKind;
  date: string;
  card: string[];
}

function fromView(sheet: Sheet, viewId: string): Query {
  const v = sheet.views.find(x => x.id === viewId) ?? sheet.views[0];
  return {
    view: v?.id ?? "", filter: v?.filter ?? [], sort: v?.sort ?? [], search: v?.search ?? "", group: v?.group ?? "",
    hidden: [...(v?.hidden ?? []), ...sheet.columns.filter(c => c.hidden).map(c => c.id)],
    kind: v?.kind ?? "grid", date: v?.date ?? "", card: v?.card ?? [],
  };
}

function sameAsView(sheet: Sheet, q: Query, views: boolean): boolean {
  const v = sheet.views.find(x => x.id === q.view);
  if (!v) return false;
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
  return same(v.filter, q.filter) && same(v.sort, q.sort) && v.search === q.search
    && same([...v.hidden].sort(), q.hidden.filter(h => !sheet.columns.find(c => c.id === h)?.hidden).sort())
    // with views off a grouping is the reader's own for the visit, never part of what a view keeps
    && (!views || (v.group === q.group && v.kind === q.kind && v.date === q.date && same(v.card, q.card)));
}

/** Whether the sheet's own column is narrower than its toolbar — measured on the element once it is there (the sheet
 *  is read first, so a ref taken on mounting would be empty). */
function useNarrow(): [boolean, (el: HTMLDivElement | null) => void] {
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setNarrow(e.contentRect.width < NARROW));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [narrow, setEl];
}

export function SheetView({ sheetId, waves, onBack, onOpen, onAsk }: {
  sheetId: string; waves: SheetsWaves; onBack: () => void; onOpen: (id: string) => void;
  onAsk?: (question: string) => void;
}) {
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [query, setQuery] = useState<Query | null>(null);
  const [panel, setPanel] = useState<Panel>(waves.chat ? "chat" : "");
  const [pop, setPop] = useState<Pop>("");
  const [recordRow, setRecordRow] = useState<number | null>(null);
  // what was just done, and the one step back (or forward, after an undo) offered beside it
  const [said, setSaid] = useState<{ text: string; tone: "ok" | "bad"; offer?: "undo" | "redo" } | null>(null);
  const [history, setHistory] = useState<{ can_undo: string; can_redo: string } | null>(null);
  const [tick, setTick] = useState(0);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [dashboard, setDashboard] = useState(false);
  const [narrow, mainRef] = useNarrow();

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

  const flat = !!query && query.kind === "grid" && !query.group;
  const rowsQuery: RowsQuery | null = useMemo(() => (sheet && query && flat
    ? { filter: query.filter, sort: query.sort, search: query.search } : null), [sheet, query, flat]);
  const rows = useRowBlocks(sheetId, rowsQuery, tick);

  /** After any change: the definition and the rows again, and what undo would take back. */
  const changed = useCallback(async (words?: string, offer: "undo" | "redo" = "undo") => {
    await readDefinition();
    setTick(t => t + 1);
    if (words) setSaid({ text: words, tone: "ok", offer });
  }, [readDefinition]);

  const run = useCallback(async (what: () => Promise<unknown>, words?: string, offer: "undo" | "redo" = "undo") => {
    try {
      await what();
      await changed(words, offer);
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
      setSaid({ text: `${c.name} of row ${row} changed`, tone: "ok", offer: "undo" });
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  }, [sheet]);

  const hidden = useMemo(() => new Set(query?.hidden ?? []), [query]);

  if (failed) return <ReadFailed what="the sheet" error={failed} onRetry={() => void readDefinition()} />;
  if (!sheet || !query) return <Loading what="the sheet" />;

  const setQ = (q: Partial<Query>) => setQuery({ ...query, ...q });
  const dirty = !sameAsView(sheet, query, waves.views);
  const view = sheet.views.find(v => v.id === query.view);
  const all = Number(sheet.rows ?? 0);
  const openRow = (row: number) => { setRecordRow(row); setPanel("record"); };
  const colName = (id: string) => sheet.columns.find(c => c.id === id)?.name ?? "";
  const viewQuery: RowsQuery = { filter: query.filter, sort: query.sort, search: query.search };

  const copyRows = () => {
    readRows(sheet.id, { ...viewQuery, limit: COPY_MOST }).then(p => {
      const shown = sheet.columns.filter(c => !hidden.has(c.id));
      const idx = Object.fromEntries(p.columns.map((id, i) => [id, i + 1]));
      const lines = [shown.map(c => c.name).join("\t"),
        ...p.rows.map(r => shown.map(c => showValue(r[idx[c.id]], c)).join("\t"))];
      if (!navigator.clipboard) throw new Error("Not copied — this browser gives the page no clipboard");
      return navigator.clipboard.writeText(lines.join("\n")).then(
        () => setSaid({ text: p.total > p.rows.length ? `Copied the first ${formatCount(p.rows.length)} of ${formatCount(p.total)} rows — the CSV holds them all`
          : `Copied ${formatCount(p.rows.length)} rows`, tone: "ok" }),
        () => { throw new Error("Not copied — the browser refused the page its clipboard"); });
    }).catch(e => setSaid({ text: e instanceof Error ? e.message : String(e), tone: "bad" }));
  };

  /** What a view keeps of what is shown: its filter, sort, hidden columns — and with SH-3 its layout. */
  const kept = (): Partial<View> => ({
    filter: query.filter, sort: query.sort, search: query.search,
    hidden: query.hidden.filter(h => !sheet.columns.find(c => c.id === h)?.hidden),
    ...(waves.views ? { kind: query.kind, group: query.group, date: query.date, card: query.card } : {}),
  });

  const keepAsView = async (name: string, kind: ViewKind, column: string, shared: boolean) => {
    if (!name.trim()) return;
    const layout = kind === "board" ? { kind, group: column, date: "" } : kind === "calendar" ? { kind, date: column, group: "" }
      : {};
    let madeId = "";
    const ok = await run(async () => {
      const s = await saveView(sheet.id, { ...kept(), ...layout, name, shared });
      madeId = s.views[s.views.length - 1]?.id ?? "";
    }, `View ${name} kept${shared ? "" : " — only you see it"}`);
    if (ok) {
      const s = await readSheet(sheet.id);
      setQuery(fromView(s, madeId || s.views[s.views.length - 1]?.id || ""));
    }
  };

  /** A click on a column's header: lowest first, then highest first, then the sheet's own order — the person's own
   *  until they keep it in the view. */
  const sortBy = (column: string) => {
    const now = query.sort[0]?.column === column ? query.sort[0] : undefined;
    setQ({ sort: !now ? [{ column, desc: false }] : !now.desc ? [{ column, desc: true }] : [] });
  };

  /** Take a view off the sheet — undo puts it back — and read the sheet on its first view. */
  const takeOff = async (v: View) => {
    const ok = await run(() => removeView(sheet.id, v.id), `View ${v.name} taken off`);
    if (ok) {
      const s = await readSheet(sheet.id);
      setQuery(fromView(s, s.views[0]?.id ?? ""));
    }
  };
  // a sheet keeps one shared view; a view of someone else's own is never listed here
  const canTakeOff = (v: View) => waves.grid && (!v.shared || sheet.views.filter(x => x.shared).length > 1);

  const updateThisView = () => view && run(() => saveView(sheet.id, { ...view, ...kept() }), `View ${view.name} changed`);

  const toolbar = (
    <>
      {query.kind === "grid" && waves.grid && (
        <ToolButton narrow={narrow} icon="plus" label="Row" onClick={() => void run(async () => {
          const r = await addRow(sheet.id);
          setSaid({ text: `Row ${r.row} added`, tone: "ok", offer: "undo" });
        })} />
      )}
      {query.kind === "grid" && (
        <ToolButton expanded={pop === "fields"} narrow={narrow} on={hidden.size > 0} onClick={() => setPop(pop === "fields" ? "" : "fields")} icon="column"
          label={hidden.size ? `Fields · ${hidden.size} hidden` : "Fields"} />
      )}
      <ToolButton expanded={pop === "filter"} narrow={narrow} on={query.filter.length > 0} onClick={() => setPop(pop === "filter" ? "" : "filter")}
        icon="filter" label={query.filter.length ? `Filter · ${query.filter.length}` : "Filter"} />
      {query.kind !== "calendar" && (
        <ToolButton expanded={pop === "sort"} narrow={narrow} on={query.sort.length > 0} onClick={() => setPop(pop === "sort" ? "" : "sort")}
          icon="sliders" label={query.sort.length ? `Sort · ${query.sort.length}` : "Sort"} />
      )}
      {query.kind === "grid" && (
        <ToolButton expanded={pop === "group"} narrow={narrow} on={!!query.group} onClick={() => setPop(pop === "group" ? "" : "group")} icon="list"
          label={query.group ? `Group · ${colName(query.group)}` : "Group"} />
      )}
      {query.kind === "board" && (
        <ToolButton expanded={pop === "lanes"} narrow={narrow} on onClick={() => setPop(pop === "lanes" ? "" : "lanes")} icon="column"
          label={`Lanes by ${colName(query.group)}`} />
      )}
      {query.kind === "calendar" && (
        <ToolButton expanded={pop === "by"} narrow={narrow} on onClick={() => setPop(pop === "by" ? "" : "by")} icon="date"
          label={`By ${colName(query.date)}`} />
      )}
      {query.kind !== "grid" && (
        <ToolButton expanded={pop === "card"} narrow={narrow} on={query.card.length > 0} onClick={() => setPop(pop === "card" ? "" : "card")}
          icon="eye" label={query.card.length ? `Card shows ${query.card.length}` : "Card shows"} />
      )}
      {waves.views && (
        <ToolButton expanded={pop === "rules"} narrow={narrow} on={sheet.rules.length > 0} onClick={() => setPop(pop === "rules" ? "" : "rules")}
          icon="bookmark" label={sheet.rules.length ? `Rules · ${sheet.rules.length}` : "Rules"} />
      )}
    </>
  );

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
      <div ref={mainRef} style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", background: "var(--bg-0)" }}>
        {/* the sheet's bar */}
        <div style={BAR}>
          <Button variant="ghost" size="sm" onClick={onBack} style={{ ...MUTED, padding: "0 4px", flex: "0 0 auto" }}>Spreadsheets /</Button>
          {renaming !== null ? (
            <Input value={renaming} autoFocus aria-label="The sheet's name" style={{ width: 240 }}
              onChange={e => setRenaming(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter") { const n = renaming; setRenaming(null); void run(() => renameSheet(sheet.id, n), "Renamed"); }
                if (e.key === "Escape") setRenaming(null);
              }} onBlur={() => setRenaming(null)} />
          ) : (
            <Button variant="ghost" size="sm" disabled={!waves.grid} title={waves.grid ? "Rename" : undefined}
              onClick={() => setRenaming(sheet.name)} style={{ fontWeight: 600, color: "var(--t1)", padding: "0 4px", flex: "0 0 auto" }}>
              {sheet.name}
            </Button>
          )}
          {/* the plain chip's look, shrinking to "…" where the bar is narrow */}
          <span className="aug-fs-xs" title={sheet.source.sql || sheet.came_from} style={{ minWidth: 40, flex: "0 1 auto",
            maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", background: "var(--bg-3)",
            color: "var(--t2)", border: "1px solid var(--b1)", borderRadius: "var(--r-pill)", padding: "1px 8px" }}>
            {sheet.came_from}
          </span>
          <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, whiteSpace: "nowrap", flex: "0 0 auto" }}>
            {flat && rows.total !== null && rows.total !== all ? `${formatCount(rows.total)} of ` : ""}{formatCount(all)} rows ·{" "}
            {sheet.columns.length} columns
          </span>
          <span style={{ marginLeft: "auto", display: "flex", gap: 6, position: "relative", flex: "0 0 auto" }}>
            {waves.dashboard && (
              <Button variant="outline" size="sm" onClick={() => setDashboard(true)}
                title={view && (view.filter.length || view.search) ? `Cards that read the view ${view.name}` : "Cards that read the sheet"}>
                <Icon name="canvas" /> {narrow ? "Dashboard" : "Make a dashboard"}
              </Button>
            )}
            <Button variant="outline" size="sm" aria-expanded={pop === "share"}
              onClick={() => setPop(pop === "share" ? "" : "share")}>Share · Workspace</Button>
            {pop === "share" && <SharePop name={sheet.name} sheetId={sheet.id} views={sheet.views} me={sheet.me}
              onDone={() => setPop("")} />}
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
        <div style={{ ...BAR, gap: 2, padding: "0 12px", background: "var(--bg-0)" }}>
          {/* the tabs scroll on their own, so what opens beside them is never clipped by the scroll */}
          <span role="tablist" aria-label="Views" style={{ display: "flex", gap: 2, overflowX: "auto", minWidth: 0, flex: "0 1 auto" }}>
          {sheet.views.map(v => {
            const n = sheet.view_rows?.[v.id];
            const narrowed = v.filter.length > 0 || !!v.search;
            const on = v.id === query.view;
            return (
              <span key={v.id} style={{ display: "inline-flex", alignItems: "center", flex: "0 0 auto",
                borderBottom: on ? "2px solid var(--blue3)" : "2px solid transparent" }}>
                <Button role="tab" aria-selected={on} variant="ghost" size="sm"
                  onClick={() => setQuery(fromView(sheet, v.id))}
                  title={v.shared ? undefined : "Your own view — only you see it"}
                  style={{ borderRadius: 0, color: on ? "var(--t1)" : "var(--t2)", height: 32 }}>
                  <Icon name={KIND_OF_VIEW[v.kind === "grid" && v.group ? "grouped" : v.kind]} size={12} /> {v.name}
                  {!v.shared && <Icon name="user" size={11} />}
                  {narrowed && n !== null && n !== undefined && <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>{formatCount(n)}</span>}
                  {v.made_by && <Chip tone="violet" title="Proposed by the assistant, applied by a person">proposed</Chip>}
                </Button>
                {on && canTakeOff(v) && (
                  <Button variant="ghost" size="icon-xs" aria-label={`Take off the view ${v.name}`}
                    title="Take off this view — Undo puts it back" onClick={() => void takeOff(v)} style={MUTED}>
                    <Icon name="close" size={11} />
                  </Button>
                )}
              </span>
            );
          })}
          </span>
          {waves.grid && (
            <span style={{ position: "relative", flex: "0 0 auto" }}>
              <Button variant="ghost" size="sm" aria-expanded={pop === "view"} onClick={() => setPop(pop === "view" ? "" : "view")}
                style={{ ...MUTED, height: 34 }}>
                <Icon name="plus" size={12} /> View
              </Button>
              {pop === "view" && (
                <ViewPop sheet={sheet} views={waves.views} initial={view && !dirty ? `${view.name} 2` : "New view"}
                  onClose={() => setPop("")}
                  onKeep={(name, kind, column, shared) => { setPop(""); void keepAsView(name, kind, column, shared); }} />
              )}
            </span>
          )}
          <span className="aug-fs-xs" style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center", flex: "0 0 auto", ...MUTED }}>
            {dirty && waves.grid ? (
              <>
                changed here, not kept
                {view && <Button variant="outline" size="xs" onClick={() => void updateThisView()}>Keep in {view.name}</Button>}
                <Button variant="ghost" size="xs" onClick={() => setQuery(fromView(sheet, query.view))}>Back to the view</Button>
              </>
            ) : waves.views && view && (
              <>
                {view.shared ? "Shared view" : "Your own view — only you see it"}
                {view.owner && view.owner === sheet.me && (
                  <Button variant="ghost" size="xs" onClick={() => void run(() => saveView(sheet.id, { ...view, shared: !view.shared }),
                    view.shared ? `${view.name} is yours alone now` : `${view.name} is shared with the workspace`)}>
                    {view.shared ? "Make it yours alone" : "Share it"}
                  </Button>
                )}
              </>
            )}
          </span>
        </div>

        {/* the toolbar */}
        <div style={{ ...BAR, gap: 4, background: "var(--bg-0)", position: "relative" }}>
          {toolbar}
          <div style={{ flex: "0 1 220px", minWidth: 110, marginLeft: 8 }}>
            <Input value={query.search} placeholder="Search this sheet" aria-label="Search this sheet"
              onChange={e => setQ({ search: e.target.value })} />
          </div>
          <span style={{ marginLeft: "auto", display: "flex", gap: 2, flex: "0 0 auto" }}>
            {waves.grid && (
              <>
                <Button variant="ghost" size="icon-sm" aria-label="Undo" title={history?.can_undo ? `Undo: ${history.can_undo}` : "Nothing to undo"}
                  disabled={!history?.can_undo} onClick={() => void run(() => undo(sheet.id), "Undone", "redo")}>
                  <Icon name="back" />
                </Button>
                <Button variant="ghost" size="icon-sm" aria-label="Redo" title={history?.can_redo ? `Redo: ${history.can_redo}` : "Nothing to redo"}
                  disabled={!history?.can_redo} onClick={() => void run(() => redo(sheet.id), "Redone")}>
                  <Icon name="next" />
                </Button>
                <ToolButton narrow={narrow} on={panel === "history"} icon="history" label="History"
                  onClick={() => setPanel(panel === "history" ? "" : "history")} />
              </>
            )}
            {query.kind === "grid" && (
              <>
                <ToolButton narrow={narrow} icon="copy" label="Copy" onClick={copyRows} />
                <ToolButton narrow={narrow} icon="download" label="CSV" onClick={() => window.open(csvUrl(sheet.id, {
                  ...viewQuery, view: query.view }), "_blank")} />
              </>
            )}
          </span>
          {pop === "fields" && (
            <FieldsPop sheet={sheet} hidden={hidden} editable={waves.grid} onHidden={h => setQ({ hidden: h })}
              onClose={() => setPop("")} run={run} />
          )}
          {pop === "filter" && (
            <FilterPop sheet={sheet} conditions={query.filter} onApply={f => { setQ({ filter: f }); setPop(""); }}
              onClose={() => setPop("")} />
          )}
          {pop === "sort" && (
            <SortPop sheet={sheet} sort={query.sort} onApply={s => { setQ({ sort: s }); setPop(""); }} onClose={() => setPop("")} />
          )}
          {pop === "group" && (
            <ColumnPop label={`Group the rows by — the largest group first${waves.views ? ", each with its totals" : ""}`}
              columns={sheet.columns} value={query.group} none="No grouping"
              onPick={g => { setQ({ group: g }); setPop(""); }} onClose={() => setPop("")} />
          )}
          {pop === "lanes" && (
            <ColumnPop label="A lane for each value of — a choice or a yes/no column"
              columns={sheet.columns.filter(c => c.kind === "choice" || c.kind === "yesno")} value={query.group}
              onPick={g => { if (g) setQ({ group: g }); setPop(""); }} onClose={() => setPop("")} />
          )}
          {pop === "by" && (
            <ColumnPop label="Place the rows by — a date column"
              columns={sheet.columns.filter(c => c.kind === "date" || c.kind === "datetime")} value={query.date}
              onPick={d => { if (d) setQ({ date: d }); setPop(""); }} onClose={() => setPop("")} />
          )}
          {pop === "card" && (
            <CardPop sheet={sheet} card={query.card} onApply={c => setQ({ card: c })} onClose={() => setPop("")} />
          )}
          {pop === "rules" && (
            <RulesPop sheet={sheet} run={run} onClose={() => setPop("")}
              onShow={id => { setQ({ filter: [{ column: "", op: "marked", value: id }] }); setPop(""); }} />
          )}
        </div>
        {(query.filter.length > 0 || said) && (
          <div className="aug-fs-xs" style={{ padding: "4px 16px", display: "flex", gap: 10, alignItems: "center",
            borderBottom: "1px solid var(--b0)", ...MUTED }}>
            {query.filter.length > 0 && <span>Filter: {filterWords(query.filter, sheet.columns, sheet.rules)}</span>}
            {said && (
              <span role={said.tone === "bad" ? "alert" : "status"} style={{ marginLeft: "auto", display: "flex", gap: 6,
                alignItems: "center", color: said.tone === "bad" ? "var(--red4)" : "var(--grn4)" }}>
                {said.text}
                {said.offer === "undo" && history?.can_undo && (
                  <Button variant="ghost" size="xs" title={`Undo: ${history.can_undo}`}
                    onClick={() => void run(() => undo(sheet.id), "Undone", "redo")}>· Undo</Button>
                )}
                {said.offer === "redo" && history?.can_redo && (
                  <Button variant="ghost" size="xs" title={`Redo: ${history.can_redo}`}
                    onClick={() => void run(() => redo(sheet.id), "Redone")}>· Redo</Button>
                )}
                <Button variant="ghost" size="icon-xs" aria-label="Dismiss" onClick={() => setSaid(null)}><Icon name="close" size={11} /></Button>
              </span>
            )}
          </div>
        )}

        {query.kind === "board" && waves.views ? (
          <SheetBoard sheet={sheet} query={viewQuery} column={query.group} card={query.card} editable={waves.grid}
            tick={tick} onOpenRow={openRow} onMoved={words => void changed(words)} />
        ) : query.kind === "calendar" && waves.views ? (
          <SheetCalendar sheet={sheet} query={viewQuery} column={query.date} card={query.card} tick={tick} onOpenRow={openRow} />
        ) : query.group ? (
          <SheetGroups sheet={sheet} query={viewQuery} group={query.group} hidden={hidden} editable={waves.grid} tick={tick}
            onEdit={onEdit} onOpenRow={openRow} onSort={sortBy} />
        ) : rows.failed ? <ReadFailed what="the rows" error={rows.failed} onRetry={rows.retry} />
          : rows.total === null ? <Loading what="the rows" /> : (
            <SheetGrid key={JSON.stringify(rowsQuery)} sheet={sheet} rows={rows} hidden={hidden} editable={waves.grid}
              onEdit={onEdit} onOpenRow={openRow} sort={query.sort} onSort={sortBy}
              footer={`${view ? view.name : "the sheet"}${query.sort.length
                ? ` · sorted by ${query.sort.map(s => colName(s.column)).join(", ")}` : " · in the sheet's order"}`} />
          )}
      </div>

      {dashboard && <SheetDashboard sheet={sheet} viewId={query.view} onClose={() => setDashboard(false)} />}
      {panel === "chat" && waves.chat && (
        <SheetChat sheet={sheet} viewId={query.view} viewRows={rows.total} onClose={() => setPanel("")}
          onApplied={() => void changed("Applied")} onOpenSheet={onOpen} onAsk={onAsk}
          onOpenView={name => { readSheet(sheet.id).then(s => {
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
          onUndo={() => void run(() => undo(sheet.id), "Undone", "redo")} />
      )}
    </div>
  );
}

/** A toolbar button: its icon and its name — the name only on hover where the sheet is narrow. */
function ToolButton({ on = false, onClick, icon, label, narrow, expanded }: {
  on?: boolean; onClick: () => void; icon: IconName; label: string; narrow: boolean;
  /** Whether the box this button opens is open — said, so a click on it toggles the box rather than closing it twice. */
  expanded?: boolean;
}) {
  return (
    <Button variant={on ? "secondary" : "ghost"} size={narrow ? "icon-sm" : "sm"} onClick={onClick} aria-expanded={expanded}
      aria-label={narrow ? label : undefined} title={narrow ? label : undefined} style={{ flex: "0 0 auto" }}>
      <Icon name={icon} />{narrow ? null : ` ${label}`}
    </Button>
  );
}

export function Popover({ children, onClose, left = 0, width = 360 }: {
  children: ReactNode; onClose: () => void; left?: number; width?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useCloseOutside(ref, onClose);
  return (
    <div ref={ref} role="dialog" className="aug-fs-sm" style={{ position: "absolute", top: "100%", left, zIndex: 30, width,
      background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
      padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8, boxShadow: "var(--shadow-md)" }}>
      {children}
      <Button variant="ghost" size="xs" onClick={onClose} style={{ alignSelf: "flex-end" }}>Close</Button>
    </div>
  );
}

/** One column picked from those given — or none, where `none` names what none means. */
function ColumnPop({ label, columns, value, none, onPick, onClose }: {
  label: string; columns: SheetColumn[]; value: string; none?: string; onPick: (id: string) => void; onClose: () => void;
}) {
  return (
    <Popover onClose={onClose} left={200}>
      <span className="aug-fs-xs" style={MUTED}>{label}</span>
      {columns.length === 0 ? <span className="aug-fs-xs" style={MUTED}>No column of this sheet is of that kind.</span> : (
        <Select value={value} onValueChange={onPick}
          items={{ ...(none ? { "": none } : {}), ...Object.fromEntries(columns.map(c => [c.id, c.name])) }}>
          <SelectTrigger aria-label={label} />
          <SelectContent>
            {none && <SelectItem value="">{none}</SelectItem>}
            {columns.map(c => <SelectItem key={c.id} value={c.id}>{c.name} · {KIND_LABEL[c.kind]}</SelectItem>)}
          </SelectContent>
        </Select>
      )}
    </Popover>
  );
}

/** The columns a card shows under its title — at most four; none chosen, the first dates, money and numbers. */
function CardPop({ sheet, card, onApply, onClose }: {
  sheet: Sheet; card: string[]; onApply: (card: string[]) => void; onClose: () => void;
}) {
  const toggle = (id: string) => onApply(card.includes(id) ? card.filter(c => c !== id) : [...card, id].slice(0, 4));
  return (
    <Popover onClose={onClose} left={240} width={300}>
      <span className="aug-fs-xs" style={MUTED}>A card shows, under its title — at most four</span>
      <div style={{ maxHeight: 280, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
        {sheet.columns.map(c => (
          <label key={c.id} className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Checkbox checked={card.includes(c.id)} onChange={() => toggle(c.id)} aria-label={`Show ${c.name} on a card`} />
            <span style={{ flex: 1 }}>{c.name}</span>
            <span className="aug-fs-xs" style={MUTED}>{KIND_LABEL[c.kind]}</span>
          </label>
        ))}
      </div>
      {card.length > 0 && <Button variant="ghost" size="xs" onClick={() => onApply([])} style={{ alignSelf: "flex-start" }}>
        Back to the first dates and amounts</Button>}
    </Popover>
  );
}

/** A new view: its name, how it lays its rows out, and — with SH-3 — whether everyone who reads the sheet sees it. */
function ViewPop({ sheet, views, initial, onKeep, onClose }: {
  sheet: Sheet; views: boolean; initial: string; onClose: () => void;
  onKeep: (name: string, kind: ViewKind, column: string, shared: boolean) => void;
}) {
  const lanes = sheet.columns.filter(c => c.kind === "choice" || c.kind === "yesno");
  const dates = sheet.columns.filter(c => c.kind === "date" || c.kind === "datetime");
  const [name, setName] = useState(initial);
  const [kind, setKind] = useState<ViewKind>("grid");
  const [column, setColumn] = useState("");
  const [shared, setShared] = useState(true);
  const choices = kind === "board" ? lanes : kind === "calendar" ? dates : [];
  const picked = column || choices[0]?.id || "";
  const options = [{ value: "grid" as ViewKind, label: "Grid" },
    ...(views && lanes.length ? [{ value: "board" as ViewKind, label: "Board" }] : []),
    ...(views && dates.length ? [{ value: "calendar" as ViewKind, label: "Calendar" }] : [])];
  return (
    <Popover onClose={onClose} width={380}>
      <span className="aug-fs-xs" style={MUTED}>Keep what is shown — its filter, sort and hidden columns — as a view</span>
      <Input value={name} autoFocus aria-label="The view's name" onChange={e => setName(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") onKeep(name, kind, picked, shared); }} />
      {options.length > 1 && (
        <Segmented label="Lay the rows out as" value={kind} onChange={v => { setKind(v); setColumn(""); }} options={options} />
      )}
      {kind !== "grid" && (
        <Select value={picked} onValueChange={setColumn} items={Object.fromEntries(choices.map(c => [c.id, c.name]))}>
          <SelectTrigger aria-label={kind === "board" ? "A lane for each value of" : "Place the rows by"} />
          <SelectContent>{choices.map(c => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}</SelectContent>
        </Select>
      )}
      {views && (
        <Segmented label="Who sees it" value={shared ? "all" : "me"} onChange={v => setShared(v === "all")}
          options={[{ value: "all", label: "Everyone who reads the sheet" }, { value: "me", label: "Only me" }]} />
      )}
      <Button size="xs" disabled={!name.trim() || (kind !== "grid" && !picked)} onClick={() => onKeep(name, kind, picked, shared)}
        style={{ alignSelf: "flex-start" }}>Keep the view</Button>
    </Popover>
  );
}

/** The rules: each with the rows it marks, shown on its own or taken off; and a new one, made of conditions. */
function RulesPop({ sheet, run, onShow, onClose }: {
  sheet: Sheet; run: (what: () => Promise<unknown>, words?: string) => Promise<boolean>; onShow: (id: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [tone, setTone] = useState<RuleTone>("amber");
  const [rows, setRows] = useState<Condition[]>([{ column: sheet.columns[0]?.id ?? "", op: "is", value: "" }]);
  const usable = rows.filter(usableCondition);
  return (
    <Popover onClose={onClose} left={300} width={560}>
      <span className="aug-fs-xs" style={MUTED}>A rule marks the rows meeting its conditions — counted as a filter counts them</span>
      {sheet.rules.length === 0 && <span className="aug-fs-xs" style={MUTED}>No rule yet.</span>}
      {sheet.rules.map(r => (
        <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 0", borderTop: "1px solid var(--b0)" }}>
          <Dot color={RULE_COLOR[r.tone]} title={r.tone} />
          <b>{r.name}</b>
          <span className="aug-fs-xs" style={{ ...MUTED, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            title={filterWords(r.conditions, sheet.columns)}>{filterWords(r.conditions, sheet.columns)}</span>
          <span className="aug-fs-xs" style={NUM}>{formatCount(sheet.rule_rows?.[r.id] ?? 0)} rows</span>
          <Button variant="ghost" size="xs" onClick={() => onShow(r.id)}>Show these</Button>
          <Button variant="ghost" size="xs" onClick={() => void run(() => removeRule(sheet.id, r.id), `Rule ${r.name} taken off`)}>
            Take off
          </Button>
        </div>
      ))}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid var(--b1)", paddingTop: 8 }}>
        <div style={{ display: "flex", gap: 6 }}>
          <Input value={name} onChange={e => setName(e.target.value)} placeholder="A new rule — e.g. Late and still open"
            aria-label="The rule's name" style={{ flex: 1 }} />
          <div style={{ width: 120 }}>
            <Select value={tone} onValueChange={v => setTone(v as RuleTone)}>
              <SelectTrigger aria-label="Its mark's colour" />
              <SelectContent>{RULE_TONES.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
            </Select>
          </div>
        </div>
        <ConditionRows sheet={sheet} rows={rows} setRows={setRows} />
        <Button size="xs" disabled={!name.trim() || usable.length === 0} style={{ alignSelf: "flex-start" }}
          onClick={() => void run(() => saveRule(sheet.id, { name, tone, conditions: usable }), `Rule ${name} kept`)
            .then(ok => { if (ok) { setName(""); setRows([{ column: sheet.columns[0]?.id ?? "", op: "is", value: "" }]); } })}>
          Keep the rule
        </Button>
      </div>
    </Popover>
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
                    `${c.name} taken off`)}>Take off</Button>
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

function usableCondition(r: Condition): boolean {
  return !!r.column && (r.op === "empty" || r.op === "not_empty"
    || (Array.isArray(r.value) ? r.value.length > 0 : String(r.value ?? "").trim() !== ""));
}

/** Conditions on columns, each a column, a way and a value — a filter's, or a rule's. */
function ConditionRows({ sheet, rows, setRows }: {
  sheet: Sheet; rows: Condition[]; setRows: (rows: Condition[]) => void;
}) {
  const colOf = (id: string) => sheet.columns.find(c => c.id === id);
  const set = (i: number, c: Partial<Condition>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...c } : r)));
  return (
    <>
      {rows.map((r, i) => {
        const col = colOf(r.column);
        const ops = opsFor(col?.kind ?? "text");
        const valueless = r.op === "empty" || r.op === "not_empty";
        return (
          // a condition is its place in the list being written
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
                  : col?.kind === "date" || col?.kind === "datetime" ? "2018-10-17" : ""}
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
      <Button variant="outline" size="xs" style={{ alignSelf: "flex-start" }}
        onClick={() => setRows([...rows, { column: sheet.columns[0]?.id ?? "", op: "is", value: "" }])}>
        <Icon name="plus" size={12} /> Condition
      </Button>
    </>
  );
}

function FilterPop({ sheet, conditions, onApply, onClose }: {
  sheet: Sheet; conditions: Condition[]; onApply: (f: Condition[]) => void; onClose: () => void;
}) {
  // a rule's marks are kept as they are; the conditions on columns are written here
  const marks = conditions.filter(c => c.op === "marked" || c.op === "not_marked");
  const [rows, setRows] = useState<Condition[]>(() => {
    const own = conditions.filter(c => c.op !== "marked" && c.op !== "not_marked");
    return own.length ? own : [{ column: sheet.columns[0]?.id ?? "", op: "is", value: "" }];
  });
  return (
    <Popover onClose={onClose} left={150} width={560}>
      <span className="aug-fs-xs" style={MUTED}>Show the rows where every condition holds</span>
      {marks.length > 0 && <span className="aug-fs-xs">{filterWords(marks, sheet.columns, sheet.rules)}</span>}
      <ConditionRows sheet={sheet} rows={rows} setRows={setRows} />
      <div style={{ display: "flex", gap: 6 }}>
        <Button size="xs" onClick={() => onApply([...marks, ...rows.filter(usableCondition)])}>Apply</Button>
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
        // a sort's terms are their place in the order
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
