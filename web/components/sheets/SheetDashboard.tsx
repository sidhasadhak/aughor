"use client";

/**
 * Make a dashboard from a sheet (Arc SH, SH-6 — its first piece; mockup screen 3's button).
 *
 * The server offers what the sheet holds — how many rows, each money column's sum, the rows per value of its choice
 * columns, the rows by month of its first date, a table of the rows — each a query card on the Sheets connection, run
 * once on the sheet so its preview is what the card will show (`GET /sheets/{id}/dashboard`). The person ticks what they
 * want and names it; each card is kept through the dashboards' own door for a query of one's own, then the dashboard,
 * and the Dashboards tab opens on it. A card reads the sheet each time it is read, so it follows every edit. With a
 * filtered view on screen, every card reads the view's rows.
 */
import { useEffect, useState } from "react";

import { MUTED, NUM } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Icon, type IconName } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { keepDashboardQuery } from "@/lib/api";
import { cardsDashboardSpec, startDashboard } from "@/lib/dashboards/start";
import { formatCount } from "@/lib/format";
import { requestTab } from "@/lib/navigate";
import {
  monthWords, proposeDashboard, rowsWord, showValue, type DashboardPiece, type DashboardProposal, type Sheet,
} from "@/lib/sheets";

const KIND_ICON: Record<DashboardPiece["kind"], IconName> = { figure: "num", bar: "chart", line: "trendup", table: "table" };

/** A piece's preview in words: the figure, the largest values, the months it runs over, the rows it lists. */
export function pieceWords(p: DashboardPiece): string {
  const v = p.preview ?? {};
  if (p.kind === "figure") {
    if (v.value === null || v.value === undefined) return "empty";
    return p.currency !== undefined ? showValue(v.value, { kind: "money", currency: p.currency ?? "" })
      : formatCount(Number(v.value));
  }
  if (p.kind === "bar") {
    const top = (v.values ?? []).map(x => `${x.x === null || x.x === undefined ? "empty" : String(x.x)} ${formatCount(x.v ?? 0)}`);
    return top.join(" · ") + (v.of && v.of > top.length ? ` · ${formatCount(v.of - top.length)} more` : "");
  }
  if (p.kind === "line") {
    if (!v.points) return "no dated rows";
    // a month's bucket is its first day: said as the month
    const at = (x: unknown) => monthWords(String(x ?? "").slice(0, 7));
    return `${formatCount(v.points)} months, ${at(v.first)} to ${at(v.last)}`;
  }
  return `${formatCount(v.rows ?? 0)}${v.more ? "+" : ""} rows listed`;
}

export function SheetDashboard({ sheet, viewId, onClose }: { sheet: Sheet; viewId: string; onClose: () => void }) {
  const [offer, setOffer] = useState<DashboardProposal | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [title, setTitle] = useState("");
  const [making, setMaking] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    proposeDashboard(sheet.id, viewId).then(p => {
      if (!live) return;
      setOffer(p);
      setTitle(p.title);
      setPicked(new Set(p.pieces.filter(x => !x.refused?.length).map(x => x.key)));
    }).catch(e => { if (live) setFailed(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [sheet.id, viewId]);

  const make = async () => {
    if (!offer) return;
    setFailed(null);
    const chosen = offer.pieces.filter(p => picked.has(p.key));
    try {
      const cards: { card: string; size: DashboardPiece["size"] }[] = [];
      for (const [i, p] of chosen.entries()) {
        setMaking(`Keeping ${p.title} (${i + 1} of ${chosen.length})…`);
        const kept = await keepDashboardQuery(offer.connection_id, { sql: offer.sql, shown: p.shown, title: p.title });
        cards.push({ card: kept.card.id, size: p.size });
      }
      setMaking("Keeping the dashboard…");
      await startDashboard(offer.connection_id, title.trim() || offer.title, cardsDashboardSpec(title.trim() || offer.title, cards),
        `Made from the sheet ${sheet.name}${offer.view ? `, its view ${offer.view}` : ""}`);
      onClose();
      requestTab("dashboards", { conn: offer.connection_id });
    } catch (e) {
      setFailed(e instanceof Error ? e.message : String(e));
    } finally {
      setMaking(null);
    }
  };

  return (
    <Dialog open onOpenChange={o => { if (!o && !making) onClose(); }}>
      <DialogContent maxWidth="760px" aria-describedby={undefined}>
        <DialogTitle>Make a dashboard from {sheet.name}</DialogTitle>
        {!offer && !failed && <div className="aug-fs-sm" style={MUTED}>Reading the sheet — each card is run once before it is offered…</div>}
        {offer && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="aug-fs-xs" style={MUTED}>
              {offer.view ? <>Every card reads the view <b>{offer.view}</b>: {offer.rows !== null ? rowsWord(offer.rows, sheet.name) : "its rows"}.</>
                : <>Every card reads the whole sheet{offer.rows !== null ? `: ${rowsWord(offer.rows, sheet.name)}` : ""}.</>}
              {" "}A card runs on the sheet each time it is read, so it follows every edit.
            </div>
            <label className="aug-fs-sm" style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ width: 70, ...MUTED }}>Name</span>
              <Input value={title} onChange={e => setTitle(e.target.value)} aria-label="The dashboard's name" style={{ flex: 1 }} />
            </label>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {offer.pieces.map(p => {
                const no = !!p.refused?.length;
                return (
                  <label key={p.key} className="aug-fs-sm" style={{ display: "grid", gap: 10, alignItems: "center",
                    gridTemplateColumns: "18px 16px minmax(0, 1fr) minmax(0, 1.1fr)", padding: "6px 8px",
                    borderRadius: "var(--r2)", background: "var(--bg-1)", opacity: no ? 0.6 : 1 }}>
                    <Checkbox checked={picked.has(p.key)} disabled={no} aria-label={p.title}
                      onChange={() => { const s = new Set(picked); if (s.has(p.key)) s.delete(p.key); else s.add(p.key); setPicked(s); }} />
                    <Icon name={KIND_ICON[p.kind]} size={14} />
                    <span style={{ minWidth: 0 }}>
                      <span style={{ display: "block", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.title}</span>
                      <span className="aug-fs-xs" style={MUTED}>{p.why}</span>
                    </span>
                    <span className="aug-fs-xs" style={{ ...NUM, color: no ? "var(--red4)" : "var(--t2)", textAlign: "right",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                      title={no ? p.refused!.join(" ") : pieceWords(p)}>
                      {no ? p.refused![0] : pieceWords(p)}
                    </span>
                  </label>
                );
              })}
            </div>
          </div>
        )}
        {failed && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>{failed}</div>}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
          <span className="aug-fs-xs" style={MUTED}>{making ?? "Kept as your own dashboard on the Sheets connection; nothing calls a model."}</span>
          <Button variant="ghost" onClick={onClose} disabled={!!making} style={{ marginLeft: "auto" }}>Cancel</Button>
          <Button onClick={() => void make()} disabled={!offer || picked.size === 0 || !!making}>
            {picked.size ? `Make it with ${picked.size} card${picked.size === 1 ? "" : "s"}` : "Make it"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
