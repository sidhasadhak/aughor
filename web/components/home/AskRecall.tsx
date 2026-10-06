"use client";

/**
 * Ask, with memory — what is already on record for the question being typed, shown BEFORE a run
 * is paid for. The engine has found earlier answers to the same question since CI-1b, and gave them
 * only to the model; on 2026-10-05 one question had run 13 times in two days with nothing telling
 * the person it was answered. Matching is exact (`GET /ask/prior`, normalised equality), so it never
 * offers another question's answer as this one's.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { askedBefore, type AskedBefore } from "@/lib/home";

const shortDate = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
};

export function AskRecall({ connectionId, question, onOpen, onRunAgain }: {
  connectionId: string;
  question: string;
  onOpen: (id: string, kind?: string) => void;
  onRunAgain: () => void;
}) {
  const [found, setFound] = useState<AskedBefore | null>(null);
  const q = question.trim();
  useEffect(() => {
    setFound(null);
    if (!connectionId || q.length < 12) return;
    let alive = true;
    const timer = setTimeout(() => {
      askedBefore(connectionId, q).then(r => { if (alive) setFound(r); }).catch(() => undefined);
    }, 350);
    return () => { alive = false; clearTimeout(timer); };
  }, [connectionId, q]);

  if (!found || found.count === 0 || !found.latest) return null;
  const times = found.count === 1 ? "once" : `${found.count} times`;
  const since = found.count > 1 ? ` since ${shortDate(found.first_at)}` : "";
  return (
    <div data-testid="ask-recall" style={{ background: "var(--bg-3)", borderRadius: "var(--r2)", padding: "10px 12px" }}>
      <div style={{ fontSize: 13, color: "var(--t1)" }}>
        {`Already on record: answered ${times}${since}, last on ${shortDate(found.last_at)}`}
      </div>
      {found.latest.headline && (
        <div style={{ fontSize: 12, color: "var(--t2)", marginTop: 2, lineHeight: 1.5 }}>{found.latest.headline}</div>
      )}
      <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
        <Button size="sm" variant="outline" onClick={() => onOpen(found.latest!.id, found.latest!.kind)}>Open that answer</Button>
        <Button size="sm" variant="outline" onClick={onRunAgain}>Run it again and compare</Button>
      </div>
    </div>
  );
}
