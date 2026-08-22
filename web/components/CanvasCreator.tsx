"use client";

import { useEffect, useMemo, useState } from "react";
import { useRichSchema } from "@/lib/schema-context";
import {
  createCanvas,
  getCatalogTree,
  suggestCanvasName,
  type Connection,
  type Canvas,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Icon as Glyph, type IconName } from "@/components/ui/icon";

// ── Icon helper ───────────────────────────────────────────────────────────────

function Icon({ name, size = 14, color = "currentColor" }: { name: IconName; size?: number; color?: string }) {
  return (
    <span style={{ color, display: "inline-flex", flexShrink: 0 }}>
      <Glyph name={name} size={size} />
    </span>
  );
}

const CLOSE_ICON: IconName = "close";
const CHECK_ICON: IconName = "check";
const CHEVR_ICON: IconName = "chevr";
const DB_ICON: IconName = "db";
const TABLE_ICON: IconName = "table";
const SEARCH_ICON: IconName = "search";
const REFRESH_ICON: IconName = "refresh";

// ── CanvasCreator ─────────────────────────────────────────────────────────────

interface Props {
  connections: Connection[];
  onCreated: (canvas: Canvas) => void;
  onCancel: () => void;
}

type AllTablesSel = { kind: "all" };
type TablesSel = { kind: "tables"; tables: Set<string> };
type Selection = AllTablesSel | TablesSel | null;

