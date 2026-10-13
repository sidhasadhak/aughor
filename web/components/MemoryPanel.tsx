"use client";
/* ── Memory — what the closed loop has learned ─────────────────────────────────────────────────────────────────────
   Laid out to CLARITY (`aughor-v2/CLARITY.md`) as a page that reads like a document, not a board: one line of what it
   holds, the trusted queries waiting on a person under "Needs you", then one sheet of headed sections in short lines —
   the readings it remembers, the queries it trusts, and side by side what reviewers said and the training corpus their
   verdicts become.

   Drawn only from what the loop stores. Left out: a "retired" list (Revoke DELETES a reading — nothing revoked is
   kept), "Add lesson" (no route writes a reading; they come from settled clarify questions, probes and verdicts), a
   reading's "because", an export of memory itself (the export here is the training corpus, and it writes), and any
   "effect on behaviour" figure (nothing measures one). Each source loads on its own and says when it could not be
   read. Org-wide; reads /learning/*. */
import { connectionLabel, keyToWords } from "@/lib/names";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { compactNumber, countNoun, formatCount, formatTimestamp, pct } from "@/lib/format";
import { dayWords } from "@/lib/home";
import {
  createTrustedQuery, deleteTrustedQuery, editTrustedQuery, getConnections,
  getLearningDataset, getLearningDatasets, getLearningSummary, listRememberedReadings,
  listTrustedQueries, revokeRememberedReading, runLearningExport, transitionTrustedQuery,
  type Connection, type LearningDatasetDetail, type LearningDatasets, type LearningSummary, type RememberedReading,
  type TrustedQueryRow,
} from "@/lib/api";
import { claimsOf, getIdToken } from "@/lib/auth";
import {
  Bar, CARD, Chip, Columns, Dot, Empty, HBars, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, Page, ROW, RULE,
} from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Loading, ReadFailed } from "@/components/ui/states";
import { SelectField } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

/** The acting identity for governance writes — the signed-in email, else the
 *  same word the actions inbox uses. The server owns identity; this is provenance. */
const actorName = () => claimsOf(getIdToken())?.email || "human";

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Who settled a reading, as a reader says it. */
const SETTLED_BY: Record<string, string> = { probe: "a probe", user: "a person", verdict: "a reviewer" };
const settledBy = (src: string) => SETTLED_BY[src] ?? keyToWords(src);

/** A verdict's word. */
const VERDICT_WORD: Record<string, string> = { accept: "accepted", correct: "corrected", reject: "rejected" };

/** Readings shown before "Show all" — a long list stays scannable, and the cut is never silent. */
const READINGS_SHOWN = 30;

/** What each gate counts — on hover; the kind keeps the name the corpus is registered under. */
const GATE_WHAT: Record<string, string> = {
  sft: "Accepted answers to train on",
  dpo: "A rejected answer paired with its correction",
  golden: "Accepted answers held out to measure against",
  guard_days: "Days of guard data on real traffic",
};

/** The dataset each kind is exported as — `aughor/learning/exporters.py`'s default names. The inspector asked for the
 *  kind itself ("sft") and the registry, which keys by name ("nl2sql-sft"), never found one: every corpus read as
 *  "no exported version yet" while the gates counted its rows. Keep in step with the exporters' defaults. */
const DATASET_OF: Record<string, string> = {
  sft: "nl2sql-sft", dpo: "nl2sql-dpo", golden: "nl2sql-golden", sft_bronze: "nl2sql-bronze", dpo_repair: "nl2sql-repairs",
};

