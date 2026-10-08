"use client";

/**
 * BriefingSections — the Briefing's switches (the canvas, docs/COCKPIT_CANVAS_2026-10-08.md, B1).
 *
 * A person shows, hides and orders the Briefing's sections and chooses which cockpit of theirs
 * rides with it. Nothing about a section's content changes: the Briefing stays the platform's,
 * and a send carries the platform's Briefing, not these switches. The preference is kept per
 * person on the server, so it follows them to their next browser.
 *
 * The same switches can be asked for in words, read here without a model (`lib/briefingSections`):
 * what the words come to is shown as a proposal, kept whole or not. A hidden section leaves one
 * line on the page saying it is hidden, and how to show it — never a silent gap.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  labelOf, moved, proposeFromWords, toggled, type BriefingSectionsPref, type CockpitChoice, type SectionId, type SwitchProposal,
} from "@/lib/briefingSections";

const NONE = "__none__";

export function BriefingSections({ pref, onChange, cockpits, cockpitsOn, busy }: {
  pref: BriefingSectionsPref;
  /** Keep this as the person's preference. */
  onChange: (next: BriefingSectionsPref, said: string) => void;
  /** The person's own cockpits, which may ride with the Briefing. */
  cockpits: CockpitChoice[];
  /** Whether cockpits are on at all; off, the standing cockpit layer rides as it always did. */
  cockpitsOn: boolean;
  busy?: boolean;
}) {
  const [words, setWords] = useState("");
  const [proposal, setProposal] = useState<SwitchProposal | null>(null);
  const items = Object.fromEntries([[NONE, "None"], ...cockpits.map(c => [c.id, c.title || c.id])]);

  const propose = () => {
    const w = words.trim();
    if (!w) return;
    setProposal(proposeFromWords(w, pref, cockpits));
  };

  return (
    <div data-testid="briefing-sections" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "12px 14px", marginBottom: 16, display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="aug-label">Your Briefing</div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 2 }}>
        {pref.sections.map((s, i) => (
          <li key={s.id} data-testid="briefing-section-switch" data-section={s.id} data-on={s.on ? "true" : "false"}
            style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}>
            <Checkbox checked={s.on} disabled={busy} aria-label={`Show ${labelOf(s.id)}`}
              onChange={e => { const on = e.target.checked; onChange(toggled(pref, s.id, on), `${on ? "Shown" : "Hidden"}: ${labelOf(s.id)}.`); }} />
            <span style={{ flex: 1, minWidth: 0 }}>{labelOf(s.id)}</span>
            <Button size="xs" variant="ghost" disabled={busy || i === 0} aria-label={`Move ${labelOf(s.id)} up`}
              onClick={() => onChange(moved(pref, s.id, i - 1), `Moved ${labelOf(s.id)} up.`)}>↑</Button>
            <Button size="xs" variant="ghost" disabled={busy || i === pref.sections.length - 1} aria-label={`Move ${labelOf(s.id)} down`}
              onClick={() => onChange(moved(pref, s.id, i + 1), `Moved ${labelOf(s.id)} down.`)}>↓</Button>
          </li>
        ))}
      </ul>
      {cockpitsOn && (
        <label style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>The cockpit that rides with it</span>
          <Select value={pref.strip || NONE} items={items} disabled={busy}
            onValueChange={v => { const id = v === NONE ? "" : String(v); if (id !== pref.strip) onChange({ ...pref, strip: id }, id ? `“${items[id]}” rides with your Briefing.` : "No cockpit rides with your Briefing."); }}>
            <SelectTrigger size="sm" aria-label="The cockpit that rides with the Briefing" data-testid="briefing-strip-pick" style={{ minWidth: 180 }}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>None</SelectItem>
              {cockpits.map(c => <SelectItem key={c.id} value={c.id}>{c.title || c.id}</SelectItem>)}
            </SelectContent>
          </Select>
        </label>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Input aria-label="Ask for a change in words" placeholder="In words: “hide the findings, put the synthesis first”" value={words}
          disabled={busy} onChange={e => setWords(e.target.value)} onKeyDown={e => { if (e.key === "Enter") propose(); }}
          style={{ flex: 1, minWidth: 240, maxWidth: 520 }} />
        <Button size="sm" variant="secondary" disabled={busy || !words.trim()} onClick={propose}>Propose</Button>
      </div>
      {proposal?.kind === "refused" && (
        <div className="aug-fs-sm" data-testid="briefing-switch-refused" style={{ color: "var(--t2)" }}>{proposal.why}</div>
      )}
      {proposal?.kind === "proposal" && (
        <div data-testid="briefing-switch-proposal" style={{ border: "1px solid var(--blue2)", borderRadius: "var(--r2)", padding: "10px 12px", display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="aug-fs-sm" style={{ fontWeight: 600 }}>A change to your Briefing — read from your words, not written by them</div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {proposal.lines.map(l => <li key={l} className="aug-fs-sm">{l}</li>)}
          </ul>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Button size="xs" disabled={busy} onClick={() => { onChange(proposal.next, "Kept. Your Briefing's switches changed; its content did not."); setProposal(null); setWords(""); }}>Keep it</Button>
            <Button size="xs" variant="ghost" disabled={busy} onClick={() => setProposal(null)}>Not this</Button>
          </div>
        </div>
      )}
      <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
        Kept as your preference. A section's content is the platform's and is the same for everyone; a send carries the platform's Briefing, not your switches.
      </div>
    </div>
  );
}

/** What a hidden section leaves on the page: one line, and the way to show it again. */
export function HiddenSection({ id, onShow }: { id: SectionId; onShow: () => void }) {
  return (
    <div className="aug-fs-sm" data-testid="briefing-section-hidden" data-section={id}
      style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--t3)", borderTop: "1px dashed var(--b1)", padding: "6px 0" }}>
      <span>{labelOf(id)} is hidden.</span>
      <Button size="xs" variant="ghost" onClick={onShow}>Show it</Button>
    </div>
  );
}
