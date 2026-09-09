"use client";
/* ── Agent Workspace · Memory (native cards) ────────────────────────────────
   The closed loop's accumulation, made visible (Wave 1 · E4): the ambiguity-
   ledger burn-down (resolutions settled, by source, times served as priors), the
   verdict acceptance economy, and the trusted assets injected authoritatively
   into prompts. Reads /learning/summary + /learning/trusted (org-wide). Degrades
   quietly when there is no data or the endpoints fail. */
import React, { useCallback, useEffect, useState } from "react";
import { compactNumber } from "@/lib/format";
import {
  createTrustedQuery, deleteTrustedQuery, editTrustedQuery, getConnections,
  getLearningDataset, getLearningDatasets, getLearningSummary, listRememberedReadings,
  listTrustedQueries, revokeRememberedReading, runLearningExport, transitionTrustedQuery,
  type Connection, type LearningDatasets, type LearningSummary, type RememberedReading,
  type TrustedQueryRow,
} from "@/lib/api";
import { claimsOf, getIdToken } from "@/lib/auth";
import { Button } from "@/components/ui/button";

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
const plural = (n: number, noun: string) => `${n} ${n === 1 ? noun : noun === "query" ? "queries" : noun + "s"}`;

const rowStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
  background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r2)",
};
const kindTag: React.CSSProperties = {
  fontSize: 11, color: "var(--t3)", textTransform: "uppercase", letterSpacing: 0.4, width: 58, flexShrink: 0,
};
const ellipsize: React.CSSProperties = {
  flex: 1, fontSize: 12, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
};

/** "72% → 84% over N wks" from the weekly acceptance series — the product's
 *  accuracy TREND (S3). Null when fewer than two measured weeks exist: one
 *  point is a number, not a direction. */
function trendSub(trend?: { week: string; acceptance_rate: number }[]): string | null {
  if (!trend || trend.length < 2) return null;
  const first = trend[0], last = trend[trend.length - 1];
  return `${Math.round(first.acceptance_rate * 100)}% → ${Math.round(last.acceptance_rate * 100)}% over ${trend.length} wks`;
}

export function MemoryPanel() {
  const [summary, setSummary] = useState<LearningSummary | null>(null);
  const [loading, setLoading] = useState(true);   // fetch runs once on mount; starts in the loading state
  // S5 cited memory — the readings themselves: remembered, cited, revocable.
  const [readings, setReadings] = useState<RememberedReading[]>([]);
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
    getLearningSummary().then(setSummary).finally(() => setLoading(false));
    listTrustedQueries().then(setTrustedRows).catch(() => setTrustedRows([]));
    listRememberedReadings().then(setReadings).catch(() => setReadings([]));
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
      setReadings(rs => rs.filter(r => r.id !== id));
    } catch { /* row stays; the user can retry */ }
    finally { setRevoking(null); }
  };

  const ledger = summary?.ledger;
  const verdicts = summary?.verdicts;
  const acc = verdicts?.acceptance_rate;
  const bySource = ledger?.by_source ?? {};
  const sources = Object.keys(bySource);
  const trustedTotal = summary?.trusted.queries ?? 0;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "18px 22px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <span style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>Memory</span>
        <span style={{ fontSize: 12, color: "var(--t3)" }}>what the closed loop has learned</span>
      </div>
      <div style={{ fontSize: 12, color: "var(--t2)", marginBottom: 16, maxWidth: 640, lineHeight: 1.5 }}>
        Every clarified ambiguity, human verdict, and verified query compounds into durable priors the agent
        reuses on later questions — retrieved at plan time so it doesn&apos;t ask twice. This is that accumulation.
      </div>

      {loading ? (
        <div style={{ fontSize: 12, color: "var(--t3)" }}>Loading…</div>
      ) : !summary ? (
        <div style={{ fontSize: 12, color: "var(--t3)" }}>No learning data yet.</div>
      ) : (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 18 }}>
            <Tile label="Resolutions" value={compactNumber(ledger?.resolutions ?? 0)} sub="ambiguities settled" />
            <Tile label="Times served" value={compactNumber(ledger?.served_total ?? 0)} sub="priors reused in answers" />
            <Tile label="Acceptance" value={acc != null ? `${Math.round(acc * 100)}%` : "—"}
                  sub={trendSub(verdicts?.trend) ?? `${verdicts?.total ?? 0} verdicts`} />
            <Tile label="Trusted" value={String(trustedTotal)} sub={plural(summary.trusted.queries, "query")} />
          </div>

          {readings.length > 0 && (
            <>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)", marginBottom: 4 }}>
                Remembered readings
              </div>
              <div style={{ fontSize: 11, color: "var(--t3)", marginBottom: 8, maxWidth: 640 }}>
                Each is injected as a prior on matching questions — cited to who settled it,
                and revocable: a revoked reading re-ambiguates instead of silently persisting.
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 1, marginBottom: 18 }}>
                {readings.slice(0, 30).map(r => (
                  <div key={r.id} style={{ ...rowStyle, padding: "7px 10px", alignItems: "center" }}>
                    <span style={{ flex: 1, fontSize: 12, color: "var(--t1)", minWidth: 0 }}>
                      <span style={{ color: "var(--t2)" }}>{r.subject}</span>
                      {" → "}{r.resolved_reading}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--t3)", whiteSpace: "nowrap" }}>
                      {SOURCE_LABEL[r.resolution_source] ?? r.resolution_source}
                      {" · served "}{compactNumber(r.use_count)}
                    </span>
                    <Button variant="ghost" size="xs" disabled={revoking === r.id}
                            onClick={() => revoke(r.id)}
                            className="h-auto px-1.5 py-0.5 aug-fs-xs font-normal text-zinc-500 hover:text-red-400 hover:bg-transparent dark:hover:bg-transparent">
                      {revoking === r.id ? "Revoking…" : "Revoke"}
                    </Button>
                  </div>
                ))}
              </div>
            </>
          )}

          {sources.length > 0 && (
            <>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)", marginBottom: 8 }}>Resolutions by source</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 1, marginBottom: 18 }}>
                {sources.map(s => (
                  <div key={s} style={{ ...rowStyle, padding: "7px 10px" }}>
                    <span style={{ flex: 1, fontSize: 12, color: "var(--t1)" }}>{SOURCE_LABEL[s] ?? s}</span>
                    <span style={{ fontSize: 12, color: "var(--t2)" }}>{bySource[s]}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* PX-4 — the closed loop's WRITE half. The flywheel moves by grading, and
              until this section grading had no door: the panel could show trusted
              queries and could not author, promote, or retire one. */}
          <TrustedGovernance rows={trustedRows} onChanged={reloadTrusted} />

          {datasets && (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 18, marginBottom: 4 }}>
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
            </>
          )}
        </>
      )}
    </div>
  );
}

