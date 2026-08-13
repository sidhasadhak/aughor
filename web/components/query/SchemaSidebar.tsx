"use client";

/**
 * SE-2 PR D — the schema sidebar: browse the catalog without leaving the editor.
 *
 * Reuses `CatalogScreen`'s idioms rather than its component: the same expansion-`Set`
 * tree, the same `typeColor` mapping for column types, the same recents key. Sharing
 * the *idioms* keeps the two surfaces recognisable as one product; sharing the
 * *component* would have meant bending a full-page browser into a 240px rail.
 *
 * The schema map is passed in, not fetched — it is the SAME object driving completion,
 * so what you can browse and what the editor can complete are the same set by
 * construction rather than by two fetches agreeing.
 *
 * Clicking a table inserts its qualified name at the cursor; clicking a column inserts
 * the column name. Insertion, not navigation, is the point: the sidebar exists to get
 * names into the query without typing them, which is also why names are inserted
 * exactly as the warehouse spells them.
 */
import { useMemo, useState } from "react";
import Fuse from "fuse.js";
import { Button } from "@/components/ui/button";

/** Column-type colour, matching CatalogScreen's mapping so a VARCHAR looks the same
 *  in both places. */
function typeColor(t: string): string {
  const u = (t || "").toUpperCase();
  if (u.includes("VARCHAR") || u.includes("TEXT")) return "var(--blue4)";
  if (u.includes("BIGINT") || u.includes("INT")) return "var(--vio4)";
  if (u.includes("DOUBLE") || u.includes("FLOAT") || u.includes("NUMERIC")) return "var(--grn4)";
  if (u.includes("DATE") || u.includes("TIME")) return "var(--amb4)";
  if (u.includes("BOOL")) return "var(--grn4)";
  return "var(--t2)";
}

export interface SidebarTable {
  /** Qualified name as the warehouse spells it — what gets inserted. */
  name: string;
  columns: Array<{ name: string; type?: string }>;
}

const rowStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 6, width: "100%",
  padding: "3px 6px", textAlign: "left", cursor: "pointer",
  fontFamily: "var(--font-code, monospace)", fontSize: 11,
};

export function SchemaSidebar({
  tables,
  onInsert,
}: {
  tables: SidebarTable[];
  /** Insert `text` at the editor's cursor. */
  onInsert: (text: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const fuse = useMemo(
    () => new Fuse(tables, { keys: ["name", "columns.name"], threshold: 0.35, ignoreLocation: true }),
    [tables],
  );

  const shown = useMemo(() => {
    const q = query.trim();
    if (!q) return tables;
    return fuse.search(q).map(r => r.item);
  }, [query, tables, fuse]);

  const toggle = (name: string) =>
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });

  return (
    <div
      style={{
        width: 240, flexShrink: 0, display: "flex", flexDirection: "column",
        borderRight: "1px solid var(--b1)", background: "var(--bg-1)", overflow: "hidden",
      }}
    >
      <div style={{ padding: "8px 8px 6px", flexShrink: 0 }}>
        <input
          className="aug-input"
          placeholder="Search tables & columns…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          style={{ fontSize: 11, width: "100%" }}
        />
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0 4px 8px" }}>
        {shown.length === 0 && (
          <div style={{ fontSize: 11, color: "var(--t4)", padding: "6px 8px" }}>
            {tables.length ? "No match." : "No schema loaded."}
          </div>
        )}
        {shown.map(t => {
          const open = expanded.has(t.name);
          return (
            <div key={t.name}>
              <div style={{ display: "flex", alignItems: "center" }}>
                <Button
                  variant="ghost"
                  onClick={() => toggle(t.name)}
                  title={open ? "Collapse" : "Expand columns"}
                  className="h-auto px-1 py-0.5"
                  style={{ fontSize: 10, color: "var(--t4)" }}
                >
                  {open ? "▾" : "▸"}
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => onInsert(t.name)}
                  title={`Insert ${t.name} at the cursor`}
                  className="h-auto flex-1 justify-start px-1 py-0.5 font-normal"
                  style={{ ...rowStyle, color: "var(--t1)" }}
                >
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {t.name}
                  </span>
                  <span style={{ marginLeft: "auto", color: "var(--t4)", fontSize: 10 }}>
                    {t.columns.length}
                  </span>
                </Button>
              </div>
              {open && t.columns.map(c => (
                <Button
                  key={c.name}
                  variant="ghost"
                  onClick={() => onInsert(c.name)}
                  title={`Insert ${c.name}${c.type ? ` (${c.type})` : ""} at the cursor`}
                  className="h-auto w-full justify-start py-0.5 pl-6 pr-1 font-normal"
                  style={rowStyle}
                >
                  <span style={{ color: "var(--t2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {c.name}
                  </span>
                  {c.type && (
                    <span style={{ marginLeft: "auto", color: typeColor(c.type), fontSize: 10 }}>
                      {c.type.toLowerCase()}
                    </span>
                  )}
                </Button>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
