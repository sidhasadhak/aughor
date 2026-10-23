/**
 * Shapes in the starter (Arc AP-5; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.6; design-mockups/cockpit-builder.html
 * screens 1 and 7). The server says which shapes an object fits and reads what each is laid out from
 * (`aughor/dashboards/shapes.py`); here each shape becomes the dashboard a person keeps as their own first version — a spec
 * the rules accept, every piece changeable after:
 *
 *   - a queue: the objects waiting past the promise in a window the author sets, figures that switch the list, a filter
 *     column counting within what waits, a chart of what waits, the list oldest first — a click chooses, a tick
 *     collects — the chosen object, its lines, and the actions on it filled from the chosen one;
 *   - a map: the objects placed by their coordinates, a click opening the chosen one beside it, and a list of them;
 *   - one object: one found by its name, its properties, and a table of each kind of object that links to it;
 *   - a timeline: each object a bar between its two moments, the chosen one beside it;
 *   - an overview: today's starter (`objectDashboardSpec`).
 *
 * Sizes are named (small, wide, full): a shape needs no grid, so it starts on an install that builds dashboards in place
 * or not.
 */
import type { DashboardFromObject, ShapeName, ShapeSignals } from "@/lib/api";
import { CHART_DAYS, MAX_LABEL, MAX_TITLE, WIRE_NAME } from "@/lib/dashboards/catalog";
import { everything, objectDashboardSpec } from "@/lib/dashboards/start";

type El = { type: string; props: Record<string, unknown>; children: string[] };
type Spec = { root: string; elements: Record<string, El>; sets?: Record<string, unknown>; values?: Record<string, unknown> };

const words = (id: string) => id.replace(/[_-]+/g, " ");
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const plural = (w: string) => (/y$/i.test(w) && !/(ay|ey|oy|uy)$/i.test(w) ? `${w.slice(0, -1)}ies` : /(s|x|z|ch|sh)$/i.test(w) ? `${w}es` : `${w}s`);
/** Words kept to `max` characters, cut between words. */
function upTo(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max + 1);
  return cut.slice(0, Math.max(cut.lastIndexOf(" "), 1)).trim();
}
/** A choice's or a set's name from words: "chosen order", kept to the catalog's name. */
function wire(text: string): string {
  const w = text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").replace(/^[^a-z]+/, "").slice(0, 40) || "chosen";
  return WIRE_NAME.test(w) ? w : "chosen";
}

/** What each shape is called, and what it is for — the cards of the shapes strip. */
export const SHAPES: Record<ShapeName, { label: string; says: string }> = {
  queue: { label: "Queue", says: "Things that wait for a person, oldest first, with what to do about each." },
  map: { label: "Map", says: "Each one placed where it is; a click opens it beside the map." },
  one: { label: "One object", says: "One found by its name, with everything that links to it." },
  timeline: { label: "Timeline", says: "Each one a bar from one moment to the next." },
  overview: { label: "Overview", says: "Figures, how they move, and what they break into." },
};

/** The filter column a shape opens with: the proposal's own categories, counting within `set` when it names one. */
function filterColumn(p: DashboardFromObject, set?: string): El | null {
  const props = p.filters.slice(0, 3).map(f => ({ path: f.path, label: upTo(f.label, MAX_LABEL), ...(f.via ? { via: upTo(f.via, MAX_LABEL) } : {}) }));
  return props.length ? { type: "ObjectFilters", children: [], props: { entity: p.entity, properties: props, ...(set ? { set } : {}) } } : null;
}

/** The buttons of the actions a shape can fill — each object parameter of the entity's own from the chosen one, each
 *  value asked in the form — reading `after` again once it ran. */
function buttons(s: ShapeSignals, chosen: string, after?: string): El | null {
  if (!s.actions.length) return null;
  return {
    type: "ActionButtons", children: [], props: {
      size: "small",
      buttons: s.actions.slice(0, 6).map((a, i) => ({
        action: a.id, label: upTo(a.label, MAX_LABEL), ...(i === 0 ? { primary: true } : {}),
        params: Object.fromEntries(a.params.map(x => [x.name, x.source === "chosen" ? { from: chosen } : { ask: true }])),
        ...(after ? { after: { read: [after] } } : {}),
      })),
    },
  };
}

function cockpit(title: string, filters: El | null, section: El, rest: Record<string, El>, extra: Partial<Spec> = {}): Spec {
  const elements: Record<string, El> = { cockpit: { type: "Cockpit", props: { title: upTo(title, MAX_TITLE) }, children: [] } };
  if (filters) { elements.filters = filters; elements.cockpit.children.push("filters"); }
  elements.desk = section;
  elements.cockpit.children.push("desk");
  return { root: "cockpit", elements: { ...elements, ...rest }, ...extra };
}

