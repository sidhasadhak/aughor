/**
 * SE-2 PR C — two-tier diagnostics for the SQL editor.
 *
 * **Tier 1 (fast, approximate).** The worker's Postgres grammar, ~300 ms after typing
 * stops. It catches unbalanced parens and malformed clauses in a few milliseconds, with
 * real character positions, so the squiggle lands under the token. It is NOT dialect
 * truth: the connection may be BigQuery or Snowflake while the grammar is Postgres.
 *
 * **Tier 2 (slow, authoritative).** `POST /query/validate` at ~600 ms — the connection's
 * real dialect plus the whole guard battery (fan-out, join and filter value-domain,
 * grain, trust checks, mutation blockers). These are the findings that actually matter
 * and they are the reason this editor is different from a text box: a query can be
 * perfectly valid SQL and still over-count, and only this tier knows that.
 *
 * **Server verdicts override.** When tier 2 answers, its findings are authoritative for
 * everything they cover. Tier 1 syntax errors survive only while the server has not
 * spoken about that revision — otherwise a Postgres-grammar complaint about a
 * BigQuery-legal function would sit on screen contradicting the server that just
 * approved it.
 *
 * Positioning: the guard battery reports table/column/literal NAMES, not offsets. Each
 * finding is anchored by locating its subject in the text; when that fails the finding
 * attaches to the whole statement rather than being dropped. A finding the user cannot
 * see is the same as a finding we never made.
 */
import { forceLinting, linter, type Diagnostic } from "@codemirror/lint";
import type { EditorView } from "@codemirror/view";
import { validateSql } from "@/lib/query/parserClient";
import { validateQuery, type QueryValidation } from "@/lib/api";

/** Locate `needle` in `text`, case-insensitively, returning a CM range or null. */
function locate(text: string, needle: string): { from: number; to: number } | null {
  if (!needle) return null;
  const i = text.toLowerCase().indexOf(needle.toLowerCase());
  return i < 0 ? null : { from: i, to: i + needle.length };
}

/** Anchor a finding: prefer its most specific subject, fall back to the whole doc. */
function anchor(text: string, ...candidates: string[]): { from: number; to: number } {
  for (const c of candidates) {
    const hit = locate(text, c);
    if (hit) return hit;
  }
  return { from: 0, to: Math.max(1, text.length) };
}

/** Guard verdict → CM diagnostics. Severity is the guard's own judgement: a mutation
 *  blocker refuses to run, everything else is advisory and says why. */
export function verdictToDiagnostics(sql: string, v: QueryValidation): Diagnostic[] {
  const out: Diagnostic[] = [];

  for (const b of v.mutation_blockers ?? []) {
    out.push({
      ...anchor(sql, b.name),
      severity: "error",
      source: "guard",
      message: `${b.name}: ${b.reason}`,
    });
  }
  for (const j of v.join_warnings ?? []) {
    out.push({
      ...anchor(sql, `${j.table_a}.${j.col_a}`, j.col_a, j.table_a),
      severity: "warning",
      source: "guard · join value-domain",
      message:
        `Joining ${j.table_a}.${j.col_a} to ${j.table_b}.${j.col_b} — measured key ` +
        `overlap is ${Math.round((j.overlap ?? 0) * 100)}%. Rows on either side may drop silently.`,
    });
  }
  for (const f of v.filter_warnings ?? []) {
    out.push({
      ...anchor(sql, `'${f.literal}'`, f.literal, `${f.table}.${f.column}`, f.column),
      severity: "warning",
      source: "guard · filter value-domain",
      message:
        `No row in ${f.table}.${f.column} ${f.op} ${JSON.stringify(f.literal)}` +
        (f.suggestion ? ` — did you mean ${JSON.stringify(f.suggestion)}?` : " — this filter matches nothing."),
    });
  }
  for (const g of v.grain_warnings ?? []) {
    out.push({
      ...anchor(sql, g.join_key, g.table),
      severity: "warning",
      source: "guard · grain",
      message: g.caveat || `Joining on ${g.join_key} fans ${g.table} out ${g.ratio}× — totals will over-count.`,
    });
  }
  // These arrive as de-duped prompt-hint STRINGS (Verifier.scan), not objects — there
  // is no subject to anchor to, so they attach to the statement.
  for (const hint of v.fanout_hits ?? []) {
    out.push({
      from: 0,
      to: Math.max(1, sql.length),
      severity: "warning",
      source: "guard · fan-out",
      message: hint,
    });
  }
  for (const t of v.trust_findings ?? []) {
    const subject = String(t.column ?? t.literal ?? "");
    out.push({
      ...anchor(sql, subject),
      severity: "warning",
      source: `guard · ${String(t.name ?? "trust")}`,
      message: String(t.message ?? t.reason ?? "Function-semantics footgun."),
    });
  }
  return out;
}

