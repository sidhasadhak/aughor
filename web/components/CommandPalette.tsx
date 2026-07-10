"use client";

/**
 * CommandPalette — ⌘K global search overlay.
 *
 * Fuzzy-searches across:
 *   • Nav actions   — static destinations within the app
 *   • Investigations — recent history (fetched from /investigations)
 *   • Tables         — schema tables for the selected connection
 *
 * Keyboard: ↑↓ navigate, Enter activate, Escape close.
 * Fuse.js powers all fuzzy matching with character-level highlights.
 */

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { formatCount } from "@/lib/format";
import Fuse, { type FuseResult, type FuseResultMatch } from "fuse.js";
import { API_BASE } from "@/lib/config";

// ── Types ─────────────────────────────────────────────────────────────────────

type ItemType = "action" | "investigation" | "table" | "canvas";

interface PaletteItem {
  id: string;
  label: string;
  sublabel?: string;
  type: ItemType;
  icon: string;         // from ICONS map below
  accent?: string;      // CSS color for the icon dot
  meta?: string;        // e.g. connection name, time ago
  onSelect: () => void;
}

// Section header order and display names
const SECTION_ORDER: ItemType[] = ["action", "investigation", "table", "canvas"];
const SECTION_LABELS: Record<ItemType, string> = {
  action:        "Navigation",
  investigation: "Recent investigations",
  table:         "Tables",
  canvas:        "Canvases",
};

// ── Icon primitives ───────────────────────────────────────────────────────────

const ICONS: Record<string, string> = {
  spark:       "M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z",
  clock:       "M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10zm.5-14v5.25l4.5 2.67-.75 1.23L11 14.5V8h1.5z",
  db:          "M12 2C7.58 2 4 3.79 4 6v12c0 2.21 3.58 4 8 4s8-1.79 8-4V6c0-2.21-3.58-4-8-4zm6 12c0 .5-2.13 2-6 2s-6-1.5-6-2v-2.23C7.61 15.51 9.72 16 12 16s4.39-.49 6-1.23V16zm0-5c0 .5-2.13 2-6 2s-6-1.5-6-2V8.77C7.61 10.51 9.72 11 12 11s4.39-.49 6-1.23V11zm0-5c0 .5-2.13 2-6 2S6 6.5 6 6s2.13-2 6-2 6 1.5 6 2z",
  node:        "M12 4a2 2 0 100 4 2 2 0 000-4zM6 18a2 2 0 100 4 2 2 0 000-4zm12 0a2 2 0 100 4 2 2 0 000-4zM12 6v4m0 4v4M8 19h8M14 7l4 10M10 7L6 17",
  process:     "M3 6h4v12H3V6zm7-3h4v18h-4V3zm7 6h4v9h-4V9z",
  catalog:     "M4 6h16M4 10h16M4 14h16M4 18h16",
  builder:     "M3 3h7v7H3V3zm11 0h7v7h-7V3zm0 11h7v7h-7v-7zM3 14h7v7H3v-7z",
  plug:        "M7 2v4M17 2v4M12 13v6M9 19h6M5 6h14l-1.5 7a2 2 0 01-2 1.73H8.5A2 2 0 016.5 13L5 6z",
  playbook:    "M9 12h6M9 16h4M5 3H3a2 2 0 00-2 2v16a2 2 0 002 2h16a2 2 0 002-2V5a2 2 0 00-2-2h-2M15 3H9a1 1 0 00-1 1v2a1 1 0 001 1h6a1 1 0 001-1V4a1 1 0 00-1-1z",
  settings:    "M12 15a3 3 0 100-6 3 3 0 000 6zm7.94-3c0-.32-.03-.63-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.49.49 0 00-.6-.22l-2.39.96a7.07 7.07 0 00-1.62-.94l-.36-2.54a.484.484 0 00-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.58.23-1.13.54-1.62.94l-2.39-.96a.48.48 0 00-.6.22L2.07 9.47a.48.48 0 00.12.61l2.03 1.58c-.05.31-.07.63-.07.94s.02.63.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.6.22l2.39-.96c.49.36 1.04.67 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.58-.27 1.13-.58 1.62-.94l2.39.96c.22.07.48 0 .6-.22l1.92-3.32a.48.48 0 00-.12-.61l-2.01-1.58c.05-.31.07-.63.07-.94z",
  activity:    "M22 12h-4l-3 9L9 3l-3 9H2",
  metric:      "M3 3v18h18M7 16l4-4 4 4 4-4",
  canvas:      "M4 6h16M4 10h16M4 14h8M4 18h5M15 14l2 2 4-4",
  inbox:       "M22 8.01V18a2 2 0 01-2 2H4a2 2 0 01-2-2V8.01M22 8l-10 7L2 8m20 0a2 2 0 00-2-2H4a2 2 0 00-2 2",
  health:      "M22 12h-4l-2.5 5-5-16L8 12H2",
  table:       "M3 3h18v4H3zm0 7h18v4H3zm0 7h18v4H3z",
};

