"use client";

/**
 * The Inbox — what the deep analyses recommended, and what became of each — laid out to CLARITY
 * (`aughor-v2/CLARITY.md`): four figures (open, in progress, verified, closed), then the reviews that came due in
 * amber with their answer on the row, then where the recommendations stand beside who they are for, then the list.
 *
 * A report keeps its recommendations as `recommendations` — `{ action, expected_impact, owner, timeline }` — and
 * an older or hand-built one as `recommended_actions`, plain strings. This page read only the second, so on an
 * install whose every report used the first it said "No pending recommendations" over seventeen of them. Both are
 * read now, in the order the report holds them: the index is the one the outcome and Execute doors key by.
 */
import { DropdownMenu } from "@radix-ui/themes";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ExecuteRecommendation as ExecuteButton } from "@/components/actions/ExecuteRecommendation";
import {
  Bar, CARD, Card, Chip, Dot, Empty, Figure, Figures, MUTED, NUM, NeedsYou, ONE_LINE, ROW, RULE, type Tone,
} from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Segmented } from "@/components/ui/segmented";
import { Loading, ReadFailed } from "@/components/ui/states";
import { getInvestigationOutcomes as readOutcomes, logOutcome, type RecOutcome, type RecStatus } from "@/lib/api";
import { getApiBase } from "@/lib/config";
import { countNoun, formatCount } from "@/lib/format";
import { dayWords } from "@/lib/home";
import { runDisplayTitle } from "@/lib/runTitle";

/** How many of the newest deep analyses the page reads — said on the page, never implied. */
const READ = 20;

const TERMINAL: RecStatus[] = ["verified", "rejected", "dismissed"];
const STATUSES: RecStatus[] = ["accepted", "implemented", "verified", "rejected", "dismissed"];

/** A status as a mark: its word and its colour. "Proposed" is a model's suggestion nobody has decided on (violet). */
const MARK: Record<RecStatus | "proposed", { word: string; color: string; tone: Tone }> = {
  proposed: { word: "proposed", color: "var(--vio4)", tone: "violet" },
  accepted: { word: "accepted", color: "var(--blue4)", tone: "accent" },
  implemented: { word: "implemented", color: "var(--blue4)", tone: "accent" },
  verified: { word: "verified", color: "var(--grn4)", tone: "up" },
  rejected: { word: "rejected", color: "var(--red4)", tone: "down" },
  dismissed: { word: "dismissed", color: "var(--t3)", tone: "plain" },
};

/** One recommendation as the page reads it. */
export interface Rec { action: string; impact: string; owner: string; timeline: string }

/** A report's recommendations, in the order the report holds them, from either shape it may keep them in. */
export function readRecs(report: unknown): Rec[] {
  const r = (report && typeof report === "object" ? report : {}) as Record<string, unknown>;
  const raw = Array.isArray(r.recommendations) && r.recommendations.length ? r.recommendations
    : Array.isArray(r.recommended_actions) ? r.recommended_actions : [];
  return raw.map(item => {
    if (typeof item === "string") return { action: item.trim(), impact: "", owner: "", timeline: "" };
    const o = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
    const text = (k: string) => (typeof o[k] === "string" ? (o[k] as string).trim() : "");
    const impact = text("expected_impact");
    return { action: text("action") || text("text"), impact: /^n\/?a$/i.test(impact) ? "" : impact,
      owner: text("owner"), timeline: text("timeline") };
  }).filter(x => x.action);
}

/** The analyses the list endpoint returns, as this page uses them. */
interface Analysis {
  id: string; question: string; headline: string | null; status: string; kind: string;
  started_at: string; completed_at: string | null;
}

interface Item { run: Analysis; recs: Rec[] }

const keyOf = (runId: string, index: number) => `${runId}:${index}`;
const isOpen = (o: RecOutcome | undefined) => !o || !TERMINAL.includes(o.status);
const titleOf = (run: Analysis) => run.headline?.trim() || runDisplayTitle(run.question).title;

/** "by 18 Oct" for a date the report set; the model's own words ("Next 7 days") otherwise. */
function timelineWords(t: string): string {
  if (!t) return "";
  return /^\d{4}-\d{2}-\d{2}$/.test(t) ? `by ${dayWords(t)}` : t.toLowerCase();
}

