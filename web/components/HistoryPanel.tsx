"use client";

import { useEffect, useState } from "react";
import type { InvestigationSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  selectedId: string | null;
  onSelect: (id: string) => void;
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

export function HistoryPanel({ selectedId, onSelect }: Props) {
  const [items, setItems] = useState<InvestigationSummary[]>([]);
  const [indexedIds, setIndexedIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch("http://localhost:8000/investigations").then(r => r.json()),
      fetch("http://localhost:8000/investigations/indexed-ids").then(r => r.json()).catch(() => ({ ids: [] })),
    ])
      .then(([invs, indexed]) => {
        setItems(invs);
        setIndexedIds(new Set(indexed.ids ?? []));
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-zinc-600">
        Loading history…
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center px-6">
        <p className="text-sm text-zinc-600">No investigations yet.</p>
        <p className="text-xs text-zinc-700">Run your first investigation to see it here.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-zinc-800 shrink-0">
        <p className="text-xs text-zinc-500 uppercase tracking-wide">Investigation history</p>
      </div>
      <ul className="flex-1 overflow-y-auto divide-y divide-zinc-800/60">
        {items.map(inv => {
          const isSelected = inv.id === selectedId;
          const isIndexed = indexedIds.has(inv.id);
          return (
            <li key={inv.id}>
              <button
                onClick={() => onSelect(inv.id)}
                className={cn(
                  "w-full text-left px-4 py-3 transition group border-l-2",
                  isSelected
                    ? "bg-violet-500/5 border-violet-500"
                    : "border-transparent hover:bg-zinc-900/50 hover:border-zinc-700"
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className={cn(
                    "text-sm leading-snug line-clamp-2 flex-1",
                    isSelected ? "text-white" : "text-zinc-200 group-hover:text-white"
                  )}>
                    {inv.question}
                  </p>
                  <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
                    <span
                      title={isIndexed ? "Indexed in Qdrant — eligible for cache" : "Not yet indexed"}
                      className={cn("text-[10px]", isIndexed ? "text-emerald-400" : "text-zinc-700")}
                    >
                      ◉
                    </span>
                    <span className="text-xs text-zinc-600">{timeAgo(inv.started_at)}</span>
                  </div>
                </div>
                {inv.headline && (
                  <p className="mt-1 text-xs text-zinc-500 line-clamp-1">{inv.headline}</p>
                )}
                <div className="mt-1.5 flex items-center gap-3 text-xs text-zinc-700">
                  <span>{inv.hypothesis_count} hypotheses</span>
                  <span>·</span>
                  <span>{inv.query_count} queries</span>
                  <span>·</span>
                  <span className="font-mono">{inv.connection_id}</span>
                  {inv.status === "timed_out" && (
                    <>
                      <span>·</span>
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded border border-amber-500/20 bg-amber-500/10 text-amber-400 text-[10px] font-medium" title="Investigation exceeded the time limit">⏱ timed out</span>
                    </>
                  )}
                  {inv.status === "failed" && (
                    <>
                      <span>·</span>
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded border border-red-500/20 bg-red-500/10 text-red-400 text-[10px] font-medium">✕ failed</span>
                    </>
                  )}
                  {inv.status === "running" && (
                    <>
                      <span>·</span>
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded border border-emerald-500/20 bg-emerald-500/10 text-emerald-400 text-[10px] font-medium">● running</span>
                    </>
                  )}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
