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
 * action for its scope, and the request that was held is sent again — the call site's own
 * `await` resolves with that answer, so a person never presses the same button twice
 * (the usability walk-through, 2026-10-09: "declare, approve, declare again"). Cancelling
 * hands the call site the original 428, which it says in words.
 */

import { getApiBase } from "./config";
export interface ApprovalInfo {
  action: string;   // e.g. "connection.delete"
  scope: string;    // e.g. the connection id
  risk: string;     // "high"
  hint: string;     // server-provided guidance
  /** Settles the request that was held: true once approved (it is sent again), false otherwise. */
  settle?: (approved: boolean) => void;
  /** Whether the held request can be sent again as it was — false for a body that cannot be re-read. */
  replays?: boolean;
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
  const res = await fetch(`${getApiBase()}/approvals/allow`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, scope }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to approve action");
  }
}

const ASK_ANYWAY = "This action requires approval before it can run.";

/** The approval a 428 asks for, or null when it is a different 428. Clones before reading, so the caller's own
 *  error handling still reads the body. */
async function approvalOf(res: Response): Promise<ApprovalInfo | null> {
  try {
    const body = await res.clone().json();
    const d = (body && (body.detail ?? body)) || {};
    if (d.error && d.error !== "approval_required") return null; // a different 428, not ours
    return { action: d.action || "this action", scope: d.scope || "", risk: d.risk || "high", hint: d.hint || ASK_ANYWAY };
  } catch {
    return { action: "this action", scope: "", risk: "high", hint: ASK_ANYWAY };
  }
}

/** If `res` is a 428 approval-required response, open the approval modal — nothing is held or sent again. */
export function noticeMaybe428(res: Response): void {
  if (res.status !== 428) return;
  void approvalOf(res).then(info => { if (info) emit(info); });
}

/** A request is sent again only as it was: a URL or a string, and a body that is a string (or none). */
function replayable(args: Parameters<typeof fetch>): boolean {
  const [input, init] = args;
  if (typeof input !== "string" && !(input instanceof URL)) return false;
  const body = init?.body;
  return body == null || typeof body === "string";
}

/** One decision per action and scope: two requests held for the same approval wait on the same answer. */
const deciding = new Map<string, Promise<boolean>>();

function decide(info: ApprovalInfo, replays: boolean): Promise<boolean> {
  const key = `${info.action}\u0000${info.scope}`;
  const open = deciding.get(key);
  if (open) return open;
  const asked = new Promise<boolean>(resolve => {
    let settled = false;
    emit({ ...info, replays, settle: approved => { if (!settled) { settled = true; resolve(approved); } } });
  }).finally(() => deciding.delete(key));
  deciding.set(key, asked);
  return asked;
}

/**
 * Patch `window.fetch` once so every response is screened for 428. Idempotent, no-op on the server (SSR), and only acts
 * on status 428 so other traffic is untouched. An approval-required 428 is HELD while a person decides: approved, the
 * same request is sent once more through the unpatched fetch (so a second 428 is returned as it is, never looped);
 * cancelled — or with nobody listening, or a body that cannot be re-read — the original 428 is returned.
 */
export function installApprovalInterceptor(): void {
  if (typeof window === "undefined") return;
  const w = window as unknown as { __aughorApprovalPatched?: boolean; fetch: typeof fetch };
  if (w.__aughorApprovalPatched) return;
  const orig = w.fetch.bind(window);
  w.fetch = async (...args: Parameters<typeof fetch>): Promise<Response> => {
    const res = await orig(...args);
    if (res.status !== 428) return res;
    const info = await approvalOf(res);
    if (!info) return res;
    if (!listeners.size) return res;
    const replays = replayable(args);
    const approved = await decide(info, replays);
    return approved && replays ? orig(...args) : res;
  };
  w.__aughorApprovalPatched = true;
}
