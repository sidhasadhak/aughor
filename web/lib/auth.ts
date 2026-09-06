/* ── VA-10 · the browser's side of OIDC ─────────────────────────────────────
   The API verifies bearer tokens (security/oidc.py); this module is how one
   gets ONTO every API call. 406 call sites build URLs from getApiBase() with
   raw fetch(), so the only complete attach point is a global fetch wrapper —
   the decision of WHAT to attach is a pure function (`authHeaderFor`) so the
   logic project can test it without touching window.

   The token is Google's ID token, verified by the SERVER on every request.
   `claimsOf` decodes for DISPLAY only (email in the chip) — trusting a claim
   client-side would be decorating, not authenticating. */

const TOKEN_KEY = "aughor_id_token";
export const AUTH_EXPIRED_EVENT = "aughor-auth-expired";

export function getIdToken(): string | null {
  try { return window.localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export function setIdToken(token: string): void {
  try { window.localStorage.setItem(TOKEN_KEY, token); } catch { /* private mode */ }
}

export function clearIdToken(): void {
  try { window.localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}

/** Display-only decode of a JWT payload. Null on anything malformed. */
export function claimsOf(token: string | null): { email?: string; exp?: number } | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
    return typeof payload === "object" && payload ? payload : null;
  } catch { return null; }
}

/**
 * The pure attach decision: the Authorization header to add, or null.
 * Only API-base URLs get the token; an existing Authorization header always
 * wins (a caller that set its own credential knows better than the wrapper).
 */
export function authHeaderFor(
  url: string, apiBase: string, token: string | null,
  existing?: HeadersInit,
): { Authorization: string } | null {
  if (!token || !apiBase || !url.startsWith(apiBase)) return null;
  if (existing) {
    const h = new Headers(existing);
    if (h.has("Authorization")) return null;
  }
  return { Authorization: `Bearer ${token}` };
}

let installed = false;

/**
 * Patch window.fetch once: attach the ID token to API calls, and on a 401 that
 * rode an attached token, clear it and announce — the sign-in control listens
 * and re-offers the button. A 401 with no token attached is someone else's
 * problem and passes through untouched.
 */
export function installAuthFetch(apiBase: string): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  const raw = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString()
      : (input as Request).url;
    const token = getIdToken();
    const add = authHeaderFor(url, apiBase, token, init?.headers);
    const nextInit = add
      ? { ...init, headers: { ...Object.fromEntries(new Headers(init?.headers ?? {})), ...add } }
      : init;
    const res = await raw(input, nextInit);
    if (add && res.status === 401) {
      clearIdToken();
      try { window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT)); } catch { /* SSR */ }
    }
    return res;
  };
}
