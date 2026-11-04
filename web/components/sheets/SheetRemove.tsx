"use client";

/**
 * Removing a sheet, asked in its own row (the user: no pop-up on every click). It says what goes, that this cannot be undone,
 * what stays, and what reads the sheet — read when it opens, from the sheet's `dependents` route — and Remove waits for
 * that read, so nothing is removed on an unknown.
 */
import { useCallback, useEffect, useState } from "react";

import { MUTED } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { formatCount } from "@/lib/format";
import {
  dependentWords, readDependents, removeSheet, type SheetDependents, type SheetSummary, type UploadedFile, whatStays,
} from "@/lib/sheets";

export function RemoveSheetConfirm({ sheet, uploads, onKeep, onRemoved }: {
  sheet: SheetSummary; uploads: UploadedFile[]; onKeep: () => void; onRemoved: () => void;
}) {
  const [reads, setReads] = useState<SheetDependents | null>(null);
  const [unread, setUnread] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState("");

  const read = useCallback(() => {
    setUnread("");
    readDependents(sheet.id).then(setReads).catch(e => setUnread(e instanceof Error ? e.message : String(e)));
  }, [sheet.id]);
  useEffect(() => { read(); }, [read]);

  const remove = async () => {
    setBusy(true);
    setFailed("");
    try {
      await removeSheet(sheet.id);
      onRemoved();
    } catch (e) {
      setFailed(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const lines = reads ? dependentWords(reads) : [];
  return (
    <div role="group" aria-label={`Remove ${sheet.name}`} className="aug-fs-sm"
      onKeyDown={e => { if (e.key === "Escape") onKeep(); }}
      style={{ display: "flex", flexDirection: "column", gap: 6, padding: "10px 12px", background: "var(--bg-2)",
        border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", color: "var(--t1)" }}>
      <b>Remove {sheet.name}?</b>
      <span>
        This cannot be undone. Its {formatCount(sheet.rows)} row{sheet.rows === 1 ? "" : "s"} go for everyone, with every edit
        and its history.
      </span>
      <span>{whatStays(sheet, uploads)}</span>
      {unread ? (
        <span role="alert" style={{ color: "var(--red4)", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          What reads it could not be read, so it is not removed yet: {unread}
          <Button variant="outline" size="xs" onClick={read}>Try again</Button>
        </span>
      ) : !reads ? (
        <span style={MUTED}>Reading what reads it…</span>
      ) : lines.length === 0 ? (
        <span style={MUTED}>No other sheet and no dashboard card reads it.</span>
      ) : (
        <>
          <span style={{ fontWeight: 600 }}>What reads it</span>
          <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 2 }}>
            {/* one sheet's account of what reads it, in the order it is said */}
            {lines.map((line, i) => <li key={i}>{line}</li>)}
          </ul>
        </>
      )}
      {failed && <span role="alert" style={{ color: "var(--red4)" }}>{failed}</span>}
      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <Button variant="outline" size="sm" autoFocus onClick={onKeep}>Keep it</Button>
        <Button variant="destructive" size="sm" disabled={!reads || busy} onClick={() => void remove()}>
          {busy ? "Removing…" : "Remove the sheet"}
        </Button>
      </div>
    </div>
  );
}