// ── PX-4 · trusted-query governance (the write half) ─────────────────────────

const STATUS_COLOR: Record<string, string> = {
  draft: "var(--t4)", proposed: "var(--blue4)", approved: "var(--grn4)",
  rejected: "var(--t4)", deprecated: "var(--t4)",
};

function StatusChip({ status }: { status: string }) {
  const color = STATUS_COLOR[status] ?? "var(--t4)";
  return (
    <span className="aug-fs-xs" style={{ color,
      border: `1px solid color-mix(in srgb, ${color} 45%, transparent)`,
      borderRadius: "var(--r-chip)", padding: "1px 8px", whiteSpace: "nowrap" }}>
      {status}
    </span>
  );
}

function TrustedGovernance({ rows, onChanged }: {
  rows: TrustedQueryRow[]; onChanged: () => void;
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
              <span className="aug-fs-xs" style={{ color: "var(--t4)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>
                {q.connection_id} · v{q.version}
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
        <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
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
        <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>Inspect a corpus:</span>
        {kinds.map(k => (
          <Button key={k} size="xs" variant={name === k ? "secondary" : "ghost"} onClick={() => inspect(k)}>
            {k}
          </Button>
        ))}
      </div>
      {name && state === "missing" && (
        <p className="aug-fs-xs" style={{ color: "var(--t4)", margin: "6px 0 0" }}>
          No exported version of “{name}” yet — press “Export now” above once the corpus has rows.
        </p>
      )}
      {name && detail && (
        <div className="aug-fs-xs" style={{ margin: "8px 0 0", border: "1px solid var(--b1)",
          borderRadius: "var(--r2)", background: "var(--bg-1)", padding: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 12px" }}>
            {Object.entries(detail).filter(([, v]) => typeof v !== "object" || v === null).map(([k, v]) => (
              <React.Fragment key={k}>
                <span style={{ color: "var(--t4)" }}>{k}</span>
                <span style={{ color: "var(--t2)", fontFamily: "var(--font-mono)", wordBreak: "break-all" }}>{String(v)}</span>
              </React.Fragment>
            ))}
          </div>
          <p style={{ color: "var(--t4)", margin: "6px 0 0" }}>
            Provenance: {compactNumber(lineage.length)} lineage record{lineage.length === 1 ? "" : "s"} —
            the verdicts that fed this version, the question MI-4 owes about any adapter it promotes.
          </p>
        </div>
      )}
    </div>
  );
}
