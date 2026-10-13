"use client";
/**
 * Integrations — redone to `aughor-v2/CLARITY.md` (2026-10-13): figures (connected, not connected, Slack bots, the
 * supervisor), then what needs a person — a provider set up with nothing connected, a grant to renew, a bot whose
 * @mentions are refused, a supervisor that stopped — then the providers as rows with their buttons, the Slack bots and
 * their supervisor, and the MCP servers. The set-up form, Slack's app door and a bot's edit form open only on their
 * buttons; the redirect URI, the client id and the granted permissions sit behind a provider's Details.
 *
 * Why two buttons (VA-11): a provider needs the ORG's OAuth client before any USER can grant anything, and those are
 * different people doing different jobs. Set up stores the client (with the redirect URI the provider console will
 * demand); Connect sends the browser to the provider's own consent screen — the one place the user's password belongs,
 * and a place this code never sees.
 *
 * What never appears here: a token. The API drops token fields server-side, so this component could not render one if
 * it tried. A client secret comes back masked and is only ever overwritten, never shown.
 */
import { DropdownMenu } from "@radix-ui/themes";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { ErrorState, Loading } from "@/components/ui/states";
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
import { formatCount, formatDateTime, relTime } from "@/lib/format";
import { dayMonth } from "@/lib/monitorSummary";
import { bindingProblem, patchBodyFor, type SlackBotChanges } from "@/lib/slackBots";
import {
  Card, Chip, Dot, Empty, Figure, Figures, MUTED, NeedsRow, NeedsYou, ONE_LINE, Page, ROW, RULE, type Tone,
} from "@/components/clarity/kit";

import { AgentSlackDoor } from "@/components/agentops/AgentSlackDoor";
import { McpServersSection } from "@/components/McpServersSection";

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "7px 10px", borderRadius: "var(--r3)",
  border: "1px solid var(--b1)", background: "var(--bg-1)", color: "var(--t1)",
};

type Hue = "green" | "amber" | "red" | "grey";

const s = (n: number) => (n === 1 ? "" : "s");

/** A provider reached through Slack's app + Socket Mode, because its OAuth cannot complete on this deployment. */
const viaApp = (p: IntegrationProvider) => !p.oauth_ready && p.alt_door === "slack_app";

/** Where a provider stands, as a dot, a chip and whether anything of it is connected. */
export function providerState(p: IntegrationProvider, bots: SlackBotSummary[]): {
  connected: boolean; chip: string; tone: Tone; hue: Hue;
} {
  const products = p.products ?? [];
  const on = products.filter(pr => pr.connected).length;
  if (viaApp(p)) {
    const listening = bots.filter(b => b.enabled && b.listening).length;
    if (!bots.length) return { connected: false, chip: "no app added", tone: "plain", hue: "grey" };
    return listening
      ? { connected: true, chip: "connected by its app", tone: "up", hue: "green" }
      : { connected: true, chip: "by its app · not listening", tone: "amber", hue: "amber" };
  }
  const conn = p.connection;
  if (conn?.status === "needs_reconnect") return { connected: false, chip: "needs reconnecting", tone: "amber", hue: "amber" };
  if (conn?.status === "active" && (!products.length || on > 0)) {
    return { connected: true, chip: products.length ? `${on} of ${products.length} connected` : "connected", tone: "up", hue: "green" };
  }
  if (p.configured) {
    return { connected: false, chip: products.length ? `set up · 0 of ${products.length} connected` : "set up · not connected",
      tone: "plain", hue: "grey" };
  }
  return { connected: false, chip: "not set up", tone: "plain", hue: "grey" };
}

const SUPERVISOR_WORD: Record<ManagedSupervisorStatus["state"], string> = {
  running: "Running", off: "Run by hand", starting: "Starting", restarting: "Restarting", stopped: "Stopped", failed: "Failed",
};

/** One fact in a Details block: a muted name and its value. */
function Fact({ name, children, mono }: { name: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <>
      <span className="aug-fs-xs" style={MUTED}>{name}</span>
      <span className="aug-fs-xs" style={{ color: "var(--t2)", minWidth: 0, overflowWrap: "anywhere",
        fontFamily: mono ? "var(--font-mono)" : undefined }}>{children}</span>
    </>
  );
}

const FACTS: React.CSSProperties = {
  display: "grid", gridTemplateColumns: "minmax(110px, 150px) minmax(0, 1fr)", gap: "4px 12px", padding: "8px 0 4px 22px",
};

