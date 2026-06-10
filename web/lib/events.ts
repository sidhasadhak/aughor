/**
 * K2 — the kernel event stream client.
 *
 * ONE EventSource over `/events/stream` (the ledger journal) shared by every
 * panel, replacing the seven independent setInterval polling loops. Panels
 * subscribe with a filter and refetch when a relevant event lands; each keeps
 * only a SLOW fallback interval for resilience (stream down ≠ stale UI).
 *
 * Lifecycle: connects on the first subscriber, disconnects when the last one
 * leaves, auto-reconnects with backoff and resumes from the last seen seq so
 * a dropped connection loses nothing (the journal is append-only).
 */
import { API_BASE } from "./config";

export interface KernelEvent {
  seq: number;
  at: string;
  kind: string;
  conn_id: string | null;
  canvas_id: string | null;
  job_id: string | null;
  payload: Record<string, unknown> | null;
}

interface Subscription {
  cb: (ev: KernelEvent) => void;
  kinds?: string[];        // prefix match, e.g. "exploration." matches exploration.phase
  connId?: string;
  canvasId?: string;
}

const subs = new Set<Subscription>();
let es: EventSource | null = null;
let lastSeq = 0;
let retryMs = 1000;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

function matches(s: Subscription, ev: KernelEvent): boolean {
  if (s.kinds && !s.kinds.some(k => ev.kind === k || ev.kind.startsWith(k))) return false;
  // Unscoped events (api.started etc.) pass every scope filter.
  if (s.connId && ev.conn_id && ev.conn_id !== s.connId) return false;
  if (s.canvasId && ev.canvas_id && ev.canvas_id !== s.canvasId) return false;
  return true;
}

function connect() {
  if (es || subs.size === 0 || typeof window === "undefined") return;
  const url = `${API_BASE}/events/stream${lastSeq ? `?since_seq=${lastSeq}` : ""}`;
  es = new EventSource(url);
  es.onmessage = (m) => {
    retryMs = 1000;
    let ev: KernelEvent;
    try { ev = JSON.parse(m.data); } catch { return; }
    if (ev.seq) lastSeq = Math.max(lastSeq, ev.seq);
    if (ev.kind === "stream.open") return;
    for (const s of subs) {
      if (matches(s, ev)) {
        try { s.cb(ev); } catch { /* one bad subscriber must not break the bus */ }
      }
    }
  };
  es.onerror = () => {
    es?.close();
    es = null;
    if (subs.size > 0 && !retryTimer) {
      retryTimer = setTimeout(() => { retryTimer = null; connect(); }, retryMs);
      retryMs = Math.min(retryMs * 2, 30_000);
    }
  };
}

function disconnectIfIdle() {
  if (subs.size === 0) {
    es?.close();
    es = null;
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  }
}

/** Subscribe to kernel events. Returns an unsubscribe function. */
export function subscribeKernelEvents(
  cb: (ev: KernelEvent) => void,
  opts: { kinds?: string[]; connId?: string; canvasId?: string } = {},
): () => void {
  const sub: Subscription = { cb, ...opts };
  subs.add(sub);
  connect();
  return () => {
    subs.delete(sub);
    disconnectIfIdle();
  };
}