function PIcon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  const d = ICONS[name] ?? ICONS.spark;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
      style={{ flexShrink: 0 }}>
      <path d={d} />
    </svg>
  );
}

// ── Match highlight ───────────────────────────────────────────────────────────

function Highlighted({ text, matches }: { text: string; matches?: readonly FuseResultMatch[] }) {
  if (!matches || matches.length === 0) return <>{text}</>;
  const match = matches.find(m => m.key === "label" || m.key === "sublabel");
  if (!match?.indices?.length) return <>{text}</>;

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  const sorted = [...match.indices].sort((a, b) => a[0] - b[0]);
  for (const [start, end] of sorted) {
    if (start > cursor) parts.push(text.slice(cursor, start));
    parts.push(
      <mark key={start} style={{ background: "var(--blue2)", color: "var(--blue5)", borderRadius: 1, padding: "0 1px" }}>
        {text.slice(start, end + 1)}
      </mark>
    );
    cursor = end + 1;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}

// ── Time helper ───────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  selectedConn: string;
  onNavigate: (tab: string) => void;
  onGoToChat: (q?: string) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CommandPalette({ open, onClose, selectedConn, onNavigate, onGoToChat }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [investigations, setInvestigations] = useState<Array<{ id: string; question: string; started_at: string; status: string }>>([]);
  const [tables, setTables] = useState<Array<{ name: string; row_count: string }>>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef  = useRef<HTMLDivElement>(null);

  // Reset + fetch on open
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setCursor(0);
    setTimeout(() => inputRef.current?.focus(), 30);

    // Fetch recent investigations
    fetch(`${API_BASE}/investigations`)
      .then(r => r.json())
      .then(d => setInvestigations(Array.isArray(d) ? d.slice(0, 20) : []))
      .catch(() => {});

    // Fetch schema tables for the selected connection. Must be /schema/rich —
    // plain /schema returns {schema: <string>} with no tables key, which left
    // the palette's table quick-jump permanently empty.
    if (selectedConn) {
      fetch(`${API_BASE}/connections/${selectedConn}/schema/rich`)
        .then(r => r.json())
        .then(d => setTables(d?.tables ?? []))
        .catch(() => {});
    }
  }, [open, selectedConn]);

  // Escape handler
  useEffect(() => {
    if (!open) return;
    const fn = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [open, onClose]);

  // ── Static nav action items ───────────────────────────────────────────────

  const NAV_ACTIONS: Omit<PaletteItem, "onSelect">[] = [
    { id: "nav-canvases",    label: "Data Canvas",           sublabel: "Browse and open Data Canvases",     type: "action", icon: "canvas",   accent: "var(--blue3)" },
    { id: "nav-recents",     label: "Investigation history", sublabel: "View all past analyses",            type: "action", icon: "clock",    accent: "var(--t3)" },
    { id: "nav-inbox",       label: "Recommendation Inbox", sublabel: "Act on Aughor's recommendations",   type: "action", icon: "inbox",    accent: "var(--amb3)" },
    { id: "nav-intel",       label: "Domain Intelligence",  sublabel: "Per-domain insights and coverage",  type: "action", icon: "process",  accent: "var(--cyn3)" },
    { id: "nav-ontology",    label: "Business Ontology",    sublabel: "Entity graph and lifecycle states", type: "action", icon: "node",     accent: "var(--grn3)" },
    { id: "nav-health",      label: "Health Scorecard",     sublabel: "Business metric targets and status",type: "action", icon: "activity", accent: "var(--grn3)" },
    { id: "nav-playbook",    label: "Playbook",             sublabel: "Strategic decision patterns",        type: "action", icon: "playbook", accent: "var(--t2)" },
    { id: "nav-catalog",     label: "Catalog",              sublabel: "Browse tables, columns, row counts", type: "action", icon: "db",       accent: "var(--blue3)" },
    { id: "nav-builder",     label: "Query Builder",        sublabel: "Visual SQL builder with live results",type: "action", icon: "builder", accent: "var(--t2)" },
    { id: "nav-connections", label: "Connections",          sublabel: "Manage data source connections",     type: "action", icon: "plug",     accent: "var(--grn3)" },
    { id: "nav-metrics",     label: "Metrics Catalog",      sublabel: "Semantic KPI definitions",           type: "action", icon: "metric",   accent: "var(--amb3)" },
    { id: "nav-actions",     label: "Action Hub",           sublabel: "Webhooks, Slack, Jira integrations", type: "action", icon: "inbox",    accent: "var(--vio3)" },
    { id: "nav-settings",    label: "Settings",             sublabel: "Theme, model, system configuration", type: "action", icon: "settings", accent: "var(--t3)" },
  ];

  const NAV_DISPATCH: Record<string, () => void> = {
    "nav-canvases":    () => onNavigate("canvases"),
    "nav-recents":     () => onNavigate("recents"),
    "nav-inbox":       () => onNavigate("inbox"),
    "nav-intel":       () => onNavigate("intel"),
    "nav-ontology":    () => onNavigate("ontology"),
    "nav-health":      () => onNavigate("health"),
    "nav-playbook":    () => onNavigate("playbook"),
    "nav-catalog":     () => onNavigate("catalog"),
    "nav-builder":     () => onNavigate("builder"),
    "nav-connections": () => onNavigate("connections"),
    "nav-metrics":     () => onNavigate("metrics"),
    "nav-actions":     () => onNavigate("actions"),
    "nav-settings":    () => onNavigate("settings"),
  };

  // ── Build full item list ──────────────────────────────────────────────────

  const allItems = useMemo<PaletteItem[]>(() => {
    const navItems: PaletteItem[] = NAV_ACTIONS.map(a => ({ ...a, onSelect: NAV_DISPATCH[a.id] ?? (() => {}) }));

    const invItems: PaletteItem[] = investigations.map(inv => ({
      id: `inv-${inv.id}`,
      label: inv.question,
      sublabel: `${timeAgo(inv.started_at)} ago · ${inv.status}`,
      type: "investigation" as ItemType,
      icon: "spark",
      accent: inv.status === "complete" ? "var(--grn3)" : inv.status === "failed" ? "var(--red3)" : "var(--t3)",
      onSelect: () => onGoToChat(inv.question),
    }));

    const tableItems: PaletteItem[] = tables.map(t => ({
      id: `table-${t.name}`,
      label: t.name,
      sublabel: t.row_count ? `${formatCount(Number(t.row_count))} rows` : undefined,
      type: "table" as ItemType,
      icon: "table",
      accent: "var(--cyn3)",
      onSelect: () => onGoToChat(`Tell me about the ${t.name} table`),
    }));

    return [...navItems, ...invItems, ...tableItems];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [investigations, tables]);

  // ── Fuse fuzzy search ─────────────────────────────────────────────────────

  const fuse = useMemo(() => new Fuse(allItems, {
    keys: [
      { name: "label",    weight: 2 },
      { name: "sublabel", weight: 1 },
    ],
    threshold: 0.35,
    includeMatches: true,
    minMatchCharLength: 1,
  }), [allItems]);

  const results: FuseResult<PaletteItem>[] = useMemo(() => {
    if (!query.trim()) {
      // No query — show defaults: top actions + 5 recent investigations + 5 tables
      const defaults = [
        ...allItems.filter(i => ["nav-canvases","nav-recents","nav-catalog","nav-builder"].includes(i.id)),
        ...allItems.filter(i => i.type === "investigation").slice(0, 5),
        ...allItems.filter(i => i.type === "table").slice(0, 5),
      ];
      return defaults.map(item => ({ item, refIndex: 0, matches: [] }));
    }
    return fuse.search(query).slice(0, 20);
  }, [query, fuse, allItems]);

  // Group results by type preserving section order
  const grouped = useMemo(() => {
    const map = new Map<ItemType, FuseResult<PaletteItem>[]>();
    for (const r of results) {
      const t = r.item.type;
      if (!map.has(t)) map.set(t, []);
      map.get(t)!.push(r);
    }
    return SECTION_ORDER.filter(t => map.has(t)).map(t => ({ type: t, items: map.get(t)! }));
  }, [results]);

  // Flat list of all rendered items (for keyboard nav)
  const flatResults = useMemo(() => results.map(r => r.item), [results]);

  // ── Keyboard navigation ───────────────────────────────────────────────────

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor(c => Math.min(c + 1, flatResults.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor(c => Math.max(c - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = flatResults[cursor];
      if (item) { item.onSelect(); onClose(); }
    }
  }, [flatResults, cursor, onClose]);

  // Reset cursor on query change
  useEffect(() => setCursor(0), [query]);

  // Scroll active item into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${cursor}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!open) return null;

  let globalIdx = 0;

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        className="aug-anim-fade"
        style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.65)", backdropFilter: "blur(3px)", zIndex: 200 }}
      />

      {/* Palette */}
      <div className="aug-anim-pop" style={{
        position: "fixed", top: "14%", left: "50%", transform: "translateX(-50%)",
        zIndex: 201, width: "100%", maxWidth: 580,
        background: "var(--bg-2)", border: "1px solid var(--b2)",
        borderRadius: "var(--r3)", overflow: "hidden",
        boxShadow: "0 24px 64px rgba(0,0,0,.65)",
      }}>
        {/* Input row */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "11px 14px", borderBottom: "1px solid var(--b1)" }}>
          <PIcon name="spark" size={13} color="var(--t3)" />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search tables, analyses, metrics…"
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", fontSize: 13, color: "var(--t1)", fontFamily: "var(--font-ui)" }}
          />
          <kbd
            onClick={onClose}
            style={{ fontSize: 11, padding: "2px 6px", background: "var(--bg-3)", border: "1px solid var(--b2)", borderRadius: 2, color: "var(--t3)", cursor: "pointer", fontFamily: "var(--font-mono)" }}
          >
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} style={{ maxHeight: 380, overflowY: "auto" }}>
          {results.length === 0 ? (
            <div style={{ padding: "28px 0", textAlign: "center", fontSize: 12, color: "var(--t3)" }}>
              No results for &ldquo;{query}&rdquo;
            </div>
          ) : (
            grouped.map(({ type, items }) => (
              <div key={type}>
                {/* Section header */}
                <div style={{ padding: "8px 14px 4px", fontSize: 11, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--t4)", borderTop: "1px solid var(--b0)" }}>
                  {SECTION_LABELS[type]}
                </div>

                {/* Items */}
                {items.map(result => {
                  const item = result.item;
                  const idx = globalIdx++;
                  const isFocused = cursor === idx;
                  return (
                    <button
                      key={item.id}
                      data-idx={idx}
                      onClick={() => { item.onSelect(); onClose(); }}
                      onMouseEnter={() => setCursor(idx)}
                      style={{
                        width: "100%", display: "flex", alignItems: "center", gap: 10,
                        padding: "8px 14px", background: isFocused ? "var(--bg-sel)" : "none",
                        border: "none", cursor: "pointer", transition: "background .08s", textAlign: "left",
                        borderLeft: isFocused ? "2px solid var(--blue3)" : "2px solid transparent",
                      }}
                    >
                      {/* Icon */}
                      <div style={{
                        width: 28, height: 28, borderRadius: "var(--r1)", flexShrink: 0,
                        background: `color-mix(in srgb, ${item.accent ?? "var(--t3)"} 12%, transparent)`,
                        border: `1px solid color-mix(in srgb, ${item.accent ?? "var(--t3)"} 25%, transparent)`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                      }}>
                        <PIcon name={item.icon} size={13} color={item.accent ?? "var(--t3)"} />
                      </div>

                      {/* Text */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          <Highlighted text={item.label} matches={result.matches?.filter(m => m.key === "label")} />
                        </div>
                        {item.sublabel && (
                          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            <Highlighted text={item.sublabel} matches={result.matches?.filter(m => m.key === "sublabel")} />
                          </div>
                        )}
                      </div>

                      {/* Enter hint on focused item */}
                      {isFocused && (
                        <kbd style={{ fontSize: 11, padding: "1px 5px", background: "var(--bg-3)", border: "1px solid var(--b2)", borderRadius: 2, color: "var(--t3)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>
                          ↵
                        </kbd>
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer hints */}
        <div style={{ padding: "6px 14px", borderTop: "1px solid var(--b0)", display: "flex", gap: 14, alignItems: "center" }}>
          {[["↑↓", "Navigate"], ["↵", "Select"], ["ESC", "Close"]].map(([k, l]) => (
            <span key={k} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <kbd style={{ fontSize: 11, padding: "1px 5px", background: "var(--bg-3)", border: "1px solid var(--b2)", borderRadius: 2, color: "var(--t3)", fontFamily: "var(--font-mono)" }}>{k}</kbd>
              <span style={{ fontSize: 11, color: "var(--t4)" }}>{l}</span>
            </span>
          ))}
          <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--t4)" }}>
            {results.length} result{results.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>
    </>
  );
}