/** A section of the page: a heading, what it counts, its one tool at the right, then its lines. */
function Section({ title, meta, right, children, testId, style }: {
  title: string; meta?: React.ReactNode; right?: React.ReactNode; children: React.ReactNode; testId?: string;
  style?: React.CSSProperties;
}) {
  return (
    <section aria-label={title} data-testid={testId} style={{ minWidth: 0, ...style }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", marginBottom: 6 }}>
        <h2 className="aug-fs-h2" style={{ margin: 0, color: "var(--t1)", fontWeight: 600 }}>{title}</h2>
        {meta != null && meta !== "" && <span className="aug-fs-sm" style={{ ...MUTED, ...NUM }}>{meta}</span>}
        {right && <span style={{ ...ROW, marginLeft: "auto" }}>{right}</span>}
      </div>
      {children}
    </section>
  );
}

/** One line of a section: what it is, one muted line, and its figure and buttons at the right. */
function Line({ first, children, figure, figureTitle, actions, below }: {
  first: boolean; children: React.ReactNode; figure?: React.ReactNode; figureTitle?: string; actions?: React.ReactNode;
  below?: React.ReactNode;
}) {
  return (
    <div style={{ padding: "8px 0", ...(first ? {} : RULE) }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12, alignItems: "center" }}>
        <div style={{ minWidth: 0 }}>{children}</div>
        {(figure != null || actions) && (
          <div style={{ ...ROW, flexWrap: "nowrap" }}>
            {figure != null && <span className="aug-fs-chrome" title={figureTitle} style={{ color: "var(--t2)", ...NUM }}>{figure}</span>}
            {actions}
          </div>
        )}
      </div>
      {below}
    </div>
  );
}

const SQL_BOX: React.CSSProperties = {
  margin: "6px 0 0", whiteSpace: "pre-wrap", fontFamily: "var(--font-mono)", color: "var(--t2)", background: "var(--bg-1)",
  borderRadius: "var(--r2)", padding: 8, overflowWrap: "anywhere",
};

