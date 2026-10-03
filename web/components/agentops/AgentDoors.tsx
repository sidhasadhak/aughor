"use client";

/**
 * Arc AO-4 — the agent's Doors: every way in to this agent, each with its STATE and the one
 * control that acts on it. The Map draws the same things as nodes; this is the list a
 * person works from. A door the platform does not have yet is said as such, never left
 * off the list — a missing row reads as "there is no such door", which is a different
 * claim from "not built yet" (Arc AO-5 builds HTTP and MCP).
 */
import { useCallback, useEffect, useState } from "react";

import { StatusChip } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { ReadFailed } from "@/components/ui/states";
import {
  getAutomations, getSlackBots, type Automation, type SlackBotSummary, type UserAgent,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { Term } from "@/components/agentops/Term";

type Hue = "positive" | "info" | "caution" | "negative" | "muted" | "accent";

function DoorRow({ kind, title, state, hue, detail, action }: {
  kind: string; title: string; state: string; hue: Hue; detail?: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
      background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r2)" }}>
      <span className="aug-fs-xs" style={{ color: "var(--t3)", width: 72, flexShrink: 0,
        textTransform: "uppercase", letterSpacing: "0.05em" }}>{kind}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="aug-fs-ui" style={{ color: "var(--t1)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
        {detail && (
          <div className="aug-fs-xs" style={{ color: "var(--t2)", marginTop: 2 }}>{detail}</div>
        )}
      </div>
      <StatusChip hue={hue} strength="soft">{state}</StatusChip>
      {action && (
        <Button variant="ghost" size="xs" onClick={action.onClick}>{action.label}</Button>
      )}
    </div>
  );
}

export function AgentDoors({ agent, onChat, onOpenAutomation, onOpenIntegrations }: {
  agent: UserAgent;
  onChat?: (agentId: string) => void;
  onOpenAutomation?: (automationId: string) => void;
  onOpenIntegrations?: () => void;
}) {
  const [bots, setBots] = useState<SlackBotSummary[] | null>(null);
  const [automations, setAutomations] = useState<Automation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const load = useCallback(() => {
    setError(null);
    Promise.all([getSlackBots(), getAutomations()])
      .then(([b, a]) => {
        setBots(b.filter(x => x.agent_id === agent.id));
        setAutomations(a.filter(x => x.agent_id === agent.id
          || x.effects.some(e => (e.config as Record<string, unknown> | undefined)?.agent_id === agent.id)));
      })
      .catch(e => setError(String((e as Error)?.message || e)));
  }, [agent.id]);
  useEffect(() => { load(); }, [load, tick]);

  if (error) {
    return <ReadFailed what="this agent's doors" error={error} onRetry={() => setTick(t => t + 1)} />;
  }
  if (bots === null || automations === null) {
    return <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Loading…</div>;
  }

  return (
    <div style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 6 }}>
      <div className="aug-fs-sm" style={{ color: "var(--t2)", marginBottom: 6 }}>
        Every <Term id="door" /> into this agent, with its state. A door that is not built
        yet says so.
      </div>
      <DoorRow kind="chat" title="Chat"
        state={agent.enabled ? "open" : "paused"} hue={agent.enabled ? "positive" : "caution"}
        detail={agent.enabled ? "answers when asked as this agent" : "paused — answers nothing"}
        action={onChat && agent.enabled ? { label: "Chat", onClick: () => onChat(agent.id) } : undefined} />
      {bots.length === 0 ? (
        <DoorRow kind="slack" title="No Slack bot fronts this agent" state="none" hue="muted"
          detail="Create one from the agent's Reach step or Integrations → Slack."
          action={onOpenIntegrations ? { label: "Open Integrations", onClick: onOpenIntegrations } : undefined} />
      ) : bots.map(b => (
        <DoorRow key={b.id} kind="slack" title={b.name}
          state={!b.enabled ? "off" : b.listening ? "listening" : "not listening"}
          hue={!b.enabled ? "caution" : b.listening ? "positive" : "negative"}
          detail={!b.enabled
            ? (b.disabled_reason || "paused by a person")
            : b.listening
              ? `listening since ${formatDateTime(b.listening.since)} · supervisor ${b.listening.supervisor_id}`
              : (b.liveness_hint || "not listening — start the supervisor")}
          action={onOpenIntegrations ? { label: "Open Integrations", onClick: onOpenIntegrations } : undefined} />
      ))}
      {automations.length === 0 ? (
        <DoorRow kind="automation" title="No automation runs as this agent" state="none" hue="muted"
          detail="Bind one on the Automations layer — a schedule or a signal, answered as this agent." />
      ) : automations.map(a => (
        <DoorRow key={a.id} kind="automation" title={a.name}
          state={a.enabled ? "enabled" : "paused"} hue={a.enabled ? "positive" : "caution"}
          detail={a.agent_id === agent.id ? "runs as this agent" : "one step runs as this agent"}
          action={onOpenAutomation ? { label: "Open automation", onClick: () => onOpenAutomation(a.id) } : undefined} />
      ))}
      <DoorRow kind="http" title="HTTP — a per-agent key and an embeddable widget"
        state="not built yet" hue="muted" detail="Arc AO-5 builds it; there is no HTTP door to this agent today." />
      <DoorRow kind="mcp" title="MCP — this agent as a tool for another agent"
        state="not built yet" hue="muted" detail="Arc AO-5 builds it, with the caller as a principal (Arc DE-2)." />
    </div>
  );
}
