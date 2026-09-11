"use client";

/**
 * ON-3 — `/objects/<type>/<key>?conn=<connection>&schema=<schema>`: one object's page, opened from a
 * key in an answer or from another object's page. A LAYOUT over `ObjectView`, the way `/chat` is a
 * layout over ChatPanel — same app, same tokens, same auth and org scoping.
 */
import { use } from "react";

import { ObjectView } from "@/components/objects/ObjectView";
import { installAuthFetch } from "@/lib/auth";
import { getApiBase } from "@/lib/config";

// An answer opens this page in a new tab, where the workbench never installed the authenticated
// fetch — so the page installs it itself, before its first request (the install is idempotent).
if (typeof window !== "undefined") installAuthFetch(getApiBase());

function one(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

/** A segment may still arrive percent-encoded; a malformed one is used as written. */
function segment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export default function ObjectRoute({ params, searchParams }: {
  params: Promise<{ type: string; pk: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { type, pk } = use(params);
  const query = use(searchParams);
  return (
    <ObjectView
      objectType={segment(type)}
      pk={segment(pk)}
      connectionId={one(query.conn)}
      schemaName={one(query.schema)}
    />
  );
}
