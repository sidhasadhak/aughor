"use client";

/**
 * OwnersPanel — Settings ▸ "Owners the platform can reach" (CB-3, 2026-09-22).
 *
 * Every owner text the organisation's declarations carry — metrics, processes, business rules,
 * glossary — with where it is used and whether the platform can reach it. An owner that reads as
 * a principal (`user:…` / `group:…` / `agent:…`) is reachable as written; a display name ("Ana
 * (logistics)") is UNRESOLVED until a person links it here, once. Nothing is ever linked by
 * matching a name: the principal is what you type.
 */
import { useCallback, useEffect, useState } from "react";
import { linkOwner, listOwners, unlinkOwner, type OwnerEntry } from "@/lib/api";
import { Button } from "@/components/ui/button";

function usesLabel(e: OwnerEntry): string {
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
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }, [reload]);

  const unresolved = owners.filter(o => !o.resolved).length;

  return (
    <section aria-label="Owners the platform can reach" className="space-y-3">
      <div>
        <h3 className="text-sm font-medium text-zinc-200">Owners the platform can reach</h3>
        <p className="aug-fs-xs text-zinc-500">
          {loading ? "Reading the declarations…"
            : `${owners.length} owner${owners.length === 1 ? "" : "s"} in use · ${unresolved} unresolved. Link a display name to a principal once (user:…, group:… or agent:…); a question for that owner then has somewhere to go.`}
        </p>
      </div>
      {error && <p role="alert" className="aug-fs-xs text-zinc-300">{error}</p>}
      <ul className="divide-y divide-zinc-700/40">
        {owners.map(e => (
          <li key={e.owner_key} className="py-2 flex flex-wrap items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-zinc-300">{e.owner_text}</p>
              <p className="aug-fs-xs text-zinc-500">{usesLabel(e)}</p>
            </div>
            {e.how === "unresolved" ? (
              <div className="flex items-center gap-2">
                <span className="aug-fs-xs px-1.5 py-0.5 rounded border border-zinc-600 text-zinc-400">unresolved</span>
                <input
                  aria-label={`Principal for ${e.owner_text}`}
                  value={drafts[e.owner_key] ?? ""}
                  onChange={ev => setDrafts(d => ({ ...d, [e.owner_key]: ev.target.value }))}
                  placeholder="user:ana@corp"
                  className="aug-fs-xs bg-zinc-900 border border-zinc-600 rounded px-2 py-1 text-zinc-200 w-44"
                />
                <Button size="sm" variant="secondary" disabled={busy === e.owner_key} onClick={() => void link(e)}>Link</Button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="aug-fs-xs px-1.5 py-0.5 rounded border border-zinc-600 text-zinc-300">{e.principal}</span>
                <span className="aug-fs-xs text-zinc-500">{e.how === "linked" ? `linked${e.linked_by ? ` by ${e.linked_by}` : ""}` : "as written"}</span>
                {e.how === "linked" && (
                  <Button size="sm" variant="ghost" disabled={busy === e.owner_key} onClick={() => void unlink(e)}>Unlink</Button>
                )}
              </div>
            )}
          </li>
        ))}
        {!loading && owners.length === 0 && (
          <li className="py-2 aug-fs-xs text-zinc-500">No declaration names an owner yet.</li>
        )}
      </ul>
    </section>
  );
}
