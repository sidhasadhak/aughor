"use client";

/**
 * CI-6b — the chat-first surface: a full-page conversation at `/chat`.
 *
 * "B's posture, C's plumbing, one application" (the roadmap's re-decision): this is
 * a LAYOUT, not a deployment unit. Same Next.js app, same ChatPanel and ThreadsRail
 * the workspace panel uses, same tokens, same auth/org scoping — a standalone chat
 * app was rejected for fragmentation, not for technical risk. The workspace inverts
 * from frame to destination: "Open in workbench" is a link, and if this route
 * underwhelms we lose a route, not an application.
 *
 * CA-1: the panel underneath crossed the seam — every turn streams through the
 * AI-SDK parts model (`/api/chat` → `projectThread` → the organ suite), thread
 * selection restores `UIMessage[]` via `setMessages`, and regen/edit ride along.
 * What is still deliberately NOT here: any second copy of chat state — thread
 * selection uses the SAME remount mechanism the workspace uses (key bump), so
 * ChatPanel remains the one owner of a conversation's lifecycle.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getConnections, getOrgLLM, type Connection } from "@/lib/api";
import { ChatPanel } from "@/components/ChatPanel";
import { ThreadsRail } from "@/components/ThreadsRail";
import { Button } from "@/components/ui/button";

/** The BYOK model chip — whose inference this org's turns run on (CI-5b). Renders
 *  nothing until loaded, and nothing at all for an unconfigured org on the
 *  deployment default: the chip earns its pixels by saying something non-obvious. */
function ModelChip() {
  const [label, setLabel] = useState("");
  useEffect(() => {
    getOrgLLM()
      .then((c) => {
        if (!c.configured || !c.backend) return;
        const coder = c.models?.coder;
        setLabel(coder ? `${c.backend} · ${coder}` : c.backend);
      })
      .catch(() => {});
  }, []);
  if (!label) return null;
  return (
    <span
      className="aug-fs-xs"
      style={{
        color: "var(--t3)", border: "1px solid var(--b1)",
        borderRadius: "var(--r-chip)", padding: "2px 10px",
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        maxWidth: 260,
      }}
      title="Your organization's own model binding (Settings ▸ Organization ▸ Models & keys)"
    >
      {label}
    </span>
  );
}

export default function ChatHome() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connId, setConnId] = useState<string>("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getConnections()
      .then((rows) => {
        setConnections(rows);
        // Deep-linkable: /chat?conn=<id>&chat=<session> restores a specific thread.
        const params = new URLSearchParams(window.location.search);
        const conn = params.get("conn");
        const chat = params.get("chat");
        const first = rows.find((c) => c.id === conn) ?? rows[0];
        if (first) setConnId(first.id);
        if (chat) setSessionId(chat);
      })
      .catch(() => setConnections([]))
      .finally(() => setLoaded(true));
  }, []);

  const conn = useMemo(
    () => connections.find((c) => c.id === connId),
    [connections, connId],
  );

  if (loaded && connections.length === 0) {
    return (
      <div style={{ height: "100dvh", display: "flex", alignItems: "center",
                    justifyContent: "center", background: "var(--bg-0)" }}>
        <div style={{ textAlign: "center", maxWidth: 380 }}>
          <div className="aug-fs-lg" style={{ color: "var(--t1)", marginBottom: 8 }}>
            Nothing to talk to yet
          </div>
          <div className="aug-fs-sm" style={{ color: "var(--t3)", marginBottom: 16 }}>
            Connect a warehouse in the workbench and the conversation starts here.
          </div>
          <Link href="/"><Button variant="default" size="sm">Open the workbench</Button></Link>
        </div>
      </div>
    );
  }

  return (
    <div style={{ height: "100dvh", display: "flex", flexDirection: "column",
                  background: "var(--bg-0)", overflow: "hidden" }}>
      {/* ── header: identity, connection, model chip, the way back ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                    padding: "10px 16px", borderBottom: "1px solid var(--b1)",
                    flexShrink: 0 }}>
        <span className="aug-fs-md" style={{ color: "var(--t1)", fontWeight: 600 }}>
          Aughor
        </span>
        {connections.length > 1 ? (
          <select
            className="aug-input"
            value={connId}
            style={{ width: "auto", cursor: "pointer" }}
            onChange={(e) => {
              setConnId(e.target.value);
              setSessionId(null);
              setChatKey((k) => k + 1);
            }}
          >
            {connections.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        ) : (
          conn && <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>{conn.name}</span>
        )}
        <ModelChip />
        <div style={{ flex: 1 }} />
        <Link
          href={sessionId && connId ? `/?chat=${encodeURIComponent(sessionId)}` : "/"}
          title="The same conversation, inside the full workspace"
        >
          <Button variant="ghost" size="xs">Open in workbench</Button>
        </Link>
      </div>

      {/* ── body: threads beside the conversation, same organs as the workspace ── */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden", minHeight: 0 }}>
        {connId && (
          <ThreadsRail
            connectionId={connId}
            activeSessionId={sessionId}
            onSelect={(sid) => { setSessionId(sid); setChatKey((k) => k + 1); }}
            onNew={() => { setSessionId(null); setChatKey((k) => k + 1); }}
          />
        )}
        {/* voice typography: one centered reading column, the page IS the conversation */}
        <div style={{ flex: 1, display: "flex", justifyContent: "center",
                      overflow: "hidden", minWidth: 0 }}>
          <div style={{ flex: 1, maxWidth: 920, display: "flex",
                        flexDirection: "column", overflow: "hidden", minWidth: 0 }}>
            {connId && (
              <ChatPanel
                key={chatKey}
                connectionId={connId}
                restoreSessionId={sessionId}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
