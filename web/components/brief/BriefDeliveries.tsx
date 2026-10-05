"use client";

/**
 * Delivered — each send of the Briefing on the page, signed and dated (ROADMAP §6 item 42c).
 *
 * A send that left names the version it delivered, who it went to, when, and the receipt it
 * carried. "Open what was sent" reads that version — not today's — so a Briefing met later in a
 * thread opens to what its reader was shown, with a line saying when it has been restated since.
 * A send the gate held or a channel refused is in Departures, with its reason, and is not here.
 */
import { useState } from "react";

import { RangeMeasures } from "@/components/brief/BriefRange";
import { Absent, Gate, Ledger, useLoad, type LedgerColumn } from "@/components/record/kit";
import { Button } from "@/components/ui/button";
import {
  getBriefingDelivery, listBriefingDeliveries, type BriefingDelivery, type BriefingRangeBlock,
} from "@/lib/api";
import { countNoun, formatDateTime } from "@/lib/format";

/** What a delivery's version is, beside the one on the page. */
export function versionWords(d: BriefingDelivery, current: number | null): string {
  if (d.version == null) return "version not recorded";
  if (d.restated_since && current) return `version ${d.version} — restated since, version ${current} now`;
  return `version ${d.version}, the one on this page`;
}

export function BriefDeliveries({ connectionId, scopeKey, block }: {
  connectionId: string; scopeKey: string; block: BriefingRangeBlock;
}) {
  const load = useLoad(() => listBriefingDeliveries(connectionId, block.covers, scopeKey, block.period),
    [connectionId, scopeKey, block.covers, block.period]);
  const [open, setOpen] = useState<string | null>(null);
  const columns: LedgerColumn<BriefingDelivery>[] = [
    { head: "Sent", cell: d => formatDateTime(d.sent_at), width: 170 },
    { head: "To", cell: d => d.to || "not recorded" },
    { head: "Version", cell: d => versionWords(d, load.data?.current_version ?? null), width: 300 },
    { head: "On the schedule", cell: d => d.subscription_name || "—", width: 200 },
    { head: "Receipt", cell: d => d.receipt_line || "—", width: 220 },
    {
      head: "Open", control: true, width: 150,
      cell: d => (
        <Button size="xs" variant="ghost" aria-expanded={open === d.id} onClick={() => setOpen(o => (o === d.id ? null : d.id))}>
          {open === d.id ? "Close it" : "Open what was sent"}
        </Button>
      ),
    },
  ];
  return (
    <div className="aug-fs-sm" data-testid="brief-deliveries" style={{ marginBottom: 14 }}>
      <div className="aug-label" style={{ marginBottom: 6 }}>
        Delivered{load.data?.deliveries.length ? ` · ${countNoun(load.data.deliveries.length, "send")}` : ""}
      </div>
      <Gate load={load} what="this Briefing's deliveries">
        {d => (
          <>
            <Ledger name="briefing-deliveries" columns={columns} rows={d.deliveries} rowKey={r => r.id} selected={open ?? undefined}
              empty="This Briefing has not been sent to anyone. A send that leaves is listed here with the version it delivered." />
            {open && <SentVersion key={open} id={open} />}
          </>
        )}
      </Gate>
    </div>
  );
}

function SentVersion({ id }: { id: string }) {
  const load = useLoad(() => getBriefingDelivery(id), [id]);
  return (
    <div className="aug-beside-box" data-testid="brief-sent-version" style={{ marginTop: 8, padding: 14, gap: 10 }}>
      <Gate load={load} what="the Briefing as it was sent">
        {d => (d.briefing == null ? (
          <Absent>The version this send delivered is no longer in the ledger.</Absent>
        ) : (
          <>
            <div className="aug-label">
              As sent {formatDateTime(d.sent_at)} to {d.to} · version {d.version}
              {d.restated_since && d.current_version ? ` · restated since: version ${d.current_version} is on the page` : ""}
            </div>
            {String(d.briefing.narrative || "").split("\n\n").filter(p => p.trim()).map((p, i) => (
              // eslint-disable-next-line react/no-array-index-key -- paragraphs of one fixed text, never reordered
              <p key={i} className="aug-fs-ui" style={{ margin: 0, color: "var(--t1)", lineHeight: 1.55 }}>{p}</p>
            ))}
            {d.briefing.period && <RangeMeasures block={d.briefing.period} />}
            {d.held_lines > 0 && <Absent>{countNoun(d.held_lines, "line")} of it was held at the gate and did not leave.</Absent>}
          </>
        ))}
      </Gate>
    </div>
  );
}
