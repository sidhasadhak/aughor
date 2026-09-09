"use client";

/**
 * OverridesDrawer — PX-6: the ontology's human-edit ledger, and its doors.
 *
 * Three capabilities existed API-only:
 *  - Overrides could be APPLIED (every inline edit writes one) but never LISTED or
 *    REVERTED — the version-controlled set of human corrections had no reader, so
 *    "what did we override, and can we take one back" had no answer on a screen.
 *  - Routing proposals had a propose→review→accept governance loop with no inbox.
 *  - Export/import round-trips the ontology to a YAML tree for version control —
 *    with no button, the workflow existed only in a docstring.
 */

import { useCallback, useEffect, useState } from "react";
import {
  acceptRoutingProposal, deleteOntologyOverride, exportOntologyTree,
  importOntologyTree, listOntologyOverrides, listRoutingProposals,
  type OntologyOverrideRow, type RoutingProposal,
} from "@/lib/api";
import { countNoun } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";

export function OverridesDrawer({ connId, schema, onClose, onChanged }: {
  connId: string; schema?: string; onClose: () => void;
  /** The graph is derived-with-overrides — a revert or accept changes what renders. */
  onChanged: () => void;
}) {
  const [overrides, setOverrides] = useState<OntologyOverrideRow[]>([]);
  const [proposals, setProposals] = useState<RoutingProposal[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try {
      const [ov, pr] = await Promise.all([
        listOntologyOverrides(connId, schema),
        listRoutingProposals(connId, schema).catch(() => []),
      ]);
      setOverrides(ov); setProposals(pr); setErr("");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setLoaded(true); }
  }, [connId, schema]);
  useEffect(() => { load(); }, [load]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true); setErr(""); setNote("");
    // `done` may be empty when the action composes its own note inside `fn` —
    // overwriting it with "" here is how the export receipt vanished on first drive.
    try { await fn(); if (done) setNote(done); await load(); onChanged(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="border border-zinc-700/60 bg-zinc-900/95 rounded-[var(--r3)] p-4 space-y-4"
      style={{ position: "absolute", right: 12, top: 46, width: 460, zIndex: 30,
        maxHeight: "78%", overflowY: "auto" }}>
      <div className="flex items-center gap-2">
        <p className="text-xs font-semibold text-zinc-300">Human edits</p>
        <span className="aug-fs-xs text-zinc-500">
          the version-controlled corrections layered over the derived graph
        </span>
        <Button variant="ghost" size="xs" className="ml-auto" onClick={onClose}>Close</Button>
      </div>

      {proposals.length > 0 && (
        <div className="space-y-2">
          <p className="aug-fs-xs text-zinc-400 font-semibold">
            Routing proposals awaiting review — accepting is the ONLY path to enforced
          </p>
          {proposals.map((p, i) => {
            const id = String(p.entity_id ?? p.target_id ?? "");
            const bindOk = (p as { bind?: { ok?: boolean } }).bind?.ok !== false;
            return (
              <div key={i} className="border border-zinc-700/50 rounded-[var(--r2)] p-2 space-y-1">
                <div className="flex items-center gap-2">
                  <span className="aug-fs-sm text-zinc-200">{id}</span>
                  {!bindOk && (
                    <span className="aug-fs-xs text-amber-300">
                      did not bind — the table it names is unreadable
                    </span>
                  )}
                  <Button size="xs" variant="minimal" className="ml-auto"
                    disabled={busy || !bindOk}
                    onClick={() => run(() => acceptRoutingProposal(id, connId, schema),
                      `Accepted — ${id}'s routing is now enforced.`)}>
                    Accept
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="space-y-2">
        <p className="aug-fs-xs text-zinc-400 font-semibold">
          {loaded ? countNoun(overrides.length, "override") : "Overrides"} on this scope
        </p>
        {loaded && overrides.length === 0 && (
          <EmptyState variant="inline"
            title="No human overrides yet — everything on screen is auto-derived.">
            Editing an entity, relationship or metric inline writes one; it will be
            listed here, revertible.
          </EmptyState>
        )}
        {overrides.map((o, i) => (
          <div key={i} className="border border-zinc-700/50 rounded-[var(--r2)] p-2">
            <div className="flex items-center gap-2">
              <span className="aug-fs-xs text-zinc-500 uppercase">{o.target_kind}</span>
              <span className="aug-fs-sm text-zinc-200 truncate">{o.target_id}</span>
              <Button size="xs" variant="ghost" className="ml-auto text-zinc-500 hover:text-red-400"
                disabled={busy}
                onClick={() => run(
                  () => deleteOntologyOverride(o.target_kind, o.target_id, connId, schema),
                  "Reverted — the auto-derived value returns on the next read.")}>
                Revert
              </Button>
            </div>
            <p className="aug-fs-xs text-zinc-500 mt-1 truncate">
              overrides: {Object.keys(o.fields ?? {}).join(", ") || "—"}
            </p>
          </div>
        ))}
      </div>

      <div className="space-y-1 border-t border-zinc-800 pt-3">
        <p className="aug-fs-xs text-zinc-400 font-semibold">Version control</p>
        <p className="aug-fs-xs text-zinc-500">
          Export writes the live ontology as a readable YAML tree; edit it in your
          editor, then re-import — only changed fields become overrides, so an
          unedited round-trip is a no-op.
        </p>
        <div className="flex items-center gap-2 pt-1">
          <Button size="xs" variant="minimal" disabled={busy}
            onClick={() => run(async () => {
              const r = await exportOntologyTree(connId, schema);
              setNote(`Exported ${countNoun(r.files, "file")} to ${r.root}`);
            }, "")}>
            Export to files
          </Button>
          <Button size="xs" variant="ghost" disabled={busy}
            onClick={() => run(() => importOntologyTree(connId, schema),
              "Re-imported — changed fields are now overrides, listed above.")}>
            Re-import edits
          </Button>
        </div>
      </div>

      {note && <p className="aug-fs-xs" style={{ color: "var(--grn4)" }}>{note}</p>}
      {err && <p className="aug-fs-xs" style={{ color: "var(--red4)" }}>{err}</p>}
    </div>
  );
}
