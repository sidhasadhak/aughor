"use client";

/**
 * E6 — "Add as test case": the on-ramp that makes the eval arc compound.
 *
 * A one-click affordance next to an answer's Trust Receipt that captures the
 * question + connection + the exact executed SQL as an EvalCase — so a real
 * answer you trust becomes a regression case, and a real answer you DON'T becomes
 * the failing case that proves the fix. Writes through E5's evals client; the
 * suite's connection is what will replay the SQL, so only suites bound to THIS
 * connection (or unbound) are offered, and a new suite is bound here.
 *
 * The routes are EVAL_SUITE-gated (Enterprise): on a lower tier the write 402s and
 * the global upsell interceptor surfaces the upgrade — the same path every gated
 * action takes, so nothing here needs its own tier check.
 */
import { useState } from "react";
import { EvalSuite, getEvalSuites, createEvalSuite, addEvalCases } from "@/lib/api";
import { Button } from "@/components/ui/button";

const NEW = "__new__";

export function AddToEvalSuite({ connectionId, sql, question }: {
  connectionId: string;
  sql: string;
  question?: string;
}) {
  const [open, setOpen] = useState(false);
  const [suites, setSuites] = useState<EvalSuite[] | null>(null);
  const [target, setTarget] = useState<string>(NEW);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function openPicker() {
    setOpen(true); setError(null);
    if (suites === null) {
      try {
        const all = await getEvalSuites();
        // A case's SQL replays against the SUITE's connection — only unbound suites
        // or ones bound to this connection are safe targets.
        const eligible = all.filter(s => !s.connection_id || s.connection_id === connectionId);
        setSuites(eligible);
        setTarget(eligible[0]?.id ?? NEW);
      } catch {
        // A 402 already surfaced the upsell via the interceptor; just fall back to the create path.
        setSuites([]); setTarget(NEW);
      }
    }
  }

  async function add() {
    if (target === NEW && !newName.trim()) { setError("Name the new suite"); return; }
    setBusy(true); setError(null);
    try {
      let suiteId = target;
      if (target === NEW) {
        const created = await createEvalSuite({
          name: newName.trim(), target: "reference", connection_id: connectionId,
        });
        suiteId = created.id;
      }
      await addEvalCases(suiteId, [{ question: question ?? "", artifact: sql }]);
      setAdded(true); setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add");
    } finally {
      setBusy(false);
    }
  }

  if (added) {
    return <span className="aug-text-xs text-emerald-400/90" title="Captured in an eval suite">✓ added to eval suite</span>;
  }

  if (!open) {
    return (
      <Button variant="ghost" size="xs" onClick={openPicker}
        className="h-auto p-0 aug-text-xs font-normal text-zinc-500 hover:text-zinc-300 hover:bg-transparent dark:hover:bg-transparent"
        title="Capture this question + executed SQL as an eval test case">
        Add as eval case
      </Button>
    );
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <select
        value={target}
        onChange={e => setTarget(e.target.value)}
        className="aug-input aug-text-xs"
        style={{ padding: "2px 6px" }}
        aria-label="Target eval suite"
      >
        {(suites ?? []).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        <option value={NEW}>＋ New suite…</option>
      </select>
      {target === NEW && (
        <input
          className="aug-input aug-text-xs"
          value={newName}
          onChange={e => setNewName(e.target.value)}
          placeholder="New suite name"
          style={{ padding: "2px 6px", width: 150 }}
          aria-label="New suite name"
        />
      )}
      <Button variant="ghost" size="xs" onClick={add} disabled={busy}
        className="h-auto px-2 py-0.5 aug-text-xs font-normal border border-zinc-700 rounded-md text-zinc-300 hover:text-zinc-100 hover:bg-transparent dark:hover:bg-transparent">
        {busy ? "Adding…" : "Add"}
      </Button>
      <Button variant="ghost" size="xs" onClick={() => { setOpen(false); setError(null); }}
        className="h-auto p-0 aug-text-xs font-normal text-zinc-500 hover:text-zinc-300 hover:bg-transparent dark:hover:bg-transparent">
        Cancel
      </Button>
      {error && <span className="aug-text-xs text-red-400/90">{error}</span>}
    </span>
  );
}
