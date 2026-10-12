"use client";

/**
 * The Briefing as a morning paper. The user, 2026-10-12: *"more like reading a newspaper where you show
 * more the synthesis or the interpretation of the findings … the trends … the gaps … a starting point
 * for my decision-making in the morning"*. The approved mockup is `design-mockups/briefing.html`.
 *
 * Presentational pieces only — `BriefingPanel` owns the state and the reads. The lead story is the
 * narrator's; the three columns are the desk's (`aughor/briefing/desk.py`: records, never a model);
 * every claim on the page carries a numbered source, listed at the foot.
 */
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { changeOf } from "@/components/brief/MetricDetail";
import { requestTab } from "@/lib/navigate";
import type { BriefingDesk, BriefingRangeBlock, DeskColumn, DeskItem } from "@/lib/api";

const SERIF = "var(--font-serif)";
const RULE = "1px solid var(--b1)";

/** Today in words: "Monday 12 October 2026". */
export function paperDate(d: Date): string {
  const weekday = d.toLocaleDateString("en-GB", { weekday: "long" });
  return `${weekday} ${d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}`;
}

/** The desk's stories in reading order (trends, gaps, decide), numbered on from the lead's own
 *  citations so one list of sources serves the whole page. */
export function numberDesk(desk: BriefingDesk | null, first: number): Map<DeskItem, number> {
  const out = new Map<DeskItem, number>();
  let n = first;
  for (const col of [desk?.trends, desk?.gaps, desk?.decide]) for (const it of col?.items ?? []) out.set(it, n++);
  return out;
}

/** Where a story's button leads: an inquiry opens in the Record, a metric in the Semantic Layer. */
export function openDeskAction(a: NonNullable<DeskItem["action"]>, connectionId: string): void {
  if (a.kind === "inquiry") requestTab("record", { layer: "inquiries", id: a.ref });
  else requestTab("semantic", { conn: connectionId, metric: a.ref });
}

export function PaperMasthead({ scope, edition, tools }: { scope: string; edition: ReactNode; tools: ReactNode }) {
  return (
    <div data-testid="paper-masthead" style={{ display: "flex", alignItems: "flex-end", gap: 14, flexWrap: "wrap",
      paddingBottom: 10, borderBottom: "2px solid var(--t1)" }}>
      <h1 style={{ fontFamily: SERIF, fontSize: 28, fontWeight: 600, margin: 0, lineHeight: 1, letterSpacing: "-0.01em" }}>The Briefing</h1>
      <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>{scope}</span>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>{edition}{tools}</div>
    </div>
  );
}

export function PaperDateline({ today, covers, lagDays, records }: {
  today: string; covers: string; lagDays?: number | null; records: number;
}) {
  return (
    <div className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", padding: "7px 0",
      borderBottom: RULE, color: "var(--t3)" }}>
      <b style={{ color: "var(--t2)", fontWeight: 500 }}>{today}</b>
      <span>{covers}</span>
      {typeof lagDays === "number" && lagDays >= 7 && (
        <span className="aug-fs-xs" style={{ padding: "2px 8px", borderRadius: "var(--r-pill)", background: "var(--amb1)", color: "var(--amb4)" }}>
          data settles {lagDays} days late
        </span>
      )}
      {records > 0 && <span style={{ marginLeft: "auto" }}>grounded in {records} record{records === 1 ? "" : "s"}</span>}
    </div>
  );
}

/** The front: the lead story beside the numbers box, a rule between them. */
export function PaperFront({ lead, side }: { lead: ReactNode; side: ReactNode }) {
  return (
    <div data-testid="paper-front" style={{ display: "grid", gridTemplateColumns: "minmax(0, 2.1fr) minmax(260px, 1fr)",
      padding: "20px 0 18px", borderBottom: RULE }}>
      <div style={{ paddingRight: 28, borderRight: RULE, minWidth: 0 }}>{lead}</div>
      <div style={{ paddingLeft: 24, minWidth: 0 }}>{side}</div>
    </div>
  );
}

