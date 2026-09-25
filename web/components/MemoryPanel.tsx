"use client";
/* ── Memory — what the closed loop has learned (Aughor Intelligence · 06 Memory) ──────────────
   Numbered sections beside a rail: §01 the remembered readings as rows (what was ambiguous → how it
   is read, who settled it, where, how often it has been served), §02 the trusted queries and their
   governance, §03 the training corpus; the rail is where memory comes from — resolutions by source,
   the verdicts, and the weekly acceptance loop.

   Drawn only from what the loop stores. Left out: a "retired" list and its count (Revoke DELETES a
   reading — nothing revoked is kept), "Add lesson" (no route writes a reading; they come from
   settled clarify questions, probes and verdicts), a lesson's "because" and kind beyond its source,
   an export of memory itself (the export here is the training corpus, and it writes), and the
   design's "effect on behaviour" figures (nothing measures them). Each source loads on its own, so
   a failed summary no longer hides the readings. Org-wide; reads /learning/*. */
import { connectionLabel } from "@/lib/names";
import React, { useCallback, useEffect, useState } from "react";
import { compactNumber, countNoun, formatCount, formatTimestamp, pct, relTime } from "@/lib/format";
import {
  createTrustedQuery, deleteTrustedQuery, editTrustedQuery, getConnections,
  getLearningDataset, getLearningDatasets, getLearningSummary, listRememberedReadings,
  listTrustedQueries, revokeRememberedReading, runLearningExport, transitionTrustedQuery,
  type Connection, type LearningDatasets, type LearningSummary, type RememberedReading,
  type TrustedQueryRow,
} from "@/lib/api";
import { claimsOf, getIdToken } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Sparkline } from "@/components/brief/Sparkline";
import { SkeletonRows } from "@/components/ui/motion";

/** The acting identity for governance writes — the signed-in email, else the
 *  same word the actions inbox uses. The server owns identity; this is provenance. */
