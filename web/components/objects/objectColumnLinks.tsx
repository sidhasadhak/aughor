"use client";

/**
 * ON-3 — an answer's key columns become links to object pages (ROADMAP §3.15's receipt: "a
 * customer id in an answer is a link").
 *
 * The column → object type map comes from the object catalog through `objectKeyColumns`: a column
 * links only when its name is an object type's key, or the column a measured link from that key
 * joins to, and exactly one type claims it. Until the catalog arrives — or when the connection has
 * no ontology — the table renders exactly as it did before.
 */
import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { TableColumnsType } from "antd";

import { objectHref, objectKeyColumns } from "@/lib/objectLinks";
import { cachedObjectCatalog, getObjectTitles } from "@/lib/objects";

type ColumnOverride = Partial<TableColumnsType<Record<string, unknown>>[number]>;

const NO_KEYS = new Map<string, string>();
const NO_TITLES = new Map<string, string>();
/** As many keys as the door resolves in one call; a longer page shows keys for the rest, as before. */
const TITLE_LIMIT = 500;

/** `type\u0000key` — one flat map for every type on screen, so a render function needs no per-type lookup. */
function titleKey(objectType: string, pk: string): string {
  return `${objectType}\u0000${pk}`;
}

export function useObjectKeyColumns(connectionId?: string): Map<string, string> {
  const [loaded, setLoaded] = useState<{ connectionId: string; keys: Map<string, string> } | null>(null);
  useEffect(() => {
    if (!connectionId) return;
    let live = true;
    cachedObjectCatalog(connectionId).then((catalog) => {
      if (live) setLoaded({ connectionId, keys: objectKeyColumns(catalog) });
    });
    return () => { live = false; };
  }, [connectionId]);
  return loaded && loaded.connectionId === connectionId ? loaded.keys : NO_KEYS;
}

/**
 * ON-3b — the NAMES behind the keys on screen.
 *
 * A key is what the warehouse stores and almost never what a person recognises: `MYT-O00003141` says nothing
 * that "Order MYT-O00003141" does not. Every type already declares a display property, measured against its
 * backing — it just never reached the table. One request per type resolves the whole page of keys, so a table
 * of 200 costs two round trips rather than 200, and a title that does not arrive leaves the key exactly as it
 * was: this decorates a link, it never gates one.
 */
export function useObjectTitles(
  rows: unknown[][] | undefined,
  columns: string[],
  keys: Map<string, string>,
  connectionId?: string,
  schemaName?: string,
): Map<string, string> {
  // The keys to resolve, as a stable string: a new array each render would re-fetch forever.
  const wanted = useMemo(() => {
    if (!rows?.length) return "";
    const byType = new Map<string, Set<string>>();
    columns.forEach((column, index) => {
      const objectType = keys.get(column.toLowerCase());
      if (!objectType) return;
      const set = byType.get(objectType) ?? new Set<string>();
      for (const row of rows) {
        const value = row[index];
        if (value == null || value === "" || set.size >= TITLE_LIMIT) continue;
        set.add(String(value));
      }
      byType.set(objectType, set);
    });
    return serialize(byType);
  }, [rows, columns, keys]);
  return useTitleMap(wanted, connectionId, schemaName);
}

/** The same resolution for keys that are not in a table — the to-one links on an object page, say. */
export function useKeyTitles(
  pairs: { objectType: string; pk: string | null | undefined }[],
  connectionId?: string,
  schemaName?: string,
): Map<string, string> {
  // Built fresh each render and immediately serialized: the STRING is what the effect depends on, so an
  // unchanged set of keys is an unchanged dependency however many times this re-renders.
  const byType = new Map<string, Set<string>>();
  for (const { objectType, pk } of pairs) {
    if (!objectType || pk == null || pk === "") continue;
    const set = byType.get(objectType) ?? new Set<string>();
    if (set.size < TITLE_LIMIT) set.add(String(pk));
    byType.set(objectType, set);
  }
  return useTitleMap(serialize(byType), connectionId, schemaName);
}

