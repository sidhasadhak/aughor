"use client";

/**
 * New dashboard ▸ From a file: a file and a sentence (design-mockups/dashboard-from-file.html).
 *
 * The file becomes a sheet, a model drafts cards for what the person asked (`aughor/sheets/dashboard_draft.py`), and they check the
 * draft here before anything is kept. What each card means is said in words read off its statement, never the model's, because a
 * confident label on a wrong definition looks just like one on a right one. What the model chose is asked about, and what could
 * not be made is said. Drafting asks a model once, and the button says so.
 *
 * A person who does not know yet what to ask may have a model explore the file first (`aughor/sheets/dashboard_explore.py`): it runs
 * its own queries, shown as they happen, and writes the words for them to change, or goes straight on to draw the cards. They may
 * also change any drafted card themselves, its title or its query, which runs on the file and asks no model.
 */
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";

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
  checkDraftedCard, createFromFile, draftSheetDashboard, exploreSheetDashboard, keepSheetDashboard, stageFile,
  type DraftedCard, type DraftedDashboard, type DraftedFilter, type ExploreLook, type StagedFile,
} from "@/lib/sheets";

const SCENARIO = "__scenario";
const ADD_ROW = "__add_row";
const filterId = (f: DraftedFilter) => `filter:${f.column}`;

