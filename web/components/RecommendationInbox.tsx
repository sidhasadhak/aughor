"use client";

import { useEffect, useState, useCallback } from "react";
import {
  logOutcome,
  getInvestigationOutcomes,
  type RecOutcome,
  type RecStatus,
} from "@/lib/api";
import type { InvestigationSummary } from "@/lib/types";

import { API_BASE as BASE } from "@/lib/config";

// Status display config
const STATUS_STYLE: Record<RecStatus, { label: string; chip: string }> = {
  accepted:    { label: "Accepted",    chip: "border-blue-500/30 bg-blue-500/10 text-blue-400"          },
  implemented: { label: "Implemented", chip: "border-violet-500/30 bg-violet-500/10 text-violet-400"    },
  verified:    { label: "Verified",    chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" },
  rejected:    { label: "Rejected",    chip: "border-red-500/30 bg-red-500/10 text-red-400"             },
  dismissed:   { label: "Dismissed",   chip: "border-zinc-600 bg-zinc-800/50 text-zinc-500"             },
};

const TERMINAL: RecStatus[] = ["verified", "rejected", "dismissed"];

// ── Execute → Action Hub button ───────────────────────────────────────────────

interface Trigger { id: string; name: string; enabled: boolean }

function ExecuteButton({ invId, index, text }: { invId: string; index: number; text: string }) {
  const [open,     setOpen]     = useState(false);
  const [triggers, setTriggers] = useState<Trigger[]>([]);
  const [firing,   setFiring]   = useState<string | null>(null);
  const [done,     setDone]     = useState<string | null>(null); // trigger name on success

  useEffect(() => {
    if (open && triggers.length === 0) {
      fetch(`${BASE}/actions/triggers`).then(r => r.json())
        .then(d => setTriggers((d.triggers ?? []).filter((t: Trigger) => t.enabled)))
        .catch(() => {});
    }
  }, [open]);

  const fire = async (triggerId: string, triggerName: string) => {
    setFiring(triggerId);
    setOpen(false);
    try {
      await fetch(`${BASE}/investigations/${invId}/recommendations/${index}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trigger_id: triggerId }),
      });
      setDone(triggerName);
    } catch { /* silent */ }
    setFiring(null);
  };

  if (done) return (
    <span className="text-[11px] text-emerald-400 font-medium px-1.5">✓ {done}</span>
  );

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        disabled={!!firing}
        className="text-[11px] text-violet-400 hover:text-violet-300 border border-violet-500/30 hover:border-violet-400/50 rounded px-2 py-1 transition whitespace-nowrap"
      >
        {firing ? "…" : "Execute →"}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-20 min-w-[160px] rounded-lg border border-zinc-600 bg-zinc-900 shadow-xl overflow-hidden">
            {triggers.length === 0
              ? <p className="text-[11px] text-zinc-500 px-3 py-2">No triggers configured.<br/>Set up one in Action Hub.</p>
              : triggers.map(t => (
                  <button
                    key={t.id}
                    onClick={() => fire(t.id, t.name)}
                    className="w-full text-left px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800 transition"
                  >
                    {t.name}
                  </button>
                ))
            }
          </div>
        </>
      )}
    </div>
  );
}

interface InvWithOutcomes {
  inv: InvestigationSummary;
  actions: string[];
  outcomes: RecOutcome[];
}

interface Props {
  onOpenInvestigation?: (invId: string) => void;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function ActionRow({
  invId,
  index,
  text,
  existing,
  onOutcome,
}: {
  invId: string;
  index: number;
  text: string;
  existing: RecOutcome | undefined;
  onOutcome: (o: RecOutcome) => void;
}) {
  const [outcome, setOutcome] = useState<RecOutcome | undefined>(existing);
  const [saving, setSaving] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const mark = useCallback(async (status: RecStatus) => {
    setSaving(true);
    setMenuOpen(false);
    try {
      const result = await logOutcome(invId, index, text, status);
      setOutcome(result);
      onOutcome(result);
    } catch {
      /* silent */
    } finally {
      setSaving(false);
    }
  }, [invId, index, text, onOutcome]);

  const current = outcome ? STATUS_STYLE[outcome.status] : null;
  const isPending = !outcome || !TERMINAL.includes(outcome.status);

  return (
    <div className={`flex items-start gap-3 py-2.5 border-b border-zinc-700/40 last:border-0 ${!isPending ? "opacity-60" : ""}`}>
      <span className="shrink-0 flex h-5 w-5 items-center justify-center rounded-full bg-zinc-800 border border-zinc-600 text-[11px] font-mono text-zinc-400 mt-0.5">
        {index + 1}
      </span>
      <p className="text-sm text-zinc-300 leading-snug flex-1">{text}</p>
      <ExecuteButton invId={invId} index={index} text={text} />
      <div className="shrink-0 relative">
        {current ? (
          <div className="flex items-center gap-1.5">
            <span className={`text-[11px] font-medium px-1.5 py-0.5 rounded border ${current.chip}`}>
              {current.label}
            </span>
            {isPending && (
              <button
                onClick={() => setMenuOpen(o => !o)}
                className="text-[11px] text-zinc-500 hover:text-zinc-400 transition px-1"
              >
                ▾
              </button>
            )}
          </div>
        ) : (
          <button
            onClick={() => setMenuOpen(o => !o)}
            disabled={saving}
            className="text-[11px] text-zinc-500 hover:text-zinc-300 border border-zinc-600 hover:border-zinc-500 rounded px-2 py-1 transition whitespace-nowrap"
          >
            {saving ? "…" : "Mark"}
          </button>
        )}
        {menuOpen && (
          <div className="absolute right-0 top-full mt-1 z-20 w-36 rounded-lg border border-zinc-600 bg-zinc-900 shadow-xl overflow-hidden">
            {(["accepted", "implemented", "verified", "rejected", "dismissed"] as RecStatus[]).map(s => (
              <button
                key={s}
                onClick={() => mark(s)}
                className="w-full text-left px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800 transition capitalize"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function InvCard({
  data,
  onOpenInvestigation,
}: {
  data: InvWithOutcomes;
  onOpenInvestigation?: (id: string) => void;
}) {
  const { inv, actions, outcomes: initialOutcomes } = data;
  const [outcomes, setOutcomes] = useState<RecOutcome[]>(initialOutcomes);

  const pending = actions.filter((_, i) => {
    const o = outcomes.find(o => o.rec_index === i);
    return !o || !TERMINAL.includes(o.status);
  }).length;

  const handleOutcome = useCallback((updated: RecOutcome) => {
    setOutcomes(prev => {
      const idx = prev.findIndex(o => o.rec_index === updated.rec_index);
      return idx >= 0
        ? prev.map((o, i) => (i === idx ? updated : o))
        : [...prev, updated];
    });
  }, []);

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-800/50 overflow-hidden">
      {/* Card header */}
      <div className="px-4 py-3 border-b border-zinc-700/60 flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-zinc-200 leading-snug line-clamp-2">{inv.question}</p>
          <p className="text-[11px] text-zinc-500 font-mono mt-1">{timeAgo(inv.completed_at ?? inv.started_at)}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {pending > 0 && (
            <span className="text-[11px] font-mono px-1.5 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/30 text-amber-400">
              {pending} pending
            </span>
          )}
          {onOpenInvestigation && (
            <button
              onClick={() => onOpenInvestigation(inv.id)}
              className="text-[11px] text-zinc-500 hover:text-zinc-300 border border-zinc-700 hover:border-zinc-500 rounded px-2 py-1 transition"
            >
              View →
            </button>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="px-4 py-1">
        {actions.map((action, i) => (
          <ActionRow
            key={i}
            invId={inv.id}
            index={i}
            text={action}
            existing={outcomes.find(o => o.rec_index === i)}
            onOutcome={handleOutcome}
          />
        ))}
      </div>
    </div>
  );
}

export function RecommendationInbox({ onOpenInvestigation }: Props) {
  const [items, setItems] = useState<InvWithOutcomes[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"pending" | "all">("pending");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const invRes = await fetch(`${BASE}/investigations?limit=20`);
        const invs: InvestigationSummary[] = await invRes.json();
        const complete = invs.filter(i => i.status === "complete" && i.kind === "investigation");

        const results: InvWithOutcomes[] = [];
        await Promise.all(
          complete.map(async inv => {
            try {
              const [detailRes, outcomesData] = await Promise.all([
                fetch(`${BASE}/investigations/${encodeURIComponent(inv.id)}`),
                getInvestigationOutcomes(inv.id),
              ]);
              const detail = await detailRes.json();
              const actions: string[] = detail?.report?.recommended_actions ?? [];
              if (actions.length > 0) {
                results.push({ inv, actions, outcomes: outcomesData });
              }
            } catch {
              /* skip */
            }
          }),
        );

        if (!cancelled) {
          results.sort((a, b) => {
            const aPending = a.actions.filter((_, i) => {
              const o = a.outcomes.find(o => o.rec_index === i);
              return !o || !TERMINAL.includes(o.status);
            }).length;
            const bPending = b.actions.filter((_, i) => {
              const o = b.outcomes.find(o => o.rec_index === i);
              return !o || !TERMINAL.includes(o.status);
            }).length;
            if (bPending !== aPending) return bPending - aPending;
            return new Date(b.inv.completed_at ?? b.inv.started_at).getTime()
              - new Date(a.inv.completed_at ?? a.inv.started_at).getTime();
          });
          setItems(results);
        }
      } catch {
        /* silent */
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, []);

  const visible = filter === "pending"
    ? items.filter(d => d.actions.some((_, i) => {
        const o = d.outcomes.find(o => o.rec_index === i);
        return !o || !TERMINAL.includes(o.status);
      }))
    : items;

  const pendingCount = items.reduce((acc, d) => {
    return acc + d.actions.filter((_, i) => {
      const o = d.outcomes.find(o => o.rec_index === i);
      return !o || !TERMINAL.includes(o.status);
    }).length;
  }, 0);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-zinc-200">Recommendation Inbox</h2>
          <p className="text-xs text-zinc-500 mt-0.5">
            Track outcomes of ADA&apos;s recommendations across investigations
          </p>
        </div>
        <div className="flex items-center gap-2">
          {pendingCount > 0 && (
            <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/30 text-amber-400">
              {pendingCount} pending
            </span>
          )}
          <div className="flex rounded-lg border border-zinc-700 overflow-hidden text-[11px]">
            {(["pending", "all"] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-2.5 py-1 capitalize transition ${
                  filter === f
                    ? "bg-zinc-700 text-zinc-200"
                    : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="py-12 text-center text-xs text-zinc-500 font-mono animate-pulse">
          Loading recommendations…
        </div>
      ) : visible.length === 0 ? (
        <div className="py-12 text-center space-y-1">
          <p className="text-sm text-zinc-400">
            {filter === "pending" ? "No pending recommendations" : "No recommendations found"}
          </p>
          <p className="text-xs text-zinc-600">
            {filter === "pending"
              ? "All recommendations have been actioned — great work."
              : "Complete an investigation to see recommendations here."}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {visible.map(d => (
            <InvCard
              key={d.inv.id}
              data={d}
              onOpenInvestigation={onOpenInvestigation}
            />
          ))}
        </div>
      )}
    </div>
  );
}
