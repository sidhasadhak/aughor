"use client";

/**
 * New dashboard ▸ From a file: a file and a sentence (design-mockups/dashboard-from-file.html).
 *
 * The file becomes a sheet, a model drafts cards for what the person asked (`aughor/sheets/dashboard_draft.py`), and they check the
 * draft here before anything is kept. What each card means is said in words read off its statement, never the model's, because a
 * confident label on a wrong definition looks just like one on a right one. What the model chose is asked about, and what could
 * not be made is said. Drafting asks a model once, and the button says so.
 */
import { useMemo, useRef, useState, type DragEvent } from "react";

import { NEEDS_EDGE } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { QueryShaped } from "@/lib/api";
import { draftedFigure } from "@/lib/dashboards/figureText";
import { fmtDate, formatCount, formatFileSize } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { requestTab } from "@/lib/navigate";
import {
  createFromFile, draftSheetDashboard, keepSheetDashboard, stageFile,
  type DraftedCard, type DraftedDashboard, type DraftedFilter, type StagedFile,
} from "@/lib/sheets";

const SCENARIO = "__scenario";
const ADD_ROW = "__add_row";
const filterId = (f: DraftedFilter) => `filter:${f.column}`;

const CARD_STYLE = { background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)" } as const;
const SECTION_LABEL = { color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" } as const;

/** A sheet's name, from the file's: its words, without its extension. */
function nameOf(file: string): string {
  const bare = file.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  return bare ? bare[0].toUpperCase() + bare.slice(1) : "From a file";
}

function ColumnsRead({ staged }: { staged: StagedFile }) {
  const tab = staged.tabs[0];
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="aug-fs-sm" data-testid="from-file-columns" style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr style={{ color: "var(--t3)", textAlign: "left" }}>
          {["Column", "Reads as", "What is in it"].map(h => <th key={h} className="aug-fs-xs" style={{ ...SECTION_LABEL, fontWeight: 400, padding: "0 12px 4px 0", borderBottom: "1px solid var(--b0)" }}>{h}</th>)}
        </tr></thead>
        <tbody>
          {withUniqueKeys(tab.columns, c => c.name).map(([key, c]) => (
            <tr key={key} style={{ height: 30 }}>
              <td style={{ fontFamily: "var(--font-mono)", paddingRight: 12, color: "var(--t2)", borderBottom: "1px solid var(--b0)", whiteSpace: "nowrap" }}>{c.name}</td>
              <td style={{ paddingRight: 12, borderBottom: "1px solid var(--b0)", textTransform: "capitalize", whiteSpace: "nowrap" }}>{c.suggested}</td>
              <td style={{ color: "var(--t2)", borderBottom: "1px solid var(--b0)" }}>
                {c.values.length ? `${formatCount(c.distinct)} values: ${c.values.slice(0, 3).map(v => v[0]).join(", ")}` : c.first ?? "Empty"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What a card would show, small: its figure, its row count, or the shape of its first series. Drawn from the run, never from words. */
function Preview({ shaped }: { shaped: QueryShaped }) {
  if (shaped.as === "figure") {
    return <span className="aug-fs-h1" data-testid="from-file-preview-figure" style={{ fontWeight: 500, fontVariantNumeric: "tabular-nums" }}>{draftedFigure(shaped.value, shaped.format)}</span>;
  }
  if (shaped.as === "table") return <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>{formatCount(shaped.rows.length)}{shaped.more ? "+" : ""} rows</span>;
  const first = shaped.series[0] ?? "";
  const values = shaped.points.filter(p => p.s === first).map(p => p.v ?? 0);
  const most = Math.max(1, ...values);
  const band = 176 / Math.max(1, values.length);
  return (
    <svg width={176} height={34} aria-hidden="true" style={{ display: "block" }}>
      {values.map((v, i) => {
        const h = Math.max(1, (v / most) * 32);
        return <rect key={i} x={i * band} y={34 - h} width={Math.max(2, band - 2)} height={h} rx={1} fill="var(--chart-1)" />;
      })}
    </svg>
  );
}

function FilterPreview({ filter }: { filter: DraftedFilter }) {
  const most = Math.max(1, ...filter.values.map(v => v[1]));
  const rows = filter.values.slice(0, 5);
  return (
    <svg width={176} height={rows.length * 7} aria-hidden="true" style={{ display: "block" }}>
      {rows.map((v, i) => <rect key={v[0]} x={0} y={i * 7} width={Math.max(2, (v[1] / most) * 176)} height={5} rx={1} fill="var(--t3)" />)}
    </svg>
  );
}

function Row({ id, on, onToggle, preview, title, says, sql }: {
  id: string; on: boolean; onToggle: (id: string) => void; preview: React.ReactNode; title: string; says: string; sql?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="from-file-row" data-row={id} style={{ display: "grid", gridTemplateColumns: "20px 188px minmax(0, 1fr) auto", gap: "4px 14px", alignItems: "center",
      padding: "8px 14px", minHeight: 54, borderTop: "1px solid var(--b0)", opacity: on ? 1 : 0.5 }}>
      <Checkbox checked={on} aria-label={`Keep ${title}`} onChange={() => onToggle(id)} />
      <div style={{ minWidth: 0, display: "flex", alignItems: "center" }}>{preview}</div>
      <div style={{ minWidth: 0 }}>
        <div className="aug-fs-ui" style={{ fontWeight: 500 }}>{title}</div>
        <div className="aug-fs-sm" data-testid="from-file-definition" style={{ color: "var(--t2)" }}>{says}</div>
      </div>
      {sql ? <Button size="xs" variant={open ? "secondary" : "ghost"} aria-expanded={open} onClick={() => setOpen(o => !o)}>Query</Button> : <span />}
      {sql && open && (
        <pre className="aug-fs-xs" style={{ gridColumn: "2 / -1", margin: "4px 0 2px", whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "var(--font-mono)", color: "var(--t2)",
          background: "var(--bg-3)", border: "1px solid var(--b0)", borderRadius: "var(--r2)", padding: "8px 10px" }}>{sql}</pre>
      )}
    </div>
  );
}

function Group({ label, chip, children }: { label: string; chip?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="aug-fs-xs" style={{ ...SECTION_LABEL, display: "flex", alignItems: "center", gap: 8, paddingBottom: 6 }}>
        {label}
        {chip && <span className="aug-fs-sm" style={{ textTransform: "none", letterSpacing: 0, padding: "0 6px", borderRadius: "var(--r2)", color: "var(--vio4)", background: "var(--vio1)" }}>{chip}</span>}
      </div>
      <div style={{ ...CARD_STYLE, overflow: "hidden" }}>{children}</div>
    </div>
  );
}

const NO_WORDS = "This query is too involved to say in words. Read it before you keep it.";

function Check({ sheetId, draft, onRedraft, onOver, onKept, busy }: {
  sheetId: string; draft: DraftedDashboard; onRedraft: (change: string) => void; onOver: () => void; busy: boolean;
  onKept: (dashboardId: string, connectionId: string) => void;
}) {
  const [title, setTitle] = useState(draft.title ?? "");
  const [cards, setCards] = useState<DraftedCard[]>(draft.cards);
  const [off, setOff] = useState<Set<string>>(new Set());
  const [answered, setAnswered] = useState<Record<string, string>>({});
  const [change, setChange] = useState("");
  const [keeping, setKeeping] = useState(false);
  const [problem, setProblem] = useState("");
  const toggle = (id: string) => setOff(s => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const on = (id: string) => !off.has(id);

  const figures = cards.filter(c => c.shown.as === "figure" && !c.reads.length);
  const pictures = cards.filter(c => c.shown.as !== "figure" && c.shown.as !== "table" && !c.reads.length);
  const tables = cards.filter(c => c.shown.as === "table" && !c.reads.length);
  const scenarioCards = cards.filter(c => c.reads.length);
  const scenario = draft.scenario;
  const useScenario = !!scenario && on(SCENARIO);

  const kept = useMemo(() => cards.filter(c => (c.reads.length ? useScenario : on(c.key) || (useScenario && c.key === scenario?.file_card))), [cards, off, useScenario, scenario]);
  const count = cards.filter(c => (c.reads.length ? useScenario : on(c.key))).length + draft.filters.filter(f => on(filterId(f))).length;

  const answer = (q: DraftedDashboard["questions"][number], other: boolean) => {
    setAnswered(a => ({ ...a, [q.says]: other && q.instead ? q.instead.label : "Yes" }));
    setCards(cs => cs.map(c => {
      const again = draft.cards.find(d => d.key === c.key) ?? c;
      return other && q.instead?.cards[c.key] ? q.instead.cards[c.key] : q.instead?.cards[c.key] ? again : c;
    }));
  };

  const keep = async () => {
    setKeeping(true);
    setProblem("");
    try {
      const made = await keepSheetDashboard(sheetId, {
        title: title.trim(),
        cards: kept.map(c => ({ key: c.key, title: c.title, sql: c.sql, shown: c.shown, ...(!c.reads.length && !on(c.key) ? { scenario_only: true } : {}) })),
        filters: draft.filters.filter(f => on(filterId(f))).map(f => ({ column: f.column, label: f.label, grain: f.grain })),
        scenario: useScenario ? scenario : null,
        add_row: on(ADD_ROW),
      });
      onKept(made.dashboard_id, made.connection_id);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    } finally {
      setKeeping(false);
    }
  };

  const waiting = draft.questions.length + draft.not_made.length > 0;
  return (
    <div data-testid="from-file-check" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <Input aria-label="The dashboard's name" value={title} onChange={e => setTitle(e.target.value)} style={{ flex: "0 1 420px", fontWeight: 500 }} />
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Drafted from your words. Nothing is kept yet.</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <Button size="xs" variant="ghost" disabled={keeping || busy} onClick={onOver}>Start over</Button>
          <Button size="sm" data-testid="from-file-keep" disabled={keeping || busy || !count || !title.trim()} onClick={keep}>{keeping ? "Keeping…" : `Keep ${count} ${count === 1 ? "card" : "cards"}`}</Button>
        </span>
      </div>
      {problem && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>{problem}</div>}
      <div className="aug-fs-ui" style={{ color: "var(--t2)", borderLeft: "2px solid var(--b1)", paddingLeft: 10 }}>{draft.words}</div>

      {waiting && (
        <section aria-label="Needs you" data-testid="from-file-needs" style={{ ...CARD_STYLE, boxShadow: NEEDS_EDGE, padding: "12px 16px" }}>
          <div className="aug-fs-xs" style={{ ...SECTION_LABEL, color: "var(--amb3)" }}>Needs you</div>
          {draft.questions.map(q => (
            <div key={q.says} data-testid="from-file-question" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 0 0", flexWrap: "wrap" }}>
              <div className="aug-fs-ui" style={{ flex: "1 1 320px", minWidth: 0, color: answered[q.says] ? "var(--t3)" : undefined }}>
                {answered[q.says] && "✓ "}<span style={{ fontWeight: answered[q.says] ? 400 : 500 }}>{q.says}</span>
                {answered[q.says] && answered[q.says] !== "Yes" ? ` Changed to: ${answered[q.says]}.` : answered[q.says] ? "" : " Is that what you mean?"}
              </div>
              {!answered[q.says] ? (
                <>
                  <Button size="xs" variant="ghost" onClick={() => answer(q, false)}>Yes</Button>
                  {q.instead && <Button size="xs" variant="ghost" onClick={() => answer(q, true)}>{q.instead.label}</Button>}
                </>
              ) : <Button size="xs" variant="ghost" onClick={() => { answer(q, false); setAnswered(a => { const n = { ...a }; delete n[q.says]; return n; }); }}>Change</Button>}
            </div>
          ))}
          {draft.not_made.map(n => (
            <div key={n.asked} data-testid="from-file-not-made" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 0 0", flexWrap: "wrap" }}>
              <div className="aug-fs-ui" style={{ flex: "1 1 320px", minWidth: 0 }}>
                <span style={{ fontWeight: 500 }}>{n.asked} is not here.</span> <span style={{ color: "var(--t2)" }}>{n.why} No card was made.</span>
              </div>
              <Button size="xs" variant="ghost" onClick={() => requestTab("spreadsheets", { sheet: sheetId })}>Open the sheet</Button>
            </div>
          ))}
        </section>
      )}

      {draft.filters.length > 0 && (
        <Group label="Filters" chip="Proposed by a model">
          {draft.filters.map(f => (
            <Row key={f.column} id={filterId(f)} on={on(filterId(f))} onToggle={toggle} preview={<FilterPreview filter={f} />} title={f.label}
              says={`Reads ${f.grain === "month" ? `the month of ${f.column}` : f.column}: ${f.values.slice(0, 5).map(v => (f.grain === "month" ? fmtDate(`${v[0]}-01`, "month") : v[0])).join(", ")}.`} />
          ))}
        </Group>
      )}
      {figures.length > 0 && (
        <Group label="Figures" chip={draft.filters.length ? undefined : "Proposed by a model"}>
          {figures.map(c => <Row key={c.key} id={c.key} on={on(c.key)} onToggle={toggle} preview={<Preview shaped={c.preview} />} title={c.title} says={c.definition || NO_WORDS} sql={c.sql} />)}
        </Group>
      )}
      {pictures.length > 0 && (
        <Group label="Pictures">
          {pictures.map(c => <Row key={c.key} id={c.key} on={on(c.key)} onToggle={toggle} preview={<Preview shaped={c.preview} />} title={c.title} says={c.definition || NO_WORDS} sql={c.sql} />)}
        </Group>
      )}
      <Group label="The rows and a scenario">
        {tables.map(c => <Row key={c.key} id={c.key} on={on(c.key)} onToggle={toggle} preview={<Preview shaped={c.preview} />} title={c.title} says={c.definition || NO_WORDS} sql={c.sql} />)}
        <Row id={ADD_ROW} on={on(ADD_ROW)} onToggle={toggle} preview={<span className="aug-fs-sm" style={{ color: "var(--t2)" }}>A button</span>} title="Add a row" says="Writes to the sheet, so every card reads it straight away." />
        {scenario && (
          <Row id={SCENARIO} on={on(SCENARIO)} onToggle={toggle} preview={<span className="aug-fs-sm" style={{ color: "var(--t2)" }}>{scenario.inputs.length} {scenario.inputs.length === 1 ? "slider" : "sliders"}</span>}
            title="What if" says={`A scenario, not your data. ${scenario.inputs.map(i => i.label).join(", ")}. At their starting values it was checked to equal your file.`} />
        )}
        {useScenario && scenarioCards.map(c => (
          <Row key={c.key} id={c.key} on={true} onToggle={() => {}} preview={<Preview shaped={c.preview} />} title={c.title} says={c.definition || NO_WORDS} sql={c.sql} />
        ))}
      </Group>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Input aria-label="Ask for a change" placeholder="Ask for a change: put Kept first, drop Department…" value={change} onChange={e => setChange(e.target.value)} style={{ flex: "1 1 320px" }} />
        <Button size="xs" variant="ghost" disabled={!change.trim() || busy} data-testid="from-file-change" onClick={() => onRedraft(change)}>{busy ? "Asking…" : "Change it"}</Button>
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Asks a model once more.</span>
      </div>
    </div>
  );
}

export function FromFile({ onKept }: { onKept: (dashboardId: string, connectionId: string) => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [staged, setStaged] = useState<StagedFile | null>(null);
  const [reading, setReading] = useState(false);
  const [words, setWords] = useState("");
  const [sheetId, setSheetId] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<DraftedDashboard | null>(null);
  const [said, setSaid] = useState<string[]>([]);

  const choose = (file: File | undefined) => {
    if (!file) return;
    setSaid([]); setReading(true); setSheetId(""); setDraft(null);
    stageFile(file).then(setStaged).catch(e => setSaid([e instanceof Error ? e.message : String(e)])).finally(() => setReading(false));
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); choose(e.dataTransfer.files?.[0]); };

  const run = async (asked: string) => {
    if (!staged) return;
    setBusy(true); setSaid([]);
    try {
      let id = sheetId;
      if (!id) {
        const tab = staged.tabs[0];
        const made = await createFromFile(staged.token, [{ tab: tab.tab, name: nameOf(staged.upload?.file ?? staged.file),
          kinds: Object.fromEntries(tab.columns.map(c => [c.name, c.suggested])) }], staged.upload);
        id = made.sheets[0].id;
        setSheetId(id);
      }
      const out = await draftSheetDashboard(id, asked);
      if (out.drafted) setDraft(out);
      else setSaid(out.sentences);
    } catch (e) {
      setSaid([e instanceof Error ? e.message : String(e)]);
    } finally {
      setBusy(false);
    }
  };

  if (draft && sheetId) {
    return (
      <Check key={draft.words} sheetId={sheetId} draft={draft} busy={busy} onKept={onKept} onOver={() => setDraft(null)}
        onRedraft={change => { void run(`${words} Then this change: ${change}`); }} />
    );
  }
  return (
    <div data-testid="from-file" style={{ display: "grid", gridTemplateColumns: "minmax(0, 5fr) minmax(0, 4fr)", gap: 24 }}>
      <div onDragOver={e => e.preventDefault()} onDrop={onDrop}>
        <div className="aug-fs-xs" style={SECTION_LABEL}>The file</div>
        <input ref={fileRef} type="file" accept=".csv,.tsv,.xlsx,.xls" data-testid="from-file-input" hidden onChange={e => { choose(e.target.files?.[0]); e.target.value = ""; }} />
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", background: "var(--bg-3)", border: "1px dashed var(--b1)", borderRadius: "var(--r2)", padding: "8px 12px", margin: "6px 0 10px" }}>
          {staged ? (
            <>
              <span className="aug-fs-ui" style={{ fontWeight: 500 }}>{staged.file}</span>
              <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>{formatFileSize(staged.size)} · {formatCount(staged.tabs[0].rows)} rows · {staged.tabs[0].columns.length} columns</span>
            </>
          ) : <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>{reading ? "Reading the file…" : "Drop a CSV or an Excel file here."}</span>}
          <Button size="xs" variant="ghost" style={{ marginLeft: "auto" }} disabled={reading || busy} onClick={() => fileRef.current?.click()}>{staged ? "Choose another file" : "Choose a file"}</Button>
        </div>
        {staged && <ColumnsRead staged={staged} />}
        {staged && staged.tabs.length > 1 && <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 8 }}>This file has {staged.tabs.length} tabs. The dashboard reads the first, {staged.tabs[0].tab}.</div>}
        {staged && <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 8 }}>It becomes a sheet, so you can correct a wrong value and every card follows.</div>}
      </div>
      <div>
        <label className="aug-fs-xs" htmlFor="from-file-words" style={{ ...SECTION_LABEL, display: "block", marginBottom: 6 }}>What should it show?</label>
        <Textarea id="from-file-words" data-testid="from-file-words" rows={6} value={words} disabled={busy} onChange={e => setWords(e.target.value)}
          placeholder="What we sold, what came back and what's still open, by week and by channel. Which categories come back most?" />
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 10, flexWrap: "wrap" }}>
          <Button size="sm" data-testid="from-file-draft" disabled={!staged || !words.trim() || busy || reading} onClick={() => { void run(words); }}>{busy ? "Drafting…" : "Draft it"}</Button>
          <span className="aug-fs-sm" style={{ color: "var(--t3)", flex: "1 1 220px" }}>Drafting asks a model once. It reads this file's columns and a few of their values, and nothing else. Nothing is kept until you keep it.</span>
        </div>
        {said.map(s => <div key={s} role="alert" className="aug-fs-sm" data-testid="from-file-said" style={{ color: "var(--t2)", marginTop: 8 }}>{s}</div>)}
      </div>
    </div>
  );
}
