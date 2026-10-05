"use client";

/**
 * The pieces the 2027 screens share (the study §V): a read with its three honest states, a
 * Ledger that every destination opens on, the Reader a ledger row opens into, and the small
 * marks a claim carries wherever it is cited — tier, status, counted confidence.
 *
 * Nothing here paints before it knows what it is showing: a read in flight says what is being
 * read, a read that failed says so with Retry, and an empty ledger says what would fill it.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { TableActions, tableFromElement } from "@/components/TableActions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loading, ReadFailed } from "@/components/ui/states";
import { claimsOf, getIdToken } from "@/lib/auth";
import { pct } from "@/lib/format";
import { markClaimWrong, type Claim, type MarkedWrong } from "@/lib/record";

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

const ACTOR_KEY = "aughor_record_actor";

export interface Actor {
  /** A sign-in names the reader; the server records it and nothing here is sent. */
  signedIn: boolean;
  name: string;
  setName: (v: string) => void;
  /** What a write carries as `by`: the typed name without a sign-in, nothing with one. */
  by: string | undefined;
}

/**
 * Who a page writes as. With a sign-in the server records the person and the form asks nothing.
 * Without one, a form that records a person's act asks for a name — once, remembered on this
 * browser — because "nobody identified marked this wrong" is not a record anyone can use.
 */
export function useActor(): Actor {
  const [signedIn] = useState(() => {
    try { return !!claimsOf(getIdToken())?.email; } catch { return false; }
  });
  const [name, setNameState] = useState(() => {
    try { return window.localStorage.getItem(ACTOR_KEY) ?? ""; } catch { return ""; }
  });
  const setName = useCallback((v: string) => {
    setNameState(v);
    try { window.localStorage.setItem(ACTOR_KEY, v); } catch { /* a private window keeps it for the page */ }
  }, []);
  return { signedIn, name, setName, by: signedIn ? undefined : name.trim() || undefined };
}

/** The name a write is recorded under, asked only when no sign-in gives one. */
export function ActorField({ actor, id = "record-actor" }: { actor: Actor; id?: string }) {
  if (actor.signedIn) return null;
  return (
    <label htmlFor={id} style={{ display: "inline-flex", alignItems: "center", gap: 8 }}
      title="Nobody is signed in on this install, so the record keeps the name you give here.">
      <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Recorded as</span>
      <Input id={id} value={actor.name} onChange={e => actor.setName(e.target.value)} placeholder="your name" style={{ width: 150 }} />
    </label>
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
export function Ledger<T>({ name, columns, rows, rowKey, onOpen, empty, selected }: {
  name: string;
  columns: LedgerColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onOpen?: (row: T) => void;
  /** What an empty ledger says: what it holds once it holds something. */
  empty: React.ReactNode;
  selected?: string;
}) {
  const ref = useRef<HTMLTableElement>(null);
  if (rows.length === 0) return <Absent>{empty}</Absent>;
  return (
    <div>
      <div style={{ overflowX: "auto" }}>
        <table className="aug-dt" ref={ref}>
          <thead>
            {/* The first column is what the row IS; it keeps room to be read whatever the others hold. */}
            <tr>{columns.map((c, i) => (
              <th key={c.head} className={c.num ? "num" : undefined}
                style={{ width: c.width, minWidth: i === 0 && c.width === undefined ? 320 : undefined }}>{c.head}</th>
            ))}</tr>
          </thead>
          <tbody>
            {rows.map(row => {
              const key = rowKey(row);
              return (
                <tr key={key} aria-selected={selected === key || undefined}
                  onClick={onOpen ? () => onOpen(row) : undefined}
                  style={onOpen ? { cursor: "pointer" } : undefined}>
                  {columns.map((c, i) => (
                    <td key={c.head} className={c.num ? "num" : undefined}>
                      {i === 0 && onOpen
                        ? <Button variant="link" size="xs" className="aug-ledger-open"
                            onClick={e => { e.stopPropagation(); onOpen(row); }}>{c.cell(row)}</Button>
                        : c.cell(row)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 4 }}>
        <TableActions name={name} read={() => {
          if (!ref.current) return null;
          const t = tableFromElement(ref.current);
          const facts = columns.map((c, i) => (c.control ? -1 : i)).filter(i => i >= 0);
          return facts.length === columns.length
            ? t : { columns: facts.map(i => t.columns[i]), rows: t.rows.map(r => facts.map(i => r[i])) };
        }} />
      </div>
    </div>
  );
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
  return <StatusChip hue="muted" title="How this statement is warranted">{TIER_WORDS[tier] ?? tier}</StatusChip>;
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
  const ready = (hypothesis ? why.trim() : corrected.trim()) && (actor.signedIn || actor.by);
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      onMarked(await markClaimWrong(claim.id, { corrected: corrected.trim(), why: why.trim(), by: actor.by }));
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
