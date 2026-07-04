"use client";

import { useEffect, useState } from "react";
import { getExplorationStatus, type ExplorationStatus } from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { cn } from "@/lib/utils";

const PHASE_LABELS: Record<string, string> = {
  pending:            "Queued",
  null_meaning:       "Null meanings",
  join_verification:  "Joins",
  lifecycle_mapping:  "Lifecycles",
  distribution:       "Distributions",
  cross_table:        "Patterns",
  synthesis:          "Synthesis",
  complete:           "Explored",
  failed:             "Failed",
};

interface Props {
  connectionId: string;
  className?: string;
}

export function ExplorationBadge({ connectionId, className }: Props) {
  const [status, setStatus] = useState<ExplorationStatus | null>(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const s = await getExplorationStatus(connectionId);
        if (!cancelled) setStatus(s);
      } catch {
        // Explorer not running — silently suppress
      }
    };

    poll();
    // K2: kernel events drive refresh; the interval is only a slow fallback.
    const timer = setInterval(poll, 60_000);
    const unsub = subscribeKernelEvents(() => poll(), {
      kinds: ["exploration.", "job.state"], connId: connectionId,
    });
    return () => {
      cancelled = true;
      clearInterval(timer);
      unsub();
    };
  }, [connectionId]);

  if (!status || status.phase === "pending") return null;

  const isActive   = !["complete", "failed", "pending"].includes(status.phase);
  const isComplete = status.phase === "complete";
  const isFailed   = status.phase === "failed";

  return (
    <div className={cn("flex items-center gap-1.5 pl-4 mt-0.5", className)}>
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-[var(--r-pill)] shrink-0",
          isActive && !status.paused ? "bg-violet-400 animate-pulse" : "",
          isActive &&  status.paused ? "bg-yellow-500"               : "",
          isComplete                 ? "bg-emerald-500"              : "",
          isFailed                   ? "bg-red-500"                  : "",
        )}
      />
      <span
        className={cn(
          "aug-fs-xs",
          isComplete ? "text-emerald-400/70" : isFailed ? "text-red-400/70" : "text-zinc-500",
        )}
      >
        {status.paused ? "Paused · " : ""}
        {PHASE_LABELS[status.phase] ?? status.phase}
        {isComplete && status.insights_found > 0
          ? ` · ${status.insights_found} insight${status.insights_found === 1 ? "" : "s"}`
          : ""}
        {isActive && status.queries_executed > 0
          ? ` · ${status.queries_executed}q`
          : ""}
      </span>
    </div>
  );
}
