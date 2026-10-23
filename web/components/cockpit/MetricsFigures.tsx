"use client";

/**
 * The Metrics cockpit as figures — `design-mockups/cockpit-day-figures.html` (the user, 2026-10-12, on the figures-first
 * mockup drawn for the Briefing: "that is how I'd like my COCKPITS to look"). The order CLARITY sets: what moved most
 * (the hero: the figure, its change, this period against the one it is compared with as two bars), then every other
 * figure, then what needs a person, then the whole table behind Details.
 *
 * Nothing the table said is lost. A figure read for an earlier month because its data stops there says that month on
 * its card, never passes as this period's (it never leads, either); one still settling says so; a metric that cannot
 * be measured is a hatched card and its reason is said once, under Needs you, with the way to set it. The table — a
 * year earlier, the expected next band, each status, Copy and CSV — is kept mounted behind Details: its bands are
 * booked as predictions the first time a period is read, as they were.
 */
import { useState, type CSSProperties } from "react";

import { RangeMeasuresExpected } from "@/components/brief/BriefRange";
import { changeOf, useOpenMetric } from "@/components/brief/MetricDetail";
import { CARD, Chip, Figure, Figures, Label, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, ROW } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import type { BriefingRangeBlock, BriefingRangeMeasure } from "@/lib/api";
import { dayWords, endsWords, figurePeriods, heroOf, moveOf, olderFigures, sentence, spanWords, unmeasuredByReason, withLatest } from "@/lib/cockpit/figures";
import { countNoun } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { requestTab } from "@/lib/navigate";

/** The big figures under the hero; the rest go small, six to a row. */
const BIG = 4;

const SMALL_GRID: CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 14 };
const HATCH: CSSProperties = {
  ...CARD, background: "repeating-linear-gradient(135deg, var(--bg-2) 0 6px, var(--bg-1) 6px 12px)",
};

/** "▲ 15%" — the change against the comparison, in the metric's own terms (points for a share). */
function changeChip(m: BriefingRangeMeasure, against: string) {
  const words = changeOf(m, "previous");
  const move = moveOf(m);
  if (!words || move === null) return null;
  const arrow = move > 0 ? "▲" : move < 0 ? "▼" : "";
  return (
    <Chip tone={move > 0 ? "up" : move < 0 ? "down" : "plain"} title={`against ${against}`}>
      {`${arrow} ${words.replace(/^[+-]/, "")}`.trim()}
    </Chip>
  );
}

/** What a figure's card says under its value: its change and what it is against, and every caveat as a chip. */
function FigureSub({ m, block }: { m: BriefingRangeMeasure; block: BriefingRangeBlock }) {
  const { previous } = figurePeriods(m, block);
  const partial = m.current_partial || m.previous_partial;
  return (
    <>
      {m.anchored && (
        <Chip tone="amber" title={m.anchored.why} testId={`figure-older-${m.metric}`}>{m.anchored.covers}</Chip>
      )}
      {partial ? (
        <span title="Its data covers only part of the period, so no change is stated">{`covers only ${spanWords(partial)}`}</span>
      ) : m.previous === null ? (
        <span>no comparison</span>
      ) : (
        <>
          {changeChip(m, previous)}
          <span style={ONE_LINE}>{`vs ${previous}`}</span>
        </>
      )}
      {m.equal_age && !m.equal_age.equal && <Chip tone="amber" title={m.equal_age.why}>not at equal age</Chip>}
      {m.status !== "final" && (
        <Chip title="Its newest days are still settling, so this figure can still move">
          {m.status === "to_date" ? "to date" : "still settling"}
        </Chip>
      )}
    </>
  );
}

/** The hero: the figure that moved most, its change, and this period against its comparison as two bars. */
function Hero({ m, block, onOpen }: { m: BriefingRangeMeasure; block: BriefingRangeBlock; onOpen?: () => void }) {
  const { current, previous } = figurePeriods(m, block);
  const max = Math.max(Math.abs(m.current ?? 0), Math.abs(m.previous ?? 0)) || 1;
  const bar = (v: number | null, color: string) => (
    <span aria-hidden style={{ display: "block", height: 10, borderRadius: 5, background: "var(--bg-2)", overflow: "hidden" }}>
      <i style={{ display: "block", height: "100%", width: `${(Math.abs(v ?? 0) / max) * 100}%`, borderRadius: 5, background: color }} />
    </span>
  );
  return (
    <section data-testid="cockpit-hero" aria-label="What moved"
      style={{ ...CARD, display: "grid", gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)", gap: 28, alignItems: "center",
        padding: "18px 20px" }}>
      <div style={{ minWidth: 0 }}>
        <Label>What moved</Label>
        {onOpen ? (
          <Button variant="link" size="xs" onClick={onOpen} title="Open its trend and how it is defined"
            style={{ padding: 0, height: "auto", color: "var(--t2)" }}>
            <span className="aug-fs-ui">{m.name}</span>
          </Button>
        ) : <span className="aug-fs-ui" style={{ color: "var(--t2)" }}>{m.name}</span>}
        <div className="aug-fs-glyph" data-testid="cockpit-hero-value"
          style={{ fontWeight: 600, color: "var(--t1)", lineHeight: 1.15, margin: "4px 0 6px", ...NUM }}>
          {m.current_text ?? "—"}
        </div>
        <div className="aug-fs-xs" style={{ ...ROW, ...MUTED }}>
          {changeChip(m, previous)}
          <span>{`vs ${previous}`}</span>
          {m.status !== "final" && <Chip>{m.status === "to_date" ? "to date" : "still settling"}</Chip>}
        </div>
      </div>
      <div data-testid="cockpit-hero-bars" className="aug-fs-sm"
        style={{ display: "grid", gridTemplateColumns: "minmax(70px, auto) minmax(0, 1fr) minmax(64px, auto)", gap: "8px 10px",
          alignItems: "center" }}>
        <span style={MUTED}>{previous}</span>{bar(m.previous, "var(--chart-deemph)")}
        <span style={{ ...NUM, textAlign: "right", color: "var(--t2)" }}>{m.previous_text}</span>
        <span style={{ color: "var(--t2)" }}>{current}</span>{bar(m.current, "var(--chart-1)")}
        <span style={{ ...NUM, textAlign: "right", color: "var(--t1)" }}>{m.current_text}</span>
      </div>
    </section>
  );
}

