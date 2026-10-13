"use client";

/**
 * CR4 — needs a human: ONE derived list over the four real sources (pending
 * kinetic proposals · paused deep runs · automation effects at
 * approval_required · unacknowledged agent alerts). It is a VIEW — resolving
 * through a native surface removes the row here because there is one store per
 * source and no copies.
 *
 * Proposal-backed rows render the ONE approval card (SP-9) and resolve through it;
 * agent alerts acknowledge inline; paused runs and automation approvals also
 * deep-link to their native surfaces, where resume/inspection already work.
 */
import { connectionLabel, needsYouTitle } from "@/lib/names";
import { getConnections as listConnectionsForNames, type Connection as ConnectionForNames } from "@/lib/api";
import { useCallback, useEffect, useRef, useState } from "react";

import { useVisiblePoll } from "@/lib/useVisiblePoll";

import { Button } from "@/components/ui/button";
import { ProposalCardById } from "@/components/ProposalCard";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { AgentAlertRulesPanel } from "@/components/agentops/AgentAlertRulesPanel";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import {
  acknowledgeAgentAlert, getNeedsHuman,
  type NeedsHuman, type NeedsHumanRow,
} from "@/lib/api";
import { relTime } from "@/lib/format";
import { approverName } from "@/lib/auth";
import { Loading, ReadFailed } from "@/components/ui/states";

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

