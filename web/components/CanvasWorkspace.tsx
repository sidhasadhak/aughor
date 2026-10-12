"use client";

/**
 * An open Data Canvas — its chrome redone to `aughor-v2/CLARITY.md` (2026-10-12). The conversation, the reports and
 * the configuration panel are what the person made and are drawn as before; around them: one header line (the way
 * back, the name, what it is in a line, its facts as chips, the three views, a new conversation and one Tools menu),
 * a two-line landing in place of a block that repeated the header, the history with a question asked eleven times said
 * once, and the saved artifacts — each saying when it could not be read, never showing that as empty.
 */
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";

import { ToolsMenu, type ToolItem } from "@/components/catalog/CatalogTools";
import { Card, Chip, Empty, Label, MUTED, NUM, ONE_LINE, Page, ROW, RULE } from "@/components/clarity/kit";
import { ChatPanel } from "@/components/ChatPanel";
import { ConfigurePanel } from "@/components/ConfigurePanel";
import { HistoryDetailPanel } from "@/components/HistoryDetailPanel";
import { LifecyclePanel } from "@/components/LifecyclePanel";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { Loading, ReadFailed } from "@/components/ui/states";
import { Textarea } from "@/components/ui/textarea";
import type { Canvas, CanvasHistoryItem as HistoryItem, Connection } from "@/lib/api";
import {
  deleteCanvasArtifact, deleteInvestigation, getCanvasArtifacts, getCanvasDocuments, getCanvasHistory, listDocuments,
  updateCanvas, type CanvasArtifact, type CanvasDocument, type DocumentEntry,
} from "@/lib/api";
import {
  agoWords, connectionGone, connectionKind, dayMonth, foldHistory, RUN_KIND_WORD, runStateWord, scopeWords, tablesOf,
  tablesTitle, type AskedQuestion, type RunKind,
} from "@/lib/canvasList";
import { countNoun, formatCount, formatTimestamp } from "@/lib/format";

type WsTab = "chat" | "history" | "artifacts";

/** How many runs the history reads; when it reads this many, it says they are the latest. */
const HISTORY_LIMIT = 30;

const HIDDEN_UNTIL_HOVER = "opacity-0 group-hover/run:opacity-100 focus-visible:opacity-100 transition-opacity";

// ── The header line ───────────────────────────────────────────────────────────────────────────────────────────────

/**
 * The line an open canvas starts on — the Catalog's `PanelHead` (`catalog/CatalogTools.tsx`), drawn the same, with the
 * two things a canvas needs that it has no slot for: a way back to the list before the name, and a name that keeps
 * room for a word when the line is short. When it is, the description gives way first, then the connection's chip,
 * then the name; the views and the tools never do (with a long name and four views the line was once wider than its
 * box, and the workspace slid sideways under the rail at 1176px).
 */
function CanvasHead({ name, what, chips, actions, onBack, overlay }: {
  name: string; what?: string; chips: ReactNode; actions: ReactNode; onBack: () => void;
  /** What opens from the line — the Settings popover — placed against it. */
  overlay?: ReactNode;
}) {
  return (
    <div data-testid="canvas-head" style={{ ...ROW, flexWrap: "nowrap", gap: 10, padding: "10px 22px",
      borderBottom: "1px solid var(--b0)", background: "var(--bg-0)", flexShrink: 0, minWidth: 0, position: "relative" }}>
      <Button variant="ghost" size="xs" onClick={onBack} title="Back to all canvases" data-testid="canvas-back"
        style={{ flexShrink: 0, color: "var(--t3)" }}>
        <Icon name="back" size={12} /> Data Canvas
      </Button>
      <span data-testid="canvas-name" className="aug-fs-ui" title={name}
        style={{ ...ONE_LINE, minWidth: 64, flexShrink: 1, color: "var(--t1)", fontWeight: 600 }}>
        {name}
      </span>
      {what && (
        <span data-testid="canvas-what" className="aug-fs-sm" title={what}
          // A basis of 0: it takes only the room left. Shrink weights scale by each item's own width, so a long
          // description at flexShrink 6 still cut the name to "E-Commerce Operations Overv…" (2026-10-12, live).
          style={{ ...MUTED, ...ONE_LINE, flex: "1 1 0%" }}>{what}</span>
      )}
      {chips}
      <span style={{ marginLeft: "auto", ...ROW, flexWrap: "nowrap", flexShrink: 0 }}>{actions}</span>
      {overlay}
    </div>
  );
}

