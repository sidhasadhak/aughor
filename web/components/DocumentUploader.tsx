"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { formatCount } from "@/lib/format";
import { KnowledgeSourcesSection } from "@/components/KnowledgeSourcesSection";
import {
  listDocuments,
  uploadDocument,
  previewDocumentChunks,
  deleteDocument,
  getKnowledgeStatus,
  getDocumentFormats,
  getDocumentMarkdown,
  getDocumentConvertFormats,
  convertDocument,
  documentOriginalUrl,
  documentConvertUrl,
  type ChunkPreview,
  type ChunkSettings,
  type DocumentEntry,
  type DocumentFormats,
  type DocumentConversion,
  type ConvertFormat,
  type KnowledgeStatus,
} from "@/lib/api";

/** Until the server answers, accept only what needs no converter. The list used to be
 *  a hard-coded five and stayed five while the parser grew to twenty — a capability
 *  that exists and is unreachable from the file picker. This is a floor, not the list. */
const FALLBACK_ACCEPT = ".md,.markdown,.txt";

/** A one-file FileList, so the approval path reuses the same uploader the drop zone
 *  used to call — one code path indexes, whatever route reached it. */
function fileListOf(file: File): FileList {
  const dt = new DataTransfer();
  dt.items.add(file);
  return dt.files;
}

/** Formats a browser can display on its own. Everything else previews as Markdown —
 *  which is what the platform actually reads anyway, so it is the honest preview. */
