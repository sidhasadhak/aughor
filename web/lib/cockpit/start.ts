/**
 * Starting a cockpit without asking a model (2026-10-09). The usability walk-through found *+ New cockpit* offered only
 * a model's draft, and a cockpit for a process only inside the designer's own session: a person could not start one
 * empty, nor for a process published last week. Here a cockpit starts from the person's words — its name and a first
 * note saying what it is for, since a cockpit holding nothing is refused by its rules — or from a declared process:
 * the board, the open-and-overdue objects, and one object beside them. Either is kept as the person's own version 1.
 */
import { keepCockpit } from "@/lib/api";
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
