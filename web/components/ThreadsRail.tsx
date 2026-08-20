"use client";
/**
 * CI-6a — the threads rail: this connection's recent conversations, resumable.
 *
 * The chat already had multi-turn sessions (CI-1 filed every turn under a
 * session_id, and `?chat=` restores one); what it lacked was a way to SEE them —
 * a conversation that vanished when the tab closed read as a chat with no memory,
 * whatever the store held. The rail is the visible half of the memory that
 * already exists: pick a thread, the panel restores it; "New" starts a fresh one.
 *
 * Selection goes through the SAME remount mechanism page.tsx already uses for
 * history restore (setSelectedChatSessionId + chatKey bump) — the rail navigates,
 * it does not own chat state.
 *
 * CA-5 — the rail becomes a place you can KEEP things, not just a log you can read:
 * rename (a thread's derived title is the first thing the user typed, which is the
 * vaguest thing they will say in that conversation), delete (a real delete, footprint
 * and all — see the route), and filter, which only appears once there are enough
 * threads that scanning them stops being instant.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getApiBase } from "@/lib/config";
import { relTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface ChatSessionSummary {
  session_id: string;
  title: string;
  /** True when the title is the user's own, not the opening question (CA-5). */
  renamed?: boolean;
  turns: number;
  last_at: string;
}

/** Threads past this count get a filter box — below it, the eye is faster. */
const FILTER_THRESHOLD = 6;

