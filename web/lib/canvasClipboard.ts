/**
 * DS-4 · what ⌘C is holding.
 *
 * Module state, not the system clipboard. The system one is refused in plenty of ordinary
 * situations — an unfocused tab, a denied permission, a non-secure origin — and this
 * codebase already carries three separate fallbacks for that (`AgentSlackDoor` selects the
 * text so a person can copy it by hand). None of that is worth paying for a gesture whose
 * whole job is moving a step between two canvases in the same tab: module state needs no
 * permission, cannot be refused, and survives navigating from one automation to another,
 * which is exactly the reach this needs.
 *
 * What it deliberately does NOT do is survive a reload or reach a second tab. A step
 * copied yesterday, pasted into a chain whose steps have since been renamed, is precisely
 * the silently-wrong paste `pasteEffect` exists to refuse — and the shorter the clipboard
 * lives, the fewer of those there are to refuse.
 */
import type { AutoEffect } from "@/lib/api";

let held: AutoEffect | null = null;

/** Hold a DEEP copy: the draft it came from keeps being edited, and a clipboard that
 *  shared structure with it would paste whatever the original had become by then. */
export function copyToCanvasClipboard(step: AutoEffect): void {
  held = JSON.parse(JSON.stringify(step)) as AutoEffect;
}

/** What is held, deep-copied again so two pastes cannot share one object. */
export function canvasClipboard(): AutoEffect | null {
  return held ? (JSON.parse(JSON.stringify(held)) as AutoEffect) : null;
}
