"use client";

/**
 * BriefingStrip — the cockpit of the person's own that rides with their Briefing (the canvas,
 * docs/COCKPIT_CANVAS_2026-10-08.md, B1: "which cockpit strip rides with it").
 *
 * It is the same cockpit the Cockpit tab draws, read for the Briefing's range, and it is read
 * here, not arranged: the doors that change it — take off, resize, a note's words — are the
 * Cockpit tab's. A card may still be refreshed. No model is asked.
 */
import { useEffect, useMemo, useState } from "react";

import type { CardState } from "@/components/brief/PinnedCardBody";
import { ComposedCockpit, type CockpitDoors } from "@/components/cockpit/ComposedCockpit";
import type { ImageStamp } from "@/components/cockpit/StaticTile";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/ui/states";
import { cockpitImageUrl, getCockpit, runDashboardCard, type BriefingRange, type PersonCockpit } from "@/lib/api";
import { cardsPlaced } from "@/lib/cockpit/edit";
import { hostStateOf } from "@/lib/cockpit/hostStatus";

export function BriefingStrip({ connectionId, schema, cockpitId, range, onOpenCockpit }: {
  connectionId: string;
  schema?: string;
  cockpitId: string;
  range: BriefingRange | null;
  /** Open the Cockpit tab, where this cockpit is arranged. */
  onOpenCockpit?: () => void;
}) {
  const [data, setData] = useState<PersonCockpit | null>(null);
  const [cards, setCards] = useState<CardState[]>([]);
  const [problem, setProblem] = useState("");
  const [tick, setTick] = useState(0);
  const rangeKey = JSON.stringify(range ?? null);

  useEffect(() => {
    let cancelled = false;
    setProblem("");
    (async () => {
      try {
        const read = await getCockpit(connectionId, cockpitId, range);
        const placed = new Set(read.cockpit.spec ? cardsPlaced(read.cockpit.spec) : []);
        const runs = await Promise.all(read.cards.filter(c => placed.has(c.id)).map(async (card): Promise<CardState> => {
          try { return { card, run: await runDashboardCard(card.id, range, { compare: true }) }; }
          catch { return { card, failed: true }; }
        }));
        if (cancelled) return;
        setData(read); setCards(runs);
      } catch (e) {
        if (!cancelled) setProblem((e as Error).message || "The cockpit could not be read.");
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }, [connectionId, cockpitId, rangeKey, tick]);

  const doors = useMemo<CockpitDoors>(() => ({
    onRefresh: async (id: string) => {
      try {
        const run = await runDashboardCard(id, range, { compare: true });
        setCards(cs => cs.map(c => (c.card.id === id ? { ...c, run, failed: false } : c)));
      } catch { setCards(cs => cs.map(c => (c.card.id === id ? { ...c, failed: true } : c))); }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the range is read through its key
  }), [rangeKey]);
  const host = useMemo(() => hostStateOf(data?.range.status ?? "standing", cards), [data?.range.status, cards]);
  const images = useMemo<Record<string, ImageStamp>>(() => Object.fromEntries(
    Object.entries(data?.images ?? {}).map(([id, s]) => [id, { ...s, url: cockpitImageUrl(connectionId, id) }])), [data?.images, connectionId]);

  const kept = data?.cockpit;
  const title = kept?.spec ? String((kept.spec as { elements?: Record<string, { props?: { title?: string } }>; root?: string }).elements?.[(kept.spec as { root: string }).root]?.props?.title ?? "") : "";
  return (
    <div data-testid="briefing-strip" data-cockpit={cockpitId}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", marginBottom: 4 }}>
        <span className="aug-label" style={{ color: "var(--vio4)" }}>Your cockpit{title ? ` · ${title}` : ""}</span>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          read for {data?.range.covers || "the Briefing's range"} · arranged in the Cockpit tab
        </span>
        {onOpenCockpit && <Button size="xs" variant="ghost" onClick={onOpenCockpit}>Open it</Button>}
        {data && <Button size="xs" variant="ghost" style={{ marginLeft: "auto" }} onClick={() => setTick(t => t + 1)}>↻ Refresh</Button>}
      </div>
      {problem ? (
        <div className="aug-fs-sm" data-testid="briefing-strip-problem" style={{ color: "var(--t2)" }}>
          This cockpit could not be read: {problem}. It still stands in the Cockpit tab.
        </div>
      ) : !data ? (
        <Loading what="your cockpit" style={{ padding: "8px 0" }} />
      ) : kept?.retired || !kept?.spec ? (
        <div className="aug-fs-sm" data-testid="briefing-strip-retired" style={{ color: "var(--t2)" }}>
          This cockpit was retired. Choose another under Sections, or bring it back in the Cockpit tab.
        </div>
      ) : (
        <ComposedCockpit spec={kept.spec} cards={cards} host={host} doors={doors} sym={data.currency_symbol || "$"}
          images={images} range={range} schema={schema} />
      )}
    </div>
  );
}
