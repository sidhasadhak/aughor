/**
 * RC-5 — the bot registry: what Aughor says this process should be running.
 *
 * The supervisor reads records over HTTP and never opens Aughor's databases. That is
 * not a style preference: `data/system.db` has been corrupted by a second process
 * mapping the same SQLite WAL index, and a long-lived bot host is exactly the kind of
 * second process that would do it.
 *
 * Records arrive with PLAINTEXT tokens — this endpoint is the one place that hands them
 * out, because a socket cannot be opened with a mask. Everything else in Aughor masks
 * them. Treat what comes back as a credential: never log it, never echo it.
 */

export interface BotRecord {
  id: string;
  name: string;
  enabled: boolean;
  agent_id: string;
  connection_id: string;
  bot_token: string;
  app_token: string;
  signing_secret: string;
  agent_view: boolean;
}

export type FetchBots = () => Promise<BotRecord[]>;

/**
 * A fingerprint of everything that, if changed, means the running socket is wrong.
 *
 * Name is deliberately EXCLUDED: renaming a bot in Aughor should not drop a live
 * WebSocket and interrupt whoever is mid-thread. Credentials, bindings and agent_view
 * are all included — each one changes what the socket IS or how it answers.
 */
export function fingerprint(b: BotRecord): string {
  return [b.bot_token, b.app_token, b.signing_secret,
          b.agent_id, b.connection_id, String(b.agent_view)].join(" ");
}

export function createRegistry(
  env: {
    AUGHOR_API_URL?: string;
    AUGHOR_API_KEY?: string;
    /** The supervisor's own key, generated in Integrations → Slack. This route is the
     *  one that returns raw `xoxb-`/`xapp-` tokens, so it refuses an unauthenticated
     *  caller; a scoped key means the whole API does not have to be locked to open it. */
    AUGHOR_RUNTIME_KEY?: string;
  } = process.env,
  fetchImpl: typeof fetch = fetch,
): FetchBots {
  const base = (env.AUGHOR_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
  return async () => {
    const res = await fetchImpl(`${base}/slack-bots/runtime`, {
      headers: {
        accept: "application/json",
        ...(env.AUGHOR_API_KEY ? { "x-api-key": env.AUGHOR_API_KEY } : {}),
        ...(env.AUGHOR_RUNTIME_KEY
          ? { "x-aughor-runtime-key": env.AUGHOR_RUNTIME_KEY } : {}),
      },
    });
    // 503 is the platform refusing to hand credentials to an unauthenticated caller —
    // a configuration answer, not an outage, and worth saying so rather than letting a
    // supervisor retry-loop against a wall.
    if (res.status === 503) {
      throw new Error(
        "the API refused to serve bot credentials: generate a supervisor key in "
        + "Integrations → Slack and set it here as AUGHOR_RUNTIME_KEY");
    }
    if (!res.ok) throw new Error(`registry read failed (HTTP ${res.status})`);
    const body = await res.json() as { bots?: BotRecord[] };
    // Disabled rows are filtered HERE rather than by the caller: "enabled" is the
    // platform's off switch, and a supervisor that opened a disabled bot's socket would
    // make that switch a lie.
    return (body.bots ?? []).filter((b) => b.enabled && b.bot_token && b.app_token);
  };
}
