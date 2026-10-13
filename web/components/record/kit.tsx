"use client";

/**
 * The pieces the 2027 screens share (the study §V): a read with its three honest states, a
 * Ledger that every destination opens on, the Reader a ledger row opens into, and the small
 * marks a claim carries wherever it is cited — tier, status, counted confidence.
 *
 * Nothing here paints before it knows what it is showing: a read in flight says what is being
 * read, a read that failed says so with Retry, and an empty ledger says what would fill it.
 */
import { Table } from "@radix-ui/themes";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { CARD, Label, MUTED, NUM, ONE_LINE, ROW, RULE } from "@/components/clarity/kit";
import { TableActions, tableFromElement } from "@/components/TableActions";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Loading, ReadFailed } from "@/components/ui/states";
import { formatCount, pct } from "@/lib/format";
import type { CsvCell } from "@/lib/query/csv";
import { markClaimWrong, type Claim, type MarkedWrong } from "@/lib/record";
import { useMe } from "@/lib/useMe";

// ── a read ───────────────────────────────────────────────────────────────────────────────

export interface Load<T> {
  data: T | null;
  error: string;
  loading: boolean;
  reload: () => void;
}

/** One read, re-run when `deps` change. A newer read's answer always wins over an older one's. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): Load<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);
  const fnRef = useRef(fn);
  useEffect(() => { fnRef.current = fn; });
  useEffect(() => {
    const mine = ++seq.current;
    setLoading(true);
    setError("");
    fnRef.current()
      .then(d => { if (mine === seq.current) setData(d); })
      .catch(e => { if (mine === seq.current) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (mine === seq.current) setLoading(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick(t => t + 1), []);
  return { data, error, loading, reload };
}

/** The three states of a read, then its body. `what` is the thing being read, as the screen names it. */
export function Gate<T>({ load, what, children }: {
  load: Load<T>; what: string; children: (data: T) => React.ReactNode;
}) {
  if (load.error) return <ReadFailed what={what} error={load.error} onRetry={load.reload} style={{ padding: "12px 0" }} />;
  if (load.data === null) return <Loading what={what} style={{ padding: "12px 0" }} />;
  return <>{children(load.data)}</>;
}

// ── who is writing ───────────────────────────────────────────────────────────────────────

export interface Actor {
  /** A sign-in names the reader; without one, the install's own login does. */
  signedIn: boolean;
  /** Who a write is recorded under, as the server says — "" until it has answered. */
  name: string;
}

/**
 * Who a page writes as. Nothing here is sent: the server records every write under the person the
 * request acts for, so a form never asks for a name. It used to ask, once per browser, and the
 * name typed was what the record kept — anyone could act as anyone.
 */
export function useActor(): Actor {
  const me = useMe();
  return { signedIn: !!me?.signed_in, name: me?.actor ?? "" };
}

/** A read-only line: who a write is recorded as. Shown so the person can see it; never asked. */
export function ActorField({ actor, id = "record-actor" }: { actor: Actor; id?: string }) {
  if (!actor.name) return null;
  return (
    <span id={id} className="aug-fs-sm" style={{ color: "var(--t3)" }}
      title={actor.signedIn ? "Recorded under your sign-in." : "Nobody signs in on this install, so the record keeps the login it runs under."}>
      Recorded as <span style={{ color: "var(--t2)" }}>{actor.name}</span>
    </span>
  );
}

// ── page furniture ───────────────────────────────────────────────────────────────────────

/** A destination's page: a scrolling body at reading width, with an optional rail of its own details. */
export function Page({ children, rail, wide = false }: { children: React.ReactNode; rail?: React.ReactNode; wide?: boolean }) {
  return (
    <div style={{ flex: 1, display: "flex", minHeight: 0, background: "var(--bg-0)" }}>
      <div style={{ flex: 1, minWidth: 0, overflowY: "auto" }}>
        <div className={wide ? "aug-page aug-page-wide" : "aug-page"}>{children}</div>
      </div>
      {rail && <aside className="aug-rail">{rail}</aside>}
    </div>
  );
}

