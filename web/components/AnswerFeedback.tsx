"use client";
/**
 * The one feedback control on an answer: thumbs at the answer's foot, in both modes.
 *
 * Until 2026-10-22 a quick answer drew the thumbs twice — the panel's pair under the
 * answer (R10) and a second pair inside "Methodology & details" — and both posted the
 * same verdict for the same receipt to /chat/feedback. One control now carries what the
 * two did between them: 👍 records the accept with the SQL the turn ran (PENDING item 23;
 * the server teaches the learned table prior from the same call), 👎 records the signal
 * and opens the typed what-was-wrong form, whose correction flows through record_verdict
 * into the ledger so the next answer cites it.
 */
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { FixItForm } from "@/components/FixItForm";
import { recordVerdict, sendChatFeedback } from "@/lib/api";
import type { ChatTurn } from "@/lib/chatTurn";

type Verdict = "helpful" | "unhelpful";

export function AnswerFeedback({ turn, connectionId }: { turn: ChatTurn; connectionId: string }) {
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [fixItOpen, setFixItOpen] = useState(false);
  const [fixItBusy, setFixItBusy] = useState(false);
  const [fixItDone, setFixItDone] = useState(false);
  const receiptId = turn.receiptId;
  if (!receiptId) return null;
  const sql = (turn.sql || "").trim();

  const rate = (v: Verdict) => {
    setVerdict(v);
    setAccepted(false);
    // A 👍 is the chat's accept: the server records it with the SQL this turn ran, and
    // the thanks line says so only when it did.
    void sendChatFeedback(connectionId, receiptId, v).then((r) => setAccepted(v === "helpful" && r.accepted));
    // The lightweight receipt signal has landed; the STRUCTURED correction is opt-in.
    if (v === "unhelpful") setFixItOpen(true);
  };

  const submitFixIt = async (note: string, correctedSql: string) => {
    setFixItBusy(true);
    try {
      await recordVerdict({
        verdict: correctedSql ? "correct" : "reject",
        connectionId,
        // The receipt id IS the run id the `done` frame carried (chatTurn's projector).
        investigationId: receiptId,
        headline: turn.headline ?? "",
        note,
        sqlSource: sql,
        correctedSql,
      });
      setFixItDone(true);
      setFixItOpen(false);
    } catch { /* the receipt signal already landed; the form stays open to retry */ }
    finally { setFixItBusy(false); }
  };

  const said = fixItDone
    ? "Correction recorded — future answers cite it"
    : verdict === "helpful"
      ? (accepted ? "Thanks — recorded as accepted 👍" : "Thanks — noted 👍")
      : "Noted 👎";

  return (
    <div className="flex flex-col gap-1.5">
      {verdict ? (
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>{said}</span>
      ) : (
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" size="icon-xs" aria-label="Helpful"
                  title="Helpful — records this answer as accepted"
                  onClick={() => rate("helpful")}>
            👍
          </Button>
          <Button variant="ghost" size="icon-xs" aria-label="Not helpful"
                  title="Not helpful — say what was wrong"
                  onClick={() => rate("unhelpful")}>
            👎
          </Button>
        </div>
      )}
      {fixItOpen && (
        <FixItForm withSql={!!sql} busy={fixItBusy}
                   onSubmit={submitFixIt} onCancel={() => setFixItOpen(false)} />
      )}
    </div>
  );
}