/** Build the linter extension. `getConn` is read at lint time (not captured) so a
 *  connection switch takes effect without rebuilding the editor. */
export function sqlDiagnostics(opts: {
  getConn: () => string;
  getDialect: () => string;
  /** Notified with the authoritative verdict, for the "Checked — N notes" chip. */
  onVerdict?: (v: QueryValidation | null) => void;
}) {
  // Cache the last server answer per exact document, so re-linting for an unrelated
  // reason (a selection change, a focus event) does not re-hit the endpoint — the
  // guard battery runs live probes against the warehouse and is not free.
  let lastSql = "";
  let lastVerdict: QueryValidation | null = null;
  let inFlight: Promise<void> | null = null;

  return linter(
    async (view: EditorView): Promise<Diagnostic[]> => {
      const sql = view.state.doc.toString();
      if (!sql.trim()) {
        if (lastVerdict) { lastVerdict = null; opts.onVerdict?.(null); }
        return [];
      }

      // Tier 1 — always, and always fast.
      const syntax = await validateSql(sql);
      const tier1: Diagnostic[] = syntax.map(e => ({
        from: Math.min(e.from, sql.length),
        to: Math.min(Math.max(e.to, e.from + 1), sql.length),
        severity: "error" as const,
        source: "syntax (approximate)",
        message: e.message,
      }));

      // Tier 2 — fired only when the document actually changed, and AWAITED (bounded)
      // so this pass returns complete results.
      //
      // The await is the fix for a defect worth recording: relying on `forceLinting`
      // alone to paint the verdict after it arrived worked on an edit but silently
      // failed on a cold page load — the request fired, the server returned the
      // finding, the header chip counted it, and the editor showed nothing. Findings
      // that exist in the response and nowhere on screen are worse than no checking
      // at all, because the chip claims the checking happened.
      //
      // Bounded at 2.5s because the guard battery runs LIVE probes against the
      // warehouse: on a slow connection the squiggles must not wait on it. Past the
      // bound the pass returns tier 1 alone and `forceLinting` remains as the
      // backstop that paints the verdict whenever it lands.
      const conn = opts.getConn();
      if (conn && sql !== lastSql) {
        if (!inFlight) {
          inFlight = validateQuery(conn, sql, opts.getDialect())
            .then(v => {
              lastSql = sql; lastVerdict = v; opts.onVerdict?.(v);
              forceLinting(view);
            })
            .catch(() => { /* validation is advisory; it must not break editing */ })
            .finally(() => { inFlight = null; });
        }
        await Promise.race([
          inFlight,
          new Promise<void>(resolve => setTimeout(resolve, 2500)),
        ]);
      }

      // "Server verdicts override" is true only for the AXIS the server actually
      // judges. `/query/validate` runs the guard battery — fan-out, value-domain,
      // grain, trust — and says nothing whatsoever about syntax. So a passing verdict
      // must NOT erase a tier-1 syntax error: that would hide a broken statement
      // behind "Checked — clean", which is the opposite of what the chip promises.
      //
      // What tier 2 legitimately overrides is tier 1's DIALECT guesswork. The worker
      // parses Postgres grammar; against a Postgres-family connection (which includes
      // DuckDB) that is the real grammar and its errors are trustworthy. Against
      // BigQuery or Snowflake it is an approximation that will flag dialect-legal
      // functions, so once the server has spoken about this exact text, those
      // false positives are dropped and only the guard findings remain.
      const guards = lastVerdict && lastSql === sql
        ? verdictToDiagnostics(sql, lastVerdict)
        : (lastVerdict ? verdictToDiagnostics(sql, lastVerdict) : []);
      const grammarIsTrue = opts.getDialect() === "postgres";
      const serverSpokeForThisText = !!lastVerdict && lastSql === sql;
      const keepTier1 = grammarIsTrue || !serverSpokeForThisText;
      return keepTier1 ? [...tier1, ...guards] : guards;
    },
    // 300 ms is tier 1's budget; tier 2 rides the same pass but is debounced further by
    // the doc-changed check above, which is what keeps warehouse probes rare.
    { delay: 300 },
  );
}