/** The row a Reader opens under: the ledger it came from as a link, then what it is. */
export function BackHeader({ from, onBack, title, chips, actions }: {
  from: string; onBack: () => void; title: string; chips?: React.ReactNode; actions?: React.ReactNode;
}) {
  return (
    <div className="aug-page-header">
      <Button variant="link" size="xs" onClick={onBack} style={{ padding: 0 }} title={`Back to ${from.toLowerCase()}`}>
        {from}
      </Button>
      <span aria-hidden style={{ color: "var(--t3)" }}>/</span>
      <h1 className="aug-content-title" style={{ margin: 0 }} title={title}>{title}</h1>
      {chips}
      <span style={{ flex: 1 }} />
      {actions}
    </div>
  );
}

/** A numbered part of a page's hierarchy: its label, what it counts, its one action, its body. */
export function Section({ label, meta, action, children, id }: {
  label: string; meta?: React.ReactNode; action?: React.ReactNode; children: React.ReactNode; id?: string;
}) {
  return (
    <section className="aug-section" id={id} aria-label={label}>
      <div className="aug-section-head">
        <h2 className="aug-label" style={{ margin: 0 }}>{label}</h2>
        {meta != null && <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>{meta}</span>}
        <span style={{ flex: 1 }} />
        {action}
      </div>
      {children}
    </section>
  );
}

/** A line that says something is absent, in the place it would be — never a blank region. */
export function Absent({ children }: { children: React.ReactNode }) {
  return <p className="aug-fs-ui aug-absent">{children}</p>;
}

/** A labelled fact in a rail or a details list. */
export function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="aug-rail-row">
      <span>{label}</span>
      <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>{children}</span>
    </div>
  );
}

// ── the ledger ───────────────────────────────────────────────────────────────────────────

export interface LedgerColumn<T> {
  head: string;
  cell: (row: T) => React.ReactNode;
  /** Right-aligned, tabular — a figure. */
  num?: boolean;
  width?: number | string;
  /** A column of buttons, not of facts: drawn, and left out of what Copy and CSV take away. */
  control?: boolean;
}

/**
 * A destination's first page: one row per thing, the first cell opening it. Every ledger can be
 * taken away — Copy puts cells on the clipboard, CSV downloads them — because a table a reader
 * cannot leave with is a picture of a table.
 */
export function Ledger<T>({ name, columns, rows, rowKey, onOpen, empty, selected, group }: {
  name: string;
  columns: LedgerColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onOpen?: (row: T) => void;
  /** What an empty ledger says: what it holds once it holds something. */
  empty: React.ReactNode;
  selected?: string;
  /** The section a row belongs to; a heading row is drawn where the section changes. Copy and CSV
   *  take the rows, not the headings. */
  group?: (row: T) => string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  if (rows.length === 0) return <Absent>{empty}</Absent>;
  return (
    <div>
      {/* On Radix Themes: its size-1 table. The first column is what the row IS. */}
      <Table.Root ref={ref} size="1" variant="ghost" data-ledger={name}>
        <Table.Header>
          <Table.Row>{columns.map((c, i) => (
            <Table.ColumnHeaderCell key={c.head} className={c.num ? "num" : undefined}
              style={{ width: c.width, minWidth: i === 0 && c.width === undefined ? 320 : undefined }}>{c.head}</Table.ColumnHeaderCell>
          ))}</Table.Row>
        </Table.Header>
        <Table.Body>
          {rows.map((row, at) => {
            const key = rowKey(row);
            const section = group?.(row);
            const heads = section !== undefined && (at === 0 || group?.(rows[at - 1]) !== section);
            return (
              <Fragment key={key}>
              {heads && (
                <Table.Row data-ledger-group="">
                  <Table.Cell colSpan={columns.length} className="aug-label" style={{ color: "var(--t3)", paddingTop: at === 0 ? undefined : 14 }}>
                    {section}
                  </Table.Cell>
                </Table.Row>
              )}
              <Table.Row align="center" aria-selected={selected === key || undefined}
                onClick={onOpen ? () => onOpen(row) : undefined}
                style={onOpen ? { cursor: "pointer" } : undefined}>
                {columns.map((c, i) => (
                  <Table.Cell key={c.head} className={c.num ? "num" : undefined}>
                    {i === 0 && onOpen
                      ? <Button variant="link" size="xs" className="aug-ledger-open"
                          onClick={e => { e.stopPropagation(); onOpen(row); }}>{c.cell(row)}</Button>
                      : c.cell(row)}
                  </Table.Cell>
                ))}
              </Table.Row>
              </Fragment>
            );
          })}
        </Table.Body>
      </Table.Root>
      <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 4 }}>
        <TableActions name={name} read={() => {
          const table = ref.current?.querySelector("table");
          if (!table) return null;
          const read = tableFromElement(table);
          const t = group ? { ...read, rows: read.rows.filter(r => r.length === columns.length) } : read;
          const facts = columns.map((c, i) => (c.control ? -1 : i)).filter(i => i >= 0);
          return facts.length === columns.length
            ? t : { columns: facts.map(i => t.columns[i]), rows: t.rows.map(r => facts.map(i => r[i])) };
        }} />
      </div>
    </div>
  );
}