/** A queue: what waits past the promise — or on a status not yet final — oldest first, with what to do about each. */
export function queueSpec(p: DashboardFromObject, s: ShapeSignals): Spec | null {
  const q = s.queue;
  if (!q) return null;
  const chosen = wire(`chosen ${s.entity}`), ticked = wire(`ticked ${s.entity}`);
  const els: Record<string, El> = {};
  const sets: Record<string, unknown> = {};
  const values: Record<string, unknown> = {};
  const desk: El = { type: "Section", props: { title: "", columns: 3 }, children: [] };
  let title = `${s.name} queue`;
  if (q.kind === "promise") {
    title = `${cap(words(q.noun))} desk`;
    values.window = { label: "Window", kind: "days", value: s.window };
    sets.placed = { label: "Placed", entity: s.entity, where: [{ path: q.placed, op: "in_last", value_from: "window" }] };
    sets.waiting = { label: "Waiting", from: "placed", segment: q.overdue };
    els["fig-waiting"] = { type: "ObjectFigure", children: [], props: { set: "waiting", of: "placed", shows: "shown", label: "Waiting past the promise", agg: "count", size: "small" } };
    desk.children.push("fig-waiting");
    if (q.reached) {
      const stage = cap(words(q.stage));
      sets.done = { label: upTo(stage, MAX_LABEL), from: "placed", where: [{ path: q.reached, op: "not_null" }] };
      if (q.late) {
        sets.late = { label: upTo(`${stage} late`, MAX_LABEL), from: "done", segment: q.late };
        els["fig-late"] = { type: "ObjectFigure", children: [], props: { set: "late", of: "done", shows: "shown", label: upTo(`${stage} late`, MAX_LABEL), agg: "count", size: "small" } };
        desk.children.push("fig-late");
      }
      els["fig-done"] = { type: "ObjectFigure", children: [], props: { set: "done", of: "placed", shows: "shown", label: upTo(stage, MAX_LABEL), agg: "count", size: "small" } };
      desk.children.push("fig-done");
    }
    // what waits holds one status — the stage it waits at — so the chart splits by a category that varies within it
    const split = p.filters.find(f => f.path && !/(^|[._])(status|state|stage)$/i.test(f.path))?.path;
    const days = (CHART_DAYS as readonly number[]).includes(s.window) ? s.window : 14;
    els.chart = { type: "ObjectChart", children: [], props: { set: "waiting", label: "Waiting, by the day placed", time: q.placed, days, ...(split ? { split, top: 3 } : {}), size: "full" } };
    desk.children.push("chart");
  } else {
    const final = q.final.join(" or ");
    sets.waiting = { label: upTo(`Not ${final}`, MAX_LABEL), entity: s.entity, where: [{ path: q.status, op: "not_in", values: q.final }] };
    els["fig-waiting"] = { type: "ObjectFigure", children: [], props: { set: "waiting", label: upTo(`Not ${final}`, MAX_LABEL), agg: "count", size: "small" } };
    desk.children.push("fig-waiting");
  }
  const time = q.kind === "promise" ? q.placed : "";
  const columns = [...new Set([time, ...p.table.columns].filter(Boolean))].slice(0, 4);
  els.table = { type: "ObjectTable", children: [], props: {
    set: "waiting", ...(q.kind === "promise" ? { set_from: "shown" } : {}), chooses: chosen, ticks: ticked,
    ...(columns.length ? { columns } : {}), ...(time ? { sort: time, descending: false } : {}), size: "wide" } };
  els.detail = { type: "ObjectDetail", children: [], props: { follows: chosen, size: "small" } };
  desk.children.push("table", "detail");
  if (s.lines) {
    sets.lines = { label: upTo(`Its ${plural(s.lines.label.toLowerCase())}`, MAX_LABEL), entity: s.lines.entity, linked_to: { choice: chosen, path: s.lines.path } };
    els.lines = { type: "ObjectTable", children: [], props: { set: "lines", size: "wide" } };
    desk.children.push("lines");
  }
  const acts = buttons(s, chosen, "waiting");
  if (acts) { els.buttons = acts; desk.children.push("buttons"); }
  desk.props.title = upTo(title, MAX_TITLE);
  return cockpit(title, filterColumn(p, "waiting"), desk, els, { sets, ...(Object.keys(values).length ? { values } : {}) });
}

/** A map: each object placed by its coordinates, the one a click chooses beside it, and a list of them. */
export function mapSpec(p: DashboardFromObject, s: ShapeSignals): Spec | null {
  if (!s.places) return null;
  const title = `${plural(s.name)} on a map`;
  const label = s.label;
  const desk: El = { type: "Section", props: { title: upTo(title, MAX_TITLE), columns: 3 }, children: ["map", "detail", "list"] };
  const els: Record<string, El> = {
    map: { type: "ObjectMap", children: [], props: { entity: s.entity, lat: s.places.lat, lng: s.places.lng, ...(label ? { label } : {}), size: "large" } },
    detail: { type: "ObjectDetail", children: [], props: { follows: "map", size: "small" } },
    list: { type: "ObjectTable", children: [], props: { entity: s.entity, ...(p.table.columns.length ? { columns: p.table.columns.slice(0, 4) } : {}), size: "full" } },
  };
  return cockpit(title, filterColumn(p), desk, els);
}

