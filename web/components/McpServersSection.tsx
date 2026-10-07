"use client";

/**
 * VA-9d · the MCP servers surface — the catalog's last entry.
 *
 * §3.4's item 4 places it here on purpose: the catalog is where a person goes to give
 * this deployment reach, and an MCP server is the one kind of reach that is not an
 * account somebody grants us but a third party an operator writes down. Everything above
 * it on this panel is "connect as me"; this is "call out to them".
 *
 * **An empty list is the posture, not an empty state.** The copy says so rather than
 * apologising for it: a deployment with no servers registered reaches nothing at all, and
 * that is the answer VA-9's risk note ("the largest new attack surface in the arc") asked
 * for. So the zero case leads with what the emptiness MEANS.
 *
 * **Every refusal sentence is the server's, rendered verbatim.** The read-only-first
 * posture lives in those words — including the one that surprises people, that a tool
 * declaring nothing is refused because the protocol reads a missing declaration as "may
 * modify". A client that re-worded them would be re-deciding the posture, and a client
 * that hid the refused rows would be the catalogue-that-lies failure DS-10 exists to end.
 * So refused tools are LISTED, dimmed, with their reason.
 *
 * **The roster's age is always on screen when the roster is.** A cached remote list shown
 * as if it were live is the failure `discovered_at` exists to prevent.
 *
 * **The write slice adds one button, and changes none of the above.** A refused tool can be
 * GRANTED here — §6.6's answer to "whose declaration of read-only is believed": nobody's but
 * ours, so a mutating call runs on a person's ratification rather than on the server's word.
 * The refusal sentences are still the server's and still verbatim; granting adds a state
 * beside them, it does not soften them. Three states are drawn rather than two, because
 * "nobody approved this" and "somebody approved it and the server has since changed what it
 * says" want different next actions, and a granted row is marked as a WRITE rather than
 * simply going green.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  beginMcpSignIn, createMcpServer, deleteMcpServer, discoverMcpServer, grantMcpTool,
  listMcpServers, mcpServerHealth, revokeMcpTool, signOutMcpServer, updateMcpServer,
  type McpServerRow, type McpToolRow,
} from "@/lib/api";
import { Input } from "@/components/ui/input";

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "7px 10px", borderRadius: "var(--r3)",
  border: "1px solid var(--b1)", background: "var(--bg-1)", color: "var(--t1)",
};

/** `args` is edited as one line and stored as a list. Split on whitespace, never handed to
 *  a shell — the model keeps `command` and `args` apart precisely so nothing ever splits
 *  them with shell semantics, and this is the one place a person types them together. */
const splitArgs = (line: string): string[] =>
  line.trim().split(/\s+/).filter(Boolean);

