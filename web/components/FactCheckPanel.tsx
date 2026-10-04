"use client";

/**
 * Idea 7 — check a document's numbers, from the web. The check had two API doors
 * (`POST /factcheck`, `POST /factcheck/upload`) and a Slack verb (`check:`), and PENDING said
 * "Still no web door": paste a memo or choose a file, and every number that states a
 * measurement is put to the platform's own answer path and compared with what the data shows.
 *
 * Each claim is one quick answer — a few model calls — so the cost is said before the button,
 * and nothing runs until a person presses it.
 */
import React, { useEffect, useRef, useState } from "react";

import { factCheckFile, factCheckText, getDocumentFormats, type FactCheckResult } from "@/lib/api";
import { SqlResultTable } from "@/components/AugTable";
import { ExportButton } from "@/components/ExportButton";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/ui/states";
import { Textarea } from "@/components/ui/textarea";

/** What a file may be when the install cannot say: Markdown and plain text always read. */
const FALLBACK_ACCEPT = ".md,.markdown,.txt";

export function FactCheckPanel({ connectionId }: { connectionId: string }) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FactCheckResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // The same converter the Documents tab uses reads the file, so the picker offers what this
  // install can read — asked of it, as the uploader asks, rather than assumed.
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
  // The body names each contradicted claim — the table already shows them — and says how many
  // claims were past the cap, which the table cannot. Only the second kind is kept.
  const notes = (env?.body ?? "").split("\n").filter(l => l.trim() && !l.startsWith("- CONTRADICTED"));

  return (
    <section aria-label="Check a document's numbers" style={{ marginBottom: 28 }}>
      <h2 className="aug-fs-ui" style={{ fontWeight: 600, color: "var(--t1)", margin: 0 }}>
        Check a document&apos;s numbers
      </h2>
      <p className="aug-fs-sm" style={{ color: "var(--t3)", margin: "4px 0 10px", lineHeight: 1.5 }}>
        Paste a memo or choose a file. Every number that states a measurement is checked against this
        connection&apos;s data through the answer path — one answer per claim, a few model calls and about
        ten seconds each, for the first 25 claims.
      </p>

      {!connectionId ? (
        <p className="aug-fs-sm" style={{ color: "var(--t3)" }}>Choose a connection to check numbers against.</p>
      ) : (
        <>
          <Textarea
            aria-label="Memo to check"
            placeholder="Paste a memo, an email or a deck's text…"
            value={text}
            onChange={e => setText(e.target.value)}
            disabled={running || file !== null}
            rows={4}
          />
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
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
      {error && <p role="alert" className="aug-fs-sm" style={{ color: "var(--red3)", marginTop: 10 }}>{error}</p>}

      {env && (
        <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
            <div className="aug-fs-ui" style={{ flex: 1, color: "var(--t1)", fontWeight: 500, lineHeight: 1.5 }}>
              {env.headline}
            </div>
            {result && <ExportButton invId={result.investigation_id} />}
          </div>
          {env.grid && env.grid.rows.length > 0 && (
            <SqlResultTable columns={env.grid.columns} rows={env.grid.rows} totals={false} name="fact-check" />
          )}
          {[...notes, ...(env.caveats ?? [])].map((line, i) => (
            <p key={`note:${i}`} className="aug-fs-sm" style={{ color: "var(--t3)", margin: 0, lineHeight: 1.5 }}>
              {line.replace(/^- /, "")}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}
