"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  listDocuments,
  uploadDocument,
  deleteDocument,
  type DocumentEntry,
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

export function DocumentUploader() {
  const [docs, setDocs] = useState<DocumentEntry[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listDocuments().then(setDocs).catch(() => {});
  }, []);

  const handleFiles = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadError(null);
    setUploading(true);
    const results: DocumentEntry[] = [];
    const errors: string[] = [];
    for (const file of Array.from(files)) {
      try {
        const entry = await uploadDocument(file);
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
  }, []);

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
        <h2 className="text-sm font-semibold text-zinc-200">Documents</h2>
        <p className="text-xs text-zinc-500 mt-0.5">
          Upload PDFs, Word docs, or Markdown files. ADA retrieves relevant snippets during investigations.
        </p>
      </div>

      {/* Drop zone */}
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onClick={() => inputRef.current?.click()}
        className={`relative rounded-md border-2 border-dashed p-8 text-center cursor-pointer transition-all ${
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
            <p className="text-sm text-zinc-400">Indexing…</p>
          </div>
        ) : (
          <div className="space-y-2">
            <p className="text-2xl">📄</p>
            <p className="text-sm text-zinc-300 font-medium">
              {dragging ? "Drop to upload" : "Drop files here or click to browse"}
            </p>
            <p className="text-xs text-zinc-500">PDF · Word · Markdown · Plain text</p>
          </div>
        )}
      </div>

      {/* Error */}
      {uploadError && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-400 whitespace-pre-wrap font-mono">
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
                  <p className="text-sm font-medium text-zinc-200 truncate">{doc.title}</p>
                  <p className="aug-fs-xs text-zinc-500 font-mono mt-0.5">
                    {doc.filename} · {doc.chunk_count} chunk{doc.chunk_count !== 1 ? "s" : ""} · {timeAgo(doc.uploaded_at)}
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
        <p className="text-xs text-zinc-500 text-center py-4">
          No documents yet. Upload one above to give ADA external context.
        </p>
      )}
    </div>
  );
}
