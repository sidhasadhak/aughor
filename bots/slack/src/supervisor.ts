/**
 * RC-5 — one process, N sockets, reconciled against the registry.
 *
 * Socket Mode is per app token: each Slack app opens its own WebSocket, so serving N
 * bots means N live connections. This owns the set of them and nothing else — it does
 * not know what a bot answers, only which ones should exist.
 *
 * `makeBot` is injected rather than built here, and that is the load-bearing choice:
 * the wiring a bot needs (chart renderer, deep-link base, adapters, state) differs by
 * deployment and grows wave to wave, so the supervisor stays ignorant of it. It also
 * keeps this file clear of the RC-2 surface, so the two can land in either order.
 *
 * Reconciliation, not a restart: a bot whose record is unchanged keeps its socket, so
 * editing one bot never interrupts a thread on another.
 */
import { fingerprint, type BotRecord, type FetchBots } from "./registry.js";

export interface RunningBot {
  shutdown(): Promise<void> | void;
}

export interface SupervisorOpts {
  fetchBots: FetchBots;
  makeBot: (record: BotRecord) => Promise<RunningBot> | RunningBot;
  log?: (msg: string) => void;
}

export interface ReconcileResult {
  started: string[];
  stopped: string[];
  restarted: string[];
  failed: { id: string; error: string }[];
  running: number;
}

export function createSupervisor({ fetchBots, makeBot, log = () => {} }: SupervisorOpts) {
  const running = new Map<string, { bot: RunningBot; print: string }>();

  async function stop(id: string): Promise<void> {
    const entry = running.get(id);
    if (!entry) return;
    running.delete(id);
    try {
      await entry.bot.shutdown();
    } catch (err) {
      // A socket that will not close cleanly must not block the ones that need opening.
      log(`bot ${id}: shutdown failed (${String(err)})`);
    }
  }

  async function reconcile(): Promise<ReconcileResult> {
    const result: ReconcileResult = {
      started: [], stopped: [], restarted: [], failed: [], running: 0,
    };

    let desired: BotRecord[];
    try {
      desired = await fetchBots();
    } catch (err) {
      // The registry being briefly unreachable is not a reason to tear down working
      // sockets. Keep serving what is already up and try again on the next tick.
      log(`registry unreachable, keeping ${running.size} running: ${String(err)}`);
      result.running = running.size;
      return result;
    }

    const wanted = new Map(desired.map((b) => [b.id, b]));

    for (const id of [...running.keys()]) {
      if (!wanted.has(id)) {
        await stop(id);
        result.stopped.push(id);
      }
    }

    for (const record of desired) {
      const current = running.get(record.id);
      const print = fingerprint(record);
      if (current && current.print === print) continue;   // unchanged — leave it alone
      if (current) {
        await stop(record.id);
        result.restarted.push(record.id);
      }
      try {
        running.set(record.id, { bot: await makeBot(record), print });
        if (!current) result.started.push(record.id);
      } catch (err) {
        // One bad credential must never take down the fleet. The bot is left out of the
        // running set, so the next reconcile retries it — a token fixed in Aughor
        // recovers on its own without anyone restarting this process.
        running.delete(record.id);
        result.failed.push({ id: record.id, error: String(err) });
        log(`bot ${record.id} (${record.name}) failed to start: ${String(err)}`);
      }
    }

    result.running = running.size;
    return result;
  }

  async function shutdown(): Promise<void> {
    await Promise.all([...running.keys()].map(stop));
  }

  return { reconcile, shutdown, runningIds: () => [...running.keys()] };
}
