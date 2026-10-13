"use client";

/**
 * Documents — the corpus every agent, canvas and prompt can search, redone to `aughor-v2/CLARITY.md` (2026-10-13).
 *
 * The screen used to open on a big fact-check form, then an amber paragraph, then a five-step authoring wizard that
 * stood open on every visit, then the connected wikis — and the documents themselves below the fold. Now it leads with
 * what the reader has: four figures (documents · chunks the index holds · sources connected · the newest), then what
 * needs a person (search down, the index and the list disagreeing, chunks no document owns), then the documents.
 * Adding one and checking a memo's numbers are tools, opened from the list's label; the wizard and the checker keep
 * every step and setting they had.
 *
 * Every number about chunks says which record it comes from. The list's per-document count is a CLAIM made at upload
 * time; the index is what search reads, and on a real install they differed (one document claimed 59 where the index
 * held 5). The figure is the index's; a row whose index disagrees shows both, the index's first.
 */
import { DropdownMenu } from "@radix-ui/themes";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { Bar, CARD, Chip, Empty, Figure, Figures, Label, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, Page, ROW, RULE }
  from "@/components/clarity/kit";
import { BROWSER_RENDERABLE, DocumentUploader } from "@/components/DocumentUploader";
import { FactCheckPanel } from "@/components/FactCheckPanel";
import { KnowledgeSourcesSection } from "@/components/KnowledgeSourcesSection";
import { FoldLine, GroupHead } from "@/components/semantic/parts";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Loading, ReadFailed } from "@/components/ui/states";
import { Segmented } from "@/components/ui/segmented";
import {
  deleteDocument,
  documentConvertUrl,
  documentOriginalUrl,
  getDocumentConvertFormats,
  getDocumentFormats,
  getDocumentMarkdown,
  getKnowledgeStatus,
  listDocuments,
  purgeOrphanChunks,
  reindexDocuments,
  restoreDocTrees,
  type ConvertFormat,
  type DocTreePlan,
  type DocumentEntry,
  type DocumentFormats,
  type KnowledgeSource,
  type KnowledgeSourceType,
  type KnowledgeStatus,
  type ReindexPlan,
} from "@/lib/api";
import {
  addedWords, chunksOf, chunkWords, dateWords, documentFigures, documentName, driftedDocuments, formatLabel,
} from "@/lib/documents";
import { countNoun, formatCount, formatTimestamp } from "@/lib/format";
import { connectionLabel } from "@/lib/names";

type Conn = { id: string; name: string };

const LISTED_IS_A_CLAIM = "The listed count is a claim from upload time; search sees the index.";

/** The host of an endpoint, for a chip: "localhost:11434". */
function hostOf(endpoint: string): string {
  try { return new URL(endpoint).host || endpoint; } catch { return endpoint; }
}

