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
import { createSlackBot, getSlackBotManifest, type SlackManifest } from "@/lib/api";

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

export function AgentSlackDoor({ agentId, agentName, connectionId, onDone }: {
  agentId: string;
  agentName: string;
  connectionId: string;
  /** Finished or skipped — either way the agent already exists, so this only closes. */
  onDone: () => void;
}) {
  const [appName, setAppName] = useState(agentName || "Aughor");
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <div className="aug-fs-h2" style={{ fontWeight: 500 }}>Give it a Slack door</div>
        <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 3, maxWidth: 620 }}>
          Optional. A Slack app lets people @mention <strong>{agentName || "this agent"}</strong> in
          a channel, and lets a scheduled automation post as it — the “post the daily numbers”
          step. Aughor renders the app manifest; you create the app in Slack and paste three
          values back.
        </div>
      </div>

      {/* ── 1 · the manifest ── */}
      <div style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14 }}>
        <div className="aug-fs-sm" style={{ fontWeight: 500, marginBottom: 8 }}>
          1 · Generate the app manifest
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <label className="aug-fs-xs" style={labelStyle}>App name — what Slack will show</label>
            <input className="aug-fs-ui" style={inputStyle} value={appName}
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
                <input className="aug-fs-ui" style={inputStyle} value={botToken} autoComplete="off" spellCheck={false}
                  onChange={e => setBotToken(e.target.value)} placeholder="xoxb-…" />
              </div>
              <div>
                <label className="aug-fs-xs" style={labelStyle}>App-level token — Basic Information, scope connections:write</label>
                <input className="aug-fs-ui" style={inputStyle} value={appToken} autoComplete="off" spellCheck={false}
                  onChange={e => setAppToken(e.target.value)} placeholder="xapp-…" />
              </div>
              <div>
                <label className="aug-fs-xs" style={labelStyle}>Signing secret — Basic Information</label>
                <input className="aug-fs-ui" style={inputStyle} value={signingSecret} autoComplete="off" spellCheck={false}
                  onChange={e => setSigningSecret(e.target.value)} placeholder="the signing secret" />
              </div>
            </div>
            <div className="aug-fs-xs" style={{ color: "var(--t4)", marginTop: 8 }}>
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

      {error && (
        <div className="aug-fs-sm" style={{ color: "var(--red4)" }}>{error}</div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <Button variant={created ? "default" : "secondary"} size="sm" onClick={onDone}>
          {created ? "Done" : "Skip — the agent is already created"}
        </Button>
      </div>
    </div>
  );
}