function serialize(byType: Map<string, Set<string>>): string {
  const groups = [...byType].map(([type, set]) => [type, [...set].sort()] as const).filter(([, g]) => g.length);
  return groups.length ? JSON.stringify(groups) : "";
}

function useTitleMap(wanted: string, connectionId?: string, schemaName?: string): Map<string, string> {
  const [titles, setTitles] = useState<Map<string, string>>(NO_TITLES);

  useEffect(() => {
    if (!wanted || !connectionId) return;
    const groups = JSON.parse(wanted) as [string, string[]][];
    let live = true;
    Promise.all(groups.map(([objectType, group]) =>
      getObjectTitles(objectType, group, connectionId, schemaName)
        .then((found) => (found.path === "titles" ? [objectType, found.titles] as const : null))
        .catch(() => null)))
      .then((answers) => {
        if (!live) return;
        const map = new Map<string, string>();
        for (const answer of answers) {
          if (!answer) continue;
          const [objectType, found] = answer;
          for (const [pk, title] of Object.entries(found)) map.set(titleKey(objectType, pk), title);
        }
        // A page whose types are all named by their key resolves nothing — keep the shared empty map so a
        // table of keys never re-renders for a result that says "there is nothing to add".
        setTitles(map.size ? map : NO_TITLES);
      });
    return () => { live = false; };
  }, [wanted, connectionId, schemaName]);

  return titles;
}

const LINK_STYLE: React.CSSProperties = {
  display: "block", maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
  fontFamily: "var(--font-mono)", color: "var(--blue3)",
};
/** A name is prose, not an identifier: it reads in the body face, and the key it stands for is on hover. */
const NAMED_STYLE: React.CSSProperties = { ...LINK_STYLE, fontFamily: "inherit" };

/** A table cell that opens the object its value names — by the object's NAME when its type declares a display
 *  property and the name resolved, and by its key otherwise, which is what every cell showed before. An answer
 *  opens it in a new tab so the conversation stays where it was; an object page's own lists navigate in place. */
export function objectLinkRender(
  objectType: string,
  scope: { connectionId?: string; schemaName?: string; newTab?: boolean; titles?: Map<string, string> } = {},
) {
  const ObjectLinkCell = (value: unknown) => {
    if (value == null || value === "") return <span style={{ color: "var(--t4)" }}>—</span>;
    const pk = String(value);
    const named = scope.titles?.get(titleKey(objectType, pk));
    const href = objectHref(objectType, pk, scope.connectionId, scope.schemaName);
    // The key stays reachable on hover even when the name is what shows: it is what the SQL filtered on.
    const title = named ? `Open ${objectType} ${pk} — ${named}` : `Open ${objectType} ${pk}`;
    const style = named ? NAMED_STYLE : LINK_STYLE;
    return scope.newTab === false ? (
      <Link href={href} className="aug-fs-xs" style={style} title={title}>{named ?? pk}</Link>
    ) : (
      <a href={href} target="_blank" rel="noopener noreferrer" className="aug-fs-xs" style={style} title={title}>
        {named ?? pk}
      </a>
    );
  };
  return ObjectLinkCell;
}

/** `SqlResultTable` column overrides for every column of `columns` that names an object. */
export function useObjectColumnLinks(
  columns: string[],
  connectionId?: string,
  scope: { schemaName?: string; newTab?: boolean; rows?: unknown[][] } = {},
): Record<string, ColumnOverride> {
  const keys = useObjectKeyColumns(connectionId);
  const { schemaName, newTab, rows } = scope;
  // Pass `rows` and every linked key is named; leave them out and the table links keys, as it did before.
  const titles = useObjectTitles(rows, columns, keys, connectionId, schemaName);
  return useMemo(() => {
    const out: Record<string, ColumnOverride> = {};
    for (const column of columns) {
      const objectType = keys.get(column.toLowerCase());
      if (objectType) {
        out[column] = { render: objectLinkRender(objectType, { connectionId, schemaName, newTab, titles }) };
      }
    }
    return out;
  }, [columns, keys, connectionId, schemaName, newTab, titles]);
}
