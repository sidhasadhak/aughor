"use client";

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
  getSlackBots,
  getSupervisorKeyStatus,
  issueSupervisorKey,
  listUserAgents,
  type SlackBotSummary,
  type UserAgent,
} from "@/lib/api";

import { AgentSlackDoor } from "@/components/agentops/AgentSlackDoor";
import { McpServersSection } from "@/components/McpServersSection";

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
  /** Which agent the new app answers AS. Optional: a bot with none still posts, it just
   *  cannot answer an @mention as anybody. */
  const [doorAgent, setDoorAgent] = useState("");
  /** The supervisor's key: whether one exists, and the freshly-minted value while it is
   *  on screen. It is returned once — the panel holds it only until the card closes. */
  const [keyIssued, setKeyIssued] = useState(false);
  const [freshKey, setFreshKey] = useState("");

  const load = useCallback(async () => {
    try {
      const d = await getIntegrationsCatalog();
      setProviders(d.providers);
      setRedirectUri(d.redirect_uri);
      setError("");
      // Only when a provider actually routes to that door — an install with no Slack
      // provider should not be asking about Slack bots on every load.
      if (d.providers.some(p => p.alt_door === "slack_app")) {
        const [b, a] = await Promise.all([
          getSlackBots().catch(() => []),
          listUserAgents().catch(() => []),
        ]);
        setBots(b);
        setAgents(a);
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
    return <div className="aug-fs-sm" style={{ padding: 24, color: "var(--t3)" }}>Loading…</div>;
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "18px 22px", maxWidth: 980 }}>
      <div className="aug-fs-sm" style={{ color: "var(--t2)", marginBottom: 14, maxWidth: 680 }}>
        Connect the org's accounts by OAuth. Aughor holds every token itself — encrypted at
        rest, refreshed before expiry, never shown to a model or a screen — and each grant
        is a governed record with an owner, scopes and a revoke.
      </div>

      {error && (
        <div className="aug-fs-sm" role="alert" style={{ padding: "8px 12px", marginBottom: 12,
          borderRadius: "var(--r2)", background: "var(--red1)",
          border: "1px solid var(--red2)", color: "var(--red5)" }}>{error}</div>
      )}
      {notice && (
        <div className="aug-fs-sm" style={{ padding: "8px 12px", marginBottom: 12,
          borderRadius: "var(--r2)", background: "var(--amb1)",
          border: "1px solid var(--amb2)", color: "var(--amb5)" }}>{notice}</div>
      )}

      {categories.map(([category, rows]) => (
        <div key={category} style={{ marginBottom: 18 }}>
          <div className="aug-fs-xs" style={{ color: "var(--t4)", letterSpacing: "0.06em",
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
                  <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 6,
                    lineHeight: 1.5 }}>
                    {p.name}&apos;s OAuth needs an HTTPS callback and this deployment is
                    reached at <code>{redirectUri}</code>. A Slack <strong>app</strong>
                    {" "}needs none — it opens an outbound socket — so it works on a
                    laptop with no tunnel. {bots.length > 0 && (
                      <>Connected: {bots.map(b => b.name).join(", ")}.</>
                    )}
                  </div>
                )}

                {/* The supervisor's key, offered where its bots are — and only once
                    there is a bot, because a key for a supervisor with nothing to
                    supervise is a control asking to be ignored. It exists so the fix
                    for "the API refused to serve bot credentials" is a button here
                    rather than a shell export and a restart. */}
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
                          process. Regenerating replaces it and the old one stops working.
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
                        <div className="aug-fs-xs" style={{ color: "var(--t4)",
                          marginBottom: 4 }}>
                          Answer as (optional) — an app with no agent can still post; it
                          just cannot answer an @mention as anybody.
                        </div>
                        <select className="aug-fs-ui" style={inputStyle} value={doorAgent}
                          aria-label="Answer as agent"
                          onChange={e => setDoorAgent(e.target.value)}>
                          <option value="">No agent — posting only</option>
                          {agents.map(a => (
                            <option key={a.id} value={a.id}>{a.name}</option>
                          ))}
                        </select>
                      </div>
                    )}
                    <AgentSlackDoor
                      agentId={doorAgent}
                      agentName={agents.find(a => a.id === doorAgent)?.name || "Aughor"}
                      connectionId=""
                      heading="Add a Slack app"
                      intro={"No callback, no tunnel, no HTTPS: a Slack app opens an "
                        + "**outbound** socket to Slack, which is why it works from a "
                        + "laptop when OAuth cannot. Aughor renders the manifest; you "
                        + "create the app in Slack and paste three values back."}
                      skipLabel="Close"
                      onDone={() => { setDoorFor(null); setDoorAgent(""); void load(); }}
                    />
                  </div>
                )}
                {p.connection?.status === "active" && p.connection.scopes && (
                  // What the provider says was GRANTED — read back from the token
                  // response, so a scope the user declined is never listed.
                  <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 6,
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
                    <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>
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
                      <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>
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
                    <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>
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
