/**
 * The active workspace, as the transport sees it.
 *
 * `api.ts` holds ~390 direct `fetch()` calls and no wrapper, so threading the active
 * workspace through each one is not a change anybody could make correctly — and that is
 * precisely why the workspace boundary leaked: a handful of call sites passed
 * `?workspace_id=`, the rest silently asked for everything in the org.
 *
 * So the workspace rides as a HEADER applied in one place, rather than a parameter every
 * call site has to remember. `installWorkspaceHeader()` wraps the global `fetch` once and
 * stamps `X-Aughor-Workspace` on requests bound for the API; the server binds it to a
 * contextvar for the life of the request and every gate reads it ambiently.
 *
 * Deliberately NOT persisted here. `page.tsx` already stores the last workspace for its
 * own restore, and a second copy in storage could disagree with the one the UI is showing
 * — the header must say what the user is actually looking at, not what they looked at
 * last. Unset, the header is omitted and the server stays unscoped: exactly today's
 * behaviour, so nothing breaks before the app has chosen.
 */
import { getApiBase } from "./config";

let activeWorkspace = "";

/** Point the transport at a workspace. Called whenever the UI's selection changes. */
export function setActiveWorkspace(id: string | undefined | null): void {
  activeWorkspace = id || "";
}

export function getActiveWorkspace(): string {
  return activeWorkspace;
}

let installed = false;

/**
 * Stamp `X-Aughor-Workspace` on every request to the API base. Idempotent, and a no-op
 * on the server (there is no shared global `fetch` to patch per user there, and a header
 * set process-wide would be one user's workspace applied to everyone's requests).
 */
export function installWorkspaceHeader(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  const original = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    if (!activeWorkspace) return original(input, init);
    let url = "";
    try {
      url = typeof input === "string" ? input
          : input instanceof URL ? input.href
          : (input as Request).url;
    } catch { return original(input, init); }

    // Only our own API. A relative URL is same-origin and safe; anything else could be a
    // third party, and a workspace id is not theirs to receive.
    const base = getApiBase();
    const ours = url.startsWith(base) || url.startsWith("/");
    if (!ours) return original(input, init);

    // A caller that set the header itself wins — never overwrite an explicit choice.
    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined),
    );
    if (!headers.has("X-Aughor-Workspace")) {
      headers.set("X-Aughor-Workspace", activeWorkspace);
    }
    return original(input, { ...init, headers });
  };
}
