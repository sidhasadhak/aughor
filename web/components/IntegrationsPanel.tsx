"use client";
import { ErrorState, Loading } from "@/components/ui/states";

/**
 * VA-11 · the integrations catalog — Set up, Connect, revoke.
 *
 * The two-button shape the user's reference screenshots describe, and the reason it is
 * two buttons: a provider needs the ORG's OAuth client before any USER can grant
 * anything, and those are different people doing different jobs. A card with no app
 * registered says **Set up** (paste client id + secret, with the redirect URI the
 * provider console will demand shown right there); a registered one says **Connect**
 * and sends the browser to the provider's own consent screen — the one place the
 * user's password belongs, and a place this code never sees.
 *
 * What never appears here: a token. The API drops token fields server-side, so this
 * component could not render one if it tried — which is the point.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  beginIntegrationConnect, getIntegrationsCatalog, revokeIntegrationConnection,
  setupIntegrationApp,
  type IntegrationProvider,
  deleteSlackBot,
  getConnections,
  getManagedSupervisor,
  getSlackBots,
  getSupervisorKeyStatus,
  issueSupervisorKey,
  listUserAgents,
  restartManagedSupervisor,
  updateSlackBot,
  type Connection,
  type ManagedSupervisorStatus,
  type SlackBotSummary,
  type UserAgent,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { bindingProblem, patchBodyFor, type SlackBotChanges } from "@/lib/slackBots";

import { AgentSlackDoor } from "@/components/agentops/AgentSlackDoor";
import { McpServersSection } from "@/components/McpServersSection";
import { SelectField } from "@/components/ui/select";

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "7px 10px", borderRadius: "var(--r3)",
  border: "1px solid var(--b1)", background: "var(--bg-1)", color: "var(--t1)",
};

export function IntegrationsPanel() {
  const [providers, setProviders] = useState<IntegrationProvider[]>([]);
  const [redirectUri, setRedirectUri] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  /** The provider whose Set up form is open. One at a time — it is a focused task. */
  const [setupFor, setSetupFor] = useState<string | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  /** The callback being authored. Seeded from what the provider has stored, else from
   *  the address this API is currently reached at — which is only the right answer when
   *  the two happen to agree. */
  const [callback, setCallback] = useState("");
  const [busy, setBusy] = useState("");
  /** Set after a revoke of a provider with no revocation endpoint — the one case where
   *  "revoked" is only half true and the reader must be told the other half. */
  const [notice, setNotice] = useState("");
  /** The provider whose alternative door is open — Slack's app flow, today. */
  const [doorFor, setDoorFor] = useState<string | null>(null);
  const [bots, setBots] = useState<SlackBotSummary[]>([]);
  const [agents, setAgents] = useState<UserAgent[]>([]);
  /** For the "asks on" choice — a bot's connection is what its @mentions run against. */
  const [connections, setConnections] = useState<Connection[]>([]);
  /** The record whose edit form is open, and the form's draft. One at a time. */
  const [editBot, setEditBot] = useState<string | null>(null);
  const [botDraft, setBotDraft] = useState({ name: "", agent_id: "", connection_id: "", channel_id: "",
    rehearse: false });
  /** The connection a NEW app asks on. Defaults to the chosen agent's own binding, which
   *  is the pairing the ask door insists on; a bot created with none used to fall back to
   *  the supervisor's default and be refused on every @mention. */
  const [doorConnection, setDoorConnection] = useState("");
  /** Which agent the new app answers AS. Optional: a bot with none still posts, it just
   *  cannot answer an @mention as anybody. */
  const [doorAgent, setDoorAgent] = useState("");
  /** The supervisor's key: whether one exists, and the freshly-minted value while it is
   *  on screen. It is returned once — the panel holds it only until the card closes. */
  const [keyIssued, setKeyIssued] = useState(false);
  const [freshKey, setFreshKey] = useState("");
  // AO-2e — until when the key a Regenerate replaced still opens the door.
  const [graceUntil, setGraceUntil] = useState("");
  // AO-2b — the managed supervisor's state, read beside the bots.
  const [supervisor, setSupervisor] = useState<ManagedSupervisorStatus | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await getIntegrationsCatalog();
      setProviders(d.providers);
      setRedirectUri(d.redirect_uri);
      setError("");
      // Only when a provider actually routes to that door — an install with no Slack
      // provider should not be asking about Slack bots on every load.
      if (d.providers.some(p => p.alt_door === "slack_app")) {
        const [b, a, c] = await Promise.all([
          getSlackBots().catch(() => []),
          listUserAgents().catch(() => []),
          getConnections().catch(() => []),
        ]);
        setBots(b);
        setAgents(a);
        setConnections(c);
        // AO-2b — read apart from the three above: an older API without the route must
        // not blank the bots, and the block simply does not render without an answer.
        getManagedSupervisor().then(setSupervisor).catch(() => setSupervisor(null));
        setKeyIssued((await getSupervisorKeyStatus().catch(() => null))?.issued ?? false);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoaded(true);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  // A finished consent lands on the API's own "Connected" page in the OAuth tab; this
  // tab still shows the old state. Refetch when the user comes back to it, so the card
  // flips to "connected" without anyone hunting for a refresh control.
  useEffect(() => {
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load]);

  const categories = useMemo(() => {
    const by = new Map<string, IntegrationProvider[]>();
    for (const p of providers) {
      by.set(p.category, [...(by.get(p.category) ?? []), p]);
    }
    return [...by.entries()];
  }, [providers]);

  /** Open (or close) one provider's form, seeded from what is stored.
   *
   *  It used to clear both fields on every open, which read as "nothing was ever saved"
   *  on a provider that was in fact configured — the user's own report. The client id
   *  comes back whole; the secret cannot (it is encrypted at rest and masked on every
   *  read) so its box stays empty and says what empty MEANS: keep the stored one. */
  const openSetup = (p: IntegrationProvider) => {
    const opening = setupFor !== p.id;
    setSetupFor(opening ? p.id : null);
    setClientId(opening ? p.client_id : "");
    setClientSecret("");
    setCallback(opening ? (p.redirect_uri || redirectUri) : "");
  };

  /** One field changed on screen is the WHOLE plain record on the wire (`patchBodyFor`):
   *  the server replaces what it is sent, and a partial body would blank the rest. */
  const saveBot = async (bot: SlackBotSummary, changes: SlackBotChanges) => {
    setBusy(bot.id); setError("");
    try {
      await updateSlackBot(bot.id, patchBodyFor(bot, changes));
      setEditBot(null);
      await load();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  };

  const removeBot = async (bot: SlackBotSummary) => {
    if (!window.confirm(
      `Delete the Slack bot “${bot.name}”? Its tokens are removed and its socket closes. `
      + "Automations that post as it will report \"unknown Slack bot\" until they are re-pointed.",
    )) return;
    setBusy(bot.id); setError("");
    try { await deleteSlackBot(bot.id); await load(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  };

  const saveApp = async (provider: string) => {
    setBusy(provider);
    setError("");
    try {
      await setupIntegrationApp(provider, {
        client_id: clientId.trim(), client_secret: clientSecret.trim(),
        // Sent only when the person changed it away from the derived address: an
        // override stored on every save would freeze a deployment to whatever host it
        // happened to be reached at the day someone last opened this form.
        redirect_uri: callback.trim() === redirectUri.trim() ? "" : callback.trim(),
      });
      setClientId(""); setClientSecret(""); setCallback(""); setSetupFor(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const connect = async (provider: string) => {
    setBusy(provider);
    setError("");
    try {
      const url = await beginIntegrationConnect(provider);
      // A NEW tab, so this one survives to refetch on refocus. The consent screen is
      // the provider's page; nothing about it belongs inside this app's frame. A popup
      // blocker returns null SILENTLY — measured — so the fallback is same-tab
      // navigation rather than a Connect button that does nothing.
      if (!window.open(url, "_blank", "noopener")) window.location.href = url;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const revoke = async (p: IntegrationProvider) => {
    if (!p.connection) return;
    setBusy(p.id);
    setError("");
    setNotice("");
    try {
      const r = await revokeIntegrationConnection(p.connection.id);
      if (!r.provider_side) {
        setNotice(`${p.name} offers no revocation endpoint — the grant is cleared here, `
          + `but also remove it on the account's own security page.`);
      }
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  if (!loaded) {
    return <Loading what="integrations" style={{ padding: 24 }} />;
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "18px 22px", maxWidth: 980 }}>
      <div className="aug-fs-sm" style={{ color: "var(--t2)", marginBottom: 14, maxWidth: 680 }}>
        Connect the org's accounts by OAuth. Aughor holds every token itself — encrypted at
        rest, refreshed before expiry, never shown to a model or a screen — and each grant
        is a governed record with an owner, scopes and a revoke.
      </div>

      {error && (
        <ErrorState kind="Integration failed" what={error} style={{ marginBottom: 12 }} />
      )}
      {notice && (
        <div className="aug-callout aug-callout-amber" style={{ marginBottom: 12 }}>{notice}</div>
      )}

      {categories.map(([category, rows]) => (
        <div key={category} style={{ marginBottom: 18 }}>
          <div className="aug-fs-xs" style={{ color: "var(--t3)", letterSpacing: "0.06em",
            textTransform: "uppercase", marginBottom: 8 }}>{category}</div>
          <div style={{ display: "grid", gap: 10,
            gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}>
            {rows.map(p => (
              <div key={p.id} style={{ border: "1px solid var(--b1)",
                borderRadius: "var(--r3)", padding: 14, background: "var(--bg-1)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="aug-fs-ui" style={{ fontWeight: 600 }}>{p.name}</span>
                  {p.connection?.status === "active" && (
                    <span className="aug-fs-xs" style={{ color: "var(--grn4)" }}>
                      ● connected{p.connection.account ? ` · ${p.connection.account}` : ""}
                    </span>
                  )}
                  {p.connection?.status === "needs_reconnect" && (
                    <span className="aug-fs-xs" style={{ color: "var(--amb4)" }}>
                      ● needs reconnect
                    </span>
                  )}
                  <span style={{ marginLeft: "auto", display: "flex", alignItems: "center",
                    gap: 6 }}>
                    {/* Set up was a ONE-WAY door: once an org client was stored the card
                        offered only Connect (or Revoke), so a client id pasted with a
                        typo, a rotated secret, or an app swapped for another could not
                        be corrected from any screen. The credentials are still never
                        READ back — the form replaces them, it does not display them. */}
                    {/* A provider whose OAuth cannot complete HERE routes to the door
                        that can. Slack refuses `http://`, a laptop has nothing else, and
                        its app+Socket-Mode path needs no callback at all — so offering
                        Connect would be pointing a fresh install at the one door its
                        deployment cannot open. OAuth comes back on its own the moment
                        the callback is https (a tunnel, or a real deployment). */}
                    {!p.oauth_ready && p.alt_door === "slack_app" ? (
                      <Button variant="default" size="xs"
                        onClick={() => setDoorFor(cur => cur === p.id ? null : p.id)}>
                        {doorFor === p.id ? "Close" : "Add Slack app"}
                      </Button>
                    ) : (<>
                    {p.configured && (
                      <Button variant="ghost" size="xs" disabled={busy === p.id}
                        title={`Replace the ${p.name} OAuth client`}
                        onClick={() => { openSetup(p); }}>
                        Edit
                      </Button>
                    )}
                    {!p.configured ? (
                      <Button variant="secondary" size="xs" disabled={busy === p.id}
                        onClick={() => { openSetup(p); }}>
                        Set up
                      </Button>
                    ) : p.connection?.status === "active" ? (
                      <Button variant="ghost" size="xs" disabled={busy === p.id}
                        onClick={() => revoke(p)}>Revoke</Button>
                    ) : (
                      <Button variant="default" size="xs" disabled={busy === p.id}
                        onClick={() => connect(p.id)}>
                        {p.connection?.status === "needs_reconnect" ? "Reconnect" : "Connect"}
                      </Button>
                    )}
                    </>)}
                  </span>
                </div>
                <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 4 }}>
                  {p.blurb}
                </div>

                {/* Why this card looks different from its neighbours — said plainly,
                    because "Add Slack app" beside Google's "Connect" is otherwise an
                    inconsistency a reader has to explain to themselves. */}
                {!p.oauth_ready && p.alt_door === "slack_app" && (
                  <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 6,
                    lineHeight: 1.5 }}>
                    {p.name}&apos;s OAuth needs an HTTPS callback and this deployment is
                    reached at <code>{redirectUri}</code>. A Slack <strong>app</strong>
                    {" "}needs none — it opens an outbound socket — so it works on a
                    laptop with no tunnel.
                  </div>
                )}

                {/* The records themselves — every field a person can change, changed
                    here. Before this the page could only ADD a bot: fixing a record meant
                    a shell PATCH, and a bot bound to the wrong connection sat answering
                    "did not answer (HTTP 409)" in Slack with nothing on this screen
                    saying why. */}
                {p.alt_door === "slack_app" && bots.length > 0 && (
                  <div style={{ marginTop: 10, borderTop: "1px solid var(--b1)",
                    paddingTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
                    {bots.map(b => {
                      const agent = agents.find(a => a.id === b.agent_id);
                      const connName = (id: string) =>
                        connections.find(c => c.id === id)?.name || id;
                      const problem = bindingProblem(b, agents, connName);
                      const editing = editBot === b.id;
                      return (
                        <div key={b.id} style={{ border: "1px solid var(--b1)",
                          borderRadius: "var(--r2)", padding: "8px 10px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8,
                            flexWrap: "wrap" }}>
                            <span className="aug-fs-ui" style={{ flex: 1 }}>
                              <strong>{b.name}</strong>
                              {!b.enabled && (
                                <span className="aug-fs-xs" style={{ color: "var(--t3)",
                                  marginLeft: 6 }}
                                  title={b.disabled_reason || undefined}>
                                  {b.disabled_reason
                                    ? `off — ${b.disabled_reason}`
                                    : "paused"}
                                </span>
                              )}
                              {/* AO-2a — "enabled" is the record; LISTENING is the socket.
                                  The card said the first and implied the second on a
                                  machine where no supervisor ran. */}
                              {b.enabled && (
                                b.listening ? (
                                  <span className="aug-fs-xs" style={{ color: "var(--grn4)",
                                    marginLeft: 6 }}
                                    title={`supervisor ${b.listening.supervisor_id} · last heard ${b.listening.last_seen_at}`}>
                                    listening since {formatDateTime(b.listening.since)}
                                  </span>
                                ) : (
                                  <span className="aug-fs-xs" style={{ color: "var(--amb4)",
                                    marginLeft: 6 }} title={b.liveness_hint}>
                                    {b.liveness_hint || "not listening — start the supervisor"}
                                  </span>
                                )
                              )}
                            </span>
                            <Button variant="ghost" size="xs" disabled={busy === b.id}
                              onClick={() => {
                                setEditBot(editing ? null : b.id);
                                setBotDraft({ name: b.name, agent_id: b.agent_id,
                                  connection_id: b.connection_id, channel_id: b.channel_id ?? "",
                                  rehearse: b.rehearse ?? false });
                              }}>
                              {editing ? "Cancel" : "Edit"}
                            </Button>
                            <Button variant="ghost" size="xs" disabled={busy === b.id}
                              title={b.enabled
                                ? "The supervisor closes this bot's socket on its next reconcile"
                                : "The supervisor re-opens this bot's socket on its next reconcile"}
                              onClick={() => saveBot(b, { enabled: !b.enabled })}>
                              {b.enabled ? "Pause" : "Resume"}
                            </Button>
                            <Button variant="ghost" size="xs" disabled={busy === b.id}
                              onClick={() => removeBot(b)}>
                              Delete
                            </Button>
                          </div>
                          <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 4,
                            lineHeight: 1.5 }}>
                            Answers as {agent ? agent.name : "nobody — posting only"}
                            {" · "}asks on {b.connection_id ? connName(b.connection_id) : "no connection"}
                            {" · "}Slack member ID <code>{b.bot_user_id || "unknown"}</code>
                          </div>
                          {problem && (
                            <div className="aug-fs-xs" style={{ color: "var(--amb4)",
                              marginTop: 4, lineHeight: 1.5 }}>
                              {problem}
                            </div>
                          )}
                          {editing && (
                            <div style={{ marginTop: 8, display: "flex",
                              flexDirection: "column", gap: 6 }}>
                              <input className="aug-fs-ui" style={inputStyle} value={botDraft.name}
                                aria-label="Bot name"
                                onChange={e => setBotDraft(d => ({ ...d, name: e.target.value }))} />
                              <SelectField className="aug-fs-ui" style={inputStyle}
                                value={botDraft.agent_id} aria-label="Answers as agent"
                                onChange={e => {
                                  const chosen = agents.find(a => a.id === e.target.value);
                                  setBotDraft(d => ({ ...d, agent_id: e.target.value,
                                    // A bound agent brings its connection along — the
                                    // pairing the ask door will insist on anyway.
                                    connection_id: chosen?.connection_id || d.connection_id }));
                                }}>
                                <option value="">No agent — posting only</option>
                                {agents.map(a => (
                                  <option key={a.id} value={a.id}>{a.name}</option>
                                ))}
                              </SelectField>
                              <SelectField className="aug-fs-ui" style={inputStyle}
                                value={botDraft.connection_id} aria-label="Asks on connection"
                                onChange={e => setBotDraft(d => ({ ...d,
                                  connection_id: e.target.value }))}>
                                <option value="">No connection</option>
                                {botDraft.connection_id
                                  && !connections.some(c => c.id === botDraft.connection_id) && (
                                  <option value={botDraft.connection_id}>
                                    {botDraft.connection_id} (not found)
                                  </option>
                                )}
                                {connections.map(c => (
                                  <option key={c.id} value={c.id}>{c.name}</option>
                                ))}
                              </SelectField>
                              {/* AO-2f — an optional home channel on the record. */}
                              <input className="aug-fs-ui" style={inputStyle} value={botDraft.channel_id}
                                aria-label="Home channel" placeholder="Home channel — #name or C… (optional)"
                                onChange={e => setBotDraft(d => ({ ...d, channel_id: e.target.value }))} />
                              {/* AO-6 — rehearse: a post from an automation AS this bot waits in
                                  Attention for a person's click before it reaches the channel, and a
                                  channel mention is answered in the asker's DM first — their ✅ there
                                  posts it in the thread. The bot reads the same row; a flip reconciles it. */}
                              <label className="aug-fs-xs" style={{ display: "inline-flex", alignItems: "center",
                                gap: 6, color: "var(--t2)", cursor: "pointer" }}>
                                <input type="checkbox" checked={botDraft.rehearse}
                                  onChange={e => setBotDraft(d => ({ ...d, rehearse: e.target.checked }))} />
                                Rehearse — a mention is answered in the asker&apos;s DM first (their ✅ posts it in
                                the thread), and every automation post as this bot waits for a person&apos;s click
                                (&quot;always allow&quot; on the held post lifts it per channel)
                              </label>
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <Button variant="default" size="xs" disabled={busy === b.id}
                                  onClick={() => saveBot(b, botDraft)}>
                                  Save
                                </Button>
                                <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                                  A new agent or connection re-opens the socket within
                                  30 seconds; a rename does not.
                                </span>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* The supervisor's key, offered where its bots are — and only once
                    there is a bot, because a key for a supervisor with nothing to
                    supervise is a control asking to be ignored. It exists so the fix
                    for "the API refused to serve bot credentials" is a button here
                    rather than a shell export and a restart. */}
                {/* AO-2b — the supervisor the API runs itself, when the flag is on: its
                    state in a sentence, and the one control. Off, one line says how it
                    is started by hand. */}
                {/* Shown with NO bots too when the API manages it: on a fresh install the
                    supervisor runs before the first bot exists, and a row that waits for a
                    bot card reads as "nothing is running" (receipt, 2026-10-03). */}
                {p.alt_door === "slack_app" && supervisor && (bots.length > 0 || supervisor.managed) && (
                  <div className="aug-fs-xs" style={{ marginTop: 10, borderTop: "1px solid var(--b1)",
                    paddingTop: 10, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ color: supervisor.state === "running" ? "var(--grn4)"
                      : supervisor.state === "off" ? "var(--t3)" : "var(--amb4)", flex: 1 }}
                      title={supervisor.log_path ? `the supervisor's own log: ${supervisor.log_path}` : undefined}>
                      {supervisor.state === "off"
                        ? "Supervisor: started by hand — cd bots/slack && npm run dev (turn on "
                          + "slack.managed_supervisor to let the API run it)"
                        : supervisor.state === "running"
                          ? `Supervisor: run by the API · pid ${supervisor.pid} · since ${formatDateTime(supervisor.started_at)}`
                            + (supervisor.restarts ? ` · restarted ${supervisor.restarts}×` : "")
                            + (supervisor.heartbeat
                                ? (supervisor.heartbeat.fresh
                                    ? ` · listening — heartbeat ${formatDateTime(supervisor.heartbeat.last_seen_at)}, ${supervisor.heartbeat.running} bot(s) open`
                                    : ` · NOT listening — last heartbeat ${formatDateTime(supervisor.heartbeat.last_seen_at)}`)
                                : " · no heartbeat yet")
                          : `Supervisor: ${supervisor.state} — ${supervisor.last_error || "no reason recorded"}`}
                    </span>
                    {supervisor.managed && (
                      <Button variant="ghost" size="xs" disabled={busy === "supervisor"}
                        onClick={async () => {
                          setBusy("supervisor"); setError("");
                          try { setSupervisor(await restartManagedSupervisor()); }
                          catch (e) { setError((e as Error).message); }
                          finally { setBusy(""); }
                        }}>Restart</Button>
                    )}
                  </div>
                )}
                {p.alt_door === "slack_app" && bots.length > 0 && (
                  <div style={{ marginTop: 10, borderTop: "1px solid var(--b1)",
                    paddingTop: 10 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span className="aug-fs-xs" style={{ color: "var(--t3)", flex: 1 }}>
                        Supervisor key — needed only to run the socket supervisor, which
                        answers @mentions. Posting from automations never uses it.
                        {keyIssued && !freshKey && " One is set."}
                      </span>
                      <Button variant="secondary" size="xs" disabled={busy === "key"}
                        onClick={async () => {
                          setBusy("key"); setError("");
                          try {
                            const k = await issueSupervisorKey();
                            setFreshKey(k.env_line);
                            setGraceUntil(k.previous_valid_until || "");
                            setKeyIssued(true);
                          } catch (e) { setError((e as Error).message); }
                          finally { setBusy(""); }
                        }}>
                        {keyIssued ? "Regenerate" : "Generate"}
                      </Button>
                    </div>
                    {freshKey && (
                      <div style={{ marginTop: 8, display: "flex", flexDirection: "column",
                        gap: 6 }}>
                        {/* Shown ONCE. Re-reading returns a status, never the value, so
                            this line is the only chance to copy it. */}
                        <code className="aug-fs-xs" style={{ padding: "6px 8px",
                          background: "var(--bg-2)", borderRadius: "var(--r2)",
                          border: "1px solid var(--b1)", overflowWrap: "anywhere" }}>
                          {freshKey}
                        </code>
                        <div className="aug-fs-xs" style={{ color: "var(--amb4)",
                          lineHeight: 1.5 }}>
                          Copy this now — it is shown once. Paste it into the bot
                          supervisor&apos;s <code>.env.local</code>, then restart that
                          process.{" "}
                          {graceUntil
                            ? `The key it replaces keeps working until ${formatDateTime(graceUntil)}, so the running supervisor stays up until you restart it.`
                            : "Regenerating later replaces it; the replaced key keeps working for a few minutes so the running supervisor can be restarted."}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {doorFor === p.id && (
                  <div style={{ marginTop: 12, borderTop: "1px solid var(--b1)",
                    paddingTop: 12 }}>
                    {agents.length > 0 && (
                      <div style={{ marginBottom: 12 }}>
                        <div className="aug-fs-xs" style={{ color: "var(--t3)",
                          marginBottom: 4 }}>
                          Answer as (optional) — an app with no agent can still post; it
                          just cannot answer an @mention as anybody.
                        </div>
                        <SelectField className="aug-fs-ui" style={inputStyle} value={doorAgent}
                          aria-label="Answer as agent"
                          onChange={e => {
                            const chosen = agents.find(a => a.id === e.target.value);
                            setDoorAgent(e.target.value);
                            if (chosen?.connection_id) setDoorConnection(chosen.connection_id);
                          }}>
                          <option value="">No agent — posting only</option>
                          {agents.map(a => (
                            <option key={a.id} value={a.id}>{a.name}</option>
                          ))}
                        </SelectField>
                      </div>
                    )}
                    <div style={{ marginBottom: 12 }}>
                      <div className="aug-fs-xs" style={{ color: "var(--t3)",
                        marginBottom: 4 }}>
                        Asks on — the connection @mentions run against. When the agent is
                        bound to a connection it must be that one, or answers are refused.
                      </div>
                      <SelectField className="aug-fs-ui" style={inputStyle} value={doorConnection}
                        aria-label="Asks on connection"
                        onChange={e => setDoorConnection(e.target.value)}>
                        <option value="">No connection — posting only</option>
                        {connections.map(c => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </SelectField>
                    </div>
                    <AgentSlackDoor
                      agentId={doorAgent}
                      agentName={agents.find(a => a.id === doorAgent)?.name || "Aughor"}
                      connectionId={doorConnection}
                      heading="Add a Slack app"
                      intro={"No callback, no tunnel, no HTTPS: a Slack app opens an "
                        + "**outbound** socket to Slack, which is why it works from a "
                        + "laptop when OAuth cannot. Aughor renders the manifest; you "
                        + "create the app in Slack and paste three values back."}
                      skipLabel="Close"
                      onDone={() => {
                        setDoorFor(null); setDoorAgent(""); setDoorConnection("");
                        void load();
                      }}
                    />
                  </div>
                )}
                {p.connection?.status === "active" && p.connection.scopes && (
                  // What the provider says was GRANTED — read back from the token
                  // response, so a scope the user declined is never listed.
                  <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 6,
                    overflowWrap: "anywhere" }}>
                    granted: {p.connection.scopes}
                  </div>
                )}

                {setupFor === p.id && (
                  <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8,
                    borderTop: "1px solid var(--b1)", paddingTop: 10 }}>
                    <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                      {p.configured && "Replace the stored client — the current secret is "
                        + "never shown, only overwritten. "}
                      {p.configured ? "Create or pick an OAuth client in " : "Create an OAuth client in "}
                      <a href={p.console_url} target="_blank" rel="noreferrer"
                        style={{ color: "var(--blue4)" }}>the {p.name} console</a>
                      {" "}with this redirect URI, then paste the client credentials back:
                    </div>
                    {/* EDITABLE. It was a read-only `<code>` of the address this API
                        happens to be reached at, which is the right answer only when
                        that matches what the provider has registered — and it cannot
                        match for a provider that refuses http:// while you develop over
                        localhost. Blank-equals-derived is preserved: saving it unchanged
                        stores no override at all. */}
                    {/* Labelled, because the field does not explain itself: asked for
                        "the redirect URI" beside a {p.name} console link, a reasonable
                        person pastes their {p.name} address. It is the opposite — the
                        address {p.name} comes BACK to. */}
                    <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                      Redirect URI — where {p.name} sends the browser <strong>back to
                      Aughor</strong>. It must reach THIS API
                      {p.https_only ? " over HTTPS (a tunnel is enough)" : ""}, and be
                      registered in the {p.name} console verbatim.
                    </div>
                    <input className="aug-fs-xs" style={{ ...inputStyle,
                      fontFamily: "var(--font-mono)" }}
                      value={callback} spellCheck={false} autoComplete="off"
                      aria-label="Redirect URI"
                      placeholder={redirectUri}
                      onChange={e => setCallback(e.target.value)} />
                    {callback.trim() && callback.trim() !== redirectUri.trim() && (
                      <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                        Overrides the derived address ({redirectUri}) — the provider will
                        be sent this one, and the exchange will use the same string.
                      </div>
                    )}
                    {/* Said BEFORE the credentials are pasted, not after the provider's
                        own error page. Slack rejects `http://` outright — localhost
                        included — while Google and Microsoft accept the loopback
                        address; `https_only` is the provider's own documented rule,
                        carried as adapter data rather than assumed here. */}
                    {p.https_only && redirectUri.startsWith("http://") && (
                      <div className="aug-fs-xs" style={{ color: "var(--amb4)",
                        lineHeight: 1.5 }}>
                        {p.name} refuses an <code>http://</code> redirect URL, localhost
                        included — registering the URI above will fail with
                        “redirect_uri did not match”. Reach this API over HTTPS (a tunnel
                        is enough — the callback follows the forwarded host), then
                        register that address instead.
                      </div>
                    )}
                    <input className="aug-fs-ui" style={inputStyle} placeholder="Client ID"
                      value={clientId} autoComplete="off" spellCheck={false}
                      onChange={e => setClientId(e.target.value)} />
                    <input className="aug-fs-ui" style={inputStyle}
                      placeholder={p.secret_preview
                        ? `Client secret — stored (${p.secret_preview}), leave blank to keep it`
                        : "Client secret"}
                      value={clientSecret} autoComplete="off" spellCheck={false}
                      onChange={e => setClientSecret(e.target.value)} />
                    <div style={{ display: "flex", gap: 6 }}>
                      <Button variant="default" size="xs"
                        /* The secret is required only when there is not one already:
                           blank now MEANS "keep the stored one", and a Save that stayed
                           disabled would have made that impossible to express. */
                        disabled={!clientId.trim() || busy === p.id
                                  || (!clientSecret.trim() && !p.secret_preview)}
                        onClick={() => saveApp(p.id)}>
                        {busy === p.id ? "Saving…" : "Save"}
                      </Button>
                      <Button variant="ghost" size="xs" onClick={() => setSetupFor(null)}>
                        Cancel
                      </Button>
                    </div>
                    <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                      <Icon name="lock" size={11} /> Stored encrypted; the secret comes back
                      masked and is never shown again.
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
      {/* VA-9d — §3.4's item 4 puts it LAST, and the order is the argument: everything
          above is "connect as me", an account a user grants us. This is "call out to
          them", a third party an operator writes down. */}
      <McpServersSection />
    </div>
  );
}