export function DocumentsPage({ connectionId, connections = [] }: {
  /** The connection a memo's numbers are checked against. */
  connectionId: string;
  /** Every connection, so a compiled schema document is named by its connection rather than its id. */
  connections?: ReadonlyArray<Conn>;
}) {
  const [docs, setDocs] = useState<DocumentEntry[] | null>(null);
  const [docsFailed, setDocsFailed] = useState<string | null>(null);
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [statusRead, setStatusRead] = useState(false);
  const [statusFailed, setStatusFailed] = useState<string | null>(null);
  const [formats, setFormats] = useState<DocumentFormats | null>(null);
  const [sources, setSources] = useState<{ list: KnowledgeSource[] | null; types: KnowledgeSourceType[] } | null>(null);

  // The two tools. Once opened they stay mounted (hidden when closed), so closing one by mistake keeps the staged
  // files, the review and a running check.
  const [tool, setTool] = useState<"" | "add" | "check">("");
  const [opened, setOpened] = useState<{ add: boolean; check: boolean }>({ add: false, check: false });
  const toolRef = useRef<HTMLDivElement>(null);
  const openTool = (t: "add" | "check") => {
    setTool(prev => (prev === t ? "" : t));
    setOpened(prev => ({ ...prev, [t]: true }));
    requestAnimationFrame(() => toolRef.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" }));
  };

  const [openDocId, setOpenDocId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteFailed, setDeleteFailed] = useState<{ docId: string; error: string } | null>(null);
  const [purging, setPurging] = useState(false);
  const [purgeNote, setPurgeNote] = useState("");
  // The purge is read first, as a dry run, and runs only when the person confirms what it will delete.
  const [purgePlan, setPurgePlan] = useState<{ chunks: number; documents: number } | null>(null);
  const [showSchemaDocs, setShowSchemaDocs] = useState(false);
  const [now] = useState(() => Date.now());

  // A failed read of the list used to leave it empty under "No documents yet", and a failed read of the plane's status
  // showed no banner at all — both read as a healthy, empty corpus.
  const readStatus = useCallback(() => {
    getKnowledgeStatus()
      .then(st => { setStatus(st); setStatusFailed(null); })
      .catch(e => { setStatus(null); setStatusFailed(e instanceof Error ? e.message : String(e)); })
      .finally(() => setStatusRead(true));
  }, []);
  const refresh = useCallback(() => {
    listDocuments().then(d => { setDocs(d); setDocsFailed(null); })
      .catch(e => setDocsFailed(e instanceof Error ? e.message : String(e)));
    // The plane's own account of itself. Without it this screen shows documents and no hint that nothing can be
    // searched — an unreachable embedder looks exactly like a healthy corpus from here.
    readStatus();
    getDocumentFormats().then(setFormats).catch(() => setFormats(null));
  }, [readStatus]);
  useEffect(() => { refresh(); }, [refresh]);

  const onSources = useCallback((list: KnowledgeSource[] | null, types: KnowledgeSourceType[]) => setSources({ list, types }), []);

  const onAdded = useCallback((added: DocumentEntry[]) => {
    setDocs(prev => {
      const have = new Set((prev ?? []).map(d => d.doc_id));
      return [...(prev ?? []), ...added.filter(r => !have.has(r.doc_id))];
    });
    readStatus();
  }, [readStatus]);

  const remove = async (doc: DocumentEntry) => {
    setDeletingId(doc.doc_id);
    setDeleteFailed(null);
    try {
      await deleteDocument(doc.doc_id);
      setDocs(prev => (prev ?? []).filter(d => d.doc_id !== doc.doc_id));
      setOpenDocId(prev => (prev === doc.doc_id ? null : prev));
      readStatus();
    } catch (e) {
      setDeleteFailed({ docId: doc.doc_id, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setDeletingId(null);
    }
  };

  // The purge endpoint deletes index orphans WITHOUT the re-embed a full re-index forces. It is a delete, so it is
  // read first as a dry run — what it would remove — and runs only on the person's confirm.
  const planPurge = async () => {
    setPurging(true);
    setPurgeNote("");
    try {
      const r = await purgeOrphanChunks(true);
      if (r.ok === false) { setPurgeNote(String(r.error ?? "The index could not be read whole, so nothing was planned.")); return; }
      setPurgePlan({ chunks: Number(r.orphan_chunks ?? 0), documents: (r.orphan_documents as unknown[] | undefined)?.length ?? 0 });
    } catch (e) {
      setPurgeNote(e instanceof Error ? e.message : String(e));
    } finally {
      setPurging(false);
    }
  };
  const purge = async () => {
    setPurging(true);
    try {
      const r = await purgeOrphanChunks(false);
      setPurgeNote(`Purged ${String(r.orphans_purged ?? r.purged ?? "the orphans")} — re-reading the status.`);
      readStatus();
    } catch (e) {
      setPurgeNote(e instanceof Error ? e.message : String(e));
    } finally {
      setPurging(false);
      setPurgePlan(null);
    }
  };

  const all = docs ?? [];
  const f = documentFigures(all, status);
  const uploaded = all.filter(d => !d.generated);
  const schemaDocs = all.filter(d => d.generated);
  const maxChunks = Math.max(1, ...all.map(d => chunksOf(d, status).claimed));
  const drifted = driftedDocuments(all, status, connections);
  const fix = useDriftFix(drifted, refresh);
  const consistency = status?.consistency;
  const consistencyError = (consistency as { error?: string } | undefined)?.error;
  const emb = status?.embedder;
  const local = !!emb && (emb.backend === "ollama" || /localhost|127\.0\.0\.1|\[::1\]/.test(emb.endpoint || ""));

  const chunksSub = f.indexed == null
    ? "search status not read"
    : f.orphans > 0 ? `${formatCount(f.orphans)} of them not listed`
    : f.indexed === f.listed ? "matches the list" : `of ${formatCount(f.listed)} listed`;

  const docRow = (doc: DocumentEntry, i: number) => (
    <DocumentRow key={doc.doc_id} doc={doc} first={i === 0} status={status} connections={connections} now={now}
      maxChunks={maxChunks} open={openDocId === doc.doc_id} removing={deletingId === doc.doc_id}
      removeFailed={deleteFailed?.docId === doc.doc_id ? deleteFailed.error : null}
      onView={() => setOpenDocId(prev => (prev === doc.doc_id ? null : doc.doc_id))}
      onRemove={() => remove(doc)} />
  );

  return (
    <Page testId="documents">
      {statusFailed !== null && <ReadFailed what="the search status" error={statusFailed} onRetry={refresh} />}

      <Figures testId="documents-figures">
        <Figure testId="fig-documents" label="Documents" value={docs ? formatCount(f.documents) : "—"}
          sub={!docs ? (docsFailed ? "could not be read" : "reading…")
            : f.documents === 0 ? "none yet"
            : f.uploaded === 0 ? "all compiled from your schemas"
            : f.generated === 0 ? "all uploaded" : `${formatCount(f.uploaded)} uploaded · ${formatCount(f.generated)} from your schemas`} />
        <Figure testId="fig-chunks" label="Chunks indexed" value={f.indexed == null ? "—" : formatCount(f.indexed)}
          title={`What search sees — the index's own count. ${LISTED_IS_A_CLAIM}`}
          sub={<>
            <span>{chunksSub}</span>
            {emb && (emb.ok
              ? <Chip testId="embedder-chip" title={`The embedding model${emb.dim != null ? ` · ${emb.dim} dimensions` : ""}. Set by configuration, `
                  + "not here: changing it means re-embedding the whole corpus — a different model is a different vector space."}>
                  {emb.model}
                </Chip>
              : <Chip tone="amber" testId="embedder-chip" title="No embedder is answering, so nothing can be indexed or searched.">
                  no embedder answering
                </Chip>)}
          </>} />
        <Figure testId="fig-sources" label="Sources connected"
          value={sources?.list ? formatCount(sources.list.length) : "—"}
          sub={!sources ? "reading…" : !sources.list ? "could not be read"
            : sources.list.length ? sources.list.map(s => s.name).join(" · ")
            : sources.types.map(t => t.label).join(" · ") || "none yet"} />
        <Figure testId="fig-newest" label="Last added" value={f.newest ? dateWords(f.newest.uploaded_at, now) : "—"}
          title={f.newest ? formatTimestamp(f.newest.uploaded_at) : undefined}
          sub={f.newest ? documentName(f.newest, connections) : docs ? "nothing added yet" : "—"} />
      </Figures>

      <NeedsYou testId="documents-needs"
        empty={status ? "Nothing needs you · search is up and the index matches the list"
          : statusRead ? "Nothing needs you that could be checked · the search status was not read" : "Reading the search status…"}>
        {[
          status && !status.ready && (
            <NeedsRow key="search" testId="needs-search"
              title={<span style={ROW}>
                Search is unavailable — {status.reason}
                {emb && !emb.ok && (
                  <Chip tone="amber" title={emb.error ?? undefined}>{emb.model} at {hostOf(emb.endpoint)}</Chip>
                )}
              </span>}
              detail={emb && !emb.ok && local
                ? "A local model — indexing and search work only where it runs. Documents already uploaded are unaffected."
                : "Documents already uploaded are unaffected; nothing can be indexed or searched until this is resolved."}
              actions={<>
                {docs?.length === 0 && <Button size="xs" variant="secondary" onClick={() => openTool("add")}>Add a document</Button>}
                <Button size="xs" variant="ghost" onClick={refresh}>Check again</Button>
              </>} />
          ),
          drifted.length > 0 && (
            <NeedsRow key="drift" testId="needs-drift"
              title={`The index and this list disagree on ${countNoun(drifted.length, "document")}`}
              detail={fix.detail ?? <span title={LISTED_IS_A_CLAIM}>
                {`${drifted.map(d => d.name).join(", ")} — the index holds ${formatCount(drifted.reduce((n, d) => n + d.indexed, 0))} `
                  + `of their ${countNoun(drifted.reduce((n, d) => n + d.claimed, 0), "listed chunk")}; search sees the index`}
              </span>}
              actions={fix.actions} />
          ),
          consistency && consistency.orphan_chunks > 0 && (
            <NeedsRow key="orphans" testId="needs-orphans"
              title={`${countNoun(consistency.orphan_chunks, "chunk")} across ${countNoun(consistency.orphan_documents, "document")} `
                + "are in the index but not listed"}
              detail={purgePlan
                ? `Purging deletes ${countNoun(purgePlan.chunks, "chunk")} across ${countNoun(purgePlan.documents, "document")} from the index · nothing is re-embedded`
                : purgeNote || "Search still finds them; no document here owns them."}
              actions={purgePlan ? <>
                <Button size="xs" variant="destructive" disabled={purging} onClick={purge}>{purging ? "Purging…" : "Purge"}</Button>
                <Button size="xs" variant="ghost" disabled={purging} onClick={() => setPurgePlan(null)}>Cancel</Button>
              </> : (
                <Button size="xs" variant="secondary" disabled={purging} onClick={planPurge}
                  title="Reads what a purge would delete first — nothing is deleted until you confirm">
                  {purging ? "Reading…" : "Purge orphans…"}
                </Button>
              )} />
          ),
          consistencyError && (
            <NeedsRow key="unchecked" testId="needs-unchecked" title="The index was not compared with this list"
              detail={consistencyError} actions={<Button size="xs" variant="ghost" onClick={refresh}>Check again</Button>} />
          ),
        ]}
      </NeedsYou>

      {opened.check && (
        <div hidden={tool !== "check"} ref={tool === "check" ? toolRef : undefined}>
          <FactCheckPanel connectionId={connectionId} connectionName={connectionId ? connectionLabel(connectionId, connections) : undefined}
            onClose={() => setTool("")} />
        </div>
      )}
      {opened.add && (
        <div hidden={tool !== "add"} ref={tool === "add" ? toolRef : undefined}>
          <DocumentUploader formats={formats} onAdded={onAdded} onClose={() => setTool("")} />
        </div>
      )}

      <section aria-label="Documents" data-testid="documents-list" style={CARD}>
        <Label right={<>
          <Button size="xs" variant="ghost" aria-pressed={tool === "check"} onClick={() => openTool("check")}>
            Check a document&apos;s numbers
          </Button>
          <Button size="xs" variant={tool === "add" ? "secondary" : "default"} aria-pressed={tool === "add"} onClick={() => openTool("add")}>
            <Icon name="plus" size={12} />Add a document
          </Button>
        </>}>
          Documents
        </Label>

        {docsFailed !== null ? (
          <ReadFailed what="the documents" error={docsFailed} onRetry={refresh} />
        ) : docs === null ? (
          <Loading what="the documents" />
        ) : all.length === 0 ? (
          <Empty>No documents yet — add one to give agents your own context.</Empty>
        ) : (
          <>
            {uploaded.length > 0 && schemaDocs.length > 0 && <GroupHead first name="Uploaded" count={uploaded.length} />}
            {uploaded.map(docRow)}
            {/* Compiled schema documentation shares the collection with uploads — right for retrieval, an agent asking
                about a table wants the schema doc — and is not the person's material. Shown open when it is all there
                is; folded under the uploads otherwise, so one real file does not read as sixteen documents. */}
            {schemaDocs.length > 0 && (uploaded.length === 0 ? (
              <>
                <GroupHead first name="Compiled from your schemas" count={schemaDocs.length}
                  right={<span className="aug-fs-xs" style={MUTED}
                    title="Built from each connection's schema so agents can answer questions about your tables. They rebuild themselves.">
                    searchable · not uploaded by you
                  </span>} />
                {schemaDocs.map(docRow)}
              </>
            ) : (
              <>
                <FoldLine open={showSchemaDocs} onToggle={() => setShowSchemaDocs(o => !o)} testId="schema-docs-fold">
                  {`Compiled from your schemas · ${formatCount(schemaDocs.length)} · `
                    + countNoun(schemaDocs.reduce((n, d) => n + chunksOf(d, status).indexed, 0), "chunk")}
                </FoldLine>
                {showSchemaDocs && schemaDocs.map(docRow)}
              </>
            ))}
          </>
        )}
      </section>

      <KnowledgeSourcesSection onSources={onSources} />
    </Page>
  );
}

// ── A document, one row ─────────────────────────────────────────────────────────────────────────────────────────────

// ── the index and the list disagreeing: what can fix it, read first ─────────────────────────────────────────────────

type Drifted = ReturnType<typeof driftedDocuments>[number];
type Fix =
  | { at: "idle" }
  | { at: "reading" }
  | { at: "restore"; conns: string[]; adds: number; reembeds: number }
  | { at: "reindex"; plan: ReindexPlan; why: string }
  | { at: "running"; what: string }
  | { at: "done"; text: string }
  | { at: "failed"; text: string };

/** The connection a compiled schema document documents — `doctree::<connection>::<schema>` read backwards (the server's
 *  `doctree_connection`) — or null for an upload. */
export function doctreeConnection(docId: string): string | null {
  if (!docId.startsWith("doctree::")) return null;
  const rest = docId.slice("doctree::".length);
  const cut = rest.lastIndexOf("::");
  return cut > 0 ? rest.slice(0, cut) : null;
}

/** An embedder named for a person deciding whether to spend it: the model, and whether it runs here. */
function embedderWords(plan: ReindexPlan): string {
  const local = plan.backend === "ollama";
  return `${plan.model ?? "the active model"}${local ? " (local — no charge)" : plan.backend ? " (hosted — billed per chunk)" : ""}`;
}

/**
 * The way back for documents whose index and list disagree, read as a dry run before anything is written. A compiled
 * schema document's source is the artifact the ontology wrote, so RESTORING puts its lost chunks back; where that
 * artifact is gone (measured 2026-10-13: DuckDB's two documents had none), restore has nothing to restore from and the
 * honest fix is CORRECTING THE LIST — a re-index that re-embeds what the index holds and sets each listed count to it.
 * Each is shown with what it would do and runs only on the person's confirm.
 */
function useDriftFix(drifted: Drifted[], onChanged: () => void): { detail: ReactNode | null; actions: ReactNode } {
  const [fix, setFix] = useState<Fix>({ at: "idle" });
  const names = drifted.map(d => d.name).join(", ");
  const failed = (e: unknown) => setFix({ at: "failed", text: e instanceof Error ? e.message : String(e) });

  const plan = async () => {
    setFix({ at: "reading" });
    try {
      const ids = new Set(drifted.map(d => d.docId));
      const conns = [...new Set(drifted.map(d => doctreeConnection(d.docId)).filter((c): c is string => !!c))];
      const plans: DocTreePlan[] = await Promise.all(conns.map(c => restoreDocTrees(true, c)));
      const docs = plans.flatMap(p => p.documents);
      const adds = docs.filter(d => ids.has(d.doc_id)).reduce((n, d) => n + d.adds, 0);
      if (adds > 0) {
        setFix({ at: "restore", conns, adds, reembeds: docs.reduce((n, d) => n + d.in_artifact, 0) });
        return;
      }
      const why = conns.length
        ? `No compiled documentation is kept for ${names}, so there is nothing to restore from.`
        : `${names} ${drifted.length === 1 ? "is an upload" : "are uploads"}: chunks come back only by adding the file again.`;
      const r = await reindexDocuments(true);
      if (r.ok === false) { setFix({ at: "failed", text: `${why} ${r.error ?? "The index could not be read whole."}` }); return; }
      setFix({ at: "reindex", plan: r, why });
    } catch (e) { failed(e); }
  };

  const restore = async (conns: string[]) => {
    setFix({ at: "running", what: "Restoring…" });
    try {
      const out = await Promise.all(conns.map(c => restoreDocTrees(false, c)));
      const broke = out.flatMap(o => o.failed ?? []);
      setFix(broke.length
        ? { at: "failed", text: `Not restored: ${broke.map(b => `${b.doc_id} (${b.error})`).join("; ")}` }
        : { at: "done", text: "Restored from the compiled documentation — re-reading the index." });
      onChanged();
    } catch (e) { failed(e); }
  };

  const reindex = async () => {
    setFix({ at: "running", what: "Re-indexing…" });
    try {
      const r = await reindexDocuments(false);
      setFix(r.ok === false
        ? { at: "failed", text: r.error ?? "The re-index did not run; the corpus is unchanged." }
        : { at: "done", text: "Re-indexed — the list now says what the index holds." });
      onChanged();
    } catch (e) { failed(e); }
  };

  const cancel = <Button size="xs" variant="ghost" onClick={() => setFix({ at: "idle" })}>Cancel</Button>;
  switch (fix.at) {
    case "idle":
      return { detail: null, actions: (
        <Button size="xs" variant="secondary" onClick={plan}
          title="Reads what a restore — or else a re-index — would do first; nothing is written until you confirm">Restore…</Button>
      ) };
    case "reading":
      return { detail: "Reading what a restore would do…", actions: <Button size="xs" variant="secondary" disabled>Reading…</Button> };
    case "restore":
      return {
        detail: <span title={`Restoring re-embeds every compiled document of ${countNoun(fix.conns.length, "connection")} — ${countNoun(fix.reembeds, "chunk")}.`}>
          {`Restoring puts back ${countNoun(fix.adds, "chunk")} from the compiled documentation · re-embeds ${countNoun(fix.reembeds, "chunk")}`}
        </span>,
        actions: <><Button size="xs" variant="secondary" onClick={() => restore(fix.conns)}>Restore</Button>{cancel}</>,
      };
    case "reindex": {
      const corrected = Object.keys(fix.plan.registry_corrections ?? {}).length;
      const text = `${fix.why} Correcting the list re-embeds ${countNoun(fix.plan.chunks_to_re_embed ?? 0, "chunk")} with `
        + `${embedderWords(fix.plan)} and sets ${countNoun(corrected, "document")} to what the index holds.`;
      return {
        detail: <span title={text}>{text}</span>,
        actions: <><Button size="xs" variant="secondary" onClick={reindex}>Correct the list</Button>{cancel}</>,
      };
    }
    case "running":
      return { detail: fix.what, actions: <Button size="xs" variant="secondary" disabled>{fix.what}</Button> };
    case "done":
      return { detail: fix.text, actions: null };
    case "failed":
      return { detail: <span style={{ color: "var(--red4)" }} title={fix.text}>{fix.text}</span>,
        actions: <Button size="xs" variant="ghost" onClick={plan}>Try again</Button> };
  }
}

/** format · name · bar · chunks · added · tools; a compiled schema document has neither a format chip nor tools. */
const ROW_GRID = "64px minmax(0, 1fr) minmax(48px, 140px) 128px 92px 76px";
const SCHEMA_ROW_GRID = "minmax(0, 1fr) minmax(48px, 140px) 128px 92px";

function DocumentRow({ doc, first, status, connections, now, maxChunks, open, removing, removeFailed, onView, onRemove }: {
  doc: DocumentEntry; first: boolean; status: KnowledgeStatus | null; connections: ReadonlyArray<Conn>; now: number;
  maxChunks: number; open: boolean; removing: boolean; removeFailed: string | null; onView: () => void; onRemove: () => void;
}) {
  // Remove deletes the row, its chunks and the original file — asked once more on the row before it runs.
  const [asking, setAsking] = useState(false);
  const c = chunksOf(doc, status);
  const name = documentName(doc, connections);
  const meta = doc.generated ? "" : [doc.filename !== doc.title ? doc.filename : "", doc.has_original === false ? "original not kept" : ""]
    .filter(Boolean).join(" · ");
  return (
    <div data-testid="document-row" style={{ ...(first ? {} : RULE), padding: "8px 2px" }}>
      <div style={{ display: "grid", gridTemplateColumns: doc.generated ? SCHEMA_ROW_GRID : ROW_GRID, gap: 12, alignItems: "center" }}>
        {/* A compiled schema document's group already says what it is; a "Schema" chip would say it on every row. */}
        {!doc.generated && <span><Chip>{formatLabel(doc)}</Chip></span>}
        <div style={{ minWidth: 0 }}>
          <div className="aug-fs-chrome" title={doc.generated ? `Schema documentation — ${name}` : name} style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }}>
            {name}
          </div>
          {meta && <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }}>{meta}</div>}
        </div>
        <span title={`${countNoun(c.indexed, "chunk")} in the index`}><Bar value={c.indexed} max={maxChunks} /></span>
        <span className="aug-fs-sm" style={{ ...NUM, textAlign: "right", color: "var(--t2)" }}>
          {c.drift ? <Chip tone="amber" title={LISTED_IS_A_CLAIM}>{chunkWords(doc, status)}</Chip> : chunkWords(doc, status)}
        </span>
        <span className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }} title={formatTimestamp(doc.uploaded_at)}>
          {addedWords(doc.uploaded_at, now)}
        </span>
        {!doc.generated && (
          <span style={{ ...ROW, flexWrap: "nowrap", gap: 2, justifyContent: "flex-end" }}>
            <Button size="xs" variant="ghost" aria-expanded={open} onClick={onView}>{open ? "Close" : "View"}</Button>
            <RowMenu doc={doc} name={name} removing={removing} onRemove={() => setAsking(true)} />
          </span>
        )}
      </div>
      {asking && (
        <div data-testid="remove-confirm" style={{ ...ROW, padding: "6px 0 0 76px" }}>
          <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>
            {`Remove ${name}? ${countNoun(c.indexed, "chunk")} leave search${doc.has_original ? " and the original file is deleted" : ""}.`}
          </span>
          <Button size="xs" variant="destructive" disabled={removing} onClick={() => { setAsking(false); onRemove(); }}>Remove</Button>
          <Button size="xs" variant="ghost" onClick={() => setAsking(false)}>Keep it</Button>
        </div>
      )}
      {removeFailed && <div role="alert" className="aug-fs-xs" style={{ color: "var(--red4)", paddingLeft: 76 }}>Could not remove it — {removeFailed}</div>}
      {open && <StoredDocument doc={doc} />}
    </div>
  );
}

