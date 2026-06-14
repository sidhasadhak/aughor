"use client";

import React, { useEffect, useMemo, useState } from "react";
import { getCanvases, deleteCanvas, type Canvas, type Connection } from "@/lib/api";
import { AugTable } from "@/components/AugTable";
import type { TableColumnsType } from "antd";

// ── Icon helper ───────────────────────────────────────────────────────────────

function Icon({ d, size = 14, color = "currentColor" }: { d: string; size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
      style={{ flexShrink: 0 }}>
      <path d={d} />
    </svg>
  );
}

const SEARCH_ICON = "M11 19a8 8 0 100-16 8 8 0 000 16zm10 2l-4.35-4.35";
const PLUS_ICON   = "M12 5v14M5 12h14";
const SLIDERS_ICON = "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6";
const CHEVD_ICON   = "M6 9l6 6 6-6";
const CANVAS_ICON = "M4 6h16M4 10h16M4 14h8M4 18h5M15 14l2 2 4-4";
const TRASH_ICON  = "M4 6h16M6 6l1 14h10L18 6M9 6V4h6v2M10 11v6M14 11v6";
const DB_ICON     = "M12 2C7.58 2 4 3.79 4 6v12c0 2.21 3.58 4 8 4s8-1.79 8-4V6c0-2.21-3.58-4-8-4zm0 2c3.87 0 6 1.5 6 2s-2.13 2-6 2-6-1.5-6-2 2.13-2 6-2zm6 12c0 .5-2.13 2-6 2s-6-1.5-6-2v-2.23C7.61 15.51 9.72 16 12 16s4.39-.49 6-1.23V16zm0-5c0 .5-2.13 2-6 2s-6-1.5-6-2V8.77C7.61 10.51 9.72 11 12 11s4.39-.49 6-1.23V11z";

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ── Filter chip ───────────────────────────────────────────────────────────────

function FilterChip({ label, active, onClick }: { label: string; active?: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "5px 13px", borderRadius: 999,
      background: active ? "color-mix(in srgb, var(--blue4) 12%, var(--bg-2))" : "var(--bg-2)",
      border: `1px solid ${active ? "var(--blue4)" : "var(--b1)"}`,
      color: active ? "var(--blue4)" : "var(--t2)",
      fontSize: 12, fontWeight: active ? 500 : 400,
      cursor: "pointer", transition: "all .1s", whiteSpace: "nowrap",
    }}>
      {label}
    </button>
  );
}

// ── Row data shape ────────────────────────────────────────────────────────────

interface CanvasRow {
  key: string;
  canvas: Canvas;
  connection: Connection | undefined;
}

// ── CanvasBrowser ─────────────────────────────────────────────────────────────

interface Props {
  connections: Connection[];
  onSelect: (canvas: Canvas) => void;
  onNew: () => void;
  /** Active workspace — scopes the canvas list to its connections. */
  workspaceId?: string;
}

