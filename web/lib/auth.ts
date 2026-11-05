/* ── VA-10 · the browser's side of OIDC — Track A9: no credential the page can read ──
   The API verifies bearer tokens (security/oidc.py). Until 2026-11-05 the browser kept
   Google's ID token in localStorage and attached it to every call — readable by any script
   on the page, so one XSS bug anywhere was the person for an hour. Now the token is handed
   to the API ONCE (`POST /auth/session`), which answers with an HttpOnly cookie the page
   cannot read; every API call carries the cookie (`credentials: "include"`) and nothing
   else. What the page keeps is the signed-in EMAIL, for the chip — not a credential.

   406 call sites build URLs from getApiBase() with raw fetch(), so the only complete attach
   point is a global fetch wrapper — the decisions of WHAT to attach are pure functions
   (`authHeaderFor`, `credentialsFor`) so the logic project can test them without window.

   `claimsOf` decodes a token for DISPLAY only — trusting a claim client-side would be
   decorating, not authenticating; the server verifies it before any session exists. */

const WHO_KEY = "aughor_signed_in";            // the email shown in the chip; never a token
const LEGACY_TOKEN_KEY = "aughor_id_token";    // what the page used to keep — cleared on sight
export const AUTH_EXPIRED_EVENT = "aughor-auth-expired";

/** The signed-in person's email, as the page remembers it (display only), or null. */
export function signedInEmail(): string | null {
  try {
    window.localStorage.removeItem(LEGACY_TOKEN_KEY);
    return window.localStorage.getItem(WHO_KEY);
  } catch { return null; }
}

function remember(email: string | null): void {
  try {
    if (email) window.localStorage.setItem(WHO_KEY, email);
    else window.localStorage.removeItem(WHO_KEY);
  } catch { /* private mode */ }
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
 * The pure attach decision for a bearer the page holds in MEMORY (a generic OIDC
 * deployment with no sign-in widget, where someone pastes a token): the Authorization
 * header to add, or null. Only API-base URLs get it; an existing Authorization header
 * always wins (a caller that set its own credential knows better than the wrapper).
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

/**
 * The pure credentials decision: API-base URLs send the session cookie; everything
 * else is left exactly as the caller asked. A caller's own `credentials` wins.
 */
export function credentialsFor(
  url: string, apiBase: string, existing?: RequestCredentials,
): RequestCredentials | undefined {
  if (existing) return existing;
  if (!apiBase || !url.startsWith(apiBase)) return undefined;
  return "include";
}

/**
 * Sign in: present the identity provider's credential ONCE, get the cookie, keep the email.
 * Resolves true when the server opened a session. The token is never stored.
 */
export async function signIn(apiBase: string, idToken: string): Promise<boolean> {
  const res = await fetch(`${apiBase}/auth/session`, {
    method: "POST", credentials: "include", headers: { Authorization: `Bearer ${idToken}` },
  });
  if (!res.ok) return false;
  const body = await res.json().catch(() => null);
  remember(body?.user_id || claimsOf(idToken)?.email || "signed in");
  return true;
}

/** Sign out: end the session on the server, forget the email. Never throws. */
export async function signOut(apiBase: string): Promise<void> {
  try { await fetch(`${apiBase}/auth/session`, { method: "DELETE", credentials: "include" }); } catch { /* offline */ }
  remember(null);
}

let installed = false;

/**
 * Patch window.fetch once: send the session cookie on API calls, and on a 401 while the
 * page believed someone was signed in, forget them and announce — the sign-in control
 * listens and re-offers the button. A 401 with nobody signed in is someone else's problem
 * and passes through untouched.
 */
export function installAuthFetch(apiBase: string): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  const raw = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString()
      : (input as Request).url;
    const credentials = credentialsFor(url, apiBase, init?.credentials);
    const nextInit = credentials ? { ...init, credentials } : init;
    const res = await raw(input, nextInit);
    if (credentials && res.status === 401 && signedInEmail()) {
      remember(null);
      try { window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT)); } catch { /* SSR */ }
    }
    return res;
  };
}


/** SP-14 — the name an accept or reject SENDS. The server no longer reads it: an accept
 *  is recorded under the person the request acts for (`authz.caller`), never a name a
 *  page sends. Kept so older servers still get the signed-in email or the surface. */
export function approverName(surface: string): string {
  return signedInEmail() || surface;
}