/** A document's tools, in one menu: open the original, download it as another format, remove it. The formats this
 *  deployment can write are asked for when the menu opens; one it cannot is shown disabled, saying why, so an operator
 *  can see what installing the export extra would add. */
function RowMenu({ doc, name, removing, onRemove }: { doc: DocumentEntry; name: string; removing: boolean; onRemove: () => void }) {
  const [formats, setFormats] = useState<ConvertFormat[] | null>(null);
  return (
    <DropdownMenu.Root onOpenChange={o => {
      if (o && formats === null) getDocumentConvertFormats(doc.doc_id).then(setFormats).catch(() => setFormats([]));
    }}>
      <DropdownMenu.Trigger>
        <Button variant="ghost" size="icon-xs" aria-label={`More for ${name}`}><Icon name="more" size={14} /></Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content size="1" align="end">
        {doc.has_original && (
          <DropdownMenu.Item asChild>
            <a href={documentOriginalUrl(doc.doc_id)} target="_blank" rel="noopener noreferrer">Open the original file</a>
          </DropdownMenu.Item>
        )}
        {formats === null ? (
          <DropdownMenu.Item disabled>Reading the formats…</DropdownMenu.Item>
        ) : formats.map(f => (f.available ? (
          <DropdownMenu.Item key={f.format} asChild>
            <a href={documentConvertUrl(doc.doc_id, f.format)}>Download as {f.label}</a>
          </DropdownMenu.Item>
        ) : (
          <DropdownMenu.Item key={f.format} disabled title="This deployment cannot render that format — the export extra is not installed.">
            Download as {f.label} · not installed
          </DropdownMenu.Item>
        )))}
        <DropdownMenu.Separator />
        <DropdownMenu.Item color="red" disabled={removing} onSelect={onRemove}>{removing ? "Removing…" : "Remove"}</DropdownMenu.Item>
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  );
}

