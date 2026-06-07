/**
 * tableName.ts — frontend mirror of the backend canonical primitive
 * (aughor/tools/table_names.py). Table names arrive from the API in more than one
 * convention depending on which builder produced them:
 *
 *   bare                    "orders"
 *   schema.table            "analytics.orders"
 *   catalog.schema.table    "memory.bakehouse.reviews"
 *
 * Any UI code that compares a name from one source (e.g. a rich-schema table)
 * against a name from another (e.g. a catalog tree node) MUST go through `same`
 * / `bare` here rather than `===` or its own `.split(".")`. This is the same
 * qualified-vs-bare mismatch that was independently re-fixed three times before
 * the shared primitive existed — keep it centralised.
 *
 * Two leaf accessors on purpose:
 *   leaf(name) → last segment, CASE PRESERVED  (for display / SQL identifiers)
 *   bare(name) → leaf lowercased + unquoted     (for comparison / map keys)
 */

/** Last dotted segment, case preserved, surrounding quotes stripped. */
export function leaf(name: string): string {
  return (name ?? "").split(".").pop()!.trim().replace(/^"|"$/g, "");
}

/** Comparison key: last segment, lowercased and unquoted. Never use for SQL. */
export function bare(name: string): string {
  return leaf(name).toLowerCase();
}

/** Schema segment (immediately left of the table) if qualified, else null.
 *  Handles 2- and 3-part names. */
export function schemaOf(name: string): string | null {
  const parts = (name ?? "")
    .split(".")
    .map((p) => p.trim().replace(/^"|"$/g, ""))
    .filter(Boolean);
  return parts.length >= 2 ? parts[parts.length - 2].toLowerCase() : null;
}

/** Schema-qualify a bare name. Passes through if already qualified or no schema. */
export function qualify(name: string, schema: string | null | undefined): string {
  if (!schema || (name ?? "").includes(".")) return name;
  return `${schema}.${name}`;
}

/**
 * True when two refs name the same table, tolerant of qualified-vs-bare. With
 * `schemaStrict` also require the schema to match WHEN BOTH carry one (a bare ref
 * still matches a qualified one — absence of a schema means "any").
 */
export function same(a: string, b: string, opts: { schemaStrict?: boolean } = {}): boolean {
  if (bare(a) !== bare(b)) return false;
  if (opts.schemaStrict) {
    const sa = schemaOf(a);
    const sb = schemaOf(b);
    if (sa && sb && sa !== sb) return false;
  }
  return true;
}
