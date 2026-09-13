"use client";

/**
 * SE-8E — the AI pane: Databricks' Genie Code seat, on our consent rules.
 *
 * A right-rail conversation scoped to the ACTIVE connection and the ACTIVE tab's SQL.
 * The model can talk, and it can PROPOSE SQL — the proposal always arrives as a merge
 * diff against the buffer as it stood when the ask was made, with Apply and Dismiss.
 * Three rules, inherited from Quick Fix and from the platform's grant decision
 * (a grant authorises PROPOSE, never EXECUTE):
 *
 *   • Nothing here runs SQL. Apply only edits the document; Run stays the user's verb.
 *   • Nothing here fires without a user's message — no auto-suggestions on mount,
 *     no completion-time calls. Every model invocation is a send.
 *   • Applying is per proposal. An applied one says so; a dismissed one stays dismissed.
 *
 * Slash commands are expanded CLIENT-side into plain instructions the endpoint can
 * read (/optimize, /explain, /fix), so the server stays one dumb ask-answer seam.
 */
import { useEffect, useRef, useState } from "react";
import { MergeView } from "@codemirror/merge";
import { EditorState } from "@codemirror/state";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { aughorEditorTheme, aughorSyntaxHighlighting } from "@/components/query/editor/theme";
import { assistSql } from "@/lib/api";

interface AiMsg {
  role: "user" | "assistant";
  content: string;
  /** A proposal, diffed against the buffer as it stood at ask time. */
  proposedSql?: string;
  baseSql?: string;
  verdict?: "applied" | "dismissed";
}

const SLASH: Record<string, string> = {
  "/optimize": "Optimize this query — same result, clearer and cheaper. Explain what you changed in one sentence.",
  "/explain": "Explain what this query does, plainly, for someone who did not write it.",
  "/fix": "Fix this query.",
};

/** One read-only side-by-side diff, the same rendering Quick Fix uses. */
function ProposalDiff({ base, proposed }: { base: string; proposed: string }) {
  const host = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!host.current) return;
    const merge = new MergeView({
      a: { doc: base, extensions: [EditorState.readOnly.of(true), aughorEditorTheme, aughorSyntaxHighlighting] },
      b: { doc: proposed, extensions: [EditorState.readOnly.of(true), aughorEditorTheme, aughorSyntaxHighlighting] },
      parent: host.current,
      collapseUnchanged: { margin: 2, minSize: 4 },
      orientation: "a-b",
      gutter: false,
      highlightChanges: true,
    });
    return () => merge.destroy();
  }, [base, proposed]);
  return <div ref={host} style={{ border: "1px solid var(--b1)", borderRadius: "var(--r2)", overflow: "hidden" }} />;
}