/** Connect one of a provider's products, chosen from a menu — the button a "Needs you" row carries. */
function ConnectMenu({ p, label, busy, onConnect }: {
  p: IntegrationProvider; label: string; busy: boolean; onConnect: (provider: string, product: string) => void;
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        <Button variant="secondary" size="xs" disabled={busy}>{label} <Icon name="chevd" size={12} /></Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content size="1" align="end">
        {(p.products ?? []).filter(pr => !pr.connected).map(pr => (
          <DropdownMenu.Item key={pr.id} onSelect={() => onConnect(p.id, pr.id)}>{pr.name}</DropdownMenu.Item>
        ))}
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  );
}

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
  /** The provider just revoked that has no revocation endpoint — the one case where
   *  "revoked" is only half true and the reader must be told the other half. */
  const [notice, setNotice] = useState("");
  /** The provider whose alternative door is open — Slack's app flow, today. */
  const [doorFor, setDoorFor] = useState<string | null>(null);
  /** The rows whose Details are open: a provider's id, or "supervisor". */
  const [details, setDetails] = useState<ReadonlySet<string>>(new Set());
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
   *  on screen. It is returned once — the panel holds it only until the page closes. */
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
  // tab still shows the old state. Refetch when the user comes back to it, so the row
  // flips to "connected" without anyone hunting for a refresh control.
  useEffect(() => {
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load]);

  const toggleDetails = (id: string) => setDetails(prev => {
    const n = new Set(prev);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

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

  const openBotEdit = (b: SlackBotSummary) => {
    setEditBot(cur => (cur === b.id ? null : b.id));
    setBotDraft({ name: b.name, agent_id: b.agent_id, connection_id: b.connection_id, channel_id: b.channel_id ?? "",
      rehearse: b.rehearse ?? false });
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

  const connect = async (provider: string, product?: string) => {
    // A NEW tab, so this one survives to refetch on refocus. It opens inside the click,
    // before anything is awaited — a tab opened after an await is a pop-up the browser may
    // block — and is pointed at the consent screen once the API has the URL. It used to be
    // `window.open(url, "_blank", "noopener")`, which returns null by spec even when the tab
    // opens, so the blocked-pop-up fallback ALWAYS ran too: the consent screen in a new
    // window AND in this tab (2026-10-07). Only a tab that truly did not open falls back.
    const tab = window.open("about:blank", "_blank");
    setBusy(product ? `${provider}:${product}` : provider);
    setError("");
    try {
      const url = await beginIntegrationConnect(provider, product);
      if (tab && !tab.closed) {
        tab.opener = null;
        tab.location.href = url;
      } else {
        window.location.href = url;
      }
    } catch (e) {
      tab?.close();
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
      if (!r.provider_side) setNotice(p.name);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const restartSupervisor = async () => {
    setBusy("supervisor"); setError("");
    try { setSupervisor(await restartManagedSupervisor()); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  };

  const generateKey = async () => {
    setBusy("key"); setError("");
    try {
      const k = await issueSupervisorKey();
      setFreshKey(k.env_line);
      setGraceUntil(k.previous_valid_until || "");
      setKeyIssued(true);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  };

  const connName = (id: string) => connections.find(c => c.id === id)?.name || id;

  const slack = providers.find(p => p.alt_door === "slack_app");
  const states = useMemo(() => new Map(providers.map(p => [p.id, providerState(p, bots)])), [providers, bots]);
  const connected = providers.filter(p => states.get(p.id)?.connected);
  const enabledBots = bots.filter(b => b.enabled);
  const listening = enabledBots.filter(b => b.listening).length;
  const supervisorShown = !!slack && !!supervisor && (bots.length > 0 || supervisor.managed);
  const heartbeat = supervisor?.heartbeat ?? null;
  const supervisorDown = !!supervisor && supervisor.managed && (supervisor.state === "failed" || supervisor.state === "stopped");
  const supervisorDeaf = !!supervisor && supervisor.state === "running" && !!heartbeat && !heartbeat.fresh;

  if (!loaded) {
    return <Loading what="integrations" style={{ padding: 24 }} />;
  }

  // ── What needs a person ─────────────────────────────────────────────────────
  const needs: React.ReactNode[] = [];
  if (notice) {
    needs.push(
      <NeedsRow key="notice" testId="needs-revoke-notice" title={`Remove the ${notice} grant on the account's own security page too`}
        detail={`${notice} offers no revocation endpoint — the grant is cleared here only`}
        actions={<Button variant="ghost" size="xs" onClick={() => setNotice("")}>Dismiss</Button>} />,
    );
  }
  for (const p of providers) {
    if (viaApp(p)) continue;
    const products = p.products ?? [];
    const conn = p.connection;
    if (conn?.status === "needs_reconnect") {
      needs.push(
        <NeedsRow key={`reconnect-${p.id}`} testId="needs-reconnect" title={`${p.name} needs reconnecting`}
          detail="Its grant expired or was withdrawn — nothing reaches it until it is renewed"
          actions={products.length
            ? <ConnectMenu p={p} label="Reconnect" busy={busy !== ""} onConnect={(pv, pr) => void connect(pv, pr)} />
            : <Button variant="secondary" size="xs" disabled={busy === p.id} onClick={() => void connect(p.id)}>Reconnect</Button>} />,
      );
    } else if (p.configured && conn?.status !== "active" && !products.some(pr => pr.connected)) {
      needs.push(
        <NeedsRow key={`half-${p.id}`} testId="needs-half-set-up" title={`${p.name} is set up, but nothing is connected`}
          detail={products.length ? `${products.length} products ready to connect` : "Its app is registered — connect an account to use it"}
          actions={products.length
            ? <ConnectMenu p={p} label="Connect" busy={busy !== ""} onConnect={(pv, pr) => void connect(pv, pr)} />
            : <Button variant="secondary" size="xs" disabled={busy === p.id} onClick={() => void connect(p.id)}>Connect</Button>} />,
      );
    }
  }
  if (slack && supervisorShown && supervisor) {
    if (supervisorDown) {
      needs.push(
        <NeedsRow key="supervisor-down" testId="needs-supervisor" title="The Slack supervisor stopped — no bot is answering"
          detail={supervisor.last_error || supervisor.preconditions.join("; ") || "no reason recorded"}
          actions={<Button variant="secondary" size="xs" disabled={busy === "supervisor"} onClick={() => void restartSupervisor()}>Restart</Button>} />,
      );
    } else if (supervisorDeaf && heartbeat) {
      needs.push(
        <NeedsRow key="supervisor-deaf" testId="needs-supervisor" title="The Slack supervisor is not listening"
          detail={`Last heard ${relTime(heartbeat.last_seen_at)} ago`}
          actions={supervisor.managed
            ? <Button variant="secondary" size="xs" disabled={busy === "supervisor"} onClick={() => void restartSupervisor()}>Restart</Button>
            : null} />,
      );
    }
  }
  if (slack) {
    for (const b of bots) {
      const problem = bindingProblem(b, agents, connName);
      if (problem) {
        needs.push(
          <NeedsRow key={`problem-${b.id}`} testId="needs-bot" title={`${b.name}: @mentions are refused`} detail={problem}
            actions={<Button variant="secondary" size="xs" onClick={() => openBotEdit(b)}>Edit</Button>} />,
        );
      }
      // A stopped supervisor is said once, above — not again for every bot it leaves deaf.
      if (b.enabled && !b.listening && !supervisorDown && !supervisorDeaf) {
        needs.push(
          <NeedsRow key={`deaf-${b.id}`} testId="needs-bot" title={`${b.name} is not listening`}
            detail={b.liveness_hint || "Start the supervisor"}
            actions={supervisor?.managed
              ? <Button variant="secondary" size="xs" disabled={busy === "supervisor"} onClick={() => void restartSupervisor()}>Restart supervisor</Button>
              : null} />,
        );
      }
      if (!b.enabled && b.disabled_reason) {
        needs.push(
          <NeedsRow key={`off-${b.id}`} testId="needs-bot" title={`${b.name} was switched off`} detail={b.disabled_reason}
            actions={<Button variant="secondary" size="xs" disabled={busy === b.id} onClick={() => void saveBot(b, { enabled: true })}>Resume</Button>} />,
        );
      }
    }
    if (supervisor && !supervisor.managed && enabledBots.length > 0 && !keyIssued) {
      needs.push(
        <NeedsRow key="no-key" testId="needs-key" title="No supervisor key"
          detail="A supervisor run by hand needs one to open the bots' sockets"
          actions={<Button variant="secondary" size="xs" disabled={busy === "key"} onClick={() => void generateKey()}>Generate key</Button>} />,
      );
    }
  }

  // ── A provider, one row ─────────────────────────────────────────────────────
  const providerRow = (p: IntegrationProvider, i: number) => {
    const st = states.get(p.id) ?? providerState(p, bots);
    const app = viaApp(p);
    const conn = p.connection;
    const products = p.products ?? [];
    const scopes = (conn?.scopes || "").split(/[\s,]+/).filter(Boolean);
    const open = details.has(p.id);
    // A few facts, never the whole record: who and since when once connected; what it is for until then. A provider
    // whose products are listed beneath it lets them say what it unlocks — its own blurb is on hover.
    const meta = conn?.status === "active"
      ? [conn.account, `since ${dayMonth(conn.created_at)}`,
         !products.length && scopes.length ? `${scopes.length} permission${s(scopes.length)} granted` : ""].filter(Boolean).join(" · ")
      : products.length ? "" : p.blurb;
    return (
      <div key={p.id} data-testid={`integration-card-${p.id}`} style={{ ...(i ? RULE : {}), padding: "9px 2px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "12px minmax(0, 1fr) auto", gap: 10, alignItems: "center" }}>
          <Dot hue={st.hue} title={st.chip} />
          <div style={{ minWidth: 0 }}>
            <div style={{ ...ROW, flexWrap: "nowrap", minWidth: 0 }}>
              <span className="aug-fs-chrome" title={p.blurb} style={{ fontWeight: 600, color: "var(--t1)" }}>{p.name}</span>
              <Chip tone={st.tone}>{st.chip}</Chip>
              {/* Why this row's button differs from its neighbours' — "Add Slack app" beside Google's "Connect" is
                  otherwise an inconsistency a reader has to explain to themselves. */}
              {app && (
                <Chip title={`${p.name}'s OAuth needs an HTTPS callback, and this deployment is reached at ${redirectUri}. `
                  + "A Slack app needs none — it opens an outbound socket — so it works on a laptop with no tunnel."}>
                  OAuth needs HTTPS
                </Chip>
              )}
            </div>
            {meta && <div className="aug-fs-xs" title={meta} style={{ ...MUTED, ...ONE_LINE }}>{meta}</div>}
          </div>
          <div style={{ ...ROW, flexWrap: "nowrap", gap: 4 }}>
            {/* A provider whose OAuth cannot complete HERE routes to the door that can. Slack refuses `http://`, a
                laptop has nothing else, and its app + Socket Mode path needs no callback at all. OAuth comes back on
                its own the moment the callback is https (a tunnel, or a real deployment). */}
            {app ? (
              <Button variant="default" size="xs" aria-expanded={doorFor === p.id}
                onClick={() => setDoorFor(cur => cur === p.id ? null : p.id)}>
                {doorFor === p.id ? "Close" : "Add Slack app"}
              </Button>
            ) : (<>
              {/* Set up is never a one-way door: a stored client can be replaced (a typo, a rotated secret, another
                  app). The credentials are never READ back — the form replaces them. */}
              {p.configured ? (
                <Button variant="ghost" size="xs" disabled={busy === p.id} title={`Replace the ${p.name} OAuth client`}
                  aria-expanded={setupFor === p.id} onClick={() => openSetup(p)}>
                  {setupFor === p.id ? "Close" : "Edit app"}
                </Button>
              ) : (
                <Button variant="secondary" size="xs" disabled={busy === p.id} aria-expanded={setupFor === p.id}
                  onClick={() => openSetup(p)}>
                  {setupFor === p.id ? "Close" : "Set up"}
                </Button>
              )}
              {conn?.status === "active" ? (
                // A product is a scope on ONE grant, and Google revokes a grant whole — so disconnecting is the
                // provider's, and says that it is every product.
                <Button variant="ghost" size="xs" disabled={busy === p.id}
                  title={products.length ? `${p.name} removes Aughor's access to every ${p.name} product at once` : undefined}
                  onClick={() => revoke(p)}>{products.length ? "Disconnect all" : "Revoke"}</Button>
              ) : p.configured && !products.length ? (
                <Button variant="default" size="xs" disabled={busy === p.id} onClick={() => connect(p.id)}>
                  {conn?.status === "needs_reconnect" ? "Reconnect" : "Connect"}
                </Button>
              ) : null}
            </>)}
            <Button variant="ghost" size="xs" aria-expanded={open} onClick={() => toggleDetails(p.id)}>
              Details <Icon name={open ? "chevu" : "chevd"} size={12} />
            </Button>
          </div>
        </div>

        {/* Each product of a provider's one app is its own row (Google, 2026-10-07): Connect opens the provider's
            consent for that product alone, and the grant grows a product at a time. */}
        {products.length > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: "4px 14px",
            padding: "6px 0 0 22px" }}>
            {products.map(pr => {
              const granted = (conn?.scopes || "").split(/[\s,]+/);
              const stale = conn?.status === "needs_reconnect" && pr.scopes.split(" ").every(sc => granted.includes(sc));
              const key = `${p.id}:${pr.id}`;
              const tools = pr.tools.map(t => t.split(" · ").pop()).join(" · ");
              // What the product does and the tools it brings are on hover; the name says the rest.
              const about = [pr.blurb, pr.connected ? conn?.account : "", tools ? `tools: ${tools}` : ""].filter(Boolean).join(" · ");
              return (
                <div key={key} data-testid={`integration-product-${pr.id}`}
                  style={{ display: "grid", gridTemplateColumns: "12px minmax(0, 1fr) auto", gap: 8, alignItems: "center",
                    minHeight: 28 }}>
                  <Dot hue={pr.connected ? "green" : stale ? "amber" : "grey"}
                    title={pr.connected ? "connected" : stale ? "needs reconnecting" : "not connected"} />
                  <span className="aug-fs-sm" title={about} style={{ ...ONE_LINE, color: "var(--t1)" }}>{pr.name}</span>
                  {pr.connected ? <Chip tone="up">connected</Chip> : (
                    <Button variant="outline" size="xs" disabled={!p.configured || busy === key}
                      title={p.configured ? undefined : `Set up the ${p.name} app first — one app serves every ${p.name} product`}
                      onClick={() => void connect(p.id, pr.id)}>
                      {busy === key ? "…" : stale ? "Reconnect" : "Connect"}
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {open && (
          <div data-testid={`integration-details-${p.id}`} style={FACTS}>
            <Fact name="Redirect URI" mono>
              {p.redirect_uri || redirectUri}{p.redirect_uri ? " (set by hand)" : ""}
            </Fact>
            <Fact name="Client ID" mono>{p.client_id || "none stored"}</Fact>
            <Fact name="Client secret">{p.secret_preview ? "stored, encrypted — never shown" : "none stored"}</Fact>
            {p.https_only && <Fact name="Callback">{`${p.name} refuses an http:// redirect, localhost included`}</Fact>}
            {app && <Fact name="Why an app">{`${p.name}'s OAuth needs HTTPS here; its app opens an outbound socket instead`}</Fact>}
            {conn && <Fact name="Account">{`${conn.account || "—"} · ${conn.status === "active" ? "connected" : conn.status === "needs_reconnect" ? "needs reconnecting" : "revoked"} since ${formatDateTime(conn.created_at)}`}</Fact>}
            {scopes.length > 0 && <Fact name="Granted" mono>{scopes.join(" ")}</Fact>}
            {products.some(pr => pr.tools.length) && (
              <Fact name="Tools">
                {products.filter(pr => pr.tools.length).map(pr => `${pr.name}: ${pr.tools.map(t => t.split(" · ").pop()).join(", ")}`).join(" · ")}
              </Fact>
            )}
            <Fact name="Group">{p.category}</Fact>
            {p.console_url && (
              <Fact name="Console">
                <a href={p.console_url} target="_blank" rel="noreferrer" style={{ color: "var(--blue4)" }}>{`the ${p.name} console`}</a>
              </Fact>
            )}
          </div>
        )}

        {doorFor === p.id && (
          <div style={{ marginTop: 10, ...RULE, paddingTop: 12, paddingLeft: 22 }}>
            {agents.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <div className="aug-fs-xs" style={{ ...MUTED, marginBottom: 4 }}>
                  Answers as (optional) — without an agent the app can post, but not answer an @mention
                </div>
                <SelectField style={inputStyle} value={doorAgent}
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
              <div className="aug-fs-xs" style={{ ...MUTED, marginBottom: 4 }}>
                Asks on — the connection @mentions run against; an agent bound to one must use it, or answers are refused
              </div>
              <SelectField style={inputStyle} value={doorConnection}
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
              intro={"No callback, no tunnel, no HTTPS: a Slack app opens an **outbound** socket to Slack, which is why "
                + "it works from a laptop when OAuth cannot. Aughor renders the manifest; you create the app in Slack "
                + "and paste three values back."}
              skipLabel="Close"
              onDone={() => {
                setDoorFor(null); setDoorAgent(""); setDoorConnection("");
                void load();
              }}
            />
          </div>
        )}

        {setupFor === p.id && (
          <div data-testid={`integration-setup-${p.id}`} style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8,
            ...RULE, paddingTop: 10, paddingLeft: 22 }}>
            <div className="aug-fs-xs" style={MUTED}>
              {p.configured && "Replace the stored client — the current secret is never shown, only overwritten. "}
              {p.configured ? "Create or pick an OAuth client in " : "Create an OAuth client in "}
              <a href={p.console_url} target="_blank" rel="noreferrer" style={{ color: "var(--blue4)" }}>the {p.name} console</a>
              {" "}with this redirect URI, then paste its credentials back.
            </div>
            {/* Editable, and labelled: the redirect URI is the address the provider sends the browser BACK to — asked
                for "the redirect URI" beside a console link, a reasonable person pastes the provider's address.
                Saving it unchanged stores no override at all. */}
            <div className="aug-fs-xs" style={MUTED}>
              Redirect URI — where {p.name} sends the browser <strong>back to Aughor</strong>; it must reach this API
              {p.https_only ? " over HTTPS (a tunnel is enough)" : ""} and match the console exactly.
            </div>
            <Input style={inputStyle}
              value={callback} spellCheck={false} autoComplete="off"
              aria-label="Redirect URI"
              placeholder={redirectUri}
              onChange={e => setCallback(e.target.value)} />
            {callback.trim() && callback.trim() !== redirectUri.trim() && (
              <div className="aug-fs-xs" style={MUTED}>
                Overrides the derived address ({redirectUri}) — the provider is sent this one, and the exchange uses the
                same string.
              </div>
            )}
            {/* Said BEFORE the credentials are pasted, not after the provider's own error page. `https_only` is the
                provider's own documented rule, carried as adapter data rather than assumed here. */}
            {p.https_only && redirectUri.startsWith("http://") && (
              <div className="aug-fs-xs" style={{ color: "var(--amb4)" }}>
                {p.name} refuses an <code>http://</code> redirect URL, localhost included — registering the URI above will
                fail with “redirect_uri did not match”. Reach this API over HTTPS (a tunnel is enough), then register
                that address instead.
              </div>
            )}
            <Input style={inputStyle} placeholder="Client ID" aria-label="Client ID"
              value={clientId} autoComplete="off" spellCheck={false}
              onChange={e => setClientId(e.target.value)} />
            <Input style={inputStyle} aria-label="Client secret"
              placeholder={p.secret_preview
                ? `Client secret — blank keeps ${p.secret_preview}`
                : "Client secret"}
              value={clientSecret} autoComplete="off" spellCheck={false}
              onChange={e => setClientSecret(e.target.value)} />
            <div style={ROW}>
              <Button variant="default" size="xs"
                /* The secret is required only when there is not one already: blank MEANS "keep the stored one". */
                disabled={!clientId.trim() || busy === p.id
                          || (!clientSecret.trim() && !p.secret_preview)}
                onClick={() => saveApp(p.id)}>
                {busy === p.id ? "Saving…" : "Save"}
              </Button>
              <Button variant="ghost" size="xs" onClick={() => setSetupFor(null)}>
                Cancel
              </Button>
              <span className="aug-fs-xs" style={MUTED}>
                <Icon name="lock" size={11} /> Stored encrypted; the secret comes back masked and is never shown again.
              </span>
            </div>
          </div>
        )}
      </div>
    );
  };

  // ── A Slack bot, one row ────────────────────────────────────────────────────
  const botRow = (b: SlackBotSummary, i: number) => {
    const agent = agents.find(a => a.id === b.agent_id);
    const problem = bindingProblem(b, agents, connName);
    const editing = editBot === b.id;
    const meta = [
      `answers as ${agent ? agent.name : "nobody — posting only"}`,
      `asks on ${b.connection_id ? connName(b.connection_id) : "no connection"}`,
      b.channel_id ? `home channel ${b.channel_id}` : "",
    ].filter(Boolean).join(" · ");
    return (
      <div key={b.id} data-testid="slack-bot-row" style={{ ...(i ? RULE : {}), padding: "9px 2px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "12px minmax(0, 1fr) auto", gap: 10, alignItems: "center" }}>
          <Dot hue={!b.enabled ? "grey" : b.listening ? "green" : "amber"} />
          <div style={{ minWidth: 0 }}>
            <div style={{ ...ROW, flexWrap: "nowrap", minWidth: 0 }}>
              <span className="aug-fs-chrome" title={`Slack member ID ${b.bot_user_id || "unknown"}`}
                style={{ ...ONE_LINE, fontWeight: 600, color: "var(--t1)" }}>{b.name}</span>
              {/* AO-2a — "enabled" is the record; LISTENING is the socket. */}
              {!b.enabled ? (
                <Chip title={b.disabled_reason || undefined}>{b.disabled_reason ? "switched off" : "paused"}</Chip>
              ) : b.listening ? (
                <Chip tone="up" title={`listening since ${formatDateTime(b.listening.since)} · last heard ${formatDateTime(b.listening.last_seen_at)}`}>
                  {`listening since ${dayMonth(b.listening.since)}`}
                </Chip>
              ) : (
                <Chip tone="amber" title={b.liveness_hint || undefined}>not listening</Chip>
              )}
              {problem && <Chip tone="amber" title={problem}>@mentions refused</Chip>}
              {b.rehearse && (
                <Chip title="A mention is answered in the asker's DM first, and an automation's post as this bot waits for a person's click">
                  rehearses
                </Chip>
              )}
            </div>
            <div className="aug-fs-xs" title={meta} style={{ ...MUTED, ...ONE_LINE }}>{meta}</div>
          </div>
          <div style={{ ...ROW, flexWrap: "nowrap", gap: 4 }}>
            <Button variant="ghost" size="xs" disabled={busy === b.id} aria-expanded={editing} onClick={() => openBotEdit(b)}>
              {editing ? "Cancel" : "Edit"}
            </Button>
            <Button variant="ghost" size="xs" disabled={busy === b.id}
              title={b.enabled
                ? "The supervisor closes this bot's socket on its next reconcile"
                : "The supervisor re-opens this bot's socket on its next reconcile"}
              onClick={() => saveBot(b, { enabled: !b.enabled })}>
              {b.enabled ? "Pause" : "Resume"}
            </Button>
            <Button variant="ghost" size="xs" disabled={busy === b.id} aria-label={`Delete ${b.name}`} title="Delete"
              style={{ color: "var(--red4)" }} onClick={() => removeBot(b)}>
              <Icon name="trash" size={12} />
            </Button>
          </div>
        </div>
        {/* The records themselves — every field a person can change, changed here. Before this the page could only
            ADD a bot, and a bot bound to the wrong connection sat answering "did not answer (HTTP 409)" in Slack. */}
        {editing && (
          <div data-testid="slack-bot-edit" style={{ marginTop: 8, paddingLeft: 22, display: "flex", flexDirection: "column", gap: 6 }}>
            <Input style={inputStyle} value={botDraft.name}
              aria-label="Bot name"
              onChange={e => setBotDraft(d => ({ ...d, name: e.target.value }))} />
            <SelectField style={inputStyle}
              value={botDraft.agent_id} aria-label="Answers as agent"
              onChange={e => {
                const chosen = agents.find(a => a.id === e.target.value);
                setBotDraft(d => ({ ...d, agent_id: e.target.value,
                  // A bound agent brings its connection along — the pairing the ask door will insist on anyway.
                  connection_id: chosen?.connection_id || d.connection_id }));
              }}>
              <option value="">No agent — posting only</option>
              {agents.map(a => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </SelectField>
            <SelectField style={inputStyle}
              value={botDraft.connection_id} aria-label="Asks on connection"
              onChange={e => setBotDraft(d => ({ ...d, connection_id: e.target.value }))}>
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
            <Input style={inputStyle} value={botDraft.channel_id}
              aria-label="Home channel" placeholder="Home channel — #name or C… (optional)"
              onChange={e => setBotDraft(d => ({ ...d, channel_id: e.target.value }))} />
            {/* AO-6 — rehearse: a post from an automation AS this bot waits in Attention for a person's click before it
                reaches the channel, and a channel mention is answered in the asker's DM first. */}
            <label className="aug-fs-xs" style={{ display: "inline-flex", alignItems: "center",
              gap: 6, color: "var(--t2)", cursor: "pointer" }}>
              <Checkbox checked={botDraft.rehearse}
                onChange={e => setBotDraft(d => ({ ...d, rehearse: e.target.checked }))} />
              Rehearse — a mention is answered in the asker&apos;s DM first (their ✅ posts it in the thread), and an
              automation&apos;s post as this bot waits for a person&apos;s click
            </label>
            <div style={ROW}>
              <Button variant="default" size="xs" disabled={busy === b.id}
                onClick={() => saveBot(b, botDraft)}>
                Save
              </Button>
              <span className="aug-fs-xs" style={MUTED}>
                A new agent or connection re-opens the socket within 30 seconds; a rename does not.
                {` Slack member ID ${b.bot_user_id || "unknown"}.`}
              </span>
            </div>
          </div>
        )}
      </div>
    );
  };

  /** The supervisor's key: only for a supervisor run by hand, so with one the API runs it is a fact behind the
   *  supervisor's Details; otherwise a row of its own. Offered only once there is a bot — a key for a supervisor with
   *  nothing to supervise is a control asking to be ignored. It exists so "the API refused to serve bot credentials"
   *  is a button here rather than a shell export and a restart. */
  const keyRow = (standalone: boolean) => (
    <div data-testid="supervisor-key" style={standalone ? { ...RULE, padding: "9px 2px" } : undefined}>
      <div style={{ display: "grid", gridTemplateColumns: standalone ? "12px minmax(0, 1fr) auto" : "minmax(0, 1fr) auto",
        gap: 10, alignItems: "center" }}>
        {standalone && <Dot hue={keyIssued ? "green" : "grey"} />}
        <div style={{ minWidth: 0 }}>
          <div style={{ ...ROW, flexWrap: "nowrap" }}>
            <span className={standalone ? "aug-fs-chrome" : "aug-fs-xs"}
              style={standalone ? { fontWeight: 600, color: "var(--t1)" } : { color: "var(--t2)" }}>Supervisor key</span>
            <Chip tone={keyIssued ? "up" : "plain"}>{keyIssued ? "set" : "not set"}</Chip>
          </div>
          <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }}>Only for running it by hand; posting never uses it</div>
        </div>
        <Button variant="secondary" size="xs" disabled={busy === "key"} onClick={() => void generateKey()}>
          {keyIssued ? "Regenerate" : "Generate"}
        </Button>
      </div>
      {freshKey && (
        <div style={{ marginTop: 8, paddingLeft: standalone ? 22 : 0, display: "flex", flexDirection: "column", gap: 6 }}>
          {/* Shown ONCE. Re-reading returns a status, never the value, so this line is the only chance to copy it. */}
          <code className="aug-fs-xs" style={{ padding: "6px 8px", background: "var(--bg-3)", borderRadius: "var(--r2)",
            overflowWrap: "anywhere" }}>
            {freshKey}
          </code>
          <div className="aug-fs-xs" style={{ color: "var(--amb4)" }}>
            Copy this now — it is shown once. Paste it into the bot supervisor&apos;s <code>.env.local</code>, then
            restart that process.{" "}
            {graceUntil
              ? `The key it replaces keeps working until ${formatDateTime(graceUntil)}, so the running supervisor stays up until you restart it.`
              : "Regenerating later replaces it; the replaced key keeps working for a few minutes so the running supervisor can be restarted."}
          </div>
        </div>
      )}
    </div>
  );

  // ── The supervisor that keeps the bots' sockets open, and its key ───────────
  const supervisorRows = () => {
    if (!supervisor) return null;
    const st = supervisor.state;
    const open = details.has("supervisor");
    const hue: Hue = st === "running" ? (heartbeat && !heartbeat.fresh ? "amber" : heartbeat ? "green" : "grey")
      : st === "failed" || st === "stopped" ? "red" : "grey";
    const tone: Tone = hue === "green" ? "up" : hue === "red" ? "down" : hue === "amber" ? "amber" : "plain";
    // Only what the Supervisor figure above does not already say: its state and when it was last heard are there.
    const meta = [
      st === "running" && !heartbeat ? "no heartbeat yet" : "",
      st === "running" && heartbeat && !heartbeat.fresh ? `not heard since ${formatDateTime(heartbeat.last_seen_at)}` : "",
      st === "off" ? "started outside the app — how, in Details" : "",
      st === "failed" || st === "stopped" ? (supervisor.last_error || "no reason recorded") : "",
      supervisor.restarts ? `restarted ${supervisor.restarts}×` : "",
    ].filter(Boolean).join(" · ");
    return (
      <>
        <div data-testid="slack-supervisor" style={{ ...(bots.length ? RULE : {}), padding: "9px 2px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "12px minmax(0, 1fr) auto", gap: 10, alignItems: "center" }}>
            <Dot hue={hue} />
            <div style={{ minWidth: 0 }}>
              <div style={{ ...ROW, flexWrap: "nowrap" }}>
                <span className="aug-fs-chrome" style={{ fontWeight: 600, color: "var(--t1)" }}
                  title="The process that keeps each bot's Slack socket open, so @mentions are answered">Supervisor</span>
                <Chip tone={tone}>{SUPERVISOR_WORD[st].toLowerCase()}</Chip>
              </div>
              {meta && <div className="aug-fs-xs" title={meta} style={{ ...MUTED, ...ONE_LINE }}>{meta}</div>}
            </div>
            <div style={{ ...ROW, flexWrap: "nowrap", gap: 4 }}>
              {supervisor.managed && (
                <Button variant="ghost" size="xs" disabled={busy === "supervisor"} onClick={() => void restartSupervisor()}>
                  Restart
                </Button>
              )}
              <Button variant="ghost" size="xs" aria-expanded={open} onClick={() => toggleDetails("supervisor")}>
                Details <Icon name={open ? "chevu" : "chevd"} size={12} />
              </Button>
            </div>
          </div>
          {open && (
            <div data-testid="supervisor-details" style={FACTS}>
              <Fact name="Run by">{supervisor.managed ? "the API" : "hand"}</Fact>
              {st === "off" && (
                <Fact name="Start it" mono>cd bots/slack &amp;&amp; npm run dev — or turn on slack.managed_supervisor to let the API run it</Fact>
              )}
              {supervisor.pid != null && <Fact name="Process" mono>{`pid ${supervisor.pid}`}</Fact>}
              {supervisor.started_at && <Fact name="Since">{formatDateTime(supervisor.started_at)}</Fact>}
              <Fact name="Restarts">{formatCount(supervisor.restarts)}</Fact>
              {heartbeat && (
                <Fact name="Last heartbeat">
                  {`${formatDateTime(heartbeat.last_seen_at)} · ${heartbeat.running} open · ${heartbeat.failed} failed`}
                </Fact>
              )}
              {supervisor.last_exit_code != null && <Fact name="Last exit">{`code ${supervisor.last_exit_code}`}</Fact>}
              {supervisor.last_error && <Fact name="Last error">{supervisor.last_error}</Fact>}
              {supervisor.preconditions.length > 0 && <Fact name="Missing">{supervisor.preconditions.join("; ")}</Fact>}
              {supervisor.log_path && <Fact name="Its log" mono>{supervisor.log_path}</Fact>}
              {supervisor.managed && bots.length > 0 && (
                <div style={{ gridColumn: "1 / -1", paddingTop: 4 }}>{keyRow(false)}</div>
              )}
            </div>
          )}
        </div>
      </>
    );
  };

  return (
    <Page testId="integrations">
      {error && <ErrorState kind="Integration failed" what={error} />}

      <Figures testId="integration-figures">
        <Figure label="Connected" testId="fig-connected"
          value={`${formatCount(connected.length)} of ${formatCount(providers.length)}`}
          sub={connected.length ? connected.map(p => viaApp(p) ? `${p.name}, by its app` : p.name).join(" · ") : "nothing yet"} />
        {slack && (
          <Figure label="Slack bots" testId="fig-bots" value={formatCount(bots.length)}
            tone={enabledBots.length > listening ? "amber" : undefined}
            sub={!bots.length ? "none added"
              : `${listening === enabledBots.length ? `${listening}` : `${listening} of ${enabledBots.length}`} listening`
                + (bots.length > enabledBots.length ? ` · ${bots.length - enabledBots.length} paused` : "")} />
        )}
        {slack && supervisorShown && supervisor && (
          <Figure label="Supervisor" testId="fig-supervisor" value={SUPERVISOR_WORD[supervisor.state]}
            tone={supervisorDown || supervisorDeaf ? "amber" : undefined}
            sub={supervisor.state === "running"
              ? (heartbeat ? (heartbeat.fresh ? `heard ${relTime(heartbeat.last_seen_at)} ago` : `not heard since ${dayMonth(heartbeat.last_seen_at)}`)
                : "no heartbeat yet") + (supervisor.managed ? " · run by the API" : "")
              : supervisor.state === "off" ? "started outside the app"
              : supervisor.last_error ? supervisor.last_error.slice(0, 60) : "no reason recorded"} />
        )}
      </Figures>

      <NeedsYou testId="integration-needs" empty="Nothing needs you">{needs}</NeedsYou>

      <Card label="Providers" testId="integration-providers"
        right={<Chip title="Aughor holds every token itself — encrypted at rest, refreshed before expiry, never shown to a model or a screen; each grant has an owner, scopes and a revoke.">
          tokens held encrypted · never shown
        </Chip>}>
        {providers.length === 0 ? <Empty>No provider is offered on this deployment.</Empty> : providers.map(providerRow)}
      </Card>

      {slack && (
        <Card label="Slack bots" testId="slack-bots">
          {bots.length === 0 && <Empty>A bot is added with Add Slack app, on the Slack row above.</Empty>}
          {bots.map(botRow)}
          {supervisorShown && supervisorRows()}
          {bots.length > 0 && !supervisor?.managed && keyRow(true)}
        </Card>
      )}

      {/* VA-9d — last on purpose: everything above is "connect as me", an account a user grants us; this is "call out to
          them", a third party an operator writes down. */}
      <McpServersSection />
    </Page>
  );
}