/** A source by the words its count says beside it, for naming one that could not be read. */
const SOURCE_WORDS: Record<keyof NeedsHuman["sources"], string> = {
  kinetic_inbox: "inbox proposals",
  paused_runs: "paused deep runs",
  automation_approvals: "automation approvals",
  agent_alerts: "agent alerts",
  broken_automations: "broken automations",
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
  /** AO-4 — carries the row's automation id (`resolve.automation_id`, else the row id),
   *  so the Automations layer opens that one rather than the list. */
  onOpenAutomations?: (automationId?: string) => void;
}) {
  // Connections by name for the row's scope line (lib/names.ts).
  const [conns, setConns] = useState<ConnectionForNames[]>([]);
  useEffect(() => { listConnectionsForNames().then(setConns).catch(() => {}); }, []);
  const [data, setData] = useState<NeedsHuman | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  // A read that failed, and an acknowledge the server refused — two different things to say.
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Reads overlap: the poll fires every 10 s and this route runs its sweeps before it answers.
  // Only an answer newer than the one on screen may replace it, so a slow read that started
  // before something arrived cannot put "nothing" back over what a later read found.
  const issued = useRef(0);
  const shown = useRef(0);
  const load = useCallback(() => {
    const n = ++issued.current;
    getNeedsHuman().then(d => {
      if (n < shown.current) return;
      shown.current = n;
      setData(d); setError(null);
    }).catch(e => {
      if (n < shown.current) return;
      shown.current = n;
      setError(String(e?.message || e));
    });
  }, []);

  useEffect(() => { load(); }, [load]);
  // Only while the Attention layer is on screen (useVisiblePoll's note); refreshed on return.
  useVisiblePoll(load, 10_000);

  const resolveAlert = async (row: NeedsHumanRow) => {
    setBusy(row.id);
    setActionError(null);
    try {
      await acknowledgeAgentAlert(row.id);
      load();
    } catch (e) {
      setActionError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  // A failed read is said whenever it happens, not only before the first answer. Kept behind an
  // earlier empty answer, it printed "Nothing needs a human … right now" over a read that never came back.
  if (error && (!data || data.rows.length === 0)) {
    return <ReadFailed what="what needs a person" error={error} onRetry={load} style={{ padding: 24 }} />;
  }
  if (!data) {
    return <Loading what="what needs a person" style={{ padding: 24 }} />;
  }

  // Rows arrive sorted by waiting_ms desc, so the head is the oldest — but read it from
  // the max rather than position 0, so a change of sort order upstream cannot silently
  // turn this into "the age of whichever row happens to be first".
  const oldest = data.rows.length
    ? Math.max(...data.rows.map(r => r.waiting_ms ?? 0)) : null;
  // A source whose read failed is not empty: its count is "—" and it is named, never folded into "nothing waits".
  const unread = data.unread ?? [];
  const n = (key: keyof NeedsHuman["sources"]) => (unread.includes(key) ? "—" : data.sources[key] ?? 0);

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
      {/* The rules come first: what is waiting on a person is downstream of what somebody
          decided was worth being told about, and an empty Attention page with no rules
          reads as "all clear" when it means "nothing is watching". */}
      <AgentAlertRulesPanel />
      {error && <ReadFailed what="what needs a person again — the list below is from the last read"
        error={error} onRetry={load} style={{ marginBottom: 12 }} />}
      {actionError && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)", marginBottom: 12 }}>
        Not done — {actionError}</div>}
      <MiniStatRow>
        <MiniStat value={data.count} label="Waiting on a human"
          tone={data.count > 0 ? "var(--amb4)" : "var(--t1)"} />
        <MiniStat value={n("kinetic_inbox")} label="Inbox proposals" />
        <MiniStat value={n("paused_runs")} label="Paused deep runs" />
        <MiniStat value={n("automation_approvals")} label="Automation approvals" />
        {/* `?? 0` because this source is newer than the panel: an API that predates
            VA-6 omits the key, and rendering `undefined` where a count belongs is a
            worse answer than zero. */}
        <MiniStat value={n("agent_alerts")} label="Agent alerts" />
        <MiniStat value={n("broken_automations")} label="Broken automations"
          tone={(data.sources.broken_automations ?? 0) > 0 ? "var(--red4)" : undefined} />
        {/* The leading indicator. A count says how many are waiting; the OLDEST says
            whether anything has been abandoned — three items waiting a minute and three
            waiting since Tuesday are the same count and a different situation. */}
        <MiniStat label="Oldest waiting"
          value={oldest == null ? "—" : humanAge(oldest)}
          tone={oldest != null && oldest > 3_600_000 ? "var(--red4)" : undefined} />
      </MiniStatRow>

      {unread.length > 0 && (
        <div role="alert" data-testid="needs-unread" className="aug-fs-sm" style={{ color: "var(--amb4)", marginBottom: 12 }}>
          {`Could not read ${unread.map(k => SOURCE_WORDS[k]).join(", ")} — anything waiting there is not shown.`}
        </div>
      )}

      {data.rows.length === 0 ? (
        <div style={{ padding: 32, textAlign: "center", color: "var(--t3)", fontSize: 12,
          background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)" }}>
          {unread.length > 0 ? "Nothing waits in the sources that could be read."
            : "Nothing needs a human. Every source is empty right now."}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {data.rows.map(row => {
            const chip = chipFor(row);
            // SP-9 — a row that IS a staged proposal renders the full approval card:
            // what either click creates, its open choices as fields, never a bare
            // Accept beside a one-line title (the measured break: "Accept and Reject
            // with no view of what either creates"). Resolving through the card hits
            // the same resolve-once inbox; `load()` then drops the row here.
            const proposalId = row.source === "kinetic_inbox" ? row.id
              : row.source === "automation_approval" ? (row.resolve?.proposal_id ?? "") : "";
            return (
              <div key={`${row.source}:${row.id}`}
                style={{ display: "flex", alignItems: "flex-start", gap: 12,
                  background: "var(--bg-2)", border: "1px solid var(--b1)",
                  borderRadius: "var(--r3)", padding: "10px 14px" }}>
                <StatusChip hue={chip.hue} strength="soft">{chip.label}</StatusChip>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap" }} title={row.title}>{needsYouTitle(row.title).display}</div>
                  <div style={{ fontSize: 12, color: "var(--t2)", marginTop: 2 }}>
                    waiting {relTime(row.since)}
                    {row.since_basis === "started_at" && " (since start — pause event aged out)"}
                    {row.connection_id ? ` · ${connectionLabel(row.connection_id, conns)}` : ""}
                  </div>
                  {proposalId && (
                    <div style={{ marginTop: 8 }}>
                      <ProposalCardById proposalId={proposalId} actor={approverName("control-room")}
                        onResolved={load} />
                    </div>
                  )}
                </div>
                {row.source === "paused_run" && onOpenInvestigation && (
                  <Button variant="secondary" size="xs"
                    onClick={() => onOpenInvestigation(row.id)}>Open & resume</Button>
                )}
                {row.source === "automation_approval" && onOpenAutomations && (
                  <Button variant="ghost" size="xs"
                    onClick={() => onOpenAutomations(row.resolve?.automation_id || row.id)}>Open automation</Button>
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
                    onClick={() => onOpenAutomations(row.resolve?.automation_id || row.id)}>Fix automation</Button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