export function McpServersSection() {
  const [servers, setServers] = useState<McpServerRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [adding, setAdding] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [health, setHealth] = useState<Record<string, string>>({});

  const [name, setName] = useState("");
  const [transport, setTransport] = useState<"stdio" | "http">("http");
  const [command, setCommand] = useState("");
  const [argsLine, setArgsLine] = useState("");
  const [url, setUrl] = useState("");
  const [authHeader, setAuthHeader] = useState("");
  const [authHeaderName, setAuthHeaderName] = useState("Authorization");
  // How a URL server is reached. Signing in on the server's own page is the default: a key in a
  // header meant finding the right key AND the header the server reads it from (2026-10-07,
  // Composio: two kinds of key, three header names, none of it on the form).
  const [access, setAccess] = useState<"signin" | "key" | "none">("signin");
  // The sign-in page, for when the browser would not let a tab open on its own.
  const [signInLinks, setSignInLinks] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      setServers((await listMcpServers()).servers);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load MCP servers");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // A sign-in finishes in another tab, at the API's callback; this list learns of it by asking.
  const waiting = servers.some(s => s.oauth?.sign_in_pending);
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [waiting, load]);

  const act = async (id: string, fn: () => Promise<unknown>) => {
    setBusy(id);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work");
    } finally {
      setBusy("");
    }
  };

  const reset = () => {
    setAdding(false); setName(""); setCommand(""); setArgsLine("");
    setUrl(""); setAuthHeader(""); setAuthHeaderName("Authorization"); setTransport("http");
    setAccess("signin");
  };

  const add = () => act("new", async () => {
    await createMcpServer({
      name: name.trim(), transport,
      ...(transport === "stdio"
        ? { command: command.trim(), args: splitArgs(argsLine) }
        : { url: url.trim(),
            ...(access === "signin" ? { auth_mode: "oauth_authorization_code" as const }
              : access === "key" ? { auth_header: authHeader.trim(),
                                     auth_header_name: authHeaderName.trim() || "Authorization" }
              : {}) }),
    });
    reset();
  });

  const signIn = (s: McpServerRow) => {
    // The tab opens inside the click, before anything is awaited: a tab opened after an await is
    // a pop-up the browser may block. It is pointed at the sign-in page once the API has it.
    const tab = window.open("about:blank", "_blank");
    void act(s.id, async () => {
      try {
        const { authorization_url } = await beginMcpSignIn(s.id);
        if (tab && !tab.closed) {
          tab.opener = null;
          tab.location.href = authorization_url;
        } else {
          setSignInLinks(prev => ({ ...prev, [s.id]: authorization_url }));
        }
      } catch (e) {
        tab?.close();
        throw e;
      }
    });
  };

  const checkHealth = (id: string) => act(id, async () => {
    const h = await mcpServerHealth(id);
    setHealth(prev => ({
      ...prev,
      [id]: h.ok ? (h.detail || "reachable") : `unreachable — ${h.reason}`,
    }));
  });

  const canAdd = name.trim() && (transport === "stdio" ? command.trim() : url.trim());

  return (
    <div style={{ marginBottom: 18 }}>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", letterSpacing: "0.06em",
        textTransform: "uppercase", marginBottom: 8 }}>
        MCP servers
      </div>

      {error && (
        <div className="aug-fs-xs" style={{ color: "var(--red3)", marginBottom: 8 }}>
          {error}
        </div>
      )}

      {loaded && servers.length === 0 && !adding && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)", marginBottom: 8,
          lineHeight: 1.6 }}>
          {/* The emptiness is the design, so it is stated as one. */}
          Nothing is registered, so this deployment can call no MCP server at all. Add one
          and Aughor will ask it what it offers — then its <strong>read-only</strong> tools
          become a step you can place on a workflow.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {servers.map(s => (
          <div key={s.id} style={{ border: "1px solid var(--b1)",
            borderRadius: "var(--r2)", background: "var(--bg-1)", padding: "10px 12px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: s.enabled ? "var(--t2)" : "var(--t3)" }}>
                <Icon name="plug" size={15} />
              </span>
              <span className="aug-fs-ui" style={{ fontWeight: 600 }}>
                {s.name || s.id}
              </span>
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                {s.transport === "stdio" ? "process" : "url"}
              </span>
              {!s.enabled && (
                <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>● off</span>
              )}
              <span style={{ flex: 1 }} />
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                {/* The number that surprises people: healthy, and offering this
                    deployment nothing it may call. */}
                {s.discovered_at
                  ? `${s.tool_count} tools · ${s.callable_count} callable here`
                  : "not discovered yet"}
              </span>
            </div>

            <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 4,
              fontFamily: "var(--font-mono)", overflow: "hidden",
              textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {s.transport === "stdio"
                ? [s.command, ...(s.args || [])].join(" ")
                : s.url}
              {s.oauth?.mode === "oauth_authorization_code"
                ? `  ·  ${s.oauth.signed_in ? "signed in" : "not signed in"}`
                : s.has_auth ? `  ·  ${s.auth_header_name || "Authorization"} header stored` : ""}
            </div>

            {s.oauth?.sign_in_pending && (
              <div className="aug-fs-xs" style={{ marginTop: 4, color: "var(--t3)" }}>
                Waiting for you to finish signing in on the server&apos;s page
                {signInLinks[s.id]
                  ? <> — <a href={signInLinks[s.id]} target="_blank" rel="noreferrer">open it</a></>
                  : "…"}
              </div>
            )}

            {health[s.id] && (
              <div className="aug-fs-xs" style={{ marginTop: 4,
                color: health[s.id].startsWith("unreachable")
                  ? "var(--red3)" : "var(--grn4)" }}>
                {health[s.id]}
              </div>
            )}

            <div style={{ display: "flex", gap: 2, marginTop: 6, flexWrap: "wrap" }}>
              {s.oauth?.mode === "oauth_authorization_code" && (s.oauth.signed_in ? (
                <Button variant="ghost" size="xs" className="aug-fs-xs" disabled={busy === s.id}
                  onClick={() => void act(s.id, () => signOutMcpServer(s.id))}>
                  Sign out
                </Button>
              ) : (
                <Button size="xs" className="aug-fs-xs" disabled={busy === s.id}
                  onClick={() => signIn(s)}>
                  {busy === s.id ? "…" : s.oauth.sign_in_pending ? "Sign in again" : "Sign in"}
                </Button>
              ))}
              <Button variant="ghost" size="xs" className="aug-fs-xs" disabled={busy === s.id}
                onClick={() => void act(s.id, () => discoverMcpServer(s.id))}>
                {busy === s.id ? "…" : s.discovered_at ? "Re-discover" : "Discover"}
              </Button>
              <Button variant="ghost" size="xs" className="aug-fs-xs" disabled={busy === s.id}
                onClick={() => void checkHealth(s.id)}>
                Check
              </Button>
              <Button variant="ghost" size="xs" className="aug-fs-xs" disabled={busy === s.id}
                onClick={() => void act(s.id, () => updateMcpServer(s.id, {
                  name: s.name, transport: s.transport, command: s.command,
                  args: s.args, url: s.url, enabled: !s.enabled,
                }))}>
                {s.enabled ? "Turn off" : "Turn on"}
              </Button>
              {s.tool_count > 0 && (
                <Button variant="ghost" size="xs" className="aug-fs-xs"
                  onClick={() => setExpanded(expanded === s.id ? null : s.id)}>
                  {expanded === s.id ? "Hide tools" : "Tools"}
                </Button>
              )}
              <span style={{ flex: 1 }} />
              <Button variant="ghost" size="xs" className="aug-fs-xs"
                style={{ color: "var(--red3)" }} disabled={busy === s.id}
                onClick={() => void act(s.id, () => deleteMcpServer(s.id))}>
                Remove
              </Button>
            </div>

            {expanded === s.id && (
              <ToolRoster tools={s.tools} discoveredAt={s.discovered_at} serverId={s.id}
                onChanged={() => void load()} />
            )}
          </div>
        ))}
      </div>

      {adding ? (
        <div style={{ border: "1px solid var(--b1)", borderRadius: "var(--r2)",
          background: "var(--bg-1)", padding: "10px 12px", marginTop: 8,
          display: "flex", flexDirection: "column", gap: 8 }}>
          <Input className="aug-fs-ui" style={inputStyle} placeholder="Name"
            value={name} onChange={e => setName(e.target.value)} aria-label="Server name" />

          <div style={{ display: "inline-flex", gap: 2, padding: 2, alignSelf: "flex-start",
            border: "1px solid var(--b1)", borderRadius: "var(--r-chip)" }}>
            {(["http", "stdio"] as const).map(m => (
              <Button key={m} size="xs" className="aug-fs-xs"
                variant={transport === m ? "secondary" : "ghost"}
                onClick={() => setTransport(m)}>
                {m === "http" ? "URL" : "Local process"}
              </Button>
            ))}
          </div>

          {transport === "http" ? (
            <>
              <Input className="aug-fs-ui" style={inputStyle} spellCheck={false}
                placeholder="https://example.com/mcp" aria-label="Server URL"
                value={url} onChange={e => setUrl(e.target.value)} />
              <div role="group" aria-label="How Aughor gets in"
                style={{ display: "inline-flex", gap: 2, padding: 2, alignSelf: "flex-start",
                  border: "1px solid var(--b1)", borderRadius: "var(--r-chip)" }}>
                {([["signin", "Sign in"], ["key", "API key"], ["none", "None"]] as const).map(([m, label]) => (
                  <Button key={m} size="xs" className="aug-fs-xs"
                    variant={access === m ? "secondary" : "ghost"}
                    onClick={() => setAccess(m)}>
                    {label}
                  </Button>
                ))}
              </div>
              {access === "signin" && (
                <div className="aug-fs-xs" style={{ color: "var(--t3)", lineHeight: 1.5 }}>
                  After adding it, press Sign in: the server&apos;s own page asks you to approve
                  Aughor. There is no key to copy, and what it hands back is stored encrypted.
                </div>
              )}
              {access === "key" && (
                <>
                  {/* The header NAME the credential travels in. Most servers read `Authorization`;
                      some name their own — Composio takes its key only as `x-api-key`. */}
                  <Input className="aug-fs-ui" style={inputStyle} spellCheck={false}
                    autoComplete="off"
                    placeholder="Header name — Authorization, or the one your server names (e.g. x-api-key)"
                    aria-label="Auth header name"
                    value={authHeaderName} onChange={e => setAuthHeaderName(e.target.value)} />
                  <Input className="aug-fs-ui" style={inputStyle} spellCheck={false}
                    autoComplete="off"
                    placeholder="Header value — e.g. Bearer …, or an API key"
                    aria-label="Auth header value"
                    value={authHeader} onChange={e => setAuthHeader(e.target.value)} />
                  <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                    <Icon name="lock" size={11} /> Stored encrypted, and never returned by any
                    read — not even masked.
                  </div>
                </>
              )}
              {access === "none" && (
                <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                  For a server that asks for no credential.
                </div>
              )}
            </>
          ) : (
            <>
              <Input className="aug-fs-ui" style={inputStyle} spellCheck={false}
                placeholder="Command — e.g. npx" aria-label="Command"
                value={command} onChange={e => setCommand(e.target.value)} />
              <Input className="aug-fs-ui" style={inputStyle} spellCheck={false}
                placeholder="Arguments — e.g. -y @modelcontextprotocol/server-everything"
                aria-label="Arguments"
                value={argsLine} onChange={e => setArgsLine(e.target.value)} />
              {/* Said before the command is pasted, not after it runs. This is the more
                  dangerous of the two transports and the form should say which. */}
              <div className="aug-fs-xs" style={{ color: "var(--amb4)", lineHeight: 1.5 }}>
                <Icon name="warning" size={11} /> A local process runs with this
                deployment&apos;s own privileges. Nothing is passed to a shell — the
                command and its arguments stay separate — but only add a process you would
                run yourself.
              </div>
            </>
          )}

          <div style={{ display: "flex", gap: 6 }}>
            <Button size="xs" className="aug-fs-xs" disabled={!canAdd || busy === "new"}
              onClick={() => void add()}>
              {busy === "new" ? "Adding…" : "Add"}
            </Button>
            <Button variant="ghost" size="xs" className="aug-fs-xs" onClick={reset}>
              Cancel
            </Button>
          </div>
          <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            Adding a server contacts nothing. Press Discover afterwards to ask it what it
            offers.
          </div>
        </div>
      ) : (
        <Button variant="ghost" size="sm" className="aug-fs-xs" style={{ marginTop: 8 }}
          onClick={() => setAdding(true)}>
          <Icon name="plus" size={12} /> Custom MCP
        </Button>
      )}
    </div>
  );
}

