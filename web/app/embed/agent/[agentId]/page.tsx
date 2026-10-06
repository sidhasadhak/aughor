"use client";

/**
 * Arc AO-5b — an embeddable chat page for ONE custom agent.
 *
 * The page talks only to the agent's HTTP door (`POST /doors/agents/{id}/ask`) with the
 * agent's key, which it asks for once and keeps in the browser's session storage — never in
 * the URL (a URL is copied, logged and shared) and never beyond the tab. What comes back is
 * the folded answer: the headline, the rows and the SQL that produced them, with the
 * receipt id. Nothing here reaches the rest of the API; the key opens one door.
 */
import { use, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { askThroughDoor, type DoorAnswer } from "@/lib/api";
import { displayCellValue, formatCount } from "@/lib/format";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Input } from "@/components/ui/input";

const KEY = (agentId: string) => `aughor.embed.key.${agentId}`;

export default function EmbedAgentPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = use(params);
  const [key, setKey] = useState("");
  const [draftKey, setDraftKey] = useState("");
  const [question, setQuestion] = useState("");
  const [asker, setAsker] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [turns, setTurns] = useState<DoorAnswer[]>([]);

  useEffect(() => {
    try { setKey(window.sessionStorage.getItem(KEY(agentId)) ?? ""); } catch { /* storage blocked */ }
  }, [agentId]);

  const saveKey = () => {
    const k = draftKey.trim();
    if (!k) return;
    try { window.sessionStorage.setItem(KEY(agentId), k); } catch { /* keep it in memory only */ }
    setKey(k); setDraftKey("");
  };
  const forgetKey = () => {
    try { window.sessionStorage.removeItem(KEY(agentId)); } catch { /* nothing stored */ }
    setKey(""); setTurns([]);
  };

  const ask = async () => {
    const q = question.trim();
    if (!q || !key) return;
    setBusy(true); setError("");
    try {
      const a = await askThroughDoor(agentId, key, { question: q, asker: asker.trim() || undefined });
      setTurns(ts => [a, ...ts]);
      setQuestion("");
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally { setBusy(false); }
  };

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "20px 16px", display: "flex",
      flexDirection: "column", gap: 14, color: "var(--t1)" }}>
      <div className="aug-fs-h2" style={{ fontWeight: 500 }}>Ask this agent</div>
      {!key ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: 14,
          border: "1px solid var(--b1)", borderRadius: "var(--r3)" }}>
          <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>
            Paste the agent&apos;s key (issued on its Doors tab). It stays in this tab&apos;s session
            only — not in the address bar, not on this page&apos;s server.
          </span>
          <Input type="password" value={draftKey} autoComplete="off"
            placeholder="the agent's key" aria-label="Agent key"
            onChange={e => setDraftKey(e.target.value)} onKeyDown={e => { if (e.key === "Enter") saveKey(); }} />
          <span><Button variant="default" size="sm" onClick={saveKey} disabled={!draftKey.trim()}>Use this key</Button></span>
        </div>
      ) : (
        <>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div style={{ flex: "3 1 320px" }}>
              <label className="aug-fs-xs" style={{ color: "var(--t3)" }}>Question</label>
              <Input value={question} aria-label="Question"
                placeholder="How many orders were placed yesterday?"
                onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === "Enter") void ask(); }} />
            </div>
            <div style={{ flex: "1 1 160px" }}>
              <label className="aug-fs-xs" style={{ color: "var(--t3)" }}>Who is asking (optional)</label>
              <Input value={asker} aria-label="Asker" placeholder="you@example.com"
                onChange={e => setAsker(e.target.value)} />
            </div>
            <Button variant="default" size="sm" onClick={() => void ask()} disabled={busy || !question.trim()}>
              {busy ? "Asking…" : "Ask"}
            </Button>
            <Button variant="ghost" size="sm" onClick={forgetKey} title="Forget the key in this tab">Forget key</Button>
          </div>
          {error && <div className="aug-fs-sm" style={{ color: "var(--red4)" }}>{error}</div>}
          {turns.map((t, i) => (
            <div key={`${t.receipt_id || "turn"}-${i}`} style={{ padding: 14, border: "1px solid var(--b1)",
              borderRadius: "var(--r3)", display: "flex", flexDirection: "column", gap: 8 }}>
              <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>{t.question}</div>
              <div className="aug-fs-ui" style={{ fontWeight: 500, color: t.error ? "var(--red4)" : "var(--t1)" }}>
                {t.error || t.headline || "No answer."}
              </div>
              {t.columns.length > 0 && t.rows.length > 0 && (
                <div style={{ overflowX: "auto" }}>
                  <Table>
                    <TableHeader><TableRow>{t.columns.map(c => <TableHead key={c}>{c}</TableHead>)}</TableRow></TableHeader>
                    <TableBody>
                      {t.rows.slice(0, 50).map((r, ri) => (
                        <TableRow key={ri}>{(r as unknown[]).map((v, ci) => <TableCell key={ci}>{displayCellValue(v)}</TableCell>)}</TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {(t.truncated || t.rows.length > 50) && (
                    <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                      {formatCount(t.row_count ?? t.rows.length)} rows in all; the first 50 shown
                    </div>
                  )}
                </div>
              )}
              {t.sql && (
                <pre className="aug-fs-xs" style={{ margin: 0, padding: 10, background: "var(--bg-1)",
                  border: "1px solid var(--b1)", borderRadius: "var(--r3)", color: "var(--t2)",
                  fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap" }}>{t.sql}</pre>
              )}
              {t.receipt_id && (
                <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>receipt {t.receipt_id}</div>
              )}
            </div>
          ))}
        </>
      )}
    </main>
  );
}
