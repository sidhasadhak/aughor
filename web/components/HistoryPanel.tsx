"use client";

import { useCallback, useEffect, useState } from "react";
import DeleteIcon from "@atlaskit/icon/core/delete";
import type { InvestigationSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { localizeCurrency } from "@/lib/orgSettings";
import { API_BASE } from "@/lib/config";
import { subscribeKernelEvents } from "@/lib/events";

interface Props {
  selectedId: string | null;
  onSelect: (id: string, kind: "investigation" | "chat") => void;
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
  const [search, setSearch] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  const load = useCallback(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8_000);
    Promise.all([
      fetch(`${API_BASE}/investigations`, { signal: controller.signal }).then(r => r.json()),
      fetch(`${API_BASE}/investigations/indexed-ids`, { signal: controller.signal }).then(r => r.json()).catch(() => ({ ids: [] })),
    ])
      .then(([invs, indexed]) => {
        setItems(invs);
        setIndexedIds(new Set(indexed.ids ?? []));
      })
      .catch(() => {})
      .finally(() => clearTimeout(timeout));
  }, []);

  useEffect(() => {
    load();
    // K2 (T3): investigation lifecycle now lands on the kernel event spine, so the
    // history list refreshes live — a run finishing in another tab, a resumed run,
    // or a boot-reconciled orphan all show up without a manual reload.
    const unsub = subscribeKernelEvents(() => load(), { kinds: ["investigation."] });
    return () => unsub();
  }, [load]);

  async function handleDelete(e: React.MouseEvent, invId: string) {
    e.stopPropagation();
    setDeletingId(invId);
    try {
      const res = await fetch(`${API_BASE}/investigations/${invId}`, { method: "DELETE" });
      if (res.ok || res.status === 204) {
        setItems(prev => prev.filter(i => i.id !== invId));
      }
    } finally {
      setDeletingId(null);
    }
  }

  async function handleClearAll() {
    if (clearing || items.length === 0) return;
    if (!window.confirm(`Delete all ${items.length} investigations and chats? This also removes their evidence and search index, and can't be undone.`)) {
      return;
    }
    setClearing(true);
    try {
      const res = await fetch(`${API_BASE}/investigations`, { method: "DELETE" });
      if (res.ok) setItems([]);
    } finally {
      setClearing(false);
    }
  }

  if (items.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center px-6">
        <p className="text-sm text-zinc-500">No investigations yet.</p>
        <p className="aug-fs-xs text-zinc-500">Run your first to see it here.</p>
      </div>
    );
  }

  const q = search.toLowerCase().trim();
  const filtered = q
    ? items.filter(inv =>
        inv.question.toLowerCase().includes(q) ||
        inv.headline?.toLowerCase().includes(q)
      )
    : items;

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2.5 border-b border-zinc-600 shrink-0 space-y-2">
        <div className="flex items-center justify-between">
          <p className="aug-label">History</p>
          <div className="flex items-center gap-2">
            {items.length > 0 && (
              <button
                onClick={handleClearAll}
                disabled={clearing}
                title="Delete all investigations and chats"
                className="aug-fs-xs text-zinc-500 hover:text-red-400 transition disabled:opacity-50"
              >
                {clearing ? "Clearing…" : "Clear all"}
              </button>
            )}
            <span className="aug-fs-xs text-[--t3]">{items.length}</span>
          </div>
        </div>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search…"
          className="aug-input py-1.5"
        />
      </div>
      <ul className="flex-1 overflow-y-auto divide-y divide-zinc-600/40">
        {filtered.length === 0 && (
          <li className="px-4 py-6 text-center aug-fs-xs text-zinc-500">No matches</li>
        )}
        {filtered.map(inv => {
          const isSelected = inv.id === selectedId;
          const isIndexed = indexedIds.has(inv.id);
          const isChat = inv.kind === "chat";
          const isDeleting = deletingId === inv.id;
          return (
            <li key={inv.id} className="relative group/item">
              <button
                onClick={() => onSelect(inv.id, inv.kind ?? "investigation")}
                className={cn(
                  "w-full text-left px-4 py-3 transition group border-l-2 pr-10",
                  isSelected
                    ? "bg-violet-500/5 border-violet-500"
                    : "border-transparent hover:bg-zinc-700/50 hover:border-zinc-600"
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-1.5 flex-1 min-w-0">
                    {/* Kind badge */}
                    <span className={cn(
                      "inline-flex shrink-0 items-center px-1 py-0.5 rounded aug-fs-xs font-semibold uppercase tracking-wider",
                      isChat
                        ? "bg-sky-500/10 text-sky-400 border border-sky-500/20"
                        : "bg-violet-500/10 text-violet-400 border border-violet-500/20"
                    )}>
                      {isChat ? "Ask" : "Inv"}
                    </span>
                    <p className={cn(
                      "text-sm leading-snug line-clamp-2 flex-1",
                      isSelected ? "text-white" : "text-zinc-200 group-hover:text-white"
                    )}>
                      {localizeCurrency(inv.question)}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
                    {!isChat && (
                      <span
                        title={isIndexed ? "Indexed in Qdrant — eligible for cache" : "Not yet indexed"}
                        className={cn("aug-fs-xs", isIndexed ? "text-emerald-400" : "text-zinc-500")}
                      >
                        ◉
                      </span>
                    )}
                    <span className="aug-fs-xs text-zinc-500">{timeAgo(inv.started_at)}</span>
                  </div>
                </div>
                {inv.headline && (
                  <p className="mt-1 aug-fs-xs text-zinc-500 line-clamp-1">{localizeCurrency(inv.headline).replace(/\*+/g, "")}</p>
                )}
                <div className="mt-1.5 flex items-center gap-3 aug-fs-xs text-zinc-500 flex-wrap">
                  {!isChat && <span>{inv.hypothesis_count} hypotheses</span>}
                  {!isChat && <span>·</span>}
                  <span>{inv.query_count} {isChat ? "query" : "queries"}</span>
                  <span>·</span>
                  <span className="font-mono">{inv.connection_id}</span>
                  {inv.status === "timed_out" && (
                    <>
                      <span>·</span>
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded border border-amber-500/20 bg-amber-500/10 text-amber-400 aug-fs-xs font-medium" title="Investigation exceeded the time limit">⏱ timed out</span>
                    </>
                  )}
                  {inv.status === "failed" && (
                    <>
                      <span>·</span>
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded border border-red-500/20 bg-red-500/10 text-red-400 aug-fs-xs font-medium">✕ failed</span>
                    </>
                  )}
                  {inv.status === "running" && (
                    <>
                      <span>·</span>
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded border border-emerald-500/20 bg-emerald-500/10 text-emerald-400 aug-fs-xs font-medium">● running</span>
                    </>
                  )}
                </div>
              </button>

              {/* Delete button — appears on row hover */}
              <button
                onClick={(e) => handleDelete(e, inv.id)}
                disabled={isDeleting}
                title="Delete"
                className={cn(
                  "absolute right-2 top-1/2 -translate-y-1/2 w-6 h-6 rounded flex items-center justify-center transition",
                  "opacity-0 group-hover/item:opacity-100",
                  "text-zinc-500 hover:text-red-400 hover:bg-red-400/10",
                  isDeleting && "opacity-50 pointer-events-none"
                )}
              >
                <DeleteIcon label="Delete" size="small" />
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
