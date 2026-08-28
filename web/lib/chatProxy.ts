/**
 * The chat proxy's shared server-side plumbing — FL-1b.
 *
 * Extracted from `app/api/chat/route.ts` when the resume route arrived: a
 * `route.ts` must not export helpers (Next validates a route file's exports —
 * the `sseFrames.ts` lesson), so anything two routes share lives here instead.
 * Server-side only — the backend URL and key never reach the client bundle.
 */

/** The Python API. */
export function backendBase(): string {
  return (
    process.env.AUGHOR_API_BASE ||
    process.env.NEXT_PUBLIC_API_BASE ||
    "http://127.0.0.1:8000"
  ).replace(/\/+$/, "");
}

export function backendHeaders(): Record<string, string> {
  return {
    "content-type": "application/json",
    accept: "text/event-stream",
    ...(process.env.AUGHOR_SECRET_KEY
      ? { "x-aughor-key": process.env.AUGHOR_SECRET_KEY }
      : {}),
  };
}
