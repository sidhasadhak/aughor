// @vitest-environment jsdom
/**
 * KB-3 — the Documents screen showed a corpus and never said whether it worked.
 *
 * Two things were invisible from here:
 *
 *  - **The plane's availability.** Embeddings come from a LOCAL Ollama, so on any deploy
 *    without it nothing indexes and every search returns empty — while this list of
 *    documents renders exactly as it does on a healthy machine.
 *  - **That `chunk_count` is a CLAIM.** It comes from the registry, not the index. Measured
 *    on a real install, one document claimed 59 chunks where the store held 5, and this
 *    screen reported 59 with no hint that most of it is unsearchable.
 *
 * The status call is allowed to fail — the API serving this UI may predate the endpoint —
 * so the third property held here is that an absent status changes nothing.
 *
 * Since the screen was redone to CLARITY (2026-10-13) the plane's state is a row under "Needs you", and the add-a-
 * document wizard opens from its button instead of standing open; the curation tests open it first. What they hold is
 * unchanged: nothing is read until step 3, nothing is stored until step 5, and moving the settings stales a review.
 */
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentEntry, KnowledgeStatus } from "@/lib/api";

const listDocuments = vi.fn();
// The screen renders KnowledgeSourcesSection beside the corpus, which loads the connected wikis on mount. Unmocked,
// that call reached the developer's running platform for real (the setup file's network guard turned it into
// unhandled rejections and the whole web suite exited non-zero while every test passed). Nothing here asserts on that
// section, so it answers what a fresh install answers: the endpoint is there, nothing is connected.
const getKnowledgeSources = vi.fn(async (..._a: unknown[]) => ({ types: [], sources: [] }));
const getKnowledgeStatus = vi.fn();
const previewDocumentChunks = vi.fn();
const convertDocument = vi.fn();
const uploadDocument = vi.fn();
const purgeOrphanChunks = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    listDocuments: (...a: unknown[]) => listDocuments(...a),
    getKnowledgeSources: (...a: unknown[]) => getKnowledgeSources(...a),
    getKnowledgeStatus: (...a: unknown[]) => getKnowledgeStatus(...a),
    previewDocumentChunks: (...a: unknown[]) => previewDocumentChunks(...a),
    convertDocument: (...a: unknown[]) => convertDocument(...a),
    uploadDocument: (...a: unknown[]) => uploadDocument(...a),
    purgeOrphanChunks: (...a: unknown[]) => purgeOrphanChunks(...a),
    getDocumentFormats: async () => null,
    deleteDocument: vi.fn(),
  };
});

const { DocumentsPage } = await import("@/components/documents/DocumentsPage");

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

const page = () => render(<DocumentsPage connectionId="c1" connections={[]} />);

/** A document in the list (the newest is also named on the "Last added" figure). */
const listed = async (text: string) => within(await screen.findByTestId("documents-list")).findByText(text);

/** The wizard is a tool now — opened from the list's label, never standing open. */
const openAdd = async () => {
  await listed("Handbook");
  fireEvent.click(screen.getByRole("button", { name: "Add a document" }));
  return screen.getByRole("region", { name: "Add a document" });
};

/** ① — choosing a file. The wizard makes no request for this, by design. */
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

