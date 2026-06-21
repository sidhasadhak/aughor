"use client";

/**
 * AugTable — Ant Design Table wired to Aughor's dark design tokens.
 *
 * Usage (raw SQL results):
 *   <SqlResultTable columns={["id","name","revenue"]} rows={rows} />
 *
 * Usage (typed data):
 *   <AugTable<MyRow> columns={antColumns} dataSource={data} />
 */

import React, { useEffect, useMemo, useState } from "react";
import { Table, ConfigProvider, theme } from "antd";
import type { TableProps, TableColumnsType } from "antd";
import { cleanLabel, formatMetricValue, formatPercent, displayCellValue } from "@/lib/format";
import { isMoneyColumn, effectiveCurrencySymbol } from "@/lib/orgSettings";
import { useOrgSettings } from "@/lib/useOrgSettings";

// ── Theme-mode hook ──────────────────────────────────────────────────────────
// Ant Design's theme tokens must be real colors (it derives shades), so we can't
// feed it CSS vars. Instead we watch <html data-theme> and hand Ant a matching
// dark/light token set so tables flip with the rest of the app.
function useThemeMode(): "light" | "dark" {
  const [mode, setMode] = useState<"light" | "dark">(() =>
    typeof document !== "undefined" && document.documentElement.getAttribute("data-theme") === "light"
      ? "light" : "dark");
  useEffect(() => {
    const el = document.documentElement;
    const sync = () => setMode(el.getAttribute("data-theme") === "light" ? "light" : "dark");
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(el, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return mode;
}

// ── Aughor dark tokens for Ant Design ───────────────────────────────────────

const AUG_THEME_DARK: Parameters<typeof ConfigProvider>[0]["theme"] = {
  algorithm: theme.darkAlgorithm,
  token: {
    // Backgrounds
    colorBgBase:         "#0D1117",   // --bg-0
    colorBgContainer:    "#111418",   // --bg-1
    colorBgElevated:     "#161A20",   // --bg-2
    colorBgLayout:       "#0D1117",
    // Borders
    colorBorder:         "#1E2329",   // --b1
    colorBorderSecondary:"#161A20",   // --b0
    colorSplit:          "#161A20",
    // Text
    colorText:           "#E2E4E9",   // --t1
    colorTextSecondary:  "#939AA6",   // --t2
    colorTextDescription:"#6E7886",   // --t3
    colorTextDisabled:   "#525B69",   // --t4
    // Brand
    colorPrimary:        "#0C8CE9",   // --blue3
    colorPrimaryHover:   "#4BA3F5",   // --blue4
    // Misc
    fontSize:            12,
    fontFamily:          "'DM Sans', system-ui, sans-serif",
    borderRadius:        3,
    borderRadiusSM:      2,
    controlHeight:       30,
    lineWidth:           1,
  },
  components: {
    Table: {
      // Header
      headerBg:             "#161A20",   // --bg-2
      headerColor:          "#6E7886",   // --t3
      headerSortActiveBg:   "#161A20",
      headerSortHoverBg:    "#1C2128",   // --bg-3
      headerSplitColor:     "#1E2329",   // --b1
      // Rows
      rowHoverBg:           "rgba(255, 255, 255, 0.035)",
      rowSelectedBg:        "rgba(12, 140, 233, 0.10)",    // --bg-sel
      rowSelectedHoverBg:   "rgba(12, 140, 233, 0.18)",
      bodySortBg:           "#111418",
      // Borders
      borderColor:          "#161A20",   // --b0
      // Cell sizing
      cellFontSize:         12,
      cellPaddingInline:    14,
      cellPaddingBlock:     9,
    },
    Pagination: {
      colorBgContainer:    "#111418",
      itemActiveBg:        "rgba(12, 140, 233, 0.12)",
    },
  },
};

// ── Aughor light tokens for Ant Design (mirrors the light palette in tokens.css) ──
const AUG_THEME_LIGHT: Parameters<typeof ConfigProvider>[0]["theme"] = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorBgBase:          "#F5F5F5",   // --bg-0
    colorBgContainer:     "#FFFFFF",   // --bg-1
    colorBgElevated:      "#FAFAFA",   // --bg-2
    colorBgLayout:        "#F5F5F5",
    colorBorder:          "#E1E1E1",   // --b1
    colorBorderSecondary: "#ECECEC",   // --b0
    colorSplit:           "#ECECEC",
    colorText:            "#333333",   // --t1
    colorTextSecondary:   "#555555",   // --t2
    colorTextDescription: "#787878",   // --t3
    colorTextDisabled:    "#9E9E9E",   // --t4
    colorPrimary:         "#1F77B4",   // --blue3
    colorPrimaryHover:    "#175A88",   // --blue4
    fontSize:             12,
    fontFamily:           "'DM Sans', system-ui, sans-serif",
    borderRadius:         3,
    borderRadiusSM:       2,
    controlHeight:        30,
    lineWidth:            1,
  },
  components: {
    Table: {
      headerBg:           "#FAFAFA",   // --bg-2
      headerColor:        "#787878",   // --t3
      headerSortActiveBg: "#F0F0F0",   // --bg-3
      headerSortHoverBg:  "#F0F0F0",   // --bg-3
      headerSplitColor:   "#E1E1E1",   // --b1
      rowHoverBg:         "rgba(0, 0, 0, 0.04)",
      rowSelectedBg:      "rgba(31, 119, 180, 0.10)",
      rowSelectedHoverBg: "rgba(31, 119, 180, 0.16)",
      bodySortBg:         "#FFFFFF",
      borderColor:        "#ECECEC",   // --b0
      cellFontSize:       12,
      cellPaddingInline:  14,
      cellPaddingBlock:   9,
    },
    Pagination: {
      colorBgContainer:   "#FFFFFF",
      itemActiveBg:       "rgba(31, 119, 180, 0.12)",
    },
  },
};

// ── Helpers ──────────────────────────────────────────────────────────────────

const ORDINAL_COL = /\bid\b|_id$|^id$|id$|Id$|ID$/i;
const SHARE_COL   = /pct|percent|share|rate|ratio|proportion/i;

function isNumericValue(v: unknown): boolean {
  if (v == null || v === "") return false;
  return !isNaN(Number(v));
}

function fmt(col: string, v: unknown): React.ReactNode {
  if (v == null) {
    return <span style={{ color: "#2B3B52", userSelect: "none" }}>—</span>;
  }
  const s = String(v);
  // Percentage columns: stored ratio (|v|≤1) ×100, else already a percentage.
  if (SHARE_COL.test(col)) {
    const n = Number(v);
    if (!isNaN(n)) {
      return <span style={{ fontVariantNumeric: "tabular-nums" }}>{formatPercent(n, 1)}</span>;
    }
  }
  // Monetary columns — prefix the configured reporting currency symbol (when one is set).
  if (isMoneyColumn(col)) {
    const money = Number(v);
    const sym = effectiveCurrencySymbol();
    if (sym && !isNaN(money) && s.trim() !== "") {
      return <span style={{ fontVariantNumeric: "tabular-nums" }}>{sym}{formatMetricValue(money)}</span>;
    }
  }
  // Large / numeric cells — canonical data-table value formatting.
  const n = Number(v);
  if (!isNaN(n) && !ORDINAL_COL.test(col) && s.trim() !== "") {
    return <span style={{ fontVariantNumeric: "tabular-nums" }}>{formatMetricValue(n)}</span>;
  }
  // Collapse a DATE_TRUNC'd midnight timestamp ("2025-04-01 00:00:00") to its date.
  return displayCellValue(s);
}

// ── Core AugTable component ──────────────────────────────────────────────────

export function AugTable<T extends object = Record<string, unknown>>(
  props: TableProps<T>,
) {
  const antTheme = useThemeMode() === "light" ? AUG_THEME_LIGHT : AUG_THEME_DARK;
  return (
    <ConfigProvider theme={antTheme}>
      <Table<T>
        size="small"
        showSorterTooltip={false}
        {...props}
      />
    </ConfigProvider>
  );
}

// ── SqlResultTable — converts raw SQL columns/rows ───────────────────────────

interface SqlResultTableProps {
  columns: string[];
  rows: unknown[][];
  maxHeight?: number;
  /** Extra column overrides, keyed by column name */
  columnOverrides?: Record<string, Partial<TableColumnsType<Record<string, unknown>>[number]>>;
  /** Show the "Σ Totals" on/off toggle (when there's at least one summable column). Default true. */
  totals?: boolean;
  /** Max rendered width (px) per cell — long text truncates with an ellipsis + tooltip. Default 320. */
  maxColWidth?: number;
}

export function SqlResultTable({
  columns,
  rows,
  maxHeight = 320,
  columnOverrides = {},
  totals = true,
  maxColWidth = 320,
}: SqlResultTableProps) {
  // Re-render when org settings change (currency/date) so the inline cell formatting
  // below re-reads them — tables previously read at render but never subscribed.
  useOrgSettings();
  const [showTotals, setShowTotals] = useState(false);

  // Per-column summable detection + column sums.
  // Summable = every non-blank value is numeric, and the column is not an
  // identifier (id/_id) nor a share/percent/rate column (summing those is meaningless).
  const sums = useMemo(
    () =>
      columns.map((col, idx) => {
        if (ORDINAL_COL.test(col) || SHARE_COL.test(col)) return null;
        let saw = false;
        let sum = 0;
        for (const r of rows) {
          const v = (r as unknown[])[idx];
          if (v == null || v === "") continue;
          if (isNaN(Number(v))) return null;
          sum += Number(v);
          saw = true;
        }
        return saw ? sum : null;
      }),
    [columns, rows],
  );
  const hasSummable = sums.some(s => s !== null);
  const firstTextCol = sums.findIndex(s => s === null);

  // Build Ant Design column defs
  const antCols: TableColumnsType<Record<string, unknown>> = columns.map(col => {
    const isNum = !ORDINAL_COL.test(col) && rows.length > 0 && isNumericValue(rows[0]?.[columns.indexOf(col)]);
    return {
      key: col,
      title: cleanLabel(col),
      dataIndex: col,
      ellipsis: true,
      align: isNum ? "right" : "left",
      sorter: (a: Record<string, unknown>, b: Record<string, unknown>) => {
        const va = a[col], vb = b[col];
        if (va == null) return -1;
        if (vb == null) return 1;
        if (isNumericValue(va) && isNumericValue(vb)) return Number(va) - Number(vb);
        return String(va).localeCompare(String(vb));
      },
      render: (val: unknown) => (
        <span
          title={val == null ? undefined : String(val)}
          style={{
            display: "block", maxWidth: maxColWidth,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            fontFamily: "var(--font-mono)", fontSize: 11,
          }}
        >
          {fmt(col, val)}
        </span>
      ),
      ...columnOverrides[col],
    };
  });

  const dataSource = rows.map((r, i) => ({
    key: i,
    ...Object.fromEntries(columns.map((c, j) => [c, (r as unknown[])[j]])),
  }));

  const showToggle = totals && hasSummable && rows.length > 0;

  const summary =
    showToggle && showTotals
      ? () => (
          <Table.Summary fixed>
            <Table.Summary.Row>
              {columns.map((col, i) => (
                <Table.Summary.Cell index={i} key={col} align={sums[i] !== null ? "right" : "left"}>
                  {sums[i] !== null ? (
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 600 }}>
                      {fmt(col, sums[i] as number)}
                    </span>
                  ) : i === firstTextCol ? (
                    <span style={{ color: "#9DA1A8", fontWeight: 600 }}>Total</span>
                  ) : null}
                </Table.Summary.Cell>
              ))}
            </Table.Summary.Row>
          </Table.Summary>
        )
      : undefined;

  return (
    <div className="flex flex-col gap-1.5">
      {showToggle && (
        <div className="flex items-center">
          <button
            onClick={() => setShowTotals(v => !v)}
            title="Show a totals row summing numeric columns"
            className={`text-[11px] px-2 py-0.5 rounded border transition-colors ${showTotals ? "border-blue-500/40 bg-blue-500/10 text-blue-300" : "border-zinc-700 text-zinc-500 hover:text-zinc-300"}`}
          >
            Σ Totals {showTotals ? "on" : "off"}
          </button>
        </div>
      )}
      <AugTable<Record<string, unknown>>
        columns={antCols}
        dataSource={dataSource}
        scroll={{ x: "max-content", y: maxHeight }}
        pagination={rows.length > 100 ? { pageSize: 100, size: "small", showSizeChanger: false } : false}
        summary={summary}
        style={{ fontSize: 12 }}
      />
    </div>
  );
}
