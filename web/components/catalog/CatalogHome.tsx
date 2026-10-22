"use client";

/**
 * The Catalog with nothing chosen — every catalog at once, redone to `aughor-v2/CLARITY.md` (2026-10-12, the approved
 * `design-mockups/catalog.html` frame 1): four figures (catalogs · tables, each once · rows · turned off), what needs
 * a person, each catalog with how far it is explored beside the largest tables — and Favorites and Recent one tap away
 * in the bar, as they were.
 *
 * Read from what the screen already holds — the tree and each catalog's datasets — plus the search index's status;
 * nothing here queries a warehouse or calls a model.
 */
import { useEffect, useMemo, useState } from "react";

import {
  Card, Chip, Empty, Figure, Figures, HBars, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, Page, ROW, RULE, Bar,
} from "@/components/clarity/kit";
import { FilterBox, LIST_CELL, LIST_HEAD, PAIR, StateMark, favorites, recents } from "@/components/catalog/CatalogTools";
import { IcoCatalog, IcoSchema, IcoTable } from "@/components/icons/catalog";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Segmented } from "@/components/ui/segmented";
import { Loading, ReadFailed } from "@/components/ui/states";
import type { CatalogTree, KnowledgeStatus } from "@/lib/api";
import {
  catalogItems, catalogRows, duplicateWords, homeFigures, largestTables, unsearchable,
  type CatalogItem, type CatalogRow, type Duplicate, type Views,
} from "@/lib/catalogSummary";
import { compactNumber, countNoun, formatCount } from "@/lib/format";

type Mode = "all" | "favorites" | "recents";

export function CatalogHome({ tree, treeError, onRetryTree, views, dups, status, label, onOpenCatalog, onRetryViews, onPick }: {
  tree: CatalogTree | null;
  treeError: string | null;
  onRetryTree: () => void;
  views: Views;
  dups: Duplicate[];
  /** The search index's status, read once by the screen; null — the read failed. */
  status: KnowledgeStatus | null | undefined;
  label: (connType: string) => string;
  onOpenCatalog: (connId: string) => void;
  onRetryViews: (connId: string) => void;
  onPick: (item: CatalogItem) => void;
}) {
  const [mode, setMode] = useState<Mode>("all");

  const entries = useMemo(() => tree?.sections.flatMap(s => s.entries) ?? [], [tree]);

  return (
    <Page testId="catalog-home">
      <div style={ROW}>
        <Segmented label="Catalog view" value={mode} onChange={setMode} options={[
          { value: "all", label: "All" },
          { value: "favorites", label: <><Icon name="star" size={12} />Favorites</> },
          { value: "recents", label: <><Icon name="clock" size={12} />Recent</> },
        ]} />
      </div>
      {mode !== "all" ? <Saved mode={mode} tree={tree} onPick={onPick} />
        : tree === null ? (treeError ? <ReadFailed what="the catalog" error={treeError} onRetry={onRetryTree} /> : <Loading what="the catalog" />)
        : entries.length === 0 ? <Empty>No connections yet. Add one to get started.</Empty>
        : <Overview entries={entries} views={views} dups={dups} label={label} status={status}
            onOpenCatalog={onOpenCatalog} onRetryViews={onRetryViews} />}
    </Page>
  );
}

