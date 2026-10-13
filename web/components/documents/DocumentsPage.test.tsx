// @vitest-environment jsdom
/**
 * The Documents screen, redone to CLARITY (2026-10-13): it opens on four figures, says what needs a person once, folds
 * the platform's compiled schema documents under a person's own uploads, and keeps its two tools behind buttons.
 * Fixtures are the shape of a live install's (7 compiled schema documents, 51 chunks indexed of 61 listed, two
 * documents the index holds none of).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentEntry, KnowledgeStatus } from "@/lib/api";
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";

const listDocuments = vi.fn();
const getKnowledgeStatus = vi.fn();
const getKnowledgeSources = vi.fn();
const getDocumentConvertFormats = vi.fn();
const deleteDocument = vi.fn();

vi.mock("@/lib/api", async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  listDocuments: (...a: unknown[]) => listDocuments(...a),
  getKnowledgeStatus: (...a: unknown[]) => getKnowledgeStatus(...a),
  getKnowledgeSources: (...a: unknown[]) => getKnowledgeSources(...a),
  getDocumentConvertFormats: (...a: unknown[]) => getDocumentConvertFormats(...a),
  deleteDocument: (...a: unknown[]) => deleteDocument(...a),
  getDocumentFormats: async () => null,
}));

const { DocumentsPage } = await import("@/components/documents/DocumentsPage");

const connections = [
  { id: "baef6c3e", name: "DuckDB" }, { id: "dcc63d83", name: "PostgreSQL" },
  { id: "8233e4fd", name: "theLook" }, { id: "workspace", name: "Workspace" },
];

const schemaDoc = (conn: string, schema: string, chunks: number, at: string): DocumentEntry => ({
  doc_id: `doctree::${conn}::${schema}`, filename: `schema-docs/${conn}/${schema}`,
  title: `Schema documentation — ${conn}/${schema}`, chunk_count: chunks, uploaded_at: at, generated: true,
  has_original: false,
});

const LIVE: DocumentEntry[] = [
  schemaDoc("baef6c3e", "ecommerce", 9, "2026-08-04T15:58:54Z"),
  schemaDoc("baef6c3e", "main", 1, "2026-08-15T14:08:08Z"),
  schemaDoc("dcc63d83", "luxexperience", 33, "2026-10-12T01:47:17Z"),
  schemaDoc("dcc63d83", "gold_governance", 5, "2026-10-12T12:02:36Z"),
  schemaDoc("dcc63d83", "gold_finance", 4, "2026-10-12T12:02:40Z"),
  schemaDoc("8233e4fd", "thelook", 8, "2026-10-12T14:40:38Z"),
  schemaDoc("workspace", "uber_ncr", 1, "2026-10-13T01:49:38Z"),
];

const STATUS: KnowledgeStatus = {
  ready: true, reason: "", documents: 7, chunks: 51,
  embedder: { backend: "ollama", model: "nomic-embed-text", endpoint: "http://localhost:11434/v1", ok: true, dim: 768 },
  store: { ok: true, backend: "qdrant", chunks: 51 },
  consistency: { ok: false, orphan_documents: 0, orphan_chunks: 0, orphans: [], listed_chunks_present: 51,
    mismatched_documents: { "doctree::baef6c3e::ecommerce": { registry: 9, store: 0 },
                            "doctree::baef6c3e::main": { registry: 1, store: 0 } } },
};

beforeEach(() => {
  vi.clearAllMocks();
  listDocuments.mockResolvedValue(LIVE);
  getKnowledgeStatus.mockResolvedValue(STATUS);
  getKnowledgeSources.mockResolvedValue({
    types: [{ conn_type: "confluence", label: "Confluence", fields: [] }, { conn_type: "notion", label: "Notion", fields: [] }],
    sources: [] });
});

const page = () => render(<DocumentsPage connectionId="8233e4fd" connections={connections} />);

describe("the figures row", () => {
  it("leads with documents · chunks the INDEX holds · sources · the newest, in the reader's words", async () => {
    page();
    const figs = await screen.findByTestId("documents-figures");
    await waitFor(() => expect(screen.getByTestId("fig-documents-value")).toHaveTextContent("7"));

    expect(within(figs).getByText("all compiled from your schemas")).toBeInTheDocument();
    // the index's count, not the list's claim of 61 — and the claim beside it
    expect(screen.getByTestId("fig-chunks-value")).toHaveTextContent("51");
    expect(within(figs).getByText("of 61 listed")).toBeInTheDocument();
    expect(within(figs).getByTestId("embedder-chip")).toHaveTextContent("nomic-embed-text");
    await waitFor(() => expect(screen.getByTestId("fig-sources-value")).toHaveTextContent("0"));
    expect(within(figs).getByText("Confluence · Notion")).toBeInTheDocument();
    // the newest document, its connection named — never `workspace/uber_ncr` or an id
    expect(within(screen.getByTestId("fig-newest")).getByText("Workspace · uber_ncr")).toBeInTheDocument();
    expect(screen.getByTestId("fig-newest-value").textContent).toMatch(/^\d{1,2} [A-Z][a-z]{2}$/);
  });

  it("says the index's count is unknown when the status is not read, rather than passing off the claim", async () => {
    getKnowledgeStatus.mockRejectedValue(new Error("network"));
    page();
    await waitFor(() => expect(screen.getByTestId("fig-documents-value")).toHaveTextContent("7"));
    expect(screen.getByTestId("fig-chunks-value")).toHaveTextContent("—");
    expect(within(screen.getByTestId("fig-chunks")).getByText("search status not read")).toBeInTheDocument();
  });
});

describe("said once, folded into a count", () => {
  it("names the disagreement once under Needs you, totalled, and leaves the per-document counts to the rows", async () => {
    page();
    const needs = await screen.findByRole("region", { name: "Needs you" });
    await within(needs).findByText("The index and this list disagree on 2 documents");
    expect(needs).toHaveAttribute("data-waiting", "true");
    expect(within(needs).getByText(/DuckDB · ecommerce, DuckDB · main — the index holds 0 of their 10 listed chunks/))
      .toBeInTheDocument();
    // one row for the disagreement, however many documents it covers
    expect(within(needs).getAllByTestId("needs-drift")).toHaveLength(1);

    const list = screen.getByTestId("documents-list");
    expect(within(list).getByText("0 of 9 indexed")).toBeInTheDocument();
    expect(within(list).getByText("33 chunks")).toBeInTheDocument();
    // no id reaches the reader as a name
    expect(within(list).queryByText(/baef6c3e|8233e4fd|dcc63d83/)).toBeNull();
    // the group says what they are; no row repeats it as a chip
    expect(within(list).getByText("Compiled from your schemas")).toBeInTheDocument();
    expect(within(list).queryByText("Schema")).toBeNull();
  });

  it("shows the compiled schema documents open when they are all there is", async () => {
    page();
    const list = await screen.findByTestId("documents-list");
    expect(await within(list).findAllByTestId("document-row")).toHaveLength(7);
    expect(within(list).queryByTestId("schema-docs-fold")).toBeNull();
  });

  it("folds them into one line with their count under a person's own uploads", async () => {
    listDocuments.mockResolvedValue([
      { doc_id: "u1", filename: "policy.pdf", title: "Refund policy", chunk_count: 12, uploaded_at: "2026-10-13T09:00:00Z",
        has_original: true },
      ...LIVE,
    ]);
    getKnowledgeStatus.mockResolvedValue({ ...STATUS, chunks: 63 });
    page();
    const list = await screen.findByTestId("documents-list");
    await within(list).findByText("Refund policy");
    // one upload row; the seven compiled ones are one line with their count until opened
    expect(within(list).getAllByTestId("document-row")).toHaveLength(1);
    expect(within(list).getByText("PDF")).toBeInTheDocument();
    const fold = within(list).getByTestId("schema-docs-fold");
    expect(fold).toHaveTextContent("Compiled from your schemas · 7 · 51 chunks");
    fireEvent.click(fold);
    expect(within(list).getAllByTestId("document-row")).toHaveLength(8);
    expect(within(screen.getByTestId("fig-documents")).getByText("1 uploaded · 7 from your schemas")).toBeInTheDocument();
  });
});

describe("an upload's actions, on its row", () => {
  it("keeps View on the row and open-original, download-as and remove in its one menu", async () => {
    listDocuments.mockResolvedValue([{ doc_id: "u1", filename: "policy.pdf", title: "Refund policy", chunk_count: 12,
      uploaded_at: "2026-10-13T09:00:00Z", has_original: true }]);
    getKnowledgeStatus.mockResolvedValue({ ...STATUS, chunks: 12, consistency: { ...STATUS.consistency, ok: true,
      mismatched_documents: {}, listed_chunks_present: 12 } });
    getDocumentConvertFormats.mockResolvedValue([
      { format: "docx", label: "Word", media_type: "", suffix: ".docx", available: true },
      { format: "pdf", label: "PDF", media_type: "", suffix: ".pdf", available: false },
    ]);
    deleteDocument.mockResolvedValue(undefined);
    page();
    const list = await screen.findByTestId("documents-list");
    await within(list).findByText("Refund policy");
    expect(within(list).getByRole("button", { name: "View" })).toBeInTheDocument();

    fireEvent.keyDown(within(list).getByRole("button", { name: "More for Refund policy" }), { key: "Enter" });
    expect(await screen.findByRole("menuitem", { name: "Download as Word" })).toHaveAttribute("href",
      expect.stringContaining("/documents/u1/convert?to=docx"));
    // a format this deployment cannot write is shown, saying so — not hidden
    expect(screen.getByRole("menuitem", { name: /Download as PDF · not installed/ })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("menuitem", { name: "Open the original file" })).toHaveAttribute("href",
      expect.stringContaining("/documents/u1/original"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Remove" }));
    await waitFor(() => expect(deleteDocument).toHaveBeenCalledWith("u1"));
    await waitFor(() => expect(within(list).queryByText("Refund policy")).toBeNull());
  });
});

describe("read first — the tools open on demand", () => {
  it("keeps the checker and the five steps behind their buttons", async () => {
    page();
    await screen.findByTestId("documents-list");
    expect(screen.queryByLabelText("Memo to check")).toBeNull();
    expect(screen.queryByRole("region", { name: "Add a document" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Check a document/ }));
    const check = screen.getByRole("region", { name: "Check a document's numbers" });
    // the cost is a fact beside the title, said before the button
    expect(within(check).getByText("a few model calls per claim")).toBeInTheDocument();
    expect(within(check).getByText("first 25 claims")).toBeInTheDocument();
    expect(within(check).getByText(/checked against theLook's data/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add a document" }));
    expect(screen.getByRole("region", { name: "Add a document" })).toBeInTheDocument();
    // one tool open at a time; the closed one keeps its state, hidden
    expect(screen.queryByRole("region", { name: "Check a document's numbers" })).toBeNull();
  });
});
