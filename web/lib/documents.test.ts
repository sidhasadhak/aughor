/**
 * What the Documents screen says about the corpus (`lib/documents.ts`): names in the reader's words, the index's count
 * before the list's claim, and the figures the screen opens on.
 */
import { describe, expect, it } from "vitest";

import type { DocumentEntry, KnowledgeStatus } from "@/lib/api";
import {
  addedWords, chunkWords, documentFigures, documentName, driftedDocuments, formatLabel, schemaDocParts,
} from "@/lib/documents";

const conns = [{ id: "baef6c3e", name: "DuckDB" }, { id: "8233e4fd", name: "theLook" }];

const schemaDoc = (conn: string, schema: string, chunks: number, at = "2026-10-12T14:40:38Z"): DocumentEntry => ({
  doc_id: `doctree::${conn}::${schema}`, filename: `schema-docs/${conn}/${schema}`,
  title: `Schema documentation — ${conn}/${schema}`, chunk_count: chunks, uploaded_at: at, generated: true,
});

const status = (over: Partial<KnowledgeStatus["consistency"]> = {}, chunks = 51): KnowledgeStatus => ({
  ready: true, reason: "", documents: 7, chunks,
  embedder: { model: "nomic-embed-text", endpoint: "http://localhost:11434/v1", ok: true, dim: 768 },
  store: { ok: true, backend: "qdrant", chunks },
  consistency: { ok: true, orphan_documents: 0, orphan_chunks: 0, orphans: [], mismatched_documents: {},
                 listed_chunks_present: chunks, ...over },
});

describe("a document's name", () => {
  it("names a compiled schema document by its connection, never the id it is filed under", () => {
    const d = schemaDoc("baef6c3e", "ecommerce", 9);
    expect(schemaDocParts(d)).toEqual({ connectionId: "baef6c3e", schema: "ecommerce" });
    expect(documentName(d, conns)).toBe("DuckDB · ecommerce");
    // a schema named like its connection is said once
    expect(documentName(schemaDoc("8233e4fd", "thelook", 8), conns)).toBe("theLook");
    // an unknown connection is a LABELLED id, not a bare hash
    expect(documentName(schemaDoc("dcc63d83", "gold", 4), conns)).toBe("connection dcc63d83 · gold");
  });

  it("names an upload by its own title, and its format as one short word", () => {
    const up: DocumentEntry = { doc_id: "d1", filename: "handbook.pdf", title: "Handbook", chunk_count: 5, uploaded_at: "" };
    expect(documentName(up, conns)).toBe("Handbook");
    expect(formatLabel(up)).toBe("PDF");
    expect(formatLabel({ filename: "deck.pptx" })).toBe("Slides");
    expect(formatLabel({ filename: "notes" })).toBe("File");
    expect(formatLabel({ filename: "x.foo" })).toBe("FOO");
    expect(formatLabel(schemaDoc("a", "b", 1))).toBe("Schema");
  });
});

describe("how much search can see", () => {
  it("puts the index's count before the list's claim when they disagree", () => {
    const d = schemaDoc("baef6c3e", "ecommerce", 9);
    const st = status({ ok: false, mismatched_documents: { [d.doc_id]: { registry: 9, store: 0 } } });
    expect(chunkWords(d, st)).toBe("0 of 9 indexed");
    expect(chunkWords(d, status())).toBe("9 chunks");
    expect(chunkWords({ ...d, chunk_count: 1 }, null)).toBe("1 chunk");
  });

  it("opens on the figures, the index's count and not the list's claim", () => {
    const docs = [
      schemaDoc("baef6c3e", "ecommerce", 9, "2026-08-04T15:58:54Z"),
      schemaDoc("baef6c3e", "main", 1, "2026-08-15T14:08:08Z"),
      schemaDoc("8233e4fd", "thelook", 51, "2026-10-13T01:49:38Z"),
    ];
    const st = status({ ok: false, mismatched_documents: {
      [docs[0].doc_id]: { registry: 9, store: 0 }, [docs[1].doc_id]: { registry: 1, store: 0 } } });
    const f = documentFigures(docs, st);
    expect(f).toMatchObject({ documents: 3, uploaded: 0, generated: 3, indexed: 51, listed: 61, orphans: 0 });
    expect(f.newest?.doc_id).toBe(docs[2].doc_id);
    // with no status read, the index's count is unknown — not the claim passed off as it
    expect(documentFigures(docs, null).indexed).toBeNull();

    expect(driftedDocuments(docs, st, conns)).toEqual([
      { docId: docs[0].doc_id, name: "DuckDB · ecommerce", indexed: 0, claimed: 9 },
      { docId: docs[1].doc_id, name: "DuckDB · main", indexed: 0, claimed: 1 },
    ]);
  });
});

describe("when a document was added", () => {
  it("is a day down a column, with the year only when it is not this one", () => {
    const now = Date.parse("2026-10-13T12:00:00");
    expect(addedWords("2026-10-13T08:00:00", now)).toBe("today");
    expect(addedWords("2026-10-12T08:00:00", now)).toBe("yesterday");
    // calendar days, not 24-hour spans: yesterday at 23:00 is yesterday, though under a day ago
    expect(addedWords("2026-10-12T23:00:00", now)).toBe("yesterday");
    expect(addedWords("2026-08-04T15:58:54", now)).toBe("4 Aug");
    expect(addedWords("2025-12-01T10:00:00", now)).toBe("1 Dec 2025");
    expect(addedWords("", now)).toBe("—");
  });
});
