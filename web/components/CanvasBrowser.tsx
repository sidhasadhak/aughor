"use client";

/**
 * The Data Canvas list — redone to `aughor-v2/CLARITY.md` (2026-10-12): three figures (how many canvases and on how
 * many connections, the one asked something last, the ones not used in 30 days), then what needs a person — a canvas
 * whose connection is gone — then the canvases, each one line: its name, its description, its facts as chips and
 * when it was last used. Sorting and the cards view sit in Tools ▾; Delete is on the row it deletes.
 *
 * What it says is decided in `lib/canvasList.ts`; this file lays it out from the one kit (`components/clarity/kit.tsx`).
 */
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";

import { FilterBox, ToolsMenu, type ToolItem } from "@/components/catalog/CatalogTools";
import { Card, Chip, Empty, Figure, Figures, Label, MUTED, NeedsRow, NeedsYou, NUM, ONE_LINE, Page, ROW, RULE } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Icon } from "@/components/ui/icon";
import { Loading, ReadFailed } from "@/components/ui/states";
import { deleteCanvas, getCanvases, type Canvas, type Connection } from "@/lib/api";
import {
  agoWords, canvasFigures, canvasNeeds, connectionGone, connectionIdOf, connectionKind, dayMonth, filterCanvases, IDLE_DAYS,
  scopeWords, SORT_WORDS, sortCanvases, tablesTitle, type CanvasSort,
} from "@/lib/canvasList";
import { countNoun, formatCount } from "@/lib/format";

interface Props {
  connections: Connection[];
  onSelect: (canvas: Canvas) => void;
  onNew: () => void;
  /** Active workspace — scopes the canvas list to its connections. */
  workspaceId?: string;
}

