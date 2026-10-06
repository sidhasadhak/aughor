"use client";
/**
 * Execute a deep analysis's recommendation through a configured trigger (Slack, webhook, Jira),
 * past the departure gate — `POST /investigations/{id}/recommendations/{i}/execute`.
 *
 * One control for every place an action is taken: the inbox, and the Briefing beside the item
 * it belongs to (2026-10-06 — it used to say "execute in the inbox" and send the reader there).
 *
 * It says what happened, and only that. "✓ sent" is shown for a delivery the trigger reports as
 * `ok`; a send the gate held says it was held and why; a failed, timed-out or skipped delivery,
 * a refused request and an unreachable API each say so. The inbox's copy of this showed "✓" for
 * all of them.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { getApiBase } from "@/lib/config";

interface Trigger { id: string; name: string; enabled: boolean }

type Outcome =
  | { kind: "sent"; trigger: string }
  | { kind: "held"; why: string }
  | { kind: "failed"; why: string };

export function ExecuteRecommendation({ invId, index, label = "Execute →" }: {
  invId: string; index: number; label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [triggers, setTriggers] = useState<Trigger[] | null>(null);
  const [readFailed, setReadFailed] = useState<string | null>(null);
  const [firing, setFiring] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    if (!open || triggers !== null || readFailed) return;
    fetch(`${getApiBase()}/actions/triggers`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(`refused (${r.status})`))))
      .then(d => setTriggers((d.triggers ?? []).filter((t: Trigger) => t.enabled)))
      // Not "no triggers": a read that failed is said, or it teaches that none exist.
      .catch(e => setReadFailed(String((e as Error)?.message || e)));
  }, [open, triggers, readFailed]);

  const fire = async (t: Trigger) => {
    setFiring(true);
    setOpen(false);
    try {
      const res = await fetch(`${getApiBase()}/investigations/${encodeURIComponent(invId)}/recommendations/${index}/execute`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trigger_id: t.id }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) setOutcome({ kind: "failed", why: String(body?.detail || `the request was refused (${res.status})`) });
      else if (body?.status === "held") setOutcome({ kind: "held", why: String(body.error || "held at departure") });
      else if (body?.status === "ok") setOutcome({ kind: "sent", trigger: t.name });
      else setOutcome({ kind: "failed", why: `${t.name}: ${body?.status || "no result"}${body?.error ? ` — ${body.error}` : ""}` });
    } catch (e) {
      setOutcome({ kind: "failed", why: `the API could not be reached (${(e as Error)?.message || e})` });
    }
    setFiring(false);
  };

  if (outcome?.kind === "sent") return (
    <span className="aug-fs-xs text-emerald-400 font-medium px-1.5">✓ sent to {outcome.trigger}</span>
  );
  if (outcome?.kind === "held") return (
    <span className="aug-fs-xs px-1.5" style={{ color: "var(--amb3)" }} title={outcome.why}>Not sent — held at departure</span>
  );
  if (outcome?.kind === "failed") return (
    <span className="aug-fs-xs px-1.5 text-red-400" title={outcome.why}>
      Not sent — {outcome.why}
      <Button variant="ghost" size="xs" className="ml-1 underline" onClick={() => setOutcome(null)}>try again</Button>
    </span>
  );

  return (
    <span className="relative inline-block">
      <Button variant="secondary" size="xs" onClick={() => setOpen(o => !o)} disabled={firing}
        className="whitespace-nowrap">
        {firing ? "Sending…" : label}
      </Button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div role="menu" className="absolute right-0 top-full mt-1 z-20 min-w-[160px] rounded-[var(--r3)] border border-zinc-600 bg-zinc-900 shadow-[var(--shadow-sm)] overflow-hidden">
            {readFailed
              ? <p className="aug-fs-xs text-red-400 px-3 py-2">Could not read the triggers — {readFailed}</p>
              : triggers === null
              ? <p className="aug-fs-xs text-zinc-500 px-3 py-2">Reading the triggers…</p>
              : triggers.length === 0
              ? <p className="aug-fs-xs text-zinc-500 px-3 py-2">No triggers configured.<br/>Set up one in Notifications.</p>
              : triggers.map(t => (
                  <Button key={t.id} role="menuitem" variant="ghost" size="xs" onClick={() => fire(t)}
                    className="w-full justify-start rounded-none px-3 py-1.5 text-zinc-300">
                    {t.name}
                  </Button>
                ))}
          </div>
        </>
      )}
    </span>
  );
}
