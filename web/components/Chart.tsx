"use client";

/**
 * Chart — the reusable chart component, extracted verbatim from ChatMessage's
 * InlineChart. Given SQL-shaped { columns, rows } (+ optional backend chartConfig),
 * it infers the right Vega-Lite view (bar / line / multi-line / stacked / pie /
 * heatmap / scatter / combo / treemap / matrix / change-metric), builds the spec,
 * and renders it via <VegaChart> with a download-PNG + drag-to-resize chrome.
 *
 * Lives independently of ChatMessage so any surface (chat, report, exploration,
 * query builder, canvas) can render the same chart. Column-role classification is
 * shared via ./charts/columnRoles; formatting/date logic via @/lib/format.
 */

import React, { useRef, useState } from "react";
import DownloadIcon from "@atlaskit/icon/core/download";
import { VegaChart, type VLSpec } from "@/components/VegaChart";
import {
  type Gran,
  cleanLabel,
  normDateStr,
  detectGranularity,
  fmtDate,
  chartDateFormat,
  pct,
} from "@/lib/format";
import {
  DATE_COL,
  SHARE_COL,
  CHANGE_METRIC_COL,
  TIME_LABEL_COL,
  DATE_VALUE_RE,
  isNumeric,
  firstNonNull,
} from "@/components/charts/columnRoles";

