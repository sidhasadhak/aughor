"use client";

import React, { useEffect, useRef, useState } from "react";
import type { Canvas, Connection, CanvasHistoryItem as HistoryItem } from "@/lib/api";
import { getCanvasHistory, updateCanvas } from "@/lib/api";
import { ConfigurePanel } from "@/components/ConfigurePanel";
import { ChatPanel } from "@/components/ChatPanel";
import { HistoryDetailPanel } from "@/components/HistoryDetailPanel";
import { DomainIntelPanel } from "@/components/DomainIntelPanel";

// ── Icon helper ───────────────────────────────────────────────────────────────

const PATHS: Record<string, string> = {
  back:     "M19 12H5M12 5l-7 7 7 7",
  canvas:   "M4 6h16M4 10h16M4 14h8M4 18h5M15 14l2 2 4-4",
  db:       "M12 2C7.58 2 4 3.79 4 6v12c0 2.21 3.58 4 8 4s8-1.79 8-4V6c0-2.21-3.58-4-8-4zm0 2c3.87 0 6 1.5 6 2s-2.13 2-6 2-6-1.5-6-2 2.13-2 6-2zm6 12c0 .5-2.13 2-6 2s-6-1.5-6-2v-2.23C7.61 15.51 9.72 16 12 16s4.39-.49 6-1.23V16zm0-5c0 .5-2.13 2-6 2s-6-1.5-6-2V8.77C7.61 10.51 9.72 11 12 11s4.39-.49 6-1.23V11z",
  chat:     "M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z",
  clock:    "M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10zm.5-14v5.25l4.5 2.67-.75 1.23L11 14.5V8h1.5z",
  process:  "M3 6h4v12H3V6zm7-3h4v18h-4V3zm7 6h4v9h-4V9z",
  catalog:  "M4 6h16M4 10h16M4 14h16M4 18h16",
  settings: "M12 15a3 3 0 100-6 3 3 0 000 6zm7.94-3c0-.32-.03-.63-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.49.49 0 00-.6-.22l-2.39.96a7.07 7.07 0 00-1.62-.94l-.36-2.54a.484.484 0 00-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.58.23-1.13.54-1.62.94l-2.39-.96a.48.48 0 00-.6.22L2.07 9.47a.48.48 0 00.12.61l2.03 1.58c-.05.31-.07.63-.07.94s.02.63.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.6.22l2.39-.96c.49.36 1.04.67 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.58-.27 1.13-.58 1.62-.94l2.39.96c.22.07.48 0 .6-.22l1.92-3.32a.48.48 0 00-.12-.61l-2.01-1.58c.05-.31.07-.63.07-.94z",
  close:    "M18 6L6 18M6 6l12 12",
  check:    "M20 6L9 17l-5-5",
  table:    "M3 3h18v4H3zM3 11h18M3 19h18M8 7v12M16 7v12",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
      style={{ flexShrink: 0 }}>
      <path d={PATHS[name] || PATHS.catalog} />
    </svg>
  );
}

// ── Types ─────────────────────────────────────────────────────────────────────

type WsTab = "chat" | "history" | "intel";

// ── History tab ───────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function statusColor(s: string): string {
  if (s === "complete" || s === "completed") return "var(--grn4)";
  if (s === "failed" || s === "timed_out") return "var(--red4)";
  if (s === "running") return "var(--amber4, #f59e0b)";
  return "var(--t4)";
}