/** What the pinned documents are, read once: how many of them were deleted since — or that it could not be told. */
type PinnedState = { missing: number } | "unread" | null;

function usePinnedState(canvas: Canvas): PinnedState {
  const [state, setState] = useState<PinnedState>(null);
  const ids = (canvas.doc_ids ?? []).join("\u0000");
  useEffect(() => {
    if (!ids) { setState(null); return; }
    let alive = true;
    const want = ids.split("\u0000").length;
    getCanvasDocuments(canvas.id)
      // The read answers one entry per pinned id, deleted or not; fewer means it was not read.
      .then(d => { if (alive) setState(d.length < want ? "unread" : { missing: d.filter(x => x.missing).length }); })
      .catch(() => { if (alive) setState("unread"); });
    return () => { alive = false; };
  }, [canvas.id, ids]);
  return state;
}

function HeadChips({ canvas, connection, gone, pinned }: {
  canvas: Canvas; connection: Connection | undefined; gone: boolean; pinned: PinnedState;
}) {
  const docs = canvas.doc_ids?.length ?? 0;
  const giveWay: CSSProperties = { display: "inline-flex", flexShrink: 3, minWidth: 56, overflow: "hidden" };
  return (
    <>
      {gone ? (
        <Chip tone="amber" testId="canvas-connection-gone" title="This workspace no longer has the connection this canvas reads">
          connection gone
        </Chip>
      ) : connection && (
        <span data-testid="canvas-connection" title={`${connection.name} · ${connectionKind(connection)}`} style={giveWay}>
          <Chip>{connection.name}</Chip>
        </span>
      )}
      <span title={tablesTitle(canvas)} style={{ display: "inline-flex", flexShrink: 0 }}><Chip>{scopeWords(canvas)}</Chip></span>
      {docs > 0 && (pinned !== null && pinned !== "unread" && pinned.missing > 0 ? (
        <Chip tone="amber" testId="canvas-docs-missing" title="A pinned document was deleted — unpin it in Settings">
          {`${countNoun(docs, "document")} pinned · ${formatCount(pinned.missing)} deleted`}
        </Chip>
      ) : (
        <Chip testId="canvas-docs" title={pinned === "unread"
          ? "Could not check that they still exist"
          : "Always in reach for work done here; the rest of the documents stay searchable"}>
          {`${countNoun(docs, "document")} pinned${pinned === "unread" ? " · not checked" : ""}`}
        </Chip>
      ))}
      {canvas.is_legacy && <Chip title="Made automatically from a connection, not by a person">auto-generated</Chip>}
    </>
  );
}

// ── The landing — what the empty conversation opens on ────────────────────────────────────────────────────────────

/** The question it invites and the two ways to answer — the name, the description and the scope are in the header. */
function CanvasLanding({ canvas, connection, gone }: { canvas: Canvas; connection: Connection | undefined; gone: boolean }) {
  const tables = tablesOf(canvas);
  const about = gone ? "this canvas"
    : tables.length === 0 ? (connection?.name ?? "this connection")
    : tables.length === 1 ? tables[0]
    : `these ${formatCount(tables.length)} tables`;
  return (
    <div data-testid="canvas-landing" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="aug-fs-h1" title={tablesTitle(canvas)} style={{ color: "var(--t1)", fontWeight: 600 }}>
        What do you want to know about {about}?
      </div>
      <div style={{ ...ROW, gap: 6 }}>
        <Chip title="One query and a straight answer">Quick · one query</Chip>
        <Chip title="Several steps that look for what moved and why">Agent · a deep analysis</Chip>
      </div>
    </div>
  );
}

