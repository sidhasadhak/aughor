"use client";

import type { ChartType } from "./chartTypeInference";

interface Props {
  value: ChartType | "auto";
  available: ChartType[];
  onChange: (t: ChartType | "auto") => void;
}

const ICONS: Record<ChartType | "auto", string> = {
  auto:           "◈",
  line:           "〜",
  "multi-line":   "≋",
  area:           "◿",
  bar:            "▬",
  "grouped-bar":  "▦",
  "stacked-bar":  "▥",
  scatter:        "⁘",
  heatmap:        "▣",
  pie:            "◔",
  treemap:        "⊞",
  table:          "≡",
};

const LABELS: Record<ChartType | "auto", string> = {
  auto:           "Auto",
  line:           "Line",
  "multi-line":   "Multi-line",
  area:           "Area",
  bar:            "Bar",
  "grouped-bar":  "Grouped",
  "stacked-bar":  "Stacked",
  scatter:        "Scatter",
  heatmap:        "Heatmap",
  pie:            "Pie",
  treemap:        "Treemap",
  table:          "Table",
};

export function ChartTypeToggle({ value, available, onChange }: Props) {
  const options: (ChartType | "auto")[] = ["auto", ...available, "table"];
  // deduplicate in case caller passed "table" in available
  const unique = Array.from(new Set(options));

  return (
    <div className="flex items-center gap-0.5">
      {unique.map((t) => (
        <button
          key={t}
          title={LABELS[t]}
          onClick={() => onChange(t)}
          className={`px-1.5 py-0.5 rounded text-[11px] font-mono transition-colors ${
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
