"use client";

/**
 * Global "action approval required" channel (P4, AI-FDE Pillar B).
 *
 * A high-risk mutation guarded by the backend returns HTTP 428 with body:
 *   { detail: { error: "approval_required", action, scope, risk, hint } }
 *
 * We screen every response for that status via a one-time `window.fetch` patch (the
 * same mechanism as the 402 upsell) and surface it as an app-wide approval modal — so
 * every mutating call site is covered with no per-call changes. Approving allowlists the
 * action for its scope; the user then retries and it proceeds.
 */

import { API_BASE as BASE } from "./config";

export interface ApprovalInfo {
  action: string;   // e.g. "connection.delete"
  scope: string;    // e.g. the connection id
  risk: string;     // "high"
  hint: string;     // server-provided guidance
}

type Listener = (info: ApprovalInfo) => void;
const listeners = new Set<Listener>();

/** Subscribe to approval-required events. Returns an unsubscribe fn. */
export function onApprovalRequired(cb: Listener): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

function emit(info: ApprovalInfo) {
  listeners.forEach(l => { try { l(info); } catch { /* one bad listener must not break the channel */ } });
}

/** Allowlist an action for a scope (approve). After this, retrying the action proceeds. */
export async function approveAction(action: string, scope: string): Promise<void> {
  const res = await fetch(`${BASE}/approvals/allow`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, scope }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to approve action");
  }
}

/**
 * If `res` is a 428 approval-required response, fire the approval modal. Non-mutating:
 * clones before reading the body so the caller's own error handling still works.
 */
export function noticeMaybe428(res: Response): void {
  if (res.status !== 428) return;
  res.clone().json().then(body => {
    const d = (body && (body.detail ?? body)) || {};
    if (d.error && d.error !== "approval_required") return; // a different 428, not ours
    emit({
      action: d.action || "this action",
      scope: d.scope || "",
      risk: d.risk || "high",
      hint: d.hint || "This action requires approval before it can run.",
    });
  }).catch(() => {
    emit({ action: "this action", scope: "", risk: "high",
           hint: "This action requires approval before it can run." });
  });
}

/**
 * Patch `window.fetch` once so every response is screened for 428. Idempotent, no-op on
 * the server (SSR), and only acts on status 428 so non-approval traffic is untouched.
 */
export function installApprovalInterceptor(): void {
  if (typeof window === "undefined") return;
  const w = window as unknown as { __aughorApprovalPatched?: boolean; fetch: typeof fetch };
  if (w.__aughorApprovalPatched) return;
  const orig = w.fetch.bind(window);
  w.fetch = async (...args: Parameters<typeof fetch>): Promise<Response> => {
    const res = await orig(...args);
    if (res.status === 428) noticeMaybe428(res);
    return res;
  };
  w.__aughorApprovalPatched = true;
}
