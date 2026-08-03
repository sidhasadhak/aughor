# Scope — a runtime-configurable API base ("bring your own backend")

**Status:** scoped, not started. 2026-08-03.

## The product question this answers

Today `NEXT_PUBLIC_API_URL` is inlined into the JS bundle **at build time**. A Vercel
deployment therefore ships one API URL, identical for every visitor. That is fine for a
hosted demo and useless for the shape this codebase actually has — local DuckDB, local
keys, `data/` gitignored, everything on the user's own machine.

The goal: **Vercel serves the UI; each user points it at their own engine on
`http://localhost:8000`.** Nobody's data leaves their machine, and there is no backend
for us to host.

## What is true today (measured, not assumed)

| Fact | Value |
|---|---|
| `${BASE}` interpolations in `web/lib/api.ts` | **269** |
| `API_BASE` references elsewhere | **40** across **15** files |
| Consumers that are **server** components | **0** — every one is `"use client"` |
| Runtime override today (localStorage etc.) | none |
| `EventSource` constructors | 2 (`lib/events.ts:49`, `components/ActivityStreamPanel.tsx:60`) |
| Candidate settings surfaces | `SystemPanel.tsx`, `ConfigurePanel.tsx`, `OrgSettingsPanel.tsx` |

**The single most important finding: there is no server-side consumer.** Every file that
touches `API_BASE` is a client component or a browser-only module. That is what makes
`localStorage` viable at all — had one `generateMetadata` or route handler used it, the
value would have to resolve on the server where `localStorage` does not exist, and this
would be a much larger change.

`web/lib/config.ts` already documents the intent ("Set NEXT_PUBLIC_API_URL … falls back
to localhost:8000 for local development"), so this extends an existing seam rather than
inventing one.

## The actual change

### 1. `config.ts`: a const becomes a resolver

```ts
export const API_BASE_DEFAULT =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) || "http://localhost:8000";

export function getApiBase(): string { /* localStorage override ?? API_BASE_DEFAULT */ }
export function setApiBase(url: string | null): void { /* persist + notify */ }
```

Precedence, most specific first: **localStorage → `NEXT_PUBLIC_API_URL` → `http://localhost:8000`.**

### 2. The 269 call sites

`lib/api.ts` imports `API_BASE as BASE` **once at module load**, then interpolates it 269
times. Because it is captured at import time, simply changing `config.ts` is not enough —
the old value would be frozen into the module.

Two options:

- **(a) Rename the import to a call.** `const BASE = getApiBase()` inside each function, or
  a module-level `const BASE = () => getApiBase()` and `${BASE()}`. Touches all 269 sites
  but is a single mechanical `sed`-able edit with a compiler to catch misses.
- **(b) Keep `${BASE}` and make `BASE` a getter object.** e.g. a `Proxy`/`toString()` trick
  so template interpolation re-resolves. Zero call-site churn, but it is clever code that
  reads as a constant while behaving as a function — the kind of thing that surprises the
  next reader. **Not recommended.**

Go with (a). 269 sites sounds worse than it is: one pattern, one file, `tsc` proves
completeness.

### 3. The two `EventSource` sites need care

`lib/events.ts:49` builds its URL inside `connect()`, so it re-resolves per connection —
good. But a live `EventSource` holds the OLD base until reconnect, so changing the API base
must **tear down and reconnect** both streams, not just update state. Same for
`ActivityStreamPanel`. This is the one place where "it compiled" will not mean "it works".

### 4. Settings UI

Add to `SystemPanel.tsx` (it already renders backend-derived state and feature flags, so a
"Backend" section belongs there): a text field, a **Test connection** button that pings
`/health` and reports the result, current effective value, and a Reset-to-default.

Do not let a bad URL brick the app: keep the last-known-good value and surface the failure
inline. A user who typos `htp://localhost` must be able to recover without clearing site
data.

### 5. Backend: CORS

Each user's local backend must allow the Vercel origin. `AUGHOR_CORS_ORIGINS` exists.
Document the one-liner; do NOT default it to `*` — the API is authenticated, and a
wildcard plus credentials is exactly the combination that leaks.

## Risks, in the order they will actually bite

1. **A live `EventSource` surviving a base change.** Silent: the UI looks connected and
   streams from the old host. Requires explicit teardown. *Highest risk, lowest visibility.*
2. **Mixed content.** An HTTPS Vercel page calling `http://localhost:8000`. Chrome and
   Firefox treat `localhost` as a trustworthy origin and allow it; **Safari is stricter**.
   Must be verified per browser, not assumed — this determines whether the feature works
   for a chunk of users at all.
3. **CORS misconfiguration** — loud and easy to diagnose, so low risk.
4. **Hydration mismatch.** `localStorage` is unavailable during SSR. Any component
   rendering the base URL as text must handle the first paint. Mitigated by there being no
   server consumers, but the *display* of the value still needs care.
5. **Auth/keys.** If the frontend holds an API key for the backend, pointing at an
   arbitrary URL would send that key to it. Check before shipping: a "bring your own
   backend" field is also a credential-exfiltration surface if a user can be talked into
   pasting someone else's URL.

## What this does NOT change

- **Local development is untouched.** No env var set → the `localhost:8000` fallback fires,
  exactly as today. `npm run dev` + uvicorn behave identically.
- No backend code changes beyond CORS documentation.
- No effect on the Python side, the flag registry, or any test.

## Estimate

| Piece | Size |
|---|---|
| `config.ts` resolver + persistence | small |
| 269 call sites in `lib/api.ts` | mechanical, `tsc`-verified |
| 40 refs across 15 other files | small |
| Two `EventSource` teardown/reconnect paths | **the real work** |
| `SystemPanel` UI + health check | small-to-medium |
| Cross-browser mixed-content verification | must be done live, not reasoned about |

One focused PR. The risk is concentrated in the streaming reconnect and the Safari
question — everything else is mechanical.

## Pre-check before building (do this first)

Per the house rule that the premise gets measured before the scoped thing gets built:

1. **Verify mixed content in Safari** against a real HTTPS page calling
   `http://localhost:8000`. If Safari blocks it outright, the whole feature is
   browser-conditional and that changes the design — possibly to requiring users to run the
   backend behind local HTTPS, which is a much bigger ask. **STILL OPEN** — this needs a
   real Safari against a real HTTPS origin; it cannot be settled by reading specs, and the
   in-app browser pane is Chromium, so it cannot answer it either.

2. ~~Confirm no API key is held client-side~~ — **DONE 2026-08-03, risk is low.**
   `lib/config.ts` and `lib/api.ts` contain no `api_key` / `Authorization` / `Bearer`
   handling, so the client holds no credential to leak into an attacker-supplied URL. The
   backend's shared-secret gate (`_API_KEY`, `aughor/api.py:100`) is **optional and off by
   default** (`AUGHOR_API_KEY` unset) "so the local dev path is unchanged".

   Note the corollary, which is a real gap rather than a risk: because the frontend sends
   no key at all, a user who DOES set `AUGHOR_API_KEY` on their backend gets a frontend
   that cannot talk to it. That is already true today and is not caused by this change —
   but "bring your own backend" makes it much more likely someone tries, so the settings
   panel should either carry an optional key field or say plainly that the gate is
   unsupported from the web UI.
