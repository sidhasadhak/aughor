"use client";

/**
 * One agent's recent runs as a row of state cells — Airflow's grid, at one-agent scale.
 *
 * Twenty runs in one glance answers "is this agent healthy right now" in a way a count of
 * failures cannot: three reds in a row is a different fact from three reds spread over a
 * week, and the shape shows which. Newest is on the RIGHT, because the eye lands there and
 * "what is happening now" is the question being asked.
 *
 * The bar height encodes duration relative to the slowest run shown, so a run that hung is
 * visible as a tall bar rather than needing a tooltip to find. Colour is state, from the
 * ramps' text-grade steps (`grn4`/`red4`/`amb4`) — the same vocabulary as every status chip
 * on the surface, and the steps that clear AA on both grounds.
 */
import { Button } from "@/components/ui/button";
import { fmtMs } from "@/lib/cost";
import { relTime } from "@/lib/format";

export type TimelineRun = {
  id: string;
  state: string;
  at: string | null;
  durationMs: number | null;
  label: string;
  /** Attempts, when the runner recorded more than one. */
  attempt?: number | null;
};

const STATE_COLOR: Record<string, string> = {
  SUCCEEDED: "var(--grn4)", RUNNING: "var(--blue4)", PENDING: "var(--t4)",
  PAUSED: "var(--amb4)", FAILED: "var(--red4)", CANCELLED: "var(--amb4)",
  INTERRUPTED: "var(--amb4)",
  ok: "var(--grn4)", failed: "var(--red4)", running: "var(--blue4)",
};

export function RunTimeline({ runs, onOpen, emptyNote }: {
  runs: TimelineRun[];
  onOpen?: (id: string) => void;
  emptyNote?: string;
}) {
  if (runs.length === 0) {
    return (
      <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: 0 }}>
        {emptyNote ?? "No runs in this window."}
      </p>
    );
  }
  const slowest = Math.max(1, ...runs.map(r => r.durationMs ?? 0));
  // Oldest → newest, so the right-hand end is "now".
  const ordered = [...runs].reverse();

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 44 }}>
        {ordered.map(r => {
          const frac = Math.max(0.18, (r.durationMs ?? 0) / slowest);
          const color = STATE_COLOR[r.state] ?? "var(--t3)";
          const title = `${r.label}\n${r.state.toLowerCase()}`
            + (r.durationMs ? ` · ${fmtMs(r.durationMs)}` : "")
            + (r.at ? ` · ${relTime(r.at)}` : "")
            + ((r.attempt ?? 1) > 1 ? ` · attempt ${r.attempt}` : "");
          const cell = (
            <span aria-hidden style={{
              display: "block", width: 12, height: `${Math.round(frac * 100)}%`,
              minHeight: 6, borderRadius: 2, background: color,
              opacity: r.state === "PENDING" ? 0.5 : 0.9,
              outline: (r.attempt ?? 1) > 1 ? "1px solid var(--amb4)" : undefined,
            }} />
          );
          return onOpen ? (
            <Button key={r.id} variant="ghost" size="xs" title={title}
              onClick={() => onOpen(r.id)}
              style={{ padding: 0, height: "100%", width: 12, minWidth: 12,
                       display: "flex", alignItems: "flex-end" }}>
              {cell}
            </Button>
          ) : (
            <span key={r.id} title={title} style={{ height: "100%", display: "flex",
                                                    alignItems: "flex-end" }}>{cell}</span>
          );
        })}
      </div>
      <p className="aug-fs-xs" style={{ color: "var(--t2)", margin: "6px 0 0" }}>
        {runs.length} most recent · oldest left, newest right · height is duration against
        the slowest shown ({fmtMs(slowest)})
      </p>
    </div>
  );
}
