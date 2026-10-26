/**
 * The Briefing's figures past its front (design-mockups/briefing-figures.html, built at the user's word 2026-10-26):
 * "Every figure, by area" under the desk, and the reader's choice of what sits on the front, below, or nowhere.
 *
 * The front holds six beside the lead, so Trends · Gaps · Decide never move down however many figures are approved.
 * Below the desk the rest fill the width by area — the income statement's areas first, as the map orders them — a
 * figure that moved 10% or more read brighter; figures whose data ended are one line per day they stopped; a figure
 * that cannot be measured keeps its reason in plain view, with the way to fix it (the 2026-10-26 rule).
 */
import { Fragment } from "react";

import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { endsWords } from "@/lib/dashboards/figures";
import { requestTab } from "@/lib/navigate";
import { withUniqueKeys } from "@/lib/listKeys";
import {
  FRONT_MAX, idOf, moved as movedChoice, placeOf, type Arranged, type FigureChoice, type Place,
} from "@/lib/briefingFigures";
import type { PaperNumber } from "@/components/brief/BriefPaper";

const SERIF = "var(--font-serif)";
const RULE = "1px solid var(--b1)";
const KICKER = { letterSpacing: "0.08em", textTransform: "uppercase" as const, fontWeight: 600 };

/** The front box's last line: how many figures read below, and the door to choosing them. */
export function FrontFooter({ arranged, onChoose }: { arranged: Arranged; onChoose: () => void }) {
  const below = arranged.below.reduce((n, g) => n + g.rows.length, 0) + arranged.blanks.length;
  const stopped = arranged.stopped.reduce((n, g) => n + g.rows.length, 0);
  const said = [below ? `${below} more below, by area` : "", stopped ? `${stopped} stopped` : "",
                arranged.hidden.length ? `${arranged.hidden.length} hidden by you` : ""].filter(Boolean).join(" · ");
  return (
    <div data-testid="paper-front-footer" className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8,
      marginTop: 10, color: "var(--t3)", flexWrap: "wrap" }}>
      <Button size="xs" variant="ghost" onClick={onChoose} data-testid="paper-choose-figures">Choose figures</Button>
      {said && <span>{said}</span>}
    </div>
  );
}

/** Under the desk: every figure not on the front, by area. */
export function EveryFigure({ arranged, connectionId, comparedWith, onChoose }: {
  arranged: Arranged; connectionId?: string; comparedWith?: string; onChoose: () => void;
}) {
  const count = arranged.below.reduce((n, g) => n + g.rows.length, 0);
  if (!count && !arranged.blanks.length && !arranged.stopped.length) {
    return arranged.hidden.length ? (
      <div data-testid="paper-every-figure" className="aug-fs-xs" style={{ padding: "12px 0", borderBottom: RULE, color: "var(--t3)" }}>
        {`${arranged.hidden.length} figure${arranged.hidden.length === 1 ? "" : "s"} hidden by you · `}
        <Button size="xs" variant="ghost" onClick={onChoose}>Choose figures</Button>
      </div>
    ) : null;
  }
  return (
    <section data-testid="paper-every-figure" aria-label="Every figure, by area" style={{ padding: "18px 0", borderBottom: RULE }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <h3 className="aug-fs-h1" style={{ fontFamily: SERIF, fontWeight: 600, margin: 0 }}>Every figure, by area</h3>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          {`${count} measured${comparedWith ? ` · each against ${comparedWith}` : ""}`}
        </span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {arranged.hidden.length > 0 && <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{`${arranged.hidden.length} hidden by you`}</span>}
          <Button size="xs" variant="ghost" onClick={onChoose}>Choose figures</Button>
        </span>
      </div>
      {arranged.below.length > 0 && (
        <div data-testid="paper-areas" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "14px 24px" }}>
          {withUniqueKeys(arranged.below, g => `area:${g.area}`).map(([key, g]) => {
            const movers = g.rows.filter(r => r.moved).length;
            return (
              <div key={key} data-testid="paper-area-card">
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, paddingBottom: 4, borderBottom: "1px solid var(--b2)" }}>
                  <span className="aug-fs-xs" style={{ ...KICKER, color: "var(--t2)" }}>{g.area}</span>
                  <span className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--t3)" }}>
                    {`${g.rows.length}${movers ? ` · ${movers} moved 10%+` : ""}`}
                  </span>
                </div>
                {withUniqueKeys(g.rows, r => `fig:${idOf(r)}`).map(([rk, r]) => <FigureRow key={rk} r={r} />)}
              </div>
            );
          })}
        </div>
      )}
      {arranged.blanks.length > 0 && (
        <div data-testid="paper-every-blanks" className="aug-fs-xs" style={{ display: "grid", gap: 6, marginTop: 14, color: "var(--t2)" }}>
          {withUniqueKeys(arranged.blanks, r => `blank:${idOf(r)}`).map(([key, r]) => (
            <div key={key}>
              <b style={{ fontWeight: 600 }}>{r.label}</b> — {r.why}
              {r.metric && connectionId && (
                <Button size="xs" variant="ghost" style={{ marginLeft: 4 }}
                  onClick={() => requestTab("semantic", { conn: connectionId, metric: r.metric! })}>Fix its definition</Button>
              )}
            </div>
          ))}
        </div>
      )}
      {arranged.stopped.length > 0 && (
        <div data-testid="paper-every-stopped" style={{ marginTop: 14 }}>
          {withUniqueKeys(arranged.stopped, g => `stopped:${g.day}`).map(([key, g]) => (
            <div key={key} className="aug-fs-sm" style={{ padding: "6px 0", borderTop: RULE, color: "var(--t2)" }}>
              <span style={{ color: "var(--amb4)" }}>{`${g.rows.length} stopped ${g.day ? endsWords([g.day]) : "before this edition"}`}</span>
              {` — ${g.rows.map(r => r.label).join(", ")}`}
            </div>
          ))}
          <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 6 }}>
            If their sources should still be loading, the feed needs fixing; if not, read them in a Custom range.
          </div>
        </div>
      )}
    </section>
  );
}

