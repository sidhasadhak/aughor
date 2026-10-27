"use client";

/**
 * The chat beside a sheet (SH-4; mockup screens 3 to 5).
 *
 * A question is answered by a query on the Sheets connection, through the one ask door, with the sheet and the view on
 * screen handed to it server-side — the table, its columns, and the view's own filter and count — so "how many of
 * these" counts the rows the grid shows. The line under the header says what the chat sees.
 *
 * A change asked for — "flag the ones that still need following up" — comes back as ONE proposal card: each change
 * checked and counted by the platform, ticked by default, applied all or in part by the person, recorded as proposed
 * by the assistant and applied by them. Which of the two something is, is read from its first words; the other way is
 * one click under the answer, so a misreading costs a click and never a change.
 *
 * A file dropped here becomes one proposal for a new sheet (screen 5): its name, its kinds and a few views. Nothing is
 * made until the person creates it, and undo removes it whole.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Chip, Dot, MUTED, NUM } from "@/components/clarity/kit";
import { PartsMessage } from "@/components/chat/PartsMessage";
import { RULE_COLOR } from "@/components/sheets/SheetGrid";
import { PANEL, PanelHead } from "@/components/sheets/SheetRecord";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { newSessionId, projectThread, type SheetRowsRef } from "@/lib/chatTurn";
import { formatCount } from "@/lib/format";
import {
  KIND_LABEL, RULE_TONES, applyProposal, asksForAChange, filterWords, propose, proposeNewSheet, readGrounding, rowsWord,
  stageFile, undo, type Grounding, type Proposal, type ProposeOutcome, type RuleTone, type Sheet,
} from "@/lib/sheets";
import { useAughorChat } from "@/lib/useAughorChat";

type Entry =
  | { id: string; type: "ask"; words: string }
  | { id: string; type: "propose"; words: string; outcome: ProposeOutcome | null; error?: string; applied?: number[];
      appliedSheet?: string };

let seq = 0;
const nextId = () => `e${++seq}`;

export function SheetChat({ sheet, viewId, viewRows, onClose, onApplied, onOpenSheet, onAsk, onOpenView, onShowRows,
  onKeepRows }: {
  sheet: Sheet; viewId: string; viewRows: number | null; onClose: () => void; onApplied: () => void;
  onOpenSheet: (id: string) => void; onAsk?: (q: string) => void; onOpenView: (name: string) => void;
  /** The rows an answer is about, on the grid as the person's own until they keep them. */
  onShowRows: (r: SheetRowsRef) => void;
  /** The same rows kept as a view of the answer's name — true when it was kept. */
  onKeepRows: (r: SheetRowsRef) => Promise<boolean>;
}) {
  const [sessionId] = useState(() => newSessionId());
  const focus = useMemo(() => ({ kind: "sheet", id: viewId ? `${sheet.id}:${viewId}` : sheet.id }), [sheet.id, viewId]);
  const { messages, sendMessage, status, error } = useAughorChat({
    connectionId: "sheets", sessionId,
    // quick depth: an answer on the sheet, never a deep analysis from here; `focus` is the sheet on screen, read by
    // the server from its own stores — nothing about the sheet is sent from this panel.
    body: { depth: "quick", surface: "sheet", focus },
  });
  const streaming = status === "submitted" || status === "streaming";
  const turns = useMemo(() => projectThread(messages, {
    streaming, transportError: status === "error" ? (error?.message ?? "The turn failed.") : null,
  }), [messages, streaming, status, error]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [draft, setDraft] = useState("");
  const [grounding, setGrounding] = useState<Grounding | null>(null);
  const [dropping, setDropping] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    readGrounding(sheet.id, viewId).then(setGrounding).catch(() => setGrounding(null));
  }, [sheet.id, viewId, viewRows]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 240) el.scrollTop = el.scrollHeight;
  }, [entries, turns.length, streaming]);

  const ask = useCallback((words: string) => {
    if (streaming) return;
    setEntries(e => [...e, { id: nextId(), type: "ask", words }]);
    void sendMessage({ text: words, metadata: { mode: "ask" } });
  }, [sendMessage, streaming]);

  const proposeChange = useCallback((words: string) => {
    const id = nextId();
    setEntries(e => [...e, { id, type: "propose", words, outcome: null }]);
    propose(sheet.id, words)
      .then(outcome => setEntries(e => e.map(x => (x.id === id ? { ...x, outcome } as Entry : x))))
      .catch(err => setEntries(e => e.map(x => (x.id === id ? { ...x, error: err instanceof Error ? err.message : String(err) } as Entry : x))));
  }, [sheet.id]);

  const dropped = useCallback((file: File, words: string) => {
    const id = nextId();
    setEntries(e => [...e, { id, type: "propose", words: `${file.name} — ${words || "make this a sheet"}`, outcome: null }]);
    stageFile(file).then(st => proposeNewSheet(st.token, words))
      .then(outcome => setEntries(e => e.map(x => (x.id === id ? { ...x, outcome } as Entry : x))))
      .catch(err => setEntries(e => e.map(x => (x.id === id ? { ...x, error: err instanceof Error ? err.message : String(err) } as Entry : x))));
  }, []);

  const send = () => {
    const words = draft.trim();
    if (!words) return;
    setDraft("");
    if (asksForAChange(words)) proposeChange(words); else ask(words);
  };

  const applied = (entryId: string, picks: number[], p: Proposal, sheetId: string) => {
    setEntries(e => e.map(x => (x.id === entryId ? { ...x, applied: picks, appliedSheet: sheetId } as Entry : x)));
    if (p.new_sheet) { onOpenSheet(sheetId); return; }
    onApplied();
    const view = picks.map(i => p.changes[i]).find(c => c.type === "view");
    if (view?.name) onOpenView(String(view.name));
  };

  let askIndex = -1;
  return (
    <aside aria-label="Ask about this sheet" style={PANEL}
      onDragOver={e => { e.preventDefault(); setDropping(true); }} onDragLeave={() => setDropping(false)}
      onDrop={e => {
        e.preventDefault();
        setDropping(false);
        const f = e.dataTransfer.files?.[0];
        if (f) { dropped(f, draft.trim()); setDraft(""); }
      }}>
      <PanelHead title="Ask about this sheet" chip={grounding?.view ? `${sheet.name} · ${grounding.view.name}` : sheet.name}
        onClose={onClose} />
      {grounding?.found && (
        <div className="aug-fs-xs" title={grounding.view?.where ? `WHERE ${grounding.view.where}` : undefined}
          style={{ ...MUTED, ...NUM, padding: "6px 14px", borderBottom: "1px solid var(--b0)" }}>
          The chat reads <span className="aug-mono">{grounding.table}</span>
          {grounding.view ? ` · the view ${grounding.view.name}: ${formatCount(grounding.view.rows)} rows` : ` · ${formatCount(grounding.rows ?? 0)} rows`}
        </div>
      )}
      <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "12px 14px",
        outline: dropping ? "2px dashed var(--blue3)" : undefined, outlineOffset: -6 }}>
        {entries.length === 0 ? (
          <div className="aug-fs-xs" style={{ ...MUTED, lineHeight: 1.6 }}>
            Ask about this sheet — answers are queries on it, each with its receipt — or ask for a change: a view, a
            computed column, a column to tick, a link to another sheet. A change is proposed and counted first; nothing
            changes until you apply it. Drop a file here to make a new sheet of it.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {entries.map(en => {
              if (en.type === "ask") {
                askIndex += 1;
                const t = turns[askIndex];
                return (
                  <div key={en.id}>
                    {t ? (
                      <PartsMessage turn={t.turn} message={t.assistantMsg} connectionId="sheets"
                        onFollowUp={(q: string) => ask(q)} onDeeper={(q: string) => onAsk?.(q)} />
                    ) : <div className="aug-fs-sm">{en.words}</div>}
                    {t?.turn.sheetRows.filter(r => r.sheet === sheet.id).map((r, i) => (
                      <RowsCard key={`${r.about}-${i}`} rows={r} sheet={sheet} onShow={() => onShowRows(r)}
                        onKeep={() => onKeepRows(r)} />
                    ))}
                    <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 4 }}>
                      Answered as a question ·{" "}
                      <Button variant="link" size="xs" onClick={() => proposeChange(en.words)}>propose a change instead</Button>
                    </div>
                  </div>
                );
              }
              return (
                <div key={en.id} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <div className="aug-fs-sm" style={{ alignSelf: "flex-end", background: "var(--bg-3)", padding: "6px 10px",
                    borderRadius: "var(--r3)", maxWidth: "90%" }}>{en.words}</div>
                  {en.error ? <span role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>{en.error}</span>
                    : !en.outcome ? <span className="aug-fs-xs" style={MUTED}>Proposing — every change is checked and counted first…</span>
                      : en.outcome.staged ? (
                        <ProposalCard proposal={en.outcome.proposal} applied={en.applied} appliedSheet={en.appliedSheet}
                          onApplied={(picks, sheetId) => applied(en.id, picks, (en.outcome as { proposal: Proposal }).proposal, sheetId)}
                          onUndone={() => { onApplied(); setEntries(e => e.map(x => (x.id === en.id ? { ...x, applied: undefined } as Entry : x))); }} />
                      ) : (
                        <div className="aug-fs-sm" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          <span className="aug-fs-xs" style={MUTED}>Nothing was proposed:</span>
                          {en.outcome.sentences.map(s => <span key={s}>{s}</span>)}
                        </div>
                      )}
                  {!en.words.includes(" — ") && (
                    <div className="aug-fs-xs" style={MUTED}>
                      Proposed as a change ·{" "}
                      <Button variant="link" size="xs" onClick={() => ask(en.words)}>ask it as a question instead</Button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div style={{ flex: "0 0 auto", padding: "10px 14px", borderTop: "1px solid var(--b1)", display: "flex", gap: 6 }}>
        <input ref={fileRef} type="file" hidden accept=".csv,.tsv,.parquet,.json,.xlsx"
          onChange={e => { const f = e.target.files?.[0]; if (f) { dropped(f, draft.trim()); setDraft(""); } e.target.value = ""; }} />
        <Button variant="ghost" size="icon-sm" aria-label="Make a sheet from a file" title="Make a sheet from a file"
          onClick={() => fileRef.current?.click()}><Icon name="attach" /></Button>
        <Input value={draft} onChange={e => setDraft(e.target.value)} disabled={streaming}
          placeholder="Ask about this sheet, drop a file, or ask for a change…" aria-label="A question, or a change to make"
          style={{ flex: 1 }} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        <Button onClick={send} disabled={!draft.trim() || streaming} aria-label="Send"><Icon name="send" /></Button>
      </div>
    </aside>
  );
}

/** The rows an answer beside the sheet is about (SH-4): how many of what whole, the filter in the grid's words, and the
 *  two things to do with them — see them in the grid, or keep them as a view. Nothing changes until one is clicked. */
export function RowsCard({ rows: r, sheet, onShow, onKeep }: {
  rows: SheetRowsRef; sheet: Sheet; onShow: () => void; onKeep: () => Promise<boolean>;
}) {
  const [did, setDid] = useState<"" | "shown" | "kept">("");
  const [busy, setBusy] = useState(false);
  const said = filterWords(r.conditions, sheet.columns, sheet.rules) || r.said;
  return (
    <div style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", background: "var(--bg-2)", padding: "10px 12px",
      display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <Icon name="table" size={14} />
        <span className="aug-fs-sm" style={{ fontWeight: 600, ...NUM }}>
          {rowsWord(r.rows, sheet.name)} <span style={{ ...MUTED, fontWeight: 400 }}>of {formatCount(r.of)}
            {r.withinView ? " in this view" : ""}{r.share !== null && r.rows ? ` · ${r.share}%` : ""}</span>
        </span>
      </div>
      <span className="aug-fs-xs" style={MUTED}>{said}</span>
      {r.rows > 0 && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <Button size="xs" variant={did === "shown" ? "secondary" : "default"} onClick={() => { onShow(); setDid("shown"); }}>
            {did === "shown" ? "Shown in the grid" : "Show in the grid"}
          </Button>
          <Button size="xs" variant="outline" disabled={busy || did === "kept"} onClick={() => {
            setBusy(true);
            void onKeep().then(ok => { if (ok) setDid("kept"); }).finally(() => setBusy(false));
          }}>{did === "kept" ? `Kept as the view ${r.about}` : `Keep as a view · ${r.about}`}</Button>
        </div>
      )}
    </div>
  );
}

export function ProposalCard({ proposal, applied, appliedSheet, onApplied, onUndone }: {
  proposal: Proposal; applied?: number[]; appliedSheet?: string;
  onApplied: (picks: number[], sheetId: string) => void; onUndone: () => void;
}) {
  const [picks, setPicks] = useState<Set<number>>(() => new Set(proposal.changes.map((_, i) => i)));
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const done = applied !== undefined;
  const apply = async () => {
    setBusy(true);
    setRefused(null);
    try {
      const out = await applyProposal(proposal.id, [...picks].sort((a, b) => a - b));
      onApplied(out.applied, out.sheet);
    } catch (e) {
      setRefused(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const takeBack = async () => {
    if (!appliedSheet) return;
    setBusy(true);
    try { await undo(appliedSheet, !!proposal.new_sheet); onUndone(); } catch (e) { setRefused(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const n = picks.size;
  return (
    <div style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", background: "var(--bg-2)", padding: "10px 12px",
      display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="aug-fs-sm" style={{ fontWeight: 600 }}>
          {proposal.new_sheet ? `A new sheet · ${proposal.name}` : `${proposal.changes.length} change${proposal.changes.length === 1 ? "" : "s"}`}
        </span>
        <span style={{ marginLeft: "auto" }}>
          {done ? <Chip tone="up">Applied by you</Chip> : <Chip>nothing {proposal.new_sheet ? "created" : "applied"} yet</Chip>}
        </span>
      </div>
      {proposal.new_sheet && (
        <div className="aug-fs-xs" style={{ ...MUTED, display: "flex", flexDirection: "column", gap: 2 }}>
          <span>{proposal.file} · {formatCount(proposal.rows ?? 0)} rows · {proposal.columns?.length ?? 0} columns, read as written:</span>
          <span>{(proposal.columns ?? []).map(c => `${c.name} ${KIND_LABEL[c.kind]}`).join(" · ")}</span>
        </div>
      )}
      {proposal.changes.map((c, i) => (
        <label key={`${c.type}-${c.said}`} className="aug-fs-sm" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
          <Checkbox checked={done ? applied!.includes(i) : picks.has(i)} disabled={done}
            onChange={() => { const p = new Set(picks); if (p.has(i)) p.delete(i); else p.add(i); setPicks(p); }}
            aria-label={c.said} />
          <span>
            {c.said}
            {c.type === "computed_column" && <span className="aug-fs-xs" style={{ ...MUTED, display: "block" }}>computed, no model</span>}
            {c.type === "rule" && (
              <span className="aug-fs-xs" style={{ ...MUTED, display: "flex", gap: 5, alignItems: "baseline" }}>
                <Dot color={RULE_COLOR[RULE_TONES.includes(c.tone as RuleTone) ? c.tone as RuleTone : "amber"]} />
                marks the rows where {String(c.where ?? "")}
              </span>
            )}
          </span>
        </label>
      ))}
      {refused && <span role="alert" className="aug-fs-xs" style={{ color: "var(--red4)" }}>{refused}</span>}
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {done ? (
          <>
            <Button variant="outline" size="xs" onClick={() => void takeBack()} disabled={busy}>
              {proposal.new_sheet ? "Undo — remove the sheet" : "Undo all"}
            </Button>
            <span className="aug-fs-xs" style={MUTED}>Each change is in the sheet&apos;s history.</span>
          </>
        ) : (
          <>
            <Button size="xs" onClick={() => void apply()} disabled={busy || (n === 0 && !proposal.new_sheet)}>
              {proposal.new_sheet ? "Create sheet" : `Apply ${n} change${n === 1 ? "" : "s"}`}
            </Button>
            <span className="aug-fs-xs" style={MUTED}>{proposal.new_sheet ? "Undo removes it whole." : "Untick what you do not want."}</span>
          </>
        )}
      </div>
    </div>
  );
}

/** The home's "In the chat": drop a file, say what it is for, and read the one proposal it becomes. */
export function NewSheetChat({ onClose, onMade }: { onClose: () => void; onMade: (sheetId: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [words, setWords] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<ProposeOutcome | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const go = async () => {
    if (!file) return;
    setBusy(true);
    setRefused(null);
    try {
      const st = await stageFile(file);
      setOutcome(await proposeNewSheet(st.token, words));
    } catch (e) {
      setRefused(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <aside aria-label="Make a sheet in the chat" style={PANEL}
      onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) setFile(f); }}>
      <PanelHead title="Chat" chip="Workspace" onClose={onClose} />
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
        <div className="aug-fs-xs" style={{ ...MUTED, lineHeight: 1.6 }}>
          Drop a file and say what it is for. It comes back as one proposal — the sheet&apos;s name, the kinds read from
          the file, and a few views — and nothing is made until you create it.
        </div>
        <input ref={fileRef} type="file" hidden accept=".csv,.tsv,.parquet,.json,.xlsx"
          onChange={e => setFile(e.target.files?.[0] ?? null)} />
        <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()} style={{ alignSelf: "flex-start" }}>
          <Icon name="attach" /> {file ? file.name : "Choose or drop a file"}
        </Button>
        <Input value={words} onChange={e => setWords(e.target.value)} aria-label="What the sheet is for"
          placeholder="What is it for? — e.g. a sheet I can follow up complaints from" />
        <Button size="sm" onClick={() => void go()} disabled={!file || busy} style={{ alignSelf: "flex-start" }}>
          {busy ? "Reading the file…" : "Propose a sheet"}
        </Button>
        {refused && <span role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>{refused}</span>}
        {outcome && (outcome.staged ? (
          <ProposalCard proposal={outcome.proposal} onApplied={(_, id) => onMade(id)} onUndone={() => undefined} />
        ) : outcome.sentences.map(s => <span key={s} className="aug-fs-sm">{s}</span>))}
      </div>
    </aside>
  );
}
