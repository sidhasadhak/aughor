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
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentEntry, KnowledgeStatus } from "@/lib/api";

const listDocuments = vi.fn();
const getKnowledgeStatus = vi.fn();
const previewDocumentChunks = vi.fn();
const convertDocument = vi.fn();
const uploadDocument = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    listDocuments: (...a: unknown[]) => listDocuments(...a),
    getKnowledgeStatus: (...a: unknown[]) => getKnowledgeStatus(...a),
    previewDocumentChunks: (...a: unknown[]) => previewDocumentChunks(...a),
    convertDocument: (...a: unknown[]) => convertDocument(...a),
    uploadDocument: (...a: unknown[]) => uploadDocument(...a),
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

const conversion = (over: Record<string, unknown> = {}) => ({
  filename: "policy.md", markdown: "# Policy\n\nbody text", characters: 4096,
  would_index_chunks: 3, page_count: 0, pages_read: 0,
  pages_needing_ocr: [], pages_failed: [], suppressed_numeric_runs: 0,
  suppressed_sample: [], settings: {}, ...over,
});

const chunkPreview = (over: Record<string, unknown> = {}) => ({
  total_chunks: 3, shown: 2, characters: 4096,
  settings: { delimiter: "\n\n", max_chars: 1200, overlap_chars: 100,
              min_chars: 50, collapse_whitespace: true, strip_urls_emails: false },
  chunks: [{ index: 0, characters: 900, tokens_estimate: 225, text: "first chunk" },
           { index: 1, characters: 880, tokens_estimate: 220, text: "second chunk" }],
  ...over,
});

/** ① — choosing a file. The panel makes no request for this, by design. */
const choose = (name = "policy.md") => {
  const picker = document.querySelector('input[type="file"][multiple]');
  fireEvent.change(picker!, { target: { files: [new File(["body"], name)] } });
};

beforeEach(() => {
  vi.clearAllMocks();
  listDocuments.mockResolvedValue([doc()]);
  getKnowledgeStatus.mockResolvedValue(status());
  convertDocument.mockResolvedValue(conversion());
  previewDocumentChunks.mockResolvedValue(chunkPreview());
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


describe("curation — settings that were only reachable through the API", () => {
  it("starts at the defaults the corpus was indexed under", async () => {
    render(<DocumentUploader />);
    await screen.findByText("Handbook");

    // Not "0 changed": a person who never touches this gets the previous behaviour, and
    // the label has to say so rather than imply an empty configuration.
    expect(screen.getByText(/defaults/)).toBeTruthy();
    // The fields are in front of the reader, not behind a disclosure. A setting you have
    // to go looking for is the reason none of this was reachable in the first place.
    expect(screen.getByLabelText(/Maximum chunk length/)).toBeTruthy();
    expect(screen.getByLabelText(/Chunk overlap/)).toBeTruthy();
  });

  it("makes no request at all when a file is merely chosen", async () => {
    // ① is a choice, not a commitment. Dropping a file used to convert it on the spot,
    // under whatever was in the settings fields — which put ② after the conversion it
    // was supposed to govern, and spent a conversion on every misdrop.
    render(<DocumentUploader />);
    await screen.findByText("Handbook");

    choose();

    // Both ① and ④ say so — the tray and the reader agree that nothing has been read.
    expect(await screen.findAllByText(/not read yet/)).toHaveLength(2);
    expect(convertDocument).not.toHaveBeenCalled();
    expect(previewDocumentChunks).not.toHaveBeenCalled();
    expect(uploadDocument).not.toHaveBeenCalled();
  });

  it("reads the file at step 3 and indexes nothing", async () => {
    render(<DocumentUploader />);
    await screen.findByText("Handbook");
    choose();

    fireEvent.click(screen.getByRole("button", { name: /Convert & review/ }));

    // The Markdown is the decision — it is literally what every agent will read.
    expect(await screen.findByText(/body text/)).toBeTruthy();
    // …and the same press answers what ② does to it, from the SAME file. That used to
    // need a second picker and a second choice of the same document.
    fireEvent.click(screen.getByRole("button", { name: "Chunks" }));
    expect(await screen.findByText(/Showing 2 of 3 chunks/)).toBeTruthy();
    expect(screen.getByText(/first chunk/)).toBeTruthy();
    // The property that makes ③ safe to press repeatedly.
    expect(uploadDocument).not.toHaveBeenCalled();
  });

  it("carries changed settings into both calls", async () => {
    render(<DocumentUploader />);
    await screen.findByText("Handbook");
    fireEvent.change(screen.getByLabelText(/Maximum chunk length/), { target: { value: "400" } });
    choose();
    fireEvent.click(screen.getByRole("button", { name: /Convert & review/ }));

    await waitFor(() => expect(previewDocumentChunks).toHaveBeenCalled());
    expect(convertDocument.mock.calls[0][1]).toMatchObject({ max_chars: 400 });
    expect(previewDocumentChunks.mock.calls[0][1]).toMatchObject({ max_chars: 400 });
  });

  it("will not index anything that has not been read", async () => {
    // ⑤ is the only call on the panel that writes. It stays shut until ③ has produced a
    // review, because "confirm" has no meaning if there is nothing to have looked at.
    render(<DocumentUploader />);
    await screen.findByText("Handbook");
    choose();

    const add = screen.getByRole("button", { name: /Add to knowledge/ });
    expect(add.hasAttribute("disabled")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /Convert & review/ }));
    await screen.findByText(/body text/);
    await waitFor(() => expect(add.hasAttribute("disabled")).toBe(false));

    uploadDocument.mockResolvedValue(doc({ doc_id: "d2", filename: "policy.md" }));
    fireEvent.click(add);
    await waitFor(() => expect(uploadDocument).toHaveBeenCalled());
  });

  it("marks a review stale when the settings move under it", async () => {
    // A review describes a document AS CUT BY settings. Change them and it is no longer
    // a description of what would be indexed — so it stops counting as one, rather than
    // standing there looking approved.
    render(<DocumentUploader />);
    await screen.findByText("Handbook");
    choose();
    fireEvent.click(screen.getByRole("button", { name: /Convert & review/ }));
    await screen.findByText(/body text/);

    const add = screen.getByRole("button", { name: /Add to knowledge/ });
    await waitFor(() => expect(add.hasAttribute("disabled")).toBe(false));

    fireEvent.change(screen.getByLabelText(/Maximum chunk length/), { target: { value: "400" } });

    expect(add.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/read under the previous settings/)).toBeTruthy();
  });

  it("names the embedder in force even when everything is healthy", async () => {
    // A corpus is only comparable with itself under ONE model, so which model produced it
    // is part of reading the list — not an error state.
    getKnowledgeStatus.mockResolvedValue(status({
      embedder: { model: "some-embedder", endpoint: "http://x/v1", ok: true, dim: 3072 },
    }));

    render(<DocumentUploader />);

    expect(await screen.findByText(/3072 dimensions/)).toBeTruthy();
    expect(screen.getByText("some-embedder")).toBeTruthy();
  });
});
