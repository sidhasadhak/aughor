"use client";

/**
 * OrgPlaybookSection — the playbook, where a person can actually act on it.
 *
 * It was a top-level nav door under Intelligence, and a door promises a room worth
 * entering. Measured on the live deployment 2026-09-19: **878 entries, all active, and
 * not one with a success rate.** 486 of them (55%) are data-quality rule-outs the
 * Verifier runs inside a deep report — never a decision a person takes. `owner_role` read
 * "Data Analyst" on all 878, so that column carried no information either. The screen was
 * a list whose two most useful columns were a constant and a blank.
 *
 * So it moves here, beside the industries, because that is the only lever a person has
 * over it: the entries arrive from the industry packages this organisation installs. A
 * setting, not a plane of the product — the user's call, and the measurement agrees.
 *
 * Collapsed by default: the count is the answer to "what do we have", and the list is for
 * the rarer "which ones". The count is always shown, because a reader who does not expand
 * must still learn the playbook exists and how big it is.
 *
 * A card (CLARITY): the count at the label's right end, the two kinds of play as chips, the list behind Show.
 */
import { useEffect, useState } from "react";

import { PlaybookPanel } from "@/components/PlaybookPanel";
import { Card, Chip, ROW } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { getApiBase } from "@/lib/config";
import { formatCount } from "@/lib/format";

export function OrgPlaybookSection() {
  const [open, setOpen] = useState(false);
  const [total, setTotal] = useState<number | null>(null);
  const [ruleOuts, setRuleOuts] = useState(0);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const r = await fetch(`${getApiBase()}/playbook`);
        if (!r.ok) return;
        const body = await r.json();
        const rows: { tags?: string[] }[] = Array.isArray(body) ? body : (body.entries ?? []);
        if (!live) return;
        setTotal(rows.length);
        setRuleOuts(rows.filter(e =>
          (e.tags ?? []).some(t => t.toLowerCase() === "data quality")).length);
      } catch {
        // A count that cannot be read leaves the section stating nothing rather than zero:
        // "0 plays" is a claim about the organisation, and this would be a claim about the
        // network.
      }
    })();
    return () => { live = false; };
  }, []);

  return (
    <div style={{ minWidth: 0, gridColumn: open ? "1 / -1" : undefined }}>
      <Card label="Playbook" testId="org-playbook"
        right={total === null ? undefined : `${formatCount(total)} plays`}>
        <div style={{ ...ROW, gap: 6 }}>
          {total !== null && (
            <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>From your installed industry packages</span>
          )}
          {total !== null && ruleOuts > 0 && (
            <Chip title="The Verifier runs these during a deep report; none is a decision a person takes.">
              {formatCount(ruleOuts)} data-quality rule-outs, run by the Verifier
            </Chip>
          )}
          {total !== null && total - ruleOuts > 0 && (
            <Chip title="Read when a run’s numbers match their trigger">
              {formatCount(total - ruleOuts)} read when a run’s numbers match
            </Chip>
          )}
        </div>
        <Button variant="ghost" size="xs" onClick={() => setOpen(v => !v)} aria-expanded={open}
          data-testid="org-playbook-toggle" style={{ marginTop: 8 }}>
          {open ? "Hide the plays" : "Show the plays"} <Icon name={open ? "chevu" : "chevd"} size={12} />
        </Button>
        {open && (
          <div style={{ marginTop: 8, height: 460, border: "1px solid var(--b1)",
                        borderRadius: "var(--r2)", overflow: "hidden" }}>
            <PlaybookPanel />
          </div>
        )}
      </Card>
    </div>
  );
}