export function CanvasBrowser({ connections, onSelect, onNew, workspaceId }: Props) {
  const [canvases, setCanvases] = useState<Canvas[]>([]);
  const [loading, setLoading] = useState(true);
  // A failed read used to read as "No Data Canvases yet" — teaching the reader they had none.
  const [failed, setFailed] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [hideAuto, setHideAuto] = useState(false);
  const [sort, setSort] = useState<CanvasSort>("activity");
  const [view, setView] = useState<"list" | "cards">("list");
  const [pendingDelete, setPendingDelete] = useState<Canvas | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    getCanvases(workspaceId)
      .then(list => { setCanvases(list); setFailed(null); })
      .catch(e => { setCanvases([]); setFailed(e instanceof Error ? e.message : String(e)); })
      .finally(() => setLoading(false));
  }, [workspaceId]);
  useEffect(load, [load]);

  const handleDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try { await deleteCanvas(pendingDelete.id); setPendingDelete(null); load(); }
    catch { /* the dialog stays open on the canvas it could not delete */ }
    finally { setDeleting(false); }
  };

  const connOf = useCallback((c: Canvas) => connections.find(x => x.id === connectionIdOf(c)), [connections]);
  // One clock per visit: "9 days ago" is read against the moment the list opened.
  const [now] = useState(() => Date.now());
  const figures = useMemo(() => canvasFigures(canvases, now), [canvases, now]);
  const needs = useMemo(() => canvasNeeds(canvases, connections), [canvases, connections]);
  const shown = useMemo(() => sortCanvases(filterCanvases(canvases, {
    query: search, hideAuto, connectionName: c => connOf(c)?.name ?? "",
  }), sort), [canvases, search, hideAuto, sort, connOf]);

  const tools: ToolItem[] = [
    ...(Object.keys(SORT_WORDS) as CanvasSort[]).map(s => ({
      label: `Sort by ${SORT_WORDS[s]}`, onSelect: () => setSort(s), hidden: s === sort, testId: `canvas-sort-${s}`,
    })),
    { label: view === "list" ? "Show as cards" : "Show as a list", onSelect: () => setView(v => (v === "list" ? "cards" : "list")),
      apart: true, testId: "canvas-view" },
  ];

  const rowProps = (c: Canvas) => ({
    canvas: c, connection: connOf(c), gone: connectionGone(c, connections), now,
    onOpen: () => onSelect(c), onDelete: c.is_legacy ? undefined : () => setPendingDelete(c),
  });

  return (
    <div className="aug-screen">
    <Page testId="canvas-list-page">
      {loading && !canvases.length && !failed && <Loading what="the canvases" />}
      {failed !== null && (
        <div style={{ ...ROW, justifyContent: "space-between" }}>
          <ReadFailed what="the canvases" error={failed} onRetry={load} />
          <Button size="xs" onClick={onNew}>New canvas</Button>
        </div>
      )}

      {!loading && failed === null && canvases.length === 0 && (
        <Card label="Canvases" testId="canvas-none">
          <div style={{ ...ROW, justifyContent: "space-between" }}>
            <Empty>No canvases yet · a canvas keeps questions to one connection and the tables you choose.</Empty>
            <Button size="xs" onClick={onNew}>New canvas</Button>
          </div>
        </Card>
      )}

      {failed === null && canvases.length > 0 && (
        <>
          <Figures testId="canvas-figures">
            <Figure label="Canvases" value={formatCount(figures.total)} testId="fig-canvases"
              sub={`on ${countNoun(figures.connections, "connection")}${figures.auto ? ` · ${formatCount(figures.auto)} auto-generated` : ""}`} />
            {/* When the latest use was, but not which canvas: that one heads the list, sorted by last used. */}
            <Figure label={`Used in the last ${IDLE_DAYS} days`} testId="fig-used"
              value={`${formatCount(figures.total - figures.idle)} of ${formatCount(figures.total)}`}
              sub={[
                figures.lastUsed ? `last ${agoWords(figures.lastUsed.at, now)}` : "none asked anything yet",
                figures.lastUsed && figures.never ? `${formatCount(figures.never)} never used` : "",
              ].filter(Boolean).join(" · ")} />
          </Figures>

          {needs.length > 0 && (
            <NeedsYou testId="canvas-needs" right={formatCount(needs.length)}>
              {needs.map(c => (
                <NeedsRow key={c.id} testId="needs-connection-gone"
                  title={`${c.name}: its connection is gone`}
                  detail="This workspace no longer has the connection it reads — questions here have nothing to read"
                  actions={<>
                    <Button size="xs" variant="secondary" onClick={() => onSelect(c)}>Open</Button>
                    {!c.is_legacy && <Button size="xs" variant="ghost" onClick={() => setPendingDelete(c)}>Delete…</Button>}
                  </>} />
              ))}
            </NeedsYou>
          )}

          <ListSection view={view} total={canvases.length} count={shown.length} sort={sort}
            right={<>
              <FilterBox value={search} onChange={setSearch} placeholder="Filter canvases" width={200} />
              {figures.auto > 0 && (
                <Button size="xs" variant={hideAuto ? "secondary" : "ghost"} aria-pressed={hideAuto}
                  onClick={() => setHideAuto(v => !v)} data-testid="canvas-hide-auto">
                  Hide auto-generated
                </Button>
              )}
              <Button size="xs" onClick={onNew} data-testid="canvas-new">New canvas</Button>
              <ToolsMenu items={tools} testId="canvas-tools" />
            </>}>
            {shown.length === 0 ? (
              <div style={{ ...ROW, gap: 6 }}>
                <Empty>{search.trim() ? `No canvas matches “${search.trim()}”.` : "Every canvas here is auto-generated, and they are hidden."}</Empty>
                <Button size="xs" variant="link" onClick={() => { setSearch(""); setHideAuto(false); }}>Show all</Button>
              </div>
            ) : view === "list" ? (
              <div data-testid="canvas-rows">
                {shown.map((c, i) => <CanvasRow key={c.id} first={i === 0} {...rowProps(c)} />)}
              </div>
            ) : (
              <div data-testid="canvas-cards" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 14 }}>
                {shown.map(c => <CanvasTile key={c.id} {...rowProps(c)} />)}
              </div>
            )}
          </ListSection>
        </>
      )}

      <Dialog open={!!pendingDelete} onOpenChange={open => { if (!open && !deleting) setPendingDelete(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {pendingDelete?.name}?</DialogTitle>
            <DialogDescription>Its saved artifacts and exploration are deleted with it. This cannot be undone.</DialogDescription>
          </DialogHeader>
          <div style={{ ...ROW, justifyContent: "flex-end" }}>
            <Button variant="ghost" size="sm" onClick={() => setPendingDelete(null)} disabled={deleting}>Cancel</Button>
            <Button variant="destructive" size="sm" onClick={handleDelete} disabled={deleting} data-testid="canvas-delete-confirm">
              {deleting ? "Deleting…" : "Delete"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Page>
    </div>
  );
}

// ── The list's section: a card holding rows, or — for the cards view — its label on the ground above the tiles, so no
//    box sits inside another ─────────────────────────────────────────────────────────────────────────────────────────

function ListSection({ view, total, count, sort, right, children }: {
  view: "list" | "cards"; total: number; count: number; sort: CanvasSort; right: ReactNode; children: ReactNode;
}) {
  const meta = (
    <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, whiteSpace: "nowrap" }} data-testid="canvas-list-meta">
      {/* How many is the figure above; the list says only when a filter shows fewer. */}
      {count === total ? "" : `${formatCount(count)} of ${formatCount(total)} · `}sorted by {SORT_WORDS[sort]}
    </span>
  );
  const label = <Label right={<>{meta}{right}</>}>Canvases</Label>;
  if (view === "cards") return <section aria-label="Canvases" data-testid="canvas-list">{label}{children}</section>;
  return (
    <Card label="Canvases" right={<>{meta}{right}</>} testId="canvas-list">{children}</Card>
  );
}

// ── A canvas: one row of the list, or one tile of the cards view ──────────────────────────────────────────────────

interface RowProps {
  canvas: Canvas;
  connection: Connection | undefined;
  gone: boolean;
  now: number;
  onOpen: () => void;
  onDelete?: () => void;
}