export function ThreadsRail({
  connectionId,
  activeSessionId,
  onSelect,
  onNew,
}: {
  connectionId: string;
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onNew: () => void;
}) {
  const [threads, setThreads] = useState<ChatSessionSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const renameRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(() => {
    fetch(`${getApiBase()}/chat-sessions?conn_id=${encodeURIComponent(connectionId)}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: ChatSessionSummary[]) => setThreads(Array.isArray(rows) ? rows : []))
      .catch(() => setThreads([]))
      .finally(() => setLoaded(true));
  }, [connectionId]);

  useEffect(() => { load(); }, [load]);

  // Focus the rename box as it opens — a rename that needs a second click to type in
  // is a rename nobody uses.
  useEffect(() => { if (renaming) renameRef.current?.select(); }, [renaming]);

  const commitRename = useCallback((sessionId: string) => {
    const title = draft.trim();
    setRenaming(null);
    // Optimistic: the rail is a navigation surface, and waiting on a round-trip to
    // see your own typing is the lag this wave exists to remove. A failed write is
    // corrected by the reload that follows it.
    setThreads((prev) => prev.map((t) =>
      t.session_id === sessionId
        ? { ...t, title: title || t.title, renamed: !!title }
        : t));
    fetch(`${getApiBase()}/chat-sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }).catch(() => { /* best-effort */ }).finally(load);
  }, [draft, load]);

  const remove = useCallback((sessionId: string) => {
    setConfirmDelete(null);
    setThreads((prev) => prev.filter((t) => t.session_id !== sessionId));
    fetch(`${getApiBase()}/chat-sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" })
      .catch(() => { /* best-effort */ })
      .finally(() => {
        load();
        // The open conversation just stopped existing — showing its turns would be
        // showing a thread the store no longer has. Start a fresh one instead.
        if (sessionId === activeSessionId) onNew();
      });
  }, [activeSessionId, load, onNew]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return threads;
    return threads.filter((t) => t.title.toLowerCase().includes(q));
  }, [threads, query]);

  // An empty store renders nothing rather than an empty shell: the rail earns its
  // pixels only once there is a second conversation worth returning to.
  if (loaded && threads.length === 0) return null;

  return (
    <div
      style={{
        width: 208, flexShrink: 0, display: "flex", flexDirection: "column",
        borderRight: "1px solid var(--b1)", background: "var(--bg-1)",
        overflow: "hidden",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "10px 10px 6px" }}>
        <span className="aug-label">Conversations</span>
        <Button variant="ghost" size="xs" onClick={onNew}>New</Button>
      </div>

      {threads.length > FILTER_THRESHOLD && (
        <div style={{ padding: "0 8px 6px" }}>
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter conversations"
            aria-label="Filter conversations"
            className="aug-fs-xs h-7"
          />
        </div>
      )}

      <div style={{ flex: 1, overflowY: "auto", padding: "0 6px 8px" }}>
        {shown.length === 0 && query.trim() !== "" && (
          <div className="aug-fs-xs" style={{ color: "var(--t4)", padding: "6px 8px" }}>
            No conversation matches “{query.trim()}”.
          </div>
        )}
        {shown.map((t) => {
          const active = t.session_id === activeSessionId;
          const isRenaming = renaming === t.session_id;
          const isConfirming = confirmDelete === t.session_id;

          if (isRenaming) {
            return (
              <div key={t.session_id} style={{ padding: "2px 2px 6px" }}>
                <Input
                  ref={renameRef}
                  value={draft}
                  autoFocus
                  aria-label="Conversation name"
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitRename(t.session_id);
                    if (e.key === "Escape") setRenaming(null);
                  }}
                  onBlur={() => commitRename(t.session_id)}
                  className="aug-fs-xs h-7"
                />
                <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 3, paddingLeft: 2 }}>
                  Enter to save · empty restores the first question
                </div>
              </div>
            );
          }

          return (
            <div
              key={t.session_id}
              className="group"
              style={{
                position: "relative", borderRadius: "var(--r2)", marginBottom: 2,
                background: active ? "var(--bg-3)" : undefined,
              }}
            >
              <Button
                variant="ghost"
                onClick={() => onSelect(t.session_id)}
                className="block h-auto w-full whitespace-normal px-2 py-1.5 text-left font-normal hover:bg-transparent dark:hover:bg-transparent"
              >
                <span
                  className="aug-fs-xs block"
                  style={{
                    color: active ? "var(--t1)" : "var(--t2)",
                    // Room for the two hover actions so a long title never slides under them.
                    paddingRight: 34,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}
                  title={t.title}
                >
                  {t.title}
                </span>
                <span className="aug-fs-xs block" style={{ color: "var(--t4)", marginTop: 2 }}>
                  {t.turns} {t.turns === 1 ? "turn" : "turns"} · {relTime(t.last_at)} ago
                </span>
              </Button>

              {/* Hover actions — invisible until the row is hovered or focused within,
                  so the rail stays a list of conversations rather than a toolbar. */}
              {!isConfirming && (
                <div
                  className="opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity"
                  style={{ position: "absolute", top: 4, right: 4, display: "flex", gap: 1 }}
                >
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    title="Rename this conversation"
                    aria-label="Rename this conversation"
                    onClick={() => { setDraft(t.renamed ? t.title : ""); setRenaming(t.session_id); }}
                  >
                    <span aria-hidden className="aug-fs-xs" style={{ color: "var(--t3)" }}>✎</span>
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    title="Delete this conversation"
                    aria-label="Delete this conversation"
                    onClick={() => setConfirmDelete(t.session_id)}
                  >
                    <span aria-hidden className="aug-fs-xs" style={{ color: "var(--t3)" }}>🗑</span>
                  </Button>
                </div>
              )}

              {/* Confirm in place. A thread delete takes its turns, their evidence and
                  their index entries with it — worth one deliberate second click, not
                  worth a modal that steals the whole screen. */}
              {isConfirming && (
                <div
                  style={{
                    position: "absolute", inset: 0, display: "flex", alignItems: "center",
                    justifyContent: "flex-end", gap: 4, padding: "0 6px",
                    background: "var(--bg-2)", borderRadius: "var(--r2)",
                  }}
                >
                  <span className="aug-fs-xs" style={{ color: "var(--t3)", marginRight: "auto" }}>
                    Delete?
                  </span>
                  <Button variant="ghost" size="xs" onClick={() => setConfirmDelete(null)}>
                    Cancel
                  </Button>
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => remove(t.session_id)}
                    style={{ color: "var(--red4)" }}
                  >
                    Delete
                  </Button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
