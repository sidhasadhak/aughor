"use client";

/**
 * VegaChart.tsx — the React wrapper for the Vega runtime (Phase 1 spike).
 *
 * Deliberately compiles Vega-Lite → Vega and drives `vega.View` directly rather than
 * going through vega-embed. Two reasons, and both are the ladder from the design doc:
 * vega-embed adds an actions menu and opinions we would only have to undo, and
 * `vl.compile()` is exactly the tier-2 → tier-3 eject — a chart that needs raw Vega
 * starts from the compiled output of the spec it already had.
 *
 * Lifecycle mirrors EChart.tsx: dynamic import, ResizeObserver, theme-flip re-render,
 * dispose on unmount. The renderer is SVG so text wears the UI's own resolved font and
 * the output is inspectable in devtools; Phase 2 measures canvas for high row counts.
 */

import { useEffect, useRef, useState } from "react";
import { buildVegaConfig, readVegaTokens } from "@/components/charts/vega/config";
import type { ChartInstance, PngOptions } from "@/lib/chartExport";

type VegaModules = {
  vega: typeof import("vega");
  vl: typeof import("vega-lite");
  tooltip: typeof import("vega-tooltip");
};

let modsP: Promise<VegaModules> | null = null;
function loadVega(): Promise<VegaModules> {
  if (!modsP) {
    modsP = Promise.all([import("vega"), import("vega-lite"), import("vega-tooltip")]).then(
      ([vega, vl, tooltip]) => ({ vega, vl, tooltip }),
    );
  }
  return modsP;
}

interface Props {
  /** A Vega-Lite spec — tier 1 from resolveVegaSpec, or a hand-authored tier-2 spec. */
  spec: Record<string, unknown>;
  height?: number;
  className?: string;
  /** Called with the compiled Vega spec — the tier-3 starting point. */
  onCompiled?: (vegaSpec: unknown) => void;
  /** Click a mark to drill in — receives the datum behind it, same contract as EChart. */
  onSelect?: (datum: Record<string, unknown>) => void;
  /** Hand an export handle back to the parent, same contract as EChart's onReady. */
  onReady?: (instance: ChartInstance) => void;
}

export function VegaChart({ spec, height = 300, className, onCompiled, onSelect, onReady }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<{ finalize: () => void } | null>(null);
  const onCompiledRef = useRef(onCompiled);
  onCompiledRef.current = onCompiled;
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;
  const [themeTick, setThemeTick] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Observe the app theme toggle once — the config is rebuilt from tokens on every flip,
  // which is what keeps a STORED spec following the token layer instead of freezing colours.
  useEffect(() => {
    const obs = new MutationObserver(() => setThemeTick((t) => t + 1));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    let ro: ResizeObserver | undefined;
    let raf = 0;

    loadVega()
      .then(({ vega, vl, tooltip }) => {
        if (cancelled || !containerRef.current) return;
        const el = containerRef.current;
        const config = buildVegaConfig(readVegaTokens(el));

        /**
         * Size is compiled INTO the spec rather than pushed into the view's signals.
         *
         * This is not a style preference — it is the one behaviour that made the first
         * render wrong. With autosize "fit", a Vega-Lite spec whose band axis is discrete
         * derives its own height from the band STEP (8 categories ≈ 177px) and ignores
         * `view.height()` entirely, so a horizontal bar rendered 177px tall inside a 412px
         * container while a line chart, whose axes are continuous, sized correctly. Giving
         * the spec explicit width/height makes both cases obey the container.
         *
         * The cost is a recompile per resize instead of a signal update. That cost is
         * exactly what Phase 2 has to measure against ECharts' `resize()`.
         */
        const render = () => {
          if (cancelled || !el.isConnected) return;
          const w = el.clientWidth;
          if (w <= 0) return;
          try {
            const sized = { ...spec, width: w, height };
            // vl.compile() IS the tier-3 eject: its output is a valid raw Vega spec.
            const compiled = vl.compile(sized as unknown as Parameters<typeof vl.compile>[0], { config }).spec;
            onCompiledRef.current?.(compiled);
            viewRef.current?.finalize();
            const view = new vega.View(vega.parse(compiled), { renderer: "svg", container: el, hover: true });
            view.tooltip(new tooltip.Handler().call);
            viewRef.current = view;

            view.addEventListener("click", (_e: unknown, item: unknown) => {
              const datum = (item as { datum?: unknown })?.datum;
              if (datum && typeof datum === "object") onSelectRef.current?.(datum as Record<string, unknown>);
            });

            /**
             * PNG export. Vega's own toImageURL() honours the spec background, which is
             * transparent by design so the chart sits on whatever card holds it — a
             * transparent PNG reads as broken anywhere it is pasted. So: render to a
             * canvas, then composite it over the requested background.
             */
            onReadyRef.current?.({
              getDataURL: async (o?: PngOptions) => {
                const scale = o?.pixelRatio ?? 2;
                const src = await view.toCanvas(scale);
                const out = document.createElement("canvas");
                out.width = src.width;
                out.height = src.height;
                const ctx = out.getContext("2d");
                if (!ctx) return "";
                if (o?.backgroundColor) {
                  ctx.fillStyle = o.backgroundColor;
                  ctx.fillRect(0, 0, out.width, out.height);
                }
                ctx.drawImage(src, 0, 0);
                return out.toDataURL(o?.type === "jpeg" ? "image/jpeg" : "image/png");
              },
            });

            void view.runAsync();
            setError(null);
          } catch (e: unknown) {
            setError(e instanceof Error ? e.message : String(e));
          }
        };

        render();
        ro = new ResizeObserver(() => {
          cancelAnimationFrame(raf);
          raf = requestAnimationFrame(render);
        });
        ro.observe(el);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      ro?.disconnect();
      viewRef.current?.finalize();
      viewRef.current = null;
    };
  }, [spec, height, themeTick]);

  if (error) {
    return (
      <div className={className} style={{ height }}>
        <pre className="aug-fs-ui" style={{ whiteSpace: "pre-wrap", padding: "0.5rem", margin: 0 }}>{error}</pre>
      </div>
    );
  }
  return <div ref={containerRef} className={className} style={{ width: "100%", height }} />;
}
