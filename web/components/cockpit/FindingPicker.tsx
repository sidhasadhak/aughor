"use client";

/**
 * FindingPicker — any recorded finding of the connection, placed on a cockpit as a card (the
 * canvas, docs/COCKPIT_CANVAS_2026-10-08.md, B3).
 *
 * Door 1 pins a finding the Briefing shows; this is the same door, opened on the whole ledger
 * the explorer has recorded for the connection — by domain, searchable — not only the findings
 * this cycle's Briefing led with. The card is made by the same route (`/cards/pin-insight`),
 * through the same guard battery, with the same link back to the finding; nothing is written
 * here. A finding with no query has nothing to measure and is said so, not offered. One already
 * on this cockpit is said to be.
 */
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loading } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { listFindingsByDomain, pinFinding, type RecordedFinding } from "@/lib/api";

const SHOWN = 60;

export function FindingPicker({ connectionId, schema, placed, busy, onPlaced, onClose }: {
  connectionId: string;
  schema?: string;
  /** The finding ids the cockpit's cards already show. */
  placed: Set<string>;
  busy?: boolean;
  onPlaced: () => void;
  onClose: () => void;
}) {
  const [ledger, setLedger] = useState<{ domain: string; findings: RecordedFinding[] }[] | null>(null);
  const [problem, setProblem] = useState("");
  const [q, setQ] = useState("");
  const [pinning, setPinning] = useState("");

  useEffect(() => {
    let alive = true;
    listFindingsByDomain(connectionId, schema).then(groups => { if (alive) setLedger(groups); })
      .catch(e => { if (alive) setProblem((e as Error).message); });
    return () => { alive = false; };
  }, [connectionId, schema]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let n = 0;
    return (ledger ?? []).map(g => ({
      domain: g.domain,
      findings: g.findings.filter(f => !needle || `${f.finding} ${f.domain} ${f.angle}`.toLowerCase().includes(needle))
        .filter(() => n++ < SHOWN),
    })).filter(g => g.findings.length);
  }, [ledger, q]);
  const total = (ledger ?? []).reduce((s, g) => s + g.findings.length, 0);

  const place = async (f: RecordedFinding) => {
    setPinning(f.id);
    try {
      await pinFinding(connectionId, f.id, { scope: "connection", scopeRef: connectionId, schema });
      toast.success("Placed. Its query ran through the guards before the card was made.");
      onPlaced();
    } catch (e) {
      toast.error("Not placed", { description: (e as Error).message.slice(0, 200) });
    } finally { setPinning(""); }
  };

  return (
    <div data-testid="cockpit-finding-picker" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16, display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span className="aug-label">From the findings ledger</span>
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
          every finding the explorer has recorded on this connection, not only this cycle's · a card is made of its query, re-run through the guards
        </span>
        <Button size="xs" variant="ghost" style={{ marginLeft: "auto" }} onClick={onClose}>Close</Button>
      </div>
      <Input aria-label="Search the findings" placeholder="Search by words, domain or angle" value={q} onChange={e => setQ(e.target.value)} style={{ maxWidth: 420 }} />
      {problem ? (
        <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>The ledger could not be read: {problem}</div>
      ) : ledger === null ? (
        <Loading what="the findings ledger" style={{ padding: "6px 0" }} />
      ) : !total ? (
        <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>The explorer has recorded no findings on this connection yet.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 360, overflow: "auto" }}>
          {shown.map(g => (
            // Keyed by the first finding's id: a domain is a kind, and the key ratchet refuses a kind as a key.
            <div key={g.findings[0].id} data-testid="finding-domain" data-domain={g.domain}>
              <div className="aug-fs-xs" style={{ color: "var(--t3)", letterSpacing: ".06em", textTransform: "uppercase", margin: "4px 0" }}>{g.domain}</div>
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {g.findings.map(f => {
                  const measured = !!(f.sql || "").trim();
                  const on = placed.has(f.id);
                  return (
                    <li key={f.id} data-testid="finding-row" data-finding={f.id} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "5px 0", borderTop: "1px solid var(--b1)" }}>
                      <span className="aug-fs-sm" style={{ flex: 1, minWidth: 0, color: measured ? "var(--t1)" : "var(--t3)" }}>
                        {f.finding}
                        {!measured && <span style={{ color: "var(--t3)" }}> · no query — nothing to measure</span>}
                        {on && <span style={{ color: "var(--t3)" }}> · on this cockpit</span>}
                      </span>
                      <Button size="xs" variant="outline" disabled={busy || !measured || on || !!pinning}
                        onClick={() => void place(f)}>{pinning === f.id ? "Running…" : "Place"}</Button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
          {total > SHOWN && <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>The first {SHOWN} are shown; search to narrow them.</div>}
        </div>
      )}
    </div>
  );
}