/** A small figure: the rest of the cockpit, six to a row. */
function SmallFigure({ m, block, onOpen }: { m: BriefingRangeMeasure; block: BriefingRangeBlock; onOpen?: () => void }) {
  return (
    <div data-testid={`figure-${m.metric}`} style={CARD}>
      {onOpen ? (
        <Button variant="link" size="xs" onClick={onOpen} title="Open its trend and how it is defined"
          style={{ padding: 0, height: "auto", color: "var(--t3)", maxWidth: "100%" }}>
          <span className="aug-fs-xs" style={ONE_LINE}>{m.name}</span>
        </Button>
      ) : <span className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE, display: "block" }}>{m.name}</span>}
      <div className="aug-fs-h1" style={{ fontWeight: 600, color: "var(--t1)", margin: "2px 0", ...NUM }}>{m.current_text ?? "—"}</div>
      <div className="aug-fs-xs" style={{ ...ROW, ...MUTED, gap: 6 }}><FigureSub m={m} block={block} /></div>
    </div>
  );
}

export function MetricsFigures({ connectionId, schema, block: measuredBlock }: {
  connectionId: string; schema?: string; block: BriefingRangeBlock;
}) {
  const block = withLatest(measuredBlock);
  const open = useOpenMetric();
  const [details, setDetails] = useState(false);
  const hero = heroOf(block);
  const rest = block.measured.filter(m => m !== hero);
  const big = rest.slice(0, BIG);
  const small = rest.slice(BIG);
  const unmeasured = unmeasuredByReason(block);
  const older = olderFigures(block);
  const opener = (m: BriefingRangeMeasure) => (open ? () => open({ measure: m, block }) : undefined);

  return (
    <div data-testid="metrics-figures" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {hero && <Hero m={hero} block={block} onOpen={opener(hero)} />}

      {big.length > 0 && (
        <Figures testId="cockpit-figures">
          {withUniqueKeys(big, m => m.metric).map(([k, m]) => (
            <Figure key={k} testId={`figure-${m.metric}`} label={m.name} value={m.current_text ?? "—"}
              title={m.time_source ?? undefined} onOpen={opener(m)} sub={<FigureSub m={m} block={block} />} />
          ))}
        </Figures>
      )}

      {(small.length > 0 || block.unmeasured.length > 0) && (
        <div data-testid="cockpit-small-figures" style={SMALL_GRID}>
          {withUniqueKeys(small, m => m.metric).map(([k, m]) => <SmallFigure key={k} m={m} block={block} onOpen={opener(m)} />)}
          {withUniqueKeys(block.unmeasured, u => u.name).map(([k, u]) => (
            <div key={k} data-testid="figure-unmeasured" title={sentence(u.reason)} style={HATCH}>
              <span className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE, display: "block" }}>{u.name}</span>
              <div className="aug-fs-h1" style={{ fontWeight: 600, color: "var(--t3)", margin: "2px 0" }}>—</div>
              <Chip>not measured</Chip>
            </div>
          ))}
        </div>
      )}

      <NeedsYou testId="cockpit-needs" empty="Nothing needs you — every approved metric is measured for this period">
        {[
          ...withUniqueKeys(unmeasured, g => g.reason).map(([k, g]) => (
            <NeedsRow key={`u-${k}`} testId="needs-unmeasured"
              title={`${countNoun(g.names.length, "approved metric")} can't be measured for a period`}
              detail={<span title={sentence(g.reason)}>{`${g.names.join(", ")} — ${g.reason}`}</span>}
              actions={<Button size="xs" variant="secondary" onClick={() => requestTab("semantic", { conn: connectionId })}>
                Set their dates</Button>} />
          )),
          older.length > 0 && (
            <NeedsRow key="older" testId="needs-older"
              title={`${countNoun(older.length, "figure")} ${older.length === 1 ? "is" : "are"} from before this period`}
              detail={<span title={older.map(o => `${o.name}: ${o.covers}, its data ends ${dayWords(o.dataEnds)}`).join("\n")}>
                {`${older.map(o => o.name).join(", ")} — their data stops ${endsWords(older.map(o => o.dataEnds))}; each card says its month`}
              </span>} />
          ),
        ]}
      </NeedsYou>

      {/* On the ground, not in a card: the table is the Briefing's own and needs the page's width. */}
      <section aria-label="Every figure" style={{ marginTop: 4 }}>
        <Label right={
          <Button size="xs" variant="ghost" aria-expanded={details} data-testid="cockpit-details" onClick={() => setDetails(d => !d)}>
            {details ? "Hide" : "Details"} <Icon name={details ? "chevu" : "chevd"} size={12} />
          </Button>}>
          {`Every figure · ${block.measured.length} measured${block.last_year_label ? " · a year earlier" : ""} · expected next`}
        </Label>
        {/* Kept mounted while hidden: the table books its expected-next bands the first time a period is read. */}
        <div hidden={!details} data-testid="cockpit-table" style={{ overflowX: "auto", marginTop: 6 }}>
          <RangeMeasuresExpected connectionId={connectionId} schema={schema} block={block} />
        </div>
      </section>
    </div>
  );
}