// ── History ───────────────────────────────────────────────────────────────────────────────────────────────────────

function CanvasHistory({ canvasId, onOpen }: {
  canvasId: string;
  onOpen: (id: string, kind: RunKind) => void;
}) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  // A failed read used to read as "No deep analyses yet in this Data Canvas".
  const [failed, setFailed] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [removing, setRemoving] = useState<string | null>(null);
  const [removeFailed, setRemoveFailed] = useState(false);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [now] = useState(() => Date.now());

  useEffect(() => {
    setLoading(true);
    getCanvasHistory(canvasId, HISTORY_LIMIT)
      .then(list => { setItems(list); setFailed(null); })
      .catch(e => { setItems([]); setFailed(e instanceof Error ? e.message : String(e)); })
      .finally(() => setLoading(false));
  }, [canvasId, reload]);

  async function handleRemove(id: string) {
    setRemoving(id);
    setRemoveFailed(false);
    const prev = items;
    setItems(list => list.filter(it => it.id !== id));  // optimistic
    try {
      await deleteInvestigation(id);
    } catch {
      setItems(prev);  // restore on failure, and say so
      setRemoveFailed(true);
    } finally {
      setRemoving(null);
    }
  }

  const asked = useMemo(() => foldHistory(items), [items]);
  const meta = items.length > 0 && (
    <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }} data-testid="canvas-history-meta">
      {items.length >= HISTORY_LIMIT ? `the latest ${formatCount(items.length)} runs` : countNoun(items.length, "run")}
      {asked.length < items.length ? ` · ${countNoun(asked.length, "question")}` : ""}
    </span>
  );
  const scope = (
    <Chip testId="canvas-history-scope"
      title="Runs on other canvases, and deep analyses that did not finish, are listed under Agent runs">
      this canvas · finished runs
    </Chip>
  );

  return (
    <Page testId="canvas-history">
      <Card label="History" right={<>{meta}{scope}</>} testId="canvas-history-card">
        {removeFailed && (
          <div role="alert" className="aug-fs-sm" style={{ color: "var(--t2)", marginBottom: 6 }}>
            Could not remove that run — it is still here.
          </div>
        )}
        {loading ? <Loading what="the history" />
          : failed !== null ? <ReadFailed what="this canvas's history" error={failed} onRetry={() => setReload(n => n + 1)} />
          : asked.length === 0 ? <Empty>Nothing asked on this canvas yet.</Empty>
          : asked.map((q, i) => (
            <AskedRow key={q.key} q={q} first={i === 0} now={now} removing={removing} open={open.has(q.group)}
              onToggle={() => setOpen(s => { const n = new Set(s); if (n.has(q.group)) n.delete(q.group); else n.add(q.group); return n; })}
              onOpen={run => onOpen(run.id, q.kind)}
              onRemove={handleRemove} />
          ))}
      </Card>
    </Page>
  );
}

/** One question: its words, its kind, how many times it was asked and when last — the newest run opens; each run,
 *  with its own Open and Remove, behind Details. */