/** A date the report set that has passed while the recommendation is still open. */
function overdue(t: string, today: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(t) && t < today;
}

interface Props {
  onOpenInvestigation?: (runId: string) => void;
  /** Active workspace — scopes recommendations to its connections' deep analyses. */
  workspaceId?: string;
}

export function RecommendationInbox({ onOpenInvestigation, workspaceId }: Props) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [unread, setUnread] = useState<string[]>([]);
  const [outcomes, setOutcomes] = useState<Map<string, RecOutcome>>(new Map());
  const [filter, setFilter] = useState<"pending" | "all">("pending");
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick(t => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setFailed(null);
      try {
        const res = await fetch(`${getApiBase()}/investigations?limit=${READ}${workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : ""}`);
        if (!res.ok) throw new Error(`the list was refused (${res.status})`);
        const runs: Analysis[] = await res.json();
        const done = runs.filter(r => r.status === "complete" && r.kind === "investigation");
        const missed: string[] = [];
        const read = await Promise.all(done.map(async run => {
          try {
            const [detail, outs] = await Promise.all([
              fetch(`${getApiBase()}/investigations/${encodeURIComponent(run.id)}`)
                .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status))))),
              readOutcomes(run.id),
            ]);
            return { run, recs: readRecs(detail?.report), outs };
          } catch {
            // Not skipped in silence: the page says how many analyses it could not read.
            missed.push(titleOf(run));
            return null;
          }
        }));
        if (cancelled) return;
        const got = read.filter((x): x is { run: Analysis; recs: Rec[]; outs: RecOutcome[] } => x !== null && x.recs.length > 0);
        const map = new Map<string, RecOutcome>();
        for (const x of got) for (const o of x.outs) map.set(keyOf(x.run.id, o.rec_index), o);
        setOutcomes(map);
        setItems(got.map(({ run, recs }) => ({ run, recs })));
        setUnread(missed);
      } catch (e) {
        if (!cancelled) { setFailed(e instanceof Error ? e.message : String(e)); setItems(null); }
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [workspaceId, tick]);

  const onOutcome = useCallback((o: RecOutcome) => {
    setOutcomes(prev => new Map(prev).set(keyOf(o.inv_id, o.rec_index), o));
  }, []);

  const rows = useMemo(() => {
    const out: { run: Analysis; rec: Rec; index: number; outcome: RecOutcome | undefined }[] = [];
    for (const it of items ?? []) it.recs.forEach((rec, index) => out.push({ run: it.run, rec, index, outcome: outcomes.get(keyOf(it.run.id, index)) }));
    // Open first, then the newest analysis first, then the report's own order.
    const when = (r: Analysis) => r.completed_at ?? r.started_at;
    return out.sort((a, b) => Number(isOpen(b.outcome)) - Number(isOpen(a.outcome))
      || when(b.run).localeCompare(when(a.run)) || a.index - b.index);
  }, [items, outcomes]);

  if (failed !== null) {
    return <ReadFailed what="the recommendations" error={failed} onRetry={reload} />;
  }
  if (items === null) return <Loading what="the recommendations" />;

  const count = (pred: (o: RecOutcome | undefined) => boolean) => rows.filter(r => pred(r.outcome)).length;
  const open = count(isOpen);
  const inProgress = count(o => o?.status === "accepted" || o?.status === "implemented");
  const verified = count(o => o?.status === "verified");
  const rejected = count(o => o?.status === "rejected");
  const dismissed = count(o => o?.status === "dismissed");
  const runsWithOpen = new Set(rows.filter(r => isOpen(r.outcome)).map(r => r.run.id)).size;
  const due = rows.filter(r => r.outcome?.review_question && isOpen(r.outcome));
  const visible = filter === "pending" ? rows.filter(r => isOpen(r.outcome)) : rows;
  const today = new Date().toISOString().slice(0, 10);

  return (
    <div data-testid="inbox" style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 1180 }}>
      <Figures testId="inbox-figures">
        <Figure testId="inbox-fig-open" label="Open" value={formatCount(open)}
          title={`Recommendations nobody has verified, rejected or dismissed, from the newest ${READ} deep analyses`}
          sub={<>
            <span>{open ? `from ${countNoun(runsWithOpen, "deep analysis", "deep analyses")}` : "nothing open"}</span>
            <Chip title={`Only the newest ${READ} deep analyses are read here`}>newest {READ} read</Chip>
          </>} />
        <Figure testId="inbox-fig-progress" label="In progress" value={formatCount(inProgress)} sub="accepted or implemented" />
        <Figure testId="inbox-fig-verified" label="Verified" value={formatCount(verified)} sub="checked again and held" />
        <Figure testId="inbox-fig-closed" label="Closed" value={formatCount(rejected + dismissed)}
          sub={`${rejected} rejected · ${dismissed} dismissed`} />
      </Figures>

      {unread.length > 0 && (
        <div className="aug-fs-xs" style={ROW}>
          <Chip tone="amber" title={unread.join("\n")}>{countNoun(unread.length, "deep analysis", "deep analyses")} could not be read</Chip>
          <Button variant="link" size="xs" onClick={reload}>Retry</Button>
        </div>
      )}

      <NeedsYou testId="inbox-needs" waiting={due.length > 0} right={due.length ? `${countNoun(due.length, "review")} due` : undefined}>
        {due.length === 0 ? (
          <Empty title="When a recommendation is accepted, a review date is set; on that day its question is asked here">
            No review has come due.
          </Empty>
        ) : due.map((r, i) => (
          <DueRow key={keyOf(r.run.id, r.index)} first={i === 0} runId={r.run.id} index={r.index} rec={r.rec}
            outcome={r.outcome!} onOutcome={onOutcome} />
        ))}
      </NeedsYou>

      {rows.length > 0 && (
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-start" }}>
          <div style={{ flex: "1 1 340px", minWidth: 0 }}>
            <Card label="Where they stand" testId="inbox-funnel" right={`${countNoun(rows.length, "recommendation")}`}>
              <Funnel rows={rows.map(r => r.outcome)} />
            </Card>
          </div>
          <div style={{ flex: "1 1 340px", minWidth: 0 }}>
            <Card label="Who they are for" testId="inbox-owners" right="open · by owner">
              <Owners recs={rows.filter(r => isOpen(r.outcome)).map(r => r.rec)} />
            </Card>
          </div>
        </div>
      )}

      <section aria-label="Recommendations" data-testid="inbox-list" style={CARD}>
        <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, color: "var(--t3)",
          textTransform: "uppercase", letterSpacing: ".06em" }}>
          Recommendations
          <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }}>
            <Segmented label="Which recommendations" value={filter} onChange={setFilter}
              options={[{ value: "pending", label: "Open" }, { value: "all", label: "All" }]} />
          </span>
        </div>
        {visible.length === 0 ? (
          <Empty title="Recommendations arrive from deep analyses; one needing your decision lands here">
            {filter === "pending"
              ? (rows.length ? "Every recommendation here has been decided." : `No recommendation in the newest ${READ} deep analyses.`)
              : `No recommendation in the newest ${READ} deep analyses.`}
          </Empty>
        ) : visible.map((r, i) => (
          <RecRow key={keyOf(r.run.id, r.index)} first={i === 0} run={r.run} index={r.index} rec={r.rec}
            outcome={r.outcome} today={today} onOutcome={onOutcome} onOpen={onOpenInvestigation} />
        ))}
      </section>
    </div>
  );
}

