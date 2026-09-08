"use client";

/**
 * Where a definition came from, whose it is, and what disagrees with it.
 *
 * The panel a reader opens when they want to know not "what is revenue" but "WHOSE
 * revenue am I looking at". Two dashboards disagreeing about a metric is not a bug to
 * resolve quietly — it is a fact about the business, and the person reading the number is
 * entitled to see it along with the name of whoever is behind the one they got.
 *
 * The ordering it renders is not this component's opinion. `aughor/ontology/authority.py`
 * decides, and it puts VERIFICATION in a tier above authority: a formula that bound
 * against the live database outranks one that did not, no matter who wrote it or how many
 * teams rely on it. So the badge that matters most here is "verified", and an unverified
 * winner says so in plain words rather than wearing the same chrome as a checked one.
 */
import { useEffect, useState } from "react";

import { getMetricProvenance, type DefinitionSource, type MetricProvenance }
  from "@/lib/api";

function Badge({ tone, children }: { tone: "good" | "warn" | "mute"; children: React.ReactNode }) {
  const cls = tone === "good" ? "text-emerald-300 border-emerald-700/50"
    : tone === "warn" ? "text-amber-300 border-amber-700/50"
    : "text-zinc-400 border-zinc-700/50";
  return (
    <span className={`aug-fs-xs border rounded px-1 py-0.5 ${cls}`}>{children}</span>
  );
}

function Claim({ d, chosen }: { d: DefinitionSource; chosen: boolean }) {
  return (
    <div className={`rounded-[var(--r3)] p-2 space-y-1 border ${
      chosen ? "border-zinc-600 bg-zinc-800/60" : "border-zinc-800 bg-zinc-900/40"}`}>
      <div className="flex items-center gap-2 flex-wrap">
        {chosen && <Badge tone="mute">in use</Badge>}
        {/* Verified is the tier, so it reads differently from every other chip. */}
        {d.verified ? <Badge tone="good">verified</Badge>
                    : <Badge tone="warn">unverified</Badge>}
        {d.certified && <Badge tone="mute">certified source</Badge>}
        {d.use_count > 0 && <Badge tone="mute">{d.use_count} uses</Badge>}
      </div>
      <code className="block aug-fs-xs font-code text-emerald-300 bg-zinc-950
                       border border-zinc-700/40 rounded px-2 py-1.5">
        {d.formula_sql}
      </code>
      <p className="aug-fs-xs text-zinc-500">
        {d.source_asset || "an unnamed source"}
        {" · "}
        {/* Never invented upstream, so never dressed up here. */}
        {d.author ? d.author : <span className="italic">unattributed</span>}
        {d.recorded_at ? ` · ${d.recorded_at.slice(0, 10)}` : ""}
      </p>
      {d.verification_note && (
        <p className="aug-fs-xs text-zinc-600">{d.verification_note}</p>
      )}
    </div>
  );
}

export function MetricProvenancePanel({ metricId, connectionId, schemaName }: {
  metricId: string; connectionId: string; schemaName?: string;
}) {
  const [data, setData] = useState<MetricProvenance | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setData(null); setError(null);
    getMetricProvenance(metricId, connectionId, schemaName)
      .then(d => { if (live) setData(d); })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : "could not read"); });
    return () => { live = false; };
  }, [metricId, connectionId, schemaName]);

  if (error) return <p className="aug-fs-xs text-zinc-500">Provenance unavailable: {error}</p>;
  if (!data) return <p className="aug-fs-xs text-zinc-600">Reading provenance…</p>;

  const others = data.definitions.filter(d => d !== data.chosen
    && d.formula_sql !== data.chosen?.formula_sql);

  return (
    <div className="space-y-2 pt-1">
      {/* The sentence the law wrote. Rendered verbatim: it names the asset and the
          author, and says whether the choice rests on a check or only on standing. */}
      <p className="aug-fs-xs text-zinc-400 leading-snug">{data.why}</p>

      {data.chosen && <Claim d={data.chosen} chosen />}

      {others.length > 0 && (
        <div className="space-y-1">
          <p className="aug-fs-xs text-zinc-500">
            {others.length === 1 ? "One other definition is recorded"
                                 : `${others.length} other definitions are recorded`}
            {data.contested ? " — and it disagrees:" : ":"}
          </p>
          {others.map((d, i) => <Claim key={i} d={d} chosen={false} />)}
        </div>
      )}

      {data.known_divergent_calculations.length > 0 && (
        <div className="space-y-1">
          <p className="aug-fs-xs text-zinc-500">Known divergent calculations:</p>
          <ul className="aug-fs-xs text-zinc-500 list-disc pl-4">
            {data.known_divergent_calculations.map((k, i) => <li key={i}>{k}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