export function MemoryPanel() {
  // Connections by name: a reading and a trusted query read `theLook`, never `8233e4fd` (lib/names.ts).
  const [conns, setConns] = useState<Connection[]>([]);
  useEffect(() => { getConnections().then(setConns).catch(() => {}); }, []);

  // Each source on its own: a failed one says so in its place and hides nothing else.
  const [summary, setSummary] = useState<LearningSummary | null>(null);
  const [summaryState, setSummaryState] = useState<"loading" | "ready" | "failed">("loading");
  const [readings, setReadings] = useState<RememberedReading[] | null>(null);
  const [readingsErr, setReadingsErr] = useState("");
  const [trusted, setTrusted] = useState<TrustedQueryRow[] | null>(null);
  const [trustedErr, setTrustedErr] = useState("");
  const [datasets, setDatasets] = useState<LearningDatasets | null>(null);
  const [datasetsState, setDatasetsState] = useState<"loading" | "ready" | "failed">("loading");

  // Each read sets only what it answers, so the first reads can run straight from the effect; a Retry says it is
  // reading again before it reads.
  const fetchSummary = useCallback(() => getLearningSummary()
    .then(s => { setSummary(s); setSummaryState(s ? "ready" : "failed"); })
    .catch(() => setSummaryState("failed")), []);
  const fetchReadings = useCallback(() => listRememberedReadings()
    .then(rs => { setReadings(rs); setReadingsErr(""); })
    .catch(e => setReadingsErr(errText(e))), []);
  const fetchTrusted = useCallback(() => listTrustedQueries()
    .then(rs => { setTrusted(rs); setTrustedErr(""); })
    .catch(e => setTrustedErr(errText(e))), []);
  const fetchDatasets = useCallback(() => getLearningDatasets()
    .then(d => { setDatasets(d); setDatasetsState(d ? "ready" : "failed"); })
    .catch(() => setDatasetsState("failed")), []);

  useEffect(() => { void fetchSummary(); void fetchReadings(); void fetchTrusted(); void fetchDatasets(); },
    [fetchSummary, fetchReadings, fetchTrusted, fetchDatasets]);

  const loadSummary = () => { setSummaryState("loading"); void fetchSummary(); };
  const loadReadings = () => { setReadings(null); setReadingsErr(""); void fetchReadings(); };
  const loadTrusted = () => { setTrusted(null); setTrustedErr(""); void fetchTrusted(); };
  const loadDatasets = () => { setDatasetsState("loading"); void fetchDatasets(); };

  // After a governance write: the queries, and what they feed — without blanking what is on screen.
  const afterTrustedWrite = useCallback(() => {
    void fetchTrusted();
    getLearningSummary().then(s => { if (s) setSummary(s); }).catch(() => {});
    getLearningDatasets().then(d => { if (d) setDatasets(d); }).catch(() => {});
  }, [fetchTrusted]);

  // ── the readings ──
  const [showAll, setShowAll] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokeErr, setRevokeErr] = useState<{ id: string; text: string } | null>(null);
  const revoke = async (id: string) => {
    setRevoking(id);
    setRevokeErr(null);
    try {
      await revokeRememberedReading(id);
      setReadings(rs => (rs ?? []).filter(r => r.id !== id));
    } catch (e) { setRevokeErr({ id, text: errText(e) }); }   // the row stays; the user can retry
    finally { setRevoking(null); }
  };

  // ── the training corpus ──
  const [exporting, setExporting] = useState(false);
  // A refused export used to end the spinner and change nothing, saying nothing.
  const [exportRefused, setExportRefused] = useState<string | null>(null);
  const exportNow = async () => {
    setExporting(true);
    setExportRefused(null);
    try {
      const out = await runLearningExport();
      setDatasets(d => ({ stats: d?.stats ?? {}, gates: out.gates }));
      setDatasetsState("ready");
      const fresh = await getLearningDatasets();
      if (fresh) setDatasets(fresh);
    } catch (e) {
      setExportRefused(e instanceof Error ? e.message : "The export was refused");
    } finally { setExporting(false); }
  };

  // ── trusted-query governance (the write half) ──
  const [busy, setBusy] = useState<string | null>(null);
  const [actErr, setActErr] = useState<{ id: string; text: string } | null>(null);
  const [actNote, setActNote] = useState("");
  const [openSql, setOpenSql] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [showSeed, setShowSeed] = useState(false);
  const act = async (id: string, fn: () => Promise<unknown>, done: string) => {
    setBusy(id); setActErr(null); setActNote("");
    try { await fn(); setActNote(done); afterTrustedWrite(); }
    catch (e) { setActErr({ id, text: errText(e) }); }
    finally { setBusy(null); }
  };
  const remove = (q: TrustedQueryRow) => {
    if (confirm("Remove this trusted query? The removal is audited."))
      void act(q.id, () => deleteTrustedQuery(q.id, actorName()), "Removed — the removal is on the ledger.");
  };

  const rows = trusted ?? [];
  // What needs a person: a proposal to approve, a draft to fix — proposals first.
  const waiting = rows.filter(q => q.status === "proposed" || q.status === "draft")
    .sort((a, b) => (a.status === "proposed" ? 0 : 1) - (b.status === "proposed" ? 0 : 1));
  const order: Record<string, number> = { approved: 0, deprecated: 1, rejected: 2 };
  const settled = rows.filter(q => q.status !== "proposed" && q.status !== "draft")
    .sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3));
  const approved = settled.filter(q => q.status === "approved").length;

  const sqlBelow = (q: TrustedQueryRow) => (
    <>
      {openSql === q.id && <pre className="aug-fs-xs" style={SQL_BOX}>{q.sql}</pre>}
      {editing === q.id && <EditTrustedForm row={q} onDone={() => { setEditing(null); afterTrustedWrite(); }} />}
      {actErr?.id === q.id && <p role="alert" className="aug-fs-xs" style={{ color: "var(--red4)", margin: "4px 0 0" }}>{actErr.text}</p>}
    </>
  );
  const sqlButton = (q: TrustedQueryRow) => (
    <Button size="xs" variant="ghost" onClick={() => setOpenSql(o => (o === q.id ? null : q.id))}>
      {openSql === q.id ? "Hide" : "SQL"}
    </Button>
  );
  const removeButton = (q: TrustedQueryRow) => (
    <Button size="xs" variant="ghost" disabled={busy === q.id} data-testid={`tq-delete-${q.id}`} onClick={() => remove(q)}>
      Remove
    </Button>
  );
  const where = (q: TrustedQueryRow) => `${connectionLabel(q.connection_id, conns)} · v${q.version}`;

  // ── the readings, said once ──
  const list = readings ?? [];
  const visible = showAll ? list : list.slice(0, READINGS_SHOWN);
  const readingsMeta = useMemo(() => {
    if (!readings?.length) return "";
    const by = new Map<string, number>();
    for (const r of readings) by.set(r.resolution_source, (by.get(r.resolution_source) ?? 0) + 1);
    const sources = [...by].sort((a, b) => b[1] - a[1]).map(([s, n]) => `${formatCount(n)} by ${settledBy(s)}`).join(", ");
    const served = readings.reduce((n, r) => n + (r.use_count || 0), 0);
    return `${formatCount(readings.length)} · ${sources} · served ${compactNumber(served)}× in all`;
  }, [readings]);

  const verdicts = summary?.verdicts;
  const trend = verdicts?.trend ?? [];

  return (
    <Page testId="memory-page">
      <p className="aug-fs-ui" style={{ margin: 0, color: "var(--t2)" }}>
        What Aughor has learned across every connection: how it reads ambiguous terms, the queries it trusts, and what
        reviewers said.
      </p>

      <NeedsYou testId="memory-needs" waiting={waiting.length > 0}
        right={waiting.length > 0 ? countNoun(waiting.length, "trusted query", "trusted queries") : undefined}>
        {trusted === null && !trustedErr ? <Loading what="the trusted queries" />
          : trustedErr ? <ReadFailed what="the trusted queries" error={trustedErr} onRetry={loadTrusted} />
          : waiting.length === 0 ? <Empty>No trusted query waits for approval.</Empty>
          : waiting.map(q => {
            const failed = q.status === "draft" && (q.verification as { passed?: boolean } | null)?.passed === false;
            return (
              <div key={q.id} data-testid={`tq-${q.id}`}>
                <NeedsRow title={<span title={q.question} style={{ ...ONE_LINE, display: "block" }}>{q.question}</span>}
                  detail={q.status === "proposed"
                    ? `Proposed · ${where(q)} — approving lets it reach prompts, and is recorded.`
                    : failed ? `Verification failed — it stays a draft, out of every prompt. ${where(q)}`
                    : `Draft · ${where(q)} — re-verify to propose it.`}
                  actions={q.status === "proposed" ? (
                    <>
                      <Button size="xs" variant="default" disabled={busy === q.id} data-testid={`tq-approve-${q.id}`}
                        onClick={() => act(q.id, () => transitionTrustedQuery(q.id, "approve", actorName()),
                          "Approved — it now reaches prompts, and the approval is on the ledger.")}>
                        Approve
                      </Button>
                      <Button size="xs" variant="ghost" disabled={busy === q.id}
                        onClick={() => act(q.id, () => transitionTrustedQuery(q.id, "reject", actorName()), "Rejected.")}>
                        Reject
                      </Button>
                      <Button size="xs" variant="ghost" disabled={busy === q.id}
                        onClick={() => setEditing(e => (e === q.id ? null : q.id))}>Edit</Button>
                      {sqlButton(q)}
                      {removeButton(q)}
                    </>
                  ) : (
                    <>
                      <Button size="xs" variant="minimal" disabled={busy === q.id}
                        onClick={() => act(q.id, () => transitionTrustedQuery(q.id, "propose", actorName()),
                          "Re-verified and proposed.")}>
                        Re-verify &amp; propose
                      </Button>
                      <Button size="xs" variant="ghost" disabled={busy === q.id}
                        onClick={() => setEditing(e => (e === q.id ? null : q.id))}>Edit</Button>
                      {sqlButton(q)}
                      {removeButton(q)}
                    </>
                  )} />
                {sqlBelow(q)}
              </div>
            );
          })}
      </NeedsYou>

      <article aria-label="What the loop has learned" style={{ ...CARD, padding: "16px 20px" }}>
        <Section title="Readings it remembers" testId="memory-readings" meta={readingsMeta}>
          {readings === null && !readingsErr ? <Loading what="the remembered readings" />
            : readingsErr ? <ReadFailed what="the remembered readings" error={readingsErr} onRetry={loadReadings} />
            : list.length === 0 ? (
              <Empty>Nothing remembered yet — a reading is kept when a probe, a person or a reviewer settles an ambiguous question.</Empty>
            ) : (
              <>
                {visible.map((r, i) => (
                  <Line key={r.id} first={i === 0}
                    figure={`${compactNumber(r.use_count)}×`}
                    figureTitle={r.last_used_at ? `served ${formatCount(r.use_count)} times · last ${formatTimestamp(r.last_used_at)}` : "not served yet"}
                    actions={
                      <Button variant="ghost" size="xs" disabled={revoking === r.id} onClick={() => { void revoke(r.id); }}
                        title="Revoke: the reading is deleted — nothing revoked is kept — and the next matching question is asked again">
                        {revoking === r.id ? "Revoking" : "Revoke"}
                      </Button>
                    }
                    below={revokeErr?.id === r.id && (
                      <p role="alert" className="aug-fs-xs" style={{ color: "var(--red4)", margin: "4px 0 0" }}>Not revoked — {revokeErr.text}</p>
                    )}>
                    <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)" }}
                      title={`${r.subject} → ${r.resolved_reading}`}>
                      <span style={{ color: "var(--t2)" }}>{r.subject}</span>
                      <span style={MUTED}> → </span>{r.resolved_reading}
                    </div>
                    <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }} title={formatTimestamp(r.created_at)}>
                      settled by {settledBy(r.resolution_source)} · {connectionLabel(r.connection_id, conns) || "no connection"} · {dayWords(r.created_at)}
                    </div>
                    {r.resolved_sql && (
                      <div className="aug-fs-xs" title={r.resolved_sql}
                        style={{ ...MUTED, ...ONE_LINE, fontFamily: "var(--font-mono)" }}>{r.resolved_sql}</div>
                    )}
                  </Line>
                ))}
                {list.length > READINGS_SHOWN && !showAll && (
                  <div className="aug-fs-xs" style={{ ...ROW, ...MUTED, ...RULE, paddingTop: 8 }}>
                    <span>{formatCount(READINGS_SHOWN)} of {formatCount(list.length)} shown</span>
                    <Button variant="ghost" size="xs" onClick={() => setShowAll(true)}>Show all {formatCount(list.length)}</Button>
                  </div>
                )}
              </>
            )}
        </Section>

        <Section title="Queries it trusts" testId="memory-trusted"
          style={{ ...RULE, marginTop: 16, paddingTop: 14 }}
          meta={trusted ? `${formatCount(approved)} approved · only approved ones reach a prompt` : ""}
          right={
            <Button variant="ghost" size="xs" onClick={() => setShowSeed(s => !s)} data-testid="tq-seed-toggle">
              {showSeed ? "Close" : "Seed a trusted query"}
            </Button>
          }>
          {showSeed && <SeedTrustedForm onDone={() => { setShowSeed(false); afterTrustedWrite(); }} />}
          {actNote && <p className="aug-fs-xs" role="status" style={{ color: "var(--grn4)", margin: "0 0 6px" }}>{actNote}</p>}
          {trusted === null && !trustedErr ? <Loading what="the trusted queries" />
            : trustedErr ? <ReadFailed what="the trusted queries" error={trustedErr} onRetry={loadTrusted} />
            : settled.length === 0 ? (
              <Empty>
                {waiting.length ? "None approved yet — the ones waiting are above." : "None yet — seed one, accept one from the Semantic Layer’s Import tab, or a verified answer lands here."}
              </Empty>
            ) : settled.map((q, i) => (
              <div key={q.id} data-testid={`tq-${q.id}`}>
                <Line first={i === 0}
                  actions={<>
                    {sqlButton(q)}
                    {q.status === "approved" && (
                      <Button size="xs" variant="ghost" disabled={busy === q.id}
                        onClick={() => act(q.id, () => transitionTrustedQuery(q.id, "deprecate", actorName()),
                          "Deprecated — it no longer reaches prompts.")}>
                        Deprecate
                      </Button>
                    )}
                    {removeButton(q)}
                  </>}
                  below={sqlBelow(q)}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                    <Dot hue={q.status === "approved" ? "green" : "grey"}
                      title={q.status === "approved" ? "approved — reaches prompts" : `${q.status} — out of every prompt`} />
                    <span className="aug-fs-chrome" title={q.question} style={{ ...ONE_LINE, color: "var(--t1)" }}>{q.question}</span>
                    {q.status !== "approved" && <Chip>{q.status}</Chip>}
                  </div>
                  <div className="aug-fs-xs" title={q.note || undefined} style={{ ...MUTED, ...ONE_LINE, paddingLeft: 15 }}>
                    {where(q)}{q.note ? ` · ${q.note}` : ""}
                  </div>
                </Line>
              </div>
            ))}
        </Section>

        <div style={{ ...RULE, marginTop: 16, paddingTop: 14, display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 24 }}>
          <Section title="What reviewers said" testId="memory-verdicts"
            meta={verdicts && verdicts.total > 0
              ? <>{countNoun(verdicts.total, "verdict")}{verdicts.acceptance_rate != null && (
                  <span title="A correction counts as half an acceptance."> · {pct(verdicts.acceptance_rate)} accepted</span>
                )}</>
              : ""}>
            {summaryState === "loading" ? <Loading what="the verdicts" />
              : summaryState === "failed" ? <ReadFailed what="the verdicts" onRetry={loadSummary} />
              : !verdicts || verdicts.total === 0 ? <Empty>No reviewer has judged an answer yet.</Empty>
              : (
                <>
                  <HBars testId="memory-verdict-bars" bars={Object.entries(verdicts.counts ?? {}).map(([k, n]) => ({
                    key: k, name: VERDICT_WORD[k] ?? keyToWords(k), value: n, shown: formatCount(n),
                    tip: `${VERDICT_WORD[k] ?? keyToWords(k)}: ${countNoun(n, "verdict")}`,
                  }))} />
                  <div style={{ marginTop: 12 }}>
                    {trend.length >= 2 ? (
                      <>
                        <div className="aug-fs-xs" style={{ ...MUTED, marginBottom: 4 }}>
                          Accepted each week · {pct(trend[0].acceptance_rate)} → {pct(trend[trend.length - 1].acceptance_rate)} over {trend.length} weeks
                        </div>
                        {/* A column per measured week, never wider than a column needs: two weeks are two marks, not a wall. */}
                        <div style={{ maxWidth: Math.max(120, trend.length * 40) }}>
                        <Columns height={44} columns={trend.map(t => ({
                          key: t.week, value: t.acceptance_rate, label: t.week.replace(/^\d{4}-/, ""),
                          tip: `${t.week}: ${pct(t.acceptance_rate)} of ${countNoun(t.total, "verdict")} accepted`,
                        }))} />
                        </div>
                      </>
                    ) : (
                      <Empty>Fewer than two measured weeks — one point is a number, not a trend.</Empty>
                    )}
                  </div>
                  <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 8 }}
                    title="Not how memory moved confidence, nor how many clarify questions it saved.">
                    Only acceptance is measured — not what memory changed.
                  </div>
                </>
              )}
          </Section>

          <Section title="Training corpus" testId="memory-corpus" meta="distillation waits until every gate passes"
            right={
              <Button variant="ghost" size="xs" disabled={exporting} onClick={exportNow}
                title="Runs every exporter once — an unchanged corpus exports nothing new, so it is safe to press.">
                {exporting ? "Exporting…" : "Export now"}
              </Button>
            }>
            {exportRefused && (
              <p role="alert" className="aug-fs-xs" style={{ color: "var(--red4)", margin: "0 0 8px" }}>{exportRefused}</p>
            )}
            {datasetsState === "loading" ? <Loading what="the training corpus" />
              : datasetsState === "failed" || !datasets ? <ReadFailed what="the training corpus" onRetry={loadDatasets} />
              : <Corpus datasets={datasets} />}
          </Section>
        </div>
      </article>
    </Page>
  );
}