describe("what the screen says about the plane", () => {
  it("says nothing needs you when everything is healthy", async () => {
    page();
    await listed("Handbook");

    const needs = await screen.findByRole("region", { name: "Needs you" });
    await waitFor(() => expect(needs).toHaveAttribute("data-waiting", "false"));
    expect(screen.queryByText(/Search is unavailable/)).toBeNull();
    expect(screen.queryByText(/disagree/)).toBeNull();
  });

  it("names an unreachable embedder, and that it is a local one", async () => {
    getKnowledgeStatus.mockResolvedValue(status({
      ready: false, reason: "the embedder is unreachable",
      embedder: { model: "nomic-embed-text", endpoint: "http://localhost:11434/v1",
                  ok: false, error: "ConnectionError: connection refused" },
    }));

    page();

    expect(await screen.findByText(/Search is unavailable/)).toBeTruthy();
    expect(screen.getByText(/A local model/)).toBeTruthy();
    expect(screen.getByText(/localhost:11434/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Needs you" })).toHaveAttribute("data-waiting", "true");
  });

  it("reassures that uploaded documents survive an outage", async () => {
    getKnowledgeStatus.mockResolvedValue(status({ ready: false, reason: "no documents are indexed" }));

    page();

    expect(await screen.findByText(/Documents already uploaded are unaffected/)).toBeTruthy();
  });
});

describe("what the screen says about the numbers", () => {
  it("shows the registry's claim when the index agrees with it", async () => {
    listDocuments.mockResolvedValue([doc({ chunk_count: 5 })]);

    page();

    expect(await screen.findByText("5 chunks")).toBeTruthy();
  });

  it("puts the INDEXED count in front when the two disagree", async () => {
    /** The defect this exists for: 59 rendered as fact while 54 of those passages are not
     *  searchable. Both numbers, the index's first — on the row and under "Needs you". */
    getKnowledgeStatus.mockResolvedValue(status({
      consistency: { ok: false, orphan_documents: 0, orphan_chunks: 0, orphans: [],
                     mismatched_documents: { d1: { registry: 59, store: 5 } },
                     listed_chunks_present: 5 },
    }));

    page();

    expect(await screen.findByText("5 of 59 indexed")).toBeTruthy();
    const needs = screen.getByRole("region", { name: "Needs you" });
    expect(within(needs).getByText(/index and this list disagree on 1 document/)).toBeTruthy();
    expect(within(needs).getByText(/the index holds 5 of their 59 listed chunks/)).toBeTruthy();
  });

  it("reports orphan chunks and offers the purge door (PX-6)", async () => {
    /** Orphans are found by search; the screen used to say they "cannot be removed from here" — true until the purge
     *  endpoint got its button. Now the row names the fact and the door sits on it, no re-embed implied. */
    getKnowledgeStatus.mockResolvedValue(status({
      chunks: 46,
      consistency: { ok: false, orphan_documents: 5, orphan_chunks: 41,
                     orphans: ["ghost"], mismatched_documents: {},
                     listed_chunks_present: 5 },
    }));
    purgeOrphanChunks.mockResolvedValue({ orphans_purged: 41 });

    page();

    expect(await screen.findByText(/41 chunks across 5 documents are in the index but not listed/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Purge orphans \(no re-embed\)/ }));
    await waitFor(() => expect(purgeOrphanChunks).toHaveBeenCalledWith(false));
    expect(await screen.findByText(/Purged 41/)).toBeTruthy();
  });
});

describe("degradation", () => {
  it("renders unchanged when the status endpoint is absent", async () => {
    /** The API serving this UI may predate `/knowledge/status` — and then it 404s. A screen that broke on that would
     *  be a regression shipped to every user whose server is one deploy behind. */
    getKnowledgeStatus.mockResolvedValue(null);

    page();

    expect(await listed("Handbook")).toBeTruthy();
    expect(screen.getByText("59 chunks")).toBeTruthy();
    expect(screen.queryByText(/Search is unavailable/)).toBeNull();
    // the figure cannot say what the index holds, and says so rather than showing the claim as the index's
    expect(screen.getByTestId("fig-chunks-value")).toHaveTextContent("—");
  });

  it("still lists documents when the status call throws", async () => {
    getKnowledgeStatus.mockRejectedValue(new Error("network"));

    page();

    expect(await listed("Handbook")).toBeTruthy();
  });
});


describe("curation — settings that were only reachable through the API", () => {
  it("keeps the wizard behind its button, and opens it at the defaults the corpus was indexed under", async () => {
    page();
    await listed("Handbook");
    // read first: the five steps are a tool, not a form standing open on every visit
    expect(screen.queryByLabelText(/Maximum chunk length/)).toBeNull();

    const add = await openAdd();

    // Not "0 changed": a person who never touches this gets the previous behaviour, and the label has to say so
    // rather than imply an empty configuration.
    expect(within(add).getByText("defaults")).toBeTruthy();
    // Once open, the fields are in front of the reader, not behind a second disclosure.
    expect(screen.getByLabelText(/Maximum chunk length/)).toBeTruthy();
    expect(screen.getByLabelText(/Chunk overlap/)).toBeTruthy();
  });

  it("makes no request at all when a file is merely chosen", async () => {
    // ① is a choice, not a commitment. Dropping a file used to convert it on the spot, under whatever was in the
    // settings fields — which put ② after the conversion it was supposed to govern, and spent a conversion on every
    // misdrop.
    page();
    await openAdd();

    choose();

    // Both ① and ④ say so — the tray and the reader agree that nothing has been read.
    expect(await screen.findAllByText(/not read yet/)).toHaveLength(2);
    expect(convertDocument).not.toHaveBeenCalled();
    expect(previewDocumentChunks).not.toHaveBeenCalled();
    expect(uploadDocument).not.toHaveBeenCalled();
  });

  it("reads the file at step 3 and indexes nothing", async () => {
    page();
    await openAdd();
    choose();

    fireEvent.click(screen.getByRole("button", { name: /Convert & review/ }));

    // The Markdown is the decision — it is literally what every agent will read.
    expect(await screen.findByText(/body text/)).toBeTruthy();
    // …and the same press answers what ② does to it, from the SAME file. That used to need a second picker and a
    // second choice of the same document.
    fireEvent.click(screen.getByRole("radio", { name: "Chunks" }));
    expect(await screen.findByText(/Showing 2 of 3 chunks/)).toBeTruthy();
    expect(screen.getByText(/first chunk/)).toBeTruthy();
    // The property that makes ③ safe to press repeatedly.
    expect(uploadDocument).not.toHaveBeenCalled();
  });

  it("carries changed settings into both calls", async () => {
    page();
    await openAdd();
    fireEvent.change(screen.getByLabelText(/Maximum chunk length/), { target: { value: "400" } });
    choose();
    fireEvent.click(screen.getByRole("button", { name: /Convert & review/ }));

    await waitFor(() => expect(previewDocumentChunks).toHaveBeenCalled());
    expect(convertDocument.mock.calls[0][1]).toMatchObject({ max_chars: 400 });
    expect(previewDocumentChunks.mock.calls[0][1]).toMatchObject({ max_chars: 400 });
  });

  it("will not index anything that has not been read, and lists what landed", async () => {
    // ⑤ is the only call in the wizard that writes. It stays shut until ③ has produced a review, because "confirm"
    // has no meaning if there is nothing to have looked at.
    page();
    await openAdd();
    choose();

    const add = screen.getByRole("button", { name: /Add to knowledge/ });
    expect(add.hasAttribute("disabled")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /Convert & review/ }));
    await screen.findByText(/body text/);
    await waitFor(() => expect(add.hasAttribute("disabled")).toBe(false));

    uploadDocument.mockResolvedValue(doc({ doc_id: "d2", filename: "policy.md", title: "Policy", chunk_count: 3 }));
    fireEvent.click(add);
    await waitFor(() => expect(uploadDocument).toHaveBeenCalled());
    // the screen's list takes in what landed, and its status is read again
    expect(await listed("Policy")).toBeTruthy();
    expect(screen.getByTestId("fig-documents-value")).toHaveTextContent("2");
  });

  it("marks a review stale when the settings move under it", async () => {
    // A review describes a document AS CUT BY settings. Change them and it is no longer a description of what would
    // be indexed — so it stops counting as one, rather than standing there looking approved.
    page();
    await openAdd();
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
    // A corpus is only comparable with itself under ONE model, so which model produced it is part of reading the
    // screen — not an error state. It is a fact on the chunks figure now, its width on hover.
    getKnowledgeStatus.mockResolvedValue(status({
      embedder: { model: "some-embedder", endpoint: "http://x/v1", ok: true, dim: 3072 },
    }));

    page();

    const chip = await screen.findByTestId("embedder-chip");
    expect(chip).toHaveTextContent("some-embedder");
    expect(chip.getAttribute("title")).toMatch(/3072 dimensions/);
  });
});


describe("a failed read is said, never shown as an empty corpus", () => {
  it("says the documents and the search status could not be read, with a Retry", async () => {
    listDocuments.mockRejectedValue(new Error("Reading the documents failed (502)"));
    getKnowledgeStatus.mockRejectedValue(new Error("Reading the search status failed (502)"));

    page();

    expect(await screen.findByText(/Could not read the documents/)).toBeInTheDocument();
    expect(screen.getByText(/Could not read the search status/)).toBeInTheDocument();
    expect(screen.queryByText(/No documents yet/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Retry" }).length).toBe(2);
  });
});
