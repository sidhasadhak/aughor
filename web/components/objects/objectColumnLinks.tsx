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
import { cachedObjectCatalog } from "@/lib/objects";

type ColumnOverride = Partial<TableColumnsType<Record<string, unknown>>[number]>;

const NO_KEYS = new Map<string, string>();

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

const LINK_STYLE: React.CSSProperties = {
  display: "block", maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
  fontFamily: "var(--font-mono)", color: "var(--blue5)",
};

/** A table cell that opens the object its value names. An answer opens it in a new tab so the
 *  conversation stays where it was; an object page's own lists navigate in place. */
export function objectLinkRender(
  objectType: string,
  scope: { connectionId?: string; schemaName?: string; newTab?: boolean } = {},
) {
  const ObjectLinkCell = (value: unknown) => {
    if (value == null || value === "") return <span style={{ color: "var(--t4)" }}>—</span>;
    const pk = String(value);
    const href = objectHref(objectType, pk, scope.connectionId, scope.schemaName);
    const title = `Open ${objectType} ${pk}`;
    return scope.newTab === false ? (
      <Link href={href} className="aug-fs-xs" style={LINK_STYLE} title={title}>{pk}</Link>
    ) : (
      <a href={href} target="_blank" rel="noopener noreferrer" className="aug-fs-xs" style={LINK_STYLE} title={title}>
        {pk}
      </a>
    );
  };
  return ObjectLinkCell;
}

/** `SqlResultTable` column overrides for every column of `columns` that names an object. */
export function useObjectColumnLinks(
  columns: string[],
  connectionId?: string,
  scope: { schemaName?: string; newTab?: boolean } = {},
): Record<string, ColumnOverride> {
  const keys = useObjectKeyColumns(connectionId);
  const { schemaName, newTab } = scope;
  return useMemo(() => {
    const out: Record<string, ColumnOverride> = {};
    for (const column of columns) {
      const objectType = keys.get(column.toLowerCase());
      if (objectType) out[column] = { render: objectLinkRender(objectType, { connectionId, schemaName, newTab }) };
    }
    return out;
  }, [columns, keys, connectionId, schemaName, newTab]);
}
