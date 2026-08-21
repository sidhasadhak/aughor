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
import { getApiBase } from "@/lib/config";
import { useRichSchema } from "@/lib/schema-context";
import { useCommands, useRegisterCommands, type Command } from "@/lib/commandRegistry";
import { Icon, type IconName } from "@/components/ui/icon";

// ── Types ─────────────────────────────────────────────────────────────────────

type ItemType = "command" | "action" | "investigation" | "table" | "canvas";

interface PaletteItem {
  id: string;
  label: string;
  sublabel?: string;
  keywords?: string;    // extra fuzzy-match terms (commands), not displayed
  type: ItemType;
  icon: string;         // from ICONS map below
  accent?: string;      // CSS color for the icon dot
  meta?: string;        // e.g. connection name, time ago
  onSelect: () => void;
}

// Section header order and display names
const SECTION_ORDER: ItemType[] = ["command", "action", "investigation", "table", "canvas"];
const SECTION_LABELS: Record<ItemType, string> = {
  command:       "Commands",
  action:        "Navigation",
  investigation: "Recent deep analyses",
  table:         "Tables",
  canvas:        "Canvases",
};

// ── Icon primitives ───────────────────────────────────────────────────────────

/** Palette glyphs, by role — drawings come from the platform set. */
const ROLE: Record<string, IconName> = {
  spark: "spark",
  clock: "clock",
  db: "db",
  node: "node",
  process: "process",
  catalog: "catalog",
  builder: "builder",
  plug: "plug",
  playbook: "playbook",
  settings: "settings",
  activity: "activity",
  metric: "chart",
  canvas: "canvas",
  inbox: "inbox",
  health: "health",
  table: "table",
};

function PIcon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <span style={{ color, display: "inline-flex", flexShrink: 0 }}>
      <Icon name={ROLE[name] ?? "spark"} size={size} />
    </span>
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

/**
 * GlobalCommands — registers the always-available action verbs for the ⌘K palette.
 * Renders nothing; mount it once (next to <CommandPalette/>). Handlers are held in
 * refs so the command closures stay stable yet always call the latest callback.
 */