/** One object: one found by its name, its properties beside it, and a table of each kind of object that links to it. */
export function oneObjectSpec(p: DashboardFromObject, s: ShapeSignals): Spec | null {
  if (!s.one) return null;
  const chosen = wire(`chosen ${s.entity}`);
  const title = `${/^[aeiou]/i.test(s.name) ? "An" : "A"} ${s.name.toLowerCase()}`;
  const desk: El = { type: "Section", props: { title: upTo(title, MAX_TITLE), columns: 3 }, children: ["choose", "detail"] };
  const els: Record<string, El> = {
    choose: { type: "ChooseOne", children: [], props: { entity: s.entity, chooses: chosen, label: s.one.label, size: "small" } },
    detail: { type: "ObjectDetail", children: [], props: { follows: chosen, size: "wide" } },
  };
  const sets: Record<string, unknown> = {};
  s.one.links.forEach((l, i) => {
    const name = wire(`its ${l.entity}`) + (sets[wire(`its ${l.entity}`)] ? `-${i}` : "");
    const label = upTo(`Its ${plural(l.label.toLowerCase())}`, MAX_LABEL);
    sets[name] = { label, entity: l.entity, linked_to: { choice: chosen, path: l.path } };
    // a kind that declares no key is counted — how many events this customer has — never listed
    els[`linked-${i}`] = l.listable === false
      ? { type: "ObjectFigure", children: [], props: { set: name, label, agg: "count", size: "small" } }
      : { type: "ObjectTable", children: [], props: { set: name, size: "full" } };
    desk.children.push(`linked-${i}`);
  });
  return cockpit(title, null, desk, els, { sets });
}

/** A timeline: each object a bar between its two moments, the chosen one beside it. */
export function timelineSpec(p: DashboardFromObject, s: ShapeSignals): Spec | null {
  if (!s.moments) return null;
  const title = `${plural(s.name)} over time`;
  const desk: El = { type: "Section", props: { title: upTo(title, MAX_TITLE), columns: 3 }, children: ["timeline", "detail"] };
  const els: Record<string, El> = {
    timeline: { type: "ObjectTimeline", children: [], props: { entity: s.entity, start: s.moments.start, end: s.moments.end, ...(s.label ? { label: s.label } : {}), size: "wide" } },
    detail: { type: "ObjectDetail", children: [], props: { follows: "timeline", size: "small" } },
  };
  return cockpit(title, filterColumn(p), desk, els);
}

/** The spec a shape makes of a proposal — null when the proposal holds nothing that shape is laid out from. */
export function shapeSpec(shape: ShapeName, p: DashboardFromObject): unknown {
  const s = p.signals;
  if (shape === "overview" || !s) return objectDashboardSpec(p, everything(p));
  return shape === "queue" ? queueSpec(p, s) : shape === "map" ? mapSpec(p, s) : shape === "one" ? oneObjectSpec(p, s) : timelineSpec(p, s);
}

/** What a shape holds, said as the mockup lists it under "It holds" — a line per piece, with what it reads. */
export function shapeHolds(shape: ShapeName, p: DashboardFromObject): string[] {
  const s = p.signals;
  if (shape === "overview" || !s) return [];
  const spec = shapeSpec(shape, p) as Spec | null;
  if (!spec) return [];
  const out: string[] = [];
  for (const [key, el] of Object.entries(spec.elements)) {
    const pr = el.props;
    if (el.type === "ObjectFilters") out.push(`Filter column · ${(pr.properties as { label: string }[]).map(x => x.label).join(" · ")}`);
    else if (el.type === "ObjectFigure") out.push(`Figure · ${String(pr.label)}`);
    else if (el.type === "ObjectChart") out.push(`Chart · ${String(pr.label)}`);
    else if (el.type === "ObjectTable") out.push(key === "table" ? `The list, ${pr.sort ? "oldest first" : "a page at a time"} — a click chooses, a tick collects` : `Table · ${String((spec.sets?.[String(pr.set)] as { label?: string } | undefined)?.label ?? words(String(pr.entity ?? "")))}`);
    else if (el.type === "ObjectDetail") out.push("The chosen one — its properties");
    else if (el.type === "ActionButtons") out.push(`Buttons · ${(pr.buttons as { label?: string; action: string }[]).map(b => b.label || words(b.action)).join(" · ")} — filled from the chosen one`);
    else if (el.type === "ObjectMap") out.push("Map · each placed by its latitude and longitude");
    else if (el.type === "ObjectTimeline") out.push(`Timeline · ${words(String(pr.start))} → ${words(String(pr.end))}`);
    else if (el.type === "ChooseOne") out.push(`Choose one · found by ${words(String(pr.label))}`);
  }
  return out;
}