function CanvasHistory({
  canvasId,
  onOpen,
}: {
  canvasId: string;
  onOpen: (id: string, kind: "investigation" | "chat") => void;
}) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getCanvasHistory(canvasId, 30)
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [canvasId]);

  if (loading) {
    return (
      <div style={{ padding: "40px 32px", color: "var(--t4)", fontSize: 12 }}>
        Loading history…
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div style={{ padding: "72px 0", display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
        <Icon name="clock" size={28} color="var(--t4)" />
        <div style={{ fontSize: 13, color: "var(--t3)" }}>No investigations yet in this canvas.</div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "16px 32px" }}>
      {items.map(item => {
        const kind = (item.kind === "chat" ? "chat" : "investigation") as "investigation" | "chat";
        return (
        <button
          key={item.id}
          onClick={() => onOpen(item.id, kind)}
          style={{
            width: "100%", textAlign: "left", display: "flex", alignItems: "center", gap: 12,
            padding: "10px 14px", marginBottom: 6,
            background: "var(--bg-2)", border: "1px solid var(--b1)",
            borderRadius: "var(--r2)", cursor: "pointer",
            transition: "border-color .1s, background .1s",
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--b2)";
            (e.currentTarget as HTMLButtonElement).style.background = "var(--bg-3)";
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--b1)";
            (e.currentTarget as HTMLButtonElement).style.background = "var(--bg-2)";
          }}
        >
          <span style={{
            width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
            background: statusColor(item.status),
          }} />
          <span style={{ flex: 1, fontSize: 12, color: "var(--t1)", lineHeight: 1.4, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {item.question}
          </span>
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0,
            padding: "1px 6px", borderRadius: 3, fontSize: 10,
            background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t4)",
          }}>
            <Icon name={kind === "chat" ? "chat" : "process"} size={9} color="var(--t4)" />
            {kind === "chat" ? "Chat" : "Investigation"}
          </span>
          <span style={{ fontSize: 11, color: "var(--t4)", whiteSpace: "nowrap", flexShrink: 0 }}>
            {timeAgo(item.started_at)}
          </span>
        </button>
        );
      })}
    </div>
  );
}

// ── Catalog tab (filtered to canvas tables) ───────────────────────────────────