export function CanvasCreator({ connections, onCreated, onCancel }: Props) {
  // Navigation: null = catalog (connection list); else browsing a connection's tables
  const [connId, setConnId] = useState<string | null>(null);
  const selectedConn = connections.find(c => c.id === connId);

  const [allTables, setAllTables] = useState<string[]>([]);
  const [loadingTables, setLoadingTables] = useState(false);
  const [search, setSearch] = useState("");

  // Selection is committed per connection; switching connections resets it.
  const [selection, setSelection] = useState<Selection>(null);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // The rich schema comes from the shared per-connection cache; the catalog-tree
  // fallback below is unchanged, because an EMPTY schema (not just a failed one) is
  // still the case it exists to cover.
  const { schema: sharedSchema, error: schemaError } = useRichSchema(connId);
  useEffect(() => {
    if (!connId) return;
    setLoadingTables(true);
    setAllTables([]);
    Promise.resolve()
      .then(() => {
        if (schemaError) throw new Error("schema unavailable");
        if (!sharedSchema) return;                      // still loading
        if (sharedSchema.tables.length > 0) {
          setAllTables(sharedSchema.tables.map((t: { name: string }) => t.name));
        } else {
          throw new Error("empty schema");
        }
      })
      .catch(() => {
        getCatalogTree()
          .then(tree => {
            const entry = tree.sections.flatMap(s => s.entries).find(e => e.conn_id === connId);
            const names = entry?.schemas.flatMap(sch => sch.tables.map(t => t.name)) ?? [];
            setAllTables(names);
          })
          .catch(() => setAllTables([]));
      })
      .finally(() => setLoadingTables(false));
  }, [connId, sharedSchema, schemaError]);

  const filteredTables = useMemo(
    () => allTables.filter(t => t.toLowerCase().includes(search.toLowerCase())),
    [allTables, search],
  );

  const openConnection = (id: string) => {
    setConnId(id);
    setSearch("");
    setSelection(null);
    setError("");
  };

  const backToCatalog = () => {
    setConnId(null);
    setSearch("");
  };

  const toggleAll = () => {
    setSelection(prev => (prev?.kind === "all" ? null : { kind: "all" }));
  };

  const toggleTable = (t: string) => {
    setSelection(prev => {
      const next = new Set(prev?.kind === "tables" ? prev.tables : []);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next.size ? { kind: "tables", tables: next } : null;
    });
  };

  const isChecked = (t: string) =>
    selection?.kind === "tables" && selection.tables.has(t);

  const canCreate = !!connId && selection !== null && !saving;

  const selectedTablesList =
    selection?.kind === "tables" ? [...selection.tables] : [];

  const handleCreate = async () => {
    if (!connId || !selection) return;
    setError("");
    setSaving(true);
    try {
      const tables = selection.kind === "all" ? [] : selectedTablesList;
      // Derive a human name + description from the schema via the LLM.
      let name = selectedConn?.name ?? "New Data Canvas";
      let description = "";
      try {
        const s = await suggestCanvasName(connId, tables);
        if (s.name) name = s.name;
        description = s.description ?? "";
      } catch { /* fall back to connection name */ }
      const canvas = await createCanvas(name.trim(), description.trim(), [
        { connection_id: connId, schema_name: null, tables },
      ]);
      onCreated(canvas);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create Data Canvas");
      setSaving(false);
    }
  };

  const connLabel = (c: Connection) =>
    c.conn_type === "duckdb" ? "DuckDB" : c.conn_type === "postgres" ? "PostgreSQL" : c.conn_type;

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 70,
        background: "rgba(0,0,0,.5)", display: "flex", alignItems: "center", justifyContent: "center",
      }}
      onClick={onCancel}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "var(--bg-1)", border: "1px solid var(--b2)",
          borderRadius: "var(--r3)", width: 560,
          display: "flex", flexDirection: "column",
          boxShadow: "var(--shadow-xl)",
          height: "76vh", maxHeight: 720,
        }}
      >
        {/* Header */}
        <div style={{ padding: "20px 24px 0", flexShrink: 0 }}>
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: "var(--t1)", margin: 0 }}>
              Connect your data
            </h2>
            <button onClick={onCancel} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)", padding: 4 }}>
              <Icon name={CLOSE_ICON} size={16} />
            </button>
          </div>
          <p style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.55, margin: "10px 0 16px", maxWidth: 460 }}>
            Canvases let you uncover meaningful insights from your data. Pick a connection,
            scope it to the tables that matter, and start asking questions — we&rsquo;ll name it for you.
          </p>

          {/* Search bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{
              flex: 1, display: "flex", alignItems: "center", gap: 8,
              border: "1px solid var(--b2)", borderRadius: "var(--r2)",
              padding: "0 12px", height: 40, background: "var(--bg-0)",
            }}>
              <Icon name={SEARCH_ICON} size={14} color="var(--t4)" />
              <input
                placeholder="Search"
                value={search}
                onChange={e => setSearch(e.target.value)}
                style={{
                  flex: 1, background: "none", border: "none", outline: "none",
                  fontSize: 13, color: "var(--t1)", fontFamily: "var(--font-ui)",
                }}
              />
            </div>
            <button
              onClick={() => { if (connId) openConnection(connId); }}
              title="Refresh"
              style={{
                width: 40, height: 40, borderRadius: "var(--r2)", border: "1px solid var(--b2)",
                background: "var(--bg-0)", color: "var(--t3)", cursor: "pointer",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}
            >
              <Icon name={REFRESH_ICON} size={15} />
            </button>
          </div>

          {/* Breadcrumb */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, margin: "16px 0 6px", fontSize: 13 }}>
            <button
              onClick={backToCatalog}
              style={{
                background: "none", border: "none", cursor: connId ? "pointer" : "default",
                color: connId ? "var(--blue4)" : "var(--t1)", fontWeight: 600, padding: 0,
              }}
            >
              All connections
            </button>
            {selectedConn && (
              <>
                <span style={{ color: "var(--t4)" }}>›</span>
                <span style={{ color: "var(--t1)", fontWeight: 600 }}>{selectedConn.name}</span>
              </>
            )}
          </div>
        </div>

        {/* Body — catalog list OR table list */}
        <div style={{ flex: 1, overflowY: "auto", padding: "4px 24px 8px" }}>
          {!connId ? (
            // ── Catalog: choose a connection ──
            connections.length === 0 ? (
              <div style={{ padding: "32px 0", textAlign: "center", fontSize: 13, color: "var(--t4)" }}>
                No connections available.
              </div>
            ) : (
              connections.map(c => (
                <button
                  key={c.id}
                  onClick={() => openConnection(c.id)}
                  style={{
                    width: "100%", display: "flex", alignItems: "center", gap: 12,
                    padding: "11px 8px", background: "transparent", border: "none",
                    borderRadius: "var(--r2)", cursor: "pointer", textAlign: "left",
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-hover)")}
                  onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                >
                  <Icon name={DB_ICON} size={17} color="var(--blue4)" />
                  <span style={{ flex: 1, fontSize: 15, color: "var(--t1)" }}>{c.name}</span>
                  <span style={{ fontSize: 11, color: "var(--t4)" }}>{connLabel(c)}</span>
                  <Icon name={CHEVR_ICON} size={14} color="var(--t4)" />
                </button>
              ))
            )
          ) : loadingTables ? (
            <div style={{ padding: "32px 0", textAlign: "center", fontSize: 13, color: "var(--t4)" }}>
              Loading tables…
            </div>
          ) : (
            // ── Table list with multi-select ──
            <>
              {/* All tables pseudo-row */}
              <button
                onClick={toggleAll}
                style={{
                  width: "100%", display: "flex", alignItems: "center", gap: 12,
                  padding: "10px 8px", background: "transparent", border: "none",
                  borderRadius: "var(--r2)", cursor: "pointer", textAlign: "left",
                  borderBottom: "1px solid var(--b0)",
                }}
                onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-hover)")}
                onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
              >
                <Checkbox checked={selection?.kind === "all"} />
                <Icon name={TABLE_ICON} size={15} color="var(--grn4)" />
                <span style={{ flex: 1, fontSize: 15, color: "var(--t1)", fontWeight: 500 }}>All tables</span>
                <span style={{ fontSize: 11, color: "var(--t4)" }}>auto-includes new tables</span>
              </button>

              {filteredTables.length === 0 ? (
                <div style={{ padding: "24px 0", textAlign: "center", fontSize: 13, color: "var(--t4)" }}>
                  {search ? "No matching tables" : "No tables found"}
                </div>
              ) : (
                filteredTables.map(t => {
                  const checked = isChecked(t);
                  const dimmed = selection?.kind === "all";
                  return (
                    <button
                      key={t}
                      onClick={() => toggleTable(t)}
                      style={{
                        width: "100%", display: "flex", alignItems: "center", gap: 12,
                        padding: "10px 8px", background: "transparent", border: "none",
                        borderRadius: "var(--r2)", cursor: "pointer", textAlign: "left",
                        opacity: dimmed ? 0.4 : 1,
                      }}
                      onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-hover)")}
                      onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                    >
                      <Checkbox checked={checked} />
                      <Icon name={TABLE_ICON} size={15} color="var(--blue4)" />
                      <span style={{ flex: 1, fontSize: 15, color: "var(--t1)", fontFamily: "var(--font-mono)" }}>{t}</span>
                    </button>
                  );
                })
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div style={{
          flexShrink: 0, borderTop: "1px solid var(--b1)", padding: "12px 24px",
          display: "flex", alignItems: "center", gap: 12,
        }}>
          {/* Selected chips */}
          <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", minWidth: 0 }}>
            {selection !== null && (
              <span style={{ fontSize: 12, color: "var(--t3)" }}>Selected:</span>
            )}
            {selection?.kind === "all" && (
              <Chip label={`${selectedConn?.name ?? ""} · all tables`} onRemove={() => setSelection(null)} />
            )}
            {selection?.kind === "tables" && selectedTablesList.slice(0, 4).map(t => (
              <Chip key={t} label={t} mono onRemove={() => toggleTable(t)} />
            ))}
            {selection?.kind === "tables" && selectedTablesList.length > 4 && (
              <span style={{ fontSize: 12, color: "var(--t4)" }}>+{selectedTablesList.length - 4} more</span>
            )}
          </div>

          {error && <span style={{ fontSize: 11, color: "var(--red4)" }}>{error}</span>}

          <Button onClick={onCancel} variant="ghost" size="sm">Cancel</Button>
          <Button
            onClick={handleCreate}
            disabled={!canCreate}
            variant="default" size="sm"
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            {saving ? "Creating…" : "Create"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Bits ────────────────────────────────────────────────────────────────────

function Checkbox({ checked }: { checked: boolean }) {
  return (
    <div style={{
      width: 16, height: 16, borderRadius: 4, flexShrink: 0,
      background: checked ? "var(--blue4)" : "var(--bg-2)",
      border: `1.5px solid ${checked ? "var(--blue4)" : "var(--b2)"}`,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      {checked && <Icon name={CHECK_ICON} size={9} color="var(--bg-0)" />}
    </div>
  );
}

function Chip({ label, onRemove, mono }: { label: string; onRemove: () => void; mono?: boolean }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "3px 6px 3px 10px", borderRadius: "var(--r2)",
      background: "var(--bg-3)", border: "1px solid var(--b1)",
      fontSize: 12, color: "var(--t1)",
      fontFamily: mono ? "var(--font-mono)" : "var(--font-ui)", maxWidth: 180,
    }}>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
      <button
        onClick={e => { e.stopPropagation(); onRemove(); }}
        style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)", padding: 0, display: "flex" }}
      >
        <Icon name={CLOSE_ICON} size={11} />
      </button>
    </span>
  );
}
