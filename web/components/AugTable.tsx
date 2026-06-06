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

import React, { useMemo, useState } from "react";
import { Table, ConfigProvider, theme } from "antd";
import type { TableProps, TableColumnsType } from "antd";

// ── Aughor dark tokens for Ant Design ───────────────────────────────────────

const AUG_THEME: Parameters<typeof ConfigProvider>[0]["theme"] = {
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
    colorTextSecondary:  "#8B929D",   // --t2
    colorTextDescription:"#5A6270",   // --t3
    colorTextDisabled:   "#3A414D",   // --t4
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
      headerColor:          "#5A6270",   // --t3
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

// ── Helpers ──────────────────────────────────────────────────────────────────

const ORDINAL_COL = /\bid\b|_id$|^id$|id$|Id$|ID$/i;
const SHARE_COL   = /pct|percent|share|rate|ratio|proportion/i;

function isNumericValue(v: unknown): boolean {
  if (v == null || v === "") return false;
  return !isNaN(Number(v));
}

function cleanLabel(col: string): string {
  return col
    .replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase());
}

function fmt(col: string, v: unknown): React.ReactNode {
  if (v == null) {
    return <span style={{ color: "#2B3B52", userSelect: "none" }}>—</span>;
  }
  const s = String(v);
  // Percentage columns: if value is in (-1, 1) it's a stored ratio → multiply ×100
  // Values outside that range are already percentages (e.g. 11.8 = 11.8%, -60.89 = -60.89%)
  if (SHARE_COL.test(col)) {
    const n = Number(v);
    if (!isNaN(n)) {
      const pct = Math.abs(n) <= 1 ? n * 100 : n;
      return <span style={{ fontVariantNumeric: "tabular-nums" }}>{pct.toFixed(1)}%</span>;
    }
  }
  // Large numbers
  const n = Number(v);
  if (!isNaN(n) && !ORDINAL_COL.test(col) && s.trim() !== "") {
    const formatted =
      Math.abs(n) >= 1e9 ? `${(n / 1e9).toFixed(2)}B` :
      Math.abs(n) >= 1e6 ? `${(n / 1e6).toFixed(2)}M` :
      Math.abs(n) >= 1e3 ? n.toLocaleString("en-US", { maximumFractionDigits: 2 }) :
      Number.isInteger(n) ? String(n) :
      n.toFixed(4).replace(/\.?0+$/, "");
    return <span style={{ fontVariantNumeric: "tabular-nums" }}>{formatted}</span>;
  }
  return s;
}

// ── Core AugTable component ──────────────────────────────────────────────────

export function AugTable<T extends object = Record<string, unknown>>(
  props: TableProps<T>,
) {
  return (
    <ConfigProvider theme={AUG_THEME}>
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
