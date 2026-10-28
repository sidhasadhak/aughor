"use client";

/**
 * Spreadsheets — the sheets people make, edit, combine and chat with (Arc SH; the ten-screen mockup the user approved,
 * `design-mockups/spreadsheets.html`). One row in the rail's Data group, under Catalog, SQL Editor and Semantic Layer.
 *
 * The home lists the workspace's sheets and the files already uploaded to start one from; a sheet opens on its grid,
 * with the chat, the combining tools or a row's record beside it.
 */
import { useCallback, useState } from "react";

import { SheetView } from "@/components/sheets/SheetView";
import { SheetsHome } from "@/components/sheets/SheetsHome";

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
  const [open, setOpen] = useState<string>(() => sheetInUrl());

  const openSheet = useCallback((id: string) => { setOpen(id); putSheetInUrl(id); }, []);

  if (open) {
    return <SheetView key={open} sheetId={open} onBack={() => openSheet("")} onOpen={openSheet} onAsk={onAsk} />;
  }
  return <SheetsHome onOpen={openSheet} />;
}