const actorName = () => claimsOf(getIdToken())?.email || "human";

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{
      flex: "1 1 120px", minWidth: 120, padding: "12px 14px",
      background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
    }}>
      <div style={{ fontSize: 11, color: "var(--t3)", textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600, color: "var(--t1)", marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

const SOURCE_LABEL: Record<string, string> = { probe: "auto-probe", user: "user choice", verdict: "reviewer" };

/** Readings shown before "Show all" — a long list stays scannable, and the cut is never silent. */
const READINGS_SHOWN = 30;

/** "72% → 84% over N wks" from the weekly acceptance series — the product's
 *  accuracy TREND (S3). Null when fewer than two measured weeks exist: one
 *  point is a number, not a direction. */
function trendSub(trend?: { week: string; acceptance_rate: number }[]): string | null {
  if (!trend || trend.length < 2) return null;
  const first = trend[0], last = trend[trend.length - 1];
  return `${Math.round(first.acceptance_rate * 100)}% → ${Math.round(last.acceptance_rate * 100)}% over ${trend.length} wks`;
}

export function MemoryPanel() {
  // Connections by name: the ledger's CONNECTION column and the trusted queries' scope line
  // read `theLook`, never `8233e4fd` (lib/names.ts).
  const [conns, setConns] = useState<Connection[]>([]);
  useEffect(() => { getConnections().then(setConns).catch(() => {}); }, []);
  const [summary, setSummary] = useState<LearningSummary | null>(null);
  const [summaryState, setSummaryState] = useState<"loading" | "ready" | "failed">("loading");
  // S5 cited memory — the readings themselves: remembered, cited, revocable.
  const [readings, setReadings] = useState<RememberedReading[] | null>(null);
  const [readingsFailed, setReadingsFailed] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  // MI-3: the corpus those verdicts become, and the measured distance to MI-4's gates.
  const [datasets, setDatasets] = useState<LearningDatasets | null>(null);
  const [exporting, setExporting] = useState(false);
  // PX-4 — the write half: every trusted query in every status, governable from here.
  const [trustedRows, setTrustedRows] = useState<TrustedQueryRow[]>([]);

  const reloadTrusted = useCallback(() => {
    listTrustedQueries().then(setTrustedRows).catch(() => setTrustedRows([]));
    getLearningSummary().then(s => { if (s) setSummary(s); }).catch(() => {});
    getLearningDatasets().then(d => { if (d) setDatasets(d); }).catch(() => {});
  }, []);

  useEffect(() => {
    // Each source on its own: a failed summary used to hide the readings with it.
    getLearningSummary()
      .then(s => { setSummary(s); setSummaryState(s ? "ready" : "failed"); })
      .catch(() => setSummaryState("failed"));
    listTrustedQueries().then(setTrustedRows).catch(() => setTrustedRows([]));
    listRememberedReadings().then(setReadings).catch(() => { setReadings([]); setReadingsFailed(true); });
    getLearningDatasets().then(setDatasets).catch(() => setDatasets(null));
  }, []);

  const exportNow = async () => {
    setExporting(true);
    try {
      const out = await runLearningExport();
      if (out) setDatasets({ stats: datasets?.stats ?? {}, gates: out.gates });
      const fresh = await getLearningDatasets();
      if (fresh) setDatasets(fresh);
    } finally { setExporting(false); }
  };

  const revoke = async (id: string) => {
    setRevoking(id);
    try {
      await revokeRememberedReading(id);
      setReadings(rs => (rs ?? []).filter(r => r.id !== id));
    } catch { /* row stays; the user can retry */ }
    finally { setRevoking(null); }
  };

  const ledger = summary?.ledger;
  const verdicts = summary?.verdicts;
  const acc = verdicts?.acceptance_rate ?? null;
  const bySource = Object.entries(ledger?.by_source ?? {}).sort((a, b) => b[1] - a[1]);
  const sourceTotal = bySource.reduce((n, [, c]) => n + c, 0);
  const trend = verdicts?.trend ?? [];
  const list = readings ?? [];
  const visible = showAll ? list : list.slice(0, READINGS_SHOWN);

  const meta = [
    readings ? `${countNoun(list.length, "reading")} remembered` : "",
    ledger ? `served ${compactNumber(ledger.served_total)}×` : "",
    acc != null ? `${pct(acc)} of verdicts accepted` : "",
  ].filter(Boolean).join(" · ");

  return (
    <div className="aug-profile">
      <div className="aug-profile-main">
        <div className="aug-brief-strip">
          <span className="aug-brief-eyebrow">Memory</span>
          {meta && <span className="aug-brief-meta">{meta}</span>}
        </div>

        <section className="aug-brief-sec">
          <div className="aug-brief-body">
            <div className="aug-brief-head">
              <span className="aug-brief-eyebrow">Remembered readings</span>
              <span className="aug-brief-meta">a prior on every matching question — cited to who settled it, and revocable</span>
            </div>
            {readings === null ? (
              <SkeletonRows rows={5} />
            ) : readingsFailed ? (
              <p className="aug-brief-note">The remembered readings could not be read.</p>
            ) : list.length === 0 ? (
              <p className="aug-brief-note">
                Nothing remembered yet. A reading is kept when an ambiguous question is settled — by a probe, by a
                person answering a clarify question, or by a reviewer&apos;s verdict.
              </p>
            ) : (
              <>
                <div className="aug-moves-wrap">
                  <table className="aug-dt aug-ledger-table">
                    <thead>
                      <tr>
                        <th>what was ambiguous → how it is read</th>
                        <th className="aug-memory-col-source">settled by</th>
                        <th className="aug-memory-col-conn">connection</th>
                        <th className="num aug-memory-col-num">served</th>
                        <th className="num aug-memory-col-when">settled</th>
                        <th className="aug-memory-col-door"><span className="sr-only">Revoke</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {visible.map(r => (
                        <tr key={r.id}>
                          <td className="aug-ledger-claim">
                            <span className="aug-ledger-text">
                              <span className="aug-memory-subject">{r.subject}</span> → {r.resolved_reading}
                            </span>
                            {r.resolved_sql && <span className="aug-ledger-query">{r.resolved_sql}</span>}
                          </td>
                          <td className="aug-memory-source">{SOURCE_LABEL[r.resolution_source] ?? r.resolution_source}</td>
                          <td className="aug-memory-conn" title={r.connection_id}>{connectionLabel(r.connection_id, conns) || "—"}</td>
                          <td className="num" title={r.last_used_at ? `last served ${formatTimestamp(r.last_used_at)}` : "not served yet"}>
                            {compactNumber(r.use_count)}×
                          </td>
                          <td className="num aug-ledger-when" title={formatTimestamp(r.created_at)}>{relTime(r.created_at)}</td>
                          <td className="aug-org-door">
                            <Button variant="ghost" size="xs" disabled={revoking === r.id}
                              onClick={() => { void revoke(r.id); }}
                              title="Revoke: the reading is deleted, and the next matching question is asked again">
                              {revoking === r.id ? "Revoking" : "Revoke"}
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="aug-profile-foot">
                  {list.length > READINGS_SHOWN && !showAll && (
                    <>
                      <Button variant="link" size="xs" onClick={() => setShowAll(true)}>
                        Show all {formatCount(list.length)}
                      </Button>{" "}
                    </>
                  )}
                  Revoking deletes a reading — nothing revoked is kept, so there is no retired list — and the next
                  matching question is asked again.
                </p>
              </>
            )}
          </div>
        </section>

        <section className="aug-brief-sec">
          <div className="aug-brief-body">
            {/* PX-4 — the closed loop's WRITE half. The flywheel moves by grading, and
                until this section grading had no door: the panel could show trusted
                queries and could not author, promote, or retire one. */}
            <TrustedGovernance rows={trustedRows} onChanged={reloadTrusted} connections={conns} />
          </div>
        </section>

        {datasets && (
          <section className="aug-brief-sec">
            <div className="aug-brief-body">
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
                <span className="aug-fs-sm" style={{ fontWeight: 600, color: "var(--t2)" }}>Training corpus</span>
                <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>graded work, exportable — and the measured distance to the MI-4 gates</span>
                <span style={{ flex: 1 }} />
                <Button variant="ghost" size="xs" disabled={exporting} onClick={exportNow}
                        className="h-auto px-1.5 py-0.5 aug-fs-xs font-normal">
                  {exporting ? "Exporting…" : "Export now"}
                </Button>
              </div>
              <div className="aug-fs-xs" style={{ color: "var(--t3)", marginBottom: 8, maxWidth: 640 }}>
                Distillation (MI-4) does not start until every gate passes; an unchanged corpus
                exports nothing new, so the button is safe to press.
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                {Object.entries(datasets.gates).map(([kind, g]) => (
                  <Tile key={kind} label={kind.toUpperCase()}
                        value={`${compactNumber(g.have)} / ${compactNumber(g.need)}`}
                        sub={g.passes ? "gate passes" : "below the gate"} />
                ))}
              </div>
              <DatasetInspector kinds={Object.keys(datasets.gates)} />
            </div>
          </section>
        )}
      </div>

      <aside className="aug-profile-rail" aria-label="Where memory comes from">
        <div className="aug-profile-rail-head">
          <span className="aug-brief-eyebrow">Sources</span>
          <span className="aug-brief-meta">{ledger ? countNoun(ledger.resolutions, "resolution") : ""}</span>
        </div>
        <div className="aug-profile-block">
          {summaryState === "loading" ? (
            <SkeletonRows rows={3} />
          ) : summaryState === "failed" ? (
            <p className="aug-brief-note">The learning summary could not be read.</p>
          ) : bySource.length === 0 ? (
            <p className="aug-brief-note">No ambiguity has been settled yet.</p>
          ) : bySource.map(([src, n]) => (
            <div key={src} className="aug-memory-share">
              <div className="aug-memory-share-head">
                <span>{SOURCE_LABEL[src] ?? src}</span>
                <span className="aug-memory-share-n">{formatCount(n)}</span>
              </div>
              <div className="aug-memory-share-rule" aria-hidden>
                <span style={{ width: `${sourceTotal ? (n / sourceTotal) * 100 : 0}%` }} />
              </div>
            </div>
          ))}
        </div>

        <div className="aug-profile-rail-head">
          <span className="aug-brief-eyebrow">Verdicts</span>
          <span className="aug-brief-meta">{verdicts ? countNoun(verdicts.total, "verdict") : ""}</span>
        </div>
        <div className="aug-profile-block">
          {summaryState === "loading" ? (
            <SkeletonRows rows={2} />
          ) : summaryState === "failed" ? (
            <p className="aug-brief-note">—</p>
          ) : !verdicts || verdicts.total === 0 ? (
            <p className="aug-brief-note">No reviewer has judged an answer yet.</p>
          ) : (
            <>
              <dl className="aug-inspector-rows">
                {Object.entries(verdicts.counts ?? {}).map(([k, n]) => (
                  <div key={k}><dt>{k}</dt><dd>{formatCount(n)}</dd></div>
                ))}
              </dl>
              {acc != null && (
                <p className="aug-inspector-note">{pct(acc)} accepted{trendSub(trend) ? ` · ${trendSub(trend)}` : ""}</p>
              )}
            </>
          )}
        </div>

        <div className="aug-profile-rail-head">
          <span className="aug-brief-eyebrow">Loop</span>
          <span className="aug-brief-meta">{trend.length >= 2 ? `acceptance · last ${trend.length} weeks` : ""}</span>
        </div>
        <div className="aug-profile-block">
          {trend.length >= 2 ? (
            <>
              <Sparkline values={trend.map(t => t.acceptance_rate)} width={300} height={48} color="var(--chart-2)" />
              <p className="aug-inspector-note">
                The weekly share of verdicts that accepted the answer. Nothing else is measured — not how memory moved
                confidence, nor how many clarify questions it saved.
              </p>
            </>
          ) : (
            <p className="aug-brief-note">Fewer than two measured weeks — one point is a number, not a trend.</p>
          )}
        </div>
      </aside>
    </div>
  );
}

// ── PX-4 · trusted-query governance (the write half) ─────────────────────────

const STATUS_COLOR: Record<string, string> = {
  draft: "var(--t3)", proposed: "var(--blue4)", approved: "var(--grn4)",
  rejected: "var(--t3)", deprecated: "var(--t3)",
};

function StatusChip({ status }: { status: string }) {
  const color = STATUS_COLOR[status] ?? "var(--t3)";
  return (
    <span className="aug-fs-xs" style={{ color,
      border: `1px solid color-mix(in srgb, ${color} 45%, transparent)`,
      borderRadius: "var(--r-chip)", padding: "1px 8px", whiteSpace: "nowrap" }}>
      {status}
    </span>
  );
}

function TrustedGovernance({ rows, onChanged, connections }: {
  rows: TrustedQueryRow[]; onChanged: () => void; connections: Connection[];
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [editing, setEditing] = useState<TrustedQueryRow | null>(null);
  const [showSeed, setShowSeed] = useState(false);

  const act = async (id: string, fn: () => Promise<unknown>, done: string) => {
    setBusy(id); setErr(""); setNote("");
    try { await fn(); setNote(done); onChanged(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  // Decisions first: what needs a human leads the list.
  const order: Record<string, number> = { proposed: 0, draft: 1, approved: 2 };
  const sorted = [...rows].sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3));

  return (
    <>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <span className="aug-fs-sm" style={{ fontWeight: 600, color: "var(--t2)" }}>Trusted queries</span>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          only <strong>approved</strong> reaches a prompt; approval is a recorded human act
        </span>
        <span style={{ flex: 1 }} />
        <Button variant="ghost" size="xs" className="h-auto px-1.5 py-0.5 aug-fs-xs font-normal"
          onClick={() => setShowSeed(s => !s)} data-testid="tq-seed-toggle">
          {showSeed ? "Close" : "Seed a trusted query"}
        </Button>
      </div>
      {showSeed && <SeedTrustedForm onDone={() => { setShowSeed(false); onChanged(); }} />}
      {sorted.length === 0 && (
        <div className="aug-fs-sm" style={{ color: "var(--t3)", marginBottom: 12 }}>
          None yet — seed one above, accept one through the Semantic Layer&rsquo;s Import tab,
          or let a verified answer crystallize here.
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 18 }}>
        {sorted.map(q => (
          <div key={q.id} data-testid={`tq-${q.id}`} style={{ border: "1px solid var(--b1)",
            borderRadius: "var(--r2)", background: "var(--bg-1)", padding: "8px 10px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <StatusChip status={q.status} />
              <span className="aug-fs-sm" style={{ flex: 1, color: "var(--t1)", minWidth: 0,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {q.question}
              </span>
              <span className="aug-fs-xs" style={{ color: "var(--t3)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>
                {connectionLabel(q.connection_id, connections)} · v{q.version}
              </span>
              <Button variant="ghost" size="xs" className="h-auto px-1 py-0.5 aug-fs-xs font-normal"
                onClick={() => setOpen(o => o === q.id ? null : q.id)}>
                {open === q.id ? "Hide" : "SQL"}
              </Button>
            </div>
            {open === q.id && (
              <pre className="aug-fs-xs" style={{ margin: "6px 0 0", whiteSpace: "pre-wrap",
                fontFamily: "var(--font-mono)", color: "var(--t2)", background: "var(--bg-2)",
                borderRadius: "var(--r2)", padding: 8 }}>{q.sql}</pre>
            )}
            {q.status === "draft" && q.verification && (q.verification as { passed?: boolean }).passed === false && (
              <p className="aug-fs-xs" style={{ color: "var(--amb4)", margin: "4px 0 0" }}>
                Verification failed — it stays a draft, out of every prompt. Edit and re-propose.
              </p>
            )}
            <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
              {q.status === "draft" && (
                <Button size="xs" variant="minimal" disabled={busy === q.id}
                  onClick={() => act(q.id, () => transitionTrustedQuery(q.id, "propose", actorName()),
                    "Re-verified and proposed.")}>
                  Re-verify &amp; propose
                </Button>
              )}
              {q.status === "proposed" && (
                <>
                  <Button size="xs" variant="default" disabled={busy === q.id} data-testid={`tq-approve-${q.id}`}
                    onClick={() => act(q.id, () => transitionTrustedQuery(q.id, "approve", actorName()),
                      "Approved — it now reaches prompts, and the approval is on the ledger.")}>
                    Approve
                  </Button>
                  <Button size="xs" variant="ghost" disabled={busy === q.id}
                    onClick={() => act(q.id, () => transitionTrustedQuery(q.id, "reject", actorName()),
                      "Rejected.")}>
                    Reject
                  </Button>
                </>
              )}
              {q.status === "approved" && (
                <Button size="xs" variant="ghost" disabled={busy === q.id}
                  onClick={() => act(q.id, () => transitionTrustedQuery(q.id, "deprecate", actorName()),
                    "Deprecated — it no longer reaches prompts.")}>
                  Deprecate
                </Button>
              )}
              {(q.status === "draft" || q.status === "proposed") && (
                <Button size="xs" variant="ghost" disabled={busy === q.id}
                  onClick={() => setEditing(editing?.id === q.id ? null : q)}>
                  Edit
                </Button>
              )}
              <Button size="xs" variant="ghost" disabled={busy === q.id} data-testid={`tq-delete-${q.id}`}
                className="text-zinc-500 hover:text-red-400"
                onClick={() => { if (confirm("Remove this trusted query? The removal is audited."))
                  act(q.id, () => deleteTrustedQuery(q.id, actorName()), "Removed — the deletion is on the ledger."); }}>
                Remove
              </Button>
            </div>
            {editing?.id === q.id && (
              <EditTrustedForm row={q} onDone={() => { setEditing(null); onChanged(); }} />
            )}
          </div>
        ))}
      </div>
      {note && <p className="aug-fs-xs" style={{ color: "var(--grn4)", margin: "0 0 10px" }}>{note}</p>}
      {err && <p className="aug-fs-xs" style={{ color: "var(--red4)", margin: "0 0 10px" }}>{err}</p>}
    </>
  );
}

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
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return (
    <div className="aug-fs-sm" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)",
      background: "var(--bg-1)", padding: 10, marginBottom: 10 }}>
      <select style={fieldStyle} value={f.connection_id}
        onChange={e => setF(v => ({ ...v, connection_id: e.target.value }))} data-testid="tq-seed-conn">
        {conns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      <input style={fieldStyle} placeholder="The question this SQL answers, in the words people ask it"
        value={f.question} onChange={e => setF(v => ({ ...v, question: e.target.value }))}
        data-testid="tq-seed-question" />
      <textarea style={{ ...fieldStyle, minHeight: 64, fontFamily: "var(--font-mono)" }}
        placeholder="SELECT …" value={f.sql} onChange={e => setF(v => ({ ...v, sql: e.target.value }))}
        data-testid="tq-seed-sql" />
      <input style={fieldStyle} placeholder="note (optional) — why this is the right answer"
        value={f.note} onChange={e => setF(v => ({ ...v, note: e.target.value }))} />
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Button size="sm" disabled={busy || !f.question.trim() || !f.sql.trim() || !f.connection_id}
          onClick={seed} data-testid="tq-seed-submit">
          {busy ? "Verifying…" : "Seed — it is executed and guarded now"}
        </Button>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          Passing lands it <em>proposed</em>; failing lands a draft with the report. Nothing
          reaches a prompt until a person approves.
        </span>
      </div>
      {err && <p className="aug-fs-xs" style={{ color: "var(--red4)", margin: "6px 0 0" }}>{err}</p>}
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
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return (
    <div style={{ marginTop: 8 }}>
      <input style={fieldStyle} value={f.question}
        onChange={e => setF(v => ({ ...v, question: e.target.value }))} />
      <textarea style={{ ...fieldStyle, minHeight: 64, fontFamily: "var(--font-mono)" }}
        value={f.sql} onChange={e => setF(v => ({ ...v, sql: e.target.value }))} />
      <input style={fieldStyle} placeholder="note" value={f.note}
        onChange={e => setF(v => ({ ...v, note: e.target.value }))} />
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Button size="xs" disabled={busy} onClick={save}>Save — re-verifies, resets any approval</Button>
        {err && <span className="aug-fs-xs" style={{ color: "var(--red4)" }}>{err}</span>}
      </div>
    </div>
  );
}

// ── PX-4 · dataset detail (which verdicts fed the corpus) ─────────────────────

function DatasetInspector({ kinds }: { kinds: string[] }) {
  const [name, setName] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [lineage, setLineage] = useState<Record<string, unknown>[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "missing">("idle");
  const inspect = async (k: string) => {
    if (name === k) { setName(null); setDetail(null); return; }
    setName(k); setState("loading"); setDetail(null); setLineage([]);
    try {
      const d = await getLearningDataset(k);
      if (!d.found) { setState("missing"); return; }
      setDetail(d.dataset ?? {});
      setLineage((d.lineage as Record<string, unknown>[]) ?? []);
      setState("idle");
    } catch { setState("missing"); }
  };
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>Inspect a corpus:</span>
        {kinds.map(k => (
          <Button key={k} size="xs" variant={name === k ? "secondary" : "ghost"} onClick={() => inspect(k)}>
            {k}
          </Button>
        ))}
      </div>
      {name && state === "missing" && (
        <p className="aug-fs-xs" style={{ color: "var(--t3)", margin: "6px 0 0" }}>
          No exported version of “{name}” yet — press “Export now” above once the corpus has rows.
        </p>
      )}
      {name && detail && (
        <div className="aug-fs-xs" style={{ margin: "8px 0 0", border: "1px solid var(--b1)",
          borderRadius: "var(--r2)", background: "var(--bg-1)", padding: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 12px" }}>
            {Object.entries(detail).filter(([, v]) => typeof v !== "object" || v === null).map(([k, v]) => (
              <React.Fragment key={k}>
                <span style={{ color: "var(--t3)" }}>{k}</span>
                <span style={{ color: "var(--t2)", fontFamily: "var(--font-mono)", wordBreak: "break-all" }}>{String(v)}</span>
              </React.Fragment>
            ))}
          </div>
          <p style={{ color: "var(--t3)", margin: "6px 0 0" }}>
            Provenance: {compactNumber(lineage.length)} lineage record{lineage.length === 1 ? "" : "s"} —
            the verdicts that fed this version, the question MI-4 owes about any adapter it promotes.
          </p>
        </div>
      )}
    </div>
  );
}
