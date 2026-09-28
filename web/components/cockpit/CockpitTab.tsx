"use client";

/**
 * CockpitTab — a Data Canvas's cockpit (Arc CT-4; ROADMAP §3.50; flag `cockpit.composed`).
 *
 * What it does, in order: reads the canvas's cockpit and its cards from the server, runs
 * each card through the guard battery the way the Briefing's cockpit does, says each card's
 * status from its run, and hands the kept spec to `ComposedCockpit`.
 *
 * **No model is called here.** A cockpit is written once, approved, and drawn from then on.
 * The one way to get a first cockpit on this screen is `Start`, which groups the canvas's
 * cards by their kind in code.
 *
 * No title bar: the canvas already carries its name, and a panel does not repeat it. The
 * range control and the version line share one toolbar row.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { NewCardComposer } from "@/components/brief/NewCardComposer";
import { RangeControl, type RangeChoice } from "@/components/brief/BriefRange";
import type { CardState } from "@/components/brief/PinnedCardBody";
import { ComposedCockpit } from "@/components/cockpit/ComposedCockpit";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState, Refusal } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import {
  CockpitRefused, deleteDashboardCard, getCanvasCockpit, restoreCanvasCockpit, retireCanvasCockpit,
  runDashboardCard, startCanvasCockpit,
  type BriefingRange, type CanvasCockpit, type CockpitKept, type CockpitVersion, type DashboardCard,
} from "@/lib/api";
import { hostStateOf } from "@/lib/cockpit/hostStatus";
import { formatDateTime } from "@/lib/format";

const AS_WRITTEN = { label: "As written", title: "Every card as it was written, not cut to a range" };

const RANGE_SAYS: Record<CanvasCockpit["range"]["status"], string> = {
  standing: "",
  final: "Final",
  provisional: "Provisional",
  to_date: "To date",
};

function person(name: string): string {
  return name.replace(/^user:/, "") || "someone";
}

function VersionLine({ v }: { v: CockpitVersion }) {
  return (
    <span className="aug-fs-sm" data-testid="cockpit-version" style={{ color: "var(--t3)" }}>
      Version {v.version} · approved by {person(v.approved_by)} · {formatDateTime(v.kept_at)}
    </span>
  );
}

function changed(c: CockpitVersion["changes"]): string {
  const parts = [
    c.added.length ? `${c.added.length} added` : "",
    c.removed.length ? `${c.removed.length} removed` : "",
    c.changed.length ? `${c.changed.length} changed` : "",
  ].filter(Boolean);
  return parts.join(" · ") || "no change to its elements";
}

function History({ versions, busy, onGoBack }: {
  versions: CockpitVersion[]; busy: boolean; onGoBack: (n: number) => void;
}) {
  return (
    <ol data-testid="cockpit-history" style={{ listStyle: "none", margin: "0 0 12px", padding: 0, borderTop: "1px solid var(--b1)" }}>
      {versions.map(v => (
        <li key={v.artifact_id} className="aug-fs-sm" style={{
          display: "flex", alignItems: "baseline", gap: 12, padding: "7px 0",
          borderBottom: "1px solid var(--b1)", color: "var(--t2)",
        }}>
          <span style={{ color: "var(--t1)", fontWeight: 500, minWidth: 74 }}>Version {v.version}</span>
          <span style={{ flex: 1, minWidth: 0 }}>
            {v.retired ? "Retired" : changed(v.changes)} · {person(v.approved_by)} · {formatDateTime(v.kept_at)}
            {v.source ? ` · ${v.source}` : ""}{v.note ? ` · ${v.note}` : ""}
          </span>
          {v.current
            ? <span style={{ color: "var(--t3)" }}>current</span>
            : v.retired
              ? null
              : <Button variant="ghost" size="xs" disabled={busy} onClick={() => onGoBack(v.version)}>Go back to this</Button>}
        </li>
      ))}
    </ol>
  );
}

export function CockpitTab({ canvasId, connectionId, schema, active }: {
  canvasId: string;
  connectionId: string;
  schema?: string;
  /** False while another tab is showing: the cockpit keeps what it has and asks for nothing. */
  active: boolean;
}) {
  const [chosen, setChosen] = useState<RangeChoice>({ preset: "standing" });
  const [data, setData] = useState<CanvasCockpit | null>(null);
  const [cards, setCards] = useState<CardState[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "off" | "failed">("loading");
  const [problem, setProblem] = useState("");
  const [refusal, setRefusal] = useState<CockpitKept | null>(null);
  const [busy, setBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [tick, setTick] = useState(0);

  const range: BriefingRange | null = chosen.preset === "standing" ? null : chosen;
  const rangeKey = JSON.stringify(range);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    (async () => {
      try {
        const read = await getCanvasCockpit(canvasId, range);
        if (cancelled) return;
        if (read === null) { setState("off"); return; }
        const runs = await Promise.all(read.cards.map(async (card: DashboardCard): Promise<CardState> => {
          try { return { card, run: await runDashboardCard(card.id, range) }; }
          catch { return { card, failed: true }; }
        }));
        if (cancelled) return;
        setData(read); setCards(runs); setState("ready"); setProblem("");
      } catch (e) {
        if (cancelled) return;
        setProblem((e as Error).message || "The cockpit could not be read."); setState("failed");
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }, [canvasId, rangeKey, tick, active]);

  const reload = useCallback(() => setTick(t => t + 1), []);

  const write = useCallback(async (act: () => Promise<CockpitKept>, done: (k: CockpitKept) => string) => {
    setBusy(true); setRefusal(null);
    try {
      const kept = await act();
      toast.success(done(kept));
      reload();
    } catch (e) {
      if (e instanceof CockpitRefused) setRefusal(e.outcome);
      else toast.error("That did not go through", { description: (e as Error).message.slice(0, 160) });
    } finally { setBusy(false); }
  }, [reload]);

  const refreshOne = useCallback(async (id: string) => {
    try {
      const run = await runDashboardCard(id, range);
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, run, failed: false } : c)));
    } catch {
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, failed: true } : c)));
      toast.error("Couldn't refresh card", { description: "The query failed the trust guards or the source is unavailable." });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }, [rangeKey]);

  const removeOne = useCallback(async (id: string) => {
    try {
      await deleteDashboardCard(id);
      toast.success("Card removed from this canvas");
      reload();
    } catch {
      toast.error("Couldn't remove card", { description: "The card store didn't accept the delete — try again." });
    }
  }, [reload]);

  const doors = useMemo(() => ({ onRemove: removeOne, onRefresh: refreshOne }), [removeOne, refreshOne]);
  const host = useMemo(
    () => hostStateOf(data?.range.status ?? "standing", cards),
    [data?.range.status, cards],
  );

  if (state === "off") return null;
  if (state === "loading") {
    return <div className="aug-fs-sm" data-testid="cockpit-loading" style={{ padding: "24px 32px", color: "var(--t3)" }}>Reading the cockpit…</div>;
  }
  if (state === "failed" || !data) {
    return (
      <div style={{ padding: "24px 32px" }}>
        <ErrorState kind="Failed" what="The cockpit could not be read." means={problem}
          doors={[{ label: "Try again", onClick: reload, primary: true }]} />
      </div>
    );
  }

  const kept = data.cockpit;
  const drawn = kept && !kept.retired && kept.spec != null;

  return (
    <div data-testid="cockpit-tab" style={{ flex: 1, overflow: "auto", padding: "14px 32px 32px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
        {data.ranges_on && (
          <RangeControl value={chosen} onChange={setChosen} disabled={busy}
            standing={AS_WRITTEN} label="Cockpit range" />
        )}
        {data.range.status !== "standing" && (
          <span className="aug-fs-sm" data-testid="cockpit-range" style={{ color: "var(--t2)" }}>
            {RANGE_SAYS[data.range.status]} · {data.range.covers}
          </span>
        )}
        <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          {kept && <VersionLine v={kept} />}
          {data.history.length > 0 && (
            <Button variant="ghost" size="xs" aria-expanded={showHistory} onClick={() => setShowHistory(s => !s)}>
              {showHistory ? "Hide history" : "History"}
            </Button>
          )}
          {drawn && (
            <Button variant="ghost" size="xs" disabled={busy}
              onClick={() => write(() => retireCanvasCockpit(canvasId), () => "Cockpit retired. Its history stays.")}>
              Retire
            </Button>
          )}
        </span>
      </div>

      {showHistory && (
        <History versions={data.history} busy={busy}
          onGoBack={n => write(() => restoreCanvasCockpit(canvasId, n),
            k => (k.status === "unchanged" ? "That is the version you are on." : `Back to version ${n}, kept as version ${k.version}.`))} />
      )}

      {refusal && (
        <div style={{ marginBottom: 12 }}>
          <Refusal
            kind={refusal.status === "not_checked" ? "Not checked · nothing was kept" : "Refused · nothing was kept"}
            claim="The cockpit was not changed."
            detail={
              <ul data-testid="cockpit-write-refusal" style={{ margin: 0, paddingLeft: 18 }}>
                {refusal.sentences.map((s, i) => <li key={`${i}-${s.slice(0, 24)}`}>{s}</li>)}
              </ul>
            }
          />
        </div>
      )}

      <NewCardComposer connectionId={connectionId} schema={schema} onCreated={reload}
        keptFor={{ scope: "canvas", scopeRef: canvasId }} />

      {drawn ? (
        <ComposedCockpit spec={kept.spec} cards={cards} host={host} doors={doors} />
      ) : (
        <EmptyState
          icon="gauge"
          title={kept?.retired ? "This cockpit was retired" : "This canvas has no cockpit yet"}
          action={data.cards.length > 0 ? (
            <Button variant="secondary" size="sm" disabled={busy}
              onClick={() => write(() => startCanvasCockpit(canvasId), () => "Cockpit started from this canvas's cards.")}>
              {kept?.retired ? "Start a new one from this canvas's cards" : "Start one from this canvas's cards"}
            </Button>
          ) : undefined}
        >
          {kept?.retired
            ? `Retired by ${person(kept.approved_by)} on ${formatDateTime(kept.kept_at)}. Its earlier versions are in the history.`
            : data.cards.length > 0
              ? `This canvas holds ${data.cards.length} ${data.cards.length === 1 ? "card" : "cards"}. A cockpit arranges them in sections, and can show a card only while a condition holds. You can also ask for one in this canvas's chat.`
              : "A cockpit is made of cards. Add a card above and start a cockpit from it, or ask for one in this canvas's chat."}
        </EmptyState>
      )}
    </div>
  );
}