export function PaperLead({ kicker, headline, children }: { kicker: string; headline: ReactNode; children?: ReactNode }) {
  return (
    <div data-testid="paper-lead">
      <div className="aug-fs-xs" style={{ letterSpacing: "0.09em", textTransform: "uppercase", color: "var(--blue4)", marginBottom: 6 }}>{kicker}</div>
      {/* A long headline (a finding's sentence, when no story is written) prints smaller, never cut. */}
      <h2 style={{ fontFamily: SERIF, fontSize: typeof headline === "string" && headline.length > 90 ? 22 : 28, lineHeight: 1.18,
        fontWeight: 600, margin: "0 0 12px", maxWidth: typeof headline === "string" && headline.length > 90 ? "52ch" : "32ch" }}>{headline}</h2>
      {children}
    </div>
  );
}

export interface PaperNumber {
  key: string; label: string; value: string; change?: { text: string; sign: number }; unknown?: string;
  /** Said under the label when the figure is not the edition's own: other months, or part of one. */
  note?: string;
}

/** An edition's measured metrics as the numbers box prints them. A metric whose data ends before
 *  the range was measured over the latest months it covers (`anchored`): its row names those months,
 *  so "€14,306 −5%" is never read as this edition's move (LuxExperience's September 2026 edition,
 *  2026-10-12: three of its four figures were June 2025 and April 2024). A part-period figure says
 *  which days it holds. A metric not measured is said, never a zero. */
export function rangeNumbers(block: BriefingRangeBlock): PaperNumber[] {
  return [
    ...block.measured.map(m => {
      const t = changeOf(m, "previous");
      const days = m.current_partial ? `only ${m.current_partial}` : "";
      const own = m.anchored ? `${m.anchored.covers}, against ${m.anchored.compared_with} — its data ends ${m.anchored.data_ends}` : "";
      return { key: m.metric, label: m.name, value: m.current_text ?? "—",
               change: t && m.rel !== null ? { text: t, sign: Math.sign(m.rel) } : undefined,
               note: [own, days].filter(Boolean).join(" · ") || undefined };
    }),
    ...block.unmeasured.map(u => ({ key: `unmeasured:${u.name}`, label: u.name, value: "", unknown: "not measured" })),
  ];
}

/** The numbers box: one row per figure, its change against the comparison beside it; a figure the
 *  platform could not measure says so in the de-emphasis hatch, never as a zero. */
export function PaperNumbers({ title, rows, note }: { title: string; rows: PaperNumber[]; note?: string }) {
  return (
    <div data-testid="paper-numbers">
      <h3 style={{ fontFamily: SERIF, fontSize: 18, fontWeight: 600, margin: "0 0 8px" }}>{title}</h3>
      {rows.length === 0
        ? <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>No figure was measured for this edition.</div>
        : rows.map((r, i) => (
          <div key={r.key} style={{ display: "flex", alignItems: "baseline", gap: 10, padding: "6px 0", borderTop: i ? RULE : "none" }}>
            <span className="aug-fs-sm" style={{ color: "var(--t2)", minWidth: 0, flex: 1 }}>
              {r.label}
              {r.note && <span className="aug-fs-xs" data-testid="paper-number-note" style={{ display: "block", color: "var(--amb4)" }}>{r.note}</span>}
            </span>
            {r.unknown
              ? <span className="aug-fs-xs" style={{ color: "var(--t3)", padding: "0 6px", borderRadius: 3,
                  background: "repeating-linear-gradient(135deg, var(--b1) 0 4px, transparent 4px 8px)" }}>{r.unknown}</span>
              : <span style={{ fontWeight: 600, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
                  {r.value}
                  {r.change && <span className="aug-fs-xs" style={{ marginLeft: 6, fontWeight: 400,
                    color: r.change.sign > 0 ? "var(--grn4)" : r.change.sign < 0 ? "var(--red4)" : "var(--t3)" }}>{r.change.text}</span>}
                </span>}
          </div>
        ))}
      {note && <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 10 }}>{note}</div>}
    </div>
  );
}

