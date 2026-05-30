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
