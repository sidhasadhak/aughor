"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { countNoun, formatCount } from "@/lib/format";
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

/** Bytes, for a file that has not been read yet. Everything else on this panel counts
 *  characters or chunks, but neither exists until ③ converts. */
function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** The numeral for one step.
 *
 *  `now` is where the person is, `done` is behind them, `todo` is not yet reachable —
 *  a disabled-looking button with no explanation is the failure this replaces. */
function StepDot({ n, state }: { n: number; state: "todo" | "now" | "done" }) {
  return (
    <span
      className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-[var(--r-pill)] aug-fs-xs font-mono ${
        state === "done"
          ? "border border-violet-500/40 bg-violet-500/15 text-violet-300"
          : state === "now"
            ? "bg-violet-500 text-white"
            : "border border-zinc-700 text-zinc-600"
      }`}
    >
      {n}
    </span>
  );
}

/** A numbered step heading.
 *
 *  The order was always there and was never shown, so the panel read as five things a
 *  person could do rather than five things they do in sequence — which is why the
 *  common path was to drop a file, not realise it had already been converted under the
 *  defaults, and go looking for the settings afterwards. */
function StepHeading({ n, state, title, hint }: {
  n: number; state: "todo" | "now" | "done"; title: string; hint?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <StepDot n={n} state={state} />
      <span className={`aug-fs-ui font-semibold ${state === "todo" ? "text-zinc-500" : "text-zinc-200"}`}>
        {title}
      </span>
      {hint && <span className="aug-fs-xs text-zinc-500 truncate">{hint}</span>}
    </div>
  );
}


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

  // ① CHOSEN, and nothing more. No request has been made for these — they are File
  // objects sitting in the browser. Dropping a file used to convert it on the spot
  // under whatever settings happened to be in the fields, which put ② after ③ for
  // anyone who had not already scrolled down and set them.
  const [staged, setStaged] = useState<File[]>([]);
  // ③ produced these, keyed by filename. Still indexed nowhere: the File objects are
  // posted again on approval, so there is no staging area on the server to expire,
  // sweep or leak, and conversion is deterministic so what is approved is what lands.
  const [reviews, setReviews] = useState<Record<string, DocumentConversion>>({});
  const [cuts, setCuts] = useState<Record<string, ChunkPreview>>({});
  // The settings ③ ran under, serialised. A review describes a document AS CUT BY
  // settings; move them afterwards and it is describing something that would no
  // longer be indexed, so the panel says so instead of letting it stand.
  const [reviewedUnder, setReviewedUnder] = useState<string | null>(null);
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

  // ④ which staged file is being read, and as what. The chunk preview had its own
  // file picker beside the settings, so a person chose the same document twice — once
  // to see how it would be cut and once to actually ingest it — and the two answers
  // were about different uploads. One file, three views of it.
  const [shown, setShown] = useState(0);
  const [reviewTab, setReviewTab] = useState<"original" | "markdown" | "chunks">("original");
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);

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

  // What ④ is currently showing, and whether ⑤ may fire at all.
  const file = staged[shown];
  const review = file ? reviews[file.name] : undefined;
  const cut = file ? cuts[file.name] : undefined;
  const settingsKey = JSON.stringify(settings);
  const stale = reviewedUnder !== null && reviewedUnder !== settingsKey;
  const reviewed = staged.length > 0 && staged.every(f => reviews[f.name]) && !stale;

  /** The staged file as itself, for ④.
   *
   *  A blob URL, because the file has not been uploaded and must not be: the whole
   *  point of this step is to look before anything leaves the browser. Guarded because
   *  `createObjectURL` is absent in jsdom and in some locked-down webviews, and the
   *  panel has to render without it rather than throw on mount. */
  useEffect(() => {
    if (!file || typeof URL.createObjectURL !== "function") { setOriginalUrl(null); return; }
    const url = URL.createObjectURL(file);
    setOriginalUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const refresh = useCallback(() => {
    listDocuments().then(setDocs).catch(() => {});
    // The plane's own account of itself. Without it this panel shows a list of documents
    // and no hint that nothing can be searched — an unreachable embedder looks exactly
    // like a healthy corpus from here.
    getKnowledgeStatus().then(setStatus).catch(() => setStatus(null));
    getDocumentFormats().then(setFormats).catch(() => setFormats(null));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  /** ① Hold what was chosen. Deliberately makes no request at all. */
  const stageFiles = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadError(null);
    setPartialNotes([]);
    setSuppressedNotes([]);
    setStaged(Array.from(files));
    setReviews({});
    setCuts({});
    setReviewedUnder(null);
    setShown(0);
    setReviewTab("original");
  }, []);

  const unstage = (name: string) => {
    setStaged(prev => prev.filter(f => f.name !== name));
    setShown(0);
  };

  const resetStaged = useCallback(() => {
    setStaged([]);
    setReviews({});
    setCuts({});
    setReviewedUnder(null);
    setShown(0);
    setUploadError(null);
  }, []);

  /** ③ Convert and cut the staged files, indexing nothing.
   *
   *  Two calls per file and neither writes: the Markdown is the decision — it is
   *  literally what every agent will read — and the chunk cut is what ②'s numbers do
   *  to it. Asking for both here is what lets ② be a set of fields with a visible
   *  effect instead of three numbers you have to imagine. */
  const convertStaged = useCallback(async () => {
    if (staged.length === 0) return;
    setUploadError(null);
    setConverting(true);
    const converted: Record<string, DocumentConversion> = {};
    const cutBy: Record<string, ChunkPreview> = {};
    const errors: string[] = [];
    for (const f of staged) {
      try {
        converted[f.name] = await convertDocument(f, settings);
      } catch (e) {
        errors.push(`${f.name}: ${e instanceof Error ? e.message : "failed"}`);
        continue;
      }
      // The cut is detail; the Markdown is the decision. A preview that fails must not
      // cost the review that succeeded.
      try {
        cutBy[f.name] = await previewDocumentChunks(f, settings);
      } catch { /* the Chunks tab says so */ }
    }
    setReviews(converted);
    setCuts(cutBy);
    setReviewedUnder(JSON.stringify(settings));
    setReviewTab(Object.keys(converted).length > 0 ? "markdown" : "original");
    if (errors.length > 0) setUploadError(errors.join("\n"));
    setConverting(false);
  }, [staged, settings]);

  /** ⑤ The only call on this panel that writes anything. */
  const commitStaged = useCallback(async (files: File[]) => {
    if (files.length === 0) return;
    setUploadError(null);
    setPartialNotes([]);
    setSuppressedNotes([]);
    setUploading(true);
    const results: DocumentEntry[] = [];
    const errors: string[] = [];
    for (const file of files) {
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
    // Only what actually landed leaves the tray. A file that failed stays staged with
    // its review intact, so the retry does not start again at ①.
    const landed = new Set(results.map(r => r.filename));
    setStaged(prev => prev.filter(f => !landed.has(f.name)));
    setReviews(prev => Object.fromEntries(
      Object.entries(prev).filter(([name]) => !landed.has(name))));
    setCuts(prev => Object.fromEntries(
      Object.entries(prev).filter(([name]) => !landed.has(name))));
    setShown(0);
    setUploading(false);
    getKnowledgeStatus().then(setStatus).catch(() => {});
  }, [settings]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    stageFiles(e.dataTransfer.files);
  }, [stageFiles]);

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
        /* PX-1 — the alarm must state ITS OWN cause. This banner once fired on a
           per-document count mismatch while its only sentence narrated a different
           metric that happened to read "121 of 121" — an alarm whose visible numbers
           said everything was fine. One sentence per actual cause, nothing else. */
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
          <p className="aug-fs-sm text-amber-300">The index and this list disagree.</p>
          {status.consistency.orphan_chunks > 0 && (
            <p className="aug-fs-xs text-zinc-400 mt-1">
              {countNoun(status.consistency.orphan_chunks, "chunk")} across{" "}
              {countNoun(status.consistency.orphan_documents, "document")} are in the
              index but not listed — they can be found by search and cannot be removed
              from here.
            </p>
          )}
          {Object.keys(status.consistency.mismatched_documents ?? {}).length > 0 && (
            <p className="aug-fs-xs text-zinc-400 mt-1">
              {countNoun(Object.keys(status.consistency.mismatched_documents).length, "document")}{" "}
              hold{Object.keys(status.consistency.mismatched_documents).length === 1 ? "s" : ""} a
              different number of chunks in the index than this list claims — the listed
              count is a claim from upload time, and search sees the index.
            </p>
          )}
        </div>
      )}

      {/* ── Add a document: one file, one set of settings, one decision ────────
          This was three unrelated motions sharing a screen. Dropping a file converted
          it on the spot under whatever happened to be in the settings fields — so the
          settings came AFTER the conversion they were supposed to govern. The chunk
          preview had its own separate file picker, so the same document was chosen
          twice to answer two different questions. And the thing actually being decided
          — the Markdown — appeared far below, past the sources list, in a card most
          people never scrolled to.

          Numbered, because the sequence is the whole point: nothing is converted until
          ③, nothing is indexed until ⑤, and moving ② after ③ marks the review stale
          rather than leaving it to describe a cut that is no longer in force. */}
      <div className="rounded-md border border-zinc-700 bg-zinc-900/40">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-zinc-800 px-4 py-2.5">
          <h3 className="aug-fs-ui font-semibold text-zinc-200">Add a document</h3>
          <p className="aug-fs-xs text-zinc-500">
            Choose it, say how it should be cut, then read what the platform will
            actually see. Nothing is converted until ③ and nothing is stored until ⑤.
          </p>
        </div>

        <div className="grid gap-4 lg:grid-cols-2 items-start p-4">

          {/* ── left: what to ingest, and how ─────────────────────────────────── */}
          <div className="space-y-4">

            <div className="space-y-2">
              <StepHeading
                n={1}
                state={staged.length > 0 ? "done" : "now"}
                title="Choose a file"
                hint={staged.length > 0 ? `${staged.length} staged · nothing sent yet` : undefined}
              />
              {staged.length === 0 ? (
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
                  <div className="space-y-1">
                    <p className="aug-fs-h2">📄</p>
                    <p className="aug-fs-ui text-zinc-300 font-medium">
                      {dragging ? "Drop to choose" : "Drop files here or click to browse"}
                    </p>
                    <p className="aug-fs-xs text-zinc-500">
                      {formats?.converter === false
                        ? "Markdown · Plain text — install the document converter for Word, PDF, slides and sheets"
                        : "PDF · Word · Slides · Sheets · OpenDocument · RTF · EPUB · CSV · Markdown"}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="rounded-md border border-zinc-700 bg-zinc-950/30 divide-y divide-zinc-800">
                  {staged.map((f, i) => (
                    <div
                      key={f.name}
                      onClick={() => { setShown(i); }}
                      className={`flex items-center gap-2 px-3 py-2 cursor-pointer ${
                        i === shown ? "bg-zinc-800/60" : "hover:bg-zinc-800/30"
                      }`}
                    >
                      <FileTypeChip filename={f.name} />
                      <div className="min-w-0 flex-1">
                        <p className="aug-fs-sm text-zinc-200 truncate">{f.name}</p>
                        <p className="aug-fs-xs text-zinc-500 font-mono">
                          {sizeLabel(f.size)}
                          {reviews[f.name]
                            ? ` · ${formatCount(reviews[f.name].would_index_chunks)} chunk${
                                reviews[f.name].would_index_chunks !== 1 ? "s" : ""} to index`
                            : " · not read yet"}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={e => { e.stopPropagation(); unstage(f.name); }}
                        className="shrink-0 aug-fs-xs text-zinc-500 hover:text-zinc-200 border border-zinc-700 rounded px-2 py-1"
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={() => inputRef.current?.click()}
                    className="w-full aug-fs-xs text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/40 px-3 py-2 text-left"
                  >
                    Choose different files…
                  </button>
                </div>
              )}
              <input
                ref={inputRef}
                type="file"
                accept={accept}
                multiple
                className="hidden"
                onChange={e => stageFiles(e.target.files)}
              />
            </div>

            <div className="space-y-2">
              <StepHeading
                n={2}
                state={staged.length === 0 ? "todo" : reviewed ? "done" : "now"}
                title="Set how it is cut"
                hint={Object.keys(settings).length === 0
                  ? "defaults"
                  : `${Object.keys(settings).length} changed`}
              />
              <div className="rounded-md border border-zinc-700 bg-zinc-950/30 p-4 space-y-4">
                <p className="aug-fs-xs text-zinc-500">
                  One chunk per delimiter block. The same chunk is retrieved and given as
                  context.
                </p>

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
                      placeholder={String(cut?.settings?.[key] ?? "default")}
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
              </div>
            </div>

            {/* ③ and ⑤ — the two moments that do something, on one line, in order.
                ⑤ cannot fire until ③ has produced a review of the settings now in
                force, which is what makes "confirm" mean something. */}
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={convertStaged}
                  disabled={staged.length === 0 || converting}
                  className="inline-flex items-center gap-1.5 aug-fs-xs px-2.5 py-1.5 rounded border border-zinc-600 text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
                >
                  <StepDot n={3} state={staged.length > 0 && !reviewed ? "now" : reviewed ? "done" : "todo"} />
                  {converting ? "Reading…" : reviewed ? "Convert again" : "Convert & review"}
                </button>
                <button
                  type="button"
                  onClick={() => { setSettings({}); resetStaged(); }}
                  className="aug-fs-xs px-2.5 py-1.5 rounded border border-zinc-700 text-zinc-400 hover:bg-zinc-800"
                >
                  Reset
                </button>
                <button
                  type="button"
                  onClick={() => commitStaged(staged)}
                  disabled={!reviewed || uploading}
                  className="ml-auto inline-flex items-center gap-1.5 aug-fs-xs px-2.5 py-1.5 rounded border border-violet-500/50 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25 disabled:opacity-40 disabled:hover:bg-violet-500/15"
                >
                  <StepDot n={5} state={reviewed ? "now" : "todo"} />
                  {uploading
                    ? "Adding…"
                    : `Add ${staged.length > 1 ? `${staged.length} documents` : "to knowledge"}`}
                </button>
              </div>
              <p className="aug-fs-xs text-zinc-600">
                {staged.length === 0
                  ? "Choose a file to begin. Converting reads it and indexes nothing."
                  : stale
                    ? "Settings changed since the last read — convert again to see what they do now."
                    : reviewed
                      ? "Read it on the right. Adding embeds it and makes it searchable."
                      : "Converting reads the file and indexes nothing. It works while search is down."}
              </p>
            </div>

            {/* The model in force. A corpus is only comparable with itself under ONE model,
                so this is part of reading the list — not an error state. It is chosen by
                configuration, and saying so beats a picker that could not take effect. */}
            <div className="rounded-md border border-zinc-700 bg-zinc-950/30 p-4">
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

          {/* ── right: ④ the file as itself, and as the platform will read it ──── */}
          <div className="space-y-2 lg:sticky lg:top-2">
            <StepHeading
              n={4}
              state={reviewed ? "done" : staged.length > 0 ? "now" : "todo"}
              title="Read it before you commit"
              hint={file?.name}
            />
            <div className="rounded-md border border-zinc-700 bg-zinc-950/30">
              <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800 px-3 py-2">
                <div className="flex shrink-0 rounded border border-zinc-700 overflow-hidden">
                  {([
                    ["original", "Original"],
                    ["markdown", "Markdown"],
                    ["chunks", "Chunks"],
                  ] as const).map(([tab, label]) => (
                    <button
                      key={tab}
                      type="button"
                      onClick={() => setReviewTab(tab)}
                      disabled={!file || (tab !== "original" && !review)}
                      className={`aug-fs-xs px-2.5 py-1 transition disabled:opacity-40 ${
                        reviewTab === tab ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:bg-zinc-800"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <p className="aug-fs-xs text-zinc-500 ml-auto truncate">
                  {review
                    ? `${formatCount(review.characters)} characters · ${
                        formatCount(review.would_index_chunks)} chunk${
                        review.would_index_chunks !== 1 ? "s" : ""} to index${
                        review.page_count > 0
                          ? ` · ${review.pages_read} of ${review.page_count} pages read`
                          : ""}`
                    : file
                      ? `${sizeLabel(file.size)} · not read yet`
                      : "nothing chosen"}
                </p>
              </div>

              {/* Losses named BEFORE the decision, not after. Approving something whose
                  gaps were only disclosed afterwards is not approval. */}
              {review && (review.pages_needing_ocr.length > 0 || review.pages_failed.length > 0) && (
                <p className="aug-fs-xs text-amber-300 px-3 pt-2">
                  {review.pages_needing_ocr.length > 0 && (
                    <>Page{review.pages_needing_ocr.length !== 1 ? "s" : ""}{" "}
                    {review.pages_needing_ocr.slice(0, 8).join(", ")}
                    {review.pages_needing_ocr.length > 8 ? "…" : ""}{" "}
                    {review.pages_needing_ocr.length !== 1 ? "are" : "is"} scanned — no text layer. </>
                  )}
                  {review.pages_failed.length > 0 && (
                    <>Page{review.pages_failed.length !== 1 ? "s" : ""}{" "}
                    {review.pages_failed.join(", ")} could not be read.</>
                  )}
                </p>
              )}
              {review && (review.charts_recovered ?? 0) > 0 && (
                <p className="aug-fs-xs text-emerald-300/90 px-3 pt-2">
                  {review.charts_recovered} chart
                  {review.charts_recovered !== 1 ? "s" : ""} read back from page
                  {(review.chart_pages?.length ?? 0) !== 1 ? "s" : ""}{" "}
                  {review.chart_pages?.slice(0, 8).join(", ")}
                  {(review.chart_pages?.length ?? 0) > 8 ? "…" : ""} and appended as
                  tables. A chart&rsquo;s values are exact text the Markdown could not
                  carry; only their positions said what they measured.
                </p>
              )}
              {review && review.suppressed_numeric_runs > 0 && (
                <p className="aug-fs-xs text-zinc-500 px-3 pt-2">
                  {review.suppressed_numeric_runs} line
                  {review.suppressed_numeric_runs !== 1 ? "s" : ""} of unlabelled figures will
                  be kept out of search. They stay in the document and in every download.
                </p>
              )}
              {stale && (
                <p className="aug-fs-xs text-amber-300 px-3 pt-2">
                  This was read under the previous settings.
                </p>
              )}

              <div className="p-3">
                {!file ? (
                  <p className="aug-fs-xs text-zinc-600">
                    Choose a file at ① to see it here — the file itself, the Markdown the
                    platform reads from it, and the chunks ② would cut it into.
                  </p>
                ) : reviewTab === "original" ? (
                  BROWSER_RENDERABLE.has(`.${file.name.split(".").pop()?.toLowerCase() ?? ""}`)
                    && originalUrl ? (
                    <>
                      <iframe
                        src={originalUrl}
                        title={file.name}
                        className="w-full h-[26rem] rounded border border-zinc-800 bg-zinc-950"
                      />
                      {/* An embedded PDF renders only where the viewer's browser has a PDF
                          plugin — headless builds, some embedded webviews and some
                          locked-down corporate profiles have none, and there the frame
                          above is simply BLANK with nothing to explain it. */}
                      <p className="aug-fs-xs text-zinc-600 mt-1.5">
                        Nothing shown above? Some browsers cannot display a file inline. The
                        Markdown tab always works, and it is what actually gets indexed.
                      </p>
                    </>
                  ) : (
                    <div className="rounded border border-zinc-800 bg-zinc-950/60 p-6 text-center">
                      <p className="aug-fs-sm text-zinc-300">
                        A browser cannot display this format directly.
                      </p>
                      <p className="aug-fs-xs text-zinc-500 mt-1">
                        The Markdown tab shows what the platform reads from it — which is the
                        half that matters for search.
                      </p>
                    </div>
                  )
                ) : reviewTab === "markdown" ? (
                  review ? (
                    <>
                      <p className="aug-fs-xs text-zinc-500 mb-2">
                        This is exactly what will be indexed and what every agent, canvas and
                        prompt will see.
                      </p>
                      <pre className="aug-fs-xs text-zinc-300 font-mono whitespace-pre-wrap max-h-[26rem] overflow-auto rounded border border-zinc-800 bg-zinc-950/60 p-3">
                        {review.markdown}
                      </pre>
                    </>
                  ) : (
                    <p className="aug-fs-xs text-zinc-600">Convert at ③ to read this.</p>
                  )
                ) : cut ? (
                  <div className="space-y-2">
                    <p className="aug-fs-xs text-zinc-500">
                      Showing {cut.shown} of {formatCount(cut.total_chunks)} chunks ·{" "}
                      {formatCount(cut.characters)} characters
                    </p>
                    {cut.chunks.map(c => (
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
                ) : (
                  <p className="aug-fs-xs text-zinc-600">
                    {review
                      ? "The cut could not be previewed for this file. The Markdown tab is the decision."
                      : "Convert at ③ to see the cut."}
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Connected sources — the other way content reaches this same corpus. */}
      <KnowledgeSourcesSection />

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
