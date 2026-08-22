"use client";

/**
 * /chart-lab/vega — the Phase 1 gate: the same six charts, the same data, two engines,
 * side by side, in whichever theme the app is in.
 *
 * These six types are ~99% of everything Aughor has ever charted (703 persisted charts,
 * measured 2026-08-21). The question this page exists to answer is the one from §03 of
 * docs/CHART_ENGINE_VEGA_DESIGN_2026-08-21.md: how much of the look is the ENGINE, and how
 * much is the theme? Both columns read the same design tokens, so what is left is the engine.
 *
 * Dev-only harness. Not linked from the app; deletable when the phase closes.
 */

import { useEffect, useMemo, useState } from "react";
import { VegaChart } from "@/components/charts/vega/VegaChart";
import { resolveVegaSpec } from "@/components/charts/vega/resolveSpec";
import { resolveTier3Spec } from "@/components/charts/vega/tier3";

const MONTHS = ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06", "2024-07", "2024-08"];
const REGIONS = ["North", "South", "East", "West"];

const byCategory = {
  columns: ["category", "gmv"],
  rows: [
    ["Apparel", 4_200_000], ["Electronics", 3_100_000], ["Home", 2_400_000], ["Beauty", 1_800_000],
    ["Grocery", 1_500_000], ["Toys", 900_000], ["Sports", 720_000], ["Books", 410_000],
  ] as unknown[][],
};

const byMonth = {
  columns: ["month", "revenue"],
  rows: MONTHS.map((m, i) => [m, 120_000 + i * 28_000 + (i % 3) * 14_000]) as unknown[][],
};

const byRegionMonth = {
  columns: ["month", "region", "revenue"],
  rows: MONTHS.flatMap((m, i) =>
    REGIONS.map((region, ri) => [m, region, 30_000 + ri * 18_000 + i * (6_000 + ri * 1_500)]),
  ) as unknown[][],
};

const paymentMix = {
  columns: ["method", "amount"],
  rows: [["Card", 5_400_000], ["Wallet", 2_900_000], ["BNPL", 1_300_000], ["Bank", 820_000], ["Cash", 240_000]] as unknown[][],
};

const oneNumber = { columns: ["net_revenue"], rows: [[8_660_000]] as unknown[][] };

// Tier 3 — the four Vega-Lite cannot express, hand-authored as raw Vega.
const funnelData = { columns: ["stage", "count"],
  rows: [["Visit", 10_000], ["Cart", 3_200], ["Checkout", 1_400], ["Paid", 900]] as unknown[][] };
const ganttData = { columns: ["task", "start", "end"],
  rows: [["Ingest", "2024-01-01", "2024-01-06"], ["Model", "2024-01-04", "2024-01-15"],
         ["Review", "2024-01-14", "2024-01-20"], ["Ship", "2024-01-19", "2024-01-24"]] as unknown[][] };
const sankeyData = { columns: ["source", "target", "value"],
  rows: [["Organic", "Signup", 500], ["Paid", "Signup", 300], ["Organic", "Bounce", 200],
         ["Referral", "Signup", 120], ["Paid", "Bounce", 80]] as unknown[][] };

interface Case {
  hint: string;
  label: string;
  note: string;
  share: string;
  data: { columns: string[]; rows: unknown[][] };
}

/** Ordered by real-world share, so the most consequential comparison is at the top. */
const CASES: Case[] = [
  { hint: "bar_horizontal", label: "bar_horizontal", share: "52.9%", note: "Ranked magnitude — the single most common chart in the product.", data: byCategory },
  { hint: "auto", label: "auto → inferred", share: "27.7%", note: "The backend defers; both engines call the same inferChartType.", data: byMonth },
  { hint: "line", label: "line", share: "7.8%", note: "Trend over time, one measure.", data: byMonth },
  { hint: "multi_line", label: "multi_line", share: "3.8%", note: "Trend by series — the legend carries identity.", data: byRegionMonth },
  { hint: "counter", label: "counter", share: "3.1%", note: "A headline number: not a plot at all.", data: oneNumber },
  { hint: "bar", label: "bar", share: "2.6%", note: "Vertical magnitude by category.", data: byCategory },
  { hint: "pie", label: "pie", share: "0.6%", note: "Part-to-whole, five slices.", data: paymentMix },

  // Tier 3. Share is 0% for all four — none has ever been persisted; they are ported so
  // that a second chart engine does not have to stay alive to draw them.
  { hint: "treemap", label: "treemap · tier 3", share: "0%", note: "Hierarchy layout — no Vega-Lite equivalent.", data: byCategory },
  { hint: "funnel", label: "funnel · tier 3", share: "0%", note: "Centred bars — not an encoding of a scale.", data: funnelData },
  { hint: "gantt", label: "gantt · tier 3", share: "0%", note: "Spans on a time axis.", data: ganttData },
  { hint: "sankey", label: "sankey · tier 3", share: "0%", note: "Flow layout Vega has no transform for — computed in TS, emitted as data.", data: sankeyData },
];

