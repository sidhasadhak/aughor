"use client";

/**
 * SE-2 PR E — saved queries, for the whole Query workbench.
 *
 * This was the visual builder's alone. The SQL editor could write a query, run it, name
 * a tab for it and lose all of it on the next connection switch — `/saved-queries` was
 * right there, connection-scoped, with full CRUD, and nothing in SQL mode ever called
 * it. That is the gap this closes: one saved surface, both modes.
 *
 * **What a save captures is the MODE's business, not this bar's.** A saved query is
 * `{sql, spec}`, where `spec` is opaque visual-builder state. Visual mode fills both;
 * SQL mode fills `sql` and leaves `spec` empty, which is not a degraded save — it is
 * exactly the roadmap's `sql-ahead` state, a query whose SQL is the source of truth.
 * Each mode supplies a `SavedQueryBinding` and this bar never learns what a dimension
 * is.
 *
 * **Loading routes by what was saved**, not by where you happen to be standing. A
 * query with a spec opens in Visual; one without opens in SQL. Loading a spec-carrying
 * query into the SQL editor would silently discard the builder state that IS the query,
 * and loading a hand-written statement into the builder would show an empty composer
 * next to SQL it cannot explain.
 */
import { useCallback, useEffect, useState } from "react";
import {
  listSavedQueries, createSavedQuery, updateSavedQuery, deleteSavedQuery,
  type SavedQuery,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";

/** What one mode can contribute to, and take from, the saved surface. */
export interface SavedQueryBinding {
  /** The query as it stands right now, or null when there is nothing worth saving. */
  capture: () => { sql: string; spec: Record<string, unknown> } | null;
  /** Put a saved query back on screen. */
  load: (q: SavedQuery) => void;
  /** A first-guess name, derived from the query's own content. */
  suggestName: () => string;
}

/** A query is a VISUAL one when it carries builder state. An empty object is not a
 *  spec — the builder writes at least `primaryTable`, so `{}` means SQL-authored. */
export function isVisualQuery(q: SavedQuery): boolean {
  return !!q.spec && Object.keys(q.spec).length > 0;
}

export function SavedQueryBar({
  connId,
  mode,
  binding,
  savable,
  onLoaded,
  onActiveChange,
}: {
  connId: string;
  /** Which editor is up. Decides whether Save UPDATES the open query or creates a new
   *  one — see `updatable` below. */
  mode: "visual" | "sql";
  /** The ACTIVE mode's binding. Null while that mode is still mounting. */
  binding: SavedQueryBinding | null;
  /** Whether the active mode has anything worth saving.
   *
   *  A PROP, not `binding.capture() !== null` read during render. The binding is stable
   *  by design — it reads through refs so typing does not re-render the workbench —
   *  which means calling it here would answer from whenever this bar last rendered, and
   *  Save would stay greyed out after you typed the first character. */
  savable: boolean;
  /** Told which query was loaded, so the workbench can switch to its mode first. */
  onLoaded?: (q: SavedQuery) => void;
  /** The saved query now open, or null. The workbench titles the results with it. */
  onActiveChange?: (q: SavedQuery | null) => void;
}) {
  const [list, setList] = useState<SavedQuery[]>([]);
  // The whole record, not just its id: Save has to know which MODE the open query was
  // authored in, and that is a property of the query.
  const [active, setActiveRecord] = useState<SavedQuery | null>(null);
  const [activeName, setActiveName] = useState("");
  const [open, setOpen] = useState(false);
  const [naming, setNaming] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");

  const refresh = useCallback(() => {
    if (!connId) { setList([]); return; }
    listSavedQueries(connId).then(setList).catch(() => setList([]));
  }, [connId]);

  // One place that says what is open, so every setter cannot forget to report it.
  const setActive = useCallback((q: SavedQuery | null) => {
    setActiveRecord(q);
    setActiveName(q?.name ?? "");
    onActiveChange?.(q);
  }, [onActiveChange]);

  // A saved query belongs to a connection, so the pointer to "the one you have open"
  // means nothing in the next warehouse.
  useEffect(() => {
    setActive(null);
    setOpen(false);
    setNaming(false);
    refresh();
  }, [connId, refresh, setActive]);

  // Close on Escape as well as on the backdrop. A menu that only closes by clicking
  // exactly where you are not looking is a menu people leave open.
  useEffect(() => {
    if (!open && !naming) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); setNaming(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, naming]);

  const settleSaved = () => {
    setState("saved");
    setTimeout(() => setState("idle"), 1500);
  };

  const create = async (name: string) => {
    const cap = binding?.capture();
    if (!connId || !cap || !name.trim()) return;
    setState("saving");
    try {
      const q = await createSavedQuery(connId, name.trim(), cap.sql, cap.spec);
      setActive(q);
      setNaming(false); setDraftName("");
      settleSaved();
      refresh();
    } catch (e) {
      setState("idle");
      toast.error("Could not save", { description: (e as Error).message?.slice(0, 140) });
    }
  };

  const update = async () => {
    const cap = binding?.capture();
    if (!active || !cap) return;
    setState("saving");
    try {
      const q = await updateSavedQuery(active.id, { name: activeName, sql: cap.sql, spec: cap.spec });
      setActive(q);
      settleSaved();
      refresh();
    } catch (e) {
      setState("idle");
      toast.error("Could not update", { description: (e as Error).message?.slice(0, 140) });
    }
  };

  const startCreate = () => {
    setActive(null);
    setOpen(false);
    setDraftName(binding?.suggestName() || "Untitled query");
    setNaming(true);
  };

  // Save UPDATES the open query only when that query belongs to the mode you are in.
  // Otherwise it creates a new one. Without this, saving a spec-carrying query from the
  // SQL editor — or a hand-written statement from the builder — overwrites the open
  // record with a query of the other kind, under its name, destroying the original.
  // Reachable in two clicks: save in SQL, flip to Visual, compose, Save.
  const updatable = !!active && isVisualQuery(active) === (mode === "visual");

  const onSave = () => {
    if (!savable) return;
    if (updatable) void update(); else startCreate();
  };

  const load = (q: SavedQuery) => {
    setOpen(false);
    setActive(q);
    // The workbench switches mode FIRST; the binding it then hands us is the right
    // one. Calling `binding.load` here would hand a visual query to whichever mode
    // happened to be showing.
    onLoaded?.(q);
  };

  const remove = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteSavedQuery(id);
      if (active?.id === id) setActive(null);
      refresh();
    } catch { /* best-effort; the list refresh below tells the truth either way */ }
  };

  return (
    <div className="relative flex items-center gap-1.5">
      <Button
        variant="ghost" size="xs" className="aug-fs-ui gap-1"
        title="Saved queries for this connection"
        onClick={() => { setOpen(v => !v); if (!open) refresh(); }}
      >
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.8" strokeLinecap="round" style={{ flexShrink: 0 }}>
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
        </svg>
        {activeName
          ? <span style={{ maxWidth: 110, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{activeName}</span>
          : "Saved"}
        {list.length > 0 && <span style={{ color: "var(--t4)" }}>{list.length}</span>}
      </Button>

      <Button
        variant="ghost" size="xs" className="aug-fs-ui"
        onClick={onSave}
        disabled={!savable || state === "saving"}
        title={updatable
          ? "Update this saved query"
          : active
            ? `Save as a new query — “${activeName}” was written in the ${isVisualQuery(active) ? "visual composer" : "SQL editor"}`
            : "Save the current query"}
        style={state === "saved" ? { color: "var(--grn3)" } : undefined}
      >
        {state === "saving" ? "Saving…" : state === "saved" ? "Saved ✓" : "Save"}
      </Button>

      {open && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 30 }} onClick={() => setOpen(false)} />
          <div
            style={{
              position: "absolute", right: 0, top: "100%", marginTop: 8, zIndex: 40, width: 300,
              borderRadius: "var(--r2)", border: "1px solid var(--b1)", background: "var(--bg-1)",
              boxShadow: "var(--shadow-lg)", overflow: "hidden",
            }}
          >
            <div
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "8px 12px", borderBottom: "1px solid var(--b0)",
              }}
            >
              <span className="aug-fs-ui" style={{ color: "var(--t3)", fontWeight: 600 }}>Saved queries</span>
              <Button
                variant="ghost" size="xs"
                className="aug-fs-ui h-auto p-0 font-normal hover:bg-transparent dark:hover:bg-transparent"
                style={{ color: "var(--blue3)" }}
                disabled={!savable}
                onClick={startCreate}
              >
                + Save current as…
              </Button>
            </div>

            <div style={{ maxHeight: 320, overflowY: "auto" }}>
              {list.length === 0 ? (
                <p className="aug-fs-ui" style={{ padding: "12px", color: "var(--t4)" }}>
                  No saved queries for this connection yet.
                </p>
              ) : list.map(q => (
                <div
                  key={q.id}
                  onClick={() => load(q)}
                  className="group/sq"
                  style={{
                    display: "flex", alignItems: "center", gap: 8, padding: "8px 12px",
                    cursor: "pointer", borderBottom: "1px solid var(--b0)",
                    background: q.id === active?.id ? "var(--bg-2)" : undefined,
                  }}
                >
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <p className="aug-fs-ui truncate" style={{ color: "var(--t1)" }}>{q.name}</p>
                    <p className="aug-fs-ui truncate font-mono" style={{ color: "var(--t4)" }}>
                      {(q.sql || "").replace(/\s+/g, " ").slice(0, 52)}
                    </p>
                  </div>
                  {/* Which editor this opens in, stated before you click rather than
                      discovered by watching the mode change under you. */}
                  <span className="aug-fs-ui shrink-0" style={{ color: "var(--t4)" }}>
                    {isVisualQuery(q) ? "visual" : "sql"}
                  </span>
                  <Button
                    variant="ghost" size="xs" title="Delete saved query"
                    onClick={e => void remove(q.id, e)}
                    className="h-auto shrink-0 p-0 font-normal leading-none opacity-0 transition group-hover/sq:opacity-100 hover:bg-transparent dark:hover:bg-transparent"
                    style={{ color: "var(--t4)" }}
                  >
                    ✕
                  </Button>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {naming && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 40 }} onClick={() => setNaming(false)} />
          <div
            style={{
              position: "absolute", right: 0, top: "100%", marginTop: 8, zIndex: 50, width: 300,
              borderRadius: "var(--r2)", border: "1px solid var(--b1)", background: "var(--bg-1)",
              boxShadow: "var(--shadow-lg)", padding: 12,
            }}
          >
            <p className="aug-fs-ui" style={{ color: "var(--t3)", fontWeight: 600, marginBottom: 8 }}>
              Save query as
            </p>
            <input
              autoFocus
              value={draftName}
              onChange={e => setDraftName(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter") void create(draftName);
                if (e.key === "Escape") setNaming(false);
              }}
              placeholder="Query name"
              className="aug-input aug-fs-ui"
              style={{ width: "100%" }}
            />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 10 }}>
              <Button variant="ghost" size="xs" className="aug-fs-ui" onClick={() => setNaming(false)}>
                Cancel
              </Button>
              <Button
                variant="default" size="xs" className="aug-fs-ui"
                disabled={!draftName.trim() || state === "saving"}
                onClick={() => void create(draftName)}
              >
                Save
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
