"use client";

/**
 * IndustryKpiStrip — the per-industry key metrics, computed live, at the top of the
 * Briefing. The BusinessProfile already knows the vertical's north-star metrics AND
 * carries a value_sql per metric; this runs each through the same authority the rest
 * of the dashboard uses (/query/run) and shows the current value.
 *
 * Fail-safe: a metric whose SQL errors, returns no scalar, or comes back out of its
 * stated range (a broken-grain rate > 1) is silently dropped — never a wrong number.
 */
import { useEffect, useState } from "react";
import { getBusinessProfile, runDirectQuery } from "@/lib/api";
import { GroundedNumber } from "@/components/brief/GroundedNumber";

interface Kpi { name: string; display: string; sql: string; raw: number; }

/** Format a raw scalar by its declared unit/range, and gate out broken values. */
function formatMetric(v: number, unit: string): { display: string; ok: boolean } {
  const u = (unit || "").toLowerCase();
  let display: string;
  if (/ratio|0-1|0\.\.1/.test(u) && !/0-100|0\.\.100/.test(u)) {
    if (v < -0.001 || v > 1.05) return { display: "", ok: false };   // broken bounded rate (>1)
    if (v >= 0.9995) return { display: "", ok: false };              // rounds to 100% — degenerate (e.g. abandoned=0 denominator bug)
    display = `${(v * 100).toFixed(1)}%`;
  } else if (/percent|0-100|0\.\.100|%/.test(u)) {
    if (v < -0.5 || v > 105) return { display: "", ok: false };
    if (v >= 99.95) return { display: "", ok: false };               // rounds to 100% — degenerate
    display = `${v.toFixed(1)}%`;
  } else if (/day/.test(u)) {
    display = `${v.toFixed(1)}d`;
  } else {
    const a = Math.abs(v);
    const s = a >= 1e9 ? `${(v / 1e9).toFixed(1)}B`
            : a >= 1e6 ? `${(v / 1e6).toFixed(1)}M`
            : a >= 1e3 ? `${(v / 1e3).toFixed(1)}K`
            : Number.isInteger(v) ? String(v) : v.toFixed(2);
    const pre = /usd|\$|revenue|spend|cost|gmv|sales/.test(u) ? "$" : "";
    display = pre + s;
  }
  // No zero values on cards: a "$0 / 0.0% / 0d" KPI is noise — almost always a
  // rounding/join bug (e.g. ROUND(weight,4) zeroing a 2e-07 attribution weight), not a
  // real result. Drop it once it has rounded to zero at the shown precision.
  if (Math.abs(parseFloat(display.replace(/[^0-9.eE-]/g, "")) || 0) === 0) {
    return { display: "", ok: false };
  }
  return { display, ok: true };
}

export function IndustryKpiStrip({ connectionId, schema }: { connectionId: string; schema?: string }) {
  const [industry, setIndustry] = useState("");
  const [kpis, setKpis] = useState<Kpi[]>([]);

  useEffect(() => {
    if (!connectionId) return;
    let alive = true;
    (async () => {
      const p = await getBusinessProfile(connectionId, schema);
      if (alive && (!p.available || !p.profile)) { setIndustry(""); setKpis([]); }
      if (!alive || !p.available || !p.profile) return;
      setIndustry(p.profile.industry || "");
      const metrics = (p.profile.north_star_metrics || []).filter(m => m.value_sql?.trim());
      const out: Kpi[] = [];
      await Promise.all(metrics.map(async (m) => {
        try {
          const r = await runDirectQuery(connectionId, m.value_sql, 2, { useCache: true });
          if (r.error || !r.rows || r.rows.length !== 1) return;   // need exactly one scalar row
          const cell = r.rows[0].find(c => c != null && c !== "" && !isNaN(Number(c)));
          if (cell == null) return;
          const f = formatMetric(Number(cell), m.unit_or_range);
          if (f.ok) out.push({ name: m.name, display: f.display, sql: m.value_sql, raw: Number(cell) });
        } catch { /* fail-safe: skip this metric */ }
      }));
      if (alive) setKpis(out);
    })();
    return () => { alive = false; };
  }, [connectionId, schema]);

  if (!kpis.length) return null;

  return (
    <div>
      <div className="aug-label" style={{ marginBottom: 8 }}>
        Key Metrics{industry ? <span style={{ fontWeight: 400, color: "var(--t4)" }}>{` · ${industry}`}</span> : null}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        {kpis.map(k => (
          <div key={k.name} style={{
            flex: "1 1 130px", minWidth: 120, padding: "9px 11px",
            borderRadius: "var(--r2)", background: "var(--bg-2)", border: "1px solid var(--b1)",
          }}>
            <div style={{
              fontSize: 9, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".05em",
              fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }} title={k.name}>{k.name}</div>
            <div style={{
              fontSize: 18, color: "var(--t1)", fontWeight: 600,
              fontFamily: "var(--font-mono)", marginTop: 3, lineHeight: 1,
            }}>
              <GroundedNumber
                token={k.display}
                resolve={async () => ({
                  sql: k.sql,
                  grounded: true,
                  matchedCell: k.raw,
                  note: "Live value — the result of this query.",
                })}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
