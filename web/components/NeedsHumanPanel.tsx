"use client";

/**
 * CR4 — needs a human: ONE derived list over the three real sources (pending
 * kinetic proposals · paused deep runs · automation effects at
 * approval_required). It is a VIEW — resolving through a native surface
 * removes the row here because there is one store per source and no copies.
 *
 * Inbox rows resolve inline (their accept/reject endpoints are one POST with
 * no follow-up stream); paused runs and automation approvals deep-link to
 * their native surfaces, where resume/inspection already work.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { StatusChip } from "@/components/brief/StatusChip";
import {
  acceptProposal, getNeedsHuman, rejectProposal,
  type NeedsHuman, type NeedsHumanRow,
} from "@/lib/api";
import { relTime } from "@/lib/format";

const SOURCE_CHIP: Record<NeedsHumanRow["source"], { hue: "caution" | "info" | "accent"; label: string }> = {
  kinetic_inbox: { hue: "caution", label: "proposal" },
  paused_run: { hue: "info", label: "paused run" },
  automation_approval: { hue: "accent", label: "approval" },
};

export function NeedsHumanPanel({ onOpenInvestigation, onOpenAutomations }: {
  onOpenInvestigation?: (invId: string) => void;
  onOpenAutomations?: () => void;
}) {
  const [data, setData] = useState<NeedsHuman | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getNeedsHuman().then(d => { setData(d); setError(null); })
      .catch(e => setError(String(e?.message || e)));
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 10_000);
    return () => clearInterval(iv);
  }, [load]);

  const resolveInbox = async (row: NeedsHumanRow, action: "accept" | "reject") => {
    setBusy(row.id);
    try {
      if (action === "accept") await acceptProposal(row.id, "control-room");
      else await rejectProposal(row.id, "control-room");
      load();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  if (error && !data) {
    return <div style={{ padding: 24, color: "var(--red4)", fontSize: 12 }}>{error}</div>;
  }
  if (!data) {
    return <div style={{ padding: 24, color: "var(--t3)", fontSize: 12 }}>Loading…</div>;
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
      <MiniStatRow>
        <MiniStat value={data.count} label="Waiting on a human"
          tone={data.count > 0 ? "var(--amb4)" : "var(--t1)"} />
        <MiniStat value={data.sources.kinetic_inbox} label="Inbox proposals" />
        <MiniStat value={data.sources.paused_runs} label="Paused deep runs" />
        <MiniStat value={data.sources.automation_approvals} label="Automation approvals" />
      </MiniStatRow>

      {data.rows.length === 0 ? (
        <div style={{ padding: 32, textAlign: "center", color: "var(--t3)", fontSize: 12,
          background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)" }}>
          Nothing needs a human. All three sources are empty right now.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {data.rows.map(row => {
            const chip = SOURCE_CHIP[row.source];
            return (
              <div key={`${row.source}:${row.id}`}
                style={{ display: "flex", alignItems: "center", gap: 12,
                  background: "var(--bg-2)", border: "1px solid var(--b1)",
                  borderRadius: "var(--r3)", padding: "10px 14px" }}>
                <StatusChip hue={chip.hue} strength="soft">{chip.label}</StatusChip>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap" }}>{row.title}</div>
                  <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2 }}>
                    waiting {relTime(row.since)}
                    {row.since_basis === "started_at" && " (since start — pause event aged out)"}
                    {row.connection_id ? ` · ${row.connection_id}` : ""}
                  </div>
                </div>
                {row.source === "kinetic_inbox" && (
                  <>
                    <Button variant="secondary" size="xs" disabled={busy === row.id}
                      onClick={() => resolveInbox(row, "accept")}>Accept</Button>
                    <Button variant="ghost" size="xs" disabled={busy === row.id}
                      onClick={() => resolveInbox(row, "reject")}>Reject</Button>
                  </>
                )}
                {row.source === "paused_run" && onOpenInvestigation && (
                  <Button variant="secondary" size="xs"
                    onClick={() => onOpenInvestigation(row.id)}>Open & resume</Button>
                )}
                {row.source === "automation_approval" && onOpenAutomations && (
                  <Button variant="secondary" size="xs"
                    onClick={onOpenAutomations}>Open automation</Button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