const COLUMNS: { key: "trends" | "gaps" | "decide"; kicker: string; title: string; empty: string; tone: string }[] = [
  { key: "trends", kicker: "Trends · the longer view", title: "Trends", empty: "No trend was recorded in the last 30 days.", tone: "var(--grn4)" },
  { key: "gaps", kicker: "Gaps · what we can't see yet", title: "Gaps", empty: "Nothing the platform knows is missing.", tone: "var(--amb4)" },
  { key: "decide", kicker: "For your morning", title: "Decide today", empty: "Nothing is waiting on you.", tone: "var(--amb4)" },
];

function Story({ item, n, connectionId }: { item: DeskItem; n?: number; connectionId: string }) {
  // Said on an investigation's reading — one run's answer — where it changes how far to lean on it;
  // every recorded finding is provisional, so on those it would only repeat itself.
  const provisional = item.status === "Provisional" && item.kind === "answer";
  return (
    <div data-testid={`desk-${item.kind}`} style={{ padding: "10px 0", borderTop: RULE }} title={item.source.label}>
      <b style={{ display: "block", fontFamily: SERIF, fontSize: 15, fontWeight: 600, lineHeight: 1.3, marginBottom: 4, color: "var(--t1)" }}>
        {item.title.replace(/_/g, " ")}{!item.text && n ? <sup style={{ fontSize: 11, color: "var(--blue4)", marginLeft: 2 }}>{n}</sup> : null}
      </b>
      {item.text && (
        <p className="aug-fs-sm" style={{ margin: 0, lineHeight: 1.55, color: "var(--t2)" }}>
          {item.text}{n ? <sup style={{ fontSize: 11, color: "var(--blue4)", marginLeft: 2 }}>{n}</sup> : null}
        </p>
      )}
      {(item.action || provisional) && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
          {provisional && (
            <span className="aug-fs-xs" style={{ padding: "1px 8px", borderRadius: "var(--r-pill)", background: "var(--vio1)", color: "var(--vio4)" }}>provisional</span>
          )}
          {item.action && (
            <Button variant={item.kind === "proposed_run" ? "default" : "secondary"} size="xs"
              onClick={() => openDeskAction(item.action!, connectionId)}>{item.action.verb}</Button>
          )}
        </div>
      )}
    </div>
  );
}

function Column({ spec, col, unread, refs, connectionId }: {
  spec: (typeof COLUMNS)[number]; col: DeskColumn | null | undefined; unread?: string; refs: Map<DeskItem, number>; connectionId: string;
}) {
  const decide = spec.key === "decide";
  return (
    <div data-testid={`paper-col-${spec.key}`} style={decide
      ? { background: "var(--amb1)", borderRadius: "var(--r3)", padding: "14px 18px", minWidth: 0 }
      : { minWidth: 0 }}>
      <div className="aug-fs-xs" style={{ letterSpacing: "0.09em", textTransform: "uppercase", color: spec.tone, marginBottom: 4 }}>{spec.kicker}</div>
      <h3 style={{ fontFamily: SERIF, fontSize: 18, fontWeight: 600, margin: "0 0 6px" }}>{spec.title}</h3>
      {col === undefined && <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>Reading…</div>}
      {col === null && <div className="aug-fs-sm" style={{ color: "var(--amb4)" }}>{unread ?? "This column could not be read just now."}</div>}
      {col && col.items.length === 0 && <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>{spec.empty}</div>}
      {col?.items.map(it => <Story key={`${it.kind}:${it.source.ref}:${it.title}`} item={it} n={refs.get(it)} connectionId={connectionId} />)}
      {!!col?.more && (
        <Button variant="ghost" size="xs" onClick={() => requestTab("record", { layer: "inquiries" })}
          style={{ color: "var(--t3)", padding: "6px 0 0" }}>{col.more} more in the Record →</Button>
      )}
    </div>
  );
}

/** Trends · Gaps · Decide — the desk's three columns. `desk` undefined while it is read, null when
 *  the read failed (then `error` is said in every column). */
