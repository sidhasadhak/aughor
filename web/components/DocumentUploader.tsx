"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { formatCount } from "@/lib/format";
import {
  listDocuments,
  uploadDocument,
  previewDocumentChunks,
  deleteDocument,
  getKnowledgeStatus,
  type ChunkPreview,
  type ChunkSettings,
  type DocumentEntry,
  type KnowledgeStatus,
} from "@/lib/api";

const ACCEPTED = ".pdf,.docx,.md,.txt,.markdown";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function FileTypeChip({ filename }: { filename: string }) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, { label: string; chip: string }> = {
    pdf:      { label: "PDF",      chip: "border-red-500/30 bg-red-500/10 text-red-400"          },
    docx:     { label: "Word",     chip: "border-blue-500/30 bg-blue-500/10 text-blue-400"       },
    doc:      { label: "Word",     chip: "border-blue-500/30 bg-blue-500/10 text-blue-400"       },
    md:       { label: "MD",       chip: "border-violet-500/30 bg-violet-500/10 text-violet-400" },
    markdown: { label: "MD",       chip: "border-violet-500/30 bg-violet-500/10 text-violet-400" },
    txt:      { label: "TXT",      chip: "border-zinc-600 bg-zinc-800 text-zinc-400"             },
  };
  const style = map[ext] ?? { label: ext.toUpperCase(), chip: "border-zinc-600 bg-zinc-800 text-zinc-400" };
  return (
    <span className={`aug-fs-xs font-mono px-1.5 py-0.5 rounded border ${style.chip}`}>
      {style.label}
    </span>
  );
}

/** What to say about a document's size.
 *
 *  `chunk_count` is the REGISTRY's claim, and the registry is not the index: measured on a
 *  real install, one document claimed 59 chunks where the store held 5. Showing the claim
 *  alone tells a person their document is searchable when most of it is not, so when the
 *  two disagree, both numbers appear and the store's is the one in front. */
function chunkLabel(doc: DocumentEntry, status: KnowledgeStatus | null): string {
  const drift = status?.consistency.mismatched_documents?.[doc.doc_id];
  const plural = (n: number) => `${n} chunk${n !== 1 ? "s" : ""}`;
  if (!drift) return plural(doc.chunk_count);
  return `${plural(drift.store)} indexed of ${drift.registry} claimed`;
}

