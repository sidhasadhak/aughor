"use client";

/**
 * The pieces the Catalog's right panel is built from (`aughor-v2/CLARITY.md`): the header line every selection opens
 * on, the one Tools menu, a state said as a mark and a word, bars that are shares of a whole, the list of tables —
 * and the tools that used to sit open in each panel (the Briefings switch, a connector's sync and files, the compiled
 * schema documents, the sample grid), moved here unchanged in what they do, to live behind Settings, Docs, a tab or
 * Tools ▾.
 *
 * Favorites and recents keep the keys they were always stored under, so nothing a person starred is lost.
 */
import { DropdownMenu } from "@radix-ui/themes";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { SqlResultTable } from "@/components/AugTable";
import { Bar, Chip, Empty, Label, MUTED, NUM, ONE_LINE, ROW, RULE } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SkeletonRows } from "@/components/ui/motion";
import { Loading, ReadFailed } from "@/components/ui/states";
import { Switch } from "@/components/ui/switch";
import {
  getConnectionSettings, getKnowledgeStatus, listDocuments, sampleTable, updateConnectionSettings,
  type DistributionProfile, type DocumentEntry, type KnowledgeStatus, type TableSample,
} from "@/lib/api";
import type { Know, ScopeTable, StateWord } from "@/lib/catalogSummary";
import { getApiBase } from "@/lib/config";
import { compactNumber, formatCount, formatTimestamp } from "@/lib/format";

// ── Favorites and recents ─────────────────────────────────────────────────────────────────────────────────────────

const FAVS_KEY = "aug.catalog.favs";
const RECENTS_KEY = "aug.catalog.recents";

function readList(key: string): string[] {
  try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch { return []; }
}
function writeList(key: string, v: string[]) {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* this browser keeps none */ }
}

export const favorites = {
  read: () => readList(FAVS_KEY),
  toggle(key: string): string[] {
    const cur = readList(FAVS_KEY);
    const next = cur.includes(key) ? cur.filter(k => k !== key) : [key, ...cur];
    writeList(FAVS_KEY, next);
    return next;
  },
};

export const recents = {
  read: () => readList(RECENTS_KEY),
  push(key: string) { writeList(RECENTS_KEY, [key, ...readList(RECENTS_KEY).filter(k => k !== key)].slice(0, 15)); },
};

/** Whether `key` is a favorite, and the menu item that stars or unstars it. */
export function useFavorite(key: string) {
  const [on, setOn] = useState(false);
  useEffect(() => { setOn(favorites.read().includes(key)); }, [key]);
  return { on, toggle: () => setOn(favorites.toggle(key).includes(key)) };
}

// ── Header, tabs' row, Tools ▾ ────────────────────────────────────────────────────────────────────────────────────

export interface ToolItem {
  label: string;
  onSelect: () => void;
  title?: string;
  danger?: boolean;
  /** A rule above it — the destructive one sits apart. */
  apart?: boolean;
  hidden?: boolean;
  testId?: string;
}

/** Every tool a selection has, in one menu (CLARITY §3: "Tools in one menu"). */
export function ToolsMenu({ items, testId }: { items: ToolItem[]; testId?: string }) {
  const shown = items.filter(i => !i.hidden);
  if (!shown.length) return null;
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        <Button variant="ghost" size="xs" data-testid={testId ?? "catalog-tools"}>
          Tools <Icon name="chevd" size={12} />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content size="1" align="end">
        {shown.map((i, n) => (
          <span key={`${n}-${i.label}`} style={{ display: "contents" }}>
            {i.apart && n > 0 && <DropdownMenu.Separator />}
            <DropdownMenu.Item onSelect={i.onSelect} title={i.title} color={i.danger ? "red" : undefined}
              data-testid={i.testId}>
              {i.label}
            </DropdownMenu.Item>
          </span>
        ))}
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  );
}