function AskedRow({ q, first, now, removing, open, onToggle, onOpen, onRemove }: {
  q: AskedQuestion; first: boolean; now: number; removing: string | null; open: boolean;
  onToggle: () => void; onOpen: (run: HistoryItem) => void; onRemove: (id: string) => void;
}) {
  const state = runStateWord(q.latest.status);
  const many = q.runs.length > 1;
  return (
    <div data-testid="canvas-history-row" style={{ ...(first ? {} : RULE), padding: "7px 2px",
      opacity: removing === q.latest.id && !many ? 0.4 : 1 }}>
      <div className="group/run" onClick={() => onOpen(q.latest)}
        style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", gap: 12, alignItems: "center", cursor: "pointer" }}>
        <div style={{ ...ROW, flexWrap: "nowrap", minWidth: 0 }}>
          <span className="aug-fs-chrome" title={q.question} style={{ ...ONE_LINE, color: "var(--t1)" }}>{q.question}</span>
          <Chip>{RUN_KIND_WORD[q.kind]}</Chip>
          {many && <Chip testId="canvas-history-count" title={`Asked ${q.runs.length} times — the newest opens`}>{`×${q.runs.length}`}</Chip>}
          {state && <Chip tone={state.tone}>{state.word}</Chip>}
        </div>
        <span className="aug-fs-sm" title={formatTimestamp(q.latest.started_at, "short")}
          style={{ ...MUTED, ...NUM, whiteSpace: "nowrap" }}>{agoWords(q.latest.started_at, now)}</span>
        {many ? (
          <Button variant="ghost" size="xs" aria-expanded={open} onClick={e => { e.stopPropagation(); onToggle(); }}>
            Details <Icon name={open ? "chevu" : "chevd"} size={12} />
          </Button>
        ) : (
          <Button variant="ghost" size="icon-xs" title="Remove from history" aria-label="Remove from history"
            disabled={removing === q.latest.id} className={HIDDEN_UNTIL_HOVER}
            onClick={e => { e.stopPropagation(); onRemove(q.latest.id); }}>
            <Icon name="trash" size={13} />
          </Button>
        )}
      </div>
      {many && open && (
        <div data-testid="canvas-history-runs" style={{ padding: "4px 0 2px 14px" }}>
          {q.runs.map(run => {
            const s = runStateWord(run.status);
            return (
              <div key={run.id} className="group/run aug-fs-sm"
                style={{ ...ROW, flexWrap: "nowrap", padding: "3px 0", opacity: removing === run.id ? 0.4 : 1 }}>
                <span style={{ ...MUTED, ...NUM, whiteSpace: "nowrap" }}>{formatTimestamp(run.started_at, "short")}</span>
                {s && <Chip tone={s.tone}>{s.word}</Chip>}
                <span style={{ marginLeft: "auto", ...ROW, flexWrap: "nowrap" }}>
                  <Button variant="ghost" size="xs" onClick={() => onOpen(run)}>Open</Button>
                  <Button variant="ghost" size="icon-xs" title="Remove from history" aria-label="Remove from history"
                    disabled={removing === run.id} onClick={() => onRemove(run.id)}>
                    <Icon name="trash" size={13} />
                  </Button>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Artifacts ─────────────────────────────────────────────────────────────────────────────────────────────────────

function ArtifactsPanel({ canvasId }: { canvasId: string }) {
  const [items, setItems] = useState<CanvasArtifact[]>([]);
  const [loading, setLoading] = useState(true);
  // A failed read used to read as "No artifacts saved yet".
  const [failed, setFailed] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [removing, setRemoving] = useState<string | null>(null);
  const [removeFailed, setRemoveFailed] = useState(false);

  useEffect(() => {
    setLoading(true);
    getCanvasArtifacts(canvasId)
      .then(list => { setItems(list); setFailed(null); })
      .catch(e => { setItems([]); setFailed(e instanceof Error ? e.message : String(e)); })
      .finally(() => setLoading(false));
  }, [canvasId, reload]);

  async function handleRemove(id: string) {
    setRemoving(id);
    setRemoveFailed(false);
    const prev = items;
    setItems(list => list.filter(it => it.id !== id));
    try { await deleteCanvasArtifact(canvasId, id); }
    catch { setItems(prev); setRemoveFailed(true); }
    finally { setRemoving(null); }
  }

  return (
    <Page testId="canvas-artifacts">
      <Card label="Artifacts" right={items.length ? <span style={NUM}>{formatCount(items.length)}</span> : undefined}
        testId="canvas-artifacts-card">
        {removeFailed && (
          <div role="alert" className="aug-fs-sm" style={{ color: "var(--t2)", marginBottom: 6 }}>
            Could not remove that artifact — it is still here.
          </div>
        )}
        {loading ? <Loading what="the artifacts" />
          : failed !== null ? <ReadFailed what="this canvas's artifacts" error={failed} onRetry={() => setReload(n => n + 1)} />
          : items.length === 0 ? <Empty>Nothing saved on this canvas yet.</Empty>
          : items.map((item, i) => (
            <div key={item.id} data-testid="canvas-artifact-row" className="group/run"
              style={{ ...(i ? RULE : {}), display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", gap: 12,
                alignItems: "center", padding: "7px 2px", opacity: removing === item.id ? 0.4 : 1 }}>
              <div style={{ ...ROW, flexWrap: "nowrap", minWidth: 0 }}>
                <span className="aug-fs-chrome" title={item.description || item.question || item.title}
                  style={{ ...ONE_LINE, color: "var(--t1)" }}>{item.title}</span>
                <Chip>{item.kind}</Chip>
              </div>
              <span className="aug-fs-sm" style={{ ...MUTED, ...NUM, whiteSpace: "nowrap" }}>
                {item.created_at ? dayMonth(item.created_at) : ""}
              </span>
              <Button variant="ghost" size="icon-xs" title="Remove artifact" aria-label={`Remove ${item.title}`}
                disabled={removing === item.id} className={HIDDEN_UNTIL_HOVER} onClick={() => handleRemove(item.id)}>
                <Icon name="trash" size={13} />
              </Button>
            </div>
          ))}
      </Card>
    </Page>
  );
}

// ── Settings: the name, the description, the pinned documents, the versions ─────────────────────────────────────

/** Bind uploaded documents to this canvas.
 *
 *  A canvas scopes DATA — a connection, a schema, a set of tables. This is the prose
 *  that belongs with it: the spec, the policy, last quarter's report. Work done here
 *  is then grounded in both, without anyone having to hope a similarity search
 *  surfaces the right file.
 *
 *  Pinned, not restrictive. Binding a document ADDS it to what is always in reach and
 *  leaves the rest of the corpus searchable — unlike an agent's documents, which fence
 *  it in. The wording below says so, because the two are easy to confuse and the
 *  consequence of guessing wrong is a workspace that quietly sees less than expected. */
function CanvasDocuments({ canvas, onSaved }: {
  canvas: Canvas;
  onSaved: (updated: Canvas) => void;
}) {
  const [pinned, setPinned] = useState<CanvasDocument[]>([]);
  const [all, setAll] = useState<DocumentEntry[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getCanvasDocuments(canvas.id).then(setPinned).catch(() => setPinned([]));
    listDocuments().then(setAll).catch(() => setAll([]));
  }, [canvas.id]);

  const setBinding = async (docIds: string[]) => {
    setBusy(true);
    try {
      onSaved(await updateCanvas(canvas.id, { doc_ids: docIds }));
      setPinned(await getCanvasDocuments(canvas.id));
    } catch {
      /* the popover stays open; the previous binding is still what is shown */
    } finally {
      setBusy(false);
    }
  };

  const pinnedIds = pinned.map(d => d.doc_id);
  const unpinned = all.filter(d => !pinnedIds.includes(d.doc_id));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <Label right={pinned.length ? <span style={NUM}>{formatCount(pinned.length)}</span> : undefined}>Pinned documents</Label>

      {pinned.length === 0 && (
        <Empty>None pinned · a pinned document is always in reach here; the rest stay searchable.</Empty>
      )}

      {pinned.map(doc => (
        <div key={doc.doc_id} className="aug-fs-sm" style={{ ...ROW, flexWrap: "nowrap" }}>
          {/* A binding whose document was deleted is SHOWN, not hidden — otherwise a
              workspace loses context with nothing to see. */}
          <span style={{ ...ONE_LINE, flex: 1, color: doc.missing ? "var(--t3)" : "var(--t2)" }}>
            {doc.missing ? doc.doc_id : (doc.title || doc.filename)}
          </span>
          {doc.missing && <Chip tone="amber">deleted</Chip>}
          <Button variant="ghost" size="xs" type="button" disabled={busy}
            onClick={() => setBinding(pinnedIds.filter(id => id !== doc.doc_id))}>
            Unpin
          </Button>
        </div>
      ))}

      {unpinned.length > 0 && (
        <SelectField value="" disabled={busy}
          onChange={e => { if (e.target.value) setBinding([...pinnedIds, e.target.value]); }}>
          <option value="">Pin a document…</option>
          {unpinned.map(doc => (
            <option key={doc.doc_id} value={doc.doc_id}>{doc.title || doc.filename}</option>
          ))}
        </SelectField>
      )}

      {all.length === 0 && <Empty>No documents uploaded yet — add them in Documents.</Empty>}
    </div>
  );
}

function SettingsPopover({ canvas, onClose, onSaved }: {
  canvas: Canvas;
  onClose: () => void;
  onSaved: (updated: Canvas) => void;
}) {
  const [name, setName] = useState(canvas.name);
  const [desc, setDesc] = useState(canvas.description);
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setSaveFailed(null);
    try {
      const updated = await updateCanvas(canvas.id, { name, description: desc });
      onSaved(updated);
      onClose();
    } catch (e) {
      setSaveFailed(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const field: CSSProperties = { display: "flex", flexDirection: "column", gap: 4, color: "var(--t3)" };
  return (
    <>
      <div className="fixed inset-0 z-50" onClick={onClose} />
      <div data-testid="canvas-settings" onClick={e => e.stopPropagation()} style={{
        position: "absolute", top: "calc(100% + 4px)", right: 12, zIndex: 60,
        background: "var(--bg-2)", border: "1px solid var(--b2)", borderRadius: "var(--r3)", padding: "12px 14px",
        width: 300, display: "flex", flexDirection: "column", gap: 10, boxShadow: "var(--shadow-lg)",
      }}>
        <Label>Settings</Label>
        <label className="aug-fs-xs" style={field}>
          Name
          <Input value={name} onChange={e => setName(e.target.value)} />
        </label>
        <label className="aug-fs-xs" style={field}>
          Description
          <Textarea value={desc} onChange={e => setDesc(e.target.value)} rows={2} style={{ resize: "none" }} />
        </label>

        {saveFailed && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>Not saved — {saveFailed}</div>}

        <div style={{ ...ROW, justifyContent: "flex-end" }}>
          <Button onClick={onClose} variant="ghost" size="xs">Cancel</Button>
          <Button onClick={save} disabled={saving || !name.trim()} variant="default" size="xs">
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>

        {/* Pinned documents save on change rather than on Save, because they are a
            binding rather than a field: Cancel restores the name you were editing,
            and an unpin that silently came back would be worse than no Cancel at all. */}
        <CanvasDocuments canvas={canvas} onSaved={onSaved} />

        {/* The canvas's revision history, publish/revert, and the freeze pin, on the
            artifact's own settings surface. Renders nothing until the canvas has a revision. */}
        <LifecyclePanel kind="canvas" naturalKey={`canvas:${canvas.id}`}
                        connectionId={canvas.scopes[0]?.connection_id} />
      </div>
    </>
  );
}

// ── CanvasWorkspace ───────────────────────────────────────────────────────────────────────────────────────────────

interface Props {
  canvas: Canvas;
  connections: Connection[];
  /** Every connection the install has — for the connection's chip and "connection gone"; Configure keeps this
   *  workspace's own. */
  allConnections?: Connection[];
  onClose: () => void;
  onCanvasUpdate: (canvas: Canvas) => void;
  initialOpenInvId?: string | null;
  initialRestoreSessionId?: string | null;
  /** Open the global document corpus (Intelligence → Documents). */
  onOpenDocuments?: () => void;
}

const VIEWS: { id: WsTab; label: string }[] = [
  { id: "chat", label: "Chat" }, { id: "history", label: "History" }, { id: "artifacts", label: "Artifacts" },
];

export function CanvasWorkspace({ canvas, connections, allConnections, onClose, onCanvasUpdate, initialOpenInvId, initialRestoreSessionId, onOpenDocuments }: Props) {
  // A canvas reading another workspace's connection still has it: the chip and "connection gone" read every connection
  // the install has (2026-10-12, judged against this workspace's alone two live canvases read "gone").
  const known = allConnections?.length ? allConnections : connections;
  const [wsTab, setWsTab] = useState<WsTab>("chat");
  const [chatKey, setChatKey] = useState(0);
  const [openInvId, setOpenInvId] = useState<string | null>(null);
  const [restoreSessionId, setRestoreSessionId] = useState<string | null>(null);
  // Seed question for ChatPanel, set by the canvas-scoped Intelligence actions that start a deep analysis.
  // ChatPanel only auto-submits on a fresh mount, so every path that bumps chatKey for
  // another reason must clear the seed or the stale question would re-submit.
  const [chatInitialQuestion, setChatInitialQuestion] = useState<string | undefined>(undefined);
  const [chatInitialMode, setChatInitialMode] = useState<"ask" | "investigate" | undefined>(undefined);
  const [showSettings, setShowSettings] = useState(false);
  const [showConfigure, setShowConfigure] = useState(false);

  const connectionId = canvas.scopes[0]?.connection_id ?? "";
  const connection = known.find(c => c.id === connectionId);
  const gone = connectionGone(canvas, known);
  const pinned = usePinnedState(canvas);

  // When canvas changes, reset to chat tab, but honour initial props
  useEffect(() => {
    setChatInitialQuestion(undefined);
    setChatInitialMode(undefined);
    if (initialOpenInvId) {
      setWsTab("history");
      setOpenInvId(initialOpenInvId);
      setRestoreSessionId(null);
      setChatKey(k => k + 1);
    } else if (initialRestoreSessionId) {
      setWsTab("chat");
      setRestoreSessionId(initialRestoreSessionId);
      setOpenInvId(null);
      setChatKey(k => k + 1);
    } else {
      setWsTab("chat");
      setChatKey(k => k + 1);
      setOpenInvId(null);
      setRestoreSessionId(null);
    }
  }, [canvas.id, initialOpenInvId, initialRestoreSessionId]);

  // History line-item → navigate.  Deep analyses open the detail report in the
  // History tab; chat sessions restore the conversation in the Chat tab (passing
  // a chat id to the deep-analysis detail panel would just render blank — the bug
  // behind "choosing a line item does not take me there").
  const handleHistoryOpen = (id: string, kind: RunKind) => {
    if (kind === "chat") {
      setOpenInvId(null);
      setRestoreSessionId(id);
      setChatInitialQuestion(undefined);
      setChatInitialMode(undefined);
      setWsTab("chat");
      setChatKey(k => k + 1);
    } else {
      setRestoreSessionId(null);
      setOpenInvId(id);
      setWsTab("history");
    }
  };

  const showView = (id: WsTab) => {
    setWsTab(id);
    if (id !== "artifacts") setOpenInvId(null);
  };

  const newConversation = () => {
    setWsTab("chat"); setChatKey(k => k + 1); setOpenInvId(null); setRestoreSessionId(null);
    setChatInitialQuestion(undefined); setChatInitialMode(undefined);
  };

  const tools: ToolItem[] = [
    { label: "Configure…", title: "The tables it reads, its instructions and metrics, and its documents",
      onSelect: () => { setShowConfigure(true); setShowSettings(false); }, testId: "canvas-tool-configure" },
    { label: "Settings…", title: "Its name and description, pinned documents and versions",
      onSelect: () => { setShowSettings(true); setShowConfigure(false); }, testId: "canvas-tool-settings" },
  ];

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-canvas)" }}>

      <CanvasHead name={canvas.name} what={canvas.description || undefined} onBack={onClose}
        chips={<HeadChips canvas={canvas} connection={connection} gone={gone} pinned={pinned} />}
        actions={<>
          {/* The three views. A fresh conversation is the "+" beside them — a distinct create action, not a second
              "go to chat". */}
          <span data-testid="canvas-tabs" style={{ ...ROW, flexWrap: "nowrap", gap: 2, flexShrink: 0 }}>
            {VIEWS.map(v => (
              <Button key={v.id} variant={wsTab === v.id ? "secondary" : "ghost"} size="xs" aria-pressed={wsTab === v.id}
                onClick={() => showView(v.id)}>
                {v.label}
              </Button>
            ))}
          </span>
          <Button onClick={newConversation} variant="ghost" size="icon-xs" title="New conversation" aria-label="New conversation">
            <Icon name="plus" size={15} />
          </Button>
          <ToolsMenu items={tools} testId="canvas-tools" />
        </>}
        overlay={showSettings && (
          <SettingsPopover
            canvas={canvas}
            onClose={() => setShowSettings(false)}
            onSaved={updated => { onCanvasUpdate(updated); setShowSettings(false); }}
          />
        )} />

      {/* ── Content ── */}
      {/*
        IMPORTANT: all three panels are always mounted — never conditionally rendered.
        Switching tabs uses CSS display:none so React keeps each panel's state alive.
        Unmounting ChatPanel mid-analysis kills its SSE stream and message list;
        the user comes back to a blank window even though the backend finished fine.
      */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>

        {/* Chat — always mounted, hidden when not active */}
        <div style={{
          display: wsTab === "chat" ? "flex" : "none",
          flex: 1, flexDirection: "column", overflow: "hidden",
        }}>
          <ChatPanel
            key={chatKey}
            connectionId={connectionId}
            canvasId={canvas.id}
            restoreSessionId={restoreSessionId}
            initialQuestion={chatInitialQuestion}
            initialMode={chatInitialMode}
            capabilities={<CanvasLanding canvas={canvas} connection={connection} gone={gone} />}
          />
        </div>

        {/* History — always mounted, hidden when not active */}
        <div style={{
          display: wsTab === "history" ? "flex" : "none",
          flex: 1, flexDirection: "column", overflow: "hidden",
        }}>
          {openInvId
            ? (
              // Back folds into HistoryDetailPanel's Report/Evidence tab bar (onBack), so viewing a run is 2 chrome
              // rows, not 4. Flex column (not a bare overflow block) so HistoryDetailPanel's flex:1 +
              // position:absolute report area gets a resolved height (without it the report collapses to 0px).
              <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
                <HistoryDetailPanel
                  invId={openInvId}
                  onBack={() => setOpenInvId(null)}
                  onContinue={() => {
                    setOpenInvId(null);
                    setChatInitialQuestion(undefined);
                    setChatInitialMode(undefined);
                    setWsTab("chat");
                    setChatKey(k => k + 1);
                  }}
                />
              </div>
            )
            : <CanvasHistory canvasId={canvas.id} onOpen={handleHistoryOpen} />
          }
        </div>

        {/* Artifacts — always mounted, hidden when not active */}
        <div style={{
          display: wsTab === "artifacts" ? "flex" : "none",
          flex: 1, flexDirection: "column", overflow: "hidden",
        }}>
          <ArtifactsPanel canvasId={canvas.id} />
        </div>
      </div>

      {/* Configure slide-over */}
      {showConfigure && (
        <ConfigurePanel
          onOpenDocuments={onOpenDocuments}
          canvas={canvas}
          connections={connections}
          onClose={() => setShowConfigure(false)}
          onCanvasUpdate={onCanvasUpdate}
        />
      )}
    </div>
  );
}