export function Chart({
  columns,
  rows,
  chartType = "auto",
  chartConfig = null,
  title = "chart",
  chrome = true,
  showLabels: showLabelsProp,
}: {
  columns: string[];
  rows: unknown[][];
  chartType?: string | null;
  chartConfig?: Record<string, unknown> | null;
  title?: string;
  /** Render the hover toolbar (labels + download) and drag-to-resize handle.
   *  Set false when an outer wrapper (e.g. InvestigationChart) supplies the chrome. */
  chrome?: boolean;
  /** Externally control data-label visibility (chromeless mode). Falls back to
   *  the internal toggle when undefined. */
  showLabels?: boolean;
}) {
  const outerRef  = useRef<HTMLDivElement>(null);
  const chartRef  = useRef<HTMLDivElement>(null);
  // userH = null means "use computed default height". Set by drag handle.
  const [userH, setUserH] = useState<number | null>(null);

  // showLabels = true renders data values on top of bars/points
  const [showLabelsState, setShowLabels] = useState(false);
  const showLabels = showLabelsProp ?? showLabelsState;

  function startDrag(e: React.MouseEvent) {
    e.preventDefault();
    const startY = e.clientY;
    const startH = outerRef.current?.clientHeight ?? 300;

    function onMove(ev: MouseEvent) {
      const newH = Math.max(80, startH + (ev.clientY - startY));
      if (outerRef.current) outerRef.current.style.minHeight = `${newH}px`;
    }
    function onUp(ev: MouseEvent) {
      // clear the inline style; re-render will set chart height via prop
      if (outerRef.current) outerRef.current.style.minHeight = "";
      setUserH(Math.max(80, startH + (ev.clientY - startY)));
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup",   onUp);
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup",   onUp);
  }

  function handleDownloadPng() {
    const svg = chartRef.current?.querySelector("svg");
    if (!svg) return;
    const w = svg.clientWidth  || 640;
    const h = svg.clientHeight || 320;
    const clone = svg.cloneNode(true) as SVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width",  String(w));
    clone.setAttribute("height", String(h));
    const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    bg.setAttribute("width",  String(w));
    bg.setAttribute("height", String(h));
    bg.setAttribute("fill", "#131c27");
    clone.insertBefore(bg, clone.firstChild);
    const svgStr = new XMLSerializer().serializeToString(clone);
    const url    = URL.createObjectURL(new Blob([svgStr], { type: "image/svg+xml;charset=utf-8" }));
    const img    = new Image();
    img.onload = () => {
      const scale  = 2;
      const canvas = Object.assign(document.createElement("canvas"), { width: w * scale, height: h * scale });
      const ctx    = canvas.getContext("2d")!;
      ctx.scale(scale, scale);
      ctx.fillStyle = "#131c27";
      ctx.fillRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0, w, h);
      URL.revokeObjectURL(url);
      canvas.toBlob(blob => {
        if (!blob) return;
        const pngUrl = URL.createObjectURL(blob);
        const fname  = title.replace(/[^a-z0-9]+/gi, "_").toLowerCase() + ".png";
        const a = Object.assign(document.createElement("a"), { href: pngUrl, download: fname });
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        URL.revokeObjectURL(pngUrl);
      }, "image/png");
    };
    img.src = url;
  }

  if (!rows.length || !columns.length) return null;

  // ── Column classification ──────────────────────────────────────────────────
  const data: Record<string, unknown>[] = rows.map(r =>
    Object.fromEntries(columns.map((c, i) => [c, (r as unknown[])[i]])),
  );

  const DATE_VALUE_RE = /^\d{4}-\d{2}(-\d{2})?/;
  const looksLikeDate = (colIdx: number) => {
    const v = firstNonNull(rows, colIdx);
    return typeof v === "string" && DATE_VALUE_RE.test(v);
  };

  const dateCol =
    columns.find(c => DATE_COL.test(c)) ||
    columns.find((c, i) => !isNumeric(firstNonNull(rows, i)) && looksLikeDate(i));

  const catCols = columns.filter(
    (c, i) => c !== dateCol && !DATE_COL.test(c) && !isNumeric(firstNonNull(rows, i)),
  );
  const PREFER_COL = /(pct|percent|share|rate|ratio|proportion)/i;
  const numericCols = columns.filter((c, i) => !DATE_COL.test(c) && isNumeric(firstNonNull(rows, i)));
  // True when ANY numeric column is a change/delta/growth metric.
  // These are COMPARISON questions — heatmap/stacked-bar are inappropriate.
  const _isChangeMetric = numericCols.some(c => CHANGE_METRIC_COL.test(c));
  // For change metrics, prefer the change column as the primary numeric
  // ONLY when there is a categorical column (series dimension).
  // When no catCol exists, plot the base metric (AOV, revenue) not the change %.
  const catCol  = catCols[0];
  const catCol2 = catCols[1];
  const CHANGE_PREFER_COL = /(change|delta|growth|pct_change|percent_change|_chg$|_diff$)/i;
  const baseNumCol = numericCols.find(c => PREFER_COL.test(c)) ?? numericCols.find(c => !CHANGE_METRIC_COL.test(c)) ?? numericCols[0];
  const changeNumCol = numericCols.find(c => CHANGE_PREFER_COL.test(c)) ?? numericCols.find(c => PREFER_COL.test(c)) ?? numericCols[0];
  const numCol  = (_isChangeMetric && catCol) ? changeNumCol : baseNumCol;
  const hint    = (chartType ?? "auto").toLowerCase();
  const isTimeLabel = catCol ? TIME_LABEL_COL.test(catCol) : false;

  // ── Backend-provided chart config (MindsDB-style) ───────────────────────────
  // When the LLM generated a chart_config alongside SQL, use it directly.
  // chartConfig = {type, x_field, y_field, y_field_2, color_field, title, format}
  const cc = chartConfig;
  const ccType = cc?.type as string | undefined;
  const ccX = cc?.x_field as string | undefined;
  const ccY = cc?.y_field as string | undefined;
  const ccY2 = cc?.y_field_2 as string | undefined;
  const ccColor = cc?.color_field as string | undefined;
  const ccFmt = cc?.format as string | undefined;
  const hasBackendConfig = cc && ccType && ccX && ccY;

  // Map backend config types to our hint system
  const backendHint = hasBackendConfig ? ccType.toLowerCase() : null;

  if (!numCol) return null;

  // ── Axis format ────────────────────────────────────────────────────────────
  const isPctCol = SHARE_COL.test(numCol);
  const sampleVals = data.slice(0, 10).map(d => Number(d[numCol])).filter(v => !isNaN(v));
  const maxSampleVal = Math.max(...sampleVals.map(Math.abs), 0);
  const isPctFraction = isPctCol && maxSampleVal <= 1;
  // Axis tick format: SI adaptive (removes trailing zeros)
  const yFmt   = isPctFraction ? ".2%" : "~s";
  // Data-label format: 3 significant figures SI (e.g. "2.14M", "891k" not "2.14438M")
  // Percentages always 2 decimal places
  const lblFmt = isPctFraction ? ".2%" : ".3s";

  // ── Build spec ─────────────────────────────────────────────────────────────
  const xTitle = catCol  ? cleanLabel(catCol)  : (dateCol ? cleanLabel(dateCol) : "");
  const yTitle = numCol  ? cleanLabel(numCol)  : "";
  // True grain of the date column → drives axis format and (for bars) discrete
  // bucket labels, so pre-aggregated weekly/daily data isn't re-binned to months.
  const dateGran: Gran = dateCol ? detectGranularity(dateCol, data.map(d => d[dateCol])) : "month";
  const multiYear = dateCol
    ? new Set(data.map(d => String(d[dateCol]).slice(0, 4)).filter(y => /^\d{4}$/.test(y))).size > 1
    : false;
  const xDateFmt = chartDateFormat(dateGran, multiYear);

  let spec: VLSpec | null = null;
  let vegaData: Record<string, unknown>[] = data;
  let defaultH = 220;

  // ── BACKEND CHART CONFIG (MindsDB-style) ──────────────────────────────────
  // If the LLM provided a chart_config, build the spec directly from it.
  if (hasBackendConfig && backendHint) {
    const bType = backendHint;
    const xF = ccX!;
    const yF = ccY!;
    const y2F = ccY2;
    const cF = ccColor;
    const bFmt = ccFmt ?? "~s";
    const bTitle = cc?.title as string | undefined;

    if (bType === "combo" && y2F) {
      spec = {
        layer: [
          {
            mark: { type: "bar", color: "#818cf8", opacity: 0.8, cornerRadiusEnd: 2 },
            encoding: {
              y: { field: yF, type: "quantitative", axis: { format: bFmt, grid: true, title: cleanLabel(yF) } },
              tooltip: [
                { field: xF, type: "nominal" },
                { field: yF, type: "quantitative", format: bFmt, title: cleanLabel(yF) },
              ],
            },
          },
          {
            mark: { type: "line", color: "#E64848", strokeWidth: 2, point: { size: 30, filled: true, opacity: 0.9 } },
            encoding: {
              y: { field: y2F, type: "quantitative", axis: { format: bFmt, title: cleanLabel(y2F) } },
              tooltip: [
                { field: xF, type: "nominal" },
                { field: y2F, type: "quantitative", format: bFmt, title: cleanLabel(y2F) },
              ],
            },
          },
        ],
        encoding: {
          x: { field: xF, type: "ordinal", axis: { labelLimit: 160, labelAngle: 0, labelOverlap: true, title: cleanLabel(xF) } },
        },
        resolve: { scale: { y: "independent" } },
        config: { axisX: { labelAngle: 0, labelOverlap: "parity" } },
      };
      defaultH = 350;
    } else if (bType === "line" || bType === "multi_line") {
      const xEnc: Record<string, unknown> = { field: xF, type: "temporal", axis: { labelAngle: 0, title: cleanLabel(xF) } };
      const yEnc: Record<string, unknown> = { field: yF, type: "quantitative", axis: { format: bFmt, grid: true, title: cleanLabel(yF) } };
      spec = {
        mark: { type: "line", strokeWidth: 1.5 },
        encoding: xEnc,
        ...(cF ? {
          layer: [
            { mark: { type: "line" }, encoding: { x: xEnc, y: yEnc, color: { field: cF, type: "nominal" } } },
            { mark: { type: "point", filled: true, size: 30 }, encoding: { x: xEnc, y: yEnc, color: { field: cF, type: "nominal" }, tooltip: [{ field: xF, type: "temporal" }, { field: cF, type: "nominal" }, { field: yF, type: "quantitative", format: bFmt }] } },
          ],
        } : {
          layer: [
            { mark: { type: "line" }, encoding: { x: xEnc, y: yEnc } },
            { mark: { type: "point", filled: true, size: 30 }, encoding: { x: xEnc, y: yEnc, tooltip: [{ field: xF, type: "temporal" }, { field: yF, type: "quantitative", format: bFmt }] } },
          ],
        }),
      };
      defaultH = 350;
    } else if (bType === "bar" || bType === "bar_horizontal") {
      spec = {
        mark: { type: "bar", color: "#818cf8", opacity: 0.85, cornerRadiusEnd: 2 },
        encoding: {
          x: { field: xF, type: "ordinal", sort: { field: yF, order: "descending" }, axis: { labelLimit: 160, labelAngle: 0, labelOverlap: true, title: cleanLabel(xF) } },
          y: { field: yF, type: "quantitative", axis: { format: bFmt, grid: true, title: cleanLabel(yF) } },
          tooltip: [
            { field: xF, type: "nominal", title: cleanLabel(xF) },
            { field: yF, type: "quantitative", format: bFmt, title: cleanLabel(yF) },
          ],
        },
      };
      defaultH = 350;
    } else if (bType === "scatter") {
      spec = {
        mark: { type: "point", filled: true, size: 60, opacity: 0.7 },
        encoding: {
          x: { field: xF, type: "quantitative", axis: { title: cleanLabel(xF) } },
          y: { field: yF, type: "quantitative", axis: { format: bFmt, grid: true, title: cleanLabel(yF) } },
          tooltip: [
            { field: xF, type: "quantitative", title: cleanLabel(xF) },
            { field: yF, type: "quantitative", format: bFmt, title: cleanLabel(yF) },
          ],
        },
      };
      defaultH = 350;
    } else if (bType === "pie") {
      const pieAgg = new Map<string, number>();
      data.forEach(d => { pieAgg.set(String(d[xF]), (pieAgg.get(String(d[xF])) ?? 0) + Number(d[yF])); });
      vegaData = [...pieAgg.entries()].sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value }));
      spec = {
        mark: { type: "arc", innerRadius: 44, outerRadius: 100 },
        encoding: {
          theta: { field: "value", type: "quantitative" },
          color: { field: "label", type: "nominal", legend: { title: cleanLabel(xF), orient: "right" } },
          tooltip: [
            { field: "label", type: "nominal", title: cleanLabel(xF) },
            { field: "value", type: "quantitative", format: bFmt, title: cleanLabel(yF) },
          ],
        },
      };
      defaultH = 350;
    }
  }

  // ── PIE / DONUT ─────────────────────────────────────────────────────────────
  if (!spec && hint === "pie" && catCol) {
    const agg = new Map<string, number>();
    data.forEach(d => {
      const k = String(d[catCol]);
      agg.set(k, (agg.get(k) ?? 0) + Number(d[numCol]));
    });
    vegaData = [...agg.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([label, value]) => ({ label, value }));

    spec = {
      mark: { type: "arc", innerRadius: 44, outerRadius: 100 },
      encoding: {
        theta: { field: "value", type: "quantitative" },
        color: { field: "label", type: "nominal", legend: { title: cleanLabel(catCol), orient: "right" } },
        tooltip: [
          { field: "label", type: "nominal",     title: cleanLabel(catCol) },
          { field: "value", type: "quantitative", format: lblFmt, title: yTitle },
        ],
      },
    };
    defaultH = 240;
  }

  // ── HEATMAP ───────────────────────────────────────────────────────────────────
  // Only rendered when the LLM explicitly returns chart_type = "heatmap".
  // Auto-heatmap is intentionally removed — temporal data defaults to multi-line
  // so users always see the trend. Change/delta metrics are additionally blocked
  // even on explicit hint (period-over-period is comparison, not distribution).
  const _stackUnique = catCol ? new Set(data.map(d => d[catCol])).size : 0;

  if (!spec && hint === "heatmap" && !_isChangeMetric) {
    const xSrc = dateCol ?? catCol2 ?? "";

    // Build raw key→value map first, then fill the FULL grid so every
    // group × stack cell gets a rect (prevents background bleeding through
    // as "black" gaps where a state simply had no orders in a given period).
    const rawRows = data.map(d => ({
      group: xSrc === dateCol ? fmtDate(String(d[xSrc]), dateGran) : String(d[xSrc]),
      stack: String(d[catCol!]),
      val:   Number(d[numCol]),
    }));
    const heatGroupOrder = [...new Set(rawRows.map(d => d.group))];
    const heatStacks     = [...new Set(rawRows.map(d => d.stack))];
    const cellMap        = new Map(rawRows.map(d => [`${d.group}__${d.stack}`, d.val]));

    // Full grid — missing cells get val: null (rendered as a neutral fill)
    vegaData = heatGroupOrder.flatMap(g =>
      heatStacks.map(s => ({
        group: g,
        stack: s,
        val:   cellMap.get(`${g}__${s}`) ?? null,
      })),
    );

    // Compute non-null max for scale calibration
    const heatVals    = rawRows.map(d => d.val).filter(v => isFinite(v) && v > 0);
    const heatMax     = heatVals.length ? Math.max(...heatVals) : 1;

    // Use sqrt scale so dominant outliers (e.g. SP with 10× others' revenue)
    // don't compress everything else to the same near-white shade.
    const heatColorScale = isPctCol
      ? { scheme: "redblue", domainMid: 0 }
      : { scheme: "blues", type: "sqrt", domainMin: 0, domainMax: heatMax, null: "#0e1520" };

    spec = {
      mark: { type: "rect", stroke: "#0e1520", strokeWidth: 0.5 },
      encoding: {
        x: {
          field: "group", type: "ordinal", sort: heatGroupOrder,
          axis: { labelAngle: 0, title: cleanLabel(xSrc), labelLimit: 80 },
        },
        y: {
          field: "stack", type: "ordinal",
          sort: { field: "val", op: "sum", order: "descending" },
          axis: { title: catCol ? cleanLabel(catCol) : "", labelLimit: 100 },
        },
        color: {
          field: "val", type: "quantitative",
          scale: heatColorScale,
          legend: { title: yTitle, orient: "right", format: yFmt },
        },
        tooltip: [
          { field: "group", type: "nominal",      title: cleanLabel(xSrc) },
          { field: "stack", type: "nominal",      title: catCol ? cleanLabel(catCol) : "" },
          { field: "val",   type: "quantitative", format: lblFmt, title: yTitle },
        ],
      },
    };
    defaultH = Math.max(220, Math.min(_stackUnique * 18 + 80, 600));
  }

  // ── MULTI-LINE (one line per category over time) ──────────────────────────────
  // Triggered explicitly with hint="multi_line"
  else if (!spec && hint === "multi_line" && catCol && dateCol) {
    // Drop rows where the value is null/NaN — LAG/LEAD queries produce null for the
    // first partition row; Number(null)=0 would create a false zero spike.
    vegaData = data
      .filter(d => { const v = d[numCol]; return v !== null && v !== undefined && v !== "" && !isNaN(Number(v)); })
      .map(d => ({
        date:   normDateStr(String(d[dateCol])),
        series: String(d[catCol]),
        val:    Number(d[numCol]),
      }));

    // For change metrics stored as large-scale percentages (e.g. 15.2 meaning 15.2%),
    // use a plain numeric format and append "(%)". For 0-1 fractions, use ".2%".
    const mlYFmt   = _isChangeMetric && !isPctFraction ? ".0f" : yFmt;
    const mlYTitle = _isChangeMetric && !isPctFraction && isPctCol ? `${yTitle} (%)` : yTitle;
    const mlSeriesCount = new Set(vegaData.map(d => d.series as string)).size;

    // symbolType "stroke" renders a short line segment that matches the chart mark.
    // symbolSize 200 gives a visible ~14 px line; symbolStrokeWidth matches chart line weight.
    const mlLegend = mlSeriesCount > 12
      ? { orient: "right", direction: "vertical", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          labelFontSize: 10, title: cleanLabel(catCol), titleLimit: 160 }
      : { direction: "horizontal", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          title: cleanLabel(catCol), titleLimit: 160 };
    const mlStrokeW = mlSeriesCount > 20 ? 0.9 : mlSeriesCount > 10 ? 1.1 : 1.5;

    const mlXEnc = { field: "date", type: "temporal", axis: { tickCount: 12, format: xDateFmt, labelAngle: 0, title: cleanLabel(dateCol) } };
    const mlYEnc = { field: "val",  type: "quantitative", axis: { format: mlYFmt, grid: true, title: mlYTitle } };
    const mlColorEnc = { field: "series", type: "nominal", legend: mlLegend };
    const mlTooltip = [
      { field: "date",   type: "temporal",     title: cleanLabel(dateCol), format: xDateFmt },
      { field: "series", type: "nominal",      title: cleanLabel(catCol) },
      { field: "val",    type: "quantitative", format: mlYFmt, title: mlYTitle },
    ];
    spec = {
      layer: [
        {
          mark: { type: "line", strokeWidth: mlStrokeW },
          encoding: { x: mlXEnc, y: mlYEnc, color: mlColorEnc },
        },
        {
          // Invisible hover points — nearest: true snaps to closest x date so the
          // user doesn't have to click exactly on the line.
          mark: { type: "point", filled: true, size: 60 },
          params: [{ name: "mlHover", select: { type: "point", fields: ["date"], nearest: true, on: "pointerover", clear: "pointerout" } }],
          encoding: {
            x: mlXEnc,
            y: mlYEnc,
            color: mlColorEnc,
            opacity: { condition: { param: "mlHover", empty: false, value: 1 }, value: 0 },
            tooltip: mlTooltip,
          },
        },
      ],
    };
    defaultH = mlSeriesCount > 15 ? 360 : 300;
  }

  // ── TREEMAP ───────────────────────────────────────────────────────────────────
  // Aggregates catCol → shows proportional area tiles
  else if (!spec && hint === "treemap" && catCol) {
    const tmAgg = new Map<string, number>();
    data.forEach(d => {
      const k = String(d[catCol]);
      tmAgg.set(k, (tmAgg.get(k) ?? 0) + Number(d[numCol]));
    });
    vegaData = [...tmAgg.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 40)
      .map(([name, value]) => ({ id: name, parent: "root", value, name }));
    // Add root node
    vegaData.unshift({ id: "root", parent: "", value: 0, name: "root" } as Record<string, unknown>);

    // Vega 6 treemap spec (not Vega-Lite)
    spec = {
      $schema: "https://vega.github.io/schema/vega/v6.json",
      background: "transparent",
      padding: 4,
      signals: [{ name: "width", value: 0 }, { name: "height", value: 0 }],
      data: [
        {
          name: "tree",
          values: vegaData,
          transform: [
            { type: "stratify", key: "id", parentKey: "parent" },
            {
              type: "treemap",
              field: "value",
              sort: { field: "value", order: "descending" },
              round: true,
              method: "squarify",
              ratio: 1.618,
              size: [{ signal: "width" }, { signal: "height" }],
            },
          ],
        },
        {
          name: "leaves",
          source: "tree",
          transform: [{ type: "filter", expr: "datum.parent !== ''" }],
        },
      ],
      marks: [
        {
          type: "rect",
          from: { data: "leaves" },
          encode: {
            update: {
              x: { field: "x0" },
              x2: { field: "x1" },
              y: { field: "y0" },
              y2: { field: "y1" },
              fill: { scale: "color", field: "name" },
              stroke: { value: "#131c27" },
              strokeWidth: { value: 1.5 },
              opacity: { value: 0.88 },
              tooltip: { signal: `{"${cleanLabel(catCol)}": datum.name, "${yTitle}": format(datum.value, "${lblFmt}")}` },
            },
          },
        },
        {
          type: "text",
          from: { data: "leaves" },
          encode: {
            update: {
              x: { signal: "(datum.x0 + datum.x1) / 2" },
              y: { signal: "(datum.y0 + datum.y1) / 2" },
              text: { signal: "(datum.x1 - datum.x0) > 50 ? datum.name : ''" },
              align: { value: "center" },
              baseline: { value: "middle" },
              fill: { value: "rgba(255,255,255,0.80)" },
              fontSize: { signal: "min(12, (datum.x1 - datum.x0) / 6)" },
              fontWeight: { value: "500" },
            },
          },
        },
      ],
      scales: [
        {
          name: "color",
          type: "ordinal",
          range: { scheme: "tableau20" },
          domain: { data: "leaves", field: "name" },
        },
      ],
    };
    defaultH = 340;
  }

  // ── PERIOD-OVER-PERIOD / CHANGE METRIC (auto only) ───────────────────────────
  // When the result contains a change/delta/growth column alongside date + category:
  //   X axis  = period (the date column)
  //   Y axis  = the delta/change metric
  //   Lines   = one per category (state, channel, product, …)
  // Always multi-line regardless of series count.
  else if (hint === "auto" && _isChangeMetric && catCol && dateCol) {
    vegaData = data
      .filter(d => { const v = d[numCol]; return v !== null && v !== undefined && v !== "" && !isNaN(Number(v)); })
      .map(d => ({
        date:   normDateStr(String(d[dateCol])),
        series: String(d[catCol]),
        val:    Number(d[numCol]),
      }));
    const changeYFmt   = isPctFraction ? ".2%" : (isPctCol ? ".0f" : "~s");
    const changeYTitle = isPctFraction ? yTitle : isPctCol ? `${yTitle} (%)` : yTitle;
    const seriesCount  = new Set(vegaData.map(d => d.series as string)).size;

    // With many series, use a right-side legend and thinner lines so colours still
    // scan left-to-right without the legend row eating half the chart height.
    const manyLegend = seriesCount > 12
      ? { orient: "right", direction: "vertical", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          labelFontSize: 10, title: cleanLabel(catCol), titleLimit: 160 }
      : { direction: "horizontal", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          title: cleanLabel(catCol), titleLimit: 160 };
    const strokeW = seriesCount > 20 ? 0.9 : seriesCount > 10 ? 1.1 : 1.5;

    const chgXEnc = { field: "date", type: "temporal", axis: { tickCount: 12, format: xDateFmt, labelAngle: 0, title: cleanLabel(dateCol) } };
    const chgYEnc = { field: "val",  type: "quantitative", axis: { format: changeYFmt, grid: true, title: changeYTitle } };
    const chgColorEnc = { field: "series", type: "nominal", legend: manyLegend };
    const chgTooltip = [
      { field: "date",   type: "temporal",     title: cleanLabel(dateCol), format: xDateFmt },
      { field: "series", type: "nominal",      title: cleanLabel(catCol) },
      { field: "val",    type: "quantitative", format: changeYFmt, title: changeYTitle },
    ];
    spec = {
      layer: [
        {
          mark: { type: "line", strokeWidth: strokeW },
          encoding: { x: chgXEnc, y: chgYEnc, color: chgColorEnc },
        },
        {
          mark: { type: "point", filled: true, size: 60 },
          params: [{ name: "chgHover", select: { type: "point", fields: ["date"], nearest: true, on: "pointerover", clear: "pointerout" } }],
          encoding: {
            x: chgXEnc,
            y: chgYEnc,
            color: chgColorEnc,
            opacity: { condition: { param: "chgHover", empty: false, value: 1 }, value: 0 },
            tooltip: chgTooltip,
          },
        },
      ],
    };
    defaultH = seriesCount > 15 ? 360 : 300;
  }

  // ── STACKED BAR (temporal or categorical) ────────────────────────────────────
  // Auto-trigger only when the category has ≤ 6 unique values — beyond that,
  // stacked bars become unreadable colour-salads. High-cardinality date+category
  // falls through to the multi-line auto path below.
  else if (hint === "stacked_bar" || (hint === "auto" && catCol && (catCol2 || dateCol) && !_isChangeMetric && _stackUnique <= 6)) {
    const isTemporalStack = !!(catCol && dateCol);
    vegaData = isTemporalStack && dateCol
      ? data.map(d => ({
          group: fmtDate(String(d[dateCol]), dateGran),
          stack: String(d[catCol]),
          val:   Number(d[numCol]),
        }))
      : data.map(d => ({
          group: String(d[catCol]),
          stack: catCol2 ? String(d[catCol2]) : "",
          val:   Number(d[numCol]),
        }));

    const groupTotals = new Map<string, number>();
    vegaData.forEach(d => groupTotals.set(
      d.group as string,
      (groupTotals.get(d.group as string) ?? 0) + (d.val as number),
    ));
    const groupOrder = (isTemporalStack || isTimeLabel)
      ? [...new Set(vegaData.map(d => d.group as string))]
      : [...groupTotals.entries()].sort((a, b) => b[1] - a[1]).map(([g]) => g);

    const stackLegendTitle = isTemporalStack
      ? cleanLabel(catCol)
      : (catCol2 ? cleanLabel(catCol2) : null);

    spec = {
      mark: { type: "bar" },
      encoding: {
        x: {
          field: "group", type: "ordinal", sort: groupOrder,
          axis: {
            labelAngle: 0, labelOverlap: true,
            title: isTemporalStack ? cleanLabel(dateCol ?? "") : cleanLabel(catCol),
          },
        },
        y: {
          field: "val", type: "quantitative", stack: "zero",
          axis: { format: yFmt, grid: true, title: yTitle },
        },
        color: {
          field: "stack", type: "nominal",
          legend: { title: stackLegendTitle },
        },
        tooltip: [
          { field: "group", type: "nominal",     title: isTemporalStack ? cleanLabel(dateCol ?? "") : cleanLabel(catCol) },
          { field: "stack", type: "nominal",     title: stackLegendTitle ?? undefined },
          { field: "val",   type: "quantitative", format: lblFmt, title: yTitle },
        ],
      },
    };
    defaultH = 280;
  }

  // ── TEMPORAL MULTI-LINE AUTO (date + category, many series, absolute metric) ──
  // Fires when stacked-bar auto was skipped (_stackUnique > 6) and no other branch
  // matched. Shows one line per category value over time — always better than a
  // heatmap for surfacing trends.  Uses P90 clipping + right legend when > 12 series.
  else if (hint === "auto" && dateCol && catCol && !_isChangeMetric) {
    vegaData = data
      .filter(d => { const v = d[numCol]; return v !== null && v !== undefined && v !== "" && !isNaN(Number(v)); })
      .map(d => ({
        date:   normDateStr(String(d[dateCol])),
        series: String(d[catCol]),
        val:    Number(d[numCol]),
      }));
    const tmSeriesCount = new Set(vegaData.map(d => d.series as string)).size;

    const tmLegend = tmSeriesCount > 12
      ? { orient: "right", direction: "vertical", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          labelFontSize: 10, title: cleanLabel(catCol), titleLimit: 160 }
      : { direction: "horizontal", symbolType: "stroke", symbolStrokeWidth: 2, symbolSize: 200,
          title: cleanLabel(catCol), titleLimit: 160 };
    const tmStrokeW = tmSeriesCount > 20 ? 0.9 : tmSeriesCount > 10 ? 1.1 : 1.5;

    const tmXEnc = { field: "date", type: "temporal", axis: { tickCount: 12, format: xDateFmt, labelAngle: 0, title: cleanLabel(dateCol) } };
    const tmYEnc = { field: "val",  type: "quantitative", axis: { format: yFmt, grid: true, title: yTitle } };
    const tmColorEnc = { field: "series", type: "nominal", legend: tmLegend };
    const tmTooltip = [
      { field: "date",   type: "temporal",     title: cleanLabel(dateCol), format: xDateFmt },
      { field: "series", type: "nominal",      title: cleanLabel(catCol) },
      { field: "val",    type: "quantitative", format: lblFmt, title: yTitle },
    ];
    spec = {
      layer: [
        {
          mark: { type: "line", strokeWidth: tmStrokeW },
          encoding: { x: tmXEnc, y: tmYEnc, color: tmColorEnc },
        },
        {
          mark: { type: "point", filled: true, size: 60 },
          params: [{ name: "tmHover", select: { type: "point", fields: ["date"], nearest: true, on: "pointerover", clear: "pointerout" } }],
          encoding: {
            x: tmXEnc,
            y: tmYEnc,
            color: tmColorEnc,
            opacity: { condition: { param: "tmHover", empty: false, value: 1 }, value: 0 },
            tooltip: tmTooltip,
          },
        },
      ],
    };
    defaultH = tmSeriesCount > 15 ? 360 : 300;
  }

  // ── DATE BAR (explicit bar on date + measure, no category) ──────────────────
  else if (dateCol && !catCol && (hint === "bar" || hint === "bar_horizontal")) {
    // The data is ALREADY aggregated by the SQL (DATE_TRUNC). Render each bucket
    // as its own bar on an ordinal axis with a grain-correct label — never re-bin
    // with timeUnit (which previously fused all weekly bars into one month bar).
    const sorted = [...data].sort((a, b) =>
      String(a[dateCol]).localeCompare(String(b[dateCol])));
    vegaData = sorted.map(d => ({
      bucket: fmtDate(String(d[dateCol]), dateGran),
      val:    Number(d[numCol]),
    }));
    const bucketOrder = vegaData.map(d => (d as { bucket: string }).bucket);
    spec = {
      padding: { top: 24 },   // room for above-bar labels
      layer: [
        { mark: { type: "bar", color: "#818cf8", opacity: 0.85 } },
        {
          // Value label above each bar, inside top padding
          mark: { type: "text", dy: -6, fontSize: 11, color: "#9AA0A8" },
          encoding: { text: { field: "val", type: "quantitative", format: lblFmt } },
        },
      ],
      encoding: {
        x: {
          field: "bucket", type: "ordinal", sort: bucketOrder,
          axis: { labelAngle: 0, title: cleanLabel(dateCol), labelOverlap: true },
        },
        y: { field: "val", type: "quantitative", axis: { format: yFmt, grid: true, title: yTitle } },
        tooltip: [
          { field: "bucket", type: "ordinal", title: cleanLabel(dateCol) },
          { field: "val",    type: "quantitative", format: lblFmt, title: yTitle },
        ],
      },
    };
    defaultH = 220;
  }

  // ── LINE / AREA (timeseries) ─────────────────────────────────────────────────
  else if (dateCol && !catCol && (hint === "line" || hint === "area" || hint === "auto")) {
    vegaData = data.map(d => ({
      ...d,
      [dateCol]: normDateStr(String(d[dateCol])),
      [numCol]:  Number(d[numCol]),
    }));
    const color = "#10b981";
    spec = {
      layer: [
        { mark: { type: "area", color, opacity: 0.08 } },
        { mark: { type: "line", color, strokeWidth: 1.5 } },
        {
          mark: { type: "point", color, size: 30, filled: true, opacity: 0.9 },
          encoding: {
            tooltip: [
              { field: dateCol, type: "temporal",     title: cleanLabel(dateCol) },
              { field: numCol,  type: "quantitative", format: lblFmt, title: yTitle },
            ],
          },
        },
      ],
      encoding: {
        x: {
          field: dateCol, type: "temporal",
          axis: { format: xDateFmt, labelAngle: 0, title: cleanLabel(dateCol) },
        },
        y: {
          field: numCol, type: "quantitative",
          axis: { format: yFmt, grid: true, title: yTitle },
        },
      },
      resolve: { scale: { y: "shared" } },
    };
    defaultH = 200;
  }

  // ── VERTICAL BAR ─────────────────────────────────────────────────────────────
  else if (catCol && hint === "bar_vertical") {
    const agg = new Map<string, number>();
    data.forEach(d => {
      const k = String(d[catCol]);
      agg.set(k, (agg.get(k) ?? 0) + Number(d[numCol]));
    });
    vegaData = (isTimeLabel
      ? [...agg.entries()]
      : [...agg.entries()].sort((a, b) => b[1] - a[1])
    ).map(([cat, val]) => ({ cat, val }));

    spec = {
      padding: { top: 24 },   // room for above-bar labels
      layer: [
        {
          mark: { type: "bar", color: "#818cf8", opacity: 0.85, cornerRadiusEnd: 2 },
        },
        {
          mark: { type: "text", dy: -6, fontSize: 11, color: "#9AA0A8" },
          encoding: { text: { field: "val", type: "quantitative", format: lblFmt } },
        },
      ],
      encoding: {
        x: {
          field: "cat", type: "ordinal",
          sort: isTimeLabel ? null : { field: "val", order: "descending" },
          axis: { labelAngle: 0, labelOverlap: true, title: xTitle },
        },
        y: {
          field: "val", type: "quantitative",
          axis: { format: yFmt, grid: true, title: yTitle },
        },
        tooltip: [
          { field: "cat", type: "nominal",     title: xTitle },
          { field: "val", type: "quantitative", format: lblFmt, title: yTitle },
        ],
      },
    };
    defaultH = 260;
  }

  // ── SCATTER ──────────────────────────────────────────────────────────────────
  else if (hint === "scatter" && numericCols.length >= 2) {
    const xNum = numericCols[0];
    const yNum = numericCols[1];
    const colorField = catCol || undefined;
    spec = {
      mark: { type: "point", filled: true, size: 40, opacity: 0.7 },
      encoding: {
        x: {
          field: xNum, type: "quantitative",
          axis: { format: "~s", grid: true, title: cleanLabel(xNum) },
        },
        y: {
          field: yNum, type: "quantitative",
          axis: { format: "~s", grid: true, title: cleanLabel(yNum) },
        },
        ...(colorField ? { color: { field: colorField, type: "nominal", legend: { title: cleanLabel(colorField) } } } : {}),
        tooltip: [
          { field: xNum, type: "quantitative", format: ",.2~f", title: cleanLabel(xNum) },
          { field: yNum, type: "quantitative", format: ",.2~f", title: cleanLabel(yNum) },
          ...(colorField ? [{ field: colorField, type: "nominal", title: cleanLabel(colorField) }] : []),
        ],
      },
    };
    defaultH = 300;
  }

  // ── HORIZONTAL BAR — default for all categorical data ────────────────────────
  else if (catCol) {
    const agg = new Map<string, number>();
    data.forEach(d => {
      const k = String(d[catCol]);
      agg.set(k, (agg.get(k) ?? 0) + Number(d[numCol]));
    });

    // ── COMBO CHART — multiple metrics with different mark types ───────────
    if (numericCols.length >= 2 && catCols.length === 1) {
      const primary   = numericCols[0];  // bars
      const secondary = numericCols[1];  // line
      vegaData = data;
      spec = {
        layer: [
          {
            mark: { type: "bar", color: "#818cf8", opacity: 0.8, cornerRadiusEnd: 2 },
            encoding: {
              y: {
                field: primary, type: "quantitative",
                axis: { format: yFmt, grid: true, title: cleanLabel(primary) },
              },
              tooltip: [
                { field: catCol, type: "nominal" },
                { field: primary, type: "quantitative", format: lblFmt, title: cleanLabel(primary) },
              ],
            },
          },
          {
            mark: { type: "line", color: "#E64848", strokeWidth: 2, point: { size: 30, filled: true, opacity: 0.9 } },
            encoding: {
              y: {
                field: secondary, type: "quantitative",
                axis: { format: yFmt, title: cleanLabel(secondary) },
              },
              tooltip: [
                { field: catCol, type: "nominal" },
                { field: secondary, type: "quantitative", format: lblFmt, title: cleanLabel(secondary) },
              ],
            },
          },
        ],
        encoding: {
          x: {
            field: catCol, type: "ordinal",
            sort: { field: primary, order: "descending" },
            axis: { labelLimit: 160, labelAngle: 0, labelOverlap: true, title: cleanLabel(catCol) },
          },
        },
        resolve: { scale: { y: "independent" } },
        config: { axisX: { labelAngle: 0, labelOverlap: "parity" } },
      };
      const groupCount = new Set(data.map(d => String(d[catCol]))).size;
      defaultH = 350;
    } else if (!spec && _isChangeMetric) {
      // ── CHANGE METRIC BAR ──────────────────────────────────────────────────
      // Sort by absolute magnitude so biggest movers (positive OR negative) appear first.
      // Use a symmetric x domain so negative bars extend to the left.
      // Diverging colours: green = growth, red = decline.
      vegaData = [...agg.entries()]
        .map(([cat, val]) => ({ cat, val }))
        .sort((a, b) => Math.abs(b.val as number) - Math.abs(a.val as number));

      const maxAbsVal = Math.max(...vegaData.map(d => Math.abs(d.val as number)), 1);
      // Format: if values look like stored-as-100x percentages (e.g. 15.2 for 15.2%)
      // keep ~g format with an axis title suffix; if they're 0-1 fractions use .2%
      const changeFmt = isPctFraction ? "+.2%" : "+.1f";
      const changeAxisTitle = isPctFraction ? yTitle : `${yTitle}${isPctCol ? " (%)" : ""}`;

      spec = {
        mark: { type: "bar", opacity: 0.85, cornerRadiusEnd: 2 },
        encoding: {
          x: {
            field: "val", type: "quantitative",
            scale: { domain: [-maxAbsVal * 1.18, maxAbsVal * 1.18] },
            axis: { format: changeFmt, grid: true, title: changeAxisTitle },
          },
          y: {
            field: "cat", type: "ordinal",
            sort: { field: "val", op: "sum", order: "descending" },
            axis: { labelLimit: 160, labelAngle: 0, labelOverlap: true, title: cleanLabel(catCol) },
          },
          color: {
            condition: { test: "datum.val >= 0", value: "#2EC87B" },
            value: "#E64848",
          },
          tooltip: [
            { field: "cat", type: "nominal",      title: cleanLabel(catCol) },
            { field: "val", type: "quantitative",  format: changeFmt, title: changeAxisTitle },
          ],
        },
      };
      defaultH = Math.max(350, vegaData.length * 28 + 60);

    } else if (!spec) {
      // ── STANDARD BAR ──────────────────────────────────────────────────────
      vegaData = (isTimeLabel
        ? [...agg.entries()]
        : [...agg.entries()].sort((a, b) => b[1] - a[1])
      ).map(([cat, val]) => ({ cat, val }));

      // Show all bars — container scrolls when needed

      // Extend x domain 14% past the max so the label of the widest bar has room.
      const maxBarVal = Math.max(...vegaData.map(d => d.val as number), 1);

      spec = {
        layer: [
          {
            mark: { type: "bar", color: "#818cf8", opacity: 0.85, cornerRadiusEnd: 2 },
          },
          // Single text layer — always positioned just past the bar's right edge.
          {
            mark: { type: "text", align: "left", dx: 5, fontSize: 11, color: "#9AA0A8" },
            encoding: { text: { field: "val", type: "quantitative", format: lblFmt } },
          },
        ],
        encoding: {
          y: {
            field: "cat", type: "ordinal",
            sort: isTimeLabel ? null : { field: "val", order: "descending" },
            axis: { labelLimit: 160, labelAngle: 0, labelOverlap: true, title: cleanLabel(catCol) },
          },
          x: {
            field: "val", type: "quantitative",
            scale: { domainMax: maxBarVal * 1.14 },
            axis: { format: yFmt, grid: true, title: yTitle },
          },
          tooltip: [
            { field: "cat", type: "nominal",     title: xTitle },
            { field: "val", type: "quantitative", format: lblFmt, title: yTitle },
          ],
        },
      };
      defaultH = Math.max(350, vegaData.length * 28 + 60);
    }
  }

  // ── FINAL FALLBACK: simple line chart when we have a date + number but
  // no other branch matched (e.g. period-over-period with a single series).
  else if (!spec && dateCol && numCol) {
    vegaData = data
      .filter(d => { const v = d[numCol]; return v !== null && v !== undefined && v !== "" && !isNaN(Number(v)); })
      .map(d => ({
        ...d,
        [dateCol]: normDateStr(String(d[dateCol])),
        [numCol]:  Number(d[numCol]),
      }));
    const fbColor = "#818cf8";
    spec = {
      layer: [
        { mark: { type: "line", color: fbColor, strokeWidth: 1.5 } },
        {
          mark: { type: "point", color: fbColor, size: 30, filled: true, opacity: 0.9 },
          encoding: {
            tooltip: [
              { field: dateCol, type: "temporal",     title: cleanLabel(dateCol) },
              { field: numCol,  type: "quantitative", format: lblFmt, title: yTitle },
            ],
          },
        },
      ],
      encoding: {
        x: {
          field: dateCol, type: "temporal",
          axis: { format: xDateFmt, labelAngle: 0, title: cleanLabel(dateCol) },
        },
        y: {
          field: numCol, type: "quantitative",
          axis: { format: yFmt, grid: true, title: yTitle },
        },
      },
    };
    defaultH = 350;
  }

  if (!spec) return null;

  // Base chart height fills the 350px component; grows only if y-axis labels would overlap.
  const chartH  = userH ?? defaultH;

  return (
    <div className="mt-2 w-full group/chart">
      {/* Header row: download + labels toggle buttons appear on hover */}
      {chrome && (
      <div className="flex justify-end h-6 mb-0.5 opacity-0 group-hover/chart:opacity-100 transition-opacity gap-1">
        <button
          onClick={() => setShowLabels(s => !s)}
          title={showLabels ? "Hide data labels" : "Show data labels"}
          className={`w-6 h-6 flex items-center justify-center rounded transition-colors ${showLabels ? "bg-blue-500/20 text-blue-300" : "bg-zinc-800/80 hover:bg-zinc-700 text-zinc-500 hover:text-zinc-200"}`}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 7V4h3" />
            <path d="M4 17v3h3" />
            <path d="M20 7V4h-3" />
            <path d="M20 17v3h-3" />
            <path d="M9 9h6v6H9z" />
          </svg>
        </button>
        <button
          onClick={handleDownloadPng}
          title="Download chart as PNG"
          className="w-6 h-6 flex items-center justify-center rounded bg-zinc-800/80 hover:bg-zinc-700 text-zinc-500 hover:text-zinc-200 transition-colors"
        >
          <DownloadIcon label="Download chart as PNG" size="small" />
        </button>
      </div>
      )}

      {/* Chart viewport — fixed 350px with internal scroll; Vega renders at full natural height */}
      <div ref={outerRef} style={{ maxHeight: 350, overflowY: 'auto', overflowX: 'auto', width: '100%' }}>
        <div ref={chartRef}>
          <VegaChart spec={spec} data={vegaData} height={chartH} showLabels={showLabels} />
        </div>
      </div>


      {/* Drag-to-resize handle */}
      {chrome && (
      <div
        onMouseDown={startDrag}
        className="flex items-center justify-center h-3 cursor-ns-resize group/drag"
      >
        <div className="w-10 h-0.5 rounded-full bg-zinc-800 group-hover/drag:bg-zinc-600 transition-colors" />
      </div>
      )}
    </div>
  );
}