// ── the training corpus: each gate as a bar to its line, then what is not a gate ─────────────────────────────────────

function Corpus({ datasets }: { datasets: LearningDatasets }) {
  const entries = Object.entries(datasets.gates);
  const gates = entries.filter(([, g]) => g.need != null);
  const tiers = entries.filter(([, g]) => g.need == null);
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(70px, auto) minmax(60px, 1fr) auto", gap: "8px 10px",
        alignItems: "center" }}>
        {gates.map(([kind, g]) => (
          <React.Fragment key={kind}>
            <span className="aug-fs-sm" title={GATE_WHAT[kind]} style={{ color: "var(--t1)" }}>{keyToWords(kind)}</span>
            <Bar value={g.have} max={g.need ?? 0} color={g.passes ? "var(--grn3)" : "var(--chart-1)"} />
            <span className="aug-fs-sm" style={{ ...ROW, gap: 6, color: "var(--t2)", ...NUM, flexWrap: "nowrap" }}>
              {formatCount(g.have)} of {formatCount(g.need)}{kind === "guard_days" ? " days" : ""}
              {g.passes && <Chip tone="up">passes</Chip>}
            </span>
          </React.Fragment>
        ))}
      </div>
      {tiers.length > 0 && (
        <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 8 }}
          title={tiers[0][1].note}>
          Not gates, graded by execution or a guard: {tiers.map(([k, g]) => `${keyToWords(k)} ${formatCount(g.have)}`).join(" · ")}
        </div>
      )}
      <DatasetInspector kinds={entries.map(([k]) => k).filter(k => DATASET_OF[k])} />
    </>
  );
}

