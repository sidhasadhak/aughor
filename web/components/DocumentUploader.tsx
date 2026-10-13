"use client";

/**
 * Add a document — the five steps a file takes into the corpus, opened from the Documents screen's "Add a document"
 * (`components/documents/DocumentsPage.tsx`). Redone to `aughor-v2/CLARITY.md` (2026-10-13): the steps, the chunk
 * settings and the pre-processing rules behave exactly as before; their explanations are one line each, the rest on
 * hover, and the embedding model became a fact on the screen's figures rather than a card here.
 *
 * Numbered, because the sequence is the whole point. This was three unrelated motions sharing a screen: dropping a
 * file converted it on the spot under whatever happened to be in the settings fields — so the settings came AFTER the
 * conversion they were supposed to govern; the chunk preview had its own file picker, so the same document was chosen
 * twice to answer two questions; and the thing actually being decided — the Markdown — appeared far below. Nothing is
 * converted until ③, nothing is indexed until ⑤, and moving ② after ③ marks the review stale rather than leaving it to
 * describe a cut that is no longer in force.
 */
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { Chip, Label, MUTED, NUM, ONE_LINE, ROW, RULE } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { ErrorState } from "@/components/ui/states";
import {
  convertDocument,
  previewDocumentChunks,
  uploadDocument,
  type ChunkPreview,
  type ChunkSettings,
  type DocumentConversion,
  type DocumentEntry,
  type DocumentFormats,
} from "@/lib/api";
import { countNoun, formatCount } from "@/lib/format";
import { formatLabel } from "@/lib/documents";

/** Until the server answers, accept only what needs no converter. The list used to be a hard-coded five and stayed
 *  five while the parser grew to twenty — a capability that exists and is unreachable from the file picker. This is a
 *  floor, not the list. */
const FALLBACK_ACCEPT = ".md,.markdown,.txt";

/** What a browser can show in a frame. */
export const BROWSER_RENDERABLE = new Set([".pdf", ".txt", ".md", ".markdown", ".csv"]);

/** Bytes, for a file that has not been read yet. Everything else here counts characters or chunks, but neither exists
 *  until ③ converts. */
function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const pagesList = (p: number[]) => p.slice(0, 8).join(", ") + (p.length > 8 ? "…" : "");

/** The numeral for one step: `now` is where the person is, `done` behind them, `todo` not yet reachable — a
 *  disabled-looking button with no explanation is the failure this replaces. */
function StepDot({ n, state }: { n: number; state: "todo" | "now" | "done" }) {
  const look: CSSProperties = state === "now"
    ? { background: "var(--accent)", color: "var(--on-primary)" }
    : state === "done"
      ? { background: "var(--blue1)", color: "var(--blue4)" }
      : { border: "1px solid var(--b2)", color: "var(--t3)" };
  return (
    <span className="aug-fs-xs" style={{ ...look, ...NUM, display: "inline-flex", alignItems: "center", justifyContent: "center",
      width: 18, height: 18, borderRadius: "var(--r-pill)", flexShrink: 0, fontWeight: 600 }}>
      {n}
    </span>
  );
}

/** A numbered step's heading: its numeral, its name, one muted hint; `title` holds what the step does, on hover. */
function StepHeading({ n, state, title, hint, tip }: {
  n: number; state: "todo" | "now" | "done"; title: string; hint?: ReactNode; tip?: string;
}) {
  return (
    <div style={{ ...ROW, flexWrap: "nowrap", marginBottom: 8 }} title={tip}>
      <StepDot n={n} state={state} />
      <span className="aug-fs-chrome" style={{ fontWeight: 600, color: state === "todo" ? "var(--t3)" : "var(--t1)" }}>{title}</span>
      {hint != null && <span className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }}>{hint}</span>}
    </div>
  );
}

/** One muted line under a field or a rule; `tip` carries the rest of the explanation. */
function Hint({ children, tip, tone }: { children: ReactNode; tip?: string; tone?: "amber" | "green" }) {
  return (
    <p className="aug-fs-xs" title={tip} style={{ margin: "2px 0 0", lineHeight: 1.45,
      color: tone === "amber" ? "var(--amb4)" : tone === "green" ? "var(--grn4)" : "var(--t3)" }}>
      {children}
    </p>
  );
}

