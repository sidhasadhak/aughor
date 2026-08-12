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
 */
import { useCallback, useEffect, useState } from "react";
import { getApiBase } from "@/lib/config";
import { relTime } from "@/lib/format";
import { Button } from "@/components/ui/button";

export interface ChatSessionSummary {
  session_id: string;
  title: string;
  turns: number;
  last_at: string;
}

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

  const load = useCallback(() => {
    fetch(`${getApiBase()}/chat-sessions?conn_id=${encodeURIComponent(connectionId)}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: ChatSessionSummary[]) => setThreads(Array.isArray(rows) ? rows : []))
      .catch(() => setThreads([]))
      .finally(() => setLoaded(true));
  }, [connectionId]);

  useEffect(() => { load(); }, [load]);

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
      <div style={{ flex: 1, overflowY: "auto", padding: "0 6px 8px" }}>
        {threads.map((t) => {
          const active = t.session_id === activeSessionId;
          return (
            <Button
              key={t.session_id}
              variant="ghost"
              onClick={() => onSelect(t.session_id)}
              className="mb-0.5 block h-auto w-full whitespace-normal px-2 py-1.5 text-left font-normal"
              style={{ background: active ? "var(--bg-3)" : undefined }}
            >
              <span
                className="aug-fs-xs block"
                style={{
                  color: active ? "var(--t1)" : "var(--t2)",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}
              >
                {t.title}
              </span>
              <span className="aug-fs-xs block" style={{ color: "var(--t4)", marginTop: 2 }}>
                {t.turns} {t.turns === 1 ? "turn" : "turns"} · {relTime(t.last_at)} ago
              </span>
            </Button>
          );
        })}
      </div>
    </div>
  );
}
