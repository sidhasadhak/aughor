/**
 * names.ts — the one name resolver (docs/UI_UX_STUDY_2026-09-25.md §2.6, 2026-09-25).
 *
 * Arc PX's law is that no machine text reaches an eye. The sweep held on the surfaces PX
 * touched and not on the ones built since: a run card said `Agentic · 8233e4fd`, the audit's
 * AGENT column said `__brief_metric_move__` and `card:2878362c`, a departure's destination was
 * `sb_e2d5c528af66:#aughor_canvas`, and a needs-you card opened with
 * `monitor:Units Sold anomaly watch+automation:Units Sold anomaly watch: …`. Each of these is a
 * KEY the platform composes for itself, and each has a name a reader can act on. This module
 * turns the key into the name; the raw key stays for a title/tooltip and the copy button.
 *
 * Pure, string-only, no React or data-layer coupling — like lib/format.ts, which owns the
 * numbers the way this file owns the names.
 */

/** A connection id as its name. When the list has not answered yet (or the id is not in it) the
 *  fallback is a LABELLED id — `connection 8233e4fd` — never the bare hash, and never nothing. */
export function connectionLabel(
  id: string | null | undefined,
  connections: ReadonlyArray<{ id: string; name: string }>,
): string {
  if (!id) return "";
  const hit = connections.find(c => c.id === id);
  return hit?.name || `connection ${id.slice(0, 8)}`;
}

/** Words out of a snake_case or dunder key: `__brief_metric_move__` → "brief metric move". */
export function keyToWords(key: string): string {
  return key.replace(/^_+|_+$/g, "").replace(/[_-]+/g, " ").trim();
}

/** Who a SQL caller was, for an audit trail: the agent's roster name and what it was doing.
 *  Known callers are named; an unknown dunder still reads as words rather than as a key. */
export function callerLabel(key: string): { agent: string; detail?: string } {
  const k = (key || "").trim();
  if (k.startsWith("card:")) return { agent: "You", detail: "a pinned card" };
  switch (k) {
    case "__brief_metric_move__": return { agent: "Briefer", detail: "metric move check" };
    case "cb2_review":            return { agent: "Curator", detail: "measurement" };
  }
  if (/^__.*__$/.test(k)) return { agent: keyToWords(k) };
  return { agent: k || "—" };
}

/** A departure's destination as the place a reader knows: `sb_e2d5c528af66:#aughor_canvas`
 *  is the `#aughor_canvas` channel (the bot's id stays in `raw`). */
export function destinationLabel(target: string | null | undefined): { label: string; raw: string } {
  const raw = (target || "").trim();
  if (!raw) return { label: "", raw };
  const channel = raw.match(/(#[A-Za-z0-9_-]+)\s*$/);
  if (channel) return { label: channel[1], raw };
  const colon = raw.indexOf(":");
  if (colon > 0 && /^[a-z_]+$/.test(raw.slice(0, colon))) return { label: raw.slice(colon + 1), raw };
  return { label: raw, raw };
}

/** A composite action key as the names it joins: `monitor:Units Sold anomaly watch+automation:Units
 *  Sold anomaly watch` is the monitor "Units Sold anomaly watch" and its automation of the same
 *  name — one name, said once. Two different names read as "A · B". A plain key stays as it is. */
export function actionKeyLabel(key: string): string {
  const parts = (key || "").split("+").map(p => {
    const colon = p.indexOf(":");
    return colon > 0 && /^[a-z_]+$/.test(p.slice(0, colon)) ? p.slice(colon + 1).trim() : p.trim();
  }).filter(Boolean);
  return [...new Set(parts)].join(" · ") || key;
}

/** The needs-you title the API composes — `<action key>: <reasoning>` — split into the subject a
 *  reader recognises and the sentence that follows it. A title with no key in front is all body. */
export function needsYouTitle(title: string): { subject: string | null; body: string; display: string } {
  const t = (title || "").trim();
  const m = t.match(/^([a-z_]+:[^:+]+(?:\+[a-z_]+:[^:+]+)*)(?::\s*([\s\S]*))?$/);
  if (!m) return { subject: null, body: t, display: t };
  const subject = actionKeyLabel(m[1]);
  const body = (m[2] || "").trim();
  return { subject, body, display: body ? `${subject} — ${body}` : subject };
}
