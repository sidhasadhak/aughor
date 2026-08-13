"use client";

/**
 * SE-2 PR D — editor tabs, persisted per connection.
 *
 * Tabs live in `localStorage["aug.sqledit.tabs:<connId>"]`, capped at 20 with LRU
 * eviction. Per connection rather than globally because a tab holds SQL written
 * against a specific warehouse's tables — carrying it to another connection would
 * offer the user a query that cannot run.
 *
 * The cap exists because this is unbounded user input in a bounded store: without it
 * a heavy session eventually throws QuotaExceededError on write, and the failure would
 * surface as "my tabs stopped saving" long after the cause.
 */
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

export interface EditorTab {
  id: string;
  name: string;
  sql: string;
  savedQueryId?: string;
  /** Last run outcome, for the per-tab status chip. */
  status?: "ok" | "error";
  /** Epoch ms of last activity — the LRU key. */
  touched: number;
}

const MAX_TABS = 20;
const VERSION = 1;
interface TabStore { v: number; tabs: EditorTab[]; activeId: string }

function key(connId: string): string {
  return `aug.sqledit.tabs:${connId}`;
}

export function readTabs(connId: string): TabStore | null {
  try {
    const raw = localStorage.getItem(key(connId));
    if (!raw) return null;
    const s = JSON.parse(raw) as TabStore;
    return s && s.v === VERSION && Array.isArray(s.tabs) ? s : null;
  } catch { return null; }
}

export function writeTabs(connId: string, tabs: EditorTab[], activeId: string): void {
  try {
    // LRU: keep the most recently touched, always including the active one.
    const kept = [...tabs]
      .sort((a, b) => b.touched - a.touched)
      .slice(0, MAX_TABS);
    if (activeId && !kept.some(t => t.id === activeId)) {
      const active = tabs.find(t => t.id === activeId);
      if (active) kept[kept.length - 1] = active;
    }
    // Preserve the user's visible ORDER rather than the LRU order — a bar that
    // reshuffled itself on every run would be unusable.
    const ordered = tabs.filter(t => kept.some(k => k.id === t.id));
    localStorage.setItem(key(connId), JSON.stringify({ v: VERSION, tabs: ordered, activeId }));
  } catch { /* storage full or disabled — tabs stay in memory for this session */ }
}

export function newTab(name = "Query"): EditorTab {
  return {
    // crypto.randomUUID is available in every browser this app targets; the fallback
    // keeps a non-secure context (plain http on a LAN) from throwing.
    id: globalThis.crypto?.randomUUID?.() ?? `tab-${Math.random().toString(36).slice(2)}`,
    name,
    sql: "",
    touched: Date.now(),
  };
}

export function TabsBar({
  tabs, activeId, onSelect, onNew, onClose, onRename,
}: {
  tabs: EditorTab[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onClose: (id: string) => void;
  onRename: (id: string, name: string) => void;
}) {
  const [editing, setEditing] = useState("");
  const [draftName, setDraftName] = useState("");

  const commit = useCallback(() => {
    if (editing && draftName.trim()) onRename(editing, draftName.trim());
    setEditing("");
  }, [editing, draftName, onRename]);

  useEffect(() => { if (!editing) setDraftName(""); }, [editing]);

  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 2, padding: "4px 6px",
        borderBottom: "1px solid var(--b0)", flexShrink: 0, overflowX: "auto",
      }}
    >
      {tabs.map(t => {
        const active = t.id === activeId;
        return (
          <div
            key={t.id}
            style={{
              display: "flex", alignItems: "center", gap: 4, flexShrink: 0,
              background: active ? "var(--bg-3)" : "transparent",
              borderRadius: "var(--r2)", paddingRight: 2,
            }}
          >
            {editing === t.id ? (
              <input
                className="aug-input"
                autoFocus
                value={draftName}
                onChange={e => setDraftName(e.target.value)}
                onBlur={commit}
                onKeyDown={e => {
                  if (e.key === "Enter") commit();
                  if (e.key === "Escape") setEditing("");
                }}
                style={{ fontSize: 13, width: 110 }}
              />
            ) : (
              <Button
                variant="ghost"
                size="xs"
                onClick={() => onSelect(t.id)}
                onDoubleClick={() => { setEditing(t.id); setDraftName(t.name); }}
                title="Double-click to rename"
                className="aug-fs-ui"
                style={{ color: active ? "var(--t1)" : "var(--t3)" }}
              >
                {t.status === "error" && (
                  <span style={{ color: "var(--red4)", marginRight: 4 }}>●</span>
                )}
                {t.status === "ok" && (
                  <span style={{ color: "var(--grn4)", marginRight: 4 }}>●</span>
                )}
                {t.name}
              </Button>
            )}
            {tabs.length > 1 && (
              <Button
                variant="ghost"
                size="xs"
                className="aug-fs-ui"
                title="Close tab"
                onClick={() => onClose(t.id)}
                style={{ color: "var(--t4)", padding: "0 4px" }}
              >
                ×
              </Button>
            )}
          </div>
        );
      })}
      <Button variant="ghost" size="xs" className="aug-fs-ui" onClick={onNew} title="New tab" style={{ color: "var(--t3)" }}>
        +
      </Button>
    </div>
  );
}
