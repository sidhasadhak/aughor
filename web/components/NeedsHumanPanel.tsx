"use client";

/**
 * CR4 — needs a human: ONE derived list over the four real sources (pending
 * kinetic proposals · paused deep runs · automation effects at
 * approval_required · unacknowledged agent alerts). It is a VIEW — resolving
 * through a native surface removes the row here because there is one store per
 * source and no copies.
 *
 * Inbox rows and agent alerts resolve inline (accept/reject and acknowledge are
 * each one POST with no follow-up stream); paused runs and automation approvals
 * deep-link to their native surfaces, where resume/inspection already work.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { AgentAlertRulesPanel } from "@/components/agentops/AgentAlertRulesPanel";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import {
  acceptProposal, acknowledgeAgentAlert, getNeedsHuman, rejectProposal,
  type NeedsHuman, type NeedsHumanRow,
} from "@/lib/api";
import { relTime } from "@/lib/format";

/** A duration a person reads at a glance — "2h 14m", not 8040000. */
function humanAge(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ${String(m % 60).padStart(2, "0")}m` : `${Math.floor(h / 24)}d ${h % 24}h`;
}

type ChipSpec = { hue: ChipHue; label: string };

const SOURCE_CHIP: Record<NeedsHumanRow["source"], ChipSpec> = {
  kinetic_inbox: { hue: "caution", label: "proposal" },
  paused_run: { hue: "info", label: "paused run" },
  automation_approval: { hue: "accent", label: "approval" },
  agent_alert: { hue: "negative", label: "alert" },
  automation_broken: { hue: "negative", label: "broken" },
};

/** An alert's own severity outranks the source chip: three rows can wait the same
 *  number of minutes and not be equally urgent. */
function chipFor(row: NeedsHumanRow): ChipSpec {
  const base = SOURCE_CHIP[row.source];
  if (row.source !== "agent_alert" || !row.severity) return base;
  const hue: ChipHue = row.severity === "critical" ? "negative"
    : row.severity === "info" ? "info" : "caution";
  return { hue, label: row.severity };
}

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

  const resolveAlert = async (row: NeedsHumanRow) => {
    setBusy(row.id);
    try {
      await acknowledgeAgentAlert(row.id);
      load();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

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
    return <div className="aug-fs-sm" style={{ padding: 24, color: "var(--red4)" }}>{error}</div>;
  }
  if (!data) {
    return <div className="aug-fs-sm" style={{ padding: 24, color: "var(--t2)" }}>Loading…</div>;
  }

  // Rows arrive sorted by waiting_ms desc, so the head is the oldest — but read it from
  // the max rather than position 0, so a change of sort order upstream cannot silently
  // turn this into "the age of whichever row happens to be first".
  const oldest = data.rows.length
    ? Math.max(...data.rows.map(r => r.waiting_ms ?? 0)) : null;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
      {/* The rules come first: what is waiting on a person is downstream of what somebody
          decided was worth being told about, and an empty Attention page with no rules
          reads as "all clear" when it means "nothing is watching". */}
      <AgentAlertRulesPanel />
      <MiniStatRow>
        <MiniStat value={data.count} label="Waiting on a human"
          tone={data.count > 0 ? "var(--amb4)" : "var(--t1)"} />
        <MiniStat value={data.sources.kinetic_inbox} label="Inbox proposals" />
        <MiniStat value={data.sources.paused_runs} label="Paused deep runs" />
        <MiniStat value={data.sources.automation_approvals} label="Automation approvals" />
        {/* `?? 0` because this source is newer than the panel: an API that predates
            VA-6 omits the key, and rendering `undefined` where a count belongs is a
            worse answer than zero. */}
        <MiniStat value={data.sources.agent_alerts ?? 0} label="Agent alerts" />
        <MiniStat value={data.sources.broken_automations ?? 0} label="Broken automations"
          tone={(data.sources.broken_automations ?? 0) > 0 ? "var(--red4)" : undefined} />
        {/* The leading indicator. A count says how many are waiting; the OLDEST says
            whether anything has been abandoned — three items waiting a minute and three
            waiting since Tuesday are the same count and a different situation. */}
        <MiniStat label="Oldest waiting"
          value={oldest == null ? "—" : humanAge(oldest)}
          tone={oldest != null && oldest > 3_600_000 ? "var(--red4)" : undefined} />
      </MiniStatRow>

      {data.rows.length === 0 ? (
        <div style={{ padding: 32, textAlign: "center", color: "var(--t3)", fontSize: 12,
          background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)" }}>
          Nothing needs a human. Every source is empty right now.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {data.rows.map(row => {
            const chip = chipFor(row);
            return (
              <div key={`${row.source}:${row.id}`}
                style={{ display: "flex", alignItems: "center", gap: 12,
                  background: "var(--bg-2)", border: "1px solid var(--b1)",
                  borderRadius: "var(--r3)", padding: "10px 14px" }}>
                <StatusChip hue={chip.hue} strength="soft">{chip.label}</StatusChip>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap" }}>{row.title}</div>
                  <div style={{ fontSize: 12, color: "var(--t2)", marginTop: 2 }}>
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
                {/* DS-8 — an automation's approval is resolved the same way an agent's is,
                    because it IS the same proposal in the same resolve-once inbox. Before
                    the pause was durable this row could only offer "Open automation", which
                    led to a panel with nothing on it that could approve anything: the row
                    named a decision and then had no door for it. Accepting here resumes the
                    parked chain from its checkpoint. */}
                {row.source === "automation_approval" && row.resolve?.proposal_id && (
                  <>
                    <Button variant="secondary" size="xs" disabled={busy === row.id}
                      onClick={() => resolveInbox(row, "accept")}>Accept</Button>
                    <Button variant="ghost" size="xs" disabled={busy === row.id}
                      onClick={() => resolveInbox(row, "reject")}>Reject</Button>
                  </>
                )}
                {row.source === "automation_approval" && onOpenAutomations && (
                  <Button variant="ghost" size="xs"
                    onClick={onOpenAutomations}>Open automation</Button>
                )}
                {row.source === "agent_alert" && (
                  <Button variant="secondary" size="xs" disabled={busy === row.id}
                    onClick={() => resolveAlert(row)}>Acknowledge</Button>
                )}
                {/* No Acknowledge here on purpose. A broken automation is not something a
                    person can dismiss — it fails identically on the next tick until its
                    configuration changes, so the only honest action is to go and fix it. */}
                {row.source === "automation_broken" && onOpenAutomations && (
                  <Button variant="secondary" size="xs"
                    onClick={onOpenAutomations}>Fix automation</Button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
