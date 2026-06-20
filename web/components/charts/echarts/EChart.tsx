"use client";

/**
 * EChart — the thin React wrapper around Apache ECharts, the replacement for
 * <VegaChart>. Given a fully-built ECharts `option`, it owns the imperative
 * lifecycle ECharts requires: init, setOption, resize, theme-flip, click,
 * dispose.
 *
 * Design notes (mirrors the proven VegaChart patterns in this Next 16 app):
 *  - ECharts is dynamically imported INSIDE the effect (like vega-embed was) so
 *    the heavy lib stays out of the base bundle; we register only the
 *    chart/component/renderer modules we use (tree-shaking via echarts/core).
 *  - The Aughor theme is baked from CSS tokens at init; because a theme is fixed
 *    at init, a dark/light flip bumps `themeTick`, re-running the init effect to
 *    dispose + re-init with fresh colours.
 *  - setOption uses notMerge:true — every render rebuilds the whole option, so a
 *    clean replace avoids stale series/axes leaking across data changes.
 *  - Canvas renderer (default) for performance; PNG export is available to the
 *    parent via onReady(instance) → instance.getDataURL().
 */

import { useEffect, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import { registerAughorTheme } from "./theme";

// One-time dynamic import + module registration, shared across all instances.
let echartsModP: Promise<typeof import("echarts/core")> | null = null;

async function loadECharts(): Promise<typeof import("echarts/core")> {
  if (echartsModP) return echartsModP;
  echartsModP = (async () => {
    const echarts = await import("echarts/core");
    const [charts, components, renderers] = await Promise.all([
      import("echarts/charts"),
      import("echarts/components"),
      import("echarts/renderers"),
    ]);
    echarts.use([
      charts.LineChart, charts.BarChart, charts.PieChart,
      charts.ScatterChart, charts.HeatmapChart, charts.TreemapChart,
      components.GridComponent,
      components.TooltipComponent,
      components.LegendComponent,
      components.TitleComponent,
      components.DataZoomComponent,
      components.MarkLineComponent,
      components.VisualMapComponent,
      components.AxisPointerComponent,
      renderers.CanvasRenderer,
    ]);
    return echarts;
  })();
  return echartsModP;
}

type EChartsInstance = {
  setOption: (opt: unknown, opts?: { notMerge?: boolean; lazyUpdate?: boolean }) => void;
  resize: () => void;
  dispose: () => void;
  on: (event: string, handler: (params: unknown) => void) => void;
  getDataURL: (opts?: { type?: string; pixelRatio?: number; backgroundColor?: string }) => string;
};

interface Props {
  option: EChartsOption;
  height?: number;
  className?: string;
  /** Click a datum to drill in — receives the data behind the clicked element. */
  onSelect?: (datum: Record<string, unknown>) => void;
  /** Hand the live instance back to the parent (e.g. for PNG export). */
  onReady?: (instance: EChartsInstance) => void;
}

export function EChart({ option, height = 320, className, onSelect, onReady }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsInstance | null>(null);
  // Latest callbacks in refs so the click handler (bound once per init) always
  // calls the current callback without re-running the heavy init effect.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;
  // Bump on dark/light flip to force a dispose+re-init with the fresh theme.
  const [themeTick, setThemeTick] = useState(0);

  // Observe the app theme toggle once.
  useEffect(() => {
    const obs = new MutationObserver(() => setThemeTick((t) => t + 1));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
    return () => obs.disconnect();
  }, []);

  // Init + setOption; re-runs when the option object or the theme changes.
  useEffect(() => {
    let cancelled = false;
    let ro: ResizeObserver | undefined;

    loadECharts().then((echarts) => {
      if (cancelled || !containerRef.current) return;
      const themeName = registerAughorTheme(echarts);
      chartRef.current?.dispose();
      const inst = echarts.init(containerRef.current, themeName, { renderer: "canvas" }) as unknown as EChartsInstance;
      chartRef.current = inst;
      inst.setOption(option, { notMerge: true });
      onReadyRef.current?.(inst);

      inst.on("click", (params: unknown) => {
        const d = (params as { data?: unknown })?.data;
        if (d && typeof d === "object" && !Array.isArray(d)) onSelectRef.current?.(d as Record<string, unknown>);
      });

      ro = new ResizeObserver(() => inst.resize());
      ro.observe(containerRef.current);
    });

    return () => {
      cancelled = true;
      ro?.disconnect();
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, [option, themeTick]);

  return <div ref={containerRef} className={className} style={{ width: "100%", height }} />;
}