/**
 * A stored document, as itself and as the platform reads it. Two views because they answer different questions:
 * "Original" is the file the person uploaded — the one they recognise; "Markdown" is what reaches an agent, a canvas or
 * a prompt, and seeing it is the only way to know whether a table survived the conversion.
 */
function StoredDocument({ doc }: { doc: DocumentEntry }) {
  const suffix = `.${doc.filename.split(".").pop()?.toLowerCase() ?? ""}`;
  const renderable = !!doc.has_original && BROWSER_RENDERABLE.has(suffix);
  const [view, setView] = useState<"original" | "markdown">(renderable ? "original" : "markdown");
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    getDocumentMarkdown(doc.doc_id)
      .then(m => { if (live) setMarkdown(m); })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : "Could not read the document"); });
    return () => { live = false; };
  }, [doc.doc_id]);

  const original = (
    <a href={documentOriginalUrl(doc.doc_id)} target="_blank" rel="noopener noreferrer" style={{ color: "var(--t1)" }}>
      Open the original file
    </a>
  );
  return (
    <div data-testid="stored-document" style={{ margin: "8px 0 2px 76px", display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={ROW}>
        <Segmented label="Document view" value={view} onChange={setView}
          options={[
            ...(doc.has_original ? [{ value: "original" as const, label: "Original" }] : []),
            { value: "markdown", label: "Markdown" },
          ]} />
        {view === "markdown" && markdown !== null && (
          <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>
            {formatCount(markdown.length)} characters · the text every agent, canvas and prompt sees
          </span>
        )}
      </div>
      {error && <p role="alert" className="aug-fs-xs" style={{ color: "var(--amb4)", margin: 0 }}>{error}</p>}
      {view === "original" && !error && (doc.has_original ? (renderable ? (
        <>
          <iframe src={documentOriginalUrl(doc.doc_id)} title={doc.title}
            style={{ width: "100%", height: "28rem", border: "1px solid var(--b1)", borderRadius: "var(--r2)", background: "var(--bg-0)" }} />
          {/* An embedded PDF renders only where the browser has a PDF plugin; elsewhere the frame is simply BLANK.
              A frame that can fail silently needs a way out beside it. */}
          <span className="aug-fs-xs" style={MUTED}>Blank? {original} — some browsers cannot show it inline. The Markdown view always works.</span>
        </>
      ) : (
        <span className="aug-fs-xs" style={MUTED}>
          A browser cannot display this format — the Markdown view shows what the platform reads from it. {original}
        </span>
      )) : (
        <span className="aug-fs-xs" style={MUTED}>Uploaded before originals were kept, so only its text remains — re-upload it to preview.</span>
      ))}
      {view === "markdown" && !error && (markdown === null ? <Loading what="the Markdown" /> : (
        <pre className="aug-fs-xs" style={{ margin: 0, padding: "8px 10px", borderRadius: "var(--r2)", background: "var(--code-bg)",
          color: "var(--t2)", fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "28rem",
          overflow: "auto" }}>
          {markdown}
        </pre>
      ))}
    </div>
  );
}
