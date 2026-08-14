"use client";

/**
 * `/chat/parts` — the parts model, driven end to end — CI-1d.
 *
 * A PROVING SURFACE, not the product. `/chat` keeps its ChatPanel and the
 * 107-case reducer; this route runs the same backend through the AI SDK path —
 * `useAughorChat` → `DefaultChatTransport` → `/api/chat` → `AughorToUIMessage` →
 * `/ask` — so the seam can be exercised in a browser before any surface depends
 * on it.
 *
 * It exists because the C1 spike sat for two weeks with zero consumers and three
 * type errors nobody could see, and because the ONE live run of the finished
 * route found a wire-format bug that every gate had passed. A path this long
 * needs somewhere it can actually be run.
 *
 * When the migration moves `/chat` across, this route goes away — it should not
 * outlive the thing it proves.
 */

import { useEffect, useState } from "react";

import { PartsMessage } from "@/components/chat/PartsMessage";
import { Button } from "@/components/ui/button";
import { getConnections, type Connection } from "@/lib/api";
import { useAughorChat } from "@/lib/useAughorChat";

/** Stable for the tab's lifetime — it is the SESSION the backend rebuilds history from. */
function useSessionId() {
  const [id] = useState(() => `parts_${Math.random().toString(36).slice(2, 10)}`);
  return id;
}

export default function ChatPartsPage() {
  const [conns, setConns] = useState<Connection[]>([]);
  const [connId, setConnId] = useState("");
  const [input, setInput] = useState("");
  const sessionId = useSessionId();

  useEffect(() => {
    getConnections()
      .then((c) => {
        setConns(c);
        setConnId((prev) => prev || c[0]?.id || "");
      })
      .catch(() => {});
  }, []);

  const { messages, sendMessage, status, error, stop } = useAughorChat({
    connectionId: connId,
    sessionId,
  });

  const busy = status === "submitted" || status === "streaming";

  return (
    <div style={{ padding: 16, maxWidth: 900, marginInline: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span className="aug-label" style={{ color: "var(--t3)" }}>
          parts model · /api/chat
        </span>
        <div style={{ flex: 1 }} />
        <select
          className="aug-fs-ui"
          aria-label="Connection"
          value={connId}
          onChange={(e) => setConnId(e.target.value)}
          style={{ background: "var(--bg-2)", color: "var(--t1)",
                   border: "1px solid var(--b1)", borderRadius: 4, padding: "3px 6px" }}
        >
          {conns.map((c) => <option key={c.id} value={c.id}>{c.name || c.id}</option>)}
        </select>
        {/* The status the SDK reports, shown rather than inferred — `streaming`
            and `submitted` are different states and a spinner conflates them. */}
        <span className="aug-fs-ui" style={{ color: "var(--t3)" }}>{status}</span>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          const q = input.trim();
          if (!q || !connId || busy) return;
          setInput("");
          void sendMessage({ text: q });
        }}
        style={{ display: "flex", gap: 8, marginBottom: 14 }}
      >
        <input
          className="aug-fs-ui"
          aria-label="Question"
          value={input}
          placeholder="Ask a question of this connection…"
          onChange={(e) => setInput(e.target.value)}
          style={{ flex: 1, background: "var(--bg-2)", color: "var(--t1)",
                   border: "1px solid var(--b1)", borderRadius: 4, padding: "5px 8px" }}
        />
        <Button type="submit" disabled={busy || !connId}>Ask</Button>
        {busy && <Button type="button" onClick={() => stop()}>Stop</Button>}
      </form>

      {error && (
        <p className="aug-fs-ui" style={{ color: "var(--red4)" }}>
          {error.message}
        </p>
      )}

      {messages.length === 0 && !busy && (
        <p className="aug-fs-ui" style={{ color: "var(--t3)" }}>
          No turns yet. Every frame the backend emits renders below as a typed part —
          including any this build does not recognise.
        </p>
      )}

      {messages.map((m) => <PartsMessage key={m.id} message={m} />)}
    </div>
  );
}
