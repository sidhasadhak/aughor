/**
 * What the Documents screen says about the corpus, decided here and laid out by `components/documents/DocumentsPage.tsx`
 * to `aughor-v2/CLARITY.md`: a document's name in the reader's words, its format as a chip, how much of it search can
 * see, and the figures the screen opens on. Pure: nothing here fetches.
 */
import type { DocumentEntry, KnowledgeStatus } from "@/lib/api";
import { dayMonth } from "@/lib/canvasList";
import { countNoun, formatCount } from "@/lib/format";
import { connectionLabel } from "@/lib/names";

/** When a document was added, as a person says it: "today", "yesterday", "12 Oct" — and the year when it is not this
 *  one. Calendar days in the reader's own zone (something added at noon yesterday is "yesterday", not "today" because
 *  it is under 24 hours old), and a date rather than "58 days ago" beside "2 months ago": rows are read down a column. */
export function addedWords(iso: string | null | undefined, now: number): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(t)) return "—";
  const day = (ms: number) => { const d = new Date(ms); return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime(); };
  const days = Math.round((day(now) - day(t)) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return dateWords(iso, now);
}

/** A day as a date: "12 Oct", and "1 Dec 2025" when it is not this year. */
export function dateWords(iso: string | null | undefined, now: number): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(t)) return "—";
  const year = new Date(t).getFullYear();
  return year === new Date(now).getFullYear() ? dayMonth(iso) : `${dayMonth(iso)} ${year}`;
}

/** The connection and schema a compiled schema document describes: `doctree::<connection>::<schema>` (or its filename,
 *  `schema-docs/<connection>/<schema>`). Null for a person's upload. */
export function schemaDocParts(doc: DocumentEntry): { connectionId: string; schema: string } | null {
  const byId = /^doctree::([^:]+)::(.+)$/.exec(doc.doc_id);
  if (byId) return { connectionId: byId[1], schema: byId[2] };
  const byFile = /^schema-docs\/([^/]+)\/(.+)$/.exec(doc.filename || "");
  if (byFile) return { connectionId: byFile[1], schema: byFile[2] };
  return null;
}

/** The documents an agent on `connectionId` can be given, in the order a person picks from: its connection's schema
 *  documentation (the scoped schema's first), then uploads, which belong to no connection and are the organisation's
 *  (`orgWide`). The other connections' schema documentation is left out and counted (`hidden`) — the agent wizard
 *  listed every connection's (the Olist study, 2026-10-22). With no connection chosen, nothing is left out. */
export function documentsForConnection(docs: DocumentEntry[], connectionId: string, schema = ""):
  { shown: { doc: DocumentEntry; orgWide: boolean }[]; hidden: number } {
  const rank = (d: DocumentEntry) => {
    const parts = schemaDocParts(d);
    if (!parts) return 2;
    return schema && parts.schema.toLowerCase() === schema.toLowerCase() ? 0 : 1;
  };
  const kept = docs.filter(d => !connectionId || (schemaDocParts(d)?.connectionId ?? connectionId) === connectionId);
  const shown = kept.map((doc, i) => ({ doc, i })).sort((a, b) => rank(a.doc) - rank(b.doc) || a.i - b.i)
    .map(({ doc }) => ({ doc, orgWide: schemaDocParts(doc) === null }));
  return { shown, hidden: docs.length - kept.length };
}

const squash = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

/**
 * A document as the reader names it. An upload is its own title; a compiled schema document is its connection, named
 * (never the id the platform files it under — "Schema documentation — 8233e4fd/thelook" is theLook), and the schema
 * when it says something the connection's name does not.
 */
export function documentName(doc: DocumentEntry, connections: ReadonlyArray<{ id: string; name: string }>): string {
  const parts = doc.generated ? schemaDocParts(doc) : null;
  if (!parts) return doc.title || doc.filename || doc.doc_id;
  const conn = connectionLabel(parts.connectionId, connections);
  return squash(conn) === squash(parts.schema) ? conn : `${conn} · ${parts.schema}`;
}