// ── trusted-query forms (read first, edit behind Edit) ───────────────────────────────────────────────────────────────

const fieldStyle: React.CSSProperties = {
  width: "100%", boxSizing: "border-box", background: "var(--bg-2)",
  border: "1px solid var(--b1)", borderRadius: "var(--r2)",
  color: "var(--t1)", padding: "6px 8px", marginBottom: 6,
};

function SeedTrustedForm({ onDone }: { onDone: () => void }) {
  const [conns, setConns] = useState<Connection[]>([]);
  const [f, setF] = useState({ connection_id: "", question: "", sql: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { getConnections().then(cs => {
    setConns(cs); setF(v => ({ ...v, connection_id: v.connection_id || cs[0]?.id || "" }));
  }).catch(() => {}); }, []);
  const seed = async () => {
    setBusy(true); setErr("");
    try {
      await createTrustedQuery({ ...f, actor: actorName() });
      onDone();
    } catch (e) { setErr(errText(e)); }
    finally { setBusy(false); }
  };
  return (
    <div className="aug-fs-sm" style={{ background: "var(--bg-1)", borderRadius: "var(--r3)", padding: 10, marginBottom: 10 }}>
      <SelectField style={fieldStyle} value={f.connection_id}
        onChange={e => setF(v => ({ ...v, connection_id: e.target.value }))} data-testid="tq-seed-conn">
        {conns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
      </SelectField>
      <Input style={fieldStyle} placeholder="The question this SQL answers, in the words people ask it"
        value={f.question} onChange={e => setF(v => ({ ...v, question: e.target.value }))}
        data-testid="tq-seed-question" />
      <Textarea style={{ ...fieldStyle, minHeight: 64 }}
        placeholder="SELECT …" value={f.sql} onChange={e => setF(v => ({ ...v, sql: e.target.value }))}
        data-testid="tq-seed-sql" />
      <Input style={fieldStyle} placeholder="note (optional) — why this is the right answer"
        value={f.note} onChange={e => setF(v => ({ ...v, note: e.target.value }))} />
      <div style={{ ...ROW, gap: 10 }}>
        <Button size="sm" disabled={busy || !f.question.trim() || !f.sql.trim() || !f.connection_id}
          onClick={seed} data-testid="tq-seed-submit">
          {busy ? "Verifying…" : "Seed"}
        </Button>
        <span className="aug-fs-xs" style={MUTED}>
          It runs and is guarded now: passing lands it proposed, failing a draft. Only approval reaches a prompt.
        </span>
      </div>
      {err && <p role="alert" className="aug-fs-xs" style={{ color: "var(--red4)", margin: "6px 0 0" }}>{err}</p>}
    </div>
  );
}

function EditTrustedForm({ row, onDone }: { row: TrustedQueryRow; onDone: () => void }) {
  const [f, setF] = useState({ question: row.question, sql: row.sql, note: row.note });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true); setErr("");
    try { await editTrustedQuery(row.id, { ...f, actor: actorName() }); onDone(); }
    catch (e) { setErr(errText(e)); }
    finally { setBusy(false); }
  };
  return (
    <div style={{ marginTop: 8 }}>
      <Input style={fieldStyle} value={f.question}
        onChange={e => setF(v => ({ ...v, question: e.target.value }))} />
      <Textarea style={{ ...fieldStyle, minHeight: 64 }}
        value={f.sql} onChange={e => setF(v => ({ ...v, sql: e.target.value }))} />
      <Input style={fieldStyle} placeholder="note" value={f.note}
        onChange={e => setF(v => ({ ...v, note: e.target.value }))} />
      <div style={{ ...ROW, gap: 10 }}>
        <Button size="xs" disabled={busy} onClick={save} title="Saving re-verifies it and resets any approval">Save</Button>
        <span className="aug-fs-xs" style={MUTED}>re-verifies, and resets any approval</span>
        {err && <span role="alert" className="aug-fs-xs" style={{ color: "var(--red4)" }}>{err}</span>}
      </div>
    </div>
  );
}

