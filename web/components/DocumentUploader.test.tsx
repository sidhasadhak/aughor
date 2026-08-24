// @vitest-environment jsdom
/**
 * KB-3 — the panel showed a corpus and never said whether it worked.
 *
 * Two things were invisible from here:
 *
 *  - **The plane's availability.** Embeddings come from a LOCAL Ollama, so on any deploy
 *    without it nothing indexes and every search returns empty — while this list of
 *    documents renders exactly as it does on a healthy machine.
 *  - **That `chunk_count` is a CLAIM.** It comes from the registry, not the index. Measured
 *    on a real install, one document claimed 59 chunks where the store held 5, and this
 *    panel reported 59 with no hint that most of it is unsearchable.
 *
 * The status call is allowed to fail — the API serving this UI may predate the endpoint —
 * so the third property held here is that an absent status changes nothing.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentEntry, KnowledgeStatus } from "@/lib/api";

const listDocuments = vi.fn();
const getKnowledgeStatus = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    listDocuments: (...a: unknown[]) => listDocuments(...a),
    getKnowledgeStatus: (...a: unknown[]) => getKnowledgeStatus(...a),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
  };
});

const { DocumentUploader } = await import("@/components/DocumentUploader");

const doc = (over: Partial<DocumentEntry> = {}): DocumentEntry => ({
  doc_id: "d1", filename: "handbook.pdf", title: "Handbook", chunk_count: 59,
  uploaded_at: new Date().toISOString(), ...over,
});

const status = (over: Partial<KnowledgeStatus> = {}): KnowledgeStatus => ({
  ready: true, reason: "", documents: 1, chunks: 5,
  embedder: { model: "nomic-embed-text", endpoint: "http://localhost:11434/v1", ok: true },
  store: { ok: true, backend: "qdrant", chunks: 5 },
  consistency: { ok: true, orphan_documents: 0, orphan_chunks: 0, orphans: [],
                 mismatched_documents: {}, listed_chunks_present: 5 },
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  listDocuments.mockResolvedValue([doc()]);
  getKnowledgeStatus.mockResolvedValue(status());
});

describe("what the panel says about the plane", () => {
  it("says nothing when everything is healthy", async () => {
    render(<DocumentUploader />);
    await screen.findByText("Handbook");

    expect(screen.queryByText(/Search is unavailable/)).toBeNull();
    expect(screen.queryByText(/disagree/)).toBeNull();
  });

  it("names an unreachable embedder, and that it is a local one", async () => {
    getKnowledgeStatus.mockResolvedValue(status({
      ready: false, reason: "the embedder is unreachable",
      embedder: { model: "nomic-embed-text", endpoint: "http://localhost:11434/v1",
                  ok: false, error: "ConnectionError: connection refused" },
    }));

    render(<DocumentUploader />);

    expect(await screen.findByText(/Search is unavailable/)).toBeTruthy();
    expect(screen.getByText(/LOCAL model/)).toBeTruthy();
    expect(screen.getByText(/localhost:11434/)).toBeTruthy();
  });

  it("reassures that uploaded documents survive an outage", async () => {
    getKnowledgeStatus.mockResolvedValue(status({ ready: false, reason: "no documents are indexed" }));

    render(<DocumentUploader />);

    expect(await screen.findByText(/Documents already uploaded are unaffected/)).toBeTruthy();
  });
});

describe("what the panel says about the numbers", () => {
  it("shows the registry's claim when the index agrees with it", async () => {
    listDocuments.mockResolvedValue([doc({ chunk_count: 5 })]);

    render(<DocumentUploader />);

    expect(await screen.findByText(/5 chunks/)).toBeTruthy();
  });

  it("puts the INDEXED count in front when the two disagree", async () => {
    /** The defect this exists for: 59 rendered as fact while 54 of those passages are not
     *  searchable. Both numbers, store first. */
    getKnowledgeStatus.mockResolvedValue(status({
      consistency: { ok: false, orphan_documents: 0, orphan_chunks: 0, orphans: [],
                     mismatched_documents: { d1: { registry: 59, store: 5 } },
                     listed_chunks_present: 5 },
    }));

    render(<DocumentUploader />);

    expect(await screen.findByText(/5 chunks indexed of 59 claimed/)).toBeTruthy();
  });

  it("reports chunks that are in the index but on no listed document", async () => {
    /** Orphans are found by search and cannot be removed from here — the panel has to say
     *  so, because every control it offers works off the list. */
    getKnowledgeStatus.mockResolvedValue(status({
      chunks: 46,
      consistency: { ok: false, orphan_documents: 5, orphan_chunks: 41,
                     orphans: ["ghost"], mismatched_documents: {},
                     listed_chunks_present: 5 },
    }));

    render(<DocumentUploader />);

    expect(await screen.findByText(/index and this list disagree/)).toBeTruthy();
    expect(screen.getByText(/cannot be removed from here/)).toBeTruthy();
  });
});

describe("degradation", () => {
  it("renders unchanged when the status endpoint is absent", async () => {
    /** The API serving this UI may predate `/knowledge/status` — it does right now, and it
     *  404s. A panel that broke on that would be a regression shipped to every user whose
     *  server is one deploy behind. */
    getKnowledgeStatus.mockResolvedValue(null);

    render(<DocumentUploader />);

    expect(await screen.findByText("Handbook")).toBeTruthy();
    expect(screen.getByText(/59 chunks/)).toBeTruthy();
    expect(screen.queryByText(/Search is unavailable/)).toBeNull();
  });

  it("still lists documents when the status call throws", async () => {
    getKnowledgeStatus.mockRejectedValue(new Error("network"));

    render(<DocumentUploader />);

    await waitFor(() => expect(screen.getByText("Handbook")).toBeTruthy());
  });
});