function Pane({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="aug-card" style={{ padding: "0.75rem", minWidth: 0 }}>
      <div className="aug-label" style={{ marginBottom: "0.5rem", opacity: 0.7 }}>{title}</div>
      {children}
    </div>
  );
}

function Comparison({ c, showLabels }: { c: Case; showLabels: boolean }) {
  const [compiled, setCompiled] = useState<unknown>(null);

  const tier3 = useMemo(
    () => resolveTier3Spec({ columns: c.data.columns, rows: c.data.rows, chartType: c.hint }),
    [c],
  );
  const vega = useMemo(
    () => tier3 ?? resolveVegaSpec({ columns: c.data.columns, rows: c.data.rows, chartType: c.hint, showLabels }),
    [tier3, c, showLabels],
  );

  const h = vega?.defaultH ?? 300;

  return (
    <section style={{ marginBottom: "2rem" }}>
      <header style={{ display: "flex", gap: "0.75rem", alignItems: "baseline", marginBottom: "0.5rem", flexWrap: "wrap" }}>
        <code className="aug-fs-ui" style={{ fontWeight: 600 }}>{c.label}</code>
        <span className="aug-label" style={{ opacity: 0.65 }}>{c.share} of persisted charts</span>
        <span className="aug-fs-ui" style={{ opacity: 0.6 }}>{c.note}</span>
        {vega && <span className="aug-label" style={{ opacity: 0.65 }}>→ {vega.resolved}</span>}
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "0.75rem" }}>
        <Pane title={vega?.tier === 3 ? "Vega — tier 3 (hand-authored)" : "Vega-Lite — tier 1"}>
          {vega
            ? <VegaChart spec={vega.spec} tier={vega.tier} height={h} onCompiled={setCompiled} />
            : <div className="aug-fs-ui" style={{ opacity: 0.6 }}>no chart</div>}
        </Pane>
      </div>

      {vega && (
        <details style={{ marginTop: "0.5rem" }}>
          <summary className="aug-label" style={{ cursor: "pointer", opacity: 0.7 }}>
            spec — {JSON.stringify(vega.spec).length} bytes of pure JSON, zero functions
          </summary>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "0.75rem", marginTop: "0.5rem" }}>
            <pre className="aug-fs-ui" style={{ overflowX: "auto", maxHeight: "18rem", opacity: 0.8 }}>
              {JSON.stringify(vega.spec, null, 2)}
            </pre>
            <pre className="aug-fs-ui" style={{ overflowX: "auto", maxHeight: "18rem", opacity: 0.8 }}>
              {"// tier-3 eject — vl.compile() output, hand-editable raw Vega\n"}
              {compiled ? JSON.stringify(compiled, null, 2) : "…"}
            </pre>
          </div>
        </details>
      )}
    </section>
  );
}

export default function VegaCompareLab() {
  const [showLabels, setShowLabels] = useState(false);
  // `?only=<hint>` renders one comparison alone, at the top of the page. Phase 2's
  // visual-regression harness screenshots one chart at a time; so does anyone trying to
  // look closely at a single type without scrolling past the ones above it.
  //
  // Read AFTER mount, not during render: reading location.search while rendering makes the
  // client's first pass disagree with the server's HTML, which is a hydration failure, not
  // a cosmetic warning — React discards the server tree and the page flashes.
  const [only, setOnly] = useState<string | null>(null);
  useEffect(() => setOnly(new URLSearchParams(window.location.search).get("only")), []);
  const cases = only ? CASES.filter((c) => c.hint === only) : CASES;
  return (
    <main style={{ padding: "1.5rem", maxWidth: "90rem", margin: "0 auto" }}>
      <h1 className="aug-h2" style={{ marginBottom: "0.25rem" }}>Phase 1 — engine parity</h1>
      <p className="aug-fs-ui" style={{ opacity: 0.7, marginBottom: "1rem", maxWidth: "60rem" }}>
        Same data, same tokens, same inference — ECharts on the left, Vega-Lite tier 1 on the right.
        Ordered by how often each type actually occurs in the ledger. Flip the app theme to check both.
      </p>
      <label className="aug-fs-ui" style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center", marginBottom: "1.5rem", cursor: "pointer" }}>
        <input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} />
        value labels
      </label>
      {cases.map((c) => <Comparison key={c.hint} c={c} showLabels={showLabels} />)}
      {only && cases.length === 0 && (
        <p className="aug-fs-ui" style={{ opacity: 0.7 }}>
          No case named “{only}”. Known: {CASES.map((c) => c.hint).join(", ")}.
        </p>
      )}
    </main>
  );
}
