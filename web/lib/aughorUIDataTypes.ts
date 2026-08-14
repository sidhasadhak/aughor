/**
 * Aughor's `data-*` part vocabulary, as an AI SDK `UIDataTypes` map — CI-1d.
 *
 * The SDK's streaming union carries structured payloads through
 * `DataUIMessageChunk<DATA_TYPES>`, which is a MAPPED type:
 *
 *     ValueOf<{ [NAME in keyof DATA_TYPES & string]:
 *                 { type: `data-${NAME}`; id?: string; data: DATA_TYPES[NAME] } }>
 *
 * so `data-${string}` alone does not satisfy it. A part type is only well-typed
 * if its NAME is a key of a declared map — which is the whole reason this file
 * exists rather than the adapter casting to `data-${string}` and moving on.
 *
 * THE NAMES ARE MEASURED, NOT GUESSED. They were extracted from the lowercase
 * (wire-frame) arm of `investigationStream.ts`'s dispatch, which is the
 * authority on what the backend actually emits; the C1 spike's hand-written set
 * covered 14 of them. Frames that legitimately change no rendered state live in
 * that module's `UNRENDERED_FRAMES` and are deliberately absent here — a frame
 * being unrendered is a decision, and this map is the place it stays visible.
 *
 * `unknown` rather than concrete shapes: this map's job is to make the part
 * NAMES a closed, checkable set. The payload shapes are owned by
 * `investigationStream.ts`, and duplicating them here would create a second
 * authority that drifts — the failure this whole programme keeps finding.
 */

/*
 * `type` aliases, not `interface`. The SDK constrains its map to
 * `UIDataTypes = Record<string, unknown>`, and a TypeScript INTERFACE does not
 * get an implicit index signature — only a type alias does. Declared as
 * interfaces these fail the constraint with "Index signature for type 'string'
 * is missing", which reads like a missing key and is actually a declaration-form
 * problem. Keep them as aliases.
 */

/** Report frames — each carries a whole rendered artifact, never a delta. */
export type AughorReportData = {
  "answer_report": unknown;
  "ada_report": unknown;
  "report": unknown;
  "dossier_report": unknown;
  "overview_report": unknown;
  "explore_report": unknown;
}

/** Advisory frames — evidence and provenance that accompany an answer. */
export type AughorEvidenceData = {
  "route": unknown;
  "sql": unknown;
  "columns": unknown;
  "rows": unknown;
  "chart_type": unknown;
  "chart_config": unknown;
  "tables_used": unknown;
  "queries_executed": unknown;
  "figure": unknown;
  "receipt_id": unknown;
  "context_assembled": unknown;
  "guard_receipt": unknown;
  "playbook_refs": unknown;
  "hypotheses": unknown;
  "score": unknown;
  "analysis": unknown;
}

/** Interaction frames — the turn is asking the user for something. */
export type AughorGateData = {
  "clarify": unknown;
  "clarify_pending": unknown;
  "clarifying_questions": unknown;
  "plan_pending": unknown;
  "escalate": unknown;
  "followups": unknown;
}

/** Progress frames — what the run is doing right now. */
export type AughorProgressData = {
  "agent": unknown;
  "status": unknown;
  "phase_complete": unknown;
  "phase_progress": unknown;
  "converse_step": unknown;
  "mode": unknown;
  "inspect_warning": unknown;
}

/**
 * The escape hatch — a frame the backend emits that this map does not name.
 *
 * A closed map and a no-swallow rule look contradictory: an undeclared name
 * cannot be typed as `data-${that name}`, so forwarding it means either casting
 * a lie or dropping the frame. Neither is acceptable — the cast fails at the
 * CONSUME site anyway (TS knows the union has no such arm), and dropping is the
 * failure mode this whole programme keeps finding.
 *
 * So an undeclared frame rides under a DECLARED name, carrying its own event
 * name in the payload. The types stay closed and honest, nothing is swallowed,
 * and the shell can render one fallback for the whole class while still being
 * able to say which frame it was. A backend that grows a frame renders as
 * "unrecognised: <name>" instead of vanishing.
 */
export type AughorEscapeHatchData = {
  "unknown_frame": { event: string; payload: Record<string, unknown> };
}

export type AughorUIDataTypes = AughorReportData &
  AughorEvidenceData &
  AughorGateData &
  AughorProgressData &
  AughorEscapeHatchData;

/** The report frames, as a runtime set — terminal, and each replaces the stream. */
export const REPORT_FRAMES = new Set<keyof AughorReportData>([
  "answer_report", "ada_report", "report",
  "dossier_report", "overview_report", "explore_report",
]);

/**
 * Every declared part name, at runtime. Derived from one literal list that the
 * type above is checked against, so a name added to the types and forgotten
 * here is a COMPILE error rather than a part that silently falls through to the
 * unknown-frame path.
 */
const DECLARED = [
  "answer_report", "ada_report", "report", "dossier_report", "overview_report",
  "explore_report",
  "route", "sql", "columns", "rows", "chart_type", "chart_config", "tables_used",
  "queries_executed", "figure", "receipt_id", "context_assembled", "guard_receipt",
  "playbook_refs", "hypotheses", "score", "analysis",
  "clarify", "clarify_pending", "clarifying_questions", "plan_pending", "escalate",
  "followups",
  "agent", "status", "phase_complete", "phase_progress", "converse_step", "mode",
  "inspect_warning",
  "unknown_frame",
] as const satisfies readonly (keyof AughorUIDataTypes)[];

export const DECLARED_DATA_PARTS: ReadonlySet<string> = new Set(DECLARED);

/**
 * Compile-time proof the runtime list covers every declared key.
 *
 * The other direction is already covered: `satisfies readonly (keyof
 * AughorUIDataTypes)[]` rejects a name in DECLARED that is not in the types.
 *
 * `[T] extends [never]` rather than `T extends never`: a naked type parameter
 * DISTRIBUTES over a union, and distributing over `never` yields `never` — so
 * the obvious spelling passes whether or not a key is missing, which is a guard
 * that cannot fail. The tuple wrapper stops the distribution.
 */
type _Missing = Exclude<keyof AughorUIDataTypes, (typeof DECLARED)[number]>;
type _IsNever<T> = [T] extends [never] ? true : false;
const _exhaustive: _IsNever<_Missing> = true;
void _exhaustive;
