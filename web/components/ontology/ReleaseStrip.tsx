"use client";

/**
 * Arc OC-2 — the release, on the ontology's own screen (ROADMAP §3.56).
 *
 * While releases are on, a change to the ontology — a person's, the explorer's or a pack's — waits in a draft. These
 * screens read the draft; the agent, the Briefing, metrics and automations keep reading what was published. This strip
 * says which release they read, and lists each waiting change the way `GET /ontology/release` classes it: whether it
 * breaks something (ERR), changes what a definition means (MEANING), is worth a look (WARN) or is safe — with the
 * claims, automations and cockpit cards it touches. Publishing is the person's act, refused while anything breaks; a
 * change of meaning restates the claims computed under the old one. Off, the strip renders nothing.
 */
import React, { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { countNoun, formatTimestamp } from "@/lib/format";
import {
  discardDraft,
  getRelease,
  publishRelease,
  type ChangeClass,
  type ReleaseChange,
  type ReleaseState,
} from "@/lib/objectTypes";

const RULE = "1px solid var(--b1)";

/** The class as a person reads it, and its tag colour. */
const CLASS_LOOK: Record<ChangeClass, { label: string; tag: string }> = {
  ERR: { label: "breaks something", tag: "aug-tag-red" },
  MEANING: { label: "changes a meaning", tag: "aug-tag-amber" },
  WARN: { label: "worth a look", tag: "aug-tag-violet" },
  SAFE: { label: "safe", tag: "aug-tag-gray" },
};

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function touchesLine(c: ReleaseChange): string {
  const parts: string[] = [];
  if (c.touches.claims.length) parts.push(countNoun(c.touches.claims.length, "claim"));
  if (c.touches.automations.length) parts.push(countNoun(c.touches.automations.length, "automation"));
  if (c.touches.cards.length) parts.push(countNoun(c.touches.cards.length, "cockpit card"));
  return parts.join(" · ");
}

function ChangeRow({ change, busy, onDiscard }: {
  change: ReleaseChange; busy: boolean; onDiscard: () => void;
}) {
  const look = CLASS_LOOK[change.class];
  const touched = touchesLine(change);
  return (
    <li style={{ padding: "8px 0", borderTop: RULE, listStyle: "none" }} data-testid="release-change">
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <span className={`aug-tag ${look.tag}`}>{look.label}</span>
        <span className="aug-fs-sm" style={{ color: "var(--t1)" }}>
          {change.kind} <span style={{ fontFamily: "var(--font-mono)" }}>{change.target_id}</span> — {change.change}
        </span>
        {change.by && <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>by {change.by}</span>}
        <span style={{ flex: 1 }} />
        <Button variant="ghost" size="xs" disabled={busy} onClick={onDiscard}>Discard</Button>
      </div>
      <ul style={{ margin: "4px 0 0", padding: 0 }}>
        {change.reasons.filter(r => r.class !== "SAFE" || change.class === "SAFE").map((r, i) => (
          <li key={`${change.element}-reason-${i}`} className="aug-fs-xs"
            style={{ listStyle: "none", color: r.class === "ERR" ? "var(--red5)" : "var(--t2)" }}>
            {r.why}
          </li>
        ))}
      </ul>
      {touched && (
        <p className="aug-fs-xs" style={{ margin: "4px 0 0", color: "var(--t2)" }}>
          Touches {touched}
          {change.touches.automations.length > 0 && <>: {change.touches.automations.map(a => a.name).join(", ")}</>}
          {change.class === "MEANING" && change.touches.claims.length > 0 && " — publishing restates the claims"}
        </p>
      )}
    </li>
  );
}

export function ReleaseStrip({ connectionId, schema, onChanged }: {
  connectionId: string;
  schema?: string;
  /** Called after a publish or a discard, so the screens re-read what they show. */
  onChanged: () => void;
}) {
  const [state, setState] = useState<ReleaseState | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [said, setSaid] = useState<string | null>(null);

  const read = useCallback(() => {
    getRelease(connectionId, schema).then(setState).catch(e => setError(errorText(e)));
  }, [connectionId, schema]);

  useEffect(() => { read(); }, [read]);

  if (!state?.enabled) return null;

  const changes = state.draft;
  const breaking = changes.filter(c => c.class === "ERR").length;
  const published = state.published;
  const reads = published ? `release ${published.number}` : "what was declared before releases";

  const act = async (run: () => Promise<string>) => {
    setBusy(true); setError(null); setSaid(null);
    try {
      setSaid(await run());
      read();
      onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const publish = () => act(async () => {
    const made = await publishRelease(connectionId, schema);
    const restated = made.restated_claims.length;
    return `Published release ${made.number}` + (restated ? ` — ${countNoun(restated, "claim")} restated` : "");
  });
  const discardAll = () => act(async () => `Discarded ${countNoun(await discardDraft(connectionId, schema), "change")}`);
  const discardOne = (c: ReleaseChange) => act(async () => {
    await discardDraft(connectionId, schema, { kind: c.kind, target_id: c.target_id });
    return `Discarded the change to ${c.target_id}`;
  });

  return (
    <section style={{ padding: "8px 16px", borderBottom: RULE }} aria-label="Ontology release" data-testid="release-strip">
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>
          {changes.length === 0
            ? <>Everyone reads {reads}{published?.at && published.number > 1 ? `, published ${formatTimestamp(published.at, "short")}` : ""}.</>
            : <>{countNoun(changes.length, "change")} waiting to be published — the agent, the Briefing and
              automations still read {reads}.</>}
        </span>
        <span style={{ flex: 1 }} />
        {changes.length > 0 && (
          <>
            <Button variant="ghost" size="xs" onClick={() => setOpen(v => !v)} aria-expanded={open}>
              {open ? "Hide the changes" : "Review the changes"}
            </Button>
            <Button variant="outline" size="xs" disabled={busy} onClick={discardAll}>Discard all</Button>
            <Button size="xs" disabled={busy || breaking > 0} onClick={publish}
              title={breaking ? `${countNoun(breaking, "change")} would break something — discard or fix first` : undefined}>
              Publish
            </Button>
          </>
        )}
      </div>
      {said && <p className="aug-fs-xs" role="status" style={{ margin: "4px 0 0", color: "var(--t2)" }}>{said}</p>}
      {error && <p className="aug-fs-xs" role="alert" style={{ margin: "4px 0 0", color: "var(--red5)" }}>{error}</p>}
      {open && changes.length > 0 && (
        <ul style={{ margin: "8px 0 0", padding: 0 }}>
          {changes.map(c => (
            <ChangeRow key={c.element} change={c} busy={busy} onDiscard={() => discardOne(c)} />
          ))}
        </ul>
      )}
    </section>
  );
}