/** The line a selection opens on: where it is, its name, what it is, its state — and Ask about it · Tools ▾. */
export function PanelHead({ crumbs, name, mono, what, chips, actions, testId }: {
  crumbs?: string[]; name: string; mono?: boolean; what?: string; chips?: ReactNode; actions?: ReactNode; testId?: string;
}) {
  return (
    <div data-testid={testId} style={{ ...ROW, flexWrap: "nowrap", gap: 10, padding: "10px 22px", borderBottom: "1px solid var(--b0)",
      background: "var(--bg-0)", flexShrink: 0, minWidth: 0 }}>
      {crumbs?.map(c => (
        <span key={`crumb-${c}`} className="aug-fs-sm" style={{ ...MUTED, whiteSpace: "nowrap" }}>{c} ›</span>
      ))}
      <span className={mono ? "aug-fs-chrome" : "aug-fs-ui"} title={name}
        style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 600, fontFamily: mono ? "var(--font-mono)" : undefined }}>
        {name}
      </span>
      {what && <span className="aug-fs-sm" title={what} style={{ ...MUTED, ...ONE_LINE }}>{what}</span>}
      {chips}
      <span style={{ marginLeft: "auto", ...ROW, flexWrap: "nowrap" }}>{actions}</span>
    </div>
  );
}

