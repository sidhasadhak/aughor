"use client";

/**
 * AddDataPanel — Databricks-style "Add data" experience as a full page.
 *
 * Renders like any other page (not a slide-in panel). Presents the connector
 * registry (`/connectors/types`) with real brand logos, a "Files" section for
 * uploads, and category-grouped connector cards. Picking a database/warehouse/
 * application source reveals a dynamic config form built from that connector's
 * `fields`. Picking "Create or modify table" opens a file-upload experience
 * that ingests CSV / Parquet / Excel / JSON into the built-in **Workspace**
 * (a DuckDB-backed scratch space) as new tables.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  addConnection,
  getConnectorTypes,
  uploadFileToConnection,
  analyzeConnectionFile,
  listConnectionFiles,
  deleteConnectionFile,
  listConnectionSchemas,
  createConnectionSchema,
  type ConnectorTypeInfo,
  type ConnectionFile,
  type FileAnalysis,
} from "@/lib/api";
import { BrandLogo, brandColor } from "@/components/BrandLogos";

const WORKSPACE_ID = "workspace";

// ── Display metadata per connector ────────────────────────────────────────────

const META: Record<string, { label: string; blurb: string; badge?: string }> = {
  duckdb:       { label: "DuckDB",       blurb: "Local analytical database file" },
  postgres:     { label: "PostgreSQL",   blurb: "Connect to a Postgres database" },
  bigquery:     { label: "BigQuery",     blurb: "Google Cloud data warehouse" },
  snowflake:    { label: "Snowflake",    blurb: "Cloud data warehouse" },
  mysql:        { label: "MySQL",        blurb: "Connect to a MySQL database" },
  motherduck:   { label: "MotherDuck",   blurb: "DuckDB in the cloud", badge: "New" },
  exasol:       { label: "Exasol",       blurb: "In-memory analytics database", badge: "New" },
  gsheets:      { label: "Google Sheets", blurb: "Read worksheets as tables", badge: "New" },
  local_upload: { label: "Create or modify table", blurb: "Upload CSV, Parquet, Excel or JSON into your Workspace" },
  s3:           { label: "Amazon S3",    blurb: "Object storage bucket" },
  federated:    { label: "Federated",    blurb: "Combine existing connections" },
  stripe:       { label: "Stripe",       blurb: "Payments & billing data", badge: "Preview" },
  hubspot:      { label: "HubSpot",      blurb: "CRM & marketing data" },
  salesforce:   { label: "Salesforce",   blurb: "CRM objects & pipelines" },
  confluence:   { label: "Confluence",   blurb: "Team wiki & knowledge" },
  notion:       { label: "Notion",       blurb: "Docs & databases" },
};

const CATEGORY_ORDER: Array<{ id: string; label: string }> = [
  { id: "built-in",   label: "Databases" },
  { id: "warehouse",  label: "Data warehouses" },
  { id: "api",        label: "Applications" },
];

const meta = (t: string) => META[t] ?? { label: t, blurb: "" };

const fmtBytes = (n: number) =>
  n < 1024 ? `${n} B` : n < 1_048_576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1_048_576).toFixed(1)} MB`;

// ── Cards ──────────────────────────────────────────────────────────────────────

function LogoBox({ type, size = 36 }: { type: string; size?: number }) {
  const c = brandColor(type);
  return (
    <span style={{ width: size, height: size, borderRadius: 8, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
      background: `color-mix(in srgb, ${c} 12%, var(--bg-2))`, border: `1px solid color-mix(in srgb, ${c} 26%, transparent)` }}>
      <BrandLogo type={type} size={Math.round(size * 0.56)} />
    </span>
  );
}

function FileTile({ info, onClick }: { info: ConnectorTypeInfo; onClick: () => void }) {
  const m = meta(info.type);
  return (
    <button onClick={onClick}
      style={{ display: "flex", flexDirection: "column", gap: 10, padding: 16, borderRadius: 10, cursor: "pointer",
        background: "var(--bg-1)", border: "1px solid var(--b1)", textAlign: "left", transition: "all .12s", width: "100%" }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = brandColor(info.type); (e.currentTarget as HTMLElement).style.background = "var(--bg-2)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--b1)"; (e.currentTarget as HTMLElement).style.background = "var(--bg-1)"; }}
    >
      <LogoBox type={info.type} size={34} />
      <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{m.label}</span>
      <span style={{ fontSize: 11.5, color: "var(--t3)", lineHeight: 1.45 }}>{m.blurb}</span>
    </button>
  );
}

function ConnectorCard({ info, onClick }: { info: ConnectorTypeInfo; onClick: () => void }) {
  const m = meta(info.type);
  return (
    <button onClick={onClick}
      style={{ display: "flex", alignItems: "center", gap: 11, padding: "11px 13px", borderRadius: 9, cursor: "pointer",
        background: "var(--bg-1)", border: "1px solid var(--b1)", textAlign: "left", transition: "all .12s", width: "100%" }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = brandColor(info.type); (e.currentTarget as HTMLElement).style.background = "var(--bg-2)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--b1)"; (e.currentTarget as HTMLElement).style.background = "var(--bg-1)"; }}
    >
      <LogoBox type={info.type} size={34} />
      <span style={{ minWidth: 0, flex: 1 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.label}</span>
          {m.badge && <span style={{ fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 4, background: "color-mix(in srgb, var(--blue4,#60a5fa) 16%, transparent)", color: "var(--blue4,#60a5fa)", whiteSpace: "nowrap" }}>{m.badge}</span>}
        </span>
        <span style={{ display: "block", fontSize: 11, color: "var(--t3)", marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.blurb}</span>
      </span>
    </button>
  );
}

const S: React.CSSProperties = { width: "100%", fontSize: 12, padding: "8px 10px", borderRadius: 6, background: "var(--bg-0)", border: "1px solid var(--b1)", color: "var(--t1)", outline: "none", fontFamily: "inherit" };
const L: React.CSSProperties = { fontSize: 11, color: "var(--t3)", marginBottom: 5, display: "block", fontWeight: 500 };
const sectionLabel: React.CSSProperties = { fontSize: 11, fontWeight: 700, color: "var(--t2)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 12, display: "flex", alignItems: "center", gap: 7 };

// ── Workspace file-upload view ──────────────────────────────────────────────────

const ACCEPT = ".csv,.tsv,.parquet,.parq,.xlsx,.xls,.json";

// Cast targets offered per column (must mirror the backend allow-list).
const CAST_TYPES = ["VARCHAR", "BIGINT", "INTEGER", "DOUBLE", "DECIMAL", "BOOLEAN", "DATE", "TIMESTAMP", "TIME"];

// Normalize a DuckDB type like "DECIMAL(18,3)" to a dropdown base option.
const baseType = (t: string) => t.toUpperCase().replace(/\(.*\)/, "").trim();

type Staged = { file: File; analysis: FileAnalysis };

function WorkspaceUploader({ onAdded }: { onAdded: () => void }) {
  const [files, setFiles]       = useState<ConnectionFile[]>([]);
  const [schemas, setSchemas]   = useState<string[]>(["main"]);
  const [drag, setDrag]         = useState(false);
  const [error, setError]       = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Review-flow state
  const [queue, setQueue]       = useState<File[]>([]);
  const [staged, setStaged]     = useState<Staged | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [tableName, setTableName] = useState("");
  const [schema, setSchema]     = useState("main");
  const [chosen, setChosen]     = useState<Record<string, string>>({});  // col -> type
  const [newSchema, setNewSchema] = useState("");
  const [addingSchema, setAddingSchema] = useState(false);

  const reload = useCallback(() => {
    listConnectionFiles(WORKSPACE_ID).then(setFiles).catch(() => setFiles([]));
    listConnectionSchemas(WORKSPACE_ID).then(setSchemas).catch(() => setSchemas(["main"]));
  }, []);
  useEffect(() => { reload(); }, [reload]);

  // Analyze the next queued file and open the review panel.
  const analyzeNext = useCallback(async (nextQueue: File[]) => {
    if (nextQueue.length === 0) { setStaged(null); return; }
    const [head, ...rest] = nextQueue;
    setQueue(rest);
    setAnalyzing(true); setError("");
    try {
      const analysis = await analyzeConnectionFile(WORKSPACE_ID, head);
      setStaged({ file: head, analysis });
      setTableName(analysis.suggested_table_name);
      setSchema("main");
      // Default each column to its detected type (no override sent unless changed).
      setChosen(Object.fromEntries(analysis.columns.map(c => [c.name, baseType(c.detected_type)])));
    } catch (ex: unknown) {
      setError((ex as Error).message);
      // Skip the bad file, continue with the rest.
      if (rest.length) analyzeNext(rest); else setStaged(null);
    } finally {
      setAnalyzing(false);
    }
  }, []);

  const handleFiles = useCallback((list: FileList | null) => {
    if (!list || list.length === 0) return;
    const arr = Array.from(list);
    analyzeNext(arr);
    if (inputRef.current) inputRef.current.value = "";
  }, [analyzeNext]);

  const commit = useCallback(async () => {
    if (!staged) return;
    setCommitting(true); setError("");
    try {
      // Only send columns whose chosen type differs from what DuckDB inferred.
      const columnTypes: Record<string, string> = {};
      for (const c of staged.analysis.columns) {
        const pick = chosen[c.name];
        if (pick && pick !== baseType(c.detected_type)) columnTypes[c.name] = pick;
      }
      await uploadFileToConnection(WORKSPACE_ID, staged.file, {
        tableName: tableName.trim() || staged.analysis.suggested_table_name,
        schema,
        columnTypes,
      });
      reload(); onAdded();
      analyzeNext(queue);  // advance to next file or finish
    } catch (ex: unknown) {
      setError((ex as Error).message);
    } finally {
      setCommitting(false);
    }
  }, [staged, chosen, tableName, schema, queue, reload, onAdded, analyzeNext]);

  const cancelReview = () => { setStaged(null); setQueue([]); setError(""); };

  const addSchema = async () => {
    const name = newSchema.trim();
    if (!name) return;
    setAddingSchema(true);
    try {
      const created = await createConnectionSchema(WORKSPACE_ID, name);
      const next = await listConnectionSchemas(WORKSPACE_ID);
      setSchemas(next); setSchema(created); setNewSchema("");
    } catch (ex: unknown) { setError((ex as Error).message); }
    finally { setAddingSchema(false); }
  };

  const remove = async (f: ConnectionFile) => {
    try { await deleteConnectionFile(WORKSPACE_ID, f.filename, f.schema); reload(); onAdded(); }
    catch (ex: unknown) { setError((ex as Error).message); }
  };

  const conflict = staged
    ? files.find(f => f.schema === schema && f.table_name === (tableName.trim() || staged.analysis.suggested_table_name))
    : undefined;

  // ── Review panel ──────────────────────────────────────────────────────────
  if (staged) {
    const a = staged.analysis;
    const mismatches = a.columns.filter(c => c.suggested_type && c.suggested_type !== baseType(c.detected_type)).length;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <LogoBox type="local_upload" size={42} />
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>Configure import</p>
            <p style={{ fontSize: 11.5, color: "var(--t3)", marginTop: 1 }}>
              <strong style={{ color: "var(--t2)" }}>{staged.file.name}</strong> · {a.row_count.toLocaleString()} rows · {a.columns.length} columns
              {queue.length > 0 && <> · {queue.length} more queued</>}
            </p>
          </div>
        </div>

        {/* Destination */}
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 200px" }}>
            <label style={L}>Table name</label>
            <input style={{ ...S, fontFamily: "var(--font-mono)" }} value={tableName}
              onChange={e => setTableName(e.target.value)} placeholder={a.suggested_table_name} />
          </div>
          <div style={{ flex: "1 1 200px" }}>
            <label style={L}>Schema</label>
            <select style={{ ...S, cursor: "pointer" }} value={schema} onChange={e => setSchema(e.target.value)}>
              {schemas.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>

        {/* New schema */}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input style={{ ...S, maxWidth: 220 }} value={newSchema} onChange={e => setNewSchema(e.target.value)}
            placeholder="New schema name…" onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addSchema(); } }} />
          <button type="button" onClick={addSchema} disabled={!newSchema.trim() || addingSchema}
            style={{ fontSize: 12, padding: "8px 12px", borderRadius: 6, cursor: newSchema.trim() ? "pointer" : "not-allowed", background: "transparent", color: "var(--t2)", border: "1px solid var(--b1)", whiteSpace: "nowrap" }}>
            + Add schema
          </button>
        </div>

        {conflict && (
          <div style={{ fontSize: 11.5, color: "var(--amb4)", padding: "9px 12px", borderRadius: 6, background: "color-mix(in srgb, var(--amb4) 10%, var(--bg-1))", border: "1px solid color-mix(in srgb, var(--amb4) 35%, transparent)" }}>
            A table <strong style={{ fontFamily: "var(--font-mono)" }}>{schema}.{conflict.table_name}</strong> already exists — importing will <strong>replace</strong> it. Rename above to keep both.
          </div>
        )}

        {/* Columns + types */}
        <div>
          <p style={sectionLabel}>
            Columns · {a.columns.length}
            {mismatches > 0 && <span style={{ fontSize: 9.5, fontWeight: 600, padding: "1px 7px", borderRadius: 4, background: "color-mix(in srgb, var(--amb4) 16%, transparent)", color: "var(--amb4)", textTransform: "none", letterSpacing: 0 }}>{mismatches} type suggestion{mismatches > 1 ? "s" : ""}</span>}
          </p>
          <div style={{ border: "1px solid var(--b1)", borderRadius: 8, overflow: "hidden" }}>
            {a.columns.map((c, i) => {
              const detected = baseType(c.detected_type);
              const suggest = c.suggested_type && c.suggested_type !== detected ? c.suggested_type : null;
              const opts = Array.from(new Set([detected, ...CAST_TYPES]));
              const changed = chosen[c.name] && chosen[c.name] !== detected;
              return (
                <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", background: i % 2 ? "var(--bg-1)" : "var(--bg-0)", borderTop: i ? "1px solid var(--b0)" : "none" }}>
                  <span style={{ flex: "1 1 0", minWidth: 0, fontSize: 12, fontWeight: 500, color: "var(--t1)", fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</span>
                  <span style={{ fontSize: 10.5, color: "var(--t4)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>{c.detected_type}</span>
                  <select value={chosen[c.name] ?? detected} onChange={e => setChosen(p => ({ ...p, [c.name]: e.target.value }))}
                    style={{ fontSize: 11.5, padding: "5px 8px", borderRadius: 5, background: "var(--bg-2)", color: changed ? "var(--blue4,#60a5fa)" : "var(--t2)", border: `1px solid ${changed ? "var(--blue4,#60a5fa)" : "var(--b1)"}`, cursor: "pointer", fontFamily: "var(--font-mono)", flexShrink: 0, width: 120 }}>
                    {opts.map(o => <option key={o} value={o}>{o}</option>)}
                  </select>
                  {suggest && (
                    <button type="button" onClick={() => setChosen(p => ({ ...p, [c.name]: suggest }))}
                      title={`DuckDB read this as text but the values look like ${suggest}`}
                      style={{ fontSize: 10, fontWeight: 600, padding: "3px 8px", borderRadius: 5, cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0,
                        background: chosen[c.name] === suggest ? "transparent" : "color-mix(in srgb, var(--amb4) 16%, transparent)",
                        color: "var(--amb4)", border: "1px solid color-mix(in srgb, var(--amb4) 35%, transparent)" }}>
                      {chosen[c.name] === suggest ? "✓ " : "→ "}{suggest}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
          <p style={{ fontSize: 10.5, color: "var(--t4)", marginTop: 6 }}>
            Overridden types use <span style={{ fontFamily: "var(--font-mono)" }}>TRY_CAST</span> — values that don&apos;t fit become NULL rather than failing the import.
          </p>
        </div>

        {/* Preview */}
        {a.preview.columns.length > 0 && (
          <div>
            <p style={sectionLabel}>Preview · first {a.preview.rows.length} rows</p>
            <div style={{ overflowX: "auto", border: "1px solid var(--b1)", borderRadius: 8 }}>
              <table style={{ borderCollapse: "collapse", fontSize: 11, width: "100%" }}>
                <thead>
                  <tr>
                    {a.preview.columns.map(col => (
                      <th key={col} style={{ textAlign: "left", padding: "7px 10px", color: "var(--t3)", fontWeight: 600, borderBottom: "1px solid var(--b1)", background: "var(--bg-2)", whiteSpace: "nowrap", fontFamily: "var(--font-mono)" }}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {a.preview.rows.map((row, ri) => (
                    <tr key={ri}>
                      {row.map((v, ci) => (
                        <td key={ci} style={{ padding: "6px 10px", color: v === null ? "var(--t4)" : "var(--t2)", borderBottom: "1px solid var(--b0)", whiteSpace: "nowrap", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", fontStyle: v === null ? "italic" : "normal" }}>{v === null ? "NULL" : v}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {error && <p style={{ fontSize: 12, color: "var(--red4)" }}>{error}</p>}

        <div style={{ display: "flex", gap: 10 }}>
          <button type="button" onClick={commit} disabled={committing}
            style={{ fontSize: 13, fontWeight: 600, padding: "9px 20px", borderRadius: 6, cursor: committing ? "not-allowed" : "pointer", background: "var(--blue3)", color: "#fff", border: "none", opacity: committing ? 0.6 : 1 }}>
            {committing ? "Importing…" : conflict ? "Replace table" : "Add table"}
          </button>
          {queue.length > 0 && (
            <button type="button" onClick={() => analyzeNext(queue)} disabled={committing}
              style={{ fontSize: 13, padding: "9px 16px", borderRadius: 6, cursor: "pointer", background: "transparent", color: "var(--t3)", border: "1px solid var(--b1)" }}>Skip</button>
          )}
          <button type="button" onClick={cancelReview}
            style={{ fontSize: 13, padding: "9px 16px", borderRadius: 6, cursor: "pointer", background: "transparent", color: "var(--t3)", border: "1px solid var(--b1)" }}>Cancel</button>
        </div>
      </div>
    );
  }

  // ── Dropzone + existing tables ────────────────────────────────────────────
  const grouped = schemas.map(s => ({ schema: s, items: files.filter(f => f.schema === s) }));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <LogoBox type="local_upload" size={42} />
        <div>
          <p style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>Create or modify table</p>
          <p style={{ fontSize: 11.5, color: "var(--t3)", marginTop: 1 }}>
            Upload files into your <strong style={{ color: "var(--t2)" }}>Workspace</strong> — a DuckDB-backed
            space. Review column types and pick a schema before each table is created.
          </p>
        </div>
      </div>

      {/* Dropzone */}
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); handleFiles(e.dataTransfer.files); }}
        style={{
          border: `1.5px dashed ${drag ? brandColor("local_upload") : "var(--b1)"}`,
          borderRadius: 12, padding: "34px 24px", textAlign: "center", cursor: "pointer",
          background: drag ? "color-mix(in srgb, var(--blue4,#60a5fa) 8%, var(--bg-1))" : "var(--bg-1)",
          transition: "all .12s",
        }}
      >
        <input ref={inputRef} type="file" accept={ACCEPT} multiple hidden
          onChange={e => handleFiles(e.target.files)} />
        <BrandLogo type="local_upload" size={30} />
        <p style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", marginTop: 10 }}>
          {analyzing ? "Analyzing…" : "Drop files here or click to browse"}
        </p>
        <p style={{ fontSize: 11.5, color: "var(--t3)", marginTop: 4 }}>
          CSV · TSV · Parquet · Excel (xlsx/xls) · JSON
        </p>
      </div>

      {error && <p style={{ fontSize: 12, color: "var(--red4)" }}>{error}</p>}

      {/* Existing tables, grouped by schema */}
      <div>
        <p style={sectionLabel}>Tables in Workspace{files.length ? ` · ${files.length}` : ""}</p>
        {files.length === 0 ? (
          <p style={{ fontSize: 12, color: "var(--t4)" }}>No tables yet. Upload a file to create your first one.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {grouped.filter(g => g.items.length > 0).map(g => (
              <div key={g.schema}>
                <p style={{ fontSize: 10.5, fontWeight: 700, color: "var(--t4)", fontFamily: "var(--font-mono)", marginBottom: 7 }}>{g.schema}</p>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {g.items.map(f => (
                    <div key={`${f.schema}.${f.filename}`} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 13px", borderRadius: 8, background: "var(--bg-1)", border: "1px solid var(--b1)" }}>
                      <span style={{ width: 30, height: 30, borderRadius: 6, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-2)", border: "1px solid var(--b1)", fontSize: 9, fontWeight: 700, color: "var(--t3)", textTransform: "uppercase" }}>
                        {f.extension.replace(".", "")}
                      </span>
                      <span style={{ minWidth: 0, flex: 1 }}>
                        <span style={{ display: "block", fontSize: 12.5, fontWeight: 600, color: "var(--t1)", fontFamily: "var(--font-mono)" }}>{f.table_name}</span>
                        <span style={{ display: "block", fontSize: 11, color: "var(--t3)", marginTop: 1 }}>{f.filename} · {fmtBytes(f.size_bytes)}{f.column_types && Object.keys(f.column_types).length > 0 ? ` · ${Object.keys(f.column_types).length} typed` : ""}</span>
                      </span>
                      <button onClick={() => remove(f)} title="Remove table"
                        style={{ width: 26, height: 26, borderRadius: 6, cursor: "pointer", background: "transparent", border: "1px solid var(--b1)", color: "var(--t4)", display: "flex", alignItems: "center", justifyContent: "center" }}
                        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "var(--red4)"; (e.currentTarget as HTMLElement).style.borderColor = "var(--red4)"; }}
                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "var(--t4)"; (e.currentTarget as HTMLElement).style.borderColor = "var(--b1)"; }}
                      >
                        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M3 4h10M6.5 4V2.5h3V4M5 4l.5 9h5l.5-9" /></svg>
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export function AddDataPanel({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [types, setTypes]     = useState<ConnectorTypeInfo[]>([]);
  const [search, setSearch]   = useState("");
  const [picked, setPicked]   = useState<ConnectorTypeInfo | null>(null);
  const [name, setName]       = useState("");
  const [values, setValues]   = useState<Record<string, string>>({});
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState("");

  useEffect(() => { getConnectorTypes().then(setTypes).catch(() => setTypes([])); }, []);

  // Esc to close (form first, then page)
  useEffect(() => {
    const fn = (e: KeyboardEvent) => { if (e.key === "Escape") { picked ? setPicked(null) : onClose(); } };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [picked, onClose]);

  const q = search.toLowerCase();
  const visible = useMemo(
    () => types.filter(t => t.type !== "federated" && (!q || meta(t.type).label.toLowerCase().includes(q) || t.type.includes(q))),
    [types, q],
  );
  const fileSources = visible.filter(t => t.category === "file");
  const grouped = useMemo(
    () => CATEGORY_ORDER.map(cat => ({ ...cat, items: visible.filter(t => t.category === cat.id) })).filter(g => g.items.length > 0),
    [visible],
  );

  const isUpload = picked?.type === "local_upload";

  const pick = (info: ConnectorTypeInfo) => {
    setPicked(info); setError("");
    setName(meta(info.type).label);
    setValues(Object.fromEntries(info.fields.map(f => [f.key, ""])));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!picked) return;
    setSaving(true); setError("");
    try {
      const m: Record<string, string> = {};
      let dsn = ""; let schema: string | undefined;
      for (const f of picked.fields) {
        const v = (values[f.key] ?? "").trim();
        if (f.key === "dsn") dsn = v;
        else if (f.key === "schema_name") schema = v || undefined;
        else if (v) m[f.key] = v;
      }
      await addConnection(name.trim() || meta(picked.type).label, picked.type, dsn, schema, m);
      onAdded();
      onClose();
    } catch (ex: unknown) {
      setError((ex as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ height: "100%", overflowY: "auto", background: "var(--bg-0)" }}>
      {/* Header bar */}
      <div style={{ position: "sticky", top: 0, zIndex: 5, display: "flex", alignItems: "center", gap: 14, padding: "16px 28px", borderBottom: "1px solid var(--b1)", background: "var(--bg-0)" }}>
        {picked ? (
          <button onClick={() => setPicked(null)} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "var(--t3)", background: "none", border: "none", cursor: "pointer", fontFamily: "inherit" }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = "var(--t1)"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = "var(--t3)"}>
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M10 12 6 8l4-4" /></svg>
            All sources
          </button>
        ) : (
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 600, color: "var(--t1)" }}>Add data</h1>
            <p style={{ fontSize: 11.5, color: "var(--t3)", marginTop: 2 }}>Connect to a data source, upload local files, or read from an application.</p>
          </div>
        )}
        <button onClick={onClose} title="Close (Esc)"
          style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, fontSize: 12, padding: "6px 12px", borderRadius: 6, cursor: "pointer", background: "transparent", border: "1px solid var(--b1)", color: "var(--t3)", fontFamily: "inherit" }}
          onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = "var(--t1)"}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = "var(--t3)"}>
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M12 4 4 12M4 4l8 8" /></svg>
          Done
        </button>
      </div>

      {/* Body */}
      <div style={{ maxWidth: 940, margin: "0 auto", padding: "26px 28px 64px" }}>
        {!picked ? (
          <>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search data sources…"
              style={{ ...S, maxWidth: 420, marginBottom: 28 }} />

            {/* Files */}
            {fileSources.length > 0 && (
              <div style={{ marginBottom: 30 }}>
                <p style={sectionLabel}>Files</p>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12 }}>
                  {fileSources.map(info => <FileTile key={info.type} info={info} onClick={() => pick(info)} />)}
                </div>
              </div>
            )}

            {/* Connectors */}
            {grouped.map(g => (
              <div key={g.id} style={{ marginBottom: 28 }}>
                <p style={sectionLabel}>{g.label}</p>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: 10 }}>
                  {g.items.map(info => <ConnectorCard key={info.type} info={info} onClick={() => pick(info)} />)}
                </div>
              </div>
            ))}

            {visible.length === 0 && <p style={{ fontSize: 12, color: "var(--t4)" }}>No sources match.</p>}
          </>
        ) : isUpload ? (
          <div style={{ maxWidth: 760 }}>
            <WorkspaceUploader onAdded={onAdded} />
          </div>
        ) : (
          <form onSubmit={submit} style={{ maxWidth: 520, display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <LogoBox type={picked.type} size={42} />
              <div>
                <p style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>Connect {meta(picked.type).label}</p>
                <p style={{ fontSize: 11.5, color: "var(--t3)", marginTop: 1 }}>{meta(picked.type).blurb}</p>
              </div>
            </div>

            <div>
              <label style={L}>Connection name</label>
              <input style={S} value={name} onChange={e => setName(e.target.value)} placeholder={meta(picked.type).label} required />
            </div>

            {picked.fields.length === 0 && (
              <p style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.5, padding: "10px 12px", background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: 6 }}>
                No configuration needed — create the connection, then manage it from the catalog.
              </p>
            )}

            {picked.fields.map(f => (
              <div key={f.key}>
                <label style={L}>{f.label}</label>
                <input
                  style={{ ...S, fontFamily: f.secret || f.key === "dsn" ? "var(--font-mono)" : "inherit" }}
                  type={f.secret ? "password" : "text"}
                  placeholder={f.placeholder}
                  value={values[f.key] ?? ""}
                  onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                  required={f.key === "dsn"}
                />
              </div>
            ))}

            {error && <p style={{ fontSize: 12, color: "var(--red4)" }}>{error}</p>}

            <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
              <button type="submit" disabled={saving}
                style={{ fontSize: 13, fontWeight: 600, padding: "9px 20px", borderRadius: 6, cursor: saving ? "not-allowed" : "pointer", background: "var(--blue3)", color: "#fff", border: "none", opacity: saving ? 0.6 : 1 }}>
                {saving ? "Connecting…" : "Create connection"}
              </button>
              <button type="button" onClick={() => setPicked(null)}
                style={{ fontSize: 13, padding: "9px 16px", borderRadius: 6, cursor: "pointer", background: "transparent", color: "var(--t3)", border: "1px solid var(--b1)" }}>Back</button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
