"use client";

/**
 * WorkspaceSwitcher — the top-level scope selector, extracted from page.tsx.
 *
 * A Workspace is a named grouping of DB connections; switching it re-scopes the
 * whole app. This component now also OWNS membership: before it, creating a
 * workspace always sent an empty connection list and no surface anywhere could
 * add a connection to it afterwards — the new workspace cleared the selected
 * connection and every panel rendered blank, permanently. The manage view is
 * that missing surface: a checkbox per connection, saved through the PUT the
 * backend has accepted all along, plus the delete the API offered and no
 * button reached. Creating a workspace drops you straight into it, so a new
 * workspace starts populatable instead of dead.
 */
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import type { Connection, Workspace } from "@/lib/api";

/** One spacing system for the whole popover. Every row — a workspace, the section
 *  header, the divider, the footer — shares this horizontal inset, so the icons, the
 *  names and the trailing controls all sit on the same two vertical lines. Before this
 *  there were five different paddings in one 280px panel, which is most of what read
 *  as untidy. */
const ROW_PAD = "7px 8px";
/** The trailing check's slot, RESERVED on every row: a mark that appears only on the
 *  selected row would shift that row's name by its own width. */
const CHECK_SLOT = 14;

function Glyph({ name, size = 14, color = "currentColor" }: {
  name: string; size?: number; color?: string;
}) {
  return (
    <span style={{ color, display: "inline-flex", flexShrink: 0 }}>
      <Icon name={name as IconName} size={size} />
    </span>
  );
}

