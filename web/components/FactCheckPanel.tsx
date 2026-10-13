"use client";

/**
 * Check a document's numbers — a tool on the Documents screen (`components/documents/DocumentsPage.tsx`), opened from
 * its button rather than standing open at the top (CLARITY, 2026-10-13). Paste a memo or choose a file, and every
 * number that states a measurement is put to the platform's own answer path and compared with what the data shows.
 * The check had two API doors (`POST /factcheck`, `POST /factcheck/upload`) and a Slack verb (`check:`); this is its
 * web door.
 *
 * Each claim is one quick answer — a few model calls — so the cost is said as a chip beside the title, and nothing
 * runs until a person presses the button.
 */
import React, { useEffect, useRef, useState } from "react";

import { SqlResultTable } from "@/components/AugTable";
import { Chip, Label, MUTED, ROW } from "@/components/clarity/kit";
import { ExportButton } from "@/components/ExportButton";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Loading } from "@/components/ui/states";
import { Textarea } from "@/components/ui/textarea";
import { factCheckFile, factCheckText, getDocumentFormats, type FactCheckResult } from "@/lib/api";

/** What a file may be when the install cannot say: Markdown and plain text always read. */
const FALLBACK_ACCEPT = ".md,.markdown,.txt";

export function FactCheckPanel({ connectionId, connectionName, onClose }: {
  connectionId: string;
  /** The connection the numbers are checked against, by its name. */
  connectionName?: string;
  onClose?: () => void;
}) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FactCheckResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // The same converter the Documents screen uses reads the file, so the picker offers what this install can read —
  // asked of it, as the uploader asks, rather than assumed.
  const [accept, setAccept] = useState(FALLBACK_ACCEPT);
  useEffect(() => {
    getDocumentFormats().then(f => { if (f?.accept) setAccept(f.accept); }).catch(() => {});
  }, []);

  const ready = !!connectionId && (file !== null || text.trim().length > 0) && !running;

  async function run() {
    if (!ready) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      setResult(file ? await factCheckFile(file, connectionId) : await factCheckText(text, connectionId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The check failed");
    } finally {
      setRunning(false);
    }
  }

  const env = result?.envelope;
  // The body names each contradicted claim — the table already shows them — and says how many claims were past the
  // cap, which the table cannot. Only the second kind is kept.
  const notes = (env?.body ?? "").split("\n").filter(l => l.trim() && !l.startsWith("- CONTRADICTED"));

  return (
    <section aria-label="Check a document's numbers" data-testid="fact-check"
      style={{ background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "12px 14px" }}>
      <Label right={<>
        <Chip title="Each claim is one quick answer: a few model calls and about ten seconds">a few model calls per claim</Chip>
        <Chip title="Claims past the 25th are not checked; the result says how many were left">first 25 claims</Chip>
        {onClose && <Button size="xs" variant="ghost" onClick={onClose} aria-label="Close Check a document's numbers">
          <Icon name="close" size={12} />Close
        </Button>}
      </>}>
        Check a document&apos;s numbers
      </Label>

      {!connectionId ? (
        <p className="aug-fs-sm" style={{ ...MUTED, margin: 0 }}>Choose a connection to check numbers against.</p>
      ) : (
        <>
          <p className="aug-fs-sm" style={{ ...MUTED, margin: "-2px 0 8px" }}>
            Every number that states a measurement is checked against {connectionName ? `${connectionName}'s` : "this connection's"} data.
          </p>
          <Textarea
            aria-label="Memo to check"
            placeholder="Paste a memo, an email or a deck's text…"
            value={text}
            onChange={e => setText(e.target.value)}
            disabled={running || file !== null}
            rows={4}
          />
          <div style={{ ...ROW, marginTop: 8 }}>
            <input ref={inputRef} type="file" accept={accept} hidden
                   onChange={e => { setFile(e.target.files?.[0] ?? null); e.target.value = ""; }} />
            {file ? (
              <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>
                {file.name}{" "}
                <Button size="xs" variant="ghost" onClick={() => setFile(null)} disabled={running}>Remove</Button>
              </span>
            ) : (
              <Button size="xs" variant="ghost" onClick={() => inputRef.current?.click()} disabled={running}>
                Or choose a file…
              </Button>
            )}
            <div style={{ flex: 1 }} />
            <Button size="sm" onClick={run} disabled={!ready}>Check the numbers</Button>
          </div>
        </>
      )}

      {running && (
        <Loading what="the verdicts — one answer per claim, which can take a few minutes" style={{ marginTop: 10 }} />
      )}
      {error && <p role="alert" className="aug-fs-sm" style={{ color: "var(--red4)", marginTop: 10 }}>{error}</p>}

      {env && (
        <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
            <div className="aug-fs-ui" style={{ flex: 1, color: "var(--t1)", fontWeight: 500, lineHeight: 1.5 }}>
              {env.headline}
            </div>
            {result && <ExportButton invId={result.answerId} />}
          </div>
          {env.grid && env.grid.rows.length > 0 && (
            <SqlResultTable columns={env.grid.columns} rows={env.grid.rows} totals={false} name="fact-check" />
          )}
          {[...notes, ...(env.caveats ?? [])].map((line, i) => (
            <p key={`note:${i}`} className="aug-fs-sm" style={{ ...MUTED, margin: 0, lineHeight: 1.5 }}>
              {line.replace(/^- /, "")}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}