// ── the picture ──────────────────────────────────────────────────────────────────────────

const RANK: Partial<Record<RecStatus, number>> = { accepted: 1, implemented: 2, verified: 3 };

/** The process a recommendation goes through, as stage · bar · count: how many reached at least each stage. */
function Funnel({ rows }: { rows: (RecOutcome | undefined)[] }) {
  const reached = (n: number) => rows.filter(o => (o ? RANK[o.status] ?? -1 : 0) >= n).length;
  const stages: [string, number][] = [["Proposed", rows.length], ["Accepted", reached(1)], ["Implemented", reached(2)], ["Verified", reached(3)]];
  const off = rows.filter(o => o?.status === "rejected").length;
  const gone = rows.filter(o => o?.status === "dismissed").length;
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "96px minmax(0, 1fr) 40px", gap: "7px 10px", alignItems: "center" }}>
        {stages.map(([stage, n], i) => (
          <div key={stage} style={{ display: "contents" }}>
            <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>{stage}</span>
            <Bar value={n} max={rows.length} color={i === 0 ? "var(--chart-3)" : "var(--chart-1)"} />
            <span className="aug-fs-sm" style={{ ...NUM, textAlign: "right", color: "var(--t1)" }}>{formatCount(n)}</span>
          </div>
        ))}
      </div>
      <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 8 }}>{off} rejected · {gone} dismissed</div>
    </div>
  );
}