/** Two cards side by side, wrapping one under the other when the panel is narrow. */
export const PAIR: CSSProperties = { display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-start" };

// ── Marks ─────────────────────────────────────────────────────────────────────────────────────────────────────────

const STATE_COLOR: Record<StateWord["tone"], string> = {
  up: "var(--grn4)", accent: "var(--blue4)", amber: "var(--amb4)", muted: "var(--t3)",
};

/** A state as its mark and word, coloured by what it means: ✓ watched daily, ● exploring, listed twice. */
export function StateMark({ s, title }: { s: StateWord; title?: string }) {
  return (
    <span className="aug-fs-sm" title={title} style={{ color: STATE_COLOR[s.tone], whiteSpace: "nowrap" }}>
      {s.mark ? `${s.mark} ` : ""}{s.word}
    </span>
  );
}

/** The state as a chip beside a name, with how far it is explored: "✓ watched daily · 100%". */
export function StateChip({ s, percent }: { s: StateWord; percent?: number | null }) {
  const tone = s.tone === "up" ? "up" : s.tone === "accent" ? "accent" : s.tone === "amber" ? "amber" : "plain";
  return (
    <Chip tone={tone} testId="catalog-state-chip">
      {s.mark ? `${s.mark} ` : ""}{s.word}{percent != null ? ` · ${percent}%` : ""}
    </Chip>
  );
}

/** What the platform knows, each a share of its whole — a full bar is all of it; unknown is hatched and said. */
export function ShareBars({ rows, testId }: { rows: Know[]; testId?: string }) {
  return (
    <div data-testid={testId} style={{ display: "grid", gridTemplateColumns: "minmax(110px, 170px) minmax(0, 1fr) auto",
      gap: "9px 12px", alignItems: "center" }}>
      {rows.map(r => {
        const counted = r.n != null && r.of != null;
        const shown = counted && !r.short ? `${formatCount(r.n)} of ${formatCount(r.of)}` : r.short;
        return (
          <div key={r.key} style={{ display: "contents" }}>
            <div className="aug-fs-sm" style={{ minWidth: 0 }}>
              <div style={{ ...ONE_LINE, color: "var(--t1)" }}>{r.label}</div>
              <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }}>{r.meta}</div>
            </div>
            <span role="img" aria-label={`${r.label}: ${shown}${r.note ? ` — ${r.note}` : ""}`} title={r.note || undefined}>
              <Bar value={r.share ?? 1} max={1} color={r.share === 1 ? "var(--grn3)" : "var(--chart-1)"} hatched={r.share == null} />
            </span>
            <span className="aug-fs-sm" title={r.note || undefined}
              style={{ textAlign: "right", color: r.share != null ? "var(--t2)" : "var(--t3)", whiteSpace: "nowrap", ...NUM }}>
              {shown}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── The tables list ───────────────────────────────────────────────────────────────────────────────────────────────

const GRID: CSSProperties = {
  display: "grid", gridTemplateColumns: "minmax(150px, 1.3fr) minmax(120px, 1fr) 92px 100px 128px minmax(120px, 150px)",
  columnGap: 0, alignItems: "stretch",
};
/** A list's column heading and cell. No gap between columns — the space is the cell's padding — so the rule under each
 *  row runs the whole width instead of breaking at every column. */
export const LIST_HEAD: CSSProperties = { ...MUTED, textTransform: "uppercase", letterSpacing: ".06em", padding: "2px 12px 6px 2px",
  whiteSpace: "nowrap" };
export const LIST_CELL: CSSProperties = { ...RULE, padding: "8px 12px 8px 2px", minWidth: 0, display: "flex",
  flexDirection: "column", justifyContent: "center" };
const HEAD = LIST_HEAD;
const CELL = LIST_CELL;
const RIGHT: CSSProperties = { textAlign: "right", ...NUM };

/** Each table: its name (the door to it), its business object, rows, questions asked of it, metrics that read it,
 *  its state. "not counted" — never 0 — for a table whose rows are not counted. */
export function TablesList({ tables, onOpen, showSchema, testId }: {
  tables: ScopeTable[]; onOpen: (t: ScopeTable) => void; showSchema?: boolean; testId?: string;
}) {
  if (!tables.length) return <Empty>No tables.</Empty>;
  return (
    <div data-testid={testId} style={{ overflowX: "auto" }}>
      <div className="aug-fs-sm" style={{ ...GRID, minWidth: 640 }}>
        <span className="aug-fs-xs" style={HEAD}>Table</span>
        <span className="aug-fs-xs" style={HEAD}>Business object</span>
        <span className="aug-fs-xs" style={{ ...HEAD, ...RIGHT }}>Rows</span>
        <span className="aug-fs-xs" style={{ ...HEAD, ...RIGHT }}>Questions</span>
        <span className="aug-fs-xs" style={{ ...HEAD, ...RIGHT }}>Metrics read it</span>
        <span className="aug-fs-xs" style={HEAD}>State</span>
        {tables.map(t => (
          <div key={t.key} data-testid="catalog-table-row" style={{ display: "contents" }}>
            <div style={CELL}>
              <Button variant="link" size="xs" onClick={() => onOpen(t)} title={`Open ${t.schema}.${t.name}`}
                style={{ fontFamily: "var(--font-mono)", padding: 0, height: "auto", maxWidth: "100%", alignSelf: "flex-start" }}>
                <span style={ONE_LINE}>{t.name}</span>
              </Button>
              {showSchema && <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }}>{t.schema}</div>}
            </div>
            <div style={{ ...CELL, ...ONE_LINE, color: t.object ? "var(--t1)" : "var(--t3)" }}>
              {t.object?.words ?? "—"}
            </div>
            <div style={{ ...CELL, ...RIGHT, color: t.rows == null ? "var(--t3)" : "var(--t1)" }}
              title={t.rows == null ? "Its rows are not counted" : `${formatCount(t.rows)} rows`}>
              {t.rows == null ? "not counted" : compactNumber(t.rows)}
            </div>
            <div style={{ ...CELL, ...RIGHT, color: t.questions ? "var(--t1)" : "var(--t3)" }} title={t.questionsNote || undefined}>
              {t.questions ? `${t.questions.n}/${t.questions.of}` : "—"}
            </div>
            <div style={{ ...CELL, ...RIGHT, color: t.metrics ? "var(--t1)" : "var(--t3)" }}
              title={t.metrics == null ? "The metrics could not be read" : t.metrics ? undefined : "No approved metric reads it"}>
              {t.metrics == null ? "not read" : t.metrics || "—"}
            </div>
            <div style={CELL}><StateMark s={t.state} /></div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** A filter box above a list. */
export function FilterBox({ value, onChange, placeholder, width = 220 }: {
  value: string; onChange: (v: string) => void; placeholder?: string; width?: number;
}) {
  return (
    <Input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder ?? "Filter…"}
      aria-label={placeholder ?? "Filter"} style={{ width, flexShrink: 0 }} />
  );
}

// ── Moved tools: the Briefings switch, a connector's sync and files ──────────────────────────────────────────────

/** Per-connection opt-in for the Briefing workspace. Opt-out by default (on unless turned off here); persisted via the
 *  connection's settings. */
export function BriefingsToggle({ connId }: { connId: string }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    getConnectionSettings(connId)
      .then(s => { if (alive) setEnabled(s.briefings_enabled !== false); })
      .catch(() => { if (alive) setEnabled(true); });
    return () => { alive = false; };
  }, [connId]);

  const toggle = async () => {
    if (enabled === null || saving) return;
    const next = !enabled;
    setEnabled(next);
    setSaving(true);
    try { await updateConnectionSettings(connId, { briefings_enabled: next }); }
    catch { setEnabled(!next); }
    finally { setSaving(false); }
  };

  return (
    <label className="aug-fs-sm" style={{ ...ROW, flexWrap: "nowrap", justifyContent: "space-between", color: "var(--t2)" }}>
      <span>Show this connection in the Briefing</span>
      <Switch checked={enabled === true} disabled={enabled === null || saving} onChange={toggle}
        aria-label="Enable briefings for this connection" />
    </label>
  );
}

const SYNCABLE = ["stripe", "hubspot", "salesforce", "s3"];
const KNOWLEDGE = ["confluence", "notion"];
const FILE_UPLOAD = ["local_upload"];

/** Whether a connector has sync, knowledge sync or files to manage — the Settings card shows only then. */
export function hasConnectorActions(connType: string): boolean {
  return SYNCABLE.includes(connType) || KNOWLEDGE.includes(connType) || FILE_UPLOAD.includes(connType);
}

export function ConnectorActions({ connId, connType }: { connId: string; connType: string }) {
  const [status, setStatus] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [files, setFiles] = useState<Array<{ filename: string; table_name: string; size_bytes: number }>>([]);
  const [uploading, setUploading] = useState(false);
  const [restoreMsg, setRestoreMsg] = useState<string | null>(null);

  const isSyncable = SYNCABLE.includes(connType);
  const isKnowledge = KNOWLEDGE.includes(connType);
  const isFileUpload = FILE_UPLOAD.includes(connType);

  useEffect(() => {
    if (isSyncable || isKnowledge) {
      const endpoint = isKnowledge
        ? `${getApiBase()}/connections/${connId}/knowledge-sync/status`
        : `${getApiBase()}/connections/${connId}/sync-status`;
      fetch(endpoint).then(r => r.json())
        .then(d => setStatus(d.last_sync ? `Last sync: ${formatTimestamp(d.last_sync)}` : "Never synced"))
        .catch(() => setStatus(null));
    }
    if (isFileUpload) {
      fetch(`${getApiBase()}/connections/${connId}/files`).then(r => r.json())
        .then(d => setFiles(d.files ?? []))
        .catch(() => {});
    }
  }, [connId, connType, isSyncable, isKnowledge, isFileUpload]);

  const handleSync = async () => {
    setSyncing(true);
    const endpoint = isKnowledge
      ? `${getApiBase()}/connections/${connId}/knowledge-sync`
      : `${getApiBase()}/connections/${connId}/sync`;
    try {
      await fetch(endpoint, { method: "POST" });
      setStatus("Sync triggered — running in background…");
    } catch {
      setStatus("Sync failed");
    }
    setSyncing(false);
  };

  const handleFileUpload = async (file: File) => {
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const resp = await fetch(`${getApiBase()}/connections/${connId}/files`, { method: "POST", body: form });
      if (resp.ok) {
        const fresh = await fetch(`${getApiBase()}/connections/${connId}/files`).then(r => r.json());
        setFiles(fresh.files ?? []);
      }
    } catch { /* the list below stays as it was */ }
    setUploading(false);
  };

  const handleDelete = async (filename: string) => {
    await fetch(`${getApiBase()}/connections/${connId}/files/${encodeURIComponent(filename)}`, { method: "DELETE" });
    setFiles(f => f.filter(x => x.filename !== filename));
  };

  const handleRestoreSamples = async () => {
    setRestoreMsg("Restoring…");
    try {
      const r = await fetch(`${getApiBase()}/connections/${connId}/restore-samples`, { method: "POST" });
      setRestoreMsg(r.ok ? "Sample data restored — refresh to see it." : "Restore failed.");
    } catch {
      setRestoreMsg("Restore failed.");
    }
  };

  if (!isSyncable && !isKnowledge && !isFileUpload) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {(isSyncable || isKnowledge) && (
        <div style={ROW}>
          <Button variant="secondary" size="xs" onClick={handleSync} disabled={syncing}>
            {syncing ? "Syncing…" : isKnowledge ? "Sync knowledge" : "Sync now"}
          </Button>
          {status && <span className="aug-fs-xs" style={MUTED}>{status}</span>}
        </div>
      )}
      {isFileUpload && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <label className="aug-fs-xs" style={{ ...ROW, cursor: uploading ? "not-allowed" : "pointer", color: "var(--blue4)" }}>
            <Icon name="upload" size={12} />
            {uploading ? "Uploading…" : "Upload CSV, Parquet or Excel"}
            <input type="file" accept=".csv,.tsv,.parquet,.parq,.xlsx,.xls,.json" style={{ display: "none" }}
              disabled={uploading} onChange={e => { const f = e.target.files?.[0]; if (f) handleFileUpload(f); }} />
          </label>
          {files.map(f => (
            <div key={f.filename} className="aug-fs-xs" style={{ ...ROW, flexWrap: "nowrap", color: "var(--t2)" }}>
              <span style={{ fontFamily: "var(--font-mono)", flex: 1, ...ONE_LINE }}>{f.filename}</span>
              <span style={MUTED}>{Math.round(f.size_bytes / 1024)}KB</span>
              <Button variant="ghost" size="xs" onClick={() => handleDelete(f.filename)} title="Remove">
                <Icon name="close" size={11} />
              </Button>
            </div>
          ))}
          <div style={ROW}>
            <Button variant="ghost" size="xs" onClick={handleRestoreSamples}
              title="Re-add the bundled sample schemas you previously removed">
              Restore sample data
            </Button>
            {restoreMsg && <span className="aug-fs-xs" style={MUTED}>{restoreMsg}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Moved tools: the compiled schema documents ────────────────────────────────────────────────────────────────────

/** What the ontology compiled for this connection (or one schema of it) — the only per-connection part of the corpus:
 *  `doctree::<connection>::<schema>`, one part per table, rebuilt when intelligence runs. The registry is not the
 *  index: when they disagree, both numbers appear. Uploads live in Documents, shared by every connection. */
export function SchemaDocs({ connId, name, schema, onOpenDocuments }: {
  connId: string; name: string; schema?: string; onOpenDocuments?: () => void;
}) {
  const [docs, setDocs] = useState<DocumentEntry[]>([]);
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const prefix = schema ? `doctree::${connId}::${schema}` : `doctree::${connId}::`;

  useEffect(() => {
    let alive = true;
    let docsFailed: string | null = null;
    setLoading(true);
    Promise.all([
      listDocuments().catch(e => { docsFailed = String(e?.message || e); return [] as DocumentEntry[]; }),
      getKnowledgeStatus().catch(() => null),
    ]).then(([d, st]) => {
      if (!alive) return;
      setDocs(d.filter(x => (schema ? x.doc_id === prefix : x.doc_id.startsWith(prefix))));
      setStatus(st);
      setFailed(docsFailed);
      setLoading(false);
    });
    return () => { alive = false; };
  }, [prefix, schema, reload]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {loading ? <Loading what="the schema documentation" />
        : failed !== null ? <ReadFailed what="the schema documentation" error={failed} onRetry={() => setReload(n => n + 1)} />
        : docs.length === 0 ? (
          <Empty>Nothing compiled for {name} yet — it is written when intelligence runs over a schema.</Empty>
        ) : docs.map((d, i) => {
          const drift = status?.consistency.mismatched_documents?.[d.doc_id];
          return (
            <div key={d.doc_id} className="aug-fs-sm" style={{ ...ROW, flexWrap: "nowrap", justifyContent: "space-between",
              padding: "7px 0", ...(i ? RULE : {}) }}>
              <span style={{ color: "var(--t1)", ...ONE_LINE }}>{d.title}</span>
              {drift
                ? <Chip tone="amber" title="The registry lists more parts than the search index holds">
                    {`${drift.store} searchable of ${drift.registry}`}
                  </Chip>
                : <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>{`${d.chunk_count} part${d.chunk_count === 1 ? "" : "s"}`}</span>}
            </div>
          );
        })}
      <div className="aug-fs-xs" style={{ ...MUTED, ...ROW, gap: 4 }}>
        Your own documents are shared by every connection, so they live in
        {onOpenDocuments
          ? <Button variant="link" size="xs" onClick={onOpenDocuments}>Documents</Button>
          : " Documents"}
      </div>
    </div>
  );
}

// ── Moved tools: the sample grid and a column's distribution ─────────────────────────────────────────────────────

export function SampleGrid({ connId, tableName, schemaName }: { connId: string; tableName: string; schemaName?: string }) {
  const [data, setData] = useState<TableSample | null>(null);
  const [loading, setLoad] = useState(false);
  const [error, setErr] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const fetched = useRef(false);

  useEffect(() => { setData(null); setErr(null); fetched.current = false; }, [connId, tableName, schemaName, reload]);
  useEffect(() => {
    if (fetched.current) return;
    fetched.current = true;
    setLoad(true);
    sampleTable(connId, tableName, 200, schemaName)
      .then(d => {
        // Three distinct states: execution error ≠ empty table ≠ data.
        if (d.error) setErr(d.error);
        else setData(d);
      })
      .catch(e => setErr(`Could not load sample: ${(e as Error).message}`))
      .finally(() => setLoad(false));
  }, [connId, tableName, schemaName, reload]);

  if (loading) return <div style={{ flex: 1, padding: 16 }} aria-label="Loading sample data"><SkeletonRows rows={8} /></div>;
  if (error) return <div style={{ padding: "16px 22px" }}><ReadFailed what="the sample" error={error} onRetry={() => setReload(n => n + 1)} /></div>;
  if (!data || data.rows.length === 0) return <div style={{ padding: "16px 22px" }}><Empty>The table is empty — no rows to show.</Empty></div>;
  return (
    <div style={{ flex: 1, overflow: "auto", padding: "12px 22px" }}>
      <Label right={`${formatCount(data.rows.length)} row${data.rows.length === 1 ? "" : "s"}`}>First 200 rows</Label>
      <SqlResultTable columns={data.columns} rows={data.rows as unknown[][]} maxHeight={520} />
    </div>
  );
}

const DIST_LABEL: Record<string, string> = {
  fraction_0_1: "0–1 ratio", normal: "Normal", concentrated: "Concentrated", skewed_right: "Right-skewed",
  skewed_left: "Left-skewed", uniform: "Uniform", bimodal: "Bimodal",
};

function miniBarHeights(shape: string): number[] {
  switch (shape) {
    case "normal":       return [4, 8, 22, 24, 16, 6];
    case "fraction_0_1": return [6, 14, 24, 16, 8, 4];
    case "concentrated": return [3, 10, 24, 18, 8, 3];
    case "skewed_right": return [24, 20, 14, 8, 4, 2];
    case "skewed_left":  return [2, 4, 8, 14, 20, 24];
    case "uniform":      return [20, 22, 22, 21, 20, 21];
    case "bimodal":      return [20, 8, 4, 8, 22, 16];
    default:             return [10, 14, 18, 16, 12, 8];
  }
}

/** A numeric column's distribution from the explorer's profile: its shape, quartiles and range. */
export function ColumnDistribution({ d }: { d: DistributionProfile }) {
  const barH = miniBarHeights(d.shape);
  const maxH = Math.max(...barH);
  const fmt = (n: number | null | undefined) => (n == null ? "—" : compactNumber(n, 1));
  return (
    <div className="aug-fs-xs" style={{ ...ROW, gap: 14, padding: "6px 4px 8px 30px" }}>
      <div aria-hidden style={{ display: "flex", alignItems: "flex-end", gap: 1.5, height: 24, width: 64, flexShrink: 0 }}>
        {barH.map((h, i) => (
          <div key={i} style={{ flex: 1, height: `${h}px`, background: h >= maxH * 0.6 ? "var(--chart-1)" : "var(--b2)",
            borderRadius: "2px 2px 0 0" }} />
        ))}
      </div>
      {([["p25", d.p25], ["median", d.p50], ["p75", d.p75], ["mean", d.mean]] as const).map(([label, value]) => (
        <span key={label} style={{ display: "inline-flex", flexDirection: "column", alignItems: "center", ...NUM }}>
          <span style={MUTED}>{label}</span>
          <span style={{ color: "var(--t1)" }}>{fmt(value)}</span>
        </span>
      ))}
      {d.min != null && d.max != null && (
        <span style={{ display: "inline-flex", flexDirection: "column", alignItems: "center", ...NUM }}>
          <span style={MUTED}>range</span>
          <span style={{ color: "var(--t2)" }}>{fmt(d.min)}–{fmt(d.max)}</span>
        </span>
      )}
      <Chip>{DIST_LABEL[d.shape] ?? d.shape}</Chip>
    </div>
  );
}
