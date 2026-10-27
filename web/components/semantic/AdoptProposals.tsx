/**
 * Adopt the proposals — the explorer's and an industry's — in one door (the user's decision, 2026-10-23; the Olist
 * study, Gaps 21, 22 and 24). Each proposal with a formula is listed with a tick and the date it would be dated by,
 * the platform's first choice selected (the business date: the parent table's, the record's own creation) and the
 * others one click away; one button approves the ticked set, and the approval is asked ONCE for the set. What
 * could not be adopted is listed with its reason.
 */
import { useEffect, useMemo, useState } from "react";

import { Card, Empty, MUTED, ROW } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { SelectField } from "@/components/ui/select";
import { adoptMetrics, getMetricProposals, type AdoptResult, type CatalogueMetric } from "@/lib/api";
import { countNoun } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";

/** A proposal the door can adopt: not yet defined, with a formula for this connection. */
export function adoptable(rows: CatalogueMetric[]): CatalogueMetric[] {
  return rows.filter(r => r.source !== "defined" && r.state === "proposed" && (r.sql || "").trim());
}

type Dates = Record<string, { options: string[]; chosen: string; error?: string }>;

export function AdoptProposals({ connId, schema, rows, onDone, label = "Adopt the proposals" }: {
  connId: string;
  schema?: string;
  rows: CatalogueMetric[];
  /** Read the catalogue again once a set was adopted. */
  onDone: () => void;
  /** Arc MC — the card's label when it adopts one area's proposals. */
  label?: string;
}) {
  const list = useMemo(() => adoptable(rows), [rows]);
  const [open, setOpen] = useState(false);
  const [ticked, setTicked] = useState<Record<string, boolean>>({});
  const [dates, setDates] = useState<Dates>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AdoptResult | null>(null);
  const [error, setError] = useState("");

  // The dates each proposal can take, read when the door opens — the platform's own proposals, the first selected.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    for (const r of list) {
      if (dates[r.name]) continue;
      getMetricProposals(connId, r.sql, r.tables, [], r.name)
        .then(p => {
          if (!alive) return;
          const options = (p.candidates || []).map(c => c.grain);
          setDates(d => ({ ...d, [r.name]: { options, chosen: options[0] ?? "" } }));
        })
        .catch(e => { if (alive) setDates(d => ({ ...d, [r.name]: { options: [], chosen: "", error: e instanceof Error ? e.message : String(e) } })); });
    }
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, connId, list]);

  if (list.length === 0) return null;
  const isTicked = (name: string) => ticked[name] !== false;          // every proposal is ticked until unticked
  const chosen = list.filter(r => isTicked(r.name));
  const undated = chosen.filter(r => !dates[r.name]?.chosen);

  async function adopt() {
    setBusy(true);
    setError("");
    try {
      const out = await adoptMetrics(connId, schema, chosen.map(r => ({ name: r.name, time_column: dates[r.name]?.chosen || undefined })));
      setResult(out);
      if (out.adopted.length) onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card label={label} testId="adopt-proposals"
      right={!open ? <Button size="xs" variant="secondary" onClick={() => setOpen(true)}>Choose and date them</Button> : undefined}>
      {!open ? (
        <div className="aug-fs-sm" style={MUTED}>
          {countNoun(list.length, "proposal")} with a formula {list.length === 1 ? "is" : "are"} ready to adopt: each is dated,
          proposed and approved together, and the set is approved once.
        </div>
      ) : (
        <div data-testid="adopt-list">
          {list.map(r => {
            const d = dates[r.name];
            return (
              <div key={`${r.schema}:${r.name}`} data-testid="adopt-row"
                style={{ ...ROW, gap: 10, padding: "6px 0", borderTop: "1px solid var(--b1)", flexWrap: "wrap" }}>
                <Checkbox checked={isTicked(r.name)} aria-label={`Adopt ${r.label}`}
                  onChange={e => setTicked(t => ({ ...t, [r.name]: e.target.checked }))} />
                <span className="aug-fs-sm" style={{ color: "var(--t1)", minWidth: 200, flex: "1 1 200px" }}>{r.label}</span>
                <span className="aug-fs-xs" style={MUTED}>dated by</span>
                {!d ? <span className="aug-fs-xs" style={MUTED}>reading its dates…</span>
                  : d.options.length === 0 ? <span className="aug-fs-xs" style={{ color: "var(--amb4)" }}>{d.error || "no date on the tables it reads"}</span>
                  : (
                    <SelectField value={d.chosen} aria-label={`Date for ${r.label}`}
                      onChange={e => setDates(x => ({ ...x, [r.name]: { ...d, chosen: e.target.value } }))}>
                      {d.options.map(o => <option key={o} value={o}>{o}</option>)}
                    </SelectField>
                  )}
              </div>
            );
          })}
          <div style={{ ...ROW, gap: 10, marginTop: 10 }}>
            <Button size="xs" variant="secondary" disabled={busy || chosen.length === 0 || undated.length > 0} onClick={() => void adopt()}>
              {busy ? "Adopting…" : `Approve ${countNoun(chosen.length, "metric")}`}
            </Button>
            {undated.length > 0 && (
              <span className="aug-fs-xs" style={MUTED}>{countNoun(undated.length, "ticked metric")} without a date — untick or wait for its dates.</span>
            )}
            <Button size="xs" variant="ghost" disabled={busy} onClick={() => setOpen(false)}>Close</Button>
          </div>
          {error && <div className="aug-fs-xs" style={{ color: "var(--red4)", marginTop: 6 }}>{error}</div>}
          {result && (
            <div data-testid="adopt-result" className="aug-fs-sm" style={{ marginTop: 8 }}>
              {result.adopted.length > 0 && <div>Approved: {result.adopted.map(a => a.label).join(", ")}.</div>}
              {withUniqueKeys(result.skipped, s => `skipped:${s.name}`).map(([key, s]) => (
                <div key={key} style={MUTED}>{s.label} was not adopted: {s.reason}</div>
              ))}
              {result.adopted.length === 0 && result.skipped.length === 0 && <Empty>Nothing was adopted.</Empty>}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