function Owners({ recs }: { recs: Rec[] }) {
  if (recs.length === 0) return <Empty>Nothing open.</Empty>;
  const by = new Map<string, number>();
  for (const r of recs) by.set(r.owner || "no owner named", (by.get(r.owner || "no owner named") ?? 0) + 1);
  const ranked = [...by.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const top = ranked.slice(0, 5);
  const max = top[0]?.[1] ?? 1;
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 190px) minmax(0, 1fr) 40px", gap: "7px 10px", alignItems: "center" }}>
        {top.map(([owner, n]) => (
          <div key={owner} style={{ display: "contents" }}>
            <span className="aug-fs-sm" style={{ ...ONE_LINE, color: owner === "no owner named" ? "var(--t3)" : "var(--t2)" }} title={owner}>{owner}</span>
            <Bar value={n} max={max} />
            <span className="aug-fs-sm" style={{ ...NUM, textAlign: "right", color: "var(--t1)" }}>{formatCount(n)}</span>
          </div>
        ))}
      </div>
      {ranked.length > 5 && (
        <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 8 }} title={ranked.slice(5).map(([o, n]) => `${o} · ${n}`).join("\n")}>
          +{ranked.length - 5} more owners · {formatCount(ranked.slice(5).reduce((s, [, n]) => s + n, 0))} open
        </div>
      )}
    </div>
  );
}

// ── rows ─────────────────────────────────────────────────────────────────────────────────

/** Mark a recommendation; a write that failed says so on its row (it used to be swallowed). */
function useMark(runId: string, index: number, text: string, onOutcome: (o: RecOutcome) => void) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const mark = useCallback(async (status: RecStatus) => {
    setSaving(true);
    setError("");
    try { onOutcome(await logOutcome(runId, index, text, status)); }
    catch (e) { setError(`Not marked ${status} — ${e instanceof Error ? e.message : String(e)}`); }
    finally { setSaving(false); }
  }, [runId, index, text, onOutcome]);
  return { mark, saving, error };
}

function MarkMenu({ current, saving, onMark }: { current?: RecStatus; saving: boolean; onMark: (s: RecStatus) => void }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        <Button variant="outline" size="xs" disabled={saving}>
          {saving ? "Marking…" : current ? "Change" : "Mark"} <Icon name="chevd" size={12} />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content size="1" align="end">
        {STATUSES.map(s => (
          <DropdownMenu.Item key={s} disabled={s === current} onSelect={() => onMark(s)}>{MARK[s].word}</DropdownMenu.Item>
        ))}
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  );
}

function StatusMark({ status }: { status: RecStatus | "proposed" }) {
  const m = MARK[status];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: m.color }}>
      <Dot color={m.color} />{m.word}
    </span>
  );
}

