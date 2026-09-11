/**
 * ON-3 — where an object's page lives, and which answer columns name an object.
 *
 * A column links to an object page only when the object catalog says its NAME is an object
 * type's key, or the column a usable link from that key joins to (`orders.customer_id` names a
 * Customer, because `customer_id = customer_id` from Customer's key is a measured link). A name
 * two types claim links to neither: guessing which object a value means is the mistake the object
 * page exists to remove. Pure functions — the chat's answer tables and the object page share them.
 */
import type { ObjectCatalog } from "@/lib/objects";

export function objectHref(objectType: string, pk: string, connectionId?: string, schemaName?: string): string {
  const q = new URLSearchParams();
  if (connectionId) q.set("conn", connectionId);
  if (schemaName) q.set("schema", schemaName);
  const s = q.toString();
  return `/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(pk)}${s ? `?${s}` : ""}`;
}

/** Where declared actions are proposed and reviewed: Intelligence's Actions layer. The layer's id
 *  is a URL value frozen from before the glossary named the plane "actions", spelled as the
 *  workspace reads it. */
export function declaredActionsHref(connectionId?: string): string {
  const q = new URLSearchParams({ tab: "intelligence", layer: "kinetic" });
  if (connectionId) q.set("conn", connectionId);
  return `/?${q.toString()}`;
}

/** `local = remote`, as the catalog spells a link's join. */
function joinColumns(on: string): [string, string] | null {
  const parts = on.split("=").map((s) => s.trim());
  return parts.length === 2 && parts[0] && parts[1] ? [parts[0], parts[1]] : null;
}

/** Lower-cased column name → the object type (api name) whose instances its values name. */
export function objectKeyColumns(catalog: ObjectCatalog | null | undefined): Map<string, string> {
  const claims = new Map<string, Set<string>>();
  const claim = (column: string, objectType: string) => {
    const name = column.toLowerCase();
    const owners = claims.get(name) ?? new Set<string>();
    owners.add(objectType);
    claims.set(name, owners);
  };
  for (const type of catalog?.object_types ?? []) {
    if (!type.key) continue;
    claim(type.key, type.object_type);
    for (const link of type.links) {
      const join = link.usable ? joinColumns(link.on) : null;
      if (join && join[0].toLowerCase() === type.key.toLowerCase()) claim(join[1], type.object_type);
    }
  }
  const out = new Map<string, string>();
  claims.forEach((owners, column) => {
    if (owners.size === 1) out.set(column, Array.from(owners)[0]);
  });
  return out;
}
