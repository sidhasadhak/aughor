"use client";

/**
 * VA-14 · give an agent a Slack door, at the moment it is created.
 *
 * The last hop of "post the daily numbers into #aughor-canvas" was not code — it was that
 * creating a Slack bot required an API call. `POST /slack-bots` and the manifest renderer
 * shipped with RC-5 and no surface ever reached them, so the one step a person cannot
 * automate (making an app in someone else's product) was also the one step the product
 * gave them no help with.
 *
 * It belongs to agent creation because a bot IS an agent's door: `SlackBot.agent_id` binds
 * them, and a bot with no agent answers as nobody. Asking "how do people reach it?" right
 * after "how should it think?" is the same question continued.
 *
 * **The manifest is rendered by the SERVER.** Its scopes and socket-mode settings have to
 * match what the running bot actually does; a manifest this component assembled would
 * drift from the code the first time either changed. So this shows what
 * `GET /slack-bots/manifest` returns and never edits it.
 *
 * **The credentials go straight to the server, and are never stored here.** They are typed
 * into three fields, POSTed once, and the response carries them back masked. The server
 * verifies each against Slack BEFORE the record exists, so a rejection is Slack's own
 * answer rather than a guess — a bot saved with a bad token is a socket that fails to open
 * at 03:00 with nobody watching.
 */
import { useCallback, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  createSlackApp, createSlackBot, getSlackBotManifest, updateSlackBot,
  type SlackAppCreated, type SlackManifest,
} from "@/lib/api";
import { getApiBase } from "@/lib/config";
import { Input } from "@/components/ui/input";

/** Sizes come from the type scale via `aug-fs-*` classes on the elements, never as a
 *  literal here — a `fontSize` inside a style object is exactly what the design-token
 *  gate ratchets, and it is right to: a number here sits on no scale anyone can read. */
const inputStyle: React.CSSProperties = {
  width: "100%", padding: "7px 10px", borderRadius: "var(--r3)",
  border: "1px solid var(--b1)", background: "var(--bg-1)", color: "var(--t1)",
};

const labelStyle: React.CSSProperties = {
  fontWeight: 600, color: "var(--t3)", marginBottom: 4, display: "block",
  textTransform: "uppercase",
};

/**
 * `**bold**` → a real <strong>, because this app has no markdown renderer.
 *
 * The server writes its steps with emphasis on the words that are load-bearing — "paste
 * this on the **JSON** tab — not YAML" is the line that stops the failure the user
 * already hit once. Rendered raw, the asterisks print, and the emphasis becomes noise
 * exactly where it was most needed.
 */
function emphasise(line: string): React.ReactNode[] {
  // Split KEEPING the delimiters, so odd indices are the emphasised runs.
  return line.split(/\*\*(.+?)\*\*/g).map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : <span key={i}>{part}</span>);
}