function RecRow({ first, run, index, rec, outcome, today, onOutcome, onOpen }: {
  first: boolean; run: Analysis; index: number; rec: Rec; outcome: RecOutcome | undefined; today: string;
  onOutcome: (o: RecOutcome) => void; onOpen?: (runId: string) => void;
}) {
  const { mark, saving, error } = useMark(run.id, index, rec.action, onOutcome);
  const open = isOpen(outcome);
  const late = open && overdue(rec.timeline, today);
  const source = titleOf(run);
  return (
    <div data-testid="inbox-rec" style={{ padding: "9px 0", opacity: open ? 1 : 0.7, ...(first ? {} : RULE) }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12, alignItems: "center" }}>
        <div style={{ minWidth: 0 }}>
          <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)" }}
            title={rec.impact ? `${rec.action}\n\nExpected: ${rec.impact}` : rec.action}>{rec.action}</div>
          <div className="aug-fs-xs" style={{ ...ROW, gap: 6, color: "var(--t2)", marginTop: 2 }}>
            {/* Every open row is "proposed" until someone decides: a violet mark, the word on hover — said once, in the funnel. */}
            {outcome ? <StatusMark status={outcome.status} />
              : <span title="proposed — nobody has decided on it yet" style={{ display: "inline-flex" }}><Dot color={MARK.proposed.color} title="proposed" /></span>}
            {rec.owner && <span>{outcome ? "· " : ""}{rec.owner}</span>}
            {rec.timeline && (late
              ? <Chip tone="amber" title="The date the report set has passed and it is still open">was due {dayWords(rec.timeline)}</Chip>
              : <span>· {timelineWords(rec.timeline)}</span>)}
            {/* The analysis it came from, cut to one line; its question on hover. An ellipsis cannot cut a button,
                so the words inside it are what is cut. */}
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4, minWidth: 0, maxWidth: 440 }}
              title={`${runDisplayTitle(run.question).title} · ${dayWords(run.completed_at ?? run.started_at)}`}>
              <span style={{ flex: "0 0 auto" }}>· from</span>
              {onOpen
                ? <Button variant="link" size="xs" onClick={() => onOpen(run.id)}
                    style={{ height: "auto", padding: 0, margin: 0, minWidth: 0, flexShrink: 1 }}>
                    <span style={ONE_LINE}>{source}</span>
                  </Button>
                : <span style={ONE_LINE}>{source}</span>}
            </span>
          </div>
          {/* What acceptance decided: the baseline measured then, and the review date. */}
          {outcome?.baseline_at && (
            <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 2 }}>
              {outcome.baseline_value != null
                ? `baseline ${outcome.metric_name ?? "metric"} ${outcome.baseline_value} (${outcome.baseline_window})`
                : `baseline not measured${outcome.review_note ? `: ${outcome.review_note}` : ""}`}
              {outcome.review_at ? ` · review ${dayWords(outcome.review_at)}` : ""}
            </div>
          )}
        </div>
        <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <ExecuteButton invId={run.id} index={index} />
          {open && <MarkMenu current={outcome?.status} saving={saving} onMark={s => void mark(s)} />}
        </span>
      </div>
      {error && <div className="aug-fs-xs" role="alert" style={{ color: "var(--red4)", marginTop: 4 }}>{error}</div>}
    </div>
  );
}

/** A review that came due: the question it asks, answered on the row. */
function DueRow({ first, runId, index, rec, outcome, onOutcome }: {
  first: boolean; runId: string; index: number; rec: Rec; outcome: RecOutcome; onOutcome: (o: RecOutcome) => void;
}) {
  const { mark, saving, error } = useMark(runId, index, rec.action, onOutcome);
  return (
    <div data-testid="inbox-due" style={{ padding: "8px 0", ...(first ? {} : RULE) }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12, alignItems: "center" }}>
        <div style={{ minWidth: 0 }}>
          <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }} title={rec.action}>{rec.action}</div>
          <div className="aug-fs-xs" style={{ ...ONE_LINE, color: "var(--t2)" }} title={outcome.review_question}>
            {outcome.review_question}{outcome.review_asked_to ? ` · asked to ${outcome.review_asked_to}` : ""}
          </div>
        </div>
        <span style={{ display: "inline-flex", gap: 6 }}>
          <Button size="xs" variant="secondary" disabled={saving} onClick={() => void mark("verified")}>Verified</Button>
          <Button size="xs" variant="ghost" disabled={saving} onClick={() => void mark("rejected")}>Rejected</Button>
        </span>
      </div>
      {error && <div className="aug-fs-xs" role="alert" style={{ color: "var(--red4)", marginTop: 4 }}>{error}</div>}
    </div>
  );
}