function Overview({ entries, views, dups, label, status, onOpenCatalog, onRetryViews }: {
  entries: CatalogTree["sections"][number]["entries"];
  views: Views;
  dups: Duplicate[];
  label: (connType: string) => string;
  status: KnowledgeStatus | null | undefined;
  onOpenCatalog: (connId: string) => void;
  onRetryViews: (connId: string) => void;
}) {
  const f = homeFigures(entries, dups, views);
  const rows = catalogRows(entries, dups, views, label);
  const largest = largestTables(entries, dups, 8);
  // The index speaks for the whole org; NEEDS YOU on this page speaks for the catalogs listed on it ("2 baef6c3e
  // documents can't be searched" reached a workspace that never held baef6c3e, 2026-10-22).
  const docs = unsearchable(status).filter(g => g.connId === null || entries.some(e => e.conn_id === g.connId));
  const nameOf = (id: string | null) => entries.find(e => e.conn_id === id)?.name ?? id ?? "";
  const failed = entries.filter(e => views[e.conn_id] === null);
  const schemas = entries.reduce((a, e) => a + e.schemas.length, 0);
  const offTotal = f.off.schemas + f.off.tables;
  const pctOf = (id: string) => { const r = rows.find(x => x.id === id)?.explored; return typeof r === "object" ? r.percent : null; };

  const offSub = [
    f.off.read === 0 && f.off.failed === 0 ? "reading…"
      : offTotal === 0 ? "no schema or table set aside"
      : [f.off.schemas ? countNoun(f.off.schemas, "schema") : "", f.off.tables ? countNoun(f.off.tables, "table") : ""]
        .filter(Boolean).join(" · "),
    f.off.failed ? `${countNoun(f.off.failed, "catalog")} not read` : "",
  ].filter(Boolean).join(" · ");

  return (
    <>
      <Figures testId="catalog-home-figures">
        <Figure label="Catalogs" value={formatCount(entries.length)} testId="fig-catalogs"
          sub={<span title={f.catalogs.join(" · ")} style={ONE_LINE}>{f.catalogs.join(" · ")}</span>} />
        <Figure label="Tables" value={formatCount(f.tables)} testId="fig-tables"
          title={f.twice ? "Each table counted once: a second connection lists some of them again" : undefined}
          sub={f.twice ? <Chip tone="amber" testId="fig-tables-twice">{`+${formatCount(f.twice)} listed twice`}</Chip>
            : `in ${countNoun(schemas, "schema")}`} />
        <Figure label="Rows" value={f.rows == null ? "—" : compactNumber(f.rows)} testId="fig-rows"
          title={f.rows == null ? undefined : `${formatCount(f.rows)} rows, each table once`}
          sub={f.rows == null ? "no table carries a row count"
            : `in ${countNoun(f.counted, "table")}${f.uncounted ? ` · ${formatCount(f.uncounted)} not counted` : ""}`} />
        <Figure label="Turned off" value={f.off.read === 0 && f.off.failed === 0 ? "—" : formatCount(offTotal)} testId="fig-off"
          title="Schemas and tables a person turned off for analysis — never explored, never asked" sub={offSub} />
      </Figures>

      <NeedsYou testId="catalog-home-needs"
        empty={`Nothing needs you${status === null ? " · the search index's status could not be read" : ""}`}>
        {[
          ...dups.map(d => {
            const pct = pctOf(d.copy.id);
            return (
              <NeedsRow key={`dup-${d.copy.id}-${d.of.id}`} testId="needs-listed-twice" title={duplicateWords(d)}
                detail={`counted once here${pct != null ? ` · ${d.copy.name}'s copy is ${pct}% explored` : ""}`}
                actions={<Button size="xs" variant="secondary" onClick={() => onOpenCatalog(d.copy.id)}
                  title={`Open ${d.copy.name} to compare it with ${d.of.name}`}>Compare</Button>} />
            );
          }),
          ...docs.map(g => (
            <NeedsRow key={`docs-${g.connId ?? "uploads"}`} testId="needs-unsearchable"
              title={`${countNoun(g.documents, g.connId ? `${nameOf(g.connId)} document` : "uploaded document")} can't be searched`}
              detail={`registered, but ${formatCount(g.missing)} of ${formatCount(g.claimed)} parts are missing from the search index`} />
          )),
          ...failed.map(e => (
            <NeedsRow key={`failed-${e.conn_id}`} testId="needs-unread"
              title={`${e.name}: how far it is explored could not be read`}
              actions={<Button size="xs" variant="ghost" onClick={() => onRetryViews(e.conn_id)}>Retry</Button>} />
          )),
        ]}
      </NeedsYou>

      <div style={PAIR}>
        <Card label="Catalogs" right="bar: how far the platform has explored it" testId="catalog-home-catalogs"
          style={{ flex: "1.6 1 480px" }}>
          <CatalogsTable rows={rows} onOpen={onOpenCatalog} />
        </Card>
        <Card label="Largest tables" right="counted rows · each once" testId="catalog-home-largest"
          style={{ flex: "1 1 300px" }}>
          {largest.length ? (
            <HBars bars={largest.map(t => ({
              key: `${t.connId}:${t.schema}:${t.name}`,
              name: <span style={{ fontFamily: "var(--font-mono)" }}>{t.name}</span>,
              meta: t.catalog, value: t.rows, shown: compactNumber(t.rows),
              tip: `${t.catalog} · ${t.schema}.${t.name}: ${formatCount(t.rows)} rows`,
            }))} />
          ) : <Empty>No table carries a row count yet.</Empty>}
        </Card>
      </div>
    </>
  );
}

const CAT_GRID = {
  display: "grid", gridTemplateColumns: "minmax(140px, 1.3fr) 56px 84px minmax(110px, 150px) minmax(96px, 120px)",
  columnGap: 0, alignItems: "stretch",
} as const;
const HEAD = LIST_HEAD;
const CELL = LIST_CELL;

function CatalogsTable({ rows, onOpen }: { rows: CatalogRow[]; onOpen: (connId: string) => void }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <div className="aug-fs-sm" style={{ ...CAT_GRID, minWidth: 520 }}>
        <span className="aug-fs-xs" style={HEAD}>Catalog</span>
        <span className="aug-fs-xs" style={{ ...HEAD, textAlign: "right" }}>Tables</span>
        <span className="aug-fs-xs" style={{ ...HEAD, textAlign: "right" }}>Rows</span>
        <span className="aug-fs-xs" style={HEAD}>Explored</span>
        <span className="aug-fs-xs" style={HEAD}>State</span>
        {rows.map(r => (
          <div key={r.id} data-testid="catalog-home-row" style={{ display: "contents" }}>
            <div style={CELL}>
              <Button variant="link" size="xs" onClick={() => onOpen(r.id)}
                style={{ padding: 0, height: "auto", maxWidth: "100%", alignSelf: "flex-start" }}>
                <span style={{ ...ONE_LINE, fontWeight: 500 }}>{r.name}</span>
              </Button>
              <div className="aug-fs-xs" title={r.what} style={{ ...MUTED, ...ONE_LINE }}>{r.what}</div>
            </div>
            <div style={{ ...CELL, textAlign: "right", ...NUM }}>{formatCount(r.tables)}</div>
            <div style={{ ...CELL, textAlign: "right", ...NUM, color: r.rows == null ? "var(--t3)" : "var(--t1)" }}
              title={r.uncounted && r.rows != null ? `${formatCount(r.uncounted)} of its tables are not counted` : undefined}>
              {r.rows != null ? compactNumber(r.rows) : r.tables ? "not counted" : "—"}
            </div>
            <div style={CELL}><Explored e={r.explored} /></div>
            <div style={CELL}><StateMark s={r.state} /></div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Explored({ e }: { e: CatalogRow["explored"] }) {
  if (e === "reading") return <span className="aug-fs-xs" style={MUTED}>reading…</span>;
  if (e === "failed") return <span className="aug-fs-xs" style={MUTED}>not read</span>;
  if (e.percent == null) {
    return <span className="aug-fs-xs" style={MUTED} title={e.of ? `${e.given} of ${e.of} schemas carry a number` : "Nothing to explore"}>
      not given</span>;
  }
  return (
    <span style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 36px", gap: 8, alignItems: "center" }}
      title={e.given < e.of ? `${e.given} of ${e.of} schemas carry a number` : undefined}>
      <Bar value={e.percent} max={100} color={e.percent >= 100 ? "var(--grn3)" : "var(--chart-1)"} />
      <span className="aug-fs-xs" style={{ textAlign: "right", color: "var(--t2)", ...NUM }}>{e.percent}%</span>
    </span>
  );
}

// ── Favorites and Recent ──────────────────────────────────────────────────────────────────────────────────────────

const ICON = { Catalog: <IcoCatalog color="var(--t2)" size={14} />, Schema: <IcoSchema color="var(--blue3)" size={14} />, Table: <IcoTable size={14} /> };

function Saved({ mode, tree, onPick }: { mode: "favorites" | "recents"; tree: CatalogTree | null; onPick: (it: CatalogItem) => void }) {
  const [filter, setFilter] = useState("");
  const [favs, setFavs] = useState<string[]>([]);
  const [recent, setRecent] = useState<string[]>([]);
  useEffect(() => { setFavs(favorites.read()); setRecent(recents.read()); }, [mode]);
  const byKey = useMemo(() => new Map(catalogItems(tree).map(i => [i.key, i])), [tree]);
  const q = filter.toLowerCase();
  const items = (mode === "favorites" ? favs : recent).map(k => byKey.get(k)).filter((i): i is CatalogItem => !!i)
    .filter(i => !q || i.name.toLowerCase().includes(q) || i.path.toLowerCase().includes(q));

  return (
    <Card label={mode === "favorites" ? "Favorites" : "Recent"} testId={`catalog-${mode}`}
      right={<FilterBox value={filter} onChange={setFilter} width={180} />}>
      {tree === null ? <Loading what="the catalog" />
        : items.length === 0 ? (
          <Empty>{filter ? "Nothing here matches that filter."
            : mode === "favorites" ? "No favorites yet — star a catalog, schema or table from its Tools menu."
            : "Nothing opened yet — a table you open appears here."}</Empty>
        ) : items.map((it, i) => {
          const fav = favs.includes(it.key);
          return (
            <div key={it.key} data-testid="catalog-saved-row"
              style={{ ...ROW, flexWrap: "nowrap", gap: 10, padding: "7px 0", ...(i ? RULE : {}) }}>
              <span style={{ display: "inline-flex", color: "var(--t3)" }}>{ICON[it.type]}</span>
              <div style={{ minWidth: 0, flex: 1 }}>
                <Button variant="link" size="xs" onClick={() => onPick(it)} style={{ padding: 0, height: "auto", maxWidth: "100%" }}>
                  <span style={{ ...ONE_LINE, fontFamily: it.type === "Catalog" ? undefined : "var(--font-mono)" }}>{it.name}</span>
                </Button>
                <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }}>{it.path}</div>
              </div>
              <span className="aug-fs-xs" style={MUTED}>{it.type}</span>
              <Button variant="ghost" size="icon-xs" onClick={() => setFavs(favorites.toggle(it.key))}
                title={fav ? "Remove from favorites" : "Add to favorites"} aria-pressed={fav}
                style={{ color: fav ? "var(--amb4)" : "var(--t3)" }}>
                <Icon name="star" size={13} className={fav ? "aug-icon-filled" : undefined} />
              </Button>
            </div>
          );
        })}
    </Card>
  );
}
