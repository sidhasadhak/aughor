/**
 * Names a reader can read, laid over a finished spec (2026-11-06).
 *
 * The analyst names columns for itself — `r28`, `r29`, `d` — and every chart printed them: the
 * Daily Briefing's legend read "r28 · r29" over an axis called "Value". The backend reads what
 * each column IS from its SQL (`aughor/answer/series_names.py`) and hands the names over as
 * `{ labels: { column: name }, y_title }`. They are applied HERE, after the spec is resolved,
 * and never as renamed columns: the resolver classifies a grid by its column names, and a column
 * renamed "Oct 28" was read as a date — the chart lost a series (measured on the 09:00 grid).
 *
 * Pure and branch-blind: whatever form the resolver chose, a folded measure key is relabelled
 * right after its fold, and any axis or legend title that is a labelled column's default title
 * takes the name instead.
 */
import { cleanLabel } from "@/lib/format";

export interface SeriesNames {
  labels?: Record<string, string> | null;
  y_title?: string | null;
}

type Obj = Record<string, unknown>;

/** The backend's names, read defensively off a chart config. */
export function namesOf(chartConfig: unknown): SeriesNames | null {
  const names = (chartConfig as { names?: unknown } | null | undefined)?.names;
  if (!names || typeof names !== "object") return null;
  const n = names as SeriesNames;
  const labels = n.labels && typeof n.labels === "object"
    ? Object.fromEntries(Object.entries(n.labels).filter(([, v]) => typeof v === "string" && v.trim()))
    : {};
  const y = typeof n.y_title === "string" && n.y_title.trim() ? n.y_title : null;
  return Object.keys(labels).length || y ? { labels, y_title: y } : null;
}

function lookup(field: string, labels: Record<string, string>): string {
  // Nested ternaries rather than an object literal: the plainest Vega expression there is.
  const arms = Object.entries(labels)
    .map(([k, v]) => `datum[${JSON.stringify(field)}] === ${JSON.stringify(k)} ? ${JSON.stringify(v)} : `)
    .join("");
  return `${arms}datum[${JSON.stringify(field)}]`;
}

export function applyNames<T>(spec: T, names: SeriesNames | null | undefined): T {
  const labels = names?.labels ?? {};
  const yTitle = names?.y_title ?? null;
  if (!Object.keys(labels).length && !yTitle) return spec;
  const out = JSON.parse(JSON.stringify(spec)) as Obj;

  // 1 · a fold of measures: the series key is a column name, relabelled where the fold made it.
  let foldValue: string | null = null;
  const tf = Array.isArray(out.transform) ? (out.transform as Obj[]) : null;
  const at = tf ? tf.findIndex((t) => Array.isArray(t.fold)) : -1;
  if (tf && at >= 0) {
    const as = (tf[at].as as string[] | undefined) ?? ["key", "value"];
    foldValue = as[1] ?? "value";
    const folded = (tf[at].fold as string[]).filter((c) => labels[c]);
    if (folded.length) tf.splice(at + 1, 0, { calculate: lookup(as[0] ?? "key", labels), as: as[0] ?? "key" });
  }

  // 2 · titles: a labelled column's default title becomes its name; a folded value's is the axis.
  const defaults = new Map(Object.entries(labels).map(([col, name]) => [cleanLabel(col), name]));
  const retitle = (holder: Obj | undefined, field: string | undefined) => {
    if (!holder || typeof holder !== "object") return;
    const current = holder.title;
    if (field && labels[field]) holder.title = labels[field];
    else if (field && foldValue && field === foldValue && yTitle) holder.title = yTitle;
    else if (typeof current === "string" && defaults.has(current)) holder.title = defaults.get(current);
    else if (typeof current === "string" && yTitle && current === cleanLabel("value")) holder.title = yTitle;
  };
  const encodings = [out.encoding, ...((out.layer as Obj[] | undefined) ?? []).map((l) => l.encoding)]
    .filter((e): e is Obj => !!e && typeof e === "object");
  for (const enc of encodings) {
    for (const channel of ["x", "y", "theta", "color"]) {
      const c = enc[channel] as Obj | undefined;
      if (!c) continue;
      const field = typeof c.field === "string" ? c.field : undefined;
      if (c.axis && typeof c.axis === "object") retitle(c.axis as Obj, field);
      else if (c.legend && typeof c.legend === "object") retitle(c.legend as Obj, field);
      else if (field && labels[field] && channel !== "color") c.title = labels[field];
    }
  }
  return out as T;
}
