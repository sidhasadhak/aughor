/**
 * Central API configuration.
 *
 * The API base is resolved at RUNTIME, not baked in at build time. That distinction is the
 * whole point: `NEXT_PUBLIC_*` is inlined into the JS bundle when the app is built, so a
 * hosted deployment would otherwise ship one backend URL for every visitor. This product is
 * local-first — the data, the DuckDB files and the keys all live on the user's machine — so
 * the UI can be served from anywhere while each user points it at their own engine.
 *
 * Precedence, most specific first:
 *   1. the user's own setting (localStorage) — set from Settings → System → Backend
 *   2. NEXT_PUBLIC_API_URL at build time — for a deployment with a known backend
 *   3. http://localhost:8000 — the local development default
 *
 * Nothing here changes local development: with no override stored and no env var set, the
 * fallback fires and the app talks to localhost exactly as it always has.
 */

/** The build-time answer: what the base resolves to with no user override stored. */
export const API_BASE_DEFAULT =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000";

const STORAGE_KEY = "aughor.apiBase";

/**
 * Demo posture. A hosted deployment with no backend resolves to `http://localhost:8000`,
 * which is the VISITOR's machine — so every list comes back empty and the app looks broken
 * when it is in fact working exactly as designed. With this set, the frontend serves a
 * frozen recording of one connection's read surface from `/demo-api` instead, and a visitor
 * sees real completed work with no backend, no key and no spend.
 *
 * A deployment env var rather than a runtime flag, deliberately: `DEMO_PACK_DESIGN.md`
 * calls out "demo mode leaking into normal use" as a risk and prescribes exactly this —
 * "an explicit deployment env var, not a new registry flag". Unset (every local dev run,
 * every self-hosted install), nothing here changes.
 */
export const DEMO_PACK =
  typeof process !== "undefined" && process.env.NEXT_PUBLIC_DEMO_PACK === "1";

/** Same-origin base the recording is served from. Relative on purpose — the deployment's
 *  own host answers it, so there is no URL to configure and no CORS to arrange. */
export const DEMO_API_BASE = "/demo-api";

/** Where the effective value came from — the Settings UI says this out loud, because
 *  "why is it talking to the wrong backend" is otherwise an invisible question. */
export type ApiBaseSource = "user" | "env" | "default" | "demo";

function readStored(): string | null {
  // Guarded for SSR and for browsers that throw on localStorage (Safari private mode).
  if (typeof window === "undefined") return null;
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v && v.trim() ? v.trim() : null;
  } catch {
    return null;
  }
}

/**
 * Normalise a user-supplied base: trim, drop a trailing slash, and require an absolute
 * http(s) URL. Returns null when the input could not be understood — the caller decides
 * whether that means "reject" or "fall back", and both callers here choose to keep the
 * previous value rather than leave the app pointed at nothing.
 */
export function normalizeApiBase(raw: string): string | null {
  const s = (raw || "").trim().replace(/\/+$/, "");
  if (!s) return null;
  try {
    const u = new URL(s);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    return s;
  } catch {
    return null;
  }
}

/** The API base in force right now. Call this — never capture it at module load, or the
 *  value freezes and a later change is silently ignored. */
export function getApiBase(): string {
  // A stored override still wins in demo mode: "connect your own backend" is the demo's
  // one call to action, so it must not be the one thing the demo posture blocks.
  const stored = readStored();
  if (stored) return stored;
  if (DEMO_PACK) return DEMO_API_BASE;
  return API_BASE_DEFAULT;
}

export function getApiBaseSource(): ApiBaseSource {
  if (readStored()) return "user";
  if (DEMO_PACK) return "demo";
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) return "env";
  return "default";
}

// ── change notification ──────────────────────────────────────────────────────────
// A long-lived connection (an EventSource) keeps talking to the host it was OPENED
// against, so persisting a new base is not enough: whoever holds a stream has to be told
// to tear it down and reopen. Without this the UI looks connected while streaming from the
// previous backend — the failure mode that is invisible precisely because nothing errors.

type Listener = (base: string) => void;
const listeners = new Set<Listener>();

/** Subscribe to API-base changes. Returns an unsubscribe function. */
export function onApiBaseChange(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/**
 * Persist a new API base (or `null` to clear the override and fall back to env/default),
 * then notify every holder of a live connection.
 *
 * Returns the value now in force, so a caller can render it without re-reading.
 */
export function setApiBase(raw: string | null): string {
  if (typeof window !== "undefined") {
    try {
      if (raw === null) {
        window.localStorage.removeItem(STORAGE_KEY);
      } else {
        const clean = normalizeApiBase(raw);
        // An unparseable value is dropped rather than stored: the app must never be left
        // pointed at nothing by a typo, because the settings UI that would fix it is
        // itself reached through the app.
        if (clean) window.localStorage.setItem(STORAGE_KEY, clean);
      }
    } catch {
      /* storage unavailable — this session simply keeps the previous value */
    }
  }
  const now = getApiBase();
  for (const fn of listeners) {
    try {
      fn(now);
    } catch {
      /* one bad listener must not stop the others from reconnecting */
    }
  }
  return now;
}

/**
 * CK-1: route the unified `/ask` turn through the AG-UI protocol seam (POST /agui/run) instead
 * of the native `/ask` SSE. The adapter (lib/aguiTransport.ts) re-frames AG-UI events back into
 * the same reducer dispatches, so the UI is identical either way — this is a transport swap for
 * dogfooding the seam. Default OFF ⇒ the native transport (byte-identical). Requires the backend
 * flag `agui.endpoint` to be on as well.
 */
export const AUGHOR_AGUI =
  typeof process !== "undefined" && process.env.NEXT_PUBLIC_AUGHOR_AGUI === "1";