const FORMAT: Record<string, string> = {
  pdf: "PDF", docx: "Word", doc: "Word", docm: "Word", odt: "ODT", rtf: "RTF",
  md: "MD", markdown: "MD", txt: "TXT",
  pptx: "Slides", ppt: "Slides", pptm: "Slides", odp: "Slides",
  xlsx: "Sheet", xls: "Sheet", xlsm: "Sheet", xlsb: "Sheet", ods: "Sheet", csv: "CSV",
  epub: "EPUB",
};

/** A file's format as one short word for its chip: "PDF", "Word", "Sheet". A compiled schema document is "Schema". */
export function formatLabel(doc: Pick<DocumentEntry, "filename" | "generated">): string {
  if (doc.generated) return "Schema";
  const name = doc.filename || "";
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
  return FORMAT[ext] ?? (ext ? ext.toUpperCase() : "File");
}

/**
 * How much of a document search can see. `chunk_count` is the list's CLAIM, made at upload time; the index is what
 * search reads, and on a real install one document claimed 59 chunks where the index held 5. So when the two disagree
 * the indexed count leads and the claim follows; with no status read, the claim is all there is to show.
 */
export function chunksOf(doc: DocumentEntry, status: KnowledgeStatus | null): {
  indexed: number; claimed: number; drift: boolean;
} {
  const drift = status?.consistency?.mismatched_documents?.[doc.doc_id];
  return drift
    ? { indexed: drift.store, claimed: drift.registry, drift: true }
    : { indexed: doc.chunk_count ?? 0, claimed: doc.chunk_count ?? 0, drift: false };
}

/** The row's words for its chunks: "59 chunks", or — when the index holds a different number — "5 of 59 indexed". */
export function chunkWords(doc: DocumentEntry, status: KnowledgeStatus | null): string {
  const c = chunksOf(doc, status);
  if (!c.drift) return countNoun(c.claimed, "chunk");
  return `${formatCount(c.indexed)} of ${formatCount(c.claimed)} indexed`;
}

export interface DocumentFigures {
  documents: number;
  uploaded: number;
  generated: number;
  /** What the index holds — what search sees. Null when the status could not be read. */
  indexed: number | null;
  /** What the list claims, summed. */
  listed: number;
  /** Chunks in the index that no listed document owns (search still finds them). */
  orphans: number;
  /** The newest document, by when it was added. */
  newest: DocumentEntry | null;
}

export function documentFigures(docs: DocumentEntry[], status: KnowledgeStatus | null): DocumentFigures {
  const generated = docs.filter(d => d.generated).length;
  const newest = docs.reduce<DocumentEntry | null>(
    (best, d) => (!best || (d.uploaded_at || "") > (best.uploaded_at || "") ? d : best), null);
  return {
    documents: docs.length,
    uploaded: docs.length - generated,
    generated,
    indexed: status ? status.chunks ?? 0 : null,
    listed: docs.reduce((n, d) => n + (d.chunk_count ?? 0), 0),
    orphans: status?.consistency?.orphan_chunks ?? 0,
    newest,
  };
}

/** The documents whose indexed count differs from the list's claim, each named — the "Needs you" row's detail. A
 *  document the status names that the list no longer holds is still counted, by its id. */
export function driftedDocuments(
  docs: DocumentEntry[], status: KnowledgeStatus | null, connections: ReadonlyArray<{ id: string; name: string }>,
): { docId: string; name: string; indexed: number; claimed: number }[] {
  const drift = status?.consistency?.mismatched_documents ?? {};
  return Object.entries(drift).map(([docId, d]) => {
    const doc = docs.find(x => x.doc_id === docId);
    return { docId, name: doc ? documentName(doc, connections) : docId, indexed: d.store, claimed: d.registry };
  });
}