// ── which verdicts fed a corpus ──────────────────────────────────────────────────────────────────────────────────────

function DatasetInspector({ kinds }: { kinds: string[] }) {
  const [kind, setKind] = useState<string | null>(null);
  const [detail, setDetail] = useState<LearningDatasetDetail | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "missing" | "failed">("idle");
  const inspect = async (k: string) => {
    if (kind === k) { setKind(null); setDetail(null); return; }
    setKind(k); setState("loading"); setDetail(null);
    try {
      const d = await getLearningDataset(DATASET_OF[k]);
      if (!d.found) { setState("missing"); return; }
      setDetail(d);
      setState("idle");
    } catch { setState("failed"); }
  };
  if (!kinds.length) return null;
  const node = detail?.dataset ?? {};
  const lineage = detail?.lineage?.length ?? 0;
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ ...ROW, gap: 6 }}>
        <span className="aug-fs-xs" style={MUTED}>Inspect a corpus:</span>
        {kinds.map(k => (
          <Button key={k} size="xs" variant={kind === k ? "secondary" : "ghost"} onClick={() => inspect(k)}>
            {keyToWords(k)}
          </Button>
        ))}
      </div>
      {kind && state === "loading" && <Loading what={`the ${keyToWords(kind)} corpus`} style={{ marginTop: 6 }} />}
      {kind && state === "failed" && <Empty>Could not read the {keyToWords(kind)} corpus.</Empty>}
      {kind && state === "missing" && (
        <Empty>No exported version of “{DATASET_OF[kind]}” yet — press Export now once the corpus has rows.</Empty>
      )}
      {kind && detail && (
        <div className="aug-fs-xs" style={{ marginTop: 8, background: "var(--bg-1)", borderRadius: "var(--r2)", padding: 10,
          color: "var(--t2)" }} title={`id ${String(node.id ?? "")} · data ${String(node.data_id ?? "")}`}>
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--t1)" }}>{String(node.name ?? DATASET_OF[kind])}</span>
          {" · "}version {String(node.version ?? "—")}
          {" · "}{countNoun(Number(node.row_count ?? 0), "example")}
          {node.created_at ? ` · exported ${dayWords(String(node.created_at))}` : ""}
          <div style={{ ...MUTED, marginTop: 4 }}>
            {countNoun(lineage, "lineage record")} — the verdicts and trusted queries that fed this version.
          </div>
          {detail.note && <div style={{ color: "var(--amb4)", marginTop: 4 }}>{detail.note}</div>}
        </div>
      )}
    </div>
  );
}
