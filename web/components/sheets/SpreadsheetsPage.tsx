"use client";

/**
 * Spreadsheets — the sheets people make, edit, combine and chat with (Arc SH; the ten-screen mockup the user approved,
 * `design-mockups/spreadsheets.html`). One row in the rail's Data group, under Catalog, SQL Editor and Semantic Layer.
 *
 * The home lists the workspace's sheets and the files already uploaded to start one from; a sheet opens on its grid,
 * with the chat, the combining tools or a row's record beside it. Each wave shows only with its flag on: the sheets
 * themselves (`sheets.core`), editing (`sheets.grid`), the chat (`sheets.chat`), combining (`sheets.combine`) and
 * boards, calendars, rules and views kept to oneself (`sheets.views`), and a dashboard made from a sheet
 * (`sheets.everywhere`).
 */
import { useCallback, useEffect, useState } from "react";

import { SheetView } from "@/components/sheets/SheetView";
import { SheetsHome } from "@/components/sheets/SheetsHome";
import { Loading } from "@/components/ui/states";
import { getSystemFlags } from "@/lib/api";

export interface SheetsWaves {
  grid: boolean; chat: boolean; combine: boolean; views: boolean;
  /** SH-6's first piece: Make a dashboard — offered where sheets reach the rest of the platform (`sheets.everywhere`). */
  dashboard: boolean;
  /** SH-8: a sheet shared with chosen people and groups, each to read or to edit it. */
  sharing?: boolean;
  /** SH-5: a column a model writes, filled for the rows of a view. */
  modelColumns?: boolean;
}

/** The sheet in the address, so a sheet is linkable and the back button leaves it. */
function sheetInUrl(): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("sheet") ?? "";
}

function putSheetInUrl(id: string) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("sheet", id); else url.searchParams.delete("sheet");
  window.history.replaceState(window.history.state, "", url.toString());
}

export function SpreadsheetsPage({ onAsk }: { onAsk?: (question: string) => void }) {
  const [waves, setWaves] = useState<SheetsWaves | null>(null);
  const [core, setCore] = useState<boolean | null>(null);
  const [open, setOpen] = useState<string>(() => sheetInUrl());

  useEffect(() => {
    let live = true;
    getSystemFlags().then(f => {
      if (!live) return;
      const on = (k: string) => !!f[k]?.value;
      setCore(on("sheets.core"));
      setWaves({ grid: on("sheets.grid"), chat: on("sheets.chat"), combine: on("sheets.combine"),
        views: on("sheets.views"),
        dashboard: on("sheets.everywhere"),
        sharing: on("sheets.sharing"), modelColumns: on("sheets.model_columns") });
    }).catch(() => { if (live) { setCore(false); setWaves({ grid: false, chat: false, combine: false, views: false, dashboard: false, sharing: false }); } });
    return () => { live = false; };
  }, []);

  const openSheet = useCallback((id: string) => { setOpen(id); putSheetInUrl(id); }, []);

  if (core === null || waves === null) return <Loading what="the sheets" />;
  if (!core) {
    return (
      <div className="aug-fs-sm" style={{ padding: "24px 22px", color: "var(--t3)" }}>
        Spreadsheets are off on this install. They are turned on in Settings ▸ System, as
        “Spreadsheets: tables you make and keep”.
      </div>
    );
  }
  if (open) {
    return <SheetView key={open} sheetId={open} waves={waves} onBack={() => openSheet("")} onOpen={openSheet}
      onAsk={onAsk} />;
  }
  return <SheetsHome waves={waves} onOpen={openSheet} />;
}
