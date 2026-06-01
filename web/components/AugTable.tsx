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

import React from "react";
import { Table, ConfigProvider, theme } from "antd";
import type { TableProps, TableColumnsType } from "antd";

// ── Aughor dark tokens for Ant Design ───────────────────────────────────────

const AUG_THEME: Parameters<typeof ConfigProvider>[0]["theme"] = {
  algorithm: theme.darkAlgorithm,
  token: {
    // Backgrounds
    colorBgBase:         "#11171d",   // --bg-0
    colorBgContainer:    "#172030",   // --bg-2
    colorBgElevated:     "#1C2839",   // --bg-3
    colorBgLayout:       "#11171d",
    // Borders
    colorBorder:         "#1B2840",   // --b1
    colorBorderSecondary:"#131C2B",   // --b0
    colorSplit:          "#131C2B",
    // Text
    colorText:           "#C8D4E4",   // --t1
    colorTextSecondary:  "#8296AF",   // --t2
    colorTextDescription:"#485E7C",   // --t3
    colorTextDisabled:   "#2B3B52",   // --t4
    // Brand
    colorPrimary:        "#4C8EEE",   // --blue4
    colorPrimaryHover:   "#88BAFF",   // --blue5
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
      headerBg:             "#1C2839",   // --bg-3
      headerColor:          "#485E7C",   // --t3 — same as aug-label
      headerSortActiveBg:   "#1C2839",
      headerSortHoverBg:    "#223246",   // --bg-4
      headerSplitColor:     "#1B2840",   // --b1
      // Rows
      rowHoverBg:           "rgba(45, 114, 210, 0.07)",  // --bg-hover
      rowSelectedBg:        "#1A3A6E",   // --blue2
      rowSelectedHoverBg:   "#1A3A6E",
      bodySortBg:           "#172030",
      // Borders
      borderColor:          "#131C2B",   // --b0
      // Cell sizing
      cellFontSize:         12,
      cellPaddingInline:    14,
      cellPaddingBlock:     9,
      // Sort icon
      // filterDropdownBg: "#1C2839",
    },
    Pagination: {
      colorBgContainer:    "#172030",
      itemActiveBg:        "#1A3A6E",
    },
  },
};

// ── Helpers ──────────────────────────────────────────────────────────────────

const ORDINAL_COL = /\bid\b|_id$|^id$/i;
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
}

export function SqlResultTable({
  columns,
  rows,
  maxHeight = 320,
  columnOverrides = {},
}: SqlResultTableProps) {
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
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>
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

  return (
    <AugTable<Record<string, unknown>>
      columns={antCols}
      dataSource={dataSource}
      scroll={{ x: "max-content", y: maxHeight }}
      pagination={rows.length > 100 ? { pageSize: 100, size: "small", showSizeChanger: false } : false}
      style={{ fontSize: 12 }}
    />
  );
}
