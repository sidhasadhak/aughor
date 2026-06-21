/**
 * Ergonomic, hand-maintained surface over the AUTO-GENERATED OpenAPI types in `api.gen.ts`.
 *
 * `api.gen.ts` is generated from the live FastAPI schema by `npm run gen:api` (do not edit it).
 * This file gives the rest of the app friendly aliases so call sites can import a typed
 * request/response without reaching into the generated `paths`/`components` shape directly,
 * and so the hand-written interfaces in `api.ts` can be migrated onto the generated source of
 * truth incrementally. Re-run `gen:api` after any backend schema change to catch drift in tsc.
 */
import type { components } from "./api.gen";

/** All generated component schemas, keyed by their backend (Pydantic) model name. */
export type Schemas = components["schemas"];

/** Pull a single generated schema by name, e.g. `Schema<"OrgSettings">`. */
export type Schema<K extends keyof Schemas> = Schemas[K];
