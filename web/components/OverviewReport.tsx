"use client";

/**
 * OverviewReportView — the "interesting facts" TOUR.
 *
 * Renders the backend's deterministic `overview_report` (aughor/overview/build.py) as a
 * scannable GRID of diverse fact cards — the Genie-style default first-look at a schema
 * ("Show me interesting facts about this dataset"). NOT a vertical timeline: the facts are
 * already notability-ranked and diversity-selected across seven lenses, so the grid lets the
 * eye jump between fact TYPES (scale · concentration · outlier · distribution · composition ·
 * coverage · relationship) rather than reading one measure ranked N ways.
 *
 * Every number is pre-rendered by the backend (`fact.stat` / `fact.stat_label`), so this
 * component never formats a figure — it renders the strings as-is and draws the small probe
 * result through the shared <Chart> primitive.
 */

import { useState } from "react";
import type { OverviewReport, OverviewFact, OverviewLens } from "@/lib/types";
import type { SourcePanelData } from "@/components/ChatMessage";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { Chart } from "@/components/Chart";

// lens → one semantic hue, so the diverse fact TYPES read as distinct chips at a glance.
// (concentration/composition = "where the mass is" → info · outlier/relationship = a
// structural signal → accent · distribution = shape/spread → caution · scale/coverage =
// context/gaps → muted.) Unknown lenses degrade to muted rather than throw.
const LENS_HUE: Record<OverviewLens, ChipHue> = {
  concentration: "info",
  composition:   "info",
  outlier:       "accent",
  relationship:  "accent",
  distribution:  "caution",
  coverage:      "muted",
  scale:         "muted",
};

function lensHue(lens: string): ChipHue {
  return LENS_HUE[lens as OverviewLens] ?? "muted";
}

// ── One fact card ─────────────────────────────────────────────────────────────
function FactCard({
  fact,
  onShowSource,
}: {
  fact: OverviewFact;
  onShowSource?: (data: SourcePanelData) => void;
}) {
  const [sqlOpen, setSqlOpen] = useState(false);
  const hasChart = fact.chart_type !== "none" && fact.columns.length > 0 && fact.rows.length > 0;

  return (
    <div
      className="flex flex-col gap-2.5 min-w-0 rounded-[var(--r3)] border p-4"
      style={{ borderColor: "var(--b1)", background: "var(--bg-2)" }}
    >
      {/* lens chip + originating table */}
      <div className="flex items-center justify-between gap-2">
        <StatusChip hue={lensHue(fact.lens)} strength="soft" className="uppercase tracking-wide">
          {fact.lens}
        </StatusChip>
        {fact.table && (
          <span className="aug-fs-xs font-mono truncate min-w-0" style={{ color: "var(--t4)" }} title={fact.table}>
            {fact.table}
          </span>
        )}
      </div>

      {/* headline */}
      <p className="aug-fs-ui font-medium leading-snug" style={{ color: "var(--t1)" }}>
        {fact.headline}
      </p>

      {/* the big pre-rendered stat + its label (numbers are backend-formatted — render as-is) */}
      <div className="flex flex-col gap-0.5">
        <span className="aug-fs-display font-mono tabular-nums leading-none" style={{ color: "var(--t1)" }}>
          {fact.stat}
        </span>
        {fact.stat_label && (
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{fact.stat_label}</span>
        )}
      </div>

      {/* why it's notable */}
      {fact.why && (
        <p className="aug-fs-xs leading-relaxed" style={{ color: "var(--t3)" }}>{fact.why}</p>
      )}

      {/* the small probe result, as a compact chart (chromeless, half-height) */}
      {hasChart && (
        <Chart
          columns={fact.columns}
          rows={fact.rows}
          chartType={fact.chart_type}
          chartConfig={fact.chart_config}
          chrome={false}
          heightScale={0.55}
        />
      )}

      {/* SQL — the probe behind the fact. With a source panel wired, one click opens the
          richer drawer (formatted SQL + sortable data); otherwise a self-contained inline
          toggle. Pure-profile facts (scale / distribution / coverage) carry no SQL. */}
      {fact.sql && (
        <div className="mt-auto pt-0.5">
          {onShowSource ? (
            <Button
              variant="ghost"
              size="xs"
              onClick={() =>
                onShowSource({ columns: fact.columns, rows: fact.rows, sql: fact.sql, title: fact.headline })
              }
              className="h-auto gap-1 px-0 aug-fs-xs font-normal hover:bg-transparent dark:hover:bg-transparent"
              style={{ color: "var(--t3)" }}
            >
              View SQL &amp; data
            </Button>
          ) : (
            <>
              <Button
                variant="ghost"
                size="xs"
                onClick={() => setSqlOpen((o) => !o)}
                className="h-auto gap-1 px-0 aug-fs-xs font-normal hover:bg-transparent dark:hover:bg-transparent"
                style={{ color: "var(--t3)" }}
              >
                <span className="inline-block w-2">{sqlOpen ? "▼" : "▶"}</span> SQL
              </Button>
              {sqlOpen && (
                <pre
                  className="mt-1.5 aug-fs-sm font-code overflow-x-auto whitespace-pre-wrap leading-relaxed rounded-[var(--r2)] p-2.5"
                  style={{ background: "var(--code-bg)", color: "var(--t2)" }}
                >
                  {fact.sql}
                </pre>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── The tour ──────────────────────────────────────────────────────────────────
export function OverviewReportView({
  report,
  onShowSource,
}: {
  report: OverviewReport;
  onShowSource?: (data: SourcePanelData) => void;
}) {
  const facts = report.facts ?? [];

  return (
    // Gentle single arrival fade (reduced-motion disables it globally via app/globals.css).
    <section className="aug-anim-fade flex flex-col gap-4" aria-label="Interesting facts about this schema">
      {report.summary && (
        <p className="aug-fs-sm" style={{ color: "var(--t2)" }}>{report.summary}</p>
      )}

      {facts.length === 0 ? (
        <p className="aug-fs-sm" style={{ color: "var(--t3)" }}>
          No notable facts surfaced for this schema.
        </p>
      ) : (
        // Backend order is authoritative (notability-ranked + diversity-selected) — never re-sort.
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {facts.map((f, i) => (
            <FactCard key={`${f.lens}-${f.table}-${f.dimension ?? "_"}-${i}`} fact={f} onShowSource={onShowSource} />
          ))}
        </div>
      )}
    </section>
  );
}
