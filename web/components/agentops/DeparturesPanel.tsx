"use client";

import { destinationLabel } from "@/lib/names";
import { requestTab } from "@/lib/navigate";
import { askSpotlight } from "@/lib/commandRegistry";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import {
  answerDeparture, getDepartureSummary, getDepartures, markDeparture,
  type Departure, type DepartureSummary, type RemedyDoor,
} from "@/lib/api";
import {
  GUARD_LABEL,
  addressedText, departureFromUrl, filterDepartures, guardRows, kindLabel, outcomeColor,
  outcomeWord, owes, readingsOf, sourceName, stateHue, stateLabel, summaryLine, whenText,
  type DepartureFilter,
} from "@/lib/departures";
import { StatusChip } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { SkeletonRows } from "@/components/ui/motion";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const FILTERS: { id: DepartureFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "owed", label: "Needs a person" },
  { id: "held", label: "Held" },
  { id: "departed", label: "Departed" },
];

/**
 * HB-2 — the departures screen: everything the platform sent out, and everything the
 * departure gate kept in, with its reasons. The two things a person owes it live here too —
 * a declarer marking an automation still on probation, and an owner choosing between two
 * readings of a metric that disagreed. Hub-wide by definition, like the Hub map beside it.
 */
/** The screens a remedy can open — handed down by the workspace, which owns the layers. */
interface Doors {
  onOpenAutomation?: () => void;
  onOpenTrace?: (analysisId: string) => void;
}

