"use client";

import { CHART_TYPE_LABEL, type ChartType } from "./chartTypeInference";
import { Segmented } from "@/components/ui/segmented";

interface Props {
  value: ChartType | "auto";
  available: ChartType[];
  onChange: (t: ChartType | "auto") => void;
}

const ICONS: Record<ChartType | "auto", string> = {
  auto:           "◈",
  line:           "〜",
  "multi-line":   "≋",
  "small-multiples": "⊟",
  area:           "◿",
  bar:            "▬",
  "grouped-bar":  "▦",
  "combo":        "◫",
  "delta-bar":    "±",
  "stacked-bar":  "▥",
  scatter:        "⁘",
  heatmap:        "▣",
  matrix:         "⊞",
  pie:            "◔",
  treemap:        "⊞",
  counter:        "#",
  funnel:         "▽",
  histogram:      "≣",
  boxplot:        "⧗",
  sankey:         "⋈",
  waterfall:      "▨",
  "line-forecast": "⤳",
  gantt:          "▤",
  choropleth:     "◍",
  "point-map":    "◉",
  table:          "≡",
};

// Labels come from the shared CHART_TYPE_LABEL (single source of truth).

export function ChartTypeToggle({ value, available, onChange }: Props) {
  const options: (ChartType | "auto")[] = ["auto", ...available, "table"];
  // deduplicate in case caller passed "table" in available
  const unique = Array.from(new Set(options));

  return (
    <Segmented label="Chart type" value={value} onChange={onChange}
      options={unique.map((t) => ({ value: t, title: CHART_TYPE_LABEL[t], label: <span className="font-mono">{ICONS[t]}</span> }))} />
  );
}