function CanvasCatalog({
  canvas,
  connection,
}: {
  canvas: Canvas;
  connection: Connection | undefined;
}) {
  const scope = canvas.scopes[0];
  const tables = scope?.tables ?? [];
  const isFullSchema = tables.length === 0;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "16px 32px" }}>
      {/* Scope summary */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "10px 14px", marginBottom: 16,
        background: isFullSchema
          ? "color-mix(in srgb, var(--grn3) 8%, transparent)"
          : "color-mix(in srgb, var(--blue3) 8%, transparent)",
        border: `1px solid ${isFullSchema
          ? "color-mix(in srgb, var(--grn3) 20%, transparent)"
          : "color-mix(in srgb, var(--blue3) 20%, transparent)"}`,
        borderRadius: "var(--r2)", fontSize: 12,
      }}>
        <Icon name="db" size={13} color={isFullSchema ? "var(--grn4)" : "var(--blue4)"} />
        <span style={{ color: "var(--t2)" }}>
          {connection
            ? <><strong style={{ color: "var(--t1)" }}>{connection.name}</strong> {connection.conn_type === "duckdb" ? "· DuckDB" : connection.conn_type === "postgres" ? "· PostgreSQL" : ""}</>
            : <span style={{ color: "var(--t4)" }}>Unknown connection</span>
          }
        </span>
        <span style={{ marginLeft: "auto", color: isFullSchema ? "var(--grn4)" : "var(--blue4)", fontWeight: 500 }}>
          {isFullSchema ? "All tables" : `${tables.length} table${tables.length !== 1 ? "s" : ""} selected`}
        </span>
      </div>

      {isFullSchema ? (
        <div style={{ padding: "24px 0", color: "var(--t3)", fontSize: 12, textAlign: "center" }}>
          This canvas includes the full schema. Open the Catalog tab to browse all tables.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {tables.map(table => (
            <div key={table} style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "8px 14px",
              background: "var(--bg-2)", border: "1px solid var(--b1)",
              borderRadius: "var(--r2)",
            }}>
              <Icon name="table" size={13} color="var(--t4)" />
              <span style={{ fontSize: 12, color: "var(--t1)", fontFamily: "var(--font-mono)" }}>
                {table}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Settings popover ──────────────────────────────────────────────────────────

function SettingsPopover({
  canvas,
  onClose,
  onSaved,
}: {
  canvas: Canvas;
  onClose: () => void;
  onSaved: (updated: Canvas) => void;
}) {
  const [name, setName] = useState(canvas.name);
  const [desc, setDesc] = useState(canvas.description);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const updated = await updateCanvas(canvas.id, { name, description: desc });
      onSaved(updated);
      onClose();
    } catch {
      /* ignore */
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-50" onClick={onClose} />
      <div onClick={e => e.stopPropagation()} style={{
        position: "absolute", top: 44, right: 12, zIndex: 60,
        background: "var(--bg-2)", border: "1px solid var(--b2)",
        borderRadius: "var(--r3)", padding: "16px",
        width: 280, display: "flex", flexDirection: "column", gap: 10,
        boxShadow: "0 8px 32px rgba(0,0,0,.4)",
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", marginBottom: 2 }}>Canvas Settings</div>
        <label style={{ fontSize: 11, color: "var(--t3)", display: "flex", flexDirection: "column", gap: 4 }}>
          Name
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            style={{
              background: "var(--bg-3)", border: "1px solid var(--b1)",
              borderRadius: "var(--r2)", padding: "6px 10px",
              fontSize: 12, color: "var(--t1)", outline: "none",
              fontFamily: "var(--font-ui)",
            }}
          />
        </label>
        <label style={{ fontSize: 11, color: "var(--t3)", display: "flex", flexDirection: "column", gap: 4 }}>
          Description
          <textarea
            value={desc}
            onChange={e => setDesc(e.target.value)}
            rows={2}
            style={{
              background: "var(--bg-3)", border: "1px solid var(--b1)",
              borderRadius: "var(--r2)", padding: "6px 10px",
              fontSize: 12, color: "var(--t1)", outline: "none", resize: "none",
              fontFamily: "var(--font-ui)",
            }}
          />
        </label>
        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 4 }}>
          <button onClick={onClose} className="aug-btn aug-btn-ghost aug-btn-sm">Cancel</button>
          <button
            onClick={save}
            disabled={saving || !name.trim()}
            className="aug-btn aug-btn-primary aug-btn-sm"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Tab pill ──────────────────────────────────────────────────────────────────

function TabPill({
  icon,
  label,
  active,
  onClick,
}: {
  icon: string;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "inline-flex", alignItems: "center", gap: 5,
        padding: "5px 12px", borderRadius: "var(--r2)",
        background: active ? "color-mix(in srgb, var(--blue4) 12%, transparent)" : "transparent",
        border: `1px solid ${active ? "color-mix(in srgb, var(--blue4) 35%, transparent)" : "transparent"}`,
        color: active ? "var(--blue4)" : "var(--t3)",
        fontSize: 12, fontWeight: active ? 500 : 400,
        cursor: "pointer", transition: "all .1s",
      }}
    >
      <Icon name={icon} size={12} color={active ? "var(--blue4)" : "var(--t4)"} />
      {label}
    </button>
  );
}

// ── Capabilities block (canvas landing — Databricks Genie style) ───────────────

function CapabilitiesBlock({
  canvas,
  connection,
}: {
  canvas: Canvas;
  connection: Connection | undefined;
}) {
  const [expanded, setExpanded] = useState(false);
  const scope = canvas.scopes[0];
  const tables = scope?.tables ?? [];
  const isFull = tables.length === 0;
  const connType = connection
    ? (connection.conn_type === "duckdb" ? "DuckDB" : connection.conn_type === "postgres" ? "PostgreSQL" : connection.conn_type)
    : null;

  const caps: string[] = [
    isFull
      ? `Query the full schema of ${connection?.name ?? "this connection"}${connType ? ` (${connType})` : ""}`
      : `Query ${tables.length} curated table${tables.length !== 1 ? "s" : ""}${connection ? ` from ${connection.name}` : ""}${connType ? ` (${connType})` : ""}`,
    "Ask in Quick mode for fast SQL answers, or Agentic for multi-step root-cause analysis",
    "Build domain intelligence, outcomes, and ontology scoped to exactly this table set",
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, textAlign: "left", marginBottom: 4 }}>
      {/* Title */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{
          width: 34, height: 34, borderRadius: "var(--r2)",
          background: canvas.is_legacy ? "var(--bg-3)" : "color-mix(in srgb, var(--blue3) 16%, transparent)",
          border: `1px solid ${canvas.is_legacy ? "var(--b2)" : "color-mix(in srgb, var(--blue3) 32%, transparent)"}`,
          display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
        }}>
          <Icon name="canvas" size={17} color={canvas.is_legacy ? "var(--t4)" : "var(--blue4)"} />
        </div>
        <div style={{ fontSize: 18, fontWeight: 700, color: "var(--t1)" }}>{canvas.name}</div>
      </div>

      {/* Description */}
      {canvas.description && (
        <p style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.55, margin: 0 }}>
          {canvas.description}
        </p>
      )}

      {/* Capabilities */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--t2)", marginBottom: 7 }}>Capabilities</div>
        <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
          {caps.map(c => (
            <li key={c} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12.5, color: "var(--t2)", lineHeight: 1.5 }}>
              <span style={{ width: 4, height: 4, borderRadius: "50%", background: "var(--t4)", marginTop: 7, flexShrink: 0 }} />
              {c}
            </li>
          ))}
        </ul>

        {/* Table chips — revealed via Show more, like Databricks */}
        {!isFull && tables.length > 0 && (
          <>
            {expanded && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                {tables.map(t => (
                  <span key={t} style={{
                    display: "inline-flex", alignItems: "center", gap: 5,
                    padding: "3px 9px", borderRadius: 999,
                    background: "var(--bg-2)", border: "1px solid var(--b1)",
                    fontSize: 11, color: "var(--t2)", fontFamily: "var(--font-mono)",
                  }}>
                    <Icon name="table" size={10} color="var(--t4)" />
                    {t}
                  </span>
                ))}
              </div>
            )}
            <button
              onClick={() => setExpanded(v => !v)}
              style={{
                marginTop: 8, background: "none", border: "none", cursor: "pointer",
                color: "var(--blue4)", fontSize: 12, fontWeight: 500, padding: 0,
              }}
            >
              {expanded ? "Show less" : `Show ${tables.length} table${tables.length !== 1 ? "s" : ""}`}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ── CanvasWorkspace ───────────────────────────────────────────────────────────

interface Props {
  canvas: Canvas;
  connections: Connection[];
  onClose: () => void;
  onCanvasUpdate: (canvas: Canvas) => void;
}

export function CanvasWorkspace({ canvas, connections, onClose, onCanvasUpdate }: Props) {
  const [wsTab, setWsTab] = useState<WsTab>("chat");
  const [chatKey, setChatKey] = useState(0);
  const [openInvId, setOpenInvId] = useState<string | null>(null);
  const [restoreSessionId, setRestoreSessionId] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showConfigure, setShowConfigure] = useState(false);
  const headerRef = useRef<HTMLDivElement>(null);

  const connectionId = canvas.scopes[0]?.connection_id ?? "";
  const connection = connections.find(c => c.id === connectionId);
  const tableCount = canvas.scopes[0]?.tables.length ?? 0;
  const connLabel = connection
    ? (connection.conn_type === "duckdb" ? "DuckDB" : connection.conn_type === "postgres" ? "PostgreSQL" : connection.conn_type)
    : null;

  // When canvas changes, reset to chat tab
  useEffect(() => {
    setWsTab("chat");
    setChatKey(k => k + 1);
    setOpenInvId(null);
    setRestoreSessionId(null);
  }, [canvas.id]);

  // History line-item → navigate.  Investigations open the detail report in the
  // History tab; chat sessions restore the conversation in the Chat tab (passing
  // a chat id to the investigation detail panel would just render blank — the bug
  // behind "choosing a line item does not take me there").
  const handleHistoryOpen = (id: string, kind: "investigation" | "chat") => {
    if (kind === "chat") {
      setOpenInvId(null);
      setRestoreSessionId(id);
      setWsTab("chat");
      setChatKey(k => k + 1);
    } else {
      setRestoreSessionId(null);
      setOpenInvId(id);
      setWsTab("history");
    }
  };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>

      {/* ── Header ── */}
      <div ref={headerRef} style={{
        position: "relative",
        display: "flex", alignItems: "center", gap: 8,
        padding: "0 12px", height: 44, flexShrink: 0,
        borderBottom: "1px solid var(--b1)", background: "var(--bg-1)",
      }}>
        {/* Back button */}
        <button
          onClick={onClose}
          title="Back to Canvases"
          style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "4px 8px", borderRadius: "var(--r2)",
            background: "none", border: "1px solid transparent",
            color: "var(--t3)", fontSize: 11, cursor: "pointer",
            transition: "all .1s",
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLButtonElement).style.color = "var(--t1)";
            (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--b1)";
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLButtonElement).style.color = "var(--t3)";
            (e.currentTarget as HTMLButtonElement).style.borderColor = "transparent";
          }}
        >
          <Icon name="back" size={12} color="currentColor" />
          Canvases
        </button>

        <span style={{ color: "var(--b1)", fontSize: 16, lineHeight: 1, userSelect: "none" }}>/</span>

        {/* Canvas icon + name */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{
            width: 22, height: 22, borderRadius: 3,
            background: canvas.is_legacy
              ? "var(--bg-3)"
              : "color-mix(in srgb, var(--blue3) 18%, transparent)",
            border: `1px solid ${canvas.is_legacy ? "var(--b2)" : "color-mix(in srgb, var(--blue3) 35%, transparent)"}`,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <Icon name="canvas" size={11} color={canvas.is_legacy ? "var(--t4)" : "var(--blue4)"} />
          </div>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{canvas.name}</span>
        </div>

        {/* Table count badge */}
        <span style={{
          display: "inline-flex", alignItems: "center", gap: 4,
          padding: "2px 7px", borderRadius: 3,
          background: tableCount === 0
            ? "color-mix(in srgb, var(--grn3) 10%, transparent)"
            : "var(--bg-3)",
          border: `1px solid ${tableCount === 0
            ? "color-mix(in srgb, var(--grn3) 25%, transparent)"
            : "var(--b1)"}`,
          fontSize: 10,
          color: tableCount === 0 ? "var(--grn4)" : "var(--t3)",
        }}>
          {tableCount === 0 ? "All tables" : `${tableCount} table${tableCount !== 1 ? "s" : ""}`}
        </span>

        {/* Connection badge */}
        {connection && (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            padding: "2px 7px", borderRadius: 3,
            background: "var(--bg-3)", border: "1px solid var(--b1)",
            fontSize: 10, color: "var(--t3)",
          }}>
            <Icon name="db" size={10} color="var(--t4)" />
            {connection.name}
            {connLabel && <span style={{ color: "var(--t4)" }}>{connLabel}</span>}
          </span>
        )}

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* New chat button */}
        <button
          onClick={() => { setWsTab("chat"); setChatKey(k => k + 1); setOpenInvId(null); setRestoreSessionId(null); }}
          className="aug-btn aug-btn-ghost aug-btn-sm"
          title="New conversation"
          style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
        >
          <Icon name="chat" size={11} color="currentColor" />
          New
        </button>

        {/* Configure */}
        <button
          onClick={() => { setShowConfigure(v => !v); setShowSettings(false); }}
          className={`aug-btn aug-btn-sm ${showConfigure ? "aug-btn-primary" : "aug-btn-ghost"}`}
          title="Configure canvas"
          style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
        >
          <Icon name="settings" size={11} color="currentColor" />
          Configure
        </button>

        {/* Settings */}
        <button
          onClick={() => setShowSettings(v => !v)}
          title="Canvas settings"
          style={{
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            width: 28, height: 28, borderRadius: "var(--r2)",
            background: showSettings ? "var(--bg-3)" : "none",
            border: `1px solid ${showSettings ? "var(--b2)" : "transparent"}`,
            color: "var(--t3)", cursor: "pointer", transition: "all .1s",
          }}
          onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.color = "var(--t1)"}
          onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.color = "var(--t3)"}
        >
          <Icon name="settings" size={13} color="currentColor" />
        </button>

        {showSettings && (
          <SettingsPopover
            canvas={canvas}
            onClose={() => setShowSettings(false)}
            onSaved={updated => { onCanvasUpdate(updated); setShowSettings(false); }}
          />
        )}
      </div>

      {/* ── Tab nav ── */}
      <div style={{
        display: "flex", alignItems: "center", gap: 2,
        padding: "6px 12px", borderBottom: "1px solid var(--b1)", flexShrink: 0,
        background: "var(--bg-1)",
      }}>
        <TabPill icon="chat"    label="Chat"          active={wsTab === "chat"}    onClick={() => { setWsTab("chat"); setOpenInvId(null); }} />
        <TabPill icon="clock"   label="History"       active={wsTab === "history"} onClick={() => { setWsTab("history"); setOpenInvId(null); }} />
        <TabPill icon="process" label="Intelligence"  active={wsTab === "intel"}   onClick={() => setWsTab("intel")} />
      </div>

      {/* ── Content ── */}
      {/*
        IMPORTANT: all three panels are always mounted — never conditionally rendered.
        Switching tabs uses CSS display:none so React keeps each panel's state alive.
        Unmounting ChatPanel mid-investigation kills its SSE stream and message list;
        the user comes back to a blank window even though the backend finished fine.
      */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>

        {/* Chat — always mounted, hidden when not active */}
        <div style={{
          display: wsTab === "chat" ? "flex" : "none",
          flex: 1, flexDirection: "column", overflow: "hidden",
        }}>
          <ChatPanel
            key={chatKey}
            connectionId={connectionId}
            canvasId={canvas.id}
            restoreSessionId={restoreSessionId}
            capabilities={<CapabilitiesBlock canvas={canvas} connection={connection} />}
          />
        </div>

        {/* History — always mounted, hidden when not active */}
        <div style={{
          display: wsTab === "history" ? "flex" : "none",
          flex: 1, flexDirection: "column", overflow: "hidden",
        }}>
          {openInvId
            ? (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
                <div style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "0 16px", height: 40, flexShrink: 0,
                  borderBottom: "1px solid var(--b1)",
                }}>
                  <button
                    onClick={() => setOpenInvId(null)}
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 5,
                      background: "none", border: "none", cursor: "pointer",
                      color: "var(--t3)", fontSize: 11, padding: "4px 0",
                    }}
                  >
                    <Icon name="back" size={12} /> Back
                  </button>
                </div>
                <div style={{ flex: 1, overflowY: "auto" }}>
                  <HistoryDetailPanel
                    invId={openInvId}
                    onContinue={() => {
                      setOpenInvId(null);
                      setWsTab("chat");
                      setChatKey(k => k + 1);
                    }}
                  />
                </div>
              </div>
            )
            : (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
                <div style={{
                  padding: "14px 32px 0", flexShrink: 0,
                  fontSize: 12, fontWeight: 500, color: "var(--t2)",
                }}>
                  Recent investigations
                </div>
                <CanvasHistory canvasId={canvas.id} onOpen={handleHistoryOpen} />
              </div>
            )
          }
        </div>

        {/* Intelligence — always mounted, hidden when not active */}
        <div style={{
          display: wsTab === "intel" ? "flex" : "none",
          flex: 1, overflowY: "auto", padding: "16px 24px",
        }}>
          <DomainIntelPanel
            connectionId={connectionId}
            canvasId={canvas.id}
            isActive={wsTab === "intel"}
          />
        </div>

      </div>

      {/* Configure slide-over */}
      {showConfigure && (
        <ConfigurePanel
          canvas={canvas}
          connections={connections}
          onClose={() => setShowConfigure(false)}
          onCanvasUpdate={onCanvasUpdate}
        />
      )}
    </div>
  );
}