export function CanvasBrowser({ connections, onSelect, onNew, workspaceId }: Props) {
  const [canvases, setCanvases]         = useState<Canvas[]>([]);
  const [loading, setLoading]           = useState(true);
  const [search, setSearch]             = useState("");
  const [filter, setFilter]             = useState<"all" | "mine">("all");
  const [sort, setSort]                 = useState<"activity" | "modified" | "name" | "tables">("activity");
  const [sortOpen, setSortOpen]         = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Canvas | null>(null);
  const [deleting, setDeleting]         = useState(false);

  const load = () => {
    setLoading(true);
    getCanvases(workspaceId).then(setCanvases).catch(() => setCanvases([]))
      .finally(() => setLoading(false));
  };
  useEffect(load, [workspaceId]);

  const handleDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try { await deleteCanvas(pendingDelete.id); setPendingDelete(null); load(); }
    catch { /* ignore */ }
    finally { setDeleting(false); }
  };

  const connMap = Object.fromEntries(connections.map(c => [c.id, c]));

  const displayed: CanvasRow[] = useMemo(() => {
    let list = [...canvases];
    if (filter === "mine") list = list.filter(c => !c.is_legacy);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(c =>
        c.name.toLowerCase().includes(q) ||
        c.description.toLowerCase().includes(q) ||
        (connMap[c.scopes[0]?.connection_id]?.name ?? "").toLowerCase().includes(q),
      );
    }
    const activityTs = (c: Canvas) =>
      c.last_activity ? new Date(c.last_activity).getTime() : 0;
    const cmp = {
      activity: (a: Canvas, b: Canvas) =>
        activityTs(b) - activityTs(a) ||
        new Date(b.updated_at || b.created_at).getTime() - new Date(a.updated_at || a.created_at).getTime(),
      modified: (a: Canvas, b: Canvas) =>
        new Date(b.updated_at || b.created_at).getTime() -
        new Date(a.updated_at || a.created_at).getTime(),
      name: (a: Canvas, b: Canvas) => a.name.localeCompare(b.name),
      tables: (a: Canvas, b: Canvas) =>
        (b.scopes[0]?.tables.length ?? 0) - (a.scopes[0]?.tables.length ?? 0),
    }[sort];
    return list
      .sort(cmp)
      .map(c => ({ key: c.id, canvas: c, connection: connMap[c.scopes[0]?.connection_id] }));
  }, [canvases, filter, search, sort, connMap]);

  // Up to 5 most-recently-used canvases (those with any investigation/chat).
  const recent: CanvasRow[] = useMemo(() => {
    return [...canvases]
      .filter(c => !!c.last_activity)
      .sort((a, b) => new Date(b.last_activity!).getTime() - new Date(a.last_activity!).getTime())
      .slice(0, 5)
      .map(c => ({ key: c.id, canvas: c, connection: connMap[c.scopes[0]?.connection_id] }));
  }, [canvases, connMap]);

  const SORT_LABELS: Record<typeof sort, string> = {
    activity: "Latest investigation",
    modified: "Last modified",
    name: "Name",
    tables: "Table count",
  };

  // ── Ant Design column defs ────────────────────────────────────────────────

  const columns: TableColumnsType<CanvasRow> = [
    {
      title: "Name",
      key: "name",
      render: (_, { canvas }) => (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 3, flexShrink: 0,
            background: canvas.is_legacy
              ? "var(--bg-3)"
              : "color-mix(in srgb, var(--blue3) 18%, transparent)",
            border: `1px solid ${canvas.is_legacy
              ? "var(--b2)"
              : "color-mix(in srgb, var(--blue3) 35%, transparent)"}`,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <Icon d={CANVAS_ICON} size={13} color={canvas.is_legacy ? "var(--t4)" : "var(--blue4)"} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 500, color: "var(--t1)" }}>
              {canvas.name}
            </div>
            {canvas.is_legacy && (
              <div style={{ fontSize: 10, color: "var(--t4)" }}>auto-generated</div>
            )}
          </div>
        </div>
      ),
    },
    {
      title: "Description",
      key: "description",
      ellipsis: true,
      render: (_, { canvas }) => (
        <span style={{ fontSize: 12, color: "var(--t3)" }}>
          {canvas.description || "—"}
        </span>
      ),
    },
    {
      title: "Modified",
      key: "modified",
      width: 110,
      render: (_, { canvas }) => (
        <span style={{ fontSize: 12, color: "var(--t3)" }}>
          {timeAgo(canvas.updated_at || canvas.created_at)}
        </span>
      ),
    },
    {
      title: "Connection",
      key: "connection",
      width: 200,
      render: (_, { canvas, connection }) => {
        if (!connection) return <span style={{ color: "var(--t4)" }}>—</span>;
        const ct = connection.conn_type;
        const label = ct === "duckdb" ? "DuckDB" : ct === "postgres" ? "PG" : ct.toUpperCase().slice(0, 4);
        return (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "2px 8px", borderRadius: 3,
            background: "var(--bg-3)", border: "1px solid var(--b1)",
            fontSize: 11, color: "var(--t2)", whiteSpace: "nowrap",
          }}>
            <Icon d={DB_ICON} size={10} color="var(--t4)" />
            {connection.name}
            <span style={{ color: "var(--t4)", fontSize: 10 }}>{label}</span>
          </span>
        );
      },
    },
    {
      title: "Tables",
      key: "tables",
      width: 120,
      render: (_, { canvas }) => {
        const n = canvas.scopes[0]?.tables.length ?? 0;
        const label = n === 0 ? "All tables" : `${n} table${n !== 1 ? "s" : ""}`;
        return (
          <span style={{
            display: "inline-block", padding: "2px 8px", borderRadius: 3,
            background: n === 0
              ? "color-mix(in srgb, var(--grn3) 10%, transparent)"
              : "var(--bg-3)",
            border: `1px solid ${n === 0
              ? "color-mix(in srgb, var(--grn3) 25%, transparent)"
              : "var(--b1)"}`,
            fontSize: 11,
            color: n === 0 ? "var(--grn4)" : "var(--t3)",
          }}>
            {label}
          </span>
        );
      },
    },
    {
      title: "",
      key: "actions",
      width: 40,
      render: (_, { canvas }) =>
        canvas.is_legacy ? null : (
          <button
            onClick={e => { e.stopPropagation(); setPendingDelete(canvas); }}
            title="Delete Data Canvas"
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: "var(--t4)", padding: "4px", opacity: 0,
              display: "inline-flex", alignItems: "center", borderRadius: 3,
              transition: "color .1s, opacity .1s",
            }}
            className="aug-canvas-row-delete"
            onMouseEnter={e => { e.currentTarget.style.color = "var(--red4)"; }}
            onMouseLeave={e => { e.currentTarget.style.color = "var(--t4)"; }}
          >
            <Icon d={TRASH_ICON} size={13} />
          </button>
        ),
    },
  ];

  return (
    <div className="aug-screen">

      {/* ── Page header ── */}
      <div style={{
        padding: "28px 32px 0",
        display: "flex", alignItems: "flex-start", justifyContent: "space-between",
        flexShrink: 0,
      }}>
        <div>
          <h1 style={{
            fontSize: 22, fontWeight: 700, color: "var(--t1)",
            letterSpacing: "-.02em", margin: 0, lineHeight: 1.2,
          }}>Data Canvas</h1>
          <p style={{ fontSize: 12, color: "var(--t3)", margin: "5px 0 0", lineHeight: 1.5 }}>
            Curated table sets you can run scoped intelligence and investigations on.
          </p>
        </div>
        <button
          onClick={onNew}
          className="aug-btn aug-btn-primary"
          style={{ display: "inline-flex", alignItems: "center", gap: 6, flexShrink: 0, marginTop: 4 }}
        >
          <Icon d={PLUS_ICON} size={12} color="currentColor" />
          New
        </button>
      </div>

      {/* ── Search ── */}
      <div style={{ padding: "20px 32px 0", flexShrink: 0 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "8px 14px",
          background: "var(--bg-2)", border: "1px solid var(--b1)",
          borderRadius: "var(--r2)", transition: "border-color .1s",
        }}
          onFocusCapture={e => { (e.currentTarget as HTMLDivElement).style.borderColor = "var(--b2)"; }}
          onBlurCapture={e => { (e.currentTarget as HTMLDivElement).style.borderColor = "var(--b1)"; }}
        >
          <Icon d={SEARCH_ICON} size={14} color="var(--t4)" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search Data Canvases, connections…"
            style={{
              flex: 1, background: "none", border: "none", outline: "none",
              fontSize: 13, color: "var(--t1)", fontFamily: "var(--font-ui)",
            }}
          />
          {search && (
            <button onClick={() => setSearch("")}
              style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t4)", padding: 0 }}>
              ✕
            </button>
          )}
        </div>
      </div>

      {/* ── Filter chips ── */}
      <div style={{
        padding: "12px 32px 0",
        display: "flex", alignItems: "center", gap: 6,
        flexShrink: 0,
      }}>
        <div style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 30, height: 30, borderRadius: "var(--r2)",
          background: "var(--bg-2)", border: "1px solid var(--b1)", color: "var(--t3)",
          marginRight: 2,
        }}>
          <Icon d={SLIDERS_ICON} size={14} color="var(--t3)" />
        </div>
        <FilterChip label="All"           active={filter === "all"}  onClick={() => setFilter("all")} />
        <FilterChip label="Created by me" active={filter === "mine"} onClick={() => setFilter("mine")} />
      </div>

      {/* ── Table ── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "14px 32px 24px" }}>
        {/* Section bar */}
        <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
          <span style={{ fontSize: 12, fontWeight: 500, color: "var(--t2)" }}>
            {loading ? "Loading…" : `All Data Canvases${displayed.length > 0 ? ` (${displayed.length})` : ""}`}
          </span>

          {/* Sort control */}
          <div style={{ marginLeft: "auto", position: "relative" }}>
            <button
              onClick={() => setSortOpen(v => !v)}
              onBlur={() => setTimeout(() => setSortOpen(false), 120)}
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "5px 10px", borderRadius: "var(--r2)",
                background: sortOpen ? "var(--bg-3)" : "transparent",
                border: `1px solid ${sortOpen ? "var(--b2)" : "transparent"}`,
                color: "var(--t2)", fontSize: 12, cursor: "pointer", transition: "all .1s",
              }}
              onMouseEnter={e => { if (!sortOpen) e.currentTarget.style.background = "var(--bg-2)"; }}
              onMouseLeave={e => { if (!sortOpen) e.currentTarget.style.background = "transparent"; }}
            >
              <span style={{ color: "var(--t4)" }}>Sort:</span>
              {SORT_LABELS[sort]}
              <Icon d={CHEVD_ICON} size={12} color="var(--t4)" />
            </button>
            {sortOpen && (
              <div style={{
                position: "absolute", top: "calc(100% + 4px)", right: 0, zIndex: 30,
                minWidth: 160, padding: 4,
                background: "var(--bg-2)", border: "1px solid var(--b2)",
                borderRadius: "var(--r2)", boxShadow: "0 8px 28px rgba(0,0,0,.35)",
              }}>
                {(["activity", "modified", "name", "tables"] as const).map(opt => (
                  <button
                    key={opt}
                    onMouseDown={() => { setSort(opt); setSortOpen(false); }}
                    style={{
                      display: "flex", alignItems: "center", gap: 8, width: "100%",
                      padding: "7px 9px", borderRadius: "var(--r1, 4px)", textAlign: "left",
                      background: sort === opt ? "color-mix(in srgb, var(--blue4) 10%, transparent)" : "transparent",
                      border: "none", cursor: "pointer",
                      color: sort === opt ? "var(--blue4)" : "var(--t2)", fontSize: 12,
                    }}
                    onMouseEnter={e => { if (sort !== opt) e.currentTarget.style.background = "var(--bg-hover)"; }}
                    onMouseLeave={e => { if (sort !== opt) e.currentTarget.style.background = "transparent"; }}
                  >
                    {sort === opt
                      ? <Icon d="M20 6L9 17l-5-5" size={12} color="var(--blue4)" />
                      : <span style={{ width: 12 }} />}
                    {SORT_LABELS[opt]}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {!loading && displayed.length === 0 ? (
          /* Empty state */
          <div style={{
            padding: "72px 0", display: "flex", flexDirection: "column",
            alignItems: "center", gap: 14,
          }}>
            <div style={{
              width: 52, height: 52, borderRadius: 4,
              background: "color-mix(in srgb, var(--blue3) 10%, transparent)",
              border: "1px solid color-mix(in srgb, var(--blue3) 22%, transparent)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <Icon d={CANVAS_ICON} size={22} color="var(--blue4)" />
            </div>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", marginBottom: 5 }}>
                {search ? "No matching Data Canvases" : "No Data Canvases yet"}
              </div>
              <div style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.6, maxWidth: 300 }}>
                {search
                  ? "Try a different search or clear the filter."
                  : "Create a Data Canvas to scope a workspace to a connection and specific tables."}
              </div>
            </div>
            {!search && (
              <button onClick={onNew} className="aug-btn aug-btn-primary"
                style={{ display: "inline-flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                <Icon d={PLUS_ICON} size={12} color="currentColor" />
                Create your first Data Canvas
              </button>
            )}
          </div>
        ) : (
          <>
            <style>{`
              .aug-canvas-table .ant-table-row:hover .aug-canvas-row-delete { opacity: 1 !important; }
              .aug-canvas-table .ant-table-row { cursor: pointer; }
              /* Databricks Genie: borderless list — rows sit on the page, hairline separators only */
              .aug-canvas-table .ant-table,
              .aug-canvas-table .ant-table-container,
              .aug-canvas-table .ant-table-thead > tr > th,
              .aug-canvas-table .ant-table-tbody > tr > td { background: transparent !important; }
              .aug-canvas-table .ant-table-thead > tr > th {
                border-bottom: 1px solid var(--b1) !important;
                font-weight: 500;
              }
              .aug-canvas-table .ant-table-thead > tr > th::before { display: none !important; }
              .aug-canvas-table .ant-table-tbody > tr > td { border-bottom: 1px solid var(--b0) !important; }
              .aug-canvas-table .ant-table-tbody > tr:hover > td { background: var(--bg-hover) !important; }
              .aug-canvas-table .ant-table-tbody > tr:last-child > td { border-bottom: none !important; }
            `}</style>
            <AugTable<CanvasRow>
              className="aug-canvas-table"
              columns={columns}
              dataSource={displayed}
              loading={loading}
              pagination={false}
              showSorterTooltip={false}
              onRow={({ canvas }) => ({
                onClick: () => onSelect(canvas),
              })}
            />
          </>
        )}

        {/* ── Recently used (up to 5, by latest investigation) ── */}
        {!loading && !search && recent.length > 0 && (
          <div style={{ marginTop: 28 }}>
            <span style={{ fontSize: 12, fontWeight: 500, color: "var(--t2)", display: "block", marginBottom: 10 }}>
              Recently used
            </span>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
              {recent.map(({ canvas, connection }) => (
                <button
                  key={canvas.id}
                  onClick={() => onSelect(canvas)}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, textAlign: "left",
                    padding: "11px 13px", borderRadius: "var(--r2)", cursor: "pointer",
                    background: "var(--bg-2)", border: "1px solid var(--b1)", transition: "all .1s",
                  }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--blue4)"; e.currentTarget.style.background = "var(--bg-3)"; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b1)"; e.currentTarget.style.background = "var(--bg-2)"; }}
                >
                  <div style={{
                    width: 30, height: 30, borderRadius: 4, flexShrink: 0,
                    background: "color-mix(in srgb, var(--blue3) 16%, transparent)",
                    border: "1px solid color-mix(in srgb, var(--blue3) 32%, transparent)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <Icon d={CANVAS_ICON} size={14} color="var(--blue4)" />
                  </div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 500, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {canvas.name}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--t4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {connection?.name ?? "—"} · {timeAgo(canvas.last_activity!)}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Delete confirmation modal ── */}
      {pendingDelete && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 60,
          background: "rgba(0,0,0,.5)", display: "flex", alignItems: "center", justifyContent: "center",
        }}
          onClick={() => setPendingDelete(null)}
        >
          <div onClick={e => e.stopPropagation()} style={{
            background: "var(--bg-2)", border: "1px solid var(--b2)",
            borderRadius: "var(--r3)", padding: "24px 24px 20px",
            width: 360, display: "flex", flexDirection: "column", gap: 12,
            boxShadow: "0 20px 60px rgba(0,0,0,.4)",
          }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)" }}>Delete Data Canvas</div>
            <div style={{ fontSize: 12, color: "var(--t2)", lineHeight: 1.6 }}>
              Are you sure you want to delete{" "}
              <strong style={{ color: "var(--t1)" }}>{pendingDelete.name}</strong>?
              This cannot be undone.
            </div>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button onClick={() => setPendingDelete(null)} className="aug-btn aug-btn-ghost">Cancel</button>
              <button onClick={handleDelete} disabled={deleting} style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "5px 12px", borderRadius: "var(--r2)", fontSize: 12, fontWeight: 500,
                background: "var(--red1)", border: "1px solid var(--red2)", color: "var(--red4)",
                cursor: deleting ? "not-allowed" : "pointer", opacity: deleting ? 0.5 : 1,
              }}>
                {deleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
