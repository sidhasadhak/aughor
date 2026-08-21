"use client";

/**
 * /chart-lab/bench — the Phase 2 performance gate.
 *
 * Measures the CPU cost of the chart path, split into the phases that behave differently.
 * It began as a two-engine comparison; ECharts is retired, so what remains is a profile of
 * the engine that stayed — resolve, compile, and the recompile a resize costs.
 *
 * PAINT IS DELIBERATELY NOT MEASURED. requestAnimationFrame is throttled whenever the
 * document is hidden — in the embedded preview pane only 1 frame in 10 fires — so a
 * paint-to-screen number taken there is fiction. Everything below is synchronous CPU work
 * that runs regardless of visibility. Run it with the tab actually visible if you want to
 * add paint on top.
 *
 * Exposes window.__chartBench() so results can be read as JSON without a screenshot.
 */

import { useEffect, useState } from "react";
import { resolveVegaSpec } from "@/components/charts/vega/resolveSpec";
import { buildVegaConfig, readVegaTokens } from "@/components/charts/vega/config";

const ROW_COUNTS = [50, 500, 2_000, 10_000];
const REPEATS = 12;

interface Phase { resolve: number[]; compile: number[]; mount: number[]; resize: number[] }
const emptyPhase = (): Phase => ({ resolve: [], compile: [], mount: [], resize: [] });

function pct(xs: number[], p: number): number {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return Math.round(s[Math.min(Math.floor(p * s.length), s.length - 1)] * 100) / 100;
}

/** A time series of n points — the shape the ledger says dominates (bar and line over time). */
function makeData(n: number): { columns: string[]; rows: unknown[][] } {
  const rows: unknown[][] = [];
  const start = Date.UTC(2024, 0, 1);
  for (let i = 0; i < n; i++) {
    rows.push([new Date(start + i * 86_400_000).toISOString().slice(0, 10), 1000 + ((i * 37) % 900)]);
  }
  return { columns: ["day", "revenue"], rows };
}

async function runBench(): Promise<Record<string, unknown>> {
  const [vega, vl] = await Promise.all([import("vega"), import("vega-lite")]);

  const visible = document.visibilityState === "visible";
  const host = document.createElement("div");
  host.style.cssText = "position:absolute;left:-10000px;top:0;width:800px;height:400px";
  document.body.appendChild(host);
  const config = buildVegaConfig(readVegaTokens(document.body));

  const out: Record<string, unknown> = {};

  const progress = (msg: string) => {
    (window as unknown as { __benchProgress: string }).__benchProgress = msg;
  };

  for (const n of ROW_COUNTS) {
    progress(`rows=${n} starting`);
    const { columns, rows } = makeData(n);
    const v = emptyPhase();

    for (let r = 0; r < REPEATS; r++) {
      progress(`rows=${n} repeat ${r + 1}/${REPEATS}`);
      // ── Vega-Lite ─────────────────────────────────────────────────────────
      let t = performance.now();
      const spec = resolveVegaSpec({ columns, rows, chartType: "line" });
      v.resolve.push(performance.now() - t);

      const el2 = document.createElement("div");
      el2.style.cssText = "width:800px;height:400px";
      host.appendChild(el2);

      t = performance.now();
      const compiled = vl.compile({ ...spec!.spec, width: 800, height: 400 } as Parameters<typeof vl.compile>[0], { config }).spec;
      const parsed = vega.parse(compiled);
      v.compile.push(performance.now() - t);

      // Vega's SVG render is only awaited when the document is VISIBLE. runAsync() does not
      // settle in a hidden document — the first run of this bench in the embedded preview
      // pane hung indefinitely on exactly this line, while ECharts' setOption returned
      // normally because it is synchronous. That asymmetry is worth knowing on its own:
      // anything that renders Vega off-screen (a background tab, a headless export) has to
      // drive the view explicitly rather than await a paint that will never come.
      if (visible) {
        t = performance.now();
        const view = new vega.View(parsed, { renderer: "svg", container: el2 });
        await view.runAsync();
        v.mount.push(performance.now() - t);
        view.finalize();
      }

      // THE number the design doc flagged: compiling size into the spec means a resize costs
      // a recompile + reparse, where ECharts calls resize() on a live instance. Both are pure
      // CPU, so this comparison holds whether or not the document is painting.
      t = performance.now();
      const compiled2 = vl.compile({ ...spec!.spec, width: 600, height: 400 } as Parameters<typeof vl.compile>[0], { config }).spec;
      vega.parse(compiled2);
      v.resize.push(performance.now() - t);

      el2.remove();
    }

    const sum = (p: Phase) => ({
      resolve_p50: pct(p.resolve, 0.5), resolve_p95: pct(p.resolve, 0.95),
      compile_p50: pct(p.compile, 0.5), compile_p95: pct(p.compile, 0.95),
      mount_p50: pct(p.mount, 0.5), mount_p95: pct(p.mount, 0.95),
      resize_p50: pct(p.resize, 0.5), resize_p95: pct(p.resize, 0.95),
    });
    out[`rows_${n}`] = { vega: sum(v) };
  }

  host.remove();
  return {
    repeats: REPEATS,
    visibility: document.visibilityState,
    paint_measured: visible,
    note: visible
      ? "mount includes Vega's SVG render"
      : "document hidden — mount SKIPPED (runAsync never settles); resize is compile+parse",
    ...out,
  };
}

export default function ChartBench() {
  const [state, setState] = useState("idle");
  useEffect(() => {
    (window as unknown as { __chartBench: () => Promise<unknown> }).__chartBench = async () => {
      setState("running");
      const r = await runBench().catch((e: unknown) => {
        (window as unknown as { __benchError: string }).__benchError = e instanceof Error ? e.message : String(e);
        throw e;
      });
      (window as unknown as { __chartBenchResult: unknown }).__chartBenchResult = r;
      setState("done");
      return r;
    };
  }, []);
  return (
    <main style={{ padding: "1.5rem" }}>
      <h1 className="aug-h2">Chart engine benchmark</h1>
      <p className="aug-fs-ui" style={{ opacity: 0.7, maxWidth: "56rem" }}>
        CPU cost per phase, both engines, over a row-count sweep. Paint is excluded on purpose:
        requestAnimationFrame is throttled while the document is hidden, so a paint number taken
        in an embedded pane would be fiction. Call <code>window.__chartBench()</code>.
      </p>
      <p className="aug-fs-ui">state: {state}</p>
    </main>
  );
}