export function DeparturesPanel({ onOpenAutomation, onOpenTrace }: Doors = {}) {
  const doors: Doors = { onOpenAutomation, onOpenTrace };
  const [rows, setRows] = useState<Departure[]>([]);
  const [summary, setSummary] = useState<DepartureSummary | null>(null);
  const [absent, setAbsent] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<DepartureFilter>("all");
  // A receipt's link names one departure: open it, once.
  const [focusId] = useState(() =>
    typeof window === "undefined" ? "" : departureFromUrl(window.location.search));
  const [openId, setOpenId] = useState(focusId);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    Promise.all([getDepartures({ limit: 200 }), getDepartureSummary()])
      .then(([list, counts]) => {
        setAbsent(list === null);
        setRows(list ?? []);
        setSummary(counts);
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!focusId || typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    params.delete("departure");
    const qs = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
  }, [focusId]);

  useEffect(() => {
    if (!focusId || !rows.some(r => r.id === focusId) || typeof document === "undefined") return;
    document.querySelector(`[data-departure="${focusId}"]`)?.scrollIntoView?.({ block: "center" });
  }, [focusId, rows]);

  const shown = useMemo(() => filterDepartures(rows, filter), [rows, filter]);

  if (loading && rows.length === 0 && !error) {
    return <div style={{ flex: 1, background: "var(--bg-0)", padding: 16 }}><SkeletonRows rows={6} /></div>;
  }

  if (error) {
    return (
      <div style={{ flex: 1, background: "var(--bg-0)", padding: 24 }}>
        <div className="aug-fs-sm" style={{ color: "var(--amb3)", marginBottom: 10 }}>
          Could not read the departures ledger — {error}
        </div>
        <Button variant="outline" size="xs" onClick={load}>Retry</Button>
      </div>
    );
  }

  if (absent) {
    return (
      <EmptyState icon="send" title="No departures ledger on this API">
        This API predates the departure gate&apos;s ledger (HB-2). Update the server and reload.
      </EmptyState>
    );
  }

  const by = summary?.by_state ?? {};
  const held = (by.held ?? 0) + (by.held_probation ?? 0) + (by.held_owner ?? 0);

  return (
    <div style={{ flex: 1, background: "var(--bg-0)", display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 14, padding: "10px 16px 8px",
        borderBottom: "1px solid var(--b1)", flexWrap: "wrap",
      }}>
        <span className="aug-fs-ui" style={{ fontWeight: 600, color: "var(--t1)" }}>
          What left the platform, and what was held
        </span>
        {summary && (
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            {by.departed ?? 0} departed · {held} held · {summary.awaiting} need a person
          </span>
        )}
        <span style={{ flex: 1 }} />
        <div role="group" aria-label="Filter departures" style={{ display: "flex", gap: 4 }}>
          {FILTERS.map(f => (
            <Button key={f.id} size="xs" variant={filter === f.id ? "secondary" : "ghost"}
              aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
              {f.label}
            </Button>
          ))}
        </div>
        <Button variant="outline" size="xs" onClick={load}>Refresh</Button>
      </div>

      {rows.length === 0 ? (
        <EmptyState icon="send" title="Nothing has left yet">
          Every Slack post, webhook, ticket, alert and scheduled briefing is judged here before
          it leaves. The ledger fills with the first one.
        </EmptyState>
      ) : shown.length === 0 ? (
        <EmptyState variant="inline" title="Nothing under this filter." />
      ) : (
        <div style={{ flex: 1, overflow: "auto", padding: "0 16px 16px" }}>
          {/* Fixed layout: a long reason truncates in its own column instead of pushing the
              Review door off the right edge (measured: 1,233px of table in 1,160px). */}
          <Table className="aug-dt" style={{ tableLayout: "fixed" }}>
            <TableHeader>
              <TableRow>
                <TableHead style={{ width: 132 }}>When</TableHead>
                <TableHead style={{ width: "30%" }}>What, and where to</TableHead>
                <TableHead style={{ width: 172 }}>State</TableHead>
                <TableHead>Why</TableHead>
                <TableHead style={{ width: 84 }} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map(d => (
                <DepartureRow key={d.id} departure={d} open={openId === d.id} doors={doors}
                  focused={focusId === d.id}
                  onToggle={() => setOpenId(openId === d.id ? "" : d.id)}
                  onChanged={load} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function DepartureRow({ departure: d, open, focused, onToggle, onChanged, doors }: {
  departure: Departure;
  open: boolean;
  focused: boolean;
  onToggle: () => void;
  onChanged: () => void;
  doors: Doors;
}) {
  const owed = owes(d);
  return (
    <Fragment>
      <TableRow data-departure={d.id} aria-selected={focused || undefined}>
        <TableCell>
          <span className="aug-fs-xs" style={{ fontFamily: "var(--font-mono, monospace)", color: "var(--t2)", whiteSpace: "nowrap" }}>
            {whenText(d.ts)}
          </span>
        </TableCell>
        <TableCell>
          <div className="aug-fs-sm" title={sourceName(d)} style={{ color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis" }}>
            {sourceName(d)}
          </div>
          <div className="aug-fs-xs" style={{ color: "var(--t3)", overflow: "hidden", textOverflow: "ellipsis" }}>
            {kindLabel(d.kind)}{d.target ? <> → <span title={d.target}>{destinationLabel(d.target).label}</span></> : ""}
          </div>
        </TableCell>
        <TableCell>
          <StatusChip hue={stateHue(d)}>{stateLabel(d)}</StatusChip>
        </TableCell>
        <TableCell>
          <div className="aug-fs-xs" title={summaryLine(d)} style={{
            color: d.state === "departed" ? "var(--t3)" : "var(--t2)", whiteSpace: "normal",
            overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical", padding: "3px 0",
          }}>
            {summaryLine(d)}
          </div>
        </TableCell>
        <TableCell>
          <Button variant={owed ? "secondary" : "ghost"} size="xs" aria-expanded={open}
            onClick={onToggle}>
            {open ? "Hide" : owed ? "Review" : "Details"}
          </Button>
        </TableCell>
      </TableRow>
      {open && (
        <TableRow>
          <TableCell colSpan={5} style={{ background: "var(--bg-1)", whiteSpace: "normal" }}>
            <DepartureDetail departure={d} onChanged={onChanged} doors={doors} />
          </TableCell>
        </TableRow>
      )}
    </Fragment>
  );
}

function DepartureDetail({ departure: d, onChanged, doors }: {
  departure: Departure; onChanged: () => void; doors: Doors;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const owed = owes(d);
  const guards = guardRows(d);
  const analysisId = d.investigation_id;   // the wire field, read once
  // The wall, and the way past it: for every guard that held or asked, what it means, what
  // to change, and the screens that hold the fix (asked for 2026-09-25). Served on the row
  // (SP-15) from the one module beside the laws, so this screen, `platform_help` and
  // Spotlight's `explain` read the same words; absent on a departed row and on an older API.
  const remedy = d.remedy ?? null;
  const remedies = remedy?.guards ?? [];
  const door = (kind: RemedyDoor, guardLabel: string, summary: string) => {
    if (kind === "automation") {
      if (!doors.onOpenAutomation || !d.automation_id) return null;
      return <Button key={kind} variant="outline" size="xs" onClick={doors.onOpenAutomation}
        title={d.automation_name ? `Automations · ${d.automation_name}` : undefined}>Open Automations</Button>;
    }
    if (kind === "analysis") {
      if (!doors.onOpenTrace || !analysisId) return null;
      return <Button key={kind} variant="outline" size="xs"
        onClick={() => doors.onOpenTrace?.(analysisId)}>Open the analysis</Button>;
    }
    if (kind === "semantic") {
      return <Button key={kind} variant="outline" size="xs"
        onClick={() => requestTab("semantic", d.conn_id ? { conn: d.conn_id } : undefined)}>Open the Semantic Layer</Button>;
    }
    // The palette, with THIS hold as its object: the departure id travels beside the
    // question (SP-15), so the turn opens on this row's live state and the id is never
    // parsed out of the prose.
    return <Button key={kind} variant="ghost" size="xs"
      onClick={() => askSpotlight(
        `A departure was held by the ${guardLabel} guard: ${summary}. What does that mean, and what `
        + `should I change so the next run sends?`
        + (d.automation_name ? ` (automation "${d.automation_name}")` : ""),
        { kind: "departure", id: d.id })}>Ask Spotlight about this hold</Button>;
  };

  const act = async (run: () => Promise<string>) => {
    setBusy(true);
    setNote("");
    try {
      setNote(await run());
      onChanged();
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "8px 4px 12px" }}>
      {owed === "mark" && (
        <section aria-label="Mark this departure">
          <div className="aug-fs-sm" style={{ color: "var(--t1)", marginBottom: 6 }}>
            This automation is on probation: its sends reach {d.addressed_to || "its declarer"} first.
            Was this one worth sending?
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Button variant="secondary" size="xs" disabled={busy}
              onClick={() => act(async () => (await markDeparture(d.id, "accept")).graduated
                ? "Marked. It has graduated — its next sends reach the channel."
                : "Marked.")}>Accept</Button>
            <Button variant="outline" size="xs" disabled={busy}
              onClick={() => act(async () => { await markDeparture(d.id, "correct"); return "Marked."; })}>
              Needs correction
            </Button>
            <Button variant="destructive" size="xs" disabled={busy}
              onClick={() => act(async () => { await markDeparture(d.id, "reject"); return "Marked."; })}>
              Reject
            </Button>
          </div>
        </section>
      )}

      {owed === "answer" && (
        <section aria-label="Choose a reading">
          <div className="aug-fs-sm" style={{ color: "var(--t1)", marginBottom: 6 }}>
            {d.question.question || `The readings of ${d.question.metric_label || "a metric"} disagree.`}
          </div>
          <div className="aug-fs-xs" style={{ color: "var(--t3)", marginBottom: 8 }}>
            Nothing was sent. The reading you choose is remembered, and the next run uses it.
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {readingsOf(d.question).map(r => (
              <Button key={r.label} variant="outline" size="xs" disabled={busy}
                onClick={() => act(async () => {
                  await answerDeparture(d.id, r.label);
                  return `Remembered: ${r.label}.`;
                })}>
                {r.label}{r.preview ? ` ${r.preview}` : ""}
              </Button>
            ))}
          </div>
        </section>
      )}

      {note && <div role="status" className="aug-fs-xs" style={{ color: "var(--t2)" }}>{note}</div>}

      {d.verdict && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          Marked <StatusChip strength="soft" hue={d.verdict === "accept" ? "positive" : d.verdict === "reject" ? "negative" : "caution"}>{d.verdict}</StatusChip>
          {d.verdict_at ? ` · ${whenText(d.verdict_at)}` : ""}
        </div>
      )}
      {d.answer && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          Answered: {d.answer}{d.answered_at ? ` · ${whenText(d.answered_at)}` : ""} — remembered for the next run
        </div>
      )}
      {addressedText(d) && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>{addressedText(d)}</div>
      )}

      {d.reasons.length > 0 && (
        <section aria-label="Why it was held">
          <div className="aug-label" style={{ marginBottom: 4 }}>Why</div>
          <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 4 }}>
            {d.reasons.map((r, i) => (
              <li key={i} className="aug-fs-sm" style={{ color: "var(--t1)" }}>{r}</li>
            ))}
          </ul>
        </section>
      )}

      {remedy && remedies.length > 0 && (
        <section aria-label="What to do next">
          <div className="aug-label" style={{ marginBottom: 4 }}>What to do next</div>
          {d.state === "held" && (
            <div className="aug-fs-xs" style={{ color: "var(--t3)", marginBottom: 8 }}>{remedy.lead}</div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {remedies.map(g => (
              <div key={g.guard}>
                <div className="aug-fs-sm" style={{ color: "var(--t1)" }}>
                  <span style={{ fontWeight: 500 }}>{GUARD_LABEL[g.guard] ?? g.label}</span> — {g.meaning}
                </div>
                <div className="aug-fs-sm" style={{ color: "var(--t2)", marginTop: 2 }}>{g.action}</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                  {g.doors.map(kind => door(kind, GUARD_LABEL[g.guard] ?? g.label, g.reason))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {d.text_preview && (
        <section aria-label="The message">
          <div className="aug-label" style={{ marginBottom: 4 }}>The message</div>
          <div className="aug-fs-sm" style={{
            color: "var(--t2)", whiteSpace: "pre-wrap", borderLeft: "2px solid var(--b2)",
            paddingLeft: 10,
          }}>{d.text_preview}</div>
        </section>
      )}

      {guards.length > 0 && (
        <section aria-label="Guards">
          <div className="aug-label" style={{ marginBottom: 4 }}>Guards, in the order they ran</div>
          <div style={{ display: "grid", gridTemplateColumns: "max-content max-content 1fr", columnGap: 14, rowGap: 3 }}>
            {guards.map(g => (
              <Fragment key={g.guard}>
                <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>{g.label}</span>
                <span className="aug-fs-xs" style={{ color: outcomeColor(g.outcome) }}>{outcomeWord(g.outcome)}</span>
                <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{g.summary}</span>
              </Fragment>
            ))}
          </div>
        </section>
      )}

      {d.receipt.line && (
        <section aria-label="Receipt">
          <div className="aug-label" style={{ marginBottom: 4 }}>
            {d.state === "departed" ? "The receipt it carried" : "The receipt it would have carried"}
          </div>
          <div className="aug-fs-xs" style={{ fontFamily: "var(--font-mono, monospace)", color: "var(--t2)", wordBreak: "break-word" }}>
            {d.receipt.line}
          </div>
        </section>
      )}
    </div>
  );
}