export function WorkspaceSwitcher({
  workspaces,
  selectedWorkspace,
  allConnections,
  onWorkspaceChange,
  onCreateWorkspace,
  onUpdateWorkspace,
  onDeleteWorkspace,
}: {
  workspaces: Workspace[];
  selectedWorkspace: string;
  /** Every connection in the org — the membership editor offers all of them,
   *  not just the active workspace's slice (which is exactly what an empty
   *  workspace doesn't have). */
  allConnections: Connection[];
  onWorkspaceChange: (id: string) => void;
  /** Creates and RETURNS the workspace, so the switcher can open its
   *  membership editor immediately. */
  onCreateWorkspace: (name: string) => Promise<Workspace>;
  onUpdateWorkspace: (id: string, connectionIds: string[]) => Promise<void>;
  onDeleteWorkspace: (id: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  /** Workspace id whose membership is being edited; null = the list view. */
  const [managing, setManaging] = useState<string | null>(null);
  const [draft, setDraft] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const active = workspaces.find(w => w.id === selectedWorkspace);
  const managed = managing ? workspaces.find(w => w.id === managing) : undefined;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false); setCreating(false); setManaging(null); setError(null);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const startManaging = (w: Workspace) => {
    setManaging(w.id);
    setDraft([...w.connection_ids]);
    setError(null);
  };

  const submitNew = async () => {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      const ws = await onCreateWorkspace(name);
      setNewName("");
      setCreating(false);
      // Straight into membership — an empty workspace with no editor was the
      // dead-end this component exists to close.
      setManaging(ws.id);
      setDraft([...ws.connection_ids]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed.");
    } finally { setBusy(false); }
  };

  const saveMembership = async () => {
    if (!managing) return;
    setBusy(true);
    setError(null);
    try {
      await onUpdateWorkspace(managing, draft);
      setManaging(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally { setBusy(false); }
  };

  const removeWorkspace = async () => {
    if (!managed) return;
    if (!window.confirm(
      `Delete workspace “${managed.name}”? Its connections are not deleted — they stay in the org.`)) return;
    setBusy(true);
    setError(null);
    try {
      await onDeleteWorkspace(managed.id);
      setManaging(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed.");
    } finally { setBusy(false); }
  };

  const toggleDraft = (id: string) =>
    setDraft(d => (d.includes(id) ? d.filter(x => x !== id) : [...d, id]));

  return (
    <div ref={ref} style={{ position: "relative", flexShrink: 0 }}>
      <Button
        onClick={() => setOpen(v => !v)}
        title="Switch workspace"
        aria-label="Switch workspace"
        variant="ghost"
        size="sm"
        /* `h-auto`: the size variants are single-line boxes (`sm` is 28px) and this
           trigger stacks a label over a name. Constrained, the two lines overlap. */
        className="h-auto font-normal"
        style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "5px 10px", borderRadius: "var(--r2)",
          background: open ? "var(--bg-sel)" : "var(--bg-2)",
          border: `1px solid ${open ? "var(--blue2)" : "var(--b1)"}`,
          color: "var(--t1)", maxWidth: 220,
        }}
      >
        <Glyph name="layers" size={14} color="var(--blue4)" />
        <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start",
          minWidth: 0, gap: 1 }}>
          <span className="aug-fs-xs" style={{ color: "var(--t4)", textTransform: "uppercase",
            letterSpacing: ".06em", lineHeight: 1.2 }}>Workspace</span>
          <span className="aug-fs-sm" style={{ fontWeight: 500, color: "var(--t1)",
            lineHeight: 1.3, whiteSpace: "nowrap", overflow: "hidden",
            textOverflow: "ellipsis", maxWidth: 150 }}>
            {active?.name ?? "—"}
          </span>
        </span>
        <Glyph name="chevd" size={13} color="var(--t3)" />
      </Button>

      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 6px)", right: 0, zIndex: 100,
          minWidth: 280, background: "var(--bg-1)", border: "1px solid var(--b2)",
          borderRadius: "var(--r3)", boxShadow: "var(--shadow-lg, 0 8px 28px rgba(0,0,0,.4))",
          padding: 6,
        }}>
          {error && (
            <div className="aug-fs-xs" style={{ color: "var(--red4)", padding: "4px 8px" }}>{error}</div>
          )}

          {managed ? (
            /* ── membership editor ── */
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 8px 4px" }}>
                <span className="aug-fs-xs" style={{ color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {managed.name} · connections
                </span>
                <Button variant="ghost" size="xs" disabled={busy}
                  onClick={() => { setManaging(null); setError(null); }}>Back</Button>
              </div>
              {allConnections.length === 0 ? (
                <div className="aug-fs-sm" style={{ color: "var(--t3)", padding: "6px 8px 8px",
                  lineHeight: 1.4 }}>
                  No connections in the org yet — add one first, then pick it here.
                </div>
              ) : (
                <div style={{ maxHeight: 240, overflowY: "auto" }}>
                  {allConnections.map(c => (
                    <label key={c.id} className="aug-fs-sm" style={{
                      display: "flex", alignItems: "center", gap: 9, padding: ROW_PAD,
                      borderRadius: "var(--r2)", cursor: "pointer", color: "var(--t1)",
                    }}>
                      <input type="checkbox" checked={draft.includes(c.id)}
                        disabled={busy} onChange={() => toggleDraft(c.id)} />
                      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</span>
                    </label>
                  ))}
                </div>
              )}
              <div className="aug-fs-xs" style={{ color: "var(--t4)", padding: "4px 8px 7px",
                lineHeight: 1.4 }}>
                Checked connections belong to this workspace — every panel scopes to them.
              </div>
              <div style={{ display: "flex", gap: 6, padding: "0 8px 6px" }}>
                <Button onClick={saveMembership} variant="secondary" size="sm" disabled={busy}
                  className="aug-fs-sm" style={{ flex: 1 }}>
                  {busy ? "Saving…" : "Save"}
                </Button>
                {!managed.is_default && (
                  <Button onClick={removeWorkspace} variant="ghost" size="sm" disabled={busy}
                    title="Delete this workspace (its connections stay in the org)"
                    className="aug-fs-sm" style={{ color: "var(--red4)" }}>
                    <Glyph name="trash" size={13} color="var(--red4)" />
                  </Button>
                )}
              </div>
            </>
          ) : (
            /* ── workspace list ── */
            <>
              <div className="aug-fs-xs" style={{ color: "var(--t4)",
                textTransform: "uppercase", letterSpacing: ".06em", padding: "6px 8px 5px" }}>
                Workspaces
              </div>
              {workspaces.map(w => {
                const on = w.id === selectedWorkspace;
                return (
                  /* The ROW is the hover unit, not the name button inside it. Hovering
                     the manage control used to leave the row unlit, so the two halves of
                     one row highlighted separately — half the untidiness on its own. */
                  <div
                    key={w.id}
                    style={{
                      display: "flex", alignItems: "center", gap: 2,
                      borderRadius: "var(--r2)",
                      background: on ? "var(--bg-sel)" : "transparent",
                    }}
                    onMouseEnter={e => { if (!on) e.currentTarget.style.background = "var(--bg-hover)"; }}
                    onMouseLeave={e => { if (!on) e.currentTarget.style.background = "transparent"; }}
                  >
                    <Button
                      onClick={() => { onWorkspaceChange(w.id); setOpen(false); }}
                      variant="ghost"
                      size="sm"
                      /* `h-auto`: `size="sm"` is a 28px single-line box and this row
                         stacks a name over a count — constrained, the second line
                         overlapped the row below it. */
                      className="h-auto font-normal"
                      style={{
                        display: "flex", alignItems: "center", gap: 9, flex: 1, minWidth: 0,
                        padding: ROW_PAD, borderRadius: "var(--r2)",
                        background: "transparent", border: "1px solid transparent",
                        textAlign: "left",
                      }}
                    >
                      <Glyph name="layers" size={14} color={on ? "var(--blue4)" : "var(--t3)"} />
                      <span style={{ flex: 1, minWidth: 0, display: "flex",
                        flexDirection: "column", gap: 1 }}>
                        <span className="aug-fs-sm" style={{ fontWeight: on ? 500 : 400,
                          color: "var(--t1)", lineHeight: 1.35, whiteSpace: "nowrap",
                          overflow: "hidden", textOverflow: "ellipsis" }}>
                          {w.name}
                        </span>
                        <span className="aug-fs-xs" style={{ color: "var(--t4)",
                          lineHeight: 1.35, whiteSpace: "nowrap", overflow: "hidden",
                          textOverflow: "ellipsis" }}>
                          {(() => {
                            // What the workspace SEES (membership ∪ grants), with the
                            // grant-only surplus called out — a row that counted only
                            // membership understated a granted workspace as empty.
                            const seen = (w.accessible_connection_ids ?? w.connection_ids).length;
                            const granted = seen - w.connection_ids.length;
                            return `${seen} connection${seen === 1 ? "" : "s"}`
                              + (granted > 0 ? ` · ${granted} via grant` : "")
                              + (w.is_default ? " · default" : "");
                          })()}
                        </span>
                      </span>
                      <span style={{ width: CHECK_SLOT, display: "inline-flex",
                        justifyContent: "flex-end", flexShrink: 0 }}>
                        {on && <Glyph name="check" size={13} color="var(--blue4)" />}
                      </span>
                    </Button>
                    <Button
                      onClick={() => startManaging(w)}
                      variant="ghost"
                      size="icon-sm"
                      title={`Manage ${w.name} — connections and deletion`}
                      aria-label={`Manage ${w.name}`}
                      /* Dimmer than the name it sits beside: three pencils at full
                         strength in a 280px popover read as three competing actions,
                         when the row's own job is switching. */
                      style={{ color: "var(--t4)", flexShrink: 0, marginRight: 2 }}
                    >
                      <Glyph name="edit" size={13} />
                    </Button>
                  </div>
                );
              })}

              <div style={{ height: 1, background: "var(--b1)", margin: "7px 8px" }} />

              {creating ? (
                <div style={{ display: "flex", gap: 6, padding: "2px 8px 6px" }}>
                  <input
                    autoFocus
                    className="aug-fs-sm"
                    value={newName}
                    onChange={e => setNewName(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter") submitNew(); if (e.key === "Escape") { setCreating(false); setNewName(""); } }}
                    placeholder="Workspace name…"
                    style={{
                      flex: 1, minWidth: 0, padding: "6px 9px",
                      background: "var(--bg-2)", border: "1px solid var(--b2)",
                      borderRadius: "var(--r2)", color: "var(--t1)", outline: "none",
                    }}
                  />
                  <Button onClick={submitNew} variant="secondary" size="sm" disabled={busy}
                    className="aug-fs-sm">
                    {busy ? "…" : "Create"}
                  </Button>
                </div>
              ) : (
                <Button
                  onClick={() => setCreating(true)}
                  variant="ghost"
                  size="sm"
                  className="h-auto font-normal"
                  style={{
                    display: "flex", alignItems: "center", gap: 9, width: "100%",
                    padding: ROW_PAD, borderRadius: "var(--r2)",
                    background: "transparent", border: "1px solid transparent",
                    color: "var(--t2)", textAlign: "left",
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = "var(--bg-hover)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
                >
                  {/* Same icon column and inset as a workspace row, so the list and its
                      one action read as one column rather than two stacked designs. */}
                  <Glyph name="plus" size={14} color="var(--t3)" />
                  <span className="aug-fs-sm">New workspace</span>
                </Button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
