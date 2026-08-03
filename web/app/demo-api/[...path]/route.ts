/**
 * The demo backend: a frozen recording, served.
 *
 * A hosted deployment has no engine behind it — the Python API is local-first and does not
 * fit a serverless function. So in demo posture `getApiBase()` points here, and this handler
 * answers the read routes from a recording captured off a real backend
 * (`aughor/demo/record_api.py`). The visitor sees genuine completed work: the connection,
 * its briefing, its curated investigations and its context graph — with no backend, no API
 * key and no spend. Generation was paid once; consumption is free.
 *
 * Two rules make this honest rather than a mock:
 *
 *  1. **Recorded or refused.** The recording is an explicit allowlist. Anything outside it —
 *     asking a new question, editing an ontology, running an investigation — gets 501 and a
 *     message naming what to do about it, never an empty list. An empty list would read as
 *     "there is nothing here", which is the exact failure this whole path exists to fix.
 *  2. **Nothing is synthesised.** Every byte was recorded from a real response, so shapes
 *     cannot drift from the API the UI actually expects.
 */
import recording from "../../../public/demo-api.json";

type Recording = {
  version: number;
  connection_id: string;
  routes: Record<string, unknown>;
};

const REC = recording as Recording;

/** This build's recording format. A future recording is refused rather than mis-read —
 *  the same rule `pack.py` and `interchange.py` already apply to their artifacts. */
const RECORDING_VERSION = 1;

const REFUSAL =
  "This demo shows completed analyses. To ask new questions, connect your own backend " +
  "in Settings → System → Backend.";

/** Rebuild the request path exactly as it was recorded: `/segments?sorted&query`.
 *  Query order is normalised on both sides so a caller that happens to emit its params in a
 *  different order still hits the recording rather than falling through to the refusal. */
function recordedKey(method: string, segments: string[], search: URLSearchParams): string {
  const path = "/" + segments.join("/");
  const params = [...search.entries()].sort(([a], [b]) => a.localeCompare(b));
  const qs = params.length
    ? "?" + params.map(([k, v]) => `${k}=${v}`).join("&")
    : "";
  return `${method} ${path}${qs}`;
}

function lookup(method: string, segments: string[], search: URLSearchParams): unknown {
  const routes = REC.routes || {};
  const exact = recordedKey(method, segments, search);
  if (exact in routes) return routes[exact];
  // Fall back to the path alone. A caller may add a param the recording did not carry
  // (a cache-buster, a refresh flag); the frozen answer is still the right one, and a
  // refusal here would be wrong.
  const bare = `${method} /${segments.join("/")}`;
  return bare in routes ? routes[bare] : undefined;
}

function serve(method: string, segments: string[], url: URL): Response {
  // A live event stream is the one thing a frozen recording cannot be. 204 is the answer
  // the EventSource spec defines for "done, do not reconnect" — a 501 here would leave the
  // browser retrying a route that will never exist, every few seconds, forever.
  if (segments.join("/") === "events/stream") {
    return new Response(null, { status: 204 });
  }
  if (REC.version > RECORDING_VERSION) {
    return Response.json(
      { detail: `Recording is version ${REC.version}; this build understands ${RECORDING_VERSION}.` },
      { status: 500 },
    );
  }
  const body = lookup(method, segments, url.searchParams);
  if (body === undefined) {
    return Response.json(
      { detail: REFUSAL, demo: true, route: `${method} /${segments.join("/")}` },
      { status: 501 },
    );
  }
  return Response.json(body, {
    // The recording is immutable for the life of a deployment, so it caches hard. A new
    // recording ships as a new build, which invalidates this along with everything else.
    headers: { "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400" },
  });
}

export async function GET(request: Request, ctx: RouteContext<"/demo-api/[...path]">) {
  const { path } = await ctx.params;
  return serve("GET", path, new URL(request.url));
}

export async function POST(request: Request, ctx: RouteContext<"/demo-api/[...path]">) {
  const { path } = await ctx.params;
  return serve("POST", path, new URL(request.url));
}

/** Everything that changes state. Recorded reads never arrive here, so a plain refusal is
 *  the whole implementation — and it is the product surface a visitor is meant to hit. */
function refuse(): Response {
  return Response.json({ detail: REFUSAL, demo: true }, { status: 501 });
}

export const PUT = refuse;
export const PATCH = refuse;
export const DELETE = refuse;
