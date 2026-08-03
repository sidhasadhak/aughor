"use client";

/**
 * WP-10 — "Why this number": the unified public Trust Receipt, on demand.
 *
 * A small trigger under an answer opens a drawer that resolves the answer's receipt id
 * through GET /receipt/{id} — one signed contract for any mode. It shows the executed SQL
 * (copyable), the guards that fired (each named, with its action), caveats, governed-metric
 * enforcement, confidence + caps, the model, and the run cost — the moat made inspectable.
 *
 * Reusable by any surface that can hand it a receipt id (chat today; ResultFigure / KPI tiles /
 * briefing figures once those stamp one).
 */
import { useEffect, useState } from "react";
import {
  getAnswerTrace, getPublicReceipt,
  type AnswerTrace, type PublicReceipt, type PublicReceiptGuard, type TracedNode,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { WarrantChip } from "@/components/graph/WarrantChip";
import { AddToEvalSuite } from "@/components/AddToEvalSuite";
import { costSummary } from "@/lib/cost";
import { formatTimestamp } from "@/lib/format";

// A guard's action → chip hue + verb. `flagged` is the only cautionary one; a repair/trust is
// a guard doing its job (info/positive), never red.
function guardTone(action: string): { hue: ChipHue; verb: string } {
  if (action === "flagged") return { hue: "caution", verb: "flagged" };
  // `trusted` is deliberately absent: it is not a guard and is rendered in its own section.
  // It used to map to "reused a trusted query" here — a claim the receipt cannot support,
  // since the pattern was shown to the model rather than demonstrably used by it.
  return { hue: "info", verb: action.replace(/_/g, " ") };   // validated_by, etc.
}

const MODE_LABEL: Record<string, string> = {
  quick: "Quick answer", deep: "Deep analysis", builder: "Query Builder",
  explore: "Exploration", monitor: "Monitor", brief: "Briefing",
};

/**
 * Wave P1 — the answer's walk: the knowledge-graph nodes it stands on, grouped by WHY
 * each one is here, plus the connections between them.
 *
 * Ordered strongest-first by role: what the planner was shown, then what the SQL read,
 * then the governed metrics it used. A node the answer named but the graph does not hold
 * is shown struck through rather than dropped — "the graph does not cover this table" is
 * a real answer to "can I check every node", and quietly listing 3 of 4 is not.
 */
const REASON_TITLE: Record<TracedNode["reason"], string> = {
  cited: "Shown to the planner before it wrote the SQL",
  read: "Read by the SQL",
  metric: "Governed metrics used",
  finding: "Recorded back onto the graph",
};

function GroundingWalk({ trace }: { trace: AnswerTrace }) {
  const order: TracedNode["reason"][] = ["cited", "read", "metric", "finding"];
  const groups = order
    .map((r) => ({ reason: r, nodes: trace.nodes.filter((n) => n.reason === r) }))
    .filter((g) => g.nodes.length > 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {groups.map((g) => (
        <div key={g.reason} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>{REASON_TITLE[g.reason]}</div>
          {g.nodes.map((n) => (
            <div key={n.id} style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span className="aug-fs-xs" style={{
                color: n.present ? "var(--t1)" : "var(--t4)",
                textDecoration: n.present ? "none" : "line-through",
              }}>
                {n.label}
              </span>
              {n.present
                ? <WarrantChip warrant={n.warrant} showDetail />
                : <StatusChip hue="muted" strength="soft" title="This answer named it, but the knowledge graph does not hold it.">not in the graph</StatusChip>}
              {n.summary && (
                <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{n.summary.slice(0, 120)}</span>
              )}
            </div>
          ))}
        </div>
      ))}

      {trace.edges.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>How they connect</div>
          {trace.edges.map((e) => {
            const from = trace.nodes.find((n) => n.id === e.from_id);
            const to = trace.nodes.find((n) => n.id === e.to_id);
            return (
              <div key={e.id} style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>
                  {from?.label ?? e.from_id} → {to?.label ?? e.to_id}
                </span>
                <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>{e.label || e.kind.replace(/_/g, " ")}</span>
                <WarrantChip warrant={e.warrant} showDetail />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div className="aug-fs-xs" style={{ color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em" }}>{title}</div>
      {children}
    </div>
  );
}

function SqlBlock({ q }: { q: PublicReceipt["executed_sql"][number] }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(q.sql).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    });
  };
  return (
    <div style={{ border: "1px solid var(--b1)", borderRadius: "var(--r2)", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "4px 8px", background: "var(--bg-2)" }}>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{q.label}</span>
        <Button size="xs" variant="ghost" onClick={copy}>{copied ? "copied ✓" : "copy"}</Button>
      </div>
      <pre style={{
        margin: 0, padding: "8px 10px", background: "var(--code-bg)", fontSize: 11,
        fontFamily: "var(--font-code)", color: "var(--t2)", whiteSpace: "pre-wrap",
        wordBreak: "break-word", lineHeight: 1.5,
      }}>{q.sql}</pre>
    </div>
  );
}

function Drawer({ receiptId, preloaded, onClose }: {
  receiptId: string; preloaded?: PublicReceipt | null; onClose: () => void;
}) {
  const [rec, setRec] = useState<PublicReceipt | null>(preloaded ?? null);
  const [state, setState] = useState<"loading" | "ready" | "missing">(
    preloaded ? "ready" : "loading");

  useEffect(() => {
    // The glance row above already fetched this receipt; re-fetching on open would make
    // the same answer cost two requests again, which is what the S2 collapse removed.
    if (preloaded) { setRec(preloaded); setState("ready"); return; }
    let alive = true;
    getPublicReceipt(receiptId)
      .then(r => { if (alive) { setRec(r); setState(r ? "ready" : "missing"); } })
      .catch(() => { if (alive) setState("missing"); });
    return () => { alive = false; };
  }, [receiptId, preloaded]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Wave P1 — the knowledge-graph subgraph this answer stands on. Fetched only when the
  // drawer opens (it costs a graph load) and never blocks the receipt: an answer whose
  // connection has no graph shows the receipt exactly as it did before this wave.
  const [trace, setTrace] = useState<AnswerTrace | null>(null);
  useEffect(() => {
    let alive = true;
    getAnswerTrace(receiptId).then(t => { if (alive) setTrace(t); }).catch(() => {});
    return () => { alive = false; };
  }, [receiptId]);

  // Wave S2 — a reused trusted pattern arrives in the same `guards` array as a real guard
  // (one lineage shape, one reader), but it is not a guard that FIRED and must not be
  // listed as one. It also carries a whole question as its name, which is a sentence, not
  // a chip label. So the two are separated here and rendered differently.
  const allRows: PublicReceiptGuard[] = rec?.guards ?? [];
  const guards = allRows.filter(g => g.action !== "trusted");
  const trusted = allRows.filter(g => g.action === "trusted");

  // The Learning Receipt as sentences. Only what this run actually did — a zeroed
  // counter is "the loop ran and changed nothing", which is not worth a line.
  const l = rec?.learning;
  const learned: string[] = [];
  if (l?.readings_reused) {
    learned.push(`reused ${l.readings_reused} resolved reading${l.readings_reused !== 1 ? "s" : ""}` +
      (l.corrections_applied ? ` (${l.corrections_applied} correction${l.corrections_applied !== 1 ? "s" : ""})` : ""));
  }
  if (l?.resolutions_crystallized) {
    learned.push(`crystallized ${l.resolutions_crystallized} new resolution${l.resolutions_crystallized !== 1 ? "s" : ""}`);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Why this number — Trust Receipt"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.55)", backdropFilter: "blur(2px)", zIndex: 300, display: "flex", justifyContent: "flex-end" }}
    >
      <div style={{
        width: "100%", maxWidth: 460, height: "100%", background: "var(--bg-1)",
        borderLeft: "1px solid var(--b2)", display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "14px 16px", borderBottom: "1px solid var(--b1)" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 650, color: "var(--t1)" }}>Why this number</span>
              {rec && <StatusChip hue="info" strength="soft">{MODE_LABEL[rec.mode] ?? rec.mode}</StatusChip>}
              {rec?.signature && <StatusChip hue="positive" strength="soft" icon="🔏">server-signed</StatusChip>}
            </div>
            {rec?.question && <div style={{ fontSize: 12, color: "var(--t3)", marginTop: 4, lineHeight: 1.5 }}>{rec.question}</div>}
          </div>
          <Button size="xs" variant="ghost" onClick={onClose} aria-label="Close">✕</Button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "14px 16px", display: "flex", flexDirection: "column", gap: 16 }}>
          {state === "loading" && <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>Loading receipt…</div>}
          {state === "missing" && <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>No receipt is available for this answer.</div>}
          {rec && (
            <>
              {rec.headline && (
                <div style={{ fontSize: 13, color: "var(--t1)", fontWeight: 500, lineHeight: 1.5 }}>{rec.headline}</div>
              )}

              {rec.executed_sql.length > 0 && (
                <Section title={`Executed SQL (${rec.executed_sql.length})`}>
                  {rec.executed_sql.map((q, i) => <SqlBlock key={`sql:${i}`} q={q} />)}
                </Section>
              )}

              {guards.length > 0 && (
                <Section title="Guards that fired">
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {guards.map((g, i) => {
                      const t = guardTone(g.action);
                      return (
                        <div key={`g:${i}`} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <StatusChip hue={t.hue} strength="soft">{g.name.replace(/_/g, " ")}</StatusChip>
                            <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>{t.verb}</span>
                          </div>
                          {g.caveat && <div className="aug-fs-xs" style={{ color: "var(--t3)", lineHeight: 1.5 }}>{g.caveat}</div>}
                        </div>
                      );
                    })}
                  </div>
                </Section>
              )}

              {trusted.length > 0 && (
                <Section title={`Trusted patterns in scope (${trusted.length})`}>
                  <div className="aug-fs-xs" style={{ color: "var(--t4)", lineHeight: 1.5 }}>
                    Verified query patterns for this connection were put in front of the model
                    for this question. That is what the model was shown — not proof that this
                    answer reused one.
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
                    {trusted.map((t, i) => (
                      <div key={`t:${i}`} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <div className="aug-fs-xs" style={{ color: "var(--t2)", lineHeight: 1.5 }}>
                          {t.name}
                        </div>
                        {/* The promoter's own warrant sentence, verbatim — it is what
                            separates consistency-verified from human-checked. */}
                        {t.caveat && (
                          <div className="aug-fs-xs" style={{ color: "var(--t4)", lineHeight: 1.5 }}>
                            {t.caveat}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {rec.resolved_readings.length > 0 && (
                <Section title="Readings this connection already settled">
                  <div className="aug-fs-xs" style={{ color: "var(--t4)", lineHeight: 1.5 }}>
                    Applied so this question does not re-ask what was decided before.
                  </div>
                  {rec.resolved_readings.map((r, i) => (
                    <div key={`rr:${i}`} className="aug-fs-xs"
                      style={{ color: "var(--t2)", lineHeight: 1.5, marginTop: 4 }}>
                      {r.reading}{r.note ? ` — ${r.note}` : ""}
                    </div>
                  ))}
                </Section>
              )}

              {learned.length > 0 && (
                <Section title="What the loop learned this run">
                  <div className="aug-fs-xs" style={{ color: "var(--t2)", lineHeight: 1.5 }}>
                    {learned.join(" · ")}.
                  </div>
                </Section>
              )}

              {rec.activations.length > 0 && (
                <Section title="Capabilities whose trigger fired">
                  {rec.activations.map((a, i) => (
                    <div key={`ac:${i}`} className="aug-fs-xs"
                      style={{ color: "var(--t2)", lineHeight: 1.5, marginTop: 2 }}>
                      {a.capability.replace(/^[a-z]+\./, "").replace(/[._]/g, " ")}
                      {a.reason ? ` — activated because ${a.reason}` : ""}
                      {a.count > 1 ? ` (×${a.count})` : ""}
                    </div>
                  ))}
                </Section>
              )}

              {rec.caveats.length > 0 && (
                <Section title="Caveats">
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {rec.caveats.map((c, i) => (
                      <div key={`c:${i}`} className="aug-fs-xs" style={{ color: "var(--t2)", lineHeight: 1.5 }}>• {c}</div>
                    ))}
                  </div>
                </Section>
              )}

              {(rec.metrics.used.length > 0 || rec.metrics.drifted.length > 0 || rec.metrics.available.length > 0) && (
                <Section title="Governed metrics">
                  <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                    {rec.metrics.used.map((m, i) => <StatusChip key={`u:${i}`} hue="positive" strength="soft">{m} · governed ✓</StatusChip>)}
                    {rec.metrics.drifted.map((m, i) => <StatusChip key={`d:${i}`} hue="caution" strength="soft">⚠ {m.metric} · non-governed</StatusChip>)}
                    {rec.metrics.available.map((m, i) => <StatusChip key={`a:${i}`} hue="muted" strength="soft">{m}</StatusChip>)}
                  </div>
                </Section>
              )}

              {/* Wave P1 — the walk. When the connection has a knowledge graph, the bare
                  table strings become the graph nodes this answer stands on, each with
                  the warrant behind it and each checkable. Falls back to the plain list
                  when there is no graph, so nothing is ever lost. */}
              {trace?.available && trace.nodes.length > 0 ? (
                <Section title={`What this answer stands on · ${trace.nodes.length} nodes`}>
                  <GroundingWalk trace={trace} />
                </Section>
              ) : rec.input_tables.length > 0 && (
                <Section title="Input tables">
                  <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                    {rec.input_tables.map((t, i) => <StatusChip key={`t:${i}`} hue="muted" strength="soft">{t}</StatusChip>)}
                  </div>
                </Section>
              )}

              {(rec.confidence.level || rec.confidence.capped_by) && (
                <Section title="Confidence">
                  <div className="aug-fs-xs" style={{ color: "var(--t2)" }}>
                    {rec.confidence.level ?? "—"}
                    {rec.confidence.capped_by && <span style={{ color: "var(--t3)" }}> · capped by {rec.confidence.capped_by}</span>}
                  </div>
                </Section>
              )}

              {/* Footer facts — connection · model · cost · recorded-at */}
              <div style={{ display: "flex", flexDirection: "column", gap: 4, paddingTop: 8, borderTop: "1px solid var(--b1)" }}>
                {rec.connection.name && (
                  <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                    Connection: {rec.connection.name}{rec.connection.dialect ? ` · ${rec.connection.dialect}` : ""}
                  </div>
                )}
                {rec.model.id && <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>Model: {rec.model.id} ({rec.model.role})</div>}
                {costSummary(rec.cost) && <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>Cost: {costSummary(rec.cost)}</div>}
                {rec.created_at && <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>Recorded {formatTimestamp(rec.created_at)}</div>}
                <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>Receipt {rec.id} · server-signed (HMAC)</div>
                {/* E6 — capture this exact question + executed SQL as an eval case. Moved
                    here from the older per-mode panel, which was the only place it lived. */}
                {rec.connection.id && rec.executed_sql[0]?.sql && (
                  <div style={{ marginTop: 4 }}>
                    <AddToEvalSuite connectionId={rec.connection.id}
                      sql={rec.executed_sql[0].sql} question={rec.question} />
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** The at-a-glance chips: what this answer's receipt says, without opening anything.
 *
 *  B-9's inline badge row, restored after the S2 collapse removed the second panel that
 *  carried it — but fed by the UNIFIED receipt rather than the retired per-mode route, and
 *  by the SAME fetch the drawer uses. The old arrangement cost two components and two
 *  requests per answer; this is one of each.
 *
 *  Every chip states something the receipt actually carries. `trusted` says "in scope"
 *  rather than "verified" for the same reason the drawer does: the pattern was shown to
 *  the model, not demonstrably used by it.
 */
function GlanceChips({ rec }: { rec: PublicReceipt }) {
  const trusted = rec.guards.filter(g => g.action === "trusted").length;
  const fired = rec.guards.filter(g => g.action !== "trusted").length;
  const learned = rec.learning
    ? (rec.learning.resolutions_crystallized || 0)
    : 0;
  const chips: React.ReactNode[] = [];

  rec.metrics.used.forEach((m, i) => chips.push(
    <StatusChip key={`u${i}`} hue="info" strength="soft">{m} · governed</StatusChip>));
  rec.metrics.drifted.forEach((m, i) => chips.push(
    <StatusChip key={`d${i}`} hue="caution" strength="soft" title={m.detail ?? undefined}>
      {m.metric} · non-governed
    </StatusChip>));
  rec.metrics.proposed.forEach((m, i) => chips.push(
    <StatusChip key={`p${i}`} hue="accent" strength="soft"
      title={m.detail ?? "Define this metric in the Semantic Layer to enforce it"}>
      define {m.metric}
    </StatusChip>));
  if (fired > 0) chips.push(
    <StatusChip key="g" hue="positive" strength="soft">
      {fired} guard{fired !== 1 ? "s" : ""} fired
    </StatusChip>);
  if (trusted > 0) chips.push(
    <StatusChip key="t" hue="info" strength="soft"
      title="Verified query patterns were put in front of the model — not proof this answer reused one">
      {trusted} trusted pattern{trusted !== 1 ? "s" : ""} in scope
    </StatusChip>);
  if (rec.resolved_readings.length > 0) chips.push(
    <StatusChip key="r" hue="info" strength="soft">
      {rec.resolved_readings.length === 1 ? "resolved reading"
        : `${rec.resolved_readings.length} resolved readings`}
    </StatusChip>);
  if (learned > 0) chips.push(
    <StatusChip key="l" hue="positive" strength="soft">the loop learned something</StatusChip>);
  if (rec.activations.length > 0) chips.push(
    <StatusChip key="a" hue="positive" strength="soft">
      {rec.activations.length} capabilit{rec.activations.length !== 1 ? "ies" : "y"}
    </StatusChip>);

  // Nothing notable fired — say what the answer rests on rather than showing an empty row.
  if (chips.length === 0) chips.push(
    <StatusChip key="s" hue="muted" strength="soft">
      {rec.input_tables.length} source{rec.input_tables.length !== 1 ? "s" : ""} · executed SQL
    </StatusChip>);

  return <>{chips}</>;
}

export function WhyThisNumber({ receiptId }: { receiptId: string }) {
  const [open, setOpen] = useState(false);
  const [rec, setRec] = useState<PublicReceipt | null>(null);

  // Fetched once here and handed to the drawer, so opening it costs nothing and the chips
  // and the panel can never disagree about the same answer.
  useEffect(() => {
    let alive = true;
    getPublicReceipt(receiptId)
      .then(r => { if (alive) setRec(r); })
      .catch(() => { /* no receipt → the trigger still opens and says so */ });
    return () => { alive = false; };
  }, [receiptId]);

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap", marginTop: 6 }}>
        <span className="aug-fs-xs" style={{ color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em" }}>receipt</span>
        {rec && <GlanceChips rec={rec} />}
        <Button size="xs" variant="ghost" onClick={() => setOpen(true)}
          style={{ color: "var(--t3)" }} aria-label="Why this number — open the Trust Receipt">
          Why this number →
        </Button>
      </div>
      {open && <Drawer receiptId={receiptId} preloaded={rec} onClose={() => setOpen(false)} />}
    </>
  );
}