// ── a list, the CLARITY way ──────────────────────────────────────────────────────────────

/** One column of what Copy and CSV take: the full words of a row, not the short label it shows. */
export interface ListColumn<T> {
  head: string;
  value: (row: T) => CsvCell;
}

/**
 * A ledger as CLARITY lays it out (`aughor-v2/CLARITY.md` §3): a card on the ground, its small label with the count and
 * Copy · CSV at the right end, then one row per thing — name · its marks · a figure · one muted line. The first `page`
 * rows show; the rest are one click away and the label says how many are held back. Copy and CSV take every row, in the
 * words the record keeps (the full question, not its label), because a table a reader cannot leave with is a picture
 * of a table.
 */
export function ListCard<T>({ label, tools, rows, rowKey, columns, name, renderRow, empty, page = 50, group, testId }: {
  label: React.ReactNode;
  /** What filters or acts on the list (a filter, its one action), at the label's right end before Copy · CSV. */
  tools?: React.ReactNode;
  rows: T[];
  rowKey: (row: T) => string;
  columns: ListColumn<T>[];
  /** The CSV's file name. */
  name: string;
  renderRow: (row: T, first: boolean) => React.ReactNode;
  /** What an empty list says, in one muted line. */
  empty: React.ReactNode;
  page?: number;
  /** Rows that share a key (a day) under one small heading, which says once what the rows would each repeat. The
   *  rows arrive in order; a heading is drawn where the key changes. Copy and CSV take the rows, not the headings. */
  group?: { key: (row: T) => string; head: (key: string, rows: T[]) => React.ReactNode; meta?: (key: string, rows: T[]) => React.ReactNode };
  testId?: string;
}) {
  const [shown, setShown] = useState(page);
  const read = () => ({ columns: columns.map(c => c.head), rows: rows.map(r => columns.map(c => c.value(r))) });
  const members = new Map<string, T[]>();
  if (group) for (const r of rows) { const k = group.key(r); members.set(k, [...(members.get(k) ?? []), r]); }
  return (
    <section aria-label={typeof label === "string" ? label : undefined} data-testid={testId} style={CARD}>
      <Label right={<>
        {tools}
        {rows.length > 0 && <TableActions name={name} read={read} />}
      </>}>{label}</Label>
      {rows.length === 0
        ? <div className="aug-fs-sm" style={{ ...MUTED, padding: "2px 0" }}>{empty}</div>
        : rows.slice(0, shown).map((r, i, all) => {
          const k = group?.key(r);
          const heads = group && k !== undefined && (i === 0 || group.key(all[i - 1]) !== k);
          return (
            <Fragment key={rowKey(r)}>
              {heads && (
                <div data-list-group="" className="aug-fs-xs" style={{ display: "flex", alignItems: "baseline", gap: 8,
                  padding: i === 0 ? "0 2px 2px" : "14px 2px 2px", color: "var(--t3)" }}>
                  <span style={{ textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                    {group.head(k, members.get(k) ?? [])}
                  </span>
                  {group.meta && <span style={{ ...ONE_LINE, marginLeft: "auto" }}>{group.meta(k, members.get(k) ?? [])}</span>}
                </div>
              )}
              {renderRow(r, i === 0 || !!heads)}
            </Fragment>
          );
        })}
      {rows.length > shown && (
        <div style={{ ...ROW, ...RULE, paddingTop: 8 }}>
          <span className="aug-fs-xs" style={MUTED}>
            {formatCount(shown)} of {formatCount(rows.length)} shown · Copy and CSV take all {formatCount(rows.length)}
          </span>
          <Button size="xs" variant="ghost" onClick={() => setShown(s => s + page)}>
            Show {formatCount(Math.min(page, rows.length - shown))} more
          </Button>
        </div>
      )}
    </section>
  );
}

/**
 * One row of a list: a mark, the name (its full text on hover; a click opens it), the chips only this row carries,
 * the figure at the right, and one muted line under the name.
 */
export function ListRow({ first, mark, title, full, onOpen, chips, figure, figureTitle, meta, metaTitle, actions, testId }: {
  first: boolean;
  mark?: React.ReactNode;
  title: React.ReactNode;
  /** The whole text the name stands for. */
  full?: string;
  onOpen?: () => void;
  chips?: React.ReactNode;
  figure?: React.ReactNode;
  figureTitle?: string;
  meta?: React.ReactNode;
  metaTitle?: string;
  actions?: React.ReactNode;
  testId?: string;
}) {
  const name = <span className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)" }}>{title}</span>;
  return (
    <div data-testid={testId} style={{ padding: "8px 2px", ...(first ? {} : RULE) }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12, alignItems: "center" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            {mark}
            {onOpen
              ? <Button variant="link" size="xs" onClick={onOpen} title={full}
                  style={{ height: "auto", padding: 0, margin: 0, minWidth: 0, flexShrink: 1, justifyContent: "flex-start" }}>
                  {name}
                </Button>
              : <span title={full} style={{ minWidth: 0, display: "flex" }}>{name}</span>}
            {chips}
          </div>
          {meta != null && meta !== "" && (
            <div className="aug-fs-xs" title={metaTitle} style={{ ...MUTED, ...ONE_LINE, marginTop: 1 }}>{meta}</div>
          )}
        </div>
        {(figure != null || actions) && (
          <div style={{ ...ROW, flexWrap: "nowrap" }}>
            {figure != null && (
              <span className="aug-fs-chrome" title={figureTitle} style={{ color: "var(--t2)", textAlign: "right", ...NUM }}>{figure}</span>
            )}
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}

export interface FacetValue {
  value: string;
  label: React.ReactNode;
  count: number;
  title?: string;
}

/**
 * One filter in a left column (CLARITY §3): value · count · a 6px bar, the chosen rows tinted. Nothing chosen is
 * everything; choosing narrows the list beside it.
 */
export function Facet({ label, values, chosen, onToggle, testId }: {
  label: string; values: FacetValue[]; chosen: ReadonlySet<string>; onToggle: (value: string) => void; testId?: string;
}) {
  const top = Math.max(1, ...values.map(v => v.count));
  return (
    <div role="group" aria-label={label} data-testid={testId} style={{ marginBottom: 12 }}>
      <Label>{label}</Label>
      {values.map(v => {
        const on = chosen.has(v.value);
        return (
          <label key={v.value} data-on={on || undefined} title={v.title} className="aug-fs-sm"
            style={{ display: "grid", gridTemplateColumns: "16px minmax(0, 1fr) 40px 40px", alignItems: "center", gap: 7,
              padding: "3px 4px", borderRadius: "var(--r2)", cursor: "pointer", background: on ? "var(--bg-sel)" : undefined }}>
            <Checkbox checked={on} aria-label={`${label}: ${typeof v.label === "string" ? v.label : v.value}`}
              onChange={() => onToggle(v.value)} />
            <span style={{ ...ONE_LINE, color: "var(--t1)" }}>{v.label}</span>
            <span style={{ textAlign: "right", color: "var(--t2)", ...NUM }}>{formatCount(v.count)}</span>
            <span aria-hidden="true" style={{ height: 6, background: "var(--bg-3)", borderRadius: 3, overflow: "hidden" }}>
              <span style={{ display: "block", height: "100%", width: `${(v.count / top) * 100}%`, background: "var(--chart-1)" }} />
            </span>
          </label>
        );
      })}
    </div>
  );
}

/** A set of chosen facet values, toggled one at a time. */
export function useChosen(): [ReadonlySet<string>, (value: string) => void, () => void] {
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set());
  const toggle = useCallback((v: string) => setChosen(prev => {
    const next = new Set(prev);
    if (next.has(v)) next.delete(v); else next.add(v);
    return next;
  }), []);
  const clear = useCallback(() => setChosen(new Set()), []);
  return [chosen, toggle, clear];
}

// ── the marks a claim carries ────────────────────────────────────────────────────────────

const STATUS_HUE: Record<string, ChipHue> = { Final: "positive", Provisional: "caution", "To date": "info" };

/** Final · Provisional · To date — the same three words everywhere a figure is shown. */
export function StatusMark({ status }: { status: string }) {
  return <StatusChip hue={STATUS_HUE[status] ?? "muted"}>{status}</StatusChip>;
}

const TIER_WORDS: Record<string, string> = {
  approved: "approved by a person",
  declared: "declared by a person",
  measured: "measured",
  mined: "computed",
  said: "said",
};

/** Where a claim sits on the authority ladder, in words. */
export function TierMark({ tier }: { tier: string }) {
  return <StatusChip hue="muted" title="How this statement is warranted">{tierWords(tier)}</StatusChip>;
}

/** "measured" · "computed" · "approved by a person" — a tier in the words the marks use. */
export function tierWords(tier: string): string {
  return TIER_WORDS[tier] ?? tier;
}

/** How often claims of this class have been right, as one line of text — what `Counted` shows, for a copy or a CSV. */
export function countedWords(claim: Pick<Claim, "confidence" | "confidence_note">): string {
  const c = claim.confidence;
  if (!c) return claim.confidence_note || "not counted yet";
  if (c.hit_rate == null) return c.note || `${c.n} cases so far`;
  return `right ${pct(c.hit_rate)} of ${c.n} times`;
}

/**
 * How often claims of this class have been right — a hit rate with its count, the count alone
 * when there are too few to state a rate, or the reason nothing is counted. Never a model's own
 * estimate of itself.
 */
export function Counted({ claim, brief = false }: {
  claim: Pick<Claim, "confidence" | "confidence_note">;
  /** In a table cell: the short form, with the reason on hover. */
  brief?: boolean;
}) {
  const c = claim.confidence;
  if (!c) {
    const why = claim.confidence_note || "not counted yet";
    return <span className="aug-fs-sm" style={{ color: "var(--t3)" }} title={brief ? why : undefined}>{brief ? "not counted" : why}</span>;
  }
  if (c.hit_rate == null) {
    return (
      <span className="aug-fs-sm" style={{ color: "var(--t3)" }} title={brief ? `${c.reference_class}: ${c.note}` : c.reference_class}>
        {brief ? `${c.n} so far — too few to count` : c.note || `${c.n} cases so far`}
      </span>
    );
  }
  return (
    <span className="aug-fs-sm" style={{ color: "var(--t2)" }} title={c.reference_class}>
      right {pct(c.hit_rate)} of {c.n} times
    </span>
  );
}

/** A claim as one cited line: the statement, then its marks. The statement opens the claim. */
export function ClaimLine({ claim, onOpen, note, action }: {
  claim: Claim; onOpen?: (id: string) => void;
  /** Something a reader must know about this citation — that the claim was restated since. */
  note?: React.ReactNode;
  /** What a person can do to the claim from here. */
  action?: React.ReactNode;
}) {
  return (
    <div className="aug-claim-line">
      <div className="aug-fs-ui" style={{ color: "var(--t1)", minWidth: 0 }}>
        {onOpen
          ? <Button variant="link" size="xs" className="aug-ledger-open" onClick={() => onOpen(claim.id)}>{claim.statement.text}</Button>
          : claim.statement.text}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <StatusMark status={claim.status} />
        <TierMark tier={claim.tier} />
        <Counted claim={claim} />
        {claim.as_of && <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>as of {claim.as_of}</span>}
        {note && <span className="aug-fs-sm" style={{ color: "var(--amb4)" }}>{note}</span>}
        {action && <><span style={{ flex: 1 }} />{action}</>}
      </div>
    </div>
  );
}

/**
 * A person says a claim is wrong. A hypothesis takes the reason it is false and is kept as
 * refuted; anything else takes what is true instead and is restated as that person's statement,
 * the wrong version kept. A prediction is not offered this — it is scored on its day, by code.
 */
export function MarkWrong({ claim, actor, onMarked }: {
  claim: Pick<Claim, "id" | "kind" | "state" | "statement">;
  actor: Actor;
  onMarked: (out: MarkedWrong) => void;
}) {
  const [open, setOpen] = useState(false);
  const [corrected, setCorrected] = useState("");
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (claim.kind === "prediction" || (claim.kind === "hypothesis" && claim.state === "refuted")) return null;
  if (!open) return <Button size="xs" variant="ghost" onClick={() => setOpen(true)}>Mark wrong</Button>;
  const hypothesis = claim.kind === "hypothesis";
  const ready = hypothesis ? why.trim() : corrected.trim();
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      onMarked(await markClaimWrong(claim.id, { corrected: corrected.trim(), why: why.trim() }));
      setOpen(false);
      setCorrected("");
      setWhy("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="aug-form-grid" style={{ flexBasis: "100%", marginTop: 8 }}>
      {!hypothesis && (
        <>
          <label className="aug-fs-sm" htmlFor={`wrong-is-${claim.id}`}>What is true instead</label>
          <Input id={`wrong-is-${claim.id}`} value={corrected} onChange={e => setCorrected(e.target.value)}
            placeholder="The corrected statement, in full" />
        </>
      )}
      <label className="aug-fs-sm" htmlFor={`wrong-why-${claim.id}`}>{hypothesis ? "What shows it is false" : "Why"}</label>
      <Input id={`wrong-why-${claim.id}`} value={why} onChange={e => setWhy(e.target.value)}
        placeholder={hypothesis ? "The evidence against it" : "What the wrong version missed (optional)"} />
      <span />
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <ActorField actor={actor} id={`wrong-by-${claim.id}`} />
        <Button size="xs" disabled={busy || !ready} onClick={() => void submit()}>Mark it wrong</Button>
        <Button size="xs" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
          {hypothesis ? "It is kept, as refuted." : "The wrong version is kept; whatever relied on it is told."}
        </span>
        {error && <span className="aug-fs-sm" role="alert" style={{ color: "var(--red4)" }}>{error}</span>}
      </div>
    </div>
  );
}

/** What marking a claim wrong set in motion, as a sentence. */
export function markedWords(out: Pick<MarkedWrong, "woke_inquiries" | "reopened_decisions">): string {
  const parts = [
    out.woke_inquiries.length ? `${out.woke_inquiries.length} inquir${out.woke_inquiries.length === 1 ? "y" : "ies"} that established it woke` : "",
    out.reopened_decisions.length ? `${out.reopened_decisions.length} decision${out.reopened_decisions.length === 1 ? "" : "s"} that relied on it reopened` : "",
  ].filter(Boolean);
  return parts.length ? `Recorded: ${parts.join(" and ")}.` : "Recorded. Nothing else relied on it.";
}

/** A day as the ledger wrote it (`2026-10-26`, or a full instant) read as a date. */
export function day(iso: string | null | undefined): string {
  return (iso ?? "").slice(0, 10);
}

/** Whole days from today to an ISO day; negative when it has passed. */
export function daysUntil(iso: string | null | undefined): number | null {
  const d = day(iso);
  if (!d) return null;
  const then = Date.parse(`${d}T00:00:00Z`);
  if (Number.isNaN(then)) return null;
  const now = new Date();
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((then - today) / 86_400_000);
}

/** "in 6 days" · "today" · "9 days ago" — beside a date, never instead of it. */
export function dayDistance(iso: string | null | undefined): string {
  const n = daysUntil(iso);
  if (n === null) return "";
  if (n === 0) return "today";
  const days = `${Math.abs(n)} day${Math.abs(n) === 1 ? "" : "s"}`;
  return n > 0 ? `in ${days}` : `${days} ago`;
}