export function AiPane({
  connId,
  getSql,
  getError,
  onApply,
}: {
  connId: string;
  /** The ACTIVE tab's buffer, read at send time — a ref-read, so typing never
   *  re-renders this pane. */
  getSql: () => string;
  /** The last run's error, for /fix. */
  getError: () => string;
  /** Replace the editor's contents. Called ONLY from a proposal's Apply. */
  onApply: (sql: string) => void;
}) {
  const [msgs, setMsgs] = useState<AiMsg[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const scroller = useRef<HTMLDivElement | null>(null);

  // A conversation is with ONE warehouse; carrying it across a switch would let
  // "add the region column" land on a schema that has no regions.
  useEffect(() => { setMsgs([]); }, [connId]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [msgs, busy]);

  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || busy || !connId) return;
    const lower = text.toLowerCase();
    const slash = Object.keys(SLASH).find(s => lower === s || lower.startsWith(`${s} `));
    const instruction = slash
      ? `${SLASH[slash]} ${text.slice(slash.length).trim()}`.trim()
      : text;
    const baseSql = getSql();
    const history = msgs.slice(-6).map(m => ({ role: m.role, content: m.content }));
    setMsgs(prev => [...prev, { role: "user", content: text }]);
    setDraft("");
    setBusy(true);
    try {
      const res = await assistSql(connId, instruction, {
        sql: baseSql,
        error: slash === "/fix" ? getError() : undefined,
        history,
      });
      setMsgs(prev => [...prev, {
        role: "assistant",
        content: res.reply || (res.changed ? "Here is the change." : "…"),
        ...(res.changed ? { proposedSql: res.proposed_sql, baseSql } : {}),
      }]);
    } catch (e) {
      setMsgs(prev => [...prev, {
        role: "assistant",
        content: e instanceof Error ? e.message : "The assistant is unavailable.",
      }]);
    } finally {
      setBusy(false);
    }
  };

  const settle = (i: number, verdict: "applied" | "dismissed") =>
    setMsgs(prev => prev.map((m, j) => j === i ? { ...m, verdict } : m));

  return (
    <div
      style={{
        flex: 1, minWidth: 0, display: "flex", flexDirection: "column",
        borderLeft: "1px solid var(--b1)", background: "var(--bg-1)", overflow: "hidden",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 10px 6px", flexShrink: 0 }}>
        <Icon name="spark" size={13} />
        <span className="aug-label">Assistant</span>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>proposes — never runs</span>
      </div>

      <div ref={scroller} style={{ flex: 1, overflowY: "auto", padding: "0 10px 8px" }}>
        {msgs.length === 0 && (
          <div className="aug-fs-ui" style={{ color: "var(--t3)", lineHeight: 1.6, padding: "4px 2px" }}>
            Ask about this connection's data, or about the SQL in the editor.
            Proposed changes arrive as a diff you apply or dismiss.
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8 }}>
              {["/optimize", "/explain", "/fix"].map(s => (
                <Button key={s} variant="secondary" size="xs" className="aug-fs-ui font-mono"
                  onClick={() => setDraft(`${s} `)}>
                  {s}
                </Button>
              ))}
            </div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} style={{ marginTop: 8 }}>
            <div className="aug-fs-xs" style={{ color: "var(--t3)", marginBottom: 2 }}>
              {m.role === "user" ? "You" : "Assistant"}
            </div>
            <div className="aug-fs-ui" style={{
              color: m.role === "user" ? "var(--t2)" : "var(--t1)",
              whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.5,
            }}>
              {m.content}
            </div>
            {m.proposedSql && m.baseSql !== undefined && (
              <div style={{ marginTop: 6 }}>
                {m.verdict !== "dismissed" && (
                  <ProposalDiff base={m.baseSql} proposed={m.proposedSql} />
                )}
                <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
                  {m.verdict === "applied" ? (
                    <span className="aug-fs-ui" style={{ color: "var(--grn4)" }}>Applied to the editor</span>
                  ) : m.verdict === "dismissed" ? (
                    <span className="aug-fs-ui" style={{ color: "var(--t3)" }}>Dismissed</span>
                  ) : (
                    <>
                      <Button variant="default" size="xs" className="aug-fs-ui"
                        onClick={() => { onApply(m.proposedSql!); settle(i, "applied"); }}>
                        Apply
                      </Button>
                      <Button variant="ghost" size="xs" className="aug-fs-ui"
                        onClick={() => settle(i, "dismissed")}>
                        Dismiss
                      </Button>
                      <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                        edits the document — running stays yours
                      </span>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="aug-fs-ui" style={{ color: "var(--t3)", marginTop: 8 }}>Thinking…</div>
        )}
      </div>

      <div style={{ display: "flex", gap: 6, padding: "6px 10px 10px", borderTop: "1px solid var(--b0)", flexShrink: 0 }}>
        <input
          className="aug-input aug-fs-ui"
          style={{ flex: 1 }}
          placeholder="Ask, or /optimize · /explain · /fix"
          value={draft}
          disabled={busy}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") void send(draft); }}
        />
        <Button variant="default" size="xs" disabled={busy || !draft.trim()}
          aria-label="Send" onClick={() => void send(draft)}>
          <Icon name="send" size={13} />
        </Button>
      </div>
    </div>
  );
}
