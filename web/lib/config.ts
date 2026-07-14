/**
 * Central API configuration.
 *
 * Set NEXT_PUBLIC_API_URL in your environment to point at a non-local backend:
 *   NEXT_PUBLIC_API_URL=https://api.aughor.io
 *
 * Falls back to localhost:8000 for local development.
 */
export const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000";

/**
 * CK-1: route the unified `/ask` turn through the AG-UI protocol seam (POST /agui/run) instead
 * of the native `/ask` SSE. The adapter (lib/aguiTransport.ts) re-frames AG-UI events back into
 * the same reducer dispatches, so the UI is identical either way — this is a transport swap for
 * dogfooding the seam. Default OFF ⇒ the native transport (byte-identical). Requires the backend
 * flag `agui.endpoint` to be on as well.
 */
export const AUGHOR_AGUI =
  typeof process !== "undefined" && process.env.NEXT_PUBLIC_AUGHOR_AGUI === "1";