const PANEL: CSSProperties = { background: "var(--bg-1)", borderRadius: "var(--r2)", padding: 12, minWidth: 0 };

export function DocumentUploader({ formats, onAdded, onClose }: {
  /** What this deployment can read, as the screen asked it. */
  formats: DocumentFormats | null;
  /** The documents that landed, for the screen's list and its status to take in. */
  onAdded?: (entries: DocumentEntry[]) => void;
  onClose?: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [partialNotes, setPartialNotes] = useState<string[]>([]);
  const [suppressedNotes, setSuppressedNotes] = useState<string[]>([]);

  // ① CHOSEN, and nothing more. No request has been made for these — they are File objects sitting in the browser.
  const [staged, setStaged] = useState<File[]>([]);
  // ③ produced these, keyed by filename. Still indexed nowhere: the File objects are posted again on approval, so
  // there is no staging area on the server to expire, sweep or leak, and conversion is deterministic so what is
  // approved is what lands.
  const [reviews, setReviews] = useState<Record<string, DocumentConversion>>({});
  const [cuts, setCuts] = useState<Record<string, ChunkPreview>>({});
  // The settings ③ ran under, serialised. A review describes a document AS CUT BY settings; move them afterwards and
  // it describes something that would no longer be indexed, so the panel says so instead of letting it stand.
  const [reviewedUnder, setReviewedUnder] = useState<string | null>(null);
  const [converting, setConverting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const accept = formats?.accept ?? FALLBACK_ACCEPT;

  // Chunking, as settings rather than three constants nobody could see. Empty means the defaults the corpus was
  // indexed under — an omitted field is the previous behaviour.
  const [settings, setSettings] = useState<Partial<ChunkSettings>>({});

  // ④ which staged file is being read, and as what. One file, three views of it.
  const [shown, setShown] = useState(0);
  const [reviewTab, setReviewTab] = useState<"original" | "markdown" | "chunks">("original");
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);

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

  /** The staged file as itself, for ④. A blob URL, because the file has not been uploaded and must not be. Guarded
   *  because `createObjectURL` is absent in jsdom and in some locked-down webviews. */
  useEffect(() => {
    if (!file || typeof URL.createObjectURL !== "function") { setOriginalUrl(null); return; }
    const url = URL.createObjectURL(file);
    setOriginalUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

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

  /** ③ Convert and cut the staged files, indexing nothing. Two calls per file and neither writes: the Markdown is the
   *  decision, the cut is what ②'s numbers do to it. */
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
      // The cut is detail; the Markdown is the decision. A preview that fails must not cost the review that succeeded.
      try {
        cutBy[f.name] = await previewDocumentChunks(f, settings);
      } catch { /* the Chunks view says so */ }
    }
    setReviews(converted);
    setCuts(cutBy);
    setReviewedUnder(JSON.stringify(settings));
    setReviewTab(Object.keys(converted).length > 0 ? "markdown" : "original");
    if (errors.length > 0) setUploadError(errors.join("\n"));
    setConverting(false);
  }, [staged, settings]);

  /** ⑤ The only call here that writes anything. */
  const commitStaged = useCallback(async (files: File[]) => {
    if (files.length === 0) return;
    setUploadError(null);
    setPartialNotes([]);
    setSuppressedNotes([]);
    setUploading(true);
    const results: DocumentEntry[] = [];
    const errors: string[] = [];
    for (const f of files) {
      try {
        results.push(await uploadDocument(f, settings));
      } catch (e) {
        errors.push(`${f.name}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }
    if (results.length > 0) onAdded?.(results);
    // Held back from SEARCH, not from the document — reported so it is never silent.
    setSuppressedNotes(results
      .filter(r => (r.suppressed_numeric_runs ?? 0) > 0)
      .map(r => `${r.filename}: ${countNoun(r.suppressed_numeric_runs ?? 0, "line")} of unlabelled figures`));
    // A part-scanned PDF is a SUCCESS with a hole in it. The two causes are named separately: OCR fixes one and
    // nothing fixes the other, so merging them would send a person to buy OCR they do not need.
    setPartialNotes(results
      .filter(r => (r.pages_needing_ocr?.length ?? 0) + (r.pages_failed?.length ?? 0) > 0)
      .map(r => {
        const scanned = r.pages_needing_ocr ?? [];
        const broken = r.pages_failed ?? [];
        const why = [
          scanned.length ? `page${scanned.length !== 1 ? "s" : ""} ${pagesList(scanned)} `
                         + `${scanned.length !== 1 ? "are" : "is"} scanned (no text layer)` : "",
          broken.length ? `page${broken.length !== 1 ? "s" : ""} ${pagesList(broken)} could not be read` : "",
        ].filter(Boolean).join("; ");
        return `${r.filename}: read ${r.pages_read} of ${r.page_count} pages — ${why}.`;
      }));
    if (errors.length > 0) setUploadError(errors.join("\n"));
    // Only what actually landed leaves the tray. A file that failed stays staged with its review intact, so the retry
    // does not start again at ①.
    const landed = new Set(results.map(r => r.filename));
    setStaged(prev => prev.filter(f => !landed.has(f.name)));
    setReviews(prev => Object.fromEntries(Object.entries(prev).filter(([name]) => !landed.has(name))));
    setCuts(prev => Object.fromEntries(Object.entries(prev).filter(([name]) => !landed.has(name))));
    setShown(0);
    setUploading(false);
  }, [settings, onAdded]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    stageFiles(e.dataTransfer.files);
  }, [stageFiles]);

  const changed = Object.keys(settings).length;
  const ext = (name: string) => `.${name.split(".").pop()?.toLowerCase() ?? ""}`;

  return (
    <section aria-label="Add a document" data-testid="add-document"
      style={{ background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "12px 14px" }}>
      <Label right={<>
        <Chip title="Converting reads the file and indexes nothing; only step 5 stores it">nothing stored until step 5</Chip>
        {onClose && <Button size="xs" variant="ghost" onClick={onClose} aria-label="Close Add a document">
          <Icon name="close" size={12} />Close
        </Button>}
      </>}>
        Add a document
      </Label>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 14, alignItems: "start" }}>
        {/* ── left: what to add, and how ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
          <div>
            <StepHeading n={1} state={staged.length > 0 ? "done" : "now"} title="Choose a file"
              hint={staged.length > 0 ? `${staged.length} chosen · nothing sent yet` : undefined} />
            {staged.length === 0 ? (
              <div
                role="button" tabIndex={0} aria-label="Choose files to add"
                onDrop={onDrop}
                onDragOver={e => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onClick={() => inputRef.current?.click()}
                onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inputRef.current?.click(); } }}
                style={{ borderRadius: "var(--r2)", padding: "20px 12px", textAlign: "center", cursor: "pointer",
                  border: `1px dashed ${dragging ? "var(--blue3)" : "var(--b2)"}`,
                  background: dragging ? "var(--blue1)" : "var(--bg-1)" }}>
                <div className="aug-fs-chrome" style={{ color: "var(--t1)", fontWeight: 500, ...ROW, justifyContent: "center" }}>
                  <Icon name="upload" size={14} />{dragging ? "Drop to choose" : "Drop files here or click to browse"}
                </div>
                <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 4 }}
                  title={formats?.converter === false ? "Install the document converter to read Word, PDF, slides and sheets" : undefined}>
                  {formats?.converter === false
                    ? "Markdown · Plain text — no converter installed for Word, PDF, slides or sheets"
                    : "PDF · Word · Slides · Sheets · OpenDocument · RTF · EPUB · CSV · Markdown"}
                </div>
              </div>
            ) : (
              <div style={PANEL}>
                {staged.map((f, i) => (
                  <div key={f.name} style={{ ...(i ? RULE : {}), display: "flex", alignItems: "center", gap: 8, padding: "6px 4px",
                    borderRadius: i === shown ? "var(--r2)" : undefined, background: i === shown ? "var(--bg-sel)" : undefined }}>
                    <Button variant="ghost" size="xs" onClick={() => setShown(i)} aria-pressed={i === shown}
                      style={{ flex: 1, minWidth: 0, justifyContent: "flex-start", height: "auto", padding: "2px 4px", fontWeight: 400 }}>
                      <Chip>{formatLabel({ filename: f.name })}</Chip>
                      <span style={{ minWidth: 0, textAlign: "left" }}>
                        <span className="aug-fs-sm" style={{ ...ONE_LINE, display: "block", color: "var(--t1)" }}>{f.name}</span>
                        <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, display: "block" }}>
                          {sizeLabel(f.size)}
                          {reviews[f.name] ? ` · ${countNoun(reviews[f.name].would_index_chunks, "chunk")} to index` : " · not read yet"}
                        </span>
                      </span>
                    </Button>
                    <Button variant="ghost" size="xs" onClick={() => unstage(f.name)} aria-label={`Remove ${f.name}`}>Remove</Button>
                  </div>
                ))}
                <Button variant="ghost" size="xs" onClick={() => inputRef.current?.click()} style={{ marginTop: 4 }}>
                  Choose different files…
                </Button>
              </div>
            )}
            <input ref={inputRef} type="file" accept={accept} multiple hidden onChange={e => stageFiles(e.target.files)} />
          </div>

          <div>
            <StepHeading n={2} state={staged.length === 0 ? "todo" : reviewed ? "done" : "now"} title="Set how it is cut"
              hint={changed === 0 ? "defaults" : `${changed} changed`}
              tip="One chunk per delimiter block. The same chunk is retrieved and given as context." />
            <div style={{ ...PANEL, display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
                <div>
                  <label className="aug-fs-xs" style={{ color: "var(--t2)", display: "block", marginBottom: 4 }} htmlFor="chunk-delimiter">
                    Delimiter
                  </label>
                  <Input id="chunk-delimiter" type="text" value={settings.delimiter ?? ""} placeholder="\n\n"
                    onChange={e => setSettings(prev => (e.target.value
                      ? { ...prev, delimiter: e.target.value }
                      : Object.fromEntries(Object.entries(prev).filter(([k]) => k !== "delimiter"))))}
                    style={{ width: "100%" }} />
                </div>
                {([
                  ["max_chars", "Maximum chunk length", "characters", undefined],
                  ["overlap_chars", "Chunk overlap", "characters", undefined],
                  ["min_chars", "Minimum chunk length", "shorter chunks are discarded", "Below this a chunk is DISCARDED — it is not indexed at all"],
                ] as const).map(([key, label, hint, tip]) => (
                  <div key={key}>
                    <label className="aug-fs-xs" style={{ color: "var(--t2)", display: "block", marginBottom: 4 }} htmlFor={`chunk-${key}`}>
                      {label}
                    </label>
                    <Input id={`chunk-${key}`} type="number" min={1} value={settings[key] ?? ""}
                      placeholder={String(cut?.settings?.[key] ?? "default")}
                      onChange={e => setNum(key)(e.target.value)} style={{ width: "100%" }} />
                    <Hint tip={tip}>{hint}</Hint>
                  </div>
                ))}
              </div>

              <div>
                <div className="aug-fs-xs" style={{ color: "var(--t2)", fontWeight: 500, marginBottom: 6 }}
                  title="Applied before chunking and embedding">
                  Text pre-processing rules
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <label className="aug-fs-xs" style={{ ...ROW, flexWrap: "nowrap", color: "var(--t2)" }}>
                    <Checkbox checked={settings.collapse_whitespace ?? true}
                      onChange={e => setSettings(prev => ({ ...prev, collapse_whitespace: e.target.checked }))} />
                    Replace consecutive spaces, newlines and tabs
                  </label>
                  <div>
                    <label className="aug-fs-xs" style={{ ...ROW, flexWrap: "nowrap", color: "var(--t2)" }}>
                      <Checkbox checked={settings.strip_urls_emails ?? false}
                        onChange={e => setSettings(prev => ({ ...prev, strip_urls_emails: e.target.checked }))} />
                      Delete all URLs and email addresses
                    </label>
                    <Hint>Off by default: a policy that cites a source loses the citation.</Hint>
                  </div>
                  <div>
                    <label className="aug-fs-xs" style={{ ...ROW, flexWrap: "nowrap", color: "var(--t2)" }}>
                      <Checkbox checked={settings.suppress_numeric_runs ?? true}
                        onChange={e => setSettings(prev => ({ ...prev, suppress_numeric_runs: e.target.checked }))} />
                      Keep unlabelled runs of figures out of search
                    </label>
                    <Hint tip={"A chart's labels are graphics, so its values arrive as a headless row where every figure is right and "
                      + "none is attached to what it measures. They stay in the file and in every download; only search skips them."}>
                      On by default; it does not change the document — only search skips them.
                    </Hint>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* ③ and ⑤ — the two moments that do something, on one line, in order. ⑤ cannot fire until ③ has produced a
              review of the settings now in force, which is what makes "confirm" mean something. */}
          <div>
            <div style={ROW}>
              <Button variant="outline" size="xs" onClick={convertStaged} disabled={staged.length === 0 || converting}>
                <StepDot n={3} state={staged.length > 0 && !reviewed ? "now" : reviewed ? "done" : "todo"} />
                {converting ? "Reading…" : reviewed ? "Convert again" : "Convert & review"}
              </Button>
              <Button variant="ghost" size="xs" onClick={() => { setSettings({}); resetStaged(); }}>Reset</Button>
              <Button variant="default" size="xs" onClick={() => commitStaged(staged)} disabled={!reviewed || uploading}
                style={{ marginLeft: "auto" }}>
                <StepDot n={5} state={reviewed ? "now" : "todo"} />
                {uploading ? "Adding…" : `Add ${staged.length > 1 ? `${staged.length} documents` : "to knowledge"}`}
              </Button>
            </div>
            <Hint tone={stale ? "amber" : undefined}>
              {staged.length === 0
                ? "Choose a file to begin. Converting reads it and indexes nothing."
                : stale
                  ? "Settings changed since the last read — convert again to see what they do now."
                  : reviewed
                    ? "Read it alongside. Adding embeds it and makes it searchable."
                    : "Converting reads the file and indexes nothing. It works while search is down."}
            </Hint>
          </div>
        </div>

        {/* ── right: ④ the file as itself, and as the platform will read it ── */}
        <div style={{ minWidth: 0 }}>
          <StepHeading n={4} state={reviewed ? "done" : staged.length > 0 ? "now" : "todo"} title="Read it before you commit"
            hint={file?.name} />
          <div style={PANEL}>
            <div style={{ ...ROW, marginBottom: 8 }}>
              {/* The views a review has: the original always, the rest once it is read. */}
              <Segmented label="Review view" value={reviewTab} onChange={setReviewTab} disabled={!file}
                options={[
                  { value: "original", label: "Original" },
                  ...(review ? [{ value: "markdown" as const, label: "Markdown" }, { value: "chunks" as const, label: "Chunks" }] : []),
                ]} />
              <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, marginLeft: "auto" }}>
                {review
                  ? `${formatCount(review.characters)} characters · ${countNoun(review.would_index_chunks, "chunk")} to index${
                      review.page_count > 0 ? ` · ${review.pages_read} of ${review.page_count} pages read` : ""}`
                  : file ? `${sizeLabel(file.size)} · not read yet` : "nothing chosen"}
              </span>
            </div>

            {/* Losses named BEFORE the decision, not after. Approving something whose gaps were only disclosed
                afterwards is not approval. */}
            {review && (review.pages_needing_ocr.length > 0 || review.pages_failed.length > 0) && (
              <Hint tone="amber">
                {review.pages_needing_ocr.length > 0 && (
                  <>Page{review.pages_needing_ocr.length !== 1 ? "s" : ""} {pagesList(review.pages_needing_ocr)}{" "}
                  {review.pages_needing_ocr.length !== 1 ? "are" : "is"} scanned — no text layer. </>
                )}
                {review.pages_failed.length > 0 && (
                  <>Page{review.pages_failed.length !== 1 ? "s" : ""} {review.pages_failed.join(", ")} could not be read.</>
                )}
              </Hint>
            )}
            {review && (review.charts_recovered ?? 0) > 0 && (
              <Hint tone="green" tip="A chart's values are exact text the Markdown could not carry; only their positions said what they measured.">
                {countNoun(review.charts_recovered ?? 0, "chart")} read back from page{(review.chart_pages?.length ?? 0) !== 1 ? "s" : ""}{" "}
                {pagesList(review.chart_pages ?? [])} and appended as tables.
              </Hint>
            )}
            {review && review.suppressed_numeric_runs > 0 && (
              <Hint tip="They stay in the document and in every download.">
                {countNoun(review.suppressed_numeric_runs, "line")} of unlabelled figures will be kept out of search.
              </Hint>
            )}
            {stale && <Hint tone="amber">This was read under the previous settings.</Hint>}

            <div style={{ marginTop: 8 }}>
              {!file ? (
                <Hint>Choose a file to see it here — the file, the Markdown the platform reads, and its chunks.</Hint>
              ) : reviewTab === "original" ? (
                BROWSER_RENDERABLE.has(ext(file.name)) && originalUrl ? (
                  <>
                    <iframe src={originalUrl} title={file.name}
                      style={{ width: "100%", height: "26rem", border: "1px solid var(--b1)", borderRadius: "var(--r2)", background: "var(--bg-0)" }} />
                    {/* An embedded PDF renders only where the viewer's browser has a PDF plugin; elsewhere the frame
                        is simply BLANK with nothing to explain it. */}
                    <Hint>Blank? Some browsers cannot show a file inline — the Markdown view always works, and it is what gets indexed.</Hint>
                  </>
                ) : (
                  <Hint>A browser cannot display this format directly — the Markdown view shows what search reads from it.</Hint>
                )
              ) : reviewTab === "markdown" ? (
                review ? (
                  <>
                    <Hint>This is exactly what will be indexed and what every agent, canvas and prompt will see.</Hint>
                    <pre className="aug-fs-xs" style={{ margin: "6px 0 0", padding: "8px 10px", borderRadius: "var(--r2)",
                      background: "var(--code-bg)", color: "var(--t2)", fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap",
                      wordBreak: "break-word", maxHeight: "26rem", overflow: "auto" }}>
                      {review.markdown}
                    </pre>
                  </>
                ) : <Hint>Convert at step 3 to read this.</Hint>
              ) : cut ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <Hint>Showing {cut.shown} of {formatCount(cut.total_chunks)} chunks · {formatCount(cut.characters)} characters</Hint>
                  {cut.chunks.map(c => (
                    <div key={c.index} style={{ background: "var(--bg-2)", borderRadius: "var(--r2)", padding: "6px 8px" }}>
                      <div className="aug-fs-xs" style={{ ...MUTED, ...NUM, marginBottom: 2 }}>
                        <span style={{ color: "var(--t1)" }}>Chunk {c.index + 1}</span>
                        {" · "}{formatCount(c.characters)} characters · ~{formatCount(c.tokens_estimate)} tokens
                      </div>
                      <div className="aug-fs-xs line-clamp-6" style={{ color: "var(--t2)", whiteSpace: "pre-wrap" }}>{c.text}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <Hint>
                  {review ? "The cut could not be previewed for this file. The Markdown view is the decision." : "Convert at step 3 to see the cut."}
                </Hint>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* After step 5. Indexed less than the document holds, said out loud — neutral, because nothing is lost: the
          figures stay in the file and every download. Imported with pages missing is amber: the document IS indexed,
          and the person's next move is OCR or a different export, not a retry. */}
      {(suppressedNotes.length > 0 || partialNotes.length > 0 || uploadError) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 14 }}>
          {partialNotes.length > 0 && (
            <div data-testid="add-partial">
              <Chip tone="amber" title="The rest of each document is indexed and searchable. Scanned pages need OCR, which is off by default because it sends the file to a third party.">
                Imported with pages missing
              </Chip>
              {partialNotes.map(note => <Hint key={note}>{note}</Hint>)}
            </div>
          )}
          {suppressedNotes.length > 0 && (
            <div data-testid="add-suppressed">
              <Chip title="Chart labels extract as figures attached to nothing, so an answer drawn from them can be confidently wrong. They remain in the document and in every download. Turn the rule off at step 2 to index them.">
                Kept out of search
              </Chip>
              {suppressedNotes.map(note => <Hint key={note}>{note}</Hint>)}
            </div>
          )}
          {uploadError && (
            <ErrorState kind="Upload failed" what={<span className="aug-mono" style={{ whiteSpace: "pre-wrap" }}>{uploadError}</span>} />
          )}
        </div>
      )}
    </section>
  );
}
