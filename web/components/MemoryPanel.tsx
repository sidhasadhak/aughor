"use client";
/* ── Agent Workspace · Memory (native cards) ────────────────────────────────
   The closed loop's accumulation, made visible (Wave 1 · E4): the ambiguity-
   ledger burn-down (resolutions settled, by source, times served as priors), the
   verdict acceptance economy, and the trusted assets injected authoritatively
   into prompts. Reads /learning/summary + /learning/trusted (org-wide). Degrades
   quietly when there is no data or the endpoints fail. */
import { useEffect, useState } from "react";
import { compactNumber } from "@/lib/format";
import {
  getLearningSummary, getTrustedAssets,
  type LearningSummary, type TrustedAssets,
} from "@/lib/api";

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
  fontSize: 10, color: "var(--t3)", textTransform: "uppercase", letterSpacing: 0.4, width: 58, flexShrink: 0,
};
const ellipsize: React.CSSProperties = {
  flex: 1, fontSize: 12, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
};

export function MemoryPanel() {
  const [summary, setSummary] = useState<LearningSummary | null>(null);
  const [trusted, setTrusted] = useState<TrustedAssets | null>(null);
  const [loading, setLoading] = useState(true);   // fetch runs once on mount; starts in the loading state

  useEffect(() => {
    Promise.all([getLearningSummary(), getTrustedAssets()])
      .then(([s, t]) => { setSummary(s); setTrusted(t); })
      .finally(() => setLoading(false));
  }, []);

  const ledger = summary?.ledger;
  const verdicts = summary?.verdicts;
  const acc = verdicts?.acceptance_rate;
  const bySource = ledger?.by_source ?? {};
  const sources = Object.keys(bySource);
  const trustedTotal = (summary?.trusted.queries ?? 0) + (summary?.trusted.programs ?? 0);

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "18px 22px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <span style={{ fontSize: 16, fontWeight: 600, color: "var(--t1)" }}>Memory</span>
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
            <Tile label="Acceptance" value={acc != null ? `${Math.round(acc * 100)}%` : "—"} sub={`${verdicts?.total ?? 0} verdicts`} />
            <Tile label="Trusted" value={String(trustedTotal)} sub={`${plural(summary.trusted.queries, "query")} · ${plural(summary.trusted.programs, "program")}`} />
          </div>

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

          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)", marginBottom: 8 }}>Trusted assets</div>
          {(!trusted || (trusted.queries.length === 0 && trusted.programs.length === 0)) ? (
            <div style={{ fontSize: 12, color: "var(--t3)" }}>None yet — verified queries and clean plan replays crystallize here.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              {trusted.queries.map(q => (
                <div key={`q:${q.id}`} style={rowStyle}>
                  <span style={kindTag}>query</span>
                  <span style={ellipsize}>{q.question}</span>
                </div>
              ))}
              {trusted.programs.map(p => (
                <div key={`p:${p.id}`} style={rowStyle}>
                  <span style={kindTag}>program</span>
                  <span style={ellipsize}>{p.question}</span>
                  <span style={{ fontSize: 11, color: "var(--t3)", flexShrink: 0 }}>{p.use_count > 0 ? `${p.use_count}× replayed` : "new"}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
