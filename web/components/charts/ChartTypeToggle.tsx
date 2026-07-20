"use client";

import { CHART_TYPE_LABEL, type ChartType } from "./chartTypeInference";

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
    <div className="flex items-center gap-0.5">
      {unique.map((t) => (
        <button
          key={t}
          title={CHART_TYPE_LABEL[t]}
          onClick={() => onChange(t)}
          className={`px-1.5 py-0.5 rounded aug-fs-xs font-mono transition-colors ${
            value === t
              ? "bg-blue-500/20 text-blue-300 border border-blue-500/40"
              : "text-zinc-500 hover:text-zinc-300 border border-transparent"
          }`}
        >
          {ICONS[t]}
        </button>
      ))}
    </div>
  );
}