export function DeskColumns({ desk, error, refs, connectionId }: {
  desk: BriefingDesk | null | undefined; error?: string | null; refs: Map<DeskItem, number>; connectionId: string;
}) {
  const unreadWord = (k: "trends" | "gaps" | "decide") =>
    error ?? (k === "trends" ? desk?.unread?.claims : desk?.unread?.inquiries ?? desk?.unread?.metrics);
  return (
    <div data-testid="paper-desk" style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 22,
      padding: "18px 0", borderBottom: RULE }}>
      {COLUMNS.map(spec => (
        <Column key={spec.key} spec={spec} connectionId={connectionId} refs={refs}
          col={error ? null : desk === undefined ? undefined : desk ? desk[spec.key] : null} unread={unreadWord(spec.key)} />
      ))}
    </div>
  );
}

/** In brief — what the platform knows, one line each, and the door to every finding. */
export function InBrief({ items, total, onAll, allOpen, title, empty, standing }: {
  items: { id: string; node: ReactNode }[]; total: number; onAll: () => void; allOpen: boolean; title: string;
  /** What an empty list says (a range's: measuring, failed, or why nothing was measured). */
  empty?: string;
  /** Under a range: leads to What we know, where every finding is. */
  standing?: () => void;
}) {
  return (
    <div data-testid="paper-brief" style={{ padding: "16px 0", borderBottom: RULE }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 6 }}>
        <h3 style={{ fontFamily: SERIF, fontSize: 18, fontWeight: 600, margin: 0 }}>{title}</h3>
        {total > 0 && (
          <Button variant="ghost" size="xs" onClick={onAll} style={{ marginLeft: "auto", color: "var(--blue4)" }}>
            {allOpen ? "Hide the findings ▴" : `All ${total} finding${total === 1 ? "" : "s"} →`}
          </Button>
        )}
      </div>
      {items.length === 0
        ? <div className="aug-fs-sm" data-testid="paper-brief-empty" style={{ color: "var(--t3)" }}>
            {empty ?? "No finding to report in this edition."}
            {standing && (
              <Button variant="ghost" size="xs" onClick={standing} style={{ marginLeft: 8, color: "var(--blue4)" }}>What we know →</Button>
            )}
          </div>
        : <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", columnGap: 34 }}>
            {items.map(it => (
              <div key={it.id} className="aug-fs-sm" style={{ lineHeight: 1.5, color: "var(--t2)", padding: "6px 0", borderTop: RULE }}>{it.node}</div>
            ))}
          </div>}
    </div>
  );
}

export function PaperSources({ refs }: { refs: { n: number; label: string; onOpen?: () => void }[] }) {
  if (refs.length === 0) return null;
  return (
    <div data-testid="paper-sources" className="aug-fs-xs" style={{ padding: "14px 0 0", color: "var(--t3)", lineHeight: 1.7, columns: 2, columnGap: 34 }}>
      {refs.map(r => (
        <div key={r.n} style={{ breakInside: "avoid" }}>
          <span style={{ color: "var(--blue4)", marginRight: 4 }}>{r.n}</span>
          {/* A span, not a button element: a button never wraps inline, so a long label broke away from its number. */}
          {r.onOpen
            ? <span role="button" tabIndex={0} onClick={r.onOpen} onKeyDown={e => { if (e.key === "Enter") r.onOpen!(); }}
                style={{ cursor: "pointer" }}>{r.label}</span>
            : r.label}
        </div>
      ))}
    </div>
  );
}

export function AskBar({ onOpen }: { onOpen: () => void }) {
  return (
    <Button variant="ghost" data-testid="paper-ask" onClick={onOpen} className="h-auto w-full justify-start"
      style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 18, padding: "10px 12px",
        background: "var(--bg-1)", borderRadius: "var(--r3)", cursor: "text", textAlign: "left" }}>
      <span className="aug-fs-sm" style={{ flex: 1, color: "var(--t3)" }}>Ask a follow-up about this briefing…</span>
      <span className="aug-fs-sm" style={{ padding: "4px 12px", borderRadius: "var(--r2)", background: "var(--blue3)", color: "var(--t1)" }}>Ask</span>
    </Button>
  );
}