export function AgentSlackDoor({
  agentId, agentName, connectionId, onDone,
  heading = "Give it a Slack door",
  intro,
  skipLabel = "Skip — the agent is already created",
}: {
  agentId: string;
  agentName: string;
  connectionId: string;
  /** Finished or skipped — either way the agent already exists, so this only closes. */
  onDone: () => void;
  /** The framing, so the same flow can be reached from somewhere that is not agent
   *  creation. It is the only Slack door a deployment without an HTTPS callback can
   *  open, so Integrations routes to it — and "Skip, the agent is already created"
   *  would be a sentence about a step that reader never took. `**bold**` works. */
  heading?: string;
  intro?: string;
  skipLabel?: string;
}) {
  const [appName, setAppName] = useState(agentName || "Aughor");
  // AO-2d — the one-token path: a configuration token creates the app from the manifest
  // Aughor renders; what remains is an install (a button on HTTPS, a paste elsewhere) and
  // the app-level token, which Slack offers no API for.
  const [configToken, setConfigToken] = useState("");
  const [creating, setCreating] = useState(false);
  const [app, setApp] = useState<SlackAppCreated | null>(null);
  const [pastedBotToken, setPastedBotToken] = useState("");
  const [pastedAppToken, setPastedAppToken] = useState("");
  const [finishing, setFinishing] = useState(false);
  const [finished, setFinished] = useState(false);
  const [byHand, setByHand] = useState(false);
  const [manifest, setManifest] = useState<SlackManifest | null>(null);
  const [rendering, setRendering] = useState(false);
  const [copied, setCopied] = useState(false);
  const [botToken, setBotToken] = useState("");
  const [appToken, setAppToken] = useState("");
  const [signingSecret, setSigningSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<string>("");

  const json = manifest ? JSON.stringify(manifest.manifest, null, 2) : "";

  const render = useCallback(async () => {
    setRendering(true);
    setError("");
    try {
      setManifest(await getSlackBotManifest({
        name: appName.trim() || "Aughor",
        description: `Aughor — ${agentName || "agent"}`,
        agentId,
      }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRendering(false);
    }
  }, [appName, agentName, agentId]);

  const preRef = useRef<HTMLPreElement | null>(null);

  const copy = useCallback(() => {
    /** The clipboard API is refused in plenty of ordinary situations — an unfocused tab,
     *  a denied permission, a non-secure origin. Telling someone to "select the JSON and
     *  copy it" and leaving them to do it is a worse answer than doing the selecting: the
     *  manifest is 40 lines and selecting it by hand inside a scrolling box is fiddly. */
    const selectIt = () => {
      const el = preRef.current;
      if (!el) return;
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
      setError("Clipboard blocked by the browser — the JSON is selected, press ⌘C.");
    };
    navigator.clipboard?.writeText(json).then(() => {
      setError("");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    }).catch(selectIt) ?? selectIt();
  }, [json]);

  const save = useCallback(async () => {
    setSaving(true);
    setError("");
    try {
      const bot = await createSlackBot({
        name: appName.trim() || agentName,
        agent_id: agentId,
        connection_id: connectionId,
        bot_token: botToken.trim(),
        app_token: appToken.trim(),
        signing_secret: signingSecret.trim(),
      });
      // Cleared the moment the server has them. They are masked in the response, so
      // nothing on this screen holds a usable credential afterwards.
      setBotToken(""); setAppToken(""); setSigningSecret("");
      setCreated(bot.name || bot.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }, [appName, agentName, agentId, connectionId, botToken, appToken, signingSecret]);

  const haveAll = !!(botToken.trim() && appToken.trim() && signingSecret.trim());

  const createApp = useCallback(async () => {
    setCreating(true);
    setError("");
    try {
      const made = await createSlackApp({
        config_token: configToken.trim(), name: appName.trim() || agentName || "Aughor",
        agent_id: agentId, connection_id: connectionId, agent_view: true,
      });
      // The token was used once; nothing on this screen keeps it.
      setConfigToken("");
      setApp(made);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }, [configToken, appName, agentName, agentId, connectionId]);

  const finish = useCallback(async () => {
    if (!app) return;
    setFinishing(true);
    setError("");
    try {
      const b = app.bot;
      await updateSlackBot(b.id, {
        name: b.name, enabled: false, agent_id: b.agent_id, connection_id: b.connection_id,
        agent_view: b.agent_view,
        ...(pastedBotToken.trim() ? { bot_token: pastedBotToken.trim() } : {}),
        ...(pastedAppToken.trim() ? { app_token: pastedAppToken.trim() } : {}),
      });
      setPastedBotToken(""); setPastedAppToken("");
      setFinished(true);
      setCreated(b.name || b.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setFinishing(false);
    }
  }, [app, pastedBotToken, pastedAppToken]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <div className="aug-fs-h2" style={{ fontWeight: 500 }}>{heading}</div>
        <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 3, maxWidth: 620 }}>
          {intro ? emphasise(intro) : (<>
            Optional. A Slack app lets people @mention <strong>{agentName || "this agent"}</strong> in
            a channel, and lets a scheduled automation post as it — the “post the daily numbers”
            step. One configuration token lets Aughor create the app itself; then an install
            and one more token, and it listens.
          </>)}
        </div>
      </div>

      {/* ── the one-token path (AO-2d) ── */}
      {!byHand && (
        <div style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14 }}>
          <div className="aug-fs-sm" style={{ fontWeight: 500, marginBottom: 8 }}>
            1 · Let Aughor create the app
          </div>
          {!app ? (
            <>
              <div className="aug-fs-xs" style={{ color: "var(--t3)", marginBottom: 8 }}>
                At api.slack.com/apps → <strong>Your App Configuration Tokens</strong> → Generate,
                copy the token and paste it here. It is used once to create the app from the
                manifest Aughor renders (agent mode, Socket Mode, every scope) and is never stored.
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
                <div style={{ flex: "1 1 220px", minWidth: 0 }}>
                  <label className="aug-fs-xs" style={labelStyle}>App name — what Slack will show</label>
                  <Input className="aug-fs-ui" style={inputStyle} value={appName}
                    onChange={e => setAppName(e.target.value)} placeholder="Aughor" />
                </div>
                <div style={{ flex: "2 1 320px", minWidth: 0 }}>
                  <label className="aug-fs-xs" style={labelStyle}>Configuration token</label>
                  <Input className="aug-fs-ui" style={inputStyle} value={configToken} autoComplete="off"
                    spellCheck={false} onChange={e => setConfigToken(e.target.value)} placeholder="xoxe.xoxp-…" />
                </div>
                <Button variant="default" size="sm" onClick={createApp}
                  disabled={creating || !configToken.trim()}>
                  {creating ? "Creating in Slack…" : "Create the app"}
                </Button>
              </div>
            </>
          ) : (
            <div className="aug-fs-sm" style={{ color: "var(--chart-2)" }}>
              App <strong>{app.bot.name}</strong> created in Slack ({app.app_id}); its signing secret
              is stored. Two steps remain — both are said below, neither is hidden.
              {app.manage_url && (
                <>{" "}<a href={app.manage_url} target="_blank" rel="noreferrer">Open it at api.slack.com ↗</a></>
              )}
            </div>
          )}

          {app && !finished && (
            <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
              <div className="aug-fs-sm" style={{ fontWeight: 500 }}>2 · Install it to your workspace</div>
              {app.oauth_available && app.install_url ? (
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <Button variant="default" size="sm"
                    onClick={() => { window.location.href = `${getApiBase()}${app.install_url}`; }}>
                    Install to Slack
                  </Button>
                  <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                    Slack asks you to approve the scopes and sends the bot token back here.
                  </span>
                </div>
              ) : (
                <>
                  <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>{app.steps[0]}</div>
                  <Input className="aug-fs-ui" style={inputStyle} value={pastedBotToken} autoComplete="off"
                    spellCheck={false} onChange={e => setPastedBotToken(e.target.value)} placeholder="xoxb-…" />
                </>
              )}
              <div className="aug-fs-sm" style={{ fontWeight: 500 }}>3 · The app-level token (the one Slack has no API for)</div>
              <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>{app.steps[1]}</div>
              <Input className="aug-fs-ui" style={inputStyle} value={pastedAppToken} autoComplete="off"
                spellCheck={false} onChange={e => setPastedAppToken(e.target.value)} placeholder="xapp-…" />
              <Button variant="default" size="sm" style={{ alignSelf: "flex-start" }}
                disabled={finishing || !pastedAppToken.trim() || (!app.oauth_available && !pastedBotToken.trim())}
                onClick={finish}>
                {finishing ? "Verifying with Slack…" : "Finish — the bot goes live"}
              </Button>
            </div>
          )}
          {finished && (
            <div className="aug-fs-sm" style={{ color: "var(--chart-2)", marginTop: 10 }}>
              Slack bot <strong>{created}</strong> is live. Invite it to the channel you want it
              to post in; the bot card says when a supervisor is listening for it.
            </div>
          )}
          {!app && (
            <div style={{ marginTop: 10 }}>
              <Button variant="ghost" size="xs" onClick={() => setByHand(true)}>
                Do it by hand instead — paste the manifest at api.slack.com
              </Button>
            </div>
          )}
        </div>
      )}

      {byHand && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          The manual path: Aughor renders the manifest, you create the app in Slack and paste
          three values back.{" "}
          <Button variant="ghost" size="xs" onClick={() => setByHand(false)}>Use one token instead</Button>
        </div>
      )}

      {/* ── 1 · the manifest ── */}
      {byHand && (<>
      <div style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14 }}>
        <div className="aug-fs-sm" style={{ fontWeight: 500, marginBottom: 8 }}>
          1 · Generate the app manifest
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <label className="aug-fs-xs" style={labelStyle}>App name — what Slack will show</label>
            <Input className="aug-fs-ui" style={inputStyle} value={appName}
              onChange={e => setAppName(e.target.value)} placeholder="Aughor" />
          </div>
          <Button variant="secondary" size="sm" onClick={render} disabled={rendering}>
            {rendering ? "Rendering…" : manifest ? "Re-render" : "Generate JSON"}
          </Button>
        </div>

        {manifest && (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "12px 0 6px" }}>
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                Paste this on the <strong>JSON</strong> tab at api.slack.com — not YAML.
              </span>
              <Button variant="secondary" size="xs" style={{ marginLeft: "auto" }} onClick={copy}>
                <Icon name={copied ? "check" : "copy"} size={12} />
                {copied ? "Copied" : "Copy JSON"}
              </Button>
            </div>
            <pre ref={preRef} className="aug-fs-xs nowheel" style={{
              margin: 0, maxHeight: 260, overflow: "auto", padding: 10,
              background: "var(--bg-1)", border: "1px solid var(--b1)",
              borderRadius: "var(--r3)", color: "var(--t2)",
              fontFamily: "var(--font-mono)", whiteSpace: "pre",
            }}>{json}</pre>

            {/* The server's own steps, not a copy of them kept here — the scopes and the
                socket-mode toggle it names are the ones it just rendered. */}
            <ol className="aug-fs-xs" style={{ color: "var(--t3)", margin: "10px 0 0",
              paddingLeft: 18, display: "flex", flexDirection: "column", gap: 3 }}>
              {manifest.instructions.map((line, i) => <li key={i}>{emphasise(line)}</li>)}
            </ol>
          </>
        )}
      </div>

      {/* ── 2 · the credentials ── */}
      <div style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14,
                    opacity: manifest ? 1 : 0.55 }}>
        <div className="aug-fs-sm" style={{ fontWeight: 500, marginBottom: 8 }}>
          2 · Paste the three values back
        </div>
        {created ? (
          <div className="aug-fs-sm" style={{ color: "var(--chart-2)" }}>
            Slack bot <strong>{created}</strong> created and verified against Slack. Invite it
            to the channel you want it to post in, then add a “Post to Slack” action to an
            automation.
          </div>
        ) : (
          <>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div>
                <label className="aug-fs-xs" style={labelStyle}>Bot user OAuth token — OAuth &amp; Permissions</label>
                <Input className="aug-fs-ui" style={inputStyle} value={botToken} autoComplete="off" spellCheck={false}
                  onChange={e => setBotToken(e.target.value)} placeholder="xoxb-…" />
              </div>
              <div>
                <label className="aug-fs-xs" style={labelStyle}>App-level token — Basic Information, scope connections:write</label>
                <Input className="aug-fs-ui" style={inputStyle} value={appToken} autoComplete="off" spellCheck={false}
                  onChange={e => setAppToken(e.target.value)} placeholder="xapp-…" />
              </div>
              <div>
                <label className="aug-fs-xs" style={labelStyle}>Signing secret — Basic Information</label>
                <Input className="aug-fs-ui" style={inputStyle} value={signingSecret} autoComplete="off" spellCheck={false}
                  onChange={e => setSigningSecret(e.target.value)} placeholder="the signing secret" />
              </div>
            </div>
            <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 8 }}>
              Sent once to Aughor, checked against Slack before anything is stored, and held
              encrypted. They are cleared from this form as soon as the server has them.
            </div>
            <Button variant="default" size="sm" style={{ marginTop: 10 }}
              disabled={!haveAll || saving} onClick={save}>
              {saving ? "Verifying with Slack…" : "Create Slack bot"}
            </Button>
          </>
        )}
      </div>
      </>)}

      {error && (
        <div className="aug-fs-sm" style={{ color: "var(--red4)" }}>{error}</div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <Button variant={created ? "default" : "secondary"} size="sm" onClick={onDone}>
          {created ? "Done" : skipLabel}
        </Button>
      </div>
    </div>
  );
}
