"use client";

/**
 * Global "upgrade required" channel.
 *
 * A gated API call returns HTTP 402 with a `capability_locked` body:
 *   { detail: { error, capability, current_tier, upgrade_hint } }
 *
 * We screen every response for that status via a one-time `window.fetch` patch and
 * surface it as an app-wide upsell modal — so new gates are covered automatically,
 * with no change to the ~100 fetch call sites in `api.ts`.
 */

export interface UpgradeInfo {
  capability: string;   // raw capability value, e.g. "analysis.deep"
  feature: string;      // friendly label, e.g. "Deep Analysis"
  currentTier: string;  // e.g. "free"
  requiredTier: string; // e.g. "Pro"
  hint: string;         // server-provided upgrade_hint
}

// Friendly labels for the capabilities we gate (fallback prettifies the raw value).
const FEATURE_LABELS: Record<string, string> = {
  "analysis.deep": "Deep Analysis",
  "exploration.auto": "Autonomous Exploration",
  "intel.domain": "Domain Intelligence",
  "fix.save": "Save & Repair",
  "ontology.edit": "Ontology Editing",
  "semantic.edit": "Semantic Layer Editing",
  "monitors": "Monitors",
  "metrics.define": "Metric Definitions",
  "actions.hub": "Action Hub",
  "briefs.scheduled": "Scheduled Briefs",
  "playbook": "Playbook",
  "federation": "Multi-Connection Federation",
};

// Which plan a capability belongs to (everything we gate today is Pro; the
// enterprise-only set is listed so the CTA names the right plan).
const ENTERPRISE_CAPS = new Set([
  "temporal.tier3", "semantic.compiler", "security.suite",
  "eval.suite", "rbac.sso", "audit.export", "query.cancel",
]);

function prettify(cap: string): string {
  return FEATURE_LABELS[cap]
    ?? cap.split(/[._]/).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function requiredTierFor(cap: string): string {
  return ENTERPRISE_CAPS.has(cap) ? "Enterprise" : "Pro";
}

type Listener = (info: UpgradeInfo) => void;
const listeners = new Set<Listener>();

/** Subscribe to upgrade-required events. Returns an unsubscribe fn. */
export function onUpgradeRequired(cb: Listener): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

function emit(info: UpgradeInfo) {
  // A misbehaving listener must not break the channel for the others.
  listeners.forEach(l => { try { l(info); } catch { /* swallow listener error */ } });
}

/**
 * If `res` is a 402 capability-locked response, fire the upsell. Non-mutating: clones
 * before reading the body, so the caller's own `res.json()` still works.
 */
export function noticeMaybe402(res: Response): void {
  if (res.status !== 402) return;
  res.clone().json().then(body => {
    const d = (body && (body.detail ?? body)) || {};
    if (d.error && d.error !== "capability_locked") return; // a different 402, not ours
    const cap: string = d.capability || "this feature";
    emit({
      capability: cap,
      feature: prettify(cap),
      currentTier: d.current_tier || "free",
      requiredTier: requiredTierFor(cap),
      hint: d.upgrade_hint || `${prettify(cap)} requires a higher plan.`,
    });
  }).catch(() => {
    emit({
      capability: "this feature", feature: "This feature",
      currentTier: "free", requiredTier: "Pro",
      hint: "This feature requires a higher plan.",
    });
  });
}

/**
 * Patch `window.fetch` once so every response is screened for 402. Idempotent and a
 * no-op on the server (SSR). Safe for non-API traffic: it only acts on status 402.
 */
export function installUpsellInterceptor(): void {
  if (typeof window === "undefined") return;
  const w = window as unknown as { __aughorUpsellPatched?: boolean; fetch: typeof fetch };
  if (w.__aughorUpsellPatched) return;
  const orig = w.fetch.bind(window);
  w.fetch = async (...args: Parameters<typeof fetch>): Promise<Response> => {
    const res = await orig(...args);
    if (res.status === 402) noticeMaybe402(res);
    return res;
  };
  w.__aughorUpsellPatched = true;
}
