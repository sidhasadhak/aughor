"use client";
/**
 * S3 — the typed "what was wrong" form behind a negative verdict.
 *
 * A bare 👎 teaches the system nothing it can act on. This form turns the
 * click into a correction the closed loop actually reads back: the note (and
 * optional corrected SQL) flow through record_verdict into the Ambiguity
 * Ledger as the HIGHEST-authority resolution, so the next answer on this
 * connection cites the fix instead of repeating the mistake. That loop is
 * permanent (flag endgame Wave 5) — this is the surface that feeds it.
 */
import { useState } from "react";
import { Button } from "@/components/ui/button";

export function FixItForm({
  onSubmit,
  onCancel,
  busy = false,
  withSql = false,
}: {
  /** Submit the typed correction. `correctedSql` is empty unless the user gave one. */
  onSubmit: (note: string, correctedSql: string) => void;
  onCancel: () => void;
  busy?: boolean;
  /** Offer the optional corrected-SQL field (quick answers, where one query produced the number). */
  withSql?: boolean;
}) {
  const [note, setNote] = useState("");
  const [sql, setSql] = useState("");
  const [showSql, setShowSql] = useState(false);

  return (
    <div
      className="flex flex-col gap-1.5 rounded-[var(--r2)] p-2 my-1"
      style={{ background: "var(--bg-2)", border: "1px solid var(--b1)" }}
    >
      <textarea
        autoFocus
        rows={2}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="What was wrong? (e.g. 'revenue should exclude cancelled orders')"
        className="w-full bg-transparent aug-fs-xs text-zinc-200 placeholder:text-zinc-500 resize-none focus:outline-none"
      />
      {withSql && !showSql && (
        <Button
          variant="ghost"
          size="xs"
          onClick={() => setShowSql(true)}
          className="h-auto self-start p-0 aug-fs-xs font-normal text-zinc-500 hover:text-zinc-300 hover:bg-transparent dark:hover:bg-transparent"
        >
          + add corrected SQL
        </Button>
      )}
      {withSql && showSql && (
        <textarea
          rows={3}
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          placeholder="SELECT … (the query that computes it correctly)"
          className="w-full bg-transparent aug-fs-xs font-mono text-zinc-200 placeholder:text-zinc-600 resize-none focus:outline-none"
        />
      )}
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="xs"
          disabled={busy || !note.trim()}
          onClick={() => onSubmit(note.trim(), sql.trim())}
          className="h-auto px-2 py-0.5 aug-fs-xs border rounded-[var(--r1)] border-amber-500/40 text-amber-300 hover:bg-amber-500/10 dark:hover:bg-amber-500/10"
        >
          {busy ? "Recording…" : "Record correction"}
        </Button>
        <Button
          variant="ghost"
          size="xs"
          disabled={busy}
          onClick={onCancel}
          className="h-auto p-0 aug-fs-xs font-normal text-zinc-500 hover:text-zinc-300 hover:bg-transparent dark:hover:bg-transparent"
        >
          Cancel
        </Button>
        <span className="aug-fs-xs text-zinc-600">
          The next answer on this connection cites your correction.
        </span>
      </div>
    </div>
  );
}