function FigureRow({ r }: { r: PaperNumber }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 10, padding: "5px 0", borderTop: RULE }}>
      <span className="aug-fs-sm" style={{ color: r.moved ? "var(--t1)" : "var(--t2)", minWidth: 0, flex: 1 }}>
        {r.label}
        {r.note && <span className="aug-fs-xs" style={{ display: "block", color: "var(--amb4)" }}>{r.note}</span>}
      </span>
      <span className="aug-fs-sm" style={{ fontWeight: 600, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
        {r.value}
        {r.change && <span className="aug-fs-xs" style={{ marginLeft: 6, fontWeight: 400,
          color: r.change.sign > 0 ? "var(--grn4)" : r.change.sign < 0 ? "var(--red4)" : "var(--t3)" }}>{r.change.text}</span>}
      </span>
    </div>
  );
}

/** The reader's choice, per figure: on the front, below, or hidden. Theirs alone, per dataset. */
export function ChooseFigures({ rows, choice, onChange, onClose, busy }: {
  rows: PaperNumber[]; choice: FigureChoice; onChange: (next: FigureChoice, said: string) => void;
  onClose: () => void; busy?: boolean;
}) {
  const onFront = rows.filter(r => placeOf(rows, choice, idOf(r)) === "front").length;
  const full = onFront >= FRONT_MAX;
  const groups: { area: string; rows: PaperNumber[] }[] = [];
  for (const r of rows) {
    const area = r.ended ? "Data ended" : r.area || "Figures";
    const g = groups.find(x => x.area === area);
    if (g) g.rows.push(r); else groups.push({ area, rows: [r] });
  }
  const words: Record<Place, string> = { front: "on the front", below: "below, by area", hidden: "hidden" };
  return (
    <section data-testid="paper-choose" aria-label="Choose figures" style={{ margin: "14px 0", padding: "14px 16px",
      border: "1px solid var(--b2)", borderRadius: "var(--r3)", background: "var(--bg-1)" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <h3 className="aug-fs-h2" style={{ fontFamily: SERIF, fontWeight: 600, margin: 0 }}>Choose figures</h3>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{`${onFront} of ${FRONT_MAX} on the front`}</span>
        <Button size="xs" variant="ghost" style={{ marginLeft: "auto" }} onClick={onClose}>Done</Button>
      </div>
      <p className="aug-fs-xs" style={{ color: "var(--t3)", margin: "4px 0 10px" }}>
        Front — beside the lead, up to {FRONT_MAX}. Below — in Every figure, by area. Hidden — not in your Briefing. Yours
        alone, for this dataset; every approved figure is still measured.
      </p>
      {withUniqueKeys(groups, g => `choose:${g.area}`).map(([key, g]) => (
        <Fragment key={key}>
          <div className="aug-fs-xs" style={{ ...KICKER, color: "var(--t3)", padding: "8px 0 4px" }}>{g.area}</div>
          {withUniqueKeys(g.rows, r => `choose-row:${idOf(r)}`).map(([rk, r]) => {
            const id = idOf(r);
            const place = placeOf(rows, choice, id);
            // A full front offers no seventh place: the control holds only what can be chosen.
            const options = ([
              ...(place === "front" || !full ? [{ value: "front" as Place, label: "Front" }] : []),
              { value: "below" as Place, label: "Below" },
              { value: "hidden" as Place, label: "Hidden" },
            ]);
            return (
              <div key={rk} data-testid="paper-choose-row" style={{ display: "flex", alignItems: "center", gap: 10,
                padding: "5px 0", borderTop: RULE }}>
                <span className="aug-fs-sm" style={{ flex: 1, minWidth: 0, color: "var(--t1)" }}>{r.label}</span>
                <Segmented<Place> label={`Where ${r.label} reads`} value={place} disabled={busy} options={options}
                  onChange={to => onChange(movedChoice(rows, choice, id, to), `${r.label}: ${words[to]}.`)} />
              </div>
            );
          })}
        </Fragment>
      ))}
      {full && <p className="aug-fs-xs" style={{ color: "var(--t3)", margin: "8px 0 0" }}>The front is full — move one below to put another there.</p>}
    </section>
  );
}
