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
 */
import { useEffect, useState } from "react";

import { PlaybookPanel } from "@/components/PlaybookPanel";
import { Icon } from "@/components/ui/icon";
import { getApiBase } from "@/lib/config";

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
    <section style={{ marginTop: 18 }}>
      <button
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
        data-testid="org-playbook-toggle"
        style={{
          display: "flex", alignItems: "center", gap: 7, width: "100%",
          background: "none", border: "none", padding: "6px 0", cursor: "pointer",
          textAlign: "left", color: "var(--t1)",
        }}
      >
        <Icon name={open ? "chevd" : "chevr"} size={11} />
        <span className="aug-fs-sm" style={{ fontWeight: 500 }}>Playbook</span>
        <span className="aug-fs-xs" style={{ color: "var(--t3)", marginLeft: "auto" }}>
          {total === null ? "" : `${total} plays from your installed industry packages`}
        </span>
      </button>
      {!open && total !== null && ruleOuts > 0 && (
        <div className="aug-fs-xs" style={{ color: "var(--t3)", paddingLeft: 18,
                                            lineHeight: 1.45 }}>
          {ruleOuts} of them are data-quality rule-outs the Verifier runs during a deep
          report; the rest are read when a run’s numbers match their trigger.
        </div>
      )}
      {open && (
        <div style={{ marginTop: 8, height: 460, border: "1px solid var(--b1)",
                      borderRadius: "var(--r2)", overflow: "hidden" }}>
          <PlaybookPanel />
        </div>
      )}
    </section>
  );
}
