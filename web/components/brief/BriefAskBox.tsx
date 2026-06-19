"use client";

import { useState } from "react";
import { InlineInvestigationThread } from "@/components/brief/InlineInvestigationThread";

interface Card { id: string; question: string; }

/**
 * Capability E — the living brief. A persistent ask box anchored to the briefing:
 * each question spawns an inline ADA investigation card, seeded with the brief's own
 * context (theme + top findings) so the answer is grounded in what the brief is about.
 * Answers stack; each can be opened in the full Ask surface or closed. Reuses the same
 * InlineInvestigationThread that the finding/citation/chart drills use.
 */
export function BriefAskBox({
  connectionId,
  schema,
  canvasId,
  briefContext,
  onOpenInAsk,
}: {
  connectionId: string;
  schema?: string;
  canvasId?: string;
  /** Theme + top findings — handed to ADA as seed context so it answers in the brief's terms. */
  briefContext?: string;
  onOpenInAsk: (q: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const [cards, setCards] = useState<Card[]>([]);

  function ask() {
    const q = draft.trim();
    if (!q) return;
    setCards(prev => [{ id: Math.random().toString(36).slice(2), question: q }, ...prev]);
    setDraft("");
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <div className="aug-label" style={{ marginBottom: 8 }}>Ask this briefing</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") ask(); }}
            placeholder="Ask a follow-up — e.g. “Which region drove the revenue dip?”"
            style={{
              flex: 1, fontSize: 12, padding: "9px 12px", borderRadius: "var(--r2)",
              background: "var(--bg-2)", border: "1px solid var(--b1)", color: "var(--t1)",
              outline: "none",
            }}
          />
          <button
            onClick={ask}
            disabled={!draft.trim()}
            style={{
              fontSize: 12, fontWeight: 600, padding: "9px 16px", borderRadius: "var(--r2)",
              color: draft.trim() ? "var(--bg-0)" : "var(--t4)",
              background: draft.trim() ? "var(--blue5)" : "var(--bg-2)",
              border: `1px solid ${draft.trim() ? "var(--blue5)" : "var(--b1)"}`,
              cursor: draft.trim() ? "pointer" : "default",
            }}
          >
            Ask →
          </button>
        </div>
      </div>

      {/* Newest answer on top — a living stack of investigations anchored to this brief. */}
      {cards.map(card => (
        <InlineInvestigationThread
          key={card.id}
          question={card.question}
          opts={{
            connectionId,
            schema: schema ?? null,
            canvasId: canvasId ?? null,
            seedSql: null,
            seedContext: briefContext ?? "",
          }}
          onClose={() => setCards(prev => prev.filter(c => c.id !== card.id))}
          onOpenInAsk={onOpenInAsk}
        />
      ))}
    </div>
  );
}
