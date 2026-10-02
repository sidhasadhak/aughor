"use client";
/**
 * A result of ONE row is its figures, read in a line — not a table.
 *
 * "If it's a single number being displayed, does one really need a table? How un-intelligent is
 * that?" (2026-10-02). Q1's units sold and revenue each came back as one cell, and each was drawn
 * as a collapsed "Data · 1 rows" table with a totals toggle and copy buttons around a single value.
 * A row of one record is a statement of fact: each value beside its label, in the form its table
 * cell would take — money to the cent — with the source data a click away as before.
 */
import React from "react";
import { cleanLabel, formatMoney, formatPercent, formatTableNumber } from "@/lib/format";
import { columnCurrencySymbol, isMoneyColumn } from "@/lib/orgSettings";
import { ORDINAL_COL, SHARE_COL } from "@/components/charts/columnRoles";

/** The widest record still read as a line; past it, a table reads better. */
export const MAX_FIGURES = 6;

export function isOneRecord(columns: string[], rows: unknown[][]): boolean {
  return rows.length === 1 && columns.length >= 1 && columns.length <= MAX_FIGURES;
}

/** One value as a figure: a share as a percentage, money to the cent with its symbol, a count with
 *  separators; a key (a year, an id) and any text as written. Money and shares are read first, as the
 *  table's cells read them: `monthly_revenue` names a month and is money. */
export function figureValue(col: string, v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (typeof v === "boolean" || Number.isNaN(n)) return String(v);
  if (SHARE_COL.test(col)) return formatPercent(n, 1);
  if (isMoneyColumn(col)) return formatMoney(n, columnCurrencySymbol(col));
  if (ORDINAL_COL.test(col)) return String(v);
  return formatTableNumber(n);
}

export function FindingFigures({ columns, row }: { columns: string[]; row: unknown[] }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
      {columns.map((col, i) => (
        <div key={`${col}-${i}`} className="flex items-baseline gap-1.5">
          <span className="aug-fs-xs text-zinc-500">{cleanLabel(col)}</span>
          <span className="aug-text-ui font-semibold text-zinc-200 tabular-nums">{figureValue(col, row[i])}</span>
        </div>
      ))}
    </div>
  );
}
