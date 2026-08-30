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
} from "@/lib/api";

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
  const [busy, setBusy] = useState("");
  /** Set after a revoke of a provider with no revocation endpoint — the one case where
   *  "revoked" is only half true and the reader must be told the other half. */
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const d = await getIntegrationsCatalog();
      setProviders(d.providers);
      setRedirectUri(d.redirect_uri);
      setError("");
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

  const saveApp = async (provider: string) => {
    setBusy(provider);
    setError("");
    try {
      await setupIntegrationApp(provider, {
        client_id: clientId.trim(), client_secret: clientSecret.trim(),
      });
      setClientId(""); setClientSecret(""); setSetupFor(null);
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
                    {p.configured && (
                      <Button variant="ghost" size="xs" disabled={busy === p.id}
                        title={`Replace the ${p.name} OAuth client`}
                        onClick={() => { setSetupFor(cur => cur === p.id ? null : p.id);
                                         setClientId(""); setClientSecret(""); }}>
                        Edit
                      </Button>
                    )}
                    {!p.configured ? (
                      <Button variant="secondary" size="xs" disabled={busy === p.id}
                        onClick={() => { setSetupFor(cur => cur === p.id ? null : p.id);
                                         setClientId(""); setClientSecret(""); }}>
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
                  </span>
                </div>
                <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 4 }}>
                  {p.blurb}
                </div>
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
                    <code className="aug-fs-xs" style={{ padding: "5px 8px",
                      background: "var(--bg-2)", borderRadius: "var(--r2)",
                      border: "1px solid var(--b1)", overflowWrap: "anywhere" }}>
                      {redirectUri}
                    </code>
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
                    <input className="aug-fs-ui" style={inputStyle} placeholder="Client secret"
                      value={clientSecret} autoComplete="off" spellCheck={false}
                      onChange={e => setClientSecret(e.target.value)} />
                    <div style={{ display: "flex", gap: 6 }}>
                      <Button variant="default" size="xs"
                        disabled={!clientId.trim() || !clientSecret.trim() || busy === p.id}
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
    </div>
  );
}