const BROWSER_RENDERABLE = new Set([".pdf", ".txt", ".md", ".markdown", ".csv"]);

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
    docm:     { label: "Word",     chip: "border-blue-500/30 bg-blue-500/10 text-blue-400"       },
    odt:      { label: "ODT",      chip: "border-blue-500/30 bg-blue-500/10 text-blue-400"       },
    rtf:      { label: "RTF",      chip: "border-blue-500/30 bg-blue-500/10 text-blue-400"       },
    pptx:     { label: "Slides",   chip: "border-orange-500/30 bg-orange-500/10 text-orange-400" },
    ppt:      { label: "Slides",   chip: "border-orange-500/30 bg-orange-500/10 text-orange-400" },
    pptm:     { label: "Slides",   chip: "border-orange-500/30 bg-orange-500/10 text-orange-400" },
    odp:      { label: "Slides",   chip: "border-orange-500/30 bg-orange-500/10 text-orange-400" },
    xlsx:     { label: "Sheet",    chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" },
    xls:      { label: "Sheet",    chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" },
    xlsm:     { label: "Sheet",    chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" },
    xlsb:     { label: "Sheet",    chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" },
    ods:      { label: "Sheet",    chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" },
    csv:      { label: "CSV",      chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" },
    epub:     { label: "EPUB",     chip: "border-cyan-500/30 bg-cyan-500/10 text-cyan-400"       },
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
  const [partialNotes, setPartialNotes] = useState<string[]>([]);
  const [suppressedNotes, setSuppressedNotes] = useState<string[]>([]);

  // Files converted and WAITING for a decision. Nothing here has been indexed, paid
  // for, or written anywhere — the File objects are held in the browser and posted
  // again on approval, so there is no staging area on the server to expire or leak.
  const [pending, setPending] = useState<{ file: File; result: DocumentConversion }[]>([]);
  const [converting, setConverting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const [status, setStatus] = useState<KnowledgeStatus | null>(null);

  // What this deployment can read, asked of it rather than assumed.
  const [formats, setFormats] = useState<DocumentFormats | null>(null);
  const accept = formats?.accept ?? FALLBACK_ACCEPT;

  // Looking at a document that is already stored — distinct from the CHUNK preview
  // beside the settings, which is about how a file would be cut. This one is about
  // the document itself: the file as uploaded, and the Markdown everything reads.
  const [openDoc, setOpenDoc] = useState<DocumentEntry | null>(null);
  const [openTab, setOpenTab] = useState<"original" | "markdown">("original");
  const [openMarkdown, setOpenMarkdown] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [convertFormats, setConvertFormats] = useState<ConvertFormat[]>([]);

  // Chunking, as settings rather than three constants nobody could see. Empty means the
  // defaults the corpus was indexed under — an omitted field is the previous behaviour,
  // so a person who never opens this panel gets exactly what they got before.
  const [settings, setSettings] = useState<Partial<ChunkSettings>>({});
  const [preview, setPreview] = useState<ChunkPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewName, setPreviewName] = useState<string>("");
  const previewRef = useRef<HTMLInputElement>(null);

  // The server flags which rows it compiled; this surface only decides how to show
  // them. `generated === undefined` (an older API) counts as an upload — a person's own
  // document must never be the thing that gets folded away by a missing field.
  const uploaded = docs.filter(d => !d.generated);
  const generated = docs.filter(d => d.generated);
  const generatedChunks = generated.reduce((n, d) => n + (d.chunk_count ?? 0), 0);

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
    getDocumentFormats().then(setFormats).catch(() => setFormats(null));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  /** Convert what was dropped and show it. Indexes nothing.
   *
   *  Dropping a file used to convert, chunk, embed and register in one motion, so the
   *  first sight of what the converter made of it came after it was in the corpus —
   *  and on a hosted embedder, already paid for. Now the result is shown and waits. */
  const convertFiles = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadError(null);
    setPartialNotes([]);
    setSuppressedNotes([]);
    setConverting(true);
    const converted: { file: File; result: DocumentConversion }[] = [];
    const errors: string[] = [];
    for (const file of Array.from(files)) {
      try {
        converted.push({ file, result: await convertDocument(file, settings) });
      } catch (e) {
        errors.push(`${file.name}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }
    setPending(prev => [...prev, ...converted]);
    if (errors.length > 0) setUploadError(errors.join("\n"));
    setConverting(false);
  }, [settings]);

  const discardPending = (name: string) =>
    setPending(prev => prev.filter(p => p.file.name !== name));

  const handleFiles = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadError(null);
    setPartialNotes([]);
    setSuppressedNotes([]);
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
    // A part-scanned PDF is a SUCCESS with a hole in it. Reported beside the errors
    // rather than inside them, because the document did import and is searchable —
    // but saying only "indexed" would let the pages behind a scanned cover go missing
    // with nothing to notice.
    // Held back from SEARCH, not from the document — reported so it is never silent.
    setSuppressedNotes(results
      .filter(r => (r.suppressed_numeric_runs ?? 0) > 0)
      .map(r => `${r.filename}: ${r.suppressed_numeric_runs} line`
              + `${r.suppressed_numeric_runs !== 1 ? "s" : ""} of unlabelled figures`));

    const partial = results.filter(
      r => (r.pages_needing_ocr?.length ?? 0) + (r.pages_failed?.length ?? 0) > 0);
    setPartialNotes(partial.map(r => {
      const list = (p: number[]) => p.slice(0, 8).join(", ") + (p.length > 8 ? "…" : "");
      const scanned = r.pages_needing_ocr ?? [];
      const broken = r.pages_failed ?? [];
      // The two causes are named separately: OCR fixes one and nothing fixes the
      // other, so merging them would send a person to buy OCR they do not need.
      const why = [
        scanned.length ? `page${scanned.length !== 1 ? "s" : ""} ${list(scanned)} `
                       + `${scanned.length !== 1 ? "are" : "is"} scanned (no text layer)` : "",
        broken.length ? `page${broken.length !== 1 ? "s" : ""} ${list(broken)} could not be read` : "",
      ].filter(Boolean).join("; ");
      return `${r.filename}: read ${r.pages_read} of ${r.page_count} pages — ${why}.`;
    }));
    if (errors.length > 0) setUploadError(errors.join("\n"));
    setPending(prev => prev.filter(p => !results.some(r => r.filename === p.file.name)));
    setUploading(false);
    getKnowledgeStatus().then(setStatus).catch(() => {});
  }, [settings]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    convertFiles(e.dataTransfer.files);
  }, [convertFiles]);

  const onDragOver = (e: React.DragEvent) => { e.preventDefault(); setDragging(true); };
  const onDragLeave = () => setDragging(false);

  /** Open a stored document. The original is shown when it was retained and the browser
   *  can render it; otherwise the Markdown, which is what the platform reads regardless. */
  const openDocument = useCallback(async (doc: DocumentEntry) => {
    const suffix = `.${doc.filename.split(".").pop()?.toLowerCase() ?? ""}`;
    const canRenderOriginal = !!doc.has_original && BROWSER_RENDERABLE.has(suffix);
    setOpenDoc(doc);
    setOpenTab(canRenderOriginal ? "original" : "markdown");
    setOpenMarkdown(null);
    setOpenError(null);
    setConvertFormats([]);
    getDocumentConvertFormats(doc.doc_id).then(setConvertFormats).catch(() => {});
    try {
      setOpenMarkdown(await getDocumentMarkdown(doc.doc_id));
    } catch (e) {
      setOpenError(e instanceof Error ? e.message : "Could not read the document");
    }
  }, []);

  const handleDelete = async (docId: string) => {
    setDeletingId(docId);
    try {
      await deleteDocument(docId);
      setDocs(prev => prev.filter(d => d.doc_id !== docId));
      setOpenDoc(prev => (prev?.doc_id === docId ? null : prev));
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
          Upload a document in almost any format — it is converted to Markdown, kept as
          you uploaded it, and made available as context to the Agent, the conversation
          and anywhere else on the platform.
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
              accept={accept}
              multiple
              className="hidden"
              onChange={e => convertFiles(e.target.files)}
            />
            {uploading || converting ? (
              <div className="space-y-2">
                <div className="h-5 w-5 rounded-[var(--r-pill)] border-2 border-violet-500 border-t-transparent animate-spin mx-auto" />
                <p className="aug-fs-ui text-zinc-400">
                  {converting ? "Reading…" : "Indexing…"}
                </p>
              </div>
            ) : (
              <div className="space-y-1">
                <p className="aug-fs-h2">📄</p>
                <p className="aug-fs-ui text-zinc-300 font-medium">
                  {dragging ? "Drop to upload" : "Drop files here or click to browse"}
                </p>
                <p className="aug-fs-xs text-zinc-500">
                  {formats?.converter === false
                    ? "Markdown · Plain text — install the document converter for Word, PDF, slides and sheets"
                    : "PDF · Word · Slides · Sheets · OpenDocument · RTF · EPUB · CSV · Markdown"}
                </p>
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
              <p className="aug-fs-xs text-zinc-600 mt-2 mb-2">
                Off by default: a policy that cites a source loses the citation.
              </p>
              <label className="flex items-center gap-2 aug-fs-xs text-zinc-400">
                <input
                  type="checkbox"
                  checked={settings.suppress_numeric_runs ?? true}
                  onChange={e => setSettings(prev => ({ ...prev, suppress_numeric_runs: e.target.checked }))}
                />
                Keep unlabelled runs of figures out of search
              </label>
              <p className="aug-fs-xs text-zinc-600 mt-2">
                On by default, and it does not change the document — a chart&rsquo;s labels
                are graphics, so its values arrive as a headless row where every figure is
                right and none is attached to what it measures. They stay in the file and
                in every download; only search skips them.
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
                accept={accept}
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

      {/* Connected sources — the other way content reaches this same corpus. */}
      <KnowledgeSourcesSection />

      {/* ── Waiting for a decision ────────────────────────────────────────────
          Converted and shown, indexed nowhere. This is the moment the person can see
          what the platform will actually read — a scanned deck missing eight pages, a
          table that survived, a wall of figures — and say no before it costs anything
          or starts answering questions. */}
      {pending.map(({ file, result }) => (
        <div key={file.name}
             className="rounded-md border border-violet-500/40 bg-violet-500/5">
          <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-2.5">
            <FileTypeChip filename={file.name} />
            <div className="min-w-0 flex-1">
              <p className="aug-fs-sm font-medium text-zinc-200 truncate">{file.name}</p>
              <p className="aug-fs-xs text-zinc-500">
                {formatCount(result.characters)} characters ·{" "}
                {formatCount(result.would_index_chunks)} chunk
                {result.would_index_chunks !== 1 ? "s" : ""} to index
                {result.page_count > 0 && ` · ${result.pages_read} of ${result.page_count} pages read`}
              </p>
            </div>
            <button
              type="button"
              onClick={() => discardPending(file.name)}
              className="shrink-0 aug-fs-xs text-zinc-500 hover:text-zinc-200 border border-zinc-700 rounded px-2 py-1"
            >
              Discard
            </button>
            <button
              type="button"
              disabled={uploading}
              onClick={() => handleFiles(fileListOf(file))}
              className="shrink-0 aug-fs-xs px-2.5 py-1 rounded border border-violet-500/50 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25 disabled:opacity-50"
            >
              {uploading ? "Adding…" : "Add to knowledge"}
            </button>
          </div>

          {/* Losses named BEFORE the decision, not after. Approving something whose
              gaps were only disclosed afterwards is not approval. */}
          {(result.pages_needing_ocr.length > 0 || result.pages_failed.length > 0) && (
            <p className="aug-fs-xs text-amber-300 px-4 pt-2.5">
              {result.pages_needing_ocr.length > 0 && (
                <>Page{result.pages_needing_ocr.length !== 1 ? "s" : ""}{" "}
                {result.pages_needing_ocr.slice(0, 8).join(", ")}
                {result.pages_needing_ocr.length > 8 ? "…" : ""}{" "}
                {result.pages_needing_ocr.length !== 1 ? "are" : "is"} scanned — no text layer. </>
              )}
              {result.pages_failed.length > 0 && (
                <>Page{result.pages_failed.length !== 1 ? "s" : ""}{" "}
                {result.pages_failed.join(", ")} could not be read.</>
              )}
            </p>
          )}
          {result.suppressed_numeric_runs > 0 && (
            <p className="aug-fs-xs text-zinc-500 px-4 pt-1.5">
              {result.suppressed_numeric_runs} line
              {result.suppressed_numeric_runs !== 1 ? "s" : ""} of unlabelled figures will
              be kept out of search. They stay in the document and in every download.
            </p>
          )}

          <div className="p-4">
            <p className="aug-fs-xs text-zinc-500 mb-2">
              This is exactly what will be indexed and what every agent, canvas and
              prompt will see.
            </p>
            <pre className="aug-fs-xs text-zinc-300 font-mono whitespace-pre-wrap max-h-[24rem] overflow-auto rounded border border-zinc-800 bg-zinc-950/60 p-3">
              {result.markdown}
            </pre>
          </div>
        </div>
      ))}

      {/* Indexed less than the document holds, said out loud. Neutral rather than
          amber: nothing is wrong and nothing is lost — the figures are still in the
          file and in every download, they are simply not offered as search results. */}
      {suppressedNotes.length > 0 && (
        <div className="rounded-md border border-zinc-700 bg-zinc-900/40 p-3 space-y-1">
          <p className="aug-fs-sm text-zinc-300">Kept out of search</p>
          {suppressedNotes.map(note => (
            <p key={note} className="aug-fs-xs text-zinc-400">{note}</p>
          ))}
          <p className="aug-fs-xs text-zinc-500">
            Chart labels extract as figures attached to nothing, so an answer drawn from
            them can be confidently wrong. They remain in the document and in every
            download. Turn this off in chunk settings to index them.
          </p>
        </div>
      )}

      {/* Imported, but not all of it. Amber rather than red: the document IS indexed
          and searchable, and the person's next move is OCR or a different export —
          not a retry of the same upload. */}
      {partialNotes.length > 0 && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 space-y-1">
          <p className="aug-fs-sm text-amber-300">Imported with pages missing</p>
          {partialNotes.map(note => (
            <p key={note} className="aug-fs-xs text-zinc-400">{note}</p>
          ))}
          <p className="aug-fs-xs text-zinc-500">
            The rest of the document is indexed and searchable. Scanned pages need OCR,
            which is off by default because it sends the file to a third party.
          </p>
        </div>
      )}

      {/* Error */}
      {uploadError && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 aug-fs-xs text-red-400 whitespace-pre-wrap font-mono">
          {uploadError}
        </div>
      )}

      {/* ── Document list ──────────────────────────────────────────────────────
          Split, because these are not the same kind of thing. Compiled schema
          documentation shares the collection with uploads (right for retrieval — an
          agent asking about a table wants the schema doc) and shared this list too,
          which was wrong: on a live install 15 of 16 rows were `doctree::`, so one real
          file read as sixteen documents nobody uploaded and nobody can act on. */}
      {uploaded.length > 0 && (
        <div className="space-y-2">
          <p className="aug-fs-xs text-zinc-500 uppercase tracking-widest font-mono">
            {uploaded.length} document{uploaded.length !== 1 ? "s" : ""} indexed
          </p>
          <div className="space-y-2">
            {uploaded.map(doc => (
              <div
                key={doc.doc_id}
                className={`rounded-md border bg-zinc-800/50 px-4 py-3 flex items-center gap-3 ${
                  openDoc?.doc_id === doc.doc_id ? "border-violet-500/60" : "border-zinc-700"
                }`}
              >
                <FileTypeChip filename={doc.filename} />
                <div className="flex-1 min-w-0">
                  <p className="aug-fs-sm font-medium text-zinc-200 truncate">{doc.title}</p>
                  <p className="aug-fs-xs text-zinc-500 font-mono mt-0.5">
                    {doc.filename} · {chunkLabel(doc, status)} · {timeAgo(doc.uploaded_at)}
                    {doc.has_original === false && " · original not kept"}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => openDocument(doc)}
                  className="shrink-0 aug-fs-xs text-zinc-400 hover:text-zinc-100 border border-zinc-700 hover:border-zinc-500 rounded px-2 py-1 transition"
                >
                  {openDoc?.doc_id === doc.doc_id ? "Viewing" : "View"}
                </button>
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

      {/* ── A stored document, as itself and as the platform reads it ────────────
          Two tabs because they answer different questions. "Original" is the file the
          person uploaded — the one they recognise. "Markdown" is what actually reaches
          an agent, a canvas or a prompt, and seeing it is the only way to know whether
          a table survived the conversion. Neither substitutes for the other. */}
      {openDoc && (
        <div className="rounded-md border border-zinc-700 bg-zinc-900/40">
          <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-2.5">
            <FileTypeChip filename={openDoc.filename} />
            <div className="min-w-0 flex-1">
              <p className="aug-fs-sm font-medium text-zinc-200 truncate">{openDoc.title}</p>
              <p className="aug-fs-xs text-zinc-500 font-mono truncate">{openDoc.filename}</p>
            </div>
            <div className="flex shrink-0 rounded border border-zinc-700 overflow-hidden">
              {(["original", "markdown"] as const).map(tab => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setOpenTab(tab)}
                  disabled={tab === "original" && !openDoc.has_original}
                  className={`aug-fs-xs px-2.5 py-1 transition disabled:opacity-40 ${
                    openTab === tab ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:bg-zinc-800"
                  }`}
                >
                  {tab === "original" ? "Original" : "Markdown"}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setOpenDoc(null)}
              className="shrink-0 aug-fs-xs text-zinc-500 hover:text-zinc-200 border border-zinc-700 rounded px-2 py-1"
            >
              Close
            </button>
          </div>

          {/* Convert — the outbound half of the pivot. Anything readable became
              Markdown coming in, so it can leave as anything this deployment renders.
              Formats the install cannot write are shown disabled with the reason
              rather than hidden, so an operator can see what installing an extra
              would add. */}
          {convertFormats.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 border-b border-zinc-800 px-4 py-2">
              <span className="aug-fs-xs text-zinc-500 mr-1">Download as</span>
              {convertFormats.map(f => (
                f.available ? (
                  <a
                    key={f.format}
                    href={documentConvertUrl(openDoc.doc_id, f.format)}
                    className="aug-fs-xs px-2 py-1 rounded border border-zinc-700 text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100 transition"
                  >
                    {f.label}
                  </a>
                ) : (
                  <span
                    key={f.format}
                    title="This deployment cannot render that format — the export extra is not installed."
                    className="aug-fs-xs px-2 py-1 rounded border border-zinc-800 text-zinc-600 cursor-not-allowed"
                  >
                    {f.label}
                  </span>
                )
              ))}
            </div>
          )}

          <div className="p-4">
            {openError && (
              <p className="aug-fs-xs text-amber-400">{openError}</p>
            )}

            {openTab === "original" && !openError && (
              openDoc.has_original ? (
                BROWSER_RENDERABLE.has(`.${openDoc.filename.split(".").pop()?.toLowerCase() ?? ""}`) ? (
                  <>
                    <iframe
                      src={documentOriginalUrl(openDoc.doc_id)}
                      title={openDoc.title}
                      className="w-full h-[28rem] rounded border border-zinc-800 bg-zinc-950"
                    />
                    {/* An embedded PDF renders only where the viewer's browser has a PDF
                        plugin — headless builds, some embedded webviews and some locked-down
                        corporate profiles have none, and there the frame above is simply
                        BLANK with nothing to explain it. Observed while capturing this very
                        panel. A frame that can fail silently needs a way out beside it. */}
                    <p className="aug-fs-xs text-zinc-600 mt-1.5">
                      Nothing shown above?{" "}
                      <a
                        href={documentOriginalUrl(openDoc.doc_id)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-zinc-400 hover:text-zinc-200 underline"
                      >
                        Open the original file
                      </a>{" "}
                      — some browsers cannot display it inline. The Markdown tab always works.
                    </p>
                  </>
                ) : (
                  /* A browser cannot render a .docx or .pptx. Saying so and offering the
                     file beats an empty frame that looks like a failure. */
                  <div className="rounded border border-zinc-800 bg-zinc-950/60 p-6 text-center">
                    <p className="aug-fs-sm text-zinc-300">
                      A browser cannot display this format directly.
                    </p>
                    <p className="aug-fs-xs text-zinc-500 mt-1">
                      The Markdown tab shows what the platform reads from it.
                    </p>
                    <a
                      href={documentOriginalUrl(openDoc.doc_id)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-block mt-3 aug-fs-xs px-2.5 py-1.5 rounded border border-zinc-600 text-zinc-200 hover:bg-zinc-800"
                    >
                      Open the original file
                    </a>
                  </div>
                )
              ) : (
                <p className="aug-fs-xs text-zinc-500">
                  This document was uploaded before originals were kept, so only its text
                  remains. Re-upload it to enable preview.
                </p>
              )
            )}

            {openTab === "markdown" && !openError && (
              openMarkdown === null ? (
                <p className="aug-fs-xs text-zinc-500">Reading…</p>
              ) : (
                <>
                  <p className="aug-fs-xs text-zinc-500 mb-2">
                    {formatCount(openMarkdown.length)} characters · this is the text every
                    agent, canvas and prompt sees
                  </p>
                  <pre className="aug-fs-xs text-zinc-300 font-mono whitespace-pre-wrap max-h-[28rem] overflow-auto rounded border border-zinc-800 bg-zinc-950/60 p-3">
                    {openMarkdown}
                  </pre>
                </>
              )
            )}
          </div>
        </div>
      )}

      {/* Generated schema docs, behind a disclosure. Present because they ARE part of
          what search will return — hiding them entirely would misrepresent the corpus —
          but folded away because they are not the person's material. */}
      {generated.length > 0 && (
        <details className="rounded-md border border-zinc-800 bg-zinc-900/30">
          <summary className="aug-fs-xs text-zinc-500 px-4 py-2.5 cursor-pointer select-none">
            {generated.length} schema document{generated.length !== 1 ? "s" : ""} compiled
            by the platform — {formatCount(generatedChunks)} chunk
            {generatedChunks !== 1 ? "s" : ""}, searchable, not uploaded by you
          </summary>
          <div className="px-4 pb-3 space-y-1">
            <p className="aug-fs-xs text-zinc-600 mb-2">
              Built from each connection&rsquo;s schema so agents can answer questions about
              your tables. They rebuild themselves; removing one here is temporary.
            </p>
            {generated.map(doc => (
              <div key={doc.doc_id} className="flex items-center gap-2">
                <span className="aug-fs-xs text-zinc-400 font-mono truncate flex-1">
                  {doc.filename || doc.doc_id}
                </span>
                <span className="aug-fs-xs text-zinc-600 shrink-0">
                  {chunkLabel(doc, status)}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}

      {docs.length === 0 && !uploading && (
        <p className="aug-fs-xs text-zinc-500 text-center py-4">
          No documents yet. Upload one above to give the Agent external context.
        </p>
      )}
    </div>
  );
}
