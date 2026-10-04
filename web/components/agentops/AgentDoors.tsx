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
import { Loading, ReadFailed } from "@/components/ui/states";
import {
  createTeamsBot, deleteTeamsBot, getAgentDoors, getAutomations, getSlackBots, issueAgentKey,
  revokeAgentKey, type AgentDoorsInfo, type Automation, type SlackBotSummary, type UserAgent,
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
  const [doors, setDoors] = useState<AgentDoorsInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  // AO-5 — a minted key is shown ONCE; the status never discloses it again.
  const [freshKey, setFreshKey] = useState<{ header: string; curl: string } | null>(null);
  const [teamsDraft, setTeamsDraft] = useState<{ name: string; app_id: string; app_password: string } | null>(null);
  const [teamsMade, setTeamsMade] = useState<{ endpoint: string; needs: string[] } | null>(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    setError(null);
    Promise.all([getSlackBots(), getAutomations(), getAgentDoors(agent.id)])
      .then(([b, a, d]) => {
        setBots(b.filter(x => x.agent_id === agent.id));
        setAutomations(a.filter(x => x.agent_id === agent.id
          || x.effects.some(e => (e.config as Record<string, unknown> | undefined)?.agent_id === agent.id)));
        setDoors(d);
      })
      .catch(e => setError(String((e as Error)?.message || e)));
  }, [agent.id]);
  useEffect(() => { load(); }, [load, tick]);

  const act = async (what: string, fn: () => Promise<void>) => {
    setBusy(what); setError(null);
    try { await fn(); setTick(t => t + 1); }
    catch (e) { setError(String((e as Error)?.message || e)); }
    finally { setBusy(""); }
  };

  if (error) {
    return <ReadFailed what="this agent's doors" error={error} onRetry={() => setTick(t => t + 1)} />;
  }
  if (bots === null || automations === null) {
    return <Loading what="this agent's doors" />;
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
      {doors && (
        <>
          <DoorRow kind="mcp" title={`MCP tool ${doors.mcp.tool}`}
            state={doors.mcp.state} hue={doors.mcp.state === "open" ? "positive" : "caution"}
            detail={doors.mcp.how} />
          <DoorRow kind="http" title="HTTP — ask this agent with its key"
            state={doors.http.state}
            hue={doors.http.state === "open" ? "positive" : doors.http.state === "no key" ? "muted" : "caution"}
            detail={doors.http.key_issued_at
              ? `key issued ${formatDateTime(doors.http.key_issued_at)} · POST ${doors.http.url}`
              : `no key yet · POST ${doors.http.url} once one is issued`}
            action={{
              label: busy === "key" ? "…" : doors.http.key_issued_at ? "Rotate key" : "Issue key",
              onClick: () => act("key", async () => { const k = await issueAgentKey(agent.id); setFreshKey(k); }),
            }} />
          {freshKey && (
            <div className="aug-fs-xs" style={{ padding: "8px 10px", border: "1px solid var(--b1)",
              borderRadius: "var(--r2)", background: "var(--bg-2)", display: "flex", flexDirection: "column", gap: 6 }}>
              <span style={{ color: "var(--amb4)" }}>
                Copy this now — it is shown once. Rotating replaces it; revoking closes the door.
              </span>
              <code style={{ overflowWrap: "anywhere" }}>{freshKey.header}</code>
              <code style={{ overflowWrap: "anywhere", color: "var(--t2)" }}>{freshKey.curl}</code>
              <span>
                <Button variant="ghost" size="xs" onClick={() => setFreshKey(null)}>Hide</Button>
                {doors.http.key_issued_at && (
                  <Button variant="ghost" size="xs" disabled={busy === "revoke"}
                    onClick={() => act("revoke", async () => { await revokeAgentKey(agent.id); setFreshKey(null); })}>
                    Revoke key
                  </Button>
                )}
              </span>
            </div>
          )}
          <DoorRow kind="embed" title="Embed — a chat page for this agent alone"
            state={doors.embed.state} hue={doors.embed.state === "open" ? "positive" : "muted"}
            detail={`${doors.embed.url} · asks for the agent's key once and keeps it in the browser's session only`}
            action={doors.http.key_issued_at
              ? { label: "Open", onClick: () => window.open(doors.embed.url, "_blank", "noopener") }
              : undefined} />
          <DoorRow kind="webhook" title="Webhook — a question in, the answer back"
            state={doors.webhook.state} hue={doors.webhook.state === "open" ? "positive" : "muted"}
            detail={`POST ${doors.webhook.url} with the key · {question, asker, callback_url?}`} />
          <DoorRow kind="a2a" title="A2A — an agent card and a message/send endpoint"
            state={doors.a2a.state} hue={doors.a2a.state === "open" ? "positive" : "muted"}
            detail={`card ${doors.a2a.card} · POST ${doors.a2a.url} (JSON-RPC message/send, bearer key)`} />
          {doors.teams.bots.length === 0 ? (
            <DoorRow kind="teams" title="Microsoft Teams — no bot fronts this agent"
              state={doors.teams.state} hue="muted"
              detail="Register an Azure Bot (app id + password) and bind it here; the messaging endpoint is said back."
              action={{ label: teamsDraft ? "Cancel" : "Add a Teams bot",
                onClick: () => setTeamsDraft(teamsDraft ? null : { name: `${agent.name} in Teams`, app_id: "", app_password: "" }) }} />
          ) : doors.teams.bots.map(b => (
            <DoorRow key={b.id} kind="teams" title={b.name}
              state={b.enabled ? "bound" : "paused"} hue={b.enabled ? "positive" : "caution"}
              detail={`app ${b.app_id} · messaging endpoint ${doors.http.url.replace(/\/doors\/agents\/.*$/, "")}/doors/teams/${b.id}/messages`}
              action={{ label: "Remove", onClick: () => act("teams", async () => { await deleteTeamsBot(b.id); }) }} />
          ))}
          {teamsDraft && (
            <div className="aug-fs-xs" style={{ padding: "8px 10px", border: "1px solid var(--b1)",
              borderRadius: "var(--r2)", display: "flex", flexDirection: "column", gap: 6 }}>
              <input className="aug-input" value={teamsDraft.name} aria-label="Teams bot name"
                onChange={e => setTeamsDraft({ ...teamsDraft, name: e.target.value })} />
              <input className="aug-input" value={teamsDraft.app_id} placeholder="Microsoft App ID" aria-label="App ID"
                autoComplete="off" onChange={e => setTeamsDraft({ ...teamsDraft, app_id: e.target.value })} />
              <input className="aug-input" value={teamsDraft.app_password} placeholder="App password (client secret)"
                aria-label="App password" autoComplete="off" type="password"
                onChange={e => setTeamsDraft({ ...teamsDraft, app_password: e.target.value })} />
              <span>
                <Button variant="default" size="xs" disabled={busy === "teams" || !teamsDraft.app_id || !teamsDraft.app_password}
                  onClick={() => act("teams", async () => {
                    const made = await createTeamsBot({ name: teamsDraft.name, agent_id: agent.id,
                      connection_id: agent.connection_id, app_id: teamsDraft.app_id, app_password: teamsDraft.app_password });
                    setTeamsMade({ endpoint: made.messaging_endpoint, needs: made.needs });
                    setTeamsDraft(null);
                  })}>Bind</Button>
              </span>
            </div>
          )}
          {teamsMade && (
            <div className="aug-fs-xs" style={{ color: teamsMade.endpoint ? "var(--grn4)" : "var(--amb4)" }}>
              {teamsMade.endpoint
                ? `Set this as the Azure Bot's messaging endpoint: ${teamsMade.endpoint}`
                : teamsMade.needs.join(" ")}
            </div>
          )}
        </>
      )}
    </div>
  );
}