const CARD_STYLE = { background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)" } as const;
const SECTION_LABEL = { color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" } as const;
const QUERY_TEXT = { margin: "4px 0 2px", whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "var(--font-mono)", color: "var(--t2)",
  background: "var(--bg-3)", border: "1px solid var(--b0)", borderRadius: "var(--r2)", padding: "8px 10px" } as const;

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

/** Change a card's title or query. Running it asks no model; what comes back replaces the card, and a refusal is said here. */
function CardEditor({ card, change, onDone }: { card: DraftedCard; change: (title: string, sql: string) => Promise<string[]>; onDone: () => void }) {
  const [title, setTitle] = useState(card.title);
  const [sql, setSql] = useState(card.sql);
  const [running, setRunning] = useState(false);
  const [said, setSaid] = useState<string[]>([]);
  const run = async () => {
    setRunning(true); setSaid([]);
    const wrong = await change(title.trim(), sql);
    setRunning(false);
    if (wrong.length) setSaid(wrong);
    else onDone();
  };
  return (
    <div data-testid="from-file-card-editor" style={{ gridColumn: "2 / -1", display: "flex", flexDirection: "column", gap: 6, padding: "4px 0 6px" }}>
      <Input aria-label="The card's title" data-testid="from-file-card-title" value={title} disabled={running} onChange={e => setTitle(e.target.value)} />
      <Textarea bespoke aria-label="The card's query" data-testid="from-file-card-query" rows={Math.min(10, 2 + Math.ceil(sql.length / 90))} value={sql} disabled={running}
        onChange={e => setSql(e.target.value)} style={{ fontFamily: "var(--font-mono)" }} />
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <Button size="xs" data-testid="from-file-card-run" disabled={running || !title.trim() || !sql.trim()} onClick={() => { void run(); }}>{running ? "Running…" : "Run it"}</Button>
        <Button size="xs" variant="ghost" disabled={running} onClick={onDone}>Cancel</Button>
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Runs on the file. No model is asked.</span>
      </div>
      {said.map(s => <div key={s} role="alert" className="aug-fs-sm" data-testid="from-file-card-said" style={{ color: "var(--red4)" }}>{s}</div>)}
    </div>
  );
}

function Row({ id, on, onToggle, preview, title, says, card, change, changed }: {
  id: string; on: boolean; onToggle: (id: string) => void; preview: React.ReactNode; title: string; says: string;
  card?: DraftedCard; change?: (title: string, sql: string) => Promise<string[]>; changed?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="from-file-row" data-row={id} style={{ display: "grid", gridTemplateColumns: "20px 188px minmax(0, 1fr) auto", gap: "4px 14px", alignItems: "center",
      padding: "8px 14px", minHeight: 54, borderTop: "1px solid var(--b0)", opacity: on ? 1 : 0.5 }}>
      <Checkbox checked={on} aria-label={`Keep ${title}`} onChange={() => onToggle(id)} />
      <div style={{ minWidth: 0, display: "flex", alignItems: "center" }}>{preview}</div>
      <div style={{ minWidth: 0 }}>
        <div className="aug-fs-ui" style={{ fontWeight: 500 }}>
          {title}
          {changed && <span className="aug-fs-sm" data-testid="from-file-changed" style={{ fontWeight: 400, color: "var(--t3)", marginLeft: 8 }}>Changed by you</span>}
        </div>
        <div className="aug-fs-sm" data-testid="from-file-definition" style={{ color: "var(--t2)" }}>{says}</div>
      </div>
      {card && change ? <Button size="xs" variant={open ? "secondary" : "ghost"} aria-expanded={open} data-testid="from-file-edit" onClick={() => setOpen(o => !o)}>Edit</Button> : <span />}
      {card && change && open && <CardEditor card={card} change={change} onDone={() => setOpen(false)} />}
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

function Noticed({ noticed }: { noticed: string[] }) {
  return (
    <div data-testid="from-file-noticed">
      <div className="aug-fs-xs" style={{ ...SECTION_LABEL, paddingBottom: 4 }}>What it noticed</div>
      {noticed.map(n => <div key={n} className="aug-fs-sm" style={{ color: "var(--t2)", padding: "2px 0" }}>{n}</div>)}
    </div>
  );
}

function Look({ look }: { look: ExploreLook }) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="from-file-look" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", gap: "2px 10px", alignItems: "center", padding: "3px 0", borderTop: "1px solid var(--b0)" }}>
      <span className="aug-fs-sm" style={{ color: look.refused ? "var(--t3)" : "var(--t2)" }}>{look.why}</span>
      <span className="aug-fs-sm" style={{ color: "var(--t3)", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{look.refused ? "Refused" : `${formatCount(look.rows)}${look.more ? "+" : ""} ${look.rows === 1 ? "row" : "rows"}`}</span>
      <Button size="xs" variant={open ? "secondary" : "ghost"} aria-expanded={open} onClick={() => setOpen(o => !o)}>Query</Button>
      {open && <pre className="aug-fs-xs" style={{ ...QUERY_TEXT, gridColumn: "1 / -1" }}>{look.refused ? `${look.sql}\n\n${look.refused}` : look.sql}</pre>}
    </div>
  );
}

const pickCard = (c: DraftedCard) => ({ key: c.key, title: c.title, sql: c.sql, shown: c.shown });

function Check({ sheetId, draft, onRedraft, onOver, onKept, busy, noticed, fromModel, said }: {
  sheetId: string; draft: DraftedDashboard; onRedraft: (change: string) => void; onOver: () => void; busy: boolean;
  onKept: (dashboardId: string, connectionId: string) => void; noticed: string[]; fromModel: boolean; said: string[];
}) {
  const [title, setTitle] = useState(draft.title ?? "");
  const [cards, setCards] = useState<DraftedCard[]>(draft.cards);
  const [off, setOff] = useState<Set<string>>(new Set());
  const [edited, setEdited] = useState<Set<string>>(new Set());
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
  const keptCards = cards.filter(c => (c.reads.length ? useScenario : on(c.key))).length;
  const keptFilters = draft.filters.filter(f => on(filterId(f))).length;
  const count = keptCards + keptFilters;
  const keepWords = [keptCards ? `${keptCards} ${keptCards === 1 ? "card" : "cards"}` : "", keptFilters ? `${keptFilters} ${keptFilters === 1 ? "filter" : "filters"}` : ""].filter(Boolean).join(" and ") || "nothing";

  const answer = (q: DraftedDashboard["questions"][number], other: boolean) => {
    setAnswered(a => ({ ...a, [q.says]: other && q.instead ? q.instead.label : "Yes" }));
    setCards(cs => cs.map(c => {
      const again = draft.cards.find(d => d.key === c.key) ?? c;
      if (other && q.instead?.cards[c.key]) return q.instead.cards[c.key];
      return q.instead?.cards[c.key] && !edited.has(c.key) ? again : c;     // "Yes" never undoes what the person changed themselves
    }));
    if (other && q.instead) {
      const replaced = q.instead.cards;
      setEdited(s => new Set([...s].filter(key => !replaced[key])));
    }
  };

  /** A card the person changed: run on the file, with its scenario's other card when it belongs to one, which it must still equal. */
  const changeCard = (card: DraftedCard) => async (newTitle: string, sql: string): Promise<string[]> => {
    const twinKey = useScenario && scenario ? (card.key === scenario.scenario_card ? scenario.file_card : card.key === scenario.file_card ? scenario.scenario_card : "") : "";
    const twin = cards.find(c => c.key === twinKey);
    try {
      const out = await checkDraftedCard(sheetId, { card: { ...pickCard(card), title: newTitle, sql }, scenario: useScenario ? scenario : null, twin: twin ? pickCard(twin) : null });
      if (!out.card) return out.sentences;
      const now = out.card;
      setCards(cs => cs.map(c => (c.key === card.key ? now : c)));
      setEdited(s => new Set(s).add(card.key));
      return [];
    } catch (e) {
      return [e instanceof Error ? e.message : String(e)];
    }
  };
  const rowOf = (c: DraftedCard, always = false) => (
    <Row key={c.key} id={c.key} on={always || on(c.key)} onToggle={always ? () => {} : toggle} preview={<Preview shaped={c.preview} />} title={c.title}
      says={c.definition || NO_WORDS} card={c} change={changeCard(c)} changed={edited.has(c.key)} />
  );

  const keep = async () => {
    setKeeping(true);
    setProblem("");
    try {
      const made = await keepSheetDashboard(sheetId, {
        title: title.trim(),
        cards: kept.map(c => ({ ...pickCard(c), ...(!c.reads.length && !on(c.key) ? { scenario_only: true } : {}), ...(edited.has(c.key) ? { edited: true } : {}) })),
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
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>{fromModel ? "Drafted from what a model found in the file." : "Drafted from your words."} Nothing is kept yet.</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <Button size="xs" variant="ghost" disabled={keeping || busy} onClick={onOver}>Back to the words</Button>
          <Button size="sm" data-testid="from-file-keep" disabled={keeping || busy || !count || !title.trim()} onClick={keep}>{keeping ? "Keeping…" : `Keep ${keepWords}`}</Button>
        </span>
      </div>
      {problem && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>{problem}</div>}
      {said.map(s => <div key={s} role="alert" className="aug-fs-sm" data-testid="from-file-said" style={{ color: "var(--red4)" }}>{s}</div>)}
      <div className="aug-fs-ui" style={{ color: "var(--t2)", borderLeft: "2px solid var(--b1)", paddingLeft: 10 }}>{draft.words}</div>
      {noticed.length > 0 && <Noticed noticed={noticed} />}

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
          {figures.map(c => rowOf(c))}
        </Group>
      )}
      {pictures.length > 0 && (
        <Group label="Pictures">
          {pictures.map(c => rowOf(c))}
        </Group>
      )}
      <Group label="The rows and a scenario">
        {tables.map(c => rowOf(c))}
        <Row id={ADD_ROW} on={on(ADD_ROW)} onToggle={toggle} preview={<span className="aug-fs-sm" style={{ color: "var(--t2)" }}>A button</span>} title="Add a row" says="Writes to the sheet, so every card reads it straight away." />
        {scenario && (
          <Row id={SCENARIO} on={on(SCENARIO)} onToggle={toggle} preview={<span className="aug-fs-sm" style={{ color: "var(--t2)" }}>{scenario.inputs.length} {scenario.inputs.length === 1 ? "slider" : "sliders"}</span>}
            title="What if" says={`A scenario, not your data. ${scenario.inputs.map(i => i.label).join(", ")}. At their starting values it was checked to equal your file.`} />
        )}
        {useScenario && scenarioCards.map(c => rowOf(c, true))}
      </Group>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Input aria-label="Ask for a change" placeholder="Ask for a change: put Kept first, drop Department…" value={change} onChange={e => setChange(e.target.value)} style={{ flex: "1 1 320px" }} />
        <Button size="xs" variant="ghost" disabled={!change.trim() || busy} data-testid="from-file-change" onClick={() => onRedraft(change)}>{busy ? "Asking…" : "Change it"}</Button>
        <span className="aug-fs-sm" style={{ color: edited.size ? "var(--amb3)" : "var(--t3)" }}>{edited.size ? "Asks a model once more. It redraws every card, so what you changed goes." : "Asks a model once more."}</span>
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
  // exploring: what it is doing now, what it looked at, what it noticed, and whether the words in the box are still its own
  const [exploring, setExploring] = useState<{ draw: boolean; drafting: boolean } | null>(null);
  const [looks, setLooks] = useState<ExploreLook[]>([]);
  const [noticed, setNoticed] = useState<string[]>([]);
  const [wrote, setWrote] = useState(false);
  const [written, setWritten] = useState(0);
  const [before, setBefore] = useState<string | null>(null);
  const [showLooks, setShowLooks] = useState(false);
  const stopper = useRef<AbortController | null>(null);
  useEffect(() => () => stopper.current?.abort(), []);     // leaving stops the spending

  const choose = (file: File | undefined) => {
    if (!file) return;
    setSaid([]); setReading(true); setSheetId(""); setDraft(null);
    setLooks([]); setNoticed([]); setBefore(null); setWritten(0);
    if (wrote) { setWords(""); setWrote(false); }           // what a model wrote was about the other file
    stageFile(file).then(setStaged).catch(e => setSaid([e instanceof Error ? e.message : String(e)])).finally(() => setReading(false));
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); choose(e.dataTransfer.files?.[0]); };

  const sheetOf = async (file: StagedFile): Promise<string> => {
    if (sheetId) return sheetId;
    const tab = file.tabs[0];
    const made = await createFromFile(file.token, [{ tab: tab.tab, name: nameOf(file.upload?.file ?? file.file),
      kinds: Object.fromEntries(tab.columns.map(c => [c.name, c.suggested])) }], file.upload);
    const id = made.sheets[0].id;
    setSheetId(id);
    return id;
  };

  const run = async (asked: string) => {
    if (!staged) return;
    setBusy(true); setSaid([]);
    try {
      const out = await draftSheetDashboard(await sheetOf(staged), asked, noticed);
      if (out.drafted) setDraft(out);
      else setSaid(out.sentences);
    } catch (e) {
      setSaid([e instanceof Error ? e.message : String(e)]);
    } finally {
      setBusy(false);
    }
  };

  const explore = async (draw: boolean) => {
    if (!staged) return;
    const started = words;
    const stopping = new AbortController();
    stopper.current = stopping;
    setExploring({ draw, drafting: false }); setLooks([]); setNoticed([]); setSaid([]); setShowLooks(false); setWritten(0);
    try {
      await exploreSheetDashboard(await sheetOf(staged), { focus: started, draw }, frame => {
        if (frame.type === "look") setLooks(l => [...l, frame]);
        else if (frame.type === "explored") {
          setLooks(frame.looks); setNoticed(frame.noticed); setWords(frame.words); setWrote(true);
          setWritten(frame.looks.length); setBefore(started.trim() ? started : null);
        } else if (frame.type === "drafting") setExploring({ draw, drafting: true });
        else if (frame.type === "drafted") {
          if (frame.draft.drafted) setDraft(frame.draft);
          else setSaid(frame.draft.sentences);
        } else if (frame.type === "failed") setSaid(frame.sentences);
      }, stopping.signal);
    } catch (e) {
      if (!stopping.signal.aborted) setSaid([e instanceof Error ? e.message : String(e)]);
    } finally {
      setExploring(null);
      stopper.current = null;
    }
  };
  const stop = () => {
    setSaid([exploring?.drafting ? "Stopped before the cards were drafted. The words it wrote are in the box." : `Stopped after ${formatCount(looks.length)} ${looks.length === 1 ? "query" : "queries"}. Nothing was written.`]);
    stopper.current?.abort();
  };

  if (draft && sheetId) {
    return (
      <Check key={draft.words} sheetId={sheetId} draft={draft} busy={busy} onKept={onKept} onOver={() => { setDraft(null); setSaid([]); }} noticed={noticed} fromModel={wrote} said={said}
        onRedraft={change => { void run(`${draft.words ?? words} Then this change: ${change}`); }} />
    );
  }
  const working = busy || !!exploring;
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
          <Button size="xs" variant="ghost" style={{ marginLeft: "auto" }} disabled={reading || working} onClick={() => fileRef.current?.click()}>{staged ? "Choose another file" : "Choose a file"}</Button>
        </div>
        {staged && <ColumnsRead staged={staged} />}
        {staged && staged.tabs.length > 1 && <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 8 }}>This file has {staged.tabs.length} tabs. The dashboard reads the first, {staged.tabs[0].tab}.</div>}
        {staged && <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 8 }}>It becomes a sheet, so you can correct a wrong value and every card follows.</div>}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
        <div>
          <label className="aug-fs-xs" htmlFor="from-file-words" style={{ ...SECTION_LABEL, display: "block", marginBottom: 6 }}>What should it show?</label>
          <Textarea id="from-file-words" data-testid="from-file-words" rows={Math.max(6, Math.min(16, Math.ceil(words.length / 62) + 1))} value={words} disabled={working} onChange={e => { setWords(e.target.value); setWrote(false); }}
            placeholder="What we sold, what came back and what's still open, by week and by channel. Which categories come back most?" />
          {written > 0 && (
            <div data-testid="from-file-wrote" className="aug-fs-sm" style={{ color: "var(--t3)", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
              <span>{wrote ? `Written by a model after ${formatCount(written)} ${written === 1 ? "query" : "queries"}. It is yours to change.` : `Started by a model after ${formatCount(written)} ${written === 1 ? "query" : "queries"}, and changed by you.`}</span>
              {before !== null && <Button size="xs" variant="ghost" data-testid="from-file-put-back" disabled={working} onClick={() => { setWords(before); setBefore(null); setWrote(false); setWritten(0); setNoticed([]); }}>Put back what you wrote</Button>}
            </div>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <Button size="sm" data-testid="from-file-draft" disabled={!staged || !words.trim() || working || reading} onClick={() => { void run(words); }}>{busy ? "Drafting…" : "Draft it"}</Button>
          <span className="aug-fs-sm" style={{ color: "var(--t3)", flex: "1 1 220px" }}>Drafting asks a model once. It reads this file's columns and a few of their values{noticed.length ? ", and what was noticed below" : ""}, and nothing else. Nothing is kept until you keep it.</span>
        </div>
        {noticed.length > 0 && <Noticed noticed={noticed} />}

        <section aria-label="Let a model explore the file" data-testid="from-file-explore" style={{ borderTop: "1px solid var(--b0)", paddingTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
          {exploring ? (
            <div data-testid="from-file-exploring" aria-live="polite" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span className="aug-fs-xs" style={SECTION_LABEL}>{exploring.drafting ? "Drafting the cards from what it found" : "Exploring the file"}</span>
              <span className="aug-fs-sm" style={{ color: "var(--t3)", fontVariantNumeric: "tabular-nums" }}>{formatCount(looks.length)} {looks.length === 1 ? "query" : "queries"} so far</span>
              <Button size="xs" variant="ghost" data-testid="from-file-stop" style={{ marginLeft: "auto" }} onClick={stop}>Stop</Button>
            </div>
          ) : (
            <>
              <div className="aug-fs-xs" style={SECTION_LABEL}>Not sure what to ask?</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <Button size="sm" variant="ghost" data-testid="from-file-write" disabled={!staged || busy || reading} onClick={() => { void explore(false); }}>Write the words for me</Button>
                <Button size="sm" variant="ghost" data-testid="from-file-draw" disabled={!staged || busy || reading} onClick={() => { void explore(true); }}>Explore and draw it</Button>
              </div>
              <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
                A model runs up to 16 queries of its own on this file, reads up to 30 rows of each, and says what it would show. It takes a minute or two. It writes the words for you to change, or goes straight on to draw the cards.{words.trim() ? " It starts from what is in the box." : ""}
              </div>
            </>
          )}
          {looks.length > 0 && !exploring && (
            <div><Button size="xs" variant="ghost" aria-expanded={showLooks} data-testid="from-file-looked" onClick={() => setShowLooks(o => !o)}>What it looked at</Button></div>
          )}
          {looks.length > 0 && (exploring || showLooks) && (
            <div data-testid="from-file-looks">{withUniqueKeys(looks, l => l.sql).map(([key, l]) => <Look key={key} look={l} />)}</div>
          )}
        </section>
        {said.map(s => <div key={s} role="alert" className="aug-fs-sm" data-testid="from-file-said" style={{ color: "var(--t2)" }}>{s}</div>)}
      </div>
    </div>
  );
}
