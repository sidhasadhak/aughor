"use client";

/**
 * SE-8F — "+ → Open existing": one searchable place to resume work.
 *
 * Databricks' new-tab menu offers "Create new query" or "Open existing query", and the
 * open dialog searches everything with a Recent tab. This is that dialog for our
 * editor: SAVED queries (the named record) and RECENT runs (the audit log the history
 * rail already reads), behind one search box.
 *
 * **Everything opens as a COPY — a new tab with the text, linked to nothing.** Linking
 * a tab to the saved record (so Save updates it, the sync chip tracks it, versions
 * attach) is the SavedQueryBar's job, and it involves mode routing this dialog has no
 * business re-implementing. A copy can never overwrite the original, which for a
 * two-click "grab that query from last week" is the safe default.
 */
import { useEffect, useMemo, useState } from "react";
import {
  getQueryHistory, listSavedQueries, type AuditRecord, type SavedQuery,
} from "@/lib/api";
import { isVisualQuery } from "@/components/query/SavedQueryBar";
import { relTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";

/** One line of SQL, however it was written. */
function preview(sql: string): string {
  return (sql || "").replace(/\s+/g, " ").trim().slice(0, 96);
}

export function OpenQueryDialog({
  connId, open, onClose, onOpen,
}: {
  connId: string;
  open: boolean;
  onClose: () => void;
  /** Receives the SQL and a tab name; the caller opens the tab. */
  onOpen: (sql: string, name: string) => void;
}) {
  const [tab, setTab] = useState<"saved" | "recent">("saved");
  const [search, setSearch] = useState("");
  const [saved, setSaved] = useState<SavedQuery[]>([]);
  const [recent, setRecent] = useState<AuditRecord[]>([]);
  const [loaded, setLoaded] = useState(false);

  // Fetched when OPENED, not when mounted — this dialog spends most of its life
  // closed, and a stale list behind a search box misleads more than an empty one.
  useEffect(() => {
    if (!open || !connId) return;
    setLoaded(false);
    setSearch("");
    Promise.allSettled([listSavedQueries(connId), getQueryHistory(connId, 30)])
      .then(([s, r]) => {
        setSaved(s.status === "fulfilled" ? s.value : []);
        setRecent(r.status === "fulfilled" ? r.value : []);
        setLoaded(true);
      });
  }, [open, connId]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const q = search.trim().toLowerCase();
  const savedHits = useMemo(
    () => saved.filter(s => !q || `${s.name} ${s.sql}`.toLowerCase().includes(q)),
    [saved, q],
  );
  const recentHits = useMemo(
    () => recent.filter(r => !q || (r.sql_full || r.sql_digest || "").toLowerCase().includes(q)),
    [recent, q],
  );

  if (!open) return null;

  const pill = (id: "saved" | "recent", label: string, n: number) => (
    <Button
      variant={tab === id ? "secondary" : "ghost"} size="xs" className="aug-fs-ui"
      onClick={() => setTab(id)}
    >
      {label} <span style={{ color: "var(--t3)" }}>{n}</span>
    </Button>
  );

  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 60, background: "var(--scrim)" }}
        onClick={onClose} />
      <div role="dialog" aria-label="Open a query"
        style={{
          position: "fixed", zIndex: 61, top: "12vh", left: "50%", transform: "translateX(-50%)",
          width: "min(560px, 92vw)", maxHeight: "70vh", display: "flex", flexDirection: "column",
          background: "var(--bg-2)", border: "1px solid var(--b2)",
          borderRadius: "var(--r3)", boxShadow: "var(--shadow-md)", overflow: "hidden",
        }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px 8px" }}>
          <span className="aug-fs-h2" style={{ fontWeight: 600, color: "var(--t1)" }}>Open a query</span>
          <span style={{ flex: 1 }} />
          {pill("saved", "Saved", savedHits.length)}
          {pill("recent", "Recent", recentHits.length)}
          <Button variant="ghost" size="xs" onClick={onClose} aria-label="Close">
            <Icon name="close" size={13} />
          </Button>
        </div>
        <div style={{ padding: "0 12px 8px" }}>
          <input
            autoFocus
            className="aug-input aug-fs-ui"
            style={{ width: "100%" }}
            placeholder={tab === "saved" ? "Search saved queries by name or SQL…" : "Search recent runs…"}
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", borderTop: "1px solid var(--b0)" }}>
          {!loaded ? (
            <p className="aug-fs-ui" style={{ padding: 12, color: "var(--t3)" }}>Loading…</p>
          ) : tab === "saved" ? (
            savedHits.length === 0 ? (
              <p className="aug-fs-ui" style={{ padding: 12, color: "var(--t3)" }}>
                {saved.length === 0
                  ? "No saved queries for this connection yet — Save names the current tab."
                  : "Nothing matches this search."}
              </p>
            ) : savedHits.map(s => (
              <Button key={s.id} variant="ghost"
                onClick={() => { onOpen(s.sql, s.name); onClose(); }}
                title="Open this query's SQL in a new tab (a copy — Save creates a new record)"
                className="block h-auto w-full whitespace-normal px-3 py-2 text-left font-normal"
                style={{ borderBottom: "1px solid var(--b0)", borderRadius: 0 }}>
                <span className="aug-fs-ui" style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                  <span style={{ color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
                  <span style={{ flex: 1 }} />
                  <span style={{ color: "var(--t3)", flexShrink: 0 }}>{isVisualQuery(s) ? "visual" : "sql"}</span>
                </span>
                <span className="aug-fs-ui font-mono" style={{
                  display: "block", color: "var(--t3)", overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 2,
                }}>
                  {preview(s.sql)}
                </span>
              </Button>
            ))
          ) : recentHits.length === 0 ? (
            <p className="aug-fs-ui" style={{ padding: 12, color: "var(--t3)" }}>
              {recent.length === 0 ? "Nothing has run on this connection yet." : "Nothing matches this search."}
            </p>
          ) : recentHits.map(r => (
            <Button key={r.id} variant="ghost"
              onClick={() => { onOpen(r.sql_full || r.sql_digest, "History"); onClose(); }}
              title="Open this run's SQL in a new tab"
              className="block h-auto w-full whitespace-normal px-3 py-2 text-left font-normal"
              style={{ borderBottom: "1px solid var(--b0)", borderRadius: 0 }}>
              <span className="aug-fs-ui font-mono" style={{
                display: "block", color: "var(--t2)", overflow: "hidden",
                textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>
                {preview(r.sql_full || r.sql_digest)}
              </span>
              <span className="aug-fs-ui" style={{ display: "block", color: "var(--t3)", marginTop: 2 }}>
                {r.row_count != null && `${r.row_count} rows · `}{r.ts && `${relTime(r.ts)} ago`}
              </span>
            </Button>
          ))}
        </div>
      </div>
    </>
  );
}