export function GlobalCommands({ onNavigate, onGoToChat }: { onNavigate: (t: string) => void; onGoToChat: (q?: string) => void }) {
  const navRef = useRef(onNavigate);
  const chatRef = useRef(onGoToChat);
  useEffect(() => { navRef.current = onNavigate; chatRef.current = onGoToChat; });

  const commands = useMemo<Command[]>(() => [
    { id: "cmd-ask",         label: "Ask a question",     sublabel: "Start a new deep analysis",       icon: "spark",    accent: "var(--blue3)", keywords: "new chat investigate ask question analyze", run: () => chatRef.current() },
    { id: "cmd-new-canvas",  label: "New Data Canvas",    sublabel: "Create or browse Data Canvases",  icon: "canvas",   accent: "var(--blue3)", keywords: "create canvas new workspace",             run: () => navRef.current("canvases") },
    { id: "cmd-new-monitor", label: "New monitor",        sublabel: "Watch a metric for threshold, drift or staleness", icon: "activity", accent: "var(--grn3)", keywords: "create alert watch threshold notify", run: () => navRef.current("monitors") },
    { id: "cmd-new-query",   label: "Build a query",      sublabel: "Open the visual Query Builder",   icon: "builder",  accent: "var(--t2)",    keywords: "sql query builder new compose",           run: () => navRef.current("builder") },
    { id: "cmd-add-source",  label: "Add a data source",  sublabel: "Connect or upload data",          icon: "plug",     accent: "var(--grn3)", keywords: "connect connection upload csv source database", run: () => navRef.current("connections") },
  ], []);

  useRegisterCommands("global", commands);
  return null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CommandPalette({ open, onClose, selectedConn, onNavigate, onGoToChat }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [investigations, setInvestigations] = useState<Array<{ id: string; question: string; started_at: string; status: string }>>([]);
  const [tables, setTables] = useState<Array<{ name: string; row_count: string }>>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef  = useRef<HTMLDivElement>(null);
  const commands = useCommands();   // contextual + global action verbs (registry)

  // Reset + fetch on open
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setCursor(0);
    setTimeout(() => inputRef.current?.focus(), 30);

    // Fetch recent investigations
    fetch(`${getApiBase()}/investigations`)
      .then(r => r.json())
      .then(d => setInvestigations(Array.isArray(d) ? d.slice(0, 20) : []))
      .catch(() => {});

  }, [open, selectedConn]);

  // Schema tables for the quick-jump, from the shared per-connection cache. It must be
  // /schema/rich — plain /schema returns {schema: <string>} with no tables key, which
  // once left this list permanently empty. Only fetched while the palette is open.
  const { schema: paletteSchema } = useRichSchema(open ? selectedConn : null);
  useEffect(() => {
    // `row_count` is `string | null` on the wire; this list has always declared it
    // non-null and got away with it because the old raw `r.json()` was untyped. The
    // shared hook is typed, so the coercion becomes explicit rather than accidental.
    setTables((paletteSchema?.tables ?? []).map(t => ({ ...t, row_count: t.row_count ?? "" })));
  }, [paletteSchema]);

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
    { id: "nav-recents",     label: "Deep analysis history", sublabel: "View all past analyses",            type: "action", icon: "clock",    accent: "var(--t3)" },
    { id: "nav-inbox",       label: "Inbox",                sublabel: "Act on Aughor's recommendations",   type: "action", icon: "inbox",    accent: "var(--amb3)" },
    { id: "nav-intel",       label: "Profile",              sublabel: "Per-domain findings and coverage",  type: "action", icon: "process",  accent: "var(--cyn3)" },
    { id: "nav-ontology",    label: "Ontology",             sublabel: "Entity graph and lifecycle states", type: "action", icon: "node",     accent: "var(--grn3)" },
    { id: "nav-health",      label: "Health",               sublabel: "Business metric targets and status",type: "action", icon: "activity", accent: "var(--grn3)" },
    { id: "nav-agentic-ops", label: "Agents",               sublabel: "Overview, agents, attention, activity, run graphs", type: "action", icon: "process", accent: "var(--vio3)" },
    { id: "nav-playbook",    label: "Playbook",             sublabel: "Strategic decision patterns",        type: "action", icon: "playbook", accent: "var(--t2)" },
    { id: "nav-catalog",     label: "Catalog",              sublabel: "Browse tables, columns, row counts", type: "action", icon: "db",       accent: "var(--blue3)" },
    { id: "nav-builder",     label: "SQL Editor",           sublabel: "Write SQL, or compose visually, with live results",type: "action", icon: "builder", accent: "var(--t2)" },
    { id: "nav-connections", label: "Connections",          sublabel: "Manage data source connections",     type: "action", icon: "plug",     accent: "var(--grn3)" },
    { id: "nav-metrics",     label: "Metrics Catalog",      sublabel: "Semantic KPI definitions",           type: "action", icon: "metric",   accent: "var(--amb3)" },
    { id: "nav-actions",     label: "Notifications",        sublabel: "Webhooks, Slack, Jira integrations", type: "action", icon: "inbox",    accent: "var(--vio3)" },
    { id: "nav-settings",    label: "Settings",             sublabel: "Theme, model, system configuration", type: "action", icon: "settings", accent: "var(--t3)" },
  ];

  const NAV_DISPATCH: Record<string, () => void> = {
    "nav-canvases":    () => onNavigate("canvases"),
    "nav-recents":     () => onNavigate("recents"),
    "nav-inbox":       () => onNavigate("inbox"),
    "nav-intel":       () => onNavigate("intel"),
    "nav-ontology":    () => onNavigate("ontology"),
    "nav-health":      () => onNavigate("health"),
    "nav-agentic-ops": () => onNavigate("agentic-ops"),
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
    const cmdItems: PaletteItem[] = commands.map(c => ({
      id: c.id,
      label: c.label,
      sublabel: c.sublabel,
      keywords: c.keywords,
      type: "command" as ItemType,
      icon: c.icon ?? "spark",
      accent: c.accent ?? "var(--vio3)",
      onSelect: c.run,
    }));

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

    return [...cmdItems, ...navItems, ...invItems, ...tableItems];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commands, investigations, tables]);

  // ── Fuse fuzzy search ─────────────────────────────────────────────────────

  const fuse = useMemo(() => new Fuse(allItems, {
    keys: [
      { name: "label",    weight: 2 },
      { name: "sublabel", weight: 1 },
      { name: "keywords", weight: 1 },
    ],
    threshold: 0.35,
    includeMatches: true,
    minMatchCharLength: 1,
  }), [allItems]);

  const results: FuseResult<PaletteItem>[] = useMemo(() => {
    if (!query.trim()) {
      // No query — show defaults: all commands, top nav, then a few recents + tables.
      const defaults = [
        ...allItems.filter(i => i.type === "command"),
        ...allItems.filter(i => ["nav-canvases","nav-recents","nav-catalog","nav-builder"].includes(i.id)),
        ...allItems.filter(i => i.type === "investigation").slice(0, 4),
        ...allItems.filter(i => i.type === "table").slice(0, 4),
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
        style={{ position: "fixed", inset: 0, background: "var(--scrim)", backdropFilter: "blur(3px)", zIndex: 200 }}
      />

      {/* Palette */}
      <div className="aug-anim-pop" style={{
        position: "fixed", top: "14%", left: "50%", transform: "translateX(-50%)",
        zIndex: 201, width: "100%", maxWidth: 580,
        background: "var(--bg-2)", border: "1px solid var(--b2)",
        borderRadius: "var(--r3)", overflow: "hidden",
        boxShadow: "var(--shadow-xl)",
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
