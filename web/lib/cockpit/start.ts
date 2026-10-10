/**
 * Starting a cockpit without asking a model (2026-10-09). The usability walk-through found *+ New cockpit* offered only
 * a model's draft, and a cockpit for a process only inside the designer's own session: a person could not start one
 * empty, nor for a process published last week. Here a cockpit starts from the person's words — its name and a first
 * note saying what it is for, since a cockpit holding nothing is refused by its rules — or from a declared process:
 * the board, the open-and-overdue objects, and one object beside them. Either is kept as the person's own version 1.
 *
 * Or, since 2026-10-10, from an object (design-mockups/cockpit-from-object.html): the server proposes what the object
 * holds — its categories as filters, its numbers as figures, a chart of it per day, a table with a detail and its
 * declared actions (`aughor/cockpit/from_object.py`) — the person ticks what they want, and it is laid out here.
 */
import { keepCockpit, type CockpitFromObject } from "@/lib/api";
import { CHART_DAYS, MAX_LABEL, MAX_TITLE } from "@/lib/cockpit/catalog";
import { placeNote, placePiece } from "@/lib/cockpit/edit";
import type { ProcessDetail } from "@/lib/objectTypes";
import { cockpitIdFor } from "@/lib/processDraft";

function base(title: string): unknown {
  return { root: "cockpit", elements: {
    cockpit: { type: "Cockpit", props: { title }, children: ["sec"] },
    sec: { type: "Section", props: { title, columns: 3 }, children: [] },
  } };
}

/** A cockpit holding one note in the person's words — what it is for. */
export function emptyCockpitSpec(title: string, purpose: string): unknown {
  return placeNote(base(title.trim()), purpose);
}

/** A cockpit for a process: its board, and — when it promises something — the objects open and past the promise
 *  (`segment`, the `overdue_<noun>` it derives) with one of them beside the table. */
export function processCockpitSpec(title: string, processId: string, entity: string, segment = ""): unknown {
  let { spec } = placePiece(base(title.trim()), "ProcessBoard", { process: processId, size: "full" });
  if (!segment) return spec;
  const table = placePiece(spec, "ObjectTable", { entity, segment, size: "wide" });
  spec = table.spec;
  if (table.key) spec = placePiece(spec, "ObjectDetail", { follows: table.key, size: "small" }).spec;
  return spec;
}

/** The overdue segment a process's cockpit lists: its first promise's, while cockpit pieces are on. */
export function overdueSegmentOf(process: Pick<ProcessDetail, "stages">): string {
  return process.stages.map(s => s.promise?.overdue_segment ?? "").find(Boolean) ?? "";
}

/** What a cockpit started for ``process`` holds, in a sentence. A process whose promises name no overdue list is one
 *  read while cockpits are not built from the ontology here (the list is offered only then), not one that promises
 *  nothing — the two are said apart. */
export function processCockpitHolds(process: Pick<ProcessDetail, "stages">): string {
  if (overdueSegmentOf(process)) return "Its board, the objects open past the promise, and one of them beside the list.";
  return process.stages.some(s => s.promise)
    ? "Its board — its promises' overdue lists are not offered on this install."
    : "Its board — it promises nothing, so there is nothing to list as overdue.";
}

/** Keep a new cockpit under an id of its own (the server's shape, a random suffix — never another cockpit's), and
 *  remember it as the one to open. Returns its id. */
export async function startCockpit(connectionId: string, title: string, spec: unknown, note: string): Promise<string> {
  const id = cockpitIdFor(title);
  await keepCockpit(connectionId, id, spec, note);
  try { localStorage.setItem(`aughor:cockpit:${connectionId}`, id); } catch { /* the cockpit opens on its own tab */ }
  return id;
}

/** What a person ticked of a cockpit proposed from an object. */
export interface ObjectCockpitChoice {
  filters: string[];
  /** Indexes into the proposal's figures. */
  figures: number[];
  chart: boolean;
  table: boolean;
  actions: string[];
}

/** Everything the proposal offers, ticked. */
export function everything(p: CockpitFromObject): ObjectCockpitChoice {
  return { filters: p.filters.map(f => f.path), figures: p.figures.map((_, i) => i), chart: !!p.chart,
           table: true, actions: p.actions.map(a => a.id) };
}

/** Whether a choice holds a piece to narrow — a cockpit of filters alone is refused by its rules. */
export const holdsAPiece = (c: ObjectCockpitChoice, p: CockpitFromObject): boolean =>
  c.figures.length > 0 || (c.chart && !!p.chart) || c.table;

type El = { type: string; props: Record<string, unknown>; children: string[] };

/** The cockpit a choice makes, laid out as the approved mockup lays it out: the filter column at the left, then one
 *  section named as the cockpit (its heading is not drawn) holding the figures across, the chart below them, and the
 *  table with the chosen object's detail — its actions on it — beside it. */
export function objectCockpitSpec(p: CockpitFromObject, c: ObjectCockpitChoice): unknown {
  const title = p.title.slice(0, MAX_TITLE);
  const label = (s: string) => s.slice(0, MAX_LABEL);
  const els: Record<string, El> = { cockpit: { type: "Cockpit", props: { title }, children: [] } };
  const filters = p.filters.filter(f => c.filters.includes(f.path));
  if (filters.length) {
    els.filters = { type: "ObjectFilters", children: [], props: { entity: p.entity, properties: filters.map(f => (
      { path: f.path, label: label(f.label), ...(f.via ? { via: label(f.via) } : {}) })) } };
    els.cockpit.children.push("filters");
  }
  const sec: El = { type: "Section", props: { title, columns: 3 }, children: [] };
  els.sec = sec;
  els.cockpit.children.push("sec");
  p.figures.forEach((f, i) => {
    if (!c.figures.includes(i)) return;
    els[`figure-${i}`] = { type: "ObjectFigure", children: [], props: {
      entity: p.entity, label: label(f.label), agg: f.agg, ...(f.path ? { path: f.path } : {}), format: f.format, size: "small" } };
    sec.children.push(`figure-${i}`);
  });
  if (c.chart && p.chart) {
    const days = (CHART_DAYS as readonly number[]).includes(p.chart.days) ? p.chart.days : 30;
    els.chart = { type: "ObjectChart", children: [], props: {
      entity: p.entity, label: label(p.chart.label), time: p.chart.time, days, size: "full" } };
    sec.children.push("chart");
  }
  if (c.table) {
    // newest first, by the object's own date, when it has one the table lists
    const newest = p.chart && p.table.columns.includes(p.chart.time) ? { sort: p.chart.time, descending: true } : {};
    els.table = { type: "ObjectTable", children: [], props: {
      entity: p.entity, ...(p.table.columns.length ? { columns: p.table.columns } : {}), ...newest, size: "wide" } };
    els.detail = { type: "ObjectDetail", props: { follows: "table", size: "small" }, children: [] };
    sec.children.push("table", "detail");
    for (const id of p.actions.map(a => a.id).filter(a => c.actions.includes(a))) {
      const key = `action-${id}`.replace(/[^A-Za-z0-9_-]/g, "-").slice(0, 64);
      els[key] = { type: "ActionButton", props: { action: id }, children: [] };
      els.detail.children.push(key);
    }
  }
  return { root: "cockpit", elements: els };
}