export function DocumentUploader() {
  const [docs, setDocs] = useState<DocumentEntry[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const [status, setStatus] = useState<KnowledgeStatus | null>(null);

  // Chunking, as settings rather than three constants nobody could see. Empty means the
  // defaults the corpus was indexed under — an omitted field is the previous behaviour,
  // so a person who never opens this panel gets exactly what they got before.
  const [settings, setSettings] = useState<Partial<ChunkSettings>>({});
  const [preview, setPreview] = useState<ChunkPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewName, setPreviewName] = useState<string>("");
  const previewRef = useRef<HTMLInputElement>(null);

  const setNum = (k: keyof ChunkSettings) => (v: string) => {
    const n = Number(v);
    setSettings(prev => (v === "" || Number.isNaN(n)
      ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== k))
      : { ...prev, [k]: n }));
  };

  const runPreview = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setPreviewError(null);
    setPreviewing(true);
    try {
      setPreviewName(files[0].name);
      setPreview(await previewDocumentChunks(files[0], settings));
    } catch (e) {
      setPreview(null);
      setPreviewError(e instanceof Error ? e.message : "Preview failed");
    } finally {
      setPreviewing(false);
    }
  }, [settings]);

  const refresh = useCallback(() => {
    listDocuments().then(setDocs).catch(() => {});
    // The plane's own account of itself. Without it this panel shows a list of documents
    // and no hint that nothing can be searched — an unreachable embedder looks exactly
    // like a healthy corpus from here.
    getKnowledgeStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const handleFiles = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadError(null);
    setUploading(true);
    const results: DocumentEntry[] = [];
    const errors: string[] = [];
    for (const file of Array.from(files)) {
      try {
        const entry = await uploadDocument(file, settings);
        results.push(entry);
      } catch (e) {
        errors.push(`${file.name}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }
    if (results.length > 0) {
      setDocs(prev => {
        const existing = new Set(prev.map(d => d.doc_id));
        return [...prev, ...results.filter(r => !existing.has(r.doc_id))];
      });
    }
    if (errors.length > 0) setUploadError(errors.join("\n"));
    setUploading(false);
    getKnowledgeStatus().then(setStatus).catch(() => {});
  }, [settings]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const onDragOver = (e: React.DragEvent) => { e.preventDefault(); setDragging(true); };
  const onDragLeave = () => setDragging(false);

  const handleDelete = async (docId: string) => {
    setDeletingId(docId);
    try {
      await deleteDocument(docId);
      setDocs(prev => prev.filter(d => d.doc_id !== docId));
      getKnowledgeStatus().then(setStatus).catch(() => {});
    } catch {
      /* silent */
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h2 className="aug-fs-ui font-semibold text-zinc-200">Documents</h2>
        <p className="aug-fs-xs text-zinc-500 mt-0.5">
          Upload PDFs, Word docs, or Markdown files. Deep analysis and the conversation both
          retrieve relevant snippets.
        </p>
      </div>

      {/* What the plane can actually do. Shown only when something is wrong or drifted —
          a banner that appears on every healthy load is a banner nobody reads. */}
      {status && !status.ready && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
          <p className="aug-fs-sm text-amber-300">Search is unavailable — {status.reason}.</p>
          {!status.embedder.ok && (
            <p className="aug-fs-xs text-zinc-400 font-mono mt-1">
              embedder {status.embedder.model} at {status.embedder.endpoint} · this is a
              LOCAL model, so indexing and search only work where it is running
            </p>
          )}
          <p className="aug-fs-xs text-zinc-500 mt-1">
            Documents already uploaded are unaffected; nothing can be indexed or searched
            until this is resolved.
          </p>
        </div>
      )}
      {status && status.ready && !status.consistency.ok && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
          <p className="aug-fs-sm text-amber-300">
            The index and this list disagree — {status.consistency.listed_chunks_present} of
            the {status.chunks} indexed chunks belong to documents shown here.
          </p>
          {status.consistency.orphan_chunks > 0 && (
            <p className="aug-fs-xs text-zinc-400 mt-1">
              {status.consistency.orphan_chunks} chunk
              {status.consistency.orphan_chunks !== 1 ? "s" : ""} across{" "}
              {status.consistency.orphan_documents} document
              {status.consistency.orphan_documents !== 1 ? "s" : ""} are in the index but not
              listed — they can be found by search and cannot be removed from here.
            </p>
          )}
        </div>
      )}

      {/* Ingest — settings on the left, what they DO on the right.
          Chunk settings and preview both existed in the API and neither was reachable, so
          the only way to see a setting's effect was upload → read a count → delete → try
          again, an embedding call per attempt. Side by side is the whole point: a number
          in a field means nothing until you can see the cut it produces. */}
      <div className="grid gap-4 lg:grid-cols-2 items-start">

        {/* ── left: what to ingest, and how ─────────────────────────────────── */}
        <div className="space-y-4">
          <div
            onDrop={onDrop}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onClick={() => inputRef.current?.click()}
            className={`relative rounded-md border-2 border-dashed p-6 text-center cursor-pointer transition-all ${
              dragging
                ? "border-violet-500 bg-violet-500/10"
                : "border-zinc-600 hover:border-zinc-500 hover:bg-zinc-800/50"
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPTED}
              multiple
              className="hidden"
              onChange={e => handleFiles(e.target.files)}
            />
            {uploading ? (
              <div className="space-y-2">
                <div className="h-5 w-5 rounded-[var(--r-pill)] border-2 border-violet-500 border-t-transparent animate-spin mx-auto" />
                <p className="aug-fs-ui text-zinc-400">Indexing…</p>
              </div>
            ) : (
              <div className="space-y-1">
                <p className="aug-fs-h2">📄</p>
                <p className="aug-fs-ui text-zinc-300 font-medium">
                  {dragging ? "Drop to upload" : "Drop files here or click to browse"}
                </p>
                <p className="aug-fs-xs text-zinc-500">PDF · Word · Markdown · Plain text</p>
              </div>
            )}
          </div>

          <div className="rounded-md border border-zinc-700 bg-zinc-900/40 p-4 space-y-4">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="aug-fs-ui font-semibold text-zinc-200">Chunk settings</h3>
                <span className="aug-fs-xs text-zinc-500 border border-zinc-700 rounded-[var(--r-pill)] px-1.5">
                  General
                </span>
                <span className="aug-fs-xs text-zinc-600 ml-auto">
                  {Object.keys(settings).length === 0
                    ? "defaults"
                    : `${Object.keys(settings).length} changed`}
                </span>
              </div>
              <p className="aug-fs-xs text-zinc-500 mt-1">
                One chunk per delimiter block. The same chunk is retrieved and given as context.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block aug-fs-xs text-zinc-400 mb-1" htmlFor="chunk-delimiter">
                  Delimiter
                </label>
                <input
                  id="chunk-delimiter"
                  type="text"
                  value={settings.delimiter ?? ""}
                  placeholder="\n\n"
                  onChange={e => setSettings(prev => (e.target.value
                    ? { ...prev, delimiter: e.target.value }
                    : Object.fromEntries(Object.entries(prev).filter(([k]) => k !== "delimiter"))))}
                  className="aug-input w-full font-mono"
                />
              </div>
              {([
                ["max_chars", "Maximum chunk length", "characters"],
                ["overlap_chars", "Chunk overlap", "characters"],
                ["min_chars", "Minimum chunk length", "below this a chunk is DISCARDED"],
              ] as const).map(([key, label, hint]) => (
                <div key={key}>
                  <label className="block aug-fs-xs text-zinc-400 mb-1" htmlFor={`chunk-${key}`}>
                    {label}
                  </label>
                  <input
                    id={`chunk-${key}`}
                    type="number"
                    min={1}
                    value={settings[key] ?? ""}
                    placeholder={String(preview?.settings?.[key] ?? "default")}
                    onChange={e => setNum(key)(e.target.value)}
                    className="aug-input w-full"
                  />
                  <p className="aug-fs-xs text-zinc-600 mt-1">{hint}</p>
                </div>
              ))}
            </div>

            <div>
              <p className="aug-fs-xs text-zinc-300 font-medium">Text pre-processing rules</p>
              <p className="aug-fs-xs text-zinc-600 mb-2">Applied before chunking and embedding.</p>
              <label className="flex items-center gap-2 aug-fs-xs text-zinc-400 mb-1">
                <input
                  type="checkbox"
                  checked={settings.collapse_whitespace ?? true}
                  onChange={e => setSettings(prev => ({ ...prev, collapse_whitespace: e.target.checked }))}
                />
                Replace consecutive spaces, newlines and tabs
              </label>
              <label className="flex items-center gap-2 aug-fs-xs text-zinc-400">
                <input
                  type="checkbox"
                  checked={settings.strip_urls_emails ?? false}
                  onChange={e => setSettings(prev => ({ ...prev, strip_urls_emails: e.target.checked }))}
                />
                Delete all URLs and email addresses
              </label>
              <p className="aug-fs-xs text-zinc-600 mt-2">
                Off by default: a policy that cites a source loses the citation.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => previewRef.current?.click()}
                disabled={previewing}
                className="aug-fs-xs px-2.5 py-1.5 rounded border border-zinc-600 text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
              >
                {previewing ? "Chunking…" : "Preview chunks"}
              </button>
              <input
                ref={previewRef}
                type="file"
                accept={ACCEPTED}
                className="hidden"
                onChange={e => runPreview(e.target.files)}
              />
              <button
                type="button"
                onClick={() => { setSettings({}); setPreview(null); setPreviewName(""); }}
                className="aug-fs-xs px-2.5 py-1.5 rounded border border-zinc-700 text-zinc-400 hover:bg-zinc-800"
              >
                Reset
              </button>
            </div>
            {previewError && <p className="aug-fs-xs text-red-400">{previewError}</p>}
          </div>

          {/* The model in force. A corpus is only comparable with itself under ONE model,
              so this is part of reading the list — not an error state. It is chosen by
              configuration, and saying so beats a picker that could not take effect. */}
          <div className="rounded-md border border-zinc-700 bg-zinc-900/40 p-4">
            <h3 className="aug-fs-ui font-semibold text-zinc-200">Embedding model</h3>
            {status?.embedder?.ok ? (
              <>
                <div className="mt-2 flex items-baseline justify-between">
                  <span className="aug-fs-xs text-zinc-500">Model</span>
                  <span className="aug-fs-xs text-zinc-200 font-mono">{status.embedder.model}</span>
                </div>
                {status.embedder.dim != null && (
                  <div className="mt-1 flex items-baseline justify-between">
                    <span className="aug-fs-xs text-zinc-500">Vector width</span>
                    <span className="aug-fs-xs text-zinc-200 font-mono">
                      {status.embedder.dim} dimensions
                    </span>
                  </div>
                )}
                <p className="aug-fs-xs text-zinc-600 mt-2">
                  Set by configuration, not here. Changing it means re-embedding the whole
                  corpus — a different model is a different vector space.
                </p>
              </>
            ) : (
              <p className="aug-fs-xs text-zinc-500 mt-2">
                No embedder is answering, so nothing can be indexed or searched.
              </p>
            )}
          </div>
        </div>

        {/* ── right: what those settings actually do ─────────────────────────── */}
        <div className="rounded-md border border-zinc-700 bg-zinc-900/40 p-4 lg:sticky lg:top-2">
          <h3 className="aug-fs-ui font-semibold text-zinc-200">Preview</h3>
          <p className="aug-fs-xs text-zinc-500 mt-0.5">
            {preview
              ? `${previewName || "document"} · ${formatCount(preview.total_chunks)} chunk${preview.total_chunks !== 1 ? "s" : ""} · ${formatCount(preview.characters)} characters`
              : "Indexes nothing — no embedder, no writes. Works while search is down."}
          </p>

          {!preview ? (
            <p className="aug-fs-xs text-zinc-600 mt-4">
              Choose a file with <span className="text-zinc-400">Preview chunks</span> to see
              how these settings cut it, before anything is embedded.
            </p>
          ) : (
            <div className="mt-3 space-y-2">
              <p className="aug-fs-xs text-zinc-500">
                Showing {preview.shown} of {formatCount(preview.total_chunks)} chunks
              </p>
              {preview.chunks.map(c => (
                <div key={c.index} className="rounded border border-zinc-800 bg-zinc-950/60 p-2.5">
                  <p className="aug-fs-xs text-zinc-500 font-mono mb-1">
                    <span className="text-zinc-300">Chunk-{c.index + 1}</span>
                    {" · "}{formatCount(c.characters)} characters
                    {" · "}~{formatCount(c.tokens_estimate)} tokens
                  </p>
                  <p className="aug-fs-xs text-zinc-400 whitespace-pre-wrap line-clamp-6">
                    {c.text}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Error */}
      {uploadError && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 aug-fs-xs text-red-400 whitespace-pre-wrap font-mono">
          {uploadError}
        </div>
      )}

      {/* Document list */}
      {docs.length > 0 && (
        <div className="space-y-2">
          <p className="aug-fs-xs text-zinc-500 uppercase tracking-widest font-mono">
            {docs.length} document{docs.length !== 1 ? "s" : ""} indexed
          </p>
          <div className="space-y-2">
            {docs.map(doc => (
              <div
                key={doc.doc_id}
                className="rounded-md border border-zinc-700 bg-zinc-800/50 px-4 py-3 flex items-center gap-3"
              >
                <FileTypeChip filename={doc.filename} />
                <div className="flex-1 min-w-0">
                  <p className="aug-fs-sm font-medium text-zinc-200 truncate">{doc.title}</p>
                  <p className="aug-fs-xs text-zinc-500 font-mono mt-0.5">
                    {doc.filename} · {chunkLabel(doc, status)} · {timeAgo(doc.uploaded_at)}
                  </p>
                </div>
                <button
                  onClick={() => handleDelete(doc.doc_id)}
                  disabled={deletingId === doc.doc_id}
                  className="shrink-0 aug-fs-xs text-zinc-500 hover:text-red-400 border border-zinc-700 hover:border-red-500/40 rounded px-2 py-1 transition"
                >
                  {deletingId === doc.doc_id ? "…" : "Remove"}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {docs.length === 0 && !uploading && (
        <p className="aug-fs-xs text-zinc-500 text-center py-4">
          No documents yet. Upload one above to give deep analysis external context.
        </p>
      )}
    </div>
  );
}
