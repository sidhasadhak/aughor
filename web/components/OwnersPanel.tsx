"use client";

/**
 * OwnersPanel — Settings ▸ "Owners the platform can reach" (CB-3, 2026-09-22).
 *
 * Every owner text the organisation's declarations carry — metrics, processes, business rules,
 * glossary — with where it is used and whether the platform can reach it. An owner that reads as
 * a principal (`user:…` / `group:…` / `agent:…`) is reachable as written; a display name ("Ana
 * (logistics)") is UNRESOLVED until a person links it here, once. Nothing is ever linked by
 * matching a name: the principal is what you type.
 *
 * A card (CLARITY, 2026-10-12): the counts at the label's right end, the owners not linked yet first, each with the
 * one control that resolves it. The Organization section's "Needs you" counts the same owners and brings a person
 * here (`settings-owners`); a link or an unlink here is announced, so that count follows.
 */
import { useCallback, useEffect, useState } from "react";
import { linkOwner, listOwners, unlinkOwner, type OwnerEntry } from "@/lib/api";
import { Card, Chip, Empty, MUTED, ONE_LINE, ROW, RULE } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** Fired on `window` when an owner is linked or unlinked, so every reader of the owners re-reads them. */
export const OWNERS_CHANGED = "aughor:owners-changed";
export function announceOwnersChanged(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(OWNERS_CHANGED));
}

export function usesLabel(e: OwnerEntry): string {
  const counts: Record<string, number> = {};
  for (const u of e.uses) counts[u.kind] = (counts[u.kind] ?? 0) + 1;
  const parts = Object.entries(counts).map(([k, n]) => `${n} ${k.replace("_", " ")}${n === 1 ? "" : "s"}`);
  return parts.length ? parts.join(" · ") : "not used by any declaration";
}

export function OwnersPanel({ connectionId }: { connectionId?: string }) {
  const [owners, setOwners] = useState<OwnerEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listOwners(connectionId);
      setOwners(data.owners);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [connectionId]);

  useEffect(() => { void reload(); }, [reload]);

  const link = useCallback(async (e: OwnerEntry) => {
    const principal = (drafts[e.owner_key] ?? "").trim();
    if (!principal) return;
    setBusy(e.owner_key);
    try {
      await linkOwner(e.owner_text, principal);
      setDrafts(d => ({ ...d, [e.owner_key]: "" }));
      await reload();
      announceOwnersChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }, [drafts, reload]);

  const unlink = useCallback(async (e: OwnerEntry) => {
    setBusy(e.owner_key);
    try {
      await unlinkOwner(e.owner_text);
      await reload();
      announceOwnersChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }, [reload]);

  // The ones not linked first: they are the rows that ask something of the reader.
  const shown = [...owners].sort((a, b) => Number(a.resolved) - Number(b.resolved));

  return (
    <div id="settings-owners" style={{ minWidth: 0 }}>
      <Card label="Owners" ariaLabel="Owners the platform can reach" testId="settings-owners-card"
        right={!loading && `${owners.length} owner${owners.length === 1 ? "" : "s"} in use`}>
        <div className="aug-fs-xs" style={{ ...MUTED, marginBottom: 6 }}>
          Link a name once to user:…, group:… or agent:… so a question for it reaches someone.
        </div>
        {error && <p role="alert" className="aug-fs-xs" style={{ color: "var(--red4)", margin: "4px 0" }}>{error}</p>}
        {loading && owners.length === 0 && <Empty>Reading the declarations…</Empty>}
        {shown.map(e => (
          <div key={e.owner_key} data-owner-unlinked={e.how === "unresolved" ? "true" : undefined}
            style={{ ...ROW, ...RULE, gap: 10, padding: "8px 0", flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 200px", minWidth: 0 }}>
              <div className="aug-fs-sm" style={{ color: "var(--t1)", ...ONE_LINE }}>{e.owner_text}</div>
              <div className="aug-fs-xs" style={MUTED}>{usesLabel(e)}</div>
            </div>
            {e.how === "unresolved" ? (
              <div style={{ ...ROW, flexWrap: "nowrap" }}>
                <Chip tone="amber">unresolved</Chip>
                <Input
                  aria-label={`Principal for ${e.owner_text}`}
                  value={drafts[e.owner_key] ?? ""}
                  onChange={ev => setDrafts(d => ({ ...d, [e.owner_key]: ev.target.value }))}
                  onKeyDown={ev => { if (ev.key === "Enter") void link(e); }}
                  placeholder="user:ana@corp"
                  style={{ width: 176 }}
                />
                <Button size="sm" variant="secondary" disabled={busy === e.owner_key} onClick={() => void link(e)}>Link</Button>
              </div>
            ) : (
              <div style={{ ...ROW, flexWrap: "nowrap" }}>
                <Chip><span style={{ fontFamily: "var(--font-mono)" }}>{e.principal}</span></Chip>
                <span className="aug-fs-xs" style={MUTED}>{e.how === "linked" ? `linked${e.linked_by ? ` by ${e.linked_by}` : ""}` : "as written"}</span>
                {e.how === "linked" && (
                  <Button size="sm" variant="ghost" disabled={busy === e.owner_key} onClick={() => void unlink(e)}>Unlink</Button>
                )}
              </div>
            )}
          </div>
        ))}
        {!loading && owners.length === 0 && <Empty>No declaration names an owner yet.</Empty>}
      </Card>
    </div>
  );
}