/** The roster, refused rows included. Hiding them would be the catalogue that lies.
 *
 * **The write slice's surface is here, and it is one button.** A refused tool can be
 * GRANTED — the ratification §6.6 made the authority for a mutating call. Three states are
 * drawn, never two, because "nobody has approved this" and "somebody approved it and the
 * server has since changed what it says" are different situations with different next
 * actions, and flattening them into one dimmed row is how a person re-approves a change
 * they never saw.
 *
 * A granted row is marked as a WRITE rather than simply going green. A tool that mutates
 * somebody else's system rendering identically to one that reads is the property a person
 * most needs before putting it on a canvas that runs at 07:00 unattended.
 */
function ToolRoster({ tools, discoveredAt, serverId, onChanged }: {
  tools: McpToolRow[]; discoveredAt: string; serverId: string; onChanged: () => void;
}) {
  const [busy, setBusy] = useState("");
  const [failed, setFailed] = useState("");

  const act = async (toolName: string, grant: boolean) => {
    setBusy(toolName); setFailed("");
    try {
      if (grant) await grantMcpTool(serverId, toolName);
      else await revokeMcpTool(serverId, toolName);
      onChanged();
    } catch (e) {
      setFailed(e instanceof Error ? e.message : "that did not work");
    } finally {
      setBusy("");
    }
  };

  return (
    <div style={{ marginTop: 8, borderTop: "1px solid var(--b1)", paddingTop: 8 }}>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", marginBottom: 6 }}>
        {/* Never the list without its age. */}
        Read from the server at {discoveredAt || "an unknown time"}.
      </div>
      {failed && (
        <div className="aug-fs-xs" style={{ color: "var(--red4)", marginBottom: 6 }}>
          {failed}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {tools.map(t => {
          const callable = t.disposition === "callable";
          const granted = t.grant_state === "active";
          const stale = t.grant_state === "stale";
          return (
            <div key={t.name} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <span className="aug-fs-xs" style={{ paddingTop: 1, flexShrink: 0,
                color: callable ? "var(--grn4)" : granted ? "var(--amb4)"
                  : stale ? "var(--red4)" : "var(--t3)" }}>
                {callable || granted ? "●" : "○"}
              </span>
              <div style={{ minWidth: 0, flex: 1 }}>
                <span className="aug-fs-xs" style={{ fontFamily: "var(--font-mono)",
                  color: callable || granted ? "var(--t2)" : "var(--t3)" }}>{t.name}</span>
                {granted && (
                  // Named a write, not merely allowed. This is the one row on the panel
                  // that changes somebody else's system.
                  <span className="aug-fs-xs" style={{ color: "var(--amb4)", marginLeft: 6 }}>
                    writes
                  </span>
                )}
                {t.description && (
                  <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                    {" "}— {t.description}
                  </span>
                )}
                {!callable && !granted && (
                  // The server's sentence, verbatim. It is the whole posture. For a STALE
                  // grant it is the drift sentence instead, which says what changed.
                  <div className="aug-fs-xs" style={{ color: stale ? "var(--red4)" : "var(--t3)",
                    marginTop: 2 }}>
                    {stale ? t.grant_reason : t.reason}
                  </div>
                )}
                {granted && (
                  <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>
                    Granted{t.granted_by ? ` by ${t.granted_by}` : ""}
                    {t.granted_at ? ` on ${t.granted_at.slice(0, 10)}` : ""}. Covers the
                    declaration this server makes today — if that changes, the grant lapses.
                  </div>
                )}
              </div>
              {!callable && (
                <Button variant="ghost" size="xs" className="aug-fs-xs"
                  disabled={busy === t.name}
                  onClick={() => void act(t.name, !granted)}>
                  {busy === t.name ? "…" : granted ? "Revoke" : stale ? "Grant again" : "Grant"}
                </Button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
