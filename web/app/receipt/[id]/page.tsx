"use client";

/**
 * Idea 11 — `/receipt/<id>`: how an answer's numbers were produced, as a page of its own. Every
 * chart, table and key figure in an exported PDF or deck links here (`export/document.py`
 * `receipt_link`), so a reader can check a number without the conversation it came from. A
 * LAYOUT over the "Why this number" drawer's body — same app, same tokens, same auth and org
 * scoping, so a receipt outside the reader's organisation answers "no receipt", as in the app.
 */
import { use } from "react";

import { TrustReceiptPage } from "@/components/WhyThisNumber";
import { installAuthFetch } from "@/lib/auth";
import { getApiBase } from "@/lib/config";

// A document opens this page in a new tab, where the workbench never installed the authenticated
// fetch — so the page installs it itself, before its first request (the install is idempotent).
if (typeof window !== "undefined") installAuthFetch(getApiBase());

/** A segment may still arrive percent-encoded; a malformed one is used as written. */
function segment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export default function ReceiptRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <TrustReceiptPage receiptId={segment(id)} />;
}
