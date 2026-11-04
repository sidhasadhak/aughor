"use client";

/**
 * Add a row to the sheet a dashboard's cards read. It goes through the sheet's own door, so what the reader may do is the sheet's
 * sharing, and a row is a change that can be undone from the sheet. Nothing is a copy: every card reads it straight away.
 */
import { useEffect, useState } from "react";

import { useQueryNarrowing } from "@/components/dashboards/QueryFilters";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { addRow, readSheet, type Sheet, type SheetColumn } from "@/lib/sheets";

const typed = (c: SheetColumn) => (c.kind === "date" ? "date" : c.kind === "number" || c.kind === "money" ? "number" : "text");

export function AddRowPiece({ sheetId }: { sheetId: string }) {
  const { changed } = useQueryNarrowing();
  const [open, setOpen] = useState(false);
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open || sheet) return;
    let live = true;
    readSheet(sheetId).then(s => { if (live) setSheet(s); }).catch(e => { if (live) setSaid(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [open, sheet, sheetId]);
  const columns = (sheet?.columns ?? []).filter(c => !c.hidden && !c.expression);
  const add = async () => {
    setBusy(true);
    try {
      const filled = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim() !== ""));
      await addRow(sheetId, filled);
      setSaid("Added. Every card read it.");
      setValues({});
      changed();
    } catch (e) {
      setSaid(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div data-testid="add-row">
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button size="xs" variant="ghost" aria-expanded={open} data-testid="add-row-open" onClick={() => setOpen(o => !o)}>{open ? "Close" : "+ Add a row"}</Button>
      </div>
      {open && (
        <div style={{ marginTop: 8, background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "12px 16px" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
            {columns.map(c => (
              <label key={c.id} className="aug-fs-sm" style={{ flex: "1 1 130px", minWidth: 0, display: "flex", flexDirection: "column", gap: 3, color: "var(--t2)" }}>
                {c.name}
                {c.kind === "choice" && c.choices.length ? (
                  <SelectField aria-label={c.name} value={values[c.name] ?? ""} onChange={e => setValues(v => ({ ...v, [c.name]: e.target.value }))}>
                    <option value="" />
                    {c.choices.map(o => <option key={o} value={o}>{o}</option>)}
                  </SelectField>
                ) : (
                  <Input aria-label={c.name} type={typed(c)} value={values[c.name] ?? ""} onChange={e => setValues(v => ({ ...v, [c.name]: e.target.value }))} />
                )}
              </label>
            ))}
            <Button size="sm" data-testid="add-row-go" disabled={busy || !Object.values(values).some(v => v.trim())} onClick={add}>{busy ? "Adding…" : "Add it"}</Button>
          </div>
          <div className="aug-fs-sm" role="status" data-testid="add-row-said" style={{ color: "var(--t3)", marginTop: 6 }}>
            {said || "It goes in the sheet. Nothing here is a copy, so every card reads it straight away."}
          </div>
        </div>
      )}
    </div>
  );
}