/** Its facts as chips: the connection it reads, its tables, and any caveat — said, never left to an absence. */
function Facts({ canvas, connection, gone }: Pick<RowProps, "canvas" | "connection" | "gone">) {
  const docs = canvas.doc_ids?.length ?? 0;
  return (
    <>
      {gone
        ? <Chip tone="amber" title="The connection this canvas reads is not in this workspace">connection gone</Chip>
        : connection && <Chip title={`${connection.name} · ${connectionKind(connection)}`}>{connection.name}</Chip>}
      <Chip title={tablesTitle(canvas)}>{scopeWords(canvas)}</Chip>
      {docs > 0 && <Chip title="Always in reach for work done here; the rest of the documents stay searchable">
        {countNoun(docs, "document")} pinned</Chip>}
      {canvas.is_legacy && <Chip title="Made automatically from a connection, not by a person">auto-generated</Chip>}
    </>
  );
}

function usedWords(c: Canvas, now: number): string {
  return c.last_activity ? `used ${agoWords(c.last_activity, now)}` : "never used";
}

function editedTitle(c: Canvas): string {
  const made = c.created_at ? `made ${dayMonth(c.created_at)}` : "";
  const edited = c.updated_at && c.updated_at !== c.created_at ? `edited ${dayMonth(c.updated_at)}` : "";
  return [made, edited].filter(Boolean).join(" · ");
}

/** The name, the door to the canvas: it gives way to its chips when the line is short, and keeps its whole on hover. */
const NAME_LINK: CSSProperties = { padding: 0, margin: 0, height: "auto", minWidth: 0, maxWidth: "100%", flexShrink: 1,
  overflow: "hidden", color: "var(--t1)", fontWeight: 600 };

function DeleteButton({ name, onDelete }: { name: string; onDelete: () => void }) {
  return (
    <Button variant="ghost" size="icon-xs" title="Delete canvas" aria-label={`Delete ${name}`}
      onClick={e => { e.stopPropagation(); onDelete(); }}
      className="opacity-0 group-hover/canvas:opacity-100 focus-visible:opacity-100 transition-opacity">
      <Icon name="trash" size={13} />
    </Button>
  );
}

function CanvasRow({ canvas, connection, gone, now, onOpen, onDelete, first }: RowProps & { first: boolean }) {
  return (
    <div data-testid="canvas-row" className="group/canvas" onClick={onOpen}
      style={{ ...(first ? {} : RULE), display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", gap: 12,
        alignItems: "center", padding: "8px 2px", cursor: "pointer" }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ ...ROW, flexWrap: "nowrap", minWidth: 0 }}>
          <Button variant="link" size="xs" onClick={e => { e.stopPropagation(); onOpen(); }} title={`Open ${canvas.name}`}
            style={NAME_LINK}>
            <span className="aug-fs-chrome" style={ONE_LINE}>{canvas.name}</span>
          </Button>
          <Facts canvas={canvas} connection={connection} gone={gone} />
        </div>
        {canvas.description && (
          <div className="aug-fs-xs" title={canvas.description} style={{ ...MUTED, ...ONE_LINE }}>{canvas.description}</div>
        )}
      </div>
      <span className="aug-fs-sm" title={editedTitle(canvas)} style={{ ...MUTED, ...NUM, whiteSpace: "nowrap" }}>
        {usedWords(canvas, now)}
      </span>
      <span style={{ width: 24, display: "inline-flex", justifyContent: "flex-end" }}>
        {onDelete && <DeleteButton name={canvas.name} onDelete={onDelete} />}
      </span>
    </div>
  );
}

function CanvasTile({ canvas, connection, gone, now, onOpen, onDelete }: RowProps) {
  return (
    <div data-testid="canvas-tile" className="group/canvas" onClick={onOpen}
      style={{ background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "12px 14px",
        minWidth: 0, display: "flex", flexDirection: "column", gap: 8, cursor: "pointer" }}>
      <div style={{ ...ROW, flexWrap: "nowrap" }}>
        <Button variant="link" size="xs" onClick={e => { e.stopPropagation(); onOpen(); }} title={`Open ${canvas.name}`}
          style={NAME_LINK}>
          <span className="aug-fs-chrome" style={ONE_LINE}>{canvas.name}</span>
        </Button>
        <span style={{ marginLeft: "auto" }}>{onDelete && <DeleteButton name={canvas.name} onDelete={onDelete} />}</span>
      </div>
      {canvas.description && (
        <div className="aug-fs-xs" title={canvas.description} style={{ ...MUTED, ...ONE_LINE }}>{canvas.description}</div>
      )}
      <div style={{ ...ROW, gap: 6 }}>
        <Facts canvas={canvas} connection={connection} gone={gone} />
        <span className="aug-fs-xs" title={editedTitle(canvas)} style={{ ...MUTED, ...NUM, marginLeft: "auto", whiteSpace: "nowrap" }}>
          {usedWords(canvas, now)}
        </span>
      </div>
    </div>
  );
}
