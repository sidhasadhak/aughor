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
import { Table, ConfigProvider, theme, type ThemeConfig } from "antd";
import type { TableProps, TableColumnsType } from "antd";
import { cleanLabel, formatTableNumber, formatPercent, displayCellValue } from "@/lib/format";
import { isMoneyColumn, columnCurrencySymbol } from "@/lib/orgSettings";
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

// ── Aughor tokens for Ant Design — DERIVED from the live token sheet ─────────
// Ant's theme tokens must be real colors (it derives shades), so we can't hand it
// `var(--bg-0)` strings. Instead both mode themes are built from a single
// getComputedStyle read of the ACTIVE sheet (tokens-v2 wins the cascade), so the
// antd grid can never drift from the design tokens again — the old hand-mirrored
// LIGHT block had fossilized the retired v1 palette. The literals below are
// SSR/fallback values only, kept in sync with aughor-v2/theme/tokens-v2.css.

const TOKEN_FALLBACK: Record<"dark" | "light", Record<string, string>> = {
  dark: {
    "--bg-0": "#0A0A0E", "--bg-1": "#0C0D12", "--bg-2": "#121318", "--bg-3": "#181A21",
    "--bg-4": "#20222B", "--b0": "#1A1C23", "--b1": "#23252E",
    "--t1": "#F2F3F6", "--t2": "#989BA6", "--t3": "#686B77", "--t4": "#525B69",
    "--blue3": "#5A9FD6", "--blue4": "#7DB6E8",
    "--bg-hover": "rgba(255, 255, 255, 0.045)", "--bg-sel": "rgba(90, 159, 214, 0.14)",
  },
  light: {
    "--bg-0": "#F4F6FA", "--bg-1": "#FFFFFF", "--bg-2": "#FFFFFF", "--bg-3": "#F7F9FC",
    "--bg-4": "#EDF1F7", "--b0": "#EEF1F6", "--b1": "#E7ECF3",
    "--t1": "#1C2330", "--t2": "#5A6678", "--t3": "#8593A6", "--t4": "#A9B4C4",
    "--blue3": "#1F77B4", "--blue4": "#175A88",
    "--bg-hover": "rgba(15, 30, 60, 0.04)", "--bg-sel": "rgba(31, 119, 180, 0.10)",
  },
};

// Selected-row hover: a stronger tint of the selection wash — no dedicated token.
const ROW_SELECTED_HOVER: Record<"dark" | "light", string> = {
  dark: "rgba(90, 159, 214, 0.22)",
  light: "rgba(31, 119, 180, 0.16)",
};

function buildAntTheme(mode: "dark" | "light"): ThemeConfig {
  const fb = TOKEN_FALLBACK[mode];
  const cs = typeof window !== "undefined" ? getComputedStyle(document.documentElement) : null;
  const v = (name: string) => (cs?.getPropertyValue(name).trim() || fb[name]);
  return {
    algorithm: mode === "light" ? theme.defaultAlgorithm : theme.darkAlgorithm,
    token: {
      // Backgrounds
      colorBgBase:          v("--bg-0"),
      colorBgContainer:     v("--bg-1"),
      colorBgElevated:      v("--bg-2"),
      colorBgLayout:        v("--bg-0"),
      // Borders (hairlines)
      colorBorder:          v("--b1"),
      colorBorderSecondary: v("--b0"),
      colorSplit:           v("--b0"),
      // Text
      colorText:            v("--t1"),
      colorTextSecondary:   v("--t2"),
      colorTextDescription: v("--t3"),
      colorTextDisabled:    v("--t4"),
      // Brand (interaction accent)
      colorPrimary:         v("--blue3"),
      colorPrimaryHover:    v("--blue4"),
      // Misc — grid stays DM Sans (text columns readable); numeric formatting keeps tabular alignment
      fontSize:             12,
      fontFamily:           "'DM Sans', system-ui, sans-serif",
      borderRadius:         6,   // --r1 (v2 control radius; was the retired 3px)
      borderRadiusSM:       4,
      controlHeight:        30,
      lineWidth:            1,
    },
    components: {
      Table: {
        // Header
        headerBg:           v("--bg-3"),
        headerColor:        v("--t2"),
        headerSortActiveBg: v("--bg-3"),
        headerSortHoverBg:  v("--bg-4"),
        headerSplitColor:   v("--b1"),
        // Rows
        rowHoverBg:         v("--bg-hover"),
        rowSelectedBg:      v("--bg-sel"),
        rowSelectedHoverBg: ROW_SELECTED_HOVER[mode],
        bodySortBg:         v("--bg-1"),
        // Borders
        borderColor:        v("--b0"),
        // Cell sizing
        cellFontSize:       12,
        cellPaddingInline:  14,
        cellPaddingBlock:   9,
      },
      Pagination: {
        colorBgContainer:   v("--bg-1"),
        itemActiveBg:       v("--bg-sel"),
      },
    },
  };
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const ORDINAL_COL = /\bid\b|_id$|^id$|id$|Id$|ID$/i;
const SHARE_COL   = /pct|percent|share|rate|ratio|proportion/i;
// Temporal/grouping KEY columns (departure_month=6, departure_quarter=2, year=2024). These are
// labels, not measures: summing them is meaningless and metric-formatting turns a year into
// "2.02K". Treat as identifiers — render the raw value and exclude from the Σ totals.
const DIMENSION_KEY_COL = /(?<![a-z])(?:year|quarter|qtr|month|week|weekday|dow|day_of_week|hour|fiscal_period|period_no)(?![a-z])/i;

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
    // A column that names its own currency (refund_chf → CHF) overrides the workspace default.
    const sym = columnCurrencySymbol(col);
    if (sym && !isNaN(money) && s.trim() !== "") {
      return <span style={{ fontVariantNumeric: "tabular-nums" }}>{sym}{formatTableNumber(money)}</span>;
    }
  }
  // Large / numeric cells — the FULL number with separators, never K/M/B: a column is read
  // down, and a per-row magnitude suffix makes two cells incomparable at a glance. Skip key
  // columns (ids + temporal grouping keys) so a month "6" or year "2024" renders raw.
  const n = Number(v);
  if (!isNaN(n) && !ORDINAL_COL.test(col) && !DIMENSION_KEY_COL.test(col) && s.trim() !== "") {
    return <span style={{ fontVariantNumeric: "tabular-nums" }}>{formatTableNumber(n)}</span>;
  }
  // Collapse a DATE_TRUNC'd midnight timestamp ("2025-04-01 00:00:00") to its date.
  return displayCellValue(s);
}

// ── Core AugTable component ──────────────────────────────────────────────────

export function AugTable<T extends object = Record<string, unknown>>(
  props: TableProps<T>,
) {
  const mode = useThemeMode();
  // Re-read tokens whenever the theme flips — getComputedStyle sees the sheet the
  // moment [data-theme] changes (the MutationObserver in useThemeMode re-renders us).
  const antTheme = useMemo(() => buildAntTheme(mode), [mode]);
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
        if (ORDINAL_COL.test(col) || SHARE_COL.test(col) || DIMENSION_KEY_COL.test(col)) return null;
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
            className={`aug-fs-xs px-2 py-0.5 rounded border transition-colors ${showTotals ? "border-blue-500/40 bg-blue-500/10 text-blue-300" : "border-zinc-700 text-zinc-500 hover:text-zinc-300"}`}
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
